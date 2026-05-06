# 📘 Cómo calcula Hawkeye tu ahorro

Este documento explica, **paso a paso y con ejemplos**, cómo Hawkeye calcula cuánto te has ahorrado gestionando la energía de tu hogar.

Si solo quieres entender el **resultado** que ves en tu dashboard, lee la primera sección. Si quieres entender **el porqué** detrás de cada número, sigue leyendo.

---

## 🎯 La pregunta que respondemos

> *"¿Cuánto dinero te has ahorrado **hoy** gestionando inteligentemente tus electrodomésticos, comparado con haberlos usado sin pensar en las tarifas?"*

Para responder esto, Hawkeye compara dos escenarios:

| Escenario | Qué representa |
|---|---|
| **Real** | Lo que **ha pasado realmente** en tu casa hoy. |
| **Baseline** | Lo que **habría pasado** si no gestionaras la energía. |

La diferencia entre los dos es **tu ahorro real**.

---

## 💡 La idea fundamental

Lo importante de Hawkeye es **qué se gestiona y qué no**.

### Lo que NO se puede gestionar

- Frigorífico, router, standby de la TV...
- Cocinas que enciendes a la hora de comer
- Visitas que vienen a casa
- Cualquier cosa que no tenga sentido desplazar en el tiempo

A todo esto lo llamamos **carga base no gestionable**. Hawkeye **no inventa** lo que esto consume — lo **mide directamente** del medidor de tu casa. Y aquí está la clave:

> Esta carga base es **idéntica** en ambos escenarios (real y baseline). Si hoy ha venido tu suegra y la nevera ha trabajado más, eso aparece igual en los dos lados y **no afecta al cálculo del ahorro**.

### Lo que SÍ se puede gestionar

- Lavadora, lavavajillas, secadora — desplazables a hora más barata
- Vehículo eléctrico — se puede cargar cuando convenga
- Solar fotovoltaica — se aprovecha más si haces coincidir consumos con sol

Para cada uno de estos **gestionables**, Hawkeye necesita **un sensor propio** que mida su consumo individualmente. Si no tienes sensor para ese electrodoméstico, queda fuera de la medición — pero no falla nada, simplemente no aparece como fuente de ahorro.

---

## 🔢 La fórmula (versión sencilla)

Para cada gestionable que tienes configurado:

```
Ahorro €/hora = (Lo que el ingenuo habría consumido esa hora
                - Lo que el real consumió esa hora) × precio €/kWh
```

Total del día = suma de los 24 valores horarios.

**Cuidado con las palabras**:
- "Ingenuo" = la versión sin gestión, lo que un usuario tonto haría.
- "Real" = lo que de verdad pasó, leído de tu sensor.

Y ya está. Esa es toda la matemática.

---

## 🏠 ¿Qué es el "comportamiento ingenuo"?

Hawkeye necesita saber qué habrías hecho **sin gestionar**. Para cada tipo de equipo, esto es lo ingenuo:

| Equipo | Comportamiento ingenuo |
|---|---|
| **Lavadora / lavavajillas** | Lo enciendes a la **hora típica** que tú declaras (ej. "los martes a las 21h"), siempre igual. |
| **Vehículo eléctrico** | En cuanto llegas a casa lo enchufas, y carga **a potencia máxima** sin parar. |
| **Solar PV** | Los paneles producen lo que les da el sol — no es desplazable. |

> **Importante**: el ingenuo **consume la misma energía total** que el real. Lo que cambia es **cuándo**. Si hoy has lavado 1,2 kWh, el ingenuo también lavará 1,2 kWh — pero a la hora "tonta", no a la hora barata.

Esta es una decisión deliberada: Hawkeye no penaliza al usuario por haber lavado más o menos hoy. Solo mide el ahorro por **redistribuir** el consumo en el tiempo.

---

## 📊 Un ejemplo paso a paso

Supongamos que es martes y has configurado en Hawkeye:

- Tu lavadora normalmente la pondrías **los martes a las 21h** (hora pico, 0,32 €/kWh)
- Pero hoy realmente has gestionado y la has puesto **a las 13h** (hora valle, 0,08 €/kWh)
- El ciclo dura **2 horas** y consume **1,2 kWh** en total

### Paso 1: leer los sensores

A las 00:05 del miércoles, Hawkeye lee del Recorder de HA cuánto consumió la lavadora cada hora del martes. Encuentra:

```
Lavadora (real): 0 kWh ... 0 kWh ... 0,6 kWh a las 13h, 0,6 kWh a las 14h ... 0 kWh ...
```

### Paso 2: calcular lo que habría hecho el ingenuo

Como tú declaraste "lavadora los martes a las 21h" y el martes consumió 1,2 kWh, el ingenuo asume:

```
Lavadora (ingenuo): 0 kWh ... 0 kWh ... 0,6 kWh a las 21h, 0,6 kWh a las 22h ... 0 kWh ...
```

(Misma cantidad total, pero a la hora "tonta".)

### Paso 3: calcular el ahorro hora a hora

Ahora aplicamos la fórmula a cada hora con su precio:

| Hora | Ingenuo | Real | Diferencia | Precio | Ahorro € |
|---|---|---|---|---|---|
| 13h | 0 | 0,6 | -0,6 | 0,08 | -0,048 |
| 14h | 0 | 0,6 | -0,6 | 0,08 | -0,048 |
| 21h | 0,6 | 0 | +0,6 | 0,32 | +0,192 |
| 22h | 0,6 | 0 | +0,6 | 0,32 | +0,192 |
| Resto | 0 | 0 | 0 | varios | 0 |

### Paso 4: sumar todo

```
Ahorro total = (-0,048) + (-0,048) + (+0,192) + (+0,192) = +0,288 €
```

