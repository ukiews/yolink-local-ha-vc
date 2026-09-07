"""Sensor platform for YoLink Local integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import YoLocalCoordinator
from .entity import YoLocalEntity

# Device types known to report a YoLink 0-4 battery level. The state-based
# fallback in async_setup_entry also discovers battery support on newer devices.
BATTERY_DEVICE_TYPES = frozenset(
    {
        "DoorSensor",
        "LeakSensor",
        "Lock",
        "Manipulator",
        "MotionSensor",
        "Siren",
        "SmartRemoter",
        "THSensor",
        "VibrationSensor",
        "WaterLeakController",
        "WaterMeterController",
    }
)
POWER_SOURCE_DEVICE_TYPES = frozenset(
    {"Manipulator", "WaterLeakController", "WaterMeterController"}
)
CLOUD_BATTERY_STATES = {
    0: "not_connected",
    1: "powering_hub",
    2: "charging",
    3: "standing_by",
    4: "maintenance",
}


def _state_value(device_state: dict[str, Any], key: str) -> Any:
    """Return a value from either YoLink state response shape."""
    state = device_state.get("state")
    if isinstance(state, dict) and key in state:
        return state[key]
    return device_state.get(key)


def _battery_percentage(device_state: dict[str, Any]) -> int | None:
    """Return a YoLink 0-4 battery level as a percentage."""
    state = device_state.get("state")
    level = state.get("battery") if isinstance(state, dict) else None

    # Some device families, including valve controllers, report the battery at
    # the top level even though their functional state is nested.
    if level is None:
        level = device_state.get("battery")

    if level is None or isinstance(level, bool):
        return None

    try:
        numeric_level = int(level)
    except (TypeError, ValueError):
        return None

    if not 0 <= numeric_level <= 4:
        return None

    return numeric_level * 25


def _cloud_state(device_state: dict[str, Any]) -> dict[str, Any]:
    """Return cloud hub data when optional diagnostics are configured."""
    state = device_state.get("cloud")
    return state if isinstance(state, dict) else {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up YoLink sensors from a config entry."""
    coordinator: YoLocalCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    for device in coordinator.devices.values():
        if device.device_type == "THSensor":
            entities.append(YoLocalTemperatureSensor(coordinator, device))
            entities.append(YoLocalHumiditySensor(coordinator, device))

        if device.device_type == "Hub":
            entities.append(YoLocalHubIPAddressSensor(coordinator, device))
            entities.append(YoLocalHubDeviceCountSensor(coordinator, device))
            entities.append(YoLocalHubOnlineDeviceCountSensor(coordinator, device))
            entities.append(YoLocalHubOfflineDeviceCountSensor(coordinator, device))
            entities.append(YoLocalHubHTTPLatencySensor(coordinator, device))
            entities.append(YoLocalHubLastHTTPPollSensor(coordinator, device))
            entities.append(YoLocalHubLastMQTTMessageSensor(coordinator, device))
            entities.append(YoLocalHubTokenExpirySensor(coordinator, device))
            if coordinator.cloud_diagnostics_enabled:
                entities.append(YoLocalHubCloudBatteryStateSensor(coordinator, device))
                entities.append(YoLocalHubCloudNetworkSensor(coordinator, device))
                entities.append(YoLocalHubCloudComponentsSensor(coordinator, device))
                entities.append(YoLocalHubLastCloudPollSensor(coordinator, device))
            if _state_value(
                coordinator.get_state(device.device_id), "version"
            ) is not None:
                entities.append(YoLocalHubFirmwareSensor(coordinator, device))

        if (
            device.device_type in POWER_SOURCE_DEVICE_TYPES
            or _state_value(
                coordinator.get_state(device.device_id), "powerSupply"
            )
            is not None
        ):
            entities.append(YoLocalPowerSourceSensor(coordinator, device))

        if (
            device.device_type in BATTERY_DEVICE_TYPES
            or _battery_percentage(coordinator.get_state(device.device_id)) is not None
        ):
            entities.append(YoLocalBatterySensor(coordinator, device))

    async_add_entities(entities)


class YoLocalTemperatureSensor(YoLocalEntity, SensorEntity):
    """Temperature sensor for YoLink THSensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name = "Temperature"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        state = self.device_state.get("state", {})
        if isinstance(state, dict):
            return state.get("temperature")
        return self.device_state.get("temperature")


class YoLocalHumiditySensor(YoLocalEntity, SensorEntity):
    """Humidity sensor for YoLink THSensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_name = "Humidity"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_humidity"

    @property
    def native_value(self) -> float | None:
        """Return the humidity."""
        state = self.device_state.get("state", {})
        if isinstance(state, dict):
            return state.get("humidity")
        return self.device_state.get("humidity")


