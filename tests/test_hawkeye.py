"""Tests de Hawkeye.

Ejecutar: python tests/test_hawkeye.py

Tests organizados en torno a los invariantes M&V:

  1. Si NO hay gestión (real == naive) → ahorro 0.
  2. La energía total medida del gestionable es la misma en baseline y real
     (Σ naive == Σ real). El ingenuo redistribuye, no añade ni quita.
  3. La carga no gestionable es la misma en baseline y real (por construcción).
  4. Si el real está en horas más caras que el naive, el ahorro puede ser
     negativo (y eso es correcto: refleja una mala gestión real).
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "custom_components", "hawkeye"))

from models import (
    Appliance,
    DayOfWeek,
    ElectricVehicle,
    HawkeyeConfig,
    HourlyData,
    HourlyMV,
    SolarPV,
)
from core import calculate_mv, constant_price, hourly_prices


def hourly(values: dict[int, float], default: float = 0.0) -> HourlyData:
    """Crea un HourlyData a partir de un dict {hora: kwh}."""
    arr = [default] * 24
    for h, v in values.items():
        arr[h] = v
    return HourlyData.from_list(arr)


# ── Test 1: ahorro 0 si no hay gestión ─────────────────────────────────


def test_invariante_1_sin_gestion_ahorro_cero():
    """Si la lavadora arranca exactamente a la hora ingenua, el ahorro es 0
    en cualquier tarifa."""
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY,),
            naive_start_hour=17,
            naive_duration_hours=2,
        ),
    ])

    # Real == lo que el ingenuo asume
    consumo_total = HourlyData.from_list([
        0.18 if h not in (17, 18) else 0.78
        for h in range(24)
    ])
    lavadora_real = hourly({17: 0.6, 18: 0.6})

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )

    # Probamos con tarifa plana y horaria
    for price_fn, label in [
        (constant_price(0.20), "plana"),
        (hourly_prices([0.10] * 8 + [0.30] * 12 + [0.10] * 4), "horaria"),
    ]:
        result = calculate_mv(config, mv, price_fn)
        assert abs(result.total_savings_kwh) < 1e-9, \
            f"[{label}] kWh esperado 0, obtenido {result.total_savings_kwh}"
        assert abs(result.total_savings_eur) < 1e-9, \
            f"[{label}] € esperado 0, obtenido {result.total_savings_eur}"
    print("✓ test_invariante_1_sin_gestion_ahorro_cero (plana y horaria)")


# ── Test 2: Σ(naive) == Σ(real) por gestionable ────────────────────────


def test_invariante_2_naive_y_real_suman_igual():
    """El ingenuo redistribuye en el tiempo pero no añade ni quita energía."""
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY,),
            naive_start_hour=21,
            naive_duration_hours=2,
        ),
        ElectricVehicle(
            name="coche",
            naive_arrival_hour=18,
            max_power_kw=7.0,
        ),
    ])

    # Lavadora real: 1.2 kWh totales (arranca a las 13h)
    lavadora_real = hourly({13: 0.6, 14: 0.6})
    # EV real: 14 kWh (cargó de madrugada)
    coche_real = hourly({3: 7.0, 4: 7.0})

    consumo_total = HourlyData.from_list([
        0.18 + (0.6 if h in (13, 14) else 0) + (7.0 if h in (3, 4) else 0)
        for h in range(24)
    ])

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={
            "lavadora": lavadora_real,
            "coche": coche_real,
        },
    )
    result = calculate_mv(config, mv)

    # Σ naive == Σ real para cada asset
    sum_lav_real = result.appliance_reals["lavadora"].total()
    sum_lav_naive = result.appliance_naives["lavadora"].total()
    assert abs(sum_lav_real - sum_lav_naive) < 1e-9, \
        f"Lavadora: real {sum_lav_real} != naive {sum_lav_naive}"

    sum_ev_real = result.ev_real.total()
    sum_ev_naive = result.ev_naive.total()
    assert abs(sum_ev_real - sum_ev_naive) < 1e-9, \
        f"EV: real {sum_ev_real} != naive {sum_ev_naive}"

    print(f"✓ test_invariante_2_naive_y_real_suman_igual "
          f"(lavadora: {sum_lav_real:.2f} kWh, EV: {sum_ev_real:.2f} kWh)")


# ── Test 3: carga no gestionable idéntica en ambas curvas ──────────────


def test_invariante_3_no_gestionable_igual_en_ambos():
    """La curva no_gestionable_real es idéntica en baseline y real
    (por construcción del cálculo).

    Comprobamos que:
      baseline[h] = no_gestionable[h] + Σ ingenuos[h]
      real[h]     = no_gestionable[h] + Σ reales[h]    (con la misma base)
    """
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY,),
            naive_start_hour=21,
            naive_duration_hours=2,
        ),
    ])

    consumo_total = HourlyData.from_list([
        0.18 + (0.6 if h in (13, 14) else 0)
        for h in range(24)
    ])
    lavadora_real = hourly({13: 0.6, 14: 0.6})

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )
    result = calculate_mv(config, mv)

    # Reconstruir la "curva real" desde la base + reales: debería dar el total
    for h in range(24):
        nm = result.non_manageable_curve.at(h)
        real_lav = result.appliance_reals["lavadora"].at(h)
        total_h = result.real_curve.at(h)
        reconstruido = nm + real_lav
        assert abs(reconstruido - total_h) < 1e-9, \
            f"Hora {h}: reconstruido {reconstruido} != real {total_h}"

    # La base es la misma en baseline y real (por construcción)
    # baseline[h] - Σ naive[h] = real[h] - Σ real[h]  → ambos = no_gestionable[h]
    for h in range(24):
        nm = result.non_manageable_curve.at(h)
        baseline_h = result.baseline_curve.at(h)
        real_h = result.real_curve.at(h)
        naive_lav = result.appliance_naives["lavadora"].at(h) or 0.0
        real_lav = result.appliance_reals["lavadora"].at(h) or 0.0

        base_desde_baseline = baseline_h - naive_lav
        base_desde_real = real_h - real_lav
        assert abs(base_desde_baseline - base_desde_real) < 1e-9, \
            f"Hora {h}: base distinta — desde baseline {base_desde_baseline}, " \
            f"desde real {base_desde_real}"
        assert abs(base_desde_baseline - nm) < 1e-9

    print("✓ test_invariante_3_no_gestionable_igual_en_ambos")


# ── Test 4: ahorro no negativo si gestión razonable ────────────────────


def test_invariante_4_desplazar_a_horas_baratas_da_ahorro_positivo():
    """Caso del usuario: lavadora declarada a las 21h (pico),
    gestionada realmente a las 13h (valle). Ahorro debe ser > 0."""
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY,),
            naive_start_hour=21,        # ingenuo: hora pico
            naive_duration_hours=2,
        ),
    ])

    # Real: lavadora a las 13-14h (valle)
    consumo_total = HourlyData.from_list([
        0.18 + (0.6 if h in (13, 14) else 0)
        for h in range(24)
    ])
    lavadora_real = hourly({13: 0.6, 14: 0.6})

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )

    # Tarifa: valle 0.10, pico 0.30
    prices = [0.10] * 24
    for h in (20, 21, 22):
        prices[h] = 0.30

    result = calculate_mv(config, mv, hourly_prices(prices))

    # Ahorro esperado: ingenuo a 0.30 €, real a 0.10 € → 1.2 × (0.30 - 0.10) = 0.24 €
    expected = 1.2 * 0.20  # 0.24
    assert abs(result.total_savings_eur - expected) < 1e-3, \
        f"Esperado {expected}, obtenido {result.total_savings_eur}"
    assert result.total_savings_eur > 0
    print(f"✓ test_invariante_4_desplazar_a_horas_baratas_da_ahorro_positivo "
          f"(ahorro {result.total_savings_eur:.4f} €)")


# ── Test 5: ahorro negativo SI el real es peor que el naive ───────────


def test_ahorro_negativo_si_gestion_es_peor_que_ingenuo():
    """Si el usuario lava a las 21h (pico) cuando el ingenuo lo programa a las
    13h (valle), el ahorro es negativo. Esto NO es un bug, es una métrica
    correcta de mala gestión real."""
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY,),
            naive_start_hour=13,        # ingenuo: pone ya en valle
            naive_duration_hours=2,
        ),
    ])

    # Real: lavadora a las 21h (pico)
    consumo_total = HourlyData.from_list([
        0.18 + (0.6 if h in (21, 22) else 0)
        for h in range(24)
    ])
    lavadora_real = hourly({21: 0.6, 22: 0.6})

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )

    prices = [0.10] * 24
    for h in (20, 21, 22):
        prices[h] = 0.30

    result = calculate_mv(config, mv, hourly_prices(prices))

    # En este caso el real costó más que el ingenuo → ahorro < 0
    assert result.total_savings_eur < 0, \
        f"Esperaba ahorro < 0 (mala gestión), obtenido {result.total_savings_eur}"
    print(f"✓ test_ahorro_negativo_si_gestion_es_peor_que_ingenuo "
          f"(ahorro {result.total_savings_eur:.4f} € — mala gestión real)")


# ── Test 6: caso completo del usuario ──────────────────────────────────


def test_caso_real_usuario():
    """Reproduce el caso real del usuario:
       - Lavadora declarada los martes a las 21h
       - Realmente lavada a las 13-14h
       - Tarifa simple
       - Resultado: ahorro positivo, sin valores negativos en el desglose
    """
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY, DayOfWeek.THURSDAY),
            naive_start_hour=21,
            naive_duration_hours=2,
        ),
    ])

    consumo_total = HourlyData.from_list([
        0.18 + (0.6 if h in (13, 14) else 0)
        for h in range(24)
    ])
    lavadora_real = hourly({13: 0.6, 14: 0.6})

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )

    prices = [0.10] * 24
    prices[10] = prices[11] = prices[12] = prices[13] = prices[14] = prices[15] = 0.08
    prices[19] = prices[20] = prices[21] = prices[22] = 0.32

    result = calculate_mv(config, mv, hourly_prices(prices))

    # Ahorro positivo
    assert result.total_savings_eur > 0
    # No hay warnings (no_gestionable bien calculado)
    assert not result.warnings
    print(f"✓ test_caso_real_usuario "
          f"(ahorro {result.total_savings_eur:.4f} €, sin warnings)")


# ── Otros tests defensivos ─────────────────────────────────────────────


def test_appliance_no_usado_hoy_ahorro_cero():
    """Si la lavadora no se usó hoy, el ingenuo también es 0 → ahorro = 0."""
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY,),
            naive_start_hour=17,
            naive_duration_hours=2,
        ),
    ])

    consumo_total = HourlyData.from_list([0.18] * 24)
    lavadora_real = HourlyData.zeros()

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )
    result = calculate_mv(config, mv)
    assert abs(result.total_savings_kwh) < 1e-9
    assert abs(result.total_savings_eur) < 1e-9
    print("✓ test_appliance_no_usado_hoy_ahorro_cero")


def test_dia_no_aplica_ahorro_cero():
    """Si el día no es de los declarados (aunque la lavadora real haya
    consumido, cosa que sería atípica), el ingenuo es 0 y el ahorro queda
    como una pérdida (porque consumió sin estar previsto)."""
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.MONDAY,),  # solo lunes
            naive_start_hour=17,
            naive_duration_hours=2,
        ),
    ])

    consumo_total = HourlyData.from_list([
        0.18 + (0.6 if h in (13, 14) else 0)
        for h in range(24)
    ])
    lavadora_real = hourly({13: 0.6, 14: 0.6})

    mv = HourlyMV(
        target_date=date(2026, 5, 5),  # martes
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )
    result = calculate_mv(config, mv, constant_price(0.20))

    # naive = 0 todo el día, real = 1.2 kWh. Ahorro kWh = 0 - 1.2 = -1.2 kWh
    # Esto refleja: "lavaste un día atípico, el ingenuo no contaba con eso"
    assert result.appliance_naives["lavadora"].total() == 0
    assert result.total_savings_kwh < 0
    print(f"✓ test_dia_no_aplica_ahorro_cero "
          f"(naive=0, real=1.2 → ahorro kWh negativo: {result.total_savings_kwh:.2f})")


def test_no_gestionable_negativo_se_trunca():
    """Si la suma de gestionables supera el consumo total, el no_gest se
    trunca a 0 y se reporta warning. Comprobado solo el sensor anómalo."""
    config = HawkeyeConfig(assets=[
        Appliance(
            name="lavadora",
            days_of_week=(DayOfWeek.TUESDAY,),
            naive_start_hour=17,
            naive_duration_hours=2,
        ),
    ])

    consumo_total = HourlyData.from_list([0.5 if h == 13 else 0.18 for h in range(24)])
    lavadora_real = hourly({13: 0.8})  # más que el total

    mv = HourlyMV(
        target_date=date(2026, 5, 5),
        total_consumption=consumo_total,
        asset_consumptions={"lavadora": lavadora_real},
    )
    result = calculate_mv(config, mv)
    assert any("no_gestionable_real salió" in w for w in result.warnings)
    assert result.non_manageable_curve.at(13) == 0.0
    print(f"✓ test_no_gestionable_negativo_se_trunca")


# ── Run ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("\nRunning Hawkeye tests...\n")

    print("▸ Invariantes M&V:")
    test_invariante_1_sin_gestion_ahorro_cero()
    test_invariante_2_naive_y_real_suman_igual()
    test_invariante_3_no_gestionable_igual_en_ambos()
    test_invariante_4_desplazar_a_horas_baratas_da_ahorro_positivo()

    print("\n▸ Casos especiales:")
    test_ahorro_negativo_si_gestion_es_peor_que_ingenuo()
    test_caso_real_usuario()
    test_appliance_no_usado_hoy_ahorro_cero()
    test_dia_no_aplica_ahorro_cero()
    test_no_gestionable_negativo_se_trunca()

    print("\n✅ All tests passed.\n")
