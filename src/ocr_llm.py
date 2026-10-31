"""Extracción de datos de tickets de compra desde imágenes usando LLM de visión.

Soporta dos modos:
- **Cloud**: glm-5.3-flash via Ollama Cloud (API OpenAI-compatible, reasoning_effort=none)
- **Local**: minicpm-v4.5:8b via Ollama local (API /api/chat, sin thinking, num_predict alto)

El modo se selecciona con la variable de entorno OCR_MODE=local (por defecto: cloud).
En modo local, el modelo se ejecuta en un contenedor Docker Ollama CPU-only.
"""
import os
import re
import json
import base64
import logging
from pathlib import Path
from typing import Optional

import httpx

from src.parse_ticket import Ticket, LineItem

logger = logging.getLogger(__name__)

# ─── Configuración del cliente LLM ───────────────────────────────────────────

OCR_MODE = os.environ.get("OCR_MODE", "cloud")  # "cloud" o "local"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
TICKET_OCR_MODEL = os.environ.get("TICKET_OCR_MODEL", "glm-5.3-flash")

# En modo local, usar el endpoint /api/chat nativo de Ollama (no OpenAI-compat)
LOCAL_OLLAMA_URL = os.environ.get("LOCAL_OLLAMA_URL", "http://localhost:11434")
LOCAL_OCR_MODEL = os.environ.get("LOCAL_OCR_MODEL", "minicpm-v4.5:8b")

# Reducción de la imagen antes de enviarla al modelo. 0 desactiva la reducción.
# Se recorta por píxeles conservando el ancho (mínimo OCR_MIN_IMAGE_WIDTH) para no
# perder legibilidad en tickets estrechos; el JPEG a 88 mantiene el texto limpio.
OCR_MAX_IMAGE_PIXELS = int(os.environ.get("OCR_MAX_IMAGE_PIXELS", "2500000"))
OCR_MIN_IMAGE_WIDTH = int(os.environ.get("OCR_MIN_IMAGE_WIDTH", "900"))
OCR_JPEG_QUALITY = int(os.environ.get("OCR_JPEG_QUALITY", "88"))

# Cloud: 120s es suficiente con reasoning_effort=none
# Local: minicpm-v4.5:8b en CPU tarda hasta 5 min por ticket con 44 items
API_TIMEOUT = int(os.environ.get("OCR_TIMEOUT", "600" if OCR_MODE == "local" else "120"))

# Cloud: 2000 tokens con reasoning_effort=none es suficiente
# Local: minicpm-v4.5:8b necesita ~1700 tokens para 44 items + JSON
MAX_TOKENS = int(os.environ.get("OCR_MAX_TOKENS", "4000" if OCR_MODE == "local" else "2000"))

# Contexto para el modelo local (mayor = más espacio para imagen + output)
LOCAL_NUM_CTX = int(os.environ.get("OCR_NUM_CTX", "8192"))

