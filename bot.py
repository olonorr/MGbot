import telebot
import websockets
import json
import asyncio
import threading
import time
from datetime import datetime

bot = telebot.TeleBot("8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4")
uri = "wss://magicgarden.gg/version/311/api/rooms/7TWG/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22p_KWTb7ix7rFYy9yhS%22&version=%22311%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"

# Хранилище подписок: {chat_id: {'items': [список товаров], 'weather': bool}}
subscriptions = {}

# Последнее известное состояние
last_stock_state = {}  # {chat_id: {товар: количество}}
last_weather_state = {}  # {chat_id: погода}

# Флаг для остановки потоков
monitoring_threads = {}

# Словарь для перевода названий погоды на русский
weather_translations = {
    "Clear": "☀️ Ясно",
    "Sunny": "☀️ Солнечно",
    "Rain": "🌧 Дождь",
    "Rainy": "🌧 Дождливо",
    "Storm": "⛈ Гроза",
    "Thunderstorm": "⛈ Гроза",
    "Snow": "❄️ Снег",
    "Snowy": "❄️ Снежно",
    "Cloudy": "☁️ Облачно",
    "PartlyCloudy": "⛅️ Переменная облачность",
    "Fog": "🌫 Туман",
    "Foggy": "🌫 Туманно",
    "Windy": "💨 Ветрено",
    "Hot": "🔥 Жарко",
    "Cold": "❄️ Холодно",
    "Mist": "🌫 Дымка"
}

def translate_weather(weather_en: str) -> str:
    """Переводит название погоды на русский с эмодзи"""
    if not weather_en:
        return "❓ Неизвестно"
    return weather_translations.get(weather_en, f"🌤 {weather_en}")

async def fetch_shop_and_weather():
    """Получает текущие данные магазина и погоду"""
    try:
        async with websockets.connect(uri) as websocket:
            while True:
                data = await websocket.recv()
                try:
                    json_data = json.loads(data)
                    if 'type' in json_data and json_data['type'] == 'Welcome':
                        result = {}
                        
                        # Получаем данные магазина
                        shops = json_data['fullState']['child']['data']['shops']
                        inventory = shops['seed']['inventory']
                        
                        stock_dict = {}
                        for item in inventory:
                            stock_dict[item['species']] = item['initialStock']
                        result['stock'] = stock_dict
                        
                        # Получаем погоду
                        weather = json_data['fullState']['child']['data'].get('weather')
                        result['weather'] = weather if weather else None
                        
                        return result
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return None

