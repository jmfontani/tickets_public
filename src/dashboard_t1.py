#!/usr/bin/env python3
"""Dashboard Streamlit de tickets de compra — multi-tienda, drill-down, dark mode configurable."""
import sys
from pathlib import Path

# Path del proyecto
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_option_menu import option_menu

from src.data_loader import (
    load_data, filter_data, get_stores, get_categories,
    get_subcategories, get_products,
)

# ============================================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================================

st.set_page_config(
    page_title="Dashboard de Compras",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)


# === T1 MOCKUP: CSS TOKENS + TARJETAS ===
def inject_css():
    dark = st.session_state.get("dark_mode", True)
    bg      = "#0e1117" if dark else "#f4f6f8"
    card    = "#1e1e2e" if dark else "#ffffff"
    text    = "#ffffff" if dark else "#22262a"
    muted   = "#8a8f98" if dark else "#6c757d"
    border  = "#2b2b3d" if dark else "#e3e6e8"
    accent  = "#2f9e6e"
    st.markdown(f"""
<style>
:root {{
  --bg:{bg}; --card:{card}; --text:{text}; --muted:{muted};
  --border:{border}; --accent:{accent};
}}
div.block-container {{ padding-top: 1.2rem; }}
.stApp {{ background: var(--bg); color: var(--text); }}
h1, h2, h3 {{ color: var(--text); font-weight: 650; letter-spacing:.2px }}
[data-testid="stMetric"] {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 1rem 1.1rem;
  box-shadow: 0 1px 2px rgba(0,0,0,.18);
  transition: transform .15s ease, box-shadow .15s ease;
}}
[data-testid="stMetric"]:hover {{ transform: translateY(-2px); box-shadow: 0 4px 10px rgba(0,0,0,.25) }}
[data-testid="stMetricLabel"] p {{ color: var(--muted); font-size: .85rem }}
[data-testid="stMetricValue"] {{ color: var(--text); font-weight:700 }}
[data-testid="stMetricDelta"] {{ font-weight: 600 }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow:hidden }}
[data-testid="stSidebar"] {{ background: {("#171724" if dark else "#ffffff")}; border-right:1px solid {border} }}
[data-testid="stSidebar"] hr {{ border-color:{border} }}
div[data-testid="stExpander"] {{ background: var(--card); border:1px solid var(--border); border-radius:12px }}
.stTabs [data-baseweb="tab"] {{ color: var(--muted) }}
.stTabs [aria-selected="true"] {{ color: var(--accent) }}
div[data-baseweb="input"], div[data-baseweb="select"] > div {{
  border-color: var(--border) !important; border-radius: 10px !important
}}
.element-container:has([data-testid="stToggleButton"]) {{ margin-bottom: 0 }}
</style>
""", unsafe_allow_html=True)

inject_css()


# ============================================================================
# TEMA / DARK MODE
# ============================================================================

def init_theme():
    """Inicializa el tema del usuario."""
    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = True

def get_plotly_template() -> str:
    """Devuelve el template de Plotly según el modo."""
    return "plotly_dark" if st.session_state.dark_mode else "plotly_white"

def get_bg_color() -> str:
    return "#0e1117" if st.session_state.dark_mode else "#ffffff"

def get_card_color() -> str:
    return "#1e1e2e" if st.session_state.dark_mode else "#f8f9fa"

def get_text_color() -> str:
    return "#ffffff" if st.session_state.dark_mode else "#2c3e50"

def get_muted_color() -> str:
    return "#888" if st.session_state.dark_mode else "#7f8c8d"

# ============================================================================
# CARGA DE DATOS (CACHEADA)
# ============================================================================

@st.cache_data(ttl=60)
def get_data():
    return load_data()

# ============================================================================
# SIDEBAR: FILTROS GLOBALES
# ============================================================================

def render_sidebar(df_tickets, df_items):
    """Renderiza la sidebar con filtros globales y configuración."""
    init_theme()

    with st.sidebar:
        # Dark mode toggle
        st.session_state.dark_mode = st.toggle(
            "🌙 Dark Mode",
            value=st.session_state.dark_mode,
        )

        st.divider()

        st.markdown("### 🎛️ Filtros")

        # Rango de fechas
        fecha_min = df_items["fecha_dt"].min().date()
        fecha_max = df_items["fecha_dt"].max().date()
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Desde", value=fecha_min, min_value=fecha_min, max_value=fecha_max)
        with col2:
            end_date = st.date_input("Hasta", value=fecha_max, min_value=fecha_min, max_value=fecha_max)

        # Tienda
        stores = get_stores(df_tickets)
        store_sel = st.selectbox("🏪 Establecimiento", ["Todas"] + stores)

        # Categoría
        cats = get_categories(df_items)
        cat_sel = st.selectbox("📂 Categoría", ["Todas"] + cats)

        # Subcategoría (depende de categoría)
        if cat_sel != "Todas":
            subcats = get_subcategories(df_items, cat_sel)
            subcat_sel = st.selectbox("📎 Subcategoría", ["Todas"] + subcats)
        else:
            subcat_sel = "Todas"

        st.divider()

        # Info de datos
        st.markdown("### 📊 Datos")
        st.metric("Tickets", len(df_tickets))
        st.metric("Items", len(df_items))
        st.metric("Productos únicos", df_items["descripcion"].nunique())

    return str(start_date), str(end_date), store_sel, cat_sel, subcat_sel


# ============================================================================
# KPI CARDS
# ============================================================================

