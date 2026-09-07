"""YoLink Local integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .api import AuthenticationError
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_CLOUD_CLIENT_ID,
    CONF_CLOUD_CLIENT_SECRET,
    CONF_CLOUD_HUB_ID,
    CONF_HUB_IP,
    CONF_NET_ID,
    DEFAULT_HTTP_PORT,
    DEFAULT_MQTT_PORT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import YoLocalCoordinator, create_coordinator

_LOGGER = logging.getLogger(__name__)

OBSOLETE_CLOUD_ENTITY_SUFFIXES = frozenset(
    {
        "cloud_firmware",
        "cloud_connectivity",
        "cloud_authentication",
        "cloud_online",
    }
)


def _remove_obsolete_cloud_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: YoLocalCoordinator,
) -> None:
    """Remove cloud entities superseded by metadata or compact attributes."""
    hub_ids = {
        device.device_id
        for device in coordinator.devices.values()
        if device.device_type == "Hub"
    }
    obsolete_unique_ids = {
        f"{hub_id}_{suffix}"
        for hub_id in hub_ids
        for suffix in OBSOLETE_CLOUD_ENTITY_SUFFIXES
    }
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id in obsolete_unique_ids:
            registry.async_remove(entity.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up YoLink Local from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    try:
        coordinator = await create_coordinator(
            hass=hass,
            host=entry.data[CONF_HUB_IP],
            client_id=entry.data[CONF_CLIENT_ID],
            client_secret=entry.data[CONF_CLIENT_SECRET],
            net_id=entry.data[CONF_NET_ID],
            http_port=DEFAULT_HTTP_PORT,
            mqtt_port=DEFAULT_MQTT_PORT,
            cloud_client_id=entry.options.get(CONF_CLOUD_CLIENT_ID) or None,
            cloud_client_secret=entry.options.get(CONF_CLOUD_CLIENT_SECRET) or None,
            cloud_hub_id=entry.options.get(CONF_CLOUD_HUB_ID) or None,
        )
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed("YoLink Local authentication failed") from err
    except Exception as err:
        raise ConfigEntryNotReady(
            "YoLink Local Hub is unavailable; setup will be retried"
        ) from err

    hass.data[DOMAIN][entry.entry_id] = coordinator
    _remove_obsolete_cloud_entities(hass, entry, coordinator)

    # Perform the first data refresh so the coordinator (and therefore
    # all entities) have valid state before platforms are set up.
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: YoLocalCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok
