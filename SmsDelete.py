from heroku.utils import admin_cmd
import asyncio

# Функция удаления
async def sms_del(event):
    await event.delete() # Удаляем саму команду -смс
    
    args = event.pattern_match.group(1)
    
    if event.is_reply:
        # Если есть репли — удаляем то сообщение
        reply = await event.get_reply_message()
        await reply.delete()
    elif args and args.isdigit():
        # Если число — чистим историю
        count = int(args)
        async for msg in event.client.iter_messages(event.chat_id, limit=count):
            await msg.delete()

# Исправленная регистрация под твой лог
def register(module_name):
    bot.add_handler(admin_cmd(pattern=r"-смс(?: |$)(.*)")(sms_del))

__doc__ = "Удаление через -смс"
