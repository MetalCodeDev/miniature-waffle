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
    """Ультимативный модуль Gemini: генерация фото/видео, поиск, саммари, анализ аудио и роли"""

    strings = {
        "name": "GeminiAI",
        "no_key": (
            "🚫 <b>Не задан API-ключ Gemini.</b>\n"
            "Укажи в конфиге: <code>.config GeminiAI</code>\n"
            "Или в переменной: <code>GEMINI_API_KEY</code>"
        ),
        "no_prompt": "❓ Укажи запрос или промпт.",
        "no_reply_media": "❓ Ответь командой на медиа (фото, аудио, голос).",
        "error": "🚫 Ошибка: <code>{}</code>",
        "generating": "🎨 Генерирую...",
        "animating": "🎬 Оживляю картинку (это может занять время)...",
        "thinking": "🧠 Обрабатываю...",
        "summarizing": "📚 Читаю историю чата...",
        "role_set": "🎭 Роль успешно изменена на:\n<code>{}</code>",
        "role_cleared": "🎭 Роль сброшена на стандартную.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue("api_key", None, "API-ключ Gemini", validator=loader.validators.Hidden()),
            loader.ConfigValue("chat_model", "gemini-2.5-pro", "Модель для текста, поиска и анализа", validator=loader.validators.String()),
            loader.ConfigValue("image_model", "imagen-3.0-generate-002", "Модель для генерации фото", validator=loader.validators.String()),
            loader.ConfigValue("video_model", "veo-2.0-generate-001", "Модель для анимации/генерации видео", validator=loader.validators.String()),
        )

    async def client_ready(self, client, db):
        self.db = db

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

    def _get_system_instruction(self) -> str | None:
        role = self.db.get(self.strings["name"], "role", None)
        return role if role else None

    @loader.command()
    async def grole(self, message):
        """<текст> - задать боту роль/характер (без аргументов - сброс)"""
        role = utils.get_args_raw(message)
        if not role:
            self.db.set(self.strings["name"], "role", None)
            await message.reply(self.strings["role_cleared"])
            return

        self.db.set(self.strings["name"], "role", role)
        await message.reply(self.strings["role_set"].format(utils.escape_html(role)))

    @loader.command()
    async def gsum(self, message):
        """<число> - сделать краткую выжимку последних N сообщений в чате"""
        args = utils.get_args_raw(message)
        count = int(args) if args.isdigit() else 50

        if not self._get_key():
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["summarizing"])
        try:
            msgs = await message.client.get_messages(message.chat_id, limit=count + 1)
            chat_log = "\n".join(
                [f"{m.sender.first_name if m.sender else 'Кто-то'}: {m.text}" for m in msgs if m.text][::-1]
            )

            prompt = f"Сделай очень краткую и понятную выжимку (саммари) этого диалога. О чем общались, к чему пришли:\n\n{chat_log}"
            
            client = self._get_client()
            config = types.GenerateContentConfig(system_instruction=self._get_system_instruction())
            
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=prompt,
                config=config
            )
            
            await message.reply(response.text or "Пустой ответ.")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def animate(self, message):
        """<реплай на фото> [промпт] - оживить картинку (превратить в видео)"""
        reply = await message.get_reply_message()
        if not reply or not reply.media:
            return await message.reply(self.strings["no_reply_media"])

        prompt = utils.get_args_raw(message) or "Оживи это изображение, сделай кинематографичное движение"
        if not self._get_key():
            return await message.reply(self.strings["no_key"])

        status_msg = await reply.reply(self.strings["animating"])
        try:
            image_bytes = await reply.download_media(bytes)
            img = Image.open(io.BytesIO(image_bytes))

            client = self._get_client()
            # Используем мультимодальный запрос для генерации видео из картинки
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["video_model"],
                contents=[img, prompt],
            )
            
            video_found = False
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and "video" in part.inline_data.mime_type:
                        out_video = io.BytesIO(part.inline_data.data)
                        out_video.name = "animated.mp4"
                        await reply.reply(file=out_video)
                        video_found = True
                        break

            if not video_found:
                await status_msg.edit("🚫 Модель не вернула видеофайл. Возможно, функция генерации видео пока ограничена для этого API-ключа.")
            else:
                await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def gemini(self, message):
        """[-s] <запрос> или <реплай на фото/ГС> - универсальный чат с ИИ. Флаг -s для поиска в интернете."""
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()
        
        use_search = False
        if args.startswith("-s "):
            use_search = True
            args = args[3:]
        elif args == "-s":
            use_search = True
            args = ""

        if not args and not reply:
            return await message.reply(self.strings["no_prompt"])

        if not self._get_key():
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["thinking"])
        try:
            contents = []
            
            # Поддержка фото, голосовых (voice) и аудиофайлов
            if reply and reply.media:
                media_bytes = await reply.download_media(bytes)
                mime = "image/jpeg"
                if getattr(reply.document, "mime_type", "").startswith("audio"):
                    mime = reply.document.mime_type
                
                contents.append(types.Part(inline_data=types.Blob(mime_type=mime, data=media_bytes)))
            
            if args:
                contents.append(args)

            client = self._get_client()
            
            # Включаем поиск, если передан флаг -s
            tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
            config = types.GenerateContentConfig(
                system_instruction=self._get_system_instruction(),
                tools=tools
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=contents,
                config=config
            )
            
            await message.reply(response.text or "Пустой ответ.")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def genimg(self, message):
        """<промпт> - сгенерировать картинку"""
        prompt = utils.get_args_raw(message)
        if not prompt:
            return await message.reply(self.strings["no_prompt"])

        if not self._get_key():
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["generating"])
        try:
            client = self._get_client()
            result = await asyncio.to_thread(
                client.models.generate_images,
                model=self.config["image_model"],
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1),
            )

            if not result.generated_images:
                return await status_msg.edit("🚫 Gemini не вернул изображение.")

            photo = io.BytesIO(result.generated_images[0].image.image_bytes)
            photo.name = "gemini.png"
            
            await message.reply(file=photo)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))
