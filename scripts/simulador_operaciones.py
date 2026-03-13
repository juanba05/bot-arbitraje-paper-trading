"""
simulador_operaciones.py — Simulación realista de arbitraje CEDEAR→NYSE en IOL.

COSTOS REALES IOL (verificados Feb 2026, fuente: invertironline.com/tarifas-estados-unidos):
  BYMA (venta CEDEAR):
    - Comisión IOL: 0.60% + IVA (21%)
    - Derechos de mercado BYMA: incluidos en la comisión
  NYSE (compra acción):
    - Comisión IOL: 0.35% + IVA (21%), mínimo USD 2 + IVA
    - ADR Fee: ~0.02 USD por ADR/CEDEAR, estimado anual 2% del valor nominal
      (lo cobra el banco depositario, no IOL, pero IOL lo transfiere al cliente)
    - SEC Fee: USD 8.50 por USD 1.000.000 operados (despreciable en montos pequeños)

  CONVERSIÓN DE MONEDA (ARS → USD para comprar en NYSE):
    - IOL no publica el spread, estimado en 1.0% a 2.0% sobre el monto convertido
    - Se modela como "spread_conversion_pct" configurable (default 1.5%)
    - ESTE ES EL COSTO MÁS IMPORTANTE Y MÁS OPACO DEL CICLO COMPLETO

  PARKING (regulación BCRA/CNV):
    - Para vender CEDEAR y usar los ARS para comprar MEP/CCL:
      el CEDEAR debe estar en tenencia al menos 1 día hábil previo a la venta
    - Si el CEDEAR fue "comprado" en el mismo ciclo → parking BLOQUEADO
    - El simulador asume que el CEDEAR YA está en cartera (parking cumplido)
      salvo que se indique explícitamente lo contrario

  LIQUIDACIÓN:
    - Venta CEDEAR BYMA: fondos disponibles para operar en la misma sesión
      (NO para retirar hasta T+2)
    - Compra acción NYSE: liquida en T+1
    - Descalce: 1 día de riesgo de tipo de cambio entre venta y liquidación NYSE

PRE/POST MARKET:
    - El simulador detecta si el precio NYSE es de horario extendido
    - Aplica un descuento de confiabilidad al spread en pre/post market
    - Informa el riesgo adicional de volatilidad de precios en horario extendido

MODELO PARA PAPER TRADING:
    - El bot NO hace conversiones reales, solo simula el resultado
    - Las "ganancias" de arbitraje son en USD (dolarización del capital)
    - Las ganancias en ARS solo se realizan si se cierra el ciclo completo
"""

import os
import sqlite3
from datetime import datetime, timedelta
import pytz

from config import RUTA_DATOS, NOMBRE_DB, CEDEARS

RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)

ZONA_ARG  = pytz.timezone("America/Argentina/Buenos_Aires")
ZONA_NY   = pytz.timezone("America/New_York")

# ── ESTRUCTURA DE COSTOS IOL (actualizada Feb 2026) ─────────────
COSTOS = {
    # BYMA — venta del CEDEAR
    "byma_comision_pct":    0.60,   # % sobre monto ARS
    "byma_iva_pct":         0.21,   # IVA sobre la comisión

    # NYSE — compra de la acción
    "nyse_comision_pct":    0.35,   # % sobre monto USD
    "nyse_comision_min_usd": 2.00,  # mínimo USD sin IVA
    "nyse_iva_pct":         0.21,   # IVA sobre la comisión
    "nyse_adr_fee_pct":     0.02,   # 2% del valor nominal (banco depositario)
    "nyse_sec_fee_ppm":     8.50,   # USD por cada USD 1.000.000 (despreciable)

    # CONVERSIÓN ARS→USD (spread oculto de IOL, no publicado oficialmente)
    "spread_conversion_pct": 1.50,  # estimado conservador 1.5% sobre el monto

    # SLIPPAGE según volumen
    "slippage_alto_pct":    0.80,   # > 500 CEDEARs
    "slippage_medio_pct":   0.50,   # 100-500 CEDEARs
    "slippage_bajo_pct":    0.25,   # < 100 CEDEARs

    # UMBRAL para tipo de orden
    "spread_limite_alto":   6.0,    # > 6%: orden LÍMITE (capturar precio exacto)
    "spread_limite_medio":  3.0,    # 3-6%: LÍMITE con 0.2% de margen
    # < 3%: MERCADO (asegurar ejecución)
}

