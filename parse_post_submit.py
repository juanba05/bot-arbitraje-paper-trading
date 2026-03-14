import re, glob, os

htmls = sorted(glob.glob("datos/screenshots/*post_submit*.html"))
if not htmls:
    print("No hay HTML de post_submit")
    exit()

with open(htmls[-1], encoding="utf-8", errors="replace") as f:
    html = f.read()

print("Archivo:", os.path.basename(htmls[-1]))
print()

# Buscar botones y links visibles
btns = re.findall(r'<(?:button|input|a)[^>]*(?:type=["\']submit["\']|class=[^>]*btn[^>]*)[^>]*>([^<]*)', html, re.IGNORECASE)
print("Botones/links tipo submit o con clase btn:")
for b in btns[:20]:
    t = b.strip()
    if t:
        print(f"  {repr(t)}")

# Buscar IDs de botones que podrían ser el confirm
ids = re.findall(r'id=["\']([^"\']*(?:confirm|accept|acepta|colocar|caucionar|enviar|ok|btn)[^"\']*)["\']', html, re.IGNORECASE)
print("\nIDs relacionados con confirmacion:")
for i in set(ids):
    print(f"  {repr(i)}")

# Mostrar texto visible que parece tabla de resultados
idx = html.find("Monto estimado")
if idx == -1:
    idx = html.find("Tasa Total")
if idx > 0:
    chunk = html[max(0,idx-500):idx+2000]
    # Limpiar HTML
    clean = re.sub(r'<[^>]+>', ' ', chunk)
    clean = re.sub(r'\s+', ' ', clean).strip()
    print("\nTexto alrededor de 'Monto estimado':")
    print(clean[:1500])
