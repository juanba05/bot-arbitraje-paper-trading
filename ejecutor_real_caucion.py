"""
ejecutor_real_caucion.py
------------------------
Punto de entrada para ejecucion real de cauciones.
Delega en ejecutor_selenium_caucion.py para el flujo web de IOL.

Guardas de seguridad:
  - real_caucion_enabled debe ser True en dashboard_config.json
  - Idempotencia por ciclo_id (una sola orden por ciclo)
  - Monto maximo configurable
  - Modo canario para pruebas con monto minimo
"""

import json
import os
import sqlite3
import logging

from config import RUTA_DATOS, NOMBRE_DB, COMISION_CAUCION_PCT
from ejecutor_paper import capital_disponible
from motor_cauciones import (
    registrar_intento_orden_real_caucion,
    actualizar_orden_real_caucion,
)

log = logging.getLogger("ejecutor_real")

RUTA_CONFIG = os.path.join(RUTA_DATOS, "dashboard_config.json")
RUTA_DB     = os.path.join(RUTA_DATOS, NOMBRE_DB)

DEFAULTS_REAL = {
    "real_caucion_enabled":          False,
    "real_caucion_canary_mode":      True,
    "real_caucion_canary_amount_ars": 20000.0,
    "real_caucion_max_monto_ars":    20000.0,
    "real_caucion_headless":         False,
}

ESTADOS_IDEMPOTENTES = {
    "PENDIENTE_ENVIO", "ENVIADA", "ENVIADA_SIN_ID",
    "PENDIENTE", "CONFIRMADA", "FILLED", "PARCIAL", "COLOCADA",
}


def _cfg():
    cfg = {}
    if os.path.exists(RUTA_CONFIG):
        try:
            with open(RUTA_CONFIG, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    for k, v in DEFAULTS_REAL.items():
        cfg.setdefault(k, v)
    return cfg


def _ya_ejecutado_en_ciclo(ciclo_id):
    if not ciclo_id:
        return False
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur  = conn.cursor()
        marks  = ",".join(["?"] * len(ESTADOS_IDEMPOTENTES))
        params = [str(ciclo_id)] + list(ESTADOS_IDEMPOTENTES)
        cur.execute(
            f"SELECT COUNT(*) FROM cauciones_ordenes_real WHERE ciclo_id=? AND estado IN ({marks})",
            params,
        )
        n = int(cur.fetchone()[0] or 0)
        conn.close()
        return n > 0
    except Exception:
        return False


def _monto_objetivo(cfg, forzar_todo=False):
    disp = max(0.0, capital_disponible())
    if disp <= 0:
        return 0.0
    if bool(cfg.get("real_caucion_canary_mode", True)):
        base = min(disp, float(cfg.get("real_caucion_canary_amount_ars", 1000.0)))
    elif forzar_todo:
        base = disp
    else:
        pct  = float(cfg.get("max_capital_caucion_pct", 70.0))
        base = disp * min(max(pct, 0.0), 100.0) / 100.0
    tope = float(cfg.get("real_caucion_max_monto_ars", 5000.0))
    return round(min(base, tope) if tope > 0 else base, 2)


def _ganancia_estimada(monto, tna, plazo):
    gan  = float(monto) * (float(tna) / 100.0) * (max(1, int(plazo)) / 365.0)
    com  = float(monto) * (COMISION_CAUCION_PCT / 100.0)
    return round(gan - com, 2)


def ejecutar_caucion_real(resultado_caucion, ciclo_id, forzar_todo=False):
    """
    Ejecuta una caucion real via Selenium.

    Parametros:
        resultado_caucion : dict devuelto por analizar_cauciones()
        ciclo_id          : string unico por ciclo (para idempotencia)
        forzar_todo       : True = usar todo el capital disponible

    Devuelve dict con: ok, estado, detalle, ganancia_neta_real
    """
    cfg = _cfg()

    # ── Guardia 1: kill switch ──────────────────────────────────
    if not bool(cfg.get("real_caucion_enabled", False)):
        return {"ok": False, "estado": "BLOQUEADA_CONFIG",
                "detalle": "real_caucion_enabled=false en dashboard_config.json"}

    # ── Guardia 2: idempotencia ─────────────────────────────────
    if _ya_ejecutado_en_ciclo(ciclo_id):
        return {"ok": False, "estado": "BLOQUEADA_IDEMPOTENCIA",
                "detalle": f"Ya existe una orden para el ciclo: {ciclo_id}"}

    # ── Guardia 3: señal valida ─────────────────────────────────
    if not resultado_caucion or not bool(resultado_caucion.get("tiene_senal")):
        return {"ok": False, "estado": "SIN_SENAL"}

    plazo = int(resultado_caucion.get("plazo", 1))
    tna   = float(resultado_caucion.get("tna", resultado_caucion.get("tasa", 0.0)))
    if tna <= 0:
        return {"ok": False, "estado": "TASA_INVALIDA"}

    monto = _monto_objetivo(cfg, forzar_todo=forzar_todo)
    if monto <= 0:
        return {"ok": False, "estado": "SIN_CAPITAL",
                "detalle": "Capital disponible insuficiente"}

    # ── Registrar intento ───────────────────────────────────────
    orden_id = registrar_intento_orden_real_caucion(
        ciclo_id       = ciclo_id,
        plazo_dias     = plazo,
        tna_objetivo   = tna,
        monto_objetivo = monto,
        execution_mode = "real",
        source         = "BOT_PRINCIPAL",
        request_payload= {"monto": monto, "plazo": plazo, "tna": tna},
    )

    # ── Ejecutar via Selenium ───────────────────────────────────
    try:
        from ejecutor_selenium_caucion import ejecutar_caucion_selenium
        headless = bool(cfg.get("real_caucion_headless", False))
        resultado = ejecutar_caucion_selenium(
            monto      = monto,
            plazo      = plazo,
            tna_minima = tna,
            headless   = headless,
        )
    except Exception as e:
        actualizar_orden_real_caucion(
            orden_real_id   = orden_id,
            estado          = "ERROR_SELENIUM",
            mensaje_error   = str(e),
            response_payload= {},
        )
        return {"ok": False, "estado": "ERROR_SELENIUM", "detalle": str(e)}

    # ── Guardar resultado ───────────────────────────────────────
    estado_db = "COLOCADA" if resultado.get("ok") else resultado.get("estado", "ERROR")
    actualizar_orden_real_caucion(
        orden_real_id   = orden_id,
        estado          = estado_db,
        id_transaccion  = resultado.get("id_op"),
        mensaje_error   = None if resultado.get("ok") else resultado.get("detalle"),
        response_payload= resultado,
    )

    if resultado.get("ok"):
        gan = _ganancia_estimada(monto, tna, plazo)
        resultado["ganancia_neta_real"] = gan
        log.info(f"  Caucion real colocada. Ganancia estimada: ARS {gan:.2f}")

    return resultado
