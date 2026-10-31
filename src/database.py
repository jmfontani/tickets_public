"""Gestión de base de datos SQLite para tickets de compra (multi-comercio)."""
import json
import sqlite3
from pathlib import Path
from typing import List, Optional
from dataclasses import asdict

from .parse_ticket import Ticket, LineItem


BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "tickets.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    num_ticket TEXT UNIQUE NOT NULL,
    fecha TEXT NOT NULL,
    tienda TEXT,
    direccion TEXT,
    telefono TEXT,
    operador TEXT,
    total REAL,
    metodo_pago TEXT,
    pdf_file TEXT,
    iva_json TEXT,
    comercio TEXT DEFAULT 'mercadona',
    source_type TEXT DEFAULT 'email_pdf',
    source_file TEXT DEFAULT '',
    content_hash TEXT,
    email_account TEXT,
    cuadre_ok INTEGER,
    cuadre_diff REAL
);

CREATE TABLE IF NOT EXISTS line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    cantidad INTEGER,
    descripcion TEXT,
    precio_unit REAL,
    importe REAL,
    fecha TEXT,
    producto_norm TEXT,
    categoria TEXT
);

CREATE INDEX IF NOT EXISTS idx_line_items_descripcion ON line_items(descripcion);
CREATE INDEX IF NOT EXISTS idx_line_items_fecha ON line_items(fecha);
CREATE INDEX IF NOT EXISTS idx_line_items_ticket_id ON line_items(ticket_id);
"""

# Columnas nuevas para migración incremental
_NEW_COLUMNS = {
    "comercio": "TEXT DEFAULT 'mercadona'",
    "source_type": "TEXT DEFAULT 'email_pdf'",
    "source_file": "TEXT DEFAULT ''",
    "content_hash": "TEXT",
    "email_account": "TEXT",
    # Cuadre aritmético calculado en código (ver ocr_llm.compute_cuadre):
    # 1 = suma de items coincide con el total, 0 = descuadre, NULL = no evaluable.
    "cuadre_ok": "INTEGER",
    "cuadre_diff": "REAL",
}


def init_db(db_path: Optional[Path] = None):
    """Crea las tablas si no existen y migra columnas nuevas si faltan."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()

    # Migración incremental: añadir columnas nuevas si no existen
    for col, col_def in _NEW_COLUMNS.items():
        try:
            conn.execute(f"ALTER TABLE tickets ADD COLUMN {col} {col_def}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Columna ya existe

    conn.close()


def insert_ticket(conn: sqlite3.Connection, ticket: Ticket,
                  comercio: str = "mercadona",
                  source_type: str = "email_pdf",
                  source_file: str = "",
                  content_hash: Optional[str] = None,
                  email_account: Optional[str] = None) -> int:
    """Inserta un ticket y sus items. Devuelve el ID del ticket.
    Si el ticket ya existe (por num_ticket), lo reemplaza (upsert).
    Si content_hash coincide con uno existente, salta (deduplicación)."""
    cur = conn.cursor()

    # Deduplicación por content_hash si se proporciona
    if content_hash:
        existing = cur.execute(
            "SELECT id FROM tickets WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            return existing[0]  # Ya existe, no insertar

    # Upsert por num_ticket SOLO si es la misma fuente (mismo content_hash o
    # mismo source_file). Si llega una fuente distinta con el mismo num_ticket
    # (p.ej. una foto cuyo OCR lee mal el código de barras de un ticket ya
    # insertado desde PDF), NO se borra el existente.
    cur.execute(
        "SELECT id, content_hash, source_file FROM tickets WHERE num_ticket = ?",
        (ticket.num_ticket,),
    )
    existing = cur.fetchone()
    if existing:
        existing_id, existing_hash, existing_src = existing
        same_source = (
            (content_hash and existing_hash == content_hash)
            or (source_file and existing_src == source_file)
        )
        if same_source:
            cur.execute("DELETE FROM line_items WHERE ticket_id = ?", (existing_id,))
            cur.execute("DELETE FROM tickets WHERE id = ?", (existing_id,))
        elif content_hash:
            # Fuente distinta (p.ej. foto): num_ticket único con sufijo del
            # hash para no chocar con UNIQUE ni pisar el ticket existente.
            ticket.num_ticket = f"{ticket.num_ticket}-{content_hash[:8]}"
        else:
            return existing_id  # duplicado sin hash: conservar el existente

    cur.execute(
        """INSERT INTO tickets 
           (num_ticket, fecha, tienda, direccion, telefono, operador, 
            total, metodo_pago, pdf_file, iva_json,
            comercio, source_type, source_file, content_hash, email_account,
            cuadre_ok, cuadre_diff)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticket.num_ticket,
            ticket.fecha,
            ticket.tienda,
            ticket.direccion,
            ticket.telefono,
            ticket.operador,
            ticket.total,
            ticket.metodo_pago,
            ticket.pdf_file,
            json.dumps(ticket.iva_desglose, ensure_ascii=False),
            comercio,
            source_type,
            source_file,
            content_hash,
            email_account,
            getattr(ticket, "cuadre_ok", None),
            getattr(ticket, "cuadre_diff", None),
        )
    )
    ticket_id = cur.lastrowid

    for item in ticket.items:
        cur.execute(
            """INSERT INTO line_items 
               (ticket_id, cantidad, descripcion, precio_unit, importe, fecha)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticket_id, item.cantidad, item.descripcion,
             item.precio_unit, item.importe, ticket.fecha),
        )

    conn.commit()
    return ticket_id


def get_all_items(db_path: Optional[Path] = None) -> List[dict]:
    """Devuelve todos los line_items con info del ticket."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT li.*, t.num_ticket, t.direccion, t.metodo_pago, t.comercio, t.tienda
           FROM line_items li
           JOIN tickets t ON li.ticket_id = t.id
           ORDER BY li.fecha, li.id"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tickets(db_path: Optional[Path] = None) -> List[dict]:
    """Devuelve todos los tickets."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM tickets ORDER BY fecha"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unique_products(db_path: Optional[Path] = None) -> List[dict]:
    """Devuelve productos únicos con stats."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT descripcion, 
                  COUNT(*) as veces_comprado,
                  SUM(cantidad) as unidades_totales,
                  SUM(importe) as gasto_total,
                  AVG(precio_unit) as precio_medio,
                  MIN(precio_unit) as precio_min,
                  MAX(precio_unit) as precio_max,
                  MIN(fecha) as primera_compra,
                  MAX(fecha) as ultima_compra
           FROM line_items
           GROUP BY descripcion
           ORDER BY gasto_total DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price_history(db_path: Optional[Path] = None) -> List[dict]:
    """Devuelve historial de precios por producto y fecha."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT descripcion, precio_unit, importe, cantidad, fecha,
                  num_ticket
           FROM line_items li
           JOIN tickets t ON li.ticket_id = t.id
           ORDER BY descripcion, fecha"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"BD inicializada en {DB_PATH}")