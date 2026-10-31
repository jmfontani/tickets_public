#!/usr/bin/env python3
"""Reprocesa en lote los tickets de foto cuya suma no cuadra con el total.

Uso:
    reprocesa_lote.py                 # DRY RUN: lista los candidatos
    reprocesa_lote.py --apply         # ejecuta
    reprocesa_lote.py --apply --ids 955,833

Por cada ticket: backup unico de la BD, borrado (lineas + ticket), re-extraccion
con el LLM (modo cloud) y reinsercion. Al final, una sola pasada de
normalize_all_in_db() + apply_taxonomy_to_db() para todos los reinsertados.

Corre en modo CLOUD: glm-5.3-flash. El modelo local (minicpm-v4.5:8b) lee mal la
maquetacion de estos tickets (desplaza importes y confunde lineas de desglose).
"""
import argparse
import datetime
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

BASE = Path("/ruta/a/tickets")
sys.path.insert(0, str(BASE))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from src.database import DB_PATH, SCHEMA, init_db, insert_ticket  # noqa: E402
from src.ingest import process_image_to_ticket, PHOTOS_DIR       # noqa: E402

# Duplicados conocidos: source_file que ya no existe pero cuya imagen sigue en
# disco con otro nombre (mismo contenido).
ALIAS = {
    "ticket_20260825_1787656837_Scan_20260825_122747.jpg":
        "ticket_20260825_d0ea3336d22a_Scan_20260825_122747.jpg",
}


def candidatos(conn, ids=None):
    q = """SELECT t.id, t.comercio, t.total, t.source_file, t.fecha, t.num_ticket,
                  COALESCE(SUM(li.importe),0) s, COUNT(li.id) n
           FROM tickets t JOIN line_items li ON li.ticket_id = t.id
           WHERE t.source_type = 'email_photo'
           GROUP BY t.id
           HAVING ABS(COALESCE(SUM(li.importe),0) - t.total) > 0.06
           ORDER BY ABS(COALESCE(SUM(li.importe),0) - t.total) DESC"""
    filas = [dict(r) for r in conn.execute(q)]
    if ids:
        filas = [f for f in filas if f["id"] in ids]
    return filas


def imagen_de(f):
    """Ruta real de la imagen, aplicando alias si hace falta."""
    p = PHOTOS_DIR / f["source_file"]
    if p.exists():
        return p
    alt = ALIAS.get(f["source_file"])
    if alt and (PHOTOS_DIR / alt).exists():
        return PHOTOS_DIR / alt
    return None


