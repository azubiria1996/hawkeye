"""Hawkeye — medidor de ahorro energético para Home Assistant.

Implementa el método Measurement & Verification (M&V) del IPMVP para
calcular ahorros reales en una vivienda.
"""
from __future__ import annotations

import logging
from datetime import date as date_type

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR_OVERRIDE,
    SERVICE_RECALCULATE,
    SERVICE_SET_OVERRIDE,
)
from .coordinator import HawkeyeCoordinator
from .overrides import OverrideStore

_LOGGER = logging.getLogger(__name__)


SET_OVERRIDE_SCHEMA = vol.Schema({
    vol.Required("asset_name"): str,
    vol.Required("date"): str,                    # ISO YYYY-MM-DD
    vol.Optional("naive_start_hour"): vol.All(int, vol.Range(min=0, max=23)),
    vol.Optional("naive_duration_hours"): vol.All(int, vol.Range(min=1, max=24)),
    vol.Optional("naive_arrival_hour"): vol.All(int, vol.Range(min=0, max=23)),
    vol.Optional("days_of_week"): [vol.All(int, vol.Range(min=0, max=6))],
})


CLEAR_OVERRIDE_SCHEMA = vol.Schema({
    vol.Required("asset_name"): str,
    vol.Required("date"): str,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura la integración para una entry."""
    # Storage compartido para overrides (uno por entry, pero como solo
    # esperamos una entry por instalación, lo hacemos a nivel global)
    if "override_store" not in hass.data.setdefault(DOMAIN, {}):
        store = OverrideStore(hass)
        await store.async_load()
        hass.data[DOMAIN]["override_store"] = store
    store: OverrideStore = hass.data[DOMAIN]["override_store"]

    coordinator = HawkeyeCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Registrar servicios (una sola vez aunque haya varias entries)
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

        # Si no quedan entries, quitamos los servicios y el store
        remaining_entries = [
            k for k in hass.data[DOMAIN].keys() if k != "override_store"
        ]
        if not remaining_entries:
            for svc in (SERVICE_RECALCULATE, SERVICE_SET_OVERRIDE, SERVICE_CLEAR_OVERRIDE):
                hass.services.async_remove(DOMAIN, svc)
            hass.data[DOMAIN].pop("override_store", None)

    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entry cuando el usuario cambia opciones."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _register_services(hass: HomeAssistant) -> None:
    """Registra los servicios públicos de Hawkeye."""

    async def handle_recalculate(call: ServiceCall):
        """Fuerza un recálculo manual."""
        for k, v in hass.data[DOMAIN].items():
            if k == "override_store":
                continue
            await v.async_request_refresh()
            _LOGGER.info("Recálculo manual disparado para entry %s", k)

    async def handle_set_override(call: ServiceCall):
        """Fija un override para un asset en un día concreto.

        Ejemplo:
          service: hawkeye.set_override
          data:
            asset_name: lavadora
            date: "2026-05-07"
            naive_start_hour: 14
        """
        store: OverrideStore = hass.data[DOMAIN]["override_store"]
        params = {k: v for k, v in call.data.items() if k not in ("asset_name", "date")}
        await store.async_set(call.data["asset_name"], call.data["date"], params)
        _LOGGER.info(
            "Override establecido: %s en %s → %s",
            call.data["asset_name"], call.data["date"], params,
        )
        # Forzar recálculo en todas las entries
        for k, v in hass.data[DOMAIN].items():
            if k != "override_store":
                await v.async_request_refresh()

    async def handle_clear_override(call: ServiceCall):
        """Borra un override concreto."""
        store: OverrideStore = hass.data[DOMAIN]["override_store"]
        await store.async_clear(call.data["asset_name"], call.data["date"])
        _LOGGER.info(
            "Override borrado: %s en %s",
            call.data["asset_name"], call.data["date"],
        )
        for k, v in hass.data[DOMAIN].items():
            if k != "override_store":
                await v.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_RECALCULATE, handle_recalculate)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_OVERRIDE, handle_set_override,
        schema=SET_OVERRIDE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_OVERRIDE, handle_clear_override,
        schema=CLEAR_OVERRIDE_SCHEMA,
    )
