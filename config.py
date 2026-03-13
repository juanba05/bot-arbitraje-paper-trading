# ============================================================
# CONFIG.PY — Configuracion central del bot de arbitraje
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

IOL_USUARIO      = os.getenv("IOL_USUARIO")
IOL_PASSWORD     = os.getenv("IOL_PASSWORD")
POLYGON_API_KEY  = os.getenv("POLYGON_API_KEY")
IOL_SANDBOX      = False

if not IOL_USUARIO or not IOL_PASSWORD:
    raise ValueError(
        "ERROR: No se encontraron credenciales de IOL.\n"
        "Asegurate de tener el archivo .env en la carpeta del proyecto."
    )

RUTA_BASE  = r"C:\Users\Usuario\bot_arbitraje"
RUTA_DATOS = r"C:\Users\Usuario\bot_arbitraje\datos"
RUTA_LOGS  = r"C:\Users\Usuario\bot_arbitraje\logs"
NOMBRE_DB  = "bot_arbitraje.db"

# ============================================================
# CEDEARs A MONITOREAR
# simbolo_iol:  ticker exacto en IOL para precio ARS (bCBA)
# simbolo_nyse: ticker en NYSE/NASDAQ para precio USD
# ratio:        cuantos CEDEARs = 1 accion NYSE
#
# TICKERS IOL QUE DIFIEREN DEL NYSE (verificados Feb 2026):
#   BAC  → BA.C  (verificado, funcionando)
#   TS   → TEN   (Tenaris CEDEAR en BYMA = TEN, no TS)
#   DIS  → DISN  (Disney CEDEAR en BYMA = DISN, ratio 4:1)
#   AGRO → EXCLUIDO (no cotiza como CEDEAR en bCBA)
# ============================================================

