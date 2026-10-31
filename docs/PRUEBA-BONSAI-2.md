# Prueba de contexto: Bonsai 2 (ternario) como OCR/visión local para los tickets

> Estado: **Fases 0 y 1 EJECUTADAS el 17-oct-2026** (resultados y mediciones en
> `experimentos/bonsai2/RESULTADOS-FASE0-1.md`); Fases 2-4 pendientes de
> confirmación. El sistema en servicio no se ha modificado: BD en solo-lectura,
> `.env`/compose/contenedor `tickets` intactos y el contenedor `ollama` (0.40.0)
> sin tocar — el modelo se probó en un Ollama 0.40.6 temporal nativo en :11435.
>
> Plan original redactado el
> 17-oct-2026 con el sistema en servicio verificado hoy (contenedores, `.env` vivo,
> BD, hardware, fichas de modelo). Toda ejecución (pull, carga de modelos, barrido
> sobre imágenes) queda **a la espera de confirmación del usuario**.

---

## 0. Preguntas que debe responder la prueba

| # | Pregunta | Métrica que la responde |
|---|----------|------------------------|
| P1 | ¿Bonsai 2 lee las **fotos** de tickets con calidad suficiente para sustituir al OCR en la nube? | Exactitud por campo y por línea vs baseline cloud **+ cuadre aritmético** (métrica independiente del baseline) |
| P2 | ¿Qué **tamaño** de los disponibles es el mínimo que sirve? | Barrido 2b / 4b / 9b con el mismo prompt e imágenes; % de JSON válido, líneas detectadas, importes exactos |
| P3 | ¿Es **viable en el servidor** (este host, CPU-only, RAM escasa)? | RAM pico del contenedor ollama durante la inferencia, tokens/s, segundos/ticket, swap tocado |
| P4 | ¿Aguanta el **régimen real** de trabajo (cron nocturno, pocas fotos/semana)? | Tiempo total por lote de las 28 fotos vs ventana de ingesta; 0 € / 0 llamadas a internet |
| P5 | ¿Se elimina de verdad la **dependencia de nube** sin perder datos? | Las 25 fotos históricas releídas en local, comparadas contra lo que hoy está en BD |

---

## 1. Contexto verificado hoy (17-oct-2026)

### 1.1 La tarea real, medida (no supuesta)

- El OCR de visión sólo se aplica a **fotos de comercios no Mercadona**; los 249
  tickets de Mercadona entran por **PDF de texto** (`parse_pdf`), no por visión.
- Población real de la tarea: **25 tickets `source_type='email_photo'`** (348 líneas,
  **13,9 items/ticket** de media) y **28 ficheros en `data/raw_photos/`** (47 MB;
  mediana 1,8 MB, máximo 2,6 MB). Ritmo observado: ~3 fotos/semana.
- El prompt (`src/ocr_llm.py::SYSTEM_PROMPT`) pide JSON de ticket completo
  (comercio, fecha, hora, dirección, num_ticket, items[], total, metodo_pago) con 8
  reglas de lectura (ticket girado, IVA suelto a la derecha, líneas `2 x 1,59 €`
  indentadas, descuentos en negativo, transcripción literal) y una **verificación
  aritmética obligatoria** (suma de importes = total impreso). Es decir: el propio
  prompt ya define una métrica objetiva y gratis de evaluar.

### 1.2 Baseline (lo que hay en servicio, y será el brazo de comparación)

- `.env` **vivo** (la doc `ARQUITECTURA_EN_SERVICIO.md` §6 sigue mostrando
  `OCR_MODE=local`: está desactualizada, como ya avisaba la skill):
  `OCR_MODE=cloud`, `OLLAMA_BASE_URL=https://ollama.com/v1`,
  `LOCAL_OCR_MODEL=minicpm-v4.5:8b`, `OCR_TIMEOUT=300`, `OCR_NUM_CTX=8192`.
  `TICKET_OCR_MODEL` **no** está en `.env` → rige el default del código,
  **`glm-5.3-flash`** por Ollama Cloud.
