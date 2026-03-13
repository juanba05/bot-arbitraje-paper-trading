"""
bot_principal.py - Orquestador principal del bot de cauciones.
Ciclo principal: cada 30 segundos evalua si hay senal, y si la hay ejecuta.
"""

import os
import sys
import json
import time
import logging
import sqlite3
from datetime import datetime, timedelta

from config import (
    RUTA_DATOS, RUTA_LOGS, NOMBRE_DB,
    INTERVALO_ACTUALIZACION,
    MAX_NEGATIVAS_CONSECUTIVAS,
    MAX_FALLAS_API_CONSEC,
    CIRCUIT_BREAKER_MINUTOS,
)
from mercado import estado_mercado
from motor_cauciones import analizar_cauciones
from ejecutor_paper import ejecutar_caucion_paper, capital_disponible, mostrar_resumen
from ejecutor_real_caucion import ejecutar_caucion_real

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RUTA_BOT_ON     = os.path.join(RUTA_DATOS, "bot_activo.json")
RUTA_ESTADO_BOT = os.path.join(RUTA_DATOS, "estado_bot.json")
RUTA_CONFIG     = os.path.join(RUTA_DATOS, "dashboard_config.json")
RUTA_DB         = os.path.join(RUTA_DATOS, NOMBRE_DB)

# ── LOGGING ──────────────────────────────────────────────────────

