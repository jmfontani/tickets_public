# Plan · Ingesta de tickets de Decathlon

> **Estado: PROPUESTA. No se ha modificado nada del código.**
> Fecha: 25-sep-2026 · basado en correos reales abiertos por IMAP, no en supuestos.

---

## 1. Qué llega (verificado en el buzón)

**Remitente:** `no-reply.ticketes@decathlon.com`
**Asunto:** `El ticket de compra Decathlon del DD/MM/AAAA`
*(el nombre del remitente es la TIENDA: «USERA», «GETAFE MADRID»)*

Volumen: **95 correos** con ese asunto en la cuenta principal, **30** con
«Decathlon» en la segunda cuenta (solapados por fecha).

**Adjuntos por correo:**

| Fichero | ¿es el ticket? | Notas |
|---|---|---|
| `sale_ticket.pdf` | **Sí** | La compra. Siempre presente. |
| `ticket_regalo.pdf` | No (probable) | Aparece en los recientes |
| `gift_card_ticket.pdf` | No (probable) | Aparece en los de 2025 |

⚠️ **No verificado**: no se ha leído el contenido de `ticket_regalo.pdf`
(el comando quedó bloqueado). El nombre apunta a justificante de tarjeta regalo,
sin líneas de compra. **Hay que comprobarlo antes de implementar** — si tuviera
líneas, descartarlo perdería datos.

⚠️ **Todos los ficheros se llaman igual** (`sale_ticket.pdf`), así que el nombre no
identifica la compra: hace falta nombrar por tienda + fecha + hash.

---

## 2. Por qué no entra hoy

El pipeline actual solo conoce dos caminos, y ninguno encaja:

| Filtro | Valor actual | Decathlon |
|---|---|---|
| Remitente (PDF) | `MERCADONA_SENDERS` | no coincide |
| Asunto (fotos) | regex `\[ticket\]` | el asunto no lo lleva |
| Extensión | `.pdf` solo en la ruta Mercadona; fotos solo imágenes | desajuste |

Consecuencia: los correos de Decathlon **se ignoran** en la fase IMAP.

---

## 3. El PDF de Decathlon (texto real extraído)

**No tiene tablas** (`extract_tables()` devuelve 0): hay que parsear por el texto.

```
USERA                                    <- tienda (línea 1)
M40 salida 24 Avda Rafaela Ybarra s/
28041, Spain                             <- dirección
+34 913410080
NIF: A79935607
VENTA-V2026029400600043555               <- ID de venta (num_ticket)
Precio
Cant. Descripción Precio
Unitario
COQUILLA JOCKSTRAP 100                   <- descripción (multilínea)
1                                        <- cantidad (línea suelta)
ADULTO
Ref: 2232644 9,99 9,99 EUR               <- ref + P.unitario + importe
RFID: 009198140695
Subtotal 9,99 EUR
TOTAL 9,99 EUR                           <- total
Tasa Sin IVA Total IVA IVA Inc.
21,00 8,26 1,73 9,99 EUR                 <- desglose IVA
Numero de tarjeta: 2091908809626
Tarjeta 9,99 EUR                         <- método de pago
25/09/2026 - 18:12:16                    <- fecha y hora
Caja № 6 - QCO
Tran: 1900 - Tienda: 700294
FACTURA SIMPLIFICADA
```

**Lo que ya funciona mal:** el parser actual aplicado a ese PDF devuelve
`tienda='USERA'`, `fecha=''`, `total=0.0`, **0 líneas**. Es un formato nuevo, no un
ajuste menor.

---

## 4. Plan de cambio

### Fase 1 · Detectar y descargar (`src/ingest.py`)

