import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Optional, Set

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
    FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.enums import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8193091744:AAHjUopkLIBC5zuP4swtDkFKaFUeVqqnoEc"
CREATOR_ID = 103161998
ADMIN_IDS = {37607526, 103161998}  # Изначальные админы

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

# ========== БАЗА ДАННЫХ С СИСТЕМОЙ РОЛЕЙ И БАНОМ ==========
class Database:
    def __init__(self):
        self.users: Dict[int, Dict] = {}
        self.tasks: Dict[int, Dict] = {}
        self.task_counter = 0
        self.admin_stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'active_users': set(),
            'tasks_today': 0,
            'users_today': set()
        }
        
        # Система ролей и банов
        self.roles: Dict[int, str] = {}  # user_id -> role (creator/admin/user)
        self.banned_users: Set[int] = set()  # Забаненные пользователи
        
        # Инициализация создателя
        self.roles[CREATOR_ID] = 'creator'
    
    def add_user(self, user_id: int, username: str, full_name: str):
        """Добавление пользователя с проверкой на бан"""
        if user_id in self.banned_users:
            return False
        
        if user_id not in self.users:
            self.users[user_id] = {
                'user_id': user_id,
                'username': username,
                'full_name': full_name,
                'joined': datetime.now(),
                'task_count': 0,
                'completed_count': 0,
                'last_active': datetime.now(),
                'warnings': 0  # Количество предупреждений
            }
            
            # Установка роли по умолчанию
            if user_id not in self.roles:
                if user_id in ADMIN_IDS:
                    self.roles[user_id] = 'admin'
                else:
                    self.roles[user_id] = 'user'
            
            if datetime.now().date() == self.users[user_id]['joined'].date():
                self.admin_stats['users_today'].add(user_id)
        return True
    
    def get_user_role(self, user_id: int) -> str:
        """Получение роли пользователя"""
        return self.roles.get(user_id, 'user')
    
    def is_banned(self, user_id: int) -> bool:
        """Проверка, забанен ли пользователь"""
        return user_id in self.banned_users
    
    def ban_user(self, user_id: int, reason: str = "Нарушение правил") -> bool:
        """Бан пользователя"""
        if user_id == CREATOR_ID:
            return False  # Нельзя забанить создателя
        
        # Проверяем права того, кто банит
        # Только создатель может банить админов
        if self.get_user_role(user_id) == 'admin':
            # Для бана админа нужен создатель
            return False
        
        self.banned_users.add(user_id)
        
        # Удаляем все задачи забаненного пользователя
        task_ids_to_delete = []
        for task_id, task in self.tasks.items():
            if task['user_id'] == user_id:
                task_ids_to_delete.append(task_id)
        
        for task_id in task_ids_to_delete:
            self.delete_task(task_id)
        
        # Удаляем из статистики
        if user_id in self.admin_stats['active_users']:
            self.admin_stats['active_users'].remove(user_id)
        if user_id in self.admin_stats['users_today']:
            self.admin_stats['users_today'].remove(user_id)
        
        logger.info(f"User {user_id} banned. Reason: {reason}")
        return True
    
    def unban_user(self, user_id: int) -> bool:
        """Разбан пользователя"""
        if user_id in self.banned_users:
            self.banned_users.remove(user_id)
            logger.info(f"User {user_id} unbanned")
            return True
        return False
    
    def set_admin(self, user_id: int) -> bool:
        """Назначение пользователя админом"""
        if user_id == CREATOR_ID:
            return False  # Создатель уже выше админа
        
        if self.is_banned(user_id):
            return False
        
        self.roles[user_id] = 'admin'
        
        # Добавляем в список админов если нужно
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.add(user_id)
        
        logger.info(f"User {user_id} promoted to admin")
        return True
    
    def remove_admin(self, user_id: int) -> bool:
        """Снятие пользователя с админки"""
        if user_id == CREATOR_ID:
            return False  # Нельзя снять создателя
        
        if self.get_user_role(user_id) == 'admin':
            self.roles[user_id] = 'user'
            
            # Удаляем из списка админов если нужно
            if user_id in ADMIN_IDS:
                ADMIN_IDS.remove(user_id)
            
            logger.info(f"User {user_id} demoted from admin")
            return True
        return False
    
    def can_manage_user(self, manager_id: int, target_id: int) -> bool:
        """Проверка прав на управление пользователем"""
        manager_role = self.get_user_role(manager_id)
        target_role = self.get_user_role(target_id)
        
        if manager_id == CREATOR_ID:
            return True  # Создатель может управлять всеми
        
        if manager_role == 'admin':
            # Админ может управлять только обычными пользователями
            return target_role == 'user'
        
        return False
    
    def can_ban_user(self, manager_id: int, target_id: int) -> bool:
        """Проверка прав на бан пользователя"""
        manager_role = self.get_user_role(manager_id)
        target_role = self.get_user_role(target_id)
        
        if manager_id == CREATOR_ID:
            return target_id != CREATOR_ID  # Создатель может банить всех кроме себя
        
        if manager_role == 'admin':
            # Админ может банить только обычных пользователей
            return target_role == 'user'
        
        return False
    
    def get_all_admins(self) -> List[int]:
        """Получение списка всех админов"""
        return [user_id for user_id, role in self.roles.items() if role == 'admin']
    
    def get_all_users_with_roles(self) -> List[Dict]:
        """Получение всех пользователей с информацией о ролях и бане"""
        result = []
        for user_id, user_data in self.users.items():
            user_copy = user_data.copy()
            user_copy['role'] = self.get_user_role(user_id)
            user_copy['banned'] = self.is_banned(user_id)
            result.append(user_copy)
        return result
    
    def add_task(self, user_id: int, text: str, category: str = "Общее") -> Optional[int]:
        """Добавление задачи с проверкой на бан"""
        if self.is_banned(user_id):
            return None
        
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
            self.users[user_id]['last_active'] = datetime.now()
        
        self.admin_stats['total_tasks'] += 1
        self.admin_stats['active_users'].add(user_id)
        
        if datetime.now().date() == self.tasks[self.task_counter]['created'].date():
            self.admin_stats['tasks_today'] += 1
        
        return self.task_counter
    
    def get_user_tasks(self, user_id: int, completed: Optional[bool] = None) -> List[Dict]:
        """Получение задач пользователя с проверкой на бан"""
        if self.is_banned(user_id):
            return []
        
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
        if task and not self.is_banned(task['user_id']):
            was_completed = task['completed']
            task['completed'] = not task['completed']
            task['completed_at'] = datetime.now() if task['completed'] else None
            
            user_id = task['user_id']
            if user_id in self.users:
                if task['completed'] and not was_completed:
                    self.users[user_id]['completed_count'] += 1
                elif not task['completed'] and was_completed:
                    self.users[user_id]['completed_count'] -= 1
            
            if task['completed'] and not was_completed:
                self.admin_stats['completed_tasks'] += 1
            elif not task['completed'] and was_completed:
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
        if task and not self.is_banned(task['user_id']):
            task['priority'] = priority
            return True
        return False
    
    def update_task_category(self, task_id: int, category: str) -> bool:
        task = self.tasks.get(task_id)
        if task and not self.is_banned(task['user_id']):
            task['category'] = category
            return True
        return False
    
    def update_task_text(self, task_id: int, text: str) -> bool:
        task = self.tasks.get(task_id)
        if task and not self.is_banned(task['user_id']):
            task['text'] = text
            return True
        return False
    
    def get_tasks_by_category(self, user_id: int, category: str) -> List[Dict]:
        if self.is_banned(user_id):
            return []
        return [task for task in self.tasks.values() 
                if task['user_id'] == user_id and task['category'] == category]
    
    def search_tasks(self, user_id: int, query: str) -> List[Dict]:
        if self.is_banned(user_id):
            return []
        return [task for task in self.tasks.values() 
                if task['user_id'] == user_id and query.lower() in task['text'].lower()]

