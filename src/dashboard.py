#!/usr/bin/env python
"""Dashboard interactivo de costumbres de compra y evolución de precios de Mercadona."""
import sys
from pathlib import Path
from datetime import datetime

# Asegurar que el directorio del proyecto está en el path
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, dcc, html, dash_table, Input, Output, State, no_update
import dash
import dash_bootstrap_components as dbc
import sqlite3
import threading
import time
import base64
import urllib.parse
from pathlib import Path as PathLib

from src.database import DB_PATH, init_db
from src.normalize import normalize_all_in_db
from src.config import load_accounts, add_account, remove_account, test_account
from src.ingest import run_ingestion
from src.catalog import update_catalog

# Directorio de PDFs
PDF_DIR = PathLib(__file__).parent.parent / "data" / "raw_pdfs"


def load_data():
    """Carga todos los datos de SQLite en DataFrames."""
    conn = sqlite3.connect(str(DB_PATH))
    
    # Tickets
    df_tickets = pd.read_sql_query(
        "SELECT * FROM tickets ORDER BY fecha", conn
    )
    
    # Items
    df_items = pd.read_sql_query(
        """SELECT li.*, t.num_ticket, t.direccion, t.metodo_pago, t.total as ticket_total
           FROM line_items li 
           JOIN tickets t ON li.ticket_id = t.id
           ORDER BY li.fecha""", conn
    )
    conn.close()
    
    # Parse fechas
    df_tickets["fecha_dt"] = pd.to_datetime(
        df_tickets["fecha"], format="%d/%m/%Y %H:%M", errors="coerce"
    )
    df_items["fecha_dt"] = pd.to_datetime(
        df_items["fecha"], format="%d/%m/%Y %H:%M", errors="coerce"
    )
    df_tickets["fecha_short"] = df_tickets["fecha_dt"].dt.strftime("%d/%m/%Y")
    df_items["fecha_short"] = df_items["fecha_dt"].dt.strftime("%d/%m/%Y")
    
    return df_tickets, df_items


def create_app():
    """Crea y configura la app Dash."""
    # Asegurar que las tablas existen y normalizar
    init_db()
    normalize_all_in_db()
    
    df_tickets, df_items = load_data()
    
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.title = "Mercadona Dashboard"

    # Script para abrir enlaces de DataTable en nueva pestaña
    app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
            <script>
            // Abrir enlaces de la tabla de tickets en nueva pestaña
            document.addEventListener('click', function(e) {
                if (e.target.tagName === 'A' && e.target.getAttribute('href') 
                    && e.target.getAttribute('href').startsWith('/pdf/')) {
                    e.preventDefault();
                    window.open(e.target.getAttribute('href'), '_blank');
                }
            });
            </script>
        </footer>
    </body>
