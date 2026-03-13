# ============================================================
# OBTENER_CCL.PY — Obtiene el CCL desde fuentes confiables
# Fuentes: API pública de dolarapi.com (datos oficiales y de mercado)
# Si no encuentra datos frescos, devuelve None (nunca inventa un valor)
# ============================================================

import requests
import sqlite3
import os
from datetime import datetime, timedelta
from config import RUTA_DATOS, NOMBRE_DB

RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)

# Tolerancia maxima: si el dato tiene mas de X minutos, lo consideramos viejo
MINUTOS_MAXIMO = 60


def obtener_ccl_dolarapi():
    """
    Consulta dolarapi.com — fuente confiable y gratuita.
    Devuelve el valor de venta del dolar CCL, o None si falla.
    """
    url = "https://dolarapi.com/v1/dolares/contadoconliqui"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            valor = data.get("venta")
            if valor and valor > 0:
                print(f"  CCL desde dolarapi.com: ${valor:,.2f}")
                return float(valor)
        print(f"  dolarapi.com: respuesta inesperada ({r.status_code})")
        return None
    except Exception as e:
        print(f"  dolarapi.com: error de conexion ({e})")
        return None


def obtener_mep_dolarapi():
    """
    Consulta el dolar MEP como alternativa al CCL.
    El MEP y el CCL suelen estar muy cerca entre si.
    """
    url = "https://dolarapi.com/v1/dolares/bolsa"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            valor = data.get("venta")
            if valor and valor > 0:
                print(f"  MEP desde dolarapi.com: ${valor:,.2f} (usando como respaldo del CCL)")
                return float(valor)
        return None
    except Exception as e:
        print(f"  MEP dolarapi.com: error ({e})")
        return None


def guardar_ccl_en_db(ccl_valor, fuente):
    """Guarda el CCL obtenido en la base de datos para historial."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        c = conn.cursor()
        c.execute("""
            INSERT INTO ccl_historico (timestamp, ccl_valor)
            VALUES (?, ?)
        """, (datetime.now().isoformat(), ccl_valor))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  Advertencia: no se pudo guardar CCL en DB ({e})")


def obtener_ultimo_ccl_db():
    """
    Devuelve el ultimo CCL guardado en la base de datos,
    solo si tiene menos de MINUTOS_MAXIMO minutos.
    """
    try:
        conn = sqlite3.connect(RUTA_DB)
        c = conn.cursor()
        c.execute("""
            SELECT ccl_valor, timestamp FROM ccl_historico
            ORDER BY timestamp DESC LIMIT 1
        """)
        fila = c.fetchone()
        conn.close()

        if not fila:
            return None

        ccl_valor, ts_str = fila
        ts = datetime.fromisoformat(ts_str)
        edad = datetime.now() - ts

        if edad < timedelta(minutes=MINUTOS_MAXIMO):
            print(f"  CCL desde historial local (hace {int(edad.total_seconds()/60)} min): ${ccl_valor:,.2f}")
            return float(ccl_valor)
        else:
            print(f"  CCL en historial local demasiado viejo ({int(edad.total_seconds()/60)} min), ignorando.")
            return None
    except Exception as e:
        print(f"  Error leyendo CCL de DB: {e}")
        return None


def obtener_ccl():
    """
    Funcion principal. Intenta obtener el CCL en este orden:
      1. dolarapi.com (CCL directo)
      2. dolarapi.com (MEP como respaldo)
      3. Historial local (si es reciente)
      4. Devuelve None — NUNCA inventa un valor

    Si devuelve None, el motor de calculo NO ejecuta.
    """
    print("\n--- Buscando CCL ---")

    # 1. CCL directo
    ccl = obtener_ccl_dolarapi()
    if ccl:
        guardar_ccl_en_db(ccl, "dolarapi-ccl")
        return ccl

    # 2. MEP como respaldo
    ccl = obtener_mep_dolarapi()
    if ccl:
        guardar_ccl_en_db(ccl, "dolarapi-mep")
        return ccl

    # 3. Historial local reciente
    ccl = obtener_ultimo_ccl_db()
    if ccl:
        return ccl

    # 4. No hay dato confiable
    print("  ERROR: No se pudo obtener el CCL desde ninguna fuente.")
    print("  El motor de calculo NO se ejecutara para evitar errores.")
    return None


# --- Probar directamente ---
if __name__ == "__main__":
    ccl = obtener_ccl()
    if ccl:
        print(f"\nCCL obtenido: ${ccl:,.2f}")
    else:
        print("\nNo se pudo obtener el CCL. Revisa tu conexion a internet.")
