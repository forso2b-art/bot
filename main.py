import asyncio
import logging
import re
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message

# --- CONFIGURATION ---
# Я оставил ваш токен, но будьте осторожны, не светите им
API_TOKEN = '8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM' 
ADMIN_IDS = [103161998, 37607526]

# --- SETUP ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- PINTEREST DOWNLOAD LOGIC ---
def get_pinterest_image_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, allow_redirects=True)
        if response.status_code != 200:
            return None
        
        # Поиск ссылки на изображение
        match = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        return None

# --- HANDLERS ---

@dp.message(Command("start"))
async def send_welcome(message: Message):
    await message.reply("Система активна (v3). Пришлите ссылку на Pinterest.")

# Админ-панель
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.reply(f"Admin Panel Access Granted.\nUser ID: {message.from_user.id}\nStatus: Superuser")

# Рассылка
@dp.message(Command("broadcast"))
async def broadcast_message(message: Message):
    if message.from_user.id in ADMIN_IDS:
        # Разбиваем сообщение, чтобы получить аргументы
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("Error: Empty message. Use /broadcast <text>")
            return
        await message.reply(f"Broadcasting to network: {parts[1]}")

# Обработка ссылок (используем Magic Filter F)
@dp.message(F.text.regexp(r'(https?://)?(www\.)?(pinterest\.(com|ru)|pin\.it)/.+'))
async def process_pinterest_link(message: Message):
    await message.answer("Обработка запроса...")
    
    url = message.text
    image_url = get_pinterest_image_url(url)
    
    if image_url:
        await bot.send_photo(chat_id=message.chat.id, photo=image_url, caption="Изображение извлечено.")
    else:
        await message.reply("Ошибка: Не удалось извлечь изображение.")

# Запуск
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
