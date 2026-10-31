#!/usr/bin/env python3
"""Reprocesa UN ticket concreto desde su imagen original (por defecto, dry run).

Borra el ticket y sus line_items y lo vuelve a extraer del LLM con el prompt
actual, reinsertandolo con el MISMO pipeline que la ingesta (insert_ticket,
que ademas normaliza y clasifica).

Uso:
    reprocesa_ticket.py <id|source_file>            # DRY RUN
    reprocesa_ticket.py <id|source_file> --apply    # ejecuta

Notas:
  - line_items tiene REFERENCES tickets(id) ON DELETE CASCADE en el esquema,
    pero SQLite NO aplica FK por defecto (PRAGMA foreign_keys=0). Se borran
    las lineas EXPLICITAMENTE para no dejar huerfanos.
  - insert_ticket deduplica por content_hash: como la imagen no cambia, hay que
    borrar el ticket viejo ANTES (su hash desaparece con el) para que la
    reinsercion no se salte por deduplicacion.
  - Se hace copia de seguridad de la BD antes de escribir.
"""
import argparse
import datetime
import hashlib
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

BASE = Path("/ruta/a/tickets")
sys.path.insert(0, str(BASE))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from src import database as db              # noqa: E402
from src.database import SCHEMA, DB_PATH, init_db  # noqa: E402
from src.ingest import process_image_to_ticket, PHOTOS_DIR  # noqa: E402


def localiza(conn, clave):
    if clave.isdigit():
        return conn.execute("SELECT * FROM tickets WHERE id=?", (int(clave),)).fetchone()
    return conn.execute("SELECT * FROM tickets WHERE source_file=?", (clave,)).fetchone()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clave", help="id del ticket o nombre del fichero de imagen")
    ap.add_argument("--apply", action="store_true", help="ejecuta (por defecto dry run)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    init_db(DB_PATH)

    fila = localiza(conn, args.clave)
    if not fila:
        sys.exit(f"No se encontro ticket para {args.clave!r}")
    fila = dict(fila)

    tid = fila["id"]
    img = PHOTOS_DIR / fila["source_file"]
    print(f"Ticket {tid}: comercio={fila['comercio']} fecha={fila['fecha']} total={fila['total']}")
    print(f"  imagen: {img}")
    if not img.exists():
        sys.exit(f"  ERROR: la imagen no existe: {img}")

    n = conn.execute("SELECT COUNT(*) FROM line_items WHERE ticket_id=?", (tid,)).fetchone()[0]
    s = conn.execute("SELECT COALESCE(SUM(importe),0) FROM line_items WHERE ticket_id=?", (tid,)).fetchone()[0]
    print(f"  lineas actuales: {n}   suma={s:.2f}   total={fila['total']}   diff={s - float(fila['total']):+.2f}")

    if not args.apply:
        print("\nDRY RUN: no se ha tocado nada. Repetir con --apply para ejecutar.")
        return

    bak = Path(DB_PATH).parent / f"tickets.db.bak-pre-reproceso{tid}-{datetime.datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(DB_PATH, bak)
    print(f"  backup: {bak.name}")

    print("  extrayendo del LLM (puede tardar varios minutos)...")
    # EXTRAER PRIMERO: si el LLM falla, el ticket original queda intacto.
    # Con reintentos: el fallo (prosa en vez de JSON) es intermitente.
    ticket, ultimo = None, None
    for intento in range(1, 5):
        try:
            ticket = process_image_to_ticket(str(img))
            break
        except Exception as e:
            ultimo = e
            print(f"  intento {intento}/4 fallido: {type(e).__name__}: {str(e)[:90]}")
    if ticket is None:
        print("  NO se pudo extraer; el ticket original queda INTACTO.")
        raise ultimo or RuntimeError("extraccion fallida")
    comercio_prev = fila["comercio"]
    comercio = (getattr(ticket, "tienda", "") or "").lower().strip() or "otros"
    if comercio in ("otros", ""):
        comercio = comercio_prev
    chash = hashlib.md5(img.read_bytes()).hexdigest()

    conn.execute("DELETE FROM line_items WHERE ticket_id=?", (tid,))
    conn.execute("DELETE FROM tickets WHERE id=?", (tid,))
    conn.commit()
    print(f"  ticket {tid} y sus lineas borrados")

    nuevo = db.insert_ticket(conn, ticket, comercio=comercio,
                             source_type="email_photo", source_file=fila["source_file"],
                             content_hash=chash)
    conn.commit()

    # Mismo cierre que run_ingestion: normalize rellena `categoria` y
    # apply_taxonomy_to_db rellena categoria_general/subcategoria. Sin las dos,
    # las lineas quedan sin clasificar y el dashboard las agrupa en "Otros".
    from src.normalize import normalize_all_in_db
    from src.taxonomy import apply_taxonomy_to_db
    print("  normalizando y aplicando taxonomia...")
    normalize_all_in_db()
    apply_taxonomy_to_db()

    n2 = conn.execute("SELECT COUNT(*) FROM line_items WHERE ticket_id=?", (nuevo,)).fetchone()[0]
    s2 = conn.execute("SELECT COALESCE(SUM(importe),0) FROM line_items WHERE ticket_id=?", (nuevo,)).fetchone()[0]
    t2 = conn.execute("SELECT total, comercio FROM tickets WHERE id=?", (nuevo,)).fetchone()
    print(f"\n  RESULTADO: id={nuevo}  comercio={t2['comercio']}  lineas={n2}  "
          f"suma={s2:.2f}  total={t2['total']}  diff={s2 - float(t2['total']):+.2f}")
    if n2 == 0:
        print("  ATENCION: 0 lineas — revisar la extraccion")


if __name__ == "__main__":
    main()
