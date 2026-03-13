"""
test_caucion_manual.py
----------------------
Prueba PUNTUAL de ejecucion real de caucion.
Usa el ejecutor Selenium directamente, sin esperar señal del motor.

Correr UNA sola vez para confirmar funcionamiento de punta a punta.
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from ejecutor_selenium_caucion import ejecutar_caucion_selenium

MONTO_TEST = 20001   # ARS — minimo IOL es 20000
PLAZO_TEST = 1       # 1 dia habil: colocado hoy viernes, vence el lunes

# Consultar la tasa actual del mercado para usar como minima
try:
    from motor_cauciones import analizar_cauciones
    res = analizar_cauciones(modo="real")
    TNA_TEST = float(res.get("tna", res.get("tasa", 0)) or 0) if res else 0
    if TNA_TEST <= 0:
        TNA_TEST = None   # sin minima si no hay dato
except Exception:
    TNA_TEST = None

print("=" * 55)
print("  TEST MANUAL — CAUCION REAL IOL")
print("=" * 55)
print(f"  Monto : ARS {MONTO_TEST:,}")
print(f"  Plazo : {PLAZO_TEST} dia habil (vence el lunes)")
print(f"  TNA   : {f'{TNA_TEST:.2f}% (minimo detectado)' if TNA_TEST else 'sin minimo'}")
print()
print("  Chrome se va a abrir. NO toques nada.")
print("  El bot va a completar el formulario e ingresar la contrasena.")
print()

resultado = ejecutar_caucion_selenium(
    monto      = MONTO_TEST,
    plazo      = PLAZO_TEST,
    tna_minima = TNA_TEST,
    headless   = False,   # Chrome visible para verificar
)

print()
print("=" * 55)
print("  RESULTADO:")
print(f"  ok     : {resultado.get('ok')}")
print(f"  estado : {resultado.get('estado')}")
print(f"  detalle: {resultado.get('detalle', '')}")
print(f"  id_op  : {resultado.get('id_op', 'no parseado')}")
print("=" * 55)
