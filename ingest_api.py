#!/usr/bin/env python3
"""Servicio HTTP de ingesta para orquestación n8n (rama n8n-ingest).

Endpoints (puerto 8060):
  POST /ingest          → pipeline completo (IMAP 7d → PDFs → OCR → normalizar)
  POST /ingest/ocr      → solo OCR de imágenes pendientes
  GET  /status          → estado: ocupado/libre + última ejecución
  GET  /health          → liveness

Diseño:
  - Un solo job en marcha (lock). Si llega otra petición mientras corre → 409.
  - El trabajo pesado corre en un thread; la petición devuelve 202 al momento
    con job_id. n8n sondea /status con <job_id> hasta finished.
  - Sin dependencias nuevas: http.server de stdlib.
"""
import json
import logging
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/app")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_api")

STATE = {
    "running": False,
    "job_id": None,
    "started_at": None,
    "finished_at": None,
    "mode": None,
    "result": None,
    "error": None,
}
LOCK = threading.Lock()

DB_PATH = "/app/data/tickets.db"


def _pending_snapshot() -> dict:
    """Trabajo que queda por hacer, para que un fallo del modelo no se disfrace.

    - `items_sin_llm`: ítems que la taxonomía aún no ha resuelto y que enviaría
      al LLM en la próxima pasada (misma selección que `apply_taxonomy_to_db`).
      `llm_classified=0` NO significa pendiente: los miles de ítems que resuelven
      las reglas de Mercadona también lo tienen a 0.
    - `fotos_sin_ticket`: imágenes de `raw_photos/` sin ticket en la BD, contadas
      con el mismo criterio que usa el pipeline (nombre o hash de contenido).
    """
    import sqlite3

    snap: dict = {"items_sin_llm": None, "fotos_sin_ticket": None, "tickets": None}
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        snap["items_sin_llm"] = conn.execute(
            """SELECT COUNT(*) FROM line_items li
               JOIN tickets t ON li.ticket_id = t.id
               WHERE (li.llm_classified = 0 OR li.llm_classified IS NULL)
                 AND (t.tienda NOT LIKE '%MERCADONA%'
                      OR li.categoria_general = 'Otros'
                      OR li.categoria_general IS NULL)"""
        ).fetchone()[0]
        snap["tickets"] = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        from src.ingest import _find_unprocessed_images

        snap["fotos_sin_ticket"] = len(_find_unprocessed_images(conn))
        conn.close()
    except Exception:  # noqa: BLE001 - el estado nunca debe tumbar el servicio
        pass
    return snap


def _run_job(job_id: str, mode: str):
    global STATE
    try:
        from src.ingest import run_ingestion, run_ocr_only

        def progress(msg):
            log.info("[%s] %s", job_id, msg)

        t0 = time.time()
        if mode == "ocr_only":
            result = run_ocr_only(progress)
        else:
            result = run_ingestion(progress, since_days=7)
        elapsed = round(time.time() - t0, 1)
        with LOCK:
            STATE["running"] = False
            STATE["finished_at"] = time.time()
            STATE["result"] = result
            STATE["result"]["elapsed_s"] = elapsed
            STATE["error"] = None
        log.info("[%s] OK en %ss: %s", job_id, elapsed,
                 json.dumps({k: v for k, v in result.items() if k != "new_pdf_files"}, ensure_ascii=False)[:400])
    except Exception as e:  # noqa: BLE001
        log.exception("[%s] FALLO", job_id)
        with LOCK:
            STATE["running"] = False
            STATE["finished_at"] = time.time()
            STATE["error"] = str(e)
            STATE["result"] = None


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/health":
            return self._json(200, {"ok": True})
        if path == "/status":
            with LOCK:
                s = dict(STATE)
            s["pending"] = _pending_snapshot()
            return self._json(200, s)
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path not in ("/ingest", "/ingest/ocr"):
            return self._json(404, {"error": "not found"})
        mode = "full" if path == "/ingest" else "ocr_only"

        with LOCK:
            if STATE["running"]:
                return self._json(409, {
                    "error": "busy",
                    "job_id": STATE["job_id"],
                    "started_at": STATE["started_at"],
                })
            job_id = str(uuid.uuid4())[:8]
            STATE.update(running=True, job_id=job_id, started_at=time.time(),
                         finished_at=None, mode=mode, result=None, error=None)

        threading.Thread(target=_run_job, args=(job_id, mode), daemon=True).start()
        return self._json(202, {"accepted": True, "job_id": job_id, "mode": mode,
                                "poll": "/status"})

    def log_message(self, format, *args):  # noqa: A002 - firma de stdlib
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8060
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("ingest_api escuchando en :%s", port)
    srv.serve_forever()