import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.enums import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM"
ADMIN_IDS = {37607526, 103161998}

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ========== БАЗА ДАННЫХ (В ПАМЯТИ ДЛЯ ПРИМЕРА) ==========
class Database:
    def __init__(self):
        self.users: Dict[int, Dict] = {}
        self.tasks: Dict[int, Dict] = {}
        self.task_counter = 0
        self.admin_stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'active_users': set()
        }
    
    def add_user(self, user_id: int, username: str, full_name: str):
        if user_id not in self.users:
            self.users[user_id] = {
                'user_id': user_id,
                'username': username,
                'full_name': full_name,
                'joined': datetime.now(),
                'task_count': 0,
                'completed_count': 0
            }
    
    def add_task(self, user_id: int, text: str, category: str = "Общее") -> int:
        self.task_counter += 1
        self.tasks[self.task_counter] = {
            'id': self.task_counter,
            'user_id': user_id,
            'text': text,
            'category': category,
            'created': datetime.now(),
            'completed': False,
            'completed_at': None,
            'priority': 'medium'
        }
        
        if user_id in self.users:
            self.users[user_id]['task_count'] += 1
        
        self.admin_stats['total_tasks'] += 1
        self.admin_stats['active_users'].add(user_id)
        
        return self.task_counter
    
    def get_user_tasks(self, user_id: int, completed: Optional[bool] = None) -> List[Dict]:
        tasks = []
        for task in self.tasks.values():
            if task['user_id'] == user_id:
                if completed is None or task['completed'] == completed:
                    tasks.append(task)
        return sorted(tasks, key=lambda x: x['created'], reverse=True)
    
    def get_task(self, task_id: int) -> Optional[Dict]:
        return self.tasks.get(task_id)
    
    def toggle_task(self, task_id: int) -> bool:
        task = self.tasks.get(task_id)
        if task:
            task['completed'] = not task['completed']
            task['completed_at'] = datetime.now() if task['completed'] else None
            
            user_id = task['user_id']
            if task['completed']:
                if user_id in self.users:
                    self.users[user_id]['completed_count'] += 1
                self.admin_stats['completed_tasks'] += 1
            else:
                if user_id in self.users:
                    self.users[user_id]['completed_count'] -= 1
                self.admin_stats['completed_tasks'] -= 1
            
            return True
        return False
    
    def delete_task(self, task_id: int) -> bool:
        task = self.tasks.get(task_id)
        if task:
            user_id = task['user_id']
            if user_id in self.users:
                self.users[user_id]['task_count'] -= 1
                if task['completed']:
                    self.users[user_id]['completed_count'] -= 1
            
            del self.tasks[task_id]
            self.admin_stats['total_tasks'] -= 1
            if task['completed']:
                self.admin_stats['completed_tasks'] -= 1
            return True
        return False
    
    def get_all_tasks(self) -> List[Dict]:
        return list(self.tasks.values())
    
    def get_all_users(self) -> List[Dict]:
        return list(self.users.values())
    
    def update_task_priority(self, task_id: int, priority: str) -> bool:
        task = self.tasks.get(task_id)
        if task:
            task['priority'] = priority
            return True
        return False
    
    def update_task_category(self, task_id: int, category: str) -> bool:
        task = self.tasks.get(task_id)
        if task:
            task['category'] = category
            return True
        return False

db = Database()

