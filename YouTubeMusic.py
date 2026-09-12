# meta developer: @PlayBoyCart4
# scope: heroku_only
# requires: yt-dlp, ytmusicapi, pillow, requests

import asyncio
import os
import tempfile
import logging
import io
import json
from pathlib import Path
from datetime import datetime

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class YouTubeMusicMod(loader.Module):
    """YouTube Music audio downloader with now playing support."""

    strings = {
        "name": "YouTubeMusic",
        "search": "🔎 <b>Ищу:</b> <code>{}</code>",
        "download": "⬇️ <b>Скачиваю:</b> <code>{}</code>",
        "done": "🎵 <b>Готово.</b>",
        "added": "➕ <b>Трек добавлен.</b>",
        "no_query": "❌ <b>Укажи название трека или ссылку.</b>",
        "error": "❌ <b>Ошибка:</b>\n<code>{}</code>",
        "now_playing": "🎵 <b>Слушаю сейчас:</b>\n<b>{artist}</b>\n<code>{title}</code>\n⏱️ <code>{progress}/{duration}</code>",
        "not_playing": "⏸️ <b>Сейчас ничего не слушаю или история пуста.</b>",
        "yt_music_error": "❌ <b>Ошибка YouTube Music:</b>\n<code>{}</code>",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ytmusic_client = None

    async def client_ready(self, client, db):
        """Инициализация при запуске."""
        await self._init_ytmusic()

    async def _init_ytmusic(self):
        """Инициализировать YouTube Music клиент."""
        try:
            from ytmusicapi import YTMusic
        except ImportError:
            logger.warning("ytmusicapi не установлен. Команда .whoami будет недоступна.")
            return

        try:
            # Попытка загрузить сохраненные headers/auth данные
            auth_file = os.getenv("YTMUSIC_AUTH_FILE", "ytmusic_auth.json")
            
            if os.path.exists(auth_file):
                self.ytmusic_client = YTMusic(auth_file)
                logger.info("YouTube Music клиент инициализирован с сохраненной авторизацией")
            else:
                # Если нет файла авторизации, пытаемся создать без авторизации (ограничено)
                self.ytmusic_client = YTMusic()
                logger.info("YouTube Music клиент инициализирован без авторизации")
        except Exception as e:
            logger.error(f"Ошибка инициализации YouTube Music: {e}")
            self.ytmusic_client = None

    def _format_duration(self, ms: int) -> str:
        """Преобразовать миллисекунды в mm:ss."""
        try:
            total_seconds = int(ms) // 1000
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}:{seconds:02d}"
        except:
            return "0:00"

    async def _download_image(self, url: str) -> bytes:
        """Загрузить изображение с URL."""
        try:
            import requests
            response = await asyncio.to_thread(
                lambda: requests.get(url, timeout=10)
            )
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"Ошибка загрузки изображения: {e}")
            return None

    async def _create_now_playing_image(self, now_playing: dict) -> bytes:
        """Создать изображение с информацией о текущем треке."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.warning("Pillow не установлен")
            return None

        try:
            # Загружаем обложку
            cover_data = None
            if now_playing.get("thumbnail"):
                cover_data = await self._download_image(now_playing["thumbnail"])

            # Если нет обложки, создаем пустой фон
            if cover_data:
                cover_image = Image.open(io.BytesIO(cover_data)).convert("RGB")
                # Оптимизируем размер
                cover_image.thumbnail((400, 400), Image.Resampling.LANCZOS)
                width, height = cover_image.size
            else:
                width, height = 400, 400
                cover_image = Image.new("RGB", (width, height), color=(30, 30, 30))

            # Создаем финальное изображение с информацией
            final_height = height + 180
            final_image = Image.new("RGB", (width, final_height), color=(20, 20, 20))

            # Вставляем обложку
            final_image.paste(cover_image, (0, 0))

            # Добавляем текст
            draw = ImageDraw.Draw(final_image)

            try:
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
                font_artist = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except:
                font_title = ImageFont.load_default()
                font_artist = ImageFont.load_default()
                font_small = ImageFont.load_default()

            y_offset = height + 10

            # Артист
            artist_text = now_playing.get("artist", "Unknown")[:50]
            draw.text((10, y_offset), artist_text, fill=(100, 200, 255), font=font_artist)

            # Трек
            title_text = now_playing.get("title", "Unknown")[:40]
            draw.text((10, y_offset + 25), title_text, fill=(255, 255, 255), font=font_title)

            # Время
            progress_str = self._format_duration(now_playing.get("duration", 0))
            time_text = f"🎵 YouTube Music"
            draw.text((10, y_offset + 50), time_text, fill=(150, 150, 150), font=font_small)

            # Сохраняем в памяти
            buffer = io.BytesIO()
            final_image.save(buffer, format="PNG")
            buffer.seek(0)
            return buffer.getvalue()

        except Exception as e:
            logger.error(f"Ошибка создания изображения: {e}")
            return None

    async def _download(self, query: str, directory: str):
        """Загрузить аудиофайл с YouTube."""
        try:
            import yt_dlp
        except ImportError as error:
            raise RuntimeError(
                "Не установлен yt-dlp. Перезагрузи модуль после установки зависимости."
            ) from error

        output = str(
            Path(directory) / "%(title).120s.%(ext)s"
        )

        options = {
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": output,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
        }

        if not query.startswith(("http://", "https://")):
            query = f"ytsearch1:{query}"

        def download():
            with yt_dlp.YoutubeDL(options) as ydl:
                try:
                    logger.debug(f"Начинаю загрузку: {query}")
                    info = ydl.extract_info(
                        query,
                        download=True,
                    )

                    if info and "entries" in info:
                        info = next(
                            (item for item in info["entries"] if item),
                            None,
                        )

                    if not info:
                        raise RuntimeError(
                            "Не удалось найти трек."
                        )

                    return ydl.prepare_filename(info)
                except Exception as e:
                    logger.error(f"Ошибка yt-dlp: {e}")
                    raise RuntimeError(f"Ошибка загрузки: {e}") from e

        try:
            filepath = await asyncio.wait_for(
                asyncio.to_thread(download),
                timeout=300
            )
        except asyncio.TimeoutError:
            raise RuntimeError("Загрузка заняла слишком много времени (>5 мин)")

        if os.path.isfile(filepath):
            # Проверка размера файла
            max_size_mb = 50
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > max_size_mb:
                os.remove(filepath)
                raise RuntimeError(
                    f"Файл слишком большой ({file_size_mb:.1f}MB > {max_size_mb}MB)"
                )
            return filepath

        # Резервный поиск файла (на случай если путь не совпадает)
        files = sorted(
            (path for path in Path(directory).iterdir() if path.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not files:
            raise RuntimeError(
                "yt-dlp не создал аудиофайл."
            )

        return str(files[0])

    async def _process_download(
        self,
        message,
        query: str,
        caption: str,
        show_download_status: bool = True,
    ):
        """Общий метод для обработки загрузки и отправки файла.
        
        Args:
            message: Сообщение от пользователя
            query: Запрос (название или ссылка)
            caption: Подпись для отправляемого файла
            show_download_status: Показывать ли промежуточный статус "Скачиваю"
        """
        if not query or not query.strip():
            await utils.answer(
                message,
                self.strings["no_query"],
            )
            return

        status = await utils.answer(
            message,
            self.strings["search"].format(
                utils.escape_html(query)
            ),
        )

        with tempfile.TemporaryDirectory(
            prefix="heroku_yt_"
        ) as temp:

            try:
                if show_download_status:
                    await utils.answer(
                        status,
                        self.strings["download"].format(
                            utils.escape_html(query)
                        ),
                    )

                filepath = await self._download(
                    query,
                    temp,
                )

                await message.client.send_file(
                    message.chat_id,
                    filepath,
                    caption=caption,
                )

                await status.delete()

            except Exception as error:
                logger.error(f"Ошибка при обработке загрузки: {error}")
                await utils.answer(
                    status,
                    self.strings["error"].format(
                        utils.escape_html(str(error))
                    ),
                )

    async def _get_now_playing_youtube_music(self):
        """Получить текущий/последний трек из YouTube Music."""
        if not self.ytmusic_client:
            return None

        try:
            # Получаем историю прослушивания (последние треки)
            history = await asyncio.to_thread(
                self.ytmusic_client.get_history
            )

            if not history or len(history) == 0:
                return None

            # Берем первый (последний проигранный) трек
            track = history[0]

            return {
                "title": track.get("title", "Unknown"),
                "artist": track.get("artists", [{"name": "Unknown"}])[0].get("name", "Unknown") if track.get("artists") else "Unknown",
                "duration": track.get("duration_seconds", 0),
                "thumbnail": track.get("thumbnail", [{"url": None}])[0].get("url") if track.get("thumbnail") else None,
                "is_playing": True,  # YouTube Music API не показывает статус, предполагаем играет
            }
        except Exception as e:
            logger.error(f"Ошибка YouTube Music API: {e}")
            return None

    @loader.command(
        ru_doc="Показать последний трек: .whoami"
    )
    async def whoamicmd(self, message):
        """Show what you recently listened to on YouTube Music."""
        
        status = await utils.answer(
            message,
            "⏳ <b>Проверяю YouTube Music...</b>"
        )

        try:
            now_playing = await self._get_now_playing_youtube_music()

            if not now_playing:
                await utils.answer(
                    status,
                    self.strings["not_playing"],
                )
                return

            # Создаем красивое изображение
            image_data = await self._create_now_playing_image(now_playing)

            if image_data:
                await message.client.send_file(
                    message.chat_id,
                    image_data,
                    caption="🎵 Последний трек",
                )
                await status.delete()
            else:
                # Если не удалось создать изображение, отправляем текст
                duration_str = self._format_duration(now_playing["duration"])

                text = self.strings["now_playing"].format(
                    artist=utils.escape_html(now_playing["artist"]),
                    title=utils.escape_html(now_playing["title"]),
                    progress=duration_str,
                    duration=duration_str,
                )

                await utils.answer(
                    status,
                    f"🎵 {text}"
                )

        except Exception as error:
            logger.error(f"Ошибка whoami: {error}")
            await utils.answer(
                status,
                self.strings["yt_music_error"].format(
                    utils.escape_html(str(error))
                ),
            )

    @loader.command(
        ru_doc="Скачать трек: .yt <название или ссылка>"
    )
    async def ytcmd(self, message):
        """Download audio from YouTube / YouTube Music."""

        query = utils.get_args_raw(message).strip()

        if not query:
            await utils.answer(
                message,
                self.strings["no_query"],
            )
            return

        await self._process_download(
            message,
            query,
            self.strings["done"],
            show_download_status=True,
        )

    @loader.command(
        ru_doc="Скачать трек: .ytadd <название или ссылка>"
    )
    async def ytaddcmd(self, message):
        """Download a track using .ytadd."""

        query = utils.get_args_raw(message).strip()

        # Если нет аргументов, пытаемся получить текст из ответа
        if not query:
            reply = await message.get_reply_message()

            if reply and reply.message:
                query = reply.message.strip()

        if not query:
            await utils.answer(
                message,
                self.strings["no_query"],
            )
            return

        await self._process_download(
            message,
            query,
            self.strings["added"],
            show_download_status=True,
        )
