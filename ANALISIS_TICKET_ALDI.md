# Análisis del ticket de Aldi (id nº 1007) y prompt OCR corregido

Fecha: 17-sep-2026. Ticket: `ticket_20260917_e229466327a0_gmail_images20260917.png`
(4000×1848, **fotografiado girado 90°**), total **54,24 €**.

## Qué interpretó mal el LLM (30 líneas leídas)

| Error | Detalle |
|---|---|
| **2 líneas inventadas** | `"2,332 €/0.85 kg/KE"` y `"X 0.66 €"` se emitieron como **artículos** con importes 2,98 € y 2,64 €. Son desgloses de otros artículos. |
| **Importes desplazados una fila** | `PISTOLA QUITAMANCHAS` recibió 1,75 (era del ZUMO), `GALLADIVERS`/`SUSHI` desalineados. |
| **Cantidades duplicadas** | `SUSHI` cant=3 (importe 1,25), `FLAN` cant=1. |
| **Suma descuadrada** | Suma de importes **75,09 €** frente a un total impreso de **54,24 €** → *diferencia +20,85 €*. |
| **Descripción corrupta** | `TORTILLA PATATA CALABA` → producto_norm "Patata"; `MUESLI CHOCO / FRUTA` → "Sepia". |

## La estructura real del ticket (verificada contra el papel)

Transcripción reconstruida y **validada aritméticamente**: la suma de las 28 líneas da
**54,24 €**, exactamente el "A PAGAR".

```
CALDO PARA PAELLA            1,79 € 3
CALDO DE VERDURAS 1 L        0,89 € 3
    2 x 1,59 €               3,18 € 3   <- detalle de ECO TOMATE FRITO (VA ENCIMA)
ECO TOMATE FRITO
CALDO DE POLLO               0,69 € 3
PISTOLA QUITAMANCHAS         2,99 € 4
ZUMO MANDARINA 1L            1,75 € 3
    2,332 kg x 0,85 €/kg     1,98 € 2   <- venta al peso
MELON PIEL SAPO CONVEN       2,09 € 3
SALMOREJO 1L
    2 x 1,65 €               3,30 € 3   <- detalle de FLAN DE QUESO/CAFE
FLAN DE QUESO/CAFÉ
    2 x 0,66 €               1,32 € 2   <- detalle de YOGUR CON GRAGEAS
YOGUR CON GRAGEAS CHOC
...
Descuento posición 30%      -1,80 €
...
A PAGAR                     54,24 €
```

### Las dos reglas que faltaban

**1. El dígito de IVA (2, 3 o 4).** Va a la derecha del importe y **no es parte de él**:
es el tipo (2 = 4 %, 3 = 10 %, 4 = 21 %). Se comprobó contra el bloque IVA del propio
ticket, que cuadra exacto:

| Dígito | Tipo | Bruto | Base | IVA |
|---|---|---|---|---|
| 2 | 4 % | 9,74 | **9,37** | 0,37 |
| 3 | 10 % | 40,32 | 36,65 | 3,67 |
| 4 | 21 % | 5,98 | **4,94** | 1,04 |

El ticket imprime NETO 9,37 / 35,02 / 4,94 y BRUTO 9,74 / 38,52 / 5,98. Los dígitos 2 y 4
cuadran exactos con los tipos 4 % y 21 %, lo que **confirma la equivalencia**.

**2. La línea "2 x 1,65 €".** Va **indentada e INMEDIATAMENTE ENCIMA** de la descripción,
no debajo (respondiendo a tu duda). Es el desglose cantidad × precio unitario de ese
artículo. Se identifica sin ambigüedad porque el importe del artículo **coincide
exactamente**: 2 × 1,65 = 3,30. Los tres casos del ticket cuadran todos.

Las líneas de peso (`2,332 kg x 0,85 €/kg`) siguen el mismo patrón pero con cantidad 1.

## Prompt corregido

Reescrito `SYSTEM_PROMPT` en `src/ocr_llm.py` con 8 reglas de lectura: enderezar la
imagen, asignar el importe a la fila correcta, **ignorar el dígito de IVA**, tratar las
líneas `n x precio` como desglose (con su regla de posición), descuentos en negativo,
cantidad entera, transcripción literal y no repetir filas. Cierra con una
**verificación obligatoria**: sumar y comparar con el total impreso antes de responder.

### Resultado medido (mismo modelo, `glm-5.3-flash`)

| | Antes | Después |
|---|---|---|
| Líneas | 30 (2 inventadas) | **28** (todas reales) |
| Suma | 75,09 € | **54,24 €** |
| vs total impreso | **+20,85 €** | **0,00 €** |
| Filas de desglose como artículo | 2 | **0** |
| `cant × pu = importe` | falla | **28/28 OK** |

Verificado también **sin regresión**: un ticket de Mercadona cuadra igual (8,22 € = 8,22 €).

## Hallazgo aparte: el límite de tokens es insuficiente

Probando otro ticket (`Scan_...122747.jpg`, 4 artículos) el LLM devolvió
`finish_reason: length` con **4000 tokens** y el JSON quedó **truncado** → sin JSON válido.
Con 16000 tokens terminó (`stop`) y cuadró (84,36 = 84,36), consumiendo **5693 tokens**.

`MAX_TOKENS` está en 4000. Un ticket de moda con 4 artículos ya necesita 5693, porque el
modelo **razona** antes de responder y ese razonamiento cuenta. **Recomendación: subir
`OCR_MAX_TOKENS` a 8000-16000.** No lo cambié por no tocar `.env` de producción sin
permiso.

## Pendiente

- **Reprocesar el ticket 1007** para corregir sus datos en la BD (sigue con los 30
  items erróneos).
- Decidir sobre `OCR_MAX_TOKENS`.
- Reconstruir la imagen de `tickets-ingest-api`: el prompt nuevo está en el fichero del
  host pero el contenedor ejecuta el código **horneado en la imagen**.
