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
class DownloaderMod(loader.Module):
    """Universal Downloader"""

    strings = {
        "name": "Downloader",

        "usage": (
            "📥 <b>Использование:</b>\n"
            "<code>.dl &lt;ссылка&gt;</code>\n"
            "<code>.dl</code> — ответом на медиа"
        ),

        "starting": "⏳ <b>Подготавливаю загрузку...</b>",
        "downloading": "📥 <b>Загружаю...</b>",
        "sending": "📤 <b>Отправляю файл...</b>",
        "done": "✅ <b>Готово.</b>",
        "cancelled": "❌ <b>Загрузка отменена.</b>",
        "no_task": "ℹ️ <b>Активной загрузки нет.</b>",
        "error": "⚠️ <b>Ошибка:</b> <code>{}</code>",
    }

    def __init__(self):
        self.task = None
        self.tmpdir = None

    async def _cleanup(self):
        if self.tmpdir and os.path.exists(self.tmpdir):
            shutil.rmtree(
                self.tmpdir,
                ignore_errors=True
            )

        self.tmpdir = None

    async def _http_download(self, url, output):
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=30,
            sock_read=60
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url,
                allow_redirects=True
            ) as response:

                response.raise_for_status()

                with open(output, "wb") as file:
                    async for chunk in response.content.iter_chunked(
                        512 * 1024
                    ):
                        file.write(chunk)

        return output

    async def _ytdlp_download(self, url, directory):
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "Не установлен yt-dlp"
            )

        output = os.path.join(
            directory,
            "%(title).100s-%(id)s.%(ext)s"
        )

        options = {
            "outtmpl": output,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "retries": 3,
            "fragment_retries": 3,
            "merge_output_format": "mp4",
        }

        loop = asyncio.get_running_loop()

        def worker():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(
                    url,
                    download=True
                )

                filename = Path(
                    ydl.prepare_filename(info)
                )

                candidates = [
                    filename,
                    Path(
                        os.path.splitext(
                            str(filename)
                        )[0] + ".mp4"
                    ),
                    Path(
                        os.path.splitext(
                            str(filename)
                        )[0] + ".mkv"
                    ),
                    Path(
                        os.path.splitext(
                            str(filename)
                        )[0] + ".webm"
                    ),
                ]

                for file in candidates:
                    if file.exists():
                        return file

                raise RuntimeError(
                    "Скачанный файл не найден"
                )

        return await loop.run_in_executor(
            None,
            worker
        )

    async def _download(self, url, message):
        self.tmpdir = tempfile.mkdtemp(
            prefix="heroku_downloader_"
        )

        # Сначала пробуем yt-dlp
        try:
            await message.edit(
                self.strings["downloading"]
            )

            file = await self._ytdlp_download(
                url,
                self.tmpdir
            )

            if file.exists():
                return file

        except Exception:
            pass

        # Если yt-dlp не справился —
        # пробуем скачать ссылку как обычный файл
        filename = Path(
            urlparse(url).path
        ).name

        if not filename:
            filename = "download"

        output = Path(
            self.tmpdir
        ) / filename

        await self._http_download(
            url,
            output
        )

        if not output.exists():
            raise RuntimeError(
                "Не удалось скачать файл"
            )

        return output

    @loader.command()
    async def dl(self, message):
        """<ссылка> — скачать файл или медиа"""

        args = utils.get_args_raw(
            message
        ).strip()

        self.task = asyncio.current_task()

        # =========================
        # Telegram media
        # =========================

        if not args and message.is_reply:
            reply = await message.get_reply_message()

            if not reply or not reply.media:
                await utils.answer(
                    message,
                    self.strings["usage"]
                )
                return

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
                        "Не удалось скачать медиа"
                    )

                await message.edit(
                    self.strings["sending"]
                )

                await message.client.send_file(
                    message.chat_id,
                    file,
                    caption=reply.text or None
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

        # =========================
        # URL
        # =========================

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
                self.strings["usage"]
            )
            self.task = None
            return

        try:
            await message.edit(
                self.strings["starting"]
            )

            file = await self._download(
                url,
                message
            )

            if not file or not file.exists():
                raise RuntimeError(
                    "Файл не найден"
                )

            await message.edit(
                self.strings["sending"]
            )

            await message.client.send_file(
                message.chat_id,
                str(file)
            )

            await message.delete()

        except asyncio.CancelledError:
            try:
                await message.edit(
                    self.strings["cancelled"]
                )
            except Exception:
                pass

        except Exception as e:
            try:
                await message.edit(
                    self.strings["error"].format(
                        str(e)[:500]
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
                self.strings["cancelled"]
            )
        else:
            await utils.answer(
                message,
                self.strings["no_task"]
        ) 
