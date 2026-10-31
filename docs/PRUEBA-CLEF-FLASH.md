# Prueba de contexto: Clef-flash como modelo de decisión en tickets

> Estado: **PLAN, nada ejecutado aún.** Redactado el 03-oct-2026 con el sistema
> verificado en marcha (`ARQUITECTURA_EN_SERVICIO.md`, verificación 11-sep-2026)
> y comprobaciones de entorno hechas hoy (hardware, Ollama, HF, fichas de modelo).
> Toda ejecución queda a la espera de confirmación.

---

## 0. Preguntas que debe responder la prueba

| # | Pregunta | Métrica que la responde |
|---|----------|------------------------|
| P1 | ¿Clef-flash decide igual o mejor que deepseek-v4.1-flash (vía cloud) sobre las líneas que hoy pasan por el LLM? | Precisión cat+sub sobre muestra, % caídas en "Otros" |
| P2 | ¿Se reduce el uso de tokens (y el coste asociado) respecto a la vía cloud actual? | tokens de entrada/salida por línea, por brazo; coste estimado |
| P3 | ¿Sus probabilidades son utilizables sobre NUESTROS datos (umbral → cola de revisión)? | Curva de fiabilidad propia (bucket prob. declarada vs acierto), ECE aproximado |
| P4 | ¿Es viable en local (0 € por llamada, sin exponer datos de compra a la nube)? | Spike de carga del modelo: srv descartado → portátil RTX; ver Fase 3 |

---

## 1. Contexto verificado (03-oct-2026)

**Sistema actual (lo que está en servicio):**

- Clasificación = reglas (Mercadona) → LLM para el resto. BD real: **6.736 líneas
  resueltas por reglas** (`llm_classified=0`) y **302 por LLM** (`llm_classified=1`);
  33 en "Otros" (10 fijadas por LLM). **54 pares categoría>subcategoría** en uso,
  11 categorías.
- El **prompt actual** (`src/taxonomy.py::_llm_classify_once`) incluye en **cada
  llamada** el JSON completo de `CATEGORIES` (~2,5 KB de texto que viaja en todos los
  lotes; coste fijo a medir en Fase 1, no estimado a ojo) y usa lotes de 10 con
  degradación por bisección cuando el JSON sale mal (`_llm_classify_batch`).
- La configuración real en `.env` es **cloud**: `LOCAL_CLASSIFY_MODEL=deepseek-v4.1-flash:cloud`,
  `OLLAMA_BASE_URL=https://ollama.com/v1`, `OCR_MODE=cloud`. La llamada de prueba a
  hoy funcionó (0,3 s) y **`/api/chat` ya devuelve contadores exactos**
  (`prompt_eval_count`, `eval_count`) → instrumento de tokens gratis.
- El fallback silencioso a `qwen2.5:7b` documentado en §6 de ARQUITECTURA sigue en el
  código; la prueba usa siempre la misma vía que producción para el brazo baseline.

**Clef-flash (modelo candidato):**

- Lanzado 01-oct-2026 por Cloudflare: modelo **de decisión**, no de texto. Entrada =
  `state` (texto/JSON/hasta 4 imágenes) + hasta 64 preguntas tipadas (`noul` sí/no,
  `choice`, `score` rubricado); salida = **probabilidad por opción**, sin generación
  de texto. Entrenado con Brier loss + RLCD para calibrar dichas probabilidades.
- Pesos abiertos (Apache 2.0, base Qwen3.5-9B) en HF. **No publican ni una curva de
  fiabilidad** (crítica recogida por terceros el mismo día del lanzamiento: ni ECE ni
  diagrama de calibración; un tester obtuvo 0,04 y 0,54 del mismo input en los dos
  modelos). → P3 nos toca medirla con nuestros datos.

**Viabilidad local — comprobada hoy, sin deducciones:**

| Sitio | Veredicto | Evidencia |
|---|---|---|
| srv (este host) | **NO viable** | AMD Rembrandt + Radeon 680M (sin CUDA), 14 GiB RAM con 7,4 libres; el tag ejecutable pesa **11 GB** |
| Ollama de ollama.com | **tag `clef-flash:cloud` NO existe** (a 03-oct); estático `9b` con MLX 11-19 GB | ficha `ollama.com/library/clef-flash/tags` |
| Ollama srv 0.33.0 | **404 en `/v1/systemone`** | prueba directa hoy |
| HF `Cloudflare/clef-flash` | **sin GGUF**; 4 shards safetensors (~19 GB bf16) + `joint_head` custom code | API de HF |
| Portátil RTX 3060 Laptop 6 GB (IP-DEL-PORTATIL-GPU) | Único candidato local; **apagado hoy** (SSH timeout) | skill blender-remote-headless |

