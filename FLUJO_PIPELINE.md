# Pipeline Tickets — Diagrama de flujo (v2, agnostico de comercio)

## Diagrama

```
ENTRADAS
│
├─ [1] Gmail IMAP — Mercadona
│   Quien: ingest.py (imaplib, multi-cuenta)
│   Que: emails de ticket_digital@mail.mercadona.com
│   Sale: PDF adjunto -> data/raw_pdfs/
│
├─ [2] Cualquier cuenta IMAP — asunto "[ticket]"
│   Quien: ingest.py (patron TICKET_SUBJECT_RE, re.IGNORECASE)
│   Que: imagen adjunta (.jpg .jpeg .png .heic .heif .webp)
│        de CUALQUIER comercio (el remitente no se filtra)
│   Sale: imagen -> data/raw_photos/
│
├─ [4] Decathlon — asunto "El ticket de compra Decathlon del DD/MM/AAAA"
│   Quien: ingest.py (PENDIENTE — ver docs/PLAN-DECATHLON.md)
│   Que: PDF sale_ticket.pdf de no-reply.ticketes@decathlon.com
│   Sale: PDF -> data/raw_pdfs/  (parser propio, el de Mercadona no vale)
│
└─ [3] Cuenta local himalaya (legacy fetch_emails.py)
    Que: PDFs de Mercadona en [Gmail]/Todos

PROCESADO
│
├─ PDF (ruta Mercadona)
│   Quien: parse_ticket.parse_pdf (pdfplumber, parser especifico
│           del layout PDF de Mercadona)
│   Sale: objeto Ticket (texto estructurado, SIN LLM)
│
└─ Imagen (ruta emails [ticket])
    Quien: ocr_llm.process_image_to_ticket
    1. extract_ticket_from_image:
       - LOCAL: minicpm-v4.5:8b en Ollama local (11434, iGPU AMD)
       - FALLBACK cloud: glm-5.3-flash via ollama.com/v1
    2. validate_ticket: coherencia de totales
    Sale: objeto Ticket (puede guardar con warning si falla validacion)

NORMALIZACION Y CLASIFICACION (comun a ambas rutas)
│
├─ normalize.normalize_all_in_db
└─ taxonomy.classify:
   1. Reglas keyword (gratis, ~1320 productos)
   2. LLM local qwen2.5:7b (11434) solo para items
      sin regla -> {categoria, subcategoria, producto}, lotes de 20, temp 0.1
   3. Overrides manuales (prioridad maxima)

SALIDAS
│
├─ data/mercadona.db (SQLite)  <- NOMBRE OBSOLETO
│   tablas: tickets, line_items (llm_classified=1), overrides
├─ data/raw_pdfs/ y data/raw_photos/ (originales)
└─ Dashboard Streamlit (container 'tickets', :8050)
   -> https://ejemplo.com/tickets/
```

## Sobre renombrar mercadona.db

Si. El nombre es un vestigio historico: la BD almacena tickets de
cualquier comercio (emails [ticket]) ademas de Mercadona.

Alcance del cambio (solo 3 ficheros + backups):
- src/database.py:12      -> DB_PATH
- src/catalog.py:11       -> DB_PATH
- src/data_loader.py:8    -> DB_PATH

Recomendacion: tickets.db

Pasos seguros:
1. Parar container tickets
2. mv data/mercadona.db data/tickets.db
3. Cambiar DB_PATH en los 3 ficheros (y mercadona-fix/)
4. docker compose up -d
5. Verificar dashboard + datos
6. Renombrar backup: mercadona.db.bak_taxonomy -> tickets.db.bak_taxonomy

Riesgo: bajo. No hay referencias al nombre en docker-compose ni scripts.