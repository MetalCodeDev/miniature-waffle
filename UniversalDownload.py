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
        "convert": "⚙️ <b>Конвертирую...</b>",
        "send": "📤 <b>Отправляю...</b>",
        "cancel": "❌ <b>Загрузка отменена.</b>",
        "no_task": "ℹ️ <b>Активной загрузки нет.</b>",
        "bad_url": "❌ <b>Укажи HTTP/HTTPS-ссылку.</b>",
        "error": "❌ <b>Ошибка:</b>\n<code>{}</code>",
    }

    def __init__(self):
        self.task = None
        self.tmpdir = None

    def _has_ffmpeg(self):
        return shutil.which("ffmpeg") is not None

    def _get_files(self):
        if not self.tmpdir:
            return []

        return [
            p
            for p in Path(self.tmpdir).rglob("*")
            if p.is_file()
            and not p.name.endswith((".part", ".ytdl"))
        ]

    def _guess_type(self, path):
        mime, _ = mimetypes.guess_type(str(path))
        ext = Path(path).suffix.lower()

        if mime:
            if mime.startswith("video/"):
                return "video"

            if mime.startswith("image/"):
                return "image"

            if mime.startswith("audio/"):
                return "audio"

        if ext in {
            ".mp4", ".mkv", ".webm", ".mov",
            ".avi", ".flv", ".m4v", ".ts", ".3gp"
        }:
            return "video"

        if ext in {
            ".jpg", ".jpeg", ".png", ".webp",
            ".gif", ".bmp", ".tiff"
        }:
            return "image"

        if ext in {
            ".mp3", ".m4a", ".aac", ".flac",
            ".ogg", ".opus", ".wav"
        }:
            return "audio"

        return "document"

    async def _cleanup(self):
        if self.tmpdir:
            shutil.rmtree(
                self.tmpdir,
                ignore_errors=True
            )
            self.tmpdir = None

    async def _ytdlp(self, url):
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError(
                "yt-dlp не установлен."
            ) from exc

        if not self._has_ffmpeg():
            raise RuntimeError(
                "FFmpeg не найден в PATH."
            )

        output = str(
            Path(self.tmpdir)
            / "%(title).100s [%(id)s].%(ext)s"
        )

        options = {
            "outtmpl": output,
            "noplaylist": True,

            # Лучшее видео + лучшее аудио.
            "format": "bv*+ba/b",

            # После объединения — MP4.
            "merge_output_format": "mp4",

            "retries": 5,
            "fragment_retries": 5,

            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": False,

            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/140.0 Safari/537.36"
                )
            },
        }

        loop = asyncio.get_running_loop()

        def worker():
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.extract_info(
                    url,
                    download=True
                )

                files = self._get_files()

                if not files:
                    raise RuntimeError(
                        "yt-dlp не создал файл."
                    )

                files.sort(
                    key=lambda item: item.stat().st_size,
                    reverse=True
                )

                return files[0]

        return await loop.run_in_executor(
            None,
            worker
        )

    async def _convert_video(self, source):
        if not self._has_ffmpeg():
            raise RuntimeError(
                "FFmpeg не найден в PATH."
            )

        target = (
            Path(self.tmpdir)
            / "telegram_video.mp4"
        )

        command = [
            "ffmpeg",
            "-y",

            "-i",
            str(source),

            "-map",
            "0:v:0",

            "-map",
            "0:a:0?",

            # H.264.
            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-crf",
            "23",

            "-pix_fmt",
            "yuv420p",

            # AAC.
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
            details = stderr.decode(
                errors="ignore"
            )[-1500:]

            raise RuntimeError(
                "FFmpeg ошибка:\n"
                + details
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

            str(target),
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, _ = await process.communicate()

        if (
            process.returncode == 0
            and target.exists()
        ):
            return target

        return source

    async def _http_download(self, url):
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=30,
            sock_read=120,
        )

        headers = {
            "User-Agent": "Mozilla/5.0"
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

                if (
                    "text/html" in content_type
                    or "application/xhtml" in content_type
                ):
                    raise RuntimeError(
                        "Ссылка ведёт на HTML-страницу."
                    )

                filename = Path(
                    urlparse(
                        str(response.url)
                    ).path
                ).name

                if not filename:
                    filename = "download"

                filename = os.path.basename(
                    filename
                )

                output = (
                    Path(self.tmpdir)
                    / filename
                )

                with open(
                    output,
                    "wb"
                ) as file:

                    async for chunk in (
                        response.content
                        .iter_chunked(
                            1024 * 1024
                        )
                    ):
                        file.write(chunk)

        if not output.exists():
            raise RuntimeError(
                "Файл не был скачан."
            )

        return output

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

        ytdlp_error = None

        try:
            file = await self._ytdlp(url)

        except Exception as exc:
            ytdlp_error = exc

            try:
                file = await self._http_download(
                    url
                )

            except Exception:
                raise RuntimeError(
                    "Не удалось скачать ссылку.\n\n"
                    + str(ytdlp_error)[-1200:]
                )

        file_type = self._guess_type(
            file
        )

        if file_type == "video":
            await message.edit(
                self.strings["convert"]
            )

            file = await self._convert_video(
                file
            )

        elif file_type == "audio":
            await message.edit(
                self.strings["convert"]
            )

            file = await self._convert_audio(
                file
            )

        return (
            file,
            self._guess_type(file)
        )

    async def _send_file(
        self,
        message,
        file,
        file_type,
        caption=None,
    ):
        kwargs = {
            "force_document": (
                file_type == "document"
            )
        }

        if file_type == "video":
            kwargs[
                "supports_streaming"
            ] = True

        await message.client.send_file(
            message.chat_id,
            str(file),
            caption=caption,
            **kwargs,
        )

    @loader.command()
    async def dl(self, message):
        """<ссылка> — скачать видео, фото, аудио или файл"""

        self.task = asyncio.current_task()

        args = utils.get_args_raw(
            message
        ).strip()

        # Telegram-медиа ответом
        if not args and message.is_reply:

            reply = await message.get_reply_message()

            if not reply or not reply.media:
                await utils.answer(
                    message,
                    self.strings["usage"]
                )

                self.task = None
                return

            self.tmpdir = tempfile.mkdtemp(
                prefix="telegram_dl_"
            )

            try:
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

                if file_type == "video":
                    await message.edit(
                        self.strings["convert"]
                    )

                    file = await self._convert_video(
                        file
                    )

                    file_type = "video"

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

                await self._send_file(
                    message,
                    file,
                    file_type,
                    caption=reply.text or None,
                )

                await message.delete()

            except asyncio.CancelledError:
                try:
                    await message.edit(
                        self.strings["cancel"]
                    )
                except Exception:
                    pass

            except Exception as exc:
                try:
                    await message.edit(
                        self.strings["error"].format(
                            str(exc)[:1500]
                        )
                    )
                except Exception:
                    pass

            finally:
                await self._cleanup()
                self.task = None

            return

        # Нет аргументов
        if not args:
            await utils.answer(
                message,
                self.strings["usage"]
            )

            self.task = None
            return

        url = args.split()[0].strip()

        if not url.startswith(
            ("http://", "https://")
        ):
            await utils.answer(
                message,
                self.strings["bad_url"]
            )

            self.task = None
            return

        self.tmpdir = None

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

            await self._send_file(
                message,
                file,
                file_type
            )

            await message.delete()

        except asyncio.CancelledError:
            try:
                await message.edit(
                    self.strings["cancel"]
                )
            except Exception:
                pass

        except Exception as exc:
            try:
                await message.edit(
                    self.strings["error"].format(
                        str(exc)[:1500]
                    )
                )
            except Exception:
                pass

        finally:
            await self._cleanup()
            self.task = None

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