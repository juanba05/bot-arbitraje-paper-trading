"""
detector_ratios.py - Detecta cambios de ratio y precios corruptos.
Logica:
  1. Calcula ratio implicito = round(precio_USD * CCL / precio_ARS)
  2. Si difiere del ratio guardado → posible cambio de ratio
  3. Si el ratio calculado es absurdo (muy lejos del esperado) → precio corrupto
  4. Guarda alertas en dashboard para confirmacion del usuario
"""

import os
import json
from datetime import datetime, timedelta
from config import RUTA_DATOS

RUTA_ALERTAS_RATIO = os.path.join(RUTA_DATOS, "alertas_ratios.json")

# Tolerancia: si el ratio calculado difiere mas de este % del guardado
# se considera cambio de ratio (no precio corrupto)
TOLERANCIA_RATIO_PCT = 0.20   # 20% — cubre splits normales

# Si el ratio calculado difiere MAS de este factor, es precio corrupto
FACTOR_CORRUPTO = 3.0         # ej: ratio esperado 4, calculado 3000 → corrupto


def calcular_ratio_implicito(precio_usd, ccl, precio_ars):
    """
    Despeja el ratio de la formula:
      precio_ars = (precio_usd / ratio) * ccl
      ratio = precio_usd * ccl / precio_ars
    Devuelve el ratio como entero redondeado.
    """
    if precio_ars <= 0:
        return None
    ratio_float = (precio_usd * ccl) / precio_ars
    return ratio_float


def evaluar_precio(simbolo, precio_usd, ccl, precio_ars, ratio_guardado):
    """
    Evalua si el precio ARS es valido y si el ratio cambio.

    Devuelve un dict con:
      - valido: bool (False si el precio es corrupto)
      - ratio_ok: bool (False si el ratio cambio)
      - ratio_calculado: int
      - tipo: 'ok' | 'corrupto' | 'ratio_cambiado'
      - mensaje: descripcion
    """
    ratio_float = calcular_ratio_implicito(precio_usd, ccl, precio_ars)

    if ratio_float is None:
        return {"valido": False, "ratio_ok": False, "ratio_calculado": None,
                "tipo": "corrupto", "mensaje": f"{simbolo}: precio ARS es 0 o negativo"}

    ratio_calculado = round(ratio_float)

    # Diferencia porcentual entre ratio calculado y guardado
    diferencia_pct = abs(ratio_float - ratio_guardado) / ratio_guardado

    # Caso 1: precio corrupto (ratio calculado es absurdamente diferente)
    if diferencia_pct > FACTOR_CORRUPTO:
        return {
            "valido": False,
            "ratio_ok": False,
            "ratio_calculado": ratio_calculado,
            "tipo": "corrupto",
            "mensaje": (f"{simbolo}: precio ARS ${precio_ars:.2f} parece corrupto. "
                        f"Ratio implicito={ratio_calculado} vs guardado={ratio_guardado}. "
                        f"Precio esperado aprox: ${(precio_usd/ratio_guardado)*ccl:,.2f} ARS")
        }

    # Caso 2: ratio cambio (diferencia razonable pero distinta)
    if diferencia_pct > TOLERANCIA_RATIO_PCT and ratio_calculado != ratio_guardado:
        return {
            "valido": True,   # el precio puede ser valido con el nuevo ratio
            "ratio_ok": False,
            "ratio_calculado": ratio_calculado,
            "tipo": "ratio_cambiado",
            "mensaje": (f"{simbolo}: posible cambio de ratio. "
                        f"Guardado={ratio_guardado}, Calculado={ratio_calculado}. "
                        f"Verificar en Banco Comafi.")
        }

    # Caso 3: todo OK
    return {
        "valido": True,
        "ratio_ok": True,
        "ratio_calculado": ratio_calculado,
        "tipo": "ok",
        "mensaje": ""
    }


# ──────────────────────────────────────────────────────────────────
# ALERTAS DE RATIO
# ──────────────────────────────────────────────────────────────────

def cargar_alertas_ratio():
    if not os.path.exists(RUTA_ALERTAS_RATIO):
        return []
    with open(RUTA_ALERTAS_RATIO) as f:
        return json.load(f)


