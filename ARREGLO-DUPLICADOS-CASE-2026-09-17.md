# Duplicados por mayúsculas/minúsculas — ARREGLADO (17-sep-2026)

## Decisión de diseño

**Opción elegida: nombre canónico único** (Forma Título: `Cerveza`), no mantener las
variantes. Razones:

1. El nombre canónico **ya existe** en el catálogo: las 1.050 reglas de `KEYWORD_RULES`
   definen `('CERVEZA', 'Bebidas', 'Cerveza', 'Cerveza')`. El canónico no había que
   inventarlo, solo respetarlo.
2. La convención dominante en la BD ya es Forma Título (342 nombres) frente a 98 en
   mayúsculas y 12 en minúsculas.
3. Mantener `Cerveza` y `CERVEZA` como productos distintos **parte las estadísticas**:
   el gasto aparecía como 800,27 € + 243,36 €, y en la lista había 696 entradas en vez
   de 690.
4. Unificar con `lower()` a secas **rompería nombres buenos**: `Aceite de oliva` →
   `Aceite De Oliva`.

## Resultado

| | antes | ahora |
|---|---|---|
| Pares de case duplicados | 6 | **0** |
| Productos únicos | 696 | **690** |
| Compras de cerveza | 135 + 38 partidas | **173 unificadas** (1.043,63 €) |
| Líneas sin subcategoría | 38 | **0** |
| Filas fusionadas | — | **44** |

## Cambios de código (4 defectos reales)

### 1. El override propagaba la descripción cruda (causa principal, 38 filas)

`taxonomy.py`, `_load_override_maps()`: si un override no tenía `producto_norm`
explícito, se usaba la descripción del ticket como nombre de producto. Con el override
id=6 (`descripcion='CERVEZA'`, `producto_norm=NULL`) eso generaba `producto_norm='CERVEZA'`
en 38 filas, **exentas de las reglas** porque el override tiene prioridad.

Ahora se deriva el canónico con las reglas del catálogo:

```python
nom = r["producto_norm"] or _canonical_product(r["descripcion"])
```

Añadida la función `_canonical_product()`, que busca el nombre en `KEYWORD_RULES`.

### 2. El override de cerveza estaba mal configurado

El override id=6 la clasificaba como `Alimentación` sin subcategoría (una cerveza es
`Bebidas`/`Cerveza`). Corregido a `Bebidas`/`Cerveza`/`Cerveza`.

También tenían el nombre vacío los overrides 7, 8 y 9 (`MELON 4%`, `NARANJA FONTESTAD 4%`,
`MELOCOTON ROJO 4% #003`). Rellenados con su canónico (`Melón`, `Naranja`, `Melocotón`).

### 3. No había unificación de case (defecto de fondo)

Añadida `unify_product_case(conn, dry_run)`, que se ejecuta como **último paso** de
`apply_taxonomy_to_db()` (así ninguna fase previa puede reintroducir un desdoble). Tiene
dos pasadas:

- **Paso 1**: fusiona grupos con varias variantes (`CERVEZA` + `Cerveza`). El canónico se
  elige solo si las reglas del catálogo lo nombran así; si no, la forma más presentable
  (Título > minúsculas > MAYÚSCULAS) y más usada.
- **Paso 2**: corrige nombres únicos que solo difieren en case del canónico. Cubre las
  líneas `llm_classified=1`, a las que las reglas no tocan (caso de `PATATA`, `MANGO`,
  `PEPINO`, `NECTARINA` de los tickets reprocesados; y `PARAGUAYO`).

### 4. Había DOS normalizadores compitiendo

`ingest.py` Fase 3 llama a `normalize.normalize_all_in_db()` y después a
`taxonomy.apply_taxonomy_to_db()`. El primero usaba el catálogo antiguo de
`normalize.CATEGORY_RULES`, que **no tiene regla para nectarina** ni otras muchas: devolvía
la descripción cruda. Los items que la taxonomía no re-toca (no-Mercadona con
`llm_classified=1`) se quedaban con el nombre del catálogo viejo.

Corregido: `normalize_all_in_db()` ahora delega en `taxonomy.normalize_product()`, y solo
rellena los items con `producto_norm` vacío (no pisa los canónicos ya calculados).

## Blindaje del dashboard (3 sitios)

Para que aunque se cuele una variante no vuelva a verse desdoblada:

- `view_producto()`: agrupa por `lower()` y muestra una sola entrada; al filtrar usa
  **todas** las variantes equivalentes.
- `view_categoria()` (drill-down "Detalle por producto"): mismo tratamiento.

La agrupación usa `max(v, key=lambda x: (x.istitle(), x))` para mostrar la forma
presentable (`Cerveza`, no `CERVEZA`).

## Verificación contra el backup

Backup previo: `data/tickets.db.bak-case-20260917_200740`.

- `line_items`: 6.845 filas, suma **16.761,64 €** — idéntica antes y después
- `tickets`: 256, suma **16.786,44 €** — idéntica
- Filas con `importe`/`cantidad`/`descripcion` distintos: **0**
- Tickets con `total`/`comercio`/`fecha` distintos: **0**
- Filas cuyo `producto_norm` cambió: 48 (las fusionadas; esperado)
- Huérfanos: 0. Sin nombre: 0.
- La diferencia preexistente line_items vs tickets (24,80 €) es **idéntica** antes y
  después: no la introdujo este cambio.

Servicios: ambos contenedores `healthy`, dashboard 200, API `{"ok": true}`.

## Pendiente

- **Ticket 898** (Lidl): diff +0,72 € (mejoró desde el fallo total, pero no cuadra).
- **4 tickets de Mercadona de PDF** descuadrados: usan `pdfplumber`, no el LLM.
