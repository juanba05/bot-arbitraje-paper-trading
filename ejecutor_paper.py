"""
ejecutor_paper.py - Simulador de ordenes con gestion de capital inteligente.
- Nunca usa todo el capital en una sola operacion
- Alerta si detecta oportunidad pero no hay capital suficiente
- Al cierre (17-18hs) cauciona todo lo disponible
- Viernes: plazo 3 dias (para el lunes)
"""

import os
import sqlite3
import json
import time
from datetime import datetime
from config import (
    RUTA_DATOS,
    NOMBRE_DB,
    MAX_CAPITAL_POR_OPERACION,
    MAX_CAPITAL_POR_DIA,
)
from mercado import estado_mercado, plazo_caucion_dias

try:
    from iol_connector import _get, _asegurar_token
    IOL_OK = True
except Exception:
    IOL_OK = False

RUTA_DB         = os.path.join(RUTA_DATOS, NOMBRE_DB)
RUTA_CONFIG     = os.path.join(RUTA_DATOS, "dashboard_config.json")
RUTA_ALERTAS    = os.path.join(RUTA_DATOS, "alertas_perdidas.json")

CAPITAL_FALLBACK = 40000.0  # fallback si IOL no responde
_SALDO_CACHE = {"ts": 0.0, "saldo": None, "fuente": "SIN_DATO"}
EXIGIR_SALDO_IOL_REAL = True

# Defaults (se sobreescriben con dashboard_config.json)
DEFAULTS = {
    "ganancia_minima_caucion_pct":   1.5,
    "ganancia_minima_arbitraje_pct": 2.0,
    "max_capital_arbitraje_pct":     30.0,
    "max_capital_caucion_pct":       70.0,
    "comision_iol_pct":              0.6,
    "slippage_pct":                  0.3,
    "margen_seguridad_pct":          0.6,
}


def cargar_config():
    if os.path.exists(RUTA_CONFIG):
        with open(RUTA_CONFIG) as f:
            cfg = json.load(f)
        for k, v in DEFAULTS.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULTS.copy()


# ──────────────────────────────────────────────────────────────────
# CAPITAL
# ──────────────────────────────────────────────────────────────────

def conectar():
    return sqlite3.connect(RUTA_DB)


def _parsear_saldo_ars_iol(datos):
    if datos is None:
        return None

    def es_pesos(cuenta):
        moneda = str(cuenta.get("moneda", "")).lower().replace("_", "").replace(" ", "")
        tipo = str(cuenta.get("tipo", "")).lower()
        return ("peso" in moneda or "ars" in moneda or "pesos" in tipo)

    if isinstance(datos, dict):
        cuentas = datos.get("cuentas", datos.get("accounts", []))
        if isinstance(cuentas, list):
            for c in cuentas:
                if es_pesos(c):
                    v = c.get("disponible", c.get("saldo"))
                    if v is not None:
                        return float(v)
            for c in cuentas:
                v = c.get("disponible", c.get("saldo"))
                if v is not None:
                    return float(v)

    if isinstance(datos, list):
        for c in datos:
            if isinstance(c, dict) and es_pesos(c):
                v = c.get("disponible", c.get("saldo"))
                if v is not None:
                    return float(v)
    return None


def capital_base_actual(force_refresh=False):
    ahora = time.time()
    if not force_refresh and _SALDO_CACHE["saldo"] is not None and (ahora - _SALDO_CACHE["ts"]) < 60:
        return _SALDO_CACHE["saldo"], _SALDO_CACHE["fuente"]

    if IOL_OK:
        try:
            if _asegurar_token():
                datos = _get("/estadocuenta")
                saldo = _parsear_saldo_ars_iol(datos)
                if saldo is not None and saldo >= 0:
                    _SALDO_CACHE["ts"] = ahora
                    _SALDO_CACHE["saldo"] = saldo
                    _SALDO_CACHE["fuente"] = "IOL_REAL"
                    return saldo, "IOL_REAL"
        except Exception:
            pass

    _SALDO_CACHE["ts"] = ahora
    _SALDO_CACHE["saldo"] = CAPITAL_FALLBACK
    _SALDO_CACHE["fuente"] = "FALLBACK_40000"
    return CAPITAL_FALLBACK, "FALLBACK_40000"


