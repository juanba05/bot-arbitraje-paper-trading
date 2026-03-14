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

def _js_click(driver, element):
    """Hace click via JavaScript — funciona aunque Chrome este minimizado."""
    driver.execute_script("arguments[0].click()", element)


def crear_driver(headless=False, minimized=True):
    """
    Crea y devuelve un Chrome driver con anti-deteccion.
    headless=False + minimized=True: Chrome arranca minimizado en la barra de
        Windows (no interrumpe el trabajo, pero es visible en la barra inferior).
    headless=True: Chrome completamente invisible (sin icono en barra).
    """
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    if headless:
        options.add_argument("--headless=new")
    driver = uc.Chrome(options=options, version_main=145)
    driver.implicitly_wait(5)
    if not headless and minimized:
        try:
            driver.minimize_window()
        except Exception:
            pass
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
        _js_click(driver, btn)
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
    # Primero vamos a la pagina principal para "calentar" la sesion,
    # luego navegamos al formulario. Esto evita que IOL redirija al
    # detectar una navegacion directa desde login al formulario de trading.
    log.info("  Esperando que la sesion se estabilice...")
    time.sleep(3)
    log.info("  Navegando a pagina principal primero...")
    driver.get(f"{BASE_URL}/micuenta/estadocuenta")
    time.sleep(2)

    url_home = driver.current_url
    if "Login" in url_home:
        _screenshot(driver, "caucion_redir_login")
        return {"ok": False, "estado": "SESION_EXPIRADA",
                "detalle": "Redireccion a login al cargar estadocuenta"}

    log.info(f"  Sesion activa en: {url_home}")
    log.info("  Navegando a /Operar/Caucionar...")
    driver.get(f"{BASE_URL}/Operar/Caucionar")

    try:
        wait.until(lambda d: "Login" not in d.current_url)
    except TimeoutException:
        _screenshot(driver, "caucion_redir_login")
        return {"ok": False, "estado": "SESION_EXPIRADA",
                "detalle": "Redireccion a login al abrir Caucionar"}

    url_form = driver.current_url
    log.info(f"  URL despues de navegar a Caucionar: {url_form}")

    # Esperar que el campo monto este presente en el DOM
    try:
        wait.until(EC.presence_of_element_located((By.ID, "textmonto")))
    except TimeoutException:
        _screenshot(driver, "caucion_form_no_cargo")
        _guardar_html_diagnostico(driver, "caucion_form_no_cargo")
        return {"ok": False, "estado": "FORMULARIO_NO_CARGADO",
                "detalle": f"Campo #textmonto no aparecio. URL actual: {driver.current_url}"}

    time.sleep(1)
    _screenshot(driver, "caucion_form_cargado")

    # ── 2. Seleccionar moneda ARS ────────────────────────────────
    try:
        radio_ars = driver.find_element(By.ID, "moneda-ars")
        if not radio_ars.is_selected():
            _js_click(driver, radio_ars)
            log.info("  Moneda ARS seleccionada.")
    except NoSuchElementException:
        log.warning("  Radio moneda-ars no encontrado — continuando.")

    # ── 3. Ingresar MONTO ────────────────────────────────────────
    campo_monto = driver.find_element(By.ID, "textmonto")
    campo_monto.clear()
    campo_monto.send_keys(str(int(monto)))
    log.info(f"  Monto ingresado: {int(monto)}")

    # ── 4. Seleccionar PLAZO ─────────────────────────────────────
    # El SELECT usa dias calendario (no habiles). Calculamos cuantos
    # dias calendario hay hasta el proximo vencimiento habil.
    try:
        select_plazo = Select(driver.find_element(By.ID, "IdPlazo"))
        cal_days = _habiles_a_calendario(plazo)
        log.info(f"  Plazo {plazo} dias habiles = {cal_days} dias calendario")
        # Intentar por valor calendario calculado
        try:
            select_plazo.select_by_value(str(cal_days))
            log.info(f"  Plazo seleccionado por valor: {cal_days}")
        except Exception:
            # Fallback: primera opcion disponible (plazo mas corto)
            opts = [o for o in select_plazo.options if o.get_attribute("value")]
            if opts:
                _js_click(driver, opts[min(plazo - 1, len(opts) - 1)])
                log.info(f"  Plazo seleccionado por indice {plazo-1}: {opts[min(plazo-1,len(opts)-1)].text}")
            else:
                log.warning(f"  Sin opciones en select de plazo")
    except Exception as e:
        log.warning(f"  No se pudo seleccionar plazo={plazo}: {e}")

    # ── 5. Seleccionar modalidad precio minimo + ingresar TNA ────
    # Siempre usamos precio minimo con la TNA detectada por el motor.
    # Esto protege contra ejecucion a tasas peores que la analizada.
    tna_a_usar = tna_minima if tna_minima is not None else 1.0
    try:
        radio_min = driver.find_element(By.ID, "minimal_price")
        if not radio_min.is_selected():
            _js_click(driver, radio_min)
        time.sleep(0.5)  # esperar que aparezca el campo Tna
        campo_tna = driver.find_element(By.ID, "Tna")
        campo_tna.clear()
        campo_tna.send_keys(str(round(tna_a_usar, 2)).replace(".", ","))
        log.info(f"  Modalidad precio minimo. TNA minima: {tna_a_usar:.2f}%")
    except NoSuchElementException:
        log.warning("  Campo TNA no encontrado — continuando sin TNA minima.")

    _screenshot(driver, "caucion_form_completo")

    # ── 7. Submit inicial (muestra preview en la misma pagina) ───
    try:
        boton_submit = driver.find_element(By.ID, "btnEnviar")
    except NoSuchElementException:
        try:
            boton_submit = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
        except NoSuchElementException:
            _screenshot(driver, "caucion_sin_boton")
            return {"ok": False, "estado": "BOTON_SUBMIT_NO_ENCONTRADO"}

    log.info("  Enviando formulario (paso 1 de 2 — preview)...")
    _js_click(driver, boton_submit)

    # ── 8. Esperar preview inline (id=ConfirmarCaucion aparece) ──
    # IOL muestra un preview con tasa estimada en la MISMA pagina
    # antes de navegar. El boton de confirmacion es id='ConfirmarCaucion'.
    try:
        wait.until(EC.presence_of_element_located((By.ID, "ConfirmarCaucion")))
    except TimeoutException:
        _screenshot(driver, "caucion_post_submit")
        _guardar_html_diagnostico(driver, "caucion_post_submit")
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            errores = [l for l in body_text.split("\n") if any(
                w in l.lower() for w in ["error", "invalid", "requer", "oblig", "monto", "plazo"]
            )]
            if errores:
                log.error(f"  Errores encontrados: {errores[:5]}")
        except Exception:
            pass
        return {"ok": False, "estado": "PREVIEW_NO_APARECIO",
                "detalle": f"URL actual: {driver.current_url}"}

    # Loguear la tasa estimada del preview
    _screenshot(driver, "caucion_preview")
    try:
        body = driver.find_element(By.TAG_NAME, "body").text
        for linea in body.split("\n"):
            if "tna" in linea.lower() or "total" in linea.lower() or "monto" in linea.lower():
                log.info(f"  Preview: {linea.strip()}")
    except Exception:
        pass

    # ── 9. Confirmar (paso 2) — abre pantalla con campo contrasena ─
    log.info("  Click en Confirmar (paso 2 de 3)...")
    try:
        btn_conf = driver.find_element(By.ID, "ConfirmarCaucion")
        _js_click(driver, btn_conf)
    except NoSuchElementException:
        _screenshot(driver, "caucion_sin_boton_confirmar")
        return {"ok": False, "estado": "BOTON_CONFIRMAR_NO_ENCONTRADO"}

    # ── 10. Ingresar contrasena (paso 3) ─────────────────────────
    # IOL muestra un campo de contrasena como paso final de seguridad.
    NOMBRES_PASS = ["Password", "password", "Contrasena", "contrasena",
                    "Pass", "pass", "Clave", "clave", "pin", "Pin"]
    campo_pass = None
    for _ in range(15):   # hasta 15 intentos x 1 seg = 15 seg de espera
        time.sleep(1)
        for nombre in NOMBRES_PASS:
            for attr in ["name", "id"]:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, f'input[{attr}="{nombre}"]')
                    # No chequeamos is_displayed() porque la ventana puede estar minimizada
                    if el.get_attribute("type") in ("password", "text"):
                        campo_pass = el
                        break
                except Exception:
                    pass
            if campo_pass:
                break
        if campo_pass:
            break

    if not campo_pass:
        # Intentar con cualquier input type=password (sin requerir visibilidad)
        try:
            campos = driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
            if campos:
                campo_pass = campos[0]
        except Exception:
            pass

    if not campo_pass:
        _screenshot(driver, "caucion_sin_campo_password")
        _guardar_html_diagnostico(driver, "caucion_sin_campo_password")
        return {"ok": False, "estado": "CAMPO_PASSWORD_NO_ENCONTRADO",
                "detalle": "No se encontro el campo de contrasena en la pantalla de confirmacion"}

    log.info(f"  Campo contrasena encontrado: name='{campo_pass.get_attribute('name')}' id='{campo_pass.get_attribute('id')}'")
    _screenshot(driver, "caucion_pantalla_password")
    campo_pass.clear()
    campo_pass.send_keys(IOL_PASSWORD)
    log.info("  Contrasena ingresada. Enviando confirmacion final...")

    # ── 11. Submit final (confirmar con contrasena) ───────────────
    # Guardar HTML para ver los botones disponibles
    _guardar_html_diagnostico(driver, "caucion_pantalla_password_html")
    btn_final = None
    # Candidatos por ID (confirmados via HTML discovery 13/03/2026).
    # No chequeamos is_displayed() — la ventana puede estar minimizada.
    for btn_id in ["btnSubmitCaucionar", "btnAceptar", "btnConfirmar", "submit", "Submit"]:
        try:
            el = driver.find_element(By.ID, btn_id)
            btn_final = el
            log.info(f"  Boton final encontrado: id='{btn_id}'")
            break
        except NoSuchElementException:
            pass
    # Fallback: cualquier submit del DOM (no requiere visibilidad)
    if not btn_final:
        try:
            btn_final = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
        except NoSuchElementException:
            pass
    if not btn_final:
        _screenshot(driver, "caucion_sin_boton_final")
        return {"ok": False, "estado": "BOTON_FINAL_NO_ENCONTRADO"}
    _js_click(driver, btn_final)

    # Esperar resultado
    try:
        wait.until(lambda d: d.current_url != f"{BASE_URL}/Operar/Caucionar")
    except TimeoutException:
        pass  # puede que el exito sea inline

    time.sleep(2)
    _screenshot(driver, "caucion_resultado_final")
    _guardar_html_diagnostico(driver, "caucion_resultado_final")

    # ── 12. Detectar exito ───────────────────────────────────────
    # La pagina de exito puede ser /Operar/CaucionExitosa O el listado
    # de "Estado de Cauciones" con la orden en estado "Iniciada".
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        palabras_exito = [
            "exitosa", "confirmada", "colocada", "fue enviada",
            "orden enviada", "operacion realizada",
            "n\xfamero de operaci\xf3n", "nro.", "comprobante",
            # pagina de estado de cauciones post-ejecucion (confirmado 13/03/2026):
            "iniciada", "cauciones pendientes", "caucion en pesos",
        ]
        es_exito = any(p in body_text.lower() for p in palabras_exito)
    except Exception:
        es_exito = False

    url_final = driver.current_url
    if es_exito or "Exitosa" in url_final or "Exitoso" in url_final:
        id_op = _parsear_id_operacion(driver)
        log.info(f"  CAUCION COLOCADA EXITOSAMENTE. ID: {id_op or 'no parseado'}")
        return {"ok": True, "estado": "COLOCADA",
                "detalle": f"URL: {url_final}", "id_op": id_op}

    # Guardar texto de la pagina para diagnostico
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        log.error(f"  Resultado desconocido. Texto pagina: {body_text[:300]}")
    except Exception:
        pass

    return {"ok": False, "estado": "RESULTADO_DESCONOCIDO",
            "detalle": f"URL final: {url_final}"}


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _habiles_a_calendario(plazo_habiles):
    """Convierte dias habiles a dias calendario desde hoy (saltea sabados y domingos)."""
    from datetime import date, timedelta
    hoy = date.today()
    count = 0
    d = hoy
    while count < plazo_habiles:
        d += timedelta(days=1)
        if d.weekday() < 5:   # lunes=0 ... viernes=4
            count += 1
    return (d - hoy).days


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
        patrones = [
            # Formato tabla Estado de Cauciones (confirmado 13/03/2026):
            # "167032333 Iniciada Caución en Pesos ..."
            r"(\d{7,12})\s+(?:Iniciada|Pendiente|Confirmada|Colocada)",
            # Formatos clasicos
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

        driver = crear_driver(headless=headless, minimized=not headless)

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
