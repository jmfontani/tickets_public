"""Descarga el catálogo completo de Mercadona desde su API pública
y lo guarda en SQLite para cruzar con los tickets."""
import urllib.request
import json
import sqlite3
import time
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "tickets.db"

API_BASE = "https://tienda.mercadona.es/api"
CATALOG_TABLE = "catalog_products"


def fetch_json(url):
    """Descarga JSON con headers de navegador."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def init_catalog_table(conn):
    """Crea la tabla del catálogo si no existe."""
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS {CATALOG_TABLE} (
        id TEXT PRIMARY KEY,
        slug TEXT,
        display_name TEXT,
        display_name_norm TEXT,
        category_id INTEGER,
        category_name TEXT,
        subcategory_id INTEGER,
        subcategory_name TEXT,
        packaging TEXT,
        unit_price REAL,
        bulk_price REAL,
        unit_size REAL,
        size_format TEXT,
        is_pack INTEGER,
        pack_size TEXT,
        total_units TEXT,
        share_url TEXT,
        thumbnail TEXT,
        updated_at TEXT
    );
    """)


def download_catalog(progress_cb=None):
    """Descarga todo el catálogo desde la API de Mercadona."""
    if progress_cb:
        progress_cb("Descargando categorías raíz...")

    cats = fetch_json(f"{API_BASE}/categories/")
    total_cats = len(cats["results"])
    all_products = []

    for i, cat in enumerate(cats["results"]):
        cat_name = cat["name"]
        if progress_cb:
            progress_cb(f"[{i+1}/{total_cats}] {cat_name}...")

        for sub in cat.get("categories", []):
            sub_id = sub["id"]
            sub_name = sub["name"]
            try:
                sub_data = fetch_json(f"{API_BASE}/categories/{sub_id}")
            except Exception as e:
                if progress_cb:
                    progress_cb(f"  Error en {sub_name}: {e}")
                continue

            # Los productos están en sub_data["categories"][].products
            # (sub-subcategorías dentro de la subcategoría)
            for sub_sub in sub_data.get("categories", []):
                for prod in sub_sub.get("products", []):
                    pi = prod.get("price_instructions", {})
                    all_products.append({
                        "id": prod["id"],
                        "slug": prod.get("slug", ""),
                        "display_name": prod.get("display_name", ""),
                        "category_id": cat["id"],
                        "category_name": cat_name,
                        "subcategory_id": sub_id,
                        "subcategory_name": f"{sub_name} / {sub_sub.get('name', '')}",
                        "packaging": prod.get("packaging", ""),
                        "unit_price": float(pi.get("unit_price", 0) or 0),
                        "bulk_price": float(pi.get("bulk_price", 0) or 0),
                        "unit_size": pi.get("unit_size"),
                        "size_format": pi.get("size_format", ""),
                        "is_pack": 1 if pi.get("is_pack") else 0,
                        "pack_size": pi.get("pack_size"),
                        "total_units": str(pi.get("total_units") or ""),
                        "share_url": prod.get("share_url", ""),
                        "thumbnail": prod.get("thumbnail", ""),
                        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    })
            time.sleep(0.1)  # No saturar la API

    return all_products


