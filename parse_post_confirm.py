import re, glob, os

htmls = sorted(glob.glob("datos/screenshots/*post_confirmar*.html"))
if not htmls:
    print("No hay HTML de post_confirmar")
    exit()

with open(htmls[-1], encoding="utf-8", errors="replace") as f:
    html = f.read()

print("Archivo:", os.path.basename(htmls[-1]))
print()

# Extraer texto visible sin HTML
clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL|re.IGNORECASE)
clean = re.sub(r'<[^>]+>', ' ', clean)
clean = re.sub(r'&[a-zA-Z]+;', ' ', clean)
clean = re.sub(r'\s+', ' ', clean).strip()

# Mostrar fragmentos relevantes
keywords = ["exitosa", "confirmada", "colocada", "orden", "operacion", "error",
            "caucion", "numero", "n\u00famero", "comprobante", "Nro"]
lines = [l.strip() for l in clean.split('.') if any(k.lower() in l.lower() for k in keywords)]
print("Fragmentos relevantes:")
for l in lines[:20]:
    if len(l) > 10:
        print(f"  {l[:200]}")

print()
# Mostrar los ultimos 800 caracteres del texto limpio
print("Final del texto de la pagina:")
print(clean[-800:])