# ========== СОСТОЯНИЯ (FSM) ==========
class TaskStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_category = State()
    waiting_for_priority = State()
    editing_text = State()
    editing_category = State()
    editing_priority = State()

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_user_message = State()

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Основная клавиатура для пользователя"""
    builder = ReplyKeyboardBuilder()
    
    builder.add(KeyboardButton(text="📝 Создать задачу"))
    builder.add(KeyboardButton(text="📋 Мои задачи"))
    builder.add(KeyboardButton(text="✅ Выполненные"))
    builder.add(KeyboardButton(text="📊 Статистика"))
    
    # Скрытые админ-кнопки только для админов
    if user_id in ADMIN_IDS:
        builder.add(KeyboardButton(text="⚙️ Админ-панель"))
    
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

def get_tasks_keyboard(tasks: List[Dict], page: int = 0, tasks_per_page: int = 5) -> InlineKeyboardMarkup:
    """Клавиатура для списка задач"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * tasks_per_page
    end_idx = start_idx + tasks_per_page
    page_tasks = tasks[start_idx:end_idx]
    
    for task in page_tasks:
        status = "✅" if task['completed'] else "⏳"
        emoji = "🔴" if task['priority'] == 'high' else "🟡" if task['priority'] == 'medium' else "🟢"
        btn_text = f"{status} {emoji} {task['text'][:30]}"
        builder.row(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"task_detail_{task['id']}"
        ))
    
    # Навигация
    navigation_buttons = []
    
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад", 
            callback_data=f"tasks_page_{page-1}"
        ))
    
    navigation_buttons.append(InlineKeyboardButton(
        text="❌ Закрыть", 
        callback_data="close_menu"
    ))
    
    if len(tasks) > end_idx:
        navigation_buttons.append(InlineKeyboardButton(
            text="Вперед ➡️", 
            callback_data=f"tasks_page_{page+1}"
        ))
    
    if navigation_buttons:
        builder.row(*navigation_buttons)
    
    return builder.as_markup()

def get_task_detail_keyboard(task_id: int, is_completed: bool) -> InlineKeyboardMarkup:
    """Клавиатура для детального просмотра задачи"""
    builder = InlineKeyboardBuilder()
    
    if not is_completed:
        builder.add(InlineKeyboardButton(
            text="✅ Отметить выполненной",
            callback_data=f"complete_task_{task_id}"
        ))
    else:
        builder.add(InlineKeyboardButton(
            text="↩️ Вернуть в активные",
            callback_data=f"uncomplete_task_{task_id}"
        ))
    
    builder.add(InlineKeyboardButton(
        text="✏️ Редактировать",
        callback_data=f"edit_task_{task_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🗑 Удалить",
        callback_data=f"delete_task_{task_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="📋 К списку задач",
        callback_data="back_to_tasks"
    ))
    
    builder.adjust(1)
    return builder.as_markup()

def get_priority_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора приоритета"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="🔴 Высокий",
        callback_data="priority_high"
    ))
    builder.add(InlineKeyboardButton(
        text="🟡 Средний",
        callback_data="priority_medium"
    ))
    builder.add(InlineKeyboardButton(
        text="🟢 Низкий",
        callback_data="priority_low"
    ))
    
    builder.adjust(1)
    return builder.as_markup()

def get_category_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора категории"""
    builder = InlineKeyboardBuilder()
    
    categories = ["Работа", "Учеба", "Личное", "Здоровье", "Финансы", "Другое"]
    
    for category in categories:
        builder.add(InlineKeyboardButton(
            text=category,
            callback_data=f"category_{category}"
        ))
    
    builder.add(InlineKeyboardButton(
        text="✏️ Своя категория",
        callback_data="category_custom"
    ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура админ-панели"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="📊 Статистика бота",
        callback_data="admin_stats"
    ))
    builder.add(InlineKeyboardButton(
        text="👥 Все пользователи",
        callback_data="admin_users"
    ))
    builder.add(InlineKeyboardButton(
        text="📋 Все задачи",
        callback_data="admin_tasks"
    ))
    builder.add(InlineKeyboardButton(
        text="📢 Рассылка",
        callback_data="admin_broadcast"
    ))
    builder.add(InlineKeyboardButton(
        text="✉️ Написать пользователю",
        callback_data="admin_message_user"
    ))
    builder.add(InlineKeyboardButton(
        text="📁 Экспорт данных",
        callback_data="admin_export"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 Главное меню",
        callback_data="back_to_main"
    ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_admin_tasks_keyboard(tasks: List[Dict], page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура для админского просмотра задач"""
    builder = InlineKeyboardBuilder()
    
    tasks_per_page = 5
    start_idx = page * tasks_per_page
    end_idx = start_idx + tasks_per_page
    page_tasks = tasks[start_idx:end_idx]
    
    for task in page_tasks:
        user = db.users.get(task['user_id'], {})
        username = user.get('username', 'Без имени')
        status = "✅" if task['completed'] else "⏳"
        btn_text = f"{status} @{username}: {task['text'][:25]}"
        builder.row(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"admin_task_detail_{task['id']}"
        ))
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"admin_tasks_page_{page-1}"
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="admin_back"
    ))
    
    if len(tasks) > end_idx:
        nav_buttons.append(InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"admin_tasks_page_{page+1}"
        ))
    
    builder.row(*nav_buttons)
    
    return builder.as_markup()

