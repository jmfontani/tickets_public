#!/usr/bin/env python3
"""Descarga de imágenes de emails [ticket] de todas las cuentas IMAP configuradas.

Este script es una alternativa ROBUSTA a la fase IMAP de `fetch_ticket_emails()`
de src/ingest.py, que se colgaba durante 18+ minutos buscando emails [ticket].

Diferencias clave frente al original:
  1. Timeout a nivel de socket (30 s) — ninguna operación de red cuelga para siempre.
  2. Plazo total de 5 minutos (deadline) compartido entre todas las cuentas.
  3. Timeout por email (30 s máximo procesando cada mensaje).
  4. Selección de carpeta en modo SOLO LECTURA (evita bloqueos y flags \\Seen).
  5. Usa BODY.PEEK (no RFC822) para no marcar los emails como leídos.
  6. Deduplicación por content_hash MD5: no vuelve a descargar imágenes cuyo
     contenido ya existe en disco (mismo hash con nombre distinto).
  7. Nombres de archivo únicos basados en timestamp.
  8. Resumen final con estadísticas por cuenta.

Uso:
    python3 run_email_download.py

Salida:
    Escribe imágenes nuevas en data/raw_photos/.
    Imprime un resumen final con cuentas, emails, imágenes descargadas/duplicadas/errores.
"""
import sys
import time
import logging
import socket
import hashlib
import imaplib
import email
import email.utils
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Dict, List, Optional, Callable

# ─── Ajustar import path para poder usar src.config como módulo local ─────────
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import load_accounts_full  # noqa: E402

# ─── Constantes de configuración ─────────────────────────────────────────────────
PHOTOS_DIR = PROJECT_DIR / "data" / "raw_photos"

# Timeouts
SOCKET_TIMEOUT = 30            # segundos por operación de red (conexión, search, fetch)
PER_EMAIL_TIMEOUT = 30         # segundos máximo procesando un solo email
TOTAL_TIMEOUT = 300            # 5 minutos de presupuesto total para todas las cuentas

# Extensiones de imagen soportadas para emails [ticket]
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp'}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("email_download")


# ─── Utilidades MIME ───────────────────────────────────────────────────────────────
def _decode_mime_header(value: Optional[str]) -> str:
    """Decodifica un header MIME (soporta asunto codificado en base64/quoted-printable)."""
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _has_ticket_subject(subject: str) -> bool:
    """True si el asunto contiene la etiqueta [ticket] (case-insensitive)."""
    return "[ticket]" in subject.lower()


def _email_date_to_str(msg) -> str:
    """Fecha del email formateada YYYYMMDD (fallback: fecha de hoy)."""
    date_raw = msg.get("Date", "")
    if date_raw:
        try:
            dt = email.utils.parsedate_to_datetime(date_raw)
            return dt.strftime("%Y%m%d")
        except (TypeError, ValueError):
            pass
    return datetime.now().strftime("%Y%m%d")


def _get_image_attachments(msg) -> list:
    """Extrae las imágenes adjuntas (JPG, PNG, HEIC, WEBP...) del mensaje.

    Returns:
        Lista de tuplas (filename_original, payload_bytes) por cada imagen adjunta.
    """
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


# ─── Deduplicación por content_hash MD5 ───────────────────────────────────────────
def _build_existing_hashes(photos_dir: Path) -> Dict[str, str]:
    """Mapa {hash_md5: filename} de las imágenes ya presentes en disco.

    Se usa para no volver a descargar una imagen cuyo CONTENIDO ya existe,
    incluso si llegó con un nombre distinto.
    """
    existing = {}
    if not photos_dir.exists():
        return existing
    for f in photos_dir.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            h = hashlib.md5(f.read_bytes()).hexdigest()
        except OSError:
            continue
        existing.setdefault(h, f.name)
    return existing


