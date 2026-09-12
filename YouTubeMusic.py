# meta developer: @PlayBoyCart4
# scope: heroku_only
# requires: yt-dlp

import asyncio
import os
import tempfile
from pathlib import Path

from .. import loader, utils


@loader.tds
class YouTubeMusicMod(loader.Module):
    """YouTube / YouTube Music audio downloader."""

    strings = {
        "name": "YouTubeMusic",
        "search": "🔎 <b>Ищу:</b> <code>{}</code>",
        "download": "⬇️ <b>Скачиваю:</b> <code>{}</code>",
        "done": "🎵 <b>Готово.</b>",
        "added": "➕ <b>Трек добавлен.</b>",
        "no_query": "❌ <b>Укажи название трека или ссылку.</b>",
        "error": "❌ <b>Ошибка:</b>\n<code>{}</code>",
    }

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

        filepath = await asyncio.to_thread(download)

        if os.path.isfile(filepath):
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
                await utils.answer(
                    status,
                    self.strings["error"].format(
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
