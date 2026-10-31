"""Carga y cache de datos desde SQLite para el dashboard Streamlit."""
import sqlite3
from pathlib import Path
from typing import Tuple, Optional

import pandas as pd

DB_PATH = Path(__file__).parent.parent / "data" / "tickets.db"


def _extract_store_name(tienda: str, direccion: str) -> str:
    """Extrae el nombre de la cadena del campo tienda. Multi-tienda."""
    if not tienda:
        return "Sin especificar"
    t = tienda.upper()
    if "MERCADONA" in t:
        return "Mercadona"
    if "LIDL" in t:
        return "Lidl"
    if "CARREFOUR" in t:
        return "Carrefour"
    if "DIA" in t or "DÍA" in t:
        return "Día"
    if "ALCAMPO" in t or "ALCAMP" in t:
        return "Alcampo"
    if "CONSUM" in t:
        return "Consum"
    if "EROSKI" in t:
        return "Eroski"
    if "AUCHAN" in t:
        return "Auchan"
    if "EL JAMON" in t or "EL JAMÓN" in t:
        return "El Jamón"
    if "JYSK" in t:
        return "JYSK"
    if "IKEA" in t:
        return "IKEA"
    if "DECATHLON" in t:
        return "Decathlon"
    # Fallback: primeras palabras del campo tienda
    parts = tienda.split(",")
    if parts:
        return parts[0].strip().title()
    return tienda


