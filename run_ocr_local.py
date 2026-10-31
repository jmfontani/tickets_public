#!/usr/bin/env python3
"""Procesa solo las imágenes pendientes con el modelo LLM local.

A diferencia de run_batch_local.py, este script NO descarga emails nuevos.
Solo procesa las imágenes que ya están en data/raw_photos/ pero que aún no
tienen ticket en la BD. Útil para probar el modelo local sin esperar a la
fase de descarga IMAP.

Uso:
    python3 run_ocr_local.py [--keep]

    --keep  No detiene el contenedor Ollama al acabar (para depurar)
"""
import os
import sys
import time
import subprocess
import logging
import sqlite3
from pathlib import Path

os.environ["OCR_MODE"] = "local"
os.environ.setdefault("LOCAL_OCR_MODEL", "minicpm-v4.5:8b")
os.environ.setdefault("LOCAL_OLLAMA_URL", "http://localhost:11434")
os.environ.setdefault("OCR_TIMEOUT", "600")
os.environ.setdefault("OCR_MAX_TOKENS", "4000")
os.environ.setdefault("OCR_NUM_CTX", "8192")

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ocr_local")

CONTAINER_NAME = "ollama"
VOLUME_NAME = "ollama_tickets_data"
OLLAMA_IMAGE = "ollama/ollama:latest"
OLLAMA_PORT = "11434"
MODEL_NAME = os.environ.get("LOCAL_OCR_MODEL", "minicpm-v4.5:8b")
KEEP_ALIVE = "--keep" in sys.argv

from src.ingest import _find_unprocessed_images, _process_images, IMAGE_EXTENSIONS
from src.database import init_db, DB_PATH

BASE_DIR = Path(__file__).parent
PHOTOS_DIR = BASE_DIR / "data" / "raw_photos"


def run_cmd(cmd, check=True, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            logger.error("CMD failed (%d): %s", r.returncode, r.stderr[:500])
        return r.returncode, (r.stdout.strip() + r.stderr.strip())
    except subprocess.TimeoutExpired:
        return 1, "timeout"


def start_ollama():
    logger.info("Levantando contenedor Ollama...")

    # Check if already running
    code, _ = run_cmd(["docker", "inspect", CONTAINER_NAME], check=False, timeout=10)
    if code == 0:
        logger.info("Contenedor ya existe, arrancando...")
        run_cmd(["docker", "start", CONTAINER_NAME], timeout=30)
    else:
        code, output = run_cmd(
            ["docker", "run", "-d", "--name", CONTAINER_NAME,
             f"-p", f"{OLLAMA_PORT}:11434",
             "-v", f"{VOLUME_NAME}:/root/.ollama",
             OLLAMA_IMAGE],
            timeout=60,
        )
        if code != 0:
            logger.error("No se pudo crear el contenedor: %s", output)
            return False

    # Wait for Ollama
    import httpx
    for i in range(30):
        try:
            r = httpx.get(f"http://localhost:{OLLAMA_PORT}/api/tags", timeout=5)
            if r.status_code == 200:
                logger.info("Ollama está listo.")
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        logger.error("Ollama no respondió después de 60s.")
        return False

    # Check if model exists
    code, output = run_cmd(["docker", "exec", CONTAINER_NAME, "ollama", "list"], timeout=10)
    if MODEL_NAME not in output:
        logger.info("Descargando modelo %s (~6 GB)...", MODEL_NAME)
        code, output = run_cmd(
            ["docker", "exec", CONTAINER_NAME, "ollama", "pull", MODEL_NAME],
            timeout=600,
        )
        if code != 0:
            logger.error("No se pudo descargar el modelo: %s", output[:500])
            return False
        logger.info("Modelo descargado.")
    else:
        logger.info("Modelo %s ya disponible.", MODEL_NAME)

    return True


def stop_ollama():
    if KEEP_ALIVE:
        logger.info("--keep: contenedor dejado corriendo.")
        return
    logger.info("Deteniendo contenedor Ollama...")
    run_cmd(["docker", "stop", CONTAINER_NAME], check=False, timeout=30)
    logger.info("Contenedor detenido. RAM liberada.")


def main():
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("  OCR LOCAL - Procesar imágenes pendientes")
    logger.info("  Modelo: %s", MODEL_NAME)
    logger.info("=" * 60)

    if not start_ollama():
        logger.error("No se pudo iniciar Ollama. Abortando.")
        sys.exit(1)

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))

        # Find unprocessed images
        pending = _find_unprocessed_images(conn)
        logger.info("Imágenes pendientes: %d", len(pending))

        if not pending:
            logger.info("No hay imágenes pendientes. Todo procesado.")
            conn.close()
            return

        # Process each image
        result = _process_images(pending, conn, lambda msg: logger.info(msg))

        logger.info("=" * 60)
        logger.info("  RESULTADO")
        logger.info("=" * 60)
        logger.info("  Tickets procesados: %d", result["tickets_from_image"])
        if result["errors"]:
            logger.warning("  Errores: %d", len(result["errors"]))
            for e in result["errors"]:
                logger.warning("    - %s", e)

        conn.close()

    finally:
        stop_ollama()

    elapsed = time.time() - start_time
    logger.info("  Tiempo total: %.1f min", elapsed / 60)


if __name__ == "__main__":
    main()