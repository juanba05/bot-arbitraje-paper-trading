"""
ejecutor_selenium_caucion.py
----------------------------
Automatiza la colocacion de cauciones en IOL usando Chrome.
Flujo: Login -> /Operar/Caucionar -> /Operar/ConfirmarCaucion -> /Operar/CaucionExitosa

Usa undetected-chromedriver para que IOL no detecte que es un robot.
"""

import os
import time
import logging
from datetime import datetime

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from config import IOL_USUARIO, IOL_PASSWORD, RUTA_DATOS

log = logging.getLogger("selenium_caucion")

BASE_URL = "https://iol.invertironline.com"
TIMEOUT  = 30   # segundos maximos de espera por elemento
RUTA_SCREENSHOTS = os.path.join(RUTA_DATOS, "screenshots")
os.makedirs(RUTA_SCREENSHOTS, exist_ok=True)


# ─────────────────────────────────────────────────────────────────
# DRIVER
# ─────────────────────────────────────────────────────────────────

def crear_driver(headless=False):
    """
    Crea y devuelve un Chrome driver con anti-deteccion.
    headless=False: Chrome visible (recomendado para la primera prueba).
    headless=True:  Chrome en segundo plano (para produccion).
    """
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    if headless:
        options.add_argument("--headless=new")
    driver = uc.Chrome(options=options, version_main=None)
    driver.implicitly_wait(5)
    return driver


def cerrar_driver(driver):
    try:
        driver.quit()
    except Exception:
        pass


def _screenshot(driver, nombre):
    """Guarda una captura de pantalla para diagnostico."""
    try:
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(RUTA_SCREENSHOTS, f"{ts}_{nombre}.png")
        driver.save_screenshot(path)
        log.info(f"  Screenshot guardado: {path}")
        return path
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────

def login(driver, usuario=None, password=None):
    """
    Hace login en la web de IOL.
    Devuelve True si el login fue exitoso, False si fallo.
    """
    usuario  = usuario  or IOL_USUARIO
    password = password or IOL_PASSWORD
    wait     = WebDriverWait(driver, TIMEOUT)

    log.info("  Abriendo pagina de login IOL...")
    driver.get(f"{BASE_URL}/User/Login")

    try:
        wait.until(EC.presence_of_element_located((By.NAME, "Usuario")))
    except TimeoutException:
        log.error("  Timeout: no aparecio el formulario de login.")
        _screenshot(driver, "login_timeout")
        return False

    driver.find_element(By.NAME, "Usuario").clear()
    driver.find_element(By.NAME, "Usuario").send_keys(usuario)
    driver.find_element(By.NAME, "Password").clear()
    driver.find_element(By.NAME, "Password").send_keys(password)

    # Click en el boton de submit
    try:
        btn = driver.find_element(
            By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'
        )
        btn.click()
    except NoSuchElementException:
        log.error("  No se encontro el boton de login.")
        _screenshot(driver, "login_no_button")
        return False

    # Esperar a que la URL deje de ser la pagina de login
    try:
        wait.until(lambda d: "Login" not in d.current_url)
    except TimeoutException:
        log.error("  El login fallo — la URL sigue siendo la de login.")
        _screenshot(driver, "login_fallido")
        return False

    log.info(f"  Login OK. URL actual: {driver.current_url}")
    return True


# ─────────────────────────────────────────────────────────────────
# DESCUBRIMIENTO DE CAMPOS DEL FORMULARIO
# ─────────────────────────────────────────────────────────────────

def _buscar_campo(driver, nombres_posibles):
    """
    Busca un campo de formulario por nombre o id.
    Devuelve el elemento si lo encuentra, None si no.
    """
    for nombre in nombres_posibles:
        for attr in ["name", "id"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, f'input[{attr}="{nombre}"]')
                if el.is_displayed():
                    return el
            except NoSuchElementException:
                pass
    return None


def _buscar_boton(driver, textos_posibles):
    """
    Busca un boton por texto visible o valor.
    """
    for texto in textos_posibles:
        # Por texto visible
        try:
            btns = driver.find_elements(By.XPATH, f'//*[contains(text(), "{texto}")]')
            for b in btns:
                if b.tag_name in ("button", "a", "input") and b.is_displayed():
                    return b
        except Exception:
            pass
        # Por value (input type=submit)
        try:
            el = driver.find_element(
                By.CSS_SELECTOR, f'input[value*="{texto}"], button[value*="{texto}"]'
            )
            if el.is_displayed():
                return el
        except NoSuchElementException:
            pass
    return None


