# Tickets · Documentación de lo que está EN SERVICIO

> Última verificación: 11-sep-2026 (rama `n8n-ingest`).
> Este documento describe **lo que realmente está desplegado y funcionando**, no lo que
> se podría hacer. Si algo no aparece aquí, no está en servicio.

---

## 1. Resumen en una frase

Pipeline de tickets de compra: se descargan los tickets por IMAP (PDF de Mercadona,
fotos de otros comercios), se les hace OCR con un LLM local, se clasifican por
categoría/subcategoría con reglas + LLM, y todo se consulta en un dashboard Streamlit
publicado en `https://ejemplo.com/tickets/`.

---

## 2. Dónde vive cada cosa

| Elemento | Ruta / valor |
|---|---|
| Código | `/ruta/a/tickets` |
| Rama git | `n8n-ingest` (remoto `origin` = github.com/jmfontani/tickets) |
| Base de datos | `/ruta/a/tickets/data/tickets.db` (SQLite) |
| Fotos de tickets | `data/raw_photos/` |
| PDFs de tickets | `data/raw_pdfs/` |
| Cuentas de correo | `data/email_accounts.json` |
| Variables de entorno | `/ruta/a/tickets/.env` |
| Workflow n8n (export) | `n8n_workflow_ingesta.json` |

**Nota de seguridad:** el remoto git tiene el token de GitHub embebido en la URL.
Conviene moverlo a un credential helper. No se documenta el valor.

---

## 3. Contenedores en servicio

Ambos se levantan con `docker-compose.n8n.yml` (NO con `docker-compose.yml`, que es la
variante antigua de un solo contenedor):

```bash
cd /ruta/a/tickets
docker compose -f docker-compose.n8n.yml up -d --build
```

| Contenedor | Imagen | Puerto | Función |
|---|---|---|---|
| `tickets` | `tickets-tickets-dashboard` | `8050:8050` | Dashboard Streamlit |
| `tickets-ingest-api` | `tickets-tickets-ingest-api` | `8060:8060` | API de ingesta para n8n |

- Ambos comparten el volumen `./data` → **misma BD SQLite**.
- Ambos usan `env_file: .env` y `extra_hosts: host.docker.internal:host-gateway`
  (para llegar a Ollama en el host).
- `tickets-ingest-api` está en la red externa `n8n_network` con alias
  `tickets-ingest-api`, para que n8n lo resuelva por nombre.

**Importante:** `src/` se copia dentro de la imagen en el build. Editar el `.py` en el
host **no** cambia el contenedor: hay que reconstruir (o `docker cp` para una prueba
puntual, que se pierde al recrear).

---

## 4. Publicación web

El dashboard no se expone directamente a internet: se publica a través del nginx del
contenedor `wikis`.

- URL: `https://ejemplo.com/tickets/`
- En nginx: `location /tickets/` → `proxy_pass http://tickets:8050`
  (con `Upgrade`/`Connection` para el websocket de Streamlit y
  `proxy_read_timeout 900s`)
- `location = /tickets` → redirección 301 a `/tickets/`
- Config dentro del contenedor: `/etc/nginx/nginx.conf` (server `ejemplo.com`)

**Detalle clave:** el contenedor arranca Streamlit con `--server.baseUrlPath=tickets`.
Por eso las rutas internas son `/tickets/_stcore/health` etc. Si cambias el prefijo del
proxy, hay que cambiar también `baseUrlPath`.

---

## 5. Flujo de ingesta (lo que se ejecuta de verdad)

Orquestado por n8n. Workflow: **`Tickets · Ingesta n8n`** (id `ticketsN8nIngest01`),
**activo** en la BD `/DATA/AppData/n8n/database.sqlite`.

Disparadores:
- **Cron: cada noche a las 3:00** (`0 3 * * *`)
- **Webhook manual**: `POST /webhook/tickets-ingest`

Secuencia del workflow:
1. `POST http://tickets-ingest-api:8060/ingest` → responde **202** y trabaja en segundo plano
2. Espera 60 s
3. `GET http://tickets-ingest-api:8060/status` en bucle hasta que termina
4. Si hubo error, lo reporta
5. Envía el resumen por WhatsApp a `http://172.17.0.1:3001/send`
   (proxy puente hacia el bridge de WhatsApp)

