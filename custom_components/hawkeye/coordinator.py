"""Coordinator de Hawkeye — reparado.

CAMBIOS PRINCIPALES vs versión anterior:

Bug 1 — Costes y ahorros a 0:
    El sensor de coste del panel HA Energy (`sensor.consumption_cost_today`)
    NO es total_increasing — se RESETEA a las 00:00 de cada día. Por eso
    la lectura de deltas estaba devolviendo None o valores erróneos.
    Solución: detectar si el sensor de coste real es daily-reset o
    total-increasing. Si es daily-reset, los deltas son state[fin] - state[inicio]
    SIEMPRE que state[fin] >= state[inicio] (sin reset entre medias).
    Como las medidas son hora a hora dentro del mismo día, el delta es directo.
    También se ha añadido fallback: si no se puede leer el sensor de coste real,
    se calcula internamente como real_kWh × precio.

Bug 2 — Baseline ≠ Real en días sin uso del electrodoméstico:
    El sensor del electrodoméstico inactivo devolvía None en algunas horas
    (estado del sensor no disponible o sin cambios registrados), y la lógica
    M&V marcaba la hora como "incompleta", dejando baseline_curve[h] = None.
    El real seguía teniendo valor → diferentes curvas.
    Solución: si el sensor del electrodoméstico existe pero no tiene estados
    registrados en una hora (sin cambios), su consumo es 0.0 (no None).
    Solo es None si el sensor está completamente caído (no existe la entidad).
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
from .overrides import OverrideStore

_LOGGER = logging.getLogger(__name__)


class HawkeyeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordina las medidas, el cálculo M&V y los costes hora a hora."""

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
            update_interval=None,
        )
        self.entry = entry
        self._override_store = override_store
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
        data = self._merged_data()
        return {a[ASSET_NAME]: a[ASSET_SENSOR] for a in data.get(CONF_ASSETS, [])}

    # ── Lectura del Recorder ────────────────────────────────────────

    async def _read_hour_delta(
        self,
        sensor_id: str,
        hour_start: datetime,
        hour_end: datetime,
        treat_missing_as_zero: bool = False,
    ) -> Optional[float]:
        """Lee el delta de un sensor entre dos instantes.

        Args:
            sensor_id: entidad a leer
            hour_start, hour_end: rango de la hora
            treat_missing_as_zero: si True, una hora sin estados se trata
                como 0 (apropiado para electrodomésticos inactivos donde
                "sin cambios" = "sin consumo"). Si False, devuelve None
                (apropiado para el medidor total — si no hay datos, no
                podemos calcular nada).

        Returns:
            kWh consumidos en la hora, o None si no se puede determinar.
        """
        # Verificar primero que el sensor existe
        state_obj = self.hass.states.get(sensor_id)
        if state_obj is None:
            _LOGGER.debug("Sensor %s no existe", sensor_id)
            return None  # sensor caído → siempre None

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

            numeric = []
            for st in states:
                try:
                    v = float(st.state)
                    numeric.append(v)
                except (ValueError, TypeError):
                    continue

            if len(numeric) == 0:
                # FIX BUG 2: si no hay estados pero el sensor existe,
                # interpretamos según el contexto.
                # Para un electrodoméstico inactivo: 0 kWh consumidos.
                # Para el medidor total: dato faltante → None.
                if treat_missing_as_zero:
                    return 0.0
                return None

            if len(numeric) == 1:
                # Solo hay un estado en el rango → no podemos calcular delta
                if treat_missing_as_zero:
                    return 0.0
                return None

            delta = numeric[-1] - numeric[0]
            if delta < 0:
                # Reset detectado dentro de la hora.
                # Para sensores daily-reset (como consumption_cost_today),
                # esto NO debería pasar dentro de una misma hora salvo en
                # el cambio de día. Si pasa, tratamos como sensor caído.
                _LOGGER.debug(
                    "Sensor %s: delta negativo (reset) entre %s y %s",
                    sensor_id, hour_start, hour_end,
                )
                return None
            return delta

        except Exception as exc:
            _LOGGER.warning("Error leyendo histórico de %s: %s", sensor_id, exc)
            return None

    async def _update_hourly_consumption(self, now: datetime) -> None:
        """Lee del Recorder los deltas de cada sensor para cada hora pasada."""
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

            local_start = datetime.combine(today, time(h, 0))
            local_end = local_start + timedelta(hours=1)
            hour_start = dt_util.as_utc(dt_util.as_local(local_start))
            hour_end = dt_util.as_utc(dt_util.as_local(local_end))

            # Consumo total (kWh) — del medidor, dato crítico, no zero-fallback
            self._real_hourly_kwh[h] = await self._read_hour_delta(
                total_sensor, hour_start, hour_end, treat_missing_as_zero=False,
            )

            # Consumo por asset (kWh) — FIX BUG 2: treat_missing_as_zero=True
            # Si el sensor del electrodoméstico no reporta nada esa hora,
            # asumimos que no consumió (que es lo correcto: lavadora apagada).
            for name, sensor_id in asset_sensors.items():
                self._asset_hourly_kwh[name][h] = await self._read_hour_delta(
                    sensor_id, hour_start, hour_end, treat_missing_as_zero=True,
                )

            # Coste real (€) — del sensor del panel HA Energy
            if real_cost_sensor:
                self._real_hourly_eur[h] = await self._read_hour_delta(
                    real_cost_sensor, hour_start, hour_end,
                    treat_missing_as_zero=False,
                )
                if self._real_hourly_eur[h] is not None:
                    self._real_cost_source = f"sensor:{real_cost_sensor}"

            self._last_hour_processed = h
            _LOGGER.info(
                "Hora %02d: total=%.3f kWh, coste real=%s",
                h,
                self._real_hourly_kwh[h] or 0,
                f"{self._real_hourly_eur[h]:.4f}€" if self._real_hourly_eur[h] is not None else "n/a",
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

        # 2. Construir HawkeyeConfig + HourlyMV
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
            "Update: target=%s, last_hour=%d, baseline_cost=%.4f€, "
            "real_cost=%.4f€, savings=%.4f€",
            target_date, self._last_hour_processed,
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
        """Calcula los costes horarios del baseline y consolida acumulados.

        FIX BUG 1: lógica revisada para que los costes nunca queden en None
        cuando hay datos. Si el sensor de coste real no funciona,
        recalculamos internamente como real_kWh × precio.
        """
        # Reset acumulados
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
                # FALLBACK: calcular como real_kWh × precio
                r_kwh = result.real_curve.at(h)
                if r_kwh is not None:
                    r_eur = r_kwh * price_fn(h)
                    self._real_hourly_eur[h] = r_eur
                    if self._real_cost_source == "computed":
                        # Solo marcamos si no se había marcado como sensor
                        self._real_cost_source = "computed"

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
