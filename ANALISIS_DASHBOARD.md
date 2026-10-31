# Análisis y Propuesta de Rediseño del Dashboard de Tickets Mercadona

## 1. Estado Actual

### 1.1 Datos disponibles
| Métrica | Valor |
|---|---|
| Tickets | 236 |
| Line items | 6.445 |
| Productos únicos (descripción) | 1.320 |
| Categorías | 18 (14% en "Otros") |
| Tiendas | 12 direcciones (2 son la misma) |
| Rango temporal | Sep 2023 → Jun 2026 |
| Catálogo Mercadona | 4.379 productos (0 matches) |
| Items/ticket (media) | 27,4 |
| Método de pago | 100% Tarjeta bancaria |

### 1.2 Dashboard actual (dashboard.py — 1.129 líneas)
6 pestañas con información solapada y sin flujo claro:

1. **Resumen General** — 3 gráficos apilados verticalmente (gasto temporal, gasto por categoría, gasto mensual). Sin contexto, sin interactividad entre ellos.
2. **Evolución de Precios** — Requiere seleccionar un producto en el filtro superior (confuso). Si no hay producto, muestra "top 15 variaciones" que mezcla packs con unidades.
3. **Hábitos de Compra** — Frecuencia semanal, pie de categorías y treemap. El pie y el treemap muestran la misma información.
4. **Ranking de Productos** — Tabla con 20 productos. Filtrada por los filtros globales pero sin poder ordenar por categoría dentro de la vista.
5. **Historial de Tickets** — Tabla con enlace a PDF. El detalle del ticket aparece debajo pero requiere click en fila concreta.
6. **Ingesta** y **Configuración** — Funcionan, no se tocan.

### 1.3 Problemas detectados

**UX/Diseño:**
- No hay drill-down: no se puede ir de lo general a lo concreto
- Los filtros globales (producto, categoría) afectan a todas las pestañas por igual, sin contexto
- Las pestañas no tienen narrativa: el usuario salta entre vistas sin sentido
- No existe vista por establecimiento
- No hay comparativas temporales (mes vs mes anterior, año vs año)
- Los KPIs son básicos (4 cajas) sin tendencia ni contexto

**Calidad de datos:**
- "C/ DE LA HULLA 21" y "C/ DE LA HULLA, 21" son la misma tienda (216 vs 80 tickets)
- 877 items en "Otros" (14% del total) — normalización incompleta
- Catálogo con 4.379 productos pero 0 matches realizados
- "AVDA. DE LOS ROSALES 26" y "AVDA. DE LOS ROSALES, 26" también duplicados
- Algunos productos normalizados incorrectamente (ej: "NARANJA S/AZ P6" → "NARANJA S/AZ P6" en Otros)

**Técnico:**
- Monolito de 1.129 líneas en un solo archivo
- Datos cargados al arranque, no on-demand
- Sin cache de agregaciones

---

## 2. Propuesta de Rediseño

### 2.1 Filosofía: Drill-down progresivo

El dashboard debe seguir un patrón **embudo**: de lo más general a lo más concreto, donde cada nivel permite "bajar" al siguiente clicando.

```
Vista Global → Vista por Dimensión → Vista de Detalle → Ticket individual
```

### 2.2 Arquitectura de vistas propuestas

#### Vista 0: Panel de Control (landing)
**KPIs con tendencia:**
- Gasto total del periodo + % vs periodo anterior
- Nº de compras + % vs periodo anterior
- Ticket medio + % vs periodo anterior
- Gasto medio mensual
- Productos únicos comprados
- Días entre compras (frecuencia media)

**Mini-gráficos de tendencia:**
- Línea de gasto mensual (últimos 12 meses) con comparativa año anterior
- Barras de gasto por categoría (top 5) — clicable → va a Vista por Categoría

#### Vista 1: Por Establecimiento
- Mapa de barras: gasto por tienda
- Tabla resumen: tienda, nº tickets, ticket medio, gasto total, % del total
- Clicable → filtra todo el dashboard por esa tienda

#### Vista 2: Por Categoría de Gasto
- Treemap jerárquico: Categoría → Producto → Gasto
- Barras horizontales: gasto por categoría con evolución mensual
- Clicable en categoría → lista de productos de esa categoría con stats
- Clicable en producto → Vista de detalle del producto

#### Vista 3: Por Producto (detalle de producto)
- Evolución de precio unitario en el tiempo
- Stats: precio min/medio/max, nº veces comprado, gasto total, variación %
- Tabla de compras: fecha, tienda, cantidad, precio unit, importe
- Comparativa: precio actual vs precio histórico

