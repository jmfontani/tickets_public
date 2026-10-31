// Prueba de conectividad: contenedor n8n -> bridge WhatsApp en host (172.17.0.1:3000)
// Ejecutar: docker exec n8n node /tmp/test_bridge.js
const HOST = process.argv[2] || '172.17.0.1:3000';
const chatId = process.env.WA_CHAT_ID || 'CAMBIAME@c.us';

fetch(`http://${HOST}/send`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'Host': 'localhost' },
  body: JSON.stringify({
    chatId,
    message: '🧪 prueba conectividad n8n→bridge',
  }),
})
  .then(async (r) => console.log('RESP:', r.status, (await r.text()).slice(0, 200)))
  .catch((e) => console.log('ERR:', e.message));