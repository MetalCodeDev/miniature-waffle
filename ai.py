from .. import loader, utils
import aiohttp
import openai


@loader.tds
class AIModule(loader.Module):
    """AI assistant via OpenRouter | Developer: @mxzavo"""

    strings = {
        "name": "AI",
        "no_key": (
            "⚠️ OpenRouter API-ключ не настроен.\n"
            "Используй: .aiconfig <ключ>"
        ),
        "processing": "🤖 Думаю...",
        "no_prompt": (
            "❓ Напиши вопрос после .ai "
            "или ответь .ai на сообщение."
        ),
        "cleared": "🗑 История очищена.",
        "model_set": "✅ Выбрана модель: {}",
        "current_model": "🤖 Текущая модель: `{}`",
        "models_loading": "⏳ Получаю список бесплатных моделей...",
        "models_empty": "❌ Бесплатные модели не найдены.",
        "model_error": "❌ Не удалось получить список моделей.",
        "bad_model": "❌ Неверный номер модели.",
        "error": "❌ Ошибка: {}",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "API_KEY",
                None,
                "OpenRouter API key",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "MODEL",
                "openrouter/free",
                "OpenRouter model",
            ),
        )

        self.models = []

    @loader.command()
    async def ai(self, message):
        """<текст> — задать вопрос AI"""

        api_key = self.config["API_KEY"]

        if not api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        prompt = utils.get_args_raw(message)

        if not prompt and message.is_reply:
            reply = await message.get_reply_message()

            if reply:
                prompt = reply.raw_text

        if not prompt:
            await utils.answer(message, self.strings("no_prompt"))
            return

        await utils.answer(message, self.strings("processing"))

        try:
            client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )

            response = await client.chat.completions.create(
                model=self.config["MODEL"],
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            answer = response.choices[0].message.content

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
        """<ключ> — установить OpenRouter API-ключ"""

        key = utils.get_args_raw(message)

        if not key:
            await utils.answer(
                message,
                "🔑 Использование:\n"
                ".aiconfig <OpenRouter API key>"
            )
            return

        self.config["API_KEY"] = key

        try:
            await message.delete()
        except Exception:
            pass

        await utils.answer(
            message,
            "✅ OpenRouter API-ключ сохранён."
        )

    @loader.command()
    async def aimodels(self, message):
        """Показать доступные бесплатные модели"""

        api_key = self.config["API_KEY"]

        if not api_key:
            await utils.answer(message, self.strings("no_key"))
            return

        await utils.answer(
            message,
            self.strings("models_loading")
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}"
                    },
                    timeout=15,
                ) as response:

                    if response.status != 200:
                        await utils.answer(
                            message,
                            self.strings("model_error")
                        )
                        return

                    data = await response.json()

            free_models = []

            for model in data.get("data", []):
                pricing = model.get("pricing", {})

                prompt_price = pricing.get("prompt", "1")
                completion_price = pricing.get("completion", "1")

                try:
                    if (
                        float(prompt_price) == 0
                        and float(completion_price) == 0
                    ):
                        free_models.append(model)
                except (ValueError, TypeError):
                    continue

            if not free_models:
                await utils.answer(
                    message,
                    self.strings("models_empty")
                )
                return

            free_models.sort(
                key=lambda x: x.get("name", "").lower()
            )

            self.models = free_models

            text = "🆓 <b>Бесплатные модели:</b>\n\n"

            for i, model in enumerate(
                free_models[:30],
                start=1
            ):
                name = model.get(
                    "name",
                    model.get("id", "Unknown")
                )

                text += f"<b>{i}.</b> {name}\n"

            text += (
                "\nИспользование:\n"
                "<code>.aimodel номер</code>"
            )

            await utils.answer(message, text)

        except Exception:
            await utils.answer(
                message,
                self.strings("model_error")
            )

    @loader.command()
    async def aimodel(self, message):
        """<номер> — выбрать бесплатную модель"""

        args = utils.get_args_raw(message)

        if not args:
            await utils.answer(
                message,
                self.strings("current_model").format(
                    self.config["MODEL"]
                )
            )
            return

        try:
            number = int(args)
        except ValueError:
            await utils.answer(
                message,
                self.strings("bad_model")
            )
            return

        if (
            number < 1
            or number > len(self.models)
        ):
            await utils.answer(
                message,
                "❌ Сначала выполни .aimodels"
            )
            return

        model = self.models[number - 1]

        model_id = model.get("id")

        if not model_id:
            await utils.answer(
                message,
                self.strings("bad_model")
            )
            return

        self.config["MODEL"] = model_id

        await utils.answer(
            message,
            self.strings("model_set").format(
                model.get("name", model_id)
            )
        )

    @loader.command()
    async def aiclear(self, message):
        """Сбросить выбранную модель"""

        self.config["MODEL"] = "openrouter/free"

        await utils.answer(
            message,
            "🔄 Модель сброшена на автоматический "
            "выбор бесплатной модели."
        )
