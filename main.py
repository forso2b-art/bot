import json
import logging
import urllib.request
import urllib.parse
import re
import time
import ssl

# --- CONFIGURATION ---
API_TOKEN = '8278293381:AAHpnS4M6txEuChRjjLY_vgZUt6ey14NMhM'
ADMIN_IDS = [103161998, 37607526]

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SurvivalBot")

# Игнорирование ошибок SSL для старых серверов
ssl._create_default_https_context = ssl._create_unverified_context

# --- MINI-FRAMEWORK (NO LIBRARIES REQUIRED) ---
class SurvivalBot:
    def __init__(self, token):
        self.api_url = f"https://api.telegram.org/bot{token}/"

    def _request(self, method, data=None):
        url = self.api_url + method
        headers = {'Content-Type': 'application/json'}
        try:
            if data:
                payload = json.dumps(data).encode('utf-8')
                req = urllib.request.Request(url, data=payload, headers=headers)
            else:
                req = urllib.request.Request(url)
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            logger.error(f"Network error: {e}")
            return None

    def send_message(self, chat_id, text, reply_markup=None):
        data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
        if reply_markup:
            data['reply_markup'] = reply_markup
        return self._request('sendMessage', data)

    def send_photo(self, chat_id, photo_url, caption=None, reply_markup=None):
        data = {'chat_id': chat_id, 'photo': photo_url, 'caption': caption, 'parse_mode': 'Markdown'}
        if reply_markup:
            data['reply_markup'] = reply_markup
        return self._request('sendPhoto', data)

    def get_updates(self, offset=None):
        data = {'timeout': 30, 'allowed_updates': ['message', 'callback_query']}
        if offset:
            data['offset'] = offset
        return self._request('getUpdates', data)

    def answer_callback(self, callback_id, text=None, show_alert=False):
        data = {'callback_query_id': callback_id, 'show_alert': show_alert}
        if text:
            data['text'] = text
        return self._request('answerCallbackQuery', data)

# --- PINTEREST LOGIC (REGEX ONLY) ---
def get_pinterest_image_no_lib(url):
    try:
        # Эмуляция браузера (обязательно для Pinterest)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            html_content = response.read().decode('utf-8')
            
            # Поиск ссылки на изображение через Regex (ищем og:image)
            # Это заменяет BeautifulSoup
            match = re.search(r'<meta property="og:image" content="([^"]+)"', html_content)
            if match:
                return match.group(1)
            
            # Запасной вариант: ищем link rel="image_src"
            match_alt = re.search(r'<link rel="image_src" href="([^"]+)"', html_content)
            if match_alt:
                return match_alt.group(1)
                
            return None
    except Exception as e:
        logger.error(f"Pinterest parsing error: {e}")
        return None

# --- MAIN ---
def main():
    bot = SurvivalBot(API_TOKEN)
    offset = 0
    print("Survival Bot v5 (No-Lib) Started...")

    while True:
        updates_response = bot.get_updates(offset)
        
        if not updates_response or not updates_response.get('ok'):
            time.sleep(2)
            continue

        for update in updates_response.get('result', []):
            offset = update['update_id'] + 1
            
            # 1. Обработка сообщений
            if 'message' in update:
                msg = update['message']
                chat_id = msg['chat']['id']
                user_id = msg['from']['id']
                text = msg.get('text', '')

                # Команды
                if text == '/start':
                    kb = {'inline_keyboard': [[{'text': '🆘 Помощь', 'callback_data': 'help'}]]}
                    bot.send_message(chat_id, "👋 **Система готова.**\nПришли ссылку с Pinterest.", reply_markup=kb)
                
                elif text == '/admin':
                    if user_id in ADMIN_IDS:
                        kb = {'inline_keyboard': [[{'text': 'Статистика', 'callback_data': 'stats'}]]}
                        bot.send_message(chat_id, "🔓 **Админ-панель активна**", reply_markup=kb)
                    else:
                        # Игнорируем или отвечаем стандартно
                        pass

                # Обработка ссылок
                elif 'pin.it' in text or 'pinterest.com' in text:
                    bot.send_message(chat_id, "🔍 *Ищу фото...*")
                    image_url = get_pinterest_image_no_lib(text)
                    
                    if image_url:
                        kb = {'inline_keyboard': [[{'text': '🔗 Источник', 'url': text}]]}
                        bot.send_photo(chat_id, image_url, "✅ **Готово**", reply_markup=kb)
                    else:
                        bot.send_message(chat_id, "❌ Не удалось найти фото. Проверьте ссылку.")

            # 2. Обработка кнопок (Callback Query)
            elif 'callback_query' in update:
                cb = update['callback_query']
                cb_id = cb['id']
                data = cb['data']
                chat_id = cb['message']['chat']['id']
                
                if data == 'help':
                    bot.answer_callback(cb_id, "Просто отправь ссылку!")
                    bot.send_message(chat_id, "ℹ️ Отправь ссылку вида `https://pin.it/...`")
                elif data == 'stats':
                    bot.answer_callback(cb_id, "Все системы в норме", show_alert=True)

        time.sleep(0.5)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("Bot stopped.")