# ── DESCUENTOS POR HORARIO EXTENDIDO ────────────────────────────
# El spread calculado con precio de pre/post market es menos confiable
DESCUENTO_PREMARKET  = 0.40   # se descuenta 40% de la ganancia estimada
DESCUENTO_POSTMARKET = 0.35   # se descuenta 35% (post market es más líquido)


def crear_tabla_simulaciones():
    """Crea la tabla de simulaciones si no existe."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS simulaciones_operaciones (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp           TEXT NOT NULL,
                simbolo             TEXT,
                nombre              TEXT,
                horario             TEXT,
                es_extended_hours   INTEGER DEFAULT 0,
                spread_pct          REAL,
                spread_ajustado_pct REAL,
                ccl_implicito       REAL,
                ccl_referencia      REAL,
                capital_ars         REAL,
                cedears_cantidad    INTEGER,
                tipo_orden_byma     TEXT,
                tipo_orden_nyse     TEXT,
                precio_ars_entrada  REAL,
                precio_usd_entrada  REAL,
                ratio               INTEGER,
                parking_ok          INTEGER DEFAULT 1,
                slippage_estimado_pct REAL,
                comision_byma       REAL,
                comision_byma_iva   REAL,
                comision_nyse_usd   REAL,
                comision_nyse_iva_usd REAL,
                adr_fee_usd         REAL,
                spread_conversion_ars REAL,
                comision_total_ars  REAL,
                ganancia_bruta_ars  REAL,
                ganancia_neta_ars   REAL,
                ganancia_neta_usd   REAL,
                rentabilidad_pct    REAL,
                viable              INTEGER DEFAULT 0,
                motivo_no_viable    TEXT,
                fecha_liquidacion_byma TEXT,
                fecha_liquidacion_nyse TEXT,
                dias_descalce       INTEGER,
                riesgo_extended     TEXT,
                notas               TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SIM] Error creando tabla: {e}")


def detectar_horario_nyse(precio_usd=None):
    """
    Detecta si el mercado NYSE está en horario regular, pre-market o post-market.

    NYSE (hora New York):
      Pre-market:  04:00 - 09:30
      Regular:     09:30 - 16:00
      Post-market: 16:00 - 20:00

    Horario Argentina (UTC-3):
      Pre-market:  06:00 - 11:30
      Regular:     11:30 - 18:00 (coincide parcialmente con BYMA 11-17hs)
      Post-market: 18:00 - 23:00

    Nota: BYMA cierra a las 17hs Argentina = 14:00 NY = mercado regular NYSE
    El overlap BYMA-NYSE regular es 11:30hs a 17:00hs Argentina.
    """
    ahora_arg = datetime.now(ZONA_ARG)
    ahora_ny  = ahora_arg.astimezone(ZONA_NY)

    hora_ny_h = ahora_ny.hour + ahora_ny.minute / 60

    es_fin_semana = ahora_ny.weekday() >= 5

    if es_fin_semana:
        return "cerrado", False

    if 4.0 <= hora_ny_h < 9.5:
        return "pre-market", True
    elif 9.5 <= hora_ny_h < 16.0:
        return "regular", False
    elif 16.0 <= hora_ny_h < 20.0:
        return "post-market", True
    else:
        return "cerrado", False


def _dias_habiles_siguientes(n, desde_fecha=None):
    """Devuelve la fecha que resulta de sumar n días hábiles desde hoy (o desde la fecha dada)."""
    fecha = desde_fecha or datetime.now(ZONA_ARG).date()
    contados = 0
    while contados < n:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5:  # lunes a viernes
            contados += 1
    return fecha.strftime("%d/%m/%Y")


def _slippage_pct(cantidad_cedears):
    if cantidad_cedears > 500:
        return COSTOS["slippage_alto_pct"]
    elif cantidad_cedears >= 100:
        return COSTOS["slippage_medio_pct"]
    return COSTOS["slippage_bajo_pct"]


def _tipo_orden(spread_pct):
    sp = abs(spread_pct)
    if sp >= COSTOS["spread_limite_alto"]:
        return "LÍMITE", "LÍMITE"
    elif sp >= COSTOS["spread_limite_medio"]:
        return "LÍMITE", "LÍMITE"
    else:
        return "MERCADO", "MERCADO"


def simular_arbitraje(simbolo, precio_ars, precio_usd, ratio, ccl_implicito,
                      ccl_referencia, spread_pct, capital_disponible=40000.0,
                      parking_cumplido=True):
    """
    Simula la operación de arbitraje CEDEAR→NYSE con todos los costos reales de IOL.

    Flujo:
      1. Vender CEDEARs en BYMA (ARS)
      2. Convertir ARS → USD (con spread de conversión)
      3. Comprar acción en NYSE (USD)

    Devuelve dict con todos los datos de la simulación.
    """
    ahora = datetime.now()
    horario_nyse, es_extended = detectar_horario_nyse()

    # ── Capital máximo a usar (30% del disponible) ─────────────
    capital_max = capital_disponible * 0.30
    cantidad    = max(1, int(capital_max / precio_ars))
    capital_ars = round(precio_ars * cantidad, 2)

    # ── Tipo de orden ──────────────────────────────────────────
    tipo_byma, tipo_nyse = _tipo_orden(spread_pct)

    # ── Slippage ───────────────────────────────────────────────
    slippage_pct = _slippage_pct(cantidad)

    # ── COSTOS BYMA (venta CEDEAR en ARS) ─────────────────────
    com_byma     = round(capital_ars * COSTOS["byma_comision_pct"] / 100, 2)
    com_byma_iva = round(com_byra := com_byma * COSTOS["byma_iva_pct"], 2)
    com_byma_total = round(com_byma + com_byma_iva, 2)

    # Slippage en venta BYMA
    slippage_ars = round(capital_ars * slippage_pct / 100, 2)

    # ── CONVERSIÓN ARS → USD ───────────────────────────────────
    # El spread de conversión es el costo oculto más importante.
    # IOL te da un tipo de cambio peor que el CCL de referencia.
    # En papel: reducimos el CCL efectivo en el spread.
    ccl_efectivo        = ccl_referencia * (1 - COSTOS["spread_conversion_pct"] / 100)
    costo_conversion    = round(capital_ars * COSTOS["spread_conversion_pct"] / 100, 2)

    # USD disponibles después de la conversión
    usd_disponibles = round(capital_ars / ccl_efectivo, 4)

    # ── COSTOS NYSE (compra acción en USD) ─────────────────────
    precio_usd_neto = precio_usd / ratio  # precio de 1 CEDEAR en USD
    monto_usd       = precio_usd_neto * cantidad

    com_nyse_usd     = max(COSTOS["nyse_comision_min_usd"],
                           round(monto_usd * COSTOS["nyse_comision_pct"] / 100, 4))
    com_nyse_iva_usd = round(com_nyse_usd * COSTOS["nyse_iva_pct"], 4)

    # ADR Fee (banco depositario)
    adr_fee_usd = round(monto_usd * COSTOS["nyse_adr_fee_pct"] / 100, 4)

    # SEC Fee (despreciable)
    sec_fee_usd = round(monto_usd * COSTOS["nyse_sec_fee_ppm"] / 1_000_000, 6)

    # Total costos NYSE en USD → convertir a ARS al CCL de referencia
    costos_nyse_usd = round(com_nyse_usd + com_nyse_iva_usd + adr_fee_usd + sec_fee_usd, 4)
    costos_nyse_ars = round(costos_nyse_usd * ccl_referencia, 2)

    # Slippage en compra NYSE (en ARS)
    slippage_nyse_ars = round(capital_ars * slippage_pct / 100, 2)

    # ── GANANCIA BRUTA ─────────────────────────────────────────
    ganancia_bruta_ars = round(capital_ars * abs(spread_pct) / 100, 2)

    # ── COSTO TOTAL ────────────────────────────────────────────
    costo_total_ars = round(
        com_byma_total +           # comisión BYMA + IVA
        slippage_ars +             # slippage venta BYMA
        costo_conversion +         # spread conversión ARS→USD
        costos_nyse_ars +          # comisiones NYSE (incluye ADR fee)
        slippage_nyse_ars          # slippage compra NYSE
    , 2)

    # ── GANANCIA NETA ──────────────────────────────────────────
    # Si el horario es extended (pre/post market), se aplica descuento
    # por menor confiabilidad del precio
    spread_ajustado = spread_pct
    riesgo_extended = ""

    if es_extended:
        if horario_nyse == "pre-market":
            descuento = DESCUENTO_PREMARKET
            riesgo_extended = (
                f"PRE-MARKET NYSE ({horario_nyse}): spread ajustado -{descuento*100:.0f}% "
                f"por baja liquidez. El precio puede cambiar significativamente "
                f"al abrir el mercado regular. Spread real puede ser ~0%."
            )
        else:  # post-market
            descuento = DESCUENTO_POSTMARKET
            riesgo_extended = (
                f"POST-MARKET NYSE ({horario_nyse}): spread ajustado -{descuento*100:.0f}% "
                f"por liquidez reducida. BYMA ya cerró, el precio refleja "
                f"movimientos de after-hours que pueden revertirse mañana."
            )
        spread_ajustado = round(spread_pct * (1 - descuento), 2)
        ganancia_bruta_ars = round(capital_ars * abs(spread_ajustado) / 100, 2)

    ganancia_neta_ars = round(ganancia_bruta_ars - costo_total_ars, 2)
    ganancia_neta_usd = round(ganancia_neta_ars / ccl_referencia, 4)
    rentabilidad_pct  = round(ganancia_neta_ars / capital_ars * 100, 4) if capital_ars > 0 else 0

    # ── PARKING ────────────────────────────────────────────────
    motivo_parking = ""
    if not parking_cumplido:
        motivo_parking = (
            "⚠️ PARKING NO CUMPLIDO: el CEDEAR debe estar en cartera "
            "≥1 día hábil antes de vender para comprar MEP/CCL. "
            "La conversión ARS→USD puede estar bloqueada por regulación BCRA/CNV. "
            "En paper trading se ignora, pero en real sería una operación incompleta."
        )

    # ── VIABILIDAD ─────────────────────────────────────────────
    min_ganancia_pct = 2.0  # mínimo exigido para arbitraje
    viable = ganancia_neta_ars > 0 and rentabilidad_pct >= min_ganancia_pct

    motivos_no_viable = []
    if ganancia_neta_ars <= 0:
        motivos_no_viable.append(f"ganancia neta negativa: ${ganancia_neta_ars:,.2f} ARS")
    if rentabilidad_pct < min_ganancia_pct:
        motivos_no_viable.append(f"rentabilidad {rentabilidad_pct:.3f}% < mínimo {min_ganancia_pct}%")
    if not parking_cumplido:
        motivos_no_viable.append("parking no cumplido (regulatorio)")

    motivo = " | ".join(motivos_no_viable) if motivos_no_viable else ""

    # ── LIQUIDACIÓN ────────────────────────────────────────────
    liq_byma  = _dias_habiles_siguientes(2)  # T+2
    liq_nyse  = _dias_habiles_siguientes(1)  # T+1
    descalce  = 1  # siempre 1 día hábil de diferencia

    # ── GUARDAR EN DB ──────────────────────────────────────────
    nombre = CEDEARS.get(simbolo, {}).get("nombre", simbolo)

    notas = []
    if es_extended:
        notas.append(f"Precio NYSE obtenido en {horario_nyse.upper()}")
    if COSTOS["spread_conversion_pct"] > 1.0:
        notas.append(f"Incluye spread de conversión ARS→USD ({COSTOS['spread_conversion_pct']}%)")
    notas.append(f"ADR Fee incluido: ${adr_fee_usd:.4f} USD")
    if motivo_parking:
        notas.append("PARKING: verificar antes de operar en real")

    try:
        conn = sqlite3.connect(RUTA_DB)
        c = conn.cursor()
        c.execute("""
            INSERT INTO simulaciones_operaciones (
                timestamp, simbolo, nombre, horario, es_extended_hours,
                spread_pct, spread_ajustado_pct, ccl_implicito, ccl_referencia,
                capital_ars, cedears_cantidad, tipo_orden_byma, tipo_orden_nyse,
                precio_ars_entrada, precio_usd_entrada, ratio, parking_ok,
                slippage_estimado_pct,
                comision_byma, comision_byma_iva,
                comision_nyse_usd, comision_nyse_iva_usd, adr_fee_usd,
                spread_conversion_ars, comision_total_ars,
                ganancia_bruta_ars, ganancia_neta_ars, ganancia_neta_usd,
                rentabilidad_pct, viable, motivo_no_viable,
                fecha_liquidacion_byma, fecha_liquidacion_nyse, dias_descalce,
                riesgo_extended, notas
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ahora.isoformat(), simbolo, nombre, horario_nyse, int(es_extended),
            spread_pct, spread_ajustado,
            round(ccl_implicito, 2), round(ccl_referencia, 2),
            capital_ars, cantidad, tipo_byma, tipo_nyse,
            precio_ars, precio_usd, ratio, int(parking_cumplido),
            slippage_pct,
            com_byma, com_byma_iva,
            com_nyse_usd, com_nyse_iva_usd, adr_fee_usd,
            costo_conversion, costo_total_ars,
            ganancia_bruta_ars, ganancia_neta_ars, ganancia_neta_usd,
            rentabilidad_pct, int(viable), motivo,
            liq_byma, liq_nyse, descalce,
            riesgo_extended, " | ".join(notas)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SIM] Error guardando simulación: {e}")

    return {
        "simbolo":              simbolo,
        "nombre":               nombre,
        "horario_nyse":         horario_nyse,
        "es_extended":          es_extended,
        "riesgo_extended":      riesgo_extended,
        "spread_pct":           spread_pct,
        "spread_ajustado":      spread_ajustado,
        "capital_ars":          capital_ars,
        "cantidad":             cantidad,
        "tipo_byma":            tipo_byma,
        "tipo_nyse":            tipo_nyse,
        "slippage_pct":         slippage_pct,
        "com_byma_total":       com_byma_total,
        "costo_conversion":     costo_conversion,
        "com_nyse_usd":         com_nyse_usd + com_nyse_iva_usd,
        "adr_fee_usd":          adr_fee_usd,
        "costos_nyse_ars":      costos_nyse_ars,
        "costo_total_ars":      costo_total_ars,
        "ganancia_bruta_ars":   ganancia_bruta_ars,
        "ganancia_neta_ars":    ganancia_neta_ars,
        "ganancia_neta_usd":    ganancia_neta_usd,
        "rentabilidad_pct":     rentabilidad_pct,
        "viable":               viable,
        "motivo":               motivo,
        "parking_ok":           parking_cumplido,
        "liq_byma":             liq_byma,
        "liq_nyse":             liq_nyse,
        "descalce_dias":        descalce,
    }


