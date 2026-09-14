# Proprietary License Agreement

# Copyright (c) 2024-29 CodWiz

# Permission is hereby granted to any person obtaining a copy of this software and associated documentation files (the "Software"), to use the Software for personal and non-commercial purposes, subject to the following conditions:

# 1. The Software may not be modified, altered, or otherwise changed in any way without the explicit written permission of the author.

# 2. Redistribution of the Software, in original or modified form, is strictly prohibited without the explicit written permission of the author.

# 3. The Software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and non-infringement. In no event shall the author or copyright holder be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the Software or the use or other dealings in the Software.

# 4. Any use of the Software must include the above copyright notice and this permission notice in all copies or substantial portions of the Software.

# 5. By using the Software, you agree to be bound by the terms and conditions of this license.

# For any inquiries or requests for permissions, please contact codwiz@yandex.ru.

# ---------------------------------------------------------------------------------
# Name: BirthdayTime
# Description: Counting down to your birthday
# Author: @mxzavo
# ---------------------------------------------------------------------------------
# meta developer: @mxzavo
# scope: BirthdayTime
# scope: Api BirthdayTime 0.0.1
# ---------------------------------------------------------------------------------

import asyncio
import calendar
from datetime import datetime

from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.errors.rpcerrorlist import UserPrivacyRestrictedError

from .. import loader, utils


D_MSG = [
    "🎯 Уже близко",
    "⏳ Время идёт",
    "🎉 Скоро праздник",
    "📅 Дата приближается",
    "✨ Осталось совсем немного",
    "🚀 Дожидаемся",
]


