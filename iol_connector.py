"""
iol_connector.py - ConexiÃ³n con la API de InvertirOnline (IOL)
Maneja autenticaciÃ³n automÃ¡tica con renovaciÃ³n de tokens.
"""

import requests
import time
import sys
from datetime import datetime, timedelta
from config import IOL_USUARIO, IOL_PASSWORD

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# â”€â”€â”€ URLs de la API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
URL_BASE   = "https://api.invertironline.com"
URL_TOKEN  = f"{URL_BASE}/token"
URL_API    = f"{URL_BASE}/api/v2"

# â”€â”€â”€ Estado interno del conector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_bearer_token  = None
_refresh_token = None
_token_expira  = None   # datetime en que vence el bearer token


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# AUTENTICACIÃ“N
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _obtener_token_inicial():
    """Hace login con usuario y contraseÃ±a y guarda los tokens."""
    global _bearer_token, _refresh_token, _token_expira

    payload = {
        "username":   IOL_USUARIO,
        "password":   IOL_PASSWORD,
        "grant_type": "password"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        resp = requests.post(URL_TOKEN, data=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        datos = resp.json()

        _bearer_token  = datos["access_token"]
        _refresh_token = datos["refresh_token"]
        _token_expira  = datetime.now() + timedelta(minutes=14)  # margen de 1 min

        print(f"[IOL] âœ… Login exitoso. Token vÃ¡lido hasta {_token_expira.strftime('%H:%M:%S')}")
        return True

    except Exception as e:
        print(f"[IOL] âŒ Error al hacer login: {e}")
        return False


def _renovar_token():
    """Renueva el bearer token usando el refresh token."""
    global _bearer_token, _refresh_token, _token_expira

    payload = {
        "refresh_token": _refresh_token,
        "grant_type":    "refresh_token"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        resp = requests.post(URL_TOKEN, data=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        datos = resp.json()

        _bearer_token  = datos["access_token"]
        _refresh_token = datos["refresh_token"]
        _token_expira  = datetime.now() + timedelta(minutes=14)

        print(f"[IOL] ðŸ”„ Token renovado. VÃ¡lido hasta {_token_expira.strftime('%H:%M:%S')}")
        return True

    except Exception as e:
        print(f"[IOL] âš ï¸  No se pudo renovar token, reintentando login: {e}")
        return _obtener_token_inicial()


def _asegurar_token():
    """Garantiza que el token estÃ© vigente antes de cada llamada."""
    global _bearer_token, _token_expira

    if _bearer_token is None:
        return _obtener_token_inicial()

    if datetime.now() >= _token_expira:
        return _renovar_token()

    return True


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# FUNCIÃ“N GENÃ‰RICA PARA LLAMADAS A LA API
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get(endpoint):
    """Hace un GET autenticado a la API de IOL. Devuelve el JSON o None."""
    if not _asegurar_token():
        print("[IOL] âŒ Sin token vÃ¡lido, no se puede consultar la API.")
        return None

    headers = {"Authorization": f"Bearer {_bearer_token}"}
    url = f"{URL_API}{endpoint}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    except requests.exceptions.HTTPError as e:
        print(f"[IOL] âŒ Error HTTP {resp.status_code} en {endpoint}: {e}")
        return None
    except Exception as e:
        print(f"[IOL] âŒ Error en {endpoint}: {e}")
        return None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# FUNCIONES DE CONSULTA
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _post(endpoint, data=None, json_body=None, headers_extra=None):
    """Hace un POST autenticado a la API de IOL. Devuelve JSON o None."""
    if not _asegurar_token():
        print("[IOL] Sin token valido, no se puede consultar la API.")
        return None

    headers = {"Authorization": f"Bearer {_bearer_token}"}
    if headers_extra:
        headers.update(headers_extra)
    url = f"{URL_API}{endpoint}"

    try:
        resp = requests.post(url, headers=headers, data=data, json=json_body, timeout=12)
        resp.raise_for_status()
        if not resp.text:
            return {}
        try:
            return resp.json()
        except Exception:
            return {"raw_text": resp.text}
    except requests.exceptions.HTTPError as e:
        print(f"[IOL] Error HTTP {resp.status_code} en {endpoint}: {e}")
        return None
    except Exception as e:
        print(f"[IOL] Error en POST {endpoint}: {e}")
        return None
def obtener_portafolio():
    """Devuelve el portafolio actual de la cuenta (paÃ­s: argentina)."""
    return _get("/portafolio/argentina")


def obtener_estado_cuenta():
    """Devuelve el estado de cuenta (saldo disponible, etc.)."""
    return _get("/estadocuenta")


def obtener_cotizacion(mercado, simbolo):
    """
    Devuelve la cotizaciÃ³n de un tÃ­tulo.
    mercado: 'bCBA' para BYMA (CEDEARs en ARS)
    simbolo: ej. 'AAPL', 'GOOGL', etc.
    """
    return _get(f"/{mercado}/Titulos/{simbolo}/Cotizacion")


def obtener_cotizacion_cedear(simbolo):
    """Atajo para cotizar un CEDEAR en BYMA."""
    return obtener_cotizacion("bCBA", simbolo)


def obtener_cauciones():
    """
    Compatibilidad historica.

    La caucion real no se confirmo por API publica v2.
    El endpoint CPD no corresponde a cauciones, sino a cheques de pago diferido.
    """
    return None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PRUEBA RÃPIDA
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    print("=" * 50)
    print("PRUEBA DE CONEXIÃ“N CON IOL")
    print("=" * 50)

    # 1. Login
    ok = _obtener_token_inicial()
    if not ok:
        print("\nâŒ No se pudo conectar. VerificÃ¡ usuario/contraseÃ±a en config.py")
        exit()

    # 2. Estado de cuenta
    print("\n--- Estado de cuenta ---")
    cuenta = obtener_estado_cuenta()
    if cuenta:
        print(f"âœ… ConexiÃ³n exitosa")
        # Mostramos algunos campos si los hay
        if isinstance(cuenta, dict):
            for k, v in list(cuenta.items())[:5]:
                print(f"   {k}: {v}")
    else:
        print("âš ï¸  No se pudo obtener el estado de cuenta")

    # 3. CotizaciÃ³n de AAPL como prueba
    print("\n--- CotizaciÃ³n AAPL (CEDEAR en BYMA) ---")
    cotiz = obtener_cotizacion_cedear("AAPL")
    if cotiz:
        print(f"âœ… Datos recibidos: {cotiz}")
    else:
        print("âš ï¸  No se pudo obtener cotizaciÃ³n de AAPL")

    print("\n" + "=" * 50)
    print("Prueba finalizada.")

