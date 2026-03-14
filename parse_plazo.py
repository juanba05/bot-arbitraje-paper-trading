import re, glob, os

htmls = sorted(glob.glob("datos/screenshots/*.html"))
print("HTMLs:", len(htmls))
if not htmls:
    print("No hay HTMLs guardados")
    exit()

latest = htmls[-1]
print("Usando:", os.path.basename(latest))

with open(latest, encoding="utf-8", errors="replace") as f:
    html = f.read()

# Buscar todas las opciones de select cerca de "IdPlazo"
idx = html.find("IdPlazo")
if idx == -1:
    print("IdPlazo no encontrado en HTML")
else:
    chunk = html[max(0, idx-50):idx+2000]
    opts = re.findall(r"value=[\"']([^\"']*)[\"'][^>]*>([^<]*)", chunk)
    print("Opciones cercanas a IdPlazo:")
    for v, t in opts[:15]:
        print(f"  value={repr(v)} | text={repr(t.strip())}")