def _capital_habilitado_para_operar():
    base, fuente = capital_base_actual(force_refresh=True)
    if EXIGIR_SALDO_IOL_REAL and fuente != "IOL_REAL":
        print("[PAPER] BLOQUEADO: fuente de capital no real (fallback activo).")
        print("        Condicion requerida: fuente_capital = IOL_REAL")
        return False
    if base <= 0:
        print("[PAPER] BLOQUEADO: saldo base <= 0.")
        return False
    return True


def capital_disponible():
    try:
        capital_base, _ = capital_base_actual()
        conn = conectar()
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(capital_usado),0) FROM operaciones_paper WHERE estado='ABIERTA'")
        comprometido = c.fetchone()[0]
        conn.close()
        return round(max(0.0, capital_base - comprometido), 2)
    except Exception:
        return CAPITAL_FALLBACK


def _monto_maximo(tipo, cierre_total=False):
    """Calcula el monto máximo a usar según tipo y horario."""
    cfg  = cargar_config()
    disp = capital_disponible()
    if cierre_total:
        return disp  # al cierre: todo lo disponible
    if tipo == "CAUCION":
        return round(disp * cfg["max_capital_caucion_pct"] / 100, 2)
    else:
        return round(disp * cfg["max_capital_arbitraje_pct"] / 100, 2)


def _capital_operado_hoy():
    hoy = datetime.now().date().isoformat()
    try:
        conn = conectar()
        c = conn.cursor()
        c.execute(
            "SELECT COALESCE(SUM(capital_usado),0) FROM operaciones_paper WHERE substr(timestamp,1,10)=?",
            (hoy,),
        )
        usado = float(c.fetchone()[0] or 0.0)
        conn.close()
        return usado
    except Exception:
        return 0.0


def _cap_diario_restante():
    base, _ = capital_base_actual()
    tope_dia = max(0.0, base * MAX_CAPITAL_POR_DIA)
    usado_hoy = _capital_operado_hoy()
    return round(max(0.0, tope_dia - usado_hoy), 2), tope_dia, usado_hoy


# ──────────────────────────────────────────────────────────────────
# ALERTAS DE OPORTUNIDADES PERDIDAS
# ──────────────────────────────────────────────────────────────────

def registrar_oportunidad_perdida(tipo, simbolo, ganancia_estimada,
                                   capital_necesario, capital_disponible_actual, motivo):
    """Guarda una oportunidad que no se pudo ejecutar por falta de capital."""
    alerta = {
        "timestamp":          datetime.now().isoformat(),
        "tipo":               tipo,
        "simbolo":            simbolo,
        "ganancia_estimada":  round(ganancia_estimada, 2),
        "capital_necesario":  round(capital_necesario, 2),
        "capital_disponible": round(capital_disponible_actual, 2),
        "capital_faltante":   round(capital_necesario - capital_disponible_actual, 2),
        "motivo":             motivo,
        "vista":              False,
    }

    alertas = []
    if os.path.exists(RUTA_ALERTAS):
        with open(RUTA_ALERTAS) as f:
            alertas = json.load(f)

    alertas.insert(0, alerta)
    alertas = alertas[:50]  # guardar solo las últimas 50

    with open(RUTA_ALERTAS, "w") as f:
        json.dump(alertas, f, indent=2)

    print(f"\n[ALERTA] Oportunidad perdida por capital insuficiente:")
    print(f"  Tipo:              {tipo} — {simbolo}")
    print(f"  Ganancia estimada: ${ganancia_estimada:,.2f} ARS")
    print(f"  Capital necesario: ${capital_necesario:,.2f} ARS")
    print(f"  Capital disponible:${capital_disponible_actual:,.2f} ARS")
    print(f"  Capital faltante:  ${capital_necesario - capital_disponible_actual:,.2f} ARS")