SYSTEM_PROMPT = (
    'Eres un extractor de tickets de compra español. Analiza la imagen del ticket '
    'y devuelve ÚNICAMENTE un JSON válido (sin markdown, sin explicaciones) con este '
    'esquema: {"comercio": "string (mercadona|lidl|aldi|alcampo|carrefour|dia|eroski|el jamon|consum|mas|otros)", '
    '"fecha": "dd/mm/yyyy", "hora": "HH:MM", "direccion": "string", "num_ticket": "string", '
    '"items": [{"cantidad": int, "descripcion": "string", "precio_unit": float, "importe": float}], '
    '"total": float, "metodo_pago": "string"}. '
    'Identifica el comercio por el nombre que aparece en el ticket (cabecera/logotipo). '
    'Si el comercio no está en la lista, usa "otros".\n'
    '\n'
    'REGLAS DE LECTURA (obligatorias):\n'
    '1. La imagen puede estar girada, torcida o en perspectiva: enderézala mentalmente '
    'antes de leer. No te inventes filas que no puedas leer.\n'
    '2. Cada artículo ocupa UNA fila: la descripción a la izquierda y su importe a la '
    'derecha. El importe pertenece SIEMPRE a la descripción de SU MISMA fila. No lo '
    'desplaces a la fila anterior ni a la siguiente.\n'
    '3. A la derecha del importe hay un dígito suelto (2, 3 o 4): es el tipo de IVA '
    '(2 = 4 %, 3 = 10 %, 4 = 21 %). NO es parte del importe, ni una cantidad, ni un '
    'precio. IGNÓRALO por completo.\n'
    '4. NO son artículos las líneas de detalle indentadas que empiezan por un número y '
    'llevan "x", por ejemplo "2 x 1,59 €" o "2,332 kg x 0,85 €/kg". Son el desglose de '
    'cantidad y precio unitario de un artículo. En Aldi esa línea aparece INDENTADA e '
    'INMEDIATAMENTE ENCIMA de la descripción del artículo al que pertenece (no debajo): '
    '"2 x 1,59 €" seguido de "ECO TOMATE FRITO 3,18" describe a ECO TOMATE FRITO. Usa la '
    'coincidencia aritmética para confirmarlo: el importe del artículo ha de ser '
    'exactamente cantidad x precio (2 x 1,59 = 3,18). No emitas esa línea como artículo '
    'propio, y no la asocies al artículo de la fila anterior. Si el artículo se vende al '
    'peso ("2,332 kg x 0,85 €/kg"), pon cantidad 1 y el importe impreso.\n'
    '5. Tampoco son artículos las líneas de descuento ("Descuento...", "DTO", "AHORRO"): '
    'emítelas como un item más con el importe en NEGATIVO, tal como aparece impreso.\n'
    '6. "cantidad" es un número entero de unidades. Si un artículo no lleva línea de '
    'detalle, su cantidad es 1 (no la dupliques ni la multipliques). Se cumple siempre: '
    'cantidad x precio_unit = importe.\n'
    '7. Transcribe las descripciones LITERALMENTE como están impresas, aunque estén '
    'abreviadas o cortadas ("MELON PIEL SAPO CONVEN", "PISTOLA QUITAMANCHAS").\n'
    '8. Cada fila del ticket aparece UNA sola vez en el JSON. No repitas artículos.\n'
    '\n'
    'VERIFICACIÓN OBLIGATORIA antes de responder: suma los importes de TODOS los items '
    '(los descuentos restan) y comprueba que coincide con el total impreso del ticket '
    '("A PAGAR", "TOTAL A PAGAR", "TOTAL"). Si no coincide, has asignado algún importe a '
    'la fila equivocada: vuelve a leer el ticket corrigiendo la alineación. NO ajustes '
    'el total para que cuadre ni omitas filas; corrige la asignación de importes.'
)

# Extensión del esquema para múltiples imágenes (merge de items)
SYSTEM_PROMPT_MULTI = (
    SYSTEM_PROMPT +
    ' Se te enviarán múltiples imágenes que son páginas consecutivas del mismo ticket. '
    'Haz merge de todos los items en una sola lista, manteniendo el orden. Devuelve un único JSON.'
)


# ─── Utilidades internas ─────────────────────────────────────────────────────

