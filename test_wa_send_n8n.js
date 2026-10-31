// Prueba final: envío WhatsApp real desde contenedor n8n vía proxy
// Ejecutar: WA_CHAT_ID="<tu-chat-id>" docker exec -e WA_CHAT_ID n8n node /tmp/test_wa_send.js
const chatId = process.env.WA_CHAT_ID || 'CAMBIAME@c.us';
fetch('http://172.17.0.1:3001/send', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'Host': 'localhost' },
  body: JSON.stringify({
    chatId,
    message: '✅ *n8n → WhatsApp conectado*\nVía proxy (172.17.0.1:3001 → loopback:3000). El aviso nocturno del pipeline de tickets ya puede enviarse desde n8n.',
  }),
})
  .then(async (r) => console.log('RESP:', r.status, await r.text()))
  .catch((e) => console.log('ERR:', e.message));