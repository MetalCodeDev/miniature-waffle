"""
Управление сообщениями.
.del [число] - Удалить сообщение (по реплаю или последние N)
.purge [число] - Массовая очистка чата
"""

from telethon import events
import asyncio

# Стандартный блок инфо для .help (если твой бот его юзает)
__doc__ = "Модуль для удаления сообщений. Работает как через репли, так и по числу."

@events.register(events.NewMessage(pattern=r"\.del(?:\s+(\d+))?", outgoing=True))
async def delete_handler(event):
    """Удаляет сообщения. Если есть репли — удаляет его. Если есть число — удаляет N сообщений."""
    args = event.pattern_match.group(1)
    
    # Сценарий 1: Есть репли (удаляем то, на что ответили, и саму команду)
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        await asyncio.gather(reply_msg.delete(), event.delete())
        return

    # Сценарий 2: Репла нет, но есть число (удаляем N последних сообщений)
    if args:
        count = int(args)
        await event.delete() # Удаляем саму команду .del
        async for msg in event.client.iter_messages(event.chat_id, limit=count):
            await msg.delete()
        return

    # Сценарий 3: Нет ни репла, ни числа — просто удаляем саму команду (или последнее сообщение)
    await event.delete()

@events.register(events.NewMessage(pattern=r"\.purge(?:\s+(\d+))?", outgoing=True))
async def purge_handler(event):
    """Массовая очистка. .purge [число]"""
    input_str = event.pattern_match.group(1)
    
    if not input_str:
        await event.edit("<code>Укажите количество сообщений: .purge 10</code>", parse_mode='html')
        await asyncio.sleep(2)
        await event.delete()
        return

    count = int(input_str)
    await event.delete()
    
    # Удаляем пачкой (так быстрее и меньше шансов на FloodWait в Heroku)
    messages = []
    async for msg in event.client.iter_messages(event.chat_id, limit=count):
        messages.append(msg)
        if len(messages) >= 100: # Лимит для одного запроса на удаление
            await event.client.delete_messages(event.chat_id, messages)
            messages = []
    
    if messages:
        await event.client.delete_messages(event.chat_id, messages)

