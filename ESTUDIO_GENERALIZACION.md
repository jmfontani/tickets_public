# Estudio: Evolución a Almacén General de Tickets

**Fecha:** 2026-08-10  
**Proyecto:** tickets
**Objetivo:** Convertir el sistema de tickets de supermercado en un almacén general de cualquier tipo de ticket/factura, con dos dashboards (supermercado + general) y auto-aprendizaje de categorización.

---

## 1. Estado actual

### 1.1 Esquema de BD

```
tickets: id, num_ticket, fecha, tienda, direccion, telefono, operador,
         total, metodo_pago, pdf_file, iva_json, email_account,
         comercio, source_type, source_file

line_items: id, ticket_id, cantidad, descripcion, precio_unit, importe,
            fecha, producto_norm, categoria
```

- 242 tickets, 6,629 líneas, todos de Mercadona
- 18 categorías hardcoded en `normalize.py` (~667 reglas de substring)
- `comercio` default = 'mercadona'
- `categoria` en `line_items` — solo aplica a productos de supermercado

### 1.2 Componentes

- `parse_ticket.py` — parser regex para PDFs de Mercadona
- `ocr_llm.py` — extracción con LLM de visión (glm-5.3-flash)
- `normalize.py` — categorización por reglas hardcoded
- `ingest.py` — ingesta por email `[ticket]` con imágenes adjuntas
- `dashboard.py` — Dash app con 7 pestañas, filtro por comercio
- `database.py` — CRUD + migraciones automáticas

### 1.3 Limitaciones para generalizar

1. **Esquema centrado en supermercado:** `comercio`, `tienda`, `producto_norm`, `categoria` solo tienen sentido para tickets de compra
2. **LLM prompt limitado a supermercados:** pide `comercio` de lista cerrada (mercadona|lidl|aldi|...)
3. **Categorización solo para productos:** 18 categorías de supermercado, no hay categorías de ticket (hogar, seguros, etc.)
4. **No hay concepto de "tipo de gasto":** un ticket de seguro o factura de luz no encaja en el modelo actual
5. **No hay aprendizaje:** las reglas son estáticas, el usuario no puede recategorizar y el sistema no aprende

---

## 2. Arquitectura propuesta

### 2.1 Nuevo esquema de BD

```sql
-- Tabla tickets (añadir columnas)
ALTER TABLE tickets ADD COLUMN tipo_ticket TEXT DEFAULT 'supermercado';
-- tipo_ticket: 'supermercado' | 'hogar' | 'seguros' | 'salud' | 'transporte' |
--              'ocio' | 'restaurantes' | 'servicios' | 'otros'
ALTER TABLE tickets ADD COLUMN proveedor TEXT DEFAULT '';
-- proveedor: nombre de la empresa/emisor (ej. Repsol, Mapfre, Endesa)
ALTER TABLE tickets ADD COLUMN subtipo TEXT DEFAULT '';
-- subtipo: granularidad dentro del tipo (ej. 'gasolina', 'seguro coche', 'luz')
ALTER TABLE tickets ADD COLUMN concepto_general TEXT DEFAULT '';
-- concepto_general: descripción libre del gasto (ej. "Factura luz agosto")

-- Tabla nueva: learning_rules (aprendizaje de categorización)
CREATE TABLE IF NOT EXISTS learning_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,          -- substring a buscar en descripcion
    campo TEXT NOT NULL,            -- 'categoria' | 'subtipo' | 'tipo_ticket' | 'producto_norm'
    valor TEXT NOT NULL,            -- valor a asignar
    fuente TEXT DEFAULT 'user',     -- 'user' | 'system'
    confianza REAL DEFAULT 1.0,    -- 0.0 a 1.0
    veces_aplicada INTEGER DEFAULT 0,
    fecha_creacion TEXT DEFAULT (datetime('now')),
    fecha_ultima_aplicacion TEXT DEFAULT '',
    UNIQUE(pattern, campo, valor)
);

-- Tabla nueva: recategorizaciones (auditoría de cambios del usuario)
CREATE TABLE IF NOT EXISTS recategorizaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    line_item_id INTEGER,
    campo_anterior TEXT NOT NULL,   -- 'categoria' | 'subtipo' | 'tipo_ticket'
    valor_anterior TEXT,
    valor_nuevo TEXT,
    fecha TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);
```

### 2.2 Modelo de datos conceptual

```
Ticket (cualquier tipo)
├── tipo_ticket: supermercado | hogar | seguros | salud | ...
├── proveedor: Mercadona | Repsol | Mapfre | Endesa | ...
├── comercio: (deprecated, se mantiene por compatibilidad = proveedor para supermercado)
├── subtipo: gasolina | seguro hogar | factura luz | ...
├── concepto_general: descripción libre
└── line_items (opcional, solo para supermercado/tienda)
    ├── descripcion
    ├── precio_unit, importe, cantidad
    ├── producto_norm (normalización)
    └── categoria (categorización)
```