db = Database()

# ========== СОСТОЯНИЯ (FSM) ==========
class TaskStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_category = State()
    waiting_for_priority = State()
    editing_text = State()
    editing_category = State()
    editing_priority = State()
    searching_tasks = State()

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_user_message = State()
    waiting_user_id = State()
    waiting_export_format = State()
    waiting_admin_id = State()  # Для назначения админа
    waiting_remove_admin_id = State()  # Для снятия админа
    waiting_ban_user_id = State()  # Для бана пользователя
    waiting_unban_user_id = State()  # Для разбана пользователя
    waiting_ban_reason = State()  # Для причины бана

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Основная клавиатура для пользователя"""
    builder = ReplyKeyboardBuilder()
    
    builder.add(KeyboardButton(text="📝 Создать задачу"))
    builder.add(KeyboardButton(text="📋 Мои задачи"))
    builder.add(KeyboardButton(text="🔍 Поиск задач"))
    builder.add(KeyboardButton(text="📊 Статистика"))
    builder.add(KeyboardButton(text="✅ Выполненные"))
    builder.add(KeyboardButton(text="📂 По категориям"))
    
    # Админ-кнопки для админов и создателя
    user_role = db.get_user_role(user_id)
    if user_role in ['admin', 'creator']:
        builder.add(KeyboardButton(text="⚙️ Админ-панель"))
    
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура админ-панели в зависимости от роли"""
    builder = InlineKeyboardBuilder()
    
    user_role = db.get_user_role(user_id)
    
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
    
    # Дополнительные функции для создателя и админов
    if user_role == 'creator':
        builder.add(InlineKeyboardButton(
            text="👑 Назначить админа",
            callback_data="admin_promote"
        ))
        builder.add(InlineKeyboardButton(
            text="👑 Снять админа",
            callback_data="admin_demote"
        ))
        builder.add(InlineKeyboardButton(
            text="🚫 Бан пользователя",
            callback_data="admin_ban_user"
        ))
        builder.add(InlineKeyboardButton(
            text="✅ Разбан пользователя",
            callback_data="admin_unban_user"
        ))
        builder.add(InlineKeyboardButton(
            text="📋 Список админов",
            callback_data="admin_list_admins"
        ))
    elif user_role == 'admin':
        builder.add(InlineKeyboardButton(
            text="👑 Назначить админа",
            callback_data="admin_promote"
        ))
        builder.add(InlineKeyboardButton(
            text="🚫 Бан пользователя",
            callback_data="admin_ban_user"
        ))
    
    builder.add(InlineKeyboardButton(
        text="🔙 Главное меню",
        callback_data="back_to_main"
    ))
    
    # Настраиваем расположение кнопок
    if user_role == 'creator':
        builder.adjust(2, 2, 2, 2, 1)
    elif user_role == 'admin':
        builder.adjust(2, 2, 2, 1)
    else:
        builder.adjust(2, 1)
    
    return builder.as_markup()

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

