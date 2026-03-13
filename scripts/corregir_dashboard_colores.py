"""
Corrige los colores hex con transparencia en dashboard.py
Plotly no acepta #rrggbbaa, hay que usar rgba(r,g,b,a)
"""

archivo = r'C:\Users\Usuario\bot_arbitraje\dashboard.py'

with open(archivo, encoding='utf-8') as f:
    contenido = f.read()

# Reemplazar los colores problemáticos
reemplazos = {
    'C["border"]+"55"':  '"rgba(26,42,58,0.33)"',
    "C['border']+'55'":  '"rgba(26,42,58,0.33)"',
    'C["border"] + "55"': '"rgba(26,42,58,0.33)"',
    '+"22"':             '# color transparente',
    'col+"22"':          '"rgba(0,230,118,0.13)"',
    'color_line + "22"': '"rgba(0,230,118,0.13)"',
    # Gridcolor directo
    'gridcolor=C["border"]+"55"': 'gridcolor="rgba(26,42,58,0.33)"',
    'gridcolor=C["border"] + "55"': 'gridcolor="rgba(26,42,58,0.33)"',
}

# Corrección directa y segura
contenido = contenido.replace(
    'gridcolor=C["border"]+"55"',
    'gridcolor="rgba(26,42,58,0.33)"'
)
contenido = contenido.replace(
    'gridcolor=C["border"] + "55"',
    'gridcolor="rgba(26,42,58,0.33)"'
)
contenido = contenido.replace(
    "gridcolor=C['border']+'55'",
    'gridcolor="rgba(26,42,58,0.33)"'
)
contenido = contenido.replace(
    'fillcolor=col+"22"',
    'fillcolor="rgba(0,230,118,0.13)"'
)
contenido = contenido.replace(
    'fillcolor=color_line+"22"',
    'fillcolor="rgba(0,230,118,0.13)"'
)
contenido = contenido.replace(
    'fillcolor=color_line + "22"',
    'fillcolor="rgba(0,230,118,0.13)"'
)
# Patron general para cualquier hex+"55" o hex+"22" que quede
import re
contenido = re.sub(
    r'gridcolor=C\[.border.\]\s*\+\s*["\']55["\']',
    'gridcolor="rgba(26,42,58,0.33)"',
    contenido
)
contenido = re.sub(
    r'fillcolor=\w+\s*\+\s*["\']22["\']',
    'fillcolor="rgba(0,230,118,0.13)"',
    contenido
)

with open(archivo, 'w', encoding='utf-8') as f:
    f.write(contenido)

print("✅ dashboard.py corregido — colores con transparencia convertidos a rgba")
print("Ahora ejecutá: python dashboard.py")
