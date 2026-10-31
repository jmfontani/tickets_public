#!/usr/bin/env python3
"""Proxy HTTP mínimo: reenvía a un upstream con Host forzado a loopback.

Motivo: el bridge de WhatsApp solo acepta peticiones con Host de loopback
(GHSA-ppp5-vxwm-4cf7, anti DNS-rebinding) y escucha solo en 127.0.0.1.
Los contenedores (n8n) no pueden fijar el header Host (fetch lo prohíbe).
Este proxy escucha en la IP de docker0 y reescribe Host → 'localhost'.

Uso: python3 wa_proxy.py <listen_host> <listen_port> <upstream_host> <upstream_port>
"""
import http.server
import sys
import urllib.error
import urllib.request

LISTEN_HOST = sys.argv[1] if len(sys.argv) > 1 else "172.17.0.1"
LISTEN_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3001
UP_HOST = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
UP_PORT = int(sys.argv[4]) if len(sys.argv) > 4 else 3000

FORBIDDEN = {"host", "content-length", "connection", "transfer-encoding"}


class Proxy(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            f"http://{UP_HOST}:{UP_PORT}{self.path}",
            data=body,
            method=self.command,
        )
        for k, v in self.headers.items():
            lk = k.lower()
            if lk not in FORBIDDEN:
                req.add_header(k, v)
        req.add_header("Host", "localhost")  # el bridge solo acepta loopback
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                self.send_response(r.status)
                ctype = r.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as e:
            payload = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:  # noqa: BLE001
            payload = f'{{"error": "{e}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _forward

    def log_message(self, format, *args):  # noqa: A002
        pass


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Proxy)
    print(f"wa_proxy: {LISTEN_HOST}:{LISTEN_PORT} -> {UP_HOST}:{UP_PORT} (Host forzado a 'localhost')")
    srv.serve_forever()