def get_alertas_no_vistas():
    if not os.path.exists(RUTA_ALERTAS):
        return []
    with open(RUTA_ALERTAS) as f:
        alertas = json.load(f)
    return [a for a in alertas if not a.get("vista", False)]


def marcar_alertas_vistas():
    if not os.path.exists(RUTA_ALERTAS):
        return
    with open(RUTA_ALERTAS) as f:
        alertas = json.load(f)
    for a in alertas:
        a["vista"] = True
    with open(RUTA_ALERTAS, "w") as f:
        json.dump(alertas, f, indent=2)


# ──────────────────────────────────────────────────────────────────
# VALIDACIONES
# ──────────────────────────────────────────────────────────────────

def _verificar_puede_operar(tipo_operacion):
    """Verifica si el mercado permite este tipo de operación ahora."""
    estado = estado_mercado()
    modo   = estado["modo"]

    if tipo_operacion == "ARBITRAJE" and not estado["abierto"]:
        print(f"[PAPER] Mercado cerrado para arbitraje — {estado['estado']}")
        return False
    if tipo_operacion == "CAUCION" and not estado["cauciones_abiertas"]:
        print(f"[PAPER] Cauciones cerradas — {estado['estado']}")
        return False
    return True


def _evaluar_rentabilidad(ganancia_neta, capital_usado, ganancia_minima_pct, tipo):
    ganancia_minima = capital_usado * (ganancia_minima_pct / 100)
    rentable = ganancia_neta >= ganancia_minima
    if not rentable:
        print(f"[PAPER] Descartado por baja rentabilidad:")
        print(f"  Ganancia neta:   ${ganancia_neta:,.2f} ARS")
        print(f"  Minimo exigido:  ${ganancia_minima:,.2f} ARS ({ganancia_minima_pct:.1f}%)")
    else:
        print(f"[PAPER] Rentabilidad OK: ${ganancia_neta:,.2f} ARS (min: ${ganancia_minima:,.2f})")
    return rentable


# ──────────────────────────────────────────────────────────────────
# EJECUTORES
# ──────────────────────────────────────────────────────────────────

