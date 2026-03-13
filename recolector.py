"""
recolector.py - Recolector de datos de precios NYSE y CEDEARs desde IOL API.
Reemplaza Polygon.io por IOL como fuente de precios NYSE.
"""

import os
import sqlite3
from datetime import datetime
from config import RUTA_DATOS, NOMBRE_DB, CEDEARS
from base_datos import guardar_precio_nyse, guardar_ccl
from obtener_ccl import obtener_ccl
from iol_connector import obtener_cotizacion, _asegurar_token

RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)

# IOL usa estos mercados para NYSE/NASDAQ
MERCADO_USA = "NYSE"  # o "NASDAQ" segun el simbolo


def obtener_precio_nyse_via_iol(simbolo):
    """
    Obtiene el precio en USD de una accion en NYSE/NASDAQ via IOL.
    IOL expone cotizaciones del mercado americano con el mismo endpoint.
    Prueba NYSE primero, luego NASDAQ.
    """
    for mercado in ["NYSE", "NASDAQ"]:
        try:
            datos = obtener_cotizacion(mercado, simbolo)
            if datos and isinstance(datos, dict):
                precio = datos.get("ultimoPrecio") or datos.get("precioPromedio")
                if precio and float(precio) > 0:
                    return float(precio), mercado
        except Exception:
            continue
    return None, None


def recolectar_precios_nyse():
    """
    Trae precios NYSE/NASDAQ de todos los CEDEARs monitoreados via IOL.
    Guarda en la tabla precios_nyse.
    """
    print("\n" + "="*55)
    print("  RECOLECTOR DE PRECIOS NYSE — via IOL API")
    print("="*55)

    # Asegurar token IOL
    if not _asegurar_token():
        print("❌ No se pudo conectar a IOL. Verificá credenciales en config.py")
        return False

    timestamp = datetime.now().isoformat()
    exitosos = 0
    fallidos  = []

    for simbolo in CEDEARS:
        precio, mercado = obtener_precio_nyse_via_iol(simbolo)
        if precio:
            guardar_precio_nyse(timestamp, simbolo, precio)
            print(f"  ✅ {simbolo:6s} [{mercado}]: ${precio:.2f} USD")
            exitosos += 1
        else:
            fallidos.append(simbolo)
            print(f"  ⚠️  {simbolo:6s}: sin precio disponible")

    print(f"\n  Exitosos: {exitosos}/{len(CEDEARS)}")
    if fallidos:
        print(f"  Sin datos: {', '.join(fallidos)}")

    return exitosos > 0


def recolectar_ccl():
    """Obtiene y guarda el CCL actual desde dolarapi.com."""
    print("\n--- Obteniendo CCL ---")
    ccl = obtener_ccl()
    if ccl:
        timestamp = datetime.now().isoformat()
        guardar_ccl(timestamp, ccl)
        print(f"  ✅ CCL guardado: ${ccl:,.2f}")
        return ccl
    else:
        print("  ⚠️  No se pudo obtener el CCL")
        return None


def recolectar_todo():
    """Ejecuta recolección completa: CCL + precios NYSE."""
    ccl = recolectar_ccl()
    ok  = recolectar_precios_nyse()
    return ccl, ok


if __name__ == "__main__":
    print("="*55)
    print("  RECOLECTOR DE DATOS — Bot Arbitraje CEDEARs")
    print("  Fuente: IOL API (NYSE/NASDAQ)")
    print("="*55)

    ccl, ok = recolectar_todo()

    if ok:
        print("\n✅ Recolección completada. Podés correr motor_calculo.py")
    else:
        print("\n❌ No se pudieron obtener precios NYSE.")
        print("   Verificá que IOL esté conectado (python iol_connector.py)")
