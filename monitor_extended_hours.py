"""
monitor_extended_hours.py — Monitor de oportunidades en pre/post market de NYSE.

El CEDEAR en BYMA NO se mueve cuando NYSE está en horario extendido.
Pero la acción en NYSE SÍ puede moverse.

Si la acción sube/baja significativamente en extended hours, hay dos tipos de
oportunidades que el bot puede detectar y alertar:

  PRE-MARKET (6:00 - 11:30hs Argentina):
    La acción subió/bajó antes de que BYMA abra.
    Al abrir BYMA a las 11hs, el CEDEAR debería ajustarse.
    → Oportunidad: comprar/vender CEDEAR en la apertura de BYMA (11hs)
      antes de que el precio se ajuste completamente.

  POST-MARKET (18:00 - 23:00hs Argentina):
    BYMA ya cerró (17hs). La acción NYSE sigue moviendose.
    → Oportunidad: mañana a las 11hs el CEDEAR abrirá ajustado.
      Si sabemos hoy que la acción subió/bajó, podemos posicionarnos
      antes de que el mercado local lo refleje.

IMPORTANTE:
  - El volumen en extended hours es MUY bajo (5-10% del volumen regular)
  - Los precios pueden ser de una sola operación de pocos lotes
  - Alta probabilidad de reversión al abrir el mercado regular
  - El bot NUNCA ejecuta en extended hours, solo ALERTA para mañana
  - Estas son señales especulativas, no de arbitraje puro

FUENTE DE PRECIOS:
  - IOL puede devolver precios de extended hours para algunos símbolos
  - Si no está disponible, el módulo usa el último precio regular de la DB
    y marca la señal como "sin dato extended"
"""

import os
import json
import sqlite3
from datetime import datetime
import pytz

from config import RUTA_DATOS, NOMBRE_DB, CEDEARS
from simulador_operaciones import detectar_horario_nyse, analizar_oportunidad_extended_hours

RUTA_DB              = os.path.join(RUTA_DATOS, NOMBRE_DB)
RUTA_ALERTAS_EXTENDED = os.path.join(RUTA_DATOS, "alertas_extended_hours.json")

ZONA_ARG = pytz.timezone("America/Argentina/Buenos_Aires")

# Umbral mínimo de spread para generar alerta en extended hours
SPREAD_MIN_EXTENDED = 3.0    # % — más bajo que el regular por baja confiabilidad


def obtener_precio_extended_iol(simbolo_iol):
    """
    Intenta obtener el precio en extended hours desde IOL.
    IOL en algunos casos devuelve 'ultimoPrecio' que puede ser de extended hours.
    Devuelve (precio, es_extended_confirmado)
    """
    try:
        from iol_connector import obtener_cotizacion_cedear
        datos = obtener_cotizacion_cedear(simbolo_iol)
        if datos and isinstance(datos, dict):
            precio = datos.get("ultimoPrecio") or datos.get("precioPromedio")
            if precio and float(precio) > 0:
                # IOL no distingue claramente si es regular o extended
                # Lo marcamos como "no confirmado"
                return float(precio), False
    except Exception:
        pass
    return None, False


def obtener_ultimo_precio_nyse_db(simbolo_nyse):
    """Obtiene el último precio NYSE guardado en la DB."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        c = conn.cursor()
        c.execute("""
            SELECT precio_usd FROM precios_nyse
            WHERE simbolo = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (simbolo_nyse,))
        fila = c.fetchone()
        conn.close()
        return fila[0] if fila else None
    except Exception:
        return None


def obtener_ultimo_precio_cedear_db(simbolo):
    """Obtiene el último precio ARS del CEDEAR guardado (para usar como precio de cierre BYMA)."""
    try:
        conn = sqlite3.connect(RUTA_DB)
        c = conn.cursor()
        # Buscar en la tabla de señales el último CCL implícito y reconstruir el precio ARS
        c.execute("""
            SELECT ccl_implicito, ccl_referencia FROM seniales
            WHERE simbolo = ? AND tipo = 'arbitraje'
            ORDER BY fecha_hora DESC LIMIT 1
        """, (simbolo,))
        fila = c.fetchone()
        conn.close()
        return fila  # (ccl_impl, ccl_ref) o None
    except Exception:
        return None


def guardar_alerta_extended(alerta):
    """Guarda alertas de extended hours en JSON."""
    alertas = []
    if os.path.exists(RUTA_ALERTAS_EXTENDED):
        try:
            with open(RUTA_ALERTAS_EXTENDED) as f:
                alertas = json.load(f)
        except Exception:
            alertas = []

    alertas.insert(0, alerta)
    alertas = alertas[:100]

    with open(RUTA_ALERTAS_EXTENDED, "w") as f:
        json.dump(alertas, f, indent=2)


