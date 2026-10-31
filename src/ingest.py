"""Ingesta incremental de tickets desde múltiples cuentas IMAP.
Descarga PDFs adjuntos de Mercadona, imágenes de emails [ticket] de cualquier comercio,
parsea los PDFs y procesa las imágenes con OCR/LLM, e inserta todo en SQLite.
Usa imaplib directamente (sin himalaya) para soportar múltiples cuentas.
"""
import imaplib
import email
import email.utils
import hashlib
import os
import re
import io
import time
import logging
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import List, Optional, Callable, Dict

from .parse_ticket import parse_pdf, parse_all, Ticket
from .database import init_db, insert_ticket, DB_PATH
from .normalize import normalize_all_in_db
from .config import load_accounts_full

import sqlite3

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data" / "raw_pdfs"
PHOTOS_DIR = BASE_DIR / "data" / "raw_photos"

MERCADONA_SENDERS = [
    "ticket_digital@mail.mercadona.com",
]

# Patrón para detectar emails con tickets: asunto [ticket]
TICKET_SUBJECT_RE = re.compile(r'\[ticket\]', re.IGNORECASE)

# Extensiones de imagen soportadas para emails [ticket]
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp'}

# Import condicional de ocr_llm (degradación elegante)
try:
    from .ocr_llm import process_image_to_ticket
    _OCR_AVAILABLE = True
    logger.debug("ocr_llm importado correctamente")
except ImportError as e:
    _OCR_AVAILABLE = False
    process_image_to_ticket = None
    logger.warning("ocr_llm no disponible (ImportError: %s) — imágenes se descargarán pero no procesarán", e)
except Exception as e:
    _OCR_AVAILABLE = False
    process_image_to_ticket = None
    logger.warning("ocr_llm no disponible (error: %s) — imágenes se descargarán pero no procesarán", e)


# ─── Utilidades ─────────────────────────────────────────────────────────

def _decode_mime_header(value):
    """Decodifica un header MIME."""
    if value is None:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _is_mercadona(msg) -> bool:
    """Comprueba si el email es de Mercadona."""
    sender = _decode_mime_header(msg.get("From", "")).lower()
    return any(s in sender for s in MERCADONA_SENDERS)


def _get_attachments(msg) -> list:
    """Extrae PDFs adjuntos del mensaje."""
    attachments = []
    for part in msg.walk():
        content_disposition = part.get("Content-Disposition", "")
        if "attachment" not in content_disposition:
            continue
        filename = part.get_filename()
        if filename and filename.lower().endswith(".pdf"):
            payload = part.get_payload(decode=True)
            attachments.append((filename, payload))
    return attachments


def _get_image_attachments(msg) -> list:
    """Extrae imágenes adjuntas del mensaje (JPG, PNG, HEIC, etc.)."""
    attachments = []
    for part in msg.walk():
        content_disposition = part.get("Content-Disposition", "")
        if "attachment" not in content_disposition:
            continue
        filename = part.get_filename()
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append((filename, payload))
    return attachments


def _has_ticket_subject(subject: str) -> bool:
    """Comprueba si el asunto del email contiene la etiqueta [ticket]."""
    return bool(TICKET_SUBJECT_RE.search(subject))


def _email_date_to_str(msg) -> str:
    """Extrae la fecha del email y la formatea como YYYYMMDD."""
    date_raw = msg.get("Date", "")
    if date_raw:
        try:
            dt = email.utils.parsedate_to_datetime(date_raw)
            return dt.strftime("%Y%m%d")
        except (TypeError, ValueError):
            pass
    return datetime.now().strftime("%Y%m%d")


def _imap_date_filter(days: int = 7) -> str:
    """Genera string de fecha para filtro IMAP (SINCE)."""
    since_date = datetime.now() - timedelta(days=days)
    return since_date.strftime("%d-%b-%Y")


def _imap_search_since(mail, search_criteria: str, since_days: int = 7) -> list:
    """Ejecuta búsqueda IMAP con filtro de fecha SINCE."""
    since_str = _imap_date_filter(since_days)
    full_criteria = f'{search_criteria} SINCE "{since_str}"'
    status, data = mail.search(None, full_criteria)
    if status != "OK":
        return []
    return data[0].split()


# ─── Fase 1A: Descargar PDFs de Mercadona ──────────────────────────────

