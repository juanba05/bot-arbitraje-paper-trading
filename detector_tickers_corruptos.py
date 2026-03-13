"""
detector_tickers_corruptos.py
Registra cuántas veces seguidas un CEDEAR fue descartado como
PRECIO CORRUPTO o dio 404. Cuando supera el umbral, genera alerta en dashboard.
"""

import os
import json
from datetime import datetime
from config import RUTA_DATOS

RUTA_ALERTAS_TICKER = os.path.join(RUTA_DATOS, "alertas_tickers.json")
UMBRAL_FALLOS = 3


def _cargar():
    if not os.path.exists(RUTA_ALERTAS_TICKER):
        return {}
    with open(RUTA_ALERTAS_TICKER) as f:
        return json.load(f)


def _guardar(datos):
    with open(RUTA_ALERTAS_TICKER, "w") as f:
        json.dump(datos, f, indent=2)


def registrar_fallo(simbolo, motivo, simbolo_iol=None):
    datos = _cargar()
    if simbolo not in datos:
        datos[simbolo] = {
            "simbolo": simbolo, "simbolo_iol": simbolo_iol or simbolo,
            "fallos_consecutivos": 0, "primer_fallo": datetime.now().isoformat(),
            "ultimo_fallo": None, "motivo": motivo, "estado": "ok", "visto": False,
        }
    datos[simbolo]["fallos_consecutivos"] += 1
    datos[simbolo]["ultimo_fallo"] = datetime.now().isoformat()
    datos[simbolo]["motivo"] = motivo
    if datos[simbolo]["fallos_consecutivos"] >= UMBRAL_FALLOS and datos[simbolo]["estado"] == "ok":
        datos[simbolo]["estado"] = "alerta"
        datos[simbolo]["visto"] = False
        print(f"\n[TICKER] 🚨 ALERTA: {simbolo} lleva {datos[simbolo]['fallos_consecutivos']} "
              f"ciclos siendo descartado. Ticker IOL: '{simbolo_iol}'")
    _guardar(datos)


def registrar_exito(simbolo):
    datos = _cargar()
    if simbolo in datos and datos[simbolo]["fallos_consecutivos"] > 0:
        datos[simbolo]["fallos_consecutivos"] = 0
        if datos[simbolo]["estado"] == "alerta":
            datos[simbolo]["estado"] = "resuelto"
        _guardar(datos)


def get_alertas_ticker():
    datos = _cargar()
    return [v for v in datos.values() if v.get("estado") == "alerta"]


def marcar_resuelto(simbolo, nuevo_ticker_iol=None):
    datos = _cargar()
    if simbolo in datos:
        datos[simbolo]["estado"] = "resuelto"
        datos[simbolo]["fallos_consecutivos"] = 0
        if nuevo_ticker_iol:
            datos[simbolo]["simbolo_iol"] = nuevo_ticker_iol
        _guardar(datos)
