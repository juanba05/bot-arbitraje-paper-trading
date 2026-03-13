# ============================================================
# CONFIG.PY — Configuracion central del bot de cauciones
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

IOL_USUARIO     = os.getenv("IOL_USUARIO")
IOL_PASSWORD    = os.getenv("IOL_PASSWORD")
IOL_SANDBOX     = False

if not IOL_USUARIO or not IOL_PASSWORD:
    raise ValueError(
        "ERROR: No se encontraron credenciales de IOL.\n"
        "Asegurate de tener el archivo .env en la carpeta del proyecto."
    )

RUTA_BASE  = r"C:\Users\Usuario\bot_arbitraje"
RUTA_DATOS = r"C:\Users\Usuario\bot_arbitraje\datos"
RUTA_LOGS  = r"C:\Users\Usuario\bot_arbitraje\logs"
NOMBRE_DB  = "bot_arbitraje.db"

# ── PARAMETROS DE CAUCIONES ──────────────────────────────────────
UMBRAL_CAUCION          = 20.0   # % sobre promedio historico para senal
PLAZO_MAX_CAUCION       = 3      # dias habiles maximos: 1, 2 o 3
CAUCION_HORA_INICIO     = 11     # apertura del mercado
CAUCION_HORA_FIN        = 17     # cierre de cauciones
INTERVALO_ACTUALIZACION = 30     # segundos entre ciclos del bot

# ── LIMITES DE RIESGO ────────────────────────────────────────────
MAX_CAPITAL_POR_OPERACION  = 0.20   # maximo 20% del capital en una sola operacion
MAX_CAPITAL_POR_DIA        = 1.00   # puede operar hasta el 100% en el dia
MAX_NEGATIVAS_CONSECUTIVAS = 3
MAX_FALLAS_API_CONSEC      = 3
CIRCUIT_BREAKER_MINUTOS    = 15
MAX_EDAD_CCL_MIN           = 15     # CCL no puede tener mas de 15 min de antiguedad

# ── COMISIONES IOL (verificadas Feb 2026) ────────────────────────
COMISION_CAUCION_PCT = 0.30
IVA_PCT              = 21.0