#### Vista 4: Evolución Temporal
- Gasto mensual con media móvil (3 meses)
- Heatmap calendario: días de compra (intensidad = gasto)
- Comparativa año vs año (líneas solapadas por mes)
- Gasto acumulado anual

#### Vista 5: Historial de Tickets
- Tabla de tickets ordenada por fecha descendente
- Filtros: fecha, tienda, rango de importe
- Clic en ticket → modal con detalle completo de items + PDF

#### Vista 6: Ingesta + Configuración (sin cambios)

### 2.3 Filtros globales (barra superior persistente)
- Rango de fechas (DatePicker)
- Tienda (dropdown — con tiendas normalizadas)
- Categoría (botones, no dropdown — más visual)
- Periodo de comparación (mes anterior, año anterior, sin comparativa)

Los filtros afectan a todas las vistas excepto Ingesta/Configuración.
Cada vista muestra los KPIs recalculados según filtros activos.

### 2.4 Correcciones de datos previas

Antes de rediseñar el dashboard, hay que arreglar:

1. **Normalizar tiendas** — limpiar direcciones duplicadas:
   - "C/ DE LA HULLA 21" = "C/ DE LA HULLA, 21" → "C/ De La Hulla, 21"
   - "AVDA. DE LOS ROSALES 26" = "AVDA. DE LOS ROSALES, 26" → "Avda. De Los Rosales, 26"
   
2. **Reducir "Otros"** — revisar los 877 items y ampliar reglas de normalización:
   - Top 20 productos en Otros representan 227 items (26% del problema)
   - Objetivo: bajar "Otros" a <5% (<320 items)

3. **Catálogo** — decidir si se usa o se elimina. Con 0 matches no aporta valor.

---

## 3. Planificación

### Fase 1: Limpieza de datos (1-2h)
- [ ] Normalizar direcciones de tiendas en BD
- [ ] Ampliar reglas de normalización para reducir "Otros"
- [ ] Ejecutar `normalize_all_in_db()` y verificar
- [ ] Eliminar o mantener tabla catalog_products (decidir)

### Fase 2: Estructura del nuevo dashboard (2-3h)
- [ ] Refactorizar dashboard.py en módulos:
  - `data.py` — carga y cache de datos
  - `views/global.py` — Vista 0
  - `views/establecimiento.py` — Vista 1
  - `views/categoria.py` — Vista 2
  - `views/producto.py` — Vista 3
  - `views/temporal.py` — Vista 4
  - `views/tickets.py` — Vista 5
  - `views/ingesta.py` — Vista 6 (sin cambios)
  - `app.py` — orquestador con layout y callbacks
- [ ] Implementar barra de filtros global persistente
- [ ] Implementar navegación drill-down entre vistas

### Fase 3: Implementar vistas (4-5h)
- [ ] Vista 0: KPIs con tendencia + mini-gráficos
- [ ] Vista 1: Por establecimiento
- [ ] Vista 2: Por categoría (treemap + barras)
- [ ] Vista 3: Por producto (evolución de precio)
- [ ] Vista 4: Evolución temporal (heatmap calendario, comparativas)
- [ ] Vista 5: Historial de tickets (mejorado)

### Fase 4: Pulido y testing (1-2h)
- [ ] Revisar consistencia de colores y estilos
- [ ] Verificar drill-down en todas las vistas
- [ ] Comprobar rendimiento con 236 tickets
- [ ] Probar en móvil (Dash responsive)

**Total estimado: 8-12 horas**

---

## 4. Decisiones pendientes

1. **¿Usar catálogo Mercadona?** Con 0 matches, la tabla catalog_products no aporta nada ahora. ¿Quieres que intente hacer matching o la eliminamos?

2. **¿Vistas separadas o tabs?** Las vistas pueden ser pestañas (como ahora) o una sola página con scroll y drill-down. Recomiendo pestañas pero con drill-down dentro de cada una.

3. **¿Comparativa temporal?** ¿Quieres ver comparativas mes vs mes anterior y año vs año anterior en los KPIs?

4. **¿Heatmap calendario?** Es visualmente atractivo pero requiere librería adicional (calplot o similar). ¿Lo incluyo?

5. **¿Dark mode?** El dashboard actual usa colores claros. ¿Prefieres dark mode?

6. **¿Mantener la tecnología Dash/Plotly?** Funciona y está desplegado. Alternativa sería Streamlit (más rápido de desarrollar, menos control interactivo).