class YoLocalBatterySensor(YoLocalEntity, SensorEntity):
    """Battery sensor for YoLink devices."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_name = "Battery"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_battery"

    @property
    def native_value(self) -> int | None:
        """Return the battery level as percentage."""
        return _battery_percentage(self.device_state)


class YoLocalPowerSourceSensor(YoLocalEntity, SensorEntity):
    """Power source reported by a YoLink valve controller."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Power source"
    _attr_options = ["battery", "mains"]

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the power source sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_power_source"

    @property
    def native_value(self) -> str | None:
        """Return battery or mains power."""
        power_supply = _state_value(self.device_state, "powerSupply")
        if not isinstance(power_supply, str):
            return None

        normalized = power_supply.casefold()
        if normalized == "battery":
            return "battery"
        if normalized in {"powerline", "mains"}:
            return "mains"
        return None


class YoLocalHubFirmwareSensor(YoLocalEntity, SensorEntity):
    """Firmware version of the YoLink hub."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"
    _attr_name = "Firmware"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the hub firmware sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_firmware"

    @property
    def native_value(self) -> str | None:
        """Return the installed hub firmware version."""
        version = _state_value(self.device_state, "version")
        return str(version) if version is not None else None


class YoLocalHubIPAddressSensor(YoLocalEntity, SensorEntity):
    """Active IP address and network details of the YoLink hub."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:ip-network"
    _attr_name = "IP address"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the hub IP address sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_ip_address"

    @property
    def native_value(self) -> str | None:
        """Return the IP address of the active network interface."""
        for interface_name in ("eth", "wifi"):
            interface = self.device_state.get(interface_name)
            if isinstance(interface, dict) and interface.get("enable"):
                address = interface.get("ip")
                if address:
                    return str(address)

        for interface_name in ("eth", "wifi"):
            interface = self.device_state.get(interface_name)
            if isinstance(interface, dict) and interface.get("ip"):
                return str(interface["ip"])
        address = self.device_state.get("ip")
        return str(address) if address else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return network details reported by the hub."""
        attributes: dict[str, Any] = {}
        for prefix, interface_name in (("ethernet", "eth"), ("wifi", "wifi")):
            interface = self.device_state.get(interface_name)
            if not isinstance(interface, dict):
                continue
            for source, target in (
                ("enable", "connected"),
                ("ip", "ip_address"),
                ("gateway", "gateway"),
                ("mask", "subnet_mask"),
            ):
                if source in interface:
                    attributes[f"{prefix}_{target}"] = interface[source]
            if interface_name == "wifi" and "ssid" in interface:
                attributes["wifi_ssid"] = interface["ssid"]
        for source, target in (
            ("homeId", "home_id"),
            ("httpPort", "local_api_port"),
            ("mqttPort", "mqtt_port"),
        ):
            if source in self.device_state:
                attributes[target] = self.device_state[source]
        return attributes


class YoLocalHubDeviceCountSensor(YoLocalEntity, SensorEntity):
    """Number of devices managed by the YoLink Local Hub."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:devices"
    _attr_name = "Managed devices"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the managed device count sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_managed_devices"

    @property
    def native_value(self) -> int | None:
        """Return the number of devices managed by the hub."""
        count = self.device_state.get("managedDevices")
        return count if isinstance(count, int) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return online counts and a breakdown by device type."""
        attributes: dict[str, Any] = {}
        for source, target in (
            ("onlineDevices", "online_devices"),
            ("offlineDevices", "offline_devices"),
            ("deviceTypes", "device_types"),
        ):
            if source in self.device_state:
                attributes[target] = self.device_state[source]
        return attributes


class YoLocalHubOnlineDeviceCountSensor(YoLocalEntity, SensorEntity):
    """Number of managed devices currently reported online."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:check-network-outline"
    _attr_name = "Online devices"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the online-device count sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_online_devices"

    @property
    def native_value(self) -> int | None:
        """Return the number of managed devices reported online."""
        count = self.device_state.get("onlineDevices")
        return count if isinstance(count, int) else None


class YoLocalHubOfflineDeviceCountSensor(YoLocalEntity, SensorEntity):
    """Number of managed devices currently reported offline."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:network-off-outline"
    _attr_name = "Offline devices"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the offline-device count sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_offline_devices"

    @property
    def native_value(self) -> int | None:
        """Return the number of managed devices reported offline."""
        count = self.device_state.get("offlineDevices")
        return count if isinstance(count, int) else None


class YoLocalHubHTTPLatencySensor(YoLocalEntity, SensorEntity):
    """Duration of the most recent Local API polling cycle."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timer-outline"
    _attr_name = "HTTP response latency"
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the HTTP latency sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_http_latency"

    @property
    def native_value(self) -> float | None:
        """Return the latest polling-cycle duration in milliseconds."""
        value = self.device_state.get("httpLatencyMs")
        return value if isinstance(value, (int, float)) else None


class YoLocalHubLastHTTPPollSensor(YoLocalEntity, SensorEntity):
    """Time of the last fully successful Local API poll."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Last successful HTTP poll"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the last HTTP poll sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_last_http_poll"

    @property
    def native_value(self) -> Any:
        """Return the timestamp of the last successful HTTP poll."""
        return self.device_state.get("lastHttpPoll")


class YoLocalHubLastMQTTMessageSensor(YoLocalEntity, SensorEntity):
    """Time of the last MQTT device message."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Last MQTT message"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the last MQTT message sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_last_mqtt_message"

    @property
    def native_value(self) -> Any:
        """Return the timestamp of the most recent MQTT message."""
        return self.device_state.get("lastMqttMessage")


