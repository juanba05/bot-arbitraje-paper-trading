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

print("=" * 55)
print("  TEST MANUAL — CAUCION REAL IOL")
print("=" * 55)
print(f"  Monto : ARS {MONTO_TEST:,}")
print(f"  Plazo : {PLAZO_TEST} dia habil (vence el lunes)")
print(f"  TNA   : la que ofrezca el mercado (sin minimo)")
print()
print("  Chrome se va a abrir. NO toques nada.")
print("  El script va a completar el formulario solo.")
print()

resultado = ejecutar_caucion_selenium(
    monto      = MONTO_TEST,
    plazo      = PLAZO_TEST,
    tna_minima = None,    # acepta cualquier tasa disponible
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
