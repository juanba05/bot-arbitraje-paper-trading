import os

archivo = 'motor_cauciones.py'

with open(archivo, encoding='utf-8') as f:
    contenido = f.read()

contenido = contenido.replace(
    'RUTA_DB = f"{RUTA_DATOS}{NOMBRE_DB}"',
    'RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)'
)

with open(archivo, 'w', encoding='utf-8') as f:
    f.write(contenido)

print("✅ Ruta corregida en motor_cauciones.py")
