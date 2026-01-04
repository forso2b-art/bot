import json
import logging
import urllib.request
import urllib.parse
import time
import ssl
import html  # <--- Добавлено: для защиты текста

# --- CONFIGURATION ---
API_TOKEN = '8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM'
ADMIN_IDS = [103161998, 37607526]

# Логирование
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
            if e.code == 400:
                logging.error(f"Bad Request (400) ignored. Method: {method}. Data: {data}")
                return None
            logging.error(f"Server Error {e.code}: {e.reason}")
            return None
        except Exception as e:
            return None

    def send(self, chat_id, text, reply_markup=None):
        # ИСПРАВЛЕНО: parse_mode='HTML'
        return self._req('sendMessage', {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'reply_markup': reply_markup})

    def edit(self, chat_id, msg_id, text, reply_markup=None):
        # ИСПРАВЛЕНО: parse_mode='HTML'
        return self._req('editMessageText', {'chat_id': chat_id, 'message_id': msg_id, 'text': text, 'parse_mode': 'HTML', 'reply_markup': reply_markup})

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
    print("Survival Bot: HTML Mode Active.")

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
                # Экранируем имя пользователя на всякий случай
                raw_name = msg['from'].get('first_name', 'User')
                name = html.escape(raw_name)

                STORAGE['users'][user_id] = raw_name # Сохраняем сырое имя, экранируем при выводе

                if text == '/start':
                    bot.send(chat_id, 
                        f"🛠 <b>Система Задач</b>\n"
                        f"Привет, {name}. Режим HTML активирован.\n\n"
                        "📌 <code>/add Дело</code> - создать\n"
                        "⚡ <code>/urgent Дело</code> - срочно\n"
                        "📋 <code>/list</code> - список\n"
                        "🧹 <code>/clear</code> - очистка")

                elif text.startswith('/add') or text.startswith('/urgent'):
                    is_urgent = text.startswith('/urgent')
                    raw = text.split(maxsplit=1)
                    if len(raw) < 2:
                        bot.send(chat_id, "ℹ Пиши: <code>/add Собрать дрова</code>")
                    else:
                        task_text = raw[1] # Сохраняем "как есть"
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
                        bot.send(chat_id, "📋 <b>Твои задачи:</b>")
                        for t in tasks:
                            # ИСПРАВЛЕНО: Экранирование + HTML теги
                            safe_text = html.escape(t['text'])
                            status = "✅" if t['done'] else ("⚡" if t['prio'] == 2 else "📌")
                            
                            if t['done']:
                                style = f"<s>{safe_text}</s>"
                            else:
                                style = f"<b>{safe_text}</b>"
                                
                            bot.send(chat_id, f"{status} {style}", reply_markup=get_keyboard(t['id'], t['done']))

                elif text == '/clear':
                    STORAGE['tasks'] = [t for t in STORAGE['tasks'] if not (t['uid'] == user_id and t['done'])]
                    bot.send(chat_id, "🧹 Выполненные задачи удалены.")

                elif text == '/spy' and user_id in ADMIN_IDS:
                    if not STORAGE['tasks']:
                        bot.send(chat_id, "Задач нет.")
                    else:
                        report = "👁 <b>Все задачи:</b>\n"
                        for t in STORAGE['tasks']:
                            uname = html.escape(STORAGE['users'].get(t['uid'], "?"))
                            ttext = html.escape(t['text'])
                            st = "V" if t['done'] else "X"
                            report += f"{uname}: {ttext} [{st}]\n"
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

                    safe_text = html.escape(task['text'])

                    if action == 'done':
                        task['done'] = True
                        task['prio'] = 0
                        # HTML обновление
                        bot.edit(chat_id, mid, f"✅ <s>{safe_text}</s>", reply_markup=get_keyboard(tid, True))
                        bot.answer(cb['id'], "OK")
                    
                    elif action == 'urg':
                        task['prio'] = 2
                        # HTML обновление
                        bot.edit(chat_id, mid, f"⚡ <b>{safe_text}</b> (СРОЧНО)", reply_markup=get_keyboard(tid, False))
                        bot.answer(cb['id'], "Срочно!")

                    elif action == 'del':
                        STORAGE['tasks'].remove(task)
                        bot.delete(chat_id, mid)
                        bot.answer(cb['id'], "Удалено")

                except Exception as e:
                    logging.error(f"Callback Error: {e}")
                    pass

if __name__ == '__main__':
    main()

