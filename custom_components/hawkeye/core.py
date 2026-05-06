"""Lógica central del cálculo M&V de Hawkeye.

Función principal: calculate_mv(config, hourly_mv, price_fn) → DailyMV

Capa 1 — sin dependencias de Home Assistant.

Cálculo M&V correcto
─────────────────────
La carga base no gestionable es IDÉNTICA en baseline y real (los dos parten
de la misma medida real). Al calcular el ahorro, esa base se cancela, así que
no necesita aparecer en la fórmula del ahorro:

    ahorro_kWh[h] = Σ_assets (naive[h] - real[h])
    ahorro_eur[h] = ahorro_kWh[h] × precio[h]

Donde:
    naive[h] = comportamiento ingenuo del asset en la hora h
    real[h]  = consumo medido del asset en la hora h

Por tanto:
    Si el real == naive → ahorro 0 (nada que ganar al gestionar).
    Si el real está en horas más baratas que el naive → ahorro positivo (€).
    Si el real está en horas más caras → ahorro negativo (mala gestión real).

Invariante clave: Σ(naive) = Σ(real) por cada asset, porque el comportamiento
ingenuo redistribuye el consumo en el tiempo, no añade ni quita energía. Por
eso Σ_h ahorro_kWh = 0 — siempre. El valor está en el cambio de DISTRIBUCIÓN,
no en el cambio de TOTAL. Por eso el ahorro real es en €, no en kWh.
"""
from __future__ import annotations

from typing import Callable, Optional

try:
    from .models import (
        Appliance,
        DailyMV,
        ElectricVehicle,
        HawkeyeConfig,
        HourlyData,
        HourlyMV,
        HourQuality,
        SolarPV,
    )
except ImportError:
    from models import (  # type: ignore
        Appliance,
        DailyMV,
        ElectricVehicle,
        HawkeyeConfig,
        HourlyData,
        HourlyMV,
        HourQuality,
        SolarPV,
    )


PriceFn = Callable[[int], float]
"""Función que devuelve el precio (€/kWh) para una hora del día (0..23)."""


def constant_price(eur_per_kwh: float) -> PriceFn:
    return lambda h: eur_per_kwh


def hourly_prices(prices: list[float]) -> PriceFn:
    if len(prices) != 24:
        raise ValueError(f"prices debe tener 24 valores: {len(prices)}")
    p = list(prices)
    return lambda h: p[h]