### API de ingesta (`ingest_api.py`, puerto 8060)

| Método | Ruta | Comportamiento |
|---|---|---|
| GET | `/health` | `{"ok": true}` |
| GET | `/status` | Estado del job en curso/último |
| POST | `/ingest` | Ingesta completa (email + OCR + taxonomía). **202** + `job_id` |
| POST | `/ingest/ocr` | Solo OCR sobre imágenes pendientes |

- Devuelve **409 `busy`** si ya hay un job corriendo (no se solapan).
- El trabajo va en un hilo aparte; se consulta con `/status`.

### Pipeline interno (`src/ingest.py` → `run_ingestion`)

1. **IMAP**: lee las cuentas de `data/email_accounts.json`, busca correos recientes (por defecto 7 días)
2. Distingue **PDF de Mercadona** de **fotos** de otros comercios
3. Deduplica por `content_hash` (MD5)
4. **OCR** de las imágenes con `src/ocr_llm.py`
5. **Normalización** con `src/normalize.py`
6. **Taxonomía** con `src/taxonomy.py` → `apply_taxonomy_to_db()`

---

## 6. OCR y clasificación (modelos en uso)

Configurado en `.env`:

```
OCR_MODE=cloud                            # valor VIVO en .env (esta doc decía 'local': estaba desfasada)
TICKET_OCR_MODEL=glm-5.3-flash            # es el DEFAULT del código; no está fijado en .env
OLLAMA_BASE_URL=https://ollama.com/v1
LOCAL_OLLAMA_URL=http://host.docker.internal:11434
LOCAL_OCR_MODEL=minicpm-v4.5:8b          # vía local (hoy sin descargar: el 100% de las fotos se leen en la nube)
LOCAL_CLASSIFY_MODEL=deepseek-v4.1-flash:cloud
OCR_TIMEOUT=300
OCR_MAX_TOKENS=8000
OCR_NUM_CTX=8192
```

Ollama corre **en el host** (contenedor `ollama`, puerto 11434) y los contenedores de
tickets llegan a él por `host.docker.internal`.

⚠️ **Aviso**: `LOCAL_CLASSIFY_MODEL` debe existir en Ollama. Si no existe, el código cae
al valor por defecto `qwen2.5:7b`, que da peores resultados y **falla de forma silenciosa**
(los tickets acaban en "Otros"). Verifica con:

```bash
curl -s http://localhost:11434/api/tags
```

### 7. Cuadre aritmético del OCR (desde 18-oct-2026)

Cada ticket leído por visión se comprueba **en código** (no se delega en el modelo):
`src/ocr_llm.py::compute_cuadre()` suma los `importe` de los items que devolvió el OCR y
los compara con el total impreso del ticket, con tolerancia **±0,02 €**.

- Resultado persistido en `tickets.cuadre_ok` (1 cuadra / 0 descuadra / NULL no
  evaluable) y `tickets.cuadre_diff` (suma − total).
- La ingesta avisa en el resultado y en el progreso (`⚠ Descuadre OCR ...`).
- El dashboard muestra la métrica **⚠ Descuadres OCR** en la barra lateral y un
  desplegable con los tickets afectados en el Panel de Control.

Por qué en código y no pidiéndoselo al modelo: medido con `bonsai-2` (oct-2026) que el
modelo puede escribir `"cuadra": true` **copiando el total impreso en su campo
`suma_items`** en vez de sumar sus propios items, es decir su autoinforme no es fiable.

Relleno histórico: `scripts/backfill_cuadre.py` (aritmética sobre datos ya en BD, con
copia de seguridad previa). Ejecutado el 18-oct-2026: 274 tickets → **269 cuadran, 5
descuadran** (4 `email_pdf` del parser de texto, hasta −9,55 €; 1 `email_photo` +0,72 €).

---

## 7. Base de datos

SQLite en `data/tickets.db`. Tablas:

- **`tickets`** — cabecera. Campos clave: `id`, `num_ticket` (UNIQUE), `fecha`, `tienda`,
  `direccion`, `total`, `metodo_pago`, `pdf_file`, `iva_json`, `comercio`, `source_type`
  (`email_pdf` | `email_photo`), `source_file`, `content_hash`, `email_account`