os.makedirs(RUTA_LOGS, exist_ok=True)
log_file = os.path.join(RUTA_LOGS, f"bot_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("bot_principal")


# ── HELPERS ──────────────────────────────────────────────────────

def bot_esta_activo():
    try:
        if os.path.exists(RUTA_BOT_ON):
            with open(RUTA_BOT_ON) as f:
                return json.load(f).get("activo", True)
    except Exception:
        pass
    return True


def cargar_config():
    try:
        if os.path.exists(RUTA_CONFIG):
            with open(RUTA_CONFIG) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def guardar_estado(estado, ciclos, seniales_hoy, ganancias_hoy, execution_mode="paper"):
    datos = {
        "timestamp":      datetime.now().isoformat(),
        "estado":         estado,
        "execution_mode": execution_mode,
        "ciclos":         ciclos,
        "seniales_hoy":   seniales_hoy,
        "ganancias_hoy":  ganancias_hoy,
        "capital":        capital_disponible(),
    }
    with open(RUTA_ESTADO_BOT, "w") as f:
        json.dump(datos, f, indent=2)


def resolver_execution_mode(cfg):
    mode = str(cfg.get("execution_mode", "paper")).lower().strip()
    return mode if mode in ("paper", "real") else "paper"


def _fuera_de_horario(ahora):
    """Despues de las 17:15 de lunes a viernes, el bot descansa."""
    if ahora.weekday() >= 5:
        return False
    return (ahora.hour, ahora.minute) >= (17, 15)


# ── CICLO DE CAUCIONES ────────────────────────────────────────────

def ciclo_cauciones(forzar_todo, execution_mode, ciclo_id):
    tipo = "CIERRE" if forzar_todo else "NORMAL"
    log.info(f"Ciclo CAUCIONES [{tipo}] (modo: {execution_mode.upper()})...")

    try:
        resultado = analizar_cauciones(modo="real")

        if not resultado or not resultado.get("tiene_senal"):
            log.info("  Sin senal en este ciclo.")
            return 0.0

        tna   = float(resultado.get("tna", resultado.get("tasa", 0)))
        plazo = int(resultado.get("plazo", 1))
        log.info(f"  Senal detectada: {tna:.2f}% TNA a {plazo} dia(s)")

        if execution_mode == "real":
            out = ejecutar_caucion_real(
                resultado_caucion = resultado,
                ciclo_id          = ciclo_id,
                forzar_todo       = forzar_todo,
            )
            if out.get("ok"):
                gan = float(out.get("ganancia_neta_real", 0.0) or 0.0)
                log.info(f"  Caucion REAL colocada. Ganancia estimada: ARS {gan:.2f}")
                return gan
            else:
                log.warning(f"  Caucion REAL no ejecutada: {out.get('estado')} — {out.get('detalle','')}")
                return 0.0
        else:
            ganancia = ejecutar_caucion_paper(tasa_anual=tna, forzar_todo=forzar_todo)
            if ganancia is not None:
                log.info(f"  Caucion PAPER ejecutada. Ganancia estimada: ARS {ganancia:.2f}")
                return ganancia
            else:
                log.info("  Caucion PAPER descartada (capital insuficiente o baja rentabilidad).")
                return 0.0

    except Exception as e:
        log.error(f"Error en ciclo de cauciones: {e}")
        return 0.0


# ── LOOP PRINCIPAL ────────────────────────────────────────────────

def iniciar():
    log.info("=" * 60)
    log.info("  BOT DE CAUCIONES IOL — INICIANDO")
    log.info(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info("=" * 60)

    ciclos            = 0
    seniales_hoy      = 0
    ganancias_hoy     = 0.0
    ultimo_dia        = datetime.now().date()
    perdidas_consec   = 0
    fallas_api_consec = 0
    circuit_hasta     = None

    def activar_circuit_breaker(motivo):
        nonlocal circuit_hasta, perdidas_consec, fallas_api_consec
        circuit_hasta     = datetime.now() + timedelta(minutes=CIRCUIT_BREAKER_MINUTOS)
        perdidas_consec   = 0
        fallas_api_consec = 0
        log.error(
            f"CIRCUIT BREAKER activado por {CIRCUIT_BREAKER_MINUTOS} min | "
            f"Motivo: {motivo} | Hasta: {circuit_hasta.strftime('%H:%M:%S')}"
        )

    try:
        while True:
            ahora = datetime.now()

            # ── Fin de jornada ──────────────────────────────────
            if _fuera_de_horario(ahora):
                log.info("Fin de jornada (17:15). Bot en pausa hasta la proxima rueda.")
                guardar_estado("fin_jornada", ciclos, seniales_hoy, ganancias_hoy)
                time.sleep(60)
                continue

            # ── Reset diario ────────────────────────────────────
            if ahora.date() != ultimo_dia:
                log.info("Nuevo dia — reseteando contadores.")
                seniales_hoy      = 0
                ganancias_hoy     = 0.0
                ultimo_dia        = ahora.date()
                perdidas_consec   = 0
                fallas_api_consec = 0

            # ── Kill switch del dashboard ───────────────────────
            if not bot_esta_activo():
                log.info("Bot APAGADO desde el dashboard.")
                guardar_estado("apagado", ciclos, seniales_hoy, ganancias_hoy)
                time.sleep(30)
                continue

            # ── Circuit breaker ─────────────────────────────────
            if circuit_hasta and ahora < circuit_hasta:
                restante = int((circuit_hasta - ahora).total_seconds())
                log.warning(f"Circuit breaker activo. Reanuda en {restante}s.")
                guardar_estado("circuit_breaker", ciclos, seniales_hoy, ganancias_hoy)
                time.sleep(min(INTERVALO_ACTUALIZACION, 30))
                continue
            if circuit_hasta and ahora >= circuit_hasta:
                log.info("Circuit breaker finalizado.")
                circuit_hasta = None

            # ── Estado del mercado ──────────────────────────────
            estado         = estado_mercado()
            cfg            = cargar_config()
            execution_mode = resolver_execution_mode(cfg)
            modo           = estado["modo"]
            ciclos        += 1

            log.info(
                f"── Ciclo #{ciclos} | Mercado: {modo.upper()} | "
                f"Ejec: {execution_mode.upper()} | {estado['hora_arg']} ──"
            )

            # ── Cauciones solo en horario valido ────────────────
            if modo == "cerrado":
                log.info("  Mercado cerrado — sin operaciones.")
                guardar_estado("cerrado", ciclos, seniales_hoy, ganancias_hoy, execution_mode)
                time.sleep(INTERVALO_ACTUALIZACION)
                continue

            if not estado["cauciones_abiertas"]:
                log.info("  Cauciones cerradas en este momento.")
                guardar_estado("cauciones_cerradas", ciclos, seniales_hoy, ganancias_hoy, execution_mode)
                time.sleep(INTERVALO_ACTUALIZACION)
                continue

            # ── Ejecutar ciclo ──────────────────────────────────
            ciclo_id = f"{ahora.date().isoformat()}_{ciclos}"
            try:
                ganancia = ciclo_cauciones(
                    forzar_todo    = estado["es_cierre_caucion"],
                    execution_mode = execution_mode,
                    ciclo_id       = ciclo_id,
                )
                if ganancia > 0:
                    seniales_hoy  += 1
                    ganancias_hoy += ganancia
                    perdidas_consec = 0
                elif ganancia < 0:
                    perdidas_consec += 1
                    log.warning(f"Operacion negativa ({perdidas_consec}/{MAX_NEGATIVAS_CONSECUTIVAS})")
                    if perdidas_consec >= MAX_NEGATIVAS_CONSECUTIVAS:
                        activar_circuit_breaker("operaciones negativas consecutivas")

            except Exception as e:
                log.error(f"Error inesperado en ciclo: {e}")
                fallas_api_consec += 1
                if fallas_api_consec >= MAX_FALLAS_API_CONSEC:
                    activar_circuit_breaker("errores consecutivos en ciclo")

            guardar_estado("corriendo", ciclos, seniales_hoy, ganancias_hoy, execution_mode)

            # ── Resumen cada 10 ciclos ──────────────────────────
            if ciclos % 10 == 0:
                log.info(f"  Resumen: señales={seniales_hoy} | ganancia ARS {ganancias_hoy:,.2f} | capital ARS {capital_disponible():,.2f}")

            log.info(f"  Esperando {INTERVALO_ACTUALIZACION}s...\n")
            time.sleep(INTERVALO_ACTUALIZACION)

    except KeyboardInterrupt:
        log.info("Bot detenido por el usuario (Ctrl+C).")
        mostrar_resumen()

    except Exception as e:
        log.critical(f"Error fatal: {e}", exc_info=True)


if __name__ == "__main__":
    iniciar()
