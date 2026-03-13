"""
bot_principal.py - Orquestador principal del bot de arbitraje.
ACTUALIZADO: operativa sin after-hours y con control estricto de datos.
"""

import os
import sys
import json
import time
import logging
import sqlite3
from datetime import datetime, timedelta

from config import (
    RUTA_DATOS,
    RUTA_LOGS,
    NOMBRE_DB,
    INTERVALO_ACTUALIZACION,
    MAX_NEGATIVAS_CONSECUTIVAS,
    MAX_FALLAS_API_CONSEC,
    CIRCUIT_BREAKER_MINUTOS,
    MAX_EDAD_CCL_MIN,
    MAX_EDAD_PRECIOS_NYSE_MIN,
)
from mercado import estado_mercado
from obtener_ccl import obtener_ccl
from recolector import recolectar_todo
from motor_calculo import calcular_spreads_real
from motor_cauciones import analizar_cauciones
from ejecutor_paper import (
    ejecutar_caucion_paper,
    capital_disponible,
    mostrar_resumen,
)
from ejecutor_real_caucion import ejecutar_caucion_real
from simulador_operaciones import detectar_horario_nyse

# Evita fallas por consola cp1252 en Windows cuando hay caracteres Unicode.
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


def guardar_estado(modo, ciclos, seniales_hoy, ganancias_hoy, horario_nyse="—", execution_mode="paper"):
    estado = {
        "timestamp":     datetime.now().isoformat(),
        "modo":          modo,
        "execution_mode": execution_mode,
        "ciclos":        ciclos,
        "seniales_hoy":  seniales_hoy,
        "ganancias_hoy": ganancias_hoy,
        "capital":       capital_disponible(),
        "horario_nyse":  horario_nyse,
    }
    with open(RUTA_ESTADO_BOT, "w") as f:
        json.dump(estado, f, indent=2)


def necesita_recolectar(ultima_recoleccion, intervalo_min=60):
    if ultima_recoleccion is None:
        return True
    return (datetime.now() - ultima_recoleccion).seconds > intervalo_min * 60


def cargar_dashboard_config():
    try:
        if os.path.exists(RUTA_CONFIG):
            with open(RUTA_CONFIG) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def resolver_modo_bot(modo_horario, cfg):
    modo_forzado = str(cfg.get("modo_forzado_bot", "auto")).lower().strip()
    if modo_forzado in ("arbitraje", "mixto", "caucion"):
        return modo_forzado, True
    return modo_horario, False


def resolver_execution_mode(cfg):
    mode = str(cfg.get("execution_mode", "paper")).lower().strip()
    if mode not in ("paper", "real"):
        return "paper"
    return mode