def get_priority_keyboard(action: str = "create") -> InlineKeyboardMarkup:
    """Клавиатура для выбора приоритета"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="🔴 Высокий",
        callback_data=f"priority_{action}_high"
    ))
    builder.add(InlineKeyboardButton(
        text="🟡 Средний",
        callback_data=f"priority_{action}_medium"
    ))
    builder.add(InlineKeyboardButton(
        text="🟢 Низкий",
        callback_data=f"priority_{action}_low"
    ))
    
    builder.adjust(1)
    return builder.as_markup()

def get_category_keyboard(action: str = "create") -> InlineKeyboardMarkup:
    """Клавиатура для выбора категории"""
    builder = InlineKeyboardBuilder()
    
    categories = ["Работа", "Учеба", "Личное", "Здоровье", "Финансы", "Другое"]
    
    for category in categories:
        builder.add(InlineKeyboardButton(
            text=category,
            callback_data=f"category_{action}_{category}"
        ))
    
    builder.add(InlineKeyboardButton(
        text="✏️ Своя категория",
        callback_data=f"category_{action}_custom"
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

def get_categories_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для выбора категорий задач"""
    builder = InlineKeyboardBuilder()
    
    # Получаем все уникальные категории пользователя
    categories = set()
    for task in db.tasks.values():
        if task['user_id'] == user_id:
            categories.add(task['category'])
    
    for category in sorted(categories):
        builder.add(InlineKeyboardButton(
            text=category,
            callback_data=f"view_category_{category}"
        ))
    
    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="back_to_main"
    ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_edit_task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для редактирования задачи"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="📝 Текст",
        callback_data=f"edit_text_{task_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="📂 Категория",
        callback_data=f"edit_category_{task_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🎯 Приоритет",
        callback_data=f"edit_priority_{task_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"task_detail_{task_id}"
    ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_export_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора формата экспорта"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="📝 JSON",
        callback_data="export_json"
    ))
    builder.add(InlineKeyboardButton(
        text="📄 TXT",
        callback_data="export_txt"
    ))
    builder.add(InlineKeyboardButton(
        text="📊 CSV",
        callback_data="export_csv"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="admin_back"
    ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_user_list_keyboard(users: List[Dict], page: int = 0, users_per_page: int = 10) -> InlineKeyboardMarkup:
    """Клавиатура для списка пользователей с ролями"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * users_per_page
    end_idx = start_idx + users_per_page
    page_users = users[start_idx:end_idx]
    
    for user in page_users:
        user_id = user['user_id']
        username = user.get('username', 'Без имени')
        role = db.get_user_role(user_id)
        banned = db.is_banned(user_id)
        
        # Эмодзи для статуса
        role_emoji = "👑" if role == 'creator' else "⚡" if role == 'admin' else "👤"
        ban_emoji = "🚫" if banned else "✅"
        
        btn_text = f"{role_emoji} {ban_emoji} @{username}"
        builder.row(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"admin_user_detail_{user_id}"
        ))
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"admin_users_page_{page-1}"
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="admin_back"
    ))
    
    if len(users) > end_idx:
        nav_buttons.append(InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"admin_users_page_{page+1}"
        ))
    
    builder.row(*nav_buttons)
    
    return builder.as_markup()

def get_user_management_keyboard(user_id: int, manager_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для управления конкретным пользователем"""
    builder = InlineKeyboardBuilder()
    
    target_role = db.get_user_role(user_id)
    is_banned = db.is_banned(user_id)
    
    # Создатель может управлять всеми кроме себя
    if manager_id == CREATOR_ID and user_id != CREATOR_ID:
        if target_role == 'admin':
            builder.add(InlineKeyboardButton(
                text="👑 Снять админа",
                callback_data=f"admin_demote_user_{user_id}"
            ))
        elif target_role == 'user':
            builder.add(InlineKeyboardButton(
                text="⚡ Назначить админом",
                callback_data=f"admin_promote_user_{user_id}"
            ))
        
        if is_banned:
            builder.add(InlineKeyboardButton(
                text="✅ Разбанить",
                callback_data=f"admin_unban_user_{user_id}"
            ))
        else:
            builder.add(InlineKeyboardButton(
                text="🚫 Забанить",
                callback_data=f"admin_ban_user_{user_id}"
            ))
    
    # Админ может управлять только пользователями
    elif db.get_user_role(manager_id) == 'admin' and target_role == 'user':
        builder.add(InlineKeyboardButton(
            text="⚡ Назначить админом",
            callback_data=f"admin_promote_user_{user_id}"
        ))
        
        if not is_banned:
            builder.add(InlineKeyboardButton(
                text="🚫 Забанить",
                callback_data=f"admin_ban_user_{user_id}"
            ))
    
    builder.add(InlineKeyboardButton(
        text="✉️ Написать",
        callback_data=f"admin_message_{user_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="📋 Задачи пользователя",
        callback_data=f"admin_user_tasks_{user_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="admin_users"
    ))
    
    builder.adjust(2)
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
    if db.is_banned(user_id):
        return "🚫 <b>Ваш аккаунт заблокирован!</b>\n\nОбратитесь к администратору для разблокировки."
    
    user = db.users.get(user_id, {})
    tasks = db.get_user_tasks(user_id)
    active_tasks = [t for t in tasks if not t['completed']]
    completed_tasks = [t for t in tasks if t['completed']]
    
    if tasks:
        progress = (len(completed_tasks) / len(tasks) * 100) if tasks else 0
        
        # Статистика по приоритетам
        high_priority = len([t for t in tasks if t['priority'] == 'high'])
        medium_priority = len([t for t in tasks if t['priority'] == 'medium'])
        low_priority = len([t for t in tasks if t['priority'] == 'low'])
        
        # Статистика по категориям
        categories = {}
        for task in tasks:
            cat = task['category']
            categories[cat] = categories.get(cat, 0) + 1
        
        top_category = max(categories.items(), key=lambda x: x[1]) if categories else ("Нет", 0)
        
        # Информация о роли
        role = db.get_user_role(user_id)
        role_text = "👑 Создатель" if role == 'creator' else "⚡ Администратор" if role == 'admin' else "👤 Пользователь"
        
        return f"""<b>📊 Ваша статистика</b>

{role_text}
👤 <b>Пользователь:</b> @{user.get('username', 'Без имени')}
🆔 <b>ID:</b> <code>{user_id}</code>
📅 <b>С нами с:</b> {user.get('joined').strftime('%d.%m.%Y') if user.get('joined') else 'Неизвестно'}

<b>📈 Активность:</b>
📝 Всего задач: {len(tasks)}
✅ Выполнено: {len(completed_tasks)}
⏳ В работе: {len(active_tasks)}
🎯 Прогресс: {progress:.1f}%

<b>🎯 Приоритеты:</b>
🔴 Высокий: {high_priority}
🟡 Средний: {medium_priority}
🟢 Низкий: {low_priority}

<b>📂 Самая частая категория:</b>
{top_category[0]} ({top_category[1]} задач)"""
    else:
        return "Создайте первую задачу, чтобы увидеть статистику!"

def format_admin_stats() -> str:
    """Форматирование статистики для админа"""
    total_users = len(db.users)
    total_tasks = db.admin_stats['total_tasks']
    completed_tasks = db.admin_stats['completed_tasks']
    active_users = len(db.admin_stats['active_users'])
    tasks_today = db.admin_stats['tasks_today']
    users_today = len(db.admin_stats['users_today'])
    banned_users = len(db.banned_users)
    admins_count = len(db.get_all_admins())
    
    completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    # Активность за последние 7 дней
    week_ago = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    new_users_week = len([u for u in db.users.values() 
                         if u['joined'] > week_ago])
    
    return f"""<b>⚙️ Статистика бота</b>

<b>👥 Пользователи:</b>
• Всего пользователей: {total_users}
• Активных пользователей: {active_users}
• Заблокированных: {banned_users}
• Администраторов: {admins_count}
• Новых за неделю: {new_users_week}

<b>📝 Задачи:</b>
• Всего задач: {total_tasks}
• Выполнено: {completed_tasks}
• В работе: {total_tasks - completed_tasks}
• Процент выполнения: {completion_rate:.1f}%

<b>📅 За сегодня:</b>
• Новых пользователей: {users_today}
• Создано задач: {tasks_today}
• Выполнено задач: {sum(1 for t in db.tasks.values() 
                        if t['completed_at'] and t['completed_at'].date() == datetime.now().date())}"""

def format_user_detail(user_id: int) -> str:
    """Форматирование детальной информации о пользователе"""
    user = db.users.get(user_id, {})
    if not user:
        return "Пользователь не найден"
    
    role = db.get_user_role(user_id)
    is_banned = db.is_banned(user_id)
    
    role_text = "👑 Создатель" if role == 'creator' else "⚡ Администратор" if role == 'admin' else "👤 Пользователь"
    ban_status = "🚫 <b>Заблокирован</b>" if is_banned else "✅ <b>Активен</b>"
    
    tasks = db.get_user_tasks(user_id)
    active_tasks = len([t for t in tasks if not t['completed']])
    completed_tasks = len([t for t in tasks if t['completed']])
    
    return f"""<b>👤 Информация о пользователе</b>

<b>Имя:</b> {user.get('full_name', 'Не указано')}
<b>Username:</b> @{user.get('username', 'Не указано')}
<b>ID:</b> <code>{user_id}</code>
<b>Роль:</b> {role_text}
<b>Статус:</b> {ban_status}

<b>📊 Активность:</b>
📅 Регистрация: {user.get('joined').strftime('%d.%m.%Y %H:%M') if user.get('joined') else 'Неизвестно'}
🕐 Последняя активность: {user.get('last_active').strftime('%d.%m.%Y %H:%M') if user.get('last_active') else 'Неизвестно'}

<b>📝 Задачи:</b>
• Всего: {len(tasks)}
• Активных: {active_tasks}
• Выполненных: {completed_tasks}
• Прогресс: {(completed_tasks/len(tasks)*100) if tasks else 0:.1f}%"""

# ========== МИДЛВАРЬ ДЛЯ ПРОВЕРКИ БАНА ==========
@router.message.middleware()
async def ban_check_middleware(handler, event, data):
    """Проверка на бан перед обработкой сообщений"""
    user_id = event.from_user.id
    
    # Проверяем, не забанен ли пользователь
    if db.is_banned(user_id):
        if isinstance(event, Message):
            await event.answer(
                "🚫 <b>Ваш аккаунт заблокирован!</b>\n\n"
                "Вы не можете использовать бота.\n"
                "Обратитесь к администратору для разблокировки.",
                reply_markup=None
            )
        return  # Прерываем обработку
    
    # Продолжаем обработку
    return await handler(event, data)

@router.callback_query.middleware()
async def ban_check_callback_middleware(handler, event, data):
    """Проверка на бан перед обработкой callback'ов"""
    user_id = event.from_user.id
    
    # Проверяем, не забанен ли пользователь
    if db.is_banned(user_id):
        await event.answer(
            "🚫 Ваш аккаунт заблокирован!",
            show_alert=True
        )
        return  # Прерываем обработку
    
    # Продолжаем обработку
    return await handler(event, data)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start с проверкой на бан"""
    user_id = message.from_user.id
    username = message.from_user.username or "Без имени"
    full_name = message.from_user.full_name
    
    # Добавляем пользователя (если не забанен)
    if not db.add_user(user_id, username, full_name):
        # Пользователь забанен, сообщение уже отправлено в middleware
        return
    
    # Проверяем роль пользователя для приветствия
    role = db.get_user_role(user_id)
    role_greeting = ""
    if role == 'creator':
        role_greeting = "\n\n👑 <b>Вы являетесь создателем бота!</b>"
    elif role == 'admin':
        role_greeting = "\n\n⚡ <b>Вы являетесь администратором!</b>"
    
    welcome_text = f"""<b>👋 Привет, {full_name}!</b>{role_greeting}

Я — ваш персональный помощник по управлению задачами 📋

<b>📌 Что я умею:</b>
• Создавать задачи с категориями и приоритетами
• Отслеживать прогресс выполнения
• Показывать статистику продуктивности
• Искать задачи по тексту
• Группировать задачи по категориям

Используйте кнопки ниже или команды:
/start - Главное меню
/help - Помощь
/tasks - Мои задачи
/search - Поиск задач
/stats - Статистика

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
/search - Поиск задач

<b>🎯 Как работать с задачами:</b>
1. Нажмите "📝 Создать задачу"
2. Введите текст задачи
3. Выберите категорию и приоритет
4. Отслеживайте выполнение в "📋 Мои задачи"
5. Отмечайте выполненные задачи

<b>🔍 Поиск задач:</b>
• Используйте кнопку "🔍 Поиск задач"
• Введите ключевое слово
• Найдем задачи по тексту

<b>📂 Категории:</b>
• Просматривайте задачи по категориям
• Создавайте свои категории

<b>🔔 Особенности:</b>
• Задачи можно редактировать
• Можно устанавливать приоритеты
• Ведется статистика продуктивности
• Данные хранятся безопасно

<b>💡 Советы:</b>
• Разбивайте большие задачи на мелкие
• Используйте категории для организации
• Регулярно проверяйте статистику
• Помечайте важные задачи высоким приоритетом"""
    
    await message.answer(help_text)

@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    """Обработчик команды /tasks"""
    await show_user_tasks(message.from_user.id, message.chat.id)

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Обработчик команды /stats"""
    await message.answer(
        format_user_stats(message.from_user.id),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
            ]]
        )
    )