def render_kpis(df_t, df_i, start_date, end_date):
    """Renderiza KPIs con comparativa vs periodo anterior."""
    template = get_plotly_template()

    # Periodo actual
    total_gasto = df_i["importe"].sum()
    n_compras = len(df_t)
    ticket_medio = total_gasto / n_compras if n_compras else 0
    n_productos = df_i["descripcion"].nunique()

    # Periodo anterior (misma duración)
    sd = pd.to_datetime(start_date)
    ed = pd.to_datetime(end_date)
    duracion = ed - sd
    prev_end = sd
    prev_start = sd - duracion

    df_t_full, df_i_full = get_data()
    mask_prev_t = (df_t_full["fecha_dt"] >= prev_start) & (df_t_full["fecha_dt"] < prev_end)
    df_t_prev = df_t_full[mask_prev_t]
    mask_prev_i = (df_i_full["fecha_dt"] >= prev_start) & (df_i_full["fecha_dt"] < prev_end)
    df_i_prev = df_i_full[mask_prev_i]

    total_prev = df_i_prev["importe"].sum()
    n_prev = len(df_t_prev)
    ticket_prev = total_prev / n_prev if n_prev else 0

    # Deltas
    delta_gasto = ((total_gasto - total_prev) / total_prev * 100) if total_prev else 0
    delta_n = ((n_compras - n_prev) / n_prev * 100) if n_prev else 0
    delta_ticket = ((ticket_medio - ticket_prev) / ticket_prev * 100) if ticket_prev else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("💰 Gasto total", f"{total_gasto:.2f} €", f"{delta_gasto:+.1f}% vs anterior")
    with col2:
        st.metric("🛒 Compras", str(n_compras), f"{delta_n:+.1f}% vs anterior")
    with col3:
        st.metric("🧾 Ticket medio", f"{ticket_medio:.2f} €", f"{delta_ticket:+.1f}% vs anterior")
    with col4:
        st.metric("📦 Productos únicos", str(n_productos))


# ============================================================================
# VISTA: PANEL DE CONTROL
# ============================================================================

