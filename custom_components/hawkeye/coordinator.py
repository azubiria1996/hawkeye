"""Coordinator de Hawkeye — con statistics_during_period (igual que HA Energy).

CAMBIOS CLAVE en esta versión:

1. Lectura de Recorder vía statistics_during_period:
   En vez de state_changes_during_period (propenso a desfases entre sensores
   por timing distinto), usamos statistics_during_period que devuelve un valor
   consolidado por hora, exactamente como hace HA Energy. Esto elimina el
   desfase entre baseline y real cuando no hay consumo gestionable.

2. Sin overrides:
   La edición de patrones se hace desde la configuración (config_flow /
   futuro panel). No hay overrides puntuales.

3. Costes con fallback:
   - Real cost: lee del sensor de coste del panel HA Energy si está
     configurado. Si no, calcula como real_kWh × precio.
   - Baseline cost: siempre calculado como baseline_kWh × precio.
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, time, timedelta
from typing import Any, Optional

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    statistics_during_period,
)
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
    CONF_REAL_COST_SENSOR,
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

_LOGGER = logging.getLogger(__name__)


class HawkeyeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordina las medidas y el cálculo M&V hora a hora."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.entry = entry
        self._unsub_hourly = None
        self._unsub_midnight = None
        self._unsub_price_sensor = None

        # Estado del día actual
        self._current_date: Optional[date_type] = None
        self._real_hourly_kwh: list[Optional[float]] = [None] * 24
        self._asset_hourly_kwh: dict[str, list[Optional[float]]] = {}
        self._real_hourly_eur: list[Optional[float]] = [None] * 24
        self._last_hour_processed: int = -1
        self._last_result: Optional[DailyMV] = None
        self._price_source: str = "default"
        self._real_cost_source: str = "computed"

        # Costes acumulados
        self._baseline_hourly_eur: list[Optional[float]] = [None] * 24
        self._baseline_cost_total: float = 0.0
        self._real_cost_total: float = 0.0
        self._savings_today_eur: float = 0.0

    # ── Setup / teardown ─────────────────────────────────────────────

    async def _async_setup(self) -> None:
        self._unsub_hourly = async_track_time_change(
            self.hass,
            self._on_hour_tick,
            minute=0,
            second=5,
        )
        self._unsub_midnight = async_track_time_change(
            self.hass,
            self._on_midnight,
            hour=0,
            minute=5,
            second=0,
        )

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
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _on_price_change(self, _event) -> None:
        _LOGGER.debug("Cambio en sensor de precios")
        self.hass.async_create_task(self.async_request_refresh())

    # ── Helpers ──────────────────────────────────────────────────────

    def _merged_data(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    def _build_assets(self, target_date: date_type) -> list:
        data = self._merged_data()
        raw_assets = data.get(CONF_ASSETS, [])
        assets = []

        for raw in raw_assets:
            asset_type = raw[ASSET_TYPE]
            name = raw[ASSET_NAME]

            if asset_type == ASSET_TYPE_APPLIANCE:
                days = raw[ASSET_DAYS]
                start_hour = raw[ASSET_NAIVE_START_HOUR]
                duration = raw[ASSET_NAIVE_DURATION_HOURS]
                assets.append(Appliance(
                    name=name,
                    days_of_week=tuple(DayOfWeek(int(d)) for d in days),
                    naive_start_hour=int(start_hour),
                    naive_duration_hours=int(duration),
                ))
            elif asset_type == ASSET_TYPE_EV:
                arrival = raw[ASSET_NAIVE_ARRIVAL_HOUR]
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
        data = self._merged_data()
        return {a[ASSET_NAME]: a[ASSET_SENSOR] for a in data.get(CONF_ASSETS, [])}

    # ── Lectura del Recorder vía statistics ─────────────────────────

    async def _read_hour_stat(
        self,
        sensor_id: str,
        hour_start: datetime,
    ) -> Optional[float]:
        """Lee el delta consolidado de un sensor durante una hora concreta
        usando statistics_during_period.

        Las statistics son el mismo formato que HA Energy usa internamente:
        un valor por hora ya consolidado, garantizando coherencia entre
        sensores.

        Args:
            sensor_id: entidad a leer
            hour_start: timestamp de inicio de la hora (en formato UTC tz-aware)

        Returns:
            kWh (o €) consumidos en esa hora, o None si no hay statistic.
            Para sensores total_increasing devuelve el 'change' de la hora.
            Para sensores monetary del panel HA Energy también.
        """
        state_obj = self.hass.states.get(sensor_id)
        if state_obj is None:
            _LOGGER.debug("Sensor %s no existe en HA states", sensor_id)
            return None

        try:
            recorder = get_instance(self.hass)
            hour_end = hour_start + timedelta(hours=1)

            def _fetch():
                # statistics_during_period devuelve {entity_id: [stat_row, ...]}
                # con period='hour' y types={'change'} pedimos el delta horario
                return statistics_during_period(
                    self.hass,
                    hour_start,
                    hour_end,
                    statistic_ids={sensor_id},
                    period="hour",
                    units=None,
                    types={"change"},
                )

            result = await recorder.async_add_executor_job(_fetch)

            if not result or sensor_id not in result:
                # FIX BUG 2: sensor existe pero no hay statistic en esa hora.
                # Para sensores total_increasing esto significa que no
                # registró cambios → consumo = 0.
                return 0.0

            rows = result[sensor_id]
            if not rows:
                return 0.0

            # Cada row es {'start': ts, 'end': ts, 'change': float}
            # Sumamos todos los 'change' del rango (debería ser solo 1 entry
            # para 1 hora, pero por seguridad sumamos)
            total = 0.0
            for row in rows:
                change = row.get("change")
                if change is not None:
                    total += float(change)

            return max(0.0, total)  # Nunca devolvemos negativos

        except Exception as exc:
            _LOGGER.warning(
                "Error leyendo statistics de %s en hora %s: %s",
                sensor_id, hour_start, exc,
            )
            return None

    async def _update_hourly_consumption(self, now: datetime) -> None:
        """Actualiza las medidas hora a hora usando statistics."""
        today = now.date()
        if self._current_date != today:
            self._current_date = today
            self._real_hourly_kwh = [None] * 24
            self._asset_hourly_kwh = {name: [None] * 24 for name in self._asset_sensor_map()}
            self._real_hourly_eur = [None] * 24
            self._baseline_hourly_eur = [None] * 24
            self._last_hour_processed = -1

        data = self._merged_data()
        total_sensor = data.get(CONF_TOTAL_CONSUMPTION_SENSOR)
        if not total_sensor:
            return

        asset_sensors = self._asset_sensor_map()
        real_cost_sensor = data.get(CONF_REAL_COST_SENSOR)

        target_last_hour = now.hour - 1
        if now.hour == 0:
            return

        for h in range(self._last_hour_processed + 1, target_last_hour + 1):
            if h < 0 or h >= 24:
                continue

            # Construir el tz-aware datetime para esta hora
            local_naive = datetime.combine(today, time(h, 0))
            local_aware = dt_util.as_local(local_naive.replace(tzinfo=None))
            hour_start_utc = dt_util.as_utc(local_aware)

            # Consumo total (kWh)
            real_kwh = await self._read_hour_stat(total_sensor, hour_start_utc)
            self._real_hourly_kwh[h] = real_kwh

            # Consumo por cada asset (kWh)
            for name, sensor_id in asset_sensors.items():
                v = await self._read_hour_stat(sensor_id, hour_start_utc)
                self._asset_hourly_kwh[name][h] = v

            # Coste real (€) si hay sensor configurado
            if real_cost_sensor:
                cost_eur = await self._read_hour_stat(real_cost_sensor, hour_start_utc)
                self._real_hourly_eur[h] = cost_eur
                if cost_eur is not None:
                    self._real_cost_source = f"sensor:{real_cost_sensor}"

            self._last_hour_processed = h
            _LOGGER.info(
                "Hora %02d: total=%.3f kWh, lavadora=%s kWh, coste real=%s €",
                h,
                real_kwh or 0.0,
                {n: round(v, 3) if v is not None else "n/a"
                 for n, v in self._asset_hourly_kwh.items()},
                f"{self._real_hourly_eur[h]:.4f}" if self._real_hourly_eur[h] is not None else "n/a",
            )

    # ── Resolución del precio ───────────────────────────────────────

    def _build_price_fn(self):
        data = self._merged_data()
        sensor_id = data.get(CONF_PRICE_SENSOR)
        fallback = float(data.get(CONF_PRICE_FALLBACK, 0.20))

        if sensor_id:
            prices = self._read_prices_from_sensor(sensor_id)
            if prices:
                return hourly_prices(prices), f"sensor:{sensor_id}"
            _LOGGER.warning(
                "Sensor de precios %s sin valores válidos. Fallback a %s €/kWh.",
                sensor_id, fallback,
            )
            return constant_price(fallback), f"fallback:flat({fallback})"

        return constant_price(fallback), f"flat:{fallback}"

    def _read_prices_from_sensor(self, entity_id: str) -> Optional[list[float]]:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        attrs = state.attributes or {}
        for key in ("today_prices", "tomorrow_prices"):
            normalized = self._normalize_prices(attrs.get(key))
            if normalized is not None:
                return normalized
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
        if self._unsub_hourly is None:
            await self._async_setup()

        now = dt_util.now()

        # 1. Actualizar medidas desde Recorder
        await self._update_hourly_consumption(now)

        # 2. Construir config y HourlyMV
        target_date = self._current_date or now.date()
        assets = self._build_assets(target_date)
        config = HawkeyeConfig(assets=assets)

        asset_consumptions = {
            name: HourlyData.from_list(list(values))
            for name, values in self._asset_hourly_kwh.items()
        }

        mv = HourlyMV(
            target_date=target_date,
            total_consumption=HourlyData.from_list(list(self._real_hourly_kwh)),
            asset_consumptions=asset_consumptions,
        )

        # 3. Resolver precio
        price_fn, price_source = self._build_price_fn()
        self._price_source = price_source

        # 4. Calcular M&V
        result = calculate_mv(config, mv, price_fn)
        self._last_result = result

        # 5. Precalcular costes
        self._calculate_hourly_costs(result, price_fn)

        _LOGGER.debug(
            "Update: target=%s, last_hour=%d, baseline_kwh=%.3f, real_kwh=%.3f, "
            "baseline_cost=%.4f€, real_cost=%.4f€, savings=%.4f€",
            target_date, self._last_hour_processed,
            sum(v for v in result.baseline_curve.values[:self._last_hour_processed + 1] if v is not None),
            sum(v for v in result.real_curve.values[:self._last_hour_processed + 1] if v is not None),
            self._baseline_cost_total, self._real_cost_total, self._savings_today_eur,
        )

        return {
            "now": now,
            "target_date": target_date,
            "result": result,
            "price_source": price_source,
            "real_cost_source": self._real_cost_source,
            "last_hour_processed": self._last_hour_processed,
        }

    def _calculate_hourly_costs(self, result: DailyMV, price_fn) -> None:
        """Calcula los costes horarios del baseline y consolida acumulados."""
        self._baseline_hourly_eur = [None] * 24
        self._baseline_cost_total = 0.0
        self._real_cost_total = 0.0
        self._savings_today_eur = 0.0

        last_h = self._last_hour_processed
        if last_h < 0:
            return

        for h in range(last_h + 1):
            # Baseline cost: baseline_kWh × precio
            b_kwh = result.baseline_curve.at(h)
            if b_kwh is not None:
                b_eur = b_kwh * price_fn(h)
                self._baseline_hourly_eur[h] = b_eur
                self._baseline_cost_total += b_eur

            # Real cost: prioridad al sensor del panel HA Energy
            r_eur = self._real_hourly_eur[h]
            if r_eur is None:
                # Fallback: calcular como real_kWh × precio
                r_kwh = result.real_curve.at(h)
                if r_kwh is not None:
                    r_eur = r_kwh * price_fn(h)
                    self._real_hourly_eur[h] = r_eur

            if r_eur is not None:
                self._real_cost_total += r_eur

            # Savings = baseline_eur - real_eur
            if (self._baseline_hourly_eur[h] is not None and
                    self._real_hourly_eur[h] is not None):
                self._savings_today_eur += (
                    self._baseline_hourly_eur[h] - self._real_hourly_eur[h]
                )

    # ── API expuesta a los sensores ─────────────────────────────────

    @property
    def last_result(self) -> Optional[DailyMV]:
        return self._last_result

    @property
    def price_source(self) -> str:
        return self._price_source

    @property
    def real_cost_source(self) -> str:
        return self._real_cost_source

    @property
    def last_hour_processed(self) -> int:
        return self._last_hour_processed

    @property
    def baseline_cost_today(self) -> float:
        return round(self._baseline_cost_total, 4)

    @property
    def real_cost_today(self) -> float:
        return round(self._real_cost_total, 4)

    @property
    def savings_today_eur(self) -> float:
        return round(self._savings_today_eur, 4)

    @property
    def baseline_hourly_eur(self) -> list[Optional[float]]:
        return list(self._baseline_hourly_eur)

    @property
    def real_hourly_eur(self) -> list[Optional[float]]:
        return list(self._real_hourly_eur)
