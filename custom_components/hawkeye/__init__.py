"""Hawkeye — medidor de ahorro energético para Home Assistant.

Implementa el método Measurement & Verification (M&V) del IPMVP.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    DOMAIN,
    PLATFORMS,
    SERVICE_RECALCULATE,
)
from .coordinator import HawkeyeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura la integración para una entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = HawkeyeCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Registrar el servicio (una sola vez aunque haya varias entries)
    if not hass.services.has_service(DOMAIN, SERVICE_RECALCULATE):
        await _register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Limpia al eliminar la entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HawkeyeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

        # Si no quedan entries, quitamos el servicio
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_RECALCULATE)

    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _register_services(hass: HomeAssistant) -> None:
    """Registra los servicios públicos de Hawkeye."""

    async def handle_recalculate(call: ServiceCall):
        """Fuerza un recálculo manual."""
        for entry_id, coord in hass.data[DOMAIN].items():
            await coord.async_request_refresh()
            _LOGGER.info("Recálculo manual disparado para entry %s", entry_id)

    hass.services.async_register(DOMAIN, SERVICE_RECALCULATE, handle_recalculate)