def view_dashboard(df_t, df_i, start_date, end_date):
    """Vista principal con KPIs y resumen."""
    st.markdown("# 📊 Panel de Control")

    render_kpis(df_t, df_i, start_date, end_date)

    st.divider()

    template = get_plotly_template()

    col1, col2 = st.columns(2)

    with col1:
        # Gasto mensual
        gasto_mes = df_i.groupby("mes").agg(
            total=("importe", "sum"),
            compras=("importe", "count"),
        ).reset_index()

        fig = px.bar(
            gasto_mes, x="mes", y="total",
            title="Gasto mensual",
            labels={"mes": "Mes", "total": "€"},
            color="total", color_continuous_scale="Blues",
            template=template,
        )
        fig.update_layout(height=350, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Gasto por categoría (top 5)
        gasto_cat = df_i.groupby("cat_display")["importe"].sum().reset_index()
        gasto_cat = gasto_cat.sort_values("importe", ascending=False).head(5)

        fig = px.bar(
            gasto_cat, x="importe", y="cat_display", orientation="h",
            title="Top 5 categorías por gasto",
            labels={"importe": "€", "cat_display": ""},
            color="importe", color_continuous_scale="Tealgrn",
            template=template,
        )
        fig.update_layout(height=350, showlegend=False, yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    # Treemap categoría → subcategoría
    tree = df_i.groupby(["cat_display", "subcat_display"])["importe"].sum().reset_index()
    fig_tree = px.treemap(
        tree, path=["cat_display", "subcat_display"], values="importe",
        title="Composición del gasto por categoría y subcategoría",
        template=template,
    )
    fig_tree.update_layout(height=450)
    st.plotly_chart(fig_tree, use_container_width=True)


# ============================================================================
# VISTA: POR ESTABLECIMIENTO
# ============================================================================

def view_establecimiento(df_t, df_i, start_date, end_date):
    """Vista por tienda/establecimiento."""
    st.markdown("# 🏪 Por Establecimiento")

    template = get_plotly_template()

    # Resumen por cadena de tienda
    resumen = df_t.groupby("tienda_nombre").agg(
        tickets=("id", "count"),
        gasto=("total", "sum"),
        ticket_medio=("total", "mean"),
    ).reset_index()
    resumen = resumen.sort_values("gasto", ascending=False)
    resumen["% del total"] = (resumen["gasto"] / resumen["gasto"].sum() * 100).round(1)

    col1, col2 = st.columns([2, 1])

    with col1:
        fig = px.bar(
            resumen, x="gasto", y="tienda_nombre", orientation="h",
            title="Gasto por establecimiento",
            labels={"gasto": "€", "tienda_nombre": ""},
            color="gasto", color_continuous_scale="Viridis",
            template=template,
        )
        fig.update_layout(height=400, showlegend=False, yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("### Resumen")
        st.dataframe(
            resumen.style.format({
                "gasto": "{:.2f} €",
                "ticket_medio": "{:.2f} €",
                "% del total": "{:.1f}%",
            }),
            use_container_width=True,
            hide_index=True,
        )

    # Evolución por cadena
    evol = df_i.groupby(["mes", "tienda_nombre"])["importe"].sum().reset_index()
    fig2 = px.line(
        evol, x="mes", y="importe", color="tienda_nombre",
        title="Evolución mensual por establecimiento",
        labels={"mes": "Mes", "importe": "€", "tienda_nombre": "Tienda"},
        template=template,
    )
    fig2.update_layout(height=400)
    st.plotly_chart(fig2, use_container_width=True)


# ============================================================================
# VISTA: POR CATEGORÍA (DRILL-DOWN)
# ============================================================================

def view_categoria(df_t, df_i, start_date, end_date, cat_sel, subcat_sel):
    """Vista por categoría con drill-down interactivo."""
    st.markdown("# 📂 Por Categoría")

    # Selectores internos (independientes del sidebar)
    cats = sorted(df_i["cat_display"].dropna().unique().tolist())
    
    col1, col2 = st.columns(2)
    with col1:
        cat_click = st.selectbox("🏷️ Selecciona una categoría", ["Todas"] + cats, key="cat_view_sel")
    with col2:
        if cat_click != "Todas":
            subcats = sorted(df_i[df_i["cat_display"] == cat_click]["subcat_display"].dropna().unique().tolist())
            subcat_click = st.selectbox("📎 Selecciona una subcategoría", ["Todas"] + subcats, key="subcat_view_sel")
        else:
            subcat_click = "Todas"

    # Filtrar según selección
    df = df_i
    if cat_click != "Todas":
        df = df[df["cat_display"] == cat_click]
        st.markdown(f"### 📌 Categoría: **{cat_click}** — {len(df)} items")
    if subcat_click != "Todas":
        df = df[df["subcat_display"] == subcat_click]
        st.markdown(f"#### Subcategoría: **{subcat_click}** — {len(df)} items")

    if df.empty:
        st.warning("No hay items en esta selección.")
        return

    # Si hay categoría seleccionada, mostrar productos
    if cat_click != "Todas":
        # Tabla de subcategorías
        st.markdown("### 📊 Subcategorías")
        gasto_sub = df.groupby(["cat_display", "subcat_display"]).agg(
            importe=("importe", "sum"),
            items=("id", "count"),
        ).reset_index().sort_values("importe", ascending=False)
        gasto_sub.columns = ["Categoría", "Subcategoría", "Gasto (€)", "Items"]
        gasto_sub["Gasto (€)"] = gasto_sub["Gasto (€)"].round(2)
        st.dataframe(gasto_sub[["Subcategoría", "Gasto (€)", "Items"]], use_container_width=True, hide_index=True)

        # Tabla de productos
        st.markdown(f"### 📦 Productos ({len(df)} items)")
        productos = df.groupby(["producto_norm", "subcat_display"]).agg(
            veces=("importe", "count"),
            unidades=("cantidad", "sum"),
            gasto=("importe", "sum"),
            precio_medio=("precio_unit", "mean"),
            precio_min=("precio_unit", "min"),
            precio_max=("precio_unit", "max"),
        ).reset_index().sort_values("gasto", ascending=False)

        productos["gasto"] = productos["gasto"].round(2)
        productos["precio_medio"] = productos["precio_medio"].round(2)
        productos["precio_min"] = productos["precio_min"].round(2)
        productos["precio_max"] = productos["precio_max"].round(2)
        productos.columns = ["Producto", "Subcategoría", "Compras", "Unidades", "Gasto (€)", "Precio medio (€)", "Precio min (€)", "Precio max (€)"]

        st.dataframe(productos, use_container_width=True, hide_index=True)

        # Gráfico de barras
        st.markdown("### Gasto por subcategoría")
        chart_data = gasto_sub.set_index("Subcategoría")["Gasto (€)"]
        st.bar_chart(chart_data)

        # --- Drill-down: seleccionar producto para ver tickets ---
        st.divider()
        st.markdown("### 🔎 Detalle por producto")
        prod_lista = sorted(df["producto_norm"].dropna().unique().tolist())
        # Agrupar variantes de case ('CERVEZA'/'Cerveza') en una sola entrada
        _var = {}
        for nom in prod_lista:
            _var.setdefault(nom.lower(), []).append(nom)
        prod_lista = sorted(
            (max(v, key=lambda x: (x.istitle(), x)) for v in _var.values()),
            key=str.lower,
        )
        prod_sel = st.selectbox("Selecciona un producto para ver sus tickets", [""] + prod_lista, key="cat_prod_detail")

        if prod_sel:
            _eq = _var.get(prod_sel.lower(), [prod_sel])
            prod_items = df[df["producto_norm"].isin(_eq)].copy()
            prod_items = prod_items.sort_values("fecha_dt", ascending=False)

            st.markdown(f"#### {prod_sel} — {len(prod_items)} compras, {prod_items['importe'].sum():.2f}€ total")

            # Tabla de compras
            tabla_prod = prod_items[["fecha_short", "tienda_nombre", "cantidad", "precio_unit", "importe", "num_ticket"]].copy()
            tabla_prod.columns = ["Fecha", "Tienda", "Cant.", "Precio (€)", "Importe (€)", "Nº Ticket"]
            tabla_prod["Precio (€)"] = tabla_prod["Precio (€)"].round(2)
            tabla_prod["Importe (€)"] = tabla_prod["Importe (€)"].round(2)
            st.dataframe(tabla_prod, use_container_width=True, hide_index=True)

            # Selector de ticket para ver detalle completo
            ticket_nums = prod_items["num_ticket"].unique().tolist()
            if ticket_nums:
                ticket_sel = st.selectbox("Ver ticket completo", [""] + ticket_nums, key="cat_ticket_detail")
                if ticket_sel:
                    ticket_info = df_t[df_t["num_ticket"] == ticket_sel].iloc[0]
                    items_ticket = df_i[df_i["num_ticket"] == ticket_sel].sort_values("importe", ascending=False)

                    st.markdown(f"**Ticket {ticket_sel}** — {ticket_info['tienda_nombre']} — {ticket_info['fecha_short']} — {ticket_info['total']:.2f}€")

                    tabla_tick = items_ticket[["descripcion", "cantidad", "precio_unit", "importe", "cat_display", "subcat_display"]].copy()
                    tabla_tick.columns = ["Producto", "Cant.", "Precio (€)", "Importe (€)", "Categoría", "Subcategoría"]
                    tabla_tick["Precio (€)"] = tabla_tick["Precio (€)"].round(2)
                    tabla_tick["Importe (€)"] = tabla_tick["Importe (€)"].round(2)
                    st.dataframe(tabla_tick, use_container_width=True, hide_index=True)
    else:
        # Resumen general: todas las categorías
        st.markdown("### 📊 Resumen por categoría")
        resumen = df_i.groupby("cat_display").agg(
            importe=("importe", "sum"),
            items=("id", "count"),
            productos=("producto_norm", "nunique"),
        ).reset_index().sort_values("importe", ascending=False)
        resumen.columns = ["Categoría", "Gasto (€)", "Items", "Productos únicos"]
        resumen["Gasto (€)"] = resumen["Gasto (€)"].round(2)
        st.dataframe(resumen, use_container_width=True, hide_index=True)

        st.markdown("### Gasto por categoría")
        chart_data = resumen.set_index("Categoría")["Gasto (€)"]
        st.bar_chart(chart_data)

        st.info("👆 Selecciona una categoría arriba para ver sus subcategorías y productos.")


# ============================================================================
# VISTA: POR PRODUCTO
# ============================================================================

def view_producto(df_t, df_i, start_date, end_date):
    """Vista de evolución de precio de un producto."""
    st.markdown("# 🔍 Por Producto")

    template = get_plotly_template()

    # Selector de producto. La agrupación es INSENSIBLE a mayúsculas/minúsculas:
    # aunque en la BD convivan variantes ('CERVEZA' / 'Cerveza'), en la lista se
    # muestra una sola entrada y se agregan las compras de todas ellas.
    variantes = {}
    for nom in df_i["producto_norm"].dropna().unique().tolist():
        variantes.setdefault(nom.lower(), []).append(nom)
    productos = sorted(
        (max(v, key=lambda x: (x.istitle(), x)) for v in variantes.values()),
        key=str.lower,
    )
    producto_sel = st.selectbox("Selecciona un producto", productos, key="producto_sel")

    if not producto_sel:
        st.warning("No hay productos disponibles")
        return

    # Filtrar por todas las variantes de case que representan ese producto
    equivalencias = [p for p in variantes.get(producto_sel.lower(), [producto_sel])]
    prod_data = df_i[df_i["producto_norm"].isin(equivalencias)].copy()
    prod_data = prod_data.sort_values("fecha_dt")

    if prod_data.empty:
        st.warning("No hay datos para este producto en el rango seleccionado")
        return

    # KPIs del producto
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Veces comprado", str(len(prod_data)))
    with col2:
        st.metric("Gasto total", f"{prod_data['importe'].sum():.2f} €")
    with col3:
        st.metric("Precio medio", f"{prod_data['precio_unit'].mean():.2f} €")
    with col4:
        st.metric("Precio min", f"{prod_data['precio_unit'].min():.2f} €")
    with col5:
        st.metric("Precio max", f"{prod_data['precio_unit'].max():.2f} €")

    # Evolución de precio
    if len(prod_data) > 1:
        precio_ini = prod_data["precio_unit"].iloc[0]
        precio_fin = prod_data["precio_unit"].iloc[-1]
        if precio_ini > 0:
            variacion = ((precio_fin - precio_ini) / precio_ini) * 100
            st.metric("Variación", f"{variacion:+.1f}%")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=prod_data["fecha_dt"], y=prod_data["precio_unit"],
        mode="lines+markers", name="Precio unitario",
        line=dict(color="#e74c3c", width=2),
        marker=dict(size=8),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Precio: %{y:.2f}€<extra></extra>",
    ))
    fig.update_layout(
        title=f"Evolución de precio: {producto_sel}",
        xaxis_title="Fecha", yaxis_title="Precio unitario (€)",
        template=template, height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Tabla de compras
    st.markdown("### Historial de compras")
    historial = prod_data[["fecha_short", "descripcion", "tienda_nombre", "cantidad", "precio_unit", "importe"]].copy()
    historial.columns = ["Fecha", "Descripción (ticket)", "Tienda", "Cant.", "Precio unit. (€)", "Importe (€)"]
    historial["Precio unit. (€)"] = historial["Precio unit. (€)"].round(2)
    historial["Importe (€)"] = historial["Importe (€)"].round(2)
    st.dataframe(historial, use_container_width=True, hide_index=True)


# ============================================================================
# VISTA: EVOLUCIÓN TEMPORAL
# ============================================================================

def view_temporal(df_t, df_i, start_date, end_date):
    """Vista de evolución temporal con calendario y comparativas."""
    st.markdown("# 📅 Evolución Temporal")

    template = get_plotly_template()

    # Gasto mensual con media móvil
    gasto_mes = df_i.groupby("mes").agg(
        total=("importe", "sum"),
        compras=("importe", "count"),
    ).reset_index()
    gasto_mes["media_movil_3m"] = gasto_mes["total"].rolling(3, min_periods=1).mean()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=gasto_mes["mes"], y=gasto_mes["total"],
        name="Gasto mensual", marker_color="#3498db", opacity=0.7,
    ))
    fig.add_trace(go.Scatter(
        x=gasto_mes["mes"], y=gasto_mes["media_movil_3m"],
        name="Media móvil (3 meses)", line=dict(color="#e74c3c", width=2),
    ))
    fig.update_layout(
        title="Gasto mensual con media móvil",
        xaxis_title="Mes", yaxis_title="€",
        template=template, height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Comparativa año vs año
    st.markdown("### Comparativa año vs año")
    gasto_año_mes = df_i.groupby(["año", df_i["fecha_dt"].dt.month])["importe"].sum().reset_index()
    gasto_año_mes.columns = ["Año", "Mes", "Gasto"]
    nombres_mes = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    gasto_año_mes["Mes"] = gasto_año_mes["Mes"].apply(lambda m: nombres_mes[m - 1])

    fig2 = px.line(
        gasto_año_mes, x="Mes", y="Gasto", color="Año",
        title="Gasto por mes, comparativa entre años",
        labels={"Gasto": "€", "Año": "Año"},
        template=template,
        category_orders={"Mes": nombres_mes},
    )
    fig2.update_layout(height=400)
    st.plotly_chart(fig2, use_container_width=True)

    # Calendario heatmap
    st.markdown("### 📆 Calendario de compras")
    gasto_dia = df_t.groupby(df_t["fecha_dt"].dt.date).agg(
        gasto=("total", "sum"),
        tickets=("id", "count"),
    ).reset_index()
    gasto_dia.columns = ["fecha", "gasto", "tickets"]

    if not gasto_dia.empty:
        # Crear matriz año x día de la semana para el heatmap
        gasto_dia["fecha"] = pd.to_datetime(gasto_dia["fecha"])
        gasto_dia["año"] = gasto_dia["fecha"].dt.year
        gasto_dia["semana"] = gasto_dia["fecha"].dt.isocalendar().week
        gasto_dia["dia_semana"] = gasto_dia["fecha"].dt.day_name()

        dias_orden = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        dias_es = {"Monday": "Lun", "Tuesday": "Mar", "Wednesday": "Mié", "Thursday": "Jue",
                   "Friday": "Vie", "Saturday": "Sáb", "Sunday": "Dom"}
        gasto_dia["dia_es"] = gasto_dia["dia_semana"].map(dias_es)

        años = sorted(gasto_dia["año"].unique())
        año_sel = st.selectbox("Año", años, key="cal_año")

        gasto_año = gasto_dia[gasto_dia["año"] == año_sel]
        pivot = gasto_año.pivot_table(
            index="dia_es", columns="semana", values="gasto", aggfunc="sum",
        ).reindex([dias_es[d] for d in dias_orden])

        fig3 = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=[f"S{int(c)}" for c in pivot.columns],
            y=pivot.index,
            colorscale="YlOrRd",
            hovertemplate="Semana %{x}<br>%{y}: %{z:.2f}€<extra></extra>",
        ))
        fig3.update_layout(
            title=f"Calendario de gasto {año_sel}",
            xaxis_title="Semana", yaxis_title="Día",
            template=template, height=350,
        )
        st.plotly_chart(fig3, use_container_width=True)

    # Gasto acumulado anual
    st.markdown("### Gasto acumulado anual")
    df_i_sorted = df_i.sort_values("fecha_dt")
    for año in sorted(df_i_sorted["año"].unique()):
        df_año = df_i_sorted[df_i_sorted["año"] == año]
        df_año = df_año.copy()
        df_año["dia_año"] = df_año["fecha_dt"].dt.dayofyear
        acum = df_año.groupby("dia_año")["importe"].sum().cumsum().reset_index()
        acum.columns = ["Día", "Acumulado"]

    acum_data = []
    for año in sorted(df_i_sorted["año"].unique()):
        df_año = df_i_sorted[df_i_sorted["año"] == año].copy()
        df_año["dia_año"] = df_año["fecha_dt"].dt.dayofyear
        acum = df_año.groupby("dia_año")["importe"].sum().cumsum().reset_index()
        acum["Año"] = año
        acum.columns = ["Día", "Acumulado", "Año"]
        acum_data.append(acum)
    acum_df = pd.concat(acum_data)

    fig4 = px.line(
        acum_df, x="Día", y="Acumulado", color="Año",
        title="Gasto acumulado por día del año",
        labels={"Día": "Día del año", "Acumulado": "€ acumulado"},
        template=template,
    )
    fig4.update_layout(height=400)
    st.plotly_chart(fig4, use_container_width=True)


