"""
dashboard.py - Centro de control del bot de arbitraje.
VERSION DEFINITIVA - todos los fixes aplicados.
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
import pandas as pd

from dash import Dash, html, dcc, Input, Output, State, callback_context
import plotly.graph_objects as go

from config import (
    RUTA_DATOS,
    NOMBRE_DB,
    CEDEARS,
    MAX_EDAD_CCL_MIN,
    MAX_EDAD_PRECIOS_NYSE_MIN,
    MAX_NEGATIVAS_CONSECUTIVAS,
    MAX_CAPITAL_POR_DIA,
)
from mercado import estado_mercado
from ejecutor_paper import capital_base_actual

try:
    from detector_tickers_corruptos import get_alertas_ticker
    DETECTOR_TICKER_OK = True
except Exception:
    DETECTOR_TICKER_OK = False
    def get_alertas_ticker(): return []

RUTA_DB            = os.path.join(RUTA_DATOS, NOMBRE_DB)
RUTA_CONFIG        = os.path.join(RUTA_DATOS, "dashboard_config.json")
RUTA_ALERTAS       = os.path.join(RUTA_DATOS, "alertas_perdidas.json")
RUTA_BOT_ON        = os.path.join(RUTA_DATOS, "bot_activo.json")
RUTA_ALERTAS_RATIO = os.path.join(RUTA_DATOS, "alertas_ratios.json")
RUTA_ESTADO_BOT    = os.path.join(RUTA_DATOS, "estado_bot.json")

CAPITAL_INICIAL = 40000.0

DEFAULTS_CONFIG = {
    "ganancia_minima_caucion_pct":   1.5,
    "ganancia_minima_arbitraje_pct": 2.0,
    "umbral_caucion":                20.0,
    "spread_minimo_arbitraje":       3.0,
    "max_capital_arbitraje_pct":     30.0,
    "max_capital_caucion_pct":       70.0,
    "comision_iol_pct":              0.6,
    "slippage_pct":                  0.3,
    "alertas_perdidas_consecutivas": 3,
    "modo_forzado_bot":              "auto",
    "execution_mode":                "paper",
    "real_caucion_enabled":          False,
    "real_caucion_backend":          "web",
    "real_caucion_canary_mode":      True,
    "real_caucion_canary_amount_ars": 1000.0,
    "real_caucion_max_monto_ars":    5000.0,
    "real_caucion_browser":          "edge",
    "real_caucion_headless":         False,
}

C = {
    "bg":     "#07090f", "panel":  "#0d1117", "card":   "#0d1520",
    "border": "#1a2a3a", "accent": "#00c8ff", "green":  "#00e676",
    "red":    "#ff1744", "yellow": "#ffc400", "purple": "#b388ff",
    "text":   "#cdd9e5", "sub":    "#7f97ab", "on":     "#00e676",
    "off":    "#ff1744", "orange": "#ff9800",
}
FONT = "'Courier New', 'Lucida Console', monospace"


#    HELPERS                                                       

def cargar_config():
    if os.path.exists(RUTA_CONFIG):
        cfg = json.load(open(RUTA_CONFIG))
        for k, v in DEFAULTS_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULTS_CONFIG.copy()

def guardar_config(cfg):
    json.dump(cfg, open(RUTA_CONFIG, "w"), indent=2)

def get_modo_forzado():
    cfg = cargar_config()
    modo = str(cfg.get("modo_forzado_bot", "auto")).lower().strip()
    if modo not in ("auto", "arbitraje", "mixto", "caucion"):
        return "auto"
    return modo

def get_execution_mode():
    cfg = cargar_config()
    mode = str(cfg.get("execution_mode", "paper")).lower().strip()
    if mode not in ("paper", "real"):
        return "paper"
    return mode

def get_real_caucion_enabled():
    cfg = cargar_config()
    return bool(cfg.get("real_caucion_enabled", False))

def bot_activo():
    if os.path.exists(RUTA_BOT_ON):
        try:
            return json.load(open(RUTA_BOT_ON)).get("activo", True)
        except Exception:
            pass
    return True

def set_bot_activo(val):
    json.dump({"activo": val, "ts": datetime.now().isoformat()}, open(RUTA_BOT_ON, "w"))

def get_alertas():
    if not os.path.exists(RUTA_ALERTAS): return []
    try: return json.load(open(RUTA_ALERTAS))
    except Exception: return []

def get_alertas_ratio():
    if not os.path.exists(RUTA_ALERTAS_RATIO): return []
    try: return [a for a in json.load(open(RUTA_ALERTAS_RATIO)) if a.get("estado") == "pendiente"]
    except Exception: return []

def get_estado_bot():
    if not os.path.exists(RUTA_ESTADO_BOT): return {}
    try: return json.load(open(RUTA_ESTADO_BOT))
    except Exception: return {}

def confirmar_ratio_dashboard(simbolo, confirmar):
    if not os.path.exists(RUTA_ALERTAS_RATIO): return
    try:
        alertas = json.load(open(RUTA_ALERTAS_RATIO))
        for a in alertas:
            if a["simbolo"] == simbolo and a["estado"] == "pendiente":
                a["estado"] = "confirmado" if confirmar else "rechazado"
                a["confirmado_en"] = datetime.now().isoformat()
                if confirmar:
                    ruta = os.path.join(RUTA_DATOS, "ratios_comafi.json")
                    if os.path.exists(ruta):
                        datos = json.load(open(ruta))
                        datos["ratios"][simbolo] = a["ratio_nuevo"]
                        json.dump(datos, open(ruta, "w"), indent=2)
                break
        json.dump(alertas, open(RUTA_ALERTAS_RATIO, "w"), indent=2)
    except Exception: pass

def conectar():
    return sqlite3.connect(RUTA_DB)

def get_df(query):
    try:
        conn = conectar()
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def get_resumen():
    try:
        capital_base, fuente_capital = capital_base_actual()
        conn = conectar()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(ganancia_neta),0) FROM operaciones_paper")
        total, gan = c.fetchone()
        c.execute("SELECT COUNT(*), COALESCE(SUM(ganancia_neta),0) FROM operaciones_paper WHERE tipo='CAUCION'")
        tc, gc = c.fetchone()
        c.execute("SELECT COUNT(*), COALESCE(SUM(ganancia_neta),0) FROM operaciones_paper WHERE tipo='ARBITRAJE'")
        ta, ga = c.fetchone()
        c.execute("SELECT COALESCE(SUM(capital_usado),0) FROM operaciones_paper WHERE estado='ABIERTA'")
        comp = c.fetchone()[0]
        conn.close()
        return {"total":total,"gan":gan,"tc":tc,"gc":gc,"ta":ta,"ga":ga,
                "comp":comp,"disp":round(max(0.0, capital_base-comp),2),
                "cap_base": capital_base, "fuente_capital": fuente_capital}
    except Exception:
        return {"total":0,"gan":0,"tc":0,"gc":0,"ta":0,"ga":0,"comp":0,
                "disp":CAPITAL_INICIAL, "cap_base": CAPITAL_INICIAL, "fuente_capital": "FALLBACK_40000"}

def get_perdidas_consecutivas():
    try:
        conn = conectar()
        c = conn.cursor()
        c.execute("SELECT ganancia_neta FROM operaciones_paper ORDER BY timestamp DESC LIMIT 20")
        filas = c.fetchall()
        conn.close()
        count = 0
        for (g,) in filas:
            if g is not None and g < 0: count += 1
            else: break
        return count
    except Exception: return 0

def get_ultimo_ccl():
    try:
        conn = conectar()
        c = conn.cursor()
        c.execute("SELECT ccl_valor FROM ccl_historico ORDER BY timestamp DESC LIMIT 1")
        fila = c.fetchone()
        conn.close()
        return fila[0] if fila else None
    except Exception: return None


def edad_min_ultimo_registro(tabla, campo_ts="timestamp"):
    try:
        conn = conectar()
        c = conn.cursor()
        c.execute(f"SELECT {campo_ts} FROM {tabla} ORDER BY {campo_ts} DESC LIMIT 1")
        fila = c.fetchone()
        conn.close()
        if not fila or not fila[0]:
            return None
        ts = datetime.fromisoformat(str(fila[0]))
        return max(0.0, (datetime.now() - ts).total_seconds() / 60.0)
    except Exception:
        return None

def get_precios_nyse():
    try:
        conn = conectar()
        c = conn.cursor()
        c.execute("""
            SELECT p1.simbolo, p1.precio_usd
            FROM precios_nyse p1
            INNER JOIN (SELECT simbolo, MAX(timestamp) as ts FROM precios_nyse GROUP BY simbolo) p2
            ON p1.simbolo=p2.simbolo AND p1.timestamp=p2.ts
        """)
        filas = c.fetchall()
        conn.close()
        return {row[0]: row[1] for row in filas}
    except Exception: return {}

def get_simulaciones():
    try:
        conn = conectar()
        c = conn.cursor()
        # Columnas que sabemos que existen siempre
        c.execute("""
            SELECT * FROM simulaciones_operaciones
            ORDER BY timestamp DESC LIMIT 50
        """)
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, row)) for row in c.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def filtrar_df_periodo(df, columna_fecha, periodo="today"):
    if df is None or df.empty or columna_fecha not in df.columns:
        return df
    tmp = df.copy()
    tmp[columna_fecha] = pd.to_datetime(tmp[columna_fecha], errors="coerce")
    tmp = tmp.dropna(subset=[columna_fecha])
    if tmp.empty:
        return tmp
    ahora = datetime.now()
    inicio_hoy = datetime(ahora.year, ahora.month, ahora.day)
    if periodo == "today":
        return tmp[tmp[columna_fecha] >= inicio_hoy]
    if periodo == "7d":
        return tmp[tmp[columna_fecha] >= (ahora - timedelta(days=7))]
    if periodo == "30d":
        return tmp[tmp[columna_fecha] >= (ahora - timedelta(days=30))]
    return tmp


def titulo_periodo(periodo):
    return {
        "today": "Hoy",
        "7d": "7 dias",
        "30d": "30 dias",
        "all": "Global",
    }.get(periodo, "Hoy")


def _en_periodo_fecha(dt, periodo="today"):
    if dt is None:
        return False
    ahora = datetime.now()
    inicio_hoy = datetime(ahora.year, ahora.month, ahora.day)
    if periodo == "today":
        return dt >= inicio_hoy
    if periodo == "7d":
        return dt >= (ahora - timedelta(days=7))
    if periodo == "30d":
        return dt >= (ahora - timedelta(days=30))
    return True


#    COMPONENTES UI                                                

def label(txt):
    return html.Div(txt, style={
        "font-size":"10px","color":C["sub"],"letter-spacing":"2px",
        "text-transform":"uppercase","margin-bottom":"6px","font-family":FONT
    })

def card(children, border_color=None, padding="18px 20px", mb="10px"):
    return html.Div(children, style={
        "background":C["card"], "border":f"1px solid {border_color or C['border']}",
        "border-radius":"10px","padding":padding,"margin-bottom":mb,
        "box-shadow":"0 8px 24px rgba(0,0,0,0.22)",
    })

def stat_block(titulo, valor, color=None, small=False):
    return html.Div([
        html.Div(titulo, style={"font-size":"9px","color":C["sub"],"letter-spacing":"2px",
                                 "text-transform":"uppercase","font-family":FONT}),
        html.Div(valor, style={"font-size":"22px" if not small else "15px",
                                "color":color or C["text"],"font-weight":"bold",
                                "font-family":FONT,"margin-top":"2px"}),
    ], style={"padding":"12px 16px","background":C["panel"],
               "border-radius":"5px","border":f"1px solid {C['border']}"})

def input_field(id_, value, step=0.1, min_=0, max_=100):
    return dcc.Input(id=id_, type="number", value=value, step=step, min=min_, max=max_,
                     style={"width":"100%","background":C["bg"],"color":C["text"],
                            "border":f"1px solid {C['border']}","border-radius":"4px",
                            "padding":"7px 10px","font-family":FONT,"font-size":"13px",
                            "box-sizing":"border-box"})

def tabla(cols, filas_data, col_colors=None, max_rows=None):
    if max_rows: filas_data = filas_data[:max_rows]
    thead = html.Thead(html.Tr([
        html.Th(c, style={"color":C["sub"],"font-size":"9px","padding":"6px 10px",
                           "text-align":"left","border-bottom":f"1px solid {C['border']}",
                           "letter-spacing":"1px","font-family":FONT})
        for c in cols
    ]))
    filas = []
    for row in filas_data:
        celdas = []
        for i, val in enumerate(row):
            color = col_colors[i](val) if col_colors and i < len(col_colors) and col_colors[i] else C["text"]
            celdas.append(html.Td(str(val), style={
                "color":color,"font-size":"11px","padding":"5px 10px",
                "border-bottom":"1px solid rgba(26,42,58,0.4)","font-family":FONT
            }))
        filas.append(html.Tr(celdas))
    return html.Table([thead, html.Tbody(filas)], style={"width":"100%","border-collapse":"collapse"})


#    ESTILOS TABS - definido ANTES del layout                      

def _tab_style():
    return {
        "style": {
            "background":C["panel"],"color":C["sub"],"border":f"1px solid {C['border']}",
            "font-family":FONT,"font-size":"11px","padding":"8px 12px",
        },
        "selected_style": {
            "background":C["card"],"color":C["accent"],
            "border-top":f"2px solid {C['accent']}",
            "font-family":FONT,"font-size":"11px","padding":"8px 12px",
        },
    }


#    GRAFICOS HELPERS                                              

def _fig_layout(fig, ytitle="", height=220, rangeslider=False):
    xaxis = dict(showgrid=False, color=C["sub"])
    if rangeslider:
        xaxis["rangeslider"] = dict(visible=True, bgcolor=C["panel"], thickness=0.05)
    fig.update_layout(
        paper_bgcolor=C["card"], plot_bgcolor=C["card"],
        font=dict(color=C["text"], family=FONT),
        height=height, margin=dict(l=55,r=20,t=15,b=40),
        xaxis=xaxis,
        yaxis=dict(showgrid=True, gridcolor="rgba(26,42,58,0.33)", color=C["sub"],
                   title=ytitle, zeroline=True, zerolinecolor="rgba(26,42,58,0.4)"),
        showlegend=False, hovermode="x unified",
    )

def _fig_vacio(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                        showarrow=False, font=dict(color=C["sub"], size=12, family=FONT))
    fig.update_layout(paper_bgcolor=C["card"], plot_bgcolor=C["card"],
                       height=180, margin=dict(l=20,r=20,t=20,b=20))
    return fig

def _cfg_grafico():
    return {"scrollZoom":True,"displayModeBar":True,
            "modeBarButtonsToRemove":["lasso2d","select2d"],"displaylogo":False}


#    LAYOUT                                                        

app = Dash(__name__, title="Bot Arbitraje")

app.layout = html.Div([
    dcc.Interval(id="tick", interval=30_000, n_intervals=0),

    # HEADER
    html.Div([
        html.Div([
            html.Span("[ ] ", style={"color":C["accent"],"font-size":"18px"}),
            html.Span("BOT ARBITRAJE", style={"font-size":"17px","font-weight":"bold",
                                               "color":C["text"],"letter-spacing":"5px"}),
            html.Span(" / CENTRO DE CONTROL", style={"font-size":"10px","color":C["sub"],
                                                       "letter-spacing":"2px","margin-left":"8px"}),
        ], style={"display":"flex","align-items":"center"}),
        html.Div([
            html.Span(id="header-ciclo", style={"font-size":"10px","color":C["sub"],"margin-right":"16px"}),
            html.Span(id="header-nyse",  style={"font-size":"10px","color":C["purple"],"margin-right":"16px"}),
            html.Span(id="header-modo",  style={"font-size":"10px","color":C["yellow"],"margin-right":"20px"}),
            html.Span(id="header-hora",  style={"font-size":"12px","color":C["accent"]}),
        ], style={"display":"flex","align-items":"center"}),
    ], style={
        "display":"flex","justify-content":"space-between","align-items":"center",
        "padding":"14px 24px","background":C["panel"],
        "border-bottom":f"1px solid {C['border']}","font-family":FONT,
        "position":"sticky","top":"0","z-index":"100",
    }),

    # BODY
    html.Div([

        # COLUMNA IZQUIERDA
        html.Div([
            card([
                html.Div([
                    html.Div(id="mercado-info", style={"flex":"1"}),
                    html.Div([
                        html.Div(id="bot-estado-txt", style={"font-size":"12px","font-weight":"bold",
                                                              "font-family":FONT,"margin-bottom":"8px","text-align":"right"}),
                        dcc.Dropdown(
                            id="sel-modo-bot",
                            options=[
                                {"label": "AUTO", "value": "auto"},
                                {"label": "SOLO ARBITRAJE", "value": "arbitraje"},
                                {"label": "MIXTO", "value": "mixto"},
                                {"label": "SOLO CAUCIONES", "value": "caucion"},
                            ],
                            value=get_modo_forzado(),
                            clearable=False,
                            style={"width":"220px","margin-bottom":"8px","font-family":FONT,"font-size":"11px"},
                        ),
                        dcc.Dropdown(
                            id="sel-execution-mode",
                            options=[
                                {"label": "EJECUCION PAPER", "value": "paper"},
                                {"label": "EJECUCION REAL", "value": "real"},
                            ],
                            value=get_execution_mode(),
                            clearable=False,
                            style={"width":"220px","margin-bottom":"8px","font-family":FONT,"font-size":"11px"},
                        ),
                        dcc.Dropdown(
                            id="sel-real-caucion-enabled",
                            options=[
                                {"label": "REAL CAUCION OFF", "value": "off"},
                                {"label": "REAL CAUCION ON", "value": "on"},
                            ],
                            value="on" if get_real_caucion_enabled() else "off",
                            clearable=False,
                            style={"width":"220px","margin-bottom":"8px","font-family":FONT,"font-size":"11px"},
                        ),
                        html.Button("ON / OFF", id="btn-toggle-bot", n_clicks=0, style={
                            "background":C["accent"],"color":C["bg"],"border":"none","border-radius":"4px",
                            "padding":"8px 14px","font-weight":"bold","font-family":FONT,
                            "font-size":"10px","cursor":"pointer"
                        }),
                        html.Div(id="msg-modo-bot", style={"font-size":"10px","color":C["sub"],"margin-top":"6px"}),
                        html.Div(id="msg-execution-mode", style={"font-size":"10px","color":C["sub"],"margin-top":"4px"}),
                        html.Div(id="msg-real-caucion-enabled", style={"font-size":"10px","color":C["sub"],"margin-top":"4px"}),
                    ], style={"text-align":"right"}),
                ], style={"display":"flex","justify-content":"space-between","align-items":"flex-start"}),
            ], border_color=C["accent"]),

            html.Div(id="card-capital"),
            html.Div(id="card-riesgo-operativo"),
            html.Div(id="card-alerta-perdidas"),
            html.Div(id="card-alertas-tickers"),
            html.Div(id="card-alertas-oportunidades"),
            html.Div(id="card-alertas-ratio"),

            card([
                label("  Configuracion"),
                html.Div([
                    html.Div([label("Gan. min CAUCION (%)"),     input_field("inp-gcau",   None, 0.1, 0.5, 10)],  style={"margin-bottom":"8px"}),
                    html.Div([label("Gan. min ARBITRAJE (%)"),   input_field("inp-garb",   None, 0.1, 0.5, 10)],  style={"margin-bottom":"8px"}),
                    html.Div([label("Max capital CAUCION (%)"),   input_field("inp-maxcau", None, 5,   10,  100)], style={"margin-bottom":"8px"}),
                    html.Div([label("Max capital ARBITRAJE (%)"), input_field("inp-maxarb", None, 5,   5,   50)],  style={"margin-bottom":"8px"}),
                    html.Div([label("Umbral SENAL CAUCION (%)"),  input_field("inp-umbral", None, 1,   5,   100)], style={"margin-bottom":"8px"}),
                    html.Div([label("Spread min ARBITRAJE (%)"),  input_field("inp-spread", None, 0.5, 1,   20)],  style={"margin-bottom":"12px"}),
                    html.Button("GUARDAR", id="btn-guardar", n_clicks=0, style={
                        "background":C["accent"],"color":C["bg"],"border":"none","border-radius":"4px",
                        "padding":"9px 0","width":"100%","font-weight":"bold","letter-spacing":"2px",
                        "font-family":FONT,"font-size":"11px","cursor":"pointer","margin-top":"4px"
                    }),
                    html.Div(id="msg-config", style={"margin-top":"8px","font-size":"11px","color":C["green"],"font-family":FONT}),
                ]),
            ]),
        ], style={"width":"28%","padding":"0 8px"}),

        # COLUMNA DERECHA
        html.Div([
            card([
                html.Div([
                    html.Div([
                        label("Ventana temporal de graficos"),
                        dcc.Dropdown(
                            id="sel-periodo",
                            options=[
                                {"label":"HOY", "value":"today"},
                                {"label":"7 DIAS", "value":"7d"},
                                {"label":"30 DIAS", "value":"30d"},
                                {"label":"GLOBAL", "value":"all"},
                            ],
                            value="today",
                            clearable=False,
                            style={"width":"220px","font-family":FONT,"font-size":"11px"},
                        ),
                    ]),
                    html.Div(
                        "Por defecto se muestra HOY.",
                        style={"color":C["sub"],"font-size":"10px","font-family":FONT}
                    ),
                ], style={"display":"flex","justify-content":"space-between","align-items":"flex-end"})
            ], mb="8px"),
            dcc.Tabs(id="tabs", value="tab-live", children=[
                dcc.Tab(label="EN VIVO",      value="tab-live",      **_tab_style()),
                dcc.Tab(label="SPREADS",      value="tab-spreads",   **_tab_style()),
                dcc.Tab(label="SIM CAUCION",  value="tab-sims",      **_tab_style()),
                dcc.Tab(label="TASAS CAUCION", value="tab-cauciones", **_tab_style()),
                dcc.Tab(label="OPERACIONES",  value="tab-ops",       **_tab_style()),
                dcc.Tab(label="SENALES",      value="tab-senales",   **_tab_style()),
            ]),
            html.Div(id="tab-content"),
        ], style={"width":"72%","padding":"0 8px"}),

    ], style={"display":"flex","padding":"16px 16px","align-items":"flex-start"}),

], style={"background":C["bg"],"min-height":"100vh","font-family":FONT,"color":C["text"]})


#    CALLBACKS HEADER                                              

@app.callback(
    Output("header-hora","children"), Output("header-modo","children"),
    Output("header-ciclo","children"), Output("header-nyse","children"),
    Input("tick","n_intervals")
)
def tick_header(_):
    e   = estado_mercado()
    est = get_estado_bot()
    modo_forzado = get_modo_forzado()
    execution_mode = get_execution_mode()
    hora  = datetime.now().strftime("* %d/%m/%Y  %H:%M:%S")
    if modo_forzado == "auto":
        modo = f"BOT: {e['modo'].upper()} (AUTO) | EJEC: {execution_mode.upper()}"
    else:
        modo = f"BOT: {modo_forzado.upper()} (FORZADO) | EJEC: {execution_mode.upper()}"
    ciclo = f"CICLO #{est.get('ciclos','-')}  SENALES: {est.get('seniales_hoy',0)}" if est else ""
    nyse  = f"NYSE: {est.get('horario_nyse','-').upper()}" if est else "NYSE: -"
    return hora, modo, ciclo, nyse


@app.callback(
    Output("mercado-info","children"), Output("bot-estado-txt","children"), Output("bot-estado-txt","style"),
    Input("tick","n_intervals"), Input("btn-toggle-bot","n_clicks"), prevent_initial_call=False
)
def actualizar_mercado(_, n):
    ctx = callback_context
    activo = bot_activo()
    if ctx.triggered and ctx.triggered[0]["prop_id"] == "btn-toggle-bot.n_clicks" and n:
        activo = not activo
        set_bot_activo(activo)

    e   = estado_mercado()
    modo_forzado = get_modo_forzado()
    ccl = get_ultimo_ccl()
    color_mer = C["green"] if e["abierto"] else (C["yellow"] if e["cauciones_abiertas"] else C["red"])

    plazos_txt = []
    for p in e.get("plazos_disponibles", []):
        plazos_txt.append(
            html.Span(f" {p['plazo_habiles']}d->{p['fecha_vencimiento']}",
                      style={"color":C["yellow"],"font-size":"10px","font-family":FONT})
        )

    info = html.Div([
        label("Estado del mercado"),
        html.Div(e["estado"], style={"color":color_mer,"font-weight":"bold","font-size":"12px","font-family":FONT}),
        html.Div(f"Hora: {e['hora_arg']}", style={"color":C["sub"],"font-size":"10px","margin-top":"3px"}),
        html.Div(f"CCL: ${ccl:,.2f}" if ccl else "CCL: -",
                 style={"color":C["accent"],"font-size":"11px","margin-top":"3px","font-weight":"bold"}),
        html.Div(
            f"Modo bot: {modo_forzado.upper()} {'(forzado)' if modo_forzado != 'auto' else '(por horario)'}",
            style={"color":C["yellow"],"font-size":"10px","margin-top":"3px","font-family":FONT}
        ),
        html.Div([html.Span("Cauciones: ", style={"color":C["sub"],"font-size":"10px"})] + plazos_txt,
                 style={"margin-top":"3px","display":"flex","flex-wrap":"wrap"}),
    ])
    color_bot = C["on"] if activo else C["off"]
    txt_bot   = "* BOT ACTIVO" if activo else "* BOT APAGADO"
    estilo    = {"color":color_bot,"font-weight":"bold","font-size":"12px",
                 "font-family":FONT,"margin-bottom":"8px","text-align":"right"}
    return info, txt_bot, estilo


#    CARDS                                                         

@app.callback(Output("card-capital","children"), Input("tick","n_intervals"))
def card_capital(_):
    r = get_resumen()
    cg  = C["green"] if r["gan"] >= 0 else C["red"]
    base = r.get("cap_base", CAPITAL_INICIAL) or CAPITAL_INICIAL
    pct = (r["gan"] / base * 100) if base > 0 else 0
    return card([
        label(f"Capital - paper trading ({r.get('fuente_capital','FALLBACK_40000')})"),
        html.Div([
            stat_block("Capital Base", f"${base:,.0f}", C["accent"]),
            stat_block("Disponible",  f"${r['disp']:,.0f}", C["green"]),
            stat_block("Comprometido",f"${r['comp']:,.0f}", C["yellow"]),
            stat_block("Ganancia",    f"${r['gan']:,.2f}",  cg),
            stat_block("Rendimiento", f"{pct:+.2f}%",       cg, small=True),
        ], style={"display":"grid","grid-template-columns":"1fr 1fr","gap":"8px","margin-top":"8px"}),
        html.Div(f"Cauciones: {r['tc']} -> ${r['gc']:,.2f}  |  Arbitrajes: {r['ta']} -> ${r['ga']:,.2f}",
                 style={"color":C["sub"],"font-size":"10px","margin-top":"8px"}),
        (html.Div(
            "BLOQUEO ACTIVO: no se permite ejecutar paper con fallback de capital.",
            style={"color":C["red"],"font-size":"10px","margin-top":"6px","font-family":FONT}
        ) if r.get("fuente_capital") != "IOL_REAL" else html.Div(
            "Capital operativo validado con IOL_REAL.",
            style={"color":C["green"],"font-size":"10px","margin-top":"6px","font-family":FONT}
        )),
    ])


@app.callback(Output("card-riesgo-operativo", "children"), Input("tick", "n_intervals"))
def card_riesgo_operativo(_):
    est = get_estado_bot()
    modo = str(est.get("modo", "-")).lower()
    breaker_activo = modo == "circuit_breaker"
    txt_breaker = "ACTIVO" if breaker_activo else "INACTIVO"
    c_breaker = C["red"] if breaker_activo else C["green"]

    edad_ccl = edad_min_ultimo_registro("ccl_historico", "timestamp")
    edad_nyse = edad_min_ultimo_registro("precios_nyse", "timestamp")
    ok_ccl = (edad_ccl is not None) and (edad_ccl <= MAX_EDAD_CCL_MIN)
    ok_nyse = (edad_nyse is not None) and (edad_nyse <= MAX_EDAD_PRECIOS_NYSE_MIN)
    txt_ccl = "sin dato" if edad_ccl is None else f"{edad_ccl:.1f} min"
    txt_nyse = "sin dato" if edad_nyse is None else f"{edad_nyse:.1f} min"

    perdidas = get_perdidas_consecutivas()
    c_perdidas = C["red"] if perdidas >= MAX_NEGATIVAS_CONSECUTIVAS else (C["yellow"] if perdidas > 0 else C["green"])

    r = get_resumen()
    base = float(r.get("cap_base", CAPITAL_INICIAL) or CAPITAL_INICIAL)
    tope_dia = base * MAX_CAPITAL_POR_DIA
    try:
        conn = conectar()
        c = conn.cursor()
        hoy = datetime.now().date().isoformat()
        c.execute("SELECT COALESCE(SUM(capital_usado),0) FROM operaciones_paper WHERE substr(timestamp,1,10)=*", (hoy,))
        usado_hoy = float(c.fetchone()[0] or 0.0)
        conn.close()
    except Exception:
        usado_hoy = 0.0

    restante = max(0.0, tope_dia - usado_hoy)
    uso_pct = (usado_hoy / tope_dia * 100.0) if tope_dia > 0 else 0.0
    c_cupo = C["red"] if uso_pct >= 95 else (C["yellow"] if uso_pct >= 75 else C["green"])

    return card([
        label("Riesgo operativo"),
        html.Div([
            stat_block("Circuit Breaker", txt_breaker, c_breaker, small=True),
            stat_block("Perdidas consec.", f"{perdidas}/{MAX_NEGATIVAS_CONSECUTIVAS}", c_perdidas, small=True),
        ], style={"display":"grid","grid-template-columns":"1fr 1fr","gap":"8px","margin-bottom":"8px"}),
        html.Div([
            stat_block("Frescura CCL", txt_ccl, C["green"] if ok_ccl else C["red"], small=True),
            stat_block("Frescura NYSE", txt_nyse, C["green"] if ok_nyse else C["red"], small=True),
        ], style={"display":"grid","grid-template-columns":"1fr 1fr","gap":"8px","margin-bottom":"8px"}),
        html.Div([
            html.Div("Cupo diario usado", style={"font-size":"10px","color":C["sub"],"font-family":FONT,"margin-bottom":"4px"}),
            html.Div(
                f"${usado_hoy:,.0f} / ${tope_dia:,.0f} ARS ({uso_pct:.1f}%)",
                style={"font-size":"12px","color":c_cupo,"font-family":FONT,"font-weight":"bold"},
            ),
            html.Div(
                f"Disponible hoy: ${restante:,.0f} ARS",
                style={"font-size":"10px","color":C["text"],"font-family":FONT,"margin-top":"4px"},
            ),
        ], style={
            "padding":"10px 12px",
            "border":f"1px solid {C['border']}",
            "border-radius":"6px",
            "background":"linear-gradient(180deg, rgba(0,200,255,0.08), rgba(13,21,32,0.75))",
        }),
        html.Div(
            f"Umbrales: CCL <= {MAX_EDAD_CCL_MIN}m | NYSE <= {MAX_EDAD_PRECIOS_NYSE_MIN}m",
            style={"font-size":"10px","color":C["sub"],"font-family":FONT,"margin-top":"8px"},
        ),
    ], border_color=C["purple"])

@app.callback(Output("card-alerta-perdidas","children"), Input("tick","n_intervals"))
def card_alerta_perdidas(_):
    cfg = cargar_config()
    consec = get_perdidas_consecutivas()
    if consec < cfg.get("alertas_perdidas_consecutivas", 3): return html.Div()
    nc = round(cfg["ganancia_minima_caucion_pct"] + 0.5, 1)
    na = round(cfg["ganancia_minima_arbitraje_pct"] + 0.5, 1)
    return card([
        html.Div(f"[WARN] {consec} OPS CONSECUTIVAS EN PERDIDA",
                 style={"color":C["red"],"font-weight":"bold","font-size":"12px","font-family":FONT,"margin-bottom":"8px"}),
        html.Div(f"Caucion: {cfg['ganancia_minima_caucion_pct']}% -> {nc}%",
                 style={"color":C["yellow"],"font-size":"11px","font-family":FONT}),
        html.Div(f"Arbitraje: {cfg['ganancia_minima_arbitraje_pct']}% -> {na}%",
                 style={"color":C["yellow"],"font-size":"11px","font-family":FONT,"margin-bottom":"10px"}),
        html.Div([
            html.Button("APROBAR", id="btn-aprobar-ajuste", n_clicks=0,
                        style={"background":C["yellow"],"color":C["bg"],"border":"none","border-radius":"4px",
                               "padding":"7px 12px","font-weight":"bold","font-family":FONT,
                               "font-size":"10px","cursor":"pointer","margin-right":"8px"}),
            html.Button("IGNORAR", id="btn-ignorar-ajuste", n_clicks=0,
                        style={"background":"transparent","color":C["sub"],"border":f"1px solid {C['border']}",
                               "border-radius":"4px","padding":"7px 12px","font-family":FONT,
                               "font-size":"10px","cursor":"pointer"}),
        ]),
        html.Div(id="msg-ajuste", style={"margin-top":"8px","font-size":"11px","font-family":FONT}),
    ], border_color=C["red"])

@app.callback(Output("card-alertas-tickers","children"), Input("tick","n_intervals"))
def card_alertas_tickers(_):
    alertas = get_alertas_ticker()
    if not alertas: return html.Div()
    items = []
    for a in alertas:
        items.append(html.Div([
            html.Div(f"[WARN] {a.get('simbolo','*')} - ticker IOL: '{a.get('simbolo_iol','*')}' ({a.get('fallos_consecutivos',0)} fallos)",
                     style={"color":C["orange"],"font-weight":"bold","font-size":"11px","font-family":FONT}),
            html.Div(str(a.get("motivo",""))[:80], style={"color":C["sub"],"font-size":"10px"}),
            html.Div("-> Corregir simbolo_iol en config.py", style={"color":C["yellow"],"font-size":"10px"}),
            html.Hr(style={"border-color":C["border"],"margin":"5px 0"}),
        ]))
    return card([
        html.Div(f"[WARN] {len(alertas)} TICKER(S) DEFECTUOSO(S)",
                 style={"color":C["orange"],"font-weight":"bold","font-size":"11px","margin-bottom":"8px","font-family":FONT}),
        *items,
    ], border_color=C["orange"])

@app.callback(Output("card-alertas-oportunidades","children"), Input("tick","n_intervals"))
def card_alertas_oportunidades(_):
    alertas = [a for a in get_alertas() if not a.get("vista", False)]
    if not alertas: return html.Div()
    items = []
    for a in alertas[:5]:
        items.append(html.Div([
            html.Div(f"* {a['tipo']} {a['simbolo']}",
                     style={"color":C["yellow"],"font-size":"11px","font-weight":"bold","font-family":FONT}),
            html.Div(f"Gan: ${a['ganancia_estimada']:,.2f} | Faltaron: ${a['capital_faltante']:,.2f}",
                     style={"color":C["sub"],"font-size":"10px"}),
            html.Hr(style={"border-color":C["border"],"margin":"4px 0"}),
        ]))
    return card([
        html.Div(f"* {len(alertas)} OPORTUNIDADES PERDIDAS POR CAPITAL",
                 style={"color":C["yellow"],"font-weight":"bold","font-size":"11px","margin-bottom":"8px","font-family":FONT}),
        *items,
    ], border_color=C["yellow"])

@app.callback(
    Output("inp-gcau","value"), Output("inp-garb","value"), Output("inp-maxcau","value"),
    Output("inp-maxarb","value"), Output("inp-umbral","value"), Output("inp-spread","value"),
    Input("tick","n_intervals")
)
def cargar_inputs(_):
    cfg = cargar_config()
    return (cfg["ganancia_minima_caucion_pct"], cfg["ganancia_minima_arbitraje_pct"],
            cfg["max_capital_caucion_pct"], cfg["max_capital_arbitraje_pct"],
            cfg["umbral_caucion"], cfg["spread_minimo_arbitraje"])

@app.callback(
    Output("msg-config","children"),
    Input("btn-guardar","n_clicks"),
    State("inp-gcau","value"), State("inp-garb","value"), State("inp-maxcau","value"),
    State("inp-maxarb","value"), State("inp-umbral","value"), State("inp-spread","value"),
    prevent_initial_call=True
)
def guardar_conf(_, gcau, garb, maxcau, maxarb, umbral, spread):
    if None in [gcau, garb, maxcau, maxarb, umbral, spread]: return "[WARN] Completa todos los campos."
    cfg = cargar_config()
    cfg.update({"ganancia_minima_caucion_pct":float(gcau),"ganancia_minima_arbitraje_pct":float(garb),
                "max_capital_caucion_pct":float(maxcau),"max_capital_arbitraje_pct":float(maxarb),
                "umbral_caucion":float(umbral),"spread_minimo_arbitraje":float(spread)})
    guardar_config(cfg)
    return f"OK {datetime.now().strftime('%H:%M:%S')}"


@app.callback(
    Output("msg-modo-bot","children"),
    Input("sel-modo-bot","value"),
    prevent_initial_call=True
)
def guardar_modo_forzado(modo):
    if modo not in ("auto", "arbitraje", "mixto", "caucion"):
        modo = "auto"
    cfg = cargar_config()
    cfg["modo_forzado_bot"] = modo
    guardar_config(cfg)
    return f"Modo guardado: {modo.upper()} ({datetime.now().strftime('%H:%M:%S')})"

@app.callback(
    Output("msg-execution-mode","children"),
    Input("sel-execution-mode","value"),
    prevent_initial_call=True
)
def guardar_execution_mode(mode):
    if mode not in ("paper", "real"):
        mode = "paper"
    cfg = cargar_config()
    cfg["execution_mode"] = mode
    guardar_config(cfg)
    return f"Ejecucion guardada: {mode.upper()} ({datetime.now().strftime('%H:%M:%S')})"

@app.callback(
    Output("msg-real-caucion-enabled","children"),
    Input("sel-real-caucion-enabled","value"),
    prevent_initial_call=True
)
def guardar_real_caucion_enabled(val):
    cfg = cargar_config()
    enabled = (str(val).lower() == "on")
    cfg["real_caucion_enabled"] = enabled
    guardar_config(cfg)
    backend = str(cfg.get("real_caucion_backend", "web")).upper()
    return f"Real caucion: {'ON' if enabled else 'OFF'} | backend {backend} ({datetime.now().strftime('%H:%M:%S')})"

@app.callback(
    Output("msg-ajuste","children"),
    Input("btn-aprobar-ajuste","n_clicks"), Input("btn-ignorar-ajuste","n_clicks"),
    prevent_initial_call=True
)
def manejar_ajuste(_, __):
    ctx = callback_context
    if not ctx.triggered: return ""
    if ctx.triggered[0]["prop_id"].split(".")[0] == "btn-aprobar-ajuste":
        cfg = cargar_config()
        cfg["ganancia_minima_caucion_pct"]   = round(cfg["ganancia_minima_caucion_pct"] + 0.5, 1)
        cfg["ganancia_minima_arbitraje_pct"] = round(cfg["ganancia_minima_arbitraje_pct"] + 0.5, 1)
        guardar_config(cfg)
        return html.Span("OK Ajuste aplicado.", style={"color":C["green"]})
    return html.Span("Ignorado.", style={"color":C["sub"]})

@app.callback(
    Output("card-alertas-ratio","children"),
    Input("tick","n_intervals"),
    Input("btn-confirmar-ratio","n_clicks"), Input("btn-rechazar-ratio","n_clicks"),
    State("store-ratio-simbolo","data"), prevent_initial_call=False
)
def card_alertas_ratio(_, conf, rech, simbolo):
    ctx = callback_context
    if ctx.triggered and simbolo:
        t = ctx.triggered[0]["prop_id"].split(".")[0]
        if t in ("btn-confirmar-ratio","btn-rechazar-ratio"):
            confirmar_ratio_dashboard(simbolo, t == "btn-confirmar-ratio")
    alertas = get_alertas_ratio()
    if not alertas: return html.Div()
    items = []
    for a in alertas[:2]:
        items.append(html.Div([
            html.Div(f"* CAMBIO DE RATIO - {a['simbolo']}",
                     style={"color":C["purple"],"font-weight":"bold","font-size":"12px","font-family":FONT,"margin-bottom":"6px"}),
            html.Div(f"{a['ratio_viejo']}:1 -> {a['ratio_nuevo']}:1",
                     style={"color":C["yellow"],"font-size":"14px","font-weight":"bold"}),
            html.Div("Verificar en banco.comafi.com.ar antes de confirmar.",
                     style={"color":C["sub"],"font-size":"10px","margin-bottom":"8px"}),
            dcc.Store(id="store-ratio-simbolo", data=a["simbolo"]),
            html.Div([
                html.Button("OK CONFIRMAR", id="btn-confirmar-ratio", n_clicks=0,
                            style={"background":C["purple"],"color":C["bg"],"border":"none","border-radius":"4px",
                                   "padding":"7px 10px","font-weight":"bold","font-family":FONT,"font-size":"10px",
                                   "cursor":"pointer","margin-right":"8px"}),
                html.Button("X RECHAZAR", id="btn-rechazar-ratio", n_clicks=0,
                            style={"background":"transparent","color":C["sub"],"border":f"1px solid {C['border']}",
                                   "border-radius":"4px","padding":"7px 10px","font-family":FONT,
                                   "font-size":"10px","cursor":"pointer"}),
            ]),
            html.Hr(style={"border-color":C["border"],"margin":"8px 0"}),
        ]))
    return card(items, border_color=C["purple"])


#    TABS                                                          

@app.callback(
    Output("tab-content","children"),
    Input("tabs","value"), Input("tick","n_intervals"), Input("sel-periodo","value")
)
def render_tab(tab, _, periodo):
    periodo = periodo or "today"
    if tab == "tab-live":      return _render_live(periodo)
    if tab == "tab-spreads":   return _render_spreads(periodo)
    if tab == "tab-sims":      return _render_simulaciones(periodo)
    if tab == "tab-cauciones": return _render_cauciones(periodo)
    if tab == "tab-ops":       return _render_ops(periodo)
    if tab == "tab-senales":   return _render_senales(periodo)
    return html.Div()


#    EN VIVO                                                       

def _render_live(periodo="today"):
    df_cau = get_df("SELECT * FROM cauciones ORDER BY fecha_hora DESC LIMIT 300")
    df_ops = get_df("SELECT * FROM operaciones_paper ORDER BY timestamp DESC LIMIT 50")
    est    = get_estado_bot()
    df_cau = filtrar_df_periodo(df_cau, "fecha_hora", periodo)
    df_ops = filtrar_df_periodo(df_ops, "timestamp", periodo)

    mini = html.Div([
        html.Div([html.Div("CICLOS",      style={"font-size":"9px","color":C["sub"],"letter-spacing":"2px","font-family":FONT}),
                  html.Div(str(est.get("ciclos","-")), style={"font-size":"20px","color":C["accent"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
        html.Div([html.Div("SENALES HOY", style={"font-size":"9px","color":C["sub"],"letter-spacing":"2px","font-family":FONT}),
                  html.Div(str(est.get("seniales_hoy","0")), style={"font-size":"20px","color":C["yellow"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
        html.Div([html.Div("GANANCIAS",   style={"font-size":"9px","color":C["sub"],"letter-spacing":"2px","font-family":FONT}),
                  html.Div(f"${est.get('ganancias_hoy',0):,.2f}", style={"font-size":"18px","color":C["green"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
        html.Div([html.Div("NYSE",        style={"font-size":"9px","color":C["sub"],"letter-spacing":"2px","font-family":FONT}),
                  html.Div(str(est.get("horario_nyse","-")).upper(), style={"font-size":"14px","color":C["purple"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
    ], style={"display":"grid","grid-template-columns":"1fr 1fr 1fr 1fr","gap":"8px","margin-bottom":"10px"})

    fig_cau = _fig_vacio("Sin datos de cauciones (1/2/3/7 dias)")
    if not df_cau.empty:
        fig_cau = go.Figure()
        plazos_cols = [
            (1, C["accent"], "1d"),
            (2, C["yellow"], "2d"),
            (3, C["purple"], "3d"),
            (7, C["orange"], "7d"),
        ]
        offsets = {1: 0.00, 2: 0.12, 3: 0.24, 7: 0.36}
        any_trace = False
        for p, col, nom in plazos_cols:
            sub = df_cau[df_cau["plazo_dias"] == p] if "plazo_dias" in df_cau.columns else pd.DataFrame()
            if sub.empty:
                continue
            sub = sub.sort_values("fecha_hora")
            y_real = pd.to_numeric(sub["tasa_anual"], errors="coerce")
            y_plot = y_real + offsets.get(p, 0.0)
            fig_cau.add_trace(go.Scatter(
                x=sub["fecha_hora"], y=y_plot,
                mode="lines+markers", name=f"Caucion {nom}",
                line=dict(color=col, width=2), marker=dict(size=4),
                customdata=y_real,
                hovertemplate=f"<b>{nom}</b><br>%{{x}}<br>Tasa real: %{{customdata:.2f}}% TNA<extra></extra>",
            ))
            any_trace = True
        if not any_trace:
            fig_cau = _fig_vacio("Sin datos de cauciones (1/2/3/7 dias)")
        else:
            fig_cau.update_layout(
                legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10, color=C["sub"])),
                hovermode="x unified",
            )
        _fig_layout(fig_cau, "% TNA", 210)

    fig_gan = _fig_vacio("Sin operaciones aun")
    if not df_ops.empty:
        df_s = df_ops.sort_values("timestamp")
        df_s["acum"] = df_s["ganancia_neta"].cumsum()
        col = C["green"] if df_s["acum"].iloc[-1] >= 0 else C["red"]
        fig_gan = go.Figure()
        fig_gan.add_trace(go.Scatter(
            x=df_s["timestamp"], y=df_s["acum"], mode="lines",
            fill="tozeroy", line=dict(color=col, width=2),
            fillcolor=f"rgba({'0,230,118' if col==C['green'] else '255,23,68'},0.10)",
            hovertemplate="<b>%{x}</b><br>Acum: $%{y:,.2f} ARS<extra></extra>",
        ))
        fig_gan.add_hline(y=0, line_dash="dot", line_color=C["border"], line_width=1)
        _fig_layout(fig_gan, "ARS", 210)

    ts = est.get("timestamp","")
    return html.Div([
        mini,
        html.Div(f"Ultimo ciclo: {ts[:16].replace('T',' ')}" if ts else "Bot no iniciado aun",
                 style={"color":C["sub"],"font-size":"10px","font-family":FONT,"text-align":"right","margin-bottom":"8px"}),
        card([label(f"* Tasas de cauciones 1/2/3/7 dias ({titulo_periodo(periodo)})"),
              html.Div("Nota: se aplica offset visual leve para evitar lineas amontonadas; el hover muestra TNA real.", style={"color":C["sub"],"font-size":"10px","margin-bottom":"6px"}),
              dcc.Graph(figure=fig_cau, config=_cfg_grafico())], mb="10px"),
        card([label(f"* Ganancias acumuladas paper trading ({titulo_periodo(periodo)})"), dcc.Graph(figure=fig_gan, config=_cfg_grafico())], mb="10px"),
    ])


#    SPREADS                                                       

def _render_spreads(periodo="today"):
    precios_nyse = get_precios_nyse()
    ccl = get_ultimo_ccl()
    cfg = cargar_config()
    spread_min = cfg.get("spread_minimo_arbitraje", 3.0)

    ruta_ratios = os.path.join(RUTA_DATOS, "ratios_comafi.json")
    ratios_json = {}
    if os.path.exists(ruta_ratios):
        try:
            ratios_json = json.load(open(ruta_ratios)).get("ratios", {})
        except Exception:
            pass

    spreads_db = {}
    try:
        conn = conectar()
        c = conn.cursor()
        c.execute("""
            SELECT simbolo, spread_pct, ccl_implicito, fecha_hora
            FROM seniales WHERE tipo='arbitraje'
            ORDER BY fecha_hora DESC LIMIT 3000
        """)
        for sym, sp, ci, ts in c.fetchall():
            try:
                dt = datetime.fromisoformat(str(ts))
            except Exception:
                dt = None
            if not _en_periodo_fecha(dt, periodo):
                continue
            if sym not in spreads_db:
                spreads_db[sym] = {"spread_pct": round(sp or 0, 2), "ts": ts}
        conn.close()
    except Exception:
        pass

    filas = []
    for simbolo, datos in CEDEARS.items():
        precio_usd = precios_nyse.get(datos["simbolo_nyse"])
        ratio = ratios_json.get(simbolo, datos["ratio"])
        if not precio_usd or not ccl:
            filas.append([simbolo, datos["nombre"][:18], f"{ratio}:1", "-", "-", "-", "-", "SIN DATO", 3, None])
            continue
        ars_teo = (precio_usd / ratio) * ccl
        if simbolo in spreads_db:
            sp = spreads_db[simbolo]["spread_pct"]
            ts_txt = str(spreads_db[simbolo]["ts"])[:16].replace("T", " ")
            estado = "SENAL" if abs(sp) >= spread_min else "ok"
            filas.append([simbolo, datos["nombre"][:18], f"{ratio}:1", f"${precio_usd:,.2f}",
                          f"${ars_teo:,.0f}", f"{sp:+.2f}%", ts_txt, estado, 0 if estado=="SENAL" else 1, sp])
        else:
            filas.append([simbolo, datos["nombre"][:18], f"{ratio}:1", f"${precio_usd:,.2f}",
                          f"${ars_teo:,.0f}", "pendiente", "-", "pendiente", 2, None])

    filas.sort(key=lambda x: (x[8], -(abs(x[9]) if x[9] is not None else 0)))
    filas_tabla = [[f[0],f[1],f[2],f[3],f[4],f[5],f[6],f[7]] for f in filas]

    def c_sp(v):
        if "pendiente" in str(v) or v == "-":
            return C["sub"]
        try:
            val = abs(float(str(v).replace("%","").replace("+","")))
            if val >= spread_min:
                return C["green"]
            if val >= spread_min * 0.6:
                return C["yellow"]
        except Exception:
            pass
        return C["text"]

    def c_est(v):
        if "SENAL" in str(v):
            return C["green"]
        if "SIN DATO" in str(v):
            return C["red"]
        return C["sub"]

    return html.Div([card([
        html.Div([
            html.Div([label(f"* Spreads en vivo - {len(CEDEARS)} CEDEARs ({titulo_periodo(periodo)})")]),
            html.Div([
                html.Div(f"CCL: ${ccl:,.2f}" if ccl else "CCL: -",
                         style={"color":C["accent"],"font-size":"13px","font-weight":"bold","font-family":FONT}),
                html.Div(f"SENAL min: {spread_min}%  |  Costo total op: ~3.5-4.5%",
                         style={"color":C["yellow"],"font-size":"10px"}),
            ], style={"text-align":"right"}),
        ], style={"display":"flex","justify-content":"space-between","margin-bottom":"12px"}),
        tabla(["CEDEAR","Empresa","Ratio","NYSE USD","ARS Teorico","Spread","Ult. SENAL","Estado"],
              filas_tabla, col_colors=[None,None,None,None,None,c_sp,None,c_est]),
    ])])


#    SIMULACIONES                                                  

def _render_simulaciones(periodo="today"):
    df = get_df("SELECT * FROM cauciones_simuladas ORDER BY timestamp DESC LIMIT 2000")
    df = filtrar_df_periodo(df, "timestamp", periodo)
    if df.empty:
        return card([
            label(f"* Simulaciones de cauciones ({titulo_periodo(periodo)})"),
            html.Div("Sin simulaciones de cauciones en el periodo seleccionado.",
                     style={"color":C["sub"],"padding":"20px","font-size":"12px"}),
        ])

    df["tiene_senal"] = pd.to_numeric(df.get("tiene_senal", 0), errors="coerce").fillna(0).astype(int)
    df["capital_faltante"] = pd.to_numeric(df.get("capital_faltante", 0), errors="coerce").fillna(0.0)
    df["ganancia_neta"] = pd.to_numeric(df.get("ganancia_neta", 0), errors="coerce").fillna(0.0)
    df["capital_usado"] = pd.to_numeric(df.get("capital_usado", 0), errors="coerce").fillna(0.0)

    total = len(df)
    con_senal = int((df["tiene_senal"] == 1).sum())
    sin_senal = total - con_senal
    por_capital = int((df["capital_faltante"] > 0).sum())
    gan_total = float(df.loc[df["tiene_senal"] == 1, "ganancia_neta"].sum())

    resumen = html.Div([
        html.Div([html.Div("SIMULADAS", style={"font-size":"9px","color":C["sub"],"font-family":FONT}),
                  html.Div(str(total), style={"font-size":"22px","color":C["accent"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
        html.Div([html.Div("CON SENAL", style={"font-size":"9px","color":C["sub"],"font-family":FONT}),
                  html.Div(str(con_senal), style={"font-size":"22px","color":C["green"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
        html.Div([html.Div("SIN SENAL", style={"font-size":"9px","color":C["sub"],"font-family":FONT}),
                  html.Div(str(sin_senal), style={"font-size":"22px","color":C["red"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
        html.Div([html.Div("CAPITAL INSUF.", style={"font-size":"9px","color":C["sub"],"font-family":FONT}),
                  html.Div(str(por_capital), style={"font-size":"22px","color":C["yellow"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
        html.Div([html.Div("GANANCIA NETA EST.", style={"font-size":"9px","color":C["sub"],"font-family":FONT}),
                  html.Div(f"${gan_total:,.2f}", style={"font-size":"16px","color":C["green"] if gan_total>=0 else C["red"],"font-weight":"bold","font-family":FONT})],
                 style={"text-align":"center","background":C["panel"],"border-radius":"5px","padding":"10px","border":f"1px solid {C['border']}"}),
    ], style={"display":"grid","grid-template-columns":"1fr 1fr 1fr 1fr 1fr","gap":"8px","margin-bottom":"12px"})

    filas = []
    for _, r in df.head(60).iterrows():
        cap_min = r.get("capital_minimo_requerido")
        cap_min_txt = "inviable" if pd.isna(cap_min) else f"${float(cap_min):,.0f}"
        motivo = str(r.get("motivo_no_senal") or "")
        filas.append([
            str(r.get("timestamp", ""))[:16].replace("T", " "),
            f"{int(r.get('plazo_dias', 0))}d",
            f"{float(r.get('tna_mercado', 0) or 0):.2f}%",
            f"${float(r.get('capital_usado', 0) or 0):,.0f}",
            cap_min_txt,
            f"${float(r.get('capital_faltante', 0) or 0):,.0f}",
            f"${float(r.get('ganancia_neta', 0) or 0):,.2f}",
            "SI" if int(r.get("tiene_senal", 0) or 0) == 1 else "NO",
            motivo[:110] if motivo else "-",
        ])

    def c_senal(v):
        return C["green"] if str(v) == "SI" else C["red"]

    def c_gan(v):
        try:
            return C["green"] if float(str(v).replace("$", "").replace(",", "")) >= 0 else C["red"]
        except Exception:
            return C["text"]

    def c_falt(v):
        try:
            return C["red"] if float(str(v).replace("$", "").replace(",", "")) > 0 else C["sub"]
        except Exception:
            return C["text"]

    return html.Div([
        card([label(f"Simulaciones de cauciones ({titulo_periodo(periodo)})"), html.Div("Fuente: cauciones_simuladas (decision simulada).", style={"color":C["sub"],"font-size":"10px","margin-bottom":"8px"}), resumen], mb="10px"),
        card([label("* Ultimas 60 simulaciones detalladas"),
              tabla(
                  ["Fecha/Hora", "Plazo", "TNA", "Capital", "Cap. min", "Faltante", "Gan. neta", "SENAL", "Motivo"],
                  filas,
                  col_colors=[None, None, None, None, None, c_falt, c_gan, c_senal, None]
              )]),
    ])


#    CAUCIONES                                                     

def _render_cauciones(periodo="today"):
    df_all = get_df("SELECT * FROM cauciones ORDER BY fecha_hora DESC LIMIT 1000")
    df_all = filtrar_df_periodo(df_all, "fecha_hora", periodo)
    if df_all.empty:
        return card([html.Div(
            "Sin datos de cauciones reales disponibles en el periodo seleccionado.",
            style={"color":C["sub"],"font-size":"12px","padding":"20px","white-space":"pre-line"}
        )])

    df_1 = df_all[df_all["plazo_dias"]==1] if "plazo_dias" in df_all.columns else df_all
    df_2 = df_all[df_all["plazo_dias"]==2] if "plazo_dias" in df_all.columns else pd.DataFrame()
    df_3 = df_all[df_all["plazo_dias"]==3] if "plazo_dias" in df_all.columns else pd.DataFrame()
    df_7 = df_all[df_all["plazo_dias"]==7] if "plazo_dias" in df_all.columns else pd.DataFrame()

    fig = go.Figure()
    # Offset visual leve para evitar solapamiento cuando las 4 curvas están muy juntas.
    offsets = {1: 0.00, 2: 0.12, 3: 0.24, 7: 0.36}
    series = [
        (1, df_1, C["accent"], "1 dia"),
        (2, df_2, C["yellow"], "2 dias"),
        (3, df_3, C["purple"], "3 dias"),
        (7, df_7, C["orange"], "7 dias"),
    ]
    for plazo, df_p, col, nom in series:
        if not df_p.empty:
            df_p = df_p.sort_values("fecha_hora")
            y_real = pd.to_numeric(df_p["tasa_anual"], errors="coerce")
            off = offsets.get(plazo, 0.0)
            y_plot = y_real + off
            fig.add_trace(go.Scatter(
                x=df_p["fecha_hora"], y=y_plot,
                mode="lines+markers", name=f"Caucion {nom}",
                line=dict(color=col, width=2), marker=dict(size=5),
                customdata=y_real,
                hovertemplate=f"<b>{nom}</b><br>%{{x}}<br>%{{customdata:.2f}}% TNA<extra></extra>",
            ))
    fig.update_layout(
        paper_bgcolor=C["card"], plot_bgcolor=C["card"],
        font=dict(color=C["text"], family=FONT), height=320,
        margin=dict(l=55,r=20,t=20,b=40),
        xaxis=dict(showgrid=False, color=C["sub"],
                   rangeslider=dict(visible=True, bgcolor=C["panel"], thickness=0.06)),
        yaxis=dict(showgrid=True, gridcolor="rgba(26,42,58,0.33)", color=C["sub"], title="% TNA (offset visual)"),
        showlegend=True, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10, color=C["sub"])),
    )

    stats = html.Div([
        *[html.Div([
            html.Div(f"Caucion {n}", style={"font-size":"9px","color":C["sub"],"font-family":FONT}),
            html.Div(f"{df.iloc[0]['tasa_anual']:.2f}% TNA" if not df.empty else "-",
                     style={"font-size":"14px","color":c,"font-weight":"bold","font-family":FONT}),
            html.Div(f"{len(df)} lecturas | {df.iloc[0].get('fuente','*')}" if not df.empty else "",
                     style={"font-size":"10px","color":C["sub"]}),
        ], style={"text-align":"center","background":C["panel"],"border-radius":"5px",
                   "padding":"10px","border":f"1px solid {C['border']}"})
        for (p,df,c,n) in [(1,df_1,C["accent"],"1 dia"),(2,df_2,C["yellow"],"2 dias"),(3,df_3,C["purple"],"3 dias"),(7,df_7,C["orange"],"7 dias")]]
    ], style={"display":"grid","grid-template-columns":"repeat(auto-fit,minmax(140px,1fr))","gap":"8px","margin-bottom":"10px"})

    filas = [[r["fecha_hora"][:16], f"{r['tasa_anual']:.2f}%", f"{int(r.get('plazo_dias',1))}d", r.get("fuente","-")]
             for _, r in df_all.head(20).iterrows()]

    def c_t(v):
        try:
            t = float(v.replace("%",""))
            return C["green"] if t > 25 else (C["yellow"] if t > 15 else C["sub"])
        except Exception: return C["text"]

    return html.Div([
        card([label(f"Tasas reales - 4 plazos (1/2/3/7) ({titulo_periodo(periodo)})"),
              html.Div("Fuente: cauciones (tasas reales de mercado). Se aplica un offset visual leve por plazo para reducir líneas amontonadas; el hover muestra la TNA real.", style={"color":C["sub"],"font-size":"10px","margin-bottom":"8px"}),
              stats,
              dcc.Graph(figure=fig, config=_cfg_grafico())], mb="10px"),
        card([label("* Ultimas 20 lecturas"),
              tabla(["Fecha/Hora","Tasa TNA","Plazo","Fuente"], filas, col_colors=[None,c_t,None,None])]),
    ])


#    OPERACIONES                                                   

def _render_ops(periodo="today"):
    df = get_df("SELECT * FROM operaciones_paper ORDER BY timestamp DESC")
    df = filtrar_df_periodo(df, "timestamp", periodo)
    if df.empty:
        return card([html.Div("Sin operaciones paper aun.", style={"color":C["sub"],"padding":"20px"})])
    df_s = df.sort_values("timestamp")
    df_s["acum"] = df_s["ganancia_neta"].cumsum()
    fig = go.Figure()
    for tipo, col in [("CAUCION",C["accent"]),("ARBITRAJE",C["purple"])]:
        sub = df_s[df_s["tipo"]==tipo]
        if not sub.empty:
            fig.add_trace(go.Bar(x=sub["timestamp"], y=sub["ganancia_neta"], name=tipo,
                marker_color=col, opacity=0.75,
                hovertemplate=f"<b>{tipo}</b><br>%{{x}}<br>$%{{y:,.2f}} ARS<extra></extra>"))
    fig.add_trace(go.Scatter(x=df_s["timestamp"], y=df_s["acum"], name="Acumulado",
        line=dict(color=C["green"], width=2, dash="dot"),
        hovertemplate="Acum: $%{y:,.2f} ARS<extra></extra>"))
    fig.add_hline(y=0, line_dash="dot", line_color=C["border"], line_width=1)
    _fig_layout(fig, "ARS", 280)
    fig.update_layout(barmode="group", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10, color=C["sub"])))

    filas = [[r["timestamp"][:16], r["tipo"], r["simbolo"],
              f"${r.get('capital_usado',0):,.0f}", f"${r.get('ganancia_neta',0):,.2f}", r.get("estado","-")]
             for _, r in df.head(20).iterrows()]

    def c_g(v):
        try: return C["green"] if float(v.replace("$","").replace(",","")) >= 0 else C["red"]
        except Exception: return C["text"]

    return html.Div([
        card([label("* Ganancias por operacion"), dcc.Graph(figure=fig, config=_cfg_grafico())]),
        card([label("* Historial"), tabla(["Fecha","Tipo","Simbolo","Capital","Ganancia","Estado"],
              filas, col_colors=[None,None,None,None,c_g,None])]),
    ])


#    SENALES                                                       

def _render_senales(periodo="today"):
    df = get_df("SELECT * FROM seniales ORDER BY fecha_hora DESC LIMIT 1000")
    df = filtrar_df_periodo(df, "fecha_hora", periodo)
    if df.empty:
        return card([html.Div("Sin SENALes.", style={"color":C["sub"],"padding":"20px"})])

    def _plazo_from_simbolo(simbolo):
        try:
            s = str(simbolo or "").upper()
            if s.startswith("CAUCION_") and s.endswith("D"):
                return int(s.replace("CAUCION_", "").replace("D", ""))
        except Exception:
            pass
        return None

    fig = go.Figure()
    # Arbitraje
    sub_arb = df[df["tipo"] == "arbitraje"] if "tipo" in df.columns else pd.DataFrame()
    if not sub_arb.empty:
        fig.add_trace(go.Scatter(
            x=sub_arb["fecha_hora"], y=sub_arb["spread_pct"], mode="markers", name="Arbitraje",
            marker=dict(color=C["purple"], size=9, symbol="diamond", line=dict(width=1, color="rgba(255,255,255,0.3)")),
            hovertemplate="<b>Arbitraje</b><br>%{x}<br>%{y:.2f}%<extra></extra>",
        ))

    # Caucion por plazo (colores diferenciados)
    sub_cau = df[df["tipo"] == "caucion"].copy() if "tipo" in df.columns else pd.DataFrame()
    if not sub_cau.empty:
        sub_cau["plazo_cau"] = sub_cau.get("simbolo", "").apply(_plazo_from_simbolo)
        palette = {
            1: C["accent"],
            2: C["yellow"],
            3: C["orange"],
            7: C["green"],
            None: C["sub"],
        }
        for p in [1, 2, 3, 7, None]:
            c = sub_cau[sub_cau["plazo_cau"].isna()] if p is None else sub_cau[sub_cau["plazo_cau"] == p]
            if c.empty:
                continue
            nombre = "Caucion s/plazo" if p is None else f"Caucion {p}d"
            fig.add_trace(go.Scatter(
                x=c["fecha_hora"], y=c["spread_pct"], mode="markers", name=nombre,
                marker=dict(color=palette[p], size=9, symbol="circle", line=dict(width=1, color="rgba(255,255,255,0.3)")),
                hovertemplate=f"<b>{nombre}</b><br>%{{x}}<br>%{{y:.2f}}%<extra></extra>",
            ))
    _fig_layout(fig, "Spread %", 260)
    fig.update_layout(showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10, color=C["sub"])))

    filas = [[str(r["fecha_hora"])[:10], str(r["fecha_hora"])[11:16], r.get("tipo",""), r.get("simbolo",""),
              (f"{_plazo_from_simbolo(r.get('simbolo',''))}d" if _plazo_from_simbolo(r.get("simbolo","")) is not None else "-"),
              f"{r.get('spread_pct',0):+.2f}%", str(r.get("accion",""))[:28]]
             for _, r in df.head(25).iterrows()]

    def c_sp(v):
        try:
            return C["green"] if float(v.replace("%","").replace("+","")) > 0 else C["red"]
        except Exception:
            return C["text"]

    def c_tipo(v):
        if str(v).lower() == "caucion":
            return C["yellow"]
        if str(v).lower() == "arbitraje":
            return C["purple"]
        return C["text"]

    # SENALes de Caucion detectadas pero sin ejecucion paper.
    df_cau_sig = df[df["tipo"] == "caucion"] if "tipo" in df.columns else pd.DataFrame()
    df_ops_cau = get_df("SELECT timestamp, simbolo FROM operaciones_paper WHERE tipo='CAUCION' ORDER BY timestamp DESC LIMIT 2000")
    df_ops_cau = filtrar_df_periodo(df_ops_cau, "timestamp", periodo)
    df_cau_sim = get_df("SELECT timestamp, plazo_dias, motivo_no_senal, fuente_saldo, capital_usado, ganancia_neta, capital_faltante FROM cauciones_simuladas ORDER BY timestamp DESC LIMIT 2000")
    df_cau_sim = filtrar_df_periodo(df_cau_sim, "timestamp", periodo)

    pendientes_rows = []
    cfg = cargar_config()
    min_pct = float(cfg.get("ganancia_minima_caucion_pct", 1.5))

    def _find_causa_no_ejec(sig_ts, simbolo):
        plazo = None
        try:
            if isinstance(simbolo, str) and simbolo.startswith("CAUCION_") and simbolo.endswith("D"):
                plazo = int(simbolo.replace("CAUCION_", "").replace("D", ""))
        except Exception:
            plazo = None

        causa = "Sin ejecucion paper registrada para esta SENAL."
        if df_cau_sim.empty:
            return causa

        cand = df_cau_sim.copy()
        if plazo is not None and "plazo_dias" in cand.columns:
            cand = cand[pd.to_numeric(cand["plazo_dias"], errors="coerce") == plazo]
        if cand.empty:
            return causa

        cand = cand.copy()
        cand["timestamp"] = pd.to_datetime(cand["timestamp"], errors="coerce")
        cand = cand.dropna(subset=["timestamp"])
        if cand.empty:
            return causa

        cand["delta"] = (cand["timestamp"] - sig_ts).abs()
        row = cand.sort_values("delta").head(1)
        if row.empty:
            return causa

        r = row.iloc[0]
        fuente_saldo = str(r.get("fuente_saldo", "") or "")
        if fuente_saldo and fuente_saldo != "IOL":
            return f"Bloqueada por politica de capital real (fuente_saldo={fuente_saldo})."

        faltante = float(r.get("capital_faltante", 0) or 0)
        if faltante > 0:
            return f"Capital insuficiente (faltante ARS {faltante:,.2f})."

        gan = float(r.get("ganancia_neta", 0) or 0)
        cap = float(r.get("capital_usado", 0) or 0)
        minimo = cap * (min_pct / 100.0)
        if gan < minimo:
            return f"Rentabilidad menor al minimo configurado ({min_pct:.2f}%)."

        motivo = str(r.get("motivo_no_senal", "") or "")
        if motivo:
            return motivo
        return causa

    if not df_cau_sig.empty:
        sig_tmp = df_cau_sig.copy()
        sig_tmp["fecha_hora"] = pd.to_datetime(sig_tmp["fecha_hora"], errors="coerce")
        sig_tmp = sig_tmp.dropna(subset=["fecha_hora"])

        ops_tmp = df_ops_cau.copy()
        if not ops_tmp.empty:
            ops_tmp["timestamp"] = pd.to_datetime(ops_tmp["timestamp"], errors="coerce")
            ops_tmp = ops_tmp.dropna(subset=["timestamp"])

        for _, r in sig_tmp.sort_values("fecha_hora", ascending=False).head(50).iterrows():
            sig_ts = r["fecha_hora"]
            simbolo = str(r.get("simbolo", ""))
            ejecutada = False
            if not ops_tmp.empty:
                m = ops_tmp["simbolo"].astype(str) == simbolo
                if m.any():
                    dif = (ops_tmp.loc[m, "timestamp"] - sig_ts).abs().dt.total_seconds()
                    ejecutada = bool((dif <= 180).any())
            if not ejecutada:
                pendientes_rows.append([
                    sig_ts.strftime("%Y-%m-%d"),
                    sig_ts.strftime("%H:%M"),
                    simbolo,
                    f"{float(r.get('spread_pct', 0) or 0):+.2f}%",
                    _find_causa_no_ejec(sig_ts, simbolo)[:120],
                ])

    return html.Div([
        card([label("* SENALes detectadas"), dcc.Graph(figure=fig, config=_cfg_grafico())]),
        card([label("* Ultimas 25 SENALes"),
              tabla(["Dia","Hora","Tipo","Simbolo","Plazo","Spread","Accion"], filas, col_colors=[None,None,c_tipo,None,None,c_sp,None])]),
        card([
            label("* SENALes de Caucion no ejecutadas"),
            (tabla(
                ["Dia", "Hora", "Simbolo", "Spread", "Causa"],
                pendientes_rows[:30],
                col_colors=[None, None, None, c_sp, None]
            ) if pendientes_rows else html.Div(
                "No hay SENALes de cauciones pendientes de ejecucion en el periodo.",
                style={"color":C["sub"],"padding":"10px","font-size":"11px"}
            ))
        ]),
    ])


#    MAIN                                                          

if __name__ == "__main__":
    print("="*55)
    print("  BOT ARBITRAJE - CENTRO DE CONTROL")
    print("  http://127.0.0.1:8050")
    print("  Ctrl+C para cerrar")
    print("="*55)
    app.run(debug=False, port=8050)