def fetch_from_account(account: dict, progress_cb: Optional[Callable] = None,
                        raw_dir: Path = None, since_days: int = 7) -> dict:
    """Conecta a una cuenta IMAP, busca emails de Mercadona, descarga PDFs.
    Devuelve dict con: {found, downloaded, errors, new_pdfs, pdf_account_map}"""
    raw_dir = raw_dir or RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    result = {"found": 0, "downloaded": 0, "errors": [], "new_pdfs": [], "pdf_account_map": {}}

    if progress_cb:
        progress_cb(f"Conectando a {account['email']}...")

    try:
        mail = imaplib.IMAP4_SSL(account["imap_host"], account.get("imap_port", 993))
        mail.login(account["email"], account["password"])

        try:
            mail.select('"[Gmail]/Todos"')
        except imaplib.IMAP4.error:
            mail.select("INBOX")

        search_criteria = f'(FROM "{MERCADONA_SENDERS[0]}")'
        mail_ids = _imap_search_since(mail, search_criteria, since_days)
        if not mail_ids:
            result["found"] = 0
            mail.logout()
            return result
        result["found"] = len(mail_ids)

        if progress_cb:
            progress_cb(f"Encontrados {len(mail_ids)} emails de Mercadona en {account['email']}")

        for i, mid in enumerate(mail_ids):
            status, msg_data = mail.fetch(mid, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            if not _is_mercadona(msg):
                continue

            attachments = _get_attachments(msg)
            for filename, payload in attachments:
                safe_name = filename.replace("/", "_").replace("\\", "_")
                pdf_path = raw_dir / safe_name

                if pdf_path.exists():
                    result["pdf_account_map"][safe_name] = account["email"]
                    continue

                with open(pdf_path, "wb") as f:
                    f.write(payload)
                result["downloaded"] += 1
                result["new_pdfs"].append(safe_name)
                result["pdf_account_map"][safe_name] = account["email"]

            if progress_cb and (i + 1) % 5 == 0:
                progress_cb(f"Procesando email {i+1}/{len(mail_ids)} de {account['email']}")

        mail.logout()

    except imaplib.IMAP4.error as e:
        result["errors"].append(f"Error IMAP {account['email']}: {e}")
    except Exception as e:
        result["errors"].append(f"Error {account['email']}: {e}")

    if progress_cb:
        progress_cb(f"Cuenta {account['email']}: {result['downloaded']} PDFs nuevos descargados")

    return result


# ─── Fase 1B: Descargar imágenes de emails [ticket] ─────────────────────

def fetch_ticket_emails(account: dict,
                        progress_cb: Optional[Callable] = None,
                        raw_dir: Path = None,
                        photos_dir: Path = None,
                        since_days: int = 7) -> dict:
    """Busca emails con asunto [ticket] y descarga imágenes adjuntas."""
    photos_dir = photos_dir or PHOTOS_DIR
    photos_dir.mkdir(parents=True, exist_ok=True)

    result: Dict = {
        "found": 0,
        "downloaded": 0,
        "errors": [],
        "new_images": [],
    }

    if progress_cb:
        progress_cb(f"Buscando emails [ticket] en {account['email']}...")

    try:
        mail = imaplib.IMAP4_SSL(account["imap_host"], account.get("imap_port", 993))
        mail.login(account["email"], account["password"])

        try:
            mail.select('"[Gmail]/Todos"')
        except imaplib.IMAP4.error:
            mail.select("INBOX")

        mail_ids = _imap_search_since(mail, 'SUBJECT "[ticket]"', since_days)

        ticket_emails = []
        for mid in mail_ids:
            status, msg_data = mail.fetch(mid, "(RFC822)")
            if status != "OK":
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_mime_header(msg.get("Subject", ""))
            if _has_ticket_subject(subject):
                ticket_emails.append((mid, msg))

        result["found"] = len(ticket_emails)

        if progress_cb:
            progress_cb(f"Encontrados {len(ticket_emails)} emails [ticket] en {account['email']}")

        for i, (mid, msg) in enumerate(ticket_emails):
            image_attachments = _get_image_attachments(msg)
            if not image_attachments:
                continue

            fecha_email = _email_date_to_str(msg)

            for orig_filename, payload in image_attachments:
                ext = Path(orig_filename).suffix.lower()
                safe_orig = Path(orig_filename).stem.replace(" ", "_")[:20]
                content_hash = hashlib.md5(payload).hexdigest()[:12]
                img_name = f"ticket_{fecha_email}_{content_hash}_{safe_orig}{ext}"
                img_path = photos_dir / img_name

                # Si ya existe este archivo exacto, saltar
                if img_path.exists():
                    continue

                # Verificar si ya existe otro archivo con el mismo contenido (hash)
                # para evitar duplicados con nombres distintos
                already_downloaded = False
                for existing in photos_dir.iterdir():
                    if existing.is_file() and existing.suffix.lower() in IMAGE_EXTENSIONS:
                        try:
                            existing_hash = hashlib.md5(existing.read_bytes()).hexdigest()[:12]
                            if existing_hash == content_hash:
                                already_downloaded = True
                                break
                        except OSError:
                            pass

                if already_downloaded:
                    continue

                try:
                    with open(img_path, "wb") as f:
                        f.write(payload)
                    result["downloaded"] += 1
                    result["new_images"].append(img_name)
                except OSError as e:
                    result["errors"].append(f"Error guardando {img_name}: {e}")


            if progress_cb and (i + 1) % 5 == 0:
                progress_cb(f"Procesando email [ticket] {i+1}/{len(ticket_emails)} de {account['email']}")

        mail.logout()

    except imaplib.IMAP4.error as e:
        result["errors"].append(f"Error IMAP {account['email']}: {e}")
    except Exception as e:
        result["errors"].append(f"Error {account['email']}: {e}")

    if progress_cb:
        progress_cb(f"Cuenta {account['email']}: {result['downloaded']} imágenes nuevas de [ticket]")

    return result


# ─── Fase 2B: Procesar imágenes con OCR/LLM ─────────────────────────────

def _process_images(new_images: List[str],
                    conn: sqlite3.Connection,
                    progress_cb: Optional[Callable] = None) -> dict:
    """Procesa imágenes de tickets con OCR/LLM y las inserta en la BD."""
    result = {"tickets_from_image": 0, "errors": []}

    if not new_images:
        return result

    if not _OCR_AVAILABLE or process_image_to_ticket is None:
        msg = f"ocr_llm no disponible — {len(new_images)} imágenes no procesadas"
        logger.warning(msg)
        if progress_cb:
            progress_cb(f"  ⚠ {msg}")
        result["errors"].append(msg)
        return result

    for img_name in new_images:
        img_path = PHOTOS_DIR / img_name
        if not img_path.exists():
            result["errors"].append(f"Imagen no encontrada: {img_name}")
            continue

        if progress_cb:
            progress_cb(f"  → Procesando imagen: {img_name}")

        try:
            content_hash = hashlib.md5(img_path.read_bytes()).hexdigest()
            ticket = process_image_to_ticket(str(img_path))
            comercio = getattr(ticket, 'tienda', '').lower() or 'otros'

            insert_ticket(
                conn,
                ticket,
                comercio=comercio,
                source_type='email_photo',
                source_file=img_name,
                content_hash=content_hash,
            )
            result["tickets_from_image"] += 1

            # Cuadre aritmético (calculado en ocr_llm.compute_cuadre, no por el modelo):
            # si la suma de items no cuadra con el total, se avisa explícitamente.
            cuadre_ok = getattr(ticket, "cuadre_ok", None)
            cuadre_diff = getattr(ticket, "cuadre_diff", None)
            if cuadre_ok is False:
                result["descuadres"] = result.get("descuadres", 0) + 1
                msg = (f"Descuadre OCR en {img_name}: suma de items se desvía "
                       f"{cuadre_diff:+.2f} € del total {ticket.total} €")
                logger.warning(msg)
                result["errors"].append(msg)
                if progress_cb:
                    progress_cb(f"    ⚠ {msg}")

            if progress_cb:
                progress_cb(f"    ✓ Ticket insertado: {comercio}, {len(ticket.items)} items, {ticket.total}€")

        except ConnectionError as e:
            logger.error("Error de conexión al LLM para %s: %s", img_name, e)
            result["errors"].append(f"LLM no disponible para {img_name}: {e}")
            if progress_cb:
                progress_cb(f"    ✗ LLM no disponible: {img_name}")
        except Exception as e:
            logger.error("Error procesando %s: %s", img_name, e, exc_info=True)
            result["errors"].append(f"Error procesando {img_name}: {e}")
            if progress_cb:
                progress_cb(f"    ✗ Error: {img_name} — {e}")

    return result


def _find_unprocessed_images(conn: sqlite3.Connection) -> List[str]:
    """Encuentra imágenes en data/raw_photos/ que no tienen ticket en la BD."""
    if not PHOTOS_DIR.exists():
        return []

    try:
        cursor = conn.execute(
            "SELECT source_file, content_hash FROM tickets "
            "WHERE source_type = 'email_photo' AND source_file != ''"
        )
        processed_names = set()
        processed_hashes = set()
        for name, h in cursor.fetchall():
            processed_names.add(name)
            if h:
                processed_hashes.add(h)
    except sqlite3.OperationalError:
        processed_names = set()
        processed_hashes = set()

    unprocessed = []
    for f in PHOTOS_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            if f.name in processed_names:
                continue
            try:
                content_hash = hashlib.md5(f.read_bytes()).hexdigest()
            except OSError:
                content_hash = ""
            if content_hash and content_hash in processed_hashes:
                continue
            unprocessed.append(f.name)

    return sorted(unprocessed)


# ─── Orquestador principal ─────────────────────────────────────────────

def run_ingestion(progress_cb: Optional[Callable] = None, since_days: int = 7) -> dict:
    """Ejecuta ingesta incremental desde todas las cuentas configuradas.

    Fase 1: Descargar PDFs de Mercadona + imágenes de [ticket]
    Fase 2: Parsear PDFs + Procesar imágenes con OCR/LLM
    Fase 3: Normalizar productos

    Args:
        progress_cb: Función de callback para progreso.
        since_days: Días hacia atrás para filtrar emails IMAP (default: 7).

    Devuelve resumen con stats.
    """
    if progress_cb:
        progress_cb(f"Iniciando ingesta incremental (últimos {since_days} días)...")

    accounts = load_accounts_full()
    if not accounts:
        if progress_cb:
            progress_cb("No hay cuentas configuradas. Añade una en la pestaña Configuración.")
        return {"error": "No hay cuentas configuradas"}

    # ═══ Fase 1: Descargar PDFs nuevos + imágenes nuevas ═══
    if progress_cb:
        progress_cb(f"Fase 1/3: Descargando PDFs e imágenes de {len(accounts)} cuenta(s)...")

    all_new_pdfs = []
    total_found = 0
    total_downloaded = 0
    all_errors = []
    pdf_account_map = {}

    for acc in accounts:
        if progress_cb:
            progress_cb(f"  → [PDFs] Procesando cuenta: {acc['email']}")
        r = fetch_from_account(acc, progress_cb, RAW_DIR, since_days)
        total_found += r["found"]
        total_downloaded += r["downloaded"]
        all_new_pdfs.extend(r["new_pdfs"])
        all_errors.extend(r["errors"])
        pdf_account_map.update(r["pdf_account_map"])

    if progress_cb:
        progress_cb(f"  PDFs: {total_found} emails encontrados, {total_downloaded} PDFs nuevos")

    # Fase 1B: Imágenes de emails [ticket]
    all_new_images = []
    total_ticket_emails_found = 0
    total_images_downloaded = 0

    for acc in accounts:
        if progress_cb:
            progress_cb(f"  → [Imágenes] Buscando [ticket] en: {acc['email']}")
        r = fetch_ticket_emails(acc, progress_cb, RAW_DIR, PHOTOS_DIR, since_days)
        total_ticket_emails_found += r["found"]
        total_images_downloaded += r["downloaded"]
        all_new_images.extend(r["new_images"])
        all_errors.extend(r["errors"])

    if progress_cb:
        progress_cb(
            f"  Imágenes: {total_ticket_emails_found} emails [ticket] encontrados, "
            f"{total_images_downloaded} imágenes nuevas"
        )
        progress_cb("Fase 1 completada.")

    # ═══ Fase 2: Parsear PDFs + Procesar imágenes ═══
    if progress_cb:
        progress_cb("Fase 2/3: Parseando tickets e insertando en base de datos...")

    init_db()
    conn = sqlite3.connect(str(DB_PATH))

    # Fase 2A: Parsear e insertar TODOS los PDFs
    tickets = parse_all(str(RAW_DIR), account_map=pdf_account_map)
    tickets_from_pdf = 0
    for t in tickets:
        insert_ticket(
            conn,
            t,
            comercio="mercadona",
            source_type="email_pdf",
            source_file=t.pdf_file or "",
        )
        tickets_from_pdf += 1

    if progress_cb:
        progress_cb(f"  PDFs: {tickets_from_pdf} tickets en base de datos")

    # Fase 2B: Procesar imágenes nuevas con OCR/LLM
    unprocessed = _find_unprocessed_images(conn)
    images_to_process = list(set(all_new_images + unprocessed))

    if images_to_process and progress_cb:
        progress_cb(
            f"  Imágenes a procesar: {len(images_to_process)} "
            f"({len(all_new_images)} nuevas + {len(unprocessed)} pendientes)"
        )

    img_result = _process_images(images_to_process, conn, progress_cb)
    tickets_from_image = img_result["tickets_from_image"]
    all_errors.extend(img_result["errors"])

    if progress_cb:
        progress_cb(f"  Imágenes: {tickets_from_image} tickets procesados")
        progress_cb("Fase 2 completada.")

    conn.close()

    # ═══ Fase 3: Normalizar ═══
    if progress_cb:
        progress_cb("Fase 3/3: Normalizando productos...")

    normalize_all_in_db()

    # Re-aplicar taxonomía (categoria_general/subcategoria) a los items nuevos:
    # normalize_all_in_db solo rellena categoria; sin esto los items recién
    # insertados quedan con categoria_general NULL y el dashboard los agrupa
    # en "Otros". Respeta overrides y llm_classified.
    from .taxonomy import apply_taxonomy_to_db

    apply_taxonomy_to_db()

    if progress_cb:
        progress_cb("¡Ingesta completada!")

    # Stats finales
    conn = sqlite3.connect(str(DB_PATH))
    n_tickets = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    n_items = conn.execute("SELECT COUNT(*) FROM line_items").fetchone()[0]
    total = conn.execute("SELECT SUM(total) FROM tickets").fetchone()[0] or 0
    conn.close()

    return {
        "emails_found": total_found,
        "ticket_emails_found": total_ticket_emails_found,
        "pdfs_downloaded": total_downloaded,
        "images_downloaded": total_images_downloaded,
        "tickets_from_pdf": tickets_from_pdf,
        "tickets_from_image": tickets_from_image,
        "tickets_in_db": n_tickets,
        "items_in_db": n_items,
        "total_gastado": round(total, 2),
        "errors": all_errors,
        "new_pdf_files": all_new_pdfs,
        "new_image_files": all_new_images,
    }


def run_ocr_only(progress_cb: Optional[Callable] = None) -> dict:
    """Reprocesa SOLO las imágenes pendientes de OCR (sin tocar IMAP ni PDFs).

    Útil para reintentar fotos que fallaron por un modelo caído o sin plan,
    sin volver a descargar correos ni re-parsear los PDFs de Mercadona.
    """
    if progress_cb:
        progress_cb("Reintentando OCR de imágenes pendientes...")

    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    pendientes = _find_unprocessed_images(conn)

    if not pendientes:
        conn.close()
        if progress_cb:
            progress_cb("No hay imágenes pendientes de OCR.")
        return {"tickets_from_image": 0, "pending_before": 0, "errors": []}

    if progress_cb:
        progress_cb(f"Imágenes pendientes: {len(pendientes)}")

    img_result = _process_images(pendientes, conn, progress_cb)
    conn.close()

    normalize_all_in_db()
    from .taxonomy import apply_taxonomy_to_db

    apply_taxonomy_to_db()

    restantes = 0
    conn = sqlite3.connect(str(DB_PATH))
    restantes = len(_find_unprocessed_images(conn))
    conn.close()

    if progress_cb:
        progress_cb(f"OCR terminado: {img_result['tickets_from_image']} tickets, "
                    f"{restantes} imágenes siguen pendientes.")

    return {
        "tickets_from_image": img_result["tickets_from_image"],
        "pending_before": len(pendientes),
        "pending_after": restantes,
        "errors": img_result["errors"],
    }


if __name__ == "__main__":
    def print_progress(msg):
        print(msg)
    result = run_ingestion(print_progress)
    print(f"\nResultado: {result}")