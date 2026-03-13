# ============================================================
# ACTUALIZAR_RATIOS.PY — Ratios oficiales de Comafi
# Estructura del Excel: col 2 = ticker, col 7 = ratio (formato "X:1")
# Filas de datos desde la fila 8 (índice 8)
# ============================================================

import json
import os
import datetime
import pandas as pd
from config import RUTA_DATOS, CEDEARS

RUTA_RATIOS    = os.path.join(RUTA_DATOS, "ratios_comafi.json")
RUTA_EXCEL_IOL = os.path.join(os.path.dirname(RUTA_DATOS), "ratios_comafi.xlsx")
# Ponemos el Excel en la raíz de bot_arbitraje para que sea fácil de reemplazar

RATIOS_RESPALDO = {
    "AAPL":  20,  "GOOGL": 58,  "MSFT":  30,  "AMZN":  144,
    "TSLA":  15,  "NVDA":  24,  "META":  24,  "NFLX":  48,
    "JPM":   15,  "BAC":   4,   "GS":    13,  "XOM":   10,
    "CVX":   16,  "MELI":  120, "VALE":  2,   "PBR":   1,
    "IBIT":  10,  "COIN":  27,  "PLTR":  3,   "AMD":   10,
    "INTC":  5,   "QCOM":  11,  "IBM":   15,  "V":     18,
    "MA":    33,  "PYPL":  8,   "DIS":   12,  "NKE":   12,
    "KO":    5,   "PEP":   18,  "MCD":   24,  "WMT":   18,
    "COST":  48,  "SBUX":  12,  "PFE":   4,   "JNJ":   15,
    "MRK":   5,   "ABBV":  10,  "LLY":   56,  "BA":    24,
    "CAT":   20,  "HON":   8,   "GE":    8,   "T":     3,
    "VZ":    4,   "CSCO":  5,   "ORCL":  3,   "CRM":   18,
    "ADBE":  44,  "NOW":   172, "SHOP":  107, "BKNG":  700,
    "RACE":  83,  "ASML":  146, "TSM":   9,   "GLOB":  18,
    "BIOX":  1,   "VIST":  3,   "TS":    1,   "AGRO":  1,
    "GDX":   10,  "SLV":   6,   "FXI":   5,   "XLK":   46,
    "XLV":   29,  "XLI":   28,  "IVV":   692, "EFA":   18,
}


def ratios_necesitan_actualizacion():
    if not os.path.exists(RUTA_RATIOS):
        return True
    ultima_mod = os.path.getmtime(RUTA_RATIOS)
    hace_un_dia = datetime.datetime.now().timestamp() - 86400
    return ultima_mod < hace_un_dia


def guardar_ratios(ratios, fuente="excel"):
    datos = {
        "fecha_actualizacion": datetime.datetime.now().isoformat(),
        "fuente": fuente,
        "total": len(ratios),
        "ratios": ratios
    }
    with open(RUTA_RATIOS, "w") as f:
        json.dump(datos, f, indent=2)


def cargar_ratios_locales():
    if os.path.exists(RUTA_RATIOS):
        with open(RUTA_RATIOS, "r") as f:
            datos = json.load(f)
            return datos["ratios"], datos.get("fecha_actualizacion", "")
    return None, None


def parsear_ratio(texto):
    """
    Convierte "4:1", "20 : 1", "1 :3" etc. al número del numerador.
    Para ratios inversos como "1:3" devuelve 1 (un CEDEAR = fracción de acción).
    """
    try:
        texto = str(texto).replace(" ", "")
        if ":" not in texto:
            return None
        partes = texto.split(":")
        num = float(partes[0])
        den = float(partes[1])
        if den == 1 and 1 <= num <= 1000:
            return int(num)
        elif num == 1 and den > 1:
            return 1  # Ratio inverso
    except Exception:
        pass
    return None