def imprimir_simulacion(s):
    """Imprime un resumen detallado de la simulación en consola."""
    ext_tag = f" [{s['horario_nyse'].upper()}]" if s['es_extended'] else ""
    viable  = "✅ VIABLE" if s['viable'] else "❌ NO VIABLE"

    print(f"\n{'='*65}")
    print(f"  SIMULACIÓN {s['simbolo']} — {s['nombre']}{ext_tag}")
    print(f"  {viable}")
    print(f"{'='*65}")

    if s['es_extended']:
        print(f"\n  ⚠️  HORARIO EXTENDIDO:")
        for linea in s['riesgo_extended'].split('.'):
            if linea.strip():
                print(f"     {linea.strip()}.")

    print(f"\n  SEÑAL:")
    print(f"    Spread original:    {s['spread_pct']:+.2f}%")
    if s['es_extended']:
        print(f"    Spread ajustado:   {s['spread_ajustado']:+.2f}% (penalizado por ext. hours)")

    print(f"\n  OPERACIÓN:")
    print(f"    {s['cantidad']} CEDEARs × ${s['capital_ars']/s['cantidad']:,.2f} = ${s['capital_ars']:,.0f} ARS")
    print(f"    Orden BYMA:  {s['tipo_byma']}")
    print(f"    Orden NYSE:  {s['tipo_nyse']}")
    print(f"    Slippage:    {s['slippage_pct']}%")

    print(f"\n  DESGLOSE DE COSTOS:")
    print(f"    Com. BYMA (0.60%+IVA):  ${s['com_byma_total']:,.2f} ARS")
    print(f"    Conv. ARS→USD (1.50%):  ${s['costo_conversion']:,.2f} ARS  ← costo oculto IOL")
    print(f"    Com. NYSE (0.35%+IVA):  ${s['costos_nyse_ars']:,.2f} ARS (incl. ADR fee)")
    print(f"    ADR Fee (2% anual):     ${s['adr_fee_usd']:.4f} USD")
    print(f"    ─────────────────────────────────────────────")
    print(f"    TOTAL COSTOS:           ${s['costo_total_ars']:,.2f} ARS")

    print(f"\n  RESULTADO:")
    print(f"    Ganancia bruta:         ${s['ganancia_bruta_ars']:,.2f} ARS")
    print(f"    Menos costos:          -${s['costo_total_ars']:,.2f} ARS")
    print(f"    ─────────────────────────────────────────────")
    cg = "✅" if s['ganancia_neta_ars'] > 0 else "❌"
    print(f"  {cg} GANANCIA NETA:        ${s['ganancia_neta_ars']:,.2f} ARS")
    print(f"                          ≈ ${s['ganancia_neta_usd']:.4f} USD")
    print(f"  Rentabilidad:           {s['rentabilidad_pct']:+.3f}% sobre capital")

    print(f"\n  LIQUIDACIÓN:")
    print(f"    Venta CEDEAR (T+2):     {s['liq_byma']}")
    print(f"    Compra NYSE  (T+1):     {s['liq_nyse']}")
    print(f"    Descalce:               {s['descalce_dias']} día hábil de riesgo cambiario")

    if not s['parking_ok']:
        print(f"\n  ⚠️  PARKING: CEDEAR debe estar en cartera ≥1 día hábil antes de vender para CCL")

    if s['motivo']:
        print(f"\n  Motivo no viable: {s['motivo']}")

    print(f"{'='*65}\n")


