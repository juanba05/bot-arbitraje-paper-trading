"""
motor_cauciones.py - Analisis de cauciones colocadoras con tasa real IOL
=========================================================================
Fuentes de datos (en orden de prioridad):
  1. IOL /estadocuenta      → saldo ARS disponible real
  2. ambito.com             → tasa TNA del mercado en tiempo real
  3. Ultimo registro en DB  → fallback si todo lo demas falla

Logica financiera real:
  - Ganancia = Monto × (TNA/100) × (plazo/365)
  - Comision = Monto × 0.30% × 1.21 (IVA)
  - Ganancia neta = Ganancia - Comision
  - Criterio senal: TNA >= TNA_MINIMA_CONFIG y ganancia_neta > 0

Reglas de negocio:
  - SOLO cauciones colocadoras (nunca tomadoras)
  - Viernes → 3 dias habiles | Jueves → 2 dias | resto → 1 dia
  - Horario 11-18hs (17-18hs = modo cierre = 100% capital)
  - 70% del capital en horario normal / 100% en cierre
"""

import os
import json
import sqlite3
import requests
from datetime import datetime, date, timedelta
from config import (
    RUTA_DATOS, NOMBRE_DB,
    UMBRAL_CAUCION, PLAZO_MAX_CAUCION,
    COMISION_CAUCION_PCT, IVA_PCT,
    IOL_USUARIO, IOL_PASSWORD
)

# ── Intentamos importar IOL ───────────────────────────────────────
try:
    from iol_connector import _get, _asegurar_token
    IOL_DISPONIBLE = True
except Exception:
    IOL_DISPONIBLE = False

RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)

# ── Constantes ────────────────────────────────────────────────────
TNA_MINIMA          = 8.0    # No colocamos si la tasa es menor a esto (mercado Feb 2026: ~10-30%)
TNA_MAXIMA_VALIDA   = 300.0  # Por encima de esto es un dato corrupto
CAPITAL_NORMAL_PCT  = 0.70   # 70% del disponible en horario normal
CAPITAL_CIERRE_PCT  = 1.00   # 100% del disponible en horario de cierre
OBJETIVO_GANANCIA_NETA_MIN_ARS = 1.0
MIN_MUESTRAS_APRENDIZAJE = 3
SALTO_EXTRA_7D_PTS = 8.0
SALTO_EXTRA_7D_PCT = 25.0


def _asegurar_columna(cur, tabla, columna, tipo_sql):
    """Agrega una columna si no existe (migracion liviana y reversible)."""
    cur.execute(f"PRAGMA table_info({tabla})")
    existentes = {r[1] for r in cur.fetchall()}
    if columna not in existentes:
        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sql}")


def _comision_pct_default_total():
    """Comision total simulada en porcentaje (incluye IVA)."""
    return COMISION_CAUCION_PCT * (1 + IVA_PCT / 100)