</html>"""

    # Endpoint para servir PDFs
    @app.server.route("/pdf/<path:filename>")
    def serve_pdf(filename):
        from flask import send_file, abort
        pdf_path = PDF_DIR / filename
        if not pdf_path.exists() or not pdf_path.is_file():
            abort(404)
        return send_file(str(pdf_path), mimetype="application/pdf")
    
    # Listas para filtros
    productos = sorted(df_items["descripcion"].unique())
    productos_norm = sorted(df_items["producto_norm"].dropna().unique())
    categorias = sorted(df_items["categoria"].dropna().unique())
    
    # Fechas min/max
    fecha_min = df_items["fecha_dt"].min()
    fecha_max = df_items["fecha_dt"].max()
    
    # KPIs globales
    total_gastado = df_tickets["total"].sum()
    num_compras = len(df_tickets)
    ticket_medio = total_gastado / num_compras if num_compras else 0
    producto_top = (
        df_items.groupby("descripcion")["importe"]
        .sum().idxmax() if len(df_items) else "N/A"
    )
    gasto_top = df_items.groupby("descripcion")["importe"].sum().max() if len(df_items) else 0
    
    app.layout = html.Div([
        dcc.Location(id="url", refresh=False),
        # Modal para visualizar PDFs de tickets
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(id="pdf-modal-title")),
                dbc.ModalBody(
                    html.Iframe(
                        id="pdf-iframe",
                        style={"width": "100%", "height": "70vh", "border": "none"},
                    )
                ),
                dbc.ModalFooter(
                    [
                        html.A(
                            "Descargar PDF", id="pdf-download-link",
                            href="#", target="_blank",
                            className="btn btn-outline-primary btn-sm",
                            style={"textDecoration": "none"},
                        ),
                        dbc.Button("Cerrar", id="pdf-close-btn", className="ms-2"),
                    ]
                ),
            ],
            id="pdf-modal",
            is_open=False,
            size="xl",
        ),
        html.Div([
            html.H1("🛒 Dashboard de Compras - Mercadona", 
                    style={"textAlign": "center", "color": "#2c3e50"}),
            html.P(f"Datos de {fecha_min.strftime('%d/%m/%Y')} a {fecha_max.strftime('%d/%m/%Y')} | "
                   f"{num_compras} tickets | {len(df_items)} productos",
                   style={"textAlign": "center", "color": "#7f8c8d", "marginBottom": "20px"}),
        ]),
        
        # Filtros globales
        html.Div([
            html.Div([
                html.Label("Rango de fechas:"),
                dcc.DatePickerRange(
                    id="date-range",
                    min_date_allowed=fecha_min.date(),
                    max_date_allowed=fecha_max.date(),
                    start_date=fecha_min.date(),
                    end_date=fecha_max.date(),
                    display_format="DD/MM/YYYY",
                ),
            ], style={"marginRight": "30px"}),
            html.Div([
                html.Label("Producto:"),
                dcc.Dropdown(
                    id="product-filter",
                    options=[{"label": p, "value": p} for p in productos],
                    placeholder="Selecciona un producto...",
                    style={"width": "300px"},
                ),
            ], style={"marginRight": "30px"}),
            html.Div([
                html.Label("Categoría:"),
                dcc.Dropdown(
                    id="category-filter",
                    options=[{"label": c, "value": c} for c in categorias],
                    placeholder="Todas las categorías...",
                    style={"width": "250px"},
                ),
            ]),
        ], style={"display": "flex", "justifyContent": "center", "marginBottom": "30px",
                   "padding": "15px", "backgroundColor": "#ecf0f1", "borderRadius": "10px"}),
        
        # KPIs
        html.Div(id="kpi-row", style={"display": "flex", "justifyContent": "center", 
                                       "gap": "20px", "marginBottom": "30px"}),
        
        # Tabs
        dcc.Tabs([
            dcc.Tab(label="📊 Resumen General", children=[
                html.Div([
                    dcc.Graph(id="graph-gasto-temporal"),
                    dcc.Graph(id="graph-gasto-categoria"),
                    dcc.Graph(id="graph-gasto-mes"),
                ], style={"padding": "20px"}),
            ]),
            dcc.Tab(label="📈 Evolución de Precios", children=[
                html.Div([
                    html.P("Selecciona un producto en el filtro de arriba para ver la evolución de su precio.",
                           style={"color": "#7f8c8d", "marginBottom": "15px"}),
                    dcc.Graph(id="graph-precio-evolucion"),
                    dcc.Graph(id="graph-ranking-productos"),
                ], style={"padding": "20px"}),
            ]),
            dcc.Tab(label="🛍️ Hábitos de Compra", children=[
                html.Div([
                    dcc.Graph(id="graph-frecuencia-compra"),
                    dcc.Graph(id="graph-distribucion-categoria"),
                    dcc.Graph(id="graph-ticket-composicion"),
                ], style={"padding": "20px"}),
            ]),
            dcc.Tab(label="🏆 Ranking de Productos", children=[
                html.Div([
                    dash_table.DataTable(
                        id="table-ranking",
                        sort_action="native",
                        sort_mode="multi",
                        filter_action="native",
                        page_size=20,
                        style_table={"overflowX": "auto"},
                        style_header={
                            "backgroundColor": "#2c3e50",
                            "color": "white",
                            "fontWeight": "bold",
                        },
                        style_cell={"textAlign": "left", "padding": "8px"},
                        style_data_conditional=[
                            {
                                "if": {"column_id": "gasto_total"},
                                "textAlign": "right",
                            },
                        ],
                    ),
                ], style={"padding": "20px"}),
            ]),
            dcc.Tab(label="🧾 Historial de Tickets", children=[
                html.Div([
                    html.P("💡 Haz click en una fila para ver el detalle del ticket.",
                           style={"color": "#7f8c8d", "marginBottom": "10px"}),
                    dash_table.DataTable(
                        id="table-tickets",
                        sort_action="native",
                        sort_mode="multi",
                        filter_action="native",
                        page_size=20,
                        style_table={"overflowX": "auto"},
                        style_header={
                            "backgroundColor": "#2c3e50",
                            "color": "white",
                            "fontWeight": "bold",
                        },
                        style_cell={"textAlign": "left", "padding": "8px"},
                    ),
                    html.Div(id="ticket-detail", style={"marginTop": "20px"}),
                ], style={"padding": "20px"}),
            ]),
            dcc.Tab(label="📥 Ingesta", children=[
                html.Div([
                    html.H3("Ingesta Incremental de Tickets", style={"color": "#2c3e50"}),
                    html.P("Descarga nuevos tickets de Mercadona desde las cuentas configuradas, "
                           "los parsea y los añade a la base de datos. Solo procesa PDFs que no "
                           "estaban ya descargados.",
                           style={"color": "#7f8c8d"}),
                    html.Div([
                        html.Button("🚀 Iniciar Ingesta", id="ingest-btn", n_clicks=0,
                                    style={"backgroundColor": "#27ae60", "color": "white",
                                           "border": "none", "padding": "12px 30px",
                                           "borderRadius": "8px", "fontSize": "16px",
                                           "cursor": "pointer", "fontWeight": "bold"}),
                        html.Span(id="ingest-status", style={"marginLeft": "15px",
                                   "fontSize": "16px", "fontWeight": "bold"}),
                    ], style={"marginBottom": "20px", "display": "flex", "alignItems": "center"}),
                    dcc.Interval(id="ingest-interval", interval=1000, n_intervals=0, disabled=True),
                    dcc.Store(id="ingest-running", data=False),
                    html.Div(id="ingest-log", style={
                        "backgroundColor": "#1e1e1e", "color": "#00ff00",
                        "padding": "15px", "borderRadius": "10px",
                        "fontFamily": "monospace", "fontSize": "13px",
                        "minHeight": "200px", "maxHeight": "400px",
                        "overflowY": "auto", "whiteSpace": "pre-wrap",
                        "marginBottom": "15px",
                    }),
                    html.Div(id="ingest-result", style={"padding": "10px"}),
                ], style={"padding": "20px"}),
            ]),
            dcc.Tab(label="⚙️ Configuración", children=[
                html.Div([
                    html.H3("Cuentas de Email", style={"color": "#2c3e50"}),
                    html.P("Configura las cuentas de email desde las que se descargan los tickets "
                           "de Mercadona. Soporta cuentas de Gmail con contraseña de aplicación.",
                           style={"color": "#7f8c8d", "marginBottom": "20px"}),

                    # Lista de cuentas existentes
                    html.Div(id="accounts-list", style={"marginBottom": "30px"}),

                    # Formulario para añadir cuenta
                    html.H4("Añadir nueva cuenta", style={"color": "#2c3e50", "marginTop": "20px"}),
                    html.Div([
                        html.Div([
                            html.Label("Email:"),
                            dcc.Input(id="new-email", type="email",
                                      placeholder="usuario@gmail.com",
                                      style={"width": "100%", "padding": "8px",
                                             "marginBottom": "10px", "borderRadius": "5px",
                                             "border": "1px solid #bdc3c7"}),
                        ], style={"width": "48%", "display": "inline-block",
                                   "marginRight": "4%"}),
                        html.Div([
                            html.Label("Contraseña de aplicación:"),
                            dcc.Input(id="new-password", type="password",
                                      placeholder="xxxx xxxx xxxx xxxx",
                                      style={"width": "100%", "padding": "8px",
                                             "marginBottom": "10px", "borderRadius": "5px",
                                             "border": "1px solid #bdc3c7"}),
                        ], style={"width": "48%", "display": "inline-block"}),
                    ]),
                    html.Div([
                        html.Div([
                            html.Label("Etiqueta (opcional):"),
                            dcc.Input(id="new-label", type="text",
                                      placeholder="Ej: Gmail personal",
                                      style={"width": "100%", "padding": "8px",
                                             "marginBottom": "10px", "borderRadius": "5px",
                                             "border": "1px solid #bdc3c7"}),
                        ], style={"width": "31%", "display": "inline-block",
                                   "marginRight": "3%"}),
                        html.Div([
                            html.Label("Servidor IMAP:"),
                            dcc.Input(id="new-imap-host", type="text",
                                      value="imap.gmail.com",
                                      style={"width": "100%", "padding": "8px",
                                             "marginBottom": "10px", "borderRadius": "5px",
                                             "border": "1px solid #bdc3c7"}),
                        ], style={"width": "31%", "display": "inline-block",
                                   "marginRight": "3%"}),
                        html.Div([
                            html.Label("Puerto IMAP:"),
                            dcc.Input(id="new-imap-port", type="number",
                                      value=993,
                                      style={"width": "100%", "padding": "8px",
                                             "marginBottom": "10px", "borderRadius": "5px",
                                             "border": "1px solid #bdc3c7"}),
                        ], style={"width": "28%", "display": "inline-block"}),
                    ]),
                    html.Div([
                        html.Button("✚ Añadir cuenta", id="add-account-btn", n_clicks=0,
                                    style={"backgroundColor": "#3498db", "color": "white",
                                           "border": "none", "padding": "10px 20px",
                                           "borderRadius": "5px", "cursor": "pointer",
                                           "marginRight": "10px"}),
                        html.Button("🔌 Probar conexión", id="test-account-btn", n_clicks=0,
                                    style={"backgroundColor": "#f39c12", "color": "white",
                                           "border": "none", "padding": "10px 20px",
                                           "borderRadius": "5px", "cursor": "pointer"}),
                    ], style={"marginBottom": "10px"}),
                    html.Div(id="account-feedback", style={
                        "padding": "10px", "marginTop": "10px",
                        "borderRadius": "5px",
                    }),
                ], style={"padding": "20px"}),
            ]),
        ]),
        
        html.Div([
            html.P("Dashboard de Mercadona - Generado desde tickets digitales por email",
                   style={"textAlign": "center", "color": "#bdc3c7", "marginTop": "30px"}),
        ]),
    ])
    
    # === CALLBACKS ===
    
    @app.callback(
        [Output("kpi-row", "children"),
         Output("graph-gasto-temporal", "figure"),
         Output("graph-gasto-categoria", "figure"),
         Output("graph-gasto-mes", "figure"),
         Output("graph-precio-evolucion", "figure"),
         Output("graph-ranking-productos", "figure"),
         Output("graph-frecuencia-compra", "figure"),
         Output("graph-distribucion-categoria", "figure"),
         Output("graph-ticket-composicion", "figure"),
         Output("table-ranking", "data"),
         Output("table-ranking", "columns"),
         Output("table-tickets", "data"),
         Output("table-tickets", "columns")],
        [Input("date-range", "start_date"),
         Input("date-range", "end_date"),
         Input("product-filter", "value"),
         Input("category-filter", "value")]
    )
    def update_dashboard(start_date, end_date, product_sel, cat_sel):
        # Filtrar por fechas
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        
        mask = (df_items["fecha_dt"] >= start_dt) & (df_items["fecha_dt"] < end_dt)
        if cat_sel:
            mask = mask & (df_items["categoria"] == cat_sel)
        if product_sel:
            mask = mask & (df_items["descripcion"] == product_sel)
        df_filt = df_items[mask].copy()
        
        # Para tickets: si hay filtro de producto o categoría, solo mostrar
        # tickets que contienen esos items
        if product_sel or cat_sel:
            ticket_ids_with_items = df_filt["ticket_id"].unique()
            df_tk_filt = df_tickets[
                (df_tickets["fecha_dt"] >= start_dt) & 
                (df_tickets["fecha_dt"] < end_dt) &
                (df_tickets["id"].isin(ticket_ids_with_items))
            ].copy()
        else:
            df_tk_filt = df_tickets[
                (df_tickets["fecha_dt"] >= start_dt) & 
                (df_tickets["fecha_dt"] < end_dt)
            ].copy()
        
        # KPIs
        total_g = df_filt["importe"].sum()
        n_compras = df_tk_filt.shape[0]
        t_medio = total_g / n_compras if n_compras else 0
        n_productos = df_filt["descripcion"].nunique()
        
        kpi_box_style = {
            "backgroundColor": "#2c3e50", "color": "white", "padding": "20px 30px",
            "borderRadius": "10px", "textAlign": "center", "minWidth": "180px",
        }
        kpis = [
            html.Div([html.H3(f"{total_g:.2f} €"), html.P("Gasto total")], style=kpi_box_style),
            html.Div([html.H3(str(n_compras)), html.P("Compras")], style=kpi_box_style),
            html.Div([html.H3(f"{t_medio:.2f} €"), html.P("Ticket medio")], style=kpi_box_style),
            html.Div([html.H3(str(n_productos)), html.P("Productos únicos")], style=kpi_box_style),
        ]
        
        # --- Graph 1: Gasto temporal ---
        # Si hay filtro de producto, mostrar gasto del item (importe), no total del ticket
        if product_sel:
            gasto_por_fecha = df_filt.groupby("fecha_dt")["importe"].sum().reset_index()
            gasto_por_fecha.columns = ["fecha_dt", "total"]
            yaxis_title = "€ (gasto en producto)"
            trace_name = f"Gasto en {product_sel}"
        else:
            gasto_por_fecha = df_tk_filt.groupby("fecha_dt")["total"].sum().reset_index()
            yaxis_title = "€"
            trace_name = "Gasto por compra"
        gasto_por_fecha["media_movil"] = gasto_por_fecha["total"].rolling(
            window=3, min_periods=1).mean()
        fig_gasto_temp = go.Figure()
        fig_gasto_temp.add_trace(go.Bar(
            x=gasto_por_fecha["fecha_dt"], y=gasto_por_fecha["total"],
            name=trace_name, marker_color="#3498db", opacity=0.7
        ))
        fig_gasto_temp.add_trace(go.Scatter(
            x=gasto_por_fecha["fecha_dt"], y=gasto_por_fecha["media_movil"],
            name="Media móvil (3)", line=dict(color="#e74c3c", width=2)
        ))
        fig_gasto_temp.update_layout(
            title="Gasto por compra a lo largo del tiempo (click en una barra para ver el ticket)",
            xaxis_title="Fecha", yaxis_title=yaxis_title, template="plotly_white",
            height=400,
            clickmode="event+select",
        )
        
        # --- Graph 2: Gasto por categoría ---
        gasto_cat = df_filt.groupby("categoria")["importe"].sum().reset_index()
        gasto_cat = gasto_cat.sort_values("importe", ascending=True)
        fig_gasto_cat = px.bar(
            gasto_cat, x="importe", y="categoria", orientation="h",
            title="Gasto por categoría", color="importe",
            color_continuous_scale="Viridis",
            labels={"importe": "€", "categoria": "Categoría"},
        )
        fig_gasto_cat.update_layout(height=400, template="plotly_white",
                                     showlegend=False)
        
        # --- Graph 3: Gasto por mes ---
        # Si hay filtro de producto, usar importe del item; si no, total del ticket
        if product_sel:
            df_mes = df_filt.copy()
            df_mes["mes"] = df_mes["fecha_dt"].dt.to_period("M").astype(str)
            gasto_mes = df_mes.groupby("mes").agg(
                total=("importe", "sum"), compras=("importe", "count")
            ).reset_index()
            mes_title = f"Gasto mensual en {product_sel}"
        else:
            df_tk_filt_copy = df_tk_filt.copy()
            df_tk_filt_copy["mes"] = df_tk_filt_copy["fecha_dt"].dt.to_period("M").astype(str)
            gasto_mes = df_tk_filt_copy.groupby("mes").agg(
                total=("total", "sum"), compras=("total", "count")
            ).reset_index()
            mes_title = "Gasto mensual"
        fig_gasto_mes = px.bar(
            gasto_mes, x="mes", y="total", text="total",
            title=mes_title, labels={"mes": "Mes", "total": "€"},
            color="total", color_continuous_scale="Blues",
        )
        fig_gasto_mes.update_traces(texttemplate="%{text:.2f}€", textposition="outside")
        fig_gasto_mes.update_layout(height=400, template="plotly_white", showlegend=False)
        
        # --- Graph 4: Evolución de precios ---
        if product_sel:
            prod_data = df_filt[df_filt["descripcion"] == product_sel].copy()
            prod_data = prod_data.sort_values("fecha_dt")
            fig_precio = go.Figure()
            # Mostrar precio unitario con información de cantidad e importe
            hover_text = [
                f"{row.fecha_short}<br>Precio: {row.precio_unit:.2f}€<br>"
                f"Cant: {row.cantidad} | Importe: {row.importe:.2f}€"
                for row in prod_data.itertuples()
            ]
            fig_precio.add_trace(go.Scatter(
                x=prod_data["fecha_dt"], y=prod_data["precio_unit"],
                mode="lines+markers+text", name="Precio unitario",
                text=prod_data["fecha_short"], textposition="top center",
                hovertext=hover_text, hoverinfo="text",
                line=dict(color="#e74c3c", width=2),
                marker=dict(size=8),
            ))
            if len(prod_data) > 1:
                precio_inicial = prod_data["precio_unit"].iloc[0]
                precio_final = prod_data["precio_unit"].iloc[-1]
                if precio_inicial > 0:
                    variacion = ((precio_final - precio_inicial) / precio_inicial) * 100
                    titulo = f"Evolución de precio: {product_sel} ({variacion:+.1f}%)"
                else:
                    titulo = f"Evolución de precio: {product_sel}"
            else:
                titulo = f"Precio de: {product_sel} (1 compra)"
            fig_precio.update_layout(
                title=titulo, xaxis_title="Fecha", yaxis_title="Precio unitario (€)",
                template="plotly_white", height=400,
                hovermode="closest",
            )
        else:
            # Mostrar top productos con más variación de precio
            # Usar importe/cantidad como precio unitario real para evitar
            # que packs vs unidades del mismo nombre generen variaciones falsas
            df_price = df_filt[df_filt["cantidad"] > 0].copy()
            df_price["precio_real"] = df_price["importe"] / df_price["cantidad"]
            price_stats = df_price.groupby("descripcion").agg(
                precio_min=("precio_real", "min"),
                precio_max=("precio_real", "max"),
                precio_medio=("precio_real", "mean"),
                n_compras=("precio_real", "count"),
            ).reset_index()
            price_stats["variacion_pct"] = (
                (price_stats["precio_max"] - price_stats["precio_min"]) 
                / price_stats["precio_min"] * 100
            )
            # Filtrar variaciones irreales (>100%) que indican formatos diferentes
            # con el mismo nombre (pack vs unidad, lata vs botella, etc.)
            price_stats = price_stats[
                (price_stats["n_compras"] >= 2) & 
                (price_stats["variacion_pct"] <= 100)
            ]
            price_stats = price_stats.sort_values("variacion_pct", ascending=False).head(15)
            fig_precio = px.bar(
                price_stats, x="descripcion", y="variacion_pct",
                title="Top 15 productos con mayor variación de precio (%)",
                labels={"descripcion": "Producto", "variacion_pct": "Variación (%)"},
                color="variacion_pct", color_continuous_scale="RdYlGn_r",
            )
            fig_precio.update_layout(height=400, template="plotly_white",
                                       xaxis_tickangle=-45)
        
        # --- Graph 5: Ranking de productos por gasto ---
        ranking = df_filt.groupby("descripcion").agg(
            gasto_total=("importe", "sum"),
            veces=("importe", "count"),
            precio_medio=("precio_unit", "mean"),
        ).reset_index().sort_values("gasto_total", ascending=False).head(20)
        fig_ranking = px.bar(
            ranking, x="gasto_total", y="descripcion", orientation="h",
            title="Top 20 productos por gasto total",
            labels={"gasto_total": "€", "descripcion": ""},
            color="gasto_total", color_continuous_scale="Tealgrn",
        )
        fig_ranking.update_layout(height=500, template="plotly_white", showlegend=False,
                                   yaxis=dict(autorange="reversed"))
        
        # --- Graph 6: Frecuencia de compra ---
        freq = df_tk_filt.copy()
        freq["semana"] = freq["fecha_dt"].dt.isocalendar().week.astype(str) + "/" + \
                         freq["fecha_dt"].dt.isocalendar().year.astype(str)
        freq_by_week = freq.groupby("semana").size().reset_index(name="compras")
        fig_freq = px.bar(
            freq_by_week, x="semana", y="compras",
            title="Frecuencia de compra por semana",
            labels={"semana": "Semana", "compras": "Nº de compras"},
        )
        fig_freq.update_layout(height=400, template="plotly_white")
        
        # --- Graph 7: Distribución por categoría (pie) ---
        dist_cat = df_filt.groupby("categoria")["importe"].sum().reset_index()
        dist_cat = dist_cat.sort_values("importe", ascending=False)
        fig_dist = px.pie(
            dist_cat, values="importe", names="categoria",
            title="Distribución de gasto por categoría",
        )
        fig_dist.update_layout(height=400, template="plotly_white")
        
        # --- Graph 8: Composición de tickets (treemap) ---
        tree_data = df_filt.groupby(["categoria", "descripcion"])["importe"].sum().reset_index()
        fig_tree = px.treemap(
            tree_data, path=["categoria", "descripcion"], values="importe",
            title="Composición del gasto (treemap)",
        )
        fig_tree.update_layout(height=500, template="plotly_white")
        
        # --- Table: Ranking ---
        ranking_table = df_filt.groupby(["descripcion", "categoria"]).agg(
            veces_comprado=("importe", "count"),
            unidades=("cantidad", "sum"),
            gasto_total=("importe", "sum"),
            precio_medio=("precio_unit", "mean"),
            precio_min=("precio_unit", "min"),
            precio_max=("precio_unit", "max"),
        ).reset_index().sort_values("gasto_total", ascending=False)
        ranking_table["gasto_total"] = ranking_table["gasto_total"].round(2)
        ranking_table["precio_medio"] = ranking_table["precio_medio"].round(2)
        ranking_cols = [
            {"name": "Producto", "id": "descripcion"},
            {"name": "Categoría", "id": "categoria"},
            {"name": "Veces comprado", "id": "veces_comprado"},
            {"name": "Unidades", "id": "unidades"},
            {"name": "Gasto total (€)", "id": "gasto_total"},
            {"name": "Precio medio (€)", "id": "precio_medio"},
            {"name": "Precio min (€)", "id": "precio_min"},
            {"name": "Precio max (€)", "id": "precio_max"},
        ]
        ranking_data = ranking_table.to_dict("records")
        
        # --- Table: Tickets ---
        tickets_table = df_tk_filt[[
            "fecha_short", "num_ticket", "direccion", "total", "metodo_pago", "pdf_file"
        ]].copy()
        # Usar fecha ISO para que la ordenación alfanumérica funcione correctamente
        tickets_table["fecha_short"] = df_tk_filt["fecha_dt"].dt.strftime("%Y-%m-%d")
        # Crear enlace al PDF (link markdown que abre en nueva pestaña)
        def make_pdf_link(f):
            if not f:
                return ''
            encoded = urllib.parse.quote(f)
            return f'[🔗 Ver ticket](/pdf/{encoded})'
        tickets_table["pdf_link"] = tickets_table["pdf_file"].apply(make_pdf_link)
        # Guardar el nombre del PDF en una columna ocuta para el callback
        tickets_table["_pdf_file"] = tickets_table["pdf_file"]
        tickets_table = tickets_table.drop(columns=["pdf_file"])
        tickets_table.columns = ["Fecha", "Nº Ticket", "Tienda", "Total (€)", "Pago", "Ver ticket", "_pdf_file"]
        tickets_table["Total (€)"] = tickets_table["Total (€)"].round(2)
        # Ordenar por fecha descendente por defecto
        tickets_table = tickets_table.sort_values("Fecha", ascending=False)
        tickets_cols = [
            {"name": "Fecha", "id": "Fecha"},
            {"name": "Nº Ticket", "id": "Nº Ticket"},
            {"name": "Tienda", "id": "Tienda"},
            {"name": "Total (€)", "id": "Total (€)"},
            {"name": "Pago", "id": "Pago"},
            {"name": "Ver ticket", "id": "Ver ticket", "type": "text", "presentation": "markdown"},
            {"name": "", "id": "_pdf_file", "hidden": True},
        ]
        tickets_data = tickets_table.to_dict("records")
        
        return (kpis, fig_gasto_temp, fig_gasto_cat, fig_gasto_mes,
                fig_precio, fig_ranking, fig_freq, fig_dist, fig_tree,
                ranking_data, ranking_cols, tickets_data, tickets_cols)

    # === CALLBACK: Detalle del ticket al hacer click ===
    @app.callback(
        Output("ticket-detail", "children"),
        Input("table-tickets", "active_cell"),
        Input("date-range", "start_date"),
        Input("date-range", "end_date"),
    )
    def show_ticket_detail(active_cell, start_date, end_date):
        if active_cell is None:
            return html.Div(
                html.P("Selecciona un ticket haciendo click en cualquier fila de la tabla de arriba.",
                       style={"color": "#95a5a6", "fontStyle": "italic"}),
                style={"padding": "20px", "backgroundColor": "#ecf0f1",
                       "borderRadius": "10px", "textAlign": "center"},
            )

        # Get the row data for the clicked row
        row_idx = active_cell["row"]
        # Reconstruct the filtered tickets data to get the row
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        df_tk_filt = df_tickets[
            (df_tickets["fecha_dt"] >= start_dt) &
            (df_tickets["fecha_dt"] < end_dt)
        ].copy()

        if row_idx >= len(df_tk_filt):
            return html.P("No se pudo cargar el detalle del ticket.")

        ticket_row = df_tk_filt.iloc[row_idx]
        num_ticket = ticket_row["num_ticket"]

        # Get all items for this ticket
        ticket_items = df_items[df_items["num_ticket"] == num_ticket].copy()
        ticket_items = ticket_items.sort_values("importe", ascending=False)

        # Build detail panel
        detail_cols = ["cantidad", "descripcion", "categoria",
                       "precio_unit", "importe"]
        detail_rename = {
            "cantidad": "Cant.",
            "descripcion": "Producto (ticket)",
            "categoria": "Categoría",
            "precio_unit": "Precio unit. (€)",
            "importe": "Importe (€)",
        }
        # Añadir columnas del catálogo si existen
        if "catalog_name" in ticket_items.columns:
            detail_cols.extend(["catalog_name", "catalog_packaging", "catalog_size"])
            detail_rename["catalog_name"] = "Catálogo"
            detail_rename["catalog_packaging"] = "Formato"
            detail_rename["catalog_size"] = "Tamaño"

        items_table = dash_table.DataTable(
            data=ticket_items[detail_cols].rename(columns=detail_rename).round(
                {"Precio unit. (€)": 2, "Importe (€)": 2}).to_dict("records"),
            columns=[
                {"name": c, "id": c} for c in [detail_rename[c] for c in detail_cols]
            ],
            sort_action="native",
            page_size=50,
            style_table={"overflowX": "auto"},
            style_header={
                "backgroundColor": "#34495e",
                "color": "white",
                "fontWeight": "bold",
            },
            style_cell={"textAlign": "left", "padding": "6px", "fontSize": "13px"},
            style_data_conditional=[
                {"if": {"column_id": "Importe (€)"},
                 "textAlign": "right", "fontWeight": "bold"},
                {"if": {"column_id": "Precio unit. (€)"},
                 "textAlign": "right"},
                {"if": {"column_id": "Cant."}, "textAlign": "center"},
            ],
        )

        header_style = {
            "backgroundColor": "#2c3e50", "color": "white",
            "padding": "15px 20px", "borderRadius": "10px 10px 0 0",
        }
        body_style = {
            "backgroundColor": "#ffffff", "padding": "15px 20px",
            "border": "1px solid #bdc3c7", "borderTop": "none",
            "borderRadius": "0 0 10px 10px",
        }

        return html.Div([
            html.Div([
                html.H4(f"🧾 Ticket {num_ticket}", style={"margin": "0 0 5px 0"}),
                html.P([
                    html.Strong(f"{ticket_row['fecha']}"),
                    f" | {ticket_row['direccion']}",
                    f" | Pago: {ticket_row['metodo_pago']}",
                ], style={"margin": 0, "fontSize": "14px"}),
            ], style=header_style),
            html.Div([
                html.Div([
                    html.Span(f"Total: {ticket_row['total']:.2f} €",
                             style={"fontSize": "20px", "fontWeight": "bold",
                                    "color": "#e74c3c"}),
                    html.Span(f"  |  {len(ticket_items)} productos",
                             style={"fontSize": "14px", "color": "#7f8c8d",
                                    "marginLeft": "15px"}),
                ], style={"marginBottom": "15px"}),
                items_table,
            ], style=body_style),
        ], style={"maxWidth": "900px", "margin": "0 auto"})

    # === CALLBACK: Lista de cuentas en Configuración ===
    @app.callback(
        Output("accounts-list", "children"),
        Input("add-account-btn", "n_clicks"),
        Input("remove-account-btn", "n_clicks"),
        Input("url", "pathname"),
    )
    def update_accounts_list(add_clicks, remove_clicks, pathname):
        accounts = load_accounts()
        if not accounts:
            return html.Div(
                html.P("No hay cuentas configuradas. Añade una abajo.",
                       style={"color": "#95a5a6", "fontStyle": "italic"}),
                style={"padding": "15px", "backgroundColor": "#ecf0f1",
                       "borderRadius": "10px", "textAlign": "center"},
            )
        
        items = []
        for acc in accounts:
            items.append(html.Div([
                html.Div([
                    html.Strong(acc["label"], style={"fontSize": "15px"}),
                    html.Span(f"  ({acc['email']})", style={"color": "#7f8c8d",
                              "marginLeft": "10px"}),
                ], style={"flex": "1"}),
                html.Div([
                    html.Span(f"{acc['imap_host']}:{acc.get('imap_port', 993)}",
                              style={"color": "#95a5a6", "fontSize": "13px",
                                     "marginRight": "15px"}),
                    html.Button("🗑️ Eliminar", id={"type": "remove-btn",
                                                     "index": acc["email"]},
                                n_clicks=0,
                                style={"backgroundColor": "#e74c3c",
                                       "color": "white", "border": "none",
                                       "padding": "5px 12px", "borderRadius": "5px",
                                       "cursor": "pointer", "fontSize": "13px"}),
                ], style={"display": "flex", "alignItems": "center"}),
            ], style={"display": "flex", "justifyContent": "space-between",
                       "alignItems": "center", "padding": "12px 15px",
                       "backgroundColor": "#ffffff", "border": "1px solid #bdc3c7",
                       "borderRadius": "8px", "marginBottom": "8px"}))
        
        return html.Div(items)

    # === CALLBACK: Eliminar cuenta ===
    @app.callback(
        Output("account-feedback", "children", allow_duplicate=True),
        Input({"type": "remove-btn", "index": "all"}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_remove_account(n_clicks):
        ctx = dash.callback_context
        if not ctx.triggered:
            return ""
        triggered_id = ctx.triggered[0]["prop_id"]
        # Extraer el email del id del botón
        import json as _json
        try:
            prop_id, _ = triggered_id.rsplit(".", 1)
            id_dict = _json.loads(prop_id)
            email = id_dict["index"]
        except Exception:
            return ""
        
        ok = remove_account(email)
        if ok:
            return html.Div(f"✅ Cuenta {email} eliminada correctamente.",
                            style={"color": "#27ae60", "backgroundColor": "#d4edda",
                                   "padding": "10px", "borderRadius": "5px"})
        return html.Div(f"❌ No se pudo eliminar la cuenta {email}.",
                        style={"color": "#e74c3c", "backgroundColor": "#f8d7da",
                               "padding": "10px", "borderRadius": "5px"})

    # === CALLBACK: Añadir cuenta ===
    @app.callback(
        Output("account-feedback", "children"),
        Input("add-account-btn", "n_clicks"),
        State("new-email", "value"),
        State("new-password", "value"),
        State("new-label", "value"),
        State("new-imap-host", "value"),
        State("new-imap-port", "value"),
        prevent_initial_call=True,
    )
    def handle_add_account(n_clicks, email, password, label, imap_host, imap_port):
        if not n_clicks:
            return ""
        if not email or not password:
            return html.Div("⚠️ Email y contraseña son obligatorios.",
                            style={"color": "#856404", "backgroundColor": "#fff3cd",
                                   "padding": "10px", "borderRadius": "5px"})
        
        ok = add_account(email, password, label or "", 
                         imap_host or "imap.gmail.com",
                         imap_port or 993)
        if ok:
            return html.Div(f"✅ Cuenta {email} añadida correctamente.",
                            style={"color": "#27ae60", "backgroundColor": "#d4edda",
                                   "padding": "10px", "borderRadius": "5px"})
        return html.Div(f"❌ La cuenta {email} ya existe.",
                        style={"color": "#e74c3c", "backgroundColor": "#f8d7da",
                               "padding": "10px", "borderRadius": "5px"})

    # === CALLBACK: Probar conexión ===
    @app.callback(
        Output("account-feedback", "children", allow_duplicate=True),
        Input("test-account-btn", "n_clicks"),
        State("new-email", "value"),
        State("new-password", "value"),
        State("new-imap-host", "value"),
        State("new-imap-port", "value"),
        prevent_initial_call=True,
    )
    def handle_test_account(n_clicks, email, password, imap_host, imap_port):
        if not n_clicks:
            return ""
        if not email or not password:
            return html.Div("⚠️ Introduce email y contraseña para probar.",
                            style={"color": "#856404", "backgroundColor": "#fff3cd",
                                   "padding": "10px", "borderRadius": "5px"})
        
        ok, msg = test_account(email, password,
                               imap_host or "imap.gmail.com",
                               imap_port or 993)
        if ok:
            return html.Div(f"✅ {msg}",
                            style={"color": "#27ae60", "backgroundColor": "#d4edda",
                                   "padding": "10px", "borderRadius": "5px"})
        return html.Div(f"❌ {msg}",
                        style={"color": "#e74c3c", "backgroundColor": "#f8d7da",
                               "padding": "10px", "borderRadius": "5px"})

    # === CALLBACK: Ingesta con feedback en tiempo real ===
    # Estado compartido entre el hilo de ingesta y los callbacks de polling
    _ingest_state = {
        "running": False,
        "log_lines": [],
        "result": None,
        "start_time": None,
    }

    @app.callback(
        Output("ingest-log", "children"),
        Output("ingest-result", "children"),
        Output("ingest-running", "data"),
        Output("ingest-status", "children"),
        Output("ingest-btn", "disabled"),
        Output("ingest-interval", "disabled"),
        Input("ingest-btn", "n_clicks"),
        Input("ingest-interval", "n_intervals"),
        State("ingest-running", "data"),
        prevent_initial_call=True,
    )
    def handle_ingest(n_clicks, n_intervals, is_running):
        ctx = dash.callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        # Click del botón → iniciar ingesta en hilo separado
        if triggered_id == "ingest-btn" and not is_running:
            _ingest_state["running"] = True
            _ingest_state["log_lines"] = []
            _ingest_state["result"] = None
            _ingest_state["start_time"] = time.time()

            def progress_cb(msg):
                _ingest_state["log_lines"].append(msg)

            def run_thread():
                try:
                    result = run_ingestion(progress_cb)
                    _ingest_state["result"] = result
                except Exception as e:
                    _ingest_state["result"] = {"error": str(e)}
                finally:
                    _ingest_state["running"] = False

            thread = threading.Thread(target=run_thread, daemon=True)
            thread.start()

            # Devolver estado inicial: log vacío, interval activado
            return ("⏳ Iniciando ingesta...\n", "", True, "⏳ Procesando...", True, False)

        # Polling del interval → actualizar log en tiempo real
        if is_running or triggered_id == "ingest-interval":
            log_text = "\n".join(_ingest_state["log_lines"])

            # Si sigue corriendo, seguir polling
            if _ingest_state["running"]:
                elapsed = time.time() - _ingest_state["start_time"] if _ingest_state["start_time"] else 0
                return (log_text, "", True, f"⏳ Procesando... ({elapsed:.0f}s)", True, False)

            # Si terminó, mostrar resultado final
            result = _ingest_state["result"]
            if result and "error" in result:
                return (log_text, html.Div(
                    f"❌ {result['error']}",
                    style={"color": "#e74c3c", "backgroundColor": "#f8d7da",
                           "padding": "15px", "borderRadius": "8px"},
                ), False, "❌ Error", False, True)

            if result:
                summary = html.Div([
                    html.H4("✅ Ingesta completada", style={"color": "#27ae60"}),
                    html.Div([
                        html.Div([
                            html.H3(str(result["emails_found"])),
                            html.P("Emails encontrados"),
                        ], style={"backgroundColor": "#2c3e50", "color": "white",
                                  "padding": "15px 25px", "borderRadius": "8px",
                                  "textAlign": "center", "minWidth": "150px"}),
                        html.Div([
                            html.H3(str(result["pdfs_downloaded"])),
                            html.P("PDFs nuevos"),
                        ], style={"backgroundColor": "#2c3e50", "color": "white",
                                  "padding": "15px 25px", "borderRadius": "8px",
                                  "textAlign": "center", "minWidth": "150px"}),
                        html.Div([
                            html.H3(str(result["tickets_in_db"])),
                            html.P("Tickets en BD"),
                        ], style={"backgroundColor": "#2c3e50", "color": "white",
                                  "padding": "15px 25px", "borderRadius": "8px",
                                  "textAlign": "center", "minWidth": "150px"}),
                        html.Div([
                            html.H3(f"{result['total_gastado']:.2f} €"),
                            html.P("Total gastado"),
                        ], style={"backgroundColor": "#2c3e50", "color": "white",
                                  "padding": "15px 25px", "borderRadius": "8px",
                                  "textAlign": "center", "minWidth": "150px"}),
                    ], style={"display": "flex", "gap": "15px", "marginBottom": "15px"}),
                ])

                if result.get("errors"):
                    summary.children.append(html.Div([
                        html.P("⚠️ Errores:", style={"fontWeight": "bold", "color": "#e74c3c"}),
                        *[html.P(f"  • {e}", style={"color": "#e74c3c", "fontSize": "13px"})
                          for e in result["errors"]],
                    ]))

                if result.get("new_pdf_files"):
                    summary.children.append(html.Div([
                        html.P(f"PDFs nuevos ({len(result['new_pdf_files'])}):",
                               style={"fontWeight": "bold", "color": "#27ae60",
                                      "marginTop": "10px"}),
                        *[html.P(f"  📄 {f}", style={"fontSize": "13px", "color": "#7f8c8d"})
                          for f in result["new_pdf_files"][:20]],
                    ]))
                    if len(result["new_pdf_files"]) > 20:
                        summary.children.append(
                            html.P(f"  ... y {len(result['new_pdf_files'])-20} más",
                                   style={"fontSize": "13px", "color": "#7f8c8d"})
                        )

                elapsed = time.time() - _ingest_state["start_time"] if _ingest_state["start_time"] else 0
                return (log_text, summary, False, f"✅ Completado ({elapsed:.0f}s)", False, True)

            # No debería llegar aquí, pero por seguridad
            return (log_text, "", False, "", False, True)

        return no_update, no_update, no_update, no_update, no_update, no_update

    # === CALLBACK: Click en gráfica de gasto temporal → mostrar PDF ===
    @app.callback(
        [Output("pdf-modal", "is_open"),
         Output("pdf-iframe", "src"),
         Output("pdf-modal-title", "children"),
         Output("pdf-download-link", "href")],
        [Input("graph-gasto-temporal", "clickData"),
         Input("pdf-close-btn", "n_clicks")],
        [State("pdf-modal", "is_open")],
        prevent_initial_call=True,
    )
    def handle_pdf_click(clickData, close_n, is_open):
        ctx = dash.callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        # Cerrar modal
        if triggered_id == "pdf-close-btn":
            return False, "", "", "#"

        if not clickData:
            return no_update, no_update, no_update, no_update

        # Obtener la fecha del punto clickado
        point = clickData["points"][0]
        click_date = point["x"]

        # Buscar el ticket de esa fecha
        import datetime
        try:
            dt = pd.to_datetime(click_date)
        except Exception:
            return no_update, no_update, no_update, no_update

        # Buscar tickets de esa fecha (puede haber varios)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT t.id, t.fecha, t.total, t.pdf_file
               FROM tickets t
               WHERE t.pdf_file IS NOT NULL
               ORDER BY t.fecha""",
            ()
        ).fetchall()
        conn.close()

        # Encontrar el ticket cuya fecha coincide con el día clickado
        matching = []
        for r in rows:
            try:
                ticket_dt = pd.to_datetime(r["fecha"], format="%d/%m/%Y %H:%M")
                if ticket_dt.date() == dt.date():
                    matching.append(r)
            except Exception:
                continue

        if not matching:
            return True, "", "No se encontró PDF para esta fecha", "#"

        # Si hay varios, usar el primero (o se podría elegir)
        ticket = matching[0]
        pdf_file = ticket["pdf_file"]
        pdf_url = f"/pdf/{pdf_file}"

        title = f"Ticket {ticket['fecha']} - {ticket['total']:.2f}€"
        if len(matching) > 1:
            title += f" ({len(matching)} tickets ese día, mostrando el primero)"

        return True, pdf_url, title, pdf_url

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=8050)