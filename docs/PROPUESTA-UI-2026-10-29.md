# PROPUESTA — Utilidad y experiencia del dashboard de Tickets

29-oct-2026 · Auditoría hecha sobre el código en servicio (`src/dashboard_streamlit.py`,
1.119 líneas, 8 vistas, Streamlit 1.66.1) y sobre capturas reales de
`http://localhost:8050/tickets/`. **Nada de esto está implementado**: es una
propuesta con alternativas y una recomendación por bloque.

---

## 1. Diagnóstico (con evidencia)

### 1.1 Navegación y estructura

| # | Problema | Evidencia |
|---|---|---|
| N1 | La navegación es **lo último** de la barra lateral: primero el toggle de tema, luego 4 filtros y 4 bloques «Datos», y al final el `st.radio` de 8 vistas. Hay que hacer scroll para cambiar de vista. | `render_sidebar()` L69-116 y el `st.radio` en L1090-1099 |
| N2 | Filtros y navegación viven en una **sidebar colapsable**: al plegarla (chevron « arriba a la izquierda) desaparece también la navegación y no queda ninguna referencia de dónde estás. | captura: chevron visible, sidebar de 260 px |
| N3 | La barra superior **no es del producto**: `Deploy` + menú ⋮ (Rerun, Settings, Print, Record, About). Es el chrome por defecto de Streamlit; en un dashboard personal solo estorba y abre ajustes que nadie debe tocar. | esquina superior derecha de la captura |
| N4 | El **primer control** del panel es «🌙 Dark Mode», una preferencia, no una herramienta de trabajo. Streamlit ya tiene tema de instancia. | L74-78 |
| N5 | La vista por defecto es **Panel**, pero la que más se usa es **Tickets**. | decisión anterior del usuario, pendiente de build |
| N6 | **Sin estado en la URL**: no se puede enlazar «Tickets de octubre del Lidl», ni usar Atrás, ni recuperar la vista al recargar. | sólo `st.session_state` |
| N7 | Los KPIs muestran «+0.0% vs anterior» porque el rango por defecto es **todo el histórico** y el periodo anterior queda vacío. El número es correcto y a la vez inútil (y parece roto). | L140-170: `prev_start = sd - (ed - sd)` |
| N8 | Duplicidad: la sidebar repite 4 cifras (Tickets, Items, Productos, Descuadres) que ya están en el Panel como KPIs. | L111-119 / L161-168 |
| N9 | El selector de **subcategoría aparece y desaparece** al elegir categoría: salta el layout y se pierden los filtros de debajo. | L102-106 |

### 1.2 Gráficos

| # | Problema | Evidencia |
|---|---|---|
| G1 | «Gasto mensual» son **~40 barras (2023-06→2026-10) con el eje X etiquetado solo por año**. No se puede leer un mes concreto y una serie temporal no se representa con barras de color. | L216-232 |
| G2 | Se usa **escala de color por el propio valor** (degradado azul/verde) en barras: codifica dos veces lo mismo y añade una barra de color al lado. | `color="total"`, `color="importe"` |
| G3 | **Sin etiquetas de valor**: para saber cuánto es «Bebidas» hay que pasar el ratón. | L234-247 |
| G4 | **Treemap** de categoría→subcategoría: texto solapado, subcategorías ilegibles, colores aleatorios sin significado y sin total ni porcentajes. | L249-256 |
| G5 | **Modebar de Plotly en cada gráfico** (cámara, zoom, ±, autoscale, lazo, fullscreen): 9 iconos permanentes por figura que no se usan a diario. | `st.plotly_chart` sin `config` |
| G6 | En **Producto**, la serie de `precio_unit` **mezcla €/kg y €/unidad** en el mismo eje cuando el producto aparece en ambos formatos (peso variable vs unidad). Los precios no son comparables y la «variación %» tampoco. | L503-516 |
| G7 | En **Temporal**, el calendario agrupa por **semana ISO dentro del año**: la semana 1 de dos años distintos cae en la misma columna. | L580-610 |
| G8 | Los 4 KPIs y los gráficos no se leen como una historia: cada bloque responde a una pregunta distinta sin jerarquía (¿cuánto? ¿en qué? ¿cuándo? ¿ha subido?). | vista completa |

### 1.3 Utilidad (lo que hoy no se puede responder)

