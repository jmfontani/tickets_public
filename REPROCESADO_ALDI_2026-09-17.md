# Reprocesado del ticket de Aldi — resultado (17-sep-2026)

Ticket: **Aldi**, 17/09/2026 11:35, nº 210001, **54,24 €**.
Imagen: `data/raw_photos/ticket_20260917_e229466327a0_gmail_images20260917.png`.

## Resultado

| | Antes (id 1007) | Ahora (id 1015) |
|---|---|---|
| Líneas | 30 (2 inventadas) | **28 reales** |
| Suma de importes | 75,09 € | **54,24 €** |
| Diferencia vs total impreso | **+20,85 €** | **0,00 €** |
| `cantidad × precio_unit = importe` | fallaba | **28/28 OK** |
| Clasificadas fuera de "Otros" | 26/30 | **26/28** |

El ticket viejo (1007) se borró con sus líneas; el nuevo es el **1015**. La copia de
seguridad previa está en `data/tickets.db.bak-pre-reproceso1007-20260917_145847`.

Las dos líneas que se quedan en "Otros" son correctas: *"PAPELERIA HARRY POTTER"*
(producto no alimentario sin regla) y *"Descuento posición 30%"* (un descuento).

## Las tres cosas que había que tocar

### 1. `OCR_MAX_TOKENS=8000` (era 4000)

Subido en `.env` con copia previa (`.env.bak-20260917_1447`). El motivo: los modelos de
visión gastan tokens **razonando** antes de emitir el JSON. Un ticket de 4 artículos
necesitó **5.693 tokens**; con 4000 devolvía `finish_reason: length` y un JSON truncado.

### 2. El prompt (`src/ocr_llm.py`)

Las 8 reglas de lectura descritas en `ANALISIS_TICKET_ALDI.md`: ignorar el dígito de IVA,
las líneas "n x precio" como desglose (van **encima** de su artículo), descuentos en
negativo, un item por fila y la verificación obligatoria de suma contra total. Verificado
sin regresión en Mercadona, Primaprix y otros.

### 3. El modelo: **hay que usar cloud, no local**

Esto es el hallazgo importante. Probé el prompt nuevo con los **dos** modelos:

| Modelo | Modo | Resultado en el ticket de Aldi |
|---|---|---|
| `glm-5.3-flash` | cloud | **28 items, 54,24 € = total** ✅ |
| `minicpm-v4.5:8b` | local | 29 items, 74,15 € → **+19,91 €** ❌ |

**El modelo local sigue fallando con el prompt corregido.** No es un problema del prompt:
`minicpm-v4.5:8b` confunde las líneas de desglose con artículos, desplaza importes
(FLAN 2×1,32 en vez de 2×1,65; PIZZA 3,33 en vez de 2,45) y se inventa precios.

Pero el `.env` del proyecto tiene **`OCR_MODE=local`**, y el contenedor
`tickets-ingest-api` **no recibe `OLLAMA_API_KEY`** (no está en su entorno ni en el `.env`
del proyecto, solo en `~/.hermes/.env`). Es decir: **la ingesta automática está usando el
modelo que da mal los tickets.**

Recomendación: pasar a modo cloud. Hace falta (a) añadir `OLLAMA_API_KEY` al `.env` del
proyecto o al `environment:` del compose, y (b) poner `OCR_MODE=cloud`.

## Un defecto de diseño que descubrí

`src/taxonomy.py` clasifica por reglas **solo los artículos de Mercadona**:

```sql
AND t.tienda LIKE '%MERCADONA%'     -- líneas 1440-1441
```

Los de cualquier otra tienda se mandan a clasificar por **LLM** contra
`LOCAL_OLLAMA_URL`. Y el clasificador del contenedor tiene configurado el modelo
`deepseek-v4-flash:0731-cloud` **retirado**, así que la clasificación de Aldi no corre.

Mientras no se corrija, los artículos de Aldi se quedan en "Otros" hasta que se ejecute
`apply_taxonomy_to_db()` **desde dentro del contenedor** (desde el host no alcanza
`host.docker.internal:11434`). Eso es lo que hice para clasificar el 1015.

## Herramientas que quedan en el proyecto

- `prueba_prompt.py <imagen> [modelo]` — ejecuta el `SYSTEM_PROMPT` real contra una imagen
  vía **cloud** y verifica suma vs total y `cantidad × precio = importe` por línea.
- `prueba_prompt_local.py <imagen> [modelo]` — lo mismo vía Ollama **local**.
- `reprocesa_ticket.py <id|fichero> [--apply]` — reprocesa un ticket desde su imagen:
  dry run por defecto, copia de seguridad de la BD, borra e inserta con el pipeline
  completo (incluye `normalize_all_in_db()` + `apply_taxonomy_to_db()`).

## Estado de la BD

256 tickets, 6.834 líneas, **0 huérfanos**, 0 líneas sin clasificar, 0 tickets sin líneas.

Hay **9 tickets de foto con la suma descuadrada** (hasta 17 € de diferencia) — anteriores
a esta corrección. Reprocesarlos arreglaría sus importes; ver `reprocesa_ticket.py`.
