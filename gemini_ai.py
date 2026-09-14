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
    """Максимально заряженный комбайн Gemini от @mxzavo: все команды, память, пресеты, ключи, медиа и автоответчик."""

    strings = {
        "name": "GeminiAI",
        "no_key": "🚫 <b>API-ключ(и) не заданы.</b> Укажи в конфиге: <code>.config GeminiAI api_key</code>",
        "no_prompt": "❓ <b>Укажи запрос или промпт.</b>",
        "no_reply_media": "❓ <b>Ответь командой на медиа (фото, файл, видео).</b>",
        "error": "🚫 <b>Ошибка:</b>\n<code>{}</code>",
        "generating": "🎨 <b>Генерирую изображение...</b>",
        "thinking": "🧠 <b>Думаю...</b>",
        "animating": "🎬 <b>Оживляю видео через Veo...</b>",
        "cleared": "🧹 <b>Память чата очищена.</b>",
        "gres_cleared": "🧹 <b>Вся память сброшена.</b>",
        "auto_on": "🎭 <b>Автоответчик включен в этом чате.</b>",
        "auto_off": "🎭 <b>Автоответчик выключен в этом чате.</b>",
    }

    TEXT_MIME_TYPES = {
        "text/plain", "text/markdown", "text/html", "text/css", "text/csv",
        "application/json", "application/xml", "application/x-python",
        "text/x-python", "application/javascript", "application/x-sh",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue("api_key", "", "API-ключи Google Gemini (можно через запятую)", validator=loader.validators.Hidden()),
            loader.ConfigValue("model_name", "gemini-2.5-pro", "Основная модель текста и анализа", validator=loader.validators.String()),
            loader.ConfigValue("image_model", "imagen-3.0-generate-002", "Модель генерации картинок", validator=loader.validators.String()),
            loader.ConfigValue("video_model", "veo-2.0-generate-001", "Модель анимации видео", validator=loader.validators.String()),
            loader.ConfigValue("max_history_length", 30, "Макс. пар сообщений в памяти (0 — без лимита)", validator=loader.validators.Integer(minimum=0)),
            loader.ConfigValue("global_memory", False, "Общая память для всех чатов", validator=loader.validators.Boolean()),
            loader.ConfigValue("temperature", 1.0, "Креативность (0.0 - 2.0)", validator=loader.validators.Float(minimum=0.0, maximum=2.0)),
            loader.ConfigValue("timezone", "Europe/Kyiv", "Часовой пояс", validator=loader.validators.String()),
            loader.ConfigValue("impersonation_chance", 0.2, "Шанс ответа автоответчика (0.0 - 1.0)", validator=loader.validators.Float(minimum=0.0, maximum=1.0)),
            loader.ConfigValue("proxy", "", "HTTP прокси (http://user:pass@host:port)", validator=loader.validators.String()),
        )
        self.conversations = {}
        self.auto_chats = set()
        self.prompt_presets = {}
        self.pager_cache = {}
        self.last_requests = {}
        self.stats = {"requests": 0, "tokens_in": 0, "tokens_out": 0}

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        self.me = await client.get_me()
        self.conversations = self.db.get(self.strings["name"], "history", {})
        self.auto_chats = set(self.db.get(self.strings["name"], "auto_chats", []))
        self.prompt_presets = self.db.get(self.strings["name"], "presets", {})
        self.stats = self.db.get(self.strings["name"], "stats", {"requests": 0, "tokens_in": 0, "tokens_out": 0})

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
                await call.edit("⚠️ <b>Сессия пагинации истекла.</b>")
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

    async def _prepare_parts(self, message, raw_text: str):
        parts, text_chunks = [], []
        reply = await message.get_reply_message()

        if reply and getattr(reply, "text", None):
            sender = await reply.get_sender()
            name = get_display_name(sender) if sender else "User"
            text_chunks.append(f"[{name}]: {reply.text}")

        if raw_text:
            text_chunks.append(raw_text)

        target = message if (message.media or message.sticker) else reply
        if target and (target.media or target.sticker):
            if target.sticker and getattr(target.sticker, "mime_type", "") == "application/x-tgsticker":
                alt = next((a.alt for a in target.sticker.attributes if isinstance(a, DocumentAttributeSticker)), "?")
                text_chunks.append(f"[Стикер: {alt}]")
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
                        text_chunks.insert(0, f"[Файл]:\n```\n{data.decode('utf-8', errors='ignore')}\n```")
                        data = None

                if data:
                    if mime.startswith(("image/", "audio/", "video/")):
                        parts.append(types.Part(inline_data=types.Blob(mime_type=mime, data=data)))

        full_text = "\n\n".join(text_chunks).strip()
        if full_text:
            parts.insert(0, types.Part(text=full_text))
        return parts

    # ================= ОСНОВНЫЕ КОМАНДЫ ЧАТА =================

    @loader.command()
    async def g(self, message):
        """[-s] <запрос/реплай> — Основной запрос к Gemini с памятью (-s включает поиск Google)"""
        await self._process_gemini_command(message)

    @loader.command()
    async def gemini(self, message):
        """[-s] <запрос/реплай> — Синоним команды .g"""
        await self._process_gemini_command(message)

    async def _process_gemini_command(self, message):
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
            parts = await self._prepare_parts(message, args)
            if not parts:
                return await status_msg.edit(self.strings["no_prompt"])

            chat_id = "global" if self.config["global_memory"] else str(utils.get_chat_id(message))
            hist = self.conversations.get(chat_id, [])

            contents = [types.Content(role=item["role"], parts=[types.Part(text=item["text"])]) for item in hist]
            contents.append(types.Content(role="user", parts=parts))

            sys_instruct = self.db.get(self.strings["name"], "system_role", None)
            try:
                tz = pytz.timezone(self.config["timezone"])
                now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
                sys_instruct = f"{sys_instruct}\n[Локальное время: {now}]" if sys_instruct else f"[Локальное время: {now}]"
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
                model=self.config["model_name"],
                contents=contents,
                config=gen_cfg,
            )
            elapsed = round(time.time() - t0, 1)

            out_text = res.text or "Пустой ответ."
            meta = getattr(res, "usage_metadata", None)
            in_t = getattr(meta, "prompt_token_count", 0) if meta else 0
            out_t = getattr(meta, "candidates_token_count", 0) if meta else 0

            self.stats["requests"] += 1
            self.stats["tokens_in"] += in_t
            self.stats["tokens_out"] += out_t
            self.db.set(self.strings["name"], "stats", self.stats)

            hist.append({"role": "user", "text": args or "[Медиа]"})
            hist.append({"role": "model", "text": out_text})
            max_h = self.config["max_history_length"] * 2
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
        """<запрос/реплай> — Разовый быстрый вопрос без сохранения в память"""
        args = utils.get_args_raw(message) or ""
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["thinking"])
        try:
            parts = await self._prepare_parts(message, args)
            if not parts:
                return await status_msg.edit(self.strings["no_prompt"])

            client = self._get_client(keys[0])
            res = await asyncio.to_thread(client.models.generate_content, model=self.config["model_name"], contents=parts)
            body = self._markdown_to_html(res.text or "Пустой ответ.")
            await message.reply(f"⚡️ <b>Быстрый ответ:</b>\n\n{body}")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def gsum(self, message):
        """[кол-во] — Саммари/выжимка последних сообщений чата"""
        args = utils.get_args_raw(message)
        count = int(args) if args and args.isdigit() else 50
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(f"📚 Читаю {count} сообщений чата...")
        try:
            msgs = await self.client.get_messages(message.chat_id, limit=count + 1)
            lines = [f"{get_display_name(m.sender) or 'User'}: {m.text or '[медиа]'}" for m in reversed(msgs) if m.id != message.id]
            dump = "\n".join(lines)
            prompt = f"Сделай краткую, понятную выжимку и анализ этого чата:\n\n{dump}"

            client = self._get_client(keys[0])
            res = await asyncio.to_thread(client.models.generate_content, model=self.config["model_name"], contents=prompt)
            body = self._markdown_to_html(res.text or "Пусто.")
            await message.reply(f"📊 <b>Саммари чата ({count} сообщ.):</b>\n\n{body}")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def gch(self, message):
        """<кол-во> <вопрос> — Задать вопрос по истории последних сообщений чата"""
        args = utils.get_args_raw(message).split(maxsplit=1)
        if len(args) < 2 or not args[0].isdigit():
            return await message.reply("ℹ️ Использование: <code>.gch <кол-во> <вопрос></code>")

        count, prompt_q = int(args[0]), args[1]
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(f"🔍 Анализирую {count} сообщений...")
        try:
            msgs = await self.client.get_messages(message.chat_id, limit=count + 1)
            lines = [f"{get_display_name(m.sender) or 'User'}: {m.text or '[медиа]'}" for m in reversed(msgs) if m.id != message.id]
            dump = "\n".join(lines)
            prompt = f"Ответь на вопрос по этому чату:\nВопрос: {prompt_q}\n\nЧАТ:\n{dump}"

            client = self._get_client(keys[0])
            res = await asyncio.to_thread(client.models.generate_content, model=self.config["model_name"], contents=prompt)
            body = self._markdown_to_html(res.text or "Пусто.")
            await message.reply(f"💬 <b>Ответ по чату:</b>\n\n{body}")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    # ================= ГЕНЕРАЦИЯ МЕДИА (ФОТО, ВИДЕО, МУЗЫКА) =================

    @loader.command()
    async def genimg(self, message):
        """<промпт> — Сгенерировать картинку через Imagen 3"""
        prompt = utils.get_args_raw(message)
        if not prompt:
            return await message.reply(self.strings["no_prompt"])
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply(self.strings["generating"])
        try:
            client = self._get_client(keys[0])
            res = await asyncio.to_thread(
                client.models.generate_images,
                model=self.config["image_model"],
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1),
            )
            if not res.generated_images:
                return await status_msg.edit("🚫 Картинка не вернулась.")

            photo = io.BytesIO(res.generated_images[0].image.image_bytes)
            photo.name = "gemini.png"
            await message.reply(file=photo, message=f"🎨 <code>{utils.escape_html(prompt[:100])}</code>")
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def animate(self, message):
        """<реплай на фото> [промпт] — Оживить картинку в видео через Veo"""
        reply = await message.get_reply_message()
        if not reply or not reply.media:
            return await message.reply(self.strings["no_reply_media"])

        prompt = utils.get_args_raw(message) or "Cinematic smooth motion"
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await reply.reply(self.strings["animating"])
        try:
            img_data = await reply.download_media(bytes)
            img = Image.open(io.BytesIO(img_data))
            client = self._get_client(keys[0])

            res = await asyncio.to_thread(client.models.generate_content, model=self.config["video_model"], contents=[img, prompt])
            vid_bytes = None
            if res.candidates:
                for p in res.candidates[0].content.parts:
                    if getattr(p, "inline_data", None) and "video" in p.inline_data.mime_type:
                        vid_bytes = p.inline_data.data
                        break

            if not vid_bytes:
                return await status_msg.edit("🚫 Видео не получено.")

            out = io.BytesIO(vid_bytes)
            out.name = "animated.mp4"
            await reply.reply(file=out)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    @loader.command()
    async def gmusic(self, message):
        """<промпт> — Сгенерировать музыку/аудио через Lyria"""
        prompt = utils.get_args_raw(message)
        if not prompt:
            return await message.reply("🎵 Укажи промпт для музыки.")
        keys = self._get_api_keys()
        if not keys:
            return await message.reply(self.strings["no_key"])

        status_msg = await message.reply("🎵 Создаю трек...")
        try:
            client = self._get_client(keys[0])
            inter = await asyncio.to_thread(client.interactions.create, model="lyria-3-clip-preview", input=prompt)
            audio_bytes = None
            for o in getattr(inter, "outputs", []) or []:
                if getattr(o, "type", "") == "audio" and getattr(o, "data", None):
                    audio_bytes = base64.b64decode(o.data)
                    break

            if not audio_bytes:
                return await status_msg.edit("🚫 Аудио не получено.")

            out = io.BytesIO(audio_bytes)
            out.name = "track.mp3"
            await message.reply(file=out, voice=True)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(self.strings["error"].format(utils.escape_html(str(e))))

    # ================= УПРАВЛЕНИЕ ПАМЯТЬЮ И ЭКСПОРТ =================

    @loader.command()
    async def gclear(self, message):
        """— Очистить историю текущего чата"""
        cid = "global" if self.config["global_memory"] else str(utils.get_chat_id(message))
        self.conversations.pop(cid, None)
        self.db.set(self.strings["name"], "history", self.conversations)
        await message.reply(self.strings["cleared"])

    @loader.command()
    async def gres(self, message):
        """— Сбросить память вообще везде"""
        self.conversations.clear()
        self.db.set(self.strings["name"], "history", {})
        await message.reply(self.strings["gres_cleared"])

    @loader.command()
    async def gmem(self, message):
        """— Показать статус памяти текущего чата"""
        cid = "global" if self.config["global_memory"] else str(utils.get_chat_id(message))
        hist = self.conversations.get(cid, [])
        await message.reply(f"🧠 В памяти чата: <b>{len(hist)//2}</b> пар сообщений.")

    @loader.command()
    async def gmemdel(self, message):
        """[N] — Удалить последние N пар сообщений из памяти"""
        try:
            n = int(utils.get_args_raw(message) or 1)
        except Exception:
            n = 1
        cid = "global" if self.config["global_memory"] else str(utils.get_chat_id(message))
        hist = self.conversations.get(cid, [])
        if n > 0 and len(hist) >= n * 2:
            self.conversations[cid] = hist[:-n * 2]
            self.db.set(self.strings["name"], "history", self.conversations)
            await message.reply(f"🧹 Удалено последних {n} пар.")
        else:
            await message.reply("Недостаточно истории.")

    @loader.command()
    async def gexport(self, message):
        """— Экспортировать историю чата в JSON файл"""
        cid = "global" if self.config["global_memory"] else str(utils.get_chat_id(message))
        hist = self.conversations.get(cid, [])
        if not hist:
            return await message.reply("История пуста.")
        bio = io.BytesIO(json.dumps(hist, ensure_ascii=False, indent=2).encode())
        bio.name = f"gemini_history_{cid}.json"
        await message.reply(file=bio, message="💾 <b>Экспорт истории Gemini</b>")

    @loader.command()
    async def gimport(self, message):
        """<реплай на JSON> — Импортировать историю в текущий чат"""
        reply = await message.get_reply_message()
        if not reply or not reply.document:
            return await message.reply("Ответь на json-файл.")
        data = await reply.download_media(bytes)
        try:
            parsed = json.loads(data.decode())
            if isinstance(parsed, list):
                cid = "global" if self.config["global_memory"] else str(utils.get_chat_id(message))
                self.conversations[cid] = parsed
                self.db.set(self.strings["name"], "history", self.conversations)
                await message.reply(f"✅ Импортировано пар: <b>{len(parsed)//2}</b>.")
            else:
                await message.reply("Неверный формат.")
        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    # ================= РОЛИ И ПРЕСЕТЫ =================

    @loader.command()
    async def grole(self, message):
        """<текст/пусто> — Задать системный промпт/характер (пусто для сброса)"""
        args = utils.get_args_raw(message)
        if not args:
            self.db.set(self.strings["name"], "system_role", None)
            return await message.reply("🎭 Роль сброшена.")
        self.db.set(self.strings["name"], "system_role", args)
        await message.reply(f"🎭 Роль установлена:\n<code>{utils.escape_html(args)}</code>")

    @loader.command()
    async def gpresets(self, message):
        """<save/load/del/list> — Управление пресетами ролей"""
        args = utils.get_args_raw(message).split(maxsplit=2)
        if not args:
            return await message.reply("ℹ️ Использование: <code>.gpresets save/load/del/list [имя] [текст]</code>")
        act = args[0].lower()
        if act == "list":
            if not self.prompt_presets:
                return await message.reply("📂 Пресетов нет.")
            txt = "📋 <b>Пресеты:</b>\n" + "\n".join(f"• <code>{k}</code>" for k in self.prompt_presets)
            return await message.reply(txt)
        if act == "save" and len(args) >= 3:
            self.prompt_presets[args[1]] = args[2]
            self.db.set(self.strings["name"], "presets", self.prompt_presets)
            return await message.reply(f"💾 Сохранен пресет <code>{args[1]}</code>.")
        if act == "load" and len(args) >= 2:
            if args[1] in self.prompt_presets:
                self.db.set(self.strings["name"], "system_role", self.prompt_presets[args[1]])
                return await message.reply(f"✅ Загружен пресет <code>{args[1]}</code>.")
            return await message.reply("🚫 Не найден.")
        if act == "del" and len(args) >= 2:
            if self.prompt_presets.pop(args[1], None):
                self.db.set(self.strings["name"], "presets", self.prompt_presets)
                return await message.reply(f"🗑 Удален пресет <code>{args[1]}</code>.")
            return await message.reply("🚫 Не найден.")
        await message.reply("Неверный синтаксис команды.")

    # ================= АВТООТВЕТЧИК И СТАТИСТИКА =================

    @loader.command()
    async def gauto(self, message):
        """— Включить/выключить фоновый автоответчик в чате"""
        cid = utils.get_chat_id(message)
        if cid in self.auto_chats:
            self.auto_chats.remove(cid)
            await message.reply(self.strings["auto_off"])
        else:
            self.auto_chats.add(cid)
            await message.reply(self.strings["auto_on"])
        self.db.set(self.strings["name"], "auto_chats", list(self.auto_chats))

    @loader.command()
    async def gstats(self, message):
        """— Показать статистику использования токенов"""
        await message.reply(
            f"📊 <b>Статистика GeminiAI:</b>\n"
            f"• Запросов: <code>{self.stats['requests']}</code>\n"
            f"• Токенов input: <code>{self.stats['tokens_in']}</code>\n"
            f"• Токенов output: <code>{self.stats['tokens_out']}</code>\n"
            f"• Всего токенов: <code>{self.stats['tokens_in'] + self.stats['tokens_out']}</code>"
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
        if random.random() > self.config["impersonation_chance"]:
            return

        keys = self._get_api_keys()
        if not keys:
            return

        try:
            client = self._get_client(keys[0])
            role = self.db.get(self.strings["name"], "system_role", "Общайся кратко и естественно как человек.")
            config = types.GenerateContentConfig(system_instruction=role, temperature=0.9)
            res = await asyncio.to_thread(client.models.generate_content, model=self.config["model_name"], contents=f"{get_display_name(sender)}: {message.text}", config=config)
            if res.text:
                async with self.client.action(cid, "typing"):
                    await asyncio.sleep(min(6.0, max(1.0, len(res.text) * 0.04)))
                await message.reply(res.text)
        except Exception:
            pass

    # ================= ИНЛАЙН =================

    @loader.callback_handler()
    async def gemini_callback(self, call: InlineCall):
        if call.data == "gnoop":
            return await call.answer()
        if call.data.startswith("gclose:"):
            self.pager_cache.pop(call.data.split(":")[1], None)
            return await call.delete()
        if call.data.startswith("gpage:"):
            _, uid, page = call.data.split(":")
            await self._render_page(uid, int(page), call=call)
