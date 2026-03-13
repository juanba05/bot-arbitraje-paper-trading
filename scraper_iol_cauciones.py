"""
scraper_iol_cauciones.py
Obtiene las tasas REALES de cauciones desde la web de IOL.
Usa el endpoint /Mercado/GetCaucionPuntas que es lo que usa la página de cauciones.
Requiere sesión web (cookies) — diferente al Bearer token de la API.
"""

import sys, os, requests, json
from datetime import datetime
from config import IOL_USUARIO, IOL_PASSWORD

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_URL  = "https://iol.invertironline.com"

def leer_credenciales():
    # Seguridad: nunca leer .env manualmente en este script.
    return IOL_USUARIO, IOL_PASSWORD


def crear_sesion_web():
    """
    Hace login en la web de IOL (no la API) y devuelve una sesión con cookies.
    La web usa ASP.NET Forms Authentication — necesitamos las cookies de sesión.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9",
        "Origin": "https://iol.invertironline.com",
        "Referer": "https://iol.invertironline.com/",
    })

    usuario, password = leer_credenciales()
    if not usuario or not password:
        print("  ERROR: No hay credenciales IOL en entorno/config")
        return None

    # 1) Obtener página de login para el token CSRF
    print(f"  Conectando a IOL web...")
    resp = session.get(f"{BASE_URL}/User/Login", timeout=10)
    if resp.status_code != 200:
        print(f"  ERROR: No se pudo acceder a login ({resp.status_code})")
        return None

    # Extraer __RequestVerificationToken del HTML
    token_csrf = None
    import re
    match = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', resp.text)
    if match:
        token_csrf = match.group(1)

    # 2) Hacer POST de login
    payload = {
        "UserName": usuario,
        "Password": password,
        "RememberMe": "false",
    }
    if token_csrf:
        payload["__RequestVerificationToken"] = token_csrf

    resp_login = session.post(
        f"{BASE_URL}/User/Login",
        data=payload,
        allow_redirects=True,
        timeout=10
    )

    # Verificar que el login fue exitoso revisando la URL de destino o cookies
    if "Login" in resp_login.url and "error" in resp_login.text.lower():
        print(f"  ERROR: Login fallido. Verificar usuario/contraseña.")
        return None

    # Verificar que tenemos cookie de sesión
    cookies = session.cookies.get_dict()
    tiene_sesion = any(k in cookies for k in [".ASPXAUTH", "ASP.NET_SessionId", "IOL", "auth"])
    print(f"  Login web OK. Cookies activas: {len(cookies)}")

    return session


def obtener_puntas_caucion(session, plazo_dias, moneda="PESOS"):
    """
    Obtiene las puntas (tasas colocadora y tomadora) para un plazo dado.
    Devuelve dict con tasaColocadora, tasaTomadora, o None si falla.
    """
    url = f"{BASE_URL}/Mercado/GetCaucionPuntas"
    payload = {
        "moneda": moneda,
        "plazo": str(plazo_dias),
        "idTipoTransaccion": "14"  # 14 = Cauciones (según el JS de IOL)
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/Operar/Caucionar/ObtenerTasas",
    }

    try:
        resp = session.post(url, data=payload, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"

        datos = resp.json()
        if not datos.get("success"):
            return None, "success=false"

        # El JS de IOL procesa listaPuntas — extraemos la primera tasa
        puntas = datos.get("listaPuntas", [])
        if not puntas:
            return None, "sin puntas"

        # Primera punta: precioCompra = tasa colocadora, precioVenta = tasa tomadora
        primera = puntas[0]
        tasa_colocadora = primera.get("tasaCompra") or primera.get("precioCompra")
        tasa_tomadora   = primera.get("tasaVenta") or primera.get("precioVenta")

        # Convertir a float
        def a_float(v):
            if v is None: return None
            return float(str(v).replace(",", ".").replace("%", "").strip() or 0)

        return {
            "tasa_colocadora": a_float(tasa_colocadora),
            "tasa_tomadora":   a_float(tasa_tomadora),
            "puntas_raw":      puntas[:3],
            "plazo":           plazo_dias,
        }, None

    except Exception as e:
        return None, str(e)


def obtener_tasas_reales(plazos=[1, 4, 7], moneda="PESOS"):
    """
    Función principal: devuelve dict con tasas reales por plazo.
    Ejemplo: {1: {"tasa_colocadora": 35.5, "tasa_tomadora": 36.0}, ...}
    """
    print(f"\n[IOL Scraper] Obteniendo tasas reales ({datetime.now().strftime('%H:%M:%S')})")

    session = crear_sesion_web()
    if not session:
        return None

    resultados = {}
    for plazo in plazos:
        datos, error = obtener_puntas_caucion(session, plazo, moneda)
        if datos:
            resultados[plazo] = datos
            tc = datos.get("tasa_colocadora")
            tt = datos.get("tasa_tomadora")
            print(f"  Plazo {plazo:2d} días → Colocadora: {tc:.2f}% TNA | Tomadora: {tt:.2f}% TNA" if tc else f"  Plazo {plazo} días → sin datos")
        else:
            print(f"  Plazo {plazo} días → ERROR: {error}")

    return resultados if resultados else None


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  SCRAPER TASAS REALES DE CAUCIONES — IOL")
    print("=" * 60)

    plazos_a_probar = [1, 4, 7, 14, 28]
    tasas = obtener_tasas_reales(plazos=plazos_a_probar)

    if tasas:
        print(f"\n  ✅ Tasas obtenidas para {len(tasas)} plazos")
        print(f"\n  DATO CLAVE: tasa a 1 día = {tasas.get(1, {}).get('tasa_colocadora', 'N/A')}% TNA")
    else:
        print(f"\n  ❌ No se pudieron obtener tasas")
        print(f"  Nota: el mercado debe estar abierto (10:30-17:00hs)")
        print(f"  Hora actual: {datetime.now().strftime('%H:%M')}")

    print("=" * 60)