- **`line_items`** — líneas. Campos clave: `ticket_id`, `descripcion`, `importe`,
  `producto_norm`, `categoria_general`, `subcategoria`, `llm_classified`, más los
  `catalog_*` (enriquecido desde el catálogo de Mercadona)
- **`taxonomy_overrides`** — reasignaciones manuales (`tipo` = `item` o `descripcion`)
- **`catalog_products`** — catálogo de productos (Mercadona)

Estado verificado: **254 tickets**, **6.791 líneas**.

### Consultas útiles

```bash
cd /ruta/a/tickets
# Líneas sin clasificar (la taxonomía no llegó a ejecutarse)
sqlite3 data/tickets.db "SELECT COUNT(*) FROM line_items WHERE categoria_general IS NULL;"
# Líneas atrapadas en Otros habiendo pasado por el LLM
sqlite3 data/tickets.db "SELECT COUNT(*) FROM line_items WHERE categoria_general='Otros' AND llm_classified=1;"
# Distribución por categoría
sqlite3 data/tickets.db "SELECT categoria_general, COUNT(*) FROM line_items GROUP BY 1 ORDER BY 2 DESC;"
```

### Backup

```bash
cp data/tickets.db data/tickets.db.bak_$(date +%Y%m%d_%H%M)
```

---

## 8. Taxonomía (`src/taxonomy.py`)

- **`CATEGORIES`** — diccionario categoría → lista de subcategorías (fuente de verdad).
- **`apply_taxonomy_to_db()`** — el barrido principal. Orden de aplicación:
  1. Overrides manuales (máxima prioridad)
  2. Reglas por palabra clave (para Mercadona)
  3. LLM para lo que las reglas no resuelven
- **`llm_classify_uncategorized()`** — fuerza la clasificación por LLM.
- **`add_override` / `reassign_product` / `reassign_item`** — reasignación manual.
- **`normalize_store()`** — limpia los nombres de tienda/dirección.

### Regla crítica aprendida

Si el LLM **no** sabe clasificar y responde "Otros", **no** se debe marcar
`llm_classified=1`. Si se marca, esa línea queda fijada en "Otros → Varios" para siempre
y ninguna ingesta posterior la reintenta. En el código:

```python
already_done = 0 if cat == "Otros" else 1
```

Esto está aplicado en **las dos** rutas del LLM (items de tiendas no-Mercadona e items de
Mercadona que caen en "Otros").

### Cómo diagnosticar "todo sale como Otros"

Son dos fallos distintos que se ven igual en el dashboard:

1. `categoria_general IS NULL` → el barrido de taxonomía **no se ejecutó** sobre esas
   filas (ingesta interrumpida, o tickets insertados después). Solución: reejecutar
   `apply_taxonomy_to_db()`.
2. `categoria_general='Otros' AND llm_classified=1` → el LLM corrió pero su respuesta
   quedó fijada. Solución: resetear el flag y reejecutar.

```bash
docker exec tickets-ingest-api sh -c 'cd /app && python3 -c "
import sys; sys.path.insert(0,\"/app\")
from src.taxonomy import apply_taxonomy_to_db
apply_taxonomy_to_db()"'
```

---

## 9. Dashboard (`src/dashboard_streamlit.py`)

Streamlit, `--server.baseUrlPath=tickets`. Ocho vistas en el menú lateral:

| Vista | Función | Qué muestra |
|---|---|---|
| 📊 Panel | `view_dashboard` | KPIs con comparativa vs periodo anterior, gasto mensual, top categorías, treemap |
| 🏪 Establecimiento | `view_establecimiento` | Gasto por cadena |
| 📂 Categoría | `view_categoria` | Subcategorías y productos; drill-down a tickets |
| 🔍 Producto | `view_producto` | Evolución de precio, historial de compras |
| 📅 Temporal | `view_temporal` | Evolución mensual, comparativas |
| 🧾 Tickets | `view_tickets` | **Historial + detalle del ticket** |
| ⚙️ Categorías | `view_gestion_categorias` | Reasignación manual (overrides) |
| 📥 Ingesta | `view_ingesta` | Lanzar ingesta y reclasificación desde la UI |

### Vista 🧾 Tickets

- Tabla de tickets con **botón "👁 Ver" en cada fila** (`st.column_config.ButtonColumn`).
  Al pulsarlo se abre el detalle del ticket debajo.
- El botón fija `st.session_state["ticket_manual_sel"]`; el detalle se resuelve por
  `num_ticket` sobre `df_t` / `df_i`.