@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext):
    """Обработчик команды /search"""
    await message.answer(
        "🔍 <b>Поиск задач</b>\n\n"
        "Введите ключевое слово для поиска:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main")
            ]]
        )
    )
    await state.set_state(TaskStates.searching_tasks)

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Команда для быстрого доступа к админ-панели"""
    user_id = message.from_user.id
    role = db.get_user_role(user_id)
    
    if role in ['admin', 'creator']:
        await admin_panel(message)
    else:
        await message.answer("У вас нет доступа к админ-панели")

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

@router.message(F.text == "🔍 Поиск задач")
async def show_search_tasks(message: Message, state: FSMContext):
    """Показать поиск задач"""
    await cmd_search(message, state)

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

@router.message(F.text == "📂 По категориям")
async def show_categories(message: Message):
    """Показать задачи по категориям"""
    tasks = db.get_user_tasks(message.from_user.id)
    
    if not tasks:
        await message.answer("У вас еще нет задач!")
        return
    
    categories = set(task['category'] for task in tasks)
    
    text = "<b>📂 Ваши категории:</b>\n\n"
    for category in sorted(categories):
        category_tasks = db.get_tasks_by_category(message.from_user.id, category)
        completed = len([t for t in category_tasks if t['completed']])
        text += f"• {category}: {len(category_tasks)} задач ({completed} ✅)\n"
    
    await message.answer(
        text,
        reply_markup=get_categories_keyboard(message.from_user.id)
    )

@router.message(F.text == "⚙️ Админ-панель")
async def admin_panel(message: Message):
    """Показать админ-панель (только для админов и создателя)"""
    user_id = message.from_user.id
    role = db.get_user_role(user_id)
    
    if role not in ['admin', 'creator']:
        await message.answer("У вас нет доступа к этой функции")
        return
    
    await message.answer(
        "<b>⚙️ Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard(user_id)
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

@router.callback_query(F.data.startswith("category_create_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории при создании"""
    category = callback.data.split("_", 2)[2]
    
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

@router.callback_query(F.data.startswith("priority_create_"))
async def process_priority(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора приоритета и сохранение задачи"""
    priority = callback.data.split("_", 2)[2]
    data = await state.get_data()
    
    task_id = db.add_task(
        user_id=callback.from_user.id,
        text=data['text'],
        category=data['category'],
    )
    
    if task_id is None:
        await callback.message.edit_text(
            "❌ <b>Ошибка создания задачи!</b>\n\n"
            "Ваш аккаунт заблокирован.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")
                ]]
            )
        )
        await state.clear()
        return
    
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

@router.message(TaskStates.searching_tasks)
async def process_search(message: Message, state: FSMContext):
    """Обработка поиска задач"""
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Введите минимум 2 символа для поиска")
        return
    
    tasks = db.search_tasks(message.from_user.id, query)
    
    if tasks:
        await message.answer(
            f"🔍 <b>Результаты поиска по запросу:</b> '{query}'\n"
            f"Найдено задач: {len(tasks)}",
            reply_markup=get_tasks_keyboard(tasks)
        )
    else:
        await message.answer(
            f"По запросу '{query}' ничего не найдено",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
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
        f"✏️ <b>Редактирование задачи #{task_id}</b>\n\n"
        f"<b>Текущий текст:</b> {task['text']}\n"
        f"<b>Категория:</b> {task['category']}\n"
        f"<b>Приоритет:</b> {task['priority']}\n\n"
        f"Что вы хотите изменить?",
        reply_markup=get_edit_task_keyboard(task_id)
    )

@router.callback_query(F.data.startswith("edit_text_"))
async def edit_task_text_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования текста задачи"""
    task_id = int(callback.data.split("_", 2)[2])
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != callback.from_user.id:
        await callback.answer("Ошибка!", show_alert=True)
        return
    
    await state.update_data(task_id=task_id)
    
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
    
    if len(message.text) > 500:
        await message.answer("Текст задачи слишком длинный (макс. 500 символов)")
        return
    
    if db.update_task_text(task_id, message.text):
        task = db.get_task(task_id)
        await message.answer(
            "✅ <b>Текст задачи обновлен!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="📋 К задаче", callback_data=f"task_detail_{task_id}")
                ]]
            )
        )
    else:
        await message.answer("❌ Ошибка при обновлении задачи")
    
    await state.clear()

