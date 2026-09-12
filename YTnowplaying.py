# requires: pillow requests
import requests
import io
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .. import loader, utils

@loader.tds
class YTMNowPlayingMod(loader.Module):
    """Показывает, что играет сейчас через Last.fm с генерацией картинки"""
    
    strings = {
        "name": "NowPlaying",
        "no_api_key": "❌ <b>Ошибка:</b> Укажи API-ключ Last.fm в конфигурации (настройки Hikka/Heroku).",
        "no_username": "❌ <b>Ошибка:</b> Укажи свой логин Last.fm в конфигурации.",
        "nothing_playing": "🔇 <b>Сейчас ничего не играет.</b> (Или скробблер не работает)",
        "processing": "🎨 <b>Рисую карточку...</b>",
        "error": "❌ <b>Произошла ошибка при получении данных:</b> {}"
    }

    def __init__(self):
        # Настройки, которые появятся в веб-панели или конфиге юзербота
        self.config = loader.ModuleConfig(
            "API_KEY", "", "Твой API Key от Last.fm",
            "USERNAME", "", "Твой никнейм на Last.fm"
        )

    @loader.command(ru_doc="Сгенерировать картинку текущего трека")
    async def npcmd(self, message):
        """- Отправляет картинку с текущим треком"""
        api_key = self.config["API_KEY"]
        username = self.config["USERNAME"]

        if not api_key:
            return await utils.answer(message, self.strings("no_api_key"))
        if not username:
            return await utils.answer(message, self.strings("no_username"))

        msg = await utils.answer(message, self.strings("processing"))

        # 1. Запрашиваем данные у Last.fm
        url = f"http://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={username}&api_key={api_key}&format=json&limit=1"
        try:
            response = requests.get(url).json()
            
            if "error" in response:
                return await utils.answer(msg, self.strings("error").format(response["message"]))
                
            tracks = response.get("recenttracks", {}).get("track", [])
            if not tracks:
                return await utils.answer(msg, self.strings("nothing_playing"))

            current_track = tracks[0]
            
            # Проверяем, играет ли трек прямо сейчас
            is_playing = current_track.get("@attr", {}).get("nowplaying") == "true"
            if not is_playing:
                 return await utils.answer(msg, self.strings("nothing_playing"))

            artist = current_track["artist"]["#text"]
            track_name = current_track["name"]
            
            # Берем самую большую обложку (extralarge)
            image_url = ""
            for img in current_track.get("image", []):
                if img["size"] == "extralarge" and img["#text"]:
                    image_url = img["#text"]

            # Если обложки нет, используем заглушку
            if not image_url:
                image_url = "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"

        except Exception as e:
            return await utils.answer(msg, self.strings("error").format(str(e)))

        # 2. Генерируем картинку
        try:
            # Скачиваем обложку
            img_data = requests.get(image_url).content
            cover = Image.open(io.BytesIO(img_data)).convert("RGBA")
            cover = cover.resize((300, 300))

            # Создаем фон (берем обложку, увеличиваем и сильно размываем)
            background = cover.resize((800, 400))
            background = background.filter(ImageFilter.GaussianBlur(50))
            
            # Затемняем фон для лучшей читаемости текста
            darker = Image.new('RGBA', background.size, (0, 0, 0, 100))
            background = Image.alpha_composite(background, darker)

            # Вставляем четкую обложку на фон слева
            background.paste(cover, (50, 50), cover)

            # Рисуем текст
            draw = ImageDraw.Draw(background)
            
            # Пытаемся загрузить стандартный шрифт, если нет - используем дефолтный
            try:
                # На серверах Ubuntu обычно есть этот шрифт
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
                font_artist = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
            except IOError:
                 # Фоллбэк (текст будет не очень красивым, но код не упадет)
                font_title = ImageFont.load_default()
                font_artist = ImageFont.load_default()

            # Обрезаем слишком длинные названия
            if len(track_name) > 25: track_name = track_name[:22] + "..."
            if len(artist) > 30: artist = artist[:27] + "..."

            # Пишем текст (Название трека и артист)
            draw.text((400, 100), "Now Playing:", font=font_artist, fill=(200, 200, 200, 255))
            draw.text((400, 150), track_name, font=font_title, fill=(255, 255, 255, 255))
            draw.text((400, 210), artist, font=font_artist, fill=(200, 200, 200, 255))

            # Сохраняем результат в байты, чтобы отправить в телеграм без сохранения на диск
            output = io.BytesIO()
            output.name = "now_playing.png"
            background.save(output, format="PNG")
            output.seek(0)

            # 3. Отправляем в чат
            await message.client.send_file(
                message.to_id,
                file=output,
                caption=f"🎧 <b>{artist} — {track_name}</b>"
            )
            
            # Удаляем сообщение с текстом "Рисую карточку..."
            await msg.delete()

        except Exception as e:
            await utils.answer(msg, self.strings("error").format(f"Ошибка отрисовки: {str(e)}"))