# ============================================================================
# VISTA: HISTORIAL DE TICKETS
# ============================================================================

def view_tickets(df_t, df_i, start_date, end_date):
    """Vista de historial de tickets con ordenación multi-criterio y detalle expandible."""
    st.markdown("# 🧾 Historial de Tickets")

    if df_t.empty:
        st.warning("No hay tickets en el rango seleccionado.")
        return

    # --- Preparar tabla resumen con columnas extra para ordenación ---
    # Calcular items por ticket y gasto por categoría dominante
    items_por_ticket = df_i.groupby("ticket_id").agg(
        n_items=("id", "count"),
        cat_top=("cat_display", lambda x: x.mode().iloc[0] if not x.mode().empty else "N/A"),
    ).reset_index()

    tabla = df_t.merge(items_por_ticket, left_on="id", right_on="ticket_id", how="left")
    tabla = tabla[["fecha_dt", "fecha_short", "num_ticket", "tienda_nombre", "direccion", "n_items", "cat_top", "total", "metodo_pago", "pdf_file"]].copy()
    tabla.columns = ["_fecha_dt", "Fecha", "Nº Ticket", "Tienda", "Dirección", "Items", "Categoría principal", "Total (€)", "Pago", "PDF"]
    tabla["Total (€)"] = tabla["Total (€)"].round(2)
    tabla["Items"] = tabla["Items"].fillna(0).astype(int)

    # --- Controles de ordenación ---
    col_sort1, col_sort2, col_search = st.columns([2, 1, 3])

    with col_sort1:
        sort_options = ["Fecha (más reciente)", "Fecha (más antigua)", "Total (mayor)", "Total (menor)",
                        "Items (más)", "Items (menos)", "Tienda (A-Z)"]
        sort_sel = st.selectbox("Ordenar por", sort_options, key="ticket_sort")

    with col_sort2:
        per_page = st.selectbox("Por página", [10, 20, 50, 100], index=1, key="ticket_pagesize")

    with col_search:
        search_term = st.text_input("🔍 Buscar (ticket, tienda, producto...)", key="ticket_search")

    # Aplicar búsqueda
    if search_term:
        mask = (
            tabla["Nº Ticket"].str.contains(search_term, case=False, na=False) |
            tabla["Tienda"].str.contains(search_term, case=False, na=False)
        )
        # Buscar también en items
        matching_ticket_ids = df_i[
            df_i["descripcion"].str.contains(search_term, case=False, na=False)
        ]["ticket_id"].unique()
        mask |= tabla.index.isin(df_t[df_t["id"].isin(matching_ticket_ids)].index)
        tabla_filt = tabla[mask]
    else:
        tabla_filt = tabla

    # Aplicar ordenación
    sort_map = {
        "Fecha (más reciente)": ("_fecha_dt", False),
        "Fecha (más antigua)": ("_fecha_dt", True),
        "Total (mayor)": ("Total (€)", False),
        "Total (menor)": ("Total (€)", True),
        "Items (más)": ("Items", False),
        "Items (menos)": ("Items", True),
        "Tienda (A-Z)": ("Tienda", True),
    }
    sort_col, sort_asc = sort_map[sort_sel]
    tabla_filt = tabla_filt.sort_values(sort_col, ascending=sort_asc)

    # --- Tabla de tickets con botón "Ver" en cada fila ---
    tabla_display = tabla_filt[["Fecha", "Tienda", "Dirección", "Items", "Categoría principal", "Total (€)", "Pago", "Nº Ticket"]].copy()

    # Paginación real
    total_rows = len(tabla_display)
    total_pages = max(1, (total_rows + per_page - 1) // per_page)
    page = st.number_input("Página", min_value=1, max_value=total_pages, value=1, step=1, key="ticket_page")
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    tabla_page = tabla_display.iloc[start_idx:end_idx].reset_index(drop=True)
    # Formatear Total
    tabla_page["Total (€)"] = tabla_page["Total (€)"].apply(lambda x: f"{x:.2f} €")
    # Columna que aloja el botón: el valor de la celda es la etiqueta del botón
    tabla_page.insert(0, "Ver", ":material/visibility: Ver")

    # Los callbacks se ejecutan antes del cuerpo del script en el siguiente rerun,
    # así que el callback resuelve el ticket desde session_state (no por cierre).
    st.session_state["ticket_page_nums"] = tabla_page["Nº Ticket"].tolist()

    def _on_view_ticket():
        """Guarda el ticket de la fila pulsada para mostrarlo en el detalle."""
        click = st.session_state.get("ticket_row_click")
        if not click:
            return
        row = click.get("row")
        nums = st.session_state.get("ticket_page_nums") or []
        if row is not None and 0 <= row < len(nums):
            st.session_state["ticket_manual_sel"] = nums[row]

    st.dataframe(
        tabla_page,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ver": st.column_config.ButtonColumn(
                "Ver",
                type="tertiary",
                help="Pulsa para ver el detalle del ticket",
                on_click=_on_view_ticket,
                key="ticket_row_click",
            ),
        },
    )
    st.caption(f"Mostrando {start_idx + 1}-{min(end_idx, total_rows)} de {total_rows} tickets · Página {page} de {total_pages}")

    # --- Detalle del ticket seleccionado ---
    st.divider()

    ticket_nums = tabla_filt["Nº Ticket"].tolist()
    # El botón de fila puede haber fijado la selección antes de dibujar el desplegable
    if st.session_state.get("ticket_manual_sel") not in ticket_nums:
        st.session_state["ticket_manual_sel"] = ticket_nums[0] if ticket_nums else None
    ticket_sel = st.selectbox(
        "O elige un ticket en la lista para ver el detalle", ticket_nums,
        key="ticket_manual_sel",
    )

    if ticket_sel:
        ticket_info = df_t[df_t["num_ticket"] == ticket_sel].iloc[0]
        items_ticket = df_i[df_i["num_ticket"] == ticket_sel].copy()
        items_ticket = items_ticket.sort_values("importe", ascending=False)

        # Cabecera del ticket
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total", f"{ticket_info['total']:.2f} €")
        with col2:
            st.metric("Productos", str(len(items_ticket)))
        with col3:
            st.metric("Fecha", ticket_info["fecha_short"])
        with col4:
            st.metric("Tienda", ticket_info.get("tienda_nombre", "N/A"))

        st.markdown(f"**Nº Ticket:** {ticket_sel} | **Pago:** {ticket_info['metodo_pago']}")

        # Desglose IVA si existe
        if ticket_info.get("iva_json"):
            import json
            try:
                iva = json.loads(ticket_info["iva_json"])
                if iva:
                    iva_cols = st.columns(len(iva))
                    for i, (col, iva_item) in enumerate(zip(iva_cols, iva)):
                        with col:
                            st.metric(
                                f"IVA {iva_item['tasa']}%",
                                f"{iva_item['cuota']:.2f} €",
                                f"Base: {iva_item['base']:.2f} €",
                            )
            except (json.JSONDecodeError, KeyError):
                pass

        # Tabla de items con ordenación nativa
        st.markdown("### Líneas del ticket")
        items_table = items_ticket[["cantidad", "descripcion", "cat_display", "subcat_display", "producto_norm", "precio_unit", "importe"]].copy()
        items_table.columns = ["Cant.", "Producto (ticket)", "Categoría", "Subcategoría", "Producto norm.", "Precio unit. (€)", "Importe (€)"]
        items_table["Precio unit. (€)"] = items_table["Precio unit. (€)"].round(2)
        items_table["Importe (€)"] = items_table["Importe (€)"].round(2)

        st.dataframe(
            items_table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Precio unit. (€)": st.column_config.NumberColumn(format="%.2f €"),
                "Importe (€)": st.column_config.NumberColumn(format="%.2f €"),
            },
        )

        # Resumen por categoría del ticket
        st.markdown("### Resumen por categoría")
        cat_resumen = items_ticket.groupby("cat_display").agg(
            items=("id", "count"),
            importe=("importe", "sum"),
        ).reset_index().sort_values("importe", ascending=False)
        cat_resumen.columns = ["Categoría", "Items", "Importe (€)"]
        cat_resumen["Importe (€)"] = cat_resumen["Importe (€)"].round(2)
        cat_resumen["%"] = (cat_resumen["Importe (€)"] / cat_resumen["Importe (€)"].sum() * 100).round(1)

        col_chart, col_table = st.columns([3, 2])
        with col_chart:
            template = get_plotly_template()
            fig = px.bar(
                cat_resumen, x="Categoría", y="Importe (€)",
                color="Importe (€)", color_continuous_scale="Tealgrn",
                template=template,
            )
            fig.update_layout(height=300, showlegend=False, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
        with col_table:
            st.dataframe(cat_resumen, use_container_width=True, hide_index=True)

        # PDF o imagen
        if ticket_info["pdf_file"]:
            pdf_dir = PROJECT_DIR / "data" / "raw_pdfs"
            pdf_path = pdf_dir / ticket_info["pdf_file"]
            photo_dir = PROJECT_DIR / "data" / "raw_photos"
            photo_path = photo_dir / ticket_info["pdf_file"]
            
            if pdf_path.exists():
                st.divider()
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "📥 Descargar PDF del ticket", f,
                        file_name=ticket_info["pdf_file"],
                        mime="application/pdf",
                        type="primary",
                    )
            elif photo_path.exists():
                st.divider()
                st.markdown("### 📷 Imagen del ticket")
                st.image(str(photo_path), use_container_width=True)
                with open(photo_path, "rb") as f:
                    st.download_button(
                        "📥 Descargar imagen", f,
                        file_name=ticket_info["pdf_file"],
                        mime="image/jpeg",
                    )


