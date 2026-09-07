"""Sensor platform for YoLink Local integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
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
    {"WaterLeakController", "WaterMeterController"}
)


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
            entities.append(YoLocalHubFirmwareSensor(coordinator, device))
            entities.append(YoLocalHubIPAddressSensor(coordinator, device))

        if device.device_type in POWER_SOURCE_DEVICE_TYPES:
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
        return None

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
        return attributes
