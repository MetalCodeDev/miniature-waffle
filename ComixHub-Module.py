import requests
from bs4 import BeautifulSoup
from .. import loader, utils # Стандарт для Hikka/FTG

@loader.tds
class ComixSearchMod(loader.Module):
    """Поиск по команде .sk с кнопками"""
    strings = {"name": "ComixHub"}

    async def skcmd(self, message):
        """🔍 Поиск: .sk [запрос] [страница]"""
        args = utils.get_args(message)
        query = args[0] if args else ""
        page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        
        await self.fetch_and_send(message, query, page)

    async def fetch_and_send(self, message, query, page):
        url = f"https://top.sexkomix22.com/home/?only={query}&sort=date&page={page}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Ищем карточки комиксов
            items = soup.find_all('div', class_='short-item') 
            if not items:
                return await utils.answer(message, f"Ничего не нашлось на стр. {page}")

            res_text = [f"🔍 **Результаты по запросу:** `{query}` (Стр. {page})\n"]
            for item in items[:8]:
                title = item.find('div', class_='short-title').get_text(strip=True)
                link = item.find('a')['href']
                res_text.append(f"🔹 [{title}]({link})")

            text = "\n".join(res_text)
            
            # Кнопки навигации
            buttons = [
                [
                    {"text": "⬅️ Назад", "callback": self.nav, "args": (query, max(1, page-1))},
                    {"text": "Вперед ➡️", "callback": self.nav, "args": (query, page+1)}
                ],
                [{"text": "🎲 Рандом", "callback": self.nav, "args": (query, __import__('random').randint(1, 100))}]
            ]

            await self.inline.form(text=text, message=message, buttons=buttons)
        except Exception as e:
            await utils.answer(message, f"Ошибка: {e}")

    async def nav(self, call, query, page):
        await self.fetch_and_send(call.message, query, page)
