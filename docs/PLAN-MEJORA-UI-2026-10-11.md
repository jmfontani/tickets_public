# PLAN — Mejora de interfaz de usuario del dashboard de Tickets

Fecha: 11-oct-2026 · Objetivo: modernizar la UI del dashboard Streamlit (`datos/tickets/src/dashboard_streamlit.py`, 1.085 líneas, 8 vistas) sin tocar el motor de ingesta ni la taxonomía.

## Estado actual (auditado)
- Navegación: `st.radio` en sidebar (8 vistas). Dark mode con toggle manual y 6 funciones `get_*_color()` repartidas a mano.
- Tickets: tabla con paginación real (page number), búsqueda simple, botón «Ver» por fila (ButtonColumn) y callback resuelto por `session_state`.
- Reasignación de categorías: formulario manual + tabla de overrides.
- Sin CSS custom (0 `<style>`), sin iconografía consistente, sin gráficos interactivos unificados.
- Served at ejemplo.com/tickets/ (Authelia) — build local: `docker compose -f docker-compose.n8n.yml up -d --build`.

## Trampas conocidas (a respetar)
- `src/` se cuece en imagen: editar .py en host NO cambia el contenedor → siempre build.
- Hay 2 dashboards (`dashboard.py` NO se sirve, es el viejo).
- Timeout 10-min en fase 3 de ingesta (pendiente).
- 404 en `/tickets/` raíz: ¿preexistente?
- Streamlit AppTest no despacha callbacks de ButtonColumn (probado).

## Plan (por tandas, cada una con build + verificación)

### T1 — Tema y estructura visual (bajo riesgo, impacto alto)
1. **CSS custom centralizado** (un bloque `<style>` con variables CSS): tarjetas con hover suave, bordes redondeados, sombras, tipografía clara, estados de éxito/error. Reemplaza las 6 funciones color-manual por un sistema de tokens (bg/card/text/muted + accent por categoría).
2. **Navegación tipo option_menu con iconos** (ya hay `streamlit_option_menu` instalado en el docker): menú lateral vertical con iconos, sección resaltada.
3. **Métricas con delta**: en Panel, `st.metric` con deltas vs periodo previo (el cálculo ya existe: `total_prev`).
4. Verificable: build + pantallazo (`browser_vision` con annotate) + vistas restantes 200.

### T2 — Vista Tickets (la más usada, la que más gana)
1. **Filtros rápidos chip-style**: tienda/categoría/subcategoría como chips clicables encima de la tabla (además de los select).
2. **Búsqueda que matchee también productos** (ya busca en items) → mostrar nº de resultados y «limpiar filtros».
3. **Detalle de ticket en `st.dialog` modal** (Streamlit ≥1.28) en vez de desplegable: items con mini-tabla, importes formateados, botón «ver en vista completa».
4. **Paginación por botones** («‹ Anterior / Siguiente / ir a página N») con estado, en vez de number_input desnudo.
5. **Acciones rápidas por fila**: botón «Reasignar» junto a «Ver» que abre dialog pre-filtro de ese ticket en la vista Categorías.
6. Verificable: mismo flujo del usuario (buscar, filtrar, ver detalle, volver) + AppTest callbacks de botón.

### T3 — Paneles y gráficos (impacto medio)
1. **Trend sparkline en KPIs** (plotly miniatura de gasto diario dentro de las cards).
2. **Top-movers**: sección «categorías que más han cambiado» (diff vs periodo previo).
3. **Color por categoría consistente** en todos los gráficos (single palette map `cat_display` → color).
4. **Responsive**: media-queries de CSS para móvil (el usuario lo consulta desde el móvil a veces), sidebar colapsable por defecto en pantallas <768px.

### T4 — Ingesta y Categorías (operación)
1. Ingesta: barra de progreso real (polling /status), log en streaming, última ejecución visible sin expandir.
2. Categorías: chips con contador de items reasignables + undo del último reasignado.
3. Export CSV de la vista activa disponible en TODAS las vistas (hoy solo en algumas).

## Fuera de alcance (no tocar)
- Motor de ingesta, taxonomy.py, OCR, base de datos, Authelia/proxy.
- Cualquier cambio que requiera re-siembra de embeddings o re-tocar reglas.

## Estimación
- T1: ~1,5 h · T2: ~2 h · T3: ~1,5 h · T4: ~1 h
- Cada tanda: build (~2 min), recreate, verificación con sonda real + pantallazo, y nota en `docs/ARQUITECTURA_EN_SERVICIO.md`.

## Entrega
Se puede ejecutar por tandas (la T1 y T2 son las que el usuario más valora: estética + flujo de Tickets).
Cada tanda es independiente y reversible (git commit antes de cada una).