def _encode_image_b64(image_path: str) -> tuple[str, str]:
    """Lee una imagen del path y la codifica en base64. Devuelve (b64_string, mime_type).

    Antes de codificar se reduce el tamaño si la imagen es muy grande: el coste
    del OCR es casi todo *prefill* de la imagen (medido: ~1 min por llamada con
    fotos de 4000 px). Se recorta por número de píxeles y **conservando el ancho**
    —nunca por debajo de `OCR_MIN_IMAGE_WIDTH`—, porque reducir el lado largo de
    un ticket estrecho se come el texto.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Imagen no encontrada: {image_path}")

    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    mime_type = mime_map.get(ext, "application/octet-stream")

    with open(image_path, "rb") as f:
        raw = f.read()

    if OCR_MAX_IMAGE_PIXELS > 0:
        try:
            return _encode_image_scaled(path, raw)
        except Exception as e:  # noqa: BLE001 - si Pillow no puede, se envía tal cual
            logger.warning("No se pudo reducir %s (%s); se envía sin tocar", path.name, e)

    return base64.b64encode(raw).decode("utf-8"), mime_type


def _encode_image_scaled(path: Path, raw: bytes) -> tuple[str, str]:
    """Reduce la imagen a `OCR_MAX_IMAGE_PIXELS` conservando el ancho. Devuelve (b64, mime)."""
    import io

    from PIL import Image

    with Image.open(path) as im:
        ancho, alto = im.size
        if ancho * alto <= OCR_MAX_IMAGE_PIXELS:
            return base64.b64encode(raw).decode("utf-8"), "image/jpeg"

        escala = (OCR_MAX_IMAGE_PIXELS / (ancho * alto)) ** 0.5
        nuevo_ancho = max(1, round(ancho * escala))
        if nuevo_ancho < OCR_MIN_IMAGE_WIDTH:
            nuevo_ancho = min(ancho, OCR_MIN_IMAGE_WIDTH)
        nuevo_alto = max(1, round(alto * nuevo_ancho / ancho))

        reducida = im.convert("RGB").resize((nuevo_ancho, nuevo_alto), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        reducida.save(buf, format="JPEG", quality=OCR_JPEG_QUALITY, optimize=True)

    datos = buf.getvalue()
    logger.info(
        "Imagen reducida %s: %dx%d (%.1f MB) -> %dx%d (%.0f KB)",
        path.name, ancho, alto, len(raw) / 1e6, nuevo_ancho, nuevo_alto, len(datos) / 1e3,
    )
    return base64.b64encode(datos).decode("utf-8"), "image/jpeg"


def _extract_json_from_text(text: str) -> dict:
    """Intenta extraer JSON válido desde una respuesta del LLM.

    Estrategias:
    1. Parse directo del texto.
    2. Extraer de dentro de ```json ... ``` code blocks.
    3. Extraer de dentro de ``` ... ``` code blocks genéricos.
    4. Buscar la primera { ... } balanceada en el texto.
    """
    text = text.strip()

    # 1. Parse directo
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Markdown code block con etiqueta json
    m = re.search(r"```json\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Markdown code block genérico
    m = re.search(r"```\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 4. Buscar primer { ... } balanceado
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(
        f"No se pudo extraer JSON válido de la respuesta del LLM. "
        f"Primeros 200 chars: {text[:200]}"
    )


def _call_llm_cloud(messages: list[dict], is_multi: bool = False) -> str:
    """Llama a la API de Ollama Cloud (OpenAI-compatible) y devuelve el texto de respuesta."""
    if not OLLAMA_API_KEY:
        raise ValueError(
            "OLLAMA_API_KEY no está configurada. Establece la variable de entorno "
            "OLLAMA_API_KEY con tu API key de Ollama Cloud."
        )

    system_prompt = SYSTEM_PROMPT_MULTI if is_multi else SYSTEM_PROMPT
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    url = f"{OLLAMA_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OLLAMA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": TICKET_OCR_MODEL,
        "messages": full_messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
        "stream": False,
        "reasoning_effort": "none",
    }

    try:
        with httpx.Client(timeout=API_TIMEOUT) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.ConnectTimeout:
        raise ConnectionError(
            f"No se pudo conectar a Ollama Cloud en {url} (timeout {API_TIMEOUT}s)."
        )
    except httpx.ConnectError as e:
        raise ConnectionError(f"Error de conexión a Ollama Cloud ({url}): {e}.")
    except httpx.ReadTimeout:
        raise ConnectionError(
            f"Ollama Cloud tardó demasiado (timeout {API_TIMEOUT}s)."
        )

    if response.status_code == 401:
        raise ConnectionError("Autenticación fallida (HTTP 401). Verifica OLLAMA_API_KEY.")
    if response.status_code in (402, 403):
        raise ConnectionError(
            f"El modelo '{TICKET_OCR_MODEL}' no está incluido en el plan de tu cuenta de "
            f"Ollama Cloud (HTTP {response.status_code}). Opciones: usar un modelo del plan "
            f"gratuito, añadir créditos, o poner OCR_MODE=local para procesar sin cuenta. "
            f"Respuesta: {response.text[:300]}"
        )
    if response.status_code == 404:
        raise ConnectionError(
            f"Modelo '{TICKET_OCR_MODEL}' no encontrado en Ollama Cloud (HTTP 404)."
        )
    if response.status_code >= 400:
        body = response.text[:500]
        raise ConnectionError(f"Error HTTP {response.status_code} de Ollama Cloud: {body}")

    try:
        data = response.json()
    except json.JSONDecodeError:
        raise ConnectionError(f"Respuesta inesperada (no-JSON) de Ollama Cloud.")

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise ValueError(f"La respuesta del LLM no tiene la estructura esperada.")

    if not content or not content.strip():
        raise ValueError("El LLM devolvió una respuesta vacía.")

    return content


def _call_llm_local(messages: list[dict], is_multi: bool = False) -> str:
    """Llama a un modelo local de Ollama via /api/chat (sin thinking).

    Usa el endpoint nativo de Ollama (no OpenAI-compatible) porque minicpm-v4.5
    no tiene thinking y devuelve content directamente.

    Args:
        messages: Lista de mensajes en formato OpenAI (con content que puede incluir images).
        is_multi: Si True, usa el prompt de múltiples imágenes.

    Returns:
        El contenido de texto de la respuesta del modelo.
    """
    system_prompt = SYSTEM_PROMPT_MULTI if is_multi else SYSTEM_PROMPT
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # Convertir mensajes al formato /api/chat de Ollama
    # El formato /api/chat acepta images como array de base64 en el mensaje
    ollama_messages = []
    for msg in full_messages:
        if isinstance(msg.get("content"), list):
            # Mensaje multimodal (texto + imagen) en formato OpenAI
            text_parts = []
            images = []
            for part in msg["content"]:
                if part["type"] == "text":
                    text_parts.append(part["text"])
                elif part["type"] == "image_url":
                    # Extraer base64 de data:image/...;base64,XXXX
                    url = part["image_url"]["url"]
                    if url.startswith("data:"):
                        b64 = url.split(",", 1)[1] if "," in url else url
                        images.append(b64)
            ollama_msg = {"role": msg["role"], "content": " ".join(text_parts)}
            if images:
                ollama_msg["images"] = images
            ollama_messages.append(ollama_msg)
        else:
            ollama_messages.append(msg)

    url = f"{LOCAL_OLLAMA_URL.rstrip('/')}/api/chat"
    payload = {
        "model": LOCAL_OCR_MODEL,
        "messages": ollama_messages,
        "stream": False,
        "options": {
            "num_predict": MAX_TOKENS,
            "temperature": 0.1,
            "num_ctx": LOCAL_NUM_CTX,
        },
    }

    try:
        with httpx.Client(timeout=API_TIMEOUT) as client:
            response = client.post(url, json=payload)
    except httpx.ConnectError as e:
        raise ConnectionError(
            f"No se pudo conectar a Ollama local en {url}: {e}. "
            "Verifica que el contenedor Ollama esté en ejecución."
        )
    except httpx.ReadTimeout:
        raise ConnectionError(
            f"Ollama local tardó demasiado (timeout {API_TIMEOUT}s). "
            "El ticket puede ser muy largo para el modelo en CPU."
        )

    if response.status_code == 404:
        raise ConnectionError(
            f"Modelo '{LOCAL_OCR_MODEL}' no encontrado en Ollama local. "
            f"Ejecuta: ollama pull {LOCAL_OCR_MODEL}"
        )
    if response.status_code >= 400:
        body = response.text[:500]
        raise ConnectionError(f"Error HTTP {response.status_code} de Ollama local: {body}")

    try:
        data = response.json()
    except json.JSONDecodeError:
        raise ConnectionError(f"Respuesta inesperada (no-JSON) de Ollama local.")

    try:
        content = data["message"]["content"]
    except (KeyError, IndexError):
        raise ValueError(f"La respuesta del LLM local no tiene la estructura esperada.")

    if not content or not content.strip():
        raise ValueError(
            "El LLM local devolvió una respuesta vacía. "
            "Posible bug de thinking — verifica que el modelo no sea Qwen."
        )

    return content


def _call_llm(messages: list[dict], is_multi: bool = False) -> str:
    """Llama al LLM en el modo configurado (cloud o local) y devuelve el texto de respuesta."""
    if OCR_MODE == "local":
        logger.info("Usando LLM local: %s (%s)", LOCAL_OCR_MODEL, LOCAL_OLLAMA_URL)
        return _call_llm_local(messages, is_multi)
    else:
        logger.info("Usando LLM cloud: %s (%s)", TICKET_OCR_MODEL, OLLAMA_BASE_URL)
        return _call_llm_cloud(messages, is_multi)


def _build_image_message(image_path: str) -> dict:
    """Construye un mensaje de usuario con una imagen en formato OpenAI vision."""
    b64, mime = _encode_image_b64(image_path)
    return {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "Analiza esta imagen de ticket de compra y extrae los datos según el esquema JSON indicado.",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{b64}",
                },
            },
        ],
    }


def _build_multi_image_message(image_paths: list[str]) -> dict:
    """Construye un mensaje de usuario con múltiples imágenes."""
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "Analiza estas imágenes que son páginas consecutivas del mismo ticket. "
                "Extrae todos los items de todas las páginas y haz merge en un único JSON."
            ),
        }
    ]
    for path in image_paths:
        b64, mime = _encode_image_b64(path)
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{b64}",
                },
            }
        )
    return {"role": "user", "content": content}


# ─── Funciones públicas ──────────────────────────────────────────────────────

_RETRY_INSTRUCTION = (
    "Tu respuesta anterior no era JSON válido. Vuelve a mirar la imagen y responde "
    "ÚNICAMENTE con el objeto JSON del ticket: sin frases, sin explicaciones y sin "
    "bloques de markdown. Empieza con '{' y termina con '}'."
)


def _extract_json_with_retry(messages: list[dict], is_multi: bool, etiqueta: str) -> dict:
    """Extrae el JSON del ticket, con un reintento correctivo si el modelo divaga.

    Medido: ~1 de cada 10 fotos hace que el modelo conteste en prosa («Let me
    analyze this receipt…») en vez de JSON. Un segundo turno con la respuesta
    anterior y una instrucción estricta lo resuelve sin cambiar de modelo.
    """
    raw_response = _call_llm(messages, is_multi=is_multi)
    try:
        return _extract_json_from_text(raw_response)
    except ValueError as e:
        logger.warning("Respuesta no-JSON para %s (%s); reintentando con instrucción estricta",
                       etiqueta, e)

    retry_messages = list(messages) + [
        {"role": "assistant", "content": raw_response[:2000]},
        {"role": "user", "content": _RETRY_INSTRUCTION},
    ]
    retry_response = _call_llm(retry_messages, is_multi=is_multi)
    try:
        return _extract_json_from_text(retry_response)
    except ValueError as e:
        logger.error("Respuesta no-JSON del LLM para %s incluso tras reintento: %s", etiqueta, e)
        raise ValueError(
            f"El modelo no devolvió JSON válido ni tras reintento ({etiqueta}): {e}"
        ) from e


def _extract_json_rotated(image_path: str) -> dict:
    """Último recurso: reintenta con la imagen girada.

    Hay tickets escaneados en vertical (texto girado 90°) en los que el modelo se
    pone a describir la imagen en vez de leerla. Girarla en el servidor lo
    resuelve: medido con una foto de pescadería que fallaba siempre, -90° la lee
    a la primera. Solo se paga este coste cuando ya han fallado los dos turnos
    normales.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow es dependencia declarada
        raise ValueError(
            f"No se pudo leer el ticket de {image_path} y Pillow no está instalado "
            f"para reintentar con la imagen girada."
        )

    import tempfile

    base = Image.open(image_path)
    ultimo_error: Exception | None = None
    for angulo in (-90, 90, 180):
        tmp = Path(tempfile.gettempdir()) / f"rot{angulo}_{Path(image_path).stem}.jpg"
        base.rotate(angulo, expand=True).convert("RGB").save(tmp, quality=90)
        mensaje = _build_image_message(str(tmp))
        try:
            # Un solo intento por orientación: esto ya es el último recurso y
            # cada llamada con una foto grande cuesta ~1 minuto.
            return _extract_json_from_text(_call_llm([mensaje], is_multi=False))
        except ValueError as e:
            ultimo_error = e
    raise ValueError(
        f"El modelo no devolvió JSON válido ni girando la imagen ({Path(image_path).name}): "
        f"{ultimo_error}"
    )