def parsear_excel_comafi(ruta):
    """
    Parsea el Excel de Comafi con la estructura conocida:
    - Columna 2 (índice): ticker
    - Columna 7: ratio en formato "X:1"
    - Datos desde fila 8 en adelante
    """
    try:
        df = pd.read_excel(ruta, engine="openpyxl", header=None)
        print(f"  📄 Excel leído: {df.shape[0]} filas, {df.shape[1]} columnas")

        ratios = {}
        errores = 0

        for i, fila in df.iterrows():
            if i < 8:  # Saltar encabezados
                continue

            ticker = str(fila[2]).strip().upper()
            ratio_texto = str(fila[7]).strip()

            # Validar ticker: entre 1 y 8 caracteres, sin espacios
            if not ticker or ticker == "NAN" or len(ticker) > 10:
                continue
            if " " in ticker and "/" not in ticker:
                continue

            ratio = parsear_ratio(ratio_texto)
            if ratio:
                ratios[ticker] = ratio
            else:
                errores += 1

        print(f"  ✅ {len(ratios)} ratios extraídos ({errores} filas sin ratio válido)")
        return ratios if len(ratios) > 10 else None

    except Exception as e:
        print(f"  ❌ Error parseando Excel: {e}")
        return None


def obtener_ratios(forzar=False):
    """
    Devuelve ratios vigentes.
    Prioridad: 1) JSON local reciente  2) Excel manual  3) respaldo hardcodeado
    """
    # 1. Usar caché si es reciente
    if not forzar and not ratios_necesitan_actualizacion():
        ratios, fecha = cargar_ratios_locales()
        if ratios:
            print(f"✅ Ratios en caché (actualizados: {fecha[:10]}).")
            return ratios

    # 2. Intentar leer el Excel manual
    print("🔄 Leyendo ratios desde Excel de Comafi...")

    # Buscar el Excel en varias ubicaciones posibles
    rutas_posibles = [
        RUTA_EXCEL_IOL,
        os.path.join(os.path.dirname(RUTA_DATOS), "14779.xlsx"),
        os.path.join(os.path.dirname(RUTA_DATOS), "ratios_comafi.xlsx"),
    ]

    for ruta in rutas_posibles:
        if os.path.exists(ruta):
            print(f"  📂 Encontrado: {ruta}")
            ratios = parsear_excel_comafi(ruta)
            if ratios:
                guardar_ratios(ratios, fuente=f"excel:{os.path.basename(ruta)}")
                return ratios

    # 3. Fallback al respaldo hardcodeado
    print("⚠️  Excel no encontrado. Usando ratios de respaldo (Feb 2026).")
    print(f"   → Para actualizar: copiá el Excel de Comafi como 'ratios_comafi.xlsx'")
    print(f"     en: {os.path.dirname(RUTA_DATOS)}")
    guardar_ratios(RATIOS_RESPALDO, fuente="respaldo")
    return RATIOS_RESPALDO


def verificar_cambios(ratios_nuevos):
    """Avisa si algún ratio del config cambió."""
    cambios = []
    for simbolo, datos in CEDEARS.items():
        ratio_config = datos["ratio"]
        ratio_nuevo = ratios_nuevos.get(simbolo)
        if ratio_nuevo and ratio_nuevo != ratio_config:
            cambios.append((simbolo, ratio_config, ratio_nuevo))

    if cambios:
        print("\n🚨 CAMBIOS EN RATIOS — actualizá config.py:")
        for s, ant, nue in cambios:
            print(f"   {s}: {ant}:1  →  {nue}:1")
    else:
        print("✅ Todos los ratios del config coinciden con el Excel.")

    return cambios


# --- Ejecutar directamente ---
if __name__ == "__main__":
    ratios = obtener_ratios(forzar=True)
    print(f"\nTotal ratios disponibles: {len(ratios)}")
    print("\nVerificando contra config.py...")
    verificar_cambios(ratios)

    # Mostrar ratios de los CEDEARs monitoreados
    print("\nRatios de tus CEDEARs monitoreados:")
    for simbolo in CEDEARS:
        r = ratios.get(simbolo, "NO ENCONTRADO")
        print(f"   {simbolo}: {r}:1")
