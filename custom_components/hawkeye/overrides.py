"""Almacenamiento de overrides puntuales (cambio de patrón ingenuo para un día concreto).

Los overrides se persisten en HA storage y se borran automáticamente
cuando pasa la fecha a la que aplican.

Estructura interna:
    {
        "<asset_name>": {
            "<YYYY-MM-DD>": {
                "naive_start_hour": 14,
                "naive_duration_hours": 2,
                ...
            }
        }
    }
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class OverrideStore:
    """Persistencia de overrides en HA storage."""

    def __init__(self, hass: HomeAssistant):
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def async_load(self) -> None:
        """Carga los datos desde disco."""
        loaded = await self._store.async_load()
        self._data = loaded or {}
        await self._purge_expired()

    async def async_save(self) -> None:
        """Persiste los datos a disco."""
        await self._store.async_save(self._data)

    async def _purge_expired(self) -> None:
        """Borra overrides cuya fecha ya ha pasado."""
        today = date_type.today()
        changed = False
        for asset_name in list(self._data.keys()):
            for date_str in list(self._data[asset_name].keys()):
                try:
                    d = datetime.fromisoformat(date_str).date()
                except ValueError:
                    # Fecha mal formada, la borramos
                    del self._data[asset_name][date_str]
                    changed = True
                    continue
                if d < today:
                    del self._data[asset_name][date_str]
                    changed = True
            if not self._data[asset_name]:
                del self._data[asset_name]
                changed = True
        if changed:
            await self.async_save()

    def get(self, asset_name: str, target_date: date_type) -> Optional[dict[str, Any]]:
        """Devuelve el override para un asset en una fecha, o None."""
        date_str = target_date.isoformat()
        return self._data.get(asset_name, {}).get(date_str)

    async def async_set(
        self,
        asset_name: str,
        date_str: str,
        params: dict[str, Any],
    ) -> None:
        """Fija un override."""
        if asset_name not in self._data:
            self._data[asset_name] = {}
        self._data[asset_name][date_str] = params
        await self.async_save()

    async def async_clear(self, asset_name: str, date_str: str) -> None:
        """Borra un override concreto."""
        if asset_name in self._data:
            self._data[asset_name].pop(date_str, None)
            if not self._data[asset_name]:
                del self._data[asset_name]
            await self.async_save()

    def all_active(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Devuelve todos los overrides activos (no expirados)."""
        return {k: dict(v) for k, v in self._data.items()}