def extract_ticket_from_image(image_path: str) -> dict:
    """Extrae datos estructurados de un ticket desde una imagen usando LLM de visión.

    Lee la imagen del path (JPG, PNG, HEIC), la envía al modelo glm-5.3-flash
    via Ollama Cloud, y devuelve un dict con los datos del ticket.

    Args:
        image_path: Ruta al archivo de imagen del ticket.

    Returns:
        Dict con el esquema: {comercio, fecha, hora, direccion, num_ticket,
        items: [{cantidad, descripcion, precio_unit, importe}], total, metodo_pago}.

    Raises:
        FileNotFoundError: Si la imagen no existe.
        ConnectionError: Si la API no responde.
        ValueError: Si la respuesta no es JSON válido.
    """
    logger.info("Extrayendo ticket de imagen: %s", image_path)

    message = _build_image_message(image_path)
    try:
        data = _extract_json_with_retry([message], is_multi=False, etiqueta=image_path)
    except ValueError:
        # Ticket vertical / ilegible en su orientación original.
        data = _extract_json_rotated(image_path)

    logger.info(
        "Ticket extraído: comercio=%s, fecha=%s, %d items, total=%s",
        data.get("comercio", "?"),
        data.get("fecha", "?"),
        len(data.get("items", [])),
        data.get("total", "?"),
    )
    return data


