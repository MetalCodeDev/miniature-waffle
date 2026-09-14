# ---------------------------------------------------------------------------------
# Name: BirthdayTime
# Description: Birthday countdown with progress bar and surname timer
# Author: @mxzavo
# ---------------------------------------------------------------------------------
# meta developer: @mxzavo
# scope: BirthdayTime
# ---------------------------------------------------------------------------------

import asyncio
from datetime import datetime

from telethon.errors import RPCError
from telethon.tl.functions.account import UpdateProfileRequest

from .. import loader, utils


@loader.tds
class BirthdayTime(loader.Module):
    """Таймер до дня рождения."""

    strings = {
        "name": "BirthdayTime",
        "no_date": "❌ Дата не установлена. Используй <code>.btset ДД.ММ</code>",
        "bad_date": "❌ Формат: <code>.btset ДД.ММ</code>",
        "saved": "✅ Дата рождения: <b>{}</b>",
        "countdown": "🎂 <b>До дня рождения</b>\n\n📅 <b>{} д. {:02d}:{:02d}:{:02d}</b>\n📊 <code>{}</code> <b>{}%</b>\n\n{}",
        "on": "🏷 Таймер в фамилии <b>включён</b>.",
        "off": "🏷 Таймер в фамилии <b>выключен</b>.\n♻️ Исходная фамилия восстановлена.",
        "refresh": "🔄 Фамилия обновлена.",
        "failed": "❌ Не удалось изменить фамилию.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "update_interval",
                60,
                "Интервал обновления фамилии (сек.)",
                validator=loader.validators.Integer(minimum=10),
            ),
            loader.ConfigValue(
                "name_format",
                "🎂 {} д.",
                "Формат фамилии, {} = дни",
            ),
        )
        self._task = None

    def _birthday(self):
        value = self.db.get(__name__, "birthday")

        if not value:
            return None

        try:
            day, month = map(int, value.split("."))

            now = datetime.now()
            birthday = datetime(now.year, month, day)

            if birthday <= now:
                birthday = datetime(now.year + 1, month, day)

            return birthday

        except (ValueError, TypeError):
            return None

    def _left(self):
        birthday = self._birthday()

        if birthday is None:
            return None

        return birthday - datetime.now()

    def _progress(self, delta):
        total = 365.2425 * 86400

        left = max(0, delta.total_seconds())

        percent = min(
            100,
            max(
                0,
                int((1 - left / total) * 100),
            ),
        )

        width = 14
        filled = round(percent / 100 * width)

        bar = "█" * filled + "░" * (width - filled)

        return bar, percent

    async def _current_name(self):
        me = await self.client.get_me()
        return me.last_name or ""

    async def _save_original(self):
        if self.db.get(__name__, "original_last_name") is None:
            self.db.set(
                __name__,
                "original_last_name",
                await self._current_name(),
            )

    async def _set_name(self):
        delta = self._left()

        if delta is None:
            return False

        await self._save_original()

        days = max(0, delta.days)

        new_name = (
            self.config["name_format"] or "🎂 {} д."
        ).format(days)

        if self.db.get(__name__, "last_applied_name") == new_name:
            return True

        await self.client(
            UpdateProfileRequest(
                last_name=new_name
            )
        )

        self.db.set(
            __name__,
            "last_applied_name",
            new_name,
        )

        return True

    async def _restore_name(self):
        original = self.db.get(
            __name__,
            "original_last_name",
        )

        if original is None:
            return False

        if await self._current_name() != original:
            await self.client(
                UpdateProfileRequest(
                    last_name=original
                )
            )

        self.db.set(
            __name__,
            "original_last_name",
            None,
        )

        self.db.set(
            __name__,
            "last_applied_name",
            None,
        )

        return True

    async def client_ready(self):
        if self._task and not self._task.done():
            self._task.cancel()

        self._task = asyncio.create_task(
            self._worker()
        )

    async def on_unload(self):
        if self._task and not self._task.done():
            self._task.cancel()

    async def _worker(self):
        while True:
            try:
                if self.db.get(
                    __name__,
                    "name_enabled",
                    False,
                ):
                    await self._set_name()

            except asyncio.CancelledError:
                raise

            except Exception as e:
                print(
                    f"BirthdayTime worker: {e}"
                )

            await asyncio.sleep(
                max(
                    10,
                    int(
                        self.config["update_interval"]
                        or 60
                    ),
                )
            )

    @loader.command(
        ru_doc="Показать отсчёт",
        en_doc="Show countdown",
    )
    async def bt(self, message):
        delta = self._left()

        if delta is None:
            return await utils.answer(
                message,
                self.strings("no_date"),
