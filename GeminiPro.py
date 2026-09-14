# meta developer: @mxzavo
# requires: google-genai pillow

import asyncio
import io
import os
from PIL import Image
from google import genai
from google.genai import types

from .. import loader, utils


@loader.tds
class GeminiAllInOneMod(loader.Module):
    """Мультимодальный модуль Gemini: генерация, редактирование, анализ фото и текстовый чат"""

    strings = {
        "name": "GeminiAI",
        "no_key": (
            "🚫 <b>Не задан API-ключ Gemini.</b>\n"
            "Получи его на aistudio.google.com и укажи:\n"
            "• в конфиге: <code>.config GeminiAI</code>\n"
            "• или в переменной окружения <code>GEMINI_API_KEY</code>"
        ),
        "no_prompt": "❓ Укажи запрос или промпт.",
        "no_reply_media": "❓ Ответь командой на фото или картинку.",
        "no_image_returned": "🚫 Gemini не вернул изображение. Попробуй другой запрос.",
        "error": "🚫 Ошибка: <code>{}</code>",
        "generating": "🎨 Генерирую изображение...",
        "editing": "🎨 Редактирую изображение...",
        "thinking": "🧠 Обрабатываю запрос...",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "api_key",
                None,
                "API-ключ Gemini (aistudio.google.com)",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "image_model",
                "imagen-3.0-generate-002",
                "Модель для генерации картинок из текста",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "chat_model",
                "gemini-2.5-flash",
                "Модель для текста, анализа и редактирования изображений",
                validator=loader.validators.String(),
            ),
        )

    def _get_key(self) -> str | None:
        key = self.config["api_key"]
        if key in (None, "", "None"):
            key = os.environ.get("GEMINI_API_KEY")
        return key

    def _get_client(self) -> genai.Client:
        key = self._get_key()
        if not key:
            raise ValueError("NO_KEY")
        return genai.Client(api_key=key)

    @loader.command()
    async def genimg(self, message):
        """<промпт> - сгенерировать новое изображение по описанию"""
        prompt = utils.get_args_raw(message)
        if not prompt:
            await utils.answer(message, self.strings["no_prompt"])
            return

        if not self._get_key():
            await utils.answer(message, self.strings["no_key"])
            return

        await utils.answer(message, self.strings["generating"])
        try:
            client = self._get_client()
            result = await asyncio.to_thread(
                client.models.generate_images,
                model=self.config["image_model"],
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1),
            )

            if not result.generated_images:
                await utils.answer(message, self.strings["no_image_returned"])
                return

            photo = io.BytesIO(result.generated_images[0].image.image_bytes)
            photo.name = "gemini.png"
            await utils.answer(message, file=photo)
        except Exception as e:
            await utils.answer(
                message, self.strings["error"].format(utils.escape_html(str(e)))
            )

    @loader.command()
    async def editimg(self, message):
        """<реплай на фото> <промпт> - отредактировать изображение по текстовой инструкции"""
        reply = await message.get_reply_message()
        if not reply or not reply.media:
            await utils.answer(message, self.strings["no_reply_media"])
            return

        prompt = utils.get_args_raw(message)
        if not prompt:
            await utils.answer(message, self.strings["no_prompt"])
            return

        if not self._get_key():
            await utils.answer(message, self.strings["no_key"])
            return

        await utils.answer(message, self.strings["editing"])
        try:
            image_bytes = await reply.download_media(bytes)
            img = Image.open(io.BytesIO(image_bytes))

            client = self._get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=[img, prompt],
            )

            # Проверяем, вернула ли мультимодальная модель отредактированную картинку
            image_found = False
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if getattr(part, "inline_data", None):
                        out_photo = io.BytesIO(part.inline_data.data)
                        out_photo.name = "edited.png"
                        await utils.answer(message, file=out_photo)
                        image_found = True
                        break

            if not image_found:
                # Если модель ответила текстовыми рекомендациями/описанием изменений
                text = response.text or self.strings["no_image_returned"]
                await utils.answer(message, text)

        except Exception as e:
            await utils.answer(
                message, self.strings["error"].format(utils.escape_html(str(e)))
            )

    @loader.command()
    async def askimg(self, message):
        """<реплай на фото> [вопрос] - анализ фото, OCR, описание или ответ на вопрос по нему"""
        reply = await message.get_reply_message()
        if not reply or not reply.media:
            await utils.answer(message, self.strings["no_reply_media"])
            return

        prompt = utils.get_args_raw(message) or "Подробно опиши, что изображено на картинке."

        if not self._get_key():
            await utils.answer(message, self.strings["no_key"])
            return

        await utils.answer(message, self.strings["thinking"])
        try:
            image_bytes = await reply.download_media(bytes)
            img = Image.open(io.BytesIO(image_bytes))

            client = self._get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=[img, prompt],
            )
            await utils.answer(message, response.text or "Пустой ответ.")
        except Exception as e:
            await utils.answer(
                message, self.strings["error"].format(utils.escape_html(str(e)))
            )

    @loader.command()
    async def gemini(self, message):
        """<запрос> - текстовый диалог с Gemini"""
        prompt = utils.get_args_raw(message)
        if not prompt:
            await utils.answer(message, self.strings["no_prompt"])
            return

        if not self._get_key():
            await utils.answer(message, self.strings["no_key"])
            return

        await utils.answer(message, self.strings["thinking"])
        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=prompt,
            )
            await utils.answer(message, response.text or "Пустой ответ.")
        except Exception as e:
            await utils.answer(
                message, self.strings["error"].format(utils.escape_html(str(e)))
            )