Consecuencia honesta: la vía local (P4) es un **spike con riesgo real** — o aparece
GGUF/soporte en llama.cpp-Ollama para la arquitectura `qwen3_5` + `joint_head`, o hay
que cuantizar a mano, o no hay local. La prueba cloud (Fases 1-2) **no depende** de
eso y se puede ejecutar ya.

---

## 2. Diseño experimental

**Unidad de evaluación:** las **302 líneas con `llm_classified=1`** (hoy decididas por
el LLM en producción). Es una unidad finita, ya etiquetada, y exactamente la población
 donde un reemplazo de Clef haría trabajo nuevo.

**Honestidad metodológica (declarada de entrada):** la "etiqueta de referencia" es lo
que el sistema actual decidió, **no un ground truth humano**. Comparar contra ella
mide *consistencia con el sistema en servicio*, no verdad. Para romper ese círculo se
añade una **muestra humana pequeña**: 40 líneas al azar de las 302 + 10 de las caídas
en "Otros", revisadas por el usuario en una sesión de ~10 min (plantilla CSV de
dos columnas). Ambas métricas se publicarán separadas: vs-sistema y vs-humano.

**Brazos:**

| Brazo | Vía | Configuración | Qué mide |
|---|---|---|---|
| A (baseline) | API `/api/chat` del sistema actual, sin tocar código en servicio | replay sobre las 302 con lotes de 10 (`temperature 0`) | tokens reales (`prompt_eval_count`/`eval_count`), latencia, nº de reintentos por bisección |
| B1 (Clef flat) | `POST /v1/systemone` (cloud o local según Fase 0) | 1 request por línea: `state` = descripción (+importe), Q1 `choice` categoría (11 opciones), Q2 `choice` subcategoría (54 opciones planas) | igual que A; salida estructurada **sin parseo frágil** |
| B2 (Clef 2-pasos) | idem | 2ª request por línea con subcategorías restringidas a las de la categoría ya elegida | compara si "preguntar menos opciones" mejora la precisión (cuestión abierta, no suponerla) |

Variantes B1/B2 son baratas una vez existe el cliente; medir ambas evita discutir por
intuición después.

**Métricas por brazo** (todas guardadas por-línea en JSONL crudo, reproducible):

1. Precisión exacta: categoría; categoría+subcategoría (vs sistema y vs humano).
2. % de líneas que acaban en "Otros" (coste de cobertura — el indicador que ya
   monitorizamos en §8 de ARQUITECTURA).
3. **Tokens**: entrada y salida por línea y total de las 302; en A se desglosa cuánto
   del prompt es el bloque `CATEGORIES` fijo. En local no hay tokens que comprar, pero
   se cuentan igual (→ latencia estimada).
4. Latencia p50/p95 y tasa de fallo de parseo (A lo hereda de la bisección; B no
   debería tener ninguna — es su argumento de valor).
5. **Calibración** (solo B1/B2): buckets de probabilidad declarada [0,5-0,7) / [0,7-0,85)
   / [0,85-0,95) / [0,95-1] vs acierto observado, y umbral τ resultante: "con τ=0,85 el
   X% se autoasigna y el Y% va a cola de revisión". Con n=302 la ECE tiene IC ancho — se
   declara así, sin sobreclaim.
6. Coste: A y B-cloud en tokens facturables; B-local = 0 €/llamada (el coste real es
   tiempo de carga en la RTX y ocupa la GPU).

**Determinismo y reversibilidad:**

- `temperature 0` en A; en B la salida es una pasada forward, determinista por diseño.
- Todo se guarda en `experimentos/clef/` (ficheros **nuevos**; no se edita nada
  existente; repo limpio comprobado con `git status` antes de empezar, como en las
  fases del TFM).
- Sobre la BD solo **lecturas** (`file:...?mode=ro`). Ninguna escritura en producción:
  los flags de cambio (`CLASSIFY_BACKEND=clef|llm`) son una decisión posterior con sus
  propios pre/post snapshots.
- Vuelta atrás trivial: no se toca nada que no sea añadir ficheros.

---

## 3. Fases

**Fase 0 · Sondas de acceso** (~15 min)
1. Probar si la cuenta de ollama del host puede llamar `clef-flash` aunque el tag no
   aparezca en el catálogo (probar en 11434 con
   `/v1/systemone`, que hoy da 404 → y en `ollama.com/v1/systemone`); si ambos fallan
   por el modelo, el brazo cloud pasa por **Workers AI** (free tier, $0,24/M tok para
   Clef) o transformers en la RTX; se anota como desvío, no como bloqueo.
2. Confirmar el esquema exacto de respuesta del endpoint que toque (campos
   `probabilities`/`confidence`, `usage`).
- **Checkpoint**: si nada de lo anterior da servicio a Clef-flash, el plan se cierra
  aquí y se entrega el informe de por qué (pesos safetensors 19 GB sin GGUF → solo
  transformers, y en la RTX 6 GB no cabe; sería la conclusión honesta).

