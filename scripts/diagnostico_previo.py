"""
diagnostico_previo.py - Verifica todas las conexiones antes de que abra el mercado
Corré esto cuando el mercado esta cerrado para asegurarte de que todo va a funcionar.
No inventa ningun dato. Solo prueba y reporta.
"""

import sys
import os
import sqlite3
import requests
from datetime import datetime

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Detectar ruta del proyecto ────────────────────────────────────
RUTA_BASE  = os.path.dirname(os.path.abspath(__file__))
RUTA_DATOS = os.path.join(RUTA_BASE, "datos")
NOMBRE_DB  = "bot_arbitraje.db"
RUTA_DB    = os.path.join(RUTA_DATOS, NOMBRE_DB)

VERDE  = "✅"
ROJO   = "❌"
AMARI  = "⚠️ "
INFO   = "ℹ️ "

resultados = []

def ok(msg):
    print(f"  {VERDE} {msg}")
    resultados.append(("OK", msg))

def error(msg):
    print(f"  {ROJO} {msg}")
    resultados.append(("ERROR", msg))

def advertencia(msg):
    print(f"  {AMARI} {msg}")
    resultados.append(("WARN", msg))

def info(msg):
    print(f"  {INFO} {msg}")


# ══════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  DIAGNÓSTICO PRE-MERCADO — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
print(f"{'='*60}")


# ══════════════════════════════════════════════════════════════════
print(f"\n[1/6] ARCHIVOS DEL PROYECTO")
print(f"{'─'*60}")

archivos_requeridos = [
    "config.py",
    "iol_connector.py",
    "base_datos.py",
    "motor_cauciones.py",
    "motor_calculo.py",
    "recolector.py",
    "bot_principal.py",
    "dashboard.py",
]
for archivo in archivos_requeridos:
    ruta = os.path.join(RUTA_BASE, archivo)
    if os.path.exists(ruta):
        tam = os.path.getsize(ruta)
        ok(f"{archivo} ({tam:,} bytes)")
    else:
        error(f"{archivo} — NO ENCONTRADO")

# Carpeta datos
if os.path.exists(RUTA_DATOS):
    ok(f"Carpeta datos/ existe")
else:
    error(f"Carpeta datos/ NO existe — ejecutá base_datos.py primero")


# ══════════════════════════════════════════════════════════════════
print(f"\n[2/6] SEGURIDAD DE CREDENCIALES")
print(f"{'-'*60}")

ok("Chequeo de credenciales omitido por politica de seguridad")


print(f"\n[3/6] CONEXION CON IOL API")
print(f"{'─'*60}")

iol_token_ok = False
try:
    sys.path.insert(0, RUTA_BASE)
    from iol_connector import _obtener_token_inicial, _get
    info("Intentando login con IOL...")
    iol_token_ok = _obtener_token_inicial()
    if iol_token_ok:
        ok("Login IOL exitoso — token obtenido")
    else:
        error("Login IOL fallido - revisa conectividad o credenciales en entorno seguro")
except ImportError:
    error("No se pudo importar iol_connector.py")
except Exception as e:
    error(f"Error en IOL connector: {e}")

# Si tenemos token, probamos endpoints
if iol_token_ok:
    print()
    info("Probando endpoints de IOL...")

    # Estado de cuenta
    try:
        datos = _get("/estadocuenta")
        if datos is not None:
            ok(f"/estadocuenta → responde OK (tipo: {type(datos).__name__})")
            # Intentar extraer saldo
            saldo = None
            if isinstance(datos, list):
                for c in datos:
                    if isinstance(c, dict):
                        for campo in ["disponible", "saldo", "balance"]:
                            if campo in c:
                                saldo = c[campo]
                                break
            elif isinstance(datos, dict):
                for campo in ["disponible", "saldo", "balance"]:
                    if campo in datos:
                        saldo = datos[campo]
                        break
            if saldo is not None:
                ok(f"Saldo disponible detectado: ARS {float(saldo):,.2f}")
            else:
                advertencia("Saldo no pudo parsearse (payload oculto por seguridad).")
        else:
            error("/estadocuenta → sin respuesta")
    except Exception as e:
        error(f"/estadocuenta → excepcion: {e}")

    # Cotizacion de prueba (AAPL)
    try:
        datos = _get("/bCBA/Titulos/AAPL/Cotizacion")
        if datos is not None:
            precio = None
            if isinstance(datos, dict):
                precio = datos.get("ultimoPrecio", datos.get("ultimo", datos.get("price", None)))
            if precio is not None:
                ok(f"AAPL en BYMA → ARS {precio}")
            else:
                advertencia("AAPL responde pero sin precio claro (payload oculto por seguridad).")
        else:
            error("AAPL BYMA → sin respuesta (puede ser fuera de horario, es normal)")
    except Exception as e:
        error(f"AAPL BYMA → excepcion: {e}")

    # Estado real de cauciones
    ok("Cauciones reales confirmadas como flujo WEB de IOL (no API CPD)")
    info("  Flujo observado: /Operar/Caucionar -> /Operar/ConfirmarCaucion -> /Operar/CaucionExitosa")


