"""Ejemplo: caso real del usuario — lavadora desplazada a hora barata.

Reproduce la situación: el usuario declara que normalmente lava los martes
a las 21h (hora pico), pero realmente la lavadora arrancó a las 13h
(hora valle). Hawkeye calcula cuánto ahorró por este desplazamiento.
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "custom_components", "hawkeye"))

from models import (
    Appliance,
    DayOfWeek,
    HawkeyeConfig,
    HourlyData,
    HourlyMV,
)
from core import calculate_mv, hourly_prices


def main():
    # Configuración del usuario
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY, DayOfWeek.THURSDAY),
            naive_start_hour=21,         # un usuario "tonto" lavaría al volver del trabajo
            naive_duration_hours=2,
        ),
    ])

    target = date(2026, 5, 5)  # martes

    # Realidad del día: el usuario gestionó la lavadora a las 13h
    # Consumo total medido (importado de red)
    consumo_total = HourlyData.from_list([
        0.18 + (0.6 if h in (13, 14) else 0)
        for h in range(24)
    ])

    # Sensor de la lavadora midió 1.2 kWh totales (0.6 + 0.6) a las 13-14h
    lavadora_real = HourlyData.from_list([
        0.6 if h in (13, 14) else 0.0 for h in range(24)
    ])

    mv = HourlyMV(
        target_date=target,
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )

    # Tarifa por horas (PVPC simplificada)
    prices = [0.10] * 24
    for h in (10, 11, 12, 13, 14, 15):
        prices[h] = 0.08    # valle solar
    for h in (19, 20, 21, 22):
        prices[h] = 0.32    # punta tarde-noche

    result = calculate_mv(config, mv, hourly_prices(prices))

    # ── Imprimir resultado ──
    print()
    print("=" * 76)
    print(f"  Hawkeye — Cálculo M&V para {target} (martes)")
    print("=" * 76)
    print()
    print(f"  Configuración:")
    print(f"    - Lavadora declarada para martes/jueves a las 21h, 2h ciclo")
    print()
    print(f"  Realidad del día:")
    print(f"    - Lavadora real ejecutada a las 13-14h (gestionada hacia hora barata)")
    print()
    print("  ┌──────┬──────┬──────────┬──────────┬──────────┐")
    print("  │ hora │ pre€ │ baseline │   real   │  ahorro  │")
    print("  ├──────┼──────┼──────────┼──────────┼──────────┤")

    for h in range(24):
        b = result.baseline_curve.at(h) or 0
        r = result.real_curve.at(h) or 0
        n_lav = result.appliance_naives["lavadora"].at(h) or 0
        r_lav = result.appliance_reals["lavadora"].at(h) or 0
        diff = (n_lav - r_lav) * prices[h]

        marker = ""
        if n_lav > 0:
            marker = " ← lavado ingenuo"
        if r_lav > 0:
            marker += " ← lavado real"

        print(f"  │  {h:02d}  │ {prices[h]:.2f} │  {b:.3f}   │  {r:.3f}   │"
              f"  {diff:+.4f}{marker}")

    print("  └──────┴──────┴──────────┴──────────┴──────────┘")
    print()
    print(f"  Totales:")
    print(f"    Baseline kWh:  {sum(result.baseline_curve.values):.2f}")
    print(f"    Real kWh:      {sum(result.real_curve.values):.2f}")
    print(f"    Diferencia:    {sum(result.baseline_curve.values) - sum(result.real_curve.values):.2f} kWh")
    print()
    print(f"    Ahorro kWh:    {result.total_savings_kwh:+.2f} (debe ser ≈ 0 — solo redistribuyes)")
    print(f"    Ahorro €:      {result.total_savings_eur:+.4f} €  ← VALOR REAL DE LA GESTIÓN")
    print()

    if result.warnings:
        print(f"  Avisos:")
        for w in result.warnings:
            print(f"    ⚠ {w}")
    else:
        print(f"  Sin warnings — cálculo limpio.")

    print("=" * 76)


if __name__ == "__main__":
    main()
