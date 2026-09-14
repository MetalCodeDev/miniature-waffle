# Gemini Media Module
# Creator: @mxzavo

import os
import base64
import asyncio
import tempfile
import logging
from google import genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is not set")

client = genai.Client(api_key=API_KEY)


async def generate_image(prompt: str) -> str:
    """
    Запрашивает у Gemini изображение по prompt и сохраняет его во временный PNG-файл.
    Возвращает путь к сохранённому файлу.
    """

    def call_api():
        return client.interactions.create(model="gemini-3.1-flash-image", input=prompt)

    try:
        response = await asyncio.to_thread(call_api)
    except Exception as e:
        logger.exception("Gemini API call failed")
        raise RuntimeError(f"API call failed: {e}") from e

    # Попробуем извлечь base64-строку из возможных форм ответа
    b64_data = None

    # 1) response.output_image.data
    if getattr(response, "output_image", None):
        out = response.output_image
        b64_data = getattr(out, "data", None) or (out.get("data") if isinstance(out, dict) else None)

    # 2) response.output_images (список)
    if not b64_data and getattr(response, "output_images", None):
        imgs = response.output_images
        if imgs:
            first = imgs[0]
            b64_data = getattr(first, "data", None) or (first.get("data") if isinstance(first, dict) else None)

    # 3) content / text fields
    if not b64_data:
        b64_data = getattr(response, "content", None) or getattr(response, "text", None)

    if not b64_data:
        # Для отладки можно логировать весь ответ
        logger.error("Gemini did not return image data. Full response: %s", repr(response))
        raise RuntimeError("Gemini не вернул изображение")

    # Если это data URI, убираем префикс
    if isinstance(b64_data, str) and b64_data.startswith("data:"):
        parts = b64_data.split(",", 1)
        if len(parts) == 2:
            b64_data = parts[1]
        else:
            raise RuntimeError("Unexpected data URI format from Gemini")

    # Если SDK вернул байты
    if isinstance(b64_data, (bytes, bytearray)):
        img_bytes = bytes(b64_data)
    else:
        try:
            img_bytes = base64.b64decode(b64_data)
        except Exception as e:
            logger.exception("Failed to decode base64 image data")
            raise RuntimeError(f"Failed to decode base64 image data: {e}") from e

    # Записываем во временный файл, чтобы не перезаписывать прошлые генерации
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        tmp.write(img_bytes)
        tmp.flush()
    finally:
        tmp.close()

    logger.info("Image saved to %s", tmp.name)
    return tmp.name