def get_current_data() -> dict:
    """Синхронная обёртка для получения данных"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(fetch_shop_and_weather())
    except Exception as e:
        print(f"Ошибка получения данных: {e}")
        return None

def format_stock_message(stock_dict: dict) -> str:
    """Форматирует словарь с товарами в читаемое сообщение"""
    if not stock_dict:
        return "Не удалось получить данные о товарах"
    
    available_items = {k: v for k, v in stock_dict.items() if v > 0}
    
    if available_items:
        message = "✅ **Товары в наличии:**\n\n"
        for item, count in sorted(available_items.items())[:20]:
            message += f"• {item}: {count} шт.\n"
        if len(available_items) > 20:
            message += f"\n... и {len(available_items) - 20} других"
    else:
        message = "❌ В магазине нет товаров в наличии"
    
    return message

def format_weather_message(weather: str) -> str:
    """Форматирует сообщение о погоде"""
    if not weather:
        return "🌤 Погодное событие не активно"
    
    weather_ru = translate_weather(weather)
    return f"🌤 **Текущая погода:** {weather_ru}"

def format_change_message(item: str, old_count: int, new_count: int) -> str:
    """Форматирует сообщение об изменении количества товара"""
    if old_count == 0 and new_count > 0:
        return f"🎉 **{item}** появился в продаже!\n📊 Количество: {new_count}"
    elif old_count > 0 and new_count == 0:
        return f"⚠️ **{item}** закончился в магазине!"
    elif new_count > old_count:
        increase = new_count - old_count
        return f"📈 **{item}** добавлено в продажу!\n📊 Было: {old_count} → Стало: {new_count} (+{increase})"
    elif new_count < old_count:
        decrease = old_count - new_count
        return f"📉 **{item}** купили!\n📊 Было: {old_count} → Осталось: {new_count} (-{decrease})"
    return None

def format_weather_change_message(old_weather: str, new_weather: str) -> str:
    """Форматирует сообщение об изменении погоды"""
    if old_weather is None and new_weather:
        return f"🌤 **Погодное событие началось!**\n\n{format_weather_message(new_weather)}\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
    elif old_weather and new_weather is None:
        old_ru = translate_weather(old_weather)
        return f"🌤 **Погодное событие закончилось!**\n\nБыло: {old_ru}\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
    elif old_weather and new_weather and old_weather != new_weather:
        old_ru = translate_weather(old_weather)
        new_ru = translate_weather(new_weather)
        return f"🌤 **Погода изменилась!**\n\nБыло: {old_ru}\nСтало: {new_ru}\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
    return None

def monitor_shop_and_weather(chat_id):
    """Функция для мониторинга магазина и погоды в отдельном потоке"""
    global last_stock_state, last_weather_state
    
    # Инициализируем последние состояния
    if chat_id not in last_stock_state:
        last_stock_state[chat_id] = {}
    if chat_id not in last_weather_state:
        last_weather_state[chat_id] = None
    
    # Первая проверка для получения начального состояния
    initial_data = get_current_data()
    if initial_data:
        last_stock_state[chat_id] = initial_data.get('stock', {}).copy()
        last_weather_state[chat_id] = initial_data.get('weather')
    
    while monitoring_threads.get(chat_id, False):
        current_data = get_current_data()
        
        if current_data:
            current_stock = current_data.get('stock', {})
            current_weather = current_data.get('weather')
            
            # Отслеживаем изменения товаров
            if subscriptions.get(chat_id, {}).get('items'):
                all_items = set(last_stock_state[chat_id].keys()) | set(current_stock.keys())
                
                for item in all_items:
                    old_count = last_stock_state[chat_id].get(item, 0)
                    new_count = current_stock.get(item, 0)
                    
                    if old_count != new_count:
                        user_subs = subscriptions.get(chat_id, {}).get('items', [])
                        
                        if item in user_subs or "*" in user_subs:
                            change_msg = format_change_message(item, old_count, new_count)
                            if change_msg:
                                bot.send_message(chat_id, change_msg, parse_mode='Markdown')
            
            # Отслеживаем изменения погоды
            if subscriptions.get(chat_id, {}).get('weather', False):
                old_weather = last_weather_state[chat_id]
                new_weather = current_weather
                
                # Проверяем изменение погоды (включая появление и исчезновение)
                if old_weather != new_weather:
                    weather_change_msg = format_weather_change_message(old_weather, new_weather)
                    if weather_change_msg:
                        bot.send_message(chat_id, weather_change_msg, parse_mode='Markdown')
            
            # Обновляем последние состояния
            last_stock_state[chat_id] = current_stock.copy()
            last_weather_state[chat_id] = current_weather
        
        # Проверяем каждые 15 секунд
        time.sleep(15)

@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔄 Получение данных...")
    
    data = get_current_data()
    
    if data:
        stock = data.get('stock', {})
        weather = data.get('weather')
        
        message_text = "🏪 **Magic Garden Shop Bot**\n\n"
        
        # Информация о погоде
        message_text += f"{format_weather_message(weather)}\n\n"
        
        # Информация о магазине
        available_items = {k: v for k, v in stock.items() if v > 0}
        message_text += f"📦 **Товары в продаже:** {len(available_items)} из {len(stock)}\n\n"
        
        if available_items:
            message_text += "**В наличии:**\n"
            for item, count in sorted(available_items.items())[:10]:
                message_text += f"• {item}: {count} шт.\n"
            if len(available_items) > 10:
                message_text += f"\n... и {len(available_items) - 10} других"
        else:
            message_text += "❌ Нет товаров в наличии"
        
        message_text += "\n\n💡 **Команды:**\n"
        message_text += "• `/help` - все команды\n"
        message_text += "• `/weather` - текущая погода\n"
        message_text += "• `/subscribe_weather` - подписка на погоду"
        
        bot.send_message(chat_id, message_text)
    else:
        bot.send_message(chat_id, "❌ Не удалось получить данные. Попробуйте позже.")

@bot.message_handler(commands=['weather'])
def weather_command(message):
    """Показать текущую погоду"""
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔄 Получение данных о погоде...")
    
    data = get_current_data()
    
    if data:
        weather = data.get('weather')
        
        if weather:
            weather_ru = translate_weather(weather)
            message_text = f"🌤 **Текущая погода:** {weather_ru}\n\n"
            message_text += f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}\n"
            message_text += f"📊 Статус: Активно"
        else:
            message_text = "🌤 **Погодное событие не активно**\n\n"
            message_text += "Погода в игре обычная, без специальных эффектов.\n"
            message_text += "Подпишитесь на уведомления: `/subscribe_weather`"
        
        bot.send_message(chat_id, message_text)
    else:
        bot.send_message(chat_id, "❌ Не удалось получить данные о погоде")

@bot.message_handler(commands=['subscribe_weather'])
def subscribe_weather(message):
    """Подписка на уведомления о погоде"""
    chat_id = message.chat.id
    
    if chat_id not in subscriptions:
        subscriptions[chat_id] = {'items': [], 'weather': False}
    elif 'weather' not in subscriptions[chat_id]:
        subscriptions[chat_id]['weather'] = False
    
    if subscriptions[chat_id]['weather']:
        bot.send_message(
            chat_id,
            "ℹ️ Вы уже подписаны на уведомления о погоде\n\n"
            "Бот будет присылать сообщения когда:\n"
            "• Погодное событие начнётся\n"
            "• Погода изменится\n"
            "• Погодное событие закончится\n\n"
            "Чтобы отписаться: `/unsubscribe_weather`"
        )
    else:
        subscriptions[chat_id]['weather'] = True
        
        # Запускаем мониторинг
        if chat_id not in monitoring_threads or not monitoring_threads[chat_id]:
            monitoring_threads[chat_id] = True
            thread = threading.Thread(target=monitor_shop_and_weather, args=(chat_id,), daemon=True)
            thread.start()
        
        # Показываем текущую погоду
        data = get_current_data()
        weather = data.get('weather') if data else None
        
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на уведомления о погоде!\n\n"
            f"Текущая погода: {translate_weather(weather) if weather else 'Не активна'}\n\n"
            f"📢 Бот будет присылать уведомления о любых изменениях погоды."
        )

@bot.message_handler(commands=['unsubscribe_weather'])
def unsubscribe_weather(message):
    """Отписка от уведомлений о погоде"""
    chat_id = message.chat.id
    
    if chat_id not in subscriptions or not subscriptions[chat_id].get('weather', False):
        bot.send_message(chat_id, "ℹ️ Вы не подписаны на уведомления о погоде")
    else:
        subscriptions[chat_id]['weather'] = False
        bot.send_message(chat_id, "✅ Вы отписались от уведомлений о погоде")
        
        # Если нет других подписок, останавливаем мониторинг
        if not subscriptions[chat_id].get('items') and not subscriptions[chat_id].get('weather'):
            monitoring_threads[chat_id] = False

@bot.message_handler(commands=['subscribe'])
def subscribe_command(message):
    """Подписка на товар: /subscribe Carrot или /subscribe * для всех товаров"""
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(
            chat_id,
            "❌ Укажите название товара.\n\n"
            "Примеры:\n"
            "`/subscribe Carrot` - подписка на конкретный товар\n"
            "`/subscribe *` - подписка на ВСЕ товары\n\n"
            "Для подписки на погоду: `/subscribe_weather`\n\n"
            "Используйте `/items` для просмотра всех товаров"
        )
        return
    
    item_name = args[1].strip()
    
    # Инициализация структуры подписок
    if chat_id not in subscriptions:
        subscriptions[chat_id] = {'items': [], 'weather': False}
    elif 'items' not in subscriptions[chat_id]:
        subscriptions[chat_id]['items'] = []
    
    # Проверка на подписку на все товары
    if item_name == "*":
        if "*" in subscriptions[chat_id]['items']:
            bot.send_message(chat_id, "ℹ️ Вы уже подписаны на ВСЕ товары")
        else:
            subscriptions[chat_id]['items'] = ["*"]
            bot.send_message(
                chat_id,
                "✅ Вы подписались на **ВСЕ товары**!\n\n"
                "Бот будет присылать уведомления о ЛЮБЫХ изменениях в магазине.\n\n"
                "Используйте `/unsubscribe *` для отписки"
            )
            
            # Запускаем мониторинг
            if chat_id not in monitoring_threads or not monitoring_threads[chat_id]:
                monitoring_threads[chat_id] = True
                thread = threading.Thread(target=monitor_shop_and_weather, args=(chat_id,), daemon=True)
                thread.start()
        return
    
    # Обычная подписка
    data = get_current_data()
    stock = data.get('stock', {}) if data else {}
    
    if stock and item_name not in stock:
        similar = [name for name in stock.keys() if item_name.lower() in name.lower()][:5]
        hint = f"\n\nВозможно, вы имели в виду:\n" + "\n".join([f"• {s}" for s in similar]) if similar else ""
        
        bot.send_message(
            chat_id,
            f"❌ Товар '{item_name}' не найден.{hint}\n\n"
            f"Используйте `/items` для просмотра всех {len(stock)} товаров"
        )
        return
    
    if item_name in subscriptions[chat_id]['items']:
        bot.send_message(chat_id, f"ℹ️ Вы уже подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id]['items'].append(item_name)
        current_count = stock.get(item_name, 0)
        
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на товар **{item_name}**\n\n"
            f"Текущее количество: {current_count} шт.\n\n"
            f"Бот будет присылать уведомления при любых изменениях."
        )
        
        # Запускаем мониторинг
        if chat_id not in monitoring_threads or not monitoring_threads[chat_id]:
            monitoring_threads[chat_id] = True
            thread = threading.Thread(target=monitor_shop_and_weather, args=(chat_id,), daemon=True)
            thread.start()

@bot.message_handler(commands=['unsubscribe'])
def unsubscribe_command(message):
    """Отписка от товара: /unsubscribe Carrot или /unsubscribe *"""
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(
            chat_id,
            "❌ Укажите название товара.\n"
            "Примеры:\n"
            "`/unsubscribe Carrot`\n"
            "`/unsubscribe *` - отписаться от всех товаров"
        )
        return
    
    item_name = args[1].strip()
    
    if chat_id not in subscriptions or 'items' not in subscriptions[chat_id]:
        subscriptions[chat_id] = {'items': [], 'weather': False}
    
    if item_name not in subscriptions[chat_id]['items']:
        bot.send_message(chat_id, f"ℹ️ Вы не подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id]['items'].remove(item_name)
        bot.send_message(chat_id, f"✅ Вы отписались от товара **{item_name}**")
        
        # Если нет других подписок, останавливаем мониторинг
        if not subscriptions[chat_id]['items'] and not subscriptions[chat_id].get('weather', False):
            monitoring_threads[chat_id] = False
            bot.send_message(chat_id, "🔕 Мониторинг остановлен (нет активных подписок)")

@bot.message_handler(commands=['mysubs'])
def list_subscriptions(message):
    """Показать все подписки пользователя"""
    chat_id = message.chat.id
    
    if chat_id not in subscriptions:
        subscriptions[chat_id] = {'items': [], 'weather': False}
    
    items_subs = subscriptions[chat_id].get('items', [])
    weather_sub = subscriptions[chat_id].get('weather', False)
    
    if not items_subs and not weather_sub:
        bot.send_message(
            chat_id, 
            "📭 У вас нет активных подписок.\n\n"
            "Доступные подписки:\n"
            "• `/subscribe НазваниеТовара` - на товар\n"
            "• `/subscribe *` - на все товары\n"
            "• `/subscribe_weather` - на погоду\n\n"
            "• `/items` - список товаров"
        )
        return
    
    message_text = "📋 **Ваши подписки:**\n\n"
    
    if weather_sub:
        message_text += "🌤 **Погода** - активна\n\n"
    
    if items_subs:
        if "*" in items_subs:
            message_text += "🛒 **ВСЕ ТОВАРЫ** - активна\n"
        else:
            message_text += f"🛒 **Товары ({len(items_subs)}):**\n"
            for item in sorted(items_subs):
                message_text += f"  • {item}\n"
    
    message_text += "\n➖ Чтобы отписаться:\n"
    message_text += "  `/unsubscribe НазваниеТовара`\n"
    message_text += "  `/unsubscribe_weather`\n\n"
    message_text += "➖ Проверить магазин: `/check`"
    
    bot.send_message(chat_id, message_text)

@bot.message_handler(commands=['check'])
def check_shop(message):
    """Проверить текущее состояние магазина и погоду"""
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔄 Получение данных...")
    
    data = get_current_data()
    
    if data:
        stock = data.get('stock', {})
        weather = data.get('weather')
        
        message_text = "🏪 **Текущее состояние:**\n\n"
        
        # Погода
        message_text += f"{format_weather_message(weather)}\n\n"
        
        # Товары в наличии
        available = {k: v for k, v in stock.items() if v > 0}
        if available:
            message_text += f"✅ **Товары в наличии ({len(available)}):**\n"
            for item, count in sorted(available.items())[:15]:
                message_text += f"  • {item}: {count} шт.\n"
            if len(available) > 15:
                message_text += f"\n  ... и {len(available) - 15} других"
        else:
            message_text += "❌ Нет товаров в наличии"
        
        bot.send_message(chat_id, message_text)
    else:
        bot.send_message(chat_id, "❌ Не удалось получить данные. Попробуйте позже.")

@bot.message_handler(commands=['items'])
def list_items(message):
    """Показать список всех доступных товаров"""
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔄 Загрузка списка товаров...")
    
    data = get_current_data()
    
    if data:
        stock = data.get('stock', {})
        available = [item for item, count in stock.items() if count > 0]
        unavailable = [item for item, count in stock.items() if count == 0]
        
        message_text = f"📋 **Всего товаров:** {len(stock)}\n\n"
        
        if available:
            message_text += f"✅ **В наличии ({len(available)}):**\n"
            message_text += "• " + "\n• ".join(sorted(available)[:20])
            if len(available) > 20:
                message_text += f"\n... и {len(available) - 20} других"
            message_text += "\n\n"
        
        if unavailable:
            message_text += f"❌ **Отсутствуют ({len(unavailable)}):**\n"
            message_text += "• " + "\n• ".join(sorted(unavailable)[:10])
            if len(unavailable) > 10:
                message_text += f"\n... и {len(unavailable) - 10} других"
        
        message_text += "\n\n💡 **Подписки:**\n"
        message_text += "• `/subscribe Название` - на товар\n"
        message_text += "• `/subscribe *` - на всё\n"
        message_text += "• `/subscribe_weather` - на погоду"
        
        bot.send_message(chat_id, message_text)
    else:
        bot.send_message(chat_id, "❌ Не удалось получить список товаров")

@bot.message_handler(commands=['status'])
def monitoring_status(message):
    """Показать статус мониторинга"""
    chat_id = message.chat.id
    is_monitoring = monitoring_threads.get(chat_id, False)
    
    if chat_id not in subscriptions:
        subscriptions[chat_id] = {'items': [], 'weather': False}
    
    items_count = len(subscriptions[chat_id].get('items', []))
    weather_sub = subscriptions[chat_id].get('weather', False)
    
    if is_monitoring:
        status = "🟢 **Активен**"
    else:
        status = "🔴 **Остановлен**"
    
    bot.send_message(
        chat_id,
        f"📊 **Статус мониторинга:**\n\n"
        f"Состояние: {status}\n"
        f"Подписки на товары: {items_count}\n"
        f"Подписка на погоду: {'✅ Да' if weather_sub else '❌ Нет'}\n"
        f"Частота проверки: каждые 15 секунд\n\n"
        f"• `/check` - проверить сейчас\n"
        f"• `/mysubs` - мои подписки\n"
        f"• `/subscribe *` - подписаться на всё"
    )

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
🤖 **Magic Garden Shop Bot - Полная справка**

🌤 **Команды погоды:**
/weather - Текущая погода
/subscribe_weather - Подписка на изменения погоды
/unsubscribe_weather - Отписка от погоды

🛒 **Команды магазина:**
/check - Проверить магазин и погоду
/items - Список всех товаров

📌 **Подписки на товары:**
/subscribe [товар] - Подписаться на товар
   Пример: `/subscribe Carrot`
   
/subscribe * - Подписаться на ВСЕ товары
/unsubscribe [товар] - Отписаться от товара
/unsubscribe * - Отписаться от всех товаров

/mysubs - Показать все подписки
/status - Статус мониторинга
/start - Начало работы
/help - Эта справка

📢 **Что отслеживается:**
• **Товары:** появление, изменение количества, исчезновение
• **Погода:** начало события, изменение, окончание

⏱️ **Частота проверки:** каждые 15 секунд

💡 **Совет:** Подпишитесь на `*` и `subscribe_weather` чтобы видеть всё!
"""
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# Запуск бота
if __name__ == "__main__":
    print("🤖 Бот запущен...")
    print("🌤 Функция отслеживания погоды активна")
    print("🛒 Функция отслеживания товаров активна")
    print("✅ Готов к работе!")
    bot.polling(non_stop=True)