# Bot de Cauciones IOL — Automatización Financiera en Python

Sistema de trading automatizado para el mercado financiero argentino.
Analiza oportunidades de caución colocadora en IOL (InvertirOnline),
toma decisiones con lógica multi-plazo y ejecuta órdenes reales de forma
autónoma mediante automatización de navegador.

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

### Modos operativos (horario Buenos Aires)

| Horario | Modo | Lógica |
|---|---|---|
| 11:00–15:00 | arbitraje | Spreads CEDEAR/NYSE |
| 15:00–17:00 | mixto | CEDEARs + cauciones |
| 17:00–17:15 | caucion | Solo cauciones (cierre) |

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
- Cálculo de ganancia neta con comisión IOL e IVA incluidos.
- Comparación con promedio histórico de 7 días para detectar desvíos.
- Regla de 7 días habilitada solo ante saltos extraordinarios de tasa.
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
