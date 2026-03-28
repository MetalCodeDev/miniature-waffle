from heroku.utils import admin_cmd
import asyncio

# Команда .del - удаляет либо репли, либо N последних сообщений
@bot.on(admin_cmd(pattern=r"del(?: |$)(.*)"))
async def delete_handler(event):
    args = event.pattern_match.group(1)
    if event.is_reply:
        reply = await event.get_reply_message()
        await asyncio.gather(reply.delete(), event.delete())
    elif args and args.isdigit():
        count = int(args)
        await event.delete()
        async for msg in event.client.iter_messages(event.chat_id, limit=count):
            await msg.delete()
    else:
        await event.delete()

# Команда .purge - массовая чистка
@bot.on(admin_cmd(pattern=r"purge(?: |$)(.*)"))
async def purge_handler(event):
    args = event.pattern_match.group(1)
    if args and args.isdigit():
        count = int(args)
        await event.delete()
        messages = []
        async for msg in event.client.iter_messages(event.chat_id, limit=count):
            messages.append(msg)
            if len(messages) >= 100:
                await event.client.delete_messages(event.chat_id, messages)
                messages = []
        if messages:
            await event.client.delete_messages(event.chat_id, messages)
    else:
        await event.edit("<b>Укажи число: .purge 10</b>")

# ВОТ ЭТА ХЕРНЯ НУЖНА БОТУ, ЧТОБЫ ОН НЕ ПЛЮВАЛСЯ В ЛОГАХ
def register(cb):
    cb(delete_handler)
    cb(purge_handler)

__doc__ = "Модуль SmsDelete: .del (репли/число) и .purge (число)"