# ─────────────────────────────────────────────────────────────────
# COLOCACION DE CAUCION
# ─────────────────────────────────────────────────────────────────

def colocar_caucion(driver, monto, plazo, tna_minima=None):
    """
    Navega al formulario de caucion, lo completa y confirma.

    Parametros:
        driver     : Chrome driver ya logueado
        monto      : monto en pesos a colocar (ej: 10000.0)
        plazo      : dias habiles (1, 2 o 3)
        tna_minima : tasa minima aceptable (opcional, ej: 25.0 para 25% TNA)

    Devuelve dict con:
        ok      : True si la caucion se coloco
        estado  : descripcion del resultado
        detalle : texto adicional
        id_op   : ID de la operacion en IOL (si se pudo parsear)
    """
    wait = WebDriverWait(driver, TIMEOUT)

    # ── 1. Ir a la pagina de caucionar ──────────────────────────
    log.info("  Navegando a /Operar/Caucionar...")
    driver.get(f"{BASE_URL}/Operar/Caucionar")

    # Esperar que NO sea la pagina de login
    try:
        wait.until(lambda d: "Login" not in d.current_url)
    except TimeoutException:
        log.error("  Redireccion al login — sesion expirada.")
        _screenshot(driver, "caucion_redir_login")
        return {"ok": False, "estado": "SESION_EXPIRADA", "detalle": "Redireccion a login al abrir Caucionar"}

    # Esperar que cargue el contenido del formulario (esperar a que desaparezca spinner o aparezca form)
    time.sleep(2)  # margen para JS del formulario
    _screenshot(driver, "caucion_form_cargado")

    # ── 2. Buscar campo MONTO ────────────────────────────────────
    campo_monto = _buscar_campo(driver, [
        "Monto", "monto", "Importe", "importe", "Capital", "capital",
        "MontoColocar", "montoColocar", "Amount", "amount",
    ])
    if not campo_monto:
        log.error("  No se encontro el campo de monto en el formulario.")
        _screenshot(driver, "caucion_sin_campo_monto")
        # Guardar HTML para diagnostico
        _guardar_html_diagnostico(driver, "caucion_html")
        return {"ok": False, "estado": "CAMPO_MONTO_NO_ENCONTRADO",
                "detalle": "Ver screenshot y caucion_html.txt en datos/screenshots/"}

    log.info(f"  Campo monto encontrado: name='{campo_monto.get_attribute('name')}' id='{campo_monto.get_attribute('id')}'")
    campo_monto.clear()
    campo_monto.send_keys(str(int(monto)))

    # ── 3. Buscar campo PLAZO ────────────────────────────────────
    campo_plazo = _buscar_campo(driver, [
        "Plazo", "plazo", "PlazoColocar", "plazoColocar", "Days", "days",
        "DiasColocar", "dias",
    ])
    if campo_plazo:
        log.info(f"  Campo plazo encontrado: name='{campo_plazo.get_attribute('name')}'")
        campo_plazo.clear()
        campo_plazo.send_keys(str(int(plazo)))
    else:
        # Algunos formularios usan un select o botones de radio para el plazo
        log.info("  Campo plazo no encontrado como input — buscando select o radio...")
        _seleccionar_plazo_alternativo(driver, plazo)

    # ── 4. Tasa minima (opcional) ────────────────────────────────
    if tna_minima is not None:
        campo_tasa = _buscar_campo(driver, [
            "TasaMinima", "tasaMinima", "Tasa", "tasa", "Rate", "rate",
            "TasaColocar", "tasaColocar",
        ])
        if campo_tasa:
            log.info(f"  Campo tasa encontrado: name='{campo_tasa.get_attribute('name')}'")
            campo_tasa.clear()
            campo_tasa.send_keys(str(tna_minima).replace(".", ","))

    _screenshot(driver, "caucion_form_completo")

    # ── 5. Enviar el formulario ──────────────────────────────────
    boton_submit = _buscar_boton(driver, [
        "Caucionar", "Colocar", "Confirmar", "Enviar", "Continuar",
        "caucionar", "colocar", "confirmar",
    ])
    if not boton_submit:
        # Ultimo recurso: buscar cualquier button de tipo submit
        try:
            boton_submit = driver.find_element(
                By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'
            )
        except NoSuchElementException:
            pass

    if not boton_submit:
        log.error("  No se encontro el boton de envio.")
        _screenshot(driver, "caucion_sin_boton")
        return {"ok": False, "estado": "BOTON_SUBMIT_NO_ENCONTRADO",
                "detalle": "Ver screenshot en datos/screenshots/"}

    log.info(f"  Haciendo click en boton de submit...")
    boton_submit.click()

    # ── 6. Manejar pagina de CONFIRMACION ───────────────────────
    try:
        wait.until(lambda d: "Confirmar" in d.current_url or "Exitosa" in d.current_url)
    except TimeoutException:
        log.error("  Timeout esperando pagina de confirmacion.")
        _screenshot(driver, "caucion_post_submit")
        return {"ok": False, "estado": "TIMEOUT_CONFIRMACION",
                "detalle": f"URL actual: {driver.current_url}"}

    if "ConfirmarCaucion" in driver.current_url:
        log.info("  Pagina de confirmacion detectada. Confirmando...")
        _screenshot(driver, "caucion_confirmar")

        boton_confirmar = _buscar_boton(driver, [
            "Confirmar", "confirmar", "Aceptar", "aceptar", "Si", "OK",
        ])
        if not boton_confirmar:
            try:
                boton_confirmar = driver.find_element(
                    By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'
                )
            except NoSuchElementException:
                pass

        if not boton_confirmar:
            log.error("  No se encontro el boton de confirmacion.")
            _screenshot(driver, "caucion_sin_boton_confirmar")
            return {"ok": False, "estado": "BOTON_CONFIRMAR_NO_ENCONTRADO"}

        boton_confirmar.click()

        # Esperar pagina de exito
        try:
            wait.until(lambda d: "Exitosa" in d.current_url or "Exitoso" in d.current_url)
        except TimeoutException:
            log.error("  Timeout esperando pagina de exito.")
            _screenshot(driver, "caucion_post_confirmar")
            return {"ok": False, "estado": "TIMEOUT_PAGINA_EXITOSA",
                    "detalle": f"URL actual: {driver.current_url}"}

    # ── 7. Pagina de EXITO ───────────────────────────────────────
    if "Exitosa" in driver.current_url or "Exitoso" in driver.current_url:
        _screenshot(driver, "caucion_exitosa")
        id_op = _parsear_id_operacion(driver)
        log.info(f"  Caucion colocada exitosamente. ID operacion: {id_op or 'no parseado'}")
        return {
            "ok":     True,
            "estado": "COLOCADA",
            "detalle": f"URL: {driver.current_url}",
            "id_op":  id_op,
        }

    # Si llego aca sin exito claro
    _screenshot(driver, "caucion_resultado_desconocido")
    return {
        "ok":     False,
        "estado": "RESULTADO_DESCONOCIDO",
        "detalle": f"URL final: {driver.current_url}",
    }


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _seleccionar_plazo_alternativo(driver, plazo):
    """Intenta seleccionar el plazo via select o radio buttons."""
    # Buscar select con opciones de plazo
    try:
        from selenium.webdriver.support.ui import Select
        selects = driver.find_elements(By.TAG_NAME, "select")
        for s in selects:
            name = s.get_attribute("name") or ""
            if "plazo" in name.lower() or "dias" in name.lower():
                sel = Select(s)
                sel.select_by_value(str(plazo))
                log.info(f"  Plazo seleccionado via select: {plazo}")
                return
    except Exception:
        pass

    # Buscar radio buttons
    try:
        radios = driver.find_elements(By.CSS_SELECTOR, f'input[type="radio"][value="{plazo}"]')
        for r in radios:
            if r.is_displayed():
                r.click()
                log.info(f"  Plazo seleccionado via radio: {plazo}")
                return
    except Exception:
        pass

    log.warning(f"  No se pudo seleccionar plazo={plazo} por metodo alternativo.")


