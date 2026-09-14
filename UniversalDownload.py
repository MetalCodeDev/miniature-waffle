# -*- coding: utf-8 -*-
# meta developer: @mxzavo
# requires: yt-dlp

import asyncio
import mimetypes
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .. import loader, utils


@loader.tds
class DownloaderMod(loader.Module):
    """Universal Downloader"""

    strings = {
        "name": "Downloader",

        "usage": (
            "📥 <b>Использование:</b>\n\n"
            "<code>.dl &lt;ссылка&gt;</code>\n"
            "<code>.dl</code> — ответом на Telegram-медиа"
        ),

        "start": "⏳ <b>Начинаю загрузку...</b>",
        "download": "📥 <b>Скачиваю...</b>",
        "convert": "⚙️ <b>Обрабатываю файл...</b>",
        "send": "📤 <b>Отправляю...</b>",
        "done": "✅ <b>Готово.</b>",
        "cancel": "❌ <b>Загрузка отменена.</b>",
        "no_task": "ℹ️ <b>Активной загрузки нет.</b>",
        "bad_url": "❌ <b>Укажи корректную HTTP/HTTPS-ссылку.</b>",
        "html": "❌ <b>Ссылка ведёт на веб-страницу, а не на файл.</b>",
        "ffmpeg": "❌ <b>FFmpeg не найден на сервере.</b>",
        "error": "❌ <b>Ошибка:</b>\n<code>{}</code>",
    }

    def __init__(self):
        self.task = None
        self.tmpdir = None

    # --------------------------------------------------
    # Utils
    # --------------------------------------------------

    def _has_ffmpeg(self):
        return shutil.which("ffmpeg") is not None

    async def _cleanup(self):
        if self.tmpdir and os.path.exists(self.tmpdir):
            shutil.rmtree(
                self.tmpdir,
                ignore_errors=True
            )

        self.tmpdir = None

    def _find_files(self):
        if not self.tmpdir:
            return []

        return [
            p for p in Path(self.tmpdir).rglob("*")
            if p.is_file()
        ]

    def _guess_type(self, path):
        mime, _ = mimetypes.guess_type(str(path))

        if not mime:
            return "document"

        if mime.startswith("video/"):
            return "video"

        if mime.startswith("image/"):
            return "image"

        if mime.startswith("audio/"):
            return "audio"

        return "document"

    # --------------------------------------------------
    # yt-dlp
    # --------------------------------------------------

    async def _ytdlp(self, url):
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "Не установлен yt-dlp."
            )

        output = str(
            Path(self.tmpdir) / "%(title).100s-%(id)s.%(ext)s"
        )

        options = {
            "outtmpl": output,

            "noplaylist": True,

            "quiet": True,
            "no_warnings": True,

            "restrictfilenames": True,

            "retries": 3,
            "fragment_retries": 3,

            # Предпочитаем нормальное видео.
            "format": (
                "bv*[ext=mp4]+ba[ext=m4a]/"
                "bv*[ext=mp4]+ba/"
                "b[ext=mp4]/"
                "best"
            ),

            "merge_output_format": "mp4",

            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/130.0 Safari/537.36"
                )
            },
        }

        loop = asyncio.get_running_loop()

        def worker():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(
                    url,
                    download=True
                )

                requested = info.get(
                    "requested_downloads"
                )

                # Получаем реальный итоговый файл.
                files = self._find_files()

                if not files:
                    filename = ydl.prepare_filename(info)
                    candidate = Path(filename)

                    if candidate.exists():
                        return candidate

                # Не возвращаем случайный файл.
                if files:
                    files.sort(
                        key=lambda x: x.stat().st_size,
                        reverse=True
                    )
                    return files[0]

                raise RuntimeError(
                    "yt-dlp не создал файл."
                )

        return await loop.run_in_executor(
            None,
            worker
        )

    # --------------------------------------------------
    # FFmpeg
    # --------------------------------------------------

    async def _convert_video(self, source):
        if not self._has_ffmpeg():
            raise RuntimeError(
                "FFmpeg не установлен."
            )

        target = (
            Path(self.tmpdir)
            / "video_converted.mp4"
        )

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),

            # Видео
            "-c:v",
            "libx264",

            # Аудио
            "-c:a",
            "aac",

            # Совместимость
            "-pix_fmt",
            "yuv420p",

            "-movflags",
            "+faststart",

            str(target)
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        _, stderr = await process.communicate()

        if process.returncode != 0:
            error = stderr.decode(
                errors="ignore"
            )[-1000:]

            raise RuntimeError(
                "FFmpeg не смог обработать видео:\n"
                + error
            )

        if not target.exists():
            raise RuntimeError(
                "FFmpeg не создал MP4."
            )

        return target

    async def _convert_audio(self, source):
        if not self._has_ffmpeg():
            return source

        target = (
            Path(self.tmpdir)
            / "audio.m4a"
        )

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(target)
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        _, stderr = await process.communicate()

        if process.returncode != 0:
            return source

        return target if target.exists() else source

    # --------------------------------------------------
    # Direct HTTP
    # --------------------------------------------------

    async def _http(self, url):
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=30,
            sock_read=60
        )

        async with aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        ) as session:

            async with session.get(
                url,
                allow_redirects=True
            ) as response:

                response.raise_for_status()

                content_type = (
                    response.headers
                    .get("Content-Type", "")
                    .lower()
                )

                # Не скачиваем HTML-страницу.
                if (
                    "text/html" in content_type
                    or "application/xhtml" in content_type
                ):
                    raise RuntimeError(
                        "Ссылка ведёт на HTML-страницу."
                    )

                name = Path(
                    urlparse(
                        str(response.url)
                    ).path
                ).name

                if not name:
                    name = "download"

                output = (
                    Path(self.tmpdir) / name
                )

                with open(
                    output,
                    "wb"
                ) as file:

                    async for chunk in response.content.iter_chunked(
                        512 * 1024
                    ):
                        file.write(chunk)

        if not output.exists():
            raise RuntimeError(
                "Файл не был скачан."
            )

        return output

    # --------------------------------------------------
    # Processing
    # --------------------------------------------------

    async def _process(self, url, message):
        self.tmpdir = tempfile.mkdtemp(
            prefix="downloader_"
        )

        # Сначала yt-dlp.
        try:
            await message.edit(
                self.strings["download"]
            )

            file = await self._ytdlp(url)

        except Exception as ytdlp_error:
            # Только после неудачи пробуем прямой файл.
            try:
                file = await self._http(url)

            except Exception:
                raise RuntimeError(
                    "Не удалось скачать ссылку.\n\n"
                    + str(ytdlp_error)[-700:]
                )

        if not file or not file.exists():
            raise RuntimeError(
                "Файл загрузить не удалось."
            )

        file_type = self._guess_type(file)

        # Видео → MP4.
        if file_type == "video":
            await message.edit(
                self.strings["convert"]
            )

            file = await self._convert_video(
                file
            )

        # Аудио → M4A.
        elif file_type == "audio":
            await message.edit(
                self.strings["convert"]
            )

            file = await self._convert_audio(
                file
            )

        return file, file_type

    # --------------------------------------------------
    # Command
    # --------------------------------------------------

    @loader.command()
    async def dl(self, message):
        """<ссылка> — скачать медиа или файл"""

        args = utils.get_args_raw(
            message
        ).strip()

        self.task = asyncio.current_task()

        # ----------------------------------------------
        # Telegram reply
        # ----------------------------------------------

        if not args and message.is_reply:
            reply = await message.get_reply_message()

            if not reply or not reply.media:
                await utils.answer(
                    message,
                    self.strings["usage"]
                )

                self.task = None
                return

            try:
                await message.edit(
                    self.strings["download"]
                )

                self.tmpdir = tempfile.mkdtemp(
                    prefix="downloader_tg_"
                )

                file = await reply.download_media(
                    file=self.tmpdir
                )

                if not file:
                    raise RuntimeError(
                        "Не удалось скачать Telegram-медиа."
                    )

                file = Path(file)
                file_type = self._guess_type(file)

                # Если Telegram дал видео —
                # делаем совместимый MP4.
                if file_type == "video":
                    await message.edit(
                        self.strings["convert"]
                    )

                    file = await self._convert_video(
                        file
                    )

                await message.edit(
                    self.strings["send"]
                )

                await message.client.send_file(
                    message.chat_id,
                    str(file),
                    caption=reply.text or None,
                    supports_streaming=True
                    if file_type == "video"
                    else False
                )

                await message.delete()

            except asyncio.CancelledError:
                await message.edit(
                    self.strings["cancel"]
                )

            except Exception as e:
                try:
                    await message.edit(
                        self.strings["error"].format(
                            str(e)[:1000]
                        )
                    )
                except Exception:
                    pass

            finally:
                await self._cleanup()
                self.task = None

            return

        # ----------------------------------------------
        # URL
        # ----------------------------------------------

        if not args:
            await utils.answer(
                message,
                self.strings["usage"]
            )

            self.task = None
            return

        url = args.split()[0]

        if not url.startswith(
            ("http://", "https://")
        ):
            await utils.answer(
                message,
                self.strings["bad_url"]
            )

            self.task = None
            return

        try:
            await message.edit(
                self.strings["start"]
            )

            file, file_type = await self._process(
                url,
                message
            )

            await message.edit(
                self.strings["send"]
            )

            kwargs = {}

            if file_type == "video":
                kwargs["supports_streaming"] = True

            if file_type == "audio":
                kwargs["voice_note"] = False

            await message.client.send_file(
                message.chat_id,
                str(file),
                **kwargs
            )

            await message.delete()

        except asyncio.CancelledError:
            try:
                await message.edit(
                    self.strings["cancel"]
                )
            except Exception:
                pass

        except Exception as e:
            try:
                await message.edit(
                    self.strings["error"].format(
                        str(e)[:1000]
                    )
                )
            except Exception:
                pass

        finally:
            await self._cleanup()
            self.task = None

    # --------------------------------------------------
    # Cancel
    # --------------------------------------------------

    @loader.command()
    async def dlcancel(self, message):
        """— отменить текущую загрузку"""

        if (
            self.task
            and not self.task.done()
        ):
            self.task.cancel()

            await utils.answer(
                message,
                self.strings["cancel"]
            )
        else:
            await utils.answer(
                message,
                self.strings["no_task"]
            )