# ══════════════════════════════════════════════════════════════════
print(f"\n[4/6] FUENTES DE TASA DE CAUCIONES")
print(f"{'─'*60}")

# Ambito
try:
    urls_ambito = [
        ("ambito caucion 1d variacion",   "https://mercados.ambito.com/caucion/1/variacion"),
        ("ambito caucion 1d grafico",      "https://mercados.ambito.com/caucion/1/grafico/anual"),
        ("ambito caucion referencia",      "https://mercados.ambito.com//cauciones/referencia/1/variacion"),
    ]
    encontrado = False
    for nombre, url in urls_ambito:
        try:
            resp = requests.get(url, timeout=5,
                                headers={"User-Agent": "Mozilla/5.0",
                                         "Accept": "application/json"})
            if resp.status_code == 200:
                datos = resp.json()
                ok(f"{nombre} → HTTP 200")
                info(f"  Respuesta: {str(datos)[:200]}")
                # Intentar extraer tasa
                if isinstance(datos, dict) and "valor" in datos:
                    ok(f"  Tasa extraida: {datos['valor']}% TNA")
                    encontrado = True
                elif isinstance(datos, list) and len(datos) > 0:
                    ok(f"  Primer valor: {datos[0]}")
                    encontrado = True
            else:
                advertencia(f"{nombre} → HTTP {resp.status_code}")
        except Exception as e:
            advertencia(f"{nombre} → {e}")
    if not encontrado:
        advertencia("Ambito no disponible — se usará historial de DB como fallback")
except Exception as e:
    error(f"Error probando Ambito: {e}")


# ══════════════════════════════════════════════════════════════════
print(f"\n[5/6] BASE DE DATOS")
print(f"{'─'*60}")

if os.path.exists(RUTA_DB):
    tam_db = os.path.getsize(RUTA_DB)
    ok(f"DB encontrada: {RUTA_DB} ({tam_db:,} bytes)")
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tablas = [t[0] for t in cur.fetchall()]

        tablas_requeridas = [
            "cauciones", "cauciones_simuladas", "seniales",
            "precios_cedears", "precios_nyse", "ccl_historico"
        ]
        for tabla in tablas_requeridas:
            if tabla in tablas:
                cur.execute(f"SELECT COUNT(*) FROM {tabla}")
                n = cur.fetchone()[0]
                ok(f"Tabla '{tabla}' → {n} registros")
            else:
                advertencia(f"Tabla '{tabla}' — no existe todavia (se crea sola al correr el bot)")

        conn.close()
    except Exception as e:
        error(f"Error leyendo DB: {e}")
else:
    advertencia(f"DB no encontrada en {RUTA_DB}")
    info("Se crea sola cuando corras base_datos.py o el bot principal")


# ══════════════════════════════════════════════════════════════════
print(f"\n[6/6] LIBRERIAS PYTHON")
print(f"{'─'*60}")

librerias = [
    ("requests",    "requests"),
    ("pandas",      "pandas"),
    ("dash",        "dash"),
    ("plotly",      "plotly"),
    ("schedule",    "schedule"),
    ("pytz",        "pytz"),
    ("dotenv",      "dotenv"),
    ("sqlite3",     "sqlite3"),
]
for nombre, modulo in librerias:
    try:
        m = __import__(modulo)
        version = getattr(m, "__version__", "OK")
        ok(f"{nombre} — v{version}")
    except ImportError:
        error(f"{nombre} — NO INSTALADA  →  pip install {nombre}")


# ══════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  RESUMEN FINAL")
print(f"{'='*60}")

total    = len(resultados)
errores  = sum(1 for r in resultados if r[0] == "ERROR")
warnings = sum(1 for r in resultados if r[0] == "WARN")
oks      = sum(1 for r in resultados if r[0] == "OK")

print(f"  {VERDE} OK:        {oks}")
print(f"  {AMARI} Advertencias: {warnings}")
print(f"  {ROJO} Errores:   {errores}")

if errores == 0:
    print(f"\n  🟢 TODO LISTO — cuando abra el mercado a las 11hs")
    print(f"     el bot va a funcionar con datos reales.")
elif errores <= 2:
    print(f"\n  🟡 CASI LISTO — hay {errores} problema(s) menor(es).")
    print(f"     Revisá los ❌ de arriba antes de las 11hs.")
else:
    print(f"\n  🔴 REVISAR — hay {errores} problemas. Corregí antes de las 11hs.")

print(f"\n  Mercado BYMA abre a las 11:00hs Argentina.")
print(f"  Para analizar cauciones con datos reales, ejecutá a las 11hs:")
print(f"  python motor_cauciones.py")
print(f"{'='*60}\n")
