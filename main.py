import asyncio
import logging
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- CONFIGURATION ---
API_TOKEN = '8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM'
ADMIN_IDS = [103161998, 37607526]

# --- SETUP ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- STATES FOR ADMIN ---
class AdminState(StatesGroup):
    waiting_for_broadcast = State()

# --- KEYBOARDS (INTERFACE) ---
def get_main_keyboard():
    kb = [
        [InlineKeyboardButton(text="🆘 Помощь", callback_data="help"),
         InlineKeyboardButton(text="👨‍💻 Статус", callback_data="status")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_admin_keyboard():
    kb = [
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- LOGIC ---
def get_pinterest_media(url):
    try:
        # Эмуляция реального браузера, чтобы Pinterest не блокировал
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
        
        session = requests.Session()
        response = session.get(url, headers=headers, allow_redirects=True)
        
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Попытка 1: Мета-теги (стандарт)
        image = soup.find("meta", property="og:image")
        if image:
            return image["content"]
            
        # Попытка 2: Поиск в JSON данных внутри страницы (если мета скрыты)
        # Это сложнее, но часто надежнее. Пока оставим базовый парсинг + UserAgent.
        return None

    except Exception as e:
        logging.error(f"Error parsing: {e}")
        return None

# --- HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 **Система Pinterest Downloader v4**\n\n"
        "Отправьте мне ссылку на Pinterest (pin.it или pinterest.com), "
        "и я достану изображение в лучшем качестве.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    text = (
        "ℹ️ **Инструкция:**\n"
        "1. Скопируйте ссылку на пин.\n"
        "2. Вставьте её в чат.\n"
        "3. Бот отправит фото.\n\n"
        "Поддерживаются ссылки: `pin.it`, `pinterest.com`"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "status")
async def callback_status(callback: CallbackQuery):
    await callback.answer("Система работает стабильно. Сервер: Online", show_alert=True)

# --- ADMIN PANEL ---

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return # Игнорируем посторонних полностью (Security)
    
    await message.answer("🔓 **Панель Администратора**\nВыберите действие:", reply_markup=get_admin_keyboard())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.answer("Статистика: Бот активен. (Здесь можно подключить БД)", show_alert=True)

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.answer("Введите текст для рассылки (или /cancel):")
    await state.set_state(AdminState.waiting_for_broadcast)
    await callback.answer()

@dp.message(AdminState.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Рассылка отменена.")
        return
        
    await message.answer(f"✅ Сообщение разослано (эмуляция): {message.text}")
    # Тут цикл for user in users: send_message...
    await state.clear()

@dp.callback_query(F.data == "close_panel")
async def close_panel(callback: CallbackQuery):
    await callback.message.delete()

# --- DOWNLOAD LOGIC ---

@dp.message(F.text.regexp(r'(https?://)?(www\.)?(pinterest\.(com|ru)|pin\.it)/.+'))
async def process_pinterest_link(message: Message):
    status_msg = await message.answer("🔍 *Ищу изображение...*", parse_mode="Markdown")
    
    url = message.text
    image_url = get_pinterest_media(url)
    
    if image_url:
        await status_msg.delete()
        
        # Клавиатура под фото
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Источник", url=url)]
        ])
        
        await bot.send_photo(
            chat_id=message.chat.id, 
            photo=image_url, 
            caption="✅ **Успешно загружено**", 
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        await status_msg.edit_text(
            "❌ **Ошибка.**\nНе удалось получить изображение. Возможно, профиль закрыт или ссылка ведет на коллекцию, а не на пин."
        )

# --- START ---
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