- `ollama list` en el contenedor: sólo tev1 (0.8b/4b), bge-m3 y modelos `:cloud`.
  **`minicpm-v4.5:8b` no está descargado** → hoy la vía local del OCR está
  inoperativa de hecho; el 100 % de las fotos se leen en la nube.
- La salida del OCR cloud ya está **persistida** en `tickets` + `line_items`
  (274 tickets / 7.158 líneas en BD): base de comparación disponible **sin gastar
  una sola llamada ni tocar el servicio**.
- Referencia circular advertida en la skill: comparar contra la BD mide
  *consistencia con el sistema*, no verdad → se añade cuadre aritmético + revisión
  humana (§2.3).

### 1.3 Ficha de Bonsai 2 (Prism ML) — verificada en registry.ollama.ai

Familia de **visión con pesos ternarios** (−1, 0, +1), Apache 2.0, **contexto
262K**, soporta *thinking*, *tool calling* e imagen. Arquitectura base `qwen35`;
`runner: llamacpp`, `format: gguf`. Los GGUF son
`Ternary-Bonsai-2-<N>B-Q2_0.gguf` + `mmproj-Q8_0.gguf` (**Q2_0 = el tipo ternario
de llama.cpp**, no un i-quant normal).

| Tag | Descarga total | Pesos | Proyector visión | Parámetros |
|-----|---------------|-------|------------------|-----------|
| `2b` | **911 MB** | 547 MB | 365 MB (Q8_0) | 1,88 B |
| `4b` | **1,6 GB** | 1,21 GB | 367 MB (Q8_0) | 4,21 B |
| `9b` (= `latest`) | **3,2 GB** | 2,56 GB | 624 MB (Q8_0) | 8,95 B |
| `27b` | **8,3 GB** | 7,63 GB | 629 MB (Q8_0) | 26,9 B |

(Existe además un tag `4b-q2_0`.) Los `params` del modelo traen
`temperature 1, top_k 20, top_p 0.95` (y `min_p 0.05` en el 27b) → **hay que fijar
temperature 0 en la prueba** si se quiere reproducibilidad, igual que en el brazo A.

### 1.4 Hardware del servidor — medido hoy, sin deducciones

| Recurso | Valor real | Consecuencia |
|---|---|---|
| CPU | 12 vCPU AMD hasta 4,56 GHz | Todo es **inferencia CPU** |
| RAM | **14 GiB totales, 5,4 GiB disponibles** (9,5 en uso, 194 MiB "libre"; swap 12 GiB con 4,2 en uso) | Recurso **escaso**; 25 contenedores conviven aquí |
| GPU | Sólo iGPU **Radeon 680M**; el contenedor `ollama` es la imagen **nvidia** sin passthrough → sin CUDA/ROCm utilizable | Sin aceleración; la 680M no es candidata práctica |
| Ollama | **0.40.0**, contenedor `ollama` (compartido por open-webui, anythingllm, buscador/PFM) | Cambiar de imagen/versión afectaría a otros servicios → **no se hará sin confirmación** |
| Disco de modelos | `/root/.ollama` sobre `/dev/sda1`: **387 GB libres** | El tamaño de descarga **no** es limitante (27b cabría en disco) |
| Consumo en reposo | ollama 32 MiB, tickets 97 MiB, open-webui 439 MiB | El margen lo consume la RAM, no el disco |

---

## 2. Veredicto de viabilidad por tamaño (regla de la casa: nada que no quepa en la RAM libre)

La regla ya verificada en este host: *cualquier modelo cuya carga ocupe más allá de
la RAM libre (~7-8 GiB en hora valle; hoy 5,4 GiB) no es viable*, y una vez cargado
**hay que descargarlo** (`keep_alive: 0`) y volver a comprobar la RAM.