- ¿Cuánto llevo **este mes** y cuánto me queda respecto a mi media?
- ¿Qué **productos han subido** más desde la última vez que los compré? (top movers)
- ¿En qué tienda me sale **más caro el mismo producto**? (requiere €/kg comparable)
- ¿Cuánto gasto **por semana** y en qué días compro?
- ¿Qué categorías **crecen** frente a las de hace tres meses?
- ¿Hay tickets **duplicados o sospechosos** (aparte de los descuadres de OCR)?

---

## 2. Principios para esta tanda

1. **La navegación no se esconde.** Siempre visible, en el mismo sitio, con la vista
   actual marcada. Nada de menús que aparecen al pulsar.
2. **Un gráfico, una pregunta.** Si un gráfico necesita explicación, está mal elegido.
   Máximo dos gráficos por vista; el resto, tabla.
3. **Los números se leen sin interactuar.** Etiquetas de valor y unidades visibles.
4. **El estado vive en la URL**, para poder enlazar y volver atrás.
5. **No depender de componentes custom**: detrás del proxy HTTPS ya nos rompieron
   `streamlit-option-menu` (no renderiza) y `st.dataframe(on_select)` (no dispara).

---

## 3. Navegación: tres alternativas

| | Cómo | Ventajas | Inconvenientes |
|---|---|---|---|
| **A. Cabecera fija con píldoras** (`st.segmented_control`) + filtros en una fila sticky, sin sidebar | Fila superior: periodo · tienda · categoría · búsqueda. Debajo, píldoras de vista. Debajo, caption `282 tickets · 7.328 líneas · 5 descuadres`. | Siempre visible, cero scroll, **solo calcula la vista elegida** (rendimiento igual que hoy), componentes nativos, sin dependencias nuevas | 8 píldoras no caben en móvil → agrupar en 5 y dejar operación en un desplegable |
| **B. Sidebar reorganizada** (nav arriba, filtros debajo, sin plegar) | Mismo `st.radio`, movido al principio; «Datos» pasa a caption al pie | Cambio mínimo, riesgo casi nulo | Sigue robando 260 px y sigue siendo un cajón en móvil; no resuelve «se oculta» |
| **C. `st.navigation` multipágina** | Una `st.Page` por vista | URLs reales por vista (`/tickets/Tickets`), Atrás del navegador gratis | Reestructura `main()`, hay que verificar rutas bajo `baseUrlPath` + Authelia; más trabajo y más riesgo de romper el proxy |

**Recomendación: A**, con la puerta abierta a C más adelante (A no lo impide).
`st.tabs` queda descartado como navegación principal: ejecuta el cuerpo de **todas**
las pestañas en cada rerun, es decir, las 8 vistas calculando a la vez.

Complementos de la opción A, baratos y de impacto alto:

- **Quitar el chrome de Streamlit**: `toolbarMode="minimal"` en `.streamlit/config.toml`
  y ocultar `Deploy`/⋮ por CSS. Se acaban los «elementos distintos» de la derecha.
- **Periodo rápido** en la cabecera: `Este mes · Mes anterior · Últimos 3 meses · Año · Todo`,
  y que el delta de los KPIs compare contra el periodo equivalente **solo si existe**.
- **Estado en URL** (`st.query_params`): vista, rango, tienda y categoría.
- **Tema**: fuera el toggle de la sidebar; se fija en `config.toml` (o con `st.context.theme`
  si se quiere respetar el del sistema).

---

## 4. Gráficos: alternativas y decisiones

| | Motor | Veredicto |
|---|---|---|
| **A. Plotly rediseñado** | ya instalado (7.1.0) y **en uso**: el usuario ve los gráficos, luego renderiza bajo el proxy | **Recomendado**: sin modebar (`config={"displayModeBar": False}`), etiquetas de valor, orden por magnitud, paleta fija por categoría, anotaciones (media, máximo), líneas para series temporales |
| B. Altair / Vega-Lite | instalado (6.3.0), declarativo, sin WebGL, muy buena tipografía y control | Segunda opción si Plotly falla en la URL pública; reescribir todas las figuras es trabajo aparte |
| C. Gráficos nativos (`st.line_chart`, `st.bar_chart`) | cero dependencias | No resuelve nada: no admite etiquetas, orden, colores ni anotaciones. Es el aspecto que ya tenemos |
| D. ECharts (`streamlit-echarts`) | mucha potencia | Descartado: componente custom, justo la familia que ya falló tras el proxy |

### Rediseño por vista (antes → después)