# ========== ФОРМАТИРОВАНИЕ ТЕКСТА ==========
def format_task(task: Dict) -> str:
    """Форматирование задачи для отображения"""
    user = db.users.get(task['user_id'], {})
    username = user.get('username', 'Неизвестно')
    
    status = "✅ <b>Выполнена</b>" if task['completed'] else "⏳ <b>В работе</b>"
    priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}[task['priority']]
    priority_text = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}[task['priority']]
    
    created = task['created'].strftime("%d.%m.%Y %H:%M")
    completed = task['completed_at'].strftime("%d.%m.%Y %H:%M") if task['completed_at'] else "Не выполнена"
    
    return f"""<b>📝 Задача #{task['id']}</b>

<b>Текст:</b> {task['text']}
<b>Категория:</b> {task['category']}
<b>Приоритет:</b> {priority_emoji} {priority_text}
<b>Статус:</b> {status}
<b>Создана:</b> {created}
<b>Выполнена:</b> {completed}
<b>Автор:</b> @{username}"""

def format_user_stats(user_id: int) -> str:
    """Форматирование статистики пользователя"""
    user = db.users.get(user_id, {})
    tasks = db.get_user_tasks(user_id)
    active_tasks = [t for t in tasks if not t['completed']]
    completed_tasks = [t for t in tasks if t['completed']]
    
    if tasks:
        progress = (len(completed_tasks) / len(tasks) * 100) if tasks else 0
        return f"""<b>📊 Ваша статистика</b>

👤 <b>Пользователь:</b> @{user.get('username', 'Без имени')}
📅 <b>С нами с:</b> {user.get('joined').strftime('%d.%m.%Y') if user.get('joined') else 'Неизвестно'}

<b>📈 Активность:</b>
📝 Всего задач: {len(tasks)}
✅ Выполнено: {len(completed_tasks)}
⏳ В работе: {len(active_tasks)}
🎯 Прогресс: {progress:.1f}%"""
    else:
        return "Создайте первую задачу, чтобы увидеть статистику!"

def format_admin_stats() -> str:
    """Форматирование статистики для админа"""
    total_users = len(db.users)
    total_tasks = db.admin_stats['total_tasks']
    completed_tasks = db.admin_stats['completed_tasks']
    active_users = len(db.admin_stats['active_users'])
    
    completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    return f"""<b>⚙️ Статистика бота</b>

<b>👥 Пользователи:</b>
• Всего пользователей: {total_users}
• Активных пользователей: {active_users}

<b>📝 Задачи:</b>
• Всего задач: {total_tasks}
• Выполнено: {completed_tasks}
• В работе: {total_tasks - completed_tasks}
• Процент выполнения: {completion_rate:.1f}%

<b>📅 За сегодня:</b>
• Новых пользователей: 0
• Создано задач: 0
• Выполнено задач: 0"""

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    username = message.from_user.username or "Без имени"
    full_name = message.from_user.full_name
    
    db.add_user(user_id, username, full_name)
    
    welcome_text = f"""<b>👋 Привет, {full_name}!</b>

Я — ваш персональный помощник по управлению задачами 📋

<b>📌 Что я умею:</b>
• Создавать задачи с категориями и приоритетами
• Отслеживать прогресс выполнения
• Показывать статистику продуктивности
• Напоминать о важных делах

Используйте кнопки ниже или команды:
/start - Главное меню
/help - Помощь
/tasks - Мои задачи

<b>🎯 Начните с создания первой задачи!</b>"""
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard(user_id))

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = """<b>🆘 Помощь по боту</b>

<b>📌 Основные команды:</b>
/start - Главное меню
/help - Эта справка
/tasks - Показать все задачи
/stats - Ваша статистика

<b>🎯 Как работать с задачами:</b>
1. Нажмите "📝 Создать задачу"
2. Введите текст задачи
3. Выберите категорию и приоритет
4. Отслеживайте выполнение в "📋 Мои задачи"
5. Отмечайте выполненные задачи

<b>🔔 Особенности:</b>
• Задачи можно редактировать
• Можно устанавливать приоритеты
• Ведется статистика продуктивности
• Данные хранятся безопасно

<b>💡 Советы:</b>
• Разбивайте большие задачи на мелкие
• Используйте категории для организации
• Регулярно проверяйте статистику"""
    
    await message.answer(help_text)

