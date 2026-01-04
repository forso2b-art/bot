import logging
import re
import requests
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters import IDFilter

# --- CONFIGURATION ---
API_TOKEN = '8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM'  # Вставьте сюда токен
ADMIN_IDS = [103161998, 37607526]

# --- SETUP ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- PINTEREST DOWNLOAD LOGIC ---
def get_pinterest_image_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, allow_redirects=True)
        if response.status_code != 200:
            return None
        
        # Поиск ссылки на изображение в мета-тегах (og:image)
        match = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        return None

# --- HANDLERS ---

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply("Система активна. Пришлите ссылку на Pinterest.")

# Админ-панель: Статистика (доступна только админам)
@dp.message_handler(commands=['admin'], user_id=ADMIN_IDS)
async def admin_panel(message: types.Message):
    await message.reply(f"Admin Panel Access Granted.\nUser ID: {message.from_user.id}\nStatus: Superuser")

# Админ-панель: Рассылка (пример функции для админов)
@dp.message_handler(commands=['broadcast'], user_id=ADMIN_IDS)
async def broadcast_message(message: types.Message):
    args = message.get_args()
    if not args:
        await message.reply("Error: Empty message. Use /broadcast <text>")
        return
    await message.reply(f"Broadcasting to network: {args}")

# Обработка ссылок
@dp.message_handler(regexp=r'(https?://)?(www\.)?(pinterest\.(com|ru)|pin\.it)/.+')
async def process_pinterest_link(message: types.Message):
    await message.answer("Обработка запроса...")
    
    url = message.text
    image_url = get_pinterest_image_url(url)
    
    if image_url:
        await bot.send_photo(chat_id=message.chat.id, photo=image_url, caption="Изображение извлечено.")
    else:
        await message.reply("Ошибка: Не удалось извлечь изображение. Возможно, ссылка некорректна.")

# Запуск
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