def extrae_con_reintentos(img, intentos=4):
    """Extrae el ticket reintentando si el JSON no sale.

    El LLM devuelve a veces PROSA en vez del JSON ("Let me analyze this
    receipt..."), y falla de forma INTERMITENTE: la misma imagen que falla en un
    intento sale bien en el siguiente. Reintentar es la mitigacion efectiva
    (subir max_tokens y reforzar el prompt NO lo evitan: probado).
    """
    ultimo = None
    for i in range(1, intentos + 1):
        try:
            return process_image_to_ticket(str(img))
        except Exception as e:
            ultimo = e
            print(f"    intento {i}/{intentos} fallido: {type(e).__name__}: {str(e)[:80]}")
    raise ultimo or RuntimeError("extraccion fallida")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ids", default="", help="lista separada por comas")
    args = ap.parse_args()

    ids = {int(x) for x in args.ids.split(",") if x.strip().isdigit()} or None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    init_db(DB_PATH)

    filas = candidatos(conn, ids)
    if not filas:
        print("No hay tickets descuadrados que reprocesar.")
        return

    print(f"{len(filas)} tickets candidatos:\n")
    listos, sin_imagen = [], []
    for f in filas:
        img = imagen_de(f)
        (listos if img else sin_imagen).append((f, img))
        marca = "" if img else "   <-- SIN IMAGEN, se omite"
        print(f"  id={f['id']:5} {str(f['comercio']):16} total={f['total']:>7} "
              f"n={f['n']:3} suma={f['s']:>7.2f} diff={f['s']-float(f['total']):+7.2f}{marca}")

    if not args.apply:
        print(f"\nDRY RUN. Reprocesables: {len(listos)}. Sin imagen: {len(sin_imagen)}.")
        print("Repetir con --apply para ejecutar.")
        return

    bak = Path(DB_PATH).parent / f"tickets.db.bak-lote-{datetime.datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(DB_PATH, bak)
    print(f"\nbackup: {bak.name}\n")

    resultados = []
    for f, img in listos:
        tid = f["id"]
        print(f"--- id={tid} ({f['comercio']}) {f['source_file']}")
        try:
            # EXTRAER PRIMERO. Si el LLM falla, el ticket original sigue intacto:
            # nunca se borra nada hasta tener en la mano la extraccion nueva.
            ticket = extrae_con_reintentos(img)
            comercio_prev = f["comercio"]
            comercio = (getattr(ticket, "tienda", "") or "").lower().strip() or "otros"
            # Si el LLM no reconoce el comercio, conservar el que ya tenia:
            # perder "primaprix" y quedarse en "otros" es una regresion silenciosa.
            if comercio in ("otros", ""):
                comercio = comercio_prev
            chash = hashlib.md5(img.read_bytes()).hexdigest()

            conn.execute("DELETE FROM line_items WHERE ticket_id=?", (tid,))
            conn.execute("DELETE FROM tickets WHERE id=?", (tid,))
            conn.commit()

            nuevo = insert_ticket(conn, ticket, comercio=comercio,
                                  source_type="email_photo",
                                  source_file=img.name, content_hash=chash)
            conn.commit()

            n2 = conn.execute("SELECT COUNT(*) FROM line_items WHERE ticket_id=?", (nuevo,)).fetchone()[0]
            s2 = conn.execute("SELECT COALESCE(SUM(importe),0) FROM line_items WHERE ticket_id=?", (nuevo,)).fetchone()[0]
            t2 = float(conn.execute("SELECT total FROM tickets WHERE id=?", (nuevo,)).fetchone()[0])
            d2 = s2 - t2
            ok = "CUADRA" if abs(d2) <= 0.06 else "sigue descuadrado"
            print(f"    id nuevo={nuevo}  lineas={n2}  suma={s2:.2f}  total={t2:.2f}  "
                  f"diff={d2:+.2f}  [{ok}]")
            resultados.append({"viejo": tid, "nuevo": nuevo, "comercio": comercio,
                               "antes": f["s"] - float(f["total"]), "despues": d2,
                               "lineas_antes": f["n"], "lineas": n2, "ok": abs(d2) <= 0.06})
        except Exception as e:
            print(f"    ERROR: {type(e).__name__}: {e}")
            resultados.append({"viejo": tid, "error": str(e)[:200], "ok": False})

    # Normalizacion + taxonomia: UNA sola pasada al final
    print("\n=== normalize + taxonomia ===")
    try:
        from src.normalize import normalize_all_in_db
        from src.taxonomy import apply_taxonomy_to_db
        normalize_all_in_db()
        apply_taxonomy_to_db()
        print("  OK")
    except Exception as e:
        print(f"  ERROR en normalize/taxonomia: {type(e).__name__}: {e}")

    print("\n=== RESUMEN ===")
    for r in resultados:
        if "error" in r:
            print(f"  id {r['viejo']}: ERROR {r['error'][:80]}")
        else:
            est = "OK" if r["ok"] else "REVISAR"
            print(f"  id {r['viejo']} -> {r['nuevo']}  {r['comercio']:16} "
                  f"diff {r['antes']:+7.2f} -> {r['despues']:+7.2f}  {est}")

    json.dump(resultados, open("/tmp/reproceso_lote.json", "w"), ensure_ascii=False, indent=1)
    print("\ndetalle en /tmp/reproceso_lote.json")


if __name__ == "__main__":
    main()
