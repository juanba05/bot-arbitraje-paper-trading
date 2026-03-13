"""
motor_calculo.py - Calcula spreads CEDEARs vs CCL de referencia.
MEJORAS:
- Filtro de señales repetidas: solo alerta si el spread cambió >30% vs la última señal
- Prioridad de ejecución por spread: ordena señales de mayor a menor rendimiento
- Doble validación para spreads >6% (potencialmente falsas)
- Integra simulador_operaciones.py automáticamente
- Integra detector_tickers_corruptos.py
"""

import sqlite3
import json
import os
import time
from datetime import datetime
from config import (
    CEDEARS, SPREAD_MINIMO_ARBITRAJE, SPREAD_VARIACION_MINIMA,
    SPREAD_SOSPECHOSO_UMBRAL, RUTA_DATOS, NOMBRE_DB
)
from obtener_ccl import obtener_ccl
from iol_connector import obtener_cotizacion_cedear, _asegurar_token
from detector_ratios import evaluar_precio, guardar_alerta_ratio, get_ratio_efectivo
from detector_tickers_corruptos import registrar_fallo, registrar_exito

RUTA_DB     = os.path.join(RUTA_DATOS, NOMBRE_DB)
RUTA_RATIOS = os.path.join(RUTA_DATOS, "ratios_comafi.json")

try:
    from simulador_operaciones import simular_arbitraje, crear_tabla_simulaciones
    SIMULADOR_DISPONIBLE = True
    crear_tabla_simulaciones()
except Exception as e:
    SIMULADOR_DISPONIBLE = False
    print(f"[MOTOR] Simulador no disponible: {e}")


def cargar_ratios():
    if not os.path.exists(RUTA_RATIOS):
        return {}
    with open(RUTA_RATIOS) as f:
        return json.load(f).get("ratios", {})


def obtener_ultimos_precios_nyse():
    conn = sqlite3.connect(RUTA_DB)
    c = conn.cursor()
    c.execute("SELECT simbolo, precio_usd, MAX(timestamp) FROM precios_nyse GROUP BY simbolo")
    filas = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in filas}


def obtener_ultimo_spread_senial(simbolo):
    """
    Devuelve el spread de la última señal guardada para este símbolo.
    Usado para el filtro de señales repetidas.
    """
    try:
        conn = sqlite3.connect(RUTA_DB)
        c = conn.cursor()
        c.execute("""
            SELECT spread_pct FROM seniales
            WHERE simbolo = ? AND tipo = 'arbitraje'
            ORDER BY fecha_hora DESC LIMIT 1
        """, (simbolo,))
        fila = c.fetchone()
        conn.close()
        return fila[0] if fila else None
    except Exception:
        return None


def spread_cambio_suficiente(spread_actual, spread_anterior):
    """
    Devuelve True si el spread cambió más del 30% en relación al spread anterior.
    Ejemplo: spread anterior 5%, actual 5.8% → cambio = 16% → NO alerta de nuevo.
    Ejemplo: spread anterior 5%, actual 7.5% → cambio = 50% → SÍ alerta.
    """
    if spread_anterior is None:
        return True  # primera vez, siempre alerta
    if spread_anterior == 0:
        return abs(spread_actual) >= SPREAD_MINIMO_ARBITRAJE
    variacion = abs(spread_actual - spread_anterior) / abs(spread_anterior)
    return variacion >= SPREAD_VARIACION_MINIMA


def obtener_precio_ars_iol(simbolo_iol):
    """Obtiene precio ARS de un CEDEAR desde IOL."""
    try:
        datos = obtener_cotizacion_cedear(simbolo_iol)
        if datos and isinstance(datos, dict):
            precio = datos.get("ultimoPrecio") or datos.get("precioPromedio")
            if precio and float(precio) > 0:
                return float(precio)
    except Exception:
        pass
    return None


