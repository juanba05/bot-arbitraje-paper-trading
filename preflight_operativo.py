import json
import os
import sqlite3
import sys
from datetime import datetime

try:
    import requests
except Exception:
    requests = None

from config import RUTA_DATOS, NOMBRE_DB, CEDEARS
from obtener_ccl import obtener_ccl
from iol_connector import _asegurar_token, _get
from motor_cauciones import _obtener_tasa_iol_web, _parsear_saldo_iol

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)
RUTA_CONFIG = os.path.join(RUTA_DATOS, "dashboard_config.json")
os.makedirs(RUTA_DATOS, exist_ok=True)

required_tables = [
    "cauciones",
    "cauciones_simuladas",
    "seniales",
    "precios_nyse",
    "ccl_historico",
]

checks = []


def cargar_dashboard_config():
    if not os.path.exists(RUTA_CONFIG):
        return {}
    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def add_check(name, ok, detail, critical=True, data=None):
    checks.append({
        "name": name,
        "ok": bool(ok),
        "critical": bool(critical),
        "detail": detail,
        "data": data or {},
    })


# 1) Entorno base
add_check(
    "python_runtime",
    True,
    f"Python {sys.version.split()[0]}",
    critical=False,
)

# 2) DB accesible + tablas
if os.path.exists(RUTA_DB):
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tablas = {r[0] for r in cur.fetchall()}
        faltantes = [t for t in required_tables if t not in tablas]

        data_counts = {}
        for t in required_tables:
            if t in tablas:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                data_counts[t] = cur.fetchone()[0]

        conn.close()
        add_check(
            "db_schema",
            len(faltantes) == 0,
            "Tablas OK" if not faltantes else f"Faltan tablas: {', '.join(faltantes)}",
            critical=True,
            data={"counts": data_counts, "missing": faltantes},
        )
    except Exception as e:
        add_check("db_schema", False, f"Error DB: {e}", critical=True)
else:
    add_check("db_schema", False, "No existe datos/bot_arbitraje.db", critical=True)

# 3) CCL real
try:
    ccl = obtener_ccl()
    add_check(
        "ccl_feed",
        ccl is not None and ccl > 0,
        f"CCL actual: {ccl:,.2f}" if ccl else "No se pudo obtener CCL",
        critical=True,
        data={"ccl": ccl},
    )
except Exception as e:
    add_check("ccl_feed", False, f"Error CCL: {e}", critical=True)

# 4) API IOL token + endpoints criticos
api_ok = False
try:
    api_ok = _asegurar_token()
    add_check("iol_token", api_ok, "Token IOL OK" if api_ok else "No se pudo obtener token", critical=True)
except Exception as e:
    add_check("iol_token", False, f"Error token IOL: {e}", critical=True)

saldo_ars = None
if api_ok:
    try:
        estado = _get("/estadocuenta")
        saldo_ars = _parsear_saldo_iol(estado)
        add_check(
            "iol_estadocuenta",
            estado is not None,
            "Endpoint /estadocuenta responde" if estado is not None else "Sin respuesta /estadocuenta",
            critical=True,
            data={"saldo_ars": saldo_ars},
        )
        add_check(
            "saldo_parseado",
            saldo_ars is not None and saldo_ars >= 0,
            f"Saldo ARS parseado: {saldo_ars:,.2f}" if saldo_ars is not None else "No se pudo parsear saldo",
            critical=True,
        )
    except Exception as e:
        add_check("iol_estadocuenta", False, f"Error /estadocuenta: {e}", critical=True)

    # cotizaciones muestra
    muestras = ["AAPL", "MELI", "TSLA"]
    precios_ok = 0
    precios_det = {}
    for sym in muestras:
        try:
            byma = _get(f"/bCBA/Titulos/{sym}/Cotizacion")
            nyse = _get(f"/NYSE/Titulos/{sym}/Cotizacion")
            p_byma = (byma or {}).get("ultimoPrecio") if isinstance(byma, dict) else None
            p_nyse = (nyse or {}).get("ultimoPrecio") if isinstance(nyse, dict) else None
            if p_byma or p_nyse:
                precios_ok += 1
            precios_det[sym] = {"byma": p_byma, "nyse": p_nyse}
        except Exception:
            precios_det[sym] = {"byma": None, "nyse": None}

    add_check(
        "precios_iol_muestra",
        precios_ok >= 2,
        f"Tickers con precio: {precios_ok}/{len(muestras)}",
        critical=True,
        data={"muestra": precios_det},
    )

