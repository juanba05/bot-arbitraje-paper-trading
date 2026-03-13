archivo = 'recolector.py'

with open(archivo, encoding='utf-8') as f:
    contenido = f.read()

# Corregir importacion con enie
contenido = contenido.replace('guardar_señal', 'guardar_senal')
contenido = contenido.replace("'señales'", "'seniales'")
contenido = contenido.replace('"señales"', '"seniales"')

with open(archivo, 'w', encoding='utf-8') as f:
    f.write(contenido)

print("✅ recolector.py corregido")