def validar_spread_sospechoso(simbolo_iol, precio_usd_referencia, precio_ars_inicial,
                               spread_pct, ccl_referencia):
    """
    Para spreads > SPREAD_SOSPECHOSO_UMBRAL (6%), hace una segunda consulta a IOL
    para confirmar el precio. Si la segunda consulta difiere mucho de la primera,
    descarta la señal como falsa.
    Devuelve (precio_confirmado, es_valido, motivo)
    """
    if abs(spread_pct) < SPREAD_SOSPECHOSO_UMBRAL:
        return precio_ars_inicial, True, "spread normal, no requiere doble validacion"

    print(f"  [VALIDACION] Spread {spread_pct:+.2f}% sospechoso. Segunda consulta a IOL...")
    time.sleep(1)  # pequeña pausa para no saturar la API

    precio_ars_2 = obtener_precio_ars_iol(simbolo_iol)

    if precio_ars_2 is None:
        return precio_ars_inicial, False, "segunda consulta falló — descartado por precaución"

    diferencia = abs(precio_ars_2 - precio_ars_inicial) / precio_ars_inicial
    if diferencia > 0.02:  # si difiere más del 2% entre consultas
        return precio_ars_inicial, False, (
            f"precio inestable: consulta1={precio_ars_inicial:.2f}, "
            f"consulta2={precio_ars_2:.2f} (diff {diferencia*100:.1f}%) — descartado"
        )

    # Usar el promedio de las dos consultas para mayor precisión
    precio_promedio = (precio_ars_inicial + precio_ars_2) / 2
    return precio_promedio, True, f"confirmado con promedio de 2 consultas: ${precio_promedio:.2f}"


def guardar_senal(simbolo, ccl_implicito, ccl_referencia, spread, precio_usd):
    conn = sqlite3.connect(RUTA_DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO seniales (fecha_hora, tipo, simbolo, spread_pct,
                              ccl_implicito, ccl_referencia, descripcion, accion)
        VALUES (?, 'arbitraje', ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(), simbolo,
        round(spread, 4), round(ccl_implicito, 2), round(ccl_referencia, 2),
        f"CCL impl {ccl_implicito:.2f} vs ref {ccl_referencia:.2f}",
        "VENTA_CEDEAR_COMPRA_NYSE"
    ))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────
# MODO REAL
# ──────────────────────────────────────────────────────────────────