**Fase 1 · Exportar muestra + baseline** (~30 min)
- `01_exportar_muestra.py`: exporta las 302 (`ticket_id`, línea, tienda, descripcion,
  importe, cat actual, sub actual) + la muestra humana de 50 a CSV/JSONL en
  `experimentos/clef/`.
- `02_replay_brazo_actual.py`: replay (sin tocar el código en servicio: importa las
  funciones de `src/taxonomy.py` desde fuera, igual que hace el docker exec de §8) y
  guarda crudo + usage + latencia por lote.
- **Entrega intermedia**: tokens/línea reales de la vía actual (el "antes" de comparar).

**Fase 2 · Brazo Clef cloud** (~1 h de máquina, incluida en la sesión de ejecución)
- `03_clef_cliente.py`: cliente `/v1/systemone` con detección de endpoint (no
  hardcodear cloud vs local) y variantes B1/B2.
- `04_metricas.py`: tabla comparativa JSON + markdown con las 6 métricas.
- **Entrega**: primera comparación A vs B (tokens, precisión vs-sistema, parseo, latencia).

**Fase 3 · Spike local en la RTX** (solo si el portátil puede estar encendido; riesgo alto)
- Comprobar si Ollama/llama.cpp en Windows ya soporta `qwen3_5`+`systemone`; si no,
  probar la vía transformers con offload a GPU (19 GB bf16 **no cabe** en 6 GB →
  necesitaría quantización manual: coste real de tiempo, estimar antes de intentarlo).
- Umbral de abandono explícito: si en una sesión no hay modelo cargado y respondiendo,
  se cierra y queda documentado como "local inviable a 03-oct-2026".
- Si funciona: repetir B1/B2 local y completar P4 (tiempo/línea, 0 €/llamada).

**Fase 4 · Revisión humana + calibración + informe**
- Sesión de 10 min del usuario con el CSV de 50 líneas (o alternativa: juzgo yo y tú
  auditas una submuestra — a decidir).
- `05_calibracion.py` + informe `experimentos/clef/INFORME.md` con: tabla final por
  brazo, curva de fiabilidad, umbral recomendado, y **veredicto** según §4.

---

## 4. Criterios de decisión (definidos AHORA, antes de medir)

| Veredicto | Condición |
|---|---|
| **Adoptar Clef (local o cloud)** | B ≥ A en precisión-vs-humano (paridad aceptable si B tiene 0 fallos de parseo Y mejor tokens Y ≥ A en "Otros"), con calibración accionable (buckets ordenados) |
| **Adoptar híbrido** | B correcto solo por encima de prob τ, A para el resto — evaluar coste de mantener dos vías |
| **No adoptar** | B peor en precisión-vs-humano, o sin calibración aprovechable, o local inviable y cloud no compensa (más coste/tokens que A) |

El resultado se cita siempre con su lado débil: n=302 (muestra humana n=50), techo de
decisión limitado por la propia coherencia del sistema actual, IC anchos en los buckets
de calibración.

## 5. Riesgos y bloqueadores declarados

1. **GGUF inexistente** (a hoy): la ruta local pura depende de cuantizar o de que
   salga soporte; es el riesgo mayor del objetivo original "local con ollama" y se
   averigua en Fase 0/3 sin gastar más de una sesión.
2. **`clef-flash:cloud` no disponible** → desvío a Workers AI (free tier con límites de
   rate: 302×2 requests caben holgado) o aplazamiento.
3. **Latencia de imagen 13-30 s** (reportada el día del lanzamiento): irrelevante aquí
   porque operamos sobre texto OCR, dato a tener presente si algún día se clasificara
   desde la foto.
4. **La referencia circular** ya está mitigada con la muestra humana; si el usuario no
   dispone de los 10 min, se publica solo vs-sistema y se marca la limitación en
   negrita.
5. **Datos personales**: hoy las líneas ya viajan a ollama.com (deepseek cloud); Clef
   cloud no cambia esa exposición; Clef local la eliminaría — argumento a favor de
   insistir en la Fase 3.

## 6. Fuera de alcance (explícito)

- No reemplazar la ingesta ni el OCR; no tocar `n8n`; no cambiar dashboards.
- No medir Clef 27B (no cabe en ningún sitio local nuestro y el cloud no lo ofrece).
- No usar `benchmark_test_a/b/c` (son fichas de datasets, no tickets — trampa de
  instrumento ya aprendida en el TFM).

## Referencias

- `docs/ARQUITECTURA_EN_SERVICIO.md` §6 y §8 (clasificación actual y regla crítica de "Otros").
- Blog Clef: https://blog.cloudflare.com/clef-decision-models/ · Docs:
  https://developers.cloudflare.com/workers-ai/models/clef/ · Ficha Ollama:
  https://ollama.com/library/clef-flash · Crítica de calibración:
  https://virtualuncle.com/cloudflares-clef-returns-a-confidence-score-nobody-has-checked-whether-its-right/