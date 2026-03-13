"""
ejecutor_real_caucion.py
------------------------
Ejecucion real de cauciones con guardas de seguridad e idempotencia.

Estado actual:
  - El flujo CPD fue descartado: corresponde a cheques de pago diferido.
  - La caucion real de IOL se confirmo como flujo web:
      /Operar/Caucionar -> /Operar/ConfirmarCaucion -> /Operar/CaucionExitosa
  - Falta automatizacion de navegador para completar ese flujo.
"""

import json
import os
import sqlite3

from config import RUTA_DATOS, NOMBRE_DB, COMISION_CAUCION_PCT
from ejecutor_paper import capital_disponible
from motor_cauciones import (
    registrar_intento_orden_real_caucion,
    actualizar_orden_real_caucion,
)

RUTA_CONFIG = os.path.join(RUTA_DATOS, "dashboard_config.json")
RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)

DEFAULTS_REAL = {
    "real_caucion_enabled": False,
    "real_caucion_backend": "web",
    "real_caucion_canary_mode": True,
    "real_caucion_canary_amount_ars": 1000.0,
    "real_caucion_max_monto_ars": 5000.0,
    "real_caucion_browser": "edge",
    "real_caucion_headless": False,
}

ESTADOS_IDEMPOTENTES = {
    "PENDIENTE_ENVIO",
    "ENVIADA",
    "ENVIADA_SIN_ID",
    "PENDIENTE",
    "CONFIRMADA",
    "FILLED",
    "PARCIAL",
}


def _cargar_cfg():
    cfg = {}
    if os.path.exists(RUTA_CONFIG):
        try:
            with open(RUTA_CONFIG, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    for k, v in DEFAULTS_REAL.items():
        cfg.setdefault(k, v)
    return cfg


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return int(default)


def _ya_hay_orden_para_ciclo(ciclo_id):
    if not ciclo_id:
        return False
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        marks = ",".join(["?"] * len(ESTADOS_IDEMPOTENTES))
        params = [str(ciclo_id)] + list(ESTADOS_IDEMPOTENTES)
        cur.execute(
            f"""
            SELECT COUNT(*) FROM cauciones_ordenes_real
            WHERE ciclo_id=?
              AND estado IN ({marks})
            """,
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
    if forzar_todo:
        base = disp
    elif bool(cfg.get("real_caucion_canary_mode", True)):
        base = min(disp, _safe_float(cfg.get("real_caucion_canary_amount_ars", 1000.0), 1000.0))
    else:
        pct = _safe_float(cfg.get("max_capital_caucion_pct", 70.0), 70.0)
        pct = max(0.0, min(100.0, pct))
        base = disp * (pct / 100.0)
    max_monto = _safe_float(cfg.get("real_caucion_max_monto_ars", 5000.0), 5000.0)
    if max_monto > 0:
        base = min(base, max_monto)
    return round(max(0.0, base), 2)


def _estimar_ganancia_neta(monto, tna, plazo):
    gan_bruta = float(monto) * (float(tna) / 100.0) * (max(1, int(plazo)) / 365.0)
    comision = float(monto) * (COMISION_CAUCION_PCT / 100.0)
    return round(gan_bruta - comision, 2)


def ejecutar_caucion_real(resultado_caucion, ciclo_id, forzar_todo=False):
    """
    Punto de entrada para operativa real de caucion.

    El backend CPD fue eliminado porque no corresponde a cauciones.
    Hasta implementar automatizacion web real, el modulo deja trazabilidad
    y devuelve un bloqueo explicito, evitando intentos contra endpoints falsos.
    """
    cfg = _cargar_cfg()
    if not bool(cfg.get("real_caucion_enabled", False)):
        return {"ok": False, "estado": "BLOQUEADA_CONFIG", "detalle": "real_caucion_enabled=false"}

    if _ya_hay_orden_para_ciclo(ciclo_id):
        return {"ok": False, "estado": "BLOQUEADA_IDEMPOTENCIA", "detalle": f"ciclo_id duplicado: {ciclo_id}"}

    if not resultado_caucion or not bool(resultado_caucion.get("tiene_senal")):
        return {"ok": False, "estado": "SIN_SENAL"}

    plazo = _safe_int(resultado_caucion.get("plazo"), 1)
    tna = _safe_float(resultado_caucion.get("tna", resultado_caucion.get("tasa", 0.0)), 0.0)
    if tna <= 0:
        return {"ok": False, "estado": "TASA_INVALIDA"}

    monto = _monto_objetivo(cfg, forzar_todo=forzar_todo)
    if monto <= 0:
        return {"ok": False, "estado": "SIN_CAPITAL"}

    backend = str(cfg.get("real_caucion_backend", "web")).lower().strip() or "web"
    payload = {
        "backend": backend,
        "monto_objetivo": monto,
        "plazo_dias": plazo,
        "tna_objetivo": tna,
        "flujo_web_confirmado": [
            "/Operar/Caucionar",
            "/Operar/ConfirmarCaucion",
            "/Operar/CaucionExitosa",
        ],
    }
    orden_local_id = registrar_intento_orden_real_caucion(
        ciclo_id=ciclo_id,
        plazo_dias=plazo,
        tna_objetivo=tna,
        monto_objetivo=monto,
        execution_mode="real",
        source="BOT_PRINCIPAL",
        request_payload=payload,
    )

    if backend != "web":
        detalle = f"Backend real_caucion_backend={backend} no soportado. Usar 'web'."
        actualizar_orden_real_caucion(
            orden_real_id=orden_local_id,
            estado="BACKEND_INVALIDO",
            mensaje_error=detalle,
            response_payload=payload,
        )
        return {"ok": False, "estado": "BACKEND_INVALIDO", "detalle": detalle}

    detalle = (
        "Ruta CPD eliminada. La caucion real en IOL es un flujo web "
        "(/Operar/Caucionar -> /Operar/ConfirmarCaucion -> /Operar/CaucionExitosa). "
        "Falta automatizacion de navegador para completar ese flujo."
    )
    actualizar_orden_real_caucion(
        orden_real_id=orden_local_id,
        estado="PENDIENTE_AUTOMATIZACION_WEB",
        mensaje_error=detalle,
        response_payload={
            "detalle": detalle,
            "ganancia_neta_estimativa": _estimar_ganancia_neta(monto, tna, plazo),
            "browser_sugerido": cfg.get("real_caucion_browser", "edge"),
            "headless": bool(cfg.get("real_caucion_headless", False)),
        },
    )
    return {
        "ok": False,
        "estado": "PENDIENTE_AUTOMATIZACION_WEB",
        "detalle": detalle,
    }
