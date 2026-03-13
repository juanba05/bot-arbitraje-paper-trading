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
    driver = uc.Chrome(options=options, version_main=145)
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

    Campos confirmados via discovery (13/03/2026):
        Monto    -> name='Monto'  id='textmonto'
        Plazo    -> SELECT name='IdPlazo' id='IdPlazo'
        TNA      -> name='Tna'   id='Tna'
        Moneda   -> radio id='moneda-ars'
        Modalidad-> radio id='minimal_price'  (precio minimo = tna minima)
        Submit   -> id='btnEnviar'

    Devuelve dict con: ok, estado, detalle, id_op
    """
    from selenium.webdriver.support.ui import Select

    wait = WebDriverWait(driver, TIMEOUT)

    # ── 1. Navegar al formulario ─────────────────────────────────
    log.info("  Navegando a /Operar/Caucionar...")
    driver.get(f"{BASE_URL}/Operar/Caucionar")
    try:
        wait.until(lambda d: "Login" not in d.current_url)
    except TimeoutException:
        _screenshot(driver, "caucion_redir_login")
        return {"ok": False, "estado": "SESION_EXPIRADA",
                "detalle": "Redireccion a login al abrir Caucionar"}

    # Esperar que el campo monto este presente en el DOM
    try:
        wait.until(EC.presence_of_element_located((By.ID, "textmonto")))
    except TimeoutException:
        _screenshot(driver, "caucion_form_no_cargo")
        _guardar_html_diagnostico(driver, "caucion_form_no_cargo")
        return {"ok": False, "estado": "FORMULARIO_NO_CARGADO",
                "detalle": "Campo #textmonto no aparecio en el DOM"}

    time.sleep(1)
    _screenshot(driver, "caucion_form_cargado")

    # ── 2. Seleccionar moneda ARS ────────────────────────────────
    try:
        radio_ars = driver.find_element(By.ID, "moneda-ars")
        if not radio_ars.is_selected():
            radio_ars.click()
            log.info("  Moneda ARS seleccionada.")
    except NoSuchElementException:
        log.warning("  Radio moneda-ars no encontrado — continuando.")

    # ── 3. Ingresar MONTO ────────────────────────────────────────
    campo_monto = driver.find_element(By.ID, "textmonto")
    campo_monto.clear()
    campo_monto.send_keys(str(int(monto)))
    log.info(f"  Monto ingresado: {int(monto)}")

    # ── 4. Seleccionar PLAZO ─────────────────────────────────────
    try:
        select_plazo = Select(driver.find_element(By.ID, "IdPlazo"))
        select_plazo.select_by_value(str(plazo))
        log.info(f"  Plazo seleccionado: {plazo}")
    except Exception as e:
        log.warning(f"  No se pudo seleccionar plazo={plazo}: {e}")

    # ── 5. Seleccionar modalidad precio minimo (ingresa TNA) ─────
    try:
        radio_min = driver.find_element(By.ID, "minimal_price")
        if not radio_min.is_selected():
            radio_min.click()
            log.info("  Modalidad 'precio minimo' (TNA minima) seleccionada.")
        time.sleep(0.5)  # esperar que aparezca el campo Tna
    except NoSuchElementException:
        log.warning("  Radio minimal_price no encontrado — continuando.")

    # ── 6. Ingresar TNA minima ───────────────────────────────────
    if tna_minima is not None:
        try:
            campo_tna = driver.find_element(By.ID, "Tna")
            campo_tna.clear()
            campo_tna.send_keys(str(tna_minima).replace(".", ","))
            log.info(f"  TNA minima ingresada: {tna_minima}")
        except NoSuchElementException:
            log.warning("  Campo Tna no encontrado — se omite tna_minima.")

    _screenshot(driver, "caucion_form_completo")

    # ── 7. Submit ────────────────────────────────────────────────
    try:
        boton_submit = driver.find_element(By.ID, "btnEnviar")
    except NoSuchElementException:
        # Fallback: primer submit del formulario
        try:
            boton_submit = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
        except NoSuchElementException:
            _screenshot(driver, "caucion_sin_boton")
            return {"ok": False, "estado": "BOTON_SUBMIT_NO_ENCONTRADO"}

    log.info("  Enviando formulario...")
    boton_submit.click()

    # ── 8. Pagina de CONFIRMACION ────────────────────────────────
    try:
        wait.until(lambda d: "Confirmar" in d.current_url or "Exitosa" in d.current_url)
    except TimeoutException:
        _screenshot(driver, "caucion_post_submit")
        return {"ok": False, "estado": "TIMEOUT_CONFIRMACION",
                "detalle": f"URL actual: {driver.current_url}"}

    if "ConfirmarCaucion" in driver.current_url:
        log.info("  Pagina de confirmacion. Confirmando...")
        _screenshot(driver, "caucion_confirmar")
        try:
            btn_conf = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
            btn_conf.click()
        except NoSuchElementException:
            _screenshot(driver, "caucion_sin_boton_confirmar")
            return {"ok": False, "estado": "BOTON_CONFIRMAR_NO_ENCONTRADO"}

        try:
            wait.until(lambda d: "Exitosa" in d.current_url or "Exitoso" in d.current_url)
        except TimeoutException:
            _screenshot(driver, "caucion_post_confirmar")
            return {"ok": False, "estado": "TIMEOUT_PAGINA_EXITOSA",
                    "detalle": f"URL actual: {driver.current_url}"}

    # ── 9. Pagina de EXITO ───────────────────────────────────────
    if "Exitosa" in driver.current_url or "Exitoso" in driver.current_url:
        _screenshot(driver, "caucion_exitosa")
        id_op = _parsear_id_operacion(driver)
        log.info(f"  Caucion colocada. ID operacion: {id_op or 'no parseado'}")
        return {"ok": True, "estado": "COLOCADA",
                "detalle": f"URL: {driver.current_url}", "id_op": id_op}

    _screenshot(driver, "caucion_resultado_desconocido")
    return {"ok": False, "estado": "RESULTADO_DESCONOCIDO",
            "detalle": f"URL final: {driver.current_url}"}


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
