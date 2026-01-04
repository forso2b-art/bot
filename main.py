import json
import logging
import urllib.request
import urllib.parse
import sqlite3
import time
import ssl

# --- CONFIGURATION ---
API_TOKEN = '8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM'
ADMIN_IDS = [103161998, 37607526]  # Ваши ID
DB_FILE = "village_tasks.db"

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
ssl._create_default_https_context = ssl._create_unverified_context

# --- DATABASE ENGINE (SQLite) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)''')
    # Таблица задач
    c.execute('''CREATE TABLE IF NOT EXISTS tasks 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def add_user(user_id, username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def add_task(user_id, text):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO tasks (user_id, text, status) VALUES (?, ?, 'active')", (user_id, text))
    conn.commit()
    conn.close()

def get_tasks(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, text, status FROM tasks WHERE user_id = ?", (user_id,))
    tasks = c.fetchall()
    conn.close()
    return tasks

def update_task_status(task_id, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if status == 'delete':
        c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    else:
        c.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    conn.commit()
    conn.close()

def get_all_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tasks")
    tasks_count = c.fetchone()[0]
    conn.close()
    return users_count, tasks_count

def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

# --- BOT FRAMEWORK (NO EXTERNAL LIBS) ---
class TaskBot:
    def __init__(self, token):
        self.api_url = f"https://api.telegram.org/bot{token}/"

    def _req(self, method, data=None):
        url = self.api_url + method
        headers = {'Content-Type': 'application/json'}
        try:
            payload = json.dumps(data).encode('utf-8') if data else None
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as res:
                return json.loads(res.read().decode())
        except Exception as e:
            logging.error(f"Error {method}: {e}")
            return None

    def send_message(self, chat_id, text, reply_markup=None):
        return self._req('sendMessage', {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'reply_markup': reply_markup})

    def edit_message(self, chat_id, msg_id, text, reply_markup=None):
        return self._req('editMessageText', {'chat_id': chat_id, 'message_id': msg_id, 'text': text, 'parse_mode': 'Markdown', 'reply_markup': reply_markup})

    def answer_callback(self, cb_id, text=None):
        return self._req('answerCallbackQuery', {'callback_query_id': cb_id, 'text': text})

# --- LOGIC ---
bot = TaskBot(API_TOKEN)

def get_task_keyboard(task_id, status):
    if status == 'done':
        return {'inline_keyboard': [[{'text': '🗑 Удалить', 'callback_data': f'del_{task_id}'}]]}
    return {'inline_keyboard': [
        [{'text': '✅ Выполнить', 'callback_data': f'done_{task_id}'}],
        [{'text': '🗑 Удалить', 'callback_data': f'del_{task_id}'}]
    ]}

def main():
    init_db()
    offset = 0
    print("System Online. Waiting for orders...")

    while True:
        updates = bot._req('getUpdates', {'offset': offset, 'timeout': 30})
        
        if not updates or 'result' not in updates:
            time.sleep(1)
            continue

        for up in updates['result']:
            offset = up['update_id'] + 1

            # 1. MESSAGES
            if 'message' in up:
                msg = up['message']
                chat_id = msg['chat']['id']
                user_id = msg['from']['id']
                text = msg.get('text', '')
                username = msg['from'].get('username', 'Unknown')
                
                add_user(user_id, username)

                # --- USER COMMANDS ---
                if text == '/start':
                    bot.send_message(chat_id, 
                        "📝 **Task System v1.0**\n\n"
                        "Команды:\n"
                        "➕ `/add Купить еды` - создать задачу\n"
                        "📋 `/list` - мои задачи\n"
                        "🆘 `/help` - помощь")

                elif text.startswith('/add'):
                    task_text = text[5:].strip()
                    if not task_text:
                        bot.send_message(chat_id, "⚠ Ошибка. Пиши: `/add Текст задачи`")
                    else:
                        add_task(user_id, task_text)
                        bot.send_message(chat_id, f"✅ Задача добавлена: *{task_text}*")

                elif text == '/list':
                    tasks = get_tasks(user_id)
                    if not tasks:
                        bot.send_message(chat_id, "📂 У вас нет активных задач.")
                    else:
                        bot.send_message(chat_id, "📋 **Ваши задачи:**")
                        for t_id, t_text, t_status in tasks:
                            status_icon = "✅" if t_status == 'done' else "🔥"
                            bot.send_message(chat_id, f"{status_icon} *{t_text}*", reply_markup=get_task_keyboard(t_id, t_status))

                # --- ADMIN COMMANDS ---
                elif text == '/admin' and user_id in ADMIN_IDS:
                    u_count, t_count = get_all_stats()
                    kb = {'inline_keyboard': [[{'text': '📢 Рассылка', 'callback_data': 'adm_broadcast'}]]}
                    bot.send_message(chat_id, 
                        f"🔒 **Admin Control Panel**\n\n"
                        f"👥 Пользователей: {u_count}\n"
                        f"📝 Всего задач: {t_count}", reply_markup=kb)

                elif text.startswith('/broadcast') and user_id in ADMIN_IDS:
                    msg_text = text[10:].strip()
                    if msg_text:
                        users = get_all_users()
                        count = 0
                        for u in users:
                            bot.send_message(u, f"📢 **ОБЪЯВЛЕНИЕ:**\n{msg_text}")
                            count += 1
                        bot.send_message(chat_id, f"✅ Отправлено {count} пользователям.")

            # 2. CALLBACKS (BUTTONS)
            elif 'callback_query' in up:
                cb = up['callback_query']
                data = cb['data']
                chat_id = cb['message']['chat']['id']
                mid = cb['message']['message_id']
                
                if data.startswith('done_'):
                    tid = data.split('_')[1]
                    update_task_status(tid, 'done')
                    bot.edit_message(chat_id, mid, f"✅ {cb['message']['text']} (Выполнено)", reply_markup=get_task_keyboard(tid, 'done'))
                    bot.answer_callback(cb['id'], "Отлично!")
                
                elif data.startswith('del_'):
                    tid = data.split('_')[1]
                    update_task_status(tid, 'delete')
                    bot._req('deleteMessage', {'chat_id': chat_id, 'message_id': mid})
                    bot.answer_callback(cb['id'], "Удалено")

                elif data == 'adm_broadcast':
                    bot.answer_callback(cb['id'])
                    bot.send_message(chat_id, "Пиши: `/broadcast Текст` для рассылки всем.")

if __name__ == '__main__':
    main()
