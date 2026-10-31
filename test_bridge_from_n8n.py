#!/usr/bin/env python3
"""Prueba de conectividad: contenedor n8n -> bridge WhatsApp en host (172.17.0.1:3000).

Ejecutar DENTRO del contenedor n8n (docker exec n8n python3 /tmp/test_bridge.py)
con el fichero montado, o copiar el contenido inline.
"""
import json
import os
import sys
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.17.0.1:3000"
CHAT_ID = os.environ.get("WA_CHAT_ID", "")

req = urllib.request.Request(
    f"http://{HOST}/send",
    data=json.dumps({
        "chatId": CHAT_ID or "CAMBIAME@c.us",
        "message": "🧪 prueba conectividad n8n→bridge",
    }).encode(),
    headers={"Content-Type": "application/json", "Host": "localhost"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print("RESP:", r.status, r.read().decode()[:200])
except Exception as e:  # noqa: BLE001
    print("ERR:", e)