def load_tickets() -> pd.DataFrame:
    """Carga todos los tickets con fecha parseada."""
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT * FROM tickets ORDER BY fecha", conn)
    conn.close()
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y %H:%M", errors="coerce")
    # Intentar formatos alternativos para los que fallan (segundos, año 2 dígitos)
    mask_failed = df["fecha_dt"].isna()
    if mask_failed.any():
        df.loc[mask_failed, "fecha_dt"] = pd.to_datetime(
            df.loc[mask_failed, "fecha"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
        )
    mask_failed2 = df["fecha_dt"].isna()
    if mask_failed2.any():
        df.loc[mask_failed2, "fecha_dt"] = pd.to_datetime(
            df.loc[mask_failed2, "fecha"], format="%d/%m/%y %H:%M:%S", errors="coerce"
        )
    mask_failed3 = df["fecha_dt"].isna()
    if mask_failed3.any():
        df.loc[mask_failed3, "fecha_dt"] = pd.to_datetime(
            df.loc[mask_failed3, "fecha"], format="%d/%m/%y %H:%M", errors="coerce"
        )
    df["fecha_short"] = df["fecha_dt"].dt.strftime("%d/%m/%Y")
    df["mes"] = df["fecha_dt"].dt.to_period("M").astype(str)
    df["año"] = df["fecha_dt"].dt.year.astype(str)
    # Nombre de cadena legible
    df["tienda_nombre"] = df.apply(lambda r: _extract_store_name(r.get("tienda", ""), r.get("direccion", "")), axis=1)
    return df


def load_items() -> pd.DataFrame:
    """Carga todos los line_items con info del ticket."""
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        """SELECT li.*, t.num_ticket, t.direccion, t.tienda, t.metodo_pago, t.total as ticket_total
           FROM line_items li
           JOIN tickets t ON li.ticket_id = t.id
           ORDER BY li.fecha""",
        conn,
    )
    conn.close()
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y %H:%M", errors="coerce")
    # Intentar formatos alternativos para los que fallan
    mask_failed = df["fecha_dt"].isna()
    if mask_failed.any():
        df.loc[mask_failed, "fecha_dt"] = pd.to_datetime(
            df.loc[mask_failed, "fecha"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
        )
    mask_failed2 = df["fecha_dt"].isna()
    if mask_failed2.any():
        df.loc[mask_failed2, "fecha_dt"] = pd.to_datetime(
            df.loc[mask_failed2, "fecha"], format="%d/%m/%y %H:%M:%S", errors="coerce"
        )
    mask_failed3 = df["fecha_dt"].isna()
    if mask_failed3.any():
        df.loc[mask_failed3, "fecha_dt"] = pd.to_datetime(
            df.loc[mask_failed3, "fecha"], format="%d/%m/%y %H:%M", errors="coerce"
        )
    df["fecha_short"] = df["fecha_dt"].dt.strftime("%d/%m/%Y")
    df["mes"] = df["fecha_dt"].dt.to_period("M").astype(str)
    df["año"] = df["fecha_dt"].dt.year.astype(str)
    # Nombre de cadena legible
    df["tienda_nombre"] = df.apply(lambda r: _extract_store_name(r.get("tienda", ""), r.get("direccion", "")), axis=1)
    # Usar categoria_general si existe, si no usar categoria
    if "categoria_general" in df.columns:
        df["cat_display"] = df["categoria_general"].fillna("Otros")
    else:
        df["cat_display"] = df.get("categoria", "Otros")
    # Subcategoria si existe
    if "subcategoria" in df.columns:
        df["subcat_display"] = df["subcategoria"].fillna("Varios")
    else:
        df["subcat_display"] = "Varios"
    return df


def load_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Carga tickets e items."""
    return load_tickets(), load_items()


def get_stores(df_tickets: pd.DataFrame) -> list:
    """Devuelve lista de tiendas por nombre de cadena."""
    if "tienda_nombre" in df_tickets.columns:
        stores = df_tickets["tienda_nombre"].unique().tolist()
        return sorted(stores)
    return []


def get_categories(df_items: pd.DataFrame) -> list:
    """Devuelve lista de categorías generales."""
    return sorted(df_items["cat_display"].unique().tolist())


def get_subcategories(df_items: pd.DataFrame, categoria: Optional[str] = None) -> list:
    """Devuelve subcategorías, opcionalmente filtradas por categoría."""
    if categoria:
        df = df_items[df_items["cat_display"] == categoria]
    else:
        df = df_items
    return sorted(df["subcat_display"].unique().tolist())


def get_products(df_items: pd.DataFrame, categoria: Optional[str] = None,
                 subcategoria: Optional[str] = None) -> list:
    """Devuelve productos normalizados, opcionalmente filtrados."""
    df = df_items
    if categoria:
        df = df[df["cat_display"] == categoria]
    if subcategoria:
        df = df[df["subcat_display"] == subcategoria]
    return sorted(df["producto_norm"].dropna().unique().tolist())


def filter_data(
    df_tickets: pd.DataFrame,
    df_items: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    store: Optional[str] = None,
    categoria: Optional[str] = None,
    subcategoria: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Filtra tickets e items por los criterios dados."""
    mask_t = pd.Series(True, index=df_tickets.index)
    mask_i = pd.Series(True, index=df_items.index)

    if start_date:
        sd = pd.to_datetime(start_date)
        mask_t &= df_tickets["fecha_dt"] >= sd
        mask_i &= df_items["fecha_dt"] >= sd
    if end_date:
        ed = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        mask_t &= df_tickets["fecha_dt"] < ed
        mask_i &= df_items["fecha_dt"] < ed
    if store and store != "Todas":
        mask_t &= df_tickets["tienda_nombre"] == store
        mask_i &= df_items["tienda_nombre"] == store
    if categoria and categoria != "Todas":
        mask_i &= df_items["cat_display"] == categoria
    if subcategoria and subcategoria != "Todas":
        mask_i &= df_items["subcat_display"] == subcategoria

    df_t = df_tickets[mask_t].copy()
    df_i = df_items[mask_i].copy()

    # Si hay filtro de categoría/subcategoría, filtrar tickets a los que tienen items
    if (categoria and categoria != "Todas") or (subcategoria and subcategoria != "Todas"):
        ticket_ids = df_i["ticket_id"].unique()
        df_t = df_t[df_t["id"].isin(ticket_ids)]

    return df_t, df_i