| Tag | RAM aprox. al cargar (pesos + proyector + KV corta) | Veredicto | Nota |
|---|---|---|---|
| `2b` | ~1,1-1,5 GB | **Viable siempre** | Cabe incluso en hora punta; es el experimento más barato |
| `4b` | ~1,9-2,5 GB | **Viable siempre** | **Candidato principal**: 4,2 B de params en 1,6 GB |
| `9b` | ~3,6-4,5 GB | **Viable con condiciones** | Sólo en hora valle, `keep_alive=0`, contexto acotado; riesgo real de swap que degradaría al resto del host |
| `27b` | ~9-10 GB | **NO viable en este host** | Supera la RAM libre total; descartado salvo cambio de hardware |

Aclaración honesta: los rangos de RAM son **cálculo a partir de los tamaños de
fichero**, no medidas → la Fase 0 los sustituye por RAM pico real del contenedor.

Comparación de contexto: el candidato local actual (`minicpm-v4.5:8b`, ~5,5 GB) es
**3,4× más grande** que Bonsai 2 4b y no está descargado. El interés real de Bonsai 2
es precisamente ese: un modelo de visión que por fin cabe en 1,6 GB, que es lo que
hace viable el OCR local en un host con 5,4 GiB disponibles.

### 2.1 ¿Y la velocidad en CPU?

No se puede afirmar sin medir. Dos hechos que la condicionan:

1. **A favor**: Q2_0 es el formato ternario que llama.cpp ya trae con kernels
   optimizados (linaje bitnet), pensado para CPU. El `runner` es `llamacpp`, no un
   backend experimental.
2. **Cuidado**: el precedente del proyecto es duro — `minicpm-v4.5:8b` en CPU
   tardaba **hasta 5 min** por ticket de 44 items (de ahí `OCR_TIMEOUT=600`), y el
   propio código avisa de que "se ejecuta en un contenedor Docker Ollama CPU-only".
   Con 13,9 items/ticket la cifra esperable es menor, pero **es una incógnita que la
   prueba resuelve en la Fase 0 con una sola foto**.
3. **Atenúa el riesgo**: el régimen real es ~3 fotos/semana en un cron nocturno. Si
   un ticket tarda 1-2 min en CPU, el sistema sigue siendo **perfectamente
   utilizable**; lo que mataría la idea es >10 min/foto o un JSON inválido recurrente.

### 2.2 ¿Es suficientemente bueno? (lo que se puede y no se puede decir hoy)

No se puede afirmar sin ejecutar, y así se declara. Lo que sí se puede fijar de
antemano es **qué significaría "suficiente"**, con los números del propio proyecto:

- Hoy sólo **348 líneas** (25 tickets) provienen de fotos → un umbral de calidad
  exigible es que el modelo local **no empeore** el cuadre aritmético ni el recuento
  de líneas respecto al cloud, y que el importe exacto por línea se mantenga.
- La experiencia previa de esta casa con modelos locales pequeños en la taxonomía
  (tev1 0,8b/4b: 25-56 %) avisa de que **2b probablemente no bastará** para leer un
  ticket torcido con abreviaturas; 4b y 9b son los candidatos reales.
- El *thinking* del modelo es un arma de doble filo: puede ayudar con la aritmética
  del ticket, pero infla tokens y `OCR_MAX_TOKENS` recortaría el JSON → hay que
  medir las dos configuraciones (thinking on/off), no suponer.

---

## 3. Diseño experimental

### 3.1 Unidad y brazos

**Unidad**: las 28 imágenes de `data/raw_photos/` (las 25 históricas + variantes),
con su JSON de referencia ya en BD.

