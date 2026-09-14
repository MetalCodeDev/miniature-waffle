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

        if process.returncode !=
