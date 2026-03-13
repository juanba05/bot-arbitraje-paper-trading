"""
explorar_iol_web.py
Busca las tasas de cauciones en la web de IOL usando la sesion autenticada.
Prueba distintas URLs y muestra el HTML/JSON que devuelven.
"""

import sys, os, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from iol_connector import _obtener_token_inicial, _bearer_token

print("Haciendo login en IOL...")
if not _obtener_token_inicial():
    print("ERROR: No se pudo conectar.")
    exit()

# Usamos el mismo bearer token que la API — IOL web usa el mismo sistema de auth
import iol_connector as iol
token = iol._bearer_token

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {token}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.invertironline.com/",
    "Origin": "https://www.invertironline.com",
})

print(f"Token obtenido. Explorando URLs...\n")

urls = [
    # API interna que usa la web de IOL (distinta de la API publica v2)
    ("IOL web cauciones",         "https://api.invertironline.com/api/v2/operar/Caucion/ObtenerTasas"),
    ("IOL web cauciones 2",       "https://api.invertironline.com/api/v2/operar/Caucion/Tasas"),
    ("IOL web cauciones plazo1",  "https://api.invertironline.com/api/v2/operar/Caucion/ObtenerTasas?plazo=1"),
    ("IOL web caucion GET",       "https://api.invertironline.com/api/v2/Caucion/ObtenerTasas"),
    ("IOL web caucion tasas",     "https://api.invertironline.com/api/v2/Caucion/Tasas"),
    ("IOL bff cauciones",         "https://bff.invertironline.com/api/cauciones/tasas"),
    ("IOL bff caucion",           "https://bff.invertironline.com/api/caucion"),
    ("IOL web v1 caucion",        "https://api.invertironline.com/api/v1/operar/Caucion/ObtenerTasas"),
    ("IOL web caucion colocar",   "https://api.invertironline.com/api/v2/operar/Caucion/Colocar"),
    # Pagina web directa
    ("IOL pagina cauciones",      "https://www.invertironline.com/cauciones"),
    ("IOL pagina operar caucion", "https://www.invertironline.com/operar/caucion"),
]

for nombre, url in urls:
    try:
        resp = session.get(url, timeout=8)
        status = resp.status_code
        content_type = resp.headers.get("Content-Type", "")

        if status == 200:
            print(f"  ✅ {nombre}")
            print(f"     URL: {url}")
            print(f"     Content-Type: {content_type}")
            if "json" in content_type:
                try:
                    datos = resp.json()
                    print(f"     JSON: {str(datos)[:400]}")
                except:
                    print(f"     Texto: {resp.text[:400]}")
            else:
                # HTML — buscamos palabras clave
                texto = resp.text
                for keyword in ["caucion", "tasa", "TNA", "plazo", "colocadora"]:
                    idx = texto.lower().find(keyword.lower())
                    if idx >= 0:
                        print(f"     Keyword '{keyword}' encontrada en pos {idx}")
                        print(f"     Contexto: ...{texto[max(0,idx-50):idx+100]}...")
                        break
                else:
                    print(f"     HTML sin keywords relevantes ({len(texto)} chars)")
            print()
        else:
            print(f"  ❌ {nombre} → HTTP {status}")
    except Exception as e:
        print(f"  ⚠️  {nombre} → {e}")

print("\nFin del explorador.")