**Tipos de ticket previstos:**

| tipo_ticket | Ejemplos | ¿Tiene line_items? | proveedor ejemplos |
|---|---|---|---|
| supermercado | Compra semanal | Sí | Mercadona, Lidl, Aldi, Carrefour |
| hogar | Luz, agua, gas, internet | No (total + concepto) | Endesa, Canal de Isabel, Repsol, Movistar |
| seguros | Seguro coche, hogar, vida | No (total + concepto) | Mapfre, Allianz, Generali |
| salud | Farmacia, dentista, fisio | A veces | Farmacia García, Clínica Dental |
| transporte | Gasolina, parking, bus, metro | A veces | Repsol, EMT, Renfe |
| ocio | Cine, concierto, parque | A veces | Cinesa, Ticketmaster |
| restaurantes | Cena, comida | A veces | Restaurante X, McDonald's |
| servicios | Peluquería, taller, fontanero | A veces | Peluquería Y, Auto Taller Z |
| otros | Lo que no encaje | Variable | — |

### 2.3 LLM de visión — prompt generalizado

El prompt actual pide solo datos de supermercado. El nuevo prompt debe:

1. **Detectar el tipo de ticket** automáticamente
2. **Extraer proveedor** (nombre de la empresa emisora)
3. **Extraer items si los hay** (para supermercado/restaurantes/farmacia)
4. **Extraer concepto_general** (para facturas sin items)
5. **Extraer subtipo** si es detectable (ej. "gasolina 95", "seguro hogar")

```python
SYSTEM_PROMPT_GENERAL = (
    'Eres un extractor de tickets y facturas español. Analiza la imagen '
    'y determina primero el TIPO de documento: supermercado, hogar, seguros, '
    'salud, transporte, ocio, restaurantes, servicios, otros. '
    'Devuelve ÚNICAMENTE un JSON válido con este esquema: '
    '{"tipo_ticket": "string", "proveedor": "string", "fecha": "dd/mm/yyyy", '
    '"hora": "HH:MM", "direccion": "string", "num_ticket": "string", '
    '"subtipo": "string (ej. gasolina, seguro_hogar, factura_luz)", '
    '"concepto_general": "string (descripción del gasto si no hay items)", '
    '"items": [{"cantidad": int, "descripcion": "string", "precio_unit": float, "importe": float}], '
    '"total": float, "metodo_pago": "string", "iva": float}'
)
```

### 2.4 Sistema de aprendizaje

**Flujo de auto-aprendizaje:**

```
1. LLM extrae ticket → asigna categoria/subtipo/tipo_ticket iniciales
2. Usuario revisa en dashboard → recategoriza si es incorrecto
3. Sistema guarda recategorización en tabla recategorizaciones
4. Sistema genera regla en learning_rules:
   - pattern: substring de la descripcion del item o concepto
   - campo: el campo que el usuario cambió
   - valor: el valor nuevo que asignó
5. En la siguiente ingesta, antes de usar la categorización del LLM,
   el sistema busca en learning_rules si hay una regla que coincida
6. Si hay regla con confianza >= 0.5, se aplica (override del LLM)
7. Cada vez que una regla se aplica, se incrementa veces_aplicada
   y se sube la confianza
```

**Algoritmo de matching de reglas:**

```python
def apply_learning(descripcion: str, campo: str, llm_value: str) -> str:
    """Aplica reglas de aprendizaje. Devuelve el valor final."""
    conn = get_db()
    cur = conn.execute(
        "SELECT valor, confianza FROM learning_rules "
        "WHERE campo = ? AND ? LIKE '%' || pattern || '%' "
        "ORDER BY confianza DESC, veces_aplicada DESC LIMIT 1",
        (campo, descripcion)
    )
    rule = cur.fetchone()
    if rule and rule[1] >= 0.5:
        # Actualizar contador
        conn.execute(
            "UPDATE learning_rules SET veces_aplicada = veces_aplicada + 1, "
            "fecha_ultima_aplicacion = datetime('now') "
            "WHERE pattern = ? AND campo = ? AND valor = ?",
            (pattern, campo, rule[0])
        )
        return rule[0]  # Override del LLM
    return llm_value  # Mantener valor del LLM
```

### 2.5 Dos dashboards

**Dashboard 1: General** (`/tickets/` — ruta actual renombrada)

- Vista global de todos los gastos por tipo
- KPIs: gasto total por tipo_ticket, por mes, por proveedor
- Gráfico de barras: gasto por tipo_ticket
- Gráfico de tarta: distribución por tipo
- Timeline: evolución de gastos por tipo
- Tabla de tickets con columnas: fecha, tipo, proveedor, concepto, total
- Filtro por tipo_ticket, proveedor, rango fechas
- Botón "recategorizar" en cada ticket → abre modal