class YoLocalHubTokenExpirySensor(YoLocalEntity, SensorEntity):
    """Expiry time and refresh details for the Local API access token."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:key-clock"
    _attr_name = "Access token expiration"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the access-token expiry sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_token_expiry"

    @property
    def native_value(self) -> Any:
        """Return the access-token expiration timestamp."""
        return self.device_state.get("tokenExpiresAt")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the latest token refresh attempt."""
        attributes: dict[str, Any] = {}
        if "lastTokenRefresh" in self.device_state:
            attributes["last_refresh"] = self.device_state["lastTokenRefresh"]
        if "tokenRefreshSuccessful" in self.device_state:
            attributes["last_refresh_successful"] = self.device_state[
                "tokenRefreshSuccessful"
            ]
        return attributes


class YoLocalHubCloudBatteryStateSensor(YoLocalEntity, SensorEntity):
    """Operating state of the hub backup battery."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-heart-variant"
    _attr_name = "Battery state (cloud)"
    _attr_options = list(CLOUD_BATTERY_STATES.values())

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the cloud battery-state sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_battery_state"

    @property
    def native_value(self) -> str | None:
        """Return the documented meaning of the cloud battery-state code."""
        other = _cloud_state(self.device_state).get("other")
        power = other.get("power") if isinstance(other, dict) else None
        code = power.get("batteryState") if isinstance(power, dict) else None
        return CLOUD_BATTERY_STATES.get(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the raw YoLink battery-state code."""
        other = _cloud_state(self.device_state).get("other")
        power = other.get("power") if isinstance(other, dict) else None
        if not isinstance(power, dict) or "batteryState" not in power:
            return {}
        return {"raw_battery_state": power["batteryState"]}


class YoLocalHubCloudNetworkSensor(YoLocalEntity, SensorEntity):
    """Active network interface reported by YoLink Cloud."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-sync-outline"
    _attr_name = "Network (cloud)"
    _attr_options = ["ethernet", "wi_fi", "disconnected"]

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the cloud network sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_network"

    @property
    def native_value(self) -> str | None:
        """Return the active cloud-reported network interface."""
        state = _cloud_state(self.device_state)
        if not state:
            return None
        if isinstance(state.get("eth"), dict) and state["eth"].get("enable"):
            return "ethernet"
        if isinstance(state.get("wifi"), dict) and state["wifi"].get("enable"):
            return "wi_fi"
        return "disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return cloud-reported Ethernet and Wi-Fi details."""
        attributes: dict[str, Any] = {}
        state = _cloud_state(self.device_state)
        for prefix, interface_name in (("ethernet", "eth"), ("wifi", "wifi")):
            interface = state.get(interface_name)
            if not isinstance(interface, dict):
                continue
            for source, target in (
                ("enable", "connected"),
                ("ip", "ip_address"),
                ("gateway", "gateway"),
                ("mask", "subnet_mask"),
                ("ssid", "ssid"),
            ):
                if source in interface:
                    attributes[f"{prefix}_{target}"] = interface[source]
        return attributes


class YoLocalHubCloudComponentsSensor(YoLocalEntity, SensorEntity):
    """Internal hub component versions reported by YoLink Cloud."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:expansion-card-variant"
    _attr_name = "Component versions (cloud)"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the component-version sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_cloud_components"

    @property
    def native_value(self) -> str | None:
        """Return the communications component version."""
        other = _cloud_state(self.device_state).get("other")
        version = other.get("comVer") if isinstance(other, dict) else None
        return str(version) if version is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return other useful internal component versions."""
        other = _cloud_state(self.device_state).get("other")
        if not isinstance(other, dict):
            return {}
        attributes: dict[str, Any] = {}
        for source, target in (
            ("netVer", "network_version"),
            ("codecVer", "codec_version"),
            ("timezone", "timezone"),
            ("supportNRP", "supports_nrp"),
        ):
            if source in other:
                attributes[target] = other[source]
        return attributes


class YoLocalHubLastCloudPollSensor(YoLocalEntity, SensorEntity):
    """Time of the last successful optional cloud diagnostics update."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-clock-outline"
    _attr_name = "Last successful poll (cloud)"

    def __init__(self, coordinator: YoLocalCoordinator, device) -> None:
        """Initialize the cloud polling timestamp sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_last_cloud_poll"

    @property
    def native_value(self) -> Any:
        """Return the timestamp of the last successful cloud update."""
        return self.device_state.get("lastCloudPoll")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return cloud health as attributes instead of duplicate entities."""
        attributes: dict[str, Any] = {
            "cloud_accessible": bool(
                self.device_state.get("cloudConnected", False)
            ),
            "authenticated": bool(
                self.device_state.get("cloudAuthenticated", False)
            ),
        }
        if "cloudHubId" in self.device_state:
            attributes["hub_device_id"] = self.device_state["cloudHubId"]
        return attributes
