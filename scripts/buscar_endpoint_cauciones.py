"""
buscar_endpoint_cauciones.py
Prueba sistematicamente todos los endpoints posibles de IOL
para encontrar donde estan las tasas reales de cauciones a 1, 2 y 3 dias.
No inventa nada. Solo muestra lo que IOL devuelve.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from iol_connector import _get, _obtener_token_inicial

print("Haciendo login en IOL...")
if not _obtener_token_inicial():
    print("ERROR: No se pudo conectar a IOL.")
    exit()

print("Login OK. Probando endpoints...\n")

endpoints = [
    # Cauciones - variantes documentadas y no documentadas
    "/operar/CPD/PuedeOperar",
    "/operar/caucion/colocadora",
    "/operar/caucion/tomadora",
    "/operar/cauciones",
    "/operar/cauciones/colocadoras",
    "/operar/cauciones/tomadoras",
    "/Mercado/Cauciones",
    "/mercado/cauciones",
    "/cauciones",
    "/cauciones/colocadoras",
    "/Titulos/cauciones",
    "/titulos/cauciones",
    "/operaciones/cauciones",
    "/portafolio/cauciones",
    "/estadocuenta/cauciones",
    # Con plazo explicito
    "/operar/caucion/1",
    "/operar/caucion/2",
    "/operar/caucion/3",
    "/cauciones/1",
    "/cauciones/2",
    "/cauciones/3",
    # Otros endpoints utiles
    "/estadocuenta",
    "/portafolio/argentina",
]

encontrados = []

for ep in endpoints:
    try:
        resultado = _get(ep)
        if resultado is not None:
            tipo = type(resultado).__name__
            if isinstance(resultado, dict):
                preview = str(resultado)[:200]
            elif isinstance(resultado, list):
                preview = f"[lista de {len(resultado)} items] {str(resultado[:1])[:150]}"
            else:
                preview = str(resultado)[:200]
            print(f"  ✅ {ep}")
            print(f"     Tipo: {tipo}")
            print(f"     Datos: {preview}")
            print()
            encontrados.append((ep, resultado))
        else:
            print(f"  ❌ {ep} → None (404 o sin datos)")
    except Exception as e:
        print(f"  ⚠️  {ep} → excepcion: {e}")

print("=" * 60)
print(f"ENDPOINTS QUE RESPONDEN: {len(encontrados)}")
for ep, _ in encontrados:
    print(f"  → {ep}")
