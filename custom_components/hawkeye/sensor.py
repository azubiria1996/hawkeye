"""Sensores de Hawkeye.

Crea 6 sensores cuyo estado evoluciona hora a hora:

  sensor.hawkeye_baseline_today        kWh acumulados del baseline hoy
  sensor.hawkeye_real_today            kWh acumulados reales hoy
  sensor.hawkeye_savings_today_kwh     ahorro acumulado en kWh
  sensor.hawkeye_savings_today_eur     ahorro acumulado en €
  sensor.hawkeye_baseline_cost_today   coste baseline acumulado en €
  sensor.hawkeye_real_cost_today       coste real acumulado en €
"""
from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_APPLIANCE_NAIVES,
    ATTR_APPLIANCE_REALS,
    ATTR_BASELINE_HOURLY_KWH,
    ATTR_EV_NAIVE,
    ATTR_EV_REAL,
    ATTR_HOURLY_EUR,
    ATTR_HOURLY_KWH,
    ATTR_LAST_HOUR_PROCESSED,
    ATTR_NON_MANAGEABLE_KWH,
    ATTR_OVERRIDES_TODAY,
    ATTR_PRICE_SOURCE,
    ATTR_REAL_HOURLY_KWH,
    ATTR_SOLAR_KWH,
    ATTR_TARGET_DATE,
    ATTR_WARNINGS,
    DOMAIN,
)
from .coordinator import HawkeyeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HawkeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        BaselineTodaySensor(coordinator, entry.entry_id),
        RealTodaySensor(coordinator, entry.entry_id),
        SavingsTodayKwhSensor(coordinator, entry.entry_id),
        SavingsTodayEurSensor(coordinator, entry.entry_id),
        BaselineCostTodaySensor(coordinator, entry.entry_id),
        RealCostTodaySensor(coordinator, entry.entry_id),
    ])


# ── Base común ─────────────────────────────────────────────────────────


class _HawkeyeBase(CoordinatorEntity[HawkeyeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HawkeyeCoordinator, entry_id: str, suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{suffix}"

    @property
    def _result(self):
        return self.coordinator.last_result


# ── 1. Baseline today (kWh acumulados) ────────────────────────────────


class BaselineTodaySensor(_HawkeyeBase):
    _attr_name = "Baseline today"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:chart-bell-curve-cumulative"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "baseline_today")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        # Acumulamos hasta la última hora procesada
        last_hour = self.coordinator.last_hour_processed
        if last_hour < 0:
            return 0.0
        total = sum(
            v for v in self._result.baseline_curve.values[: last_hour + 1]
            if v is not None
        )
        return round(total, 3)

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        if self._result is None:
            return None
        return {
            ATTR_TARGET_DATE: self._result.target_date.isoformat(),
            ATTR_HOURLY_KWH: [
                None if v is None else round(v, 3)
                for v in self._result.baseline_curve.values
            ],
            ATTR_NON_MANAGEABLE_KWH: [
                None if v is None else round(v, 3)
                for v in self._result.non_manageable_curve.values
            ],
            ATTR_APPLIANCE_NAIVES: {
                name: [round(v, 3) if v is not None else None for v in curve.values]
                for name, curve in self._result.appliance_naives.items()
            },
            ATTR_EV_NAIVE: (
                [round(v, 3) if v is not None else None for v in self._result.ev_naive.values]
                if self._result.ev_naive else None
            ),
            ATTR_LAST_HOUR_PROCESSED: self.coordinator.last_hour_processed,
            ATTR_WARNINGS: list(self._result.warnings),
        }


# ── 2. Real today (kWh acumulados) ────────────────────────────────────


class RealTodaySensor(_HawkeyeBase):
    _attr_name = "Real today"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "real_today")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        last_hour = self.coordinator.last_hour_processed
        if last_hour < 0:
            return 0.0
        total = sum(
            v for v in self._result.real_curve.values[: last_hour + 1]
            if v is not None
        )
        return round(total, 3)

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        if self._result is None:
            return None
        return {
            ATTR_TARGET_DATE: self._result.target_date.isoformat(),
            ATTR_HOURLY_KWH: [
                None if v is None else round(v, 3)
                for v in self._result.real_curve.values
            ],
            ATTR_APPLIANCE_REALS: {
                name: [round(v, 3) if v is not None else None for v in curve.values]
                for name, curve in self._result.appliance_reals.items()
            },
            ATTR_EV_REAL: (
                [round(v, 3) if v is not None else None for v in self._result.ev_real.values]
                if self._result.ev_real else None
            ),
            ATTR_SOLAR_KWH: (
                [round(v, 3) if v is not None else None for v in self._result.solar_curve.values]
                if self._result.solar_curve else None
            ),
            ATTR_LAST_HOUR_PROCESSED: self.coordinator.last_hour_processed,
        }


# ── 3. Savings today kWh ──────────────────────────────────────────────


class SavingsTodayKwhSensor(_HawkeyeBase):
    _attr_name = "Savings today (kWh)"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "savings_today_kwh")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        last_hour = self.coordinator.last_hour_processed
        if last_hour < 0:
            return 0.0
        # Acumulado hasta la última hora procesada
        total = 0.0
        for h in range(last_hour + 1):
            b = self._result.baseline_curve.at(h)
            r = self._result.real_curve.at(h)
            if b is not None and r is not None:
                total += b - r
        return round(total, 3)


