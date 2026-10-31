#!/usr/bin/env python3
"""Pipeline batch nocturno con modelo LLM LOCAL.

Este script:
1. Levanta un contenedor Docker Ollama (CPU-only) con el modelo minicpm-v4.5:8b
2. Ejecuta el pipeline de ingesta de tickets (descarga IMAP + OCR + BD)
3. Detiene y elimina el contenedor Ollama para liberar RAM

Uso:
    python3 run_batch_local.py

Variables de entorno (en .env o por línea de comandos):
    OCR_MODE=local                    # Fuerza modo local
    LOCAL_OCR_MODEL=minicpm-v4.5:8b   # Modelo a usar
    LOCAL_OLLAMA_URL=http://localhost:11434
    OCR_TIMEOUT=600                    # Timeout por ticket (segundos)
    OCR_MAX_TOKENS=4000               # Tokens máximos de output
    OCR_NUM_CTX=8192                  # Contexto del modelo

El modelo se descarga automáticamente la primera vez (6.1 GB).
Las siguientes ejecuciones usan el volumen Docker persistente.
"""
import os
import sys
import time
import subprocess
import logging
from pathlib import Path

# Forzar modo local ANTES de importar el pipeline
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
logger = logging.getLogger("batch_local")

# ─── Configuración Docker ────────────────────────────────────────────────────

CONTAINER_NAME = "ollama-tickets"
VOLUME_NAME = "ollama_tickets_data"
OLLAMA_IMAGE = "ollama/ollama:latest"
OLLAMA_PORT = "11434"
MODEL_NAME = os.environ.get("LOCAL_OCR_MODEL", "minicpm-v4.5:8b")


def run_cmd(cmd: list[str], check: bool = True, timeout: int = 120) -> tuple[int, str]:
    """Ejecuta un comando y devuelve (exit_code, output)."""
    logger.debug("CMD: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            logger.error("CMD failed (%d): %s", r.returncode, r.stderr[:500])
        return r.returncode, r.stdout.strip() + r.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.error("CMD timeout: %s", " ".join(cmd))
        return 1, "timeout"


def container_exists() -> bool:
    """True si el contenedor Ollama ya existe (corriendo o parado)."""
    code, _ = run_cmd(
        ["docker", "inspect", CONTAINER_NAME], check=False, timeout=10
    )
    return code == 0


def start_ollama() -> bool:
    """Levanta el contenedor Ollama con el modelo de visión.

    Returns:
        True si el contenedor está corriendo y el modelo está disponible.
    """
    logger.info("Levantando contenedor Ollama...")

    # Si ya existe, arrancarlo
    if container_exists():
        logger.info("Contenedor ya existe, arrancando...")
        run_cmd(["docker", "start", CONTAINER_NAME], timeout=30)
    else:
        # Crear contenedor nuevo con volumen persistente
        logger.info("Creando contenedor Ollama (primera vez)...")
        code, output = run_cmd(
            [
                "docker", "run", "-d",
                "--name", CONTAINER_NAME,
                "-p", f"{OLLAMA_PORT}:11434",
                "-v", f"{VOLUME_NAME}:/root/.ollama",
                OLLAMA_IMAGE,
            ],
            timeout=60,
        )
        if code != 0:
            logger.error("No se pudo crear el contenedor: %s", output)
            return False

    # Esperar a que Ollama esté listo
    logger.info("Esperando a que Ollama esté listo...")
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

    # Verificar si el modelo ya está descargado
    code, output = run_cmd(
        ["docker", "exec", CONTAINER_NAME, "ollama", "list"], timeout=10
    )
    if MODEL_NAME not in output:
        logger.info("Descargando modelo %s (primera vez, ~6 GB)...", MODEL_NAME)
        code, output = run_cmd(
            ["docker", "exec", CONTAINER_NAME, "ollama", "pull", MODEL_NAME],
            timeout=600,
        )
        if code != 0:
            logger.error("No se pudo descargar el modelo: %s", output[:500])
            return False
        logger.info("Modelo descargado correctamente.")
    else:
        logger.info("Modelo %s ya disponible.", MODEL_NAME)

    return True


def stop_ollama():
    """Detiene y elimina el contenedor Ollama para liberar RAM."""
    logger.info("Deteniendo contenedor Ollama...")
    run_cmd(["docker", "stop", CONTAINER_NAME], check=False, timeout=30)
    # NO eliminamos el contenedor ni el volumen: así la próxima vez
    # arranca más rápido (modelo ya descargado en el volumen)
    logger.info("Contenedor detenido. RAM liberada.")


def main():
    """Ejecuta el pipeline batch completo con modelo local."""
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("  BATCH LOCAL - Pipeline de tickets con LLM local")
    logger.info("  Modelo: %s", MODEL_NAME)
    logger.info("=" * 60)

    # 1. Levantar Ollama
    if not start_ollama():
        logger.error("No se pudo iniciar Ollama. Abortando.")
        sys.exit(1)

    try:
        # 2. Ejecutar pipeline de ingesta
        logger.info("Ejecutando pipeline de ingesta...")

        from src.ingest import run_ingestion
        from src.database import init_db, get_tickets, get_all_items

        def progress(msg):
            logger.info("  %s", msg)

        result = run_ingestion(progress)

        if "error" in result:
            logger.error("Error en pipeline: %s", result["error"])
        else:
            # Resumen
            logger.info("=" * 60)
            logger.info("  RESUMEN")
            logger.info("=" * 60)
            logger.info("  Emails encontrados:    %d", result.get("emails_found", 0))
            logger.info("  Emails [ticket]:       %d", result.get("ticket_emails_found", 0))
            logger.info("  PDFs descargados:      %d", result.get("pdfs_downloaded", 0))
            logger.info("  Imágenes descargadas:  %d", result.get("images_downloaded", 0))
            logger.info("  Tickets desde PDF:     %d", result.get("tickets_from_pdf", 0))
            logger.info("  Tickets desde imagen:  %d", result.get("tickets_from_image", 0))
            logger.info("  Tickets en BD:         %d", result.get("tickets_in_db", 0))
            logger.info("  Items en BD:           %d", result.get("items_in_db", 0))
            logger.info("  Total gastado:         %.2f €", result.get("total_gastado", 0))
            if result.get("errors"):
                logger.warning("  Errores: %d", len(result["errors"]))
                for e in result["errors"]:
                    logger.warning("    - %s", e)

    finally:
        # 3. Detener Ollama SIEMPRE (incluso si hay error)
        stop_ollama()

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("  Tiempo total: %.1f min", elapsed / 60)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()