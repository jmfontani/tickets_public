#!/usr/bin/env python
"""Pipeline orquestador: ingesta IMAP → parse PDFs + OCR imágenes → SQLite → normalizar.

Usa src/ingest.py (imaplib directo, multi-cuenta) en vez del legacy
fetch_emails.py (himalaya CLI).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.ingest import run_ingestion
from src.database import init_db, get_tickets, get_all_items


def run_pipeline():
    print("=" * 60)
    print("  PIPELINE TICKETS DASHBOARD")
    print("=" * 60)

    def progress(msg):
        print(f"  {msg}")

    result = run_ingestion(progress, since_days=7)

    if "error" in result:
        print(f"\n  ERROR: {result['error']}")
        return

    # Resumen
    print("\n" + "=" * 60)
    print("  RESUMEN")
    print("=" * 60)
    all_items = get_all_items()
    db_tickets = get_tickets()
    total_gastado = sum(t["total"] for t in db_tickets)
    fecha_min = min(t["fecha"] for t in db_tickets) if db_tickets else "N/A"
    fecha_max = max(t["fecha"] for t in db_tickets) if db_tickets else "N/A"

    print(f"  Tickets en BD:      {len(db_tickets)}")
    print(f"  Items en BD:        {len(all_items)}")
    print(f"  Total gastado:      {total_gastado:.2f} €")
    if db_tickets:
        print(f"  Ticket medio:       {total_gastado / len(db_tickets):.2f} €")
    print(f"  Rango fechas:       {fecha_min} -> {fecha_max}")
    print(f"  Productos unicos:   {len(set(i['descripcion'] for i in all_items))}")
    print(f"\n  Emails encontrados: {result.get('emails_found', 0)}")
    print(f"  PDFs nuevos:        {result.get('pdfs_downloaded', 0)}")
    print(f"  Imagenes nuevas:    {result.get('images_downloaded', 0)}")
    print(f"  Tickets desde PDF:  {result.get('tickets_from_pdf', 0)}")
    print(f"  Tickets desde img:   {result.get('tickets_from_image', 0)}")
    if result.get("errors"):
        print(f"  Errores:            {len(result['errors'])}")
        for e in result["errors"][:5]:
            print(f"    - {e}")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()