def _json_text(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None


def _es_fin_rueda_caucion(ahora):
    """Ventana de cierre para cascada de decision."""
    return (ahora.hour == 17) or (ahora.hour == 16 and ahora.minute >= 50)


def _es_salto_extraordinario_7d(tna_base_max, tna_7d):
    """Habilita 7d solo ante salto grande vs curva 1-3d."""
    if tna_base_max is None or tna_7d is None:
        return False
    if tna_7d >= (tna_base_max + SALTO_EXTRA_7D_PTS):
        return True
    return tna_7d >= (tna_base_max * (1 + SALTO_EXTRA_7D_PCT / 100.0))


# ══════════════════════════════════════════════════════════════════
# 1. INICIALIZACIÓN DE BASE DE DATOS
# ══════════════════════════════════════════════════════════════════

def crear_tabla_cauciones_simuladas():
    """Crea la tabla de cauciones simuladas si no existe."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cauciones_simuladas (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp            TEXT NOT NULL,
                fecha_vencimiento    TEXT,
                plazo_dias           INTEGER,
                tna_mercado          REAL,
                fuente_tasa          TEXT,
                saldo_disponible     REAL,
                fuente_saldo         TEXT,
                capital_usado        REAL,
                pct_capital_usado    REAL,
                ganancia_bruta       REAL,
                comision_iol         REAL,
                ganancia_neta        REAL,
                rentabilidad_pct     REAL,
                tna_efectiva         REAL,
                monto_al_vencimiento REAL,
                promedio_historico   REAL,
                desviacion_pct       REAL,
                tiene_senal          INTEGER DEFAULT 0,
                motivo_no_senal      TEXT,
                estado               TEXT DEFAULT 'SIMULADA'
            )
        """)
        _asegurar_columna(cur, "cauciones_simuladas", "capital_minimo_requerido", "REAL")
        _asegurar_columna(cur, "cauciones_simuladas", "capital_faltante", "REAL")
        _asegurar_columna(cur, "cauciones_simuladas", "ev_esperar_diario", "REAL")
        _asegurar_columna(cur, "cauciones_simuladas", "ev_carry_diario", "REAL")
        _asegurar_columna(cur, "cauciones_simuladas", "decision_oportunidad", "TEXT")
        _asegurar_columna(cur, "cauciones_simuladas", "comision_pct_aplicada", "REAL")
        _asegurar_columna(cur, "cauciones_simuladas", "origen_comision", "TEXT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cauciones_real_vs_sim (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp              TEXT NOT NULL,
                plazo_dias             INTEGER,
                tna_mercado            REAL,
                monto_colocado         REAL,
                comision_simulada      REAL,
                comision_real          REAL,
                ganancia_neta_simulada REAL,
                ganancia_neta_real     REAL,
                delta_comision         REAL,
                delta_ganancia_neta    REAL,
                fuente                 TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cauciones_ordenes_real (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp              TEXT NOT NULL,
                ciclo_id               TEXT,
                source                 TEXT,
                plazo_dias             INTEGER,
                tna_objetivo           REAL,
                monto_objetivo         REAL,
                execution_mode         TEXT,
                estado                 TEXT,
                mensaje_error          TEXT,
                broker_order_id        TEXT,
                request_payload_json   TEXT,
                response_payload_json  TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cauciones_fills_real (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                orden_real_id          INTEGER,
                timestamp              TEXT NOT NULL,
                broker_order_id        TEXT,
                plazo_dias             INTEGER,
                tna_ejecutada          REAL,
                monto_ejecutado        REAL,
                comision_real          REAL,
                iva_real               REAL,
                gastos_extra_real      REAL,
                ganancia_neta_real     REAL,
                fecha_vencimiento      TEXT,
                settlement_status      TEXT,
                raw_fill_json          TEXT,
                FOREIGN KEY(orden_real_id) REFERENCES cauciones_ordenes_real(id)
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[CAUCIONES] ⚠️  Error creando tabla: {e}")


# ══════════════════════════════════════════════════════════════════
# 2. OBTENER TASA REAL DEL MERCADO — IOL WEB SCRAPER
# ══════════════════════════════════════════════════════════════════

# Cache de sesion web para no hacer login en cada llamada
_sesion_web_cache = {"sesion": None, "ts": None}

def _leer_credenciales_env():
    """
    Compatibilidad historica: toma credenciales ya cargadas por config.py.
    Evita leer el archivo .env manualmente desde este modulo.
    """
    return IOL_USUARIO, IOL_PASSWORD


def _crear_sesion_web_iol():
    """
    Hace login en la web de IOL y devuelve una sesion con cookies.
    Cachea la sesion por 30 minutos para no re-loguear en cada consulta.
    """
    global _sesion_web_cache
    ahora = datetime.now()

    # Reusar sesion si tiene menos de 30 minutos
    if (_sesion_web_cache["sesion"] is not None and
            _sesion_web_cache["ts"] is not None and
            (ahora - _sesion_web_cache["ts"]).total_seconds() < 1800):
        return _sesion_web_cache["sesion"]

    usuario, password = _leer_credenciales_env()
    if not usuario or not password:
        return None

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "es-AR,es;q=0.9",
        "Origin": "https://iol.invertironline.com",
        "Referer": "https://iol.invertironline.com/",
    })

    try:
        # Obtener token CSRF
        resp = session.get("https://iol.invertironline.com/User/Login", timeout=10)
        token_csrf = None
        import re
        match = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', resp.text)
        if match:
            token_csrf = match.group(1)

        payload = {"UserName": usuario, "Password": password, "RememberMe": "false"}
        if token_csrf:
            payload["__RequestVerificationToken"] = token_csrf

        session.post("https://iol.invertironline.com/User/Login",
                     data=payload, allow_redirects=True, timeout=10)

        _sesion_web_cache["sesion"] = session
        _sesion_web_cache["ts"] = ahora
        return session
    except Exception as e:
        print(f"[CAUCIONES] ⚠️  Login web IOL fallido: {e}")
        return None


def _obtener_tasa_iol_web(plazo_dias=1, moneda="PESOS"):
    """
    Obtiene la tasa colocadora real desde /Mercado/GetCaucionPuntas de IOL.
    Este es el mismo endpoint que usa la pagina web de cauciones de IOL.
    Devuelve float TNA colocadora o None si falla.
    """
    try:
        session = _crear_sesion_web_iol()
        if session is None:
            return None

        resp = session.post(
            "https://iol.invertironline.com/Mercado/GetCaucionPuntas",
            data={"moneda": moneda, "plazo": str(plazo_dias), "idTipoTransaccion": "14"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://iol.invertironline.com/Operar/Caucionar/ObtenerTasas",
            },
            timeout=10
        )

        if resp.status_code != 200:
            return None

        datos = resp.json()
        if not datos.get("success"):
            return None

        puntas = datos.get("listaPuntas", [])
        if not puntas:
            return None

        # tasaCompra = tasa colocadora (quien coloca pesos)
        # tasaVenta  = tasa tomadora  (quien toma pesos prestados)
        primera = puntas[0]
        tasa_raw = primera.get("tasaCompra") or primera.get("precioCompra")
        if tasa_raw is None:
            return None

        tna = float(str(tasa_raw).replace(",", ".").replace("%", "").strip())
        if 0 < tna < TNA_MAXIMA_VALIDA:
            return tna
        return None

    except Exception as e:
        print(f"[CAUCIONES] ⚠️  IOL web scraper error: {e}")
        return None


def _obtener_tasa_db(plazo_dias=1):
    """
    Devuelve la ultima tasa registrada en la DB (solo diagnostico, no operativa).
    Solo usa registros de las ultimas 48 horas.
    """
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT tasa_anual, fecha_hora FROM cauciones
            WHERE tasa_anual > 0
              AND datetime(fecha_hora) >= datetime('now', '-48 hours')
            ORDER BY fecha_hora DESC
            LIMIT 1
        """)
        fila = cur.fetchone()
        conn.close()
        if fila:
            return float(fila[0]), fila[1]
        return None, None
    except Exception as e:
        print(f"[CAUCIONES] ⚠️  Error leyendo tasa de DB: {e}")
        return None, None


def obtener_tasa_mercado(plazo_dias=1):
    """
    Obtiene la TNA de cauciones colocadoras SOLO desde IOL web.
    Devuelve (tna, fuente, detalle)
    """
    tna = _obtener_tasa_iol_web(plazo_dias=plazo_dias)
    if tna is not None:
        return tna, "IOL_WEB", f"Tasa real IOL a {plazo_dias} dia(s): {tna:.2f}% TNA colocadora"

    return None, "SIN_DATOS", "IOL no respondio tasa real. No se opera."


# 3. OBTENER SALDO REAL DE IOL
# ══════════════════════════════════════════════════════════════════

def _parsear_saldo_iol(datos):
    """
    Extrae el saldo disponible en ARS del JSON de /estadocuenta de IOL.
    IOL devuelve: {'cuentas': [{'moneda': 'peso_Argentino', 'disponible': 613.37, ...}]}
    """
    if datos is None:
        return None

    def es_cuenta_pesos(cuenta):
        moneda = str(cuenta.get("moneda", "")).lower().replace("_", "").replace(" ", "")
        tipo   = str(cuenta.get("tipo", "")).lower()
        # IOL usa: 'peso_Argentino', 'peso_argentino', 'pesos', 'ARS'
        # Y tipo:  'inversion_Argentina_Pesos', etc.
        return ("peso" in moneda or "ars" in moneda or "pesos" in tipo)

    # Estructura real de IOL: dict con clave 'cuentas'
    if isinstance(datos, dict):
        cuentas = datos.get("cuentas", datos.get("accounts", []))
        if isinstance(cuentas, list):
            for cuenta in cuentas:
                if es_cuenta_pesos(cuenta):
                    saldo = cuenta.get("disponible", cuenta.get("saldo", None))
                    if saldo is not None:
                        return float(saldo)
            # Si no matchea ninguna, tomamos la primera cuenta con saldo
            for cuenta in cuentas:
                saldo = cuenta.get("disponible", cuenta.get("saldo", None))
                if saldo is not None:
                    return float(saldo)

    # Estructura alternativa: lista de cuentas directa
    if isinstance(datos, list):
        for cuenta in datos:
            if isinstance(cuenta, dict) and es_cuenta_pesos(cuenta):
                saldo = cuenta.get("disponible", cuenta.get("saldo", None))
                if saldo is not None:
                    return float(saldo)

    return None


def obtener_saldo_disponible():
    """
    Obtiene el saldo disponible en ARS.
    Devuelve (saldo, fuente, detalle)
    """
    # Intento 1: IOL /estadocuenta (datos reales)
    if IOL_DISPONIBLE:
        try:
            datos = _get("/estadocuenta")
            saldo = _parsear_saldo_iol(datos)
            if saldo is not None and saldo >= 0:
                return saldo, "IOL", f"Saldo real de IOL: ARS {saldo:,.2f}"
            else:
                print(f"[CAUCIONES] ℹ️  IOL respondio pero no pudo parsear saldo. Datos: {str(datos)[:200]}")
        except Exception as e:
            print(f"[CAUCIONES] ⚠️  Error consultando IOL para saldo: {e}")

    # Intento 2: Capital configurado (paper trading)
    # Buscamos en la DB el capital actual del paper trading
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT capital_usado FROM cauciones_simuladas
            ORDER BY timestamp DESC LIMIT 1
        """)
        fila = cur.fetchone()
        conn.close()
        # Usamos el capital por defecto del proyecto
        capital_default = 40000.0
        return capital_default, "PAPER_TRADING", f"Capital paper trading: ARS {capital_default:,.2f}"
    except:
        return 40000.0, "PAPER_TRADING", "Capital paper trading por defecto: ARS 40.000"


