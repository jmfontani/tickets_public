#!/usr/bin/env python3
"""Rellena `cuadre_ok` / `cuadre_diff` en los tickets ya existentes.

El cuadre es aritmética sobre datos que ya están en la BD: suma de `line_items.importe`
frente a `tickets.total`. No interviene ningún modelo, así que el relleno histórico es
exacto y reversible (volver a poner NULL).

Uso:
    python3 scripts/backfill_cuadre.py            # hace copia de seguridad y rellena
    python3 scripts/backfill_cuadre.py --dry-run   # sólo informa
"""
import argparse
import datetime as dt
import shutil
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "tickets.db"
TOLERANCIA = 0.02  # € — mismo umbral que src/ocr_llm.py::CUADRE_TOLERANCIA


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    db = Path(a.db)

    if not a.dry_run:
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        copia = db.with_suffix(f".db.bak_cuadre_{sello}")
        shutil.copy2(db, copia)
        print(f"copia de seguridad: {copia}")

    con = sqlite3.connect(str(db))
    cols = {r[1] for r in con.execute("PRAGMA table_info(tickets)")}
    for col, tipo in (("cuadre_ok", "INTEGER"), ("cuadre_diff", "REAL")):
        if col not in cols:
            if a.dry_run:
                print(f"(dry-run) faltaría añadir columna {col}")
            else:
                con.execute(f"ALTER TABLE tickets ADD COLUMN {col} {tipo}")
                print(f"columna añadida: {col} {tipo}")
    if not a.dry_run:
        con.commit()

    filas = con.execute(
        """SELECT t.id, t.source_type, t.total, SUM(li.importe) AS suma, COUNT(li.id) AS n
           FROM tickets t LEFT JOIN line_items li ON li.ticket_id = t.id
           GROUP BY t.id""").fetchall()

    upd, ok_n, bad_n, nan_n = [], 0, 0, 0
    for tid, stype, total, suma, n in filas:
        try:
            total_f = float(total)
        except (TypeError, ValueError):
            total_f = 0.0
        if not n or total_f <= 0 or suma is None:
            upd.append((None, None, tid))
            nan_n += 1
            continue
        diff = round(round(float(suma), 2) - total_f, 2)
        ok = 1 if abs(diff) <= TOLERANCIA else 0
        ok_n += ok
        bad_n += 1 - ok
        upd.append((ok, diff, tid))

    print(f"tickets: {len(filas)} | cuadran: {ok_n} | descuadran: {bad_n} | no evaluables: {nan_n}")
    if a.dry_run:
        print("(dry-run) no se escribe nada")
        return 0

    con.executemany("UPDATE tickets SET cuadre_ok=?, cuadre_diff=? WHERE id=?", upd)
    con.commit()

    # desglose por origen: el descuadre en PDF es del parser de texto, en foto es del OCR
    print("\ndesglose por origen:")
    for stype, n, ok, bad in con.execute(
            """SELECT source_type, COUNT(*), SUM(cuadre_ok=1), SUM(cuadre_ok=0)
               FROM tickets GROUP BY source_type"""):
        print(f"  {stype or '(vacío)'}: {n} tickets — cuadran {ok or 0}, descuadran {bad or 0}")

    print("\nprimeros 10 descuadres:")
    for r in con.execute(
            """SELECT num_ticket, fecha, source_type, total, cuadre_diff, source_file
               FROM tickets WHERE cuadre_ok=0 ORDER BY ABS(cuadre_diff) DESC LIMIT 10"""):
        print(f"  {r[0][:22]:22s} {r[1][:16]:16s} {r[2]:11s} total {r[3]:>7} dif {r[4]:>8} {r[5][:38]}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
