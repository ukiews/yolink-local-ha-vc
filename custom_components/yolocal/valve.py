"""Valve platform for YoLink Local integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Device
from .const import DOMAIN
from .coordinator import YoLocalCoordinator
from .entity import YoLocalEntity

VALVE_DEVICE_TYPES = frozenset(
    {"Manipulator", "WaterLeakController", "WaterMeterController"}
)
NESTED_VALVE_DEVICE_TYPES = frozenset(
    {"WaterLeakController", "WaterMeterController"}
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up YoLink valves from a config entry."""
    coordinator: YoLocalCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        YoLocalValve(coordinator, device)
        for device in coordinator.devices.values()
        if device.device_type in VALVE_DEVICE_TYPES
    ]
    async_add_entities(entities)


class YoLocalValve(YoLocalEntity, ValveEntity):
    """Valve entity for YoLink valve controllers and manipulators."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_name = None  # Use device name
    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE

    def __init__(self, coordinator: YoLocalCoordinator, device: Device) -> None:
        """Initialize the valve."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.device_id}_valve"

    @property
    def is_closed(self) -> bool | None:
        """Return True if the valve is closed."""
        state = self.device_state.get("state")

        # Water controller APIs nest the valve state, while Manipulator uses a
        # top-level state string. Accept both shapes so MQTT partial updates do
        # not make the entity unknown.
        if isinstance(state, dict):
            valve_state = state.get("valve", state.get("state"))
        else:
            valve_state = state

        if valve_state is None:
            valve_state = self.device_state.get("valve")
        if not isinstance(valve_state, str):
            return None

        normalized_state = valve_state.lower()
        if normalized_state in {"close", "closed"}:
            return True
        if normalized_state in {"open", "opened"}:
            return False
        return None

    async def async_open_valve(self, **kwargs: Any) -> None:
        """Open the valve."""
        await self.coordinator.async_send_command(
            self._device.device_id,
            self._command_params("open"),
        )

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Close the valve."""
        await self.coordinator.async_send_command(
            self._device.device_id,
            self._command_params("close"),
        )

    def _command_params(self, command: str) -> dict[str, str]:
        """Return the command payload expected by this device family."""
        if self._device.device_type in NESTED_VALVE_DEVICE_TYPES:
            return {"valve": command}
        return {"state": command}