@router.callback_query(F.data.startswith("edit_category_"))
async def edit_task_category_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования категории задачи"""
    task_id = int(callback.data.split("_", 2)[2])
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != callback.from_user.id:
        await callback.answer("Ошибка!", show_alert=True)
        return
    
    await state.update_data(task_id=task_id)
    
    await callback.message.edit_text(
        "📂 <b>Выберите новую категорию:</b>",
        reply_markup=get_category_keyboard("edit")
    )
    await state.set_state(TaskStates.editing_category)

@router.callback_query(F.data.startswith("category_edit_"))
async def process_edit_category(callback: CallbackQuery, state: FSMContext):
    """Обработка изменения категории задачи"""
    data = await state.get_data()
    task_id = data['task_id']
    
    if callback.data == "category_edit_custom":
        await callback.message.edit_text(
            "✏️ <b>Введите новую категорию:</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data=f"task_detail_{task_id}")
                ]]
            )
        )
        return
    
    category = callback.data.split("_", 2)[2]
    
    if db.update_task_category(task_id, category):
        task = db.get_task(task_id)
        await callback.message.edit_text(
            "✅ <b>Категория задачи обновлена!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="📋 К задаче", callback_data=f"task_detail_{task_id}")
                ]]
            )
        )
    else:
        await callback.answer("❌ Ошибка при обновлении категории", show_alert=True)
    
    await state.clear()

@router.message(TaskStates.editing_category)
async def process_edit_custom_category(message: Message, state: FSMContext):
    """Обработка пользовательской категории при редактировании"""
    data = await state.get_data()
    task_id = data['task_id']
    
    if len(message.text) > 50:
        await message.answer("Название категории слишком длинное (макс. 50 символов)")
        return
    
    if db.update_task_category(task_id, message.text):
        task = db.get_task(task_id)
        await message.answer(
            "✅ <b>Категория задачи обновлена!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="📋 К задаче", callback_data=f"task_detail_{task_id}")
                ]]
            )
        )
    else:
        await message.answer("❌ Ошибка при обновлении категории")
    
    await state.clear()

@router.callback_query(F.data.startswith("edit_priority_"))
async def edit_task_priority_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования приоритета задачи"""
    task_id = int(callback.data.split("_", 2)[2])
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != callback.from_user.id:
        await callback.answer("Ошибка!", show_alert=True)
        return
    
    await state.update_data(task_id=task_id)
    
    await callback.message.edit_text(
        "🎯 <b>Выберите новый приоритет:</b>",
        reply_markup=get_priority_keyboard("edit")
    )
    await state.set_state(TaskStates.editing_priority)

@router.callback_query(F.data.startswith("priority_edit_"))
async def process_edit_priority(callback: CallbackQuery, state: FSMContext):
    """Обработка изменения приоритета задачи"""
    data = await state.get_data()
    task_id = data['task_id']
    priority = callback.data.split("_", 2)[2]
    
    if db.update_task_priority(task_id, priority):
        task = db.get_task(task_id)
        await callback.message.edit_text(
            "✅ <b>Приоритет задачи обновлен!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="📋 К задаче", callback_data=f"task_detail_{task_id}")
                ]]
            )
        )
    else:
        await callback.answer("❌ Ошибка при обновлении приоритета", show_alert=True)
    
    await state.clear()

@router.callback_query(F.data.startswith("view_category_"))
async def view_category_tasks(callback: CallbackQuery):
    """Просмотр задач по категории"""
    category = callback.data.split("_", 2)[2]
    tasks = db.get_tasks_by_category(callback.from_user.id, category)
    
    if tasks:
        await callback.message.edit_text(
            f"<b>📂 Задачи в категории '{category}'</b> (всего: {len(tasks)})",
            reply_markup=get_tasks_keyboard(tasks)
        )
    else:
        await callback.message.edit_text(
            f"В категории '{category}' нет задач",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
                ]]
            )
        )

# ========== АДМИН ОБРАБОТЧИКИ ==========
@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    """Статистика для админа"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
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
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
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
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
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
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    users = db.get_all_users_with_roles()
    
    if not users:
        await callback.message.edit_text(
            "В системе пока нет пользователей",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
                ]]
            )
        )
        return
    
    await callback.message.edit_text(
        f"<b>👥 Все пользователи</b> (всего: {len(users)})",
        reply_markup=get_user_list_keyboard(users)
    )

@router.callback_query(F.data.startswith("admin_user_detail_"))
async def admin_user_detail(callback: CallbackQuery):
    """Детали пользователя для админа"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_", 3)[3])
    user = db.users.get(user_id)
    
    if not user:
        await callback.answer("Пользователь не найден!", show_alert=True)
        return
    
    await callback.message.edit_text(
        format_user_detail(user_id),
        reply_markup=get_user_management_keyboard(user_id, callback.from_user.id)
    )