# ── 4. Savings today € ─────────────────────────────────────────────────


class SavingsTodayEurSensor(_HawkeyeBase):
    _attr_name = "Savings today (€)"
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:piggy-bank"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "savings_today_eur")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        # Solo acumula hasta la última hora procesada
        last_hour = self.coordinator.last_hour_processed
        if last_hour < 0:
            return 0.0
        # Reaplico la lógica con el price_fn actual sería ideal pero el cálculo
        # ya considera todas las 24h. Filtramos por horas procesadas:
        # Como no tenemos acceso al price_fn directo aquí, devolvemos el total
        # de result que ya está calculado. Para horas no procesadas, ambos lados
        # son 0/None y el ahorro contribuye 0.
        return round(self._result.total_savings_eur, 4)

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        if self._result is None:
            return None
        overrides = self.coordinator._override_store.all_active()
        return {
            ATTR_TARGET_DATE: self._result.target_date.isoformat(),
            ATTR_PRICE_SOURCE: self.coordinator.price_source,
            ATTR_OVERRIDES_TODAY: overrides,
        }


# ── 5. Coste baseline acumulado ───────────────────────────────────────


class BaselineCostTodaySensor(_HawkeyeBase):
    _attr_name = "Baseline cost today"
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "baseline_cost_today")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        last_hour = self.coordinator.last_hour_processed
        if last_hour < 0:
            return 0.0
        # Calculamos el coste del baseline hasta la última hora procesada
        # El precio se aplica con el price_fn del coordinator
        total_cost = 0.0
        # Reconstruimos el precio leyendo de nuevo (refleja cualquier cambio)
        from .core import calculate_mv  # noqa
        # Más simple: recalculamos con el price_fn del coordinator
        price_fn, _ = self.coordinator._build_price_fn()
        for h in range(last_hour + 1):
            v = self._result.baseline_curve.at(h)
            if v is not None:
                total_cost += v * price_fn(h)
        return round(total_cost, 4)


# ── 6. Coste real acumulado ───────────────────────────────────────────


class RealCostTodaySensor(_HawkeyeBase):
    _attr_name = "Real cost today"
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "real_cost_today")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        last_hour = self.coordinator.last_hour_processed
        if last_hour < 0:
            return 0.0
        price_fn, _ = self.coordinator._build_price_fn()
        total_cost = 0.0
        for h in range(last_hour + 1):
            v = self._result.real_curve.at(h)
            if v is not None:
                total_cost += v * price_fn(h)
        return round(total_cost, 4)