1. `DECATHLON_SENDERS = ["no-reply.ticketes@decathlon.com"]`
2. `DECATHLON_SUBJECT_RE = re.compile(r"El ticket de compra Decathlon del", re.I)`
3. `fetch_decathlon_emails(account, ...)` — nueva, calcada de `fetch_ticket_emails`:
   - búsqueda IMAP por asunto
   - descarga **solo** `sale_ticket.pdf`
   - nombre: `decathlon_<fecha_del_asunto>_<hash>_<tienda>.pdf` → `data/raw_pdfs/`
   - dedup por `content_hash` (mecanismo que ya existe)
4. El extracto de la tienda sale del **nombre del remitente** o de la 1ª línea del PDF.

### Fase 2 · Parser (`src/parse_ticket.py`)

`parse_decathlon(pdf_path) -> Ticket`, con:

| Campo | Origen |
|---|---|
| `num_ticket` | `VENTA-V…` |
| `fecha` | `dd/mm/yyyy - HH:MM:SS` |
| `tienda` / `direccion` | primeras líneas |
| `total` | `TOTAL <n>,<n> EUR` |
| `iva_json` | fila `Tasa Sin IVA Total IVA IVA Inc.` |
| `metodo_pago` | `Tarjeta` / `Efectivo` |
| `items` | bloques de artículo |

Parseo de artículos (el punto frágil): la descripción **ocupa varias líneas**, la
cantidad va **sola en su línea**, y el importe viene en `Ref: <ref> <p.unit> <total> EUR`.
Hay que resolverlo por orden de líneas, no por patrón único. Además hay artículos
**sin** `Ref:` (descuentos, fianzas, envases) que no deben perderse.

**Multi-página:** el ejemplo es de 1 página, pero hay que asumir varias.

### Fase 3 · Integración

- `comercio='decathlon'`, `source_type='email_pdf'`
- El pipeline (`parse_all`) debe **enrutar** al parser según remitente/origen.
- **Taxonomía:** los productos de Decathlon son deporte. Ojo con la regla crítica
  ya aprendida: si el LLM no sabe y responde «Otros», **no** marcar
  `llm_classified=1`, o la línea queda fijada para siempre.
- Valorar un bloque de reglas por palabra clave para deporte (bicicleta, zapatilla,
  tienda de campaña, natación…) antes de gastar LLM.

### Fase 4 · Puesta en servicio

```bash
cp data/tickets.db data/tickets.db.bak_$(date +%Y%m%d_%H%M)   # backup primero
docker compose -f docker-compose.n8n.yml up -d --build          # src/ va en la imagen
```

**Histórico:** la ingesta mira **7 días** por defecto. Para cargar los ~95 correos
hay que ejecutar una vez con ventana amplia (o sin límite), y a partir de ahí el
cron de las 3:00 los va cogiendo.

---

## 5. Decisiones que necesitan tu confirmación

1. **El segundo PDF** (`ticket_regalo.pdf` / `gift_card_ticket.pdf`): ¿se ignora?
   (hay que leerlo antes de decidir — si tuviera líneas de compra, no).
2. **Cuánto histórico** cargar: ¿todos los correos disponibles o últimos N meses?
3. **Duplicados**: 30 correos aparecen en las dos cuentas. El `content_hash` los
   pilla si el PDF es idéntico byte a byte; si no, hay que deduplicar por
   `num_ticket` (`VENTA-V…`). ¿Se añade esa segunda red?
4. **Categorías de deporte** en la taxonomía: ¿añadir subcategorías propias
   (bicicleta, running, camping, natación…) o dejar que caiga en las genéricas?

---

## 6. Riesgos

- **Variantes de formato en el tiempo.** `gift_card_ticket.pdf` en 2025 frente a
  `ticket_regalo.pdf` en 2026 sugiere que Decathlon cambia el correo. El parser
  debe **fallar visiblemente** si un campo esperado no aparece, no insertar un
  ticket con total 0 (que es lo que hace hoy el parser genérico).
- **La deduplicación por nombre de fichero no sirve** (todos iguales).
- **Productos de Mercadona vs Decathlon** comparten tablas; `catalog_products` es
  de Mercadona, así que el enriquecido de catálogo no aplica aquí.