| Brazo | Vía | Configuración |
|---|---|---|
| **A (baseline)** | Ollama Cloud, `glm-5.3-flash`, `https://ollama.com/v1` | Replay del **mismo prompt y mismas imágenes**, `temperature 0`, `OCR_MAX_TOKENS/MODE` = los del `.env` vivo. **No se modifica el servicio**: el replay se hace desde un script fuera del contenedor que importa `src/ocr_llm.py` |
| **B2 / B4 / B9 (local)** | Ollama local, `bonsai-2:2b` / `:4b` / `:9b` por `/api/chat` | Mismo prompt e imágenes; `temperature 0`; `keep_alive` explícito; `num_ctx` acotado; variantes **thinking on/off** en el tamaño ganador |
| **H (humano)** | El usuario mira 8-10 pares foto ↔ JSON | Referencia externa al sistema (rompe la circularidad) |

### 3.2 Métricas (todas guardadas crudas en JSONL, por imagen y por brazo)

1. **Validez del JSON** sin reparación: % de respuestas parseables directamente
   (el pipeline actual degrada por bisección cuando el JSON sale mal → reintentos).
2. **Cuadre aritmético** `|Σ importes − total| < 0,02` → **métrica objetiva,
   independiente del baseline**; es la más importante y no es circular.
3. **Campos de cabecera**: `num_ticket`, `fecha`, `total`, `comercio` correctos.
4. **Líneas**: nº detectadas vs baseline, importes con coincidencia exacta,
   descripciones normalizadas (`producto_norm`) coincidentes.
5. **Errores tipificados del prompt**: IVA suelto contado como importe, línea
   `2 x 1,59 €` emitida como artículo, descuento mal signado. Se cuentan a mano en
   la muestra humana.
6. **Coste máquina**: segundos/ticket, tokens/s (`eval_count`/`eval_duration`),
   RAM pico del contenedor, swap tocado, tokens de entrada/salida.
7. **Ahorro**: llamadas a internet = 0; coste en tokens cloud evitado.

### 3.3 Reglas de no-interferencia (compromiso explícito)

- **Nada del servicio se toca**: ni `.env`, ni `docker-compose.n8n.yml`, ni la BD
  (`sqlite3` siempre `file:...?mode=ro`), ni el contenedor `tickets`. Sólo ficheros
  nuevos.
- **Nada de actualizar Ollama** para "probar si soporta el modelo": si el 0.40.0 no
  carga Q2_0, se documenta y se para — el contenedor `ollama` lo comparten
  open-webui, anythingllm y el buscador.
- Modelos cargados **siempre con `keep_alive: 0`** y comprobación de `free -h`
  antes y después de cada barrido (lección ya pagada en este host: 167 MiB libres).
- Los 9b/27b sólo se cargan en **ventana de baja actividad**, nunca con la ingesta
  nocturna en marcha.
- Antes de empezar: `git status` limpio (hoy hay ficheros sueltos en `docs/` y
  `src/dashboard_t1.py` sin trackear → se anotan, no se tocan).

### 3.4 Ficheros y fases

Todo bajo `experimentos/bonsai2/` (nuevo):

**Fase 0 · Sondas de soporte y coste unitario (~20 min, ~1 GB descargado)**
1. `docker exec ollama ollama pull bonsai-2:2b` → verifica que el 0.40.0 **carga**
   el ternario Q2_0 (si falla el load, se para aquí: *no se actualiza Ollama*).
2. Una sola foto → RAM pico, tokens/s, segundos, JSON válido o no.
3. **Checkpoint**: si no carga, o si >10 min/foto, el plan se cierra y se entrega el
   informe de por qué.

**Fase 1 · Export de muestra + baseline A (~30 min)**
- `01_exportar_muestra.py` → lista de las 28 imágenes con su ticket de referencia.
- `02_replay_cloud.py` → brazo A sobre las mismas 28 imágenes (coste cloud ~nulo).