def ejecutar_caucion_paper(tasa_anual, monto_solicitado=None, forzar_todo=False):
    """
    Simula colocacion de pesos en caucion.
    forzar_todo=True: usa todo el capital disponible (modo cierre 17-18hs)
    """
    if not _verificar_puede_operar("CAUCION"):
        return None
    if not _capital_habilitado_para_operar():
        return None

    cfg    = cargar_config()
    estado = estado_mercado()
    plazo  = plazo_caucion_dias()
    disp   = capital_disponible()
    cap_restante_dia, tope_dia, usado_hoy = _cap_diario_restante()

    # Determinar monto
    cierre_total = forzar_todo or estado["es_cierre_caucion"]
    monto_max    = _monto_maximo("CAUCION", cierre_total=cierre_total)
    monto_max    = min(monto_max, cap_restante_dia)

    if monto_solicitado is not None:
        monto = min(monto_solicitado, monto_max)
    else:
        monto = monto_max

    if monto <= 0:
        print(f"[PAPER] Sin capital disponible para caucionar.")
        if cap_restante_dia <= 0:
            print(f"[PAPER] Limite diario alcanzado: ${usado_hoy:,.2f}/${tope_dia:,.2f} ARS.")
        return None

    # Si el monto solicitado supera el disponible, alertar
    if monto_solicitado and monto_solicitado > disp:
        registrar_oportunidad_perdida(
            tipo="CAUCION", simbolo=f"CAUCION_{plazo}D",
            ganancia_estimada=monto_solicitado * (tasa_anual / 365 / 100),
            capital_necesario=monto_solicitado,
            capital_disponible_actual=disp,
            motivo="Capital insuficiente"
        )

    # Calcular ganancia
    tasa_periodo   = tasa_anual * plazo / 365
    ganancia_bruta = monto * (tasa_periodo / 100)
    comision       = monto * cfg["comision_iol_pct"] / 100
    slippage       = monto * cfg["slippage_pct"] / 100
    ganancia_neta  = round(ganancia_bruta - comision - slippage, 2)

    # Evaluar rentabilidad
    if not _evaluar_rentabilidad(ganancia_neta, monto,
                                  cfg["ganancia_minima_caucion_pct"], "CAUCION"):
        return None

    # Registrar
    ahora = datetime.now().isoformat()
    conn  = conectar()
    c     = conn.cursor()
    c.execute("""
        INSERT INTO operaciones_paper
        (timestamp, tipo, simbolo, accion, precio_entrada,
         cantidad, capital_usado, comision, ganancia_neta, estado)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ahora, "CAUCION", f"CAUCION_{plazo}D", "COLOCAR",
          tasa_anual, plazo, monto,
          round(comision + slippage, 2), ganancia_neta, "ABIERTA"))
    conn.commit()
    conn.close()

    viernes_txt = " (VIERNES → LUNES)" if estado["es_viernes"] else ""
    print(f"\n[PAPER] CAUCION EJECUTADA{viernes_txt}")
    print(f"  Plazo:          {plazo} dia(s)")
    print(f"  Monto:          ${monto:,.2f} ARS")
    print(f"  Tasa:           {tasa_anual:.2f}% TNA")
    print(f"  Ganancia bruta: ${ganancia_bruta:.2f} ARS")
    print(f"  Costos:         ${comision+slippage:.2f} ARS")
    print(f"  Ganancia neta:  ${ganancia_neta:.2f} ARS")
    if cierre_total:
        print(f"  [Modo cierre: se cauciono todo el capital disponible]")

    return ganancia_neta


def ejecutar_arbitraje_paper(simbolo, precio_ars, precio_usd, ratio,
                              ccl_implicito, ccl_referencia, cantidad=None):
    """
    Simula arbitraje CEDEAR vs NYSE con gestión de capital (máx 30%).
    """
    if not _verificar_puede_operar("ARBITRAJE"):
        return None
    if not _capital_habilitado_para_operar():
        return None

    cfg       = cargar_config()
    disp      = capital_disponible()
    monto_max = _monto_maximo("ARBITRAJE")
    cap_restante_dia, tope_dia, usado_hoy = _cap_diario_restante()
    monto_max = min(monto_max, cap_restante_dia)
    base_capital, _ = capital_base_actual()
    hard_cap_operacion = max(0.0, base_capital * MAX_CAPITAL_POR_OPERACION)
    monto_max = min(monto_max, hard_cap_operacion)

    if monto_max <= 0:
        print("[PAPER] Bloqueado por limites de riesgo: sin cupo operativo.")
        if cap_restante_dia <= 0:
            print(f"        Limite diario alcanzado: ${usado_hoy:,.2f}/${tope_dia:,.2f} ARS.")
        return None

    # Calcular cuántas unidades entran con el capital máximo
    if cantidad is None:
        cantidad = max(1, int(monto_max / precio_ars))

    capital_necesario = precio_ars * cantidad

    if capital_necesario > disp:
        registrar_oportunidad_perdida(
            tipo="ARBITRAJE", simbolo=simbolo,
            ganancia_estimada=capital_necesario * abs(ccl_implicito - ccl_referencia) / ccl_referencia,
            capital_necesario=capital_necesario,
            capital_disponible_actual=disp,
            motivo="Capital insuficiente"
        )
        return None

    if capital_necesario > monto_max:
        cantidad = max(1, int(monto_max / precio_ars))
        capital_necesario = precio_ars * cantidad

    spread_pct     = ((ccl_implicito - ccl_referencia) / ccl_referencia) * 100
    ganancia_bruta = capital_necesario * (spread_pct / 100)
    comision       = capital_necesario * cfg["comision_iol_pct"] / 100 * 2
    slippage       = capital_necesario * cfg["slippage_pct"] / 100 * 2
    ganancia_neta  = round(ganancia_bruta - comision - slippage, 2)

    if not _evaluar_rentabilidad(ganancia_neta, capital_necesario,
                                  cfg["ganancia_minima_arbitraje_pct"], "ARBITRAJE"):
        return None

    ahora = datetime.now().isoformat()
    conn  = conectar()
    c     = conn.cursor()
    c.execute("""
        INSERT INTO operaciones_paper
        (timestamp, tipo, simbolo, accion, precio_entrada,
         cantidad, capital_usado, comision, ganancia_neta, estado)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ahora, "ARBITRAJE", simbolo, "VENTA_CEDEAR", precio_ars,
          cantidad, capital_necesario,
          round(comision + slippage, 2), ganancia_neta, "ABIERTA"))
    conn.commit()
    conn.close()

    print(f"\n[PAPER] ARBITRAJE EJECUTADO")
    print(f"  Simbolo:        {simbolo}")
    print(f"  Spread:         {spread_pct:+.2f}%")
    print(f"  Cantidad:       {cantidad} CEDEARs")
    print(f"  Capital:        ${capital_necesario:,.2f} ARS ({capital_necesario/disp*100:.0f}% del disponible)")
    print(f"  Ganancia neta:  ${ganancia_neta:,.2f} ARS")

    return ganancia_neta


