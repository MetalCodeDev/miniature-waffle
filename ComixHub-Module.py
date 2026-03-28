import requests
from bs4 import BeautifulSoup

def search_comics(query):
    # Формируем ссылку (на примере поиска по дате, как в твоем запросе)
    url = f"https://top.sexkomix22.com/home/?only={query}&sort=date"
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        # Здесь логика поиска контейнеров с комиксами
        items = soup.find_all('div', class_='thumb') # Класс взят для примера
        return [item.get_text() for item in items]
    return "Ничего не найдено"