def guardar_alerta_ratio(simbolo, ratio_viejo, ratio_nuevo, precio_ars, precio_usd, ccl):
    alertas = cargar_alertas_ratio()

    # No duplicar si ya hay una alerta pendiente para este simbolo
    for a in alertas:
        if a["simbolo"] == simbolo and a["estado"] == "pendiente":
            return  # ya existe, no agregar otra

    alerta = {
        "simbolo":       simbolo,
        "ratio_viejo":   ratio_viejo,
        "ratio_nuevo":   ratio_nuevo,
        "precio_ars":    precio_ars,
        "precio_usd":    precio_usd,
        "ccl":           ccl,
        "timestamp":     datetime.now().isoformat(),
        "expira":        (datetime.now() + timedelta(hours=48)).isoformat(),
        "estado":        "pendiente",   # pendiente | confirmado | rechazado
        "confirmado_en": None,
    }

    alertas.insert(0, alerta)
    alertas = alertas[:30]

    with open(RUTA_ALERTAS_RATIO, "w") as f:
        json.dump(alertas, f, indent=2)

    print(f"\n[RATIO] ⚠️  Posible cambio de ratio en {simbolo}: "
          f"{ratio_viejo} → {ratio_nuevo}. Alerta guardada en dashboard.")


def confirmar_ratio(simbolo, confirmar=True):
    """
    Confirma o rechaza un cambio de ratio desde el dashboard.
    Si se confirma, actualiza ratios_comafi.json.
    """
    alertas = cargar_alertas_ratio()
    ratio_nuevo = None

    for a in alertas:
        if a["simbolo"] == simbolo and a["estado"] == "pendiente":
            a["estado"]        = "confirmado" if confirmar else "rechazado"
            a["confirmado_en"] = datetime.now().isoformat()
            ratio_nuevo = a["ratio_nuevo"] if confirmar else None
            break

    with open(RUTA_ALERTAS_RATIO, "w") as f:
        json.dump(alertas, f, indent=2)

    if confirmar and ratio_nuevo:
        _actualizar_ratio_en_json(simbolo, ratio_nuevo)
        print(f"[RATIO] ✅ Ratio de {simbolo} actualizado a {ratio_nuevo}")
    else:
        print(f"[RATIO] ↩️  Cambio de ratio de {simbolo} rechazado. Se mantiene ratio anterior.")


def _actualizar_ratio_en_json(simbolo, ratio_nuevo):
    """Actualiza el ratio en ratios_comafi.json."""
    from config import RUTA_DATOS
    ruta = os.path.join(RUTA_DATOS, "ratios_comafi.json")
    if not os.path.exists(ruta):
        return
    with open(ruta) as f:
        datos = json.load(f)
    datos["ratios"][simbolo] = ratio_nuevo
    datos["ultima_actualizacion"] = datetime.now().isoformat()
    with open(ruta, "w") as f:
        json.dump(datos, f, indent=2)


def get_ratio_efectivo(simbolo, ratio_guardado):
    """
    Devuelve el ratio a usar para este simbolo.
    Si hay una alerta pendiente (48hs), usa el ratio nuevo temporalmente.
    Si fue confirmado, usa el nuevo. Si rechazado o sin alerta, usa el guardado.
    """
    alertas = cargar_alertas_ratio()
    ahora = datetime.now()

    for a in alertas:
        if a["simbolo"] != simbolo:
            continue

        if a["estado"] == "confirmado":
            return a["ratio_nuevo"], "confirmado"

        if a["estado"] == "pendiente":
            expira = datetime.fromisoformat(a["expira"])
            if ahora < expira:
                return a["ratio_nuevo"], "provisional_48h"
            else:
                # Expiró sin confirmación, volver al viejo
                a["estado"] = "expirado"
                with open(RUTA_ALERTAS_RATIO, "w") as f:
                    json.dump(alertas, f, indent=2)
                return ratio_guardado, "expirado"

    return ratio_guardado, "original"


def get_alertas_pendientes():
    alertas = cargar_alertas_ratio()
    return [a for a in alertas if a["estado"] == "pendiente"]


if __name__ == "__main__":
    # Test
    print("Test detector_ratios.py")
    print("\nCaso 1: precio corrupto (BAC con $9.89)")
    r = evaluar_precio("BAC", 53.08, 1445.70, 9.89, 4)
    print(f"  tipo: {r['tipo']}")
    print(f"  valido: {r['valido']}")
    print(f"  mensaje: {r['mensaje']}")

    print("\nCaso 2: ratio cambiado (supongamos que AAPL cambio de 20 a 25)")
    r2 = evaluar_precio("AAPL", 264.64, 1445.70, 15273.0, 20)
    print(f"  tipo: {r2['tipo']}")
    print(f"  ratio calculado: {r2['ratio_calculado']}")
    print(f"  mensaje: {r2['mensaje']}")

    print("\nCaso 3: todo normal (AAPL con precio correcto)")
    precio_correcto = (264.64 / 20) * 1445.70
    r3 = evaluar_precio("AAPL", 264.64, 1445.70, precio_correcto, 20)
    print(f"  tipo: {r3['tipo']}")
    print(f"  ratio calculado: {r3['ratio_calculado']}")
