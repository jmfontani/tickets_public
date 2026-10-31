# Paso a cloud y reprocesado en lote — 17-sep-2026 (estado final)

## Resultado

**8 de los 9 tickets descuadrados quedan cuadrando exactamente (0,00 €).**

| id viejo | id nuevo | comercio | diff antes | diff ahora | líneas |
|---|---|---|---|---|---|
| 955 | 1016 | dia | +20,06 | **0,00** | 34 |
| 813 | 1017 | simply-business | +17,81 | **0,00** | 4 |
| 833 | 1021 | action | −3,58 | **0,00** | 8 |
| 820 | 1022 | mad factory | −2,24 | **0,00** | 16 |
| 855 | 1018 | lidl | +1,90 | **0,00** | 5 |
| 811 | 1023 | el jamon | +1,30 | **0,00** | 44 |
| 898 | 898 | lidl | +0,72 | +0,72 (intacto) | 19 |
| 839 | 1019 | primaprix | −0,60 | **0,00** | 8 |
| 999 | 1020 | primaprix | +0,30 | **0,00** | 15 |

Integridad final: **256 tickets, 6.845 líneas, 0 huérfanos, 0 sin clasificar,
0 duplicados por content_hash**. Siguen descuadrados 4 de Mercadona que vienen de **PDF**
(parser `pdfplumber`, no el LLM) y el 898 de Lidl.

Clasificación: **19 líneas en "Otros"** (12 antes) — las 7 de más son líneas nuevas que el
OCR ahora sí lee. `llm_classified=1`: 192 (antes 188). Alimentación incluso sube (+6).

## Configuración cloud aplicada

En `.env` (backups `.env.bak-cloud-*` y `.env.bak-classify-*`; sigue en `.gitignore`):

- `OCR_MODE=cloud` (era `local`) — el modelo local lee mal la maquetación
- `OCR_TIMEOUT=300` (era 600, dimensionado para CPU)
- `OCR_MAX_TOKENS=8000`
- `OLLAMA_BASE_URL=https://ollama.com/v1`
- `OLLAMA_API_KEY` — **no estaba** en el `.env` del proyecto (solo en `~/.hermes/.env`),
  por eso el contenedor no la tenía y caía en modo local
- `LOCAL_CLASSIFY_MODEL=deepseek-v4-flash:0731-cloud` ← crítico, ver abajo

Imagen reconstruida y contenedores recreados. Verificado **dentro** del contenedor:
`MODE=cloud`, `TOKENS=8000`, `CLASSIFY=deepseek-v4-flash:0731-cloud`, `KEY=SET`, prompt
nuevo presente, ambos `healthy`, API `/health` OK, dashboard 200.

## El clasificador de taxonomía estaba roto (causa raíz)

`LOCAL_CLASSIFY_MODEL` estaba en `deepseek-v4.1-flash`, y el modelo **no se encontraba**
(`model 'deepseek-v4.1-flash' not found` → todo caía a "Otros").