def extract_ticket_from_multiple_images(image_paths: list[str]) -> dict:
    """Extrae datos de un ticket largo que ocupa varias imágenes/páginas.

    Envía todas las imágenes en un solo mensaje al LLM, que se encarga de
    hacer merge de los items de todas las páginas.

    Args:
        image_paths: Lista de rutas a las imágenes (en orden).

    Returns:
        Dict con el mismo esquema que extract_ticket_from_image, con todos
        los items combinados.

    Raises:
        FileNotFoundError: Si alguna imagen no existe.
        ConnectionError: Si la API no responde.
        ValueError: Si la respuesta no es JSON válido.
    """
    if not image_paths:
        raise ValueError("Se requiere al menos una imagen.")

    logger.info("Extrayendo ticket de %d imágenes: %s", len(image_paths), image_paths)

    message = _build_multi_image_message(image_paths)
    data = _extract_json_with_retry([message], is_multi=True, etiqueta=f"{len(image_paths)} imágenes")

    logger.info(
        "Ticket multi-página extraído: comercio=%s, fecha=%s, %d items, total=%s",
        data.get("comercio", "?"),
        data.get("fecha", "?"),
        len(data.get("items", [])),
        data.get("total", "?"),
    )
    return data


CUADRE_TOLERANCIA = 0.02  # € de diferencia máxima para considerar que la suma cuadra


