# ---------------------------------------------------------------------------------
# Name: BirthdayTime
# Description: Premium birthday countdown with progress bar and surname timer
# Author: @mxzavo
# Version: 2.0
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
    """Премиум-таймер до дня рождения."""

    strings = {
        "name": "BirthdayTime",
        "no_date": "❌ Дата не установлена.\nИспользуй <code>.btset ДД.ММ</code>",
        "bad_date": "❌ Неверная дата.\nПример: <code>.btset 18.09</code>",
        "saved": "💎 Дата сохранена: <b>{}</b>",
        "countdown": (
            "╭━━━ 💎 <b>BIRTHDAY TIME</b> ━━━╮\n"
            "┃\n"
            "┃ 🎂 <b>До дня рождения</b>\n"
            "┃\n"
            "┃ 📅 <b>{} д. {:02d}:{:02d}:{:02d}</b>\n"
            "┃\n"
            "┃ 📊 <code>{}</code>\n"
            "┃    <b>{}%</b> пройдено\n"
            "┃\n"
            "┃ {}\n"
            "┃\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯"
        ),
        "on": "💎 Таймер в фамилии <b>включён</b>.",
        "off": "♻️ Исходная фамилия <b>восстановлена</b>.",
        "refresh": "✨ Фамилия <b>обновлена</b>.",
        "failed": "❌ Не удалось изменить фамилию.",
        "not_enabled": "ℹ️ Таймер в фамилии сейчас выключен.",
        "restored": "♻️ Исходная фамилия <b>восстановлена</b>.",
        "nothing_to_restore": "ℹ️ Сохранённой исходной фамилии нет.",
        "reset": "🧹 Настройки BirthdayTime <b>сброшены</b>.",
        "interval": "⚡ Интервал обновления: <b>{} сек.</b>",
        "format_saved": "📝 Формат фамилии <b>сохранён</b>.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "update_interval",
                60,
                "Интервал обновления фамилии в секундах",
                validator=loader.validators.Integer(minimum=10),
            ),
            loader.ConfigValue(
                "name_format",
                "💎 {} д.",
                "Формат фамилии. {} заменяется количеством дней",
            ),
        )
        self._task = None

    def _get_saved_date(self):
        return self.db.get(__name__, "birthday")

    def _birthday(self):
        value = self._get_saved_date()
        if not value:
            return None
        try:
            day, month = map(int, value.split("."))
            now = datetime.now()
            try:
                birthday = datetime(now.year, month, day)
            except ValueError:
                if day == 29 and month == 2:
                    birthday = datetime(now.year, 3, 1)
                else:
                    return None

            if birthday <= now:
                try:
                    birthday = datetime(now.year + 1, month, day)
                except ValueError:
                    if day == 29 and month == 2:
                        birthday = datetime(now.year + 1, 3, 1)
                    else:
                        return None
            return birthday
        except (ValueError, TypeError):
            return None

    def _left(self):
        birthday = self._birthday()
        return None if birthday is None else birthday - datetime.now()

    def _progress(self):
        current = datetime.now()
        birthday = self._birthday()
        if birthday is None:
            return "░" * 14, 0

        previous = birthday.replace(year=birthday.year - 1)
        total = (birthday - previous).total_seconds()
        elapsed = (current - previous).total_seconds()
        percent = min(100, max(0, int(elapsed / total * 100)))

        width = 14
        filled = round(percent / 100 * width)
        return "█" * filled + "░" * (width - filled), percent

    async def _current_name(self):
        me = await self.client.get_me()
        return me.last_name or ""

    async def _save_original(self):
        if self.db.get(__name__, "original_last_name") is None:
            self.db.set(__name__, "original_last_name", await self._current_name())

    async def _set_name(self):
        delta = self._left()
        if delta is None:
            return False

        await self._save_original()
        days = max(0, delta.days)
        name_format = self.config["name_format"] or "💎 {} д."

        try:
            new_name = name_format.format(days)
        except (IndexError, KeyError, ValueError):
            new_name = f"💎 {days} д."

        new_name = new_name[:64]

        if self.db.get(__name__, "last_applied_name") == new_name:
            return True

        await self.client(UpdateProfileRequest(last_name=new_name))
        self.db.set(__name__, "last_applied_name", new_name)
        return True

    async def _restore_name(self):
        original = self.db.get(__name__, "original_last_name")
        if original is None:
            return False

        current = await self._current_name()
        if current != original:
            await self.client(UpdateProfileRequest(last_name=original))

        self.db.set(__name__, "original_last_name", None)
        self.db.set(__name__, "last_applied_name", None)
        return True

    async def client_ready(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._worker())

    async def on_unload(self):
        if self._task and not self._task.done():
            self._task.cancel()

    async def _worker(self):
        while True:
            try:
                if self.db.get(__name__, "name_enabled", False):
                    await self._set_name()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"BirthdayTime worker: {e}")

            try:
                interval = int(self.config["update_interval"] or 60)
            except (ValueError, TypeError):
                interval = 60

            await asyncio.sleep(max(10, interval))

    @loader.command(ru_doc="Показать красивый отсчёт", en_doc="Show countdown")
    async def bt(self, message):
        delta = self._left()
        if delta is None:
            return await utils.answer(message, self.strings("no_date"))

        days = max(0, delta.days)
        hours, rem = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        bar, percent = self._progress()

        if days <= 7:
            status = "🔥 <b>Финишная прямая!</b>"
        elif days <= 30:
            status = "✨ <b>Уже совсем скоро!</b>"
        else:
            status = "🌙 <b>Время идёт...</b>"

        await utils.answer(
            message,
            self.strings("countdown").format(
                days, hours, minutes, seconds, bar, percent, status
            ),
        )

    @loader.command(ru_doc="Установить дату: .btset ДД.ММ", en_doc="Set date: .btset DD.MM")
    async def btset(self, message):
        raw = utils.get_args_raw(message).strip()
        try:
            day, month = map(int, raw.split("."))
            if not 1 <= month <= 12 or not 1 <= day <= 31:
                raise ValueError
            try:
                datetime(2000, month, day)
            except ValueError:
                if not (day == 29 and month == 2):
                    raise
        except (ValueError, TypeError):
            return await utils.answer(message, self.strings("bad_date"))

        value = f"{day:02d}.{month:02d}"
        self.db.set(__name__, "birthday", value)
        await utils.answer(message, self.strings("saved").format(value))

    @loader.command(ru_doc="Включить или выключить таймер в фамилии", en_doc="Toggle surname timer")
    async def btname(self, message):
        enabled = self.db.get(__name__, "name_enabled", False)
        try:
            if enabled:
                await self._restore_name()
                self.db.set(__name__, "name_enabled", False)
                return await utils.answer(message, self.strings("off"))

            if self._left() is None:
                return await utils.answer(message, self.strings("no_date"))

            await self._save_original()
            await self._set_name()
            self.db.set(__name__, "name_enabled", True)
            await utils.answer(message, self.strings("on"))

        except RPCError as e:
            self.db.set(__name__, "name_enabled", False)
            await utils.answer(
                message,
                f"❌ Telegram не разрешил изменить фамилию:\n"
                f"<code>{utils.escape_html(str(e))}</code>",
            )
        except Exception as e:
            self.db.set(__name__, "name_enabled", False)
            print(f"BirthdayTime name: {e}")
            await utils.answer(message, self.strings("failed"))

    @loader.command(ru_doc="Принудительно обновить фамилию", en_doc="Refresh surname")
    async def btrefresh(self, message):
        if not self.db.get(__name__, "name_enabled", False):
            return await utils.answer(message, self.strings("not_enabled"))
        try:
            await self._set_name()
            await utils.answer(message, self.strings("refresh"))
        except Exception as e:
            print(f"BirthdayTime refresh: {e}")
            await utils.answer(message, self.strings("failed"))

    @loader.command(ru_doc="Восстановить исходную фамилию", en_doc="Restore original surname")
    async def btrestore(self, message):
        try:
            restored = await self._restore_name()
            self.db.set(__name__, "name_enabled", False)
            if restored:
                await utils.answer(message, self.strings("restored"))
            else:
                await utils.answer(message, self.strings("nothing_to_restore"))
        except Exception as e:
            print(f"BirthdayTime restore: {e}")
            await utils.answer(message, self.strings("failed"))

    @loader.command(ru_doc="Изменить интервал: .btinterval СЕК", en_doc="Set interval: .btinterval SEC")
    async def btinterval(self, message):
        raw = utils.get_args_raw(message).strip()
        try:
            value = int(raw)
            if value < 10:
                raise ValueError
        except (ValueError, TypeError):
            return await utils.answer(message, "❌ Укажи число от <b>10</b> секунд.")

        self.config["update_interval"] = value
        await utils.answer(message, self.strings("interval").format(value))

    @loader.command(ru_doc="Изменить формат: .btformat ТЕКСТ с {}", en_doc="Set surname format")
    async def btformat(self, message):
        value = utils.get_args_raw(message).strip()
        if "{}" not in value or len(value) > 50:
            return await utils.answer(
                message,
                "❌ Формат должен содержать <code>{}</code> и быть не длиннее 50 символов.",
            )

        self.config["name_format"] = value
        await utils.answer(message, self.strings("format_saved"))

    @loader.command(ru_doc="Показать настройки", en_doc="Show settings")
    async def btstatus(self, message):
        date = self._get_saved_date() or "не установлена"
        enabled = (
            "💎 включён"
            if self.db.get(__name__, "name_enabled", False)
            else "○ выключен"
        )

        name_format = str(self.config["name_format"])
        try:
            name_format = utils.escape_html(name_format)
        except Exception:
            pass

        await utils.answer(
            message,
            "╭━━━ 💎 <b>BIRTHDAY TIME</b> ━━━╮\n"
            "┃\n"
            f"┃ 🎂 Дата: <b>{date}</b>\n"
            f"┃ 🏷 Таймер: <b>{enabled}</b>\n"
            f"┃ ⚡ Интервал: <b>{self.config['update_interval']} сек.</b>\n"
            f"┃ 📝 Формат: <code>{name_format}</code>\n"
            "┃\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        )

    @loader.command(ru_doc="Сбросить настройки BirthdayTime", en_doc="Reset BirthdayTime settings")
    async def btreset(self, message):
        try:
            if self.db.get(__name__, "name_enabled", False):
                await self._restore_name()
        except Exception as e:
            print(f"BirthdayTime reset restore: {e}")

        self.db.set(__name__, "birthday", None)
        self.db.set(__name__, "name_enabled", False)
        self.db.set(__name__, "original_last_name", None)
        self.db.set(__name__, "last_applied_name", None)

        await utils.answer(message, self.strings("reset"))

    @loader.command(ru_doc="Справка по BirthdayTime", en_doc="BirthdayTime help")
    async def bthelp(self, message):
        await utils.answer(
            message,
            "╭━━━ 💎 <b>BIRTHDAY TIME v2.0</b> ━━━╮\n"
            "┃\n"
            "┃ 🎂 <code>.bt</code> — отсчёт\n"
            "┃ 📅 <code>.btset ДД.ММ</code> — дата\n"
            "┃ 🏷 <code>.btname</code> — таймер фамилии\n"
            "┃ ✨ <code>.btrefresh</code> — обновить\n"
            "┃ ♻️ <code>.btrestore</code> — восстановить фамилию\n"
            "┃ ⚡ <code>.btinterval 60</code> — интервал\n"
            "┃ 📝 <code>.btformat 💎 {} д.</code> — формат\n"
            "┃ ⚙️ <code>.btstatus</code> — настройки\n"
            "┃ 🧹 <code>.btreset</code> — полный сброс\n"
            "┃\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        )