def calcular_spreads_real(ccl_referencia, capital_disponible=40000.0):
    if not _asegurar_token():
        print("ERROR: No se pudo conectar a IOL.")
        return 0

    ratios       = cargar_ratios()
    precios_nyse = obtener_ultimos_precios_nyse()

    if not precios_nyse:
        print("\nERROR: No hay precios NYSE. Ejecuta primero: python recolector.py")
        return 0

    print("\n" + "="*80)
    print(f"  MOTOR DE CALCULO [REAL]  |  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  CCL de referencia: ${ccl_referencia:,.2f}")
    print("="*80)
    print(f"  {'CEDEAR':<7} {'NYSE(USD)':>10} {'ARS(IOL)':>10} {'Ratio':>6} {'CCL Impl.':>11} {'SPREAD':>9}  RESULTADO")
    print("-"*80)

    seniales_candidatas = []  # lista de candidatas, luego se ordenan por spread
    sin_precio_ars      = []
    sin_precio_nyse     = []

    for simbolo_cedear, datos in CEDEARS.items():
        simbolo_nyse = datos["simbolo_nyse"]
        simbolo_iol  = datos.get("simbolo_iol", simbolo_cedear)
        ratio        = datos["ratio"]

        precio_usd = precios_nyse.get(simbolo_nyse)
        if not precio_usd:
            sin_precio_nyse.append(simbolo_cedear)
            registrar_fallo(simbolo_cedear, "Sin precio NYSE", simbolo_iol)
            continue

        precio_ars = obtener_precio_ars_iol(simbolo_iol)
        if not precio_ars:
            sin_precio_ars.append(simbolo_cedear)
            registrar_fallo(simbolo_cedear, f"Sin precio ARS en IOL (ticker: {simbolo_iol})", simbolo_iol)
            print(f"  {simbolo_cedear:<7} {precio_usd:>10.2f} {'sin precio ARS':>28}")
            continue

        ratio_guardado = ratios.get(simbolo_cedear, ratio)
        evaluacion = evaluar_precio(simbolo_cedear, precio_usd, ccl_referencia, precio_ars, ratio_guardado)

        if evaluacion["tipo"] == "corrupto":
            print(f"  {simbolo_cedear:<7} {precio_usd:>10.2f} {precio_ars:>10.2f} "
                  f"{'PRECIO CORRUPTO':>30}  ⚠️")
            print(f"           → {evaluacion['mensaje']}")
            registrar_fallo(simbolo_cedear,
                f"CORRUPTO: ratio impl={evaluacion['ratio_calculado']} vs guardado={ratio_guardado}. "
                f"Ticker IOL: '{simbolo_iol}'", simbolo_iol)
            continue

        registrar_exito(simbolo_cedear)

        if evaluacion["tipo"] == "ratio_cambiado":
            guardar_alerta_ratio(simbolo_cedear, ratio_guardado, evaluacion["ratio_calculado"],
                                  precio_ars, precio_usd, ccl_referencia)

        ratio_num, estado_ratio = get_ratio_efectivo(simbolo_cedear, ratio_guardado)
        tag_ratio = f"[{estado_ratio}]" if estado_ratio != "original" else ""

        ccl_implicito = precio_ars / (precio_usd / ratio_num)
        spread = ((ccl_implicito - ccl_referencia) / ccl_referencia) * 100

        if abs(spread) >= SPREAD_MINIMO_ARBITRAJE:
            # ── Filtro de señal repetida ──────────────────────
            spread_anterior = obtener_ultimo_spread_senial(simbolo_cedear)
            if not spread_cambio_suficiente(spread, spread_anterior):
                resultado = f"repetida ({spread:+.2f}% / ant {spread_anterior:+.2f}%)"
                print(f"  {simbolo_cedear:<7} {precio_usd:>10.2f} {precio_ars:>10.2f} "
                      f"{ratio_num:>6}{tag_ratio:<14} {ccl_implicito:>11.2f} {spread:>+8.2f}%  "
                      f"[FILTRADO — {resultado}]")
                continue

            # ── Doble validación para spreads sospechosos ─────
            precio_validado, es_valido, motivo_val = validar_spread_sospechoso(
                simbolo_iol, precio_usd, precio_ars, spread, ccl_referencia
            )

            if not es_valido:
                print(f"  {simbolo_cedear:<7} {precio_usd:>10.2f} {precio_ars:>10.2f} "
                      f"{ratio_num:>6}{tag_ratio:<14} {ccl_implicito:>11.2f} {spread:>+8.2f}%  "
                      f"[DESCARTADO — {motivo_val}]")
                continue

            if precio_validado != precio_ars:
                # Recalcular con precio confirmado
                ccl_implicito = precio_validado / (precio_usd / ratio_num)
                spread = ((ccl_implicito - ccl_referencia) / ccl_referencia) * 100
                precio_ars = precio_validado

            seniales_candidatas.append({
                "simbolo":       simbolo_cedear,
                "spread":        spread,
                "ccl_implicito": ccl_implicito,
                "precio_ars":    precio_ars,
                "precio_usd":    precio_usd,
                "ratio":         ratio_num,
                "tag_ratio":     tag_ratio,
                "sospechosa":    abs(spread) >= SPREAD_SOSPECHOSO_UMBRAL,
            })

            resultado = f">>> SEÑAL <<< {'+' if spread > 0 else ''}{spread:.2f}%"
        else:
            resultado = "."

        print(f"  {simbolo_cedear:<7} {precio_usd:>10.2f} {precio_ars:>10.2f} "
              f"{ratio_num:>6}{tag_ratio:<14} {ccl_implicito:>11.2f} {spread:>+8.2f}%  {resultado}")

    # ── ORDENAR SEÑALES POR PRIORIDAD ─────────────────────────
    # Las de mayor spread van primero (mayor rendimiento potencial)
    # PERO las sospechosas (>6%) van al final aunque tengan mayor spread
    seniales_candidatas.sort(
        key=lambda s: (1 if s["sospechosa"] else 0, -abs(s["spread"]))
    )

    # ── EJECUTAR SEÑALES EN ORDEN DE PRIORIDAD ─────────────────
    print()
    print("="*80)
    if sin_precio_ars:
        print(f"  Sin precio ARS: {', '.join(sin_precio_ars)}")
    if sin_precio_nyse:
        print(f"  Sin precio NYSE: {', '.join(sin_precio_nyse)}")

    print(f"\n  Señales detectadas: {len(seniales_candidatas)}")

    for i, s in enumerate(seniales_candidatas):
        prioridad = i + 1
        tag_sosp = " ⚠️ SOSPECHOSA" if s["sospechosa"] else ""
        print(f"  #{prioridad} {s['simbolo']}: {s['spread']:+.2f}%{tag_sosp}")

        # Guardar señal en DB
        guardar_senal(s["simbolo"], s["ccl_implicito"], ccl_referencia, s["spread"], s["precio_usd"])

        # Simular operacion
        if SIMULADOR_DISPONIBLE:
            try:
                sim = simular_arbitraje(
                    simbolo=s["simbolo"],
                    precio_ars=s["precio_ars"],
                    precio_usd=s["precio_usd"],
                    ratio=s["ratio"],
                    ccl_implicito=s["ccl_implicito"],
                    ccl_referencia=ccl_referencia,
                    spread_pct=s["spread"],
                    capital_disponible=capital_disponible,
                )
                est = "✅ VIABLE" if sim.get("viable") else "❌ NO VIABLE"
                print(f"     Simulacion: ${sim.get('ganancia_neta',0):,.2f} ARS netos — {est}")
            except Exception as e:
                print(f"     [SIM] Error: {e}")

    if not seniales_candidatas:
        print("  Todos los spreads dentro del rango normal.")
    print("="*80 + "\n")

    return len(seniales_candidatas)


