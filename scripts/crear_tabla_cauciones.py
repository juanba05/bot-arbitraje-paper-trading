import sqlite3

conn = sqlite3.connect('datos/bot_arbitraje.db')
cur = conn.cursor()

cur.execute('''
    CREATE TABLE IF NOT EXISTS cauciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_hora TEXT,
        plazo_dias INTEGER,
        tasa_anual REAL,
        fuente TEXT
    )
''')

conn.commit()
conn.close()
print('✅ Tabla cauciones creada OK')