def compute_cuadre(data: dict) -> tuple[Optional[bool], Optional[float]]:
    """Comprueba que la suma de importes que ha emitido el modelo cuadre con el total.

    Esta comprobación NO se delega en el modelo: se hace en código sobre lo que el
    modelo ya devolvió. Motivo medido (experimento bonsai-2, oct-2026): el modelo
    puede escribir ``"cuadra": true`` **copiando el total impreso en su campo
    ``suma_items``** en lugar de sumar sus propios items, así que su autoinforme no
    es fiable. Esta suma sí lo es: es la misma que ya usa ``validate_ticket``.

    Args:
        data: dict devuelto por el LLM (con 'items' y 'total').

    Returns:
        ``(True|False, diferencia)`` o ``(None, None)`` si no es evaluable
        (sin items o sin total válido).
    """
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None, None
    try:
        total = float(data.get("total"))
    except (TypeError, ValueError):
        return None, None
    if total <= 0:
        return None, None
    suma = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            suma += float(item.get("importe") or 0)
        except (TypeError, ValueError):
            continue
    diff = round(round(suma, 2) - total, 2)
    return abs(diff) <= CUADRE_TOLERANCIA, diff


def validate_ticket(data: dict) -> tuple[bool, str]:
    """Valida que un dict de ticket extraído por LLM tenga los datos correctos.

    Comprobaciones:
    - Campos obligatorios existen: comercio, fecha, items, total.
    - La suma de importes de items ≈ total (tolerancia ±0.05€).

    Args:
        data: Dict con los datos del ticket.

    Returns:
        (True, '') si el ticket es válido.
        (False, 'mensaje_error') si hay algún problema.
    """
    required_fields = ["comercio", "fecha", "items", "total"]
    for field in required_fields:
        if field not in data:
            return False, f"Campo obligatorio '{field}' no encontrado en el ticket."
        if data[field] is None:
            return False, f"Campo obligatorio '{field}' es null."

    items = data.get("items", [])
    if not isinstance(items, list):
        return False, f"El campo 'items' debe ser una lista, no {type(items).__name__}."

    if len(items) == 0:
        return False, "El ticket no tiene items."

    total = data.get("total")
    try:
        total = float(total)
    except (TypeError, ValueError):
        return False, f"El campo 'total' no es un número válido: {total}"

    suma_importes = 0.0
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"Item {i} no es un diccionario."
        importe = item.get("importe")
        if importe is None:
            return False, f"Item {i} no tiene campo 'importe'."
        try:
            suma_importes += float(importe)
        except (TypeError, ValueError):
            return False, f"Item {i} tiene importe no numérico: {importe}"

    tolerance = 0.05
    diff = abs(suma_importes - total)
    if diff > tolerance:
        return (
            False,
            f"La suma de importes ({suma_importes:.2f}€) no coincide con el total "
            f"({total:.2f}€). Diferencia: {diff:.2f}€ (tolerancia ±{tolerance}€).",
        )

    return True, ""


