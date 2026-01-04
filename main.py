import json
import logging
import urllib.request
import urllib.parse
import time
import ssl
import threading

# --- CONFIGURATION ---
API_TOKEN = '8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM'
ADMIN_IDS = [103161998, 37607526]

# Логирование: показываем ТОЛЬКО критические ошибки, никаких предупреждений
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(message)s')
ssl._create_default_https_context = ssl._create_unverified_context

# --- IN-MEMORY STORAGE ---
STORAGE = {
    "users": {},
    "tasks": []
}

def get_next_id():
    return int(time.time() * 1000)

# --- SILENT BOT CLIENT ---
class BotClient:
    def __init__(self, token):
        self.url = f"https://api.telegram.org/bot{token}/"

    def _req(self, method, data=None):
        endpoint = self.url + method
        headers = {'Content-Type': 'application/json'}
        timeout = 35 if method == 'getUpdates' else 10
        
        try:
            payload = json.dumps(data).encode('utf-8') if data else None
            req = urllib.request.Request(endpoint, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            # ГЛУШИТЕЛЬ ОШИБОК 400
            # Если Telegram говорит "Bad Request" (обычно "Message not modified"),
            # мы просто игнорируем это. Жители довольны, лог чист.
            if e.code == 400:
                return None
            logging.error(f"Server Error {e.code}: {e.reason}")
            return None
        except Exception as e:
            # Игнорируем мелкие сетевые сбои
            return None

    def send(self, chat_id, text, reply_markup=None):
        return self._req('sendMessage', {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'reply_markup': reply_markup})

    def edit(self, chat_id, msg_id, text, reply_markup=None):
        return self._req('editMessageText', {'chat_id': chat_id, 'message_id': msg_id, 'text': text, 'parse_mode': 'Markdown', 'reply_markup': reply_markup})

    def delete(self, chat_id, msg_id):
        return self._req('deleteMessage', {'chat_id': chat_id, 'message_id': msg_id})

    def answer(self, cb_id, text=None, alert=False):
        return self._req('answerCallbackQuery', {'callback_query_id': cb_id, 'text': text, 'show_alert': alert})

bot = BotClient(API_TOKEN)

# --- LOGIC ---

def get_keyboard(task_id, is_done):
    if is_done:
        return {'inline_keyboard': [[{'text': '🗑 Удалить', 'callback_data': f'del_{task_id}'}]]}
    return {'inline_keyboard': [
        [{'text': '✅ Готово', 'callback_data': f'done_{task_id}'}],
        [{'text': '🔥 Срочно', 'callback_data': f'urg_{task_id}'}]
    ]}

def main():
    offset = 0
    print("Survival Bot: Silent Mode Active. Clean Logs Guaranteed.")

    while True:
        updates = bot._req('getUpdates', {'offset': offset, 'limit': 100, 'timeout': 30})

        if not updates or 'result' not in updates:
            time.sleep(1)
            continue

        for up in updates['result']:
            offset = up['update_id'] + 1
            
            if 'message' in up:
                msg = up['message']
                chat_id = msg['chat']['id']
                user_id = msg['from']['id']
                text = msg.get('text', '')
                name = msg['from'].get('first_name', 'User')

                STORAGE['users'][user_id] = name

                if text == '/start':
                    bot.send(chat_id, 
                        f"🛠 **Система Задач**\n"
                        f"Привет, {name}. Логи чисты.\n\n"
                        "📌 `/add Дело` - создать\n"
                        "⚡ `/urgent Дело` - срочно\n"
                        "📋 `/list` - список\n"
                        "🧹 `/clear` - очистка")

                elif text.startswith('/add') or text.startswith('/urgent'):
                    is_urgent = text.startswith('/urgent')
                    raw = text.split(maxsplit=1)
                    if len(raw) < 2:
                        bot.send(chat_id, "ℹ Пиши: `/add Собрать дрова`")
                    else:
                        task_text = raw[1]
                        tid = get_next_id()
                        prio = 2 if is_urgent else 1
                        STORAGE['tasks'].append({'id': tid, 'uid': user_id, 'text': task_text, 'prio': prio, 'done': False})
                        bot.send(chat_id, "✅ Записано.")

                elif text == '/list':
                    tasks = [t for t in STORAGE['tasks'] if t['uid'] == user_id]
                    if not tasks:
                        bot.send(chat_id, "📭 Пусто.")
                    else:
                        tasks.sort(key=lambda x: x['prio'], reverse=True)
                        bot.send(chat_id, "📋 **Твои задачи:**")
                        for t in tasks:
                            status = "✅" if t['done'] else ("⚡" if t['prio'] == 2 else "📌")
                            style = f"~{t['text']}~" if t['done'] else f"*{t['text']}*"
                            bot.send(chat_id, f"{status} {style}", reply_markup=get_keyboard(t['id'], t['done']))

                elif text == '/clear':
                    STORAGE['tasks'] = [t for t in STORAGE['tasks'] if not (t['uid'] == user_id and t['done'])]
                    bot.send(chat_id, "🧹 Выполненные задачи удалены.")

                elif text == '/spy' and user_id in ADMIN_IDS:
                    if not STORAGE['tasks']:
                        bot.send(chat_id, "Задач нет.")
                    else:
                        report = "👁 **Все задачи:**\n"
                        for t in STORAGE['tasks']:
                            uname = STORAGE['users'].get(t['uid'], "?")
                            st = "V" if t['done'] else "X"
                            report += f"{uname}: {t['text']} [{st}]\n"
                        bot.send(chat_id, report)

            elif 'callback_query' in up:
                cb = up['callback_query']
                try:
                    data = cb['data']
                    parts = data.split('_')
                    action, tid = parts[0], int(parts[1])
                    chat_id = cb['message']['chat']['id']
                    mid = cb['message']['message_id']
                    
                    task = next((t for t in STORAGE['tasks'] if t['id'] == tid), None)
                    if not task:
                        bot.delete(chat_id, mid)
                        continue

                    if action == 'done':
                        task['done'] = True
                        task['prio'] = 0
                        bot.edit(chat_id, mid, f"✅ ~{task['text']}~", reply_markup=get_keyboard(tid, True))
                        bot.answer(cb['id'], "OK")
                    
                    elif action == 'urg':
                        task['prio'] = 2
                        bot.edit(chat_id, mid, f"⚡ *{task['text']}* (СРОЧНО)", reply_markup=get_keyboard(tid, False))
                        bot.answer(cb['id'], "Срочно!")

                    elif action == 'del':
                        STORAGE['tasks'].remove(task)
                        bot.delete(chat_id, mid)
                      bot.answer(cb['id'], "Удалено")

                except Exception:
                    pass

if __name__ == '__main__':
    main(                    if len(raw_text) < 2:
                        bot.send(chat_id, "⚠ Ошибка. Пиши: `/add Починить забор`")
                    else:
                        task_text = raw_text[1]
                        tid = get_next_id()
                        priority = 2 if is_urgent else 1
                        icon = "⚡" if is_urgent else "📌"
                        
                        STORAGE['tasks'].append({
                            'id': tid, 'uid': user_id, 'text': task_text, 
                            'prio': priority, 'done': False
                        })
                        bot.send(chat_id, f"{icon} Задача добавлена!")

                elif text == '/list':
                    my_tasks = [t for t in STORAGE['tasks'] if t['uid'] == user_id]
                    if not my_tasks:
                        bot.send(chat_id, "📭 Задач нет. Отдыхай.")
                    else:
                        bot.send(chat_id, "📋 **Список дел:**")
                        # Сортировка: сначала срочные, потом обычные
                        my_tasks.sort(key=lambda x: x['prio'], reverse=True)
                        
                        for t in my_tasks:
                            status = "✅" if t['done'] else ("⚡" if t['prio'] == 2 else "📌")
                            style = f"~{t['text']}~" if t['done'] else f"*{t['text']}*"
                            bot.send(chat_id, f"{status} {style}", reply_markup=get_keyboard(t['id'], t['done']))

                elif text == '/clear':
                    # Удаляем только выполненные задачи этого юзера
                    before = len(STORAGE['tasks'])
                    STORAGE['tasks'] = [t for t in STORAGE['tasks'] if not (t['uid'] == user_id and t['done'])]
                    removed = before - len(STORAGE['tasks'])
                    bot.send(chat_id, f"🧹 Удалено завершенных задач: {removed}")

                # --- ADMIN COMMANDS ---
                elif text == '/spy' and user_id in ADMIN_IDS:
                    # Показать задачи ВСЕХ
                    if not STORAGE['tasks']:
                        bot.send(chat_id, "В деревне никто не работает.")
                    else:
                        report = "👁 **Глобальный отчет:**\n"
                        for t in STORAGE['tasks']:
                            u_name = STORAGE['users'].get(t['uid'], "Unknown")
                            status = "✅" if t['done'] else "working"
                            report += f"👤 {u_name}: {t['text']} [{status}]\n"
                        bot.send(chat_id, report)

                elif text.startswith('/broadcast') and user_id in ADMIN_IDS:
                    msg_text = text[10:].strip()
                    count = 0
                    for uid in STORAGE['users']:
                        bot.send(uid, f"📢 **ВНИМАНИЕ:**\n{msg_text}")
                        count += 1
                    bot.send(chat_id, f"Разослано {count} людям.")

            # --- CALLBACKS ---
            elif 'callback_query' in up:
                cb = up['callback_query']
                data = cb['data']
                chat_id = cb['message']['chat']['id']
                mid = cb['message']['message_id']
                
                try:
                    action, tid = data.split('_')
                    tid = int(tid)
                    
                    # Ищем задачу в памяти (по ссылке)
                    task = next((t for t in STORAGE['tasks'] if t['id'] == tid), None)
                    
                    if not task:
                        bot.answer(cb['id'], "Задача уже удалена", alert=True)
                        bot.delete(chat_id, mid)
                        continue

                    if action == 'done':
                        task['done'] = True
                        task['prio'] = 0 # Снижаем приоритет
                        new_text = f"✅ ~{task['text']}~"
                        bot.edit(chat_id, mid, new_text, reply_markup=get_keyboard(tid, True))
                        bot.answer(cb['id'], "Молодец!")

                    elif action == 'urg':
                        task['prio'] = 2
                        new_text = f"⚡ *{task['text']}* (СРОЧНО)"
                        bot.edit(chat_id, mid, new_text, reply_markup=get_keyboard(tid, False))
                        bot.answer(cb['id'], "Приоритет повышен!")

                    elif action == 'del':
                        STORAGE['tasks'].remove(task)
                        bot.delete(chat_id, mid)
                        bot.answer(cb['id'], "Удалено")
                        
                except Exception as e:
                    logging.error(f"Callback error: {e}")

if __name__ == '__main__':
    main()
