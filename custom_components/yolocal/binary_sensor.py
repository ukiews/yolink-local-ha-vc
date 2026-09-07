"""Binary sensor platform for YoLink Local integration."""

from __future__ import annotations

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
            entities.append(
                YoLocalHubConnectivitySensor(coordinator, device, "eth", "Ethernet")
            )
            entities.append(
                YoLocalHubConnectivitySensor(coordinator, device, "wifi", "Wi-Fi")
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