def save_catalog(conn, products):
    """Guarda los productos en SQLite (reemplaza todo)."""
    conn.execute(f"DELETE FROM {CATALOG_TABLE}")
    conn.executemany(f"""
        INSERT OR REPLACE INTO {CATALOG_TABLE} 
        (id, slug, display_name, display_name_norm, category_id, category_name,
         subcategory_id, subcategory_name, packaging,
         unit_price, bulk_price, unit_size, size_format,
         is_pack, pack_size, total_units, share_url, thumbnail, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(
        p["id"], p["slug"], p["display_name"],
        normalize_desc(p["display_name"]),
        p["category_id"], p["category_name"],
        p["subcategory_id"], p["subcategory_name"],
        p["packaging"], p["unit_price"], p["bulk_price"],
        p["unit_size"], p["size_format"], p["is_pack"],
        p["pack_size"], p["total_units"], p["share_url"],
        p["thumbnail"], p["updated_at"]
    ) for p in products])
    conn.commit()


def normalize_desc(desc):
    """Normaliza una descripción para comparar.
    Quita acentos, pasa a minúsculas, pero mantiene palabras separadas."""
    import unicodedata
    d = unicodedata.normalize("NFD", desc).encode("ascii", "ignore").decode()
    # Mantener palabras separadas, quitar puntuación
    d = re.sub(r"[^a-z0-9\s]", "", d.lower())
    d = re.sub(r"\s+", " ", d).strip()
    return d


def match_ticket_to_catalog(conn, ticket_desc, ticket_price=None):
    """Intenta encontrar el producto del catálogo que corresponde
    a una descripción de ticket. Usa matching de texto + precio.
    
    Estrategia:
    1. Matching directo normalizado
    2. Si no hay match, buscar por palabras clave + precio
    3. Si hay varios candidatos por precio, elegir el más cercano
    
    Devuelve lista de candidatos ordenados por score."""
    cur = conn.cursor()

    ticket_norm = normalize_desc(ticket_desc)
    ticket_words = set(ticket_norm.split())
    # Filtrar palabras muy cortas o genéricas
    STOP_WORDS = {"p", "p6", "p12", "p3", "s", "sin", "con", "c", "b", "q", "x", "l"}
    ticket_words_filtered = {w for w in ticket_words if len(w) > 2 and w not in STOP_WORDS}

    candidates = []

    # ESTRATEGIA 1: Buscar en todo el catálogo con LIKE
    # Construir query con las palabras filtradas
    if ticket_words_filtered:
        like_conditions = " AND ".join(
            [f"display_name_norm LIKE ?" for _ in ticket_words_filtered]
        )
        params = []
        for w in ticket_words_filtered:
            params.append(f"%{w}%")
        
        # También buscar por precio cercano si hay
        price_filter = ""
        price_params = []
        if ticket_price:
            price_filter = " AND ABS(unit_price - ?) < 1.0"
            price_params = [ticket_price]

        query = f"""
            SELECT id, display_name, packaging, unit_price, unit_size, 
                   size_format, is_pack, total_units, category_name,
                   subcategory_name
            FROM {CATALOG_TABLE}
            WHERE {like_conditions}{price_filter}
            LIMIT 20
        """
        rows = cur.execute(query, params + price_params).fetchall()

        for row in rows:
            cat_id, name, packaging, price, unit_size, size_format, is_pack, total_units, cat_name, sub_name = row
            name_norm = normalize_desc(name)
            name_words = set(name_norm.split())

            # Score por coincidencia de texto
            score = 0
            if ticket_norm == name_norm:
                score = 100
            elif ticket_norm in name_norm or name_norm in ticket_norm:
                score = 85
            else:
                common = ticket_words & name_words
                if common:
                    weighted_common = sum(1 for w in common if len(w) > 2)
                    weighted_common += sum(0.3 for w in common if len(w) <= 2)
                    total_words = max(len(ticket_words), len(name_words))
                    score = (weighted_common / total_words) * 70

            # Bonus por precio cercano
            if ticket_price and price:
                diff = abs(ticket_price - price)
                if diff < 0.02:
                    score += 40
                elif diff < 0.10:
                    score += 30
                elif diff < 0.50:
                    score += 15
                elif diff < 1.00:
                    score += 5

            if score >= 30:
                candidates.append({
                    "score": score,
                    "catalog_id": cat_id,
                    "display_name": name,
                    "packaging": packaging,
                    "unit_price": price,
                    "unit_size": unit_size,
                    "size_format": size_format,
                    "is_pack": bool(is_pack),
                    "total_units": total_units,
                    "category": cat_name,
                    "subcategory": sub_name,
                })

    # ESTRATEGIA 2: Si no hay candidatos con LIKE, buscar solo por precio
    # Pero exigir al menos una palabra en común para evitar falsos positivos
    if not candidates and ticket_price:
        rows = cur.execute(f"""
            SELECT id, display_name, packaging, unit_price, unit_size, 
                   size_format, is_pack, total_units, category_name,
                   subcategory_name
            FROM {CATALOG_TABLE}
            WHERE ABS(unit_price - ?) < 0.02
            LIMIT 20
        """, (ticket_price,)).fetchall()

        for row in rows:
            cat_id, name, packaging, price, unit_size, size_format, is_pack, total_units, cat_name, sub_name = row
            name_norm = normalize_desc(name)
            name_words = set(name_norm.split())
            
            # Exigir al menos una palabra significativa en común
            common = ticket_words_filtered & name_words
            if not common:
                continue
            
            score = 25 + len(common) * 10
            
            # Bonus por precio exacto
            if ticket_price and price:
                diff = abs(ticket_price - price)
                if diff < 0.02:
                    score += 40

            if score >= 30:
                candidates.append({
                    "score": score,
                    "catalog_id": cat_id,
                    "display_name": name,
                    "packaging": packaging,
                    "unit_price": price,
                    "unit_size": unit_size,
                    "size_format": size_format,
                    "is_pack": bool(is_pack),
                    "total_units": total_units,
                    "category": cat_name,
                    "subcategory": sub_name,
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:5]  # Top 5


def enrich_line_items(conn, progress_cb=None):
    """Intenta enriquecer los line_items con info del catálogo."""
    # Añadir columnas si no existen
    try:
        conn.execute("ALTER TABLE line_items ADD COLUMN catalog_id TEXT")
        conn.execute("ALTER TABLE line_items ADD COLUMN catalog_name TEXT")
        conn.execute("ALTER TABLE line_items ADD COLUMN catalog_packaging TEXT")
        conn.execute("ALTER TABLE line_items ADD COLUMN catalog_size TEXT")
        conn.execute("ALTER TABLE line_items ADD COLUMN catalog_match_score INTEGER")
    except sqlite3.OperationalError:
        pass  # Ya existen

    rows = conn.execute(
        "SELECT id, descripcion, precio_unit FROM line_items"
    ).fetchall()

    total = len(rows)
    matched = 0
    for i, (item_id, desc, price) in enumerate(rows):
        candidates = match_ticket_to_catalog(conn, desc, price)
        if candidates and candidates[0]["score"] >= 65:
            best = candidates[0]
            conn.execute("""
                UPDATE line_items SET 
                    catalog_id = ?, catalog_name = ?, 
                    catalog_packaging = ?, catalog_size = ?,
                    catalog_match_score = ?
                WHERE id = ?
            """, (best["catalog_id"], best["display_name"],
                  best["packaging"], 
                  f"{best['unit_size']} {best['size_format']}" if best['unit_size'] else "",
                  best["score"], item_id))
            matched += 1

        if progress_cb and (i + 1) % 100 == 0:
            progress_cb(f"  Enriquecidos {i+1}/{total} ({matched} matched)")

    conn.commit()
    return matched, total


def update_catalog(progress_cb=None):
    """Descarga el catálogo y lo guarda en la BD."""
    conn = sqlite3.connect(str(DB_PATH))
    init_catalog_table(conn)

    products = download_catalog(progress_cb)
    if progress_cb:
        progress_cb(f"Guardando {len(products)} productos en BD...")
    save_catalog(conn, products)

    if progress_cb:
        progress_cb(f"Enriqueciendo line_items...")
    matched, total = enrich_line_items(conn, progress_cb)

    conn.close()
    return len(products), matched, total


if __name__ == "__main__":
    def print_progress(msg):
        print(msg)

    n_prod, n_matched, n_total = update_catalog(print_progress)
    print(f"\nCatálogo: {n_prod} productos descargados")
    print(f"Enriquecimiento: {n_matched}/{n_total} items matched")