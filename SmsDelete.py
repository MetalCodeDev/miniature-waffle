from heroku.utils import admin_cmd
import asyncio

# Функция удаления
async def del_msg(event):
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

# Функция очистки
async def purge_msgs(event):
    args = event.pattern_match.group(1)
    if args and args.isdigit():
        count = int(args)
        await event.delete()
        # Удаляем пачкой по 100, чтобы телега не забанила за спам запросами
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

# ВОТ ЭТОТ БЛОК ОБЯЗАТЕЛЕН ДЛЯ HEROKU-UB
# Он регистрирует команды без внешних обработчиков
def register(cb):
    cb.add_handler(admin_cmd(pattern=r"del(?: |$)(.*)")(del_msg))
    cb.add_handler(admin_cmd(pattern=r"purge(?: |$)(.*)")(purge_msgs))

__doc__ = "Модуль SmsDelete: .del (репли/число) и .purge (число)"
