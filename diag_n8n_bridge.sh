#!/bin/bash
# Diagnóstico: contenedor n8n -> host:3000 (bridge WhatsApp)
# Ejecutar: bash diag_n8n_bridge.sh
set +e
echo "=== 1. Host puede alcanzar el bridge en docker0 (172.17.0.1:3000)? ==="
curl -s -m 5 -o /dev/null -w "host->172.17.0.1:3000 = HTTP %{http_code}\n" \
  -H "Host: localhost" http://172.17.0.1:3000/health || echo "host->172.17.0.1 FALLO"

echo "=== 2. n8n puede alcanzar 172.17.0.1:3000? ==="
docker exec n8n node -e "
const net = require('net');
const s = net.connect({host:'172.17.0.1', port:3000, timeout:5000});
s.on('connect', () => { console.log('TCP n8n->172.17.0.1:3000 = OK'); process.exit(0); });
s.on('timeout', () => { console.log('TCP n8n->172.17.0.1:3000 = TIMEOUT'); process.exit(1); });
s.on('error', (e) => { console.log('TCP n8n->172.17.0.1:3000 = ERR:', e.message); process.exit(1); });
"