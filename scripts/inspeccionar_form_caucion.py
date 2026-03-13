"""
scripts/inspeccionar_form_caucion.py
-------------------------------------
Abre la pagina /Operar/Caucionar de IOL y muestra todos los campos
del formulario. Ejecutar ANTES de implementar el ejecutor real.

Uso:
    python scripts/inspeccionar_form_caucion.py

Salida esperada: lista de campos con nombre, tipo y valor.
Los campos que aparezcan son exactamente los que hay que enviar en el POST.
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper_iol_cauciones import crear_sesion_web

BASE_URL = "https://iol.invertironline.com"

PAGINAS = [
    "/Operar/Caucionar",
    "/Operar/Caucionar/ObtenerTasas",
]


def extraer_campos_form(html, url):
    print(f"\n{'='*60}")
    print(f"  PAGINA: {url}")
    print(f"{'='*60}")

    # Todos los formularios
    forms = re.findall(r'<form[^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
    if not forms:
        print("  [!] No se encontraron formularios en esta pagina.")
        # Mostrar primeros 500 chars del body para diagnosticar
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        if body_match:
            snippet = body_match.group(1).strip()[:500]
            print(f"\n  Primeros 500 chars del body:\n  {snippet}")
        return

    print(f"  Formularios encontrados: {len(forms)}")

    for i, form_html in enumerate(forms, 1):
        # Atributos del form (action, method)
        form_tag_match = re.search(
            r'<form([^>]*)>', html[html.find(form_html[:50]):], re.IGNORECASE
        )
        print(f"\n  --- Form #{i} ---")

        # Todos los inputs
        inputs = re.findall(
            r'<input([^>]*)>', form_html, re.IGNORECASE
        )
        selects = re.findall(
            r'<select([^>]*)name="([^"]*)"', form_html, re.IGNORECASE
        )
        textareas = re.findall(
            r'<textarea([^>]*)name="([^"]*)"', form_html, re.IGNORECASE
        )

        print(f"  Campos input: {len(inputs)}")
        for inp in inputs:
            name  = re.search(r'name="([^"]*)"', inp, re.IGNORECASE)
            itype = re.search(r'type="([^"]*)"', inp, re.IGNORECASE)
            value = re.search(r'value="([^"]*)"', inp, re.IGNORECASE)
            name_s  = name.group(1)  if name  else "(sin name)"
            type_s  = itype.group(1) if itype else "text"
            value_s = value.group(1) if value else ""
            # No mostrar el valor real del token, solo indicar que existe
            if "verificationtoken" in name_s.lower() or "csrf" in name_s.lower():
                value_s = "<TOKEN_CSRF — se parsea automaticamente>"
            print(f"    name='{name_s}' | type='{type_s}' | value='{value_s}'")

        for sel in selects:
            print(f"    name='{sel[1]}' | type=SELECT")

        for ta in textareas:
            tname = re.search(r'name="([^"]*)"', ta[0], re.IGNORECASE)
            if tname:
                print(f"    name='{tname.group(1)}' | type=TEXTAREA")

    # Buscar tambien scripts con configuracion JS (a veces los parametros estan ahi)
    scripts = re.findall(
        r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE
    )
    caucion_vars = []
    for sc in scripts:
        if any(k in sc.lower() for k in ["caucion", "monto", "plazo", "tasa", "colocar"]):
            # Mostrar las primeras 3 lineas relevantes
            for line in sc.split('\n'):
                stripped = line.strip()
                if stripped and any(
                    k in stripped.lower()
                    for k in ["caucion", "monto", "plazo", "tasa", "colocar", "var ", "let ", "const "]
                ):
                    caucion_vars.append(stripped[:120])
                    if len(caucion_vars) >= 10:
                        break

    if caucion_vars:
        print(f"\n  Variables JS relevantes encontradas:")
        for v in caucion_vars:
            print(f"    {v}")


def inspeccionar():
    print("Iniciando sesion web en IOL...")
    session = crear_sesion_web()
    if not session:
        print("\n[ERROR] No se pudo crear sesion web. Verificar credenciales en .env")
        sys.exit(1)

    print("\nSesion creada OK. Inspeccionando paginas de caucion...\n")

    for url_path in PAGINAS:
        url = f"{BASE_URL}{url_path}"
        try:
            resp = session.get(url, timeout=15, allow_redirects=True)
            print(f"GET {url_path} -> HTTP {resp.status_code} | {len(resp.text)} chars")

            if resp.status_code == 200:
                extraer_campos_form(resp.text, url_path)
            elif resp.status_code in (301, 302):
                print(f"  Redireccion a: {resp.headers.get('Location', '?')}")
            else:
                print(f"  [!] Respuesta inesperada: {resp.status_code}")
                print(f"  Body (200 chars): {resp.text[:200]}")

        except Exception as e:
            print(f"  [ERROR] {e}")

    print(f"\n{'='*60}")
    print("  INSPECCION COMPLETA")
    print(f"{'='*60}")
    print("\nCopia la salida anterior y compartila para implementar el ejecutor real.")


if __name__ == "__main__":
    inspeccionar()
