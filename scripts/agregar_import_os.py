archivo = 'motor_cauciones.py'

with open(archivo, encoding='utf-8') as f:
    contenido = f.read()

if 'import os' not in contenido:
    contenido = 'import os\n' + contenido

with open(archivo, 'w', encoding='utf-8') as f:
    f.write(contenido)

print("✅ import os agregado a motor_cauciones.py")