@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    """Обработчик команды /tasks"""
    await show_user_tasks(message.from_user.id, message.chat.id)

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@router.message(F.text == "📝 Создать задачу")
async def create_task_start(message: Message, state: FSMContext):
    """Начало создания задачи"""
    await message.answer(
        "📝 <b>Создание новой задачи</b>\n\n"
        "Введите текст задачи:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_creation")
            ]]
        )
    )
    await state.set_state(TaskStates.waiting_for_text)

@router.message(F.text == "📋 Мои задачи")
async def show_my_tasks(message: Message):
    """Показать задачи пользователя"""
    await show_user_tasks(message.from_user.id, message.chat.id)

@router.message(F.text == "✅ Выполненные")
async def show_completed_tasks(message: Message):
    """Показать выполненные задачи"""
    tasks = db.get_user_tasks(message.from_user.id, completed=True)
    
    if tasks:
        await message.answer(
            f"<b>✅ Выполненные задачи</b> (всего: {len(tasks)})",
            reply_markup=get_tasks_keyboard(tasks)
        )
    else:
        await message.answer("У вас нет выполненных задач 🎉")

@router.message(F.text == "📊 Статистика")
async def show_stats(message: Message):
    """Показать статистику пользователя"""
    await message.answer(
        format_user_stats(message.from_user.id),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
            ]]
        )
    )

@router.message(F.text == "⚙️ Админ-панель")
async def admin_panel(message: Message):
    """Показать админ-панель (только для админов)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет доступа к этой функции")
        return
    
    await message.answer(
        "<b>⚙️ Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard()
    )

# ========== FSM ОБРАБОТЧИКИ ==========
@router.message(TaskStates.waiting_for_text)
async def process_task_text(message: Message, state: FSMContext):
    """Обработка текста задачи"""
    if len(message.text) > 500:
        await message.answer("Текст задачи слишком длинный (макс. 500 символов)")
        return
    
    await state.update_data(text=message.text)
    
    await message.answer(
        "📂 <b>Выберите категорию:</b>",
        reply_markup=get_category_keyboard()
    )
    await state.set_state(TaskStates.waiting_for_category)

@router.callback_query(F.data.startswith("category_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории"""
    category = callback.data.split("_", 1)[1]
    
    if category == "custom":
        await callback.message.edit_text(
            "✏️ <b>Введите свою категорию:</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_creation")
                ]]
            )
        )
        await state.set_state(TaskStates.waiting_for_category)
        return
    
    await state.update_data(category=category)
    
    await callback.message.edit_text(
        "🎯 <b>Выберите приоритет:</b>\n\n"
        "🔴 Высокий - срочные и важные задачи\n"
        "🟡 Средний - обычные задачи\n"
        "🟢 Низкий - задачи без сроков",
        reply_markup=get_priority_keyboard()
    )
    await state.set_state(TaskStates.waiting_for_priority)

@router.message(TaskStates.waiting_for_category)
async def process_custom_category(message: Message, state: FSMContext):
    """Обработка пользовательской категории"""
    if len(message.text) > 50:
        await message.answer("Название категории слишком длинное (макс. 50 символов)")
        return
    
    await state.update_data(category=message.text)
    
    await message.answer(
        "🎯 <b>Выберите приоритет:</b>\n\n"
        "🔴 Высокий - срочные и важные задачи\n"
        "🟡 Средний - обычные задачи\n"
        "🟢 Низкий - задачи без сроков",
        reply_markup=get_priority_keyboard()
    )
    await state.set_state(TaskStates.waiting_for_priority)

