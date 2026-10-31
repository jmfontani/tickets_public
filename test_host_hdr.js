// Prueba de variantes de Host header contra el bridge (vía proxy socat)
// Ejecutar: docker exec n8n node /tmp/test_host_hdr.js
const variants = ['127.0.0.1', 'localhost', '[::1]', '127.0.0.1:3001', 'localhost:3001'];
(async () => {
  for (const h of variants) {
    try {
      const r = await fetch('http://172.17.0.1:3001/health', { headers: { Host: h } });
      console.log(h, '->', r.status, (await r.text()).slice(0, 60));
    } catch (e) {
      console.log(h, '-> ERR', e.message);
    }
  }
})();