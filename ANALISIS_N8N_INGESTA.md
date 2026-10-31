# Análisis: Ingesta de tickets vía n8n vs flujo programático actual

*2026-08-27 — Contexto: pipeline Python (`run_pipeline.py`, cron 3AM) + OCR local minicpm-v4.5:8b. n8n ya desplegado en el server.*

## Situación actual (programático)

- Cron Hermes 3AM → `docker compose run tickets python3 run_pipeline.py`
- Fases: IMAP since 7d → parse PDFs → OCR imágenes → SQLite → normalizar
- Errores en `result['errors']` y logs de docker; ejecución batch nocturna
- Los fallos se descubren al día siguiente (ej: drift skip del 27/8)

## Mejoras concretas que aporta n8n

### 1. Ingesta en tiempo real (event-driven)
- **Email Trigger (IMAP IDLE)**: n8n queda conectado al buzón y salta AL LLEGAR el email
- Ticket del 25/8 a las 19:00 → en BD a las 19:05, no a las 3:00 del día siguiente
- El dashboard siempre fresco sin esperar al batch
- Nota: el OCR local (2-5 min/imagen) sigue siendo el cuello; n8n no lo acelera, solo elimina la espera hasta el batch

### 2. Observabilidad y debugging visual
- Historial de ejecuciones: cada nodo con su input/output inspectable
- Reintentar UN nodo fallido sin re-ejecutar todo el pipeline (hoy: relanzar todo o nada)
- El fallo de esta mañana (drift skip + ruta vieja del cron) habría sido visible en el panel de n8n al instante, con el nodo exacto en rojo

### 3. Manejo de errores nativo
- **Error Workflow**: rama de error → notificación WhatsApp/Telegram inmediata con el detalle
- Retries con backoff por nodo (IMAP caído, Ollama ocupado)
- Validación de ticket fallida → tarea de revisión en vez de insertar silenciosamente datos aproximados (el caso Lidl 25,46 € del 26/8: suma no cuadraba y se insertó igual con solo un warning en el log)

### 4. Routing y reglas sin código
- Ramas declarativas: subject `Mercadona` → parse PDF; adjunto imagen → OCR; sin adjunto → descartar
- Añadir una tienda nueva o cambiar filtros = editar el workflow, sin tocar Python ni rebuild del contenedor (el código está baked en la imagen, cada cambio requiere `docker compose build`)

### 5. Integraciones gratis
- Notificación al chat al insertar cada ticket (gasto del día en vivo)
- Webhook al dashboard Streamlit para auto-refrescar
- Backup automático de PDFs/imágenes a Google Drive al procesarlos
- Todo esto hoy sería código custom adicional en Python

## Contras honestos

| Aspecto | Realidad |
|---|---|
| Lógica compleja | El dedup por hash, upsert seguro, taxonomía y normalización NO desaparecen. O n8n llama al Python actual (recomendado) o se reescribe en nodos = frágil y deudor técnico |
| Estado duplicado | Dos sistemas que conocer el estado (workflow n8n + BD). El dedup de emails (message_id) debe seguir viviendo en BD |
| OCR | Sigue tardando lo mismo; n8n solo cambia CUÁNDO empieza |
| Mantenimiento | Dos piezas que evolucionar (JSON del workflow + código). Riesgo de divergencia si se toca el Python y el workflow no se actualiza |
| Migración | Esfuerzo medio (1-2 días): trigger IMAP, credenciales, ramas, pruebas con emails reales |

## Recomendación: híbrido

1. **n8n = orquestador**: Email Trigger (IMAP) → filtro [ticket]/Mercadona → guardado de adjuntos → llamada al pipeline Python actual via **Execute Command** o webhook HTTP → notificación WhatsApp del resultado → rama de error con alerta
2. **Python actual = worker**: todo el dominio (dedup, OCR, taxonomía) queda intacto; n8n solo decide CUÁNDO y AVISA
3. **Mantener el cron 3AM** como red de seguridad (reprocesa pendientes si un trigger se perdió)
4. Fase 2 (opcional): mover la notificación de "ticket insertado" y el backup a Drive dentro del workflow

## Veredicto en una línea

n8n aporta valor real en **frescura (tiempo real), visibilidad y alertas**, no en la lógica de negocio — hazlo híbrido (n8n dispara, Python procesa) y gana lo mejor de ambos sin reescribir nada.