CEDEARS = {

    # ── TECNOLOGIA ──────────────────────────────────────────
    "AAPL":  {"simbolo_iol": "AAPL",  "simbolo_nyse": "AAPL",  "ratio": 20,  "nombre": "Apple Inc."},
    "GOOGL": {"simbolo_iol": "GOOGL", "simbolo_nyse": "GOOGL", "ratio": 58,  "nombre": "Alphabet Inc."},
    "MSFT":  {"simbolo_iol": "MSFT",  "simbolo_nyse": "MSFT",  "ratio": 30,  "nombre": "Microsoft Corp."},
    "AMZN":  {"simbolo_iol": "AMZN",  "simbolo_nyse": "AMZN",  "ratio": 144, "nombre": "Amazon.com Inc."},
    "TSLA":  {"simbolo_iol": "TSLA",  "simbolo_nyse": "TSLA",  "ratio": 15,  "nombre": "Tesla Inc."},
    "NVDA":  {"simbolo_iol": "NVDA",  "simbolo_nyse": "NVDA",  "ratio": 24,  "nombre": "NVIDIA Corp."},
    "META":  {"simbolo_iol": "META",  "simbolo_nyse": "META",  "ratio": 24,  "nombre": "Meta Platforms"},
    "NFLX":  {"simbolo_iol": "NFLX",  "simbolo_nyse": "NFLX",  "ratio": 48,  "nombre": "Netflix Inc."},
    "AMD":   {"simbolo_iol": "AMD",   "simbolo_nyse": "AMD",   "ratio": 10,  "nombre": "Advanced Micro Devices"},
    "INTC":  {"simbolo_iol": "INTC",  "simbolo_nyse": "INTC",  "ratio": 5,   "nombre": "Intel Corp."},
    "QCOM":  {"simbolo_iol": "QCOM",  "simbolo_nyse": "QCOM",  "ratio": 11,  "nombre": "Qualcomm Inc."},
    "IBM":   {"simbolo_iol": "IBM",   "simbolo_nyse": "IBM",   "ratio": 15,  "nombre": "IBM Corp."},
    "CSCO":  {"simbolo_iol": "CSCO",  "simbolo_nyse": "CSCO",  "ratio": 5,   "nombre": "Cisco Systems"},
    "ORCL":  {"simbolo_iol": "ORCL",  "simbolo_nyse": "ORCL",  "ratio": 3,   "nombre": "Oracle Corp."},
    "CRM":   {"simbolo_iol": "CRM",   "simbolo_nyse": "CRM",   "ratio": 18,  "nombre": "Salesforce Inc."},
    "ADBE":  {"simbolo_iol": "ADBE",  "simbolo_nyse": "ADBE",  "ratio": 44,  "nombre": "Adobe Inc."},
    "NOW":   {"simbolo_iol": "NOW",   "simbolo_nyse": "NOW",   "ratio": 172, "nombre": "ServiceNow Inc."},
    "SHOP":  {"simbolo_iol": "SHOP",  "simbolo_nyse": "SHOP",  "ratio": 107, "nombre": "Shopify Inc."},
    "PLTR":  {"simbolo_iol": "PLTR",  "simbolo_nyse": "PLTR",  "ratio": 3,   "nombre": "Palantir Technologies"},
    "COIN":  {"simbolo_iol": "COIN",  "simbolo_nyse": "COIN",  "ratio": 27,  "nombre": "Coinbase Global"},
    "ASML":  {"simbolo_iol": "ASML",  "simbolo_nyse": "ASML",  "ratio": 146, "nombre": "ASML Holding"},
    "TSM":   {"simbolo_iol": "TSM",   "simbolo_nyse": "TSM",   "ratio": 9,   "nombre": "Taiwan Semiconductor"},
    "GLOB":  {"simbolo_iol": "GLOB",  "simbolo_nyse": "GLOB",  "ratio": 18,  "nombre": "Globant S.A."},

    # ── FINANZAS ─────────────────────────────────────────────
    "JPM":   {"simbolo_iol": "JPM",   "simbolo_nyse": "JPM",   "ratio": 15,  "nombre": "JP Morgan Chase"},
    "BAC":   {"simbolo_iol": "BA.C",  "simbolo_nyse": "BAC",   "ratio": 4,   "nombre": "Bank of America"},
    "GS":    {"simbolo_iol": "GS",    "simbolo_nyse": "GS",    "ratio": 13,  "nombre": "Goldman Sachs"},
    "V":     {"simbolo_iol": "V",     "simbolo_nyse": "V",     "ratio": 18,  "nombre": "Visa Inc."},
    "MA":    {"simbolo_iol": "MA",    "simbolo_nyse": "MA",    "ratio": 33,  "nombre": "Mastercard Inc."},
    "PYPL":  {"simbolo_iol": "PYPL",  "simbolo_nyse": "PYPL",  "ratio": 8,   "nombre": "PayPal Holdings"},
    "BKNG":  {"simbolo_iol": "BKNG",  "simbolo_nyse": "BKNG",  "ratio": 700, "nombre": "Booking Holdings"},

    # ── ENERGIA Y COMMODITIES ────────────────────────────────
    "XOM":   {"simbolo_iol": "XOM",   "simbolo_nyse": "XOM",   "ratio": 10,  "nombre": "ExxonMobil"},
    "CVX":   {"simbolo_iol": "CVX",   "simbolo_nyse": "CVX",   "ratio": 16,  "nombre": "Chevron"},
    "VALE":  {"simbolo_iol": "VALE",  "simbolo_nyse": "VALE",  "ratio": 2,   "nombre": "Vale S.A."},
    "PBR":   {"simbolo_iol": "PBR",   "simbolo_nyse": "PBR",   "ratio": 1,   "nombre": "Petrobras"},
    "VIST":  {"simbolo_iol": "VIST",  "simbolo_nyse": "VIST",  "ratio": 3,   "nombre": "Vista Energy"},
    "TS":    {"simbolo_iol": "TEN",   "simbolo_nyse": "TS",    "ratio": 1,   "nombre": "Tenaris S.A."},

    # ── CONSUMO Y RETAIL ─────────────────────────────────────
    "MELI":  {"simbolo_iol": "MELI",  "simbolo_nyse": "MELI",  "ratio": 120, "nombre": "MercadoLibre"},
    "DIS":   {"simbolo_iol": "DISN",  "simbolo_nyse": "DIS",   "ratio": 4,   "nombre": "Walt Disney Co."},
    "NKE":   {"simbolo_iol": "NKE",   "simbolo_nyse": "NKE",   "ratio": 12,  "nombre": "Nike Inc."},
    "KO":    {"simbolo_iol": "KO",    "simbolo_nyse": "KO",    "ratio": 5,   "nombre": "Coca-Cola Co."},
    "PEP":   {"simbolo_iol": "PEP",   "simbolo_nyse": "PEP",   "ratio": 18,  "nombre": "PepsiCo Inc."},
    "MCD":   {"simbolo_iol": "MCD",   "simbolo_nyse": "MCD",   "ratio": 24,  "nombre": "McDonald's Corp."},
    "WMT":   {"simbolo_iol": "WMT",   "simbolo_nyse": "WMT",   "ratio": 18,  "nombre": "Walmart Inc."},
    "COST":  {"simbolo_iol": "COST",  "simbolo_nyse": "COST",  "ratio": 48,  "nombre": "Costco Wholesale"},
    "SBUX":  {"simbolo_iol": "SBUX",  "simbolo_nyse": "SBUX",  "ratio": 12,  "nombre": "Starbucks Corp."},
    "RACE":  {"simbolo_iol": "RACE",  "simbolo_nyse": "RACE",  "ratio": 83,  "nombre": "Ferrari N.V."},

    # ── SALUD ────────────────────────────────────────────────
    "PFE":   {"simbolo_iol": "PFE",   "simbolo_nyse": "PFE",   "ratio": 4,   "nombre": "Pfizer Inc."},
    "JNJ":   {"simbolo_iol": "JNJ",   "simbolo_nyse": "JNJ",   "ratio": 15,  "nombre": "Johnson & Johnson"},
    "MRK":   {"simbolo_iol": "MRK",   "simbolo_nyse": "MRK",   "ratio": 5,   "nombre": "Merck & Co."},
    "ABBV":  {"simbolo_iol": "ABBV",  "simbolo_nyse": "ABBV",  "ratio": 10,  "nombre": "AbbVie Inc."},
    "LLY":   {"simbolo_iol": "LLY",   "simbolo_nyse": "LLY",   "ratio": 56,  "nombre": "Eli Lilly and Co."},

    # ── INDUSTRIAL Y TELECOM ─────────────────────────────────
    "BA":    {"simbolo_iol": "BA",    "simbolo_nyse": "BA",    "ratio": 24,  "nombre": "Boeing Co."},
    "CAT":   {"simbolo_iol": "CAT",   "simbolo_nyse": "CAT",   "ratio": 20,  "nombre": "Caterpillar Inc."},
    "HON":   {"simbolo_iol": "HON",   "simbolo_nyse": "HON",   "ratio": 8,   "nombre": "Honeywell Intl."},
    "GE":    {"simbolo_iol": "GE",    "simbolo_nyse": "GE",    "ratio": 8,   "nombre": "GE Aerospace"},
    "T":     {"simbolo_iol": "T",     "simbolo_nyse": "T",     "ratio": 3,   "nombre": "AT&T Inc."},
    "VZ":    {"simbolo_iol": "VZ",    "simbolo_nyse": "VZ",    "ratio": 4,   "nombre": "Verizon Comms."},

    # ── CRYPTO ───────────────────────────────────────────────
    "IBIT":  {"simbolo_iol": "IBIT",  "simbolo_nyse": "IBIT",  "ratio": 10,  "nombre": "iShares Bitcoin Trust"},

    # ── ETFs ─────────────────────────────────────────────────
    "GDX":   {"simbolo_iol": "GDX",   "simbolo_nyse": "GDX",   "ratio": 10,  "nombre": "VanEck Gold Miners ETF"},
    "SLV":   {"simbolo_iol": "SLV",   "simbolo_nyse": "SLV",   "ratio": 6,   "nombre": "iShares Silver Trust"},
    "XLK":   {"simbolo_iol": "XLK",   "simbolo_nyse": "XLK",   "ratio": 46,  "nombre": "SPDR Tech Sector ETF"},
    "XLV":   {"simbolo_iol": "XLV",   "simbolo_nyse": "XLV",   "ratio": 29,  "nombre": "SPDR Health Sector ETF"},
    "IVV":   {"simbolo_iol": "IVV",   "simbolo_nyse": "IVV",   "ratio": 692, "nombre": "iShares S&P 500 ETF"},
    "EFA":   {"simbolo_iol": "EFA",   "simbolo_nyse": "EFA",   "ratio": 18,  "nombre": "iShares MSCI EAFE ETF"},
    "FXI":   {"simbolo_iol": "FXI",   "simbolo_nyse": "FXI",   "ratio": 5,   "nombre": "iShares China Large-Cap ETF"},
}

