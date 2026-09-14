from .. import loader, utils
import openai


@loader.tds
class AIModule(loader.Module):
    """AI assistant powered by OpenAI | Developer: @mxzavo"""

    strings = {
        "name": "AI",
        "no_key": "⚠️ OpenAI API-ключ не настроен.\nИспользуй: .aiconfig <ключ>",
        "processing": "🤖 Обрабатываю запрос...",
        "no_prompt": "❓ Напиши вопрос после .ai или ответь командой .ai на сообщение.",
        "cleared": "🗑 История очищена.",
        "error": "❌ Ошибка: {}",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "API_KEY",
                None,
                "OpenAI API key",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "MODEL",
                "gpt-5-mini",
                "OpenAI model",
            ),
        )

    @loader.command()
    async def ai(self, message):
        """<текст> — задать вопрос AI"""
        api_key = self.config["API_KEY"]

        if not api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        prompt = utils.get_args_raw(message)

        # Если .ai отправлена ответом на сообщение
        if not prompt and message.is_reply:
            reply = await message.get_reply_message()
            if reply:
                prompt = reply.raw_text

        if not prompt:
            await utils.answer(message, self.strings("no_prompt"))
            return

        await utils.answer(message, self.strings("processing"))

        try:
            client = openai.AsyncOpenAI(api_key=api_key)

            response = await client.responses.create(
                model=self.config["MODEL"],
                input=prompt,
            )

            answer = response.output_text

            if not answer:
                answer = "⚠️ AI не вернул ответ."

            await utils.answer(message, answer)

        except Exception as e:
            await utils.answer(
                message,
                self.strings("error").format(str(e))
            )

    @loader.command()
    async def aiconfig(self, message):
        """<API_KEY> — установить OpenAI API-ключ"""
        key = utils.get_args_raw(message)

        if not key:
            await utils.answer(
                message,
                "🔑 Использование:\n.aiconfig <OpenAI API key>"
            )
            return

        self.config["API_KEY"] = key

        # Удаляем сообщение с ключом
        try:
            await message.delete()
        except Exception:
            pass

    @loader.command()
    async def aiclear(self, message):
        """Очистить настройки AI"""
        self.config["API_KEY"] = None
        await utils.answer(message, "🗑 OpenAI API-ключ удалён.")