@router.callback_query(F.data.startswith("admin_user_tasks_"))
async def admin_user_tasks(callback: CallbackQuery):
    """Задачи конкретного пользователя"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_", 3)[3])
    user = db.users.get(user_id)
    
    if not user:
        await callback.answer("Пользователь не найден!", show_alert=True)
        return
    
    tasks = db.get_user_tasks(user_id)
    
    if tasks:
        await callback.message.edit_text(
            f"<b>📋 Задачи пользователя @{user.get('username', 'Без имени')}</b> (всего: {len(tasks)})",
            reply_markup=get_tasks_keyboard(tasks)
        )
    else:
        await callback.message.edit_text(
            f"У пользователя @{user.get('username', 'Без имени')} нет задач",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_user_detail_{user_id}")
                ]]
            )
        )

@router.callback_query(F.data == "admin_promote")
async def admin_promote_start(callback: CallbackQuery, state: FSMContext):
    """Начало назначения админа"""
    user_id = callback.from_user.id
    role = db.get_user_role(user_id)
    
    if role not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⚡ <b>Назначение администратора</b>\n\n"
        "Введите ID пользователя, которого хотите назначить админом:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
            ]]
        )
    )
    await state.set_state(AdminStates.waiting_admin_id)

@router.message(AdminStates.waiting_admin_id)
async def process_admin_promote(message: Message, state: FSMContext):
    """Обработка назначения админа"""
    try:
        target_id = int(message.text)
        manager_id = message.from_user.id
        
        # Проверяем права
        if not db.can_manage_user(manager_id, target_id):
            await message.answer(
                "❌ <b>У вас нет прав для назначения этого пользователя админом!</b>\n\n"
                "Вы можете назначать только обычных пользователей.",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Проверяем, существует ли пользователь
        if target_id not in db.users:
            await message.answer(
                "❌ Пользователь с таким ID не найден в системе.",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Назначаем админа
        if db.set_admin(target_id):
            user = db.users.get(target_id)
            await message.answer(
                f"✅ <b>Пользователь @{user.get('username', 'Без имени')} назначен администратором!</b>",
                reply_markup=get_admin_keyboard(manager_id)
            )
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    target_id,
                    "⚡ <b>Поздравляем!</b>\n\n"
                    "Вы были назначены администратором бота!\n"
                    "Теперь вам доступна админ-панель."
                )
            except:
                pass
        else:
            await message.answer(
                "❌ Не удалось назначить пользователя админом.",
                reply_markup=get_admin_keyboard(manager_id)
            )
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите числовой ID пользователя.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
                ]]
            )
        )
        return
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_promote_user_"))
async def admin_promote_user_direct(callback: CallbackQuery):
    """Прямое назначение админа из меню пользователя"""
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_", 3)[3])
    
    # Проверяем права
    if not db.can_manage_user(user_id, target_id):
        await callback.answer("У вас нет прав для назначения этого пользователя админом!", show_alert=True)
        return
    
    # Назначаем админа
    if db.set_admin(target_id):
        user = db.users.get(target_id)
        
        await callback.message.edit_text(
            f"✅ <b>Пользователь @{user.get('username', 'Без имени')} назначен администратором!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_user_detail_{target_id}")
                ]]
            )
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_id,
                "⚡ <b>Поздравляем!</b>\n\n"
                "Вы были назначены администратором бота!\n"
                "Теперь вам доступна админ-панель."
            )
        except:
            pass
    else:
        await callback.answer("Не удалось назначить пользователя админом!", show_alert=True)

@router.callback_query(F.data == "admin_demote")
async def admin_demote_start(callback: CallbackQuery, state: FSMContext):
    """Начало снятия админа (только для создателя)"""
    user_id = callback.from_user.id
    
    if db.get_user_role(user_id) != 'creator':
        await callback.answer("Только создатель может снимать админов!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👑 <b>Снятие администратора</b>\n\n"
        "Введите ID администратора, которого хотите снять:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
            ]]
        )
    )
    await state.set_state(AdminStates.waiting_remove_admin_id)

@router.message(AdminStates.waiting_remove_admin_id)
async def process_admin_demote(message: Message, state: FSMContext):
    """Обработка снятия админа"""
    try:
        target_id = int(message.text)
        manager_id = message.from_user.id
        
        # Только создатель может снимать админов
        if manager_id != CREATOR_ID:
            await message.answer(
                "❌ Только создатель может снимать администраторов!",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Нельзя снять создателя
        if target_id == CREATOR_ID:
            await message.answer(
                "❌ Нельзя снять создателя!",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Проверяем, является ли пользователь админом
        if db.get_user_role(target_id) != 'admin':
            await message.answer(
                "❌ Этот пользователь не является администратором!",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Снимаем админа
        if db.remove_admin(target_id):
            user = db.users.get(target_id)
            await message.answer(
                f"✅ <b>Пользователь @{user.get('username', 'Без имени')} снят с должности администратора!</b>",
                reply_markup=get_admin_keyboard(manager_id)
            )
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    target_id,
                    "ℹ️ <b>Уведомление</b>\n\n"
                    "Вы были сняты с должности администратора бота."
                )
            except:
                pass
        else:
            await message.answer(
                "❌ Не удалось снять пользователя с должности администратора.",
                reply_markup=get_admin_keyboard(manager_id)
            )
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите числовой ID пользователя.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
                ]]
            )
        )
        return
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_demote_user_"))
async def admin_demote_user_direct(callback: CallbackQuery):
    """Прямое снятие админа из меню пользователя"""
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_", 3)[3])
    
    # Только создатель может снимать админов
    if user_id != CREATOR_ID:
        await callback.answer("Только создатель может снимать администраторов!", show_alert=True)
        return
    
    # Нельзя снять создателя
    if target_id == CREATOR_ID:
        await callback.answer("Нельзя снять создателя!", show_alert=True)
        return
    
    # Снимаем админа
    if db.remove_admin(target_id):
        user = db.users.get(target_id)
        
        await callback.message.edit_text(
            f"✅ <b>Пользователь @{user.get('username', 'Без имени')} снят с должности администратора!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_user_detail_{target_id}")
                ]]
            )
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_id,
                "ℹ️ <b>Уведомление</b>\n\n"
                "Вы были сняты с должности администратора бота."
            )
        except:
            pass
    else:
        await callback.answer("Не удалось снять пользователя с должности администратора!", show_alert=True)

@router.callback_query(F.data == "admin_list_admins")
async def admin_list_admins_handler(callback: CallbackQuery):
    """Список всех админов"""
    user_id = callback.from_user.id
    
    if db.get_user_role(user_id) != 'creator':
        await callback.answer("Только создатель может просматривать список админов!", show_alert=True)
        return
    
    admins = db.get_all_admins()
    
    if not admins:
        await callback.message.edit_text(
            "В системе нет администраторов кроме вас.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
                ]]
            )
        )
        return
    
    text = "<b>👑 Список администраторов:</b>\n\n"
    for admin_id in admins:
        user = db.users.get(admin_id, {})
        username = user.get('username', 'Без имени')
        text += f"• @{username} (ID: <code>{admin_id}</code>)\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
            ]]
        )
    )

@router.callback_query(F.data == "admin_ban_user")
async def admin_ban_user_start(callback: CallbackQuery, state: FSMContext):
    """Начало бана пользователя"""
    user_id = callback.from_user.id
    role = db.get_user_role(user_id)
    
    if role not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🚫 <b>Блокировка пользователя</b>\n\n"
        "Введите ID пользователя, которого хотите заблокировать:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
            ]]
        )
    )
    await state.set_state(AdminStates.waiting_ban_user_id)

@router.message(AdminStates.waiting_ban_user_id)
async def process_ban_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя для бана"""
    try:
        target_id = int(message.text)
        manager_id = message.from_user.id
        
        # Проверяем права
        if not db.can_ban_user(manager_id, target_id):
            await message.answer(
                "❌ <b>У вас нет прав для блокировки этого пользователя!</b>\n\n"
                "Вы можете блокировать только обычных пользователей.",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Проверяем, существует ли пользователь
        if target_id not in db.users:
            await message.answer(
                "❌ Пользователь с таким ID не найден в системе.",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Сохраняем ID для следующего шага
        await state.update_data(ban_user_id=target_id)
        
        await message.answer(
            "📝 <b>Введите причину блокировки:</b>\n\n"
            "Причина будет сохранена в логах.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
                ]]
            )
        )
        await state.set_state(AdminStates.waiting_ban_reason)
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите числовой ID пользователя.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
                ]]
            )
        )