# ══════════════════════════════════════════════════════════════════
# 4. CALCULAR PLAZO OPTIMO
# ══════════════════════════════════════════════════════════════════

def calcular_plazo_optimo(ahora=None):
    """
    Segun reglas de negocio:
      Viernes → 3 dias habiles (vence martes)
      Jueves  → 2 dias habiles (vence lunes)
      Resto   → 1 dia habil
    Devuelve (plazo_dias, fecha_vencimiento, descripcion)
    """
    if ahora is None:
        ahora = datetime.now()

    dia_semana = ahora.weekday()  # 0=lun ... 4=vie, 5=sab, 6=dom

    # Finde → sin operacion
    if dia_semana >= 5:
        return None, None, "Fin de semana — mercado cerrado"

    # Fuera de horario BYMA (11-18hs)
    if ahora.hour < 11 or ahora.hour >= 18:
        return None, None, "Fuera de horario BYMA (11-18hs)"

    # Calcular plazo segun dia
    if dia_semana == 4:    # Viernes
        plazo = 3
        desc = "Viernes → 3 dias habiles (vence martes)"
    elif dia_semana == 3:  # Jueves
        plazo = 2
        desc = "Jueves → 2 dias habiles (vence lunes)"
    else:                  # Lun, Mar, Mie
        plazo = 1
        desc = "Dia normal → 1 dia habil"

    # Respetar PLAZO_MAX_CAUCION del config
    plazo = min(plazo, PLAZO_MAX_CAUCION)

    # Calcular fecha de vencimiento saltando finde
    vencimiento = ahora.date()
    dias_sumados = 0
    while dias_sumados < plazo:
        vencimiento += timedelta(days=1)
        if vencimiento.weekday() < 5:
            dias_sumados += 1

    return plazo, vencimiento, desc


# ══════════════════════════════════════════════════════════════════
# 5. CALCULAR CAPITAL A USAR
# ══════════════════════════════════════════════════════════════════

def calcular_capital_a_usar(saldo_disponible, ahora=None):
    """
    Segun horario:
      17-18hs (cierre): 100% del disponible
      Resto:            70% del disponible
    Devuelve (capital, pct_usado, descripcion)
    """
    if ahora is None:
        ahora = datetime.now()

    if 17 <= ahora.hour < 18:
        pct = CAPITAL_CIERRE_PCT
        desc = "Modo cierre (17-18hs) → 100% del capital"
    else:
        pct = CAPITAL_NORMAL_PCT
        desc = "Modo normal → 70% del capital"

    capital = saldo_disponible * pct
    return round(capital, 2), pct, desc


# ══════════════════════════════════════════════════════════════════
# 6. CALCULAR RENDIMIENTO DE LA CAUCIÓN
# ══════════════════════════════════════════════════════════════════

def obtener_metricas_comision_aprendida():
    """
    Aprende comision efectiva desde operaciones reales registradas.
    Si no hay suficientes muestras, usa comision simulada por defecto.
    """
    pct_default = _comision_pct_default_total()
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*), AVG((comision_real * 100.0) / monto_colocado)
            FROM cauciones_real_vs_sim
            WHERE monto_colocado > 0
              AND comision_real >= 0
              AND datetime(timestamp) >= datetime('now', '-90 days')
        """)
        fila = cur.fetchone()
        conn.close()
        muestras = int(fila[0] or 0)
        pct_aprendido = float(fila[1]) if fila and fila[1] is not None else None
        if muestras >= MIN_MUESTRAS_APRENDIZAJE and pct_aprendido is not None and pct_aprendido > 0:
            return {
                "pct_total": round(pct_aprendido, 6),
                "origen": f"REAL_APRENDIDA_{muestras}M",
                "muestras": muestras,
            }
    except Exception:
        pass
    return {"pct_total": pct_default, "origen": "SIMULADA_DEFAULT", "muestras": 0}


def calcular_capital_minimo_requerido(tna_pct, plazo_dias, comision_pct_total, objetivo_neto_ars=OBJETIVO_GANANCIA_NETA_MIN_ARS):
    """
    Capital minimo para alcanzar ganancia_neta objetivo.
    Si el margen unitario <= 0, la operacion es inviable para cualquier capital.
    """
    margen_unitario = (tna_pct / 100.0) * (plazo_dias / 365.0) - (comision_pct_total / 100.0)
    if margen_unitario <= 0:
        return None, margen_unitario
    capital_minimo = max(1.0, objetivo_neto_ars / margen_unitario)
    return round(capital_minimo, 2), margen_unitario


def obtener_media_capital_minimo_requerido(dias=7):
    """Media historica para guiar inyeccion de capital en simulacion."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT AVG(capital_minimo_requerido), COUNT(*)
            FROM cauciones_simuladas
            WHERE capital_minimo_requerido IS NOT NULL
              AND capital_minimo_requerido > 0
              AND datetime(timestamp) >= datetime('now', ?)
        """, (f"-{int(dias)} days",))
        fila = cur.fetchone()
        conn.close()
        if fila and fila[0] is not None and int(fila[1] or 0) > 0:
            return round(float(fila[0]), 2), int(fila[1] or 0)
    except Exception:
        pass
    return None, 0


def analizar_costo_oportunidad_espera(dias_espera=7, dias_hist=14):
    """
    Compara EV diario de esperar pico de tasa vs carry normal.
    """
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT tna_mercado, ganancia_neta, plazo_dias,
                   CAST(strftime('%H', timestamp) AS INTEGER) AS hora
            FROM cauciones_simuladas
            WHERE fuente_tasa = 'IOL_WEB'
              AND tna_mercado > 0
              AND ganancia_neta IS NOT NULL
              AND datetime(timestamp) >= datetime('now', ?)
            ORDER BY timestamp DESC
        """, (f"-{int(dias_hist)} days",))
        rows = cur.fetchall()
        conn.close()
        if len(rows) < 8:
            return {"disponible": False, "motivo": "sin_historial_suficiente"}

        cierre = [r for r in rows if int(r[3] or -1) == 17]
        normales = [r for r in rows if int(r[3] or -1) != 17]
        base_ref = cierre if len(cierre) >= 4 else rows
        tasas_ref = sorted(float(r[0]) for r in base_ref)
        umbral_spike = tasas_ref[int(len(tasas_ref) * 0.75)]

        spikes = [r for r in rows if float(r[0]) >= umbral_spike]
        p_spike = len(spikes) / len(rows) if rows else 0.0
        gan_spike_media = sum(float(r[1]) for r in spikes) / len(spikes) if spikes else 0.0

        base_carry = normales if normales else rows
        carry_diario = 0.0
        for r in base_carry:
            plazo = max(1, int(r[2] or 1))
            carry_diario += float(r[1]) / plazo
        carry_diario = carry_diario / len(base_carry) if base_carry else 0.0

        ev_esperar = (p_spike * gan_spike_media) / max(1, int(dias_espera))
        decision = "ESPERAR_SPIKE" if ev_esperar > carry_diario else "CARRY_NORMAL"

        return {
            "disponible": True,
            "ev_esperar_diario": round(ev_esperar, 2),
            "ev_carry_diario": round(carry_diario, 2),
            "prob_spike": round(p_spike * 100, 1),
            "umbral_spike_tna": round(float(umbral_spike), 2),
            "decision": decision,
            "muestras": len(rows),
        }
    except Exception as e:
        return {"disponible": False, "motivo": f"error:{type(e).__name__}"}


