# ============================================================
# MIGRAR_BD.PY — Corrige la base de datos (ejecutar una sola vez)
# Renombra la tabla "señales" a "seniales" para evitar problemas con la ñ
# ============================================================

import sqlite3
import os
from config import RUTA_DATOS, NOMBRE_DB

RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)

def migrar():
    conn = sqlite3.connect(RUTA_DB)
    c = conn.cursor()

    # Ver qué tablas existen
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tablas = [row[0] for row in c.fetchall()]
    print(f"Tablas actuales: {tablas}")

    # Si existe "señales" la renombramos
    if "señales" in tablas:
        print("Renombrando tabla 'señales' -> 'seniales'...")
        c.execute("ALTER TABLE 'señales' RENAME TO seniales")
        conn.commit()
        print("OK.")
    elif "seniales" in tablas:
        print("La tabla 'seniales' ya existe. No se necesita migrar.")
    else:
        print("Creando tabla 'seniales' desde cero...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS seniales (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT NOT NULL,
                tipo            TEXT NOT NULL,
                simbolo         TEXT,
                spread_pct      REAL,
                ccl_implicito   REAL,
                ccl_referencia  REAL,
                tasa_caucion    REAL,
                descripcion     TEXT
            )
        """)
        conn.commit()
        print("OK.")

    # Verificar resultado final
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tablas_final = [row[0] for row in c.fetchall()]
    print(f"Tablas ahora: {tablas_final}")
    conn.close()
    print("\nMigracion completada.")

if __name__ == "__main__":
    migrar()