**Dashboard 2: Supermercado** (`/tickets/super/`)

- El dashboard actual (KPIs por comercio, comparativa de precios, etc.)
- Filtrado automáticamente a tipo_ticket = 'supermercado'
- Accesible desde el dashboard general como "drill-down" de la categoría supermercado

**Navegación:**
- Dashboard general → clic en "Supermercados" → abre dashboard de supermercado
- Dashboard de supermercado → botón "← Volver" → dashboard general

### 2.6 Implementación técnica de los dos dashboards

**Opción A: Dos apps Dash separadas (recomendada)**

```python
# dashboard_general.py — app Dash para vista general
app_general = Dash(__name__, requests_pathname_prefix='/tickets/')
# sirve en puerto 8050

# dashboard_super.py — app Dash para supermercado (dashboard.py actual renombrado)
app_super = Dash(__name__, requests_pathname_prefix='/tickets/super/')
# sirve en puerto 8051
```

nginx:
```nginx
location /tickets/ {
    proxy_pass http://tickets:8050;
}
location /tickets/super/ {
    proxy_pass http://tickets:8051;
}
```

**Opción B: Una app con tabs condicionales**

Más simple pero menos flexible. No recomendada porque las dos vistas tienen lógica muy diferente.

---

## 3. Modificaciones por archivo

### 3.1 `database.py` — Migración de esquema

- Añadir columnas `tipo_ticket`, `proveedor`, `subtipo`, `concepto_general` a tabla `tickets`
- Crear tablas `learning_rules` y `recategorizaciones`
- Función `_migrate_db_v2()` para migrar BD existente
- `insert_ticket()` aceptar nuevos campos opcionales
- Nuevas funciones:
  - `get_tipos_ticket()` → lista de tipos
  - `get_proveedores()` → lista de proveedores
  - `get_tickets_by_tipo(tipo)` → filtrar por tipo
  - `add_learning_rule(pattern, campo, valor)` → insertar regla
  - `apply_learning_rules(descripcion, campo, llm_value)` → aplicar reglas
  - `record_recategorizacion(ticket_id, campo, valor_old, valor_new)` → auditar cambio
  - `get_learning_rules()` → listar reglas (para panel admin)

### 3.2 `ocr_llm.py` — Prompt generalizado

- `SYSTEM_PROMPT` → `SYSTEM_PROMPT_GENERAL` (detecta tipo de ticket)
- `validate_ticket()` → validar también tipo_ticket y proveedor
- `process_image_to_ticket()` → devolver tipo_ticket, proveedor, subtipo, concepto_general
- Mantener compatibilidad: si tipo_ticket = 'supermercado', seguir devolviendo items

### 3.3 `ingest.py` — Ingesta universal

- El asunto `[ticket]` ya funciona para cualquier tipo
- El LLM detecta el tipo automáticamente
- `run_ingestion()` → usar `process_image_to_ticket()` que ahora devuelve tipo
- Si tipo = 'supermercado', aplicar `normalize_product()` como ahora
- Si tipo != 'supermercado', no buscar line_items (o usarlos si los hay)
- Aplicar `apply_learning_rules()` después de la extracción del LLM

### 3.4 `normalize.py` — Mantener + delegar

- Las 667 reglas de Mercadona se mantienen intactas
- Añadir función `apply_learning_rules(descripcion, campo, llm_value)` que consulta la BD
- `normalize_product()` → primero busca en learning_rules, luego en reglas hardcoded
- Para tickets no-supermercado, la categorización viene del LLM + learning

### 3.5 `dashboard.py` → `dashboard_super.py`

- Renombrar archivo
- `requests_pathname_prefix='/tickets/super/'`
- Filtrar automáticamente `tipo_ticket = 'supermercado'`
- Mantener todas las pestañas actuales
- Añadir botón "← Volver al dashboard general"

### 3.6 `dashboard_general.py` — Nuevo archivo

- App Dash nueva con `requests_pathname_prefix='/tickets/'`
- Pestañas:
  1. **Resumen** — KPIs por tipo, gráfico de barras, tarta
  2. **Evolución** — timeline de gastos por tipo
  3. **Tickets** — tabla con todos los tickets, filtro por tipo/proveedor
  4. **Recategorizar** — panel para reclasificar tickets y que el sistema aprenda
  5. **Ingesta** — mismo que actual
- Link a dashboard de supermercado

### 3.7 `run_pipeline.py` — Lanzar ambos dashboards

- Arrancar `dashboard_general.py` en puerto 8050
- Arrancar `dashboard_super.py` en puerto 8051