def registrar_intento_orden_real_caucion(
    ciclo_id,
    plazo_dias,
    tna_objetivo,
    monto_objetivo,
    execution_mode="real",
    source="BOT_PRINCIPAL",
    request_payload=None,
):
    """
    Registra el intento de envio de una orden real.
    Devuelve el id de la orden local para trazabilidad.
    """
    crear_tabla_cauciones_simuladas()
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cauciones_ordenes_real (
                timestamp, ciclo_id, source, plazo_dias, tna_objetivo, monto_objetivo,
                execution_mode, estado, request_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                str(ciclo_id) if ciclo_id is not None else None,
                str(source),
                int(plazo_dias),
                float(tna_objetivo),
                float(monto_objetivo),
                str(execution_mode),
                "PENDIENTE_ENVIO",
                _json_text(request_payload),
            ),
        )
        order_id = cur.lastrowid
        conn.commit()
        conn.close()
        return order_id
    except Exception as e:
        print(f"[CAUCIONES] Error registrando intento real: {e}")
        return None


def actualizar_orden_real_caucion(
    orden_real_id,
    estado,
    broker_order_id=None,
    mensaje_error=None,
    response_payload=None,
):
    """Actualiza estado de una orden real registrada."""
    if orden_real_id is None:
        return False
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE cauciones_ordenes_real
            SET estado = ?,
                broker_order_id = ?,
                mensaje_error = ?,
                response_payload_json = ?
            WHERE id = ?
            """,
            (
                str(estado),
                None if broker_order_id is None else str(broker_order_id),
                None if mensaje_error is None else str(mensaje_error),
                _json_text(response_payload),
                int(orden_real_id),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[CAUCIONES] Error actualizando orden real: {e}")
        return False


def registrar_fill_real_caucion(
    orden_real_id,
    plazo_dias,
    tna_ejecutada,
    monto_ejecutado,
    comision_real,
    iva_real=0.0,
    gastos_extra_real=0.0,
    ganancia_neta_real=None,
    fecha_vencimiento=None,
    settlement_status="FILLED",
    broker_order_id=None,
    raw_fill=None,
):
    """
    Guarda el fill real de caucion y alimenta la tabla comparativa real_vs_sim.
    """
    crear_tabla_cauciones_simuladas()
    try:
        if ganancia_neta_real is None:
            ganancia_bruta = float(monto_ejecutado) * (float(tna_ejecutada) / 100.0) * (int(plazo_dias) / 365.0)
            costo_total = float(comision_real) + float(iva_real) + float(gastos_extra_real)
            ganancia_neta_real = round(ganancia_bruta - costo_total, 2)

        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cauciones_fills_real (
                orden_real_id, timestamp, broker_order_id, plazo_dias, tna_ejecutada,
                monto_ejecutado, comision_real, iva_real, gastos_extra_real,
                ganancia_neta_real, fecha_vencimiento, settlement_status, raw_fill_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None if orden_real_id is None else int(orden_real_id),
                datetime.now().isoformat(),
                None if broker_order_id is None else str(broker_order_id),
                int(plazo_dias),
                float(tna_ejecutada),
                float(monto_ejecutado),
                float(comision_real),
                float(iva_real),
                float(gastos_extra_real),
                float(ganancia_neta_real),
                fecha_vencimiento,
                str(settlement_status),
                _json_text(raw_fill),
            ),
        )
        conn.commit()
        conn.close()

        registrar_operacion_real_caucion(
            plazo_dias=int(plazo_dias),
            tna_mercado=float(tna_ejecutada),
            monto_colocado=float(monto_ejecutado),
            comision_real=float(comision_real) + float(iva_real) + float(gastos_extra_real),
            ganancia_neta_real=float(ganancia_neta_real),
            fuente="IOL_REAL",
        )
        return True
    except Exception as e:
        print(f"[CAUCIONES] Error registrando fill real: {e}")
        return False


def resumen_real_vs_sim_dia(fecha_iso=None):
    """
    Resume desvio de ejecuciones reales vs simulacion para una fecha YYYY-MM-DD.
    """
    crear_tabla_cauciones_simuladas()
    if not fecha_iso:
        fecha_iso = datetime.now().date().isoformat()
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) AS n_ops,
                COALESCE(SUM(monto_colocado), 0),
                COALESCE(AVG(delta_comision), 0),
                COALESCE(AVG(delta_ganancia_neta), 0),
                COALESCE(SUM(ganancia_neta_simulada), 0),
                COALESCE(SUM(ganancia_neta_real), 0)
            FROM cauciones_real_vs_sim
            WHERE substr(timestamp,1,10)=?
            """,
            (str(fecha_iso),),
        )
        row = cur.fetchone()
        conn.close()
        n_ops = int(row[0] or 0)
        monto_total = float(row[1] or 0.0)
        avg_delta_comision = float(row[2] or 0.0)
        avg_delta_ganancia = float(row[3] or 0.0)
        sim_total = float(row[4] or 0.0)
        real_total = float(row[5] or 0.0)
        return {
            "fecha": fecha_iso,
            "ops": n_ops,
            "monto_total": round(monto_total, 2),
            "ganancia_sim_total": round(sim_total, 2),
            "ganancia_real_total": round(real_total, 2),
            "delta_ganancia_total": round(real_total - sim_total, 2),
            "delta_comision_promedio": round(avg_delta_comision, 2),
            "delta_ganancia_promedio": round(avg_delta_ganancia, 2),
        }
    except Exception as e:
        return {"fecha": fecha_iso, "error": str(e)}