# ──────────────────────────────────────────────────────────────────
# MODO SIMULACION
# ──────────────────────────────────────────────────────────────────

def calcular_spreads_simulado(ccl_referencia, desviacion_pct=5.0):
    import random
    ratios       = cargar_ratios()
    precios_nyse = obtener_ultimos_precios_nyse()
    if not precios_nyse:
        print("\nERROR: No hay precios NYSE.")
        return 0

    print("\n" + "="*80)
    print(f"  MOTOR [SIMULACION]  |  CCL: ${ccl_referencia:,.2f}  |  Desv: +/-{desviacion_pct}%")
    print("="*80)

    seniales = 0
    for simbolo_cedear, datos in CEDEARS.items():
        precio_usd = precios_nyse.get(datos["simbolo_nyse"])
        if not precio_usd:
            continue
        ratio_num = ratios.get(simbolo_cedear, datos["ratio"])
        desviacion    = random.uniform(-desviacion_pct, desviacion_pct) / 100
        precio_ars_sim = (precio_usd / ratio_num) * ccl_referencia * (1 + desviacion)
        ccl_implicito  = precio_ars_sim / (precio_usd / ratio_num)
        spread = ((ccl_implicito - ccl_referencia) / ccl_referencia) * 100
        if abs(spread) >= SPREAD_MINIMO_ARBITRAJE:
            seniales += 1
            guardar_senal(simbolo_cedear, ccl_implicito, ccl_referencia, spread, precio_usd)
            print(f"  {simbolo_cedear:<7} {spread:>+8.2f}%  >>> SEÑAL <<<")
        else:
            print(f"  {simbolo_cedear:<7} {spread:>+8.2f}%  .")

    print(f"\n  Señales (simuladas): {seniales}")
    print("="*80)
    return seniales


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ccl_ref = obtener_ccl()
    if ccl_ref is None:
        print("No se puede continuar sin CCL.")
    else:
        print(f"CCL: ${ccl_ref:,.2f}")
        modo = input("Modo (1=Real / 2=Simulacion): ").strip()
        if modo == "2":
            desv = float(input("Desviacion max %: ").strip() or "5")
            calcular_spreads_simulado(ccl_ref, desv)
        else:
            calcular_spreads_real(ccl_ref)
