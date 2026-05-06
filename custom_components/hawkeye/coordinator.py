"""Coordinator de Hawkeye.

Cada hora cerrada (al pasar de las XX:59 a las XX+1:00):
  1. Lee del Recorder el delta del sensor de consumo total para esa hora.
  2. Lee del Recorder el delta de cada sensor de asset gestionable.
  3. Llama a calculate_mv() para ese día acumulado hasta esa hora.
  4. Actualiza el resultado en hass.data y notifica a los sensores.

A las 00:05 del día siguiente cierra el día y empieza nuevo.
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, time, timedelta
from typing import Any, Optional

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
from .core import calculate_mv, constant_price, hourly_prices
from .models import (
    Appliance,
    DailyMV,
    DayOfWeek,
    ElectricVehicle,
    HawkeyeConfig,
    HourlyData,
    HourlyMV,
    SolarPV,
)
from .overrides import OverrideStore

_LOGGER = logging.getLogger(__name__)


class HawkeyeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordina las medidas y el cálculo M&V hora a hora."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        override_store: OverrideStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # Por evento, no por polling
        )
        self.entry = entry
        self._override_store = override_store
        self._unsub_hourly = None
        self._unsub_midnight = None
        self._unsub_price_sensor = None

        # Estado del cálculo del día actual
        self._current_date: Optional[date_type] = None
        self._real_hourly: list[Optional[float]] = [None] * 24
        self._asset_hourly: dict[str, list[Optional[float]]] = {}
        self._last_hour_processed: int = -1
        self._last_result: Optional[DailyMV] = None
        self._price_source: str = "default"

    # ── Setup / teardown ─────────────────────────────────────────────

    async def _async_setup(self) -> None:
        """Programa los timers."""
        # Tick cada hora al minuto 0
        self._unsub_hourly = async_track_time_change(
            self.hass,
            self._on_hour_tick,
            minute=0,
            second=5,
        )
        # Cierre del día a las 00:05
        self._unsub_midnight = async_track_time_change(
            self.hass,
            self._on_midnight,
            hour=0,
            minute=5,
            second=0,
        )

        # Suscribirse al sensor de precios si hay
        data = self._merged_data()
        price_sensor = data.get(CONF_PRICE_SENSOR)
        if price_sensor:
            self._unsub_price_sensor = async_track_state_change_event(
                self.hass,
                [price_sensor],
                self._on_price_change,
            )

    async def async_shutdown(self) -> None:
        for unsub in (self._unsub_hourly, self._unsub_midnight, self._unsub_price_sensor):
            if unsub is not None:
                unsub()
        self._unsub_hourly = self._unsub_midnight = self._unsub_price_sensor = None

    @callback
    def _on_hour_tick(self, _now: datetime) -> None:
        _LOGGER.debug("Hour tick")
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _on_midnight(self, _now: datetime) -> None:
        _LOGGER.info("Cierre del día")
        # Forzamos un último refresh para consolidar
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _on_price_change(self, _event) -> None:
        _LOGGER.debug("Cambio en sensor de precios")
        self.hass.async_create_task(self.async_request_refresh())

    # ── Helpers ──────────────────────────────────────────────────────

    def _merged_data(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    def _build_assets(self, target_date: date_type) -> list:
        """Construye la lista de assets aplicando overrides del día.

        Si hay un override para un asset en target_date, sus parámetros
        se aplican por encima del patrón por defecto.
        """
        data = self._merged_data()
        raw_assets = data.get(CONF_ASSETS, [])
        assets = []

        for raw in raw_assets:
            asset_type = raw[ASSET_TYPE]
            name = raw[ASSET_NAME]

            # Aplicar override si lo hay
            override = self._override_store.get(name, target_date) or {}

            if asset_type == ASSET_TYPE_APPLIANCE:
                days = override.get(ASSET_DAYS, raw[ASSET_DAYS])
                start_hour = override.get(ASSET_NAIVE_START_HOUR, raw[ASSET_NAIVE_START_HOUR])
                duration = override.get(ASSET_NAIVE_DURATION_HOURS, raw[ASSET_NAIVE_DURATION_HOURS])
                assets.append(Appliance(
                    name=name,
                    days_of_week=tuple(DayOfWeek(int(d)) for d in days),
                    naive_start_hour=int(start_hour),
                    naive_duration_hours=int(duration),
                ))
            elif asset_type == ASSET_TYPE_EV:
                arrival = override.get(ASSET_NAIVE_ARRIVAL_HOUR, raw[ASSET_NAIVE_ARRIVAL_HOUR])
                power = raw[ASSET_MAX_POWER_KW]
                assets.append(ElectricVehicle(
                    name=name,
                    naive_arrival_hour=int(arrival),
                    max_power_kw=float(power),
                ))
            elif asset_type == ASSET_TYPE_SOLAR:
                assets.append(SolarPV(name=name))

        return assets

    def _asset_sensor_map(self) -> dict[str, str]:
        """Devuelve {nombre_asset: entity_id_sensor}."""
        data = self._merged_data()
        return {a[ASSET_NAME]: a[ASSET_SENSOR] for a in data.get(CONF_ASSETS, [])}

    # ── Lectura del Recorder ────────────────────────────────────────

    async def _read_hour_delta(
        self,
        sensor_id: str,
        hour_start: datetime,
        hour_end: datetime,
    ) -> Optional[float]:
        """Calcula los kWh consumidos por un sensor entre hour_start y hour_end.

        Para sensores total_increasing, el delta = state(hour_end) - state(hour_start).
        Si no hay datos, devuelve None.
        """
        try:
            recorder = get_instance(self.hass)

            def _fetch_states():
                return state_changes_during_period(
                    self.hass,
                    hour_start,
                    hour_end,
                    entity_id=sensor_id,
                    include_start_time_state=True,
                    no_attributes=True,
                )

            history = await recorder.async_add_executor_job(_fetch_states)
            states = history.get(sensor_id, [])

            if not states:
                return None

            # Filtramos estados numéricos válidos
            numeric = []
            for st in states:
                try:
                    v = float(st.state)
                    numeric.append((st.last_changed, v))
                except (ValueError, TypeError):
                    continue

            if len(numeric) < 1:
                return None

            first_value = numeric[0][1]
            last_value = numeric[-1][1]
            delta = last_value - first_value

            # Si hay reset del medidor (delta negativo), no podemos calcular
            if delta < 0:
                _LOGGER.debug(
                    "Sensor %s reset detectado entre %s y %s",
                    sensor_id, hour_start, hour_end,
                )
                return None

            return delta

        except Exception as exc:
            _LOGGER.warning("Error leyendo histórico de %s: %s", sensor_id, exc)
            return None

    async def _update_hourly_consumption(self, now: datetime) -> None:
        """Actualiza las medidas hora a hora desde el inicio del día actual.

        Lee el Recorder y rellena las horas que aún no se hayan procesado.
        """
        today = now.date()
        # Reset si cambiamos de día
        if self._current_date != today:
            self._current_date = today
            self._real_hourly = [None] * 24
            self._asset_hourly = {name: [None] * 24 for name in self._asset_sensor_map()}
            self._last_hour_processed = -1

        data = self._merged_data()
        total_sensor = data.get(CONF_TOTAL_CONSUMPTION_SENSOR)
        if not total_sensor:
            return

        asset_sensors = self._asset_sensor_map()

        # Solo procesamos horas COMPLETAS (la actual aún está en curso)
        target_last_hour = now.hour - 1
        if now.hour == 0:
            # Si es la 00, las horas a procesar son las del día ANTERIOR
            # — pero esa lógica la tratamos en el cierre de día separado.
            return

        # Procesar horas pendientes
        for h in range(self._last_hour_processed + 1, target_last_hour + 1):
            if h < 0 or h >= 24:
                continue

            hour_start = datetime.combine(today, time(h, 0))
            hour_end = datetime.combine(today, time(h, 0)) + timedelta(hours=1)

            # Convertir a UTC tz-aware para Recorder
            hour_start = dt_util.as_utc(dt_util.as_local(hour_start))
            hour_end = dt_util.as_utc(dt_util.as_local(hour_end))

            # Total
            self._real_hourly[h] = await self._read_hour_delta(
                total_sensor, hour_start, hour_end,
            )

            # Por cada asset
            for name, sensor_id in asset_sensors.items():
                self._asset_hourly[name][h] = await self._read_hour_delta(
                    sensor_id, hour_start, hour_end,
                )

            self._last_hour_processed = h
            _LOGGER.info(
                "Hora %02d procesada: total=%s, assets=%s",
                h,
                self._real_hourly[h],
                {n: vals[h] for n, vals in self._asset_hourly.items()},
            )

    # ── Resolución del precio ───────────────────────────────────────

    def _build_price_fn(self):
        """Devuelve (PriceFn, descripción del origen)."""
        data = self._merged_data()
        sensor_id = data.get(CONF_PRICE_SENSOR)
        fallback = float(data.get(CONF_PRICE_FALLBACK, 0.20))

        if sensor_id:
            prices = self._read_prices_from_sensor(sensor_id)
            if prices:
                return hourly_prices(prices), f"sensor:{sensor_id}"
            _LOGGER.warning(
                "Sensor de precios %s no proporciona today_prices/tomorrow_prices válidos. "
                "Usando fallback plano %s €/kWh.",
                sensor_id, fallback,
            )
            return constant_price(fallback), f"fallback:flat({fallback})"

        return constant_price(fallback), f"flat:{fallback}"

    def _read_prices_from_sensor(self, entity_id: str) -> Optional[list[float]]:
        """Intenta leer los precios horarios de un sensor.

        Acepta:
          - attributes['today_prices']: dict {"HH:00": precio} o lista 24
          - attributes['tomorrow_prices']: idem
          - state numérico (último recurso, repetido 24 veces)
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        attrs = state.attributes or {}
        for key in ("today_prices", "tomorrow_prices"):
            normalized = self._normalize_prices(attrs.get(key))
            if normalized is not None:
                return normalized
        # Fallback: state actual repetido
        try:
            return [float(state.state)] * 24
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _normalize_prices(raw: Any) -> Optional[list[float]]:
        if raw is None:
            return None
        if isinstance(raw, list) and len(raw) == 24:
            try:
                return [float(v) for v in raw]
            except (ValueError, TypeError):
                return None
        if isinstance(raw, dict) and len(raw) == 24:
            try:
                items = []
                for k, v in raw.items():
                    hour = int(k.split(":")[0]) if isinstance(k, str) else int(k)
                    items.append((hour, float(v)))
                items.sort(key=lambda x: x[0])
                if [h for h, _ in items] == list(range(24)):
                    return [v for _, v in items]
            except (ValueError, TypeError):
                return None
        return None

    # ── Update principal ────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Tick: lee histórico, calcula M&V, devuelve resultado."""
        if self._unsub_hourly is None:
            await self._async_setup()

        now = dt_util.now()

        # 1. Actualizar las medidas leyendo del histórico
        await self._update_hourly_consumption(now)

        # 2. Construir la HawkeyeConfig (con overrides) y la HourlyMV
        target_date = self._current_date or now.date()
        assets = self._build_assets(target_date)
        config = HawkeyeConfig(assets=assets)

        # Reorganizar self._asset_hourly en HourlyData por asset
        asset_consumptions = {
            name: HourlyData.from_list(list(values))
            for name, values in self._asset_hourly.items()
        }

        mv = HourlyMV(
            target_date=target_date,
            total_consumption=HourlyData.from_list(list(self._real_hourly)),
            asset_consumptions=asset_consumptions,
        )

        # 3. Resolver precio
        price_fn, price_source = self._build_price_fn()
        self._price_source = price_source

        # 4. Calcular M&V
        result = calculate_mv(config, mv, price_fn)
        self._last_result = result

        _LOGGER.debug(
            "M&V calculado para %s: ahorro %.4f € (%d warnings)",
            target_date, result.total_savings_eur, len(result.warnings),
        )

        return {
            "now": now,
            "target_date": target_date,
            "result": result,
            "price_source": price_source,
            "last_hour_processed": self._last_hour_processed,
            "overrides_today": self._override_store.get(
                next(iter(self._asset_sensor_map()), ""), target_date,
            ) if self._asset_sensor_map() else None,
        }

    # ── API para los sensores ───────────────────────────────────────

    @property
    def last_result(self) -> Optional[DailyMV]:
        return self._last_result

    @property
    def price_source(self) -> str:
        return self._price_source

    @property
    def last_hour_processed(self) -> int:
        return self._last_hour_processed
