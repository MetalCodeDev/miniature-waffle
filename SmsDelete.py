import asyncio

# Логика команды -смс
async def sms_handler(event):
    # Сразу удаляем сообщение с командой -смс
    await event.delete()
    
    # Если это ответ на сообщение (репли)
    if event.is_reply:
        reply = await event.get_reply_message()
        await reply.delete()
    
    # Если написали число, например "-смс 5"
    else:
        try:
            # Вытаскиваем текст после -смс
            input_str = event.text.split(maxsplit=1)[1]
            count = int(input_str)
            async for msg in event.client.iter_messages(event.chat_id, limit=count):
                await msg.delete()
        except (IndexError, ValueError):
            # Если чисел нет, ничего больше не делаем
            pass

# ТА САМАЯ ФУНКЦИЯ, КОТОРУЮ ТРЕБУЕТ ТВОЙ БОТ В ЛОГАХ
def register(cb):
    # Регистрируем функцию на текст, начинающийся с -смс
    from telethon import events
    cb.add_handler(sms_handler, events.NewMessage(pattern=r"^-смс(?: |$)(.*)", outgoing=True))

__doc__ = "Удаление через -смс"
