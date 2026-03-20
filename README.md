# Bot de Cauciones — Carry Trade Automatizado en Python

Sistema de trading automatizado para el mercado financiero argentino.
Captura oportunidades de carry trade mediante cauciones colocadoras en IOL
(InvertirOnline): analiza tasas en tiempo real, toma decisiones con lógica
multi-plazo y ejecuta órdenes reales de forma autónoma mediante
automatización de navegador.

---

## La Idea: Capturar Picos de Liquidez en el Cierre de Rueda

Las cauciones colocadoras son operaciones de pase a corto plazo: el inversor presta
pesos a cambio de una tasa (TNA) y recibe el capital más intereses al vencimiento.
Son uno de los instrumentos más líquidos del mercado argentino.

**El fenómeno que explota este bot:**

En las horas finales de la rueda bursátil, una parte de los participantes del
mercado —fondos comunes, carteras apalancadas, operadores institucionales— necesita
cerrar posiciones o cumplir compromisos de liquidez antes del cierre del día.
Cuando ese proceso se acelera (liquidaciones forzadas, rebalanceos de cartera,
rescates de cuotapartes), la demanda de efectivo a corto plazo sube abruptamente
y los tomadores de cauciones están dispuestos a pagar tasas más altas que las del
resto de la jornada para conseguir pesos de forma inmediata.

Esos picos son reales, recurrentes y estadísticamente medibles. Durante la jornada
normal la TNA puede moverse en un rango estable; en los últimos 30-60 minutos antes
del cierre puede saltar 5 a 15 puntos porcentuales por encima del promedio histórico
de la misma franja horaria.

**Cómo lo captura el bot:**

1. **Construye una baseline histórica** por plazo, hora del día y día de semana.
   Así compara una tasa del jueves a las 16:45 contra el promedio de todos los
   jueves a las 16:45, no contra el promedio general.

2. **Detecta desvíos estadísticos**: solo dispara una orden cuando la tasa supera
   la baseline en un umbral configurable (default: 20% por encima del promedio).
   Una tasa del 24% cuando el promedio histórico es 20% a esa hora representa
   exactamente el tipo de anomalía que el bot busca.

3. **Ejecuta en segundos**: al detectar el desvío, completa el formulario web de IOL
   de forma autónoma —monto, plazo, TNA mínima, confirmación con contraseña— sin
   intervención humana, para capturar la tasa antes de que el pico se normalice.

4. **Cierra el ciclo**: al vencimiento (1 a 7 días), el capital más los intereses
   vuelven a la cuenta y el bot queda disponible para la siguiente oportunidad.

El resultado es una estrategia de carry sistemática que se activa selectivamente:
no coloca a cualquier tasa, sino solo cuando el mercado está pagando por encima de
lo que históricamente paga a esa hora. El margen entre la tasa capturada y la tasa
promedio es el alpha que justifica la automatización.

---

## Qué hace

- **Monitorea tasas de caución en tiempo real** obteniendo datos directamente
  desde la plataforma web de IOL (scraping autenticado).
- **Evalúa plazos 1/2/3/7 días** y elige el óptimo según el día de semana,
  el capital disponible y la comparación con el historial.
- **Ejecuta órdenes reales automáticamente** a través de automatización del
  navegador (Selenium + undetected-chromedriver), completando el flujo web
  de IOL sin intervención humana.
- **Paper trading simultáneo** usando el saldo real de la cuenta IOL como
  base de cálculo, con guardas de seguridad estrictas.
- **Dashboard en tiempo real** para monitoreo, control y visualización de
  señales, operaciones y tasas históricas.

---

## Stack Tecnológico

| Área | Herramientas |
|---|---|
| Lenguaje | Python 3.11 |
| Automatización web | Selenium, undetected-chromedriver |
| Visualización | Dash, Plotly |
| Persistencia | SQLite, JSON |
| Integración API | Requests (API REST IOL + dolarapi.com) |
| Scheduling | schedule |
| Control remoto | Twilio WhatsApp API |
| Configuración | python-dotenv |