def _parse_price_unit(value) -> float:
    """Convierte precio_unit a float de forma tolerante.

    El LLM de OCR a veces devuelve None, texto tipo '0,76x' o pesados tipo
    '0,480 kg x 2,69 EUR/kg'. En esos casos devolvemos 0.0 — el importe es
    el campo que valida la suma contra el total; precio_unit es cosmético.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    # Pesados: '1,364 kg x 1,59 EUR/kg' -> último número antes de 'EUR/kg' (precio/kg)
    m = re.search(r"x\s*([\d.,]+)\s*EUR/kg", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return 0.0
    # Cualquier número decimal en el texto (p.ej. '0,76x' -> 0.76)
    m = re.search(r"[\d]+(?:[.,][\d]+)?", text)
    if m:
        try:
            return float(m.group(0).replace(",", "."))
        except ValueError:
            return 0.0
    return 0.0


def _dict_to_ticket(data: dict, source_file: str = "") -> Ticket:
    """Convierte un dict extraído por el LLM a un objeto Ticket del parse_ticket.py.

    NO modifica parse_ticket.py — reutiliza los dataclasses existentes.
    Los campos que no existen en el esquema LLM (telefono, operador, iva_desglose)
    se dejan con valores por defecto.
    """
    # Combinar fecha + hora en el formato que usa parse_ticket: "dd/mm/yyyy HH:MM"
    fecha = data.get("fecha", "")
    hora = data.get("hora", "")
    if fecha and hora:
        fecha_completa = f"{fecha} {hora}"
    elif fecha:
        fecha_completa = fecha
    else:
        fecha_completa = ""

    # Mapear items del esquema LLM a LineItem
    items = []
    for item in data.get("items", []):
        try:
            line_item = LineItem(
                cantidad=int(item.get("cantidad", 1)),
                descripcion=str(item.get("descripcion", "")),
                precio_unit=_parse_price_unit(item.get("precio_unit")),
                importe=float(item.get("importe", 0.0)),
            )
            items.append(line_item)
        except (TypeError, ValueError) as e:
            logger.warning("Item saltado por error de conversión: %s — %s", item, e)

    # Si se cayeron items con importe válido (precio_unit None/texto), conservarlos:
    # el importe es lo que valida la suma contra el total; precio_unit se re-deriva.
    if len(items) < len(data.get("items", [])):
        kept_descs = {it.descripcion for it in items}
        for item in data.get("items", []):
            if str(item.get("descripcion", "")) in kept_descs:
                continue
            try:
                imp = float(item.get("importe", 0.0))
            except (TypeError, ValueError):
                logger.warning("Item descartado sin importe válido: %s", item)
                continue  # sin importe no hay nada que guardar
            try:
                cant = int(item.get("cantidad", 1))
            except (TypeError, ValueError):
                cant = 1
            items.append(
                LineItem(
                    cantidad=cant,
                    descripcion=str(item.get("descripcion", "")),
                    precio_unit=round(imp / cant, 4) if cant else imp,
                    importe=imp,
                )
            )
            logger.info(
                "Item recuperado con importe válido (precio_unit no numérico): %s",
                item,
            )

    # Mapear comercio a tienda
    comercio = data.get("comercio", "")
    # Normalizar nombre de tienda (primera letra mayúscula)
    if comercio:
        tienda = comercio.capitalize() if comercio.islower() else comercio
    else:
        tienda = ""

    ticket = Ticket(
        fecha=fecha_completa,
        tienda=tienda,
        direccion=data.get("direccion", ""),
        telefono="",  # No disponible en esquema LLM
        operador="",  # No disponible en esquema LLM
        num_ticket=data.get("num_ticket", ""),
        items=items,
        total=float(data.get("total", 0.0)),
        metodo_pago=data.get("metodo_pago", ""),
        iva_desglose=[],  # No disponible en esquema LLM
        pdf_file=source_file,  # Reutilizamos pdf_file para el nombre del archivo origen
        email_account="",
    )

    # Campos adicionales no en el dataclass pero requeridos por la especificación
    # Se establecen como atributos dinámicos (Python lo permite en dataclass instances)
    ticket.source_type = "email_photo"  # type: ignore[attr-defined]
    ticket.source_file = source_file  # type: ignore[attr-defined]

    return ticket


def process_image_to_ticket(image_path: str) -> Ticket:
    """Procesa una imagen de ticket completa: extracción LLM + validación + conversión a Ticket.

    Pipeline:
    1. extract_ticket_from_image → dict con datos del LLM.
    2. validate_ticket → comprueba campos y coherencia de totales.
    3. Convierte el dict a objeto Ticket.
    4. Si la validación falla, loguea warning pero devuelve el ticket igualmente
       (mejor tener datos aprox que nada).
    5. Rellena source_type='email_photo' y source_file con el nombre del archivo.

    Args:
        image_path: Ruta al archivo de imagen del ticket.

    Returns:
        Objeto Ticket con los datos extraídos.

    Raises:
        FileNotFoundError: Si la imagen no existe.
        ConnectionError: Si la API de Ollama Cloud no responde.
        ValueError: Si la respuesta del LLM no es procesable.
    """
    source_file = Path(image_path).name

    # 1. Extracción
    data = extract_ticket_from_image(image_path)

    # 2. Validación
    is_valid, error_msg = validate_ticket(data)
    if not is_valid:
        logger.warning(
            "Validación falló para %s: %s — devolviendo ticket aproximado",
            source_file,
            error_msg,
        )
    else:
        logger.info("Ticket validado correctamente: %s", source_file)

    # 3. Conversión a Ticket
    ticket = _dict_to_ticket(data, source_file=source_file)
    ticket._validation_error = error_msg if not is_valid else ""  # type: ignore[attr-defined]

    # 3b. Cuadre aritmético en CÓDIGO (no se delega en el modelo: su "cuadra" no
    # es de fiar, puede copiar el total en suma_items). Queda en el Ticket para
    # que la ingesta lo persista y la UI lo muestre.
    cuadre_ok, cuadre_diff = compute_cuadre(data)
    ticket.cuadre_ok = cuadre_ok  # type: ignore[attr-defined]
    ticket.cuadre_diff = cuadre_diff  # type: ignore[attr-defined]
    if cuadre_ok is False:
        logger.warning(
            "DESCUADRE en %s: %d items cuya suma se desvía %+.2f € del total impreso (%.2f €)",
            source_file, len(ticket.items), cuadre_diff or 0.0, ticket.total,
        )
    elif cuadre_ok is True:
        logger.info("Cuadre correcto en %s (diferencia %+.2f €)", source_file, cuadre_diff or 0.0)

    return ticket