def _parsear_id_operacion(driver):
    """Intenta extraer el ID de operacion del texto de la pagina de exito."""
    try:
        texto = driver.find_element(By.TAG_NAME, "body").text
        import re
        # Buscar patrones como: N° 12345678 o id: 12345678 o numero: 12345678
        patrones = [
            r"[Nn][°ú]\s*(\d{5,12})",
            r"[Nn]umero[:\s]+(\d{5,12})",
            r"[Ii][dD][:\s]+(\d{5,12})",
            r"[Oo]peracion[:\s]+(\d{5,12})",
            r"#(\d{5,12})",
        ]
        for patron in patrones:
            m = re.search(patron, texto)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def _guardar_html_diagnostico(driver, nombre):
    """Guarda el HTML de la pagina actual para diagnostico."""
    try:
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(RUTA_SCREENSHOTS, f"{ts}_{nombre}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log.info(f"  HTML guardado en: {path}")
        return path
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# FUNCION PRINCIPAL — usada desde ejecutor_real_caucion.py
# ─────────────────────────────────────────────────────────────────

def ejecutar_caucion_selenium(monto, plazo, tna_minima=None, headless=False):
    """
    Punto de entrada principal.
    Abre Chrome, hace login, coloca la caucion y cierra Chrome.

    Devuelve el mismo formato de dict que ejecutar_caucion_real().
    """
    driver = None
    try:
        log.info(f"Iniciando ejecucion real de caucion via Selenium:")
        log.info(f"  Monto:  ARS {monto:,.2f}")
        log.info(f"  Plazo:  {plazo} dia(s) habil(es)")
        if tna_minima:
            log.info(f"  TNA min: {tna_minima:.2f}%")

        driver = crear_driver(headless=headless)

        # Login
        ok_login = login(driver)
        if not ok_login:
            return {"ok": False, "estado": "LOGIN_FALLIDO",
                    "detalle": "No se pudo autenticar en IOL. Verificar credenciales."}

        # Colocar
        resultado = colocar_caucion(driver, monto=monto, plazo=plazo, tna_minima=tna_minima)
        return resultado

    except Exception as e:
        log.error(f"Error inesperado en Selenium: {e}", exc_info=True)
        if driver:
            _screenshot(driver, "error_inesperado")
        return {"ok": False, "estado": "ERROR_INESPERADO", "detalle": str(e)}

    finally:
        if driver:
            log.info("  Cerrando Chrome...")
            cerrar_driver(driver)


# ─────────────────────────────────────────────────────────────────
# PRUEBA DIRECTA
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    print("=" * 55)
    print("  PRUEBA EJECUTOR SELENIUM — CAUCION IOL")
    print("=" * 55)
    print()
    print("  MODO: DISCOVERY (solo login + screenshot del formulario)")
    print("  No se va a enviar ninguna orden real.")
    print()

    driver = None
    try:
        driver = crear_driver(headless=False)
        ok = login(driver)
        if not ok:
            print("  Login fallido.")
            sys.exit(1)

        print("  Login OK. Abriendo formulario de caucion...")
        driver.get(f"{BASE_URL}/Operar/Caucionar")
        time.sleep(3)

        _screenshot(driver, "discovery_caucion_form")
        _guardar_html_diagnostico(driver, "discovery_caucion_html")

        # Imprimir todos los inputs del formulario
        print("\n  Campos encontrados en la pagina:")
        inputs = driver.find_elements(By.TAG_NAME, "input")
        for inp in inputs:
            name  = inp.get_attribute("name")  or ""
            iid   = inp.get_attribute("id")    or ""
            itype = inp.get_attribute("type")  or "text"
            ph    = inp.get_attribute("placeholder") or ""
            if inp.is_displayed() and itype not in ("hidden",):
                print(f"    name='{name}' id='{iid}' type='{itype}' placeholder='{ph}'")

        selects = driver.find_elements(By.TAG_NAME, "select")
        for sel in selects:
            if sel.is_displayed():
                print(f"    SELECT: name='{sel.get_attribute('name')}' id='{sel.get_attribute('id')}'")

        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if btn.is_displayed():
                print(f"    BUTTON: text='{btn.text.strip()[:40]}' type='{btn.get_attribute('type')}'")

        print(f"\n  URL actual: {driver.current_url}")
        print(f"\n  Screenshot guardado en: datos/screenshots/")
        print(f"  HTML guardado en:       datos/screenshots/")
        print("\n  Revisa esos archivos y compartelos para ajustar el ejecutor.")

    finally:
        if driver:
            input("\n  Presiona ENTER para cerrar Chrome...")
            cerrar_driver(driver)