def mostrar_resumen():
    conn = conectar()
    c = conn.cursor()
    c.execute("SELECT COUNT(*), COALESCE(SUM(ganancia_neta),0) FROM operaciones_paper")
    total, gan = c.fetchone()
    c.execute("SELECT COUNT(*), COALESCE(SUM(ganancia_neta),0) FROM operaciones_paper WHERE tipo='CAUCION'")
    tc, gc = c.fetchone()
    c.execute("SELECT COUNT(*), COALESCE(SUM(ganancia_neta),0) FROM operaciones_paper WHERE tipo='ARBITRAJE'")
    ta, ga = c.fetchone()
    conn.close()
    disp = capital_disponible()
    cap_base, fuente = capital_base_actual()
    print(f"\n{'='*55}")
    print(f"  RESUMEN PAPER TRADING")
    print(f"{'='*55}")
    print(f"  Capital base:       ${cap_base:,.2f} ARS ({fuente})")
    print(f"  Capital disponible:  ${disp:,.2f} ARS")
    print(f"  Cauciones:           {tc} ops → ${gc:,.2f} ARS")
    print(f"  Arbitrajes:          {ta} ops → ${ga:,.2f} ARS")
    print(f"  Ganancia total:      ${gan:,.2f} ARS")
    print(f"{'='*55}")


if __name__ == "__main__":
    estado = estado_mercado()
    print(f"Mercado: {estado['estado']}")
    print(f"Modo:    {estado['modo'].upper()}")
    print(f"Plazo caucion hoy: {plazo_caucion_dias()} dia(s)\n")

    print("Test: Caucion normal (70% del capital)")
    ejecutar_caucion_paper(tasa_anual=85.0)

    print("\nTest: Caucion cierre total (todo el disponible)")
    ejecutar_caucion_paper(tasa_anual=120.0, forzar_todo=True)

    print("\nTest: Arbitraje AAPL (max 30% del capital)")
    ejecutar_arbitraje_paper(
        simbolo="AAPL", precio_ars=19140.0, precio_usd=227.50,
        ratio=20, ccl_implicito=1517.0, ccl_referencia=1445.0
    )

    mostrar_resumen()