### 3.8 `docker-compose.yml` — Exponer puerto 8051

- Añadir `expose: ["8050", "8051"]`

### 3.9 nginx — Segunda ruta

```nginx
location /tickets/ {
    proxy_pass http://tickets:8050;
}
location /tickets/super/ {
    proxy_pass http://tickets:8051;
}
```

---

## 4. Panel de recategorización

### 4.1 UI

En el dashboard general, pestaña "Recategorizar":

1. **Tabla de tickets recientes** con columnas: fecha, proveedor, concepto, tipo actual, subtipo actual
2. **Dropdowns editables** para cambiar tipo_ticket y subtipo
3. **Botón "Aplicar y aprender"** que:
   - Actualiza el ticket en la BD
   - Registra el cambio en `recategorizaciones`
   - Genera reglas en `learning_rules` a partir del patrón:
     - Si el usuario cambia el tipo de un ticket de Endesa de "otros" a "hogar"
     - Se crea regla: pattern="endesa", campo="tipo_ticket", valor="hogar", confianza=0.8
4. **Tabla de reglas existentes** con opción de eliminar/editar

### 4.2 Generación de reglas automáticas

Cuando el usuario recategoriza:

```python
def learn_from_recategorizacion(ticket_id, campo, valor_nuevo):
    """Genera reglas de aprendizaje desde una recategorización."""
    ticket = get_ticket(ticket_id)
    
    # Patrones a probar como regla
    patrones = []
    if ticket['proveedor']:
        patrones.append(ticket['proveedor'].lower())
    if ticket['concepto_general']:
        # Palabras significativas del concepto
        palabras = [w for w in ticket['concepto_general'].lower().split() 
                    if len(w) > 3 and w not in STOPWORDS]
        patrones.extend(palabras[:3])  # Top 3 palabras
    
    for pattern in patrones:
        add_learning_rule(pattern, campo, valor_nuevo, fuente='user', confianza=0.8)
```

### 4.3 Persistencia del aprendizaje

- Las reglas se guardan en SQLite (`learning_rules`)
- Se exportan/importan como JSON para backup
- Cada regla tiene `veces_aplicada` y `confianza` que suben con el uso
- Reglas con confianza baja (< 0.3) y 0 aplicaciones se pueden purgar automáticamente

---

## 5. Plan de implementación

### Fase A: Esquema de BD + aprendizaje (1 sesión)

1. Migrar `database.py`: nuevas columnas + tablas learning
2. Funciones CRUD para learning_rules y recategorizaciones
3. Migración automática de BD existente (tipo_ticket='supermercado' para todos)

### Fase B: LLM generalizado (1 sesión)

4. Actualizar `ocr_llm.py`: prompt general, tipo_ticket, proveedor, subtipo
5. Actualizar `ingest.py`: aplicar learning_rules después de extracción
6. Test con imagen de ticket de supermercado + factura de luz

### Fase C: Dashboard general (1 sesión)

7. Crear `dashboard_general.py` con pestañas: resumen, evolución, tickets, recategorizar
8. Renombrar `dashboard.py` → `dashboard_super.py` con prefix `/tickets/super/`
9. Actualizar `run_pipeline.py` para lanzar ambos
10. Actualizar nginx y docker-compose

### Fase D: Panel de recategorización (1 sesión)

11. UI de recategorización en dashboard general
12. Generación automática de reglas desde recategorizaciones
13. Aplicación de reglas en ingesta
14. Test end-to-end: ingesta → recategorizar → nueva ingesta → ¿aprende?

---

## 6. Consideraciones

### 6.1 Compatibilidad

- Los 242 tickets existentes se migran automáticamente con `tipo_ticket='supermercado'`
- `comercio` se mantiene por compatibilidad (= proveedor para supermercados)
- Las reglas de `normalize.py` siguen funcionando para supermercados
- El dashboard de supermercado no cambia (solo se mueve de ruta)

### 6.2 Rendimiento

- `learning_rules` se consulta en cada ingesta, pero la tabla será pequeña (< 1000 reglas)
- Indexar por `(campo, pattern)` para búsquedas rápidas
- El LLM se llama una vez por ticket (igual que ahora)

### 6.3 Privacidad

- Las imágenes de tickets pueden contener datos personales
- Se guardan en `data/raw_photos/` (ya se hace)
- El LLM recibe la imagen pero no la almacena (Ollama Cloud API stateless)
- Las reglas de aprendizaje no contienen datos personales (solo patrones de texto)

### 6.4 Limitaciones

- El aprendizaje por substring es simple pero efectivo para empezar
- No hay embeddings ni ML avanzado (innecesario para el volumen actual)
- Se podría evolucionar a un clasificador basado en embeddings si el volumen crece