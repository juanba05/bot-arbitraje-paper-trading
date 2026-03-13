"""
dashboard.py - Centro de control del bot de cauciones IOL.
Dashboard oscuro con monitoreo de tasas, señales y operaciones.
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
from dash import Dash, html, dcc, Input, Output, State, callback_context
import plotly.graph_objects as go

from config import RUTA_DATOS, NOMBRE_DB, MAX_NEGATIVAS_CONSECUTIVAS
from mercado import estado_mercado
from ejecutor_paper import capital_disponible

# ── RUTAS ──────────────────────────────────────────────────────────────────

RUTA_DB        = os.path.join(RUTA_DATOS, NOMBRE_DB)
RUTA_CONFIG    = os.path.join(RUTA_DATOS, "dashboard_config.json")
RUTA_BOT_ON    = os.path.join(RUTA_DATOS, "bot_activo.json")
RUTA_ESTADO    = os.path.join(RUTA_DATOS, "estado_bot.json")

# ── COLORES ────────────────────────────────────────────────────────────────

BG         = "#0d1117"
BG_CARD    = "#161b22"
BG_CARD2   = "#1c2128"
BORDER     = "#30363d"
TEXT       = "#e6edf3"
TEXT_MUTED = "#8b949e"
GREEN      = "#3fb950"
RED        = "#f85149"
BLUE       = "#58a6ff"
YELLOW     = "#d29922"
PURPLE     = "#bc8cff"

FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"

# ── HELPERS ────────────────────────────────────────────────────────────────

DEFAULTS_CONFIG = {
    "execution_mode":                "paper",
    "real_caucion_enabled":          False,
    "real_caucion_canary_mode":      True,
    "real_caucion_canary_amount_ars": 20000.0,
    "real_caucion_max_monto_ars":    20000.0,
    "umbral_caucion":                20.0,
    "max_capital_caucion_pct":       70.0,
    "ganancia_minima_caucion_pct":   1.5,
}


def leer_config():
    cfg = {}
    if os.path.exists(RUTA_CONFIG):
        try:
            with open(RUTA_CONFIG, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    for k, v in DEFAULTS_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def guardar_config(cfg):
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def leer_estado_bot():
    try:
        if os.path.exists(RUTA_ESTADO):
            with open(RUTA_ESTADO, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def bot_activo():
    try:
        if os.path.exists(RUTA_BOT_ON):
            with open(RUTA_BOT_ON, encoding="utf-8") as f:
                return json.load(f).get("activo", True)
    except Exception:
        pass
    return True


def toggle_bot(activo: bool):
    os.makedirs(RUTA_DATOS, exist_ok=True)
    with open(RUTA_BOT_ON, "w", encoding="utf-8") as f:
        json.dump({"activo": activo, "ts": datetime.now().isoformat()}, f)


def query_db(sql, params=()):
    if not os.path.exists(RUTA_DB):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(RUTA_DB)
        df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def fmt_ars(v):
    try:
        return f"ARS {float(v):,.2f}"
    except Exception:
        return "—"


def fmt_pct(v, decimals=2):
    try:
        return f"{float(v):.{decimals}f}%"
    except Exception:
        return "—"


# ── COMPONENTES UI ─────────────────────────────────────────────────────────

def card(children, style_extra=None):
    s = {
        "background": BG_CARD,
        "border": f"1px solid {BORDER}",
        "borderRadius": "8px",
        "padding": "20px",
        "marginBottom": "16px",
    }
    if style_extra:
        s.update(style_extra)
    return html.Div(children, style=s)


def badge(text, color=BLUE):
    return html.Span(text, style={
        "background": color + "22",
        "color": color,
        "border": f"1px solid {color}44",
        "borderRadius": "4px",
        "padding": "2px 8px",
        "fontSize": "12px",
        "fontWeight": "600",
        "marginLeft": "8px",
    })


def metric_card(label, value, sub=None, color=TEXT, wide=False):
    return html.Div([
        html.Div(label, style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "4px"}),
        html.Div(value, style={"color": color, "fontSize": "24px", "fontWeight": "700"}),
        html.Div(sub, style={"color": TEXT_MUTED, "fontSize": "12px", "marginTop": "4px"}) if sub else None,
    ], style={
        "background": BG_CARD,
        "border": f"1px solid {BORDER}",
        "borderRadius": "8px",
        "padding": "16px 20px",
        "flex": "2" if wide else "1",
        "minWidth": "140px",
    })


def section_title(text):
    return html.H3(text, style={
        "color": TEXT,
        "fontSize": "14px",
        "fontWeight": "600",
        "letterSpacing": "0.05em",
        "textTransform": "uppercase",
        "marginBottom": "12px",
        "marginTop": "0",
        "color": TEXT_MUTED,
    })


# ── LAYOUT ─────────────────────────────────────────────────────────────────

app = Dash(
    __name__,
    title="Bot Cauciones IOL",
    update_title=None,
    suppress_callback_exceptions=True,
)

app.layout = html.Div([
    dcc.Interval(id="intervalo", interval=30_000, n_intervals=0),

    # Header
    html.Div([
        html.Div([
            html.Span("●", id="estado-dot", style={"color": TEXT_MUTED, "marginRight": "8px", "fontSize": "10px"}),
            html.Span("Bot Cauciones IOL", style={"color": TEXT, "fontWeight": "700", "fontSize": "18px"}),
            html.Span(id="header-modo", style={"color": TEXT_MUTED, "fontSize": "13px", "marginLeft": "12px"}),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div(id="header-timestamp", style={"color": TEXT_MUTED, "fontSize": "12px"}),
    ], style={
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
        "padding": "16px 24px",
        "borderBottom": f"1px solid {BORDER}",
        "background": BG_CARD,
    }),

    # Métricas rápidas
    html.Div(id="metricas-rapidas", style={
        "display": "flex",
        "gap": "12px",
        "padding": "16px 24px",
        "flexWrap": "wrap",
    }),

    # Tabs
    dcc.Tabs(id="tabs", value="tasas", children=[
        dcc.Tab(label="TASAS EN VIVO", value="tasas"),
        dcc.Tab(label="OPERACIONES",   value="operaciones"),
        dcc.Tab(label="SEÑALES",       value="seniales"),
        dcc.Tab(label="CONFIG",        value="config"),
    ], style={"borderBottom": f"1px solid {BORDER}"},
    colors={"border": BORDER, "primary": BLUE, "background": BG_CARD}),

    html.Div(id="tab-contenido", style={"padding": "24px"}),

], style={"background": BG, "minHeight": "100vh", "fontFamily": FONT, "color": TEXT})


# ── CALLBACKS ──────────────────────────────────────────────────────────────

@app.callback(
    Output("metricas-rapidas",  "children"),
    Output("header-timestamp",  "children"),
    Output("header-modo",       "children"),
    Output("estado-dot",        "style"),
    Input("intervalo",          "n_intervals"),
)
def actualizar_header(n):
    estado = leer_estado_bot()
    cfg    = leer_config()
    ts_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    mode   = cfg.get("execution_mode", "paper").upper()
    activo = bot_activo()

    # Color del punto según estado del bot
    estado_str = estado.get("estado", "?")
    dot_color  = GREEN if estado_str == "corriendo" else (YELLOW if estado_str in ("cerrado", "cauciones_cerradas") else RED)
    dot_style  = {"color": dot_color, "marginRight": "8px", "fontSize": "10px"}

    capital   = capital_disponible()
    ciclos    = estado.get("ciclos", 0)
    seniales  = estado.get("seniales_hoy", 0)
    ganancias = estado.get("ganancias_hoy", 0.0)

    modo_badge_color = RED if mode == "REAL" else BLUE
    header_modo = html.Span([
        badge(mode, modo_badge_color),
        badge("ACTIVO" if activo else "APAGADO", GREEN if activo else RED),
    ])

    metricas = html.Div([
        metric_card("Capital disponible", fmt_ars(capital), color=GREEN),
        metric_card("Ganancia hoy",       fmt_ars(ganancias), color=GREEN if ganancias >= 0 else RED),
        metric_card("Señales hoy",        str(seniales)),
        metric_card("Ciclos ejecutados",  str(ciclos)),
        metric_card("Estado bot",         estado_str.replace("_", " ").upper(),
                    color=GREEN if estado_str == "corriendo" else YELLOW),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "width": "100%"})

    return metricas, ts_str, header_modo, dot_style


@app.callback(
    Output("tab-contenido", "children"),
    Input("tabs", "value"),
    Input("intervalo", "n_intervals"),
)
def renderizar_tab(tab, n):
    if tab == "tasas":
        return _tab_tasas()
    elif tab == "operaciones":
        return _tab_operaciones()
    elif tab == "seniales":
        return _tab_seniales()
    elif tab == "config":
        return _tab_config()
    return html.Div("Tab no encontrado")


# ── TAB: TASAS EN VIVO ─────────────────────────────────────────────────────

def _tab_tasas():
    # Tasas actuales por plazo — tabla: cauciones (fecha_hora, plazo_dias, tasa_anual)
    plazos = [1, 2, 3, 7]
    cards_tasas = []
    for plazo in plazos:
        df = query_db(
            "SELECT tasa_anual, fecha_hora FROM cauciones WHERE plazo_dias=? ORDER BY fecha_hora DESC LIMIT 1",
            (plazo,)
        )
        if df.empty:
            tna_str = "Sin datos"
            color   = TEXT_MUTED
            sub     = "—"
        else:
            tna = float(df.iloc[0]["tasa_anual"])
            tna_str = f"{tna:.2f}%"
            color   = GREEN if tna > 80 else (BLUE if tna > 50 else TEXT)
            ts  = str(df.iloc[0].get("fecha_hora", ""))
            sub = f"Último dato: {ts[:16] if ts else '—'}"

        cards_tasas.append(
            html.Div([
                html.Div(f"{plazo}D", style={"color": TEXT_MUTED, "fontSize": "12px", "fontWeight": "600"}),
                html.Div(tna_str, style={"color": color, "fontSize": "28px", "fontWeight": "700", "margin": "4px 0"}),
                html.Div("TNA", style={"color": TEXT_MUTED, "fontSize": "11px"}),
                html.Div(sub, style={"color": TEXT_MUTED, "fontSize": "11px", "marginTop": "8px"}),
            ], style={
                "background": BG_CARD,
                "border": f"1px solid {BORDER}",
                "borderRadius": "8px",
                "padding": "20px",
                "flex": "1",
                "minWidth": "130px",
                "textAlign": "center",
            })
        )

    # Histórico de tasas (últimos 7 días) — tabla: cauciones
    df_hist = query_db("""
        SELECT plazo_dias, tasa_anual, fecha_hora
        FROM cauciones
        WHERE fecha_hora >= datetime('now', '-7 days')
        ORDER BY fecha_hora ASC
    """)

    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_CARD2,
        font={"color": TEXT, "family": FONT, "size": 12},
        margin={"t": 20, "b": 40, "l": 50, "r": 20},
        legend={"bgcolor": "rgba(0,0,0,0)", "bordercolor": BORDER},
        xaxis={"gridcolor": BORDER, "linecolor": BORDER},
        yaxis={"gridcolor": BORDER, "linecolor": BORDER, "title": "TNA (%)"},
        height=320,
    )

    colores_plazo = {1: BLUE, 2: GREEN, 3: YELLOW, 7: PURPLE}
    if not df_hist.empty:
        df_hist["fecha_hora"] = pd.to_datetime(df_hist["fecha_hora"], errors="coerce")
        for plazo, color in colores_plazo.items():
            sub = df_hist[df_hist["plazo_dias"] == plazo].dropna(subset=["fecha_hora"])
            if not sub.empty:
                fig.add_trace(go.Scatter(
                    x=sub["fecha_hora"], y=sub["tasa_anual"],
                    mode="lines+markers",
                    name=f"{plazo}D",
                    line={"color": color, "width": 2},
                    marker={"size": 4},
                ))
    else:
        fig.add_annotation(
            text="Sin datos históricos aún",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font={"color": TEXT_MUTED, "size": 14},
        )

    return html.Div([
        section_title("Tasas por plazo — ahora"),
        html.Div(cards_tasas, style={"display": "flex", "gap": "12px", "marginBottom": "24px", "flexWrap": "wrap"}),
        card([
            section_title("Histórico últimos 7 días"),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ]),
    ])


# ── TAB: OPERACIONES ──────────────────────────────────────────────────────

def _tab_operaciones():
    secciones = []

    # Cauciones REALES activas — tabla: cauciones_ordenes_real
    df_real = query_db("""
        SELECT ciclo_id, plazo_dias, tna_objetivo, monto_objetivo,
               estado, timestamp, broker_order_id
        FROM cauciones_ordenes_real
        WHERE estado IN ('COLOCADA','CONFIRMADA','FILLED','PENDIENTE')
        ORDER BY timestamp DESC
        LIMIT 20
    """)

    filas_real = []
    for _, row in df_real.iterrows():
        ts    = str(row.get("timestamp", ""))[:16]
        plazo = int(row.get("plazo_dias", 1) or 1)
        try:
            devolucion = (datetime.fromisoformat(ts) + timedelta(days=plazo)).strftime("%d/%m/%Y")
        except Exception:
            devolucion = "?"
        monto  = float(row.get("monto_objetivo", 0) or 0)
        tna    = float(row.get("tna_objetivo", 0) or 0)
        gan    = monto * (tna / 100) * (plazo / 365)
        estado = str(row.get("estado", ""))
        filas_real.append(html.Tr([
            html.Td(ts,            style={"color": TEXT_MUTED, "padding": "8px 12px"}),
            html.Td(f"{plazo}D",   style={"padding": "8px 12px"}),
            html.Td(fmt_ars(monto),style={"padding": "8px 12px"}),
            html.Td(fmt_pct(tna),  style={"padding": "8px 12px"}),
            html.Td(fmt_ars(gan),  style={"color": GREEN, "padding": "8px 12px"}),
            html.Td(devolucion,    style={"color": BLUE, "padding": "8px 12px"}),
            html.Td(badge(estado, GREEN), style={"padding": "8px 12px"}),
        ]))

    tabla_real = html.Table([
        html.Thead(html.Tr([
            html.Th(h, style={"color": TEXT_MUTED, "padding": "8px 12px", "textAlign": "left", "fontWeight": "600", "fontSize": "12px"})
            for h in ["Fecha", "Plazo", "Monto", "TNA", "Ganancia est.", "Devolución", "Estado"]
        ])),
        html.Tbody(filas_real if filas_real else [
            html.Tr([html.Td("Sin cauciones activas", colSpan=7, style={"color": TEXT_MUTED, "padding": "16px 12px", "textAlign": "center"})])
        ]),
    ], style={"width": "100%", "borderCollapse": "collapse"})

    secciones.append(card([
        section_title("Cauciones reales activas"),
        tabla_real,
    ]))

    # Alerta capital insuficiente
    df_sin_cap = query_db("""
        SELECT COUNT(*) as n FROM seniales
        WHERE tiene_senal=1
          AND timestamp >= datetime('now', '-24 hours')
          AND NOT EXISTS (
              SELECT 1 FROM cauciones_ordenes_real r
              WHERE r.ciclo_id LIKE '%' || substr(seniales.timestamp,1,10) || '%'
          )
    """)
    n_perdidas = int(df_sin_cap.iloc[0]["n"]) if not df_sin_cap.empty else 0
    if n_perdidas > 0:
        secciones.append(html.Div([
            html.Span("⚠", style={"fontSize": "16px", "marginRight": "8px"}),
            html.Span(f"{n_perdidas} señal(es) en las últimas 24h no pudieron ejecutarse — verificar capital disponible"),
        ], style={
            "background": YELLOW + "22",
            "border": f"1px solid {YELLOW}44",
            "borderRadius": "8px",
            "padding": "12px 16px",
            "color": YELLOW,
            "marginBottom": "16px",
        }))

    # Operaciones PAPER recientes — tabla: cauciones_simuladas (tiene_senal=1)
    df_paper = query_db("""
        SELECT timestamp, plazo_dias, tna_mercado, capital_usado,
               ganancia_neta, estado
        FROM cauciones_simuladas
        WHERE tiene_senal = 1
        ORDER BY timestamp DESC
        LIMIT 20
    """)

    filas_paper = []
    for _, row in df_paper.iterrows():
        fecha  = str(row.get("timestamp", ""))[:16]
        plazo  = int(row.get("plazo_dias", 1) or 1)
        monto  = float(row.get("capital_usado", 0) or 0)
        tna    = float(row.get("tna_mercado", 0) or 0)
        gan    = float(row.get("ganancia_neta", 0) or 0)
        estado = str(row.get("estado", "SIMULADA"))
        filas_paper.append(html.Tr([
            html.Td(fecha,           style={"color": TEXT_MUTED, "padding": "8px 12px"}),
            html.Td(f"{plazo}D",     style={"padding": "8px 12px"}),
            html.Td(fmt_ars(monto),  style={"padding": "8px 12px"}),
            html.Td(fmt_pct(tna),    style={"padding": "8px 12px"}),
            html.Td(fmt_ars(gan),    style={"color": GREEN, "padding": "8px 12px"}),
            html.Td(badge(estado, BLUE), style={"padding": "8px 12px"}),
        ]))

    tabla_paper = html.Table([
        html.Thead(html.Tr([
            html.Th(h, style={"color": TEXT_MUTED, "padding": "8px 12px", "textAlign": "left", "fontWeight": "600", "fontSize": "12px"})
            for h in ["Fecha", "Plazo", "Monto", "TNA", "Ganancia est.", "Estado"]
        ])),
        html.Tbody(filas_paper if filas_paper else [
            html.Tr([html.Td("Sin operaciones paper recientes", colSpan=6, style={"color": TEXT_MUTED, "padding": "16px 12px", "textAlign": "center"})])
        ]),
    ], style={"width": "100%", "borderCollapse": "collapse"})

    secciones.append(card([
        section_title("Operaciones paper — últimas 20"),
        tabla_paper,
    ]))

    return html.Div(secciones)


# ── TAB: SEÑALES ──────────────────────────────────────────────────────────

def _tab_seniales():
    # Señales — tabla: cauciones_simuladas
    df = query_db("""
        SELECT timestamp, plazo_dias, tna_mercado, tiene_senal,
               promedio_historico, desviacion_pct
        FROM cauciones_simuladas
        WHERE timestamp >= datetime('now', '-30 days')
        ORDER BY timestamp DESC
        LIMIT 200
    """)

    fig_scatter = go.Figure()
    fig_scatter.update_layout(
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_CARD2,
        font={"color": TEXT, "family": FONT, "size": 12},
        margin={"t": 20, "b": 40, "l": 50, "r": 20},
        xaxis={"gridcolor": BORDER, "linecolor": BORDER, "title": "Fecha"},
        yaxis={"gridcolor": BORDER, "linecolor": BORDER, "title": "TNA (%)"},
        height=300,
        showlegend=True,
        legend={"bgcolor": "rgba(0,0,0,0)"},
    )

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        sin_senal = df[df["tiene_senal"] == 0]
        con_senal = df[df["tiene_senal"] == 1]

        if not sin_senal.empty:
            fig_scatter.add_trace(go.Scatter(
                x=sin_senal["timestamp"], y=sin_senal["tna_mercado"],
                mode="markers", name="Sin señal",
                marker={"color": TEXT_MUTED, "size": 5, "opacity": 0.5},
            ))
        if not con_senal.empty:
            fig_scatter.add_trace(go.Scatter(
                x=con_senal["timestamp"], y=con_senal["tna_mercado"],
                mode="markers", name="SEÑAL",
                marker={"color": GREEN, "size": 10, "symbol": "star"},
                text=[f"Plazo {p}D — {t:.2f}%" for p, t in zip(con_senal["plazo_dias"], con_senal["tna_mercado"])],
                hoverinfo="text+x",
            ))
    else:
        fig_scatter.add_annotation(
            text="Sin señales registradas aún",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font={"color": TEXT_MUTED, "size": 14},
        )

    # Tabla de señales
    filas = []
    if not df.empty:
        for _, row in df.head(50).iterrows():
            ts     = str(row.get("timestamp", ""))[:16]
            plazo  = row.get("plazo_dias", "?")
            tna    = row.get("tna_mercado", 0)
            senal  = bool(row.get("tiene_senal", 0))
            prom   = row.get("promedio_historico", "")
            desvio = row.get("desviacion_pct", "")
            filas.append(html.Tr([
                html.Td(ts,                style={"color": TEXT_MUTED, "padding": "6px 12px"}),
                html.Td(f"{plazo}D",       style={"padding": "6px 12px"}),
                html.Td(fmt_pct(tna),      style={"color": BLUE, "padding": "6px 12px"}),
                html.Td(badge("SEÑAL", GREEN) if senal else badge("—", TEXT_MUTED), style={"padding": "6px 12px"}),
                html.Td(fmt_pct(prom) if prom else "—", style={"color": TEXT_MUTED, "padding": "6px 12px"}),
                html.Td(fmt_pct(desvio) if desvio else "—", style={"color": TEXT_MUTED, "padding": "6px 12px"}),
            ]))

    tabla = html.Table([
        html.Thead(html.Tr([
            html.Th(h, style={"color": TEXT_MUTED, "padding": "8px 12px", "textAlign": "left", "fontWeight": "600", "fontSize": "12px"})
            for h in ["Fecha", "Plazo", "TNA", "Estado", "Prom. histórico", "Desvío %"]
        ])),
        html.Tbody(filas if filas else [
            html.Tr([html.Td("Sin datos", colSpan=5, style={"color": TEXT_MUTED, "padding": "16px 12px", "textAlign": "center"})])
        ]),
    ], style={"width": "100%", "borderCollapse": "collapse"})

    return html.Div([
        card([
            section_title("Señales — últimos 30 días"),
            dcc.Graph(figure=fig_scatter, config={"displayModeBar": False}),
        ]),
        card([
            section_title("Historial de señales"),
            tabla,
        ]),
    ])


# ── TAB: CONFIG ───────────────────────────────────────────────────────────

def _tab_config():
    cfg    = leer_config()
    activo = bot_activo()
    estado = leer_estado_bot()

    mercado_info = {}
    try:
        mercado_info = estado_mercado()
    except Exception:
        pass

    modo      = cfg.get("execution_mode", "paper")
    real_en   = bool(cfg.get("real_caucion_enabled", False))
    canary    = bool(cfg.get("real_caucion_canary_mode", True))

    return html.Div([
        # Estado del bot
        card([
            section_title("Control del bot"),
            html.Div([
                html.Div([
                    html.Div("Estado actual", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Div(
                        estado.get("estado", "?").replace("_", " ").upper(),
                        style={"color": GREEN if estado.get("estado") == "corriendo" else YELLOW,
                               "fontSize": "18px", "fontWeight": "700", "marginTop": "4px"},
                    ),
                ], style={"flex": "1"}),
                html.Div([
                    html.Div("Mercado", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Div(
                        mercado_info.get("modo", "?").upper(),
                        style={"color": TEXT, "fontSize": "18px", "fontWeight": "700", "marginTop": "4px"},
                    ),
                ], style={"flex": "1"}),
                html.Div([
                    html.Div("Hora Argentina", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Div(
                        mercado_info.get("hora_arg", "?"),
                        style={"color": TEXT, "fontSize": "18px", "fontWeight": "700", "marginTop": "4px"},
                    ),
                ], style={"flex": "1"}),
            ], style={"display": "flex", "gap": "24px", "marginBottom": "20px"}),

            html.Div([
                html.Button(
                    "⏹ APAGAR BOT" if activo else "▶ ENCENDER BOT",
                    id="btn-toggle-bot",
                    n_clicks=0,
                    style={
                        "background": RED + "22" if activo else GREEN + "22",
                        "color": RED if activo else GREEN,
                        "border": f"1px solid {RED if activo else GREEN}44",
                        "borderRadius": "6px",
                        "padding": "10px 20px",
                        "cursor": "pointer",
                        "fontFamily": FONT,
                        "fontWeight": "600",
                        "fontSize": "13px",
                    }
                ),
                html.Span(id="msg-toggle-bot", style={"color": TEXT_MUTED, "fontSize": "12px", "marginLeft": "12px"}),
            ]),
        ]),

        # Modo de ejecución
        card([
            section_title("Modo de ejecución"),
            html.Div([
                html.Div("Modo activo:", style={"color": TEXT_MUTED, "fontSize": "13px", "marginBottom": "8px"}),
                dcc.Dropdown(
                    id="dropdown-modo",
                    options=[
                        {"label": "Paper (simulado)", "value": "paper"},
                        {"label": "Real (dinero real)", "value": "real"},
                    ],
                    value=modo,
                    clearable=False,
                    style={"maxWidth": "280px"},
                ),
                html.Div(id="msg-modo", style={"color": TEXT_MUTED, "fontSize": "12px", "marginTop": "8px"}),
            ]),
            html.Div([
                html.Div(
                    [
                        html.Span("⚠ Modo REAL activo — ", style={"fontWeight": "700"}),
                        html.Span("las órdenes se envían a IOL con dinero real."),
                    ],
                    style={
                        "background": RED + "22",
                        "border": f"1px solid {RED}44",
                        "borderRadius": "6px",
                        "padding": "10px 14px",
                        "color": RED,
                        "fontSize": "13px",
                        "marginTop": "12px",
                    }
                ) if modo == "real" and real_en else None,
            ]),
        ]),

        # Parámetros activos
        card([
            section_title("Parámetros activos"),
            html.Div([
                _param_row("Umbral señal", fmt_pct(cfg.get("umbral_caucion", 20))),
                _param_row("Capital máx. por operación", fmt_pct(cfg.get("max_capital_caucion_pct", 70))),
                _param_row("Ganancia mínima", fmt_pct(cfg.get("ganancia_minima_caucion_pct", 1.5))),
                _param_row("Modo canary", "SÍ" if canary else "NO"),
                _param_row("Monto canary", fmt_ars(cfg.get("real_caucion_canary_amount_ars", 1000))),
                _param_row("Monto máximo real", fmt_ars(cfg.get("real_caucion_max_monto_ars", 5000))),
                _param_row("Ejecución real habilitada", "SÍ" if real_en else "NO",
                           color=GREEN if real_en else TEXT_MUTED),
            ]),
        ]),
    ])


def _param_row(label, value, color=TEXT):
    return html.Div([
        html.Span(label, style={"color": TEXT_MUTED, "fontSize": "13px"}),
        html.Span(value, style={"color": color, "fontSize": "13px", "fontWeight": "600"}),
    ], style={
        "display": "flex",
        "justifyContent": "space-between",
        "padding": "8px 0",
        "borderBottom": f"1px solid {BORDER}",
    })


# ── CALLBACKS CONFIG ───────────────────────────────────────────────────────

@app.callback(
    Output("msg-toggle-bot", "children"),
    Input("btn-toggle-bot", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_bot_click(n):
    if not n:
        return ""
    activo = bot_activo()
    toggle_bot(not activo)
    return "Bot apagado." if activo else "Bot encendido."


@app.callback(
    Output("msg-modo", "children"),
    Input("dropdown-modo", "value"),
    prevent_initial_call=True,
)
def cambiar_modo(value):
    if not value:
        return ""
    cfg = leer_config()
    cfg["execution_mode"] = value
    guardar_config(cfg)
    return f"Modo guardado: {value.upper()}"


# ── MAIN ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
