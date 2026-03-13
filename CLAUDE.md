# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandos frecuentes

```bash
# Diagnóstico pre-mercado (obligatorio antes de operar)
python preflight_operativo.py

# Iniciar bot + dashboard juntos (modo recomendado)
python lanzar_sesion.py start --mode both
python lanzar_sesion.py status
python lanzar_sesion.py stop

# Componentes individuales
python bot_principal.py       # orquestador (Ctrl+C para detener)
python dashboard.py           # Dash en http://127.0.0.1:8050

# Validación de sintaxis de un módulo
python -m py_compile motor_cauciones.py

# Inicializar base de datos
python base_datos.py

# Ver logs en tiempo real (PowerShell)
Get-Content logs\sesion_bot.log -Tail 120
Get-Content logs\sesion_bot.log -Wait

# Reporte de comparación caucion real vs simulado
python reporte_cauciones_real_vs_sim.py --fecha YYYY-MM-DD

# WhatsApp bridge (control remoto)
python whatsapp_bridge.py serve --port 8787
python whatsapp_bridge.py agent --interval 5 --max 50
python whatsapp_bridge.py status
```

## Arquitectura del sistema

### Flujo de datos principal

```
IOL API (/estadocuenta, cotizaciones BYMA)
    ↓
iol_connector.py  ← autenticación Bearer token con auto-renovación (14 min)
    ↓
recolector.py     ← precios NYSE/NASDAQ desde IOL
motor_calculo.py  ← spreads CEDEAR vs CCL (arbitraje)
motor_cauciones.py← tasas desde scraping web IOL (no API)
    ↓
bot_principal.py  ← orquestador central
    ↓
ejecutor_paper.py / ejecutor_real_caucion.py
    ↓
SQLite: datos/bot_arbitraje.db
    ↓
dashboard.py      ← Dash/Plotly en :8050
```

### Modos operativos (horario Buenos Aires)
| Horario | Modo | Lógica |
|---|---|---|
| 11:00–15:00 | `arbitraje` | Solo spreads CEDEAR/NYSE |
| 15:00–17:00 | `mixto` | CEDEARs + cauciones |
| 17:00–17:00 | `caucion` | Solo cauciones (cierre) |
| Resto | `cerrado` | Sin ejecución |

El modo puede **forzarse** desde el dashboard; se persiste en `datos/dashboard_config.json` (`modo_forzado_bot`).

### Módulos clave y sus responsabilidades

- **`config.py`**: Única fuente de verdad de constantes. Carga `.env` con credenciales IOL y Polygon. Define los ~60 CEDEARs monitoreados con sus ratios verificados (muchos difieren entre IOL y NYSE: `BAC→BA.C`, `DIS→DISN`, `TS→TEN`).
- **`mercado.py`**: Calcula el estado BYMA, plazos de cauciones ajustando fines de semana, y función `estado_mercado()` usada en todo el sistema.
- **`motor_cauciones.py`**: Obtiene tasas reales via POST `https://iol.invertironline.com/Mercado/GetCaucionPuntas` (sesión de cookies, NO Bearer token). Evalúa plazos 1/2/3 días, calcula ganancia neta, guarda en `cauciones` y `cauciones_simuladas`. También contiene la lógica de aprendizaje sim-vs-real (`cauciones_real_vs_sim`).
- **`ejecutor_paper.py`**: Paper trading usando el saldo ARS real de `/estadocuenta`. Controla capital máximo por operación (20%), por día (100% del base), y tiene kill switch `EXIGIR_SALDO_IOL_REAL=True` que bloquea ejecución si IOL no responde.
- **`ejecutor_real_caucion.py`**: Motor para cauciones reales. **Estado actual: PENDIENTE** — el flujo confirmado es web (`/Operar/Caucionar → /Operar/ConfirmarCaucion → /Operar/CaucionExitosa`), falta automatización de navegador. CPD ≠ cauciones (CPD = cheques de pago diferido, error histórico ya documentado).
- **`bot_principal.py`**: Loop principal con circuit breaker (15 min de pausa tras 3 fallas API o 3 pérdidas consecutivas), corte diario a las 17:15, y bloqueo de modo real si no es `caucion`.
- **`dashboard.py`**: Dash app con tabs: EN VIVO, CAUCIONES, OPERACIONES, SEÑALES. Lee `datos/estado_bot.json` y `datos/dashboard_config.json` para control bidireccional.

### Persistencia

- **SQLite**: `datos/bot_arbitraje.db` — tablas principales: `cauciones`, `cauciones_simuladas`, `cauciones_real_vs_sim`, `cauciones_ordenes_real`, `cauciones_fills_real`, `seniales`, `operaciones_paper`, `precios_nyse`, `precios_cedears`, `ccl_historico`.
- **JSON de estado en `datos/`**: `estado_bot.json` (estado del ciclo), `bot_activo.json` (kill switch), `dashboard_config.json` (configuración persistente), `preflight_last.json`, `alertas_perdidas.json`, `sesion_procesos.json` (PIDs del lanzador).
- **Logs**: `logs/sesion_bot.log`, `logs/sesion_dashboard.log`, `logs/bot_YYYYMMDD.log`.
- Las migraciones de columnas nuevas en SQLite se hacen con `_asegurar_columna()` en `motor_cauciones.py` (liviano y reversible).

### Fórmulas financieras críticas

```
# Cauciones
ganancia_bruta = capital × (TNA/100) × (plazo/365)
comision_iol   = capital × 0.30% × 1.21  (IVA incluido)
ganancia_neta  = ganancia_bruta - comision_iol
capital_minimo_1d_10pct ≈ ARS 3.000  (para que sea rentable)

# Arbitraje CEDEAR
ccl_implicito = precio_ars / (precio_usd × ratio)
spread_pct    = (ccl_implicito - ccl_referencia) / ccl_referencia × 100
señal si spread_pct > 3.0% y variación > 30% vs última señal del mismo ticker
```

### Reglas de negocio no obvias

- El **CCL de referencia** se obtiene de `dolarapi.com` vía `obtener_ccl.py`, no de IOL.
- Las **tasas de cauciones** se obtienen por scraping web con sesión de cookies cacheada 30 minutos; no existe endpoint API oficial.
- Los **plazos de cauciones** se ajustan para que el vencimiento nunca caiga en fin de semana (la función `_dias_habiles_hasta_vencimiento()` calcula días calendario equivalentes).
- El modo 7 días de cauciones está **deshabilitado por defecto**; solo se activa si la TNA de 7d supera la curva 1-3d por 8 puntos o 25% (`SALTO_EXTRA_7D_PTS`/`SALTO_EXTRA_7D_PCT`).
- En `iol_connector.py` hay mojibake visible en los comentarios (cp1252 vs utf-8) — es cosmético, el código funciona.

### Configuración para ejecución real de cauciones

Editar `datos/dashboard_config.json`:
```json
{
  "modo_forzado_bot": "caucion",
  "execution_mode": "real",
  "real_caucion_enabled": true,
  "real_caucion_canary_mode": true,
  "real_caucion_canary_amount_ars": 1000.0,
  "real_caucion_max_monto_ars": 5000.0
}
```

**CRÍTICO**: `execution_mode=real` solo funciona cuando `modo_forzado_bot=caucion`. Si no, el bot bloquea la operativa.

### Variables de entorno requeridas (`.env`)

```
IOL_USUARIO=...
IOL_PASSWORD=...
POLYGON_API_KEY=...
# Para WhatsApp bridge (opcionales):
WSP_ALLOWED_FROM=+549...
WSP_REQUIRE_PIN=true
WSP_PIN=...
```