# ── PARAMETROS DE ESTRATEGIA ─────────────────────────────────
SPREAD_MINIMO_ARBITRAJE    = 3.0    # % minimo para generar senal
SPREAD_VARIACION_MINIMA    = 0.30   # si el spread no cambia >30% vs ultima senal, no se repite
SPREAD_SOSPECHOSO_UMBRAL   = 6.0    # % a partir del cual el spread se valida doble
UMBRAL_CAUCION             = 20.0   # % sobre promedio historico para senal de caucion
PLAZO_MAX_CAUCION          = 3      # dias: 1, 2 o 3 (maximo)
CAUCION_HORA_INICIO        = 15
CAUCION_HORA_FIN           = 17
INTERVALO_ACTUALIZACION    = 30     # segundos entre ciclos

MAX_CAPITAL_POR_OPERACION  = 0.20
MAX_CAPITAL_POR_DIA        = 1.00   # fraccion del capital base que se puede operar por dia
MAX_NEGATIVAS_CONSECUTIVAS = 3
MAX_FALLAS_API_CONSEC      = 3
CIRCUIT_BREAKER_MINUTOS    = 15
MAX_EDAD_CCL_MIN           = 15
MAX_EDAD_PRECIOS_NYSE_MIN  = 90

# ── COMISIONES IOL (verificadas Feb 2026) ────────────────────
COMISION_CEDEAR_PCT  = 0.60
COMISION_NYSE_PCT    = 0.35
COMISION_CAUCION_PCT = 0.30
IVA_PCT              = 0.21

# ── LIQUIDACION ───────────────────────────────────────────────
LIQUIDACION_CEDEAR_DIAS = 2
LIQUIDACION_NYSE_DIAS   = 1
