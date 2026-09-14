# -*- coding: utf-8 -*-
# meta developer: @mxzavo
# requires: yt-dlp

import asyncio
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .. import loader, utils


@loader.tds
class UniversalDownloadMod(loader.Module):
    """Universal Downloader"""

    strings = {
        "name": "UniversalDownload",

        "usage": (
            "📥 <b>Использование:</b>\n\n"
            "<code>.dl &lt;ссылка&gt;</code> — скачать ссылку\n"
            "<code>.dl</code> — скачать Telegram-медиа ответом\n"
            "<code>.dlcancel</code> — отменить загрузку"
        ),

        "start": "⏳ <b>Начинаю загрузку...</b>",
        "download": "📥 <b>Скачиваю...</b>",
        "convert": "⚙️ <b>Конвертирую видео...</b>",
        "send": "📤 <b>Отправляю файл...</b>",
        "cancel": "❌ <b>Загрузка отменена.</b>",
        "no_task": "ℹ️ <b>Активной загрузки нет.</b>",
        "bad_url": "❌ <b>Укажи HTTP/HTTPS-ссылку.</b>",
        "html": "❌ <b>Ссылка ведёт на веб-страницу, а не на файл.</b>",
        "error": "❌ <b>Ошибка:</b>\n<code>{}</code>",
    }

    def __init__(self):
        self.task = None
        self.tmpdir = None

    # =========================
    # UTILS
    # =========================

    def _has_ffmpeg(self):
        return shutil.which("ffmpeg") is not None

    async def _cleanup(self):
        if self.tmpdir and os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)

        self.tmpdir = None

    def _files(self):
        if not self.tmpdir:
            return []

        return [
            p for p in Path(self.tmpdir).rglob("*")
            if p.is_file()
        ]

    def _guess_type(self, path):
        mime, _ = mimetypes.guess_type(str(path))

        if mime:
            if mime.startswith("video/"):
                return "video"

            if mime.startswith("image/"):
                return "image"

            if mime.startswith("audio/"):
                return "audio"

        ext = Path(path).suffix.lower()

        if ext in {
            ".mp4", ".mkv", ".webm", ".mov", ".avi",
            ".flv", ".m4v", ".ts", ".3gp"
        }:
            return "video"

        if ext in {
            ".jpg", ".jpeg", ".png", ".webp",
            ".gif", ".bmp", ".tiff"
        }:
            return "image"

        if ext in {
            ".mp3", ".m4a", ".aac", ".flac",
            ".ogg", ".opus", ".wav", ".webm"
        }:
            return "audio"

        return "document"

    # =========================
    # YT-DLP
    # =========================

    async def _ytdlp(self, url):
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "yt-dlp не установлен."
            )

        if not self._has_ffmpeg():
            raise RuntimeError(
                "FFmpeg не найден в PATH Heroku."
            )

        output = str(
            Path(self.tmpdir) /
            "%(title).100s [%(id)s].%(ext)s"
        )

        options = {
            "outtmpl": output,

            "noplaylist": True,

            "quiet": False,
            "no_warnings": False,

            "restrictfilenames": False,

            "retries": 5,
            "fragment_retries": 5,

            # Лучшее видео + лучшее аудио.
            "format": "bv*+ba/b",

            # Всегда просим итоговый MP4.
            "merge_output_format": "mp4",

            # Не оставлять исходные потоки.
            "keepvideo": False,

            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            },

            "postprocessors": [
                {
                    "key": "FFmpegVideoRemuxer",
                    "preferedformat": "mp4",
                }
            ],
        }

        loop = asyncio.get_running_loop()

        def worker():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(
                    url,
                    download=True
                )

                files = self._files()

                if not files:
                    filename = ydl.prepare_filename(info)
                    candidate = Path(filename)

                    if candidate.exists():
                        return candidate

                    raise RuntimeError(
                        "yt-dlp не создал файл."
                    )

                # Не выбираем временные .part-файлы.
                files = [
                    f for f in files
                    if not f.name.endswith(".part")
                ]

                if not files:
                    raise RuntimeError(
                        "После загрузки файл не найден."
                    )

                # Берём самый большой файл.
                files.sort(
                    key=lambda x: x.stat().st_size,
                    reverse=True
                )

                return files[0]

        return await loop.run_in_executor(
            None,
            worker
        )

    # =========================
    # VIDEO CONVERSION
    # =========================

    async def _convert_video(self, source):
        if not self._has_ffmpeg():
            raise RuntimeError(
                "FFmpeg не найден."
            )

        source = Path(source)

        # Если уже MP4, всё равно приводим
        # к совместимому Telegram-варианту.
        target = (
            Path(self.tmpdir) /
            "telegram_video.mp4"
        )

        command = [
            "ffmpeg",
            "-y",

            "-i",
            str(source),

            # H.264
            "-c:v",
            "libx264",

            # Совместимый pixel format
            "-pix_fmt",
            "yuv420p",

            # Хорошее качество.
            "-crf",
            "23",

            # AAC audio.
            "-c:a",
            "aac",

            "-b:a",
            "192k",

            # Быстрый старт MP4.
            "-movflags",
            "+faststart",

            str(target),
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await process.communicate()

        if process.returncode != 0:
            error = stderr.decode(
                errors="ignore"
            )[-2000:]

            raise RuntimeError(
                "FFmpeg не смог обработать видео:\n"
                + error
            )

        if not target.exists():
            raise RuntimeError(
                "FFmpeg не создал MP4."
            )

        return target

    # =========================
    # AUDIO CONVERSION
    # =========================

    async def _convert_audio(self, source):
        if not self._has_ffmpeg():
            return source

        source = Path(source)

        target = (
            Path(self.tmpdir) /
            "audio.m4a"
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

            str(target),
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, _ = await process.communicate()

        if process.returncode != 0:
            return source

        if target.exists():
            return target

        return source

    # =========================
    # DIRECT HTTP FILE
    # =========================

    async def _http_download(self, url):
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=30,
            sock_read=120,
        )

        headers = {
            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/140.0 Safari/537.36"
        }

        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
        ) as session:

            async with session.get(
                url,
                allow_redirects=True,
            ) as response:

                response.raise_for_status()

                content_type = (
                    response.headers
                    .get("Content-Type", "")
                    .lower()
                )

                # HTML — это не файл.
                if (
                    "text/html" in content_type
                    or "application/xhtml" in content_type
                ):
                    raise RuntimeError(
                        "Ссылка ведёт на HTML-страницу."
                    )

                filename = None

                # Content-Disposition
                disposition = response.headers.get(
                    "Content-Disposition",
                    ""
                )

                if "filename=" in disposition:
                    filename = (
                        disposition
                        .split("filename=", 1)[1]
                        .strip()
                        .strip('"')
                        .strip("'")
                    )

                if not filename:
                    filename = Path(
                        urlparse(
                            str(response.url)
                        ).path
                    ).name

                if not filename:
                    filename = "download"

                # Безопасное имя.
                filename = os.path.basename(
                    filename
                )

                output = (
                    Path(self.tmpdir) /
                    filename
                )

                with open(
                    output,
                    "wb"
                ) as file:

                    async for chunk in (
                        response.content
                        .iter_chunked(1024 * 1024)
                    ):
                        file.write(chunk)

        if not output.exists():
            raise RuntimeError(
                "Файл не был скачан."
            )

        return output

    # =========================
    # PROCESS URL
    # =========================

    async def _process_url(
        self,
        url,
        message,
    ):
        self.tmpdir = tempfile.mkdtemp(
            prefix="universal_dl_"
        )

        await message.edit(
            self.strings["download"]
        )

        # Сначала yt-dlp.
        try:
            file = await self._ytdlp(url)

        except Exception as ytdlp_error:
            # Если yt-dlp не смог обработать
            # ссылку — пробуем прямой файл.
            try:
                file = await self._http_download(
                    url
                )

            except Exception:
                raise RuntimeError(
                    "Не удалось скачать ссылку.\n\n"
                    + str(ytdlp_error)[-1200:]
                )

        if not file or not file.exists():
            raise RuntimeError(
                "Файл загрузить не удалось."
            )

        file_type = self._guess_type(file)

        # Видео → гарантированный MP4.
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

        # После конвертации определяем заново.
        file_type = self._guess_type(file)

        return file, file_type

    # =========================
    # .DL
    # =========================

    @loader.command()
    async def dl(self, message):
        """<ссылка> — скачать видео, фото, аудио или файл"""

        self.task = asyncio.current_task()

        args = utils.get_args_raw(
            message
        ).strip()

        # -------------------------
        # Telegram reply
        # -------------------------

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
                self.tmpdir = tempfile.mkdtemp(
                    prefix="telegram_dl_"
                )

                await message.edit(
                    self.strings["download"]
                )

                file = await reply.download_media(
                    file=self.tmpdir
                )

                if not file:
                    raise RuntimeError(
                        "Не удалось скачать Telegram-медиа."
                    )

                file = Path(file)

                file_type = self._guess_type(
                    file
                )

                # Видео.
                if file_type == "video":
                    await message.edit(
                        self.strings["convert"]
                    )

                    file = await self._convert_video(
                        file
                    )

                    file_type = "video"

                # Аудио.
                elif file_type == "audio":
                    await message.edit(
                        self.strings["convert"]
                    )

                    file = await self._convert_audio(
                        file
                    )

                    file_type = self._guess_type(
                        file
                    )

                await message.edit(
                    self.strings["send"]
                )

                kwargs = {}

                if file_type == "video":
                    kwargs["supports_streaming"] = True

                # force_document=False позволяет
                # Telegram определить медиа.
                kwargs["force_document"] = False

                await message.client.send_file(
                    message.chat_id,
                    str(file),
                    caption=reply.text or None,
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
                            str(e)[:1500]
                        )
                    )
                except Exception:
                    pass

            finally:
                await self._cleanup()
                self.task = None

            return

        # -------------------------
        # No arguments
        # -------------------------

        if not args:
            await utils.answer(
                message,
                self.strings["usage"]
            )

            self.task = None
            return

        url = args.split()[0].strip()

        # -------------------------
        # URL validation
        # -------------------------

        if not url.startswith(
            ("http://", "https://")
        ):
            await utils.answer(
                message,
                self.strings["bad_url"]
            )

            self.task = None
            return

        # -------------------------
        # Download
        # -------------------------

        try:

            await message.edit(
                self.strings["start"]
            )

            file, file_type = (
                await self._process_url(
                    url,
                    message
                )
            )

            await message.edit(
                self.strings["send"]
            )

            kwargs = {
                "force_document": False
            }

            if file_type == "video":
                kwargs[
                    "supports_streaming"
                ] = True

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
                        str(e)[:1500]
                    )
                )
            except Exception:
                pass

        finally:

            await self._cleanup()

            self.task = None

    # =========================
    # CANCEL
    # =========================

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
