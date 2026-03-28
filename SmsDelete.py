from telethon import events
from heroku.utils import admin_cmd # Импорт специфического декоратора этого бота
import asyncio

@bot.on(admin_cmd(pattern="del(?: |$)(.*)"))
async def delete_handler(event):
    """Удаляет сообщения: по реплаю или указанное количество."""
    args = event.pattern_match.group(1)
    
    if event.is_reply:
        # Если есть репли, удаляем и его, и саму команду
        reply_msg = await event.get_reply_message()
        await asyncio.gather(reply_msg.delete(), event.delete())
    elif args and args.isdigit():
        # Если указано число, удаляем N последних сообщений
        count = int(args)
        await event.delete()
        async for msg in event.client.iter_messages(event.chat_id, limit=count):
            await msg.delete()
    else:
        # Если просто .del без реплая и аргументов — удаляем только саму команду
        await event.delete()

@bot.on(admin_cmd(pattern="purge(?: |$)(.*)"))
async def purge_handler(event):
    """Массовая очистка чата через .purge [число]."""
    args = event.pattern_match.group(1)
    if not args or not args.isdigit():
        await event.edit("<code>Укажите количество сообщений для очистки!</code>")
        return

    count = int(args)
    await event.delete()
    
    # Удаляем сообщения пачками по 100 (для обхода лимитов Telegram)
    messages = []
    async for msg in event.client.iter_messages(event.chat_id, limit=count):
        messages.append(msg)
        if len(messages) >= 100:
            await event.client.delete_messages(event.chat_id, messages)
            messages = []
    
    if messages:
        await event.client.delete_messages(event.chat_id, messages)

# Описание для команды .help внутри бота
__doc__ = "<b>Модуль SmsDelete</b>\n\n<b>Команды:</b>\n• <code>.del</code> — Удалить (репли или число)\n• <code>.purge</code> — Очистить чат"