def registrar_operacion_real_caucion(plazo_dias, tna_mercado, monto_colocado, comision_real, ganancia_neta_real, fuente="IOL_REAL"):
    """
    Registra una caucion real y la compara contra lo simulado para aprender costos.
    """
    crear_tabla_cauciones_simuladas()
    sim = calcular_rendimiento_caucion(float(monto_colocado), float(tna_mercado), int(plazo_dias))
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cauciones_real_vs_sim (
                timestamp, plazo_dias, tna_mercado, monto_colocado,
                comision_simulada, comision_real,
                ganancia_neta_simulada, ganancia_neta_real,
                delta_comision, delta_ganancia_neta, fuente
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            int(plazo_dias),
            float(tna_mercado),
            float(monto_colocado),
            float(sim["comision_iol"]),
            float(comision_real),
            float(sim["ganancia_neta"]),
            float(ganancia_neta_real),
            round(float(comision_real) - float(sim["comision_iol"]), 2),
            round(float(ganancia_neta_real) - float(sim["ganancia_neta"]), 2),
            str(fuente),
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[CAUCIONES] Error registrando operacion real: {e}")
        return False


def calcular_rendimiento_caucion(monto_ars, tna_pct, plazo_dias, comision_pct_total=None):
    """
    Calculo financiero completo de una caucion colocadora.
    Devuelve dict con todos los numeros.
    """
    if comision_pct_total is None:
        comision_pct_total = _comision_pct_default_total()

    # Ganancia bruta por intereses
    ganancia_bruta = monto_ars * (tna_pct / 100) * (plazo_dias / 365)

    # Comision total modelada (simulada default o aprendida desde real)
    comision_total = monto_ars * (comision_pct_total / 100)

    # Resultado
    ganancia_neta        = ganancia_bruta - comision_total
    rentabilidad_pct     = (ganancia_neta / monto_ars) * 100 if monto_ars > 0 else 0
    tna_efectiva         = (ganancia_neta / monto_ars) * (365 / plazo_dias) * 100 if (monto_ars > 0 and plazo_dias > 0) else 0
    monto_al_vencimiento = monto_ars + ganancia_neta

    return {
        "monto_colocado":      round(monto_ars, 2),
        "tna_mercado":         tna_pct,
        "plazo_dias":          plazo_dias,
        "ganancia_bruta":      round(ganancia_bruta, 2),
        "comision_iol":        round(comision_total, 2),
        "ganancia_neta":       round(ganancia_neta, 2),
        "rentabilidad_pct":    round(rentabilidad_pct, 4),
        "tna_efectiva":        round(tna_efectiva, 2),
        "monto_al_vencimiento": round(monto_al_vencimiento, 2),
        "comision_pct_aplicada": round(comision_pct_total, 6),
    }


# ══════════════════════════════════════════════════════════════════
# 7. PROMEDIO HISTORICO DE TASAS
# ══════════════════════════════════════════════════════════════════

def obtener_promedio_historico(hora_franja):
    """
    Promedio de tasas IOL_WEB de los ultimos 7 dias en la misma franja horaria.
    Solo usa registros con fuente IOL_WEB para que el promedio sea real.
    Si no hay historial real, devuelve None (no se usa promedio ficticio).
    """
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()

        # Solo registros IOL_WEB de los ultimos 7 dias
        cur.execute("""
            SELECT AVG(tna_mercado), COUNT(*) FROM cauciones_simuladas
            WHERE strftime('%H', timestamp) = ?
              AND tna_mercado > 0
              AND tna_mercado < 300
              AND fuente_tasa = 'IOL_WEB'
              AND datetime(timestamp) >= datetime('now', '-7 days')
        """, (f"{hora_franja:02d}",))
        res = cur.fetchone()
        conn.close()

        if res and res[0] is not None and res[1] >= 3:
            return round(res[0], 2)
        return None  # Sin historial suficiente

    except Exception as e:
        print(f"[CAUCIONES] ⚠️  Error leyendo historial: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# 8. GUARDAR EN BASE DE DATOS
# ══════════════════════════════════════════════════════════════════

def guardar_simulacion(datos_dict):
    """Guarda la simulacion completa en cauciones_simuladas."""
    try:
        crear_tabla_cauciones_simuladas()
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cauciones_simuladas (
                timestamp, fecha_vencimiento, plazo_dias,
                tna_mercado, fuente_tasa,
                saldo_disponible, fuente_saldo,
                capital_usado, pct_capital_usado,
                ganancia_bruta, comision_iol, ganancia_neta,
                rentabilidad_pct, tna_efectiva, monto_al_vencimiento,
                promedio_historico, desviacion_pct,
                tiene_senal, motivo_no_senal, estado,
                capital_minimo_requerido, capital_faltante,
                ev_esperar_diario, ev_carry_diario, decision_oportunidad,
                comision_pct_aplicada, origen_comision
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datos_dict["timestamp"],
            datos_dict["fecha_vencimiento"],
            datos_dict["plazo_dias"],
            datos_dict["tna_mercado"],
            datos_dict["fuente_tasa"],
            datos_dict["saldo_disponible"],
            datos_dict["fuente_saldo"],
            datos_dict["capital_usado"],
            datos_dict["pct_capital_usado"],
            datos_dict["ganancia_bruta"],
            datos_dict["comision_iol"],
            datos_dict["ganancia_neta"],
            datos_dict["rentabilidad_pct"],
            datos_dict["tna_efectiva"],
            datos_dict["monto_al_vencimiento"],
            datos_dict["promedio_historico"],
            datos_dict["desviacion_pct"],
            1 if datos_dict["tiene_senal"] else 0,
            datos_dict.get("motivo_no_senal", ""),
            datos_dict["estado"],
            datos_dict.get("capital_minimo_requerido"),
            datos_dict.get("capital_faltante"),
            datos_dict.get("ev_esperar_diario"),
            datos_dict.get("ev_carry_diario"),
            datos_dict.get("decision_oportunidad"),
            datos_dict.get("comision_pct_aplicada"),
            datos_dict.get("origen_comision"),
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[CAUCIONES] ⚠️  Error guardando simulacion: {e}")
        return False


def guardar_senal_db(tna, promedio, desviacion_pct, capital, ganancia_neta, plazo, vencimiento):
    """Guarda la senal en la tabla seniales (para el dashboard)."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        descripcion = (
            f"Caucion colocadora: TNA {tna:.1f}% ({desviacion_pct:+.1f}% sobre promedio) | "
            f"Capital ARS {capital:,.0f} | Plazo {plazo}d | "
            f"Ganancia estimada ARS {ganancia_neta:.2f} | Vence {vencimiento}"
        )
        cur.execute("""
            INSERT INTO seniales
            (fecha_hora, tipo, simbolo, descripcion, spread_pct, accion, tasa_caucion)
            VALUES (?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(),
            "caucion",
            f"CAUCION_{plazo}D",
            descripcion,
            desviacion_pct,
            "COLOCAR_PESOS_EN_CAUCION",
            tna
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[CAUCIONES] ⚠️  Error guardando senal: {e}")
        return False


def guardar_tasa_historica(tna, fuente):
    """Guarda la tasa en la tabla cauciones (historial)."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cauciones (fecha_hora, plazo_dias, tasa_anual, fuente)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), 1, tna, fuente))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[CAUCIONES] ⚠️  Error guardando tasa historica: {e}")


# ══════════════════════════════════════════════════════════════════
# 9. ANALISIS PRINCIPAL
# ══════════════════════════════════════════════════════════════════

def semaforo(desviacion_pct, tiene_senal):
    if not tiene_senal:
        return "⚪ Sin señal"
    if desviacion_pct >= UMBRAL_CAUCION * 1.5:
        return "🔴 SEÑAL FUERTE"
    return "🟡 SEÑAL"


def analizar_cauciones(modo="auto"):
    """
    Analisis completo de cauciones colocadoras.
    Devuelve el mejor plazo evaluado segun ganancia neta.
    """
    crear_tabla_cauciones_simuladas()
    ahora = datetime.now()

    print(f"\n{'='*60}")
    print(f"  SIMULADOR DE CAUCIONES - {ahora.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*60}")

    plazo_optimo, _venc, desc_plazo = calcular_plazo_optimo(ahora)
    if plazo_optimo is None:
        print(f"\n  [NO] {desc_plazo}")
        print(f"{'='*60}")
        return {"puede_operar": False, "motivo": desc_plazo}

    plazos_disponibles = [p for p in (1, 2, 3) if p <= PLAZO_MAX_CAUCION]
    fin_rueda = _es_fin_rueda_caucion(ahora)

    print(f"  Plazo optimo:   {plazo_optimo} dia(s) - {desc_plazo}")
    print(f"  Plazos a eval.: {plazos_disponibles}")
    print(f"  Fin de rueda:   {'SI' if fin_rueda else 'NO'}")

    saldo, fuente_saldo, _ = obtener_saldo_disponible()
    capital, pct_capital, desc_capital = calcular_capital_a_usar(saldo, ahora)
    print(f"  Saldo IOL:      ARS {saldo:,.2f} ({fuente_saldo})")
    print(f"  Capital a usar: ARS {capital:,.2f} ({pct_capital*100:.0f}%) - {desc_capital}")

    metricas_comision = obtener_metricas_comision_aprendida()
    comision_pct_aplicada = float(metricas_comision["pct_total"])
    origen_comision = metricas_comision["origen"]
    print(f"  Comision usada: {comision_pct_aplicada:.4f}% ({origen_comision})")

    analisis_oportunidad = analizar_costo_oportunidad_espera(dias_espera=7, dias_hist=14)
    media_capital_min, muestras_media_capital = obtener_media_capital_minimo_requerido(dias=7)

    resultados_por_plazo = {}
    mejor_plazo = None
    mejor_ganancia = -999999.0
    mejor_score_bloqueo = -999999.0

    for plazo in plazos_disponibles:
        if modo == "simulacion":
            print("\n  [NO] Modo simulacion deshabilitado por seguridad.")
            continue

        tna_raw = _obtener_tasa_iol_web(plazo_dias=plazo)
        if tna_raw is None:
            print(f"\n  [NO] Sin tasa real IOL para plazo {plazo}d")
            continue

        tna = tna_raw
        fuente_tna = "IOL_WEB"
        if tna < TNA_MINIMA or tna > TNA_MAXIMA_VALIDA:
            continue

        venc = ahora.date()
        dias_sumados = 0
        while dias_sumados < plazo:
            venc += timedelta(days=1)
            if venc.weekday() < 5:
                dias_sumados += 1

        rend = calcular_rendimiento_caucion(
            capital, tna, plazo, comision_pct_total=comision_pct_aplicada
        )
        score_bloqueo = round(rend["ganancia_neta"] / max(1, int(plazo)), 4)
        capital_minimo_req, margen_unitario = calcular_capital_minimo_requerido(
            tna, plazo, comision_pct_aplicada
        )
        capital_faltante = 0.0
        if capital_minimo_req is not None and capital < capital_minimo_req:
            capital_faltante = round(capital_minimo_req - capital, 2)

        promedio = obtener_promedio_historico(ahora.hour)
        if promedio is not None and promedio > 0:
            desviacion_pct = round(((tna - promedio) / promedio) * 100, 1)
        else:
            desviacion_pct = 0.0

        sin_historial = (promedio is None)
        if capital_minimo_req is None:
            tiene_senal = False
            motivo_no_senal = (
                f"Comision supera interes ({margen_unitario*100:.4f}% por peso). Inviable a cualquier capital."
            )
        elif capital_faltante > 0:
            tiene_senal = False
            motivo_no_senal = (
                f"Capital insuficiente: min ARS {capital_minimo_req:,.2f}; faltan ARS {capital_faltante:,.2f}"
            )
        elif rend["ganancia_neta"] > 0 and (sin_historial or desviacion_pct >= UMBRAL_CAUCION):
            tiene_senal = True
            motivo_no_senal = ""
        elif rend["ganancia_neta"] <= 0:
            tiene_senal = False
            motivo_no_senal = f"Ganancia neta negativa (ARS {rend['ganancia_neta']:.2f})"
        else:
            tiene_senal = False
            motivo_no_senal = (
                f"Desviacion {desviacion_pct:.1f}% menor al umbral {UMBRAL_CAUCION}% "
                f"sobre promedio {promedio:.1f}%"
            )

        resultados_por_plazo[plazo] = {
            "plazo": plazo,
            "vencimiento": venc,
            "tna": tna,
            "fuente_tna": fuente_tna,
            "promedio": promedio,
            "desviacion_pct": desviacion_pct,
            "rend": rend,
            "capital_minimo_requerido": capital_minimo_req,
            "capital_faltante": capital_faltante,
            "ganancia_neta_por_dia_bloqueo": score_bloqueo,
            "tiene_senal": tiene_senal,
            "motivo_no_senal": motivo_no_senal,
        }

        if (
            score_bloqueo > mejor_score_bloqueo
            or (
                score_bloqueo == mejor_score_bloqueo
                and rend["ganancia_neta"] > mejor_ganancia
            )
        ):
            mejor_score_bloqueo = score_bloqueo
            mejor_ganancia = rend["ganancia_neta"]
            mejor_plazo = plazo

    # 7d solo si la curva muestra salto extraordinario.
    max_tna_1_3 = None
    if resultados_por_plazo:
        max_tna_1_3 = max(r["tna"] for r in resultados_por_plazo.values())
    tna_7d = _obtener_tasa_iol_web(plazo_dias=7)
    usar_7d = _es_salto_extraordinario_7d(max_tna_1_3, tna_7d)
    if usar_7d and tna_7d is not None and 0 < tna_7d < TNA_MAXIMA_VALIDA:
        venc_7d = ahora.date()
        dias_sumados = 0
        while dias_sumados < 7:
            venc_7d += timedelta(days=1)
            if venc_7d.weekday() < 5:
                dias_sumados += 1

        rend_7d = calcular_rendimiento_caucion(
            capital, tna_7d, 7, comision_pct_total=comision_pct_aplicada
        )
        score_7d = round(rend_7d["ganancia_neta"] / 7.0, 4)
        cap_min_7d, margen_7d = calcular_capital_minimo_requerido(
            tna_7d, 7, comision_pct_aplicada
        )
        cap_falt_7d = 0.0
        if cap_min_7d is not None and capital < cap_min_7d:
            cap_falt_7d = round(cap_min_7d - capital, 2)

        promedio = obtener_promedio_historico(ahora.hour)
        if promedio is not None and promedio > 0:
            desviacion_7d = round(((tna_7d - promedio) / promedio) * 100, 1)
        else:
            desviacion_7d = 0.0

        if cap_min_7d is None:
            tiene_senal_7d = False
            motivo_7d = f"Comision supera interes ({margen_7d*100:.4f}% por peso)."
        elif cap_falt_7d > 0:
            tiene_senal_7d = False
            motivo_7d = f"Capital insuficiente: min ARS {cap_min_7d:,.2f}; faltan ARS {cap_falt_7d:,.2f}"
        elif rend_7d["ganancia_neta"] > 0:
            tiene_senal_7d = True
            motivo_7d = "7d habilitado por salto extraordinario"
        else:
            tiene_senal_7d = False
            motivo_7d = f"Ganancia neta negativa (ARS {rend_7d['ganancia_neta']:.2f})"

        resultados_por_plazo[7] = {
            "plazo": 7,
            "vencimiento": venc_7d,
            "tna": tna_7d,
            "fuente_tna": "IOL_WEB",
            "promedio": promedio,
            "desviacion_pct": desviacion_7d,
            "rend": rend_7d,
            "capital_minimo_requerido": cap_min_7d,
            "capital_faltante": cap_falt_7d,
            "ganancia_neta_por_dia_bloqueo": score_7d,
            "tiene_senal": tiene_senal_7d,
            "motivo_no_senal": motivo_7d,
        }

        if (
            score_7d > mejor_score_bloqueo
            or (score_7d == mejor_score_bloqueo and rend_7d["ganancia_neta"] > mejor_ganancia)
        ):
            mejor_score_bloqueo = score_7d
            mejor_ganancia = rend_7d["ganancia_neta"]
            mejor_plazo = 7

    print(f"\n  {'-'*50}")
    print("  ANALISIS POR PLAZO:")
    print(f"  {'-'*50}")

    if not resultados_por_plazo:
        print("  [NO] Sin datos de tasa para ningun plazo.")
        print(f"{'='*60}")
        return {"puede_operar": False, "motivo": "Sin tasas disponibles"}

    for p, r in sorted(resultados_por_plazo.items()):
        rend = r["rend"]
        estado = "SENAL" if r["tiene_senal"] else "SIN_SENAL"
        prom_str = f"{r['promedio']:.1f}%" if r["promedio"] else "sin historial"
        cap_min_txt = "inviable" if r["capital_minimo_requerido"] is None else f"{r['capital_minimo_requerido']:,.0f}"
        print(
            f"  {p}d | TNA {r['tna']:.2f}% | Ganancia {rend['ganancia_neta']:+.2f} ARS | "
            f"G/DiaBloq {r['ganancia_neta_por_dia_bloqueo']:+.2f} | "
            f"Prom {prom_str} | Desv {r['desviacion_pct']:+.1f}% | CapMin {cap_min_txt} | {estado}"
        )

    disparo_1_3 = any(
        (r["plazo"] in (1, 2, 3)) and r["tiene_senal"]
        for r in resultados_por_plazo.values()
    )
    cascade_aplicada = False
    if fin_rueda and not disparo_1_3:
        candidatos = [
            r for r in resultados_por_plazo.values()
            if r["plazo"] in (1, 2, 3)
            and r["capital_minimo_requerido"] is not None
            and r["capital_faltante"] <= 0
            and r["rend"]["ganancia_neta"] > 0
        ]
        if candidatos:
            elegido = sorted(
                candidatos,
                key=lambda r: (
                    -float(r.get("ganancia_neta_por_dia_bloqueo", -999999)),
                    -float(r["rend"]["ganancia_neta"]),
                    int(r["plazo"]),
                ),
            )[0]
            mejor_plazo = elegido["plazo"]
            if not elegido["tiene_senal"]:
                elegido["tiene_senal"] = True
                elegido["motivo_no_senal"] = "Cascada cierre: fallback por rentabilidad positiva (1-3d)"
            cascade_aplicada = True
            print(f"  [CASCADE] Cierre sin disparo 1-3d -> seleccionado {mejor_plazo}d")

    mejor = resultados_por_plazo[mejor_plazo]
    rend = mejor["rend"]
    tna = mejor["tna"]
    plazo = mejor["plazo"]
    vencimiento = mejor["vencimiento"]
    fuente_tna = mejor["fuente_tna"]
    promedio = mejor["promedio"]
    desviacion_pct = mejor["desviacion_pct"]
    capital_minimo_requerido = mejor["capital_minimo_requerido"]
    capital_faltante = mejor["capital_faltante"]
    tiene_senal = mejor["tiene_senal"]
    motivo_no_senal = mejor["motivo_no_senal"]

    print(f"\n  {'-'*50}")
    print(f"  MEJOR PLAZO: {plazo} dia(s) - vence {vencimiento}")
    print(f"  {'-'*50}")
    print(f"  Fuente tasa:      {fuente_tna}")
    print(f"  TNA mercado:      {tna:.2f}%")
    print(f"  Capital colocado: ARS {rend['monto_colocado']:>12,.2f}")
    print(f"  Ganancia bruta:   ARS {rend['ganancia_bruta']:>12,.2f}")
    print(f"  Comision IOL:     ARS {rend['comision_iol']:>12,.2f}")
    print(f"  Ganancia NETA:    ARS {rend['ganancia_neta']:>12,.2f}")
    print(f"  Al vencimiento:   ARS {rend['monto_al_vencimiento']:>12,.2f}")
    print(f"  Rentabilidad:     {rend['rentabilidad_pct']:.4f}%")
    print(f"  G/Dia bloqueo:    ARS {mejor['ganancia_neta_por_dia_bloqueo']:>12,.4f}")
    prom_str = f"{promedio:.2f}% TNA" if promedio else "sin historial aun"
    print(f"  Prom. historico:  {prom_str}")
    print(f"  Desviacion:       {desviacion_pct:+.1f}%")
    if capital_minimo_requerido is None:
        print("  Cap. minimo:      Inviable para cualquier capital (costos actuales)")
    else:
        print(f"  Cap. minimo:      ARS {capital_minimo_requerido:>12,.2f}")
        print(f"  Cap. faltante:    ARS {capital_faltante:>12,.2f}")
    if media_capital_min is not None:
        print(f"  Media cap. min 7d: ARS {media_capital_min:,.2f} ({muestras_media_capital} muestras)")

    if analisis_oportunidad.get("disponible"):
        print(
            f"  EV esperar/carry: {analisis_oportunidad['ev_esperar_diario']:+.2f} / "
            f"{analisis_oportunidad['ev_carry_diario']:+.2f} ARS-d | "
            f"{analisis_oportunidad['decision']}"
        )
    if tna_7d is not None:
        print(f"  Regla 7d:        {'HABILITADO' if usar_7d else 'DESCARTADO'} (TNA 7d={tna_7d:.2f}%)")

    estado_senal = semaforo(desviacion_pct, tiene_senal)
    print(f"  Estado:           {estado_senal}")

    if not tiene_senal:
        print(f"\n  [INFO] Sin senal: {motivo_no_senal}")
    else:
        print(f"\n  [SENAL] Tasa {tna:.1f}% TNA | Plazo {plazo}d | Ganancia ARS {rend['ganancia_neta']:.2f}")
        print(f"          Colocar ARS {capital:,.0f} | Vence {vencimiento}")

    print(f"{'='*60}")

    datos_guardar = {
        "timestamp": ahora.isoformat(),
        "fecha_vencimiento": str(vencimiento),
        "plazo_dias": plazo,
        "tna_mercado": tna,
        "fuente_tasa": fuente_tna,
        "saldo_disponible": saldo,
        "fuente_saldo": fuente_saldo,
        "capital_usado": capital,
        "pct_capital_usado": pct_capital,
        "ganancia_bruta": rend["ganancia_bruta"],
        "comision_iol": rend["comision_iol"],
        "ganancia_neta": rend["ganancia_neta"],
        "ganancia_neta_por_dia_bloqueo": mejor["ganancia_neta_por_dia_bloqueo"],
        "rentabilidad_pct": rend["rentabilidad_pct"],
        "tna_efectiva": rend["tna_efectiva"],
        "monto_al_vencimiento": rend["monto_al_vencimiento"],
        "promedio_historico": promedio if promedio else 0,
        "desviacion_pct": desviacion_pct,
        "tiene_senal": tiene_senal,
        "motivo_no_senal": motivo_no_senal,
        "estado": "SIMULADA",
        "capital_minimo_requerido": capital_minimo_requerido,
        "capital_faltante": capital_faltante,
        "ev_esperar_diario": analisis_oportunidad.get("ev_esperar_diario"),
        "ev_carry_diario": analisis_oportunidad.get("ev_carry_diario"),
        "decision_oportunidad": analisis_oportunidad.get("decision"),
        "comision_pct_aplicada": comision_pct_aplicada,
        "origen_comision": origen_comision,
    }
    guardar_simulacion(datos_guardar)
    if fuente_tna == "IOL_WEB":
        guardar_tasa_historica(tna, fuente_tna)

    if tiene_senal:
        ok = guardar_senal_db(tna, promedio or 0, desviacion_pct, capital,
                              rend["ganancia_neta"], plazo, vencimiento)
        if ok:
            print("  [OK] Senal guardada en base de datos.")

    return {
        "puede_operar": True,
        "tna": tna,
        "fuente_tna": fuente_tna,
        "saldo": saldo,
        "fuente_saldo": fuente_saldo,
        "capital": capital,
        "plazo": plazo,
        "vencimiento": str(vencimiento),
        "ganancia_neta": rend["ganancia_neta"],
        "rentabilidad_pct": rend["rentabilidad_pct"],
        "promedio": promedio,
        "desviacion_pct": desviacion_pct,
        "capital_minimo_requerido": capital_minimo_requerido,
        "capital_faltante": capital_faltante,
        "media_capital_minimo_7d": media_capital_min,
        "ev_esperar_diario": analisis_oportunidad.get("ev_esperar_diario"),
        "ev_carry_diario": analisis_oportunidad.get("ev_carry_diario"),
        "decision_oportunidad": analisis_oportunidad.get("decision"),
        "comision_pct_aplicada": comision_pct_aplicada,
        "origen_comision": origen_comision,
        "cascade_cierre_aplicada": cascade_aplicada,
        "fin_rueda_caucion": fin_rueda,
        "disparo_1_3": disparo_1_3,
        "tna_7d": tna_7d,
        "usa_7d_extraordinaria": usar_7d,
        "tiene_senal": tiene_senal,
        "motivo_no_senal": motivo_no_senal,
        "todos_los_plazos": {
            p: {
                "tna": r["tna"],
                "ganancia": r["rend"]["ganancia_neta"],
                "ganancia_neta_por_dia_bloqueo": r.get("ganancia_neta_por_dia_bloqueo"),
                "tiene_senal": r["tiene_senal"],
                "capital_minimo_requerido": r["capital_minimo_requerido"],
                "capital_faltante": r["capital_faltante"],
            }
            for p, r in resultados_por_plazo.items()
        },
    }

if __name__ == "__main__":
    import sqlite3, os
    os.makedirs(os.path.join(os.path.dirname(__file__), "datos"), exist_ok=True)

    print("Iniciando motor_cauciones.py - modo real estricto (solo IOL web)")
    resultado = analizar_cauciones(modo="real")

    if resultado:
        print(f"\nResumen:")
        print(f"  Puede operar: {resultado.get('puede_operar')}")
        print(f"  Tiene señal:  {resultado.get('tiene_senal')}")
        if resultado.get("puede_operar"):
            print(f"  Mejor plazo:  {resultado.get('plazo')}d | TNA {resultado.get('tna')}% | Ganancia ARS {resultado.get('ganancia_neta')}")