# ──────────────────────────────────────────────────────────────────
# ANÁLISIS PRE/POST MARKET
# ──────────────────────────────────────────────────────────────────

def analizar_oportunidad_extended_hours(simbolo, precio_ars_cierre_byma,
                                         precio_usd_extended, ratio,
                                         ccl_referencia):
    """
    Analiza si hay oportunidad de arbitraje en horario extendido de NYSE.

    En pre/post market:
    - El CEDEAR no se mueve (BYMA cerrado)
    - La acción NYSE sí puede moverse

    Si la acción sube mucho en pre-market:
      → el CCL implícito del CEDEAR sube
      → mañana cuando abra BYMA el CEDEAR debería subir
      → la oportunidad NO es de arbitraje inmediato sino de POSICIÓN ESPECULATIVA:
        comprar el CEDEAR antes de que suba mañana

    Si la acción baja mucho en post-market:
      → el CCL implícito baja
      → el CEDEAR mañana debería bajar
      → la oportunidad es VENDER el CEDEAR antes de que baje mañana (si lo tenés)

    Devuelve un dict con el análisis de la situación.
    """
    horario, es_extended = detectar_horario_nyse()

    if not es_extended:
        return {"es_extended": False, "mensaje": "Mercado NYSE en horario regular."}

    # CCL implícito con precio de extended hours
    ccl_impl_extended = precio_ars_cierre_byma / (precio_usd_extended / ratio)
    spread_extended   = ((ccl_impl_extended - ccl_referencia) / ccl_referencia) * 100

    # Determinar la situación
    if abs(spread_extended) < 2.0:
        situacion = "SIN OPORTUNIDAD"
        descripcion = "Spread en extended hours menor al 2%, sin acción relevante."
        accion = None
    elif spread_extended > 2.0:
        # La acción subió → el CEDEAR quedó "barato" → conviene comprarlo antes de que suba
        situacion = "COMPRA ESPECULATIVA"
        descripcion = (
            f"La acción subió en {horario}. El CEDEAR de {simbolo} quedó barato "
            f"vs. el precio NYSE. Mañana al abrir BYMA el CEDEAR debería subir."
        )
        accion = "COMPRAR CEDEAR hoy en BYMA (si BYMA está abierto) o mañana al abrir"
    else:
        # La acción bajó → el CEDEAR quedó "caro" → conviene venderlo si lo tenés
        situacion = "VENTA ESPECULATIVA"
        descripcion = (
            f"La acción bajó en {horario}. El CEDEAR de {simbolo} quedó caro "
            f"vs. el precio NYSE. Mañana al abrir BYMA el CEDEAR debería bajar."
        )
        accion = "VENDER CEDEAR si está en cartera, antes de que BYMA lo ajuste mañana"

    return {
        "es_extended":        True,
        "horario":            horario,
        "simbolo":            simbolo,
        "precio_ars_byma":    precio_ars_cierre_byma,
        "precio_usd_extended": precio_usd_extended,
        "ccl_implicito":      round(ccl_impl_extended, 2),
        "ccl_referencia":     round(ccl_referencia, 2),
        "spread_pct":         round(spread_extended, 2),
        "situacion":          situacion,
        "descripcion":        descripcion,
        "accion":             accion,
        "confiabilidad":      "BAJA — volumen extendido es mínimo, precio puede revertirse",
    }


