# Productos duplicados por mayúsculas/minúsculas — 17-sep-2026

## El síntoma que reporta el usuario

En la vista **🔍 Producto**, al buscar "cerveza" aparecen **dos entradas** que son la misma
cosa: `Cerveza` y `CERVEZA`. Deberían tratarse como una sola.

## Dos causas independientes

### Causa A — El override de "CERVEZA" propaga la descripción cruda (38 filas)

**Este es el caso grande: 38 compras, 243,36 €.**

En `taxonomy.py`, `_load_override_maps()` línea **1380**:

```python
overrides_by_desc[r["descripcion"]] = (
    r["categoria_general"], r["subcategoria"],
    r["producto_norm"] or r["descripcion"])      # <-- aquí
```

Si un **override** no tiene `producto_norm` explícito, se usa la **descripción cruda del
ticket** como nombre de producto. Y hay exactamente ese override:

```
id=6  tipo=producto  descripcion='CERVEZA'  categoria_general='Alimentación'
      subcategoria=''  producto_norm=None  created_at='2026-08-31 10:52:57'
```

Resultado: las 38 filas con `descripcion='CERVEZA'` reciben `producto_norm='CERVEZA'`
(mayúsculas) y quedan **exentas de las reglas de normalización**, porque el override tiene
prioridad sobre ellas. Verificado: **38/38** filas con `producto_norm='CERVEZA'` tienen
`descripcion='CERVEZA'`.

Nota: el override también fija `categoria_general='Alimentación'` y `subcategoria=''`, que
es incorrecto para una cerveza (debería ser `Bebidas` / `Cerveza`). Parece un override
creado por error desde la UI de reasignación (o con el campo "nombre normalizado" vacío).

Los otros overrides con `producto_norm=None` (`MELON 4%`, `NARANJA FONTESTAD 4%`,
`MELOCOTON ROJO 4% #003`) tienen el mismo defecto, pero como sus descripciones son únicas
no generan duplicados visibles — solo nombres feos en la lista.

### Causa B — Líneas clasificadas por LLM no se normalizan (4 filas)

`apply_taxonomy_to_db()` documenta: *"Los items marcados como clasificados por LLM
(`llm_classified=1`) no se sobreescriben con las reglas, solo con overrides manuales."*

Esas líneas se quedan con `producto_norm` = descripción cruda. Las 4 afectadas son de
tickets **reprocesados hoy** por mí:

| item | descripción | producto_norm | ticket | comercio |
|---|---|---|---|---|
| 27580 | PATATA | `PATATA` | 1016 | dia |
| 27582 | MANGO | `MANGO` | 1016 | dia |
| 27581 | PEPINO | `PEPINO` | 1016 | dia |
| 27681 | NECTARINA | `NECTARINA` | 1023 | el jamón |

Las 4 tienen `llm_classified=1`, así que las reglas no las tocan.

## Alcance real: 5 pares, 312 filas

| canónico | variante | filas | gasto canónico | gasto variante |
|---|---|---|---|---|
| Cerveza | CERVEZA | 135 + 38 | 800,27 € | 243,36 € |
| Patata | PATATA | 94 + 1 | 176,68 € | 0,83 € |
| Mango | MANGO | 28 + 1 | 57,70 € | 3,54 € |
| Pepino | PEPINO | 12 + 1 | 5,79 € | 0,20 € |
| Nectarina | NECTARINA | 1 + 1 | 2,62 € | 1,61 € |

Total a unificar: **312 filas**. Productos únicos pasan de 696 a **691**.

Efecto en las estadísticas: el gasto de cerveza aparece **partido** (800,27 € y 243,36 €
como si fueran dos productos), y el de patata/mango/pepino/nectarina duplicado en filas
sueltas.

## Por qué `Nectarina` es un caso especial

`normalize_product('NECTARINA')` devuelve `('Otros', 'NECTARINA')`: **no existe regla** para
nectarina en `CATEGORY_RULES`, así que el fallback (línea 498, `return "Otros",
descripcion`) devuelve la descripción cruda. Necesita además una regla nueva.

## Plan de arreglo propuesto (no ejecutado)

**1. Corregir el defecto de diseño** (`taxonomy.py` línea 1380). En vez de caer a la
descripción cruda, derivar el nombre canónico con las reglas:

```python
# en lugar de: r["producto_norm"] or r["descripcion"]
nom = r["producto_norm"]
if not nom:
    _, nom = normalize_product(r["descripcion"], overrides_by_desc)
```

Así un override sin nombre explícito hereda el nombre canónico en vez de propagar el texto
del ticket. **Esto solo, ya arregla las 38 filas de cerveza en la siguiente pasada.**

**2. Corregir los datos.** Backup previo de `tickets.db`, y luego:
- Unificar por `lower(producto_norm)` los 5 pares hacia el nombre canónico (capitalizado).
- Corregir el override id=6 a `producto_norm='Cerveza'`, `categoria_general='Bebidas'`,
  `subcategoria='Cerveza'`.
- Revisar los otros 3 overrides con nombre vacío.

**3. Cubrir las líneas `llm_classified=1`.** Que también reciban nombre canónico cuando su
`producto_norm` sea solo una variante de *case* de un nombre ya conocido.

**4. Añadir la regla que falta** de `NECTARINA` → `Nectarina` en `CATEGORY_RULES`.

**5. Endurecer el sistema contra futuros casos.** La solución de fondo no es parchear datos
sino **normalizar el case al escribir**: agrupar por `lower()` en la vista y/o guardar
siempre el nombre canónico. Recomendado: hacer la comparación por `lower()` en
`view_producto()`, para que aunque se cuele una variante no se vea desdoblada.

## Medidas de seguridad antes de tocar

- Backup de `tickets.db` (como en los reprocesados de hoy).
- Ejecutar los `UPDATE` con `lower(...)` y verificar el recuento antes/después.
- No hay `UNDO` para overrides: revertir = restaurar backup.