@router.message(AdminStates.waiting_ban_reason)
async def process_ban_reason(message: Message, state: FSMContext):
    """Обработка причины бана"""
    data = await state.get_data()
    target_id = data['ban_user_id']
    manager_id = message.from_user.id
    reason = message.text
    
    # Баним пользователя
    if db.ban_user(target_id, reason):
        user = db.users.get(target_id)
        
        await message.answer(
            f"✅ <b>Пользователь @{user.get('username', 'Без имени')} заблокирован!</b>\n\n"
            f"Причина: {reason}",
            reply_markup=get_admin_keyboard(manager_id)
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_id,
                f"🚫 <b>Ваш аккаунт заблокирован!</b>\n\n"
                f"Причина: {reason}\n\n"
                f"Вы не можете использовать бота до разблокировки."
            )
        except:
            pass
    else:
        await message.answer(
            "❌ Не удалось заблокировать пользователя.",
            reply_markup=get_admin_keyboard(manager_id)
        )
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_ban_user_"))
async def admin_ban_user_direct(callback: CallbackQuery):
    """Прямой бан пользователя из меню"""
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_", 3)[3])
    
    # Проверяем права
    if not db.can_ban_user(user_id, target_id):
        await callback.answer("У вас нет прав для блокировки этого пользователя!", show_alert=True)
        return
    
    # Баним пользователя
    if db.ban_user(target_id, "Блокировка через админ-панель"):
        user = db.users.get(target_id)
        
        await callback.message.edit_text(
            f"✅ <b>Пользователь @{user.get('username', 'Без имени')} заблокирован!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_user_detail_{target_id}")
                ]]
            )
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_id,
                "🚫 <b>Ваш аккаунт заблокирован!</b>\n\n"
                "Вы не можете использовать бота до разблокировки."
            )
        except:
            pass
    else:
        await callback.answer("Не удалось заблокировать пользователя!", show_alert=True)

@router.callback_query(F.data == "admin_unban_user")
async def admin_unban_user_start(callback: CallbackQuery, state: FSMContext):
    """Начало разбана пользователя"""
    user_id = callback.from_user.id
    
    # Только создатель может разбанивать
    if db.get_user_role(user_id) != 'creator':
        await callback.answer("Только создатель может разбанивать пользователей!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "✅ <b>Разблокировка пользователя</b>\n\n"
        "Введите ID пользователя, которого хотите разблокировать:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
            ]]
        )
    )
    await state.set_state(AdminStates.waiting_unban_user_id)

@router.message(AdminStates.waiting_unban_user_id)
async def process_unban_user(message: Message, state: FSMContext):
    """Обработка разбана пользователя"""
    try:
        target_id = int(message.text)
        manager_id = message.from_user.id
        
        # Только создатель может разбанивать
        if manager_id != CREATOR_ID:
            await message.answer(
                "❌ Только создатель может разбанивать пользователей!",
                reply_markup=get_admin_keyboard(manager_id)
            )
            await state.clear()
            return
        
        # Разбаниваем пользователя
        if db.unban_user(target_id):
            user = db.users.get(target_id)
            
            if user:
                await message.answer(
                    f"✅ <b>Пользователь @{user.get('username', 'Без имени')} разблокирован!</b>",
                    reply_markup=get_admin_keyboard(manager_id)
                )
                
                # Уведомляем пользователя
                try:
                    await bot.send_message(
                        target_id,
                        "✅ <b>Ваш аккаунт разблокирован!</b>\n\n"
                        "Теперь вы снова можете использовать бота."
                    )
                except:
                    pass
            else:
                await message.answer(
                    f"✅ Пользователь с ID {target_id} разблокирован!",
                    reply_markup=get_admin_keyboard(manager_id)
                )
        else:
            await message.answer(
                "❌ Этот пользователь не был заблокирован или произошла ошибка.",
                reply_markup=get_admin_keyboard(manager_id)
            )
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите числовой ID пользователя.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
                ]]
            )
        )
        return
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_unban_user_"))
async def admin_unban_user_direct(callback: CallbackQuery):
    """Прямой разбан пользователя из меню"""
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_", 3)[3])
    
    # Только создатель может разбанивать
    if user_id != CREATOR_ID:
        await callback.answer("Только создатель может разбанивать пользователей!", show_alert=True)
        return
    
    # Разбаниваем пользователя
    if db.unban_user(target_id):
        user = db.users.get(target_id)
        
        await callback.message.edit_text(
            f"✅ <b>Пользователь @{user.get('username', 'Без имени')} разблокирован!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_user_detail_{target_id}")
                ]]
            )
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_id,
                "✅ <b>Ваш аккаунт разблокирован!</b>\n\n"
                "Теперь вы снова можете использовать бота."
            )
        except:
            pass
    else:
        await callback.answer("Этот пользователь не был заблокирован!", show_alert=True)

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
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
        reply_markup=get_admin_keyboard(message.from_user.id)
    )
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_message_"))
async def admin_message_user_start(callback: CallbackQuery, state: FSMContext):
    """Начало отправки сообщения пользователю"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_", 2)[1])
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

@router.callback_query(F.data == "admin_message_user")
async def admin_message_user_general(callback: CallbackQuery, state: FSMContext):
    """Начало отправки сообщения пользователю (общий)"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "✉️ <b>Отправка сообщения пользователю</b>\n\n"
        "Введите ID пользователя:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
            ]]
        )
    )
    await state.set_state(AdminStates.waiting_user_id)

@router.message(AdminStates.waiting_user_id)
async def process_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя"""
    try:
        user_id = int(message.text)
        user = db.users.get(user_id)
        
        if not user:
            await message.answer("Пользователь с таким ID не найден")
            return
        
        await state.update_data(target_user_id=user_id)
        
        await message.answer(
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
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите числовой ID пользователя.")

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
            reply_markup=get_admin_keyboard(message.from_user.id)
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось отправить сообщение: {str(e)}",
            reply_markup=get_admin_keyboard(message.from_user.id)
        )
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_delete_task_"))
async def admin_delete_task(callback: CallbackQuery):
    """Удаление задачи админом"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    task_id = int(callback.data.split("_", 3)[3])
    
    if db.delete_task(task_id):
        await callback.message.edit_text(
            "✅ <b>Задача удалена администратором</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tasks")
                ]]
            )
        )
        await callback.answer("Задача удалена")
    else:
        await callback.answer("Ошибка удаления!", show_alert=True)