def get_alertas_extended():
    """Para el dashboard."""
    if not os.path.exists(RUTA_ALERTAS_EXTENDED):
        return []
    try:
        with open(RUTA_ALERTAS_EXTENDED) as f:
            return json.load(f)
    except Exception:
        return []


def monitorear_extended_hours(ccl_referencia):
    """
    Función principal. Corre cuando NYSE está en pre o post market.
    Analiza todos los CEDEARs y detecta si hay movimientos significativos.
    """
    horario, es_extended = detectar_horario_nyse()

    if not es_extended:
        return []

    ahora = datetime.now(ZONA_ARG)
    print(f"\n{'='*65}")
    print(f"  MONITOR EXTENDED HOURS — {horario.upper()}")
    print(f"  {ahora.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  CCL referencia: ${ccl_referencia:,.2f}")
    print(f"{'='*65}")
    print(f"  {'CEDEAR':<7} {'Precio NYSE':>12} {'Spread extd':>12}  SITUACIÓN")
    print(f"  {'-'*55}")

    alertas_generadas = []

    # Cargar último ratio de JSON
    ruta_ratios = os.path.join(RUTA_DATOS, "ratios_comafi.json")
    ratios_json = {}
    if os.path.exists(ruta_ratios):
        try:
            import json as _json
            ratios_json = _json.load(open(ruta_ratios)).get("ratios", {})
        except Exception:
            pass

    for simbolo, datos in CEDEARS.items():
        simbolo_nyse = datos["simbolo_nyse"]
        simbolo_iol  = datos.get("simbolo_iol", simbolo)
        ratio        = ratios_json.get(simbolo, datos["ratio"])

        # Obtener precio NYSE (puede ser regular o extended)
        precio_usd = obtener_ultimo_precio_nyse_db(simbolo_nyse)
        if not precio_usd:
            continue

        # Precio ARS del cierre BYMA (último que tenemos)
        # Estimamos a partir del CCL implícito guardado o precio teórico
        info_senal = obtener_ultimo_precio_cedear_db(simbolo)
        if info_senal:
            ccl_impl_anterior, ccl_ref_anterior = info_senal
            # Precio ARS = (precio_USD / ratio) * ccl_implicito_anterior
            precio_ars_cierre = (precio_usd / ratio) * ccl_impl_anterior
        else:
            # Sin dato anterior: estimar precio teórico con CCL actual
            precio_ars_cierre = (precio_usd / ratio) * ccl_referencia

        # Analizar oportunidad
        analisis = analizar_oportunidad_extended_hours(
            simbolo=simbolo,
            precio_ars_cierre_byma=precio_ars_cierre,
            precio_usd_extended=precio_usd,
            ratio=ratio,
            ccl_referencia=ccl_referencia
        )

        if not analisis["es_extended"]:
            continue

        spread = analisis["spread_pct"]
        situacion = analisis["situacion"]

        if abs(spread) >= SPREAD_MIN_EXTENDED:
            icono = "★" if "COMPRA" in situacion else ("▼" if "VENTA" in situacion else "·")
            print(f"  {simbolo:<7} ${precio_usd:>10.2f}  {spread:>+10.2f}%  {icono} {situacion}")

            alerta = {
                "timestamp":    ahora.isoformat(),
                "horario":      horario,
                "simbolo":      simbolo,
                "nombre":       datos["nombre"],
                "spread_pct":   spread,
                "situacion":    situacion,
                "descripcion":  analisis["descripcion"],
                "accion":       analisis["accion"],
                "confiabilidad": analisis["confiabilidad"],
                "vista":        False,
            }
            guardar_alerta_extended(alerta)
            alertas_generadas.append(alerta)
        else:
            print(f"  {simbolo:<7} ${precio_usd:>10.2f}  {spread:>+10.2f}%  ·")

    print(f"\n  Alertas extended hours: {len(alertas_generadas)}")
    if alertas_generadas:
        print(f"  → Estas oportunidades son especulativas y de baja confiabilidad.")
        print(f"  → El bot las mostrará en el dashboard para que las evalúes mañana.")
    print(f"{'='*65}\n")

    return alertas_generadas


if __name__ == "__main__":
    # Test manual
    from obtener_ccl import obtener_ccl
    ccl = obtener_ccl()
    if ccl:
        alertas = monitorear_extended_hours(ccl)
        print(f"\nAlertas generadas: {len(alertas)}")
    else:
        print("No se pudo obtener CCL para el test.")
