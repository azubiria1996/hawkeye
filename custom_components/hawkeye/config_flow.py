"""Config Flow de Hawkeye.

Wizard:
  1. user             → sensor de consumo total + sensor de precios + fallback
  2. add_asset        → tipo de asset (appliance / ev / solar)
  3. add_appliance    → si elige appliance: nombre, sensor, días, hora, kWh, duración
  4. add_ev           → si elige ev: nombre, sensor, hora llegada, potencia max
  5. add_solar        → si elige solar: nombre, sensor
  6. more             → ¿añadir otro asset o terminar?
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    ASSET_DAYS,
    ASSET_MAX_POWER_KW,
    ASSET_NAIVE_ARRIVAL_HOUR,
    ASSET_NAIVE_DURATION_HOURS,
    ASSET_NAIVE_START_HOUR,
    ASSET_NAME,
    ASSET_SENSOR,
    ASSET_TYPE,
    ASSET_TYPE_APPLIANCE,
    ASSET_TYPE_EV,
    ASSET_TYPE_SOLAR,
    CONF_ASSETS,
    CONF_PRICE_FALLBACK,
    CONF_PRICE_SENSOR,
    CONF_TOTAL_CONSUMPTION_SENSOR,
    DOMAIN,
)


DAY_LABELS = {
    "0": "Lunes",
    "1": "Martes",
    "2": "Miércoles",
    "3": "Jueves",
    "4": "Viernes",
    "5": "Sábado",
    "6": "Domingo",
}

ASSET_TYPE_LABELS = {
    ASSET_TYPE_APPLIANCE: "Electrodoméstico (lavadora, lavavajillas, secadora...)",
    ASSET_TYPE_EV: "Vehículo eléctrico",
    ASSET_TYPE_SOLAR: "Solar fotovoltaica",
}


def _user_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema({
        vol.Required(
            CONF_TOTAL_CONSUMPTION_SENSOR,
            default=d.get(CONF_TOTAL_CONSUMPTION_SENSOR, ""),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="energy",
            ),
        ),
        vol.Optional(
            CONF_PRICE_SENSOR,
            default=d.get(CONF_PRICE_SENSOR, ""),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Optional(
            CONF_PRICE_FALLBACK,
            default=d.get(CONF_PRICE_FALLBACK, 0.20),
        ): vol.All(vol.Coerce(float), vol.Range(min=0, max=2)),
    })


def _asset_type_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(ASSET_TYPE, default=ASSET_TYPE_APPLIANCE): vol.In(ASSET_TYPE_LABELS),
    })


def _appliance_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(ASSET_NAME): str,
        vol.Required(ASSET_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="energy",
            ),
        ),
        vol.Required(ASSET_DAYS, default=["0", "2", "4"]): cv.multi_select(DAY_LABELS),
        vol.Required(ASSET_NAIVE_START_HOUR, default=21): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=23),
        ),
        vol.Required(ASSET_NAIVE_DURATION_HOURS, default=2): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=24),
        ),
    })


def _ev_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(ASSET_NAME, default="coche"): str,
        vol.Required(ASSET_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="energy",
            ),
        ),
        vol.Required(ASSET_NAIVE_ARRIVAL_HOUR, default=18): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=23),
        ),
        vol.Required(ASSET_MAX_POWER_KW, default=7.4): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=22),
        ),
    })


def _solar_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(ASSET_NAME, default="solar"): str,
        vol.Required(ASSET_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="energy",
            ),
        ),
    })


def _more_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required("action", default="finish"): vol.In({
            "add": "Añadir otro electrodoméstico/equipo",
            "finish": "Terminar y crear",
        }),
    })


# ── Config Flow ─────────────────────────────────────────────────────────


class HawkeyeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Wizard inicial."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {CONF_ASSETS: []}
        self._next_asset_type: str = ASSET_TYPE_APPLIANCE

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._data[CONF_TOTAL_CONSUMPTION_SENSOR] = user_input[CONF_TOTAL_CONSUMPTION_SENSOR]
            if user_input.get(CONF_PRICE_SENSOR):
                self._data[CONF_PRICE_SENSOR] = user_input[CONF_PRICE_SENSOR]
            self._data[CONF_PRICE_FALLBACK] = user_input.get(CONF_PRICE_FALLBACK, 0.20)
            return await self.async_step_add_asset()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
        )

    async def async_step_add_asset(self, user_input=None):
        """El usuario elige el tipo del próximo asset a añadir."""
        if user_input is not None:
            self._next_asset_type = user_input[ASSET_TYPE]
            if self._next_asset_type == ASSET_TYPE_APPLIANCE:
                return await self.async_step_add_appliance()
            if self._next_asset_type == ASSET_TYPE_EV:
                return await self.async_step_add_ev()
            return await self.async_step_add_solar()

        return self.async_show_form(
            step_id="add_asset",
            data_schema=_asset_type_schema(),
            description_placeholders={
                "n_assets": str(len(self._data[CONF_ASSETS])),
            },
        )

    async def async_step_add_appliance(self, user_input=None):
        if user_input is not None:
            self._data[CONF_ASSETS].append({
                ASSET_TYPE: ASSET_TYPE_APPLIANCE,
                ASSET_NAME: user_input[ASSET_NAME],
                ASSET_SENSOR: user_input[ASSET_SENSOR],
                ASSET_DAYS: user_input[ASSET_DAYS],
                ASSET_NAIVE_START_HOUR: user_input[ASSET_NAIVE_START_HOUR],
                ASSET_NAIVE_DURATION_HOURS: user_input[ASSET_NAIVE_DURATION_HOURS],
            })
            return await self.async_step_more()

        return self.async_show_form(
            step_id="add_appliance",
            data_schema=_appliance_schema(),
        )

    async def async_step_add_ev(self, user_input=None):
        if user_input is not None:
            self._data[CONF_ASSETS].append({
                ASSET_TYPE: ASSET_TYPE_EV,
                ASSET_NAME: user_input[ASSET_NAME],
                ASSET_SENSOR: user_input[ASSET_SENSOR],
                ASSET_NAIVE_ARRIVAL_HOUR: user_input[ASSET_NAIVE_ARRIVAL_HOUR],
                ASSET_MAX_POWER_KW: user_input[ASSET_MAX_POWER_KW],
            })
            return await self.async_step_more()

        return self.async_show_form(
            step_id="add_ev",
            data_schema=_ev_schema(),
        )

    async def async_step_add_solar(self, user_input=None):
        if user_input is not None:
            self._data[CONF_ASSETS].append({
                ASSET_TYPE: ASSET_TYPE_SOLAR,
                ASSET_NAME: user_input[ASSET_NAME],
                ASSET_SENSOR: user_input[ASSET_SENSOR],
            })
            return await self.async_step_more()

        return self.async_show_form(
            step_id="add_solar",
            data_schema=_solar_schema(),
        )

    async def async_step_more(self, user_input=None):
        if user_input is not None:
            if user_input["action"] == "add":
                return await self.async_step_add_asset()
            if not self._data[CONF_ASSETS]:
                # No se permite terminar sin al menos un asset
                return await self.async_step_add_asset()
            return self.async_create_entry(
                title="Hawkeye",
                data=self._data,
            )

        if not self._data[CONF_ASSETS]:
            return await self.async_step_add_asset()

        names = ", ".join(a[ASSET_NAME] for a in self._data[CONF_ASSETS])
        return self.async_show_form(
            step_id="more",
            data_schema=_more_schema(),
            description_placeholders={
                "n_assets": str(len(self._data[CONF_ASSETS])),
                "asset_names": names,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return HawkeyeOptionsFlow(config_entry)


# ── Options Flow ────────────────────────────────────────────────────────


class HawkeyeOptionsFlow(config_entries.OptionsFlow):
    """Permite editar la configuración después de crearla."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry
        self._data: dict[str, Any] = {**entry.data, **entry.options}
        if CONF_ASSETS not in self._data:
            self._data[CONF_ASSETS] = []

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            choice = user_input["choice"]
            if choice == "edit_global":
                return await self.async_step_edit_global()
            if choice == "replace_assets":
                self._data[CONF_ASSETS] = []
                return await self.async_step_add_asset()
            return self.async_create_entry(title="", data=self._data)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("choice", default="edit_global"): vol.In({
                    "edit_global": "Editar sensores principales",
                    "replace_assets": "Reemplazar todos los electrodomésticos/equipos",
                    "save": "Guardar y salir",
                }),
            }),
            description_placeholders={
                "n_assets": str(len(self._data.get(CONF_ASSETS, []))),
                "assets_summary": _summarize_assets(self._data.get(CONF_ASSETS, [])),
            },
        )

    async def async_step_edit_global(self, user_input=None):
        if user_input is not None:
            self._data[CONF_TOTAL_CONSUMPTION_SENSOR] = user_input[CONF_TOTAL_CONSUMPTION_SENSOR]
            if user_input.get(CONF_PRICE_SENSOR):
                self._data[CONF_PRICE_SENSOR] = user_input[CONF_PRICE_SENSOR]
            elif CONF_PRICE_SENSOR in self._data:
                del self._data[CONF_PRICE_SENSOR]
            self._data[CONF_PRICE_FALLBACK] = user_input.get(CONF_PRICE_FALLBACK, 0.20)
            return self.async_create_entry(title="", data=self._data)

        return self.async_show_form(
            step_id="edit_global",
            data_schema=_user_schema(self._data),
        )

    async def async_step_add_asset(self, user_input=None):
        if user_input is not None:
            t = user_input[ASSET_TYPE]
            if t == ASSET_TYPE_APPLIANCE:
                return await self.async_step_add_appliance()
            if t == ASSET_TYPE_EV:
                return await self.async_step_add_ev()
            return await self.async_step_add_solar()

        return self.async_show_form(
            step_id="add_asset",
            data_schema=_asset_type_schema(),
            description_placeholders={"n_assets": str(len(self._data[CONF_ASSETS]))},
        )

    async def async_step_add_appliance(self, user_input=None):
        if user_input is not None:
            self._data[CONF_ASSETS].append({
                ASSET_TYPE: ASSET_TYPE_APPLIANCE,
                ASSET_NAME: user_input[ASSET_NAME],
                ASSET_SENSOR: user_input[ASSET_SENSOR],
                ASSET_DAYS: user_input[ASSET_DAYS],
                ASSET_NAIVE_START_HOUR: user_input[ASSET_NAIVE_START_HOUR],
                ASSET_NAIVE_DURATION_HOURS: user_input[ASSET_NAIVE_DURATION_HOURS],
            })
            return await self.async_step_more()

        return self.async_show_form(
            step_id="add_appliance",
            data_schema=_appliance_schema(),
        )

    async def async_step_add_ev(self, user_input=None):
        if user_input is not None:
            self._data[CONF_ASSETS].append({
                ASSET_TYPE: ASSET_TYPE_EV,
                ASSET_NAME: user_input[ASSET_NAME],
                ASSET_SENSOR: user_input[ASSET_SENSOR],
                ASSET_NAIVE_ARRIVAL_HOUR: user_input[ASSET_NAIVE_ARRIVAL_HOUR],
                ASSET_MAX_POWER_KW: user_input[ASSET_MAX_POWER_KW],
            })
            return await self.async_step_more()

        return self.async_show_form(
            step_id="add_ev",
            data_schema=_ev_schema(),
        )

    async def async_step_add_solar(self, user_input=None):
        if user_input is not None:
            self._data[CONF_ASSETS].append({
                ASSET_TYPE: ASSET_TYPE_SOLAR,
                ASSET_NAME: user_input[ASSET_NAME],
                ASSET_SENSOR: user_input[ASSET_SENSOR],
            })
            return await self.async_step_more()

        return self.async_show_form(
            step_id="add_solar",
            data_schema=_solar_schema(),
        )

    async def async_step_more(self, user_input=None):
        if user_input is not None:
            if user_input["action"] == "add":
                return await self.async_step_add_asset()
            if not self._data[CONF_ASSETS]:
                return await self.async_step_add_asset()
            return self.async_create_entry(title="", data=self._data)

        if not self._data[CONF_ASSETS]:
            return await self.async_step_add_asset()

        names = ", ".join(a[ASSET_NAME] for a in self._data[CONF_ASSETS])
        return self.async_show_form(
            step_id="more",
            data_schema=_more_schema(),
            description_placeholders={
                "n_assets": str(len(self._data[CONF_ASSETS])),
                "asset_names": names,
            },
        )


def _summarize_assets(assets: list[dict]) -> str:
    if not assets:
        return "(sin equipos)"
    lines = []
    for a in assets:
        t = a[ASSET_TYPE]
        name = a[ASSET_NAME]
        if t == ASSET_TYPE_APPLIANCE:
            days = "/".join(DAY_LABELS[str(d)][:3] for d in a[ASSET_DAYS])
            lines.append(
                f"🧺 {name}: {days} a las {a[ASSET_NAIVE_START_HOUR]:02d}:00 "
                f"({a[ASSET_NAIVE_DURATION_HOURS]}h)"
            )
        elif t == ASSET_TYPE_EV:
            lines.append(
                f"🚗 {name}: llega a las {a[ASSET_NAIVE_ARRIVAL_HOUR]:02d}:00, "
                f"{a[ASSET_MAX_POWER_KW]} kW"
            )
        elif t == ASSET_TYPE_SOLAR:
            lines.append(f"☀️ {name}")
    return "\n".join(lines)
