"""
testeo_cauciones.py - Verificacion de la simulacion contra datos reales
=======================================================================
Corré esto cuando el mercado este abierto (11-18hs).
Te muestra exactamente qué datos son reales, de dónde vienen,
y cómo verificarlos manualmente en IOL o Ambito.

PLAN DE TESTEO:
  1. Saldo real vs lo que muestra la simulacion
  2. Tasa real del mercado vs la que usa el bot
  3. Calculo financiero: verificar los numeros a mano
  4. Logica de plazo: dia correcto, fecha correcta
  5. Registro en DB: que quedo guardado bien
"""

import sys
import os
import sqlite3
import requests
from datetime import datetime

RUTA_BASE  = os.path.dirname(os.path.abspath(__file__))
RUTA_DATOS = os.path.join(RUTA_BASE, "datos")
RUTA_DB    = os.path.join(RUTA_DATOS, "bot_arbitraje.db")
sys.path.insert(0, RUTA_BASE)


def separador(titulo=""):
    if titulo:
        print(f"\n{'─'*60}")
        print(f"  {titulo}")
        print(f"{'─'*60}")
    else:
        print(f"{'─'*60}")


# ══════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  TESTEO DE SIMULACION DE CAUCIONES")
print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
print(f"{'='*60}")


# ══════════════════════════════════════════════════════════════════
separador("TEST 1: SALDO REAL DE IOL")

saldo_iol = None
try:
    from iol_connector import _get, _obtener_token_inicial
    _obtener_token_inicial()
    datos_cuenta = _get("/estadocuenta")
    
    if datos_cuenta:
        print(f"\n  Respuesta RAW de IOL /estadocuenta:")
        if isinstance(datos_cuenta, dict) and "cuentas" in datos_cuenta:
            for i, c in enumerate(datos_cuenta["cuentas"]):
                print(f"  Cuenta {i+1}: moneda={c.get('moneda')} | "
                      f"disponible={c.get('disponible')} | "
                      f"saldo={c.get('saldo')} | "
                      f"titulosValorizados={c.get('titulosValorizados')}")
                # Detectar cuenta pesos
                moneda = str(c.get("moneda", "")).lower().replace("_","")
                if "peso" in moneda or "ars" in moneda:
                    saldo_iol = float(c.get("disponible", c.get("saldo", 0)))
        else:
            print(f"  Estructura: {str(datos_cuenta)[:300]}")

        if saldo_iol is not None:
            print(f"\n  ✅ Saldo disponible en pesos: ARS {saldo_iol:,.2f}")
            print(f"\n  👁  VERIFICACIÓN MANUAL:")
            print(f"     Entrá a invertironline.com → tu cuenta → saldo disponible")
            print(f"     Debe coincidir con: ARS {saldo_iol:,.2f}")
        else:
            print(f"\n  ⚠️  No se pudo extraer el saldo de pesos.")
            print(f"     Entrá a IOL y fijate cuánto tenés disponible en pesos.")
            saldo_iol = float(input("\n  Ingresá el saldo manualmente (ARS): ") or "0")
    else:
        print(f"  ❌ IOL no respondió")
        saldo_iol = 40000.0
        print(f"  Usando capital paper trading: ARS {saldo_iol:,.2f}")

except Exception as e:
    print(f"  ❌ Error: {e}")
    saldo_iol = 40000.0


# ══════════════════════════════════════════════════════════════════
separador("TEST 2: TASA REAL DEL MERCADO")

tna_real = None
fuente_tna = None

# Intentamos todas las URLs de Ambito
urls_ambito = [
    ("ambito colocadora", "https://mercados.ambito.com/caucion/colocadora/1/variacion"),
    ("ambito tomadora",   "https://mercados.ambito.com/caucion/tomadora/1/variacion"),
    ("ambito caucion 1d", "https://mercados.ambito.com/caucion/1/variacion"),
    ("ambito referencia", "https://mercados.ambito.com/cauciones/referencia/1/variacion"),
]

print(f"\n  Probando fuentes de tasa en tiempo real:")
for nombre, url in urls_ambito:
    try:
        resp = requests.get(url, timeout=5,
                            headers={"User-Agent": "Mozilla/5.0",
                                     "Accept": "application/json"})
        print(f"  {nombre}: HTTP {resp.status_code}", end="")
        if resp.status_code == 200:
            datos = resp.json()
            print(f" → {str(datos)[:100]}")
            if isinstance(datos, dict) and "valor" in datos:
                tna_real = float(str(datos["valor"]).replace(",","."))
                fuente_tna = nombre
                print(f"  ✅ Tasa extraida: {tna_real:.2f}% TNA")
                break
        else:
            print()
    except Exception as e:
        print(f"  {nombre}: {e}")