@loader.tds
class DaysToMyBirthday(loader.Module):
    """Улучшенный таймер до дня рождения."""

    strings = {
        "name": "BirthdayTime",
        "date_error": "❗️ В конфиге не указана дата рождения.",
        "msg": (
            "🎂 <b>До дня рождения:</b>\n\n"
            "📅 <b>{} д.</b>  •  ⏰ <b>{:02d}:{:02d}:{:02d}</b>\n\n"
            "{}"
        ),
        "name_enabled": "✅ Таймер в фамилии включён.",
        "name_disabled": "🛑 Таймер в фамилии выключен.",
        "name_changed": "✅ Фамилия обновлена.",
        "name_not_changed": "ℹ️ Фамилия уже актуальна.",
        "name_privacy_error": "❌ Не удалось изменить фамилию из-за настроек приватности.",
        "error": "❌ Произошла ошибка. Проверь логи.",
        "conf": "⚙️ Открываю конфиг...",
        "status": (
            "🎂 <b>BirthdayTime</b>\n\n"
            "📅 Дата: <b>{}. {}</b>\n"
            "🏷 Таймер в фамилии: <b>{}</b>\n"
            "🔄 Интервал обновления: <b>{} сек.</b>"
        ),
        "help": (
            "🎂 <b>BirthdayTime — подробная справка</b>\n\n"
            "📌 <code>.bt</code>\n"
            "Показывает точное оставшееся время до следующего "
            "дня рождения: дни, часы, минуты и секунды.\n\n"
            "🏷 <code>.btname</code>\n"
            "Включает или выключает автоматический таймер в "
            "фамилии профиля. При включении фамилия будет "
            "обновляться автоматически. При выключении "
            "восстанавливается сохранённая фамилия.\n\n"
            "🔄 <code>.btrefresh</code>\n"
            "Немедленно обновляет таймер в фамилии, не дожидаясь "
            "следующего автоматического обновления. Работает, "
            "если <code>.btname</code> включён.\n\n"
            "📊 <code>.btstatus</code>\n"
            "Показывает текущие настройки модуля: дату рождения, "
            "состояние таймера в фамилии и интервал обновления.\n\n"
            "⚙️ <code>.btconfig</code>\n"
            "Открывает конфигурацию BirthdayTime, где можно изменить "
            "дату рождения, формат фамилии, интервал обновления и "
            "отображение секунд.\n\n"
            "❓ <code>.bthelp</code>\n"
            "Показывает эту подробную справку.\n\n"
            "💡 <b>Важно:</b> дата рождения задаётся в конфиге модуля."
        ),
    }

    strings_ru = strings

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "birthday_date",
                None,
                lambda: "День рождения (только число)",
                validator=loader.validators.Integer(),
            ),
            loader.ConfigValue(
                "birthday_month",
                None,
                "Месяц рождения",
                validator=loader.validators.Choice(
                    [
                        "January", "February", "March", "April",
                        "May", "June", "July", "August",
                        "September", "October", "November", "December",
                    ]
                ),
            ),
            loader.ConfigValue(
                "name_format",
                "🎂 {} д.",
                "Формат таймера в фамилии. {} = количество дней",
            ),
            loader.ConfigValue(
                "update_interval",
                60,
                "Интервал обновления фамилии в секундах",
                validator=loader.validators.Integer(),
            ),
            loader.ConfigValue(
                "show_seconds",
                True,
                "Показывать часы/минуты/секунды в команде .bt",
                validator=loader.validators.Boolean(),
            ),
        )
        self._task = None

    def _get_birthday(self):
        day = self.config["birthday_date"]
        month_name = self.config["birthday_month"]

        if day is None or month_name is None:
            return None

        month = list(calendar.month_name).index(month_name)
        now = datetime.now()

        try:
            birthday = datetime(now.year, month, day)
        except ValueError:
            return None

        if birthday <= now:
            birthday = datetime(now.year + 1, month, day)

        return birthday

    def _time_left(self):
        birthday = self._get_birthday()
        if birthday is None:
            return None

        return birthday - datetime.now()

    async def client_ready(self):
        if self._task:
            self._task.cancel()
        self._task = asyncio.create_task(self.checker())

    async def _update_name(self):
        delta = self._time_left()
        if delta is None:
            return False

        days = delta.days
        user = await self.client(GetFullUserRequest(self.client.hikka_me.id))

        if not user or not user.users:
            return False

        current_name = user.users[0].last_name or ""
        name_format = self.config["name_format"] or "🎂 {} д."
        new_name = name_format.format(days)

        if current_name == new_name:
            return False

        await self.client(UpdateProfileRequest(last_name=new_name))
        self.db.set(__name__, "last_name", current_name)
        return True

    async def checker(self):
        while True:
            try:
                if self.db.get(__name__, "change_name", False):
                    await self._update_name()
            except UserPrivacyRestrictedError:
                self.db.set(__name__, "change_name", False)
                print("BirthdayTime: privacy settings prevent changing the name.")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"BirthdayTime checker error: {e}")

            interval = max(10, int(self.config["update_interval"] or 60))
            await asyncio.sleep(interval)

    @loader.command(
        ru_doc="Показать таймер до дня рождения",
        en_doc="Display the birthday countdown",
    )
    async def bt(self, message):
        delta = self._time_left()

        if delta is None:
            await utils.answer(message, self.strings("date_error"))
            return

        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds // 60) % 60
        seconds = delta.seconds % 60

        if self.config["show_seconds"]:
            await utils.answer(
                message,
                self.strings("msg").format(
                    days, hours, minutes, seconds, D_MSG[days % len(D_MSG)]
                ),
            )
        else:
            total_minutes = int(delta.total_seconds() // 60)
            total_hours = total_minutes // 60
            total_days = total_hours // 24
            hours_left = total_hours % 24
            minutes_left = total_minutes % 60

            await utils.answer(
                message,
                self.strings("msg").format(
                    total_days,
                    hours_left,
                    minutes_left,
                    0,
                    D_MSG[days % len(D_MSG)],
                ),
            )

    @loader.command(
        ru_doc="Включить/выключить таймер в фамилии",
        en_doc="Toggle the countdown in your last name",
    )
    async def btname(self, message):
        enabled = self.db.get(__name__, "change_name", False)

        if enabled:
            self.db.set(__name__, "change_name", False)

            # Restore the last real surname saved before enabling the timer.
            old_name = self.db.get(__name__, "last_name", "")
            try:
                await self.client(UpdateProfileRequest(last_name=old_name))
            except UserPrivacyRestrictedError:
                await utils.answer(message, self.strings("name_privacy_error"))
                return
            except Exception as e:
                print(f"BirthdayTime restore error: {e}")

            await utils.answer(message, self.strings("name_disabled"))
        else:
            self.db.set(__name__, "change_name", True)
            try:
                await self._update_name()
                await utils.answer(message, self.strings("name_enabled"))
            except UserPrivacyRestrictedError:
                self.db.set(__name__, "change_name", False)
                await utils.answer(message, self.strings("name_privacy_error"))
            except Exception as e:
                print(f"BirthdayTime enable error: {e}")
                await utils.answer(message, self.strings("error"))

    @loader.command(
        ru_doc="Показать настройки модуля",
        en_doc="Display module status",
    )
    async def btstatus(self, message):
        month = self.config["birthday_month"]
        day = self.config["birthday_date"]
        enabled = self.db.get(__name__, "change_name", False)
        interval = self.config["update_interval"]

        if day is None or month is None:
            await utils.answer(message, self.strings("date_error"))
            return

        await utils.answer(
            message,
            self.strings("status").format(
                day,
                month,
                "включён" if enabled else "выключен",
                interval,
            ),
        )

    @loader.command(
        ru_doc="Принудительно обновить фамилию",
        en_doc="Force a last-name refresh",
    )
    async def btrefresh(self, message):
        if not self.db.get(__name__, "change_name", False):
            await utils.answer(message, "ℹ️ Сначала включи таймер: <code>.btname</code>")
            return

        try:
            changed = await self._update_name()
            await utils.answer(
                message,
                self.strings("name_changed")
                if changed
                else self.strings("name_not_changed"),
            )
        except UserPrivacyRestrictedError:
            await utils.answer(message, self.strings("name_privacy_error"))
        except Exception as e:
            print(f"BirthdayTime refresh error: {e}")
            await utils.answer(message, self.strings("error"))

    @loader.command(
        ru_doc="Открыть конфиг BirthdayTime",
        en_doc="Open BirthdayTime config",
    )
    async def btconfig(self, message):
        msg = await self.client.send_message(
            message.chat_id, self.strings("conf")
        )
        await self.allmodules.commands["config"](
            await utils.answer(msg, f"{self.get_prefix()}config BirthdayTime")
        )

    @loader.command(
        ru_doc="Показать справку BirthdayTime",
        en_doc="Show BirthdayTime help",
    )
    async def bthelp(self, message):
        await utils.answer(message, self.strings("help"))

