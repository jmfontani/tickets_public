# 🧾 Tickets — gastos de compra desde tu correo

Pipeline que convierte los tickets de compra que llegan por email (PDFs de
Mercadona y fotos enviadas con el asunto `[ticket]`) en una base de datos
consultable y un dashboard web: gasto por categoría, evolución de precios,
hábitos de compra e historial de tickets.

Nació como dashboard de Mercadona y hoy ingiere también tickets de otros
comercios a partir de fotos.

**No requiere ninguna suscripción.** Funciona completo con modelos locales de
Ollama; usar Ollama Cloud es una opción para ir más rápido, no un requisito. La
automatización nocturna se hace con **n8n autoalojado** (también gratuito): ver
[Ingesta automática con n8n](#ingesta-automática-con-n8n-requisito).

---

## Qué hace

```
IMAP (Gmail u otro)  →  PDFs + fotos  →  parser / OCR  →  SQLite  →  dashboard
                                                            ↑
                                              normalización + taxonomía
```

1. **Descarga** los adjuntos de los correos: PDFs de Mercadona y fotos de
   tickets (asunto `[ticket]`).
2. **Extrae** los datos: comercio, fecha, total y líneas con producto, cantidad
   e importe. Los PDFs se leen con un parser de texto; las fotos, con un modelo
   de visión (OCR por LLM).
3. **Cuadra las cuentas**: suma los importes de las líneas y los compara con el
   total impreso (±0,02 €). La comprobación la hace el código, no el modelo.
4. **Clasifica** cada producto en categoría y subcategoría: primero reglas y
   catálogo, y solo lo que las reglas no resuelven pasa por un LLM (opcional).
5. **Sirve** un dashboard Streamlit: panel, establecimiento, categoría, producto,
   vista temporal, tickets y gestión de la ingesta.

---

## Requisitos

- Docker 20+ y Docker Compose v2.
- Una cuenta de correo con IMAP y contraseña de aplicación.
- **n8n autoalojado** para la ingesta automática (gratuito; es un contenedor más,
  ver la sección de n8n). Sin él se puede lanzar la ingesta a mano o con cron.
- **Ninguna suscripción de pago.** El LLM es opcional y puede correr en tu máquina.

### Perfiles de modelo

Se eligen con dos variables (`OCR_MODE` y `CLASSIFY_MODE`) en el `.env`:

| Perfil | OCR de fotos | Clasificación | Cuenta / coste | Velocidad |
|---|---|---|---|---|
| **local** (por defecto) | Ollama local (`minicpm-v4.5:8b`) | Ollama local (`qwen2.5:7b`) | ninguna, 0 € | lenta en CPU (~2-3 min/foto) |
| **cloud** | Ollama Cloud | Ollama Cloud | API key de Ollama (plan gratuito o de pago) | segundos |
| **mixto** | lo que elijas en cada variable | | según el caso | |

En modo `cloud`, si el modelo elegido no está incluido en tu plan, Ollama
responde **HTTP 402** y el pipeline lo dice explícitamente en vez de inventarse
categorías: los ítems quedan pendientes y reintentables, y `/status` los cuenta
en `pending`. El mensaje de error de Ollama suele indicar qué modelo sí está
incluido en el plan gratuito.

Los PDFs de Mercadona **no usan LLM**: se leen con el parser de texto, así que
funcionan igual en cualquier perfil.

---

## Arranque rápido

```bash
git clone <repo-url> tickets
cd tickets

cp .env.example .env
# edita .env si quieres modo cloud; con los valores por defecto va en local

docker compose -f docker-compose.n8n.yml up -d --build
```

- Dashboard: <http://localhost:8050>
- API de ingesta: <http://localhost:8060> (`/health`, `/status`)

Servicios:

| Servicio | Contenedor | Para qué |
|---|---|---|
| `tickets-dashboard` | `tickets` | UI Streamlit y ejecución de la ingesta desde el panel |
| `tickets-ingest-api` | `tickets-ingest-api` | API HTTP que dispara la ingesta (cron, n8n, automatizaciones) |

### Configurar la cuenta de correo

1. Dashboard → pestaña **⚙️ Configuración**.
2. Email, **contraseña de aplicación** (Gmail:
   <https://myaccount.google.com/apppasswords>, requiere 2FA) y servidor IMAP
   (`imap.gmail.com:993` por defecto; Outlook: `outlook.office365.com:993`).
3. **Probar conexión** y **Añadir cuenta**.

Las cuentas se guardan en `data/email_accounts.json`, que **no se versiona**.

### Primera ingesta

Desde el panel (**📥 Ingesta**) o por API:

```bash
# pipeline completo: IMAP (últimos 7 días) → PDFs → OCR → taxonomía
curl -X POST http://localhost:8060/ingest

# reintentar solo el OCR de las fotos pendientes
curl -X POST http://localhost:8060/ingest/ocr

# estado y trabajo pendiente
curl -s http://localhost:8060/status
```

`/status` devuelve `running`, el último `result` y un bloque `pending` con los
ítems que la taxonomía no pudo clasificar y las fotos sin ticket: si algo falla,
se ve ahí en vez de disfrazarse de «0 tickets nuevos».

---

## Ingesta automática con n8n (requisito)

La forma prevista de ejecutar la ingesta es **n8n**, que lanza el pipeline cada
noche a las 03:00, espera a que termine y avisa del resultado. La API de ingesta
(`:8060`) es lo que n8n llama; también se puede invocar a mano con `curl`, pero
la automatización documentada es n8n.

### 1. Levantar n8n junto al proyecto

```yaml
# docker-compose.n8n.yml (añadir al final, o en su propio fichero)
  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      - TZ=Europe/Madrid
      - GENERIC_TIMEZONE=Europe/Madrid        # sin esto el cron de las 03:00 se va de hora
      - N8N_SECURE_COOKIE=false               # solo si entras por http en red local
    volumes:
      - ./data-n8n:/home/node/.n8n
    networks:
      - default
      - n8n_network
```

`n8n_network` tiene que ser la **misma red** en la que está `tickets-ingest-api`
(ya viene declarada, con ese alias, para el servicio de la API). Si n8n queda en
la red `bridge` por defecto, el nodo HTTP falla con `ENOTFOUND
tickets-ingest-api`: el contenedor no resuelve el nombre. Compruébalo con:

```bash
docker exec n8n node -e "fetch('http://tickets-ingest-api:8060/health').then(r=>console.log(r.status))"
```

### 2. Importar el workflow

1. Abre <http://localhost:5678> y crea el usuario propietario (es local, las
   credenciales las eliges tú).
2. **Workflows → Import from file** → `n8n_workflow_ingesta.json`.
3. En el nodo **Enviar WhatsApp**, cambia el `chatId` de ejemplo
   (`CAMBIAME@c.us`) por el tuyo. Si no quieres avisos, borra ese nodo y el de
   *Responder webhook*: el pipeline funciona igual.
4. **Publish** (en n8n 2.x guardar no basta; lo que se ejecuta es la versión
   publicada).

### 3. Comprobar que funciona de verdad

```bash
# ejecuta el grafo completo una vez (responde en ~60 s)
curl -s -m 240 -X POST -H 'Content-Type: application/json' -d '{}' \
     http://localhost:5678/webhook/tickets-ingest
```

Debe devolver `{"whatsapp":"sent",…}` y dejar una ejecución con **varios nodos**
y ~60 s de duración. Señales de que algo está mal:

| Síntoma | Causa |
|---|---|
| Ejecución `success` en 15 ms | el disparador no tiene conexión en la **versión publicada**; vuelve a conectar el arco y pulsa Publish |
| `ENOTFOUND tickets-ingest-api` | n8n no está en `n8n_network` (ver arriba) |
| `ECONNREFUSED 172.17.0.1:3001` | el nodo de WhatsApp apunta a un bridge que no está escuchando; bórralo o usa `wa_proxy.py` |
| Se ejecuta a una hora que no es la 03:00 | falta `GENERIC_TIMEZONE` |

El estado del pipeline, con lo que ha quedado pendiente, se consulta siempre en
`curl -s localhost:8060/status`.

### Alternativa sin n8n

Un cron del host hace lo mismo salvo el aviso:

```cron
0 3 * * * curl -fsS -X POST http://localhost:8060/ingest >/dev/null
```

---

## Variables de entorno

Todas en `.env` (ver `.env.example`, que documenta los tres perfiles):

| Variable | Por defecto | Qué hace |
|---|---|---|
| `OCR_MODE` | `local` | `local` usa el Ollama de tu máquina; `cloud`, la API de Ollama |
| `CLASSIFY_MODE` | `local` | ídem para la clasificación de productos |
| `LOCAL_OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama local visto desde el contenedor |
| `LOCAL_OCR_MODEL` | `minicpm-v4.5:8b` | modelo de visión local |
| `LOCAL_CLASSIFY_MODEL` | `qwen2.5:7b` | modelo de texto local |
| `OLLAMA_BASE_URL` | `https://ollama.com/v1` | API de Ollama Cloud (compatible OpenAI) |
| `OLLAMA_API_KEY` | — | clave de Ollama Cloud; vacía si usas modo local |
| `TICKET_OCR_MODEL` | `glm-5.3-flash` | modelo de visión en la nube |
| `TICKET_CLASSIFY_MODEL` | `deepseek-v4.1-flash` | modelo de texto en la nube |
| `OCR_TIMEOUT` / `OCR_MAX_TOKENS` / `OCR_NUM_CTX` | 600 / 4000 / 8192 | ajustes del OCR |
| `OCR_MAX_IMAGE_PIXELS` | 2500000 | reduce la foto antes de enviarla (0 desactiva) |
| `OCR_MIN_IMAGE_WIDTH` | 900 | ancho mínimo al reducir: no se baja de ahí para no perder texto |
| `OCR_JPEG_QUALITY` | 88 | calidad del JPEG resultante |

Los modelos locales hay que descargarlos antes: `ollama pull minicpm-v4.5:8b`.

---

## Instalación local (sin Docker)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

streamlit run src/dashboard_streamlit.py     # dashboard en :8050
python run_pipeline.py                        # ingesta desde CLI
```

---

## Esquema de datos

SQLite único en `data/tickets.db`:

- **`tickets`** — `id`, `num_ticket`, `fecha` (texto `DD/MM/YYYY HH:MM`),
  `tienda`, `direccion`, `total`, `metodo_pago`, `comercio`, `source_type`
  (`email_pdf` / `email_photo`), `source_file`, `content_hash`, `cuadre_ok`,
  `cuadre_diff`.
- **`line_items`** — `ticket_id`, `cantidad`, `descripcion`, `precio_unit`,
  `importe`, `producto_norm`, `categoria_general`, `subcategoria`,
  `llm_classified`.
- **`catalog_products`** — catálogo de productos conocidos.
- **`taxonomy_overrides`** — correcciones manuales (prioridad máxima).

`llm_classified=0` no significa «pendiente»: los miles de ítems que resuelven las
reglas de Mercadona también lo tienen a 0. Lo pendiente es lo que aparece en
`pending.items_sin_llm` de `/status`.

---

## Datos y privacidad

- `data/` (base de datos, PDFs originales, fotos, cuentas de correo) está en
  `.gitignore`: **no se versiona**. Son datos personales de consumo.
- `.env` tampoco se versiona.
- El dashboard no envía datos a ningún sitio; el único tráfico externo es IMAP y,
  si usas modo `cloud`, la API de Ollama.
- **Aviso**: las contraseñas de las cuentas IMAP se guardan en
  `data/email_accounts.json` codificadas en base64, que **no es cifrado**. Trata
  ese fichero (y sus copias) como un secreto.

---

## Estructura

```
src/ingest.py              IMAP → adjuntos → parser/OCR → SQLite (run_ingestion, run_ocr_only)
src/ocr_llm.py             OCR de fotos con LLM (local o cloud) + cuadre aritmético
src/parse_ticket.py        parser de los PDFs de Mercadona
src/taxonomy.py            reglas, catálogo y clasificación LLM opcional
src/normalize.py           normalización de productos y comercios
src/database.py            esquema y consultas
src/dashboard_streamlit.py dashboard
ingest_api.py              API HTTP de ingesta (:8060)
run_pipeline.py            ingesta desde CLI
wa_proxy.py                proxy loopback para el bridge de WhatsApp (opcional)
n8n_workflow_ingesta.json  workflow de ejemplo (opcional)
docs/                      notas de arquitectura y planes
```

---

## Limitaciones conocidas

- Fotos de ticket: la calidad depende del modelo de visión. El pipeline guarda el
  error y reintenta en la pasada siguiente, pero no garantiza leerlas todas.
- El parser de Mercadona está ajustado al formato actual de su ticket digital; si
  cambian el formato, hay que ajustarlo.
- El cuadre OCR detecta descuadres (±0,02 €) pero no corrige el ticket: avisa en
  el dashboard para revisarlo a mano.
- La ingesta incremental mira los últimos 7 días de correo; huecos mayores
  requieren ampliar la ventana (`since_days`, o `run_ocr_only` para fotos).
- El dashboard está pensado para uso personal en red local: no trae autenticación.

---

## Licencia

MIT — ver [LICENSE](LICENSE).