def calculate_mv(
    config: HawkeyeConfig,
    mv: HourlyMV,
    price_fn: PriceFn = None,
) -> DailyMV:
    """Calcula el ahorro M&V de un día completo.

    Args:
        config: configuración de la vivienda (assets declarados).
        mv: medidas reales del día (consumo total + por asset).
        price_fn: función de precio por hora (€/kWh). Si None, asume 0.20 €/kWh plano.

    Returns:
        DailyMV con todos los detalles del cálculo.
    """
    if price_fn is None:
        price_fn = constant_price(0.20)

    target_date = mv.target_date
    warnings: list[str] = []
    quality: list[HourQuality] = [HourQuality() for _ in range(24)]

    # ── 1. Curvas reales de cada asset ────────────────────────────────

    appliance_reals: dict[str, HourlyData] = {}
    for app in config.appliances():
        appliance_reals[app.name] = mv.asset_consumptions.get(
            app.name, HourlyData.zeros()
        )

    ev_real: Optional[HourlyData] = None
    ev_obj: Optional[ElectricVehicle] = None
    if config.evs():
        ev_obj = config.evs()[0]
        ev_real = mv.asset_consumptions.get(ev_obj.name, HourlyData.zeros())

    solar_obj: Optional[SolarPV] = config.solar()
    solar_curve: Optional[HourlyData] = None
    if solar_obj is not None:
        solar_curve = mv.asset_consumptions.get(solar_obj.name, HourlyData.zeros())

    # ── 2. Comportamiento ingenuo de cada asset desplazable ────────────
    # La solar NO se simula con ingenuo (los paneles producen lo que produce
    # el sol; no es desplazable).

    appliance_naives: dict[str, HourlyData] = {}
    for app in config.appliances():
        appliance_naives[app.name] = app.naive_curve(target_date, appliance_reals[app.name])

    ev_naive: Optional[HourlyData] = None
    if ev_obj is not None and ev_real is not None:
        ev_naive = ev_obj.naive_curve(target_date, ev_real)

    # ── 3. Ahorro por asset desplazable y total ────────────────────────
    # ahorro[h] = naive[h] - real[h]
    # ahorro €[h] = ahorro_kWh[h] × precio[h]
    # La carga no gestionable se cancela porque es idéntica en baseline y real.

    total_savings_kwh = 0.0
    total_savings_eur = 0.0
    hourly_savings_kwh: list[float] = [0.0] * 24
    hourly_savings_eur: list[float] = [0.0] * 24

    # Aportación de cada electrodoméstico
    for name, naive in appliance_naives.items():
        real = appliance_reals[name]
        for h in range(24):
            n = naive.at(h) or 0.0
            r = real.at(h) or 0.0
            diff_kwh = n - r
            diff_eur = diff_kwh * price_fn(h)
            hourly_savings_kwh[h] += diff_kwh
            hourly_savings_eur[h] += diff_eur
            total_savings_kwh += diff_kwh
            total_savings_eur += diff_eur

    # Aportación del EV
    if ev_naive is not None and ev_real is not None:
        for h in range(24):
            n = ev_naive.at(h) or 0.0
            r = ev_real.at(h) or 0.0
            diff_kwh = n - r
            diff_eur = diff_kwh * price_fn(h)
            hourly_savings_kwh[h] += diff_kwh
            hourly_savings_eur[h] += diff_eur
            total_savings_kwh += diff_kwh
            total_savings_eur += diff_eur

    # ── 4. Curvas baseline y real (para visualización en HA Energy) ────
    # baseline[h] = no_gestionable_real[h] + Σ ingenuos[h]
    # real[h]     = total_consumption[h]   (lo que realmente importó la red)
    #
    # No usamos baseline para calcular ahorro (eso ya está hecho), pero sí
    # para que el usuario vea ambas curvas en el panel.

    baseline_values: list[Optional[float]] = []
    non_manageable_values: list[Optional[float]] = []
    for h in range(24):
        total_h = mv.total_consumption.at(h)

        if total_h is None:
            baseline_values.append(None)
            non_manageable_values.append(None)
            quality[h] = HourQuality(incomplete=True)
            continue

        # Sumar gestionables reales que CONSUMEN (la solar genera, no consume)
        gestionable_consumed = 0.0
        any_missing = False
        for name in appliance_reals:
            v = appliance_reals[name].at(h)
            if v is None:
                any_missing = True
                break
            gestionable_consumed += v

        if not any_missing and ev_real is not None:
            v = ev_real.at(h)
            if v is None:
                any_missing = True
            else:
                gestionable_consumed += v

        if any_missing:
            baseline_values.append(None)
            non_manageable_values.append(None)
            quality[h] = HourQuality(incomplete=True)
            continue

        non_manageable = total_h - gestionable_consumed

        if non_manageable < 0:
            warnings.append(
                f"Hora {h:02d}: no_gestionable_real salió {non_manageable:.3f} kWh "
                f"(consumo total {total_h:.3f} < gestionables {gestionable_consumed:.3f}). "
                f"Trunco a 0."
            )
            non_manageable = 0.0
            quality[h] = HourQuality(negative_base=True)

        non_manageable_values.append(non_manageable)

        # Baseline = no_gestionable + Σ ingenuos
        baseline_h = non_manageable
        for naive in appliance_naives.values():
            v = naive.at(h)
            if v is not None:
                baseline_h += v
        if ev_naive is not None:
            v = ev_naive.at(h)
            if v is not None:
                baseline_h += v

        baseline_values.append(baseline_h)

    return DailyMV(
        target_date=target_date,
        baseline_curve=HourlyData.from_list(baseline_values),
        real_curve=mv.total_consumption,
        non_manageable_curve=HourlyData.from_list(non_manageable_values),
        appliance_naives=appliance_naives,
        appliance_reals=appliance_reals,
        ev_naive=ev_naive,
        ev_real=ev_real,
        solar_curve=solar_curve,
        total_savings_kwh=total_savings_kwh,
        total_savings_eur=total_savings_eur,
        warnings=warnings,
        quality_per_hour=tuple(quality),
    )
