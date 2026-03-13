"""
reporte_cauciones_real_vs_sim.py
--------------------------------
Reporte de cierre para comparar ejecuciones reales vs simulacion de cauciones.
"""

import argparse
import json
import sqlite3
from datetime import datetime

from config import RUTA_DATOS, NOMBRE_DB
from motor_cauciones import resumen_real_vs_sim_dia


RUTA_DB = f"{RUTA_DATOS}\\{NOMBRE_DB}"


def _detalle_ops(fecha_iso, limit=20):
    conn = sqlite3.connect(RUTA_DB)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            timestamp, plazo_dias, tna_mercado, monto_colocado,
            comision_simulada, comision_real,
            ganancia_neta_simulada, ganancia_neta_real,
            delta_comision, delta_ganancia_neta, fuente
        FROM cauciones_real_vs_sim
        WHERE substr(timestamp,1,10)=?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (fecha_iso, int(limit)),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser(description="Reporte diario real vs sim de cauciones")
    parser.add_argument("--fecha", default=datetime.now().date().isoformat(), help="Fecha YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=20, help="Cantidad maxima de operaciones a mostrar")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args()

    resumen = resumen_real_vs_sim_dia(args.fecha)
    detalle = _detalle_ops(args.fecha, limit=args.limit)

    if args.json:
        payload = {
            "resumen": resumen,
            "detalle": [
                {
                    "timestamp": r[0],
                    "plazo_dias": r[1],
                    "tna_mercado": r[2],
                    "monto_colocado": r[3],
                    "comision_simulada": r[4],
                    "comision_real": r[5],
                    "ganancia_neta_simulada": r[6],
                    "ganancia_neta_real": r[7],
                    "delta_comision": r[8],
                    "delta_ganancia_neta": r[9],
                    "fuente": r[10],
                }
                for r in detalle
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print("=" * 72)
    print(f"REPORTE REAL VS SIM - CAUCIONES - {args.fecha}")
    print("=" * 72)
    print(
        f"Ops: {resumen.get('ops', 0)} | "
        f"Monto total: ${resumen.get('monto_total', 0):,.2f} | "
        f"Sim: ${resumen.get('ganancia_sim_total', 0):,.2f} | "
        f"Real: ${resumen.get('ganancia_real_total', 0):,.2f} | "
        f"Delta total: ${resumen.get('delta_ganancia_total', 0):,.2f}"
    )
    print(
        f"Delta comision promedio: ${resumen.get('delta_comision_promedio', 0):,.2f} | "
        f"Delta ganancia promedio: ${resumen.get('delta_ganancia_promedio', 0):,.2f}"
    )
    print("-" * 72)
    if not detalle:
        print("Sin operaciones reales registradas para esa fecha.")
        return

    print("Ultimas operaciones:")
    for r in detalle:
        print(
            f"{r[0]} | {int(r[1])}d | TNA {float(r[2]):.2f}% | "
            f"Monto ${float(r[3]):,.2f} | "
            f"dCom ${float(r[8]):+.2f} | dGan ${float(r[9]):+.2f}"
        )


if __name__ == "__main__":
    main()
