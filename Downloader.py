# -*- coding: utf-8 -*-
# meta developer: @mxzavo
# requires: yt-dlp

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .. import loader, utils


@loader.tds
class UniversalDownloaderMod(loader.Module):
    """Универсальный загрузчик — @mxzavo"""

    strings = {
        "name": "UniversalDownloader",

        "usage": (
            "<emoji> <b>Использование:</b>\n"
            "<code>.dl &lt;ссылка&gt;</code>\n"
            "<code>.dl</code> в ответ на медиа"
        ),

        "starting": "<emoji> <b>Подготавливаю загрузку...</b>",
        "downloading": "<emoji> <b>Загружаю...</b>",
        "sending": "<emoji> <b>Отправляю файл...</b>",
        "done": "<emoji> <b>Готово.</b>",
        "cancelled": "<emoji> <b>Загрузка отменена.</b>",
        "no_task": "<emoji> <b>Активной загрузки нет.</b>",
        "error": "<emoji> <b>Ошибка:</b> <code>{}</code>",
    }

    strings_ru = strings

    def __init__(self):
        self.task = None
        self.tmpdir = None

    async def _download_http(self, url, output):
        """Скачивание обычного файла по HTTP/HTTPS."""

        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=30,
            sock_read=60,
        )

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                allow_redirects=True,
            ) as response:

                response.raise_for_status()

                with open(output, "wb") as file:
                    async for chunk in response.content.iter_chunked(
                        1024 * 512
                    ):
                        file.write(chunk)

        return output

    async def _download_ytdlp(self, url, directory):
        """Скачивание через yt-dlp."""

        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "Не установлен yt-dlp. Установи зависимость yt-dlp."
            )

        output = os.path.join(
            directory,
            "%(title).120s-%(id)s.%(ext)s",
        )

        options = {
            "outtmpl": output,
            "noplaylist": True,

            "quiet": True,
            "no_warnings": True,

            "restrictfilenames": True,

            "retries": 3,
            "fragment_retries": 3,

            # Не объединяем огромные форматы без необходимости.
            "merge_output_format": "mp4",
        }

        loop = asyncio.get_running_loop()

        def worker():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(
                    url,
                    download=True,
                )

                filename = ydl.prepare_filename(info)

                # После merge yt-dlp может изменить расширение.
                possible = [
                    Path(filename),
                    Path(os.path.splitext(filename)[0] + ".mp4"),
                    Path(os.path.splitext(filename)[0] + ".mkv"),
                    Path(os.path.splitext(filename)[0] + ".webm"),
                ]

                for file in possible:
                    if file.exists():
                        return file

                return Path(filename)

        return await loop.run_in_executor(
            None,
            worker,
        )

    async def _cleanup(self):
        """Удаляет временные файлы."""

        if self.tmpdir and os.path.exists(self.tmpdir):
            try:
                shutil.rmtree(
                    self.tmpdir,
                    ignore_errors=True,
                )
            except Exception:
                pass

        self.tmpdir = None

    async def _process_url(self, url, message):
        """Определяет способ загрузки."""

        self.tmpdir = tempfile.mkdtemp(
            prefix="heroku_dl_"
        )

        # Сначала пробуем yt-dlp.
        try:
            await message.edit(
                self.strings["downloading"]
            )

            file = await self._download_ytdlp(
                url,
                self.tmpdir,
            )

            if file and file.exists():
                return file

        except Exception:
            # Если yt-dlp не смог обработать ссылку,
            # пробуем обычный HTTP downloader.
            pass

        # Fallback: обычный HTTP/HTTPS файл.
        filename = Path(
            urlparse(url).path
        ).name

        if not filename:
            filename = "download"

        output = Path(self.tmpdir) / filename

        await self._download_http(
            url,
            output,
        )

        if not output.exists():
            raise RuntimeError(
                "Файл не был загружен."
            )

        return output

    @loader.command()
    async def dl(self, message):
        """<url> — скачать файл/медиа"""

        args = utils.get_args_raw(
            message
        ).strip()

        # ==========================================
        # Telegram media через reply
        # ==========================================

        if not args and message.is_reply:
            reply = await message.get_reply_message()

            if not reply or not reply.media:
                await utils.answer(
                    message,
                    self.strings["usage"],
                )
                return

            self.task = asyncio.current_task()

            try:
                await message.edit(
                    self.strings["downloading"]
                )

                self.tmpdir = tempfile.mkdtemp(
                    prefix="heroku_tg_"
                )

                file = await reply.download_media(
                    file=self.tmpdir
                )

                if not file:
                    raise RuntimeError(
                        "Не удалось скачать медиа."
                    )

                await message.edit(
                    self.strings["sending"]
                )

                await message.client.send_file(
                    message.chat_id,
                    file,
                    caption=reply.text or None,
                )

                await message.delete()

            except asyncio.CancelledError:
                await message.edit(
                    self.strings["cancelled"]
                )

            except Exception as e:
                await message.edit(
                    self.strings["error"].format(
                        str(e)[:500]
                    )
                )

            finally:
                await self._cleanup()
                self.task = None

            return

        # ==========================================
        # URL
        # ==========================================

        if not args:
            await utils.answer(
                message,
                self.strings["usage"],
            )
            return

        url = args.split()[0]

        if not url.startswith(
            ("http://", "https://")
        ):
            await utils.answer(
                message,
                self.strings["usage"],
            )
            return

        self.task = asyncio.current_task()

        try:
            await message.edit(
                self.strings["starting"]
            )

            file = await self._process_url(
                url,
                message,
            )

            if not file.exists():
                raise RuntimeError(
                    "Файл не найден после загрузки."
                )

            await message.edit(
                self.strings["sending"]
            )

            await message.client.send_file(
                message.chat_id,
                str(file),
            )

            await message.delete()

        except asyncio.CancelledError:
            await message.edit(
                self.strings["cancelled"]
            )

        except Exception as e:
            await message.edit(
                self.strings["error"].format(
                    str(e)[:500]
                )
            )

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
                self.strings["cancelled"],
            )
        else:
            await utils.answer(
                message,
                self.strings["no_task"],
            )