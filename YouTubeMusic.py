# meta developer: @MAXC
# scope: heroku_only
# requires: yt-dlp

import asyncio
import os
import re
import tempfile
from pathlib import Path

from .. import loader, utils


@loader.tds
class YouTubeMusicMod(loader.Module):
    """YouTube / YouTube Music downloader."""

    strings = {
        "name": "YouTubeMusic",
        "search": "🔎 <b>Ищу:</b> <code>{}</code>",
        "download": "⬇️ <b>Скачиваю:</b> <code>{}</code>",
        "done": "🎵 <b>Готово.</b>",
        "no_query": "❌ <b>Укажи название трека или ссылку.</b>",
        "error": "❌ <b>Ошибка:</b>\n<code>{}</code>",
    }

    async def _download(self, query: str, directory: str):
        output = os.path.join(
            directory,
            "%(title).120s.%(ext)s"
        )

        command = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "--restrict-filenames",
            "-f",
            "bestaudio[ext=m4a]/bestaudio",
            "-o",
            output,
            "--print",
            "after_move:filepath",
        ]

        if re.match(r"^https?://", query):
            command.append(query)
        else:
            command.extend([
                "ytsearch1:" + query
            ])

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error = stderr.decode(
                "utf-8",
                "ignore"
            ).strip()

            raise RuntimeError(
                error[-700:] or "yt-dlp завершился с ошибкой"
            )

        files = []

        for line in stdout.decode(
            "utf-8",
            "ignore"
        ).splitlines():

            line = line.strip()

            if line and os.path.isfile(line):
                files.append(line)

        if not files:
            files = [
                str(file)
                for file in Path(directory).iterdir()
                if file.is_file()
            ]

        if not files:
            raise RuntimeError(
                "yt-dlp не вернул аудиофайл"
            )

        return files[0]

    @loader.command(
        ru_doc="Скачать трек: .yt <название или ссылка>"
    )
    async def ytcmd(self, message):
        """Download audio from YouTube / YouTube Music."""

        query = utils.get_args_raw(message).strip()

        if not query:
            await utils.answer(
                message,
                self.strings["no_query"]
            )
            return

        status = await utils.answer(
            message,
            self.strings["search"].format(
                utils.escape_html(query)
            )
        )

        with tempfile.TemporaryDirectory(
            prefix="heroku_yt_"
        ) as temp:

            try:
                await utils.answer(
                    status,
                    self.strings["download"].format(
                        utils.escape_html(query)
                    )
                )

                filepath = await self._download(
                    query,
                    temp
                )

                await message.client.send_file(
                    message.chat_id,
                    filepath,
                    caption=self.strings["done"]
                )

                await status.delete()

            except Exception as error:
               
