from heroku.utils import admin_cmd
import asyncio

# Логика удаления через -смс
async def sms_del(event):
    # Саму команду -смс удаляем сразу
    await event.delete()
    
    args = event.pattern_match.group(1)
    
    if event.is_reply:
        # Если ответил на сообщение - удаляем то, на что ответил
        reply = await event.get_reply_message()
        await reply.delete()
    elif args and args.isdigit():
        # Если написал число (напр. -смс 5) - чистим последние сообщения
        count = int(args)
        async for msg in event.client.iter_messages(event.chat_id, limit=count):
            await msg.delete()

# РЕГИСТРАЦИЯ КОМАНДЫ (БЕЗ ЭТОГО БУДЕТ ОШИБКА В ЛОГАХ)
def register(cb):
    # Теперь бот будет реагировать на -смс
    cb.add_handler(admin_cmd(pattern=r"-смс(?: |$)(.*)")(sms_del))

__doc__ = "Удаление через -смс (репли или число)"