# 5) Cauciones reales (IOL web)
tasas = {}
ok_plazos = 0
for plazo in (1, 2, 3):
    try:
        tna = _obtener_tasa_iol_web(plazo_dias=plazo)
    except Exception:
        tna = None
    tasas[str(plazo)] = tna
    if tna is not None and 0 < tna < 300:
        ok_plazos += 1

add_check(
    "cauciones_iol_web",
    ok_plazos >= 1,
    f"Plazos con tasa real: {ok_plazos}/3",
    critical=True,
    data={"tasas_tna": tasas},
)

# 6) Gate financiero minimo para caucion 1d
# Regla orientativa: con comision 0.30% + IVA, saldo bajo puede dar neto negativo.
# Esto NO bloquea readiness tecnico, pero alerta operativa.
if saldo_ars is not None and tasas.get("1"):
    tna1 = tasas["1"]
    capital = float(saldo_ars)
    ganancia_bruta = capital * (tna1 / 100.0) * (1.0 / 365.0)
    comision = capital * 0.0030 * 1.21
    neta = ganancia_bruta - comision
    add_check(
        "gate_financiero_1d",
        neta > 0,
        f"Caucion 1d estimada neta: {neta:.2f} ARS",
        critical=False,
        data={"ganancia_bruta": ganancia_bruta, "comision": comision, "neta": neta},
    )
else:
    add_check(
        "gate_financiero_1d",
        False,
        "Sin saldo o tasa 1d para estimar neto",
        critical=False,
    )

# 7) Readiness real de caucion
cfg = cargar_dashboard_config()
execution_mode = str(cfg.get("execution_mode", "paper")).lower().strip()
real_enabled = bool(cfg.get("real_caucion_enabled", False))
real_backend = str(cfg.get("real_caucion_backend", "web")).lower().strip() or "web"
if execution_mode == "real" and real_enabled:
    add_check(
        "real_caucion_backend",
        False,
        (
            "La caucion real de IOL se confirmo como flujo web "
            "(/Operar/Caucionar -> /Operar/ConfirmarCaucion -> /Operar/CaucionExitosa), "
            "pero la automatizacion del navegador aun no esta implementada."
        ),
        critical=True,
        data={"backend": real_backend},
    )
else:
    add_check(
        "real_caucion_backend",
        True,
        f"Modo actual: {execution_mode.upper()} | real_caucion_enabled={real_enabled}",
        critical=False,
        data={"backend": real_backend},
    )

# Resultado global
critical_failures = [c for c in checks if c["critical"] and not c["ok"]]
status = "READY" if not critical_failures else "NOT_READY"

report = {
    "timestamp": datetime.now().isoformat(),
    "status": status,
    "critical_failures": len(critical_failures),
    "checks": checks,
}

ruta_last = os.path.join(RUTA_DATOS, "preflight_last.json")
ruta_hist = os.path.join(RUTA_DATOS, f"preflight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

with open(ruta_last, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
with open(ruta_hist, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print("=" * 70)
print(f"PREFLIGHT OPERATIVO | {report['timestamp']}")
print(f"ESTADO GLOBAL: {status}")
print("=" * 70)
for c in checks:
    icon = "[OK]" if c["ok"] else ("[NO]" if c["critical"] else "[WARN]")
    tag = "CRITICO" if c["critical"] else "INFO"
    print(f"{icon} ({tag}) {c['name']}: {c['detail']}")

print("-" * 70)
print(f"Reporte guardado en: {ruta_last}")
print(f"Histórico guardado en: {ruta_hist}")
print("=" * 70)