**Fase 2 · Barrido local 2b / 4b / 9b sobre las 28 fotos (2-8 h CPU, en franjas)**
- `03_barrido_local.py` append a JSONL por tamaño (sobrevive a cortes).
- Descarga 4b (+1,6 GB) y, sólo si el 4b queda corto y la RAM lo permite, 9b (+3,2 GB).

**Fase 3 · Métricas + revisión humana**
- `04_metricas.py` → tabla por brazo con las 7 métricas.
- Sesión de ~10 min del usuario: 8-10 pares foto ↔ JSON (o auditar mi juicio).

**Fase 4 · Informe y veredicto** → `experimentos/bonsai2/INFORME.md`.

---

## 4. Criterios de decisión (fijados AHORA, antes de medir)

| Veredicto | Condición |
|---|---|
| **Adoptar local (tamaño mínimo)** | JSON válido ≥ 90 %, cuadre aritmético ≥ 80 % de tickets, importes exactos ≈ baseline, y RAM dentro de la ventana valle |
| **Adoptar como híbrido** | Local sólo si cuadra y con cola de revisión en el resto; cloud queda como respaldo explícito |
| **No adoptar** | JSON inválido recurrente, cuadre < 60 %, o 2b/4b/9b indistinguibles de ruido → se documenta y se cierra |

n = 25 tickets / 348 líneas: **IC anchos**, se publicará así, sin sobreclaim.

## 5. Riesgos y bloqueadores declarados

1. **Q2_0 ternario y Ollama 0.40.0 — CONFIRMADO Y CERRADO**: el pull da 412; el
   soporte del tensor Q2_0 llegó en **v0.40.6** (PR #18967). Probado con éxito en un
   Ollama 0.40.6 temporal en :11435 (ver `RESULTADOS-FASE0-1.md` §1). Si el modelo
   entra en producción, hay que subir el contenedor `ollama` a ≥0.40.6 (afecta a
   open-webui, anythingllm y buscador → decisión del usuario) o mantener una
   segunda instancia dedicada a tickets.
2. **RAM**: 9b al filo de los 5,4 GiB disponibles; un swap sostenido degradaría los
   25 contenedores. Mitigación: hora valle, `keep_alive=0`, contexto acotado.
3. **Velocidad CPU**: desconocida hasta medir; el precedente minicpm-v4.5:8b (5 min/
   ticket) obliga a medir antes de prometer nada.
4. ***Thinking***: puede mejorar la aritmética y a la vez truncar el JSON; hay que
   probar ambas configuraciones.
5. **n pequeño** (25 tickets, pocas fotos/semana): conclusiones con incertidumbre
   explícita; no extrapolar a tickets manuscritos que no estén en `raw_photos`.
6. **Reintentos de OCR en la nube**: cualquier cambio de `.env` es posterior a la
   prueba y con su propio pre/post; el brazo A nunca escribe en producción.

## 6. Fuera de alcance (explícito)

- No tocar la vía PDF/Mercadona (249 tickets, `parse_pdf`), ni la taxonomía, ni
  n8n, ni dashboards, ni el proxy.
- No evaluar `bonsai-2:27b` (no cabe en este host).
- No modificar `OCR_MODE`, ni `.env`, ni la imagen/versión de Ollama.
- No cambiar `LOCAL_OCR_MODEL` (minicpm-v4.5:8b) en esta fase.

## Referencias

- Ficha y manifiestos: https://ollama.com/library/bonsai-2 ·
  `registry.ollama.ai/v2/library/bonsai-2/manifests/{2b,4b,9b,27b}`
- Whitepaper 27B: https://github.com/PrismML-Eng/Bonsai-demo/blob/main/bonsai-2-27b-whitepaper.pdf
- `docs/ARQUITECTURA_EN_SERVICIO.md` §6 (§6 desactualizado en `OCR_MODE`; rige el `.env`)
- `src/ocr_llm.py` (prompt, modos cloud/local, timeouts)
- Precedente metodológico: `docs/PRUEBA-CLEF-FLASH.md`
