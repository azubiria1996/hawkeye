"""Modelos de datos de Hawkeye.

Capa 1 — sin dependencias de Home Assistant.
Granularidad horaria — todas las magnitudes son kWh por hora.

Tipos clave:
  - DayOfWeek: enum 0=lunes ... 6=domingo
  - HourlyData: 24 valores en kWh, uno por hora del día
  - Asset (clase abstracta): cualquier equipo gestionable
  - Appliance: electrodoméstico (lavadora, lavavajillas...)
  - SolarPV: instalación fotovoltaica
  - ElectricVehicle: vehículo eléctrico
  - HawkeyeConfig: configuración completa de la vivienda
  - HourlyMV: input de medidas por hora (consumo total + por gestionable)
  - DailyMV: resultado del cálculo M&V para un día
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum
from typing import Optional


class DayOfWeek(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


# ── Datos de medida ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class HourlyData:
    """24 valores en kWh, uno por hora del día (0..23).

    Si una hora no se ha medido aún (futuro o sensor caído), su valor es None.
    """
    values: tuple[Optional[float], ...]

    def __post_init__(self):
        if len(self.values) != 24:
            raise ValueError(f"HourlyData debe tener 24 valores: {len(self.values)}")

    def at(self, hour: int) -> Optional[float]:
        if not (0 <= hour < 24):
            raise ValueError(f"hour debe estar en [0, 24): {hour}")
        return self.values[hour]

    def total(self) -> float:
        """Suma de todas las horas medidas (ignora las None)."""
        return sum(v for v in self.values if v is not None)

    @classmethod
    def zeros(cls) -> "HourlyData":
        return cls(values=tuple([0.0] * 24))

    @classmethod
    def empty(cls) -> "HourlyData":
        """Todas las horas a None — nada medido aún."""
        return cls(values=tuple([None] * 24))

    @classmethod
    def from_list(cls, values: list[Optional[float]]) -> "HourlyData":
        return cls(values=tuple(values))


# ── Assets (equipos gestionables) ───────────────────────────────────────


@dataclass(frozen=True)
class Asset(ABC):
    """Clase base para cualquier equipo gestionable.

    Cada Asset sabe:
      - Su consumo INGENUO en una hora (lo que un usuario sin gestión haría).
      - Su consumo REAL en una hora (lo que ha medido el sensor).

    El consumo real se proporciona desde fuera (lo lee el coordinator de los
    sensores HA). El consumo ingenuo lo calcula el propio Asset según sus
    parámetros declarados.
    """
    name: str

    def __post_init__(self):
        if not self.name:
            raise ValueError("name no puede estar vacío")

    @abstractmethod
    def naive_curve(
        self,
        target_date: date,
        real_curve: HourlyData,
    ) -> HourlyData:
        """Devuelve la curva 24h del comportamiento INGENUO de este asset
        para el día indicado.

        El parámetro real_curve es la curva real del asset ese día — algunos
        assets (EV, electrodomésticos) calibran su comportamiento ingenuo en
        función de la energía total que se consumió realmente, para que
        baseline y real sumen lo mismo y la comparación sea de DESPLAZAMIENTO,
        no de magnitud.
        """
        ...


@dataclass(frozen=True)
class Appliance(Asset):
    """Electrodoméstico desplazable (lavadora, lavavajillas, secadora...).

    Comportamiento ingenuo: el día que aplica (días típicos), el ciclo
    arranca a la hora típica declarada y consume la misma energía total
    que se midió en realidad, distribuida uniformemente entre las horas
    declaradas de duración.

    Si la energía real es 0 (no se usó), la curva ingenua también es 0.
    """
    days_of_week: tuple[DayOfWeek, ...]
    naive_start_hour: int           # 0..23 — hora típica de inicio
    naive_duration_hours: int       # duración del ciclo (h)

    def __post_init__(self):
        super().__post_init__()
        if not self.days_of_week:
            raise ValueError("days_of_week no puede estar vacío")
        if not (0 <= self.naive_start_hour < 24):
            raise ValueError(f"naive_start_hour fuera de rango: {self.naive_start_hour}")
        if self.naive_duration_hours <= 0:
            raise ValueError(f"naive_duration_hours debe ser > 0: {self.naive_duration_hours}")

    def runs_on(self, d: date) -> bool:
        return DayOfWeek(d.weekday()) in self.days_of_week

    def naive_curve(
        self,
        target_date: date,
        real_curve: HourlyData,
    ) -> HourlyData:
        # Energía total real del día (lo que se consumió de verdad)
        total_real = real_curve.total()

        # Si no se usó hoy o no es día típico → curva ingenua de ceros
        if total_real == 0 or not self.runs_on(target_date):
            return HourlyData.zeros()

        # Distribuir total_real uniformemente entre las horas del ciclo ingenuo
        kwh_per_hour = total_real / self.naive_duration_hours
        values: list[Optional[float]] = [0.0] * 24
        for k in range(self.naive_duration_hours):
            idx = self.naive_start_hour + k
            if 0 <= idx < 24:
                values[idx] = kwh_per_hour
            # Si el ciclo desborda fuera del día, esa parte se pierde
            # (es coherente: si el real estuvo dentro del día y el ingenuo
            #  se pasa, simulamos que el usuario "tonto" lo planificó mal)
        return HourlyData.from_list(values)


@dataclass(frozen=True)
class ElectricVehicle(Asset):
    """Vehículo eléctrico.

    Comportamiento ingenuo: en cuanto el coche llega (hora típica),
    empieza a cargar a potencia máxima hasta consumir la misma energía
    total que se midió en realidad.

    Si la energía real es 0, no hubo carga ese día.
    """
    naive_arrival_hour: int     # 0..23 — hora típica a la que llega
    max_power_kw: float         # kW — potencia máxima del cargador

    def __post_init__(self):
        super().__post_init__()
        if not (0 <= self.naive_arrival_hour < 24):
            raise ValueError(f"naive_arrival_hour fuera de rango: {self.naive_arrival_hour}")
        if self.max_power_kw <= 0:
            raise ValueError(f"max_power_kw debe ser > 0: {self.max_power_kw}")

    def naive_curve(
        self,
        target_date: date,
        real_curve: HourlyData,
    ) -> HourlyData:
        total_real = real_curve.total()
        if total_real == 0:
            return HourlyData.zeros()

        # Cargar a potencia máxima hasta consumir total_real kWh
        # (con resolución horaria, la potencia se traduce en kWh/h iguales)
        full_hours = int(total_real // self.max_power_kw)
        remainder = total_real - full_hours * self.max_power_kw

        values: list[Optional[float]] = [0.0] * 24
        for k in range(full_hours):
            idx = self.naive_arrival_hour + k
            if 0 <= idx < 24:
                values[idx] = self.max_power_kw
        if remainder > 0:
            idx = self.naive_arrival_hour + full_hours
            if 0 <= idx < 24:
                values[idx] = remainder

        return HourlyData.from_list(values)


@dataclass(frozen=True)
class SolarPV(Asset):
    """Instalación fotovoltaica.

    Conceptualmente distinto a los demás assets: la solar PRODUCE en lugar
    de consumir. Pero desde el punto de vista del baseline, es lo que
    "ahorra de la red" (autoconsumo).

    Comportamiento ingenuo (autoconsumo simple): la solar cubre lo que
    puede del consumo neto cada hora; lo que sobra se exporta sin valor;
    lo que falta se compra a la red.

    A efectos de M&V, lo que aporta la solar al baseline es la energía
    que habría auto-consumido si los demás equipos hubieran operado de
    forma ingenua. Hawkeye no calcula esto en SolarPV directamente — lo
    calcula a nivel de la curva total en core.calculate_mv (porque depende
    de la suma de todos los gestionables).

    Por convención, el naive_curve devuelve la GENERACIÓN HORARIA. La
    lógica de cuánto se autoconsume vs exporta vive en el cálculo final.
    """

    def naive_curve(
        self,
        target_date: date,
        real_curve: HourlyData,
    ) -> HourlyData:
        # En la solar, el "ingenuo" es exactamente lo generado.
        # No hay diferencia entre generación ingenua y real:
        # los paneles producen lo que les da el sol, sin gestión posible.
        return real_curve


# ── Configuración completa ──────────────────────────────────────────────


@dataclass
class HawkeyeConfig:
    """Configuración de la vivienda y sus assets."""
    assets: list[Asset]

    def __post_init__(self):
        names = [a.name for a in self.assets]
        if len(set(names)) != len(names):
            raise ValueError(f"Nombres de assets duplicados: {names}")

    def appliances(self) -> list[Appliance]:
        return [a for a in self.assets if isinstance(a, Appliance)]

    def evs(self) -> list[ElectricVehicle]:
        return [a for a in self.assets if isinstance(a, ElectricVehicle)]

    def solar(self) -> Optional[SolarPV]:
        solars = [a for a in self.assets if isinstance(a, SolarPV)]
        return solars[0] if solars else None


# ── Inputs y outputs del cálculo ────────────────────────────────────────


@dataclass(frozen=True)
class HourlyMV:
    """Inputs medidos para un día completo.

    Todos los valores son curvas de 24h en kWh.

    Attributes:
        target_date: día al que pertenecen las medidas.
        total_consumption: consumo total real de la red (medidor).
        asset_consumptions: por nombre de asset, su consumo medido. Para
            la solar es la GENERACIÓN, no el consumo.
    """
    target_date: date
    total_consumption: HourlyData
    asset_consumptions: dict[str, HourlyData]


@dataclass(frozen=True)
class HourQuality:
    """Marcadores de calidad de una hora del cálculo."""
    incomplete: bool = False     # alguna medida ausente
    negative_base: bool = False  # no_gestionable_real salió < 0
    sensor_error: bool = False   # algún sensor reportó error


@dataclass(frozen=True)
class DailyMV:
    """Resultado del cálculo M&V para un día completo.

    Attributes:
        target_date: día calculado.
        baseline_curve: kWh horarios del baseline (lo que habrías gastado).
        real_curve: kWh horarios realmente consumidos.
        non_manageable_curve: base no gestionable real, igual en baseline y real.
        appliance_savings: ahorro de cada electrodoméstico en kWh y €.
        ev_savings: ahorro del EV.
        solar_savings: ahorro/aporte de la solar.
        total_savings_kwh: ahorro total en kWh del día.
        total_savings_eur: ahorro total en €.
        warnings: avisos del cálculo.
        quality_per_hour: estado de cada una de las 24 horas.
    """
    target_date: date
    baseline_curve: HourlyData
    real_curve: HourlyData
    non_manageable_curve: HourlyData
    appliance_naives: dict[str, HourlyData]   # ingenuo de cada electrodoméstico
    appliance_reals: dict[str, HourlyData]    # real de cada electrodoméstico
    ev_naive: Optional[HourlyData]
    ev_real: Optional[HourlyData]
    solar_curve: Optional[HourlyData]         # generación medida (igual ingenua=real)
    total_savings_kwh: float
    total_savings_eur: float
    warnings: list[str] = field(default_factory=list)
    quality_per_hour: tuple[HourQuality, ...] = field(
        default_factory=lambda: tuple(HourQuality() for _ in range(24))
    )
