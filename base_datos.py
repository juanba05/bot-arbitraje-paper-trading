# ============================================================
# BASE_DATOS.PY — Crea y gestiona la base de datos del bot
# ============================================================

import sqlite3
import os
from config import RUTA_DATOS, NOMBRE_DB

RUTA_DB = os.path.join(RUTA_DATOS, NOMBRE_DB)


def conectar():
    """Devuelve una conexión a la base de datos."""
    return sqlite3.connect(RUTA_DB)


def crear_tablas():
    """Crea todas las tablas si no existen."""
    conn = conectar()
    c = conn.cursor()

    # Precios de CEDEARs en ARS (desde IOL)
    c.execute("""
        CREATE TABLE IF NOT EXISTS precios_cedears (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            simbolo     TEXT NOT NULL,
            precio_ars  REAL,
            volumen     REAL
        )
    """)

    # Precios de acciones en NYSE en USD (desde Polygon)
    c.execute("""
        CREATE TABLE IF NOT EXISTS precios_nyse (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            simbolo     TEXT NOT NULL,
            precio_usd  REAL
        )
    """)

    # CCL calculado desde dolarapi.com
    c.execute("""
        CREATE TABLE IF NOT EXISTS ccl_historico (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            ccl_valor   REAL
        )
    """)

    # Tasas de cauciones a 1 dia
    c.execute("""
        CREATE TABLE IF NOT EXISTS cauciones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora  TEXT NOT NULL,
            plazo_dias  INTEGER,
            tasa_anual  REAL,
            fuente      TEXT
        )
    """)

    # Seniales detectadas por el motor (sin enie para evitar problemas)
    c.execute("""
        CREATE TABLE IF NOT EXISTS seniales (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora      TEXT NOT NULL,
            tipo            TEXT NOT NULL,
            simbolo         TEXT,
            descripcion     TEXT,
            spread_pct      REAL,
            accion          TEXT,
            ccl_implicito   REAL,
            ccl_referencia  REAL,
            tasa_caucion    REAL
        )
    """)

    # Operaciones del paper trading (simuladas)
    c.execute("""
        CREATE TABLE IF NOT EXISTS operaciones_paper (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT NOT NULL,
            tipo            TEXT NOT NULL,
            simbolo         TEXT,
            accion          TEXT,
            precio_entrada  REAL,
            precio_salida   REAL,
            cantidad        REAL,
            capital_usado   REAL,
            ganancia_neta   REAL,
            comision        REAL,
            estado          TEXT DEFAULT 'ABIERTA'
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Base de datos lista en:", RUTA_DB)


def guardar_precio_nyse(timestamp, simbolo, precio_usd):
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        INSERT INTO precios_nyse (timestamp, simbolo, precio_usd)
        VALUES (?, ?, ?)
    """, (timestamp, simbolo, precio_usd))
    conn.commit()
    conn.close()


def guardar_ccl(timestamp, ccl_valor):
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        INSERT INTO ccl_historico (timestamp, ccl_valor)
        VALUES (?, ?)
    """, (timestamp, ccl_valor))
    conn.commit()
    conn.close()


def guardar_caucion(fecha_hora, plazo_dias, tasa_anual, fuente):
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        INSERT INTO cauciones (fecha_hora, plazo_dias, tasa_anual, fuente)
        VALUES (?, ?, ?, ?)
    """, (fecha_hora, plazo_dias, tasa_anual, fuente))
    conn.commit()
    conn.close()


def guardar_senal(fecha_hora, tipo, simbolo, descripcion, spread_pct, accion,
                  ccl_implicito=None, ccl_referencia=None, tasa_caucion=None):
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        INSERT INTO seniales
        (fecha_hora, tipo, simbolo, descripcion, spread_pct, accion,
         ccl_implicito, ccl_referencia, tasa_caucion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (fecha_hora, tipo, simbolo, descripcion, spread_pct, accion,
          ccl_implicito, ccl_referencia, tasa_caucion))
    conn.commit()
    conn.close()


def guardar_operacion_paper(timestamp, tipo, simbolo, accion, precio_entrada,
                             cantidad, capital_usado, comision):
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        INSERT INTO operaciones_paper
        (timestamp, tipo, simbolo, accion, precio_entrada,
         cantidad, capital_usado, comision, estado)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ABIERTA')
    """, (timestamp, tipo, simbolo, accion, precio_entrada,
          cantidad, capital_usado, comision))
    conn.commit()
    conn.close()


def obtener_seniales_recientes(limite=50):
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM seniales
        ORDER BY fecha_hora DESC
        LIMIT ?
    """, (limite,))
    filas = c.fetchall()
    conn.close()
    return filas


def obtener_operaciones_paper():
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM operaciones_paper
        ORDER BY timestamp DESC
    """)
    filas = c.fetchall()
    conn.close()
    return filas


def obtener_ultimos_precios_nyse():
    """Devuelve el último precio registrado de cada símbolo NYSE."""
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        SELECT simbolo, precio_usd, MAX(timestamp)
        FROM precios_nyse
        GROUP BY simbolo
    """)
    filas = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in filas}


def obtener_ultimo_ccl():
    conn = conectar()
    c = conn.cursor()
    c.execute("""
        SELECT ccl_valor FROM ccl_historico
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    fila = c.fetchone()
    conn.close()
    return fila[0] if fila else None


# --- Ejecutar directamente para inicializar la base de datos ---
if __name__ == "__main__":
    crear_tablas()
