import random
import re
import requests
from bs4 import BeautifulSoup
from .. import loader, utils  # Стандартные импорты для Hikka/FTG

@loader.tds
class ComixHubMod(loader.Module):
    """Поиск комиксов с кнопками и навигацией"""
    strings = {"name": "ComixHub"}

    async def skcmd(self, message):
        """🔍 Поиск: .sk [запрос]"""
        query = utils.get_args_raw(message)
        if not query:
            return await utils.answer(message, "⚠️ Введи название для поиска")
        
        await self.show_page(message, query, 1)

    async def show_page(self, message, query, page):
        url = f"https://top.sexkomix22.com/home/?only={query}&sort=date&page={page}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        try:
            res = requests.get(url, headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # ВАЖНО: Тут нужно адаптировать селекторы под реальную верстку сайта
            items = soup.find_all('div', class_='thumb-title') # Пример класса
            if not items:
                return await utils.answer(message, f"❌ Ничего не найдено на стр. {page}")

            text = f"📂 **Результаты для:** `{query}`\n📄 **Страница:** {page}\n\n"
            for i, item in enumerate(items[:5], 1):
                title = item.get_text(strip=True)
                link = item.find_parent('a')['href']
                text += f"{i}. [{title}]({link})\n"

            # Кнопки
            buttons = [
                [
                    {"text": "⬅️ Назад", "callback": self.change_page, "args": (query, max(1, page-1))},
                    {"text": "Вперед ➡️", "callback": self.change_page, "args": (query, page+1)},
                ],
                [{"text": "🎲 Рандом", "callback": self.change_page, "args": (query, random.randint(1, 50))}]
            ]

            await self.inline.form(text=text, message=message, buttons=buttons)
            
        except Exception as e:
            await utils.answer(message, f"Ошибка: {str(e)}")

    async def change_page(self, call, query, page):
        """Обработчик нажатия на кнопки"""
        await self.show_page(call.message, query, page)

    # Обязательная функция регистрации для лоадера
    def register(self, client):
        pass 