**Corrección importante:** `deepseek-v4.1-flash` **sí existe** en el catálogo de Ollama
(https://ollama.com/library/deepseek-v4.1-flash). Lo que faltaba era la **etiqueta
`:cloud`**, que el Ollama local necesita para enrutar al catálogo cloud. El nombre correcto
es `deepseek-v4.1-flash:cloud` — que además clasifica mejor que la alternativa.

Probado en el contenedor con las mismas descripciones:

| Modelo | Resultado |
|---|---|
| `deepseek-v4.1-flash:cloud` | **clasifica bien** — `Fruta`, `Verdura y hortaliza`, `Pasta, arroz y legumbres`, y los difíciles: `TAMPAX → Higiene íntima`, `VICTORIA CERVEZA → Cerveza`, `PANTALON FALSO → Ropa` |
| `deepseek-v4-flash:0731-cloud` | clasifica bien, pero peor en los difíciles |
| `deepseek-v4.1-flash` (sin `:cloud`) | `model not found` → todo a `Otros` |
| `qwen2.5:7b` | existe pero el parseo falla (devuelve objeto suelto, no array) |
| `llama3.2:3b` | **timeout** en todos los items |

Nota: la clasificación **no es perfectamente determinista** entre ejecuciones — el mismo
producto (`ALUBIAS CON VERDURAS`) salió como `Conservas y caldos` en una pasada y como
`Comida preparada`/`Pasta, arroz y legumbres` en otras. Todas válidas.

Procedencia del valor roto: mi propio `sustituye_modelos.py` (16-sep). El mapeo
`deepseek-v4-flash:0731-cloud` → `deepseek-v4.1-flash` **eliminaba el sufijo `:cloud`**,
que era justo lo que hacía que el nombre resolviera. El contenedor antiguo conservaba el
valor bueno en memoria, por eso no se notó; al recrearlo afloró. **Script corregido** para
preservar el sufijo.

Tras arreglarlo y relanzar la clasificación **desde el contenedor**, "Otros" bajó de 97 a
19: las 97 eran el síntoma de este fallo.

## Dos errores míos, ambos corregidos

**1. Borré antes de extraer.** El script borraba el ticket y luego llamaba al LLM. Al
fallar la extracción (prosa en vez de JSON), 4 tickets quedaron borrados (833, 820, 811,
898). **Restaurados del backup automático** con todos sus campos y líneas. Ya corregido en
ambos scripts: **extraer primero, borrar después**, con 4 reintentos.

**2. El comercio se perdía.** Al reinsertar se tomaba del LLM, que devolvía `otros`:
`primaprix` y `simply-business` se perdían en silencio. Corregido: si el LLM no reconoce
el comercio, se conserva el que ya tenía el ticket. Los 3 afectados corregidos a mano.

**3. Regresión de clasificación en "Otros" (97 líneas).** Efecto colateral de recrear el
contenedor con `LOCAL_CLASSIFY_MODEL` roto: los tickets reprocesados quedaban
`llm_classified=0` y sin clasificar. Resuelto al arreglar el clasificador y relanzarlo
desde el contenedor. Bajó de 97 a 19.

**Recuperados del backup** (`tickets.db.bak-lote-20260917_154023`, copia automática del
propio script) restaurando la fila de `tickets` y sus `line_items` con todos los campos
originales. Verificado: los 4 presentes con sus 6/14/44/19 líneas y sumas idénticas a las
de antes. No se perdió ningún dato.

## Segunda regresión: el comercio se perdía

Al reinsertar, el comercio se tomaba del LLM (`ticket.tienda`). Para los tickets que el
modelo no identifica devolvía `otros`, así que **primaprix → otros** y
**simply-business → otros**, en silencio.

Corregido: si el LLM no reconoce el comercio, se **conserva el valor que ya tenía** el
ticket. Y los 3 afectados (1017, 1019, 1020) se corrigieron a mano
(`simply-business`, `primaprix`, `primaprix`).

## Por qué fallaron 4: el LLM devuelve PROSA

No era el prompt ni el límite de tokens per se. `glm-5.3-flash` a veces responde con un
**razonamiento en texto** ("Let me analyze this receipt from Action. Header: ...") y el
JSON viene después, o no viene:

| Imagen | completion_tokens | Resultado |
|---|---|---|
| action (833) | 1.136 | prosa + JSON al final → `_extract_json_from_text` lo saca: 8 items, 14,98 ✅ |
| mad factory (820) | 1.874 | prosa + JSON → 16 items, 27,20 ✅ |
| el jamón (811) | 5.412 | prosa + JSON → 44 items, 76,76 ✅ |
| lidl (898) | **8.000 (tope)** | `finish_reason: length`, **truncado, sin JSON** ❌ |

El `reasoning_effort=none` **no impide esta prosa**: el modelo la emite como `content`
normal (el campo `reasoning` está a 0). Es un razonamiento "de facto" que se cuela en el
contenido. **El fallo es intermitente**: la misma imagen que falla sale bien al reintentar.

**Lo que SÍ funciona: reintentar.** Con 4 intentos se resolvieron 3 de los 4 fallos
(833→1021, 820→1022, 811→1023). Implementado en los dos scripts.

**Lo que NO funciona** (probado y descartado):

- `response_format: {"type": "json_object"}` → ignorado, misma prosa
- 3 variantes de prompt anti-prosa (prohibir texto antes del JSON, "empieza por `{`",
  cabecera + cola) → las 4 variantes devolvieron prosa igual
- subir `max_tokens` a 16.000 → el 898 sigue sin dar JSON (su prosa ocupa ~19.870 chars)

## Pendiente

- **Ticket 898** (Lidl): falla de forma persistente (su prosa no llega a dar JSON ni con
  reintentos).
- **4 tickets de Mercadona de PDF** descuadrados (−3,35 a −9,55 €): no pasan por el LLM,
  usan `pdfplumber` + regex. Problema distinto, sin tocar.
- **`sustituye_modelos.py`**: corregido para **preservar el sufijo `:cloud`** (quitarlo hacía
  que el modelo no resolviera). Conviene además restringirlo a ficheros/variables de OCR y
  no tocar claves de configuración como `LOCAL_CLASSIFY_MODEL`.

## Scripts en el proyecto

- `reprocesa_ticket.py <id|fichero> [--apply]` — un ticket, dry run por defecto.
- `reprocesa_lote.py [--apply] [--ids 1,2]` — lote de descuadrados, dry run por defecto.
  Ambos: backup de BD, extraer-antes-de-borrar, conservar comercio, y cierre con
  `normalize_all_in_db()` + `apply_taxonomy_to_db()`.
- `prueba_prompt.py` / `prueba_prompt_local.py` — validar el prompt con cloud / local.
- `diagnostico_prosa.py` — ver qué devuelve el LLM en crudo (prosa vs JSON).
- `prueba_json_mode.py` — comparar variantes de payload (p. ej. `response_format`).