@router.callback_query(F.data == "admin_export")
async def admin_export_start(callback: CallbackQuery, state: FSMContext):
    """Начало экспорта данных"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📁 <b>Экспорт данных</b>\n\n"
        "Выберите формат экспорта:",
        reply_markup=get_export_keyboard()
    )
    await state.set_state(AdminStates.waiting_export_format)

@router.callback_query(F.data.startswith("export_"))
async def process_export(callback: CallbackQuery, state: FSMContext):
    """Обработка экспорта данных"""
    if db.get_user_role(callback.from_user.id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    export_format = callback.data.split("_", 1)[1]
    
    await callback.answer(f"Начинаю экспорт в формате {export_format.upper()}...", show_alert=True)
    
    # Подготовка данных с учетом ролей и банов
    data = {
        "users": db.get_all_users_with_roles(),
        "tasks": db.get_all_tasks(),
        "stats": db.admin_stats,
        "banned_users": list(db.banned_users),
        "admins": db.get_all_admins(),
        "creator": CREATOR_ID,
        "export_date": datetime.now().isoformat()
    }
    
    # Экспорт в разных форматах
    try:
        if export_format == "json":
            filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            
            await bot.send_document(
                callback.from_user.id,
                FSInputFile(filename),
                caption="📁 Экспорт данных в формате JSON"
            )
            
        elif export_format == "txt":
            filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 50 + "\n")
                f.write("ЭКСПОРТ ДАННЫХ ИЗ БОТА\n")
                f.write(f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n")
                f.write("=" * 50 + "\n\n")
                
                f.write("СОЗДАТЕЛЬ БОТА:\n")
                f.write(f"ID: {CREATOR_ID}\n")
                f.write("-" * 30 + "\n\n")
                
                f.write("АДМИНИСТРАТОРЫ:\n")
                f.write("=" * 30 + "\n")
                for admin_id in db.get_all_admins():
                    user = db.users.get(admin_id, {})
                    f.write(f"ID: {admin_id}\n")
                    f.write(f"Имя: {user.get('full_name', 'Неизвестно')}\n")
                    f.write(f"Username: @{user.get('username', 'нет')}\n")
                    f.write("-" * 30 + "\n")
                
                f.write("\nПОЛЬЗОВАТЕЛИ:\n")
                f.write("=" * 30 + "\n")
                for user in data['users']:
                    role = user.get('role', 'user')
                    banned = user.get('banned', False)
                    
                    f.write(f"ID: {user['user_id']}\n")
                    f.write(f"Имя: {user['full_name']}\n")
                    f.write(f"Username: @{user.get('username', 'нет')}\n")
                    f.write(f"Роль: {role}\n")
                    f.write(f"Статус: {'Заблокирован' if banned else 'Активен'}\n")
                    f.write(f"Дата регистрации: {user['joined'].strftime('%d.%m.%Y %H:%M')}\n")
                    f.write(f"Задач создано: {user['task_count']}\n")
                    f.write(f"Задач выполнено: {user['completed_count']}\n")
                    f.write("-" * 30 + "\n")
                
                f.write("\nЗАБЛОКИРОВАННЫЕ ПОЛЬЗОВАТЕЛИ:\n")
                f.write("=" * 30 + "\n")
                for banned_id in db.banned_users:
                    user = db.users.get(banned_id, {})
                    f.write(f"ID: {banned_id}\n")
                    f.write(f"Имя: {user.get('full_name', 'Неизвестно')}\n")
                    f.write(f"Username: @{user.get('username', 'нет')}\n")
                    f.write("-" * 30 + "\n")
                
                f.write("\nЗАДАЧИ:\n")
                f.write("=" * 30 + "\n")
                for task in data['tasks']:
                    f.write(f"ID: {task['id']}\n")
                    f.write(f"Пользователь ID: {task['user_id']}\n")
                    f.write(f"Текст: {task['text']}\n")
                    f.write(f"Категория: {task['category']}\n")
                    f.write(f"Приоритет: {task['priority']}\n")
                    f.write(f"Статус: {'Выполнена' if task['completed'] else 'В работе'}\n")
                    f.write(f"Создана: {task['created'].strftime('%d.%m.%Y %H:%M')}\n")
                    if task['completed_at']:
                        f.write(f"Выполнена: {task['completed_at'].strftime('%d.%m.%Y %H:%M')}\n")
                    f.write("-" * 30 + "\n")
            
            await bot.send_document(
                callback.from_user.id,
                FSInputFile(filename),
                caption="📄 Экспорт данных в формате TXT"
            )
            
        elif export_format == "csv":
            filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                # Заголовок для задач
                f.write("ID;UserID;Text;Category;Priority;Completed;Created;CompletedAt\n")
                for task in data['tasks']:
                    completed_at = task['completed_at'].strftime('%Y-%m-%d %H:%M') if task['completed_at'] else ''
                    f.write(f"{task['id']};{task['user_id']};{task['text']};"
                           f"{task['category']};{task['priority']};"
                           f"{'Да' if task['completed'] else 'Нет'};"
                           f"{task['created'].strftime('%Y-%m-%d %H:%M')};{completed_at}\n")
            
            await bot.send_document(
                callback.from_user.id,
                FSInputFile(filename),
                caption="📊 Экспорт данных в формате CSV"
            )
        
        await callback.message.edit_text(
            "✅ <b>Экспорт данных завершен</b>\n\n"
            "Файл с данными отправлен вам в личные сообщения.",
            reply_markup=get_admin_keyboard(callback.from_user.id)
        )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Ошибка при экспорте данных:</b>\n\n{str(e)}",
            reply_markup=get_admin_keyboard(callback.from_user.id)
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
    user_id = callback.from_user.id
    if db.get_user_role(user_id) not in ['admin', 'creator']:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<b>⚙️ Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard(user_id)
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

@router.callback_query(F.data == "create_task_from_empty")
async def create_task_from_empty(callback: CallbackQuery):
    """Создать задачу из пустого списка"""
    await create_task_start(callback.message, callback.state)

@router.callback_query(F.data == "create_another")
async def create_another_task(callback: CallbackQuery, state: FSMContext):
    """Создать еще одну задачу"""
    await create_task_start(callback.message, state)

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

@router.callback_query(F.data.startswith("admin_users_page_"))
async def change_admin_users_page(callback: CallbackQuery):
    """Смена страницы списка пользователей"""
    page = int(callback.data.split("_", 3)[3])
    users = db.get_all_users_with_roles()
    
    await callback.message.edit_text(
        f"<b>👥 Все пользователи</b> (всего: {len(users)})",
        reply_markup=get_user_list_keyboard(users, page)
    )

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    logger.info("Бот запускается...")
    
    # Инициализация создателя в базе данных
    if CREATOR_ID not in db.users:
        db.users[CREATOR_ID] = {
            'user_id': CREATOR_ID,
            'username': 'creator',
            'full_name': 'Создатель бота',
            'joined': datetime.now(),
            'task_count': 0,
            'completed_count': 0,
            'last_active': datetime.now(),
            'warnings': 0
        }
        db.roles[CREATOR_ID] = 'creator'
        logger.info(f"Создатель бота (ID: {CREATOR_ID}) инициализирован")
    
    # Пропускаем накопленные updates
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запуск polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
