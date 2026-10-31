"""Descarga todos los tickets PDF de Mercadona desde Gmail vía himalaya CLI."""
import subprocess
import json
import re
import os
from pathlib import Path

HIMALAYA = os.path.expanduser("~/.local/bin/himalaya")
BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data" / "raw_pdfs"
METADATA_FILE = BASE_DIR / "data" / "email_metadata.json"


def search_mercadona_emails():
    """Busca emails de Mercadona en [Gmail]/Todos (incluye INBOX y archivados)."""
    result = subprocess.run(
        [HIMALAYA, "envelope", "list", "--folder", "[Gmail]/Todos",
         "--page", "1", "--page-size", "500",
         "from", "ticket_digital@mail.mercadona.com"],
        capture_output=True, text=True
    )
    emails = []
    for line in result.stdout.strip().split("\n"):
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts or parts[0] == "ID":
            continue
        # Skip separator lines like |-------|-------|...
        if set(parts[0]) == {"-"}:
            continue
        # Columns: ID, [FLAGS], SUBJECT, FROM, DATE
        # FLAGS may be empty (no flag char), so we get 4 or 5 parts
        if len(parts) == 5:
            emails.append({
                "id": parts[0],
                "subject": parts[2],
                "from": parts[3],
                "date": parts[4],
            })
        elif len(parts) == 4:
            emails.append({
                "id": parts[0],
                "subject": parts[1],
                "from": parts[2],
                "date": parts[3],
            })
    return emails


def parse_subject(subject: str) -> dict:
    """Extrae fecha y total del asunto: '20260627 Mercadona 63,53 €'"""
    m = re.match(r"(\d{8})\s+Mercadona\s+([\d,]+)\s*€", subject)
    if m:
        date_str = m.group(1)
        total = float(m.group(2).replace(",", "."))
        return {
            "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
            "total": total,
        }
    return {}


def download_attachments(email_ids: list):
    """Descarga el PDF adjunto de cada email desde [Gmail]/Todos."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for eid in email_ids:
        subprocess.run(
            [HIMALAYA, "attachment", "download", eid,
             "--downloads-dir", str(RAW_DIR),
             "--folder", "[Gmail]/Todos"],
            capture_output=True, text=True
        )


def main():
    # Limpiar PDFs existentes antes de descargar
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for old_pdf in RAW_DIR.glob("*.pdf"):
        old_pdf.unlink()

    emails = search_mercadona_emails()
    print(f"Encontrados {len(emails)} emails de Mercadona")

    metadata = []
    for e in emails:
        info = parse_subject(e["subject"])
        info["email_id"] = e["id"]
        info["raw_subject"] = e["subject"]
        info["email_date"] = e["date"]
        metadata.append(info)

    download_attachments([e["id"] for e in emails])

    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    pdfs = list(RAW_DIR.glob("*.pdf"))
    print(f"Descargados {len(pdfs)} PDFs a {RAW_DIR}")
    print(f"Metadatos guardados en {METADATA_FILE}")
    return metadata


if __name__ == "__main__":
    main()