- También hay un desplegable ("O elige un ticket en la lista") como alternativa.
- El detalle muestra: total, nº de productos, fecha, tienda, desglose de IVA, tabla de
  líneas, resumen por categoría con gráfico, y la imagen o PDF del ticket.

**Nota:** la tabla usa `st.dataframe` (no `st.table`). `st.table` es estático y no admite
botones — fue justo el motivo de que "pulsar la línea" no hiciera nada.

---

## 10. Operación habitual

### Ver si está todo arriba
```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep tickets
curl -s -o /dev/null -w "dashboard %{http_code}\n" http://localhost:8050/tickets/_stcore/health
curl -s -o /dev/null -w "api %{http_code}\n" http://localhost:8060/health
```

### Lanzar una ingesta a mano
```bash
# Vía API (asíncrona, responde 202)
curl -s -X POST http://localhost:8060/ingest
curl -s http://localhost:8060/status
```

### Ver logs
```bash
docker logs tickets --tail 100
docker logs tickets-ingest-api --tail 100
```

### Desplegar un cambio de código
```bash
cd /ruta/a/tickets
docker compose -f docker-compose.n8n.yml up -d --build
```

### Reiniciar tras cambiar `.env`
```bash
docker compose -f docker-compose.n8n.yml up -d --force-recreate
```

---

## 11. Probar el dashboard sin navegador

`AppTest` de Streamlit permite ejercitar la app dentro del contenedor (útil porque el
navegador headless tiene bloqueadas las IPs privadas):

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("/app/src/dashboard_streamlit.py", default_timeout=200)
at.run()
at.radio[0].set_value("🧾 Tickets")
at.run()
print(at.dataframe[0].value.columns)   # debe incluir 'Ver'
```

⚠️ Limitación conocida: `AppTest` **no dispara** los callbacks de `ButtonColumn` al
inyectar el estado del clic. Para validar el botón hay que probarlo en el navegador.

---

## 11bis. Verificación del 11-sep-2026

Comprobado en vivo, no deducido:

- Contenedores `tickets` y `tickets-ingest-api`: **up (healthy)**, ambos desde la misma
  build.
- `GET :8050/tickets/_stcore/health` → **200**; `GET :8060/health` → **200**.
- `POST :5678/webhook/tickets-ingest` → **200** (workflow activo y disparable).
- Ingesta completa ejecutada de principio a fin: **sin errores**, 31 s, y **sin cambios**
  en la BD (254 tickets / 6.791 líneas antes y después) → la deduplicación por
  `content_hash` funciona.
- `data/` está sobre **exFAT** (`/dev/sda1` → `/home/usuario/datos`), confirmado con
  `findmnt`. Ver aviso en la sección de limitaciones.

---

## 12. Limitaciones y deudas conocidas

- **`ButtonColumn` sin verificar en navegador real.** La columna y el callback están
  implementados y la app no lanza excepciones, pero el clic end-to-end no se ha podido
  comprobar con herramientas automatizadas. Pendiente de prueba manual.
- **Dos dashboards en el repo.** `src/dashboard.py` (Dash, filas clicables) existe pero
  **no está en servicio**; el que se sirve es `dashboard_streamlit.py`. Confundirlos lleva
  a editar el fichero equivocado.
- **Token de GitHub en la URL del remoto git.**
- **El `data/` está en un directorio de 131.072 bytes de tamaño de entrada** (exFAT), lo
  que sugiere que vive en un volumen exFAT. Cuidado con permisos y con SQLite sobre red.
- **`mercadona.db` está vacío (0 bytes)** — resto de versiones anteriores.
- Ficheros `tmp_apptest_*.py` y `tmp_probe.py` en la raíz del proyecto: scripts de
  diagnóstico temporal, se pueden borrar.

---

## 13. Chuleta de rutas rápidas

```
Código             /ruta/a/tickets
Compose en uso     docker-compose.n8n.yml
Dashboard (local)  http://localhost:8050/tickets/
Dashboard (público) https://ejemplo.com/tickets/
API ingesta        http://localhost:8060  (/health /status /ingest)
BD                 data/tickets.db
Config             .env
Workflow n8n       id ticketsN8nIngest01  (cron 3:00, webhook /tickets-ingest)
```