def _unique_image_name(photos_dir: Path, fecha_email: str, ext: str,
                       existing_hashes: Dict[str, str],
                       counter: int) -> str:
    """Genera un nombre de archivo único: ticket_{fecha}_{timestamp}_{seq}{ext}.

    El timestamp se incrementa con `counter` para evitar colisiones entre
    varias imágenes del mismo email y entre ejecuciones.
    """
    base_ts = int(time.time())
    while True:
        name = f"ticket_{fecha_email}_{base_ts + counter}{ext}"
        if not (photos_dir / name).exists() and name not in existing_hashes.values():
            return name
        counter += 1


# ─── Procesamiento de una cuenta ─────────────────────────────────────────────────
def process_account_images(account: dict,
                           photos_dir: Path,
                           existing_hashes: Dict[str, str],
                           deadline: float,
                           progress_cb: Optional[Callable] = None) -> Dict:
    """Busca emails [ticket] en una cuenta IMAP y descarga sus imágenes.

    Args:
        account: dict con email, password, imap_host, imap_port.
        photos_dir: directorio de salida para las imágenes.
        existing_hashes: mapa {md5: filename} ya en disco (para dedup).
        deadline: timestamp absoluto (time.time()) en el que hay que PARAR.
        progress_cb: opcional, callback(msg).

    Returns:
        Dict con: found, downloaded, duplicate, skipped, errors.
    """
    result = {"found": 0, "downloaded": 0, "duplicate": 0, "skipped": 0, "errors": []}
    email_addr = account.get("email", "?")
    label = account.get("label", email_addr)

    def progress(msg: str):
        if progress_cb:
            progress_cb(msg)

    progress(f"→ {label}: conectando...")

    mail = None
    try:
        # Timeout a nivel de socket: ninguna llamada IMAP puede colgarse > 30 s
        socket.setdefaulttimeout(SOCKET_TIMEOUT)

        mail = imaplib.IMAP4_SSL(account["imap_host"], int(account.get("imap_port", 993)))
        mail.login(account["email"], account["password"])

        # Seleccionar carpeta en SOLO LECTURA (evita marcar \Seen y bloqueos)
        # Busca [Gmail]/Todos (incluye inbox + archivados), fallback a INBOX.
        try:
            typ, _ = mail.select('"[Gmail]/Todos"', readonly=True)
            if typ != "OK":
                raise imaplib.IMAP4.error("select [Gmail]/Todos fallido")
        except imaplib.IMAP4.error:
            try:
                typ, _ = mail.select("INBOX", readonly=True)
                if typ != "OK":
                    raise imaplib.IMAP4.error("select INBOX fallido")
            except imaplib.IMAP4.error as e:
                raise RuntimeError(f"No se pudo seleccionar carpeta: {e}")

        # Búsqueda por asunto [ticket] (substring, case-insensitive en el servidor)
        try:
            typ, data = mail.search(None, 'SUBJECT', '"[ticket]"')
        except imaplib.IMAP4.error as e:
            raise RuntimeError(f"Error en búsqueda IMAP SUBJECT: {e}")
        if typ != "OK":
            raise RuntimeError("Búsqueda IMAP no devolvió OK")

        mail_ids = data[0].split() if data and data[0] else []
        result["found"] = len(mail_ids)
        progress(f"→ {label}: {len(mail_ids)} emails [ticket] encontrados")

        for i, mid in enumerate(mail_ids):
            # Respetar el límite total (5 min)
            if time.time() > deadline:
                result["errors"].append("Timeout total alcanzado — cuenta {label} interrumpida")
                break

            email_start = time.time()

            try:
                # BODY.PEEK no marca el email como leído. Timeout 30 s por email.
                typ, msg_data = mail.fetch(mid, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    result["skipped"] += 1
                    continue

                raw_email = msg_data[0][1]
                if not isinstance(raw_email, bytes):
                    result["skipped"] += 1
                    continue
                msg = email.message_from_bytes(raw_email)

                subject = _decode_mime_header(msg.get("Subject", ""))
                if not _has_ticket_subject(subject):
                    result["skipped"] += 1
                    continue

                fecha_email = _email_date_to_str(msg)
                counter = 0

                for orig_filename, payload in _get_image_attachments(msg):
                    if time.time() - email_start > PER_EMAIL_TIMEOUT:
                        result["errors"].append(
                            f"Timeout por email (>{PER_EMAIL_TIMEOUT}s) en {label}"
                        )
                        break

                    content_hash = hashlib.md5(payload).hexdigest()

                    # Dedup por content_hash: no bajar si el contenido ya está en disco
                    if content_hash in existing_hashes:
                        result["duplicate"] += 1
                        continue

                    ext = Path(orig_filename).suffix.lower()
                    if not ext:
                        ext = ".jpg"  # fallback razonable
                    img_name = _unique_image_name(photos_dir, fecha_email, ext, existing_hashes, counter)
                    counter += 1

                    try:
                        with open(photos_dir / img_name, "wb") as f:
                            f.write(payload)
                        existing_hashes[content_hash] = img_name
                        result["downloaded"] += 1
                        progress(f"  ✓ {img_name}")
                    except OSError as e:
                        result["errors"].append(f"Error guardando {img_name}: {e}")

            except Exception as e:
                result["errors"].append(f"Error procesando email {mid} de {label}: {e}")
                result["skipped"] += 1

            # Progress cada 10 emails
            if progress_cb and (i + 1) % 10 == 0:
                progress(f"→ {label}: procesados {i+1}/{len(mail_ids)}")

    except (socket.timeout, TimeoutError):
        result["errors"].append(f"Timeout de red en cuenta {label}")
    except imaplib.IMAP4.error as e:
        result["errors"].append(f"Error IMAP en {label}: {e}")
    except Exception as e:
        result["errors"].append(f"Error inesperado en {label}: {e}")
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass

    progress(f"→ {label}: {result['downloaded']} imágenes nuevas, {result['duplicate']} duplicadas, "
             f"{result['errors']} errores")
    return result


def main():
    """Orquesta la descarga en todas las cuentas y genera el resumen."""
    start_time = time.time()
    deadline = start_time + TOTAL_TIMEOUT

    photos_dir = PHOTOS_DIR
    photos_dir.mkdir(parents=True, exist_ok=True)

    # Índice de hashes ya existentes en disco (dedup)
    existing_hashes = _build_existing_hashes(photos_dir)
    logger.info("Imágenes ya en disco: %d", len(existing_hashes))

    accounts = load_accounts_full()
    if not accounts:
        logger.error("No hay cuentas configuradas en data/email_accounts.json")
        return

    logger.info("Procesando %d cuenta(s) con presupuesto total de %d s...", len(accounts), TOTAL_TIMEOUT)

    all_results = []
    for acc in accounts:
        if time.time() > deadline:
            logger.warning("Presupuesto total alcanzado. Se omiten las cuentas restantes.")
            break
        result = process_account_images(acc, photos_dir, existing_hashes, deadline, logger.info)
        all_results.append((acc, result))

    elapsed = time.time() - start_time

    # ─── Resumen final ─────────────────────────────────────────────────────────────
    total_found = sum(r["found"] for _, r in all_results)
    total_down = sum(r["downloaded"] for _, r in all_results)
    total_dup = sum(r["duplicate"] for _, r in all_results)
    total_skip = sum(r["skipped"] for _, r in all_results)
    total_err = sum(len(r["errors"]) for _, r in all_results)

    print("\n" + "=" * 60)
    print("  RESUMEN DE DESCARGA DE EMAILS [ticket]")
    print("=" * 60)
    for acc, r in all_results:
        print(f"  {acc.get('label', acc['email'])}:")
        print(f"    emails [ticket]: {r['found']}")
        print(f"    imágenes nuevas : {r['downloaded']}")
        print(f"    duplicadas (hash): {r['duplicate']}")
        print(f"    saltadas        : {r['skipped']}")
        for e in r["errors"]:
            print(f"    ✗ {e}")
    print("-" * 60)
    print(f"  Total emails      : {total_found}")
    print(f"  Total descargadas : {total_down}")
    print(f"  Duplicadas        : {total_dup}")
    print(f"  Saltadas          : {total_skip}")
    print(f"  Errores           : {total_err}")
    print(f"  Tiempo total      : {elapsed:.1f} s")
    print("=" * 60)


if __name__ == "__main__":
    main()
