# 🎯 Hawkeye — Medidor de ahorro energético para Home Assistant

![](https://img.shields.io/badge/version-0.1.0-blue)
![](https://img.shields.io/badge/HA-2024.1%2B-green)
![](https://img.shields.io/badge/license-MIT-lightgrey)
![](https://img.shields.io/badge/HACS-custom-orange)

> Mide con visión precisa cuánto te ahorras de verdad gestionando la energía de tu hogar. Hawkeye es el ojo afilado que ve **exactamente** cuánto te ha aportado mover la lavadora a la hora barata, cargar el coche por la noche, o aprovechar el sol para tus electrodomésticos.

---

## 🌟 ¿Qué hace Hawkeye?

Hawkeye implementa el método **Measurement & Verification (M&V)** del estándar IPMVP, el mismo que usan auditores energéticos profesionales para certificar ahorros en industria.

A diferencia de calculadoras que **inventan** una curva basándose en lo que tú declaras, Hawkeye **mide la realidad** y compara:

- **Lo que ha pasado** (consumo real, medido de tus sensores)
- **Lo que habría pasado** (consumo ingenuo, sin gestionar)

La diferencia entre ambos es **tu ahorro real**. Sin sesgos. Sin estimaciones especulativas. Sin sorpresas.

* 📊 **Hora a hora** — Ves la evolución del ahorro en tiempo real, igual que el panel HA Energy
* 🎯 **Sin estimaciones falsas** — Si no tiene sensor para medirlo, no se inventa
* ⏰ **Foto definitiva a las 00:05** — El ahorro del día anterior, consolidado
* 🔌 **Compatible con tu sensor de precios** — Power Pricing, Nordpool, PVPC, lo que ya tengas
* 🎛️ **Patrón flexible** — Define tu rutina típica y modifica días concretos desde el dashboard
* 🛡️ **Resiliente a fallos de sensor** — Datos incompletos no rompen el cálculo

---

## 🎯 Equipos soportados (versión actual)

| Equipo | Comportamiento ingenuo |
|---|---|
| 🧺 **Electrodomésticos** | Arrancan a la hora típica declarada los días típicos. |
| 🚗 **Vehículo eléctrico** | Carga inmediata al llegar, a potencia máxima. |
| ☀️ **Solar fotovoltaica** | Generación tal cual, sin desplazamiento posible. |

🚧 **Próximas versiones**: BESS (batería), HVAC (climatización), ACS (termo).

---

## 📊 Sensores creados

| Entity ID | Descripción |
|---|---|
| `sensor.hawkeye_baseline_today` | kWh del baseline acumulados hoy |
| `sensor.hawkeye_real_today` | kWh reales acumulados hoy |
| `sensor.hawkeye_savings_today_kwh` | Ahorro acumulado del día en kWh |
| `sensor.hawkeye_savings_today_eur` | Ahorro acumulado del día en € |
| `sensor.hawkeye_baseline_cost_today` | Coste baseline acumulado del día (€) |
| `sensor.hawkeye_real_cost_today` | Coste real acumulado del día (€) |

Cada sensor expone como atributos la **curva 24h** y el **detalle por equipo**, listos para visualizar en cualquier card de HA.

---

## 💡 Ejemplos de automatización

**Notificar el ahorro del día cada noche:**

```yaml
trigger:
  - platform: time
    at: "00:10:00"
action:
  - service: notify.mobile_app_tu_telefono
    data:
      message: >
        🎯 Ayer ahorraste {{ states('sensor.hawkeye_savings_today_eur') }} €
        gestionando tu energía.
```

**Avisar si ahorraste más de 1€ en un día:**

```yaml
trigger:
  - platform: numeric_state
    entity_id: sensor.hawkeye_savings_today_eur
    above: 1.0
action:
  - service: persistent_notification.create
    data:
      title: 🎉 Buen ahorro hoy
      message: >
        Llevas {{ states('sensor.hawkeye_savings_today_eur') }} € ahorrados.
```

**Alertar si la gestión va mal (ahorro negativo):**

```yaml
trigger:
  - platform: numeric_state
    entity_id: sensor.hawkeye_savings_today_eur
    below: -0.5
action:
  - service: notify.mobile_app_tu_telefono
    data:
      message: >
        ⚠ Hoy llevas {{ states('sensor.hawkeye_savings_today_eur') }} €
        de mala gestión. Revisa los hábitos de hoy.
```

---

## 🚀 Instalación

### Vía HACS (recomendado)

1. HACS → Integraciones → ⋮ → Repositorios personalizados
2. Añade `https://github.com/azubiria1996/hawkeye` y selecciona categoría **Integración**
3. Instala **Hawkeye**
4. Reinicia Home Assistant

Para la **card del dashboard**:

5. HACS → Frontend → ⋮ → Repositorios personalizados
6. Misma URL, categoría **Lovelace**
7. Instala **Hawkeye Card**

### Manual

1. Descarga la última release desde GitHub
2. Copia la carpeta `custom_components/hawkeye/` a tu `<config>/custom_components/`
3. Reinicia Home Assistant
4. Para la card: copia `lovelace/hawkeye-card.js` a `<config>/www/` y añade el recurso en **Ajustes → Dashboards → Recursos**:

```
/local/hawkeye-card.js  →  JavaScript Module
```

---

## ⚙️ Configuración

Ve a **Ajustes → Dispositivos y servicios → Añadir integración** y busca **Hawkeye**.

### Paso 1 — Sensores principales

* **Sensor de consumo total** — entidad de "Energía consumida" del panel HA Energy.
* **Sensor de precios** — opcional. Si tienes Power Pricing, Nordpool o PVPC, selecciónalo aquí.

### Paso 2 — Asset por asset

Para cada electrodoméstico/EV/solar que quieras incluir, el wizard te pregunta:

* **Tipo** (electrodoméstico / vehículo eléctrico / solar)
* **Sensor de consumo individual** (el smart plug, el cargador, el inversor)
* **Comportamiento ingenuo**:
  * Para electrodomésticos: días típicos + hora típica de inicio + duración del ciclo
  * Para EV: hora típica de llegada + potencia máxima del cargador
  * Para solar: solo el sensor de generación

> Después de cada asset puedes **añadir otro o terminar**.

### Modificar el patrón día a día

Desde la **card de Hawkeye en tu dashboard** puedes pulsar sobre cualquier asset y cambiar su comportamiento ingenuo **solo para mañana** sin tocar la rutina por defecto. Útil cuando rompes la rutina (ej. "mañana lavo a las 23h porque vienen visitas").

---

## 📘 Cómo se calcula el ahorro

La metodología completa está documentada en [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md). En resumen:

```
Ahorro €/hora = (consumo_ingenuo - consumo_real) × precio €/kWh
```

Para cada gestionable, hora a hora. La carga base no gestionable se cancela porque es idéntica en ambos escenarios (es la misma medida real). Resultado: el ahorro mide **exactamente** el efecto de mover cargas en el tiempo, sin sesgo por días atípicos.

> **Lectura recomendada antes de configurar la app**: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md). Está pensado para usuarios no técnicos.

---

## 🔧 Solución de problemas

**El sensor de Hawkeye está en `unavailable`**

> El primer cálculo aún no se ha completado. Espera a que cierre la primera hora completa, o lanza el servicio `hawkeye.recalculate_today` desde **Herramientas para desarrolladores → Servicios**.

**El ahorro sale negativo**

> Es correcto en algunos casos: si has consumido en horas más caras de lo que el ingenuo asume, el ahorro es negativo. Esto refleja una mala gestión real. Si crees que es un error, revisa el patrón ingenuo declarado para ese asset (Ajustes → Dispositivos y servicios → Hawkeye → Configurar).

**Aparece un warning de "no_gestionable_real salió negativo"**

> Significa que el sensor de un asset reporta más consumo del que tu medidor de red dice. Suele ser un desfase de tiempos entre sensores o un sensor mal calibrado. La hora afectada se marca como "calidad dudosa" y se trunca a 0.

**Tengo solar pero no la veo reflejada**

> Asegúrate de que el sensor de "Energía consumida" del panel HA Energy ya está **neto de la solar** (es decir, refleja la importación de red, no el consumo bruto). Si tu instalación reporta consumo bruto, configura un sensor template que reste la generación solar.

---

## 📋 Requisitos

| Componente | Versión |
|---|---|
| Home Assistant | 2024.1.0 o superior |
| Python | 3.11+ |
| Sensor de consumo total con `device_class=energy` | Obligatorio |
| Sensores individuales de gestionables | Solo de los que quieras medir |
| Sensor de precios | Opcional |

---

## 🗺️ Roadmap

* **0.1** ✅ Cálculo M&V con electrodomésticos, EV y solar (libreria pura)
* **0.2** 🔨 Integración HA completa: config flow, sensores, card del dashboard
* **0.3** Override de día concreto desde la card
* **0.4** BESS (batería con autoconsumo simple como ingenuo)
* **0.5** HVAC (climatización con calibración del modelo térmico)
* **0.6** ACS (termo con perfil de ventanas de confort)
* **1.0** App optimizadora (`hawkeye-optimizer`) que cierra el círculo: Hawkeye mide, optimizer decide

---

## 📜 Licencia

MIT License — **Ander Zubiria**

---

## ☕ Apoya el proyecto

Si Hawkeye te resulta útil, puedes apoyar el desarrollo:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/anderzubiria)

---

## 🛠️ Para desarrolladores

```bash
git clone https://github.com/azubiria1996/hawkeye
cd hawkeye
python tests/test_hawkeye.py             # Tests sin dependencias
python examples/01_caso_usuario.py
```

La metodología completa, los principios M&V y el flujo de datos están documentados en [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).