@router.callback_query(F.data.startswith("priority_"))
async def process_priority(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора приоритета и сохранение задачи"""
    priority = callback.data.split("_", 1)[1]
    data = await state.get_data()
    
    task_id = db.add_task(
        user_id=callback.from_user.id,
        text=data['text'],
        category=data['category'],
    )
    
    # Обновляем приоритет
    db.update_task_priority(task_id, priority)
    
    await callback.message.edit_text(
        f"✅ <b>Задача создана!</b>\n\n"
        f"<b>Текст:</b> {data['text']}\n"
        f"<b>Категория:</b> {data['category']}\n"
        f"<b>Приоритет:</b> {priority}\n\n"
        f"ID задачи: <code>{task_id}</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="📋 К задачам", callback_data="back_to_tasks"),
                InlineKeyboardButton(text="➕ Еще задача", callback_data="create_another")
            ]]
        )
    )
    
    await state.clear()

# ========== ОБРАБОТЧИКИ ЗАДАЧ ==========
async def show_user_tasks(user_id: int, chat_id: int, page: int = 0):
    """Показать задачи пользователя"""
    tasks = db.get_user_tasks(user_id, completed=False)
    
    if tasks:
        await bot.send_message(
            chat_id,
            f"<b>📋 Ваши задачи</b> (всего активных: {len(tasks)})",
            reply_markup=get_tasks_keyboard(tasks, page)
        )
    else:
        await bot.send_message(
            chat_id,
            "У вас нет активных задач! 🎉\n\n"
            "Создайте новую задачу, нажав кнопку ниже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="📝 Создать задачу", callback_data="create_task_from_empty")
                ]]
            )
        )

@router.callback_query(F.data.startswith("task_detail_"))
async def show_task_detail(callback: CallbackQuery):
    """Показать детали задачи"""
    task_id = int(callback.data.split("_", 2)[2])
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != callback.from_user.id:
        await callback.answer("Задача не найдена!", show_alert=True)
        return
    
    await callback.message.edit_text(
        format_task(task),
        reply_markup=get_task_detail_keyboard(task_id, task['completed'])
    )

@router.callback_query(F.data.startswith("complete_task_"))
async def complete_task(callback: CallbackQuery):
    """Отметить задачу как выполненную"""
    task_id = int(callback.data.split("_", 2)[2])
    
    if db.toggle_task(task_id):
        task = db.get_task(task_id)
        await callback.message.edit_text(
            format_task(task),
            reply_markup=get_task_detail_keyboard(task_id, True)
        )
        await callback.answer("✅ Задача отмечена как выполненная!")
    else:
        await callback.answer("Ошибка!", show_alert=True)

@router.callback_query(F.data.startswith("uncomplete_task_"))
async def uncomplete_task(callback: CallbackQuery):
    """Вернуть задачу в активные"""
    task_id = int(callback.data.split("_", 2)[2])
    
    if db.toggle_task(task_id):
        task = db.get_task(task_id)
        await callback.message.edit_text(
            format_task(task),
            reply_markup=get_task_detail_keyboard(task_id, False)
        )
        await callback.answer("↩️ Задача возвращена в активные!")
    else:
        await callback.answer("Ошибка!", show_alert=True)

@router.callback_query(F.data.startswith("delete_task_"))
async def delete_task(callback: CallbackQuery):
    """Удалить задачу"""
    task_id = int(callback.data.split("_", 2)[2])
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != callback.from_user.id:
        await callback.answer("Ошибка!", show_alert=True)
        return
    
    # Подтверждение удаления
    await callback.message.edit_text(
        f"🗑 <b>Подтвердите удаление</b>\n\n"
        f"Задача: {task['text'][:100]}...\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{task_id}"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=f"task_detail_{task_id}")
                ]
            ]
        )
    )

@router.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete(callback: CallbackQuery):
    """Подтверждение удаления задачи"""
    task_id = int(callback.data.split("_", 2)[2])
    
    if db.delete_task(task_id):
        await callback.message.edit_text(
            "✅ <b>Задача удалена</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="📋 К задачам", callback_data="back_to_tasks")
                ]]
            )
        )
        await callback.answer("Задача удалена")
    else:
        await callback.answer("Ошибка удаления!", show_alert=True)

@router.callback_query(F.data.startswith("edit_task_"))
async def edit_task_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования задачи"""
    task_id = int(callback.data.split("_", 2)[2])
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != callback.from_user.id:
        await callback.answer("Ошибка!", show_alert=True)
        return
    
    await state.update_data(task_id=task_id)
    
    await callback.message.edit_text(
        "✏️ <b>Что вы хотите изменить?</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📝 Текст", callback_data="edit_text"),
                    InlineKeyboardButton(text="📂 Категория", callback_data="edit_category")
                ],
                [
                    InlineKeyboardButton(text="🎯 Приоритет", callback_data="edit_priority"),
                    InlineKeyboardButton(text="🔙 Назад", callback_data=f"task_detail_{task_id}")
                ]
            ]
        )
    )