def _edad_min_ultimo_registro(tabla, campo_ts="timestamp"):
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute(f"SELECT {campo_ts} FROM {tabla} ORDER BY {campo_ts} DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        ts = datetime.fromisoformat(str(row[0]))
        return max(0.0, (datetime.now() - ts).total_seconds() / 60.0)
    except Exception:
        return None


def _datos_actualizados_para_operar(modo):
    edad_ccl = _edad_min_ultimo_registro("ccl_historico", "timestamp")
    if edad_ccl is None or edad_ccl > MAX_EDAD_CCL_MIN:
        return False, f"CCL desactualizado ({'sin dato' if edad_ccl is None else f'{edad_ccl:.1f} min'})"

    if modo in ("arbitraje", "mixto"):
        edad_nyse = _edad_min_ultimo_registro("precios_nyse", "timestamp")
        if edad_nyse is None or edad_nyse > MAX_EDAD_PRECIOS_NYSE_MIN:
            return False, f"Precios NYSE desactualizados ({'sin dato' if edad_nyse is None else f'{edad_nyse:.1f} min'})"

    return True, "OK"


def _fuera_horario_trabajo_diario(ahora):
    """
    Cierre operativo diario del bot.
    Regla: de lunes a viernes, luego de 17:15 no se procesa trabajo del dia.
    """
    if ahora.weekday() >= 5:
        return False
    return (ahora.hour, ahora.minute) >= (17, 15)


# ── LÓGICA POR MODO ──────────────────────────────────────────────

def ciclo_arbitraje(ccl):
    log.info("Ciclo ARBITRAJE — calculando spreads CEDEARs...")
    seniales = calcular_spreads_real(ccl, capital_disponible=capital_disponible())
    return seniales or 0


def ciclo_cauciones(ccl, forzar_todo=False, modo_datos="real", execution_mode="paper", ciclo_id=None):
    tipo = "CIERRE" if forzar_todo else "NORMAL"
    log.info(f"Ciclo CAUCIONES [{tipo}] — verificando tasas (modo datos: {modo_datos})...")
    try:
        resultado = analizar_cauciones(modo=modo_datos)
        if resultado and resultado.get("tiene_senal"):
            tasa = resultado.get("tna", resultado.get("tasa", 0))
            log.info(f"  Señal detectada: tasa {tasa:.2f}% TNA")
            if execution_mode == "real":
                out = ejecutar_caucion_real(
                    resultado_caucion=resultado,
                    ciclo_id=ciclo_id or f"cycle_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    forzar_todo=forzar_todo,
                )
                if out.get("ok"):
                    gan_real = float(out.get("ganancia_neta_real", 0.0) or 0.0)
                    log.info(f"  Caucion REAL {out.get('estado')}. Ganancia real estimada: ${gan_real:.2f} ARS")
                    return gan_real
                log.warning(f"  Caucion REAL no confirmada: {out.get('estado')} ({out.get('detalle','sin detalle')})")
                return 0
            else:
                ganancia = ejecutar_caucion_paper(tasa_anual=tasa, forzar_todo=forzar_todo)
                if ganancia is not None:
                    log.info(f"  Caución ejecutada. Ganancia estimada: ${ganancia:.2f} ARS")
                    return ganancia
                else:
                    log.info("  Caución descartada por baja rentabilidad o capital insuficiente.")
        else:
            log.info("  Sin señal de caucion en este ciclo.")
    except Exception as e:
        log.error(f"Error en ciclo de cauciones: {e}")
    return 0


def ciclo_mixto(ccl, modo_datos_caucion="real"):
    log.info("Ciclo MIXTO — arbitraje + cauciones...")
    seniales     = ciclo_arbitraje(ccl)
    ganancia_cau = ciclo_cauciones(ccl, forzar_todo=False, modo_datos=modo_datos_caucion)
    return seniales, ganancia_cau


# ── LOOP PRINCIPAL ────────────────────────────────────────────────

def iniciar():
    log.info("=" * 65)
    log.info("  BOT DE ARBITRAJE CEDEARs — INICIANDO")
    log.info(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info("=" * 65)
    log.info("Para detener el bot: Ctrl + C")
    log.info("")

    ultima_recoleccion = None
    ciclos             = 0
    seniales_hoy       = 0
    ganancias_hoy      = 0.0
    ultimo_dia         = datetime.now().date()
    perdidas_consec    = 0
    fallas_api_consec  = 0
    circuit_hasta      = None

    def activar_circuit_breaker(motivo):
        nonlocal circuit_hasta, perdidas_consec, fallas_api_consec
        circuit_hasta = datetime.now() + timedelta(minutes=CIRCUIT_BREAKER_MINUTOS)
        perdidas_consec = 0
        fallas_api_consec = 0
        log.error(
            f"CIRCUIT BREAKER ACTIVADO ({CIRCUIT_BREAKER_MINUTOS} min) | Motivo: {motivo} | "
            f"Hasta: {circuit_hasta.strftime('%H:%M:%S')}"
        )

    try:
        while True:
            ahora = datetime.now()

            if _fuera_horario_trabajo_diario(ahora):
                log.info("Fin de jornada operativa (17:15). Bot en pausa diaria hasta la proxima rueda.")
                guardar_estado("fin_jornada_diaria", ciclos, seniales_hoy, ganancias_hoy, execution_mode="paper")
                time.sleep(60)
                continue

            # Reset diario
            if ahora.date() != ultimo_dia:
                log.info("── Nuevo día: reseteando contadores ──")
                seniales_hoy  = 0
                ganancias_hoy = 0.0
                ultimo_dia    = ahora.date()
                perdidas_consec   = 0
                fallas_api_consec = 0

            if not bot_esta_activo():
                log.info("Bot APAGADO desde el dashboard. Esperando...")
                guardar_estado("apagado", ciclos, seniales_hoy, ganancias_hoy, execution_mode="paper")
                time.sleep(30)
                continue

            if circuit_hasta and ahora < circuit_hasta:
                restante = int((circuit_hasta - ahora).total_seconds())
                log.warning(f"Circuit breaker activo. Pausa operativa por {restante}s.")
                guardar_estado("circuit_breaker", ciclos, seniales_hoy, ganancias_hoy, execution_mode="paper")
                time.sleep(min(INTERVALO_ACTUALIZACION, 30))
                continue
            if circuit_hasta and ahora >= circuit_hasta:
                log.info("Circuit breaker finalizado. Retomando operativa.")
                circuit_hasta = None

            estado        = estado_mercado()
            cfg           = cargar_dashboard_config()
            modo_horario  = estado["modo"]
            modo, forzado = resolver_modo_bot(modo_horario, cfg)
            execution_mode = resolver_execution_mode(cfg)
            modo_cauciones = "real"
            horario_nyse, _ = detectar_horario_nyse()
            ciclos       += 1

            if forzado:
                log.info(
                    f"── Ciclo #{ciclos} | BYMA: {modo_horario.upper()} | "
                    f"MODO FORZADO: {modo.upper()} | EJEC: {execution_mode.upper()} | NYSE: {horario_nyse.upper()} | {estado['hora_arg']} ──"
                )
            else:
                log.info(
                    f"── Ciclo #{ciclos} | BYMA: {modo.upper()} | EJEC: {execution_mode.upper()} | "
                    f"NYSE: {horario_nyse.upper()} | {estado['hora_arg']} ──"
                )

            # Seguridad: ejecucion REAL solo para modo caucion.
            if execution_mode == "real" and modo != "caucion":
                log.error(
                    "EJECUCION REAL solo habilitada para modo CAUCION. "
                    f"Modo actual: {modo.upper()}."
                )
                guardar_estado(
                    f"{modo}_bloqueado_ejecucion_real",
                    ciclos,
                    seniales_hoy,
                    ganancias_hoy,
                    horario_nyse,
                    execution_mode=execution_mode,
                )
                time.sleep(INTERVALO_ACTUALIZACION)
                continue

            ccl = obtener_ccl()
            if ccl is None:
                fallas_api_consec += 1
                log.warning(f"Falla API CCL ({fallas_api_consec}/{MAX_FALLAS_API_CONSEC}).")
                if fallas_api_consec >= MAX_FALLAS_API_CONSEC:
                    activar_circuit_breaker("fallas consecutivas al obtener CCL")
                log.warning("No se pudo obtener CCL. Reintentando en 60 segundos...")
                time.sleep(60)
                continue
            if ccl <= 0:
                fallas_api_consec += 1
                log.warning(f"Dato anomalo de CCL ({ccl}). Falla {fallas_api_consec}/{MAX_FALLAS_API_CONSEC}.")
                if fallas_api_consec >= MAX_FALLAS_API_CONSEC:
                    activar_circuit_breaker("datos anomalos de CCL")
                time.sleep(60)
                continue

            log.info(f"  CCL: ${ccl:,.2f}")

            # Recolectar precios NYSE cada hora
            if modo in ("arbitraje", "mixto") and necesita_recolectar(ultima_recoleccion):
                log.info("  Recolectando precios NYSE desde IOL...")
                try:
                    _, ok = recolectar_todo()
                    if ok:
                        ultima_recoleccion = datetime.now()
                        log.info("  ✅ Precios NYSE actualizados")
                        if fallas_api_consec > 0:
                            log.info("Conectividad API recuperada. Reseteando contador de fallas.")
                            fallas_api_consec = 0
                    else:
                        fallas_api_consec += 1
                        log.warning("  [WARN] No se pudieron actualizar precios NYSE")
                        if fallas_api_consec >= MAX_FALLAS_API_CONSEC:
                            activar_circuit_breaker("fallas consecutivas en recoleccion NYSE")
                except Exception as e:
                    fallas_api_consec += 1
                    log.error(f"  Error en recoleccion: {e}")
                    if fallas_api_consec >= MAX_FALLAS_API_CONSEC:
                        activar_circuit_breaker("excepciones consecutivas en recoleccion NYSE")

            datos_ok, detalle_datos = _datos_actualizados_para_operar(modo)
            if not datos_ok and modo in ("arbitraje", "mixto", "caucion"):
                log.warning(f"Operacion bloqueada por datos no actualizados: {detalle_datos}")
                fallas_api_consec += 1
                if fallas_api_consec >= MAX_FALLAS_API_CONSEC:
                    activar_circuit_breaker("datos desactualizados para operar")
                guardar_estado(
                    f"{modo}_bloqueado_datos",
                    ciclos,
                    seniales_hoy,
                    ganancias_hoy,
                    horario_nyse,
                    execution_mode=execution_mode,
                )
                time.sleep(INTERVALO_ACTUALIZACION)
                continue

            # Ejecutar según modo BYMA + estado NYSE
            try:
                ganancia_ciclo = 0.0
                if modo == "arbitraje":
                    s = ciclo_arbitraje(ccl)
                    seniales_hoy += s

                elif modo == "mixto":
                    s, g = ciclo_mixto(ccl, modo_datos_caucion=modo_cauciones)
                    seniales_hoy  += s
                    ganancias_hoy += g
                    ganancia_ciclo = g

                elif modo == "caucion":
                    g = ciclo_cauciones(
                        ccl,
                        forzar_todo=estado["es_cierre_caucion"],
                        modo_datos=modo_cauciones,
                        execution_mode=execution_mode,
                        ciclo_id=f"{datetime.now().date().isoformat()}_{ciclos}",
                    )
                    ganancias_hoy += g
                    ganancia_ciclo = g

                elif modo == "cerrado":
                    log.info(f"  BYMA cerrado — {estado['estado']}")
                    log.info("  Modo cerrado: sin analisis after-hours.")

            except Exception as e:
                log.error(f"Error en ciclo {modo}: {e}")

            if ganancia_ciclo < 0:
                perdidas_consec += 1
                log.warning(
                    f"Racha negativa detectada: {perdidas_consec}/{MAX_NEGATIVAS_CONSECUTIVAS} "
                    f"(ultima ganancia: ${ganancia_ciclo:,.2f} ARS)"
                )
                if perdidas_consec >= MAX_NEGATIVAS_CONSECUTIVAS:
                    activar_circuit_breaker("maximo de operaciones negativas consecutivas")
            elif ganancia_ciclo > 0 and perdidas_consec > 0:
                log.info("Se corta racha negativa con operacion positiva.")
                perdidas_consec = 0

            # Guardar estado
            guardar_estado(modo, ciclos, seniales_hoy, ganancias_hoy, horario_nyse, execution_mode=execution_mode)

            # Resumen cada 10 ciclos
            if ciclos % 10 == 0:
                log.info("")
                log.info("── RESUMEN PARCIAL ──")
                log.info(f"  Señales hoy:   {seniales_hoy}")
                log.info(f"  Ganancias hoy: ${ganancias_hoy:,.2f} ARS")
                log.info(f"  Capital disp.: ${capital_disponible():,.2f} ARS")
                log.info(f"  Horario NYSE:  {horario_nyse.upper()}")
                log.info("")

            log.info(f"  Esperando {INTERVALO_ACTUALIZACION} segundos...\n")
            time.sleep(INTERVALO_ACTUALIZACION)

    except KeyboardInterrupt:
        log.info("")
        log.info("=" * 65)
        log.info("  BOT DETENIDO por el usuario (Ctrl+C)")
        log.info("=" * 65)
        mostrar_resumen()

    except Exception as e:
        log.critical(f"Error fatal: {e}", exc_info=True)
        log.info("El bot se detuvo por un error inesperado.")


if __name__ == "__main__":
    iniciar()


