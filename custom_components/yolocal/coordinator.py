"""Data coordinator for YoLink Local integration."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import (
    Device,
    DeviceEvent,
    TokenManager,
    YoLinkClient,
    YoLinkCloudClient,
    YoLinkMQTTClient,
)
from .api.auth import AuthenticationError

_LOGGER = logging.getLogger(__name__)

# Polling interval as fallback when MQTT events are missed
UPDATE_INTERVAL = timedelta(minutes=5)


class YoLocalCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator for YoLink Local devices.

    Manages MQTT subscription for real-time updates and provides
    device state to entities. Falls back to HTTP polling every 5 minutes
    to ensure state stays current if MQTT events are missed.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: YoLinkClient,
        token_manager: TokenManager,
        session: aiohttp.ClientSession,
        net_id: str,
        mqtt_port: int = 18080,
        cloud_client: YoLinkCloudClient | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="YoLink Local",
            update_interval=UPDATE_INTERVAL,
        )
        self._client = client
        self._token_manager = token_manager
        self._session = session
        self._net_id = net_id
        self._mqtt_port = mqtt_port
        self._cloud_client = cloud_client
        self._mqtt_client: YoLinkMQTTClient | None = None
        self._devices: dict[str, Device] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._virtual_hub_id: str | None = None

    @property
    def devices(self) -> dict[str, Device]:
        """Return the device registry."""
        return self._devices

    @property
    def cloud_diagnostics_enabled(self) -> bool:
        """Return whether optional cloud hub diagnostics are configured."""
        return self._cloud_client is not None

    async def _async_setup(self) -> None:
        """Set up the coordinator: fetch devices and connect MQTT."""
        devices = await self._client.get_devices()

        # Some Local Hub firmware omits the hub from Home.getDeviceList. Add a
        # stable virtual device so the connection still has HA diagnostics.
        if not any(device.device_type == "Hub" for device in devices):
            self._virtual_hub_id = f"local_hub_{self._client.host}"
            devices.append(
                Device(
                    device_id=self._virtual_hub_id,
                    name=f"YoLink Hub ({self._client.host})",
                    token="",
                    device_type="Hub",
                )
            )

        self._devices = {d.device_id: d for d in devices}

        await self._fetch_all_states()
        await self._connect_mqtt()

    async def _fetch_all_states(self) -> None:
        """Fetch current state for all devices via HTTP API."""
        started = monotonic()
        all_device_polls_succeeded = True
        for device in self._devices.values():
            if device.device_id == self._virtual_hub_id:
                continue
            try:
                state = await self._client.get_state(device)
                self._states[device.device_id] = state
            except Exception:
                _LOGGER.warning("Failed to get state for %s", device.name)
                all_device_polls_succeeded = False
                self._states.setdefault(device.device_id, {})["online"] = False

        hub_poll_succeeded = await self._update_hub_diagnostics()
        state = self._hub_state()
        if state is not None:
            state["httpLatencyMs"] = round((monotonic() - started) * 1000, 1)
            if all_device_polls_succeeded and hub_poll_succeeded:
                state["lastHttpPoll"] = datetime.now(timezone.utc)
            self._update_hub_runtime_diagnostics(state)
            await self._update_cloud_hub_diagnostics(state)

    def _hub_device(self) -> Device | None:
        """Return the real or synthesized hub device."""
        return next(
            (
                device
                for device in self._devices.values()
                if device.device_type == "Hub"
            ),
            None,
        )

    def _hub_state(self) -> dict[str, Any] | None:
        """Return the hub state, creating it when a hub exists."""
        hub = self._hub_device()
        return self._states.setdefault(hub.device_id, {}) if hub else None

    async def _update_hub_diagnostics(self) -> bool:
        """Update diagnostics for a real or synthesized Local Hub device."""
        hub = self._hub_device()
        if hub is None:
            return False

        state = self._states.setdefault(hub.device_id, {})
        state.update(
            {
                "ip": self._client.host,
                "managedDevices": sum(
                    device.device_type != "Hub"
                    for device in self._devices.values()
                ),
                "httpPort": self._client.port,
                "mqttPort": self._mqtt_port,
            }
        )

        try:
            home_info = await self._client.get_home_info()
        except Exception:
            _LOGGER.warning("Failed to get Local Hub general information")
            if hub.device_id == self._virtual_hub_id:
                state["online"] = False
            return False
        else:
            state["homeId"] = home_info.get("id")
            if hub.device_id == self._virtual_hub_id:
                state["online"] = True
            return True

    def _update_hub_runtime_diagnostics(
        self, state: dict[str, Any]
    ) -> None:
        """Update integration-health diagnostics on the hub device."""
        managed_devices = [
            device
            for device in self._devices.values()
            if device.device_type != "Hub"
        ]
        online_devices = sum(
            self._states.get(device.device_id, {}).get("online", True) is not False
            for device in managed_devices
        )
        device_types = Counter(device.device_type for device in managed_devices)

        state.update(
            {
                "mqttConnected": bool(
                    self._mqtt_client and self._mqtt_client.connected
                ),
                "authValid": self._token_manager.is_valid,
                "onlineDevices": online_devices,
                "offlineDevices": len(managed_devices) - online_devices,
                "deviceTypes": dict(sorted(device_types.items())),
            }
        )

        if self._token_manager.expires_at is not None:
            state["tokenExpiresAt"] = datetime.fromtimestamp(
                self._token_manager.expires_at, timezone.utc
            )
        if self._token_manager.last_refresh_at is not None:
            state["lastTokenRefresh"] = datetime.fromtimestamp(
                self._token_manager.last_refresh_at, timezone.utc
            )
        if self._token_manager.last_refresh_success is not None:
            state["tokenRefreshSuccessful"] = (
                self._token_manager.last_refresh_success
            )

    async def _update_cloud_hub_diagnostics(
        self, state: dict[str, Any]
    ) -> None:
        """Update optional cloud-sourced diagnostics without affecting local I/O."""
        if self._cloud_client is None:
            return

        try:
            async with asyncio.timeout(15):
                cloud_state = await self._cloud_client.async_get_hub_state()
        except AuthenticationError:
            _LOGGER.warning("YoLink Cloud diagnostics authentication failed")
            state["cloudConnected"] = False
            state["cloudAuthenticated"] = False
        except Exception:
            _LOGGER.warning("Failed to update optional YoLink Cloud diagnostics")
            state["cloudConnected"] = False
        else:
            state["cloud"] = cloud_state
            state["cloudConnected"] = True
            state["cloudAuthenticated"] = True
            state["lastCloudPoll"] = datetime.now(timezone.utc)
            if self._cloud_client.hub is not None:
                state["cloudHubId"] = self._cloud_client.hub.device_id
                state["cloudHubModel"] = self._cloud_client.hub.model

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Poll device states via HTTP as a fallback.

        This runs periodically (every 5 minutes) to ensure state stays
        current even if MQTT events are missed or the connection drops.
        """
        await self._fetch_all_states()
        return self._states.copy()

    async def async_shutdown(self) -> None:
        """Shut down the coordinator."""
        if self._mqtt_client:
            await self._mqtt_client.disconnect()
            self._mqtt_client = None
        await self._session.close()

    async def _connect_mqtt(self) -> None:
        """Connect to MQTT broker."""
        token = await self._token_manager.get_token()
        host = self._client.host

        self._mqtt_client = YoLinkMQTTClient(
            host=host,
            net_id=self._net_id,
            client_id=self._token_manager.client_id,
            access_token=token,
            port=self._mqtt_port,
        )
        self._mqtt_client.subscribe(self._on_device_event)
        self._mqtt_client.subscribe_connection(self._on_mqtt_connection_change)

        try:
            await self._mqtt_client.connect()
            _LOGGER.info("Connected to YoLink MQTT broker")
        except Exception:
            _LOGGER.exception("Failed to connect to MQTT broker")
            state = self._hub_state()
            if state is not None:
                state["mqttConnected"] = False
                self.async_set_updated_data(self._states.copy())

    @callback
    def _on_mqtt_connection_change(self, connected: bool) -> None:
        """Handle MQTT connection status changes."""
        state = self._hub_state()
        if state is None:
            return
        state["mqttConnected"] = connected
        self.async_set_updated_data(self._states.copy())

    @callback
    def _on_device_event(self, event: DeviceEvent) -> None:
        """Handle a device event from MQTT.

        Merges incoming event data with the existing device state so that
        partial events (e.g. connectivity-only updates) don't wipe out
        previously known sensor readings like temperature and humidity.
        """
        hub_state = self._hub_state()
        if hub_state is not None:
            hub_state["lastMqttMessage"] = datetime.now(timezone.utc)

        device_id = event.device_id
        if device_id not in self._devices:
            _LOGGER.debug("Ignoring event for unknown device: %s", device_id)
            self.async_set_updated_data(self._states.copy())
            return

        existing = self._states.get(device_id, {})
        self._states[device_id] = {**existing, **event.data}
        self.async_set_updated_data(self._states.copy())

    def get_state(self, device_id: str) -> dict[str, Any]:
        """Get the current state for a device."""
        return self._states.get(device_id, {})

    async def async_send_command(
        self, device_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a command to a device."""
        device = self._devices.get(device_id)
        if not device:
            raise ValueError(f"Unknown device: {device_id}")
        return await self._client.set_state(device, params)


async def create_coordinator(
    hass: HomeAssistant,
    host: str,
    client_id: str,
    client_secret: str,
    net_id: str,
    http_port: int = 1080,
    mqtt_port: int = 18080,
    cloud_client_id: str | None = None,
    cloud_client_secret: str | None = None,
    cloud_hub_id: str | None = None,
) -> YoLocalCoordinator:
    """Create and initialize a coordinator.

    Returns a fully-initialized, connected coordinator ready for use.

    Raises:
        AuthenticationError: If credentials are invalid.
        Exception: If setup fails.
    """
    session = aiohttp.ClientSession()
    try:
        token_manager = TokenManager(host, client_id, client_secret, session, http_port)
        await token_manager.get_token()

        client = YoLinkClient(host, token_manager, session, http_port)

        cloud_client = None
        if cloud_client_id and cloud_client_secret:
            cloud_client = YoLinkCloudClient(
                client_id=cloud_client_id,
                client_secret=cloud_client_secret,
                session=session,
                hub_device_id=cloud_hub_id,
            )

        coordinator = YoLocalCoordinator(
            hass,
            client,
            token_manager,
            session,
            net_id,
            mqtt_port,
            cloud_client,
        )
        await coordinator._async_setup()

        return coordinator
    except Exception:
        await session.close()
        raise
