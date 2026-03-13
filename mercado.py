"""
mercado.py - Estado del mercado BYMA.
ACTUALIZADO: cauciones pueden ser de 1, 2 o 3 dias habiles.
Maximo 3 dias. Siempre calcula de forma que el vencimiento
no caiga en dia no laboral.
"""

from datetime import datetime, time, timedelta
import pytz

ZONA_ARG = pytz.timezone("America/Argentina/Buenos_Aires")

APERTURA_ACCIONES = time(11, 0)
CIERRE_ACCIONES   = time(17, 0)
CIERRE_CAUCIONES  = time(17, 0)
CAUCION_INTENSIVA = time(15, 0)

PLAZO_MAX_CAUCION = 3  # dÃ­as hÃ¡biles mÃ¡ximos para colocar cauciones


def ahora_arg():
    return datetime.now(ZONA_ARG)


def mercado_abierto():
    ahora = ahora_arg()
    if ahora.weekday() >= 5:
        return False
    h = ahora.time().replace(tzinfo=None)
    return APERTURA_ACCIONES <= h < CIERRE_ACCIONES


def cauciones_abiertas():
    ahora = ahora_arg()
    if ahora.weekday() >= 5:
        return False
    h = ahora.time().replace(tzinfo=None)
    return APERTURA_ACCIONES <= h < CIERRE_CAUCIONES


def es_cierre_caucion():
    ahora = ahora_arg()
    if ahora.weekday() >= 5:
        return False
    h = ahora.time().replace(tzinfo=None)
    return CIERRE_ACCIONES <= h < CIERRE_CAUCIONES


def es_viernes():
    return ahora_arg().weekday() == 4


def es_jueves():
    return ahora_arg().weekday() == 3


def es_miercoles():
    return ahora_arg().weekday() == 2


def _dias_habiles_hasta_vencimiento(plazo):
    """
    Calcula cuÃ¡ntos dÃ­as calendario corresponden a 'plazo' dÃ­as hÃ¡biles
    desde hoy, para que el vencimiento no caiga en finde.
    Devuelve el plazo en dias hÃ¡biles correcto (<= PLAZO_MAX_CAUCION).
    """
    hoy = ahora_arg()
    fecha = hoy
    habiles = 0
    while habiles < plazo:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5:  # lunes=0, viernes=4
            habiles += 1
    return habiles, fecha


def plazos_caucion_disponibles():
    """
    Devuelve lista de plazos disponibles (en dÃ­as hÃ¡biles) con sus fechas de vencimiento.
    Maximo PLAZO_MAX_CAUCION dÃ­as. Los fines de semana no se ofrecen cauciones.

    Regla: vencimiento no puede ser sÃ¡bado ni domingo.
    El mercado automÃ¡ticamente ajusta, pero nosotros lo calculamos para mostrar bien.

    Ejemplo un jueves:
      - 1 dÃ­a hÃ¡bil â†’ vence viernes (OK)
      - 2 dÃ­as hÃ¡biles â†’ vence lunes (salta el finde)
      - 3 dÃ­as hÃ¡biles â†’ vence martes

    Ejemplo un viernes:
      - 1 dÃ­a hÃ¡bil â†’ vence lunes
      - 2 dÃ­as hÃ¡biles â†’ vence martes
      - 3 dÃ­as hÃ¡biles â†’ vence miÃ©rcoles
    """
    plazos = []
    for plazo in range(1, PLAZO_MAX_CAUCION + 1):
        _, fecha_venc = _dias_habiles_hasta_vencimiento(plazo)
        dias_calendario = (fecha_venc.date() - ahora_arg().date()).days
        plazos.append({
            "plazo_habiles":    plazo,
            "dias_calendario":  dias_calendario,
            "fecha_vencimiento": fecha_venc.strftime("%d/%m/%Y"),
            "dia_semana":       ["Lunes","Martes","Miercoles","Jueves",
                                 "Viernes","Sabado","Domingo"][fecha_venc.weekday()],
        })
    return plazos


def plazo_caucion_dias():
    """
    Plazo por defecto para el modo automatico del bot:
    - Viernes â†’ 3 dias habiles (vence miercoles)
    - Jueves â†’ 3 dias habiles (vence martes)
    - Otros dias â†’ 1 dia habil
    Siempre usa el maximo disponible al cierre para maximizar rendimiento.
    """
    ahora = ahora_arg()
    if ahora.weekday() == 4:  # viernes
        return 3
    elif ahora.weekday() == 3:  # jueves
        return 2
    else:
        return 1


def modo_operacion():
    ahora = ahora_arg()
    if ahora.weekday() >= 5:
        return "cerrado"
    h = ahora.time().replace(tzinfo=None)
    if h < APERTURA_ACCIONES:
        return "cerrado"
    elif h < CAUCION_INTENSIVA:
        return "arbitraje"
    elif h < CIERRE_ACCIONES:
        return "mixto"
    elif h < CIERRE_CAUCIONES:
        return "caucion"
    else:
        return "cerrado"


def estado_mercado():
    ahora   = ahora_arg()
    modo    = modo_operacion()
    acc     = mercado_abierto()
    cau     = cauciones_abiertas()
    viernes = es_viernes()
    plazo   = plazo_caucion_dias()
    plazos  = plazos_caucion_disponibles()

    descripciones = {
        "arbitraje": "ABIERTO â€” Modo arbitraje CEDEARs (11-15hs)",
        "mixto":     "ABIERTO â€” Modo mixto: CEDEARs + cauciones (15-17hs)",
        "caucion":   "PARCIAL â€” Solo cauciones hasta las 17:00hs",
        "cerrado":   "CERRADO â€” Solo monitoreo, sin ejecucion",
    }

    return {
        "abierto":              acc,
        "cauciones_abiertas":   cau,
        "es_cierre_caucion":    es_cierre_caucion(),
        "es_viernes":           viernes,
        "plazo_caucion_dias":   plazo,
        "plazos_disponibles":   plazos,
        "modo":                 modo,
        "estado":               descripciones[modo],
        "hora_arg":             ahora.strftime("%d/%m/%Y %H:%M:%S"),
        "dia_semana":           ["Lunes","Martes","Miercoles","Jueves",
                                 "Viernes","Sabado","Domingo"][ahora.weekday()],
    }


if __name__ == "__main__":
    e = estado_mercado()
    print(f"\n{'='*55}")
    print(f"  ESTADO DEL MERCADO â€” {e['hora_arg']}")
    print(f"{'='*55}")
    print(f"  Estado:     {e['estado']}")
    print(f"  Modo:       {e['modo'].upper()}")
    print(f"  Dia:        {e['dia_semana']}")
    print(f"\n  PLAZOS DE CAUCION DISPONIBLES:")
    for p in e["plazos_disponibles"]:
        print(f"    {p['plazo_habiles']}d habil(es) â†’ vence {p['fecha_vencimiento']} "
              f"({p['dia_semana']}) â€” {p['dias_calendario']} dias calendario")
    print(f"\n  Plazo recomendado hoy: {e['plazo_caucion_dias']}d hÃ¡bil(es)")
    print(f"{'='*55}")

