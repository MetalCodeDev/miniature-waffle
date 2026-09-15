# scope heroku_min: 2.0.0
# meta developer: @QVR0X
# meta pic: https://github.com/hikariatama/assets/raw/master/1326-command-window-line-flat.webp
# meta banner: https://github.com/hikariatama/assets/raw/master/1326-command-window-line-flat.webp

__version__ = ("7", "0", "0")

"""
🤖 AdvancedGemini v7.0 — Продвинутый AI модуль с памятью и 11 командами.

Команды:
  .ai <промпт> — генерация с сохранением контекста
  .aicode <описание> — генерация Python кода
  .aiidea — случайная идея для проекта
  .aiwrite <тема> — написать статью
  .aianalyze <текст> — анализ текста
  .aitrans <текст> — перевод
  .aifix <текст> — улучшить текст
  .aihistory — история диалога
  .aisys <инструкция> — системная инструкция
  .aiclear — очистить историю
  .aiset <ключ> — установить API ключ
  .aihelp — справка
  .aiinfo — статус модуля

Используется: Google Gemini API (бесплатный)
Автор: @QVR0X
"""

from .. import loader, utils
import aiohttp
import json
from datetime import datetime
from typing import Optional, List, Dict


@loader.tds
class AdvancedGeminiMod(loader.Module):
    """💎 AdvancedGemini — Продвинутый AI модуль с памятью и контекстом"""

    strings = {
        "name": "AdvancedGemini",
        "loading": "🤖 <b>Генерирую ответ...</b>",
        "error": "❌ <b>Ошибка при обращении к AI.</b>",
        "no_key": "❌ <b>API ключ не установлен!</b>\n\n"
                 "1️⃣ Получи ключ: https://aistudio.google.com/app/apikey\n"
                 "2️⃣ Установи: <code>.aiset AIzaSy...</code>\n",
        "key_saved": "✅ <b>API ключ сохранён!</b>",
        "memory_cleared": "🧹 <b>История очищена.</b>",
        "sys_set": "🎯 <b>Системная инструкция установлена.</b>",
        "question": "💬 <b>Запрос:</b>",
        "response": "✨ <b>Gemini:</b>",
        "memory_status": "🧠 <b>Память:</b> [{}/{}]",
        "tokens": "🔢 <b>Токены:</b> {}",
        "time": "⏱️ <b>Время:</b> {}сек",
    }

    strings_ru = {
        "name": "ПродвинутыйЖемини",
        "loading": "🤖 <b>Генерирую ответ...</b>",
        "error": "❌ <b>Ошибка при обращении к AI.</b>",
        "no_key": "❌ <b>API ключ не установлен!</b>\n\n"
                 "1️⃣ Получи ключ: https://aistudio.google.com/app/apikey\n"
                 "2️⃣ Установи: <code>.aiset AIzaSy...</code>\n",
        "key_saved": "✅ <b>API ключ сохранён!</b>",
        "memory_cleared": "🧹 <b>История очищена.</b>",
        "sys_set": "🎯 <b>Системная инструкция установлена.</b>",
        "question": "💬 <b>Запрос:</b>",
        "response": "✨ <b>Gemini:</b>",
        "memory_status": "🧠 <b>Память:</b> [{}/{}]",
        "tokens": "🔢 <b>Токены:</b> {}",
        "time": "⏱️ <b>Время:</b> {}сек",
    }

    def __init__(self):
        self.session = None
        self.api_key = None
        self.conversations = {}  # {chat_id: [{"role": "user"/"model", "content": "text"}]}
        self.system_instruction = None
        self.max_history = 10  # Максимум пар вопрос-ответ в памяти

    async def client_ready(self, client, db):
        self.session = aiohttp.ClientSession()
        self.db = db
        self.api_key = db.get(self.strings["name"], "api_key", None)
        self.system_instruction = db.get(self.strings["name"], "system_instruction", None)
        self.conversations = db.get(self.strings["name"], "conversations", {})

    async def on_unload(self):
        if self.session:
            await self.session.close()

    def _get_chat_id(self, message) -> str:
        """Получить ID чата для сохранения истории"""
        return str(message.chat_id)

    def _get_conversation(self, chat_id: str) -> List[Dict]:
        """Получить историю диалога"""
        return self.conversations.get(chat_id, [])

    def _add_to_history(self, chat_id: str, role: str, content: str):
        """Добавить сообщение в историю"""
        if chat_id not in self.conversations:
            self.conversations[chat_id] = []
        
        self.conversations[chat_id].append({
            "role": role,
            "content": content
        })
        
        # Ограничиваем размер истории
        if len(self.conversations[chat_id]) > self.max_history * 2:
            self.conversations[chat_id] = self.conversations[chat_id][-self.max_history * 2:]
        
        self.db.set(self.strings["name"], "conversations", self.conversations)

    async def _call_gemini(self, prompt: str, chat_id: str, max_tokens: int = 2000) -> tuple:
        """Обращение к Google Gemini API с контекстом истории"""
        if not self.api_key:
            return None, None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        # Строим историю
        history = self._get_conversation(chat_id)
        contents = []

        # Добавляем прошлые сообщения
        for msg in history[-self.max_history:]:  # Только последние N пар
            contents.append({
                "role": "user" if msg["role"] == "user" else "model",
                "parts": [{"text": msg["content"]}]
            })

        # Добавляем текущий запрос
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7
            }
        }

        # Добавляем системную инструкцию если она есть
        if self.system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": self.system_instruction}]
            }

        try:
            async with self.session.post(
                url, 
                json=payload, 
                headers=headers, 
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status in (401, 403):
                    return None, None
                if resp.status != 200:
                    return None, None
                
                data = await resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return None, None
                
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if not parts:
                    return None, None
                
                text = parts[0].get("text", "")
                usage = data.get("usageMetadata", {})
                
                # Сохраняем в историю
                self._add_to_history(chat_id, "user", prompt)
                self._add_to_history(chat_id, "model", text)
                
                return text, usage
        except Exception as e:
            return None, None

    @loader.command(ru_doc="<API_ключ> — установить Google Gemini API ключ")
    async def aiset(self, message):
        """<api_key> - set Google Gemini API key"""
        key = utils.get_args_raw(message).strip()
        if not key:
            await utils.answer(message, "❌ <b>Укажи API ключ:</b>\n<code>.aiset AIzaSy...</code>")
            return

        self.api_key = key
        self.db.set(self.strings["name"], "api_key", key)
        await utils.answer(message, self.strings("key_saved"))

    @loader.command(ru_doc="<промпт> — генерация текста с сохранением контекста")
    async def ai(self, message):
        """<prompt> - generate text with conversation memory"""
        if not self.api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        prompt = utils.get_args_raw(message)
        if not prompt:
            await utils.answer(message, "❌ <b>Укажи промпт:</b>\n<code>.ai напиши смешной рассказ</code>")
            return

        chat_id = self._get_chat_id(message)
        status_msg = await utils.answer(message, self.strings("loading"))

        import time
        start_time = time.time()
        response, usage = await self._call_gemini(prompt, chat_id)
        elapsed = time.time() - start_time

        if not response:
            await utils.answer(message, self.strings("error"))
            return

        # Обрезаем длинные ответы
        if len(response) > 4000:
            response = response[:3990] + "\n\n<i>... (обрезано)</i>"

        # Формируем ответ с красивым форматированием
        msg = f"<b>{self.strings('question')}</b>\n<code>{utils.escape_html(prompt[:200])}</code>\n\n"
        msg += f"<b>{self.strings('response')}</b>\n{utils.escape_html(response)}\n\n"
        
        # Добавляем метаинформацию
        history = self._get_conversation(chat_id)
        mem_status = self.strings("memory_status").format(len(history) // 2, self.max_history)
        msg += f"<i>{mem_status} • ⏱️ {elapsed:.1f}сек</i>"

        if usage:
            tokens = usage.get("totalTokenCount", 0)
            if tokens:
                msg += f" • <code>{tokens} токен</code>"

        await utils.answer(message, msg)

    @loader.command(ru_doc="— очистить историю диалога")
    async def aiclear(self, message):
        """- clear conversation memory"""
        chat_id = self._get_chat_id(message)
        if chat_id in self.conversations:
            del self.conversations[chat_id]
        self.db.set(self.strings["name"], "conversations", self.conversations)
        await utils.answer(message, self.strings("memory_cleared"))

    @loader.command(ru_doc="<инструкция> — задать системную инструкцию (промпт)")
    async def aisys(self, message):
        """<instruction> - set system instruction"""
        instruction = utils.get_args_raw(message)
        if not instruction:
            if self.system_instruction:
                await utils.answer(message, f"🎯 <b>Текущая инструкция:</b>\n<code>{utils.escape_html(self.system_instruction[:500])}</code>")
            else:
                await utils.answer(message, "❌ <b>Нет установленной инструкции.</b>")
            return

        self.system_instruction = instruction
        self.db.set(self.strings["name"], "system_instruction", instruction)
        await utils.answer(message, self.strings("sys_set"))

    @loader.command(ru_doc="<описание> — генерация Python кода")
    async def aicode(self, message):
        """<description> - generate Python code"""
        if not self.api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        description = utils.get_args_raw(message)
        if not description:
            await utils.answer(message, "❌ <b>Укажи что нужно:</b>\n<code>.aicode функция сортировки списка</code>")
            return

        prompt = f"Напиши чистый, оптимизированный код на Python для: {description}\n\nВозвращай ТОЛЬКО код без объяснений!"
        chat_id = self._get_chat_id(message)
        
        await utils.answer(message, self.strings("loading"))
        
        import time
        start_time = time.time()
        response, usage = await self._call_gemini(prompt, chat_id, max_tokens=2500)
        elapsed = time.time() - start_time

        if not response:
            await utils.answer(message, self.strings("error"))
            return

        if len(response) > 4000:
            response = response[:3990] + "\n..."

        msg = f"💻 <b>Код:</b>\n<code>{utils.escape_html(response)}</code>\n\n"
        msg += f"<i>⏱️ {elapsed:.1f}сек</i>"
        
        await utils.answer(message, msg)

    @loader.command(ru_doc="— случайная идея для проекта")
    async def aiidea(self, message):
        """- generate a random project idea"""
        if not self.api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        prompt = "Предложи одну УНИКАЛЬНУЮ и креативную идею для IT проекта, стартапа или приложения. Напиши кратко, ярко, с деталями реализации (2-4 предложения)."
        chat_id = self._get_chat_id(message)
        
        await utils.answer(message, self.strings("loading"))
        
        import time
        start_time = time.time()
        response, usage = await self._call_gemini(prompt, chat_id, max_tokens=600)
        elapsed = time.time() - start_time

        if not response:
            await utils.answer(message, self.strings("error"))
            return

        msg = f"💡 <b>Идея проекта:</b>\n{utils.escape_html(response)}\n\n"
        msg += f"<i>⏱️ {elapsed:.1f}сек</i>"
        
        await utils.answer(message, msg)

    @loader.command(ru_doc="— показать историю диалога")
    async def aihistory(self, message):
        """- show conversation history"""
        chat_id = self._get_chat_id(message)
        history = self._get_conversation(chat_id)
        
        if not history:
            await utils.answer(message, "📭 <b>История диалога пуста.</b>")
            return
        
        msg = "<b>📜 История диалога:</b>\n\n"
        for i, item in enumerate(history[-10:], 1):  # Показываем последние 10
            role = "👤 Ты" if item["role"] == "user" else "🤖 AI"
            content = item["content"][:100] + ("..." if len(item["content"]) > 100 else "")
            msg += f"{i}. {role}: <code>{utils.escape_html(content)}</code>\n"
        
        msg += f"\n<i>Всего: {len(history)} сообщений</i>"
        await utils.answer(message, msg)

    @loader.command(ru_doc="<тема> — написать статью/текст на тему")
    async def aiwrite(self, message):
        """<topic> - write an article or essay"""
        if not self.api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        topic = utils.get_args_raw(message)
        if not topic:
            await utils.answer(message, "❌ <b>Укажи тему:</b>\n<code>.aiwrite История древнего Рима</code>")
            return

        prompt = f"Напиши подробную, интересную и информативную статью на тему: '{topic}'\n\nСтруктура: введение, 3-4 основных пункта, заключение. Формат: HTML с тегами <b>, <i>."
        chat_id = self._get_chat_id(message)
        
        await utils.answer(message, self.strings("loading"))
        
        import time
        start_time = time.time()
        response, usage = await self._call_gemini(prompt, chat_id, max_tokens=3000)
        elapsed = time.time() - start_time

        if not response:
            await utils.answer(message, self.strings("error"))
            return

        if len(response) > 4000:
            response = response[:3990] + "\n\n<i>... (текст обрезан)</i>"

        msg = f"📝 <b>Статья:</b>\n{utils.escape_html(response)}\n\n"
        msg += f"<i>⏱️ {elapsed:.1f}сек</i>"
        
        await utils.answer(message, msg)

    @loader.command(ru_doc="<текст> — анализ текста (ключевые идеи, тон, и т.д.)")
    async def aianalyze(self, message):
        """<text> - analyze text"""
        if not self.api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        text = utils.get_args_raw(message)
        if not text:
            await utils.answer(message, "❌ <b>Укажи текст для анализа.</b>")
            return

        prompt = f"""Проанализируй этот текст:
"{text}"

Дай анализ по пунктам:
• Основная идея
• Тон (формальный/неформальный/нейтральный)
• Целевая аудитория
• Ключевые слова
• Рекомендации по улучшению"""

        chat_id = self._get_chat_id(message)
        
        await utils.answer(message, self.strings("loading"))
        
        import time
        start_time = time.time()
        response, usage = await self._call_gemini(prompt, chat_id, max_tokens=1000)
        elapsed = time.time() - start_time

        if not response:
            await utils.answer(message, self.strings("error"))
            return

        msg = f"🔍 <b>Анализ:</b>\n{utils.escape_html(response)}\n\n"
        msg += f"<i>⏱️ {elapsed:.1f}сек</i>"
        
        await utils.answer(message, msg)

    @loader.command(ru_doc="<текст> — перевод текста (определяет язык автоматически)")
    async def aitrans(self, message):
        """<text> - translate text"""
        if not self.api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        text = utils.get_args_raw(message)
        if not text:
            await utils.answer(message, "❌ <b>Укажи текст для перевода.</b>")
            return

        prompt = f"""Переведи этот текст на русский язык (если он на русском, то на английский).
Текст: "{text}"

Верни ТОЛЬКО перевод, без объяснений."""

        chat_id = self._get_chat_id(message)
        
        await utils.answer(message, self.strings("loading"))
        
        import time
        start_time = time.time()
        response, usage = await self._call_gemini(prompt, chat_id, max_tokens=1000)
        elapsed = time.time() - start_time

        if not response:
            await utils.answer(message, self.strings("error"))
            return

        msg = f"🌐 <b>Перевод:</b>\n<code>{utils.escape_html(response)}</code>\n\n"
        msg += f"<i>⏱️ {elapsed:.1f}сек</i>"
        
        await utils.answer(message, msg)

    @loader.command(ru_doc="<промпт> — режим \"Улучшить текст\" (для редактирования)")
    async def aifix(self, message):
        """<text> - improve/fix text"""
        if not self.api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        text = utils.get_args_raw(message)
        if not text:
            await utils.answer(message, "❌ <b>Укажи текст для улучшения.</b>")
            return

        prompt = f"""Улучши этот текст:
- Исправь грамматику и пунктуацию
- Сделай более читаемым
- Улучши стиль
- Убери лишнее

Текст: "{text}"

Верни ТОЛЬКО улучшенный текст."""

        chat_id = self._get_chat_id(message)
        
        await utils.answer(message, self.strings("loading"))
        
        import time
        start_time = time.time()
        response, usage = await self._call_gemini(prompt, chat_id, max_tokens=1500)
        elapsed = time.time() - start_time

        if not response:
            await utils.answer(message, self.strings("error"))
            return

        msg = f"✏️ <b>Улучшенный текст:</b>\n{utils.escape_html(response)}\n\n"
        msg += f"<i>⏱️ {elapsed:.1f}сек</i>"
        
        await utils.answer(message, msg)

    @loader.command(ru_doc="— список всех доступных команд")
    async def aihelp(self, message):
        """- show all available commands"""
        msg = "<b>🤖 Все команды Advanced Gemini v7.0:</b>\n\n"
        
        msg += "<b>💬 Основное:</b>\n"
        msg += "• <code>.ai &lt;промпт&gt;</code> - генерация с контекстом\n"
        msg += "• <code>.aisys &lt;инструкция&gt;</code> - задать стиль AI\n"
        msg += "• <code>.aihistory</code> - история диалога\n"
        msg += "• <code>.aiclear</code> - очистить историю\n\n"
        
        msg += "<b>💻 Код и структура:</b>\n"
        msg += "• <code>.aicode &lt;описание&gt;</code> - генерация Python кода\n"
        msg += "• <code>.aiwrite &lt;тема&gt;</code> - написать статью\n"
        msg += "• <code>.aiidea</code> - идея для проекта\n\n"
        
        msg += "<b>✏️ Текст:</b>\n"
        msg += "• <code>.aifix &lt;текст&gt;</code> - улучшить текст\n"
        msg += "• <code>.aitrans &lt;текст&gt;</code> - перевод\n"
        msg += "• <code>.aianalyze &lt;текст&gt;</code> - анализ текста\n\n"
        
        msg += "<b>⚙️ Управление:</b>\n"
        msg += "• <code>.aiset &lt;ключ&gt;</code> - установить API ключ\n"
        msg += "• <code>.aiinfo</code> - статус модуля\n"
        msg += "• <code>.aihelp</code> - эта справка\n"
        
        await utils.answer(message, msg)
