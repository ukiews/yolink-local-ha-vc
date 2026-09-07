"""Binary sensor platform for YoLink Local integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import YoLocalCoordinator
from .entity import YoLocalEntity


DEVICE_TYPE_TO_CLASS = {
    "DoorSensor": BinarySensorDeviceClass.DOOR,
    "LeakSensor": BinarySensorDeviceClass.MOISTURE,
}

DEVICE_TYPE_TO_ON_STATE = {
    "DoorSensor": "open",
    "LeakSensor": "alert",
}


def _cloud_state(device_state: dict[str, Any]) -> dict[str, Any]:
    """Return cloud hub data when optional diagnostics are configured."""
    state = device_state.get("cloud")
    return state if isinstance(state, dict) else {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up YoLink binary sensors from a config entry."""
    coordinator: YoLocalCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = []
    for device in coordinator.devices.values():
        if device.device_type in DEVICE_TYPE_TO_CLASS:
            entities.append(YoLocalBinarySensor(coordinator, device))
        if device.device_type == "Hub":
            entities.append(YoLocalHubAPIConnectivitySensor(coordinator, device))
            entities.append(YoLocalHubMQTTConnectivitySensor(coordinator, device))
            entities.append(YoLocalHubAuthenticationSensor(coordinator, device))
            if coordinator.cloud_diagnostics_enabled:
                entities.append(YoLocalHubCloudConnectivitySensor(coordinator, device))
                entities.append(
                    YoLocalHubCloudAuthenticationSensor(coordinator, device)
                )
                entities.append(YoLocalHubCloudOnlineSensor(coordinator, device))
                entities.append(YoLocalHubCloudMainsPowerSensor(coordinator, device))
                entities.append(
                    YoLocalHubCloudBatteryInstalledSensor(coordinator, device)
                )
            state = coordinator.get_state(device.device_id)
            if isinstance(state.get("eth"), dict):
                entities.append(
                    YoLocalHubConnectivitySensor(
                        coordinator, device, "eth", "Ethernet"
                    )
                )
            if isinstance(state.get("wifi"), dict):
                entities.append(
                    YoLocalHubConnectivitySensor(
                        coordinator, device, "wifi", "Wi-Fi"
                    )
                )

    async_add_entities(entities)


class YoLocalBinarySensor(YoLocalEntity, BinarySensorEntity):
    """Binary sensor for YoLink door/leak sensors."""

    _attr_name = None  # Use device name

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        self._attr_device_class = DEVICE_TYPE_TO_CLASS.get(device.device_type)
        self._on_state = DEVICE_TYPE_TO_ON_STATE.get(device.device_type, "open")

    @property
    def is_on(self) -> bool | None:
        """Return True if the sensor is triggered."""
        state = self.device_state.get("state", {})
        if isinstance(state, dict):
            sensor_state = state.get("state")
        else:
            sensor_state = state

        if sensor_state is None:
            return None
        return sensor_state == self._on_state


class YoLocalHubConnectivitySensor(YoLocalEntity, BinarySensorEntity):
    """Connectivity status of a YoLink hub network interface."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: YoLocalCoordinator,
        device,
        interface: str,
        name: str,
    ) -> None:
        """Initialize a hub connectivity sensor."""
        super().__init__(coordinator, device)
        self._interface = interface
        self._attr_name = name
        self._attr_unique_id = f"{device.device_id}_{interface}_connectivity"

    @property
    def is_on(self) -> bool | None:
        """Return True when the network interface is connected."""
        interface = self.device_state.get(self._interface)
        if not isinstance(interface, dict) or "enable" not in interface:
            return None
        return bool(interface["enable"])


class YoLocalHubAPIConnectivitySensor(YoLocalEntity, BinarySensorEntity):
    """Connectivity status of the YoLink Local HTTP API."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Local API"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the Local API connectivity sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_api_connectivity"

    @property
    def is_on(self) -> bool:
        """Return True when the Local API is reachable."""
        return bool(self.device_state.get("online", True))


class YoLocalHubMQTTConnectivitySensor(YoLocalEntity, BinarySensorEntity):
    """Connectivity status of the YoLink Local MQTT broker."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "MQTT"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the MQTT connectivity sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_mqtt_connectivity"

    @property
    def is_on(self) -> bool:
        """Return True when MQTT is connected."""
        return bool(self.device_state.get("mqttConnected", False))


class YoLocalHubAuthenticationSensor(YoLocalEntity, BinarySensorEntity):
    """Validity status of the YoLink Local API access token."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:key-variant"
    _attr_name = "Authentication"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the authentication status sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_authentication"

    @property
    def is_on(self) -> bool:
        """Return True when an unexpired access token is available."""
        return bool(self.device_state.get("authValid", False))


class YoLocalHubCloudConnectivitySensor(YoLocalEntity, BinarySensorEntity):
    """Connectivity status of optional YoLink Cloud diagnostics."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-check-outline"
    _attr_name = "Cloud API"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize cloud API connectivity."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_connectivity"

    @property
    def is_on(self) -> bool:
        """Return True after a successful cloud diagnostics request."""
        return bool(self.device_state.get("cloudConnected", False))


class YoLocalHubCloudAuthenticationSensor(YoLocalEntity, BinarySensorEntity):
    """Authentication status of optional YoLink Cloud diagnostics."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-key-outline"
    _attr_name = "Cloud authentication"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize cloud authentication status."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_authentication"

    @property
    def is_on(self) -> bool:
        """Return True when cloud authentication last succeeded."""
        return bool(self.device_state.get("cloudAuthenticated", False))


class YoLocalHubCloudOnlineSensor(YoLocalEntity, BinarySensorEntity):
    """Hub online status as reported by YoLink Cloud."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:hub-outline"
    _attr_name = "Cloud hub online"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize cloud hub online status."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_online"

    @property
    def is_on(self) -> bool | None:
        """Return the hub online state reported by YoLink Cloud."""
        if not self.device_state.get("cloudConnected", False):
            return None
        return bool(_cloud_state(self.device_state).get("online", False))


class YoLocalHubCloudMainsPowerSensor(YoLocalEntity, BinarySensorEntity):
    """Whether the hub reports external DC/mains power."""

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:power-plug-battery-outline"
    _attr_name = "Cloud mains power"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize cloud mains-power status."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_mains_power"

    @property
    def is_on(self) -> bool | None:
        """Return True when external DC power is connected."""
        other = _cloud_state(self.device_state).get("other")
        power = other.get("power") if isinstance(other, dict) else None
        if not isinstance(power, dict) or "dc" not in power:
            return None
        return bool(power["dc"])


class YoLocalHubCloudBatteryInstalledSensor(YoLocalEntity, BinarySensorEntity):
    """Whether the hub reports that a backup battery is installed."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-check-outline"
    _attr_name = "Cloud backup battery installed"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize cloud backup-battery presence."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_battery_installed"

    @property
    def is_on(self) -> bool | None:
        """Return True when a backup battery is installed."""
        other = _cloud_state(self.device_state).get("other")
        power = other.get("power") if isinstance(other, dict) else None
        if not isinstance(power, dict) or "battery" not in power:
            return None
        return bool(power["battery"])
