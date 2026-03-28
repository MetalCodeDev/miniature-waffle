# meta developer: @MetalCodeDev
import requests
from bs4 import BeautifulSoup
import random
from .. import loader, utils

@loader.tds
class SexKomixMod(loader.Module):
    """Модуль для поиска комиксов (18+) с навигацией кнопками"""
    strings = {"name": "ComixHub"}

    async def skcmd(self, message):
        """🔍 Поиск: .sk [запрос] [страница]"""
        args = utils.get_args(message)
        query = args[0] if args else ""
        page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        
        if not query:
            return await utils.answer(message, "❌ Введи поисковый запрос, например: `.sk мамочка`")

        await self.search_logic(message, query, page)

    async def search_logic(self, message, query, page):
        # Формируем URL точно под твой сайт
        url = f"https://top.sexkomix22.com/home/?only={query}&sort=date&page={page}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        try:
            res = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Селекторы для карточек на этом сайте
            items = soup.find_all('div', class_='short-item')
            if not items:
                return await utils.answer(message, f"Ничего не найдено на стр. {page}")

            out = f"📂 **Результаты:** `{query}`\n📄 **Страница:** {page}\n\n"
            for item in items[:6]:
                title = item.find('div', class_='short-title').text.strip()
                link = item.find('a')['href']
                out += f"• [{title}]({link})\n"

            # Кнопки управления
            buttons = [
                [
                    {"text": "⬅️ Назад", "callback": self.nav_inline, "args": (query, max(1, page-1))},
                    {"text": "Вперед ➡️", "callback": self.nav_inline, "args": (query, page+1)}
                ],
                [{"text": "🎲 Рандом", "callback": self.nav_inline, "args": (query, random.randint(1, 100))}]
            ]

            # Отправляем инлайн-форму (кнопки)
            await self.inline.form(text=out, message=message, buttons=buttons)
            
        except Exception as e:
            await utils.answer(message, f"🛑 Ошибка парсинга: {str(e)}")

    async def nav_inline(self, call, query, page):
        """Хендлер для нажатия кнопок"""
        await self.search_logic(call.message, query, page)

    def register(self, client):
        # Этот метод нужен для корректной инициализации в heroku/loader.py
        pass