---

## Arquitectura

```
IOL API (/estadocuenta, cotizaciones)
    ↓
iol_connector.py     ← autenticación Bearer token con auto-renovación
    ↓
motor_cauciones.py   ← tasas reales via scraping web IOL + lógica multi-plazo
    ↓
bot_principal.py     ← orquestador: circuit breaker, modos, kill switch
    ↓
┌─────────────────────────────────────────┐
│  Paper trading          Ejecución real  │
│  ejecutor_paper.py  →  ejecutor_real    │
│                        ejecutor_selenium│
│                        (Chrome + IOL web)│
└─────────────────────────────────────────┘
    ↓
SQLite: datos/bot_arbitraje.db
    ↓
dashboard.py         ← Dash/Plotly, control bidireccional
```

### Horario operativo (Buenos Aires)

| Horario | Lógica |
|---|---|
| 11:00–17:00 | Evaluación y colocación de cauciones (modo normal, 70% del capital) |
| 17:00–17:15 | Ventana de cierre (100% del capital) |

---

## Características Técnicas Destacadas

**Automatización de formulario web con Selenium**
- Login autenticado en la plataforma de IOL.
- Llenado completo del formulario de caución: monto, plazo, TNA mínima,
  moneda y modalidad de precio.
- Navegación por el flujo de 3 pasos: formulario → preview → confirmación
  con contraseña.
- Detección robusta de éxito/fallo con capturas de pantalla para auditoría.
- Funcionamiento en modo minimizado (ventana invisible durante la operación).

**Lógica financiera multi-plazo**
- Evaluación de plazos 1, 2 y 3 días según el calendario de vencimientos.
- Plazo 7 días como fallback cuando IOL no ofrece plazos cortos (feriados,
  fines de semana largos) y como disparo extraordinario si la tasa supera
  la curva 1-3d por 8 puntos o 25%.
- Cálculo de ganancia neta con comisión IOL e IVA incluidos.
- Comparación con promedio histórico por plazo, hora y día de semana.
- Capital mínimo por plazo: el sistema no coloca si la comisión supera
  la ganancia bruta.

**Guardas de seguridad y control de riesgo**
- Kill switch por dashboard (datos/bot_activo.json).
- Idempotencia por ciclo_id: una sola orden por ciclo operativo.
- Modo canario: monto mínimo para primeras pruebas reales.
- Circuit breaker: 15 minutos de pausa ante 3 fallas de API o pérdidas
  consecutivas.
- Bloqueo de modo real si IOL no responde (no opera con datos de fallback).

**Dashboard de monitoreo**
- Tabs: EN VIVO, CAUCIONES, OPERACIONES, SEÑALES.
- Control bidireccional: modo del bot, kill switch, modo de ejecución.
- Visualización de tasas por plazo (1d/2d/3d/7d) con historial.
- Filtros temporales: HOY / 7 DÍAS / 30 DÍAS / GLOBAL.

**Control remoto vía WhatsApp**
- Webhook Twilio para comandos remotos autenticados.
- Allowlist por número + PIN opcional.
- Comandos: estado, preflight, start, stop.
- Auditoría append-only en datos/wsp_inbox.jsonl.

---

## Resultado Operativo

La primera ejecución real automatizada fue completada el 13/03/2026:
orden de caución colocadora por **ARS 20.001 al 20% TNA a 3 días**,
ejecutada de forma completamente autónoma, de principio a fin sin
intervención manual.

---

## Seguridad

- Credenciales gestionadas por variables de entorno (`.env` local, nunca versionado).
- Base de datos, logs y configuración operativa excluidos del repositorio.
- El código fuente no contiene datos de cuenta, saldos ni historial de operaciones.

---

## Estado del Proyecto

Activo. Ejecución real validada. En operación con monto canario.

> Este proyecto es de uso personal y no constituye asesoramiento financiero.