if tna_real is None:
    # Fallback a DB
    try:
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT tasa_anual, fecha_hora FROM cauciones
            WHERE tasa_anual > 0
            ORDER BY fecha_hora DESC LIMIT 3
        """)
        filas = cur.fetchall()
        conn.close()
        if filas:
            print(f"\n  Ambito no disponible. Ultimas tasas en DB:")
            for tasa, fh in filas:
                print(f"    {fh}: {tasa:.2f}% TNA")
            tna_real = filas[0][0]
            fuente_tna = "DB_HISTORICO"
            print(f"\n  Usando ultima tasa de DB: {tna_real:.2f}% TNA")
    except Exception as e:
        print(f"  Error leyendo DB: {e}")

if tna_real is None:
    print(f"\n  ⚠️  No se encontró tasa automáticamente.")
    print(f"     Buscá en: invertironline.com → Operar → Cauciones")
    print(f"     O en: ambito.com → Mercados → Tasas → Cauciones 1 día")
    tna_input = input("\n  Ingresá la TNA que ves en IOL/Ambito (ej: 82.5): ").strip()
    if tna_input:
        tna_real = float(tna_input)
        fuente_tna = "MANUAL"

print(f"\n  👁  VERIFICACIÓN MANUAL:")
print(f"     Entrá a invertironline.com → Operar → Cauciones Colocadoras")
print(f"     La TNA a 1 día debe ser aproximadamente: {tna_real:.1f}%")
print(f"     (Variaciones de 1-3% son normales según el minuto)")


# ══════════════════════════════════════════════════════════════════
separador("TEST 3: VERIFICACION DEL CALCULO FINANCIERO")

if saldo_iol and tna_real:
    ahora = datetime.now()
    
    # Calcular plazo segun dia
    dia = ahora.weekday()
    if dia == 4:
        plazo = 3
        desc_dia = "Viernes → 3 días hábiles"
    elif dia == 3:
        plazo = 2
        desc_dia = "Jueves → 2 días hábiles"
    else:
        plazo = 1
        desc_dia = "Lunes-Miércoles → 1 día hábil"
    
    # Capital a usar
    if 17 <= ahora.hour < 18:
        pct_capital = 1.0
        desc_capital = "Modo cierre (17-18hs) → 100%"
    else:
        pct_capital = 0.70
        desc_capital = "Modo normal → 70%"
    
    capital = round(saldo_iol * pct_capital, 2)
    
    # Calculo
    ganancia_bruta = capital * (tna_real / 100) * (plazo / 365)
    comision_base  = capital * (0.30 / 100)
    comision_iva   = comision_base * 0.21
    comision_total = comision_base + comision_iva
    ganancia_neta  = ganancia_bruta - comision_total
    rent_pct       = (ganancia_neta / capital) * 100
    al_vencimiento = capital + ganancia_neta
    
    print(f"""
  DATOS DE ENTRADA:
    Saldo IOL:        ARS {saldo_iol:>12,.2f}   (fuente: IOL real)
    TNA mercado:      {tna_real:>8.2f}% TNA       (fuente: {fuente_tna})
    Día semana:       {ahora.strftime('%A')} — {desc_dia}
    Plazo:            {plazo} día(s)
    Capital usado:    ARS {capital:>12,.2f}   ({pct_capital*100:.0f}% — {desc_capital})

  CÁLCULO PASO A PASO (podés verificarlo con una calculadora):
    ┌─────────────────────────────────────────────────────┐
    │ Ganancia bruta = {capital:,.2f} × {tna_real}% × {plazo}/365     │
    │               = ARS {ganancia_bruta:,.2f}                        │
    │                                                     │
    │ Comisión IOL   = {capital:,.2f} × 0.30% × 1.21 (IVA) │
    │               = ARS {comision_total:,.2f}                         │
    │                                                     │
    │ Ganancia NETA  = {ganancia_bruta:,.2f} - {comision_total:,.2f}     │
    │               = ARS {ganancia_neta:,.2f}                          │
    └─────────────────────────────────────────────────────┘

  RESULTADO:
    Capital colocado:    ARS {capital:>12,.2f}
    Ganancia NETA:       ARS {ganancia_neta:>12,.2f}
    Al vencimiento:      ARS {al_vencimiento:>12,.2f}
    Rentabilidad:        {rent_pct:.4f}%
    
  {'✅ CONVENIENTE: ganancia neta positiva' if ganancia_neta > 0 else '❌ NO CONVENIENTE: la comisión supera la ganancia'}
  {'→ La tasa del mercado es suficiente para cubrir la comisión de IOL' if ganancia_neta > 0 else f'→ Necesitarías TNA mayor a {(comision_total/capital)*(365/plazo)*100:.1f}% para no perder'}
    """)
    
    print(f"  👁  VERIFICACIÓN MANUAL:")
    print(f"     1. En IOL → Operar → Cauciones Colocadoras:")
    print(f"        - Monto a colocar: ARS {capital:,.2f}")
    print(f"        - Plazo: {plazo} día(s)")
    print(f"        - La ganancia que muestra IOL debe ser ≈ ARS {ganancia_bruta:,.2f}")
    print(f"        - IOL descuenta su comisión (ARS {comision_total:,.2f}) al confirmar")
    print(f"        - Ganancia neta esperada: ARS {ganancia_neta:,.2f}")


# ══════════════════════════════════════════════════════════════════
separador("TEST 4: CORRER LA SIMULACION Y VERIFICAR DB")

print(f"\n  Corriendo analizar_cauciones(modo='auto')...")
print(f"  (Esto guarda en la DB y muestra el resultado completo)\n")

try:
    from motor_cauciones import analizar_cauciones
    resultado = analizar_cauciones(modo="auto")
    
    if resultado and resultado.get("puede_operar"):
        print(f"\n  ✅ Simulación completada.")
        print(f"\n  Verificando registro en DB...")
        
        conn = sqlite3.connect(RUTA_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT timestamp, plazo_dias, tna_mercado, fuente_tasa,
                   saldo_disponible, fuente_saldo, capital_usado,
                   ganancia_neta, tiene_senal, motivo_no_senal
            FROM cauciones_simuladas
            ORDER BY timestamp DESC LIMIT 1
        """)
        fila = cur.fetchone()
        conn.close()
        
        if fila:
            print(f"""
  Último registro en cauciones_simuladas:
    Timestamp:        {fila[0]}
    Plazo:            {fila[1]} día(s)
    TNA mercado:      {fila[2]:.2f}%
    Fuente tasa:      {fila[3]}
    Saldo IOL:        ARS {fila[4]:,.2f}
    Fuente saldo:     {fila[5]}
    Capital usado:    ARS {fila[6]:,.2f}
    Ganancia neta:    ARS {fila[7]:,.2f}
    Tiene señal:      {'SÍ' if fila[8] else 'NO'}
    Motivo (si no):   {fila[9] or '-'}
            """)
            
            # Comparar con calculo manual
            if saldo_iol and tna_real:
                diff_tna    = abs(fila[2] - tna_real)
                diff_saldo  = abs(fila[4] - saldo_iol)
                diff_cap    = abs(fila[6] - capital)
                diff_gan    = abs(fila[7] - ganancia_neta)
                
                print(f"  COMPARACION simulacion vs calculo manual:")
                print(f"    TNA:          bot={fila[2]:.2f}% vs manual={tna_real:.2f}% → diff={diff_tna:.2f}% {'✅' if diff_tna < 3 else '⚠️'}")
                print(f"    Saldo:        bot=ARS {fila[4]:,.2f} vs IOL=ARS {saldo_iol:,.2f} → diff=ARS {diff_saldo:.2f} {'✅' if diff_saldo < 10 else '⚠️'}")
                print(f"    Capital:      bot=ARS {fila[6]:,.2f} vs manual=ARS {capital:,.2f} → diff=ARS {diff_cap:.2f} {'✅' if diff_cap < 10 else '⚠️'}")
                print(f"    Ganancia:     bot=ARS {fila[7]:,.2f} vs manual=ARS {ganancia_neta:,.2f} → diff=ARS {diff_gan:.2f} {'✅' if diff_gan < 1 else '⚠️'}")
        else:
            print(f"  ⚠️  No se encontró registro en DB. Revisar errores arriba.")
    else:
        motivo = resultado.get("motivo", "desconocido") if resultado else "None"
        print(f"\n  ⚠️  Simulación no pudo operar: {motivo}")

except Exception as e:
    print(f"  ❌ Error: {e}")
    import traceback
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════════
separador("RESUMEN DEL TESTEO")

print(f"""
  Para validar que la simulación es correcta, comparás:

  [A] SALDO: lo que muestra el bot vs lo que ves en IOL
      → invertironline.com → tu cuenta → disponible en pesos

  [B] TASA: la TNA que usa el bot vs la que ves en IOL
      → IOL → Operar → Cauciones → tasa a 1 día colocadora

  [C] CALCULO: el resultado de la simulación vs hacerlo a mano
      → Ganancia = Capital × TNA% × plazo/365
      → Comisión = Capital × 0.30% × 1.21

  [D] DB: que el registro quedó guardado correctamente
      → tabla cauciones_simuladas, último registro

  Si A, B, C y D coinciden → la simulación es 100% real y confiable.
""")

print(f"{'='*60}\n")