# ============================================================================
# VISTA: GESTIÓN DE CATEGORÍAS (OVERRIDES)
# ============================================================================

def view_gestion_categorias(df_t, df_i):
    """Vista para reasignar categorías manualmente."""
    st.markdown("# ⚙️ Gestión de Categorías")

    st.markdown("""
    Reasigna productos a categorías correctas cuando el sistema se equivoca.
    - **Para todos**: aplica a todos los items pasados y futuros con esa descripción
    - **Solo este item**: aplica solo al item seleccionado
    """)

    # Import taxonomy functions
    try:
        from src.taxonomy import get_overrides, add_override, remove_override
        from src.database import DB_PATH
    except ImportError:
        st.warning("El módulo de taxonomía no está disponible aún.")
        return

    tab1, tab2 = st.tabs(["Reasignar", "Overrides activos"])

    with tab1:
        st.markdown("### Reasignar categoría")

        # Mostrar items en "Otros" o seleccionar cualquiera
        productos_unicos = sorted(df_i["descripcion"].unique().tolist())
        prod_sel = st.selectbox("Producto (descripción del ticket)", productos_unicos, key="reassign_prod")

        if prod_sel:
            # Mostrar asignación actual
            current = df_i[df_i["descripcion"] == prod_sel].iloc[0]
            st.info(f"Actual: {current.get('cat_display', 'N/A')} → {current.get('subcat_display', 'N/A')} → {current.get('producto_norm', 'N/A')}")

            col1, col2, col3 = st.columns(3)
            with col1:
                cat_options = ["Alimentación", "Bebidas", "Hogar y limpieza", "Higiene y cuidado personal", "Otros"]
                new_cat = st.selectbox("Nueva categoría", cat_options, key="new_cat")
            with col2:
                new_subcat = st.text_input("Nueva subcategoría", key="new_subcat")
            with col3:
                new_prod_norm = st.text_input("Nombre normalizado (opcional)", key="new_prod_norm")

            modo = st.radio("Modo de aplicación", ["Para todos (pasados y futuros)", "Solo este item"], key="reassign_modo")

            if st.button("Aplicar reasignación", type="primary"):
                try:
                    if "Para todos" in modo:
                        add_override(
                            str(DB_PATH), tipo="producto", descripcion=prod_sel,
                            categoria_general=new_cat, subcategoria=new_subcat,
                            producto_norm=new_prod_norm or None,
                        )
                        st.success(f"✅ Reasignado '{prod_sel}' → {new_cat} / {new_subcat} para todos los items")
                    else:
                        item_id = int(df_i[df_i["descripcion"] == prod_sel].iloc[0]["id"])
                        add_override(
                            str(DB_PATH), tipo="item", item_id=item_id,
                            categoria_general=new_cat, subcategoria=new_subcat,
                            producto_norm=new_prod_norm or None,
                        )
                        st.success(f"✅ Reasignado item {item_id} → {new_cat} / {new_subcat}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    with tab2:
        st.markdown("### Overrides activos")
        try:
            overrides = get_overrides(str(DB_PATH))
            if not overrides:
                st.info("No hay overrides activos")
            else:
                for ov in overrides:
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        target = ov.get("descripcion") or f"Item #{ov.get('item_id')}"
                        st.write(f"**{target}** → {ov['categoria_general']} / {ov['subcategoria']}" +
                                (f" / {ov['producto_norm']}" if ov.get("producto_norm") else ""))
                    with col2:
                        if st.button("🗑️", key=f"del_{ov['id']}"):
                            remove_override(str(DB_PATH), ov["id"])
                            st.cache_data.clear()
                            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ============================================================================
# APP PRINCIPAL
# ============================================================================

def view_ingesta():
    """Vista de ingesta: ejecutar pipeline, ver estado de BD y historial."""
    st.markdown("## 📥 Ingesta de tickets")

    # --- Estado actual de la BD ---
    st.markdown("### Estado actual")
    df_tickets, df_items = get_data()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tickets", len(df_tickets))
    col2.metric("Items", len(df_items))
    col3.metric("Gasto total", f"{df_items['importe'].sum():.2f} €")
    col4.metric("Categorías", df_items["cat_display"].nunique())

    st.divider()

    # --- Ejecutar ingesta ---
    st.markdown("### Ejecutar ingesta")

    with st.expander("ℹ️ ¿Qué hace la ingesta?", expanded=False):
        st.markdown("""
        1. **IMAP**: busca emails con asunto `[ticket]` en las cuentas configuradas (últimos 7 días)
        2. **PDFs**: descarga PDFs adjuntos de Mercadona y otros supermercados
        3. **Imágenes**: descarga imágenes de tickets con OCR (minicpm-v 4.5 vía Ollama)
        4. **Parse**: extrae productos, precios y cantidades de cada ticket
        5. **Taxonomía**: clasifica cada producto en categoría/subcategoría
        6. **SQLite**: guarda todo en la base de datos con deduplicación por hash

        ⚠️ El OCR de imágenes puede tardar 2-5 minutos por imagen (CPU).
        """)

    # Botón de ingesta
    if st.button("🔄 Ejecutar ingesta (últimos 7 días)", type="primary", use_container_width=True):
        with st.spinner("Ejecutando ingesta... esto puede tardar varios minutos"):
            import subprocess as sp

            # Ejecutar run_pipeline.py directamente (ya estamos dentro del contenedor)
            try:
                result = sp.run(
                    ["python", "/app/run_pipeline.py"],
                    capture_output=True, text=True, timeout=600
                )
                output = result.stdout + result.stderr

                # Limpiar cache de datos
                st.cache_data.clear()

                st.markdown("#### Salida del pipeline")
                st.code(output, language="text")

                if result.returncode == 0:
                    st.success("✅ Ingesta completada correctamente")
                else:
                    st.error(f"❌ Ingesta terminó con errores (código {result.returncode})")

            except sp.TimeoutExpired:
                st.error("⏰ Timeout: la ingesta tardó más de 10 minutos")
            except Exception as e:
                st.error(f"Error: {e}")

    # Reclasificar taxonomía
    st.divider()
    st.markdown("### Reclasificar taxonomía")
    st.markdown("Reclasifica todos los items con las reglas actuales de `taxonomy.py`.")

    col_re1, col_re2 = st.columns(2)
    with col_re1:
        if st.button("🏷️ Reglas", use_container_width=True):
            with st.spinner("Reclasificando con reglas..."):
                import subprocess as sp
                try:
                    result = sp.run(
                        ["python3", "-c",
                         "from src.taxonomy import apply_taxonomy_to_db; apply_taxonomy_to_db()"],
                        capture_output=True, text=True, timeout=60
                    )
                    st.cache_data.clear()
                    st.code(result.stdout, language="text")
                    if result.returncode == 0:
                        st.success("✅ Reclasificación completada")
                    else:
                        st.error("❌ Error en reclasificación")
                except Exception as e:
                    st.error(f"Error: {e}")

    with col_re2:
        if st.button("🤖 LLM local", use_container_width=True):
            with st.spinner("Clasificando con LLM local (Ollama)... puede tardar varios minutos"):
                import subprocess as sp
                try:
                    result = sp.run(
                        ["python3", "-c",
                         "from src.taxonomy import llm_classify_uncategorized; llm_classify_uncategorized()"],
                        capture_output=True, text=True, timeout=600
                    )
                    st.cache_data.clear()
                    st.code(result.stdout, language="text")
                    if result.returncode == 0:
                        st.success("✅ Clasificación LLM completada")
                    else:
                        st.error("❌ Error en clasificación LLM")
                except Exception as e:
                    st.error(f"Error: {e}")

    # Limpiar caché manual
    st.divider()
    if st.button("🧹 Limpiar caché del dashboard"):
        st.cache_data.clear()
        st.success("Caché limpiado. Los datos se recargarán en la próxima vista.")


def main():
    # Cargar datos
    df_tickets, df_items = get_data()

    # ============ T1 v2: FILTROS SIEMPRE VISIBLES EN CABECERA ============
    # (antes: enterrados en la sidebar; el cuerpo gana todo el espacio)
    with st.container():
        f1, f2, f3, f4, f5 = st.columns([1.35, 0.55, 1.15, 1.15, 1.0])
        fecha_min = df_items["fecha_dt"].min().date()
        fecha_max = df_items["fecha_dt"].max().date()
        with f1:
            rango = st.date_input(
                "Rango", (fecha_min, fecha_max),
                min_value=fecha_min, max_value=fecha_max, key="t1_dates",
            )
            if isinstance(rango, tuple) and len(rango) == 2:
                start_date, end_date = (str(rango[0]), str(rango[1]))
            else:
                start_date = end_date = str(rango)
        with f2:
            st.session_state.dark_mode = st.toggle(
                "🌙", value=st.session_state.get("dark_mode", True), key="t1_dark"
            )
        with f3:
            store_sel = st.selectbox("🏪 Tienda", ["Todas"] + get_stores(df_tickets), key="t1_store")
        with f4:
            cat_sel = st.selectbox("📂 Categoría", ["Todas"] + get_categories(df_items), key="t1_cat")
        with f5:
            subcats = get_subcategories(df_items, cat_sel) if cat_sel != "Todas" else []
            subcat_sel = st.selectbox("📎 Subcategoría", ["Todas"] + subcats, key="t1_sub") if subcats else "Todas"
        st.caption(
            f"{len(df_tickets)} tickets · {len(df_items)} líneas · "
            f"{df_items['descripcion'].nunique()} productos"
        )

    # ============ NAVEGACIÓN HORIZONTAL (pestañas arriba) ============
    # Tickets por defecto: la vista que más se usa abre primero
    selected = option_menu(
        menu_title=None,
        options=["Tickets","Panel","Establecimiento","Categoría","Producto","Temporal","Categorías","Ingesta"],
        icons=["receipt","house","shop","diagram-3","search","calendar-day","palette","cloud-arrow-up-fill"],
        default_index=0,
        orientation="horizontal",
        styles={
            "container": {"padding": "0.2rem 0", "background-color": "transparent"},
            "icon": {"color": "var(--muted)", "font-size": "13px"},
            "nav-link": {
                "font-size": "14px", "padding": "0.45rem 0.8rem", "border-radius": "10px",
                "color": "var(--text)", "margin": "0rem 0.2rem",
                "--hover-color": "rgba(47,158,110,.15)",
            },
            "nav-link-selected": {
                "background-color": "rgba(47,158,110,.22)", "color": "var(--text, #ffffff)",
                "font-weight": "650", "border-bottom": "2px solid var(--accent)",
            },
        },
        key="nav_t1h",
    )
    selected = {"Tickets":"🧾 Tickets","Panel":"📊 Panel","Establecimiento":"🏪 Establecimiento",
                "Categoría":"📂 Categoría","Producto":"🔍 Producto","Temporal":"📅 Temporal",
                "Categorías":"⚙️ Categorías","Ingesta":"📥 Ingesta"}[selected]

    # Filtrar
    df_t, df_i = filter_data(df_tickets, df_items, start_date, end_date, store_sel, cat_sel, subcat_sel)

    if selected == "📊 Panel":
        view_dashboard(df_t, df_i, start_date, end_date)
    elif selected == "🏪 Establecimiento":
        view_establecimiento(df_t, df_i, start_date, end_date)
    elif selected == "📂 Categoría":
        view_categoria(df_t, df_i, start_date, end_date, cat_sel, subcat_sel)
    elif selected == "🔍 Producto":
        view_producto(df_t, df_i, start_date, end_date)
    elif selected == "📅 Temporal":
        view_temporal(df_t, df_i, start_date, end_date)
    elif selected == "🧾 Tickets":
        view_tickets(df_t, df_i, start_date, end_date)
    elif selected == "⚙️ Categorías":
        view_gestion_categorias(df_t, df_i)
    elif selected == "📥 Ingesta":
        view_ingesta()


if __name__ == "__main__":
    main()