**Has ahorrado 28,8 céntimos** en este martes.

> Si haces 4 lavados así al mes, son **1,15 € al mes** de ahorro real, **medido con precisión**.

---

## ❓ Preguntas frecuentes

### ¿Y si un día gestiono peor que el ingenuo?

Si lavas a hora cara cuando el ingenuo lo programa a hora barata, el ahorro saldrá **negativo**. Esto es **correcto**: refleja que has gastado más de lo que habrías gastado sin pensar. Hawkeye no oculta este caso — te lo enseña tal cual para que aprendas.

### ¿Y si un día no uso un electrodoméstico que tenía declarado?

Si el sensor dice 0 kWh, el ingenuo también es 0 kWh. Ahorro = 0. No se penaliza ni se premia.

### ¿Y si uso un electrodoméstico un día que NO había declarado en mis hábitos?

Por ejemplo, declaras "lavadora los martes" pero hoy es jueves y has lavado. En ese caso:
- El **real** mide 1,2 kWh.
- El **ingenuo** queda a 0 (porque tú dijiste que no lavabas los jueves).
- El ahorro saldrá negativo (-1,2 kWh).

Esto refleja que has consumido un ciclo "no previsto". Si quieres evitar esto, edita tu configuración para incluir el jueves entre los días típicos, o usa el **override de día concreto** desde la card del dashboard.

### ¿Qué pasa con la solar?

Cuando tengas paneles, Hawkeye los lee como una **resta del consumo total real**. Es decir:

- Tu medidor de red muestra **lo que importas** (consumo - autoconsumo).
- En las horas donde la solar cubre el consumo, importas menos. Esto reduce automáticamente la carga base no gestionable.
- Cuando exportas excedente, la curva del medidor refleja signo negativo (vendes a la red).

El ahorro por la solar viene **automáticamente** del precio: las horas con sol pagas 0 € por la energía autoconsumida, así que cualquier consumo desplazado a esas horas multiplica su ahorro.

### ¿Cuándo se calcula el ahorro definitivo?

Hora a hora durante el día (lo vas viendo en tu dashboard) y **a las 00:05 del día siguiente** se cierra la foto definitiva. A partir de ese momento, el ahorro de ese día queda registrado en HA.

### ¿Puedo cambiar mi configuración?

Sí, de dos formas:

1. **Patrón por defecto** (lo que pasa la mayoría de los días): se edita en *Ajustes → Dispositivos y servicios → Hawkeye → Configurar*.
2. **Override para un día concreto** (cuando rompes la rutina, ej. "mañana lavo a las 23h"): se edita desde la **card de Hawkeye en tu dashboard**, con dos clics.

---

## 🛡️ Por qué este método es el correcto

Hawkeye implementa el método **Measurement & Verification (M&V) ex-post**, definido en el estándar internacional [IPMVP](https://evo-world.org/en/products-services-mainmenu-en/protocols/ipmvp). Es el método que usan auditores energéticos profesionales para certificar ahorros reales en industria, edificios e instalaciones públicas.

Las características clave:

- **No se basa en estimaciones**: usa datos medidos.
- **Aísla el efecto de la gestión**: la carga base se mide igual en ambos lados.
- **Es justo**: si el día ha sido atípico (visitas, cocina más, etc.), eso afecta a real y baseline igualmente y se cancela.
- **Es honesto**: si gestionas mal, el ahorro lo refleja en negativo.

Otros métodos (declarar el consumo entero, comparar con la media, asumir patrones fijos) **introducen sesgos** que sobreestiman o infraestiman el ahorro. Hawkeye no.

---

## 📐 Casos límite (para los curiosos)

### El cálculo se trunca a 0 cuando los sensores dan resultados imposibles

Si tu medidor de red dice que has consumido 0,5 kWh en una hora pero la lavadora dice que consumió 0,8 kWh, eso es **imposible** (la lavadora no puede consumir más que el total). Pasa por errores de medida o de timing entre sensores.

En estos casos, Hawkeye trunca la carga no gestionable a 0 (no puede ser negativa) y **registra un warning** visible para el usuario. La hora queda marcada como "calidad dudosa".

### Datos incompletos no rompen el cálculo

Si en una hora falta una medida (sensor caído, restart de HA), esa hora se marca como "incompleta" y no participa en el cálculo. El resto del día sigue calculando con normalidad.

### Cambio de hora (DST)

Hawkeye trabaja en hora local. Los días de cambio de hora tienen 23 o 25 horas en lugar de 24, y el cálculo se ajusta automáticamente.

---

## 🚧 Lo que Hawkeye **NO** hace (todavía)

- **No predice** el consumo de mañana.
- **No optimiza** automáticamente — solo mide.
- **No estima** los gestionables sin sensor — si no hay sensor, no hay M&V.
- **No incluye** todavía batería, climatización ni ACS (versiones futuras).

Estas limitaciones son **deliberadas**. La fortaleza de M&V está en su simplicidad: medir lo que se puede medir, no inventar lo que no.

---

## 🔍 Glosario

| Término | Definición |
|---|---|
| **M&V** | Measurement & Verification, el método estándar para medir ahorros energéticos. |
| **Real** | Lo que efectivamente has consumido, medido de tu medidor. |
| **Ingenuo** | El comportamiento "sin gestión" que tú declaras como rutina por defecto. |
| **Baseline** | La curva total que tendrías si todos los gestionables operaran de forma ingenua. |
| **Carga base no gestionable** | Lo que tu casa consume aparte de los gestionables medidos. Idéntico en real y baseline. |
| **Override** | Modificación temporal del patrón ingenuo para un día concreto. Se borra al pasar ese día. |
| **Cierre del día** | Cálculo definitivo del ahorro, a las 00:05 del día siguiente. |
