from heroku.utils import admin_cmd
import asyncio

# Основная функция для -смс
async def sms_run(event):
    args = event.pattern_match.group(1)
    
    if event.is_reply:
        # Если ответил на сообщение — сносим его и твою команду
        reply = await event.get_reply_message()
        await asyncio.gather(reply.delete(), event.delete())
    elif args and args.isdigit():
        # Если написал "-смс 5" — сносим 5 сообщений
        count = int(args)
        await event.delete()
        async for msg in event.client.iter_messages(event.chat_id, limit=count):
            await msg.delete()
    else:
        # Если просто "-смс" без ничего — удаляем только саму команду
        await event.delete()

# Регистрация, чтобы Heroku не плевался ошибками
def register(cb):
    # Реагирует и на русский, и на английский вариант
    cb.add_handler(admin_cmd(pattern=r"(?:-смс|-sms)(?: |$)(.*)")(sms_run))

__doc__ = "Удаление сообщений через -смс"
