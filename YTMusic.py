# meta developer: @mxzavo
# meta banner: https://example.com/banner.jpg
# requires: ytmusicapi yt-dlp

import asyncio
import logging
import os
import tempfile
from typing import Optional

import yt_dlp
from telethon import functions
from telethon.tl.types import Message
from ytmusicapi import YTMusic

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class YTMusicMod(loader.Module):
    """YouTube Music + Now Playing + Downloader (Комбайн: Куки, OAuth или Анонимно)"""

    strings = {
        "name": "YTMusic",
        "now_playing": (
            "🎧 <b>{title}</b>\n"
            "👤 <b>{artist}</b>\n"
            "💿 {album}\n"
            "⏱ {duration}"
        ),
        "not_playing": "Сейчас ничего не играет или история пуста (или вы без авторизации)",
        "status_on": "✅ Авто-статус включён",
        "status_off": "❌ Авто-статус выключен",
        "downloading": "📥 Скачиваю <b>{title}</b>...",
        "downloaded": "✅ Готово",
        "search_results": "🔍 Результаты поиска:",
        "auth_help": (
            "<b>Режимы работы YTMusic:</b>\n\n"
            "1. <b>Куки браузера:</b> вставь строку кук в <code>.cfg YTMusic cookies</code>\n"
            "2. <b>OAuth:</b> укажи путь к файлу <code>oauth.json</code> в тот же конфиг\n"
            "3. <b>Анонимно:</b> оставь конфиг пустым (доступны поиск и скачивание, но нет истории и статуса)"
        ),
        "error": "❌ Ошибка: {error}",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "cookies",
                doc="Строка кук, путь к oauth.json или пусто для анонимного режима",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "auto_status",
                False,
                lambda: "Автоматически обновлять био (требует авторизацию)",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "status_template",
                "🎧 {title} — {artist}",
                lambda: "Шаблон статуса (макс ~70 символов)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "check_interval",
                50,
                lambda: "Интервал проверки текущего трека (секунды)",
                validator=loader.validators.Integer(minimum=20),
            ),
            loader.ConfigValue(
                "audio_format",
                "mp3",
                lambda: "Формат аудио (mp3/m4a/opus)",
                validator=loader.validators.Choice(["mp3", "m4a", "opus"]),
            ),
        )

        self.yt: Optional[YTMusic] = None
        self._status_task: Optional[asyncio.Task] = None
        self.last_track = None
        self._client = None

    async def client_ready(self, client, db):
        self._client = client
        await self._init_ytmusic()

        if self.config["auto_status"]:
            self._start_status_loop()

    async def _init_ytmusic(self):
        auth_data = self.config["cookies"]
        
        # Если конфиг пустой — инициализируем анонимный YTMusic
        if not auth_data or not auth_data.strip():
            try:
                self.yt = YTMusic()
                logger.info("YTMusic инициализирован в анонимном режиме")
            except Exception as e:
                logger.error(f"Ошибка анонимной инициализации YTMusic: {e}")
                self.yt = None
            return

        auth_data = auth_data.strip()

        # Если передан путь к файлу (например, oauth.json)
        if os.path.exists(auth_data) or auth_data.endswith(".json"):
            try:
                self.yt = YTMusic(auth_data)
                logger.info("YTMusic успешно инициализирован через файл (OAuth/Headers)")
                return
            except Exception as e:
                logger.error(f"Не удалось инициализировать через файл: {e}")

        # Иначе пробуем распарсить как строку кук
        path = None
        try:
            import json
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Content-Type": "application/json",
                "X-Goog-AuthUser": "0",
                "x-origin": "https://music.youtube.com",
                "Cookie": auth_data
            }
            
            fd, path = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(headers, f)

            self.yt = YTMusic(path)
            logger.info("YTMusic успешно инициализирован через строку кук")
        except Exception as e:
            logger.error(f"Ошибка инициализации YTMusic по кукам: {e}")
            self.yt = None
        finally:
            if path and os.path.exists(path):
                os.remove(path)

    def _start_status_loop(self):
        if self._status_task and not self._status_task.done():
            self._status_task.cancel()
        self._status_task = asyncio.create_task(self._status_loop())

    async def _status_loop(self):
        while self.config["auto_status"]:
            try:
                track = await self._get_current_track()
                if track and track != self.last_track:
                    self.last_track = track
                    status = self.config["status_template"].format(**track)[:70]
                    await self._client(functions.account.UpdateProfileRequest(about=status))
            except Exception as e:
                logger.warning(f"Ошибка в status loop (возможно, нужен аккаунт): {e}")

            await asyncio.sleep(self.config["check_interval"])

    async def _get_current_track(self) -> Optional[dict]:
        if not self.yt:
            return None

        try:
            history = await utils.run_sync(self.yt.get_history)
            if not history:
                return None

            item = history[0]
            artists = ", ".join(a["name"] for a in item.get("artists", [])) or "Unknown"

            return {
                "title": item.get("title", "Unknown"),
                "artist": artists,
                "album": item.get("album", {}).get("name", "") if item.get("album") else "",
                "videoId": item.get("videoId"),
                "duration": item.get("duration", ""),
                "url": f"https://music.youtube.com/watch?v={item.get('videoId')}" if item.get("videoId") else "",
            }
        except Exception as e:
            logger.error(f"Ошибка получения истории (нужна авторизация): {e}")
            return None

    async def npcmd(self, message: Message):
        """Показать текущий трек / управление авто-статусом"""
        args = utils.get_args_raw(message).lower()

        if args in {"on", "вкл", "1"}:
            self.config["auto_status"] = True
            self._start_status_loop()
            return await utils.answer(message, self.strings["status_on"])

        if args in {"off", "выкл", "0"}:
            self.config["auto_status"] = False
            if self._status_task:
                self._status_task.cancel()
            return await utils.answer(message, self.strings["status_off"])

        if not self.yt:
            return await utils.answer(message, "❌ Модуль не инициализирован")

        track = await self._get_current_track()
        if not track:
            return await utils.answer(message, self.strings["not_playing"])

        text = self.strings["now_playing"].format(**track)
        await utils.answer(message, text)

    async def ytauthcmd(self, message: Message):
        """Информация о режимах работы"""
        await utils.answer(message, self.strings["auth_help"])

    async def ytacmd(self, message: Message):
        """Скачать аудио (текущий трек или по запросу/ссылке)"""
        if not self.yt:
            return await utils.answer(message, "❌ Модуль не инициализирован")

        args = utils.get_args_raw(message)
        url = None
        title = "трек"

        if not args:
            track = await self._get_current_track()
            if not track or not track.get("videoId"):
                return await utils.answer(message, "❌ Укажи поисковый запрос или включи трек в аккаунте")
            url = track["url"]
            title = track["title"]
        else:
            if "youtube.com" in args or "youtu.be" in args or "music.youtube.com" in args:
                url = args
            else:
                try:
                    results = await utils.run_sync(self.yt.search, args, filter="songs")
                    if not results:
                        return await utils.answer(message, "Ничего не найдено")
                    url = f"https://music.youtube.com/watch?v={results[0]['videoId']}"
                    title = results[0].get("title", args)
                except Exception as e:
                    return await utils.answer(message, self.strings["error"].format(error=str(e)))

        msg = await utils.answer(message, self.strings["downloading"].format(title=title))

        try:
            file_path = await self._download_audio(url)
            await message.client.send_file(
                message.peer_id,
                file_path,
                caption=f"🎧 {title}",
                reply_to=message.id,
            )
            await msg.delete()
            os.remove(file_path)
        except Exception as e:
            await utils.answer(msg, self.strings["error"].format(error=str(e)))

    async def _download_audio(self, url: str) -> str:
        cookie_file = None
        auth_data = self.config["cookies"]
        
        # Если в конфиге строка кук — формируем временный файл для yt-dlp
        if auth_data and "=" in auth_data and not auth_data.endswith(".json") and not os.path.exists(auth_data):
            fd, cookie_file = tempfile.mkstemp(suffix=".txt")
            os.close(fd)
            with open(cookie_file, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for cookie in auth_data.split(";"):
                    if "=" in cookie:
                        name, value = cookie.strip().split("=", 1)
                        f.write(f".youtube.com\tTRUE\t/\tTRUE\t2147483647\t{name}\t{value}\n")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": tempfile.gettempdir() + "/%(title)s.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": self.config["audio_format"],
                "preferredquality": "320",
            }],
            "quiet": True,
            "no_warnings": True,
        }

        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await utils.run_sync(ydl.extract_info, url, download=True)
                filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(filename)
                return base + f".{self.config['audio_format']}"
        finally:
            if cookie_file and os.path.exists(cookie_file):
                os.remove(cookie_file)

    async def ytscmd(self, message: Message):
        """Поиск по YouTube Music"""
        args = utils.get_args_raw(message)
        if not args:
            return await utils.answer(message, "Укажи поисковый запрос")

        if not self.yt:
            return await utils.answer(message, "❌ Модуль не инициализирован")

        try:
            results = await utils.run_sync(self.yt.search, args, filter="songs")
            if not results:
                return await utils.answer(message, "Ничего не найдено")

            text = self.strings["search_results"] + "\n\n"
            for i, item in enumerate(results[:8], 1):
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                text += f"{i}. <b>{item['title']}</b> — {artists}\n"

            await utils.answer(message, text)
        except Exception as e:
            await utils.answer(message, self.strings["error"].format(error=str(e)))