@router.callback_query(F.data == "edit_text")
async def edit_task_text(callback: CallbackQuery, state: FSMContext):
    """Редактирование текста задачи"""
    data = await state.get_data()
    task_id = data['task_id']
    
    await callback.message.edit_text(
        "📝 <b>Введите новый текст задачи:</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"task_detail_{task_id}")
            ]]
        )
    )
    await state.set_state(TaskStates.editing_text)

@router.message(TaskStates.editing_text)
async def process_edit_text(message: Message, state: FSMContext):
    """Обработка нового текста задачи"""
    data = await state.get_data()
    task_id = data['task_id']
    task = db.get_task(task_id)
    
    if task and task['user_id'] == message.from_user.id:
        task['text'] = message.text
        await message.answer(
            "✅ <b>Текст задачи обновлен!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="📋 К задаче", callback_data=f"task_detail_{task_id}")
                ]]
            )
        )
    await state.clear()

# ========== АДМИН ОБРАБОТЧИКИ ==========
@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    """Статистика для админа"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        format_admin_stats(),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
            ]]
        )
    )

@router.callback_query(F.data == "admin_tasks")
async def admin_tasks_handler(callback: CallbackQuery):
    """Все задачи для админа"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    tasks = db.get_all_tasks()
    
    if tasks:
        await callback.message.edit_text(
            f"<b>📋 Все задачи в системе</b> (всего: {len(tasks)})",
            reply_markup=get_admin_tasks_keyboard(tasks)
        )
    else:
        await callback.message.edit_text(
            "В системе пока нет задач",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
                ]]
            )
        )

@router.callback_query(F.data.startswith("admin_task_detail_"))
async def admin_task_detail(callback: CallbackQuery):
    """Детали задачи для админа"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    task_id = int(callback.data.split("_", 3)[3])
    task = db.get_task(task_id)
    
    if not task:
        await callback.answer("Задача не найдена!", show_alert=True)
        return
    
    user = db.users.get(task['user_id'], {})
    username = user.get('username', 'Неизвестно')
    
    await callback.message.edit_text(
        format_task(task),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_delete_task_{task_id}"),
                    InlineKeyboardButton(text="✉️ Написать", callback_data=f"admin_message_{task['user_id']}")
                ],
                [
                    InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tasks")
                ]
            ]
        )
    )

@router.callback_query(F.data == "admin_users")
async def admin_users_handler(callback: CallbackQuery):
    """Все пользователи для админа"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    users = db.get_all_users()
    
    text = "<b>👥 Все пользователи</b>\n\n"
    for i, user in enumerate(users, 1):
        user_tasks = db.get_user_tasks(user['user_id'])
        active_tasks = len([t for t in user_tasks if not t['completed']])
        
        text += f"{i}. @{user.get('username', 'Без имени')}\n"
        text += f"   📝 Задач: {len(user_tasks)} | ⏳ Активных: {active_tasks}\n"
        text += f"   📅 С: {user['joined'].strftime('%d.%m.%Y')}\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
            ]]
        )
    )

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 <b>Рассылка сообщения</b>\n\n"
        "Введите сообщение для рассылки всем пользователям:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
            ]]
        )
    )
    await state.set_state(AdminStates.waiting_broadcast)