# ──────────────────────────────────────────────────────────────────
# TEST MANUAL
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    crear_tabla_simulaciones()

    horario_actual, extended = detectar_horario_nyse()
    print(f"\nHorario NYSE ahora: {horario_actual.upper()} | Extended hours: {extended}")

    print("\n" + "="*65)
    print("  TEST 1: Señal normal (AMD spread +3.99%) — horario regular")
    print("="*65)
    s1 = simular_arbitraje(
        simbolo="AMD", precio_ars=1250.0, precio_usd=125.0,
        ratio=10, ccl_implicito=1498.0, ccl_referencia=1443.0,
        spread_pct=3.99, capital_disponible=40000.0
    )
    imprimir_simulacion(s1)

    print("="*65)
    print("  TEST 2: Señal sospechosa (AAPL spread +9.27%) — pre-market")
    print("="*65)
    s2 = simular_arbitraje(
        simbolo="AAPL", precio_ars=7400.0, precio_usd=227.5,
        ratio=20, ccl_implicito=1576.0, ccl_referencia=1443.0,
        spread_pct=9.27, capital_disponible=40000.0
    )
    imprimir_simulacion(s2)

    print("="*65)
    print("  TEST 3: Análisis post-market (NVDA bajó 5% en after-hours)")
    print("="*65)
    analisis = analizar_oportunidad_extended_hours(
        simbolo="NVDA",
        precio_ars_cierre_byma=5800.0,
        precio_usd_extended=120.0,  # bajó 5%
        ratio=24,
        ccl_referencia=1443.0
    )
    if analisis["es_extended"]:
        print(f"  Situación: {analisis['situacion']}")
        print(f"  Spread:    {analisis['spread_pct']:+.2f}%")
        print(f"  Descripción: {analisis['descripcion']}")
        print(f"  Acción sugerida: {analisis['accion']}")
        print(f"  Confiabilidad: {analisis['confiabilidad']}")
    else:
        print(f"  {analisis['mensaje']}")

    print("\n✅ Tests completados. Simulaciones guardadas en la base de datos.")
    print("   Abrí el dashboard → pestaña SIMULACIONES para verlas.")