| Vista | Hoy | Propuesta |
|---|---|---|
| **Panel** | 4 KPIs + barras mensuales + top-5 + treemap | 3 KPIs con periodo explícito («octubre 2026 · 4 compras · 312,45 € · 78,11 €/compra») + **línea de gasto semanal con media móvil** (no barras) + **barras horizontales con etiqueta de € y % del total**, sin degradado ni colorbar. El treemap se sustituye por una tabla de categoría→subcategoría con barras en línea (se lee mejor y suma) |
| **Temporal** | barras + media móvil, año vs año, calendario por semana ISO | Línea mensual con **máximo y media como líneas de referencia**; comparativa año vs año como **small multiples** (una mini-línea por año, mismo eje); calendario como **mapa año × mes con intensidad** (más legible que semana ISO) o directamente «gasto por día de la semana» |
| **Producto** | 5 KPIs + serie de precio unitario + historial | Separar **€/unidad y €/kg** (dos series o filtro de formato); añadir **banda de precio habitual (p25-p75)** y marcar los puntos fuera de banda; tabla con la variación respecto a la compra anterior |
| **Establecimiento** | barras de gasto + línea por cadena | Tabla ordenable con gasto, ticket medio, % del total y **€/kg medio**; una sola barra horizontal; **comparativa del mismo producto entre tiendas** (la pregunta que de verdad se hace uno) |
| **Categoría** | drill-down con tablas | Tabla con gasto, % del total, variación vs periodo anterior y **top-3 productos** de la subcategoría |
| **Tickets** | tabla + orden + búsqueda + «Ver» por fila | Se mantiene (funciona bien); añadir **chips de filtro activos**, contador de resultados y detalle en `st.dialog` en lugar de expander |
| **Categorías / Ingesta** | operación | Sin cambios de fondo: progreso real desde `/status` (ya existe `pending`) y última ejecución visible sin desplegar |

---

## 5. Plan por tandas (cada una independiente, con build y verificación)

- **T1 — Estructura y navegación** (medio día). Cabecera sticky con filtros + periodo rápido,
  navegación por píldoras, caption de conteos, `config.toml` sin toolbar, `st.query_params`.
  Fuera la sidebar. *Verificación*: capturas de las 8 vistas + que la vista activa y los
  filtros sobrevivan a un F5 + render correcto en la URL pública.
- **T2 — Tickets por defecto y su flujo** (3 h). Vista inicial = Tickets, chips de filtros,
  contador de resultados, detalle en `st.dialog`, paginación con botones.
- **T3 — Gráficos del Panel y Temporal** (medio día). Línea semanal con media, barras con
  etiquetas y porcentajes, fuera treemap y modebar, paleta fija por categoría, referencia
  de media/máximo. *Verificación*: comparar cifras contra SQL directo (no fiarse del gráfico).
- **T4 — Producto y Establecimiento** (medio día). Separar €/kg de €/unidad, banda de precio
  habitual, comparativa entre tiendas del mismo producto.
- **T5 — Utilidad nueva** (opcional). Top movers de precio, presupuesto mensual con desviación,
  aviso de duplicados.

Cada tanda: `docker compose -f docker-compose.n8n.yml up -d --build`, captura, y confirmar
que las 8 vistas responden 200. Nada de tocar motor, taxonomía, BD ni proxy.

## 6. Riesgos y fuera de alcance

- **Plotly bajo el proxy**: hoy se ve (el dashboard en producción es Plotly), pero está
  documentado que en algún momento salió en blanco. Primera comprobación de T3: abrir la
  URL pública y confirmar; si falla, se cambia a Altair sin tocar la estructura.
- **€/kg vs €/unidad**: la BD no guarda la unidad; hay que inferirla del texto
  (`(1,220 kg x 1,00 €/kg)`). Es heurística, no verdad garantizada: se marcará como tal.
- **Fuera de alcance**: ingesta, `taxonomy.py`, `ocr_llm.py`, esquema de la BD, nginx/Authelia,
  el motor de cálculo de cuadres.
- **No se toca** el aspecto por el aspecto: si una tanda solo cambia colores, se devuelve.

## 7. Cómo sabremos que ha funcionado

1. Cambiar de vista no requiere scroll ni abrir nada.
2. Los importes se leen sin pasar el ratón.
3. Cada vista responde a una pregunta en la primera pantalla.
4. Se puede enlazar «esto es lo que veo» por URL.
5. Nada de iconos de Plotly ni de Streamlit que no sean del producto.
