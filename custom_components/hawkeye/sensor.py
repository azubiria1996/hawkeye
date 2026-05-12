"""Sensores de Hawkeye.

Cinco sensores (savings_today_kwh eliminado por irrelevante):

  sensor.hawkeye_baseline_today        kWh acumulados del baseline hoy
  sensor.hawkeye_real_today            kWh acumulados reales hoy
  sensor.hawkeye_savings_today_eur     ahorro acumulado en €
  sensor.hawkeye_baseline_cost_today   coste baseline acumulado en €
  sensor.hawkeye_real_cost_today       coste real acumulado en €

Todos los cálculos viven en el coordinator. Aquí sólo leemos propiedades.
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
    ATTR_BASELINE_HOURLY_EUR,
    ATTR_BASELINE_HOURLY_KWH,
    ATTR_EV_NAIVE,
    ATTR_EV_REAL,
    ATTR_HOURLY_KWH,
    ATTR_LAST_HOUR_PROCESSED,
    ATTR_NON_MANAGEABLE_KWH,
    ATTR_OVERRIDES_TODAY,
    ATTR_PRICE_SOURCE,
    ATTR_REAL_COST_SOURCE,
    ATTR_REAL_HOURLY_EUR,
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
        SavingsTodayEurSensor(coordinator, entry.entry_id),
        BaselineCostTodaySensor(coordinator, entry.entry_id),
        RealCostTodaySensor(coordinator, entry.entry_id),
    ])


class _HawkeyeBase(CoordinatorEntity[HawkeyeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id, suffix):
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
        last_h = self.coordinator.last_hour_processed
        if last_h < 0:
            return 0.0
        total = sum(
            v for v in self._result.baseline_curve.values[: last_h + 1]
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
            ATTR_BASELINE_HOURLY_KWH: [
                None if v is None else round(v, 3)
                for v in self._result.baseline_curve.values
            ],
            ATTR_NON_MANAGEABLE_KWH: [
                None if v is None else round(v, 3)
                for v in self._result.non_manageable_curve.values
            ],
            ATTR_APPLIANCE_NAIVES: {
                name: [round(v, 3) if v is not None else None for v in c.values]
                for name, c in self._result.appliance_naives.items()
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
        last_h = self.coordinator.last_hour_processed
        if last_h < 0:
            return 0.0
        total = sum(
            v for v in self._result.real_curve.values[: last_h + 1]
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
            ATTR_REAL_HOURLY_KWH: [
                None if v is None else round(v, 3)
                for v in self._result.real_curve.values
            ],
            ATTR_APPLIANCE_REALS: {
                name: [round(v, 3) if v is not None else None for v in c.values]
                for name, c in self._result.appliance_reals.items()
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


# ── 3. Savings today € ─────────────────────────────────────────────────


class SavingsTodayEurSensor(_HawkeyeBase):
    """Ahorro acumulado del día en €.

    Sin device_class para evitar choque con state_class=measurement
    (HA exige device_class=monetary + state_class=total para "ahorro",
    pero el ahorro no es monetary stricto sensu — es una diferencia).
    """
    _attr_name = "Savings today"
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:piggy-bank"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "savings_today_eur")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        return self.coordinator.savings_today_eur

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        if self._result is None:
            return None
        overrides = self.coordinator._override_store.all_active()
        return {
            ATTR_TARGET_DATE: self._result.target_date.isoformat(),
            ATTR_PRICE_SOURCE: self.coordinator.price_source,
            ATTR_REAL_COST_SOURCE: self.coordinator.real_cost_source,
            ATTR_OVERRIDES_TODAY: overrides,
        }


# ── 4. Baseline cost today (€ acumulados) ─────────────────────────────


class BaselineCostTodaySensor(_HawkeyeBase):
    _attr_name = "Baseline cost today"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "baseline_cost_today")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        return self.coordinator.baseline_cost_today

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        if self._result is None:
            return None
        return {
            ATTR_TARGET_DATE: self._result.target_date.isoformat(),
            ATTR_BASELINE_HOURLY_EUR: [
                None if v is None else round(v, 4)
                for v in self.coordinator.baseline_hourly_eur
            ],
            ATTR_PRICE_SOURCE: self.coordinator.price_source,
            ATTR_LAST_HOUR_PROCESSED: self.coordinator.last_hour_processed,
        }


# ── 5. Real cost today (€ acumulados) ─────────────────────────────────


class RealCostTodaySensor(_HawkeyeBase):
    _attr_name = "Real cost today"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "real_cost_today")

    @property
    def native_value(self) -> Optional[float]:
        if self._result is None:
            return None
        return self.coordinator.real_cost_today

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        if self._result is None:
            return None
        return {
            ATTR_TARGET_DATE: self._result.target_date.isoformat(),
            ATTR_REAL_HOURLY_EUR: [
                None if v is None else round(v, 4)
                for v in self.coordinator.real_hourly_eur
            ],
            ATTR_REAL_COST_SOURCE: self.coordinator.real_cost_source,
            ATTR_LAST_HOUR_PROCESSED: self.coordinator.last_hour_processed,
        }
