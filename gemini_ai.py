# meta developer: @mxzavo
# requires: google-genai pillow pytz markdown_it_py aiohttp

import asyncio
import base64
import io
import json
import os
import random
import re
import tempfile
import time
from datetime import datetime

import aiohttp
from markdown_it import MarkdownIt
from PIL import Image
import pytz
from telethon import types as tg_types
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeSticker
from telethon.utils import get_display_name

from google import genai
from google.genai import types

from .. import loader, utils
from ..inline.types import InlineCall


@loader.tds
class GeminiAllInOneMod(loader.Module):
    """Комбайн Gemini от @mxzavo: контекст, пресеты, автоответчик, пагинация, поиск, генерация фото/видео/аудио"""

    strings = {
        "name": "GeminiAI",
        "no_key": (
            "🚫 <b>Не задан API-ключ Gemini.</b>\n"
            "Укажи в конфиге: <code>.config GeminiAI api_key</code>"
        ),
        "no_prompt": "❓ <b>Укажи запрос или промпт.</b>",
        "no_reply_media": "❓ <b>Ответь командой на фото/медиа.</b>",
        "error": "🚫 <b>Ошибка:</b>\n<code>{}</code>",
        "generating": "🎨 <b>Генерирую...</b>",
        "thinking": "🧠 <b>Обрабатываю...</b>",
        "animating": "🎬 <b>Оживляю картинку (Veo)...</b>",
        "cleared": "🧹 <b>Память диалога в этом чате очищена.</b>",
        "cleared_all": "🧹 <b>Память полностью сброшена во всех чатах.</b>",
        "auto_on": "🎭 <b>Автоответчик включен (шанс: {}%).</b>",
        "auto_off": "🎭 <b>Автоответчик выключен.</b>",
        "mem_status": "🧠 <b>Контекст чата:</b> <code>{}/{}</code> пар сообщений.",
        "gpresets_usage": (
            "ℹ️ <b>Управление пресетами:</b>\n"
            "• <code>.gpresets save &lt;имя&gt; &lt;текст&gt;</code>\n"
            "• <code>.gpresets load &lt;имя&gt;</code>\n"
            "• <code>.gpresets del &lt;имя&gt;</code>\n"
            "• <code>.gpresets list</code>"
        ),
    }

    TEXT_MIME_TYPES = {
        "text/plain", "text/markdown", "text/html", "text/css", "text/csv",
        "application/json", "application/xml", "application/x-python",
        "text/x-python", "application/javascript", "application/x-sh",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue("api_key", "", "API-ключи через запятую", validator=loader.validators.Hidden()),
            loader.ConfigValue("chat_model", "gemini-2.5-pro", "Модель текста/анализа", validator=loader.validators.String()),
            loader.ConfigValue("image_model", "imagen-3.0-generate-002", "Модель для .genimg", validator=loader.validators.String()),
            loader.ConfigValue("video_model", "veo-2.0-generate-001", "Модель для .animate", validator=loader.validators.String()),
            loader.ConfigValue("max_history", 20, "Пар сообщений в памяти на чат", validator=loader.validators.Integer(minimum=0)),
            loader.ConfigValue("temperature", 1.0, "Креативность (0.0 - 2.0)", validator=loader.validators.Float(minimum=0.0, maximum=2.0)),
            loader.ConfigValue("timezone", "Europe/Kyiv", "Часовой пояс", validator=loader.validators.String()),
            loader.ConfigValue("auto_chance", 0.15, "Шанс ответа .gauto (0.0 - 1.0)", validator=loader.validators.Float(minimum=0.0, maximum=1.0)),
            loader.ConfigValue("proxy", "", "HTTP прокси (http://user:pass@host:port)", validator=loader.validators.String()),
        )
        self.conversations = {}
        self.auto_chats = set()
        self.prompt_presets = {}
        self.pager_cache = {}
        self.stats = {"in_tokens": 0, "out_tokens": 0, "calls": 0}

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        self.me = await client.get_me()
        self.conversations = self.db.get(self.strings["name"], "history", {})
        self.auto_chats = set(self.db.get(self.strings["name"], "auto_chats", []))
        self.prompt_presets = self.db.get(self.strings["name"], "presets", {})
        self.stats = self.db.get(self.strings["name"], "stats", {"in_tokens": 0, "out_tokens": 0, "calls": 0})

    def _get_api_keys(self) -> list:
        raw = self.config["api_key"] or os.environ.get("GEMINI_API_KEY", "")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def _get_client(self, key: str) -> genai.Client:
        proxy = self.config["proxy"]
        http_opts = types.HttpOptions(async_client_args={"proxies": {"http://": proxy, "https://": proxy}}) if proxy else None
        return genai.Client(api_key=key, http_options=http_opts)

    def _markdown_to_html(self, text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
        text = re.sub(r"^(#+)\s+(.*)", r"<b>\2</b>", text, flags=re.MULTILINE)
        text = re.sub(r"^([ \t]*)[-*+]\s+", r"\1• ", text, flags=re.MULTILINE)
        md = MarkdownIt("commonmark", {"html": True, "linkify": True}).enable("strikethrough")
        html = md.render(text)

        def fmt_code(m):
            lang = utils.escape_html(m.group(1).strip()) if m.group(1) else ""
            code = utils.escape_html(m.group(2).strip())
            return f'<pre><code class="language-{lang}">{code}</code></pre>' if lang else f"<pre><code>{code}</code></pre>"

        html = re.sub(r"```(\w+)?\n([\s\S]+?)\n```", fmt_code, html)
        html = re.sub(r"<p>(<pre>[\s\S]*?</pre>)</p>", r"\1", html, flags=re.DOTALL)
        return html.replace("<p>", "").replace("</p>", "\n").strip()

    def _paginate_text(self, text: str, limit: int = 3400) -> list:
        pages, cur, cur_len = [], [], 0
        for line in text.split("\n"):
            if cur_len + len(line) + 1 > limit:
                if cur:
                    pages.append("\n".join(cur))
                    cur, cur_len = [], 0
            cur.append(line)
            cur_len += len(line) + 1
        if cur:
            pages.append("\n".join(cur))
        return pages

    async def _render_page(self, uid: str, page: int, call: InlineCall = None, message=None):
        data = self.pager_cache.get(uid)
        if not data:
            if call:
                await call.edit("⚠️ <b>Сессия истекла.</b>")
            return

        chunks, total = data["chunks"], data["total"]
        body = self._markdown_to_html(chunks[page])
        text = f"📄 <b>Страница {page + 1}/{total}</b>\n\n{body}"

        nav = []
        if page > 0:
            nav.append({"text": "◀️", "data": f"gpage:{uid}:{page - 1}"})
        nav.append({"text": f"{page + 1}/{total}", "data": "gnoop"})
        if page < total - 1:
            nav.append({"text": "▶️", "data": f"gpage:{uid}:{page + 1}"})

        kb = [nav, [{"text": "❌ Закрыть", "data": f"gclose:{uid}"}]]
        if call:
            await call.edit(text, reply_markup=kb)
        elif message:
            await self.inline.form(text=text, message=message, reply_markup=kb)

    async def _prepare_input_payload(self, message, raw_text: str):
        parts, text_chunks = [], []
        reply = await message.get_reply_message()

        if reply and getattr(reply, "text", None):
            sender = await reply.get_sender()
            name = get_display_name(sender) if sender else "User"
            text_chunks.append(f"[Реплай на сообщение от {name}]: {reply.text}")

        if raw_text:
            text_chunks.append(raw_text)

        target = message if (message.media or message.sticker) else reply
        if target and (target.media or target.sticker):
            if target.sticker and getattr(target.sticker, "mime_type", "") == "application/x-tgsticker":
                alt = next((a.alt for a in target.sticker.attributes if isinstance(a, DocumentAttributeSticker)), "?")
                text_chunks.append(f"[Анимированный стикер: {alt}]")
            else:
                bio = io.BytesIO()
                await self.client.download_media(target, bio)
                data = bio.getvalue()
                mime = "application/octet-stream"

                if target.photo:
                    mime = "image/jpeg"
                elif getattr(target, "document", None):
                    mime = getattr(target.document, "mime_type", mime)
                    attr = next((a for a in target.document.attributes if isinstance(a, DocumentAttributeFilename)), None)
                    ext = attr.file_name.split(".")[-1].lower() if attr else ""
                    if mime in self.TEXT_MIME_TYPES or ext in ("txt", "py", "json", "md", "csv", "log"):
                        text_chunks.insert(0, f"[Файл {attr.file_name if attr else 'file'}]:\n```\n{data.decode('utf-8', errors='ignore')}\n```")
                        data = None

                if data:
                    if mime.startswith(("image/", "audio/")):
                        parts.append(types.Part(inline_data=types.Blob(mime_type=mime, data=data)))
                    elif mime.startswith("video/"):
                        # Перекодируем через ffmpeg в легкий mp4
                        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as in_f, tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out_f:
                            in_f.write(data)
                            in_f.flush()
                            proc = await asyncio.create_subprocess_exec(
                                "ffmpeg", "-y", "-i", in_f.name, "-vf", "scale='min(640,iw)':-2",
                                "-t", "60", "-c:v", "libx264", "-c:a", "aac", out_f.name,
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                            )
                            await proc.communicate()
                            if proc.returncode == 0:
                                with open(out_f.name, "rb") as final_v:
                                    parts.append(types.Part(inline_data=types.Blob(mime_type="video/mp4", data=final_v.read())))
                            os.remove(in_f.name)
                            os.remove(out_f.name)

        full_text = "\n\n".join(text_chunks).strip()
        if full_text:
            parts.insert(0, types.Part(text=full_text))
        return parts

    # ================= КОМАНДЫ ЧАТА И АНАЛИЗА =================

    @loader.command()
    async def gemini(self, message):
        """[-s] <запрос/реплай> - Запрос к Gemini с сохранением в память (-s включает поиск Google)"""
        args = utils.get_args_raw(message) or ""
        use_search = False
        if args.startswith("-s"):
            use_search = True
            args = args[2:].strip()

        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["thinking"])
        try:
            parts = await self._prepare_input_payload(message, args)
            if not parts:
                return await status_msg.edit(self.strings["no_prompt"])

            chat_id = str(utils.get_chat_id(message))
            hist = self.conversations.get(chat_id, [])

            contents = []
            for item in hist:
                contents.append(types.Content(role=item["role"], parts=[types.Part(text=item["text"])]))
            contents.append(types.Content(role="user", parts=parts))

            # Роль/Инструкция
            sys_instruct = self.db.get(self.strings["name"], "system_role", None)
            try:
                tz = pytz.timezone(self.config["timezone"])
                now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
                time_note = f"[Локальное время: {now}]"
                sys_instruct = f"{sys_instruct}\n{time_note}" if sys_instruct else time_note
            except Exception:
                pass

            tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
            gen_cfg = types.GenerateContentConfig(
                temperature=self.config["temperature"],
                system_instruction=sys_instruct,
                tools=tools,
            )

            client = self._get_client(keys[0])
            t0 = time.time()
            res = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=contents,
                config=gen_cfg,
            )
            elapsed = round(time.time() - t0, 1)

            out_text = res.text or "Пустой ответ."
            meta = getattr(res, "usage_metadata", None)
            in_t = getattr(meta, "prompt_token_count", 0) if meta else 0
            out_t = getattr(meta, "candidates_token_count", 0) if meta else 0

            self.stats["calls"] += 1
            self.stats["in_tokens"] += in_t
            self.stats["out_tokens"] += out_t
            self.db.set(self.strings["name"], "stats", self.stats)

            # Обновление памяти
            hist.append({"role": "user", "text": args or "[Медиа]"})
            hist.append({"role": "model", "text": out_text})
            max_h = self.config["max_history"] * 2
            if max_h > 0 and len(hist) > max_h:
                hist = hist[-max_h:]
            self.conversations[chat_id] = hist
            self.db.set(self.strings["name"], "history", self.conversations)

            header = f"✨ <b>Gemini</b> ⏱️{elapsed}с 🪙{in_t + out_t}\n\n"
            if len(out_text) > 3400:
                chunks = self._paginate_text(out_text, 3000)
                uid = os.urandom(4).hex()
                self.pager_cache[uid] = {"chunks": chunks, "total": len(chunks)}
                await self._render_page(uid, 0, message=message)
                await status_msg.delete()
            else:
                body = self._markdown_to_html(out_text)
                await message.reply(f"{header}{body}")
                await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def gask(self, message):
        """<запрос/реплай> - Быстрый одиночный вопрос без записи в память"""
        args = utils.get_args_raw(message) or ""
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["thinking"])
        try:
            parts = await self._prepare_input_payload(message, args)
            if not parts:
                return await status_msg.edit(self.strings["no_prompt"])

            client = self._get_client(keys[0])
            res = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=parts,
            )
            body = self._markdown_to_html(res.text or "Пустой ответ.")
            await message.reply(f"⚡️ <b>Быстрый ответ:</b>\n\n{body}")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def gsum(self, message):
        """<кол-во сообщений> - Выжимка и саммари последних сообщений чата"""
        args = utils.get_args_raw(message)
        count = int(args) if args and args.isdigit() else 60
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(f"📚 Читаю последние {count} сообщений...")
        try:
            msgs = await self.client.get_messages(message.chat_id, limit=count + 1)
            lines = []
            for m in reversed(msgs):
                if m.id == message.id:
                    continue
                sender = get_display_name(m.sender) if m.sender else "Аноним"
                txt = m.text or "[медиа]"
                lines.append(f"{sender}: {txt}")

            chat_dump = "\n".join(lines)
            prompt = (
                f"Проанализируй данный диалог из Telegram-чата и сделай краткую, емкую выжимку:\n"
                f"1. Главные темы обсуждения\n2. Ключевые решения/выводы\n3. Забавные или важные моменты\n\n"
                f"ЧАТ:\n{chat_dump}"
            )

            client = self._get_client(keys[0])
            res = await asyncio.to_thread(client.models.generate_content, model=self.config["chat_model"], contents=prompt)
            body = self._markdown_to_html(res.text or "Пустой анализ.")
            await message.reply(f"📊 <b>Анализ {count} сообщений:</b>\n\n{body}")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    # ================= ГЕНЕРАЦИЯ МЕДИА =================

    @loader.command()
    async def genimg(self, message):
        """<промпт> - Генерация изображения через Imagen"""
        prompt = utils.get_args_raw(message)
        if not prompt:
            return await message.reply(self.strings["no_prompt"])
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["generating"])
        try:
            client = self._get_client(keys[0])
            result = await asyncio.to_thread(
                client.models.generate_images,
                model=self.config["image_model"],
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1),
            )
            if not result.generated_images:
                return await status_msg.edit("🚫 Изображение не сгенерировано.")

            photo = io.BytesIO(result.generated_images[0].image.image_bytes)
            photo.name = "gemini.png"
            await message.reply(file=photo, message=f"🎨 <code>{utils.escape_html(prompt[:120])}</code>")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def animate(self, message):
        """<реплай на фото> [промпт] - Оживить изображение в видео через Veo"""
        reply = await message.get_reply_message()
        if not reply or not reply.media:
            return await message.reply(self.strings["no_reply_media"])

        prompt = utils.get_args_raw(message) or "Animate this picture with smooth cinematic motion"
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await reply.reply(self.strings["animating"])
        try:
            img_data = await reply.download_media(bytes)
            img = Image.open(io.BytesIO(img_data))
            client = self._get_client(keys[0])

            res = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["video_model"],
                contents=[img, prompt],
            )

            video_bytes = None
            if res.candidates:
                for part in res.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and "video" in part.inline_data.mime_type:
                        video_bytes = part.inline_data.data
                        break

            if not video_bytes:
                return await status_msg.edit("🚫 Видео не получено (возможно, нет доступа к Veo на ключе).")

            out_v = io.BytesIO(video_bytes)
            out_v.name = "animated.mp4"
            await reply.reply(file=out_v)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def gmusic(self, message):
        """<промпт> - Генерация музыки/аудио через Lyria"""
        prompt = utils.get_args_raw(message)
        if not prompt:
            return await message.reply("🎵 Укажи описание трека.")
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply("🎵 Сочиняю трек...")
        try:
            client = self._get_client(keys[0])
            interaction = await asyncio.to_thread(client.interactions.create, model="lyria-3-clip-preview", input=prompt)
            audio_bytes = None
            for o in getattr(interaction, "outputs", []) or []:
                if getattr(o, "type", "") == "audio" and getattr(o, "data", None):
                    audio_bytes = base64.b64decode(o.data)
                    break

            if not audio_bytes:
                return await status_msg.edit("🚫 Не удалось получить аудио.")

            out = io.BytesIO(audio_bytes)
            out.name = "music.mp3"
            await message.reply(file=out, voice=True)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    # ================= УПРАВЛЕНИЕ ПАМЯТЬЮ И ЭКСПОРТ =================

    @loader.command()
    async def gclear(self, message):
        """- Очистить контекст диалога в текущем чате"""
        cid = str(utils.get_chat_id(message))
        self.conversations.pop(cid, None)
        self.db.set(self.strings["name"], "history", self.conversations)
        await message.reply(self.strings["cleared"])

    @loader.command()
    async def gres(self, message):
        """- Сбросить память ВООБЩЕ во всех чатах"""
        self.conversations.clear()
        self.db.set(self.strings["name"], "history", {})
        await message.reply(self.strings["cleared_all"])

    @loader.command()
    async def gmem(self, message):
        """- Показать статус контекста текущего чата"""
        cid = str(utils.get_chat_id(message))
        hist = self.conversations.get(cid, [])
        await message.reply(self.strings["mem_status"].format(len(hist) // 2, self.config["max_history"]))

    @loader.command()
    async def gexport(self, message):
        """- Экспортировать JSON файл с памятью текущего чата"""
        cid = str(utils.get_chat_id(message))
        hist = self.conversations.get(cid, [])
        if not hist:
            return await message.reply("Память чата пуста.")

        bio = io.BytesIO(json.dumps(hist, ensure_ascii=False, indent=2).encode())
        bio.name = f"gemini_history_{cid}.json"
        await message.reply(file=bio, message="💾 <b>Экспорт диалога Gemini</b>")

    @loader.command()
    async def gimport(self, message):
        """<реплай на JSON> - Импортировать контекст в текущий чат"""
        reply = await message.get_reply_message()
        if not reply or not reply.document:
            return await message.reply("Ответь на .json файл истории.")

        data = await reply.download_media(bytes)
        try:
            parsed = json.loads(data.decode())
            if isinstance(parsed, list):
                cid = str(utils.get_chat_id(message))
                self.conversations[cid] = parsed
                self.db.set(self.strings["name"], "history", self.conversations)
                await message.reply(f"✅ Импортировано <b>{len(parsed)//2}</b> пар сообщений.")
            else:
                await message.reply("Некорректная структура файла.")
        except Exception as e:
            await message.reply(f"Ошибка парсинга: {e}")

    # ================= РОЛИ И ПРЕСЕТЫ =================

    @loader.command()
    async def grole(self, message):
        """<текст/пусто> - Установить системный промпт / характер (без текста для сброса)"""
        args = utils.get_args_raw(message)
        if not args:
            self.db.set(self.strings["name"], "system_role", None)
            return await message.reply("🎭 <b>Системная роль сброшена.</b>")
        self.db.set(self.strings["name"], "system_role", args)
        await message.reply(f"🎭 <b>Роль установлена:</b>\n<code>{utils.escape_html(args)}</code>")

    @loader.command()
    async def gpresets(self, message):
        """<save/load/del/list> - Управление пресетами системных инструкций"""
        args = utils.get_args_raw(message).split(maxsplit=2)
        if not args:
            return await message.reply(self.strings["gpresets_usage"])

        act = args[0].lower()
        if act == "list":
            if not self.prompt_presets:
                return await message.reply("📂 Пресетов нет.")
            txt = "📋 <b>Сохраненные пресеты:</b>\n"
            for k, v in self.prompt_presets.items():
                txt += f"• <code>{k}</code> ({len(v)} симв.)\n"
            return await message.reply(txt)

        if act == "save" and len(args) >= 3:
            name, body = args[1], args[2]
            self.prompt_presets[name] = body
            self.db.set(self.strings["name"], "presets", self.prompt_presets)
            return await message.reply(f"💾 Пресет <code>{name}</code> сохранен.")

        if act == "load" and len(args) >= 2:
            name = args[1]
            if name in self.prompt_presets:
                self.db.set(self.strings["name"], "system_role", self.prompt_presets[name])
                return await message.reply(f"✅ Загружен пресет <code>{name}</code>.")
            return await message.reply("🚫 Пресет не найден.")

        if act == "del" and len(args) >= 2:
            name = args[1]
            if self.prompt_presets.pop(name, None):
                self.db.set(self.strings["name"], "presets", self.prompt_presets)
                return await message.reply(f"🗑 Пресет <code>{name}</code> удален.")
            return await message.reply("🚫 Пресет не найден.")

        await message.reply(self.strings["gpresets_usage"])

    # ================= АВТООТВЕТЧИК И СТАТИСТИКА =================

    @loader.command()
    async def gauto(self, message):
        """- Включить/выключить автоответчик Gemini в текущем чате"""
        cid = utils.get_chat_id(message)
        if cid in self.auto_chats:
            self.auto_chats.remove(cid)
            await message.reply(self.strings["auto_off"])
        else:
            self.auto_chats.add(cid)
            await message.reply(self.strings["auto_on"].format(int(self.config["auto_chance"] * 100)))
        self.db.set(self.strings["name"], "auto_chats", list(self.auto_chats))

    @loader.command()
    async def gstats(self, message):
        """- Статистика использованных токенов и запросов за сессию"""
        await message.reply(
            f"📊 <b>Статистика GeminiAI:</b>\n"
            f"• Всего запросов: <code>{self.stats['calls']}</code>\n"
            f"• Токенов на вход: <code>{self.stats['in_tokens']}</code>\n"
            f"• Токенов на выход: <code>{self.stats['out_tokens']}</code>\n"
            f"• Суммарно токенов: <code>{self.stats['in_tokens'] + self.stats['out_tokens']}</code>"
        )

    @loader.watcher(only_incoming=True, ignore_edited=True)
    async def watcher(self, message):
        if not hasattr(message, "chat_id") or not message.text:
            return
        cid = utils.get_chat_id(message)
        if cid not in self.auto_chats:
            return
        if message.out or (isinstance(message.from_id, tg_types.PeerUser) and message.from_id.user_id == self.me.id):
            return
        sender = await message.get_sender()
        if isinstance(sender, tg_types.User) and sender.bot:
            return
        if random.random() > self.config["auto_chance"]:
            return

        keys = self._get_api_keys()
        if not keys:
            return

        try:
            client = self._get_client(keys[0])
            role = self.db.get(self.strings["name"], "system_role", "Веди себя как живой человек в Telegram, отвечай кратко и без официоза.")
            config = types.GenerateContentConfig(system_instruction=role, temperature=0.9)
            prompt = f"{get_display_name(sender)}: {message.text}"

            res = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config["chat_model"],
                contents=prompt,
                config=config,
            )
            if res.text:
                async with self.client.action(cid, "typing"):
                    await asyncio.sleep(min(8.0, max(1.5, len(res.text) * 0.04)))
                await message.reply(res.text)
        except Exception:
            pass

    # ================= ИНЛАЙН ОБРАБОТЧИК =================

    @loader.callback_handler()
    async def gemini_callback(self, call: InlineCall):
        data = call.data
        if data == "gnoop":
            return await call.answer()
        if data.startswith("gclose:"):
            uid = data.split(":")[1]
            self.pager_cache.pop(uid, None)
            return await call.delete()
        if data.startswith("gpage:"):
            _, uid, page = data.split(":")
            await self._render_page(uid, int(page), call=call)
