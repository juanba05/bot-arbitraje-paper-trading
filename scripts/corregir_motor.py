"""
Corrige motor_calculo.py para usar simbolo_iol al consultar precios ARS en IOL.
"""

archivo = r'C:\Users\Usuario\bot_arbitraje\motor_calculo.py'

with open(archivo, encoding='utf-8') as f:
    contenido = f.read()

# Corrección 1: en calcular_spreads_real, usar simbolo_iol para precio ARS
viejo = "        precio_ars = obtener_precio_ars_iol(simbolo_cedear)\n        if not precio_ars:\n            sin_precio_ars.append(simbolo_cedear)"
nuevo = "        simbolo_iol = datos.get('simbolo_iol', simbolo_cedear)\n        precio_ars = obtener_precio_ars_iol(simbolo_iol)\n        if not precio_ars:\n            sin_precio_ars.append(simbolo_cedear)"

if viejo in contenido:
    contenido = contenido.replace(viejo, nuevo)
    print("✅ Corrección aplicada: motor_calculo usa simbolo_iol para precios ARS")
else:
    print("⚠️  No se encontró el texto exacto. Revisando...")
    # Buscar variante
    if "obtener_precio_ars_iol(simbolo_cedear)" in contenido:
        contenido = contenido.replace(
            "obtener_precio_ars_iol(simbolo_cedear)",
            "obtener_precio_ars_iol(datos.get('simbolo_iol', simbolo_cedear))"
        )
        print("✅ Corrección alternativa aplicada")
    else:
        print("❌ No se pudo aplicar la corrección automáticamente")

with open(archivo, 'w', encoding='utf-8') as f:
    f.write(contenido)

print("Listo. Probá con: python motor_calculo.py")