@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    """Обработка рассылки"""
    users = list(db.users.keys())
    success = 0
    failed = 0
    
    await message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")
    
    for user_id in users:
        try:
            await bot.send_message(user_id, f"📢 <b>Важное сообщение от администрации:</b>\n\n{message.text}")
            success += 1
            await asyncio.sleep(0.05)  # Защита от лимитов
        except Exception as e:
            failed += 1
    
    await message.answer(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Не удалось: {failed}",
        reply_markup=get_admin_keyboard()
    )
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_message_"))
async def admin_message_user_start(callback: CallbackQuery, state: FSMContext):
    """Начало отправки сообщения пользователю"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_", 2)[2])
    await state.update_data(target_user_id=user_id)
    
    user = db.users.get(user_id, {})
    
    await callback.message.edit_text(
        f"✉️ <b>Отправка сообщения пользователю</b>\n\n"
        f"Пользователь: @{user.get('username', 'Неизвестно')}\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"Введите ваше сообщение:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
            ]]
        )
    )
    await state.set_state(AdminStates.waiting_user_message)

@router.message(AdminStates.waiting_user_message)
async def process_admin_message(message: Message, state: FSMContext):
    """Обработка сообщения от админа пользователю"""
    data = await state.get_data()
    target_user_id = data['target_user_id']
    
    try:
        await bot.send_message(
            target_user_id,
            f"✉️ <b>Сообщение от администратора:</b>\n\n{message.text}"
        )
        await message.answer(
            f"✅ Сообщение отправлено пользователю ID: {target_user_id}",
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось отправить сообщение: {str(e)}",
            reply_markup=get_admin_keyboard()
        )
    
    await state.clear()

# ========== ОБЩИЕ ОБРАБОТЧИКИ ==========
@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Вернуться в главное меню"""
    await callback.message.edit_text(
        "<b>📋 Главное меню</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )

@router.callback_query(F.data == "back_to_tasks")
async def back_to_tasks(callback: CallbackQuery):
    """Вернуться к списку задач"""
    await show_user_tasks(callback.from_user.id, callback.message.chat.id)

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    """Назад в админ-панель"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<b>⚙️ Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard()
    )

@router.callback_query(F.data == "close_menu")
async def close_menu(callback: CallbackQuery):
    """Закрыть меню"""
    await callback.message.delete()

@router.callback_query(F.data == "cancel_creation")
async def cancel_creation(callback: CallbackQuery, state: FSMContext):
    """Отмена создания задачи"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Создание задачи отменено",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="📋 Главное меню", callback_data="back_to_main")
            ]]
        )
    )

@router.callback_query(F.data == "cancel_edit")
async def cancel_edit(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Редактирование отменено",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="📋 Главное меню", callback_data="back_to_main")
            ]]
        )
    )

# ========== ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ ==========
@router.callback_query(F.data.startswith("tasks_page_"))
async def change_tasks_page(callback: CallbackQuery):
    """Смена страницы задач"""
    page = int(callback.data.split("_", 2)[2])
    await show_user_tasks(callback.from_user.id, callback.message.chat.id, page)

@router.callback_query(F.data.startswith("admin_tasks_page_"))
async def change_admin_tasks_page(callback: CallbackQuery):
    """Смена страницы админских задач"""
    page = int(callback.data.split("_", 3)[3])
    tasks = db.get_all_tasks()
    
    await callback.message.edit_text(
        f"<b>📋 Все задачи в системе</b> (всего: {len(tasks)})",
        reply_markup=get_admin_tasks_keyboard(tasks, page)
    )

@router.callback_query(F.data == "create_another")
async def create_another_task(callback: CallbackQuery, state: FSMContext):
    """Создать еще одну задачу"""
    await create_task_start(callback.message, state)

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    logger.info("Бот запускается...")
    
    # Пропускаем накопленные updates
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запуск polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
