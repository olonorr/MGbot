import telebot
import websockets
import json
import asyncio
import threading
import time
from datetime import datetime
from collections import defaultdict
import ssl

bot = telebot.TeleBot("8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4")
uri = "wss://magicgarden.gg/version/311/api/rooms/7TWG/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22p_KWTb7ix7rFYy9yhS%22&version=%22311%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"

# Глобальные данные
current_global_stock = {}
current_global_weather = None
last_update_time = None
websocket_connected = False
data_ready = False  # Флаг готовности данных

# Подписки пользователей
subscriptions = defaultdict(lambda: {'items': set(), 'weather': False})

# Кэш данных (инициализируем заглушками)
data_cache = {
    'stock': {},
    'weather': None,
    'timestamp': 0
}

# Lock для потокобезопасности
data_lock = threading.Lock()
ready_event = threading.Event()  # Событие для сигнала готовности данных

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
    if not weather_en:
        return "❓ Не активно"
    return weather_translations.get(weather_en, f"🌤 {weather_en}")

def format_weather_message(weather: str) -> str:
    if not weather:
        return "🌤 Погодное событие не активно"
    weather_ru = translate_weather(weather)
    return f"🌤 **Текущая погода:** {weather_ru}"

def format_weather_change_message(old_weather: str, new_weather: str) -> str:
    if old_weather is None and new_weather:
        return f"🌤 **Погодное событие началось!**\n\n{format_weather_message(new_weather)}"
    elif old_weather and new_weather is None:
        old_ru = translate_weather(old_weather)
        return f"🌤 **Погодное событие закончилось!**\n\nБыло: {old_ru}"
    elif old_weather and new_weather and old_weather != new_weather:
        old_ru = translate_weather(old_weather)
        new_ru = translate_weather(new_weather)
        return f"🌤 **Погода изменилась!**\n\nБыло: {old_ru}\nСтало: {new_ru}"
    return None

def format_stock_change_message(item: str, old_count: int, new_count: int) -> str:
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

def update_global_data(new_stock, new_weather):
    """Обновляет глобальные данные и отправляет уведомления"""
    global current_global_stock, current_global_weather, last_update_time, data_cache, data_ready
    
    with data_lock:
        old_stock = current_global_stock.copy() if current_global_stock else {}
        old_weather = current_global_weather
        
        current_global_stock = new_stock
        current_global_weather = new_weather
        last_update_time = datetime.now()
        
        data_cache['stock'] = new_stock.copy()
        data_cache['weather'] = new_weather
        data_cache['timestamp'] = time.time()
        
        if not data_ready and new_stock:
            data_ready = True
            ready_event.set()  # Сигнализируем, что данные готовы
    
    # Отправляем уведомления только если есть старые данные
    if old_stock:
        notify_subscribers(old_stock, new_stock, old_weather, new_weather)

def notify_subscribers(old_stock, new_stock, old_weather, new_weather):
    """Отправляет уведомления всем подписчикам"""
    
    # Находим изменения товаров
    all_items = set(old_stock.keys()) | set(new_stock.keys())
    stock_changes = []
    
    for item in all_items:
        old_count = old_stock.get(item, 0)
        new_count = new_stock.get(item, 0)
        if old_count != new_count:
            stock_changes.append((item, old_count, new_count))
    
    weather_changed = old_weather != new_weather
    
    if not stock_changes and not weather_changed:
        return
    
    # Отправляем уведомления каждому пользователю
    for chat_id, subs in list(subscriptions.items()):
        try:
            # Уведомления о товарах
            for item, old_count, new_count in stock_changes:
                if item in subs['items'] or '*' in subs['items']:
                    msg = format_stock_change_message(item, old_count, new_count)
                    if msg:
                        bot.send_message(chat_id, msg, parse_mode='Markdown')
                        time.sleep(0.05)
            
            # Уведомление о погоде
            if subs['weather'] and weather_changed:
                msg = format_weather_change_message(old_weather, new_weather)
                if msg:
                    bot.send_message(chat_id, msg, parse_mode='Markdown')
        except Exception as e:
            print(f"Ошибка отправки пользователю {chat_id}: {e}")

async def websocket_listener():
    """WebSocket слушатель - работает в отдельном потоке с своим event loop"""
    global websocket_connected
    
    while True:
        try:
            print("🔄 Подключение к WebSocket...")
            async with websockets.connect(
                uri,
                ping_interval=20,
                ping_timeout=60,
                close_timeout=10
            ) as websocket:
                print("✅ WebSocket подключён успешно!")
                websocket_connected = True
                
                # Инициализируем данные первым сообщением
                first_message = await websocket.recv()
                data = json.loads(first_message)
                
                if data.get('type') == 'Welcome':
                    # Получаем данные магазина
                    shops = data['fullState']['child']['data']['shops']
                    inventory = shops['seed']['inventory']
                    
                    new_stock = {}
                    for item in inventory:
                        new_stock[item['species']] = item['initialStock']
                    
                    # Получаем погоду
                    new_weather = data['fullState']['child']['data'].get('weather')
                    
                    # Обновляем глобальные данные
                    update_global_data(new_stock, new_weather)
                    print(f"📊 Инициализировано: {len(new_stock)} товаров, погода: {new_weather}")
                
                while True:
                    try:
                        message = await websocket.recv()
                        data = json.loads(message)
                        
                        if data.get('type') == 'Welcome':
                            # Получаем данные магазина
                            shops = data['fullState']['child']['data']['shops']
                            inventory = shops['seed']['inventory']
                            
                            new_stock = {}
                            for item in inventory:
                                new_stock[item['species']] = item['initialStock']
                            
                            # Получаем погоду
                            new_weather = data['fullState']['child']['data'].get('weather')
                            
                            # Обновляем глобальные данные
                            update_global_data(new_stock, new_weather)
                            
                    except websockets.exceptions.ConnectionClosed:
                        print("❌ WebSocket соединение закрыто")
                        break
                    except json.JSONDecodeError as e:
                        print(f"Ошибка JSON: {e}")
                        continue
                    except Exception as e:
                        print(f"Ошибка обработки: {e}")
                        continue
                        
        except Exception as e:
            print(f"❌ Ошибка WebSocket: {e}")
            websocket_connected = False
            data_ready = False
            print("🔄 Переподключение через 5 секунд...")
            await asyncio.sleep(5)

def run_websocket():
    """Запускает WebSocket в отдельном потоке"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(websocket_listener())

def get_cached_data():
    """Быстрое получение кэшированных данных с ожиданием готовности"""
    # Ждём готовности данных (максимум 10 секунд)
    if not data_ready:
        ready_event.wait(timeout=10)
    
    with data_lock:
        if data_cache['timestamp'] > 0 and data_cache['stock']:
            return {
                'stock': data_cache['stock'].copy(),
                'weather': data_cache['weather']
            }
    return None

def wait_for_data(timeout=10):
    """Ожидает загрузки данных"""
    start_time = time.time()
    while not data_ready and (time.time() - start_time) < timeout:
        time.sleep(0.5)
    return data_ready

# ============ ОБРАБОТЧИКИ КОМАНД ============

@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    
    # Отправляем сообщение о загрузке
    msg = bot.send_message(chat_id, "🔄 Загрузка данных магазина, пожалуйста подождите...")
    
    # Ждём данные
    if not wait_for_data(10):
        bot.edit_message_text("❌ Не удалось загрузить данные. Попробуйте позже.", chat_id, msg.message_id)
        return
    
    data = get_cached_data()
    
    if not data or not data.get('stock'):
        bot.edit_message_text("❌ Не удалось получить данные. Попробуйте позже.", chat_id, msg.message_id)
        return
    
    stock = data.get('stock', {})
    weather = data.get('weather')
    
    available_items = {k: v for k, v in stock.items() if v > 0}
    
    message_text = "🏪 **Magic Garden Shop Bot**\n\n"
    message_text += f"{format_weather_message(weather)}\n\n"
    message_text += f"📦 **Товары в продаже:** {len(available_items)} из {len(stock)}\n\n"
    
    if available_items:
        message_text += "**В наличии:**\n"
        for item, count in sorted(available_items.items())[:10]:
            message_text += f"• {item}: {count} шт.\n"
        if len(available_items) > 10:
            message_text += f"\n... и {len(available_items) - 10} других"
    else:
        message_text += "❌ Нет товаров в наличии"
    
    message_text += "\n\n💡 **Команды:** /help"
    
    bot.edit_message_text(message_text, chat_id, msg.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['weather'])
def weather_command(message):
    chat_id = message.chat.id
    
    if not wait_for_data(5):
        bot.send_message(chat_id, "🔄 Данные загружаются, попробуйте через пару секунд")
        return
    
    data = get_cached_data()
    
    if not data:
        bot.send_message(chat_id, "🔄 Данные загружаются, попробуйте через пару секунд")
        return
    
    weather = data.get('weather')
    
    if weather:
        message_text = f"🌤 **Текущая погода:** {translate_weather(weather)}\n\n"
        message_text += f"⏰ Последнее обновление: {datetime.now().strftime('%H:%M:%S')}"
    else:
        message_text = "🌤 **Погодное событие не активно**\n\n"
        message_text += "Подпишитесь на уведомления: `/subscribe_weather`"
    
    bot.send_message(chat_id, message_text, parse_mode='Markdown')

@bot.message_handler(commands=['subscribe_weather'])
def subscribe_weather(message):
    chat_id = message.chat.id
    
    # Ждём данные для отображения текущей погоды
    wait_for_data(3)
    
    if subscriptions[chat_id]['weather']:
        bot.send_message(chat_id, "ℹ️ Вы уже подписаны на уведомления о погоде")
    else:
        subscriptions[chat_id]['weather'] = True
        weather_text = translate_weather(current_global_weather) if current_global_weather else 'Не активна'
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на уведомления о погоде!\n\n"
            f"Текущая погода: {weather_text}",
            parse_mode='Markdown'
        )

@bot.message_handler(commands=['unsubscribe_weather'])
def unsubscribe_weather(message):
    chat_id = message.chat.id
    
    if not subscriptions[chat_id]['weather']:
        bot.send_message(chat_id, "ℹ️ Вы не подписаны на уведомления о погоде")
    else:
        subscriptions[chat_id]['weather'] = False
        bot.send_message(chat_id, "✅ Вы отписались от уведомлений о погоде")

@bot.message_handler(commands=['subscribe'])
def subscribe_command(message):
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(
            chat_id,
            "❌ Укажите название товара.\n\n"
            "Примеры:\n"
            "`/subscribe Carrot`\n"
            "`/subscribe *` - все товары\n\n"
            "Для погоды: `/subscribe_weather`",
            parse_mode='Markdown'
        )
        return
    
    item_name = args[1].strip()
    
    if item_name == "*":
        subscriptions[chat_id]['items'] = {'*'}
        bot.send_message(
            chat_id,
            "✅ Вы подписались на **ВСЕ товары**!\n\n"
            "Бот будет присылать уведомления о любых изменениях в магазине.",
            parse_mode='Markdown'
        )
        return
    
    # Ждём данные для проверки существования товара
    if not wait_for_data(5):
        bot.send_message(chat_id, "🔄 Данные загружаются, попробуйте через пару секунд")
        return
    
    data = get_cached_data()
    if not data:
        bot.send_message(chat_id, "🔄 Данные загружаются, попробуйте через пару секунд")
        return
    
    stock = data.get('stock', {})
    
    if item_name not in stock:
        similar = [name for name in stock.keys() if item_name.lower() in name.lower()][:5]
        hint = f"\n\nВозможно, вы имели в виду:\n" + "\n".join([f"• {s}" for s in similar]) if similar else ""
        bot.send_message(chat_id, f"❌ Товар '{item_name}' не найден.{hint}")
        return
    
    if item_name in subscriptions[chat_id]['items']:
        bot.send_message(chat_id, f"ℹ️ Вы уже подписаны на товар **{item_name}**", parse_mode='Markdown')
    else:
        subscriptions[chat_id]['items'].add(item_name)
        current_count = stock.get(item_name, 0)
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на товар **{item_name}**\n\n"
            f"Текущее количество: {current_count} шт.",
            parse_mode='Markdown'
        )

@bot.message_handler(commands=['unsubscribe'])
def unsubscribe_command(message):
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(chat_id, "❌ Укажите название товара.\nПример: `/unsubscribe Carrot`", parse_mode='Markdown')
        return
    
    item_name = args[1].strip()
    
    if item_name == "*":
        subscriptions[chat_id]['items'].clear()
        bot.send_message(chat_id, "✅ Вы отписались от всех товаров")
        return
    
    if item_name not in subscriptions[chat_id]['items']:
        bot.send_message(chat_id, f"ℹ️ Вы не подписаны на товар **{item_name}**", parse_mode='Markdown')
    else:
        subscriptions[chat_id]['items'].discard(item_name)
        bot.send_message(chat_id, f"✅ Вы отписались от товара **{item_name}**", parse_mode='Markdown')

@bot.message_handler(commands=['mysubs'])
def list_subscriptions(message):
    chat_id = message.chat.id
    subs = subscriptions[chat_id]
    
    if not subs['items'] and not subs['weather']:
        bot.send_message(chat_id, "📭 У вас нет активных подписок.\n\nИспользуйте /help для списка команд")
        return
    
    message_text = "📋 **Ваши подписки:**\n\n"
    
    if subs['weather']:
        message_text += "🌤 **Погода** - активна\n\n"
    
    if subs['items']:
        if '*' in subs['items']:
            message_text += "🛒 **ВСЕ ТОВАРЫ** - активна\n"
        else:
            message_text += f"🛒 **Товары ({len(subs['items'])}):**\n"
            for item in sorted(subs['items']):
                message_text += f"  • {item}\n"
    
    bot.send_message(chat_id, message_text, parse_mode='Markdown')

@bot.message_handler(commands=['check'])
def check_command(message):
    chat_id = message.chat.id
    
    msg = bot.send_message(chat_id, "🔄 Получение данных...")
    
    if not wait_for_data(5):
        bot.edit_message_text("🔄 Данные загружаются, попробуйте через пару секунд", chat_id, msg.message_id)
        return
    
    data = get_cached_data()
    
    if not data:
        bot.edit_message_text("❌ Не удалось получить данные", chat_id, msg.message_id)
        return
    
    stock = data.get('stock', {})
    weather = data.get('weather')
    
    available = {k: v for k, v in stock.items() if v > 0}
    
    message_text = "🏪 **Текущее состояние:**\n\n"
    message_text += f"{format_weather_message(weather)}\n\n"
    
    if available:
        message_text += f"✅ **Товары в наличии ({len(available)}):**\n"
        for item, count in sorted(available.items())[:15]:
            message_text += f"  • {item}: {count} шт.\n"
        if len(available) > 15:
            message_text += f"\n  ... и {len(available) - 15} других"
    else:
        message_text += "❌ Нет товаров в наличии"
    
    message_text += f"\n\n🕐 Обновлено: {last_update_time.strftime('%H:%M:%S') if last_update_time else 'только что'}"
    
    bot.edit_message_text(message_text, chat_id, msg.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['items'])
def items_command(message):
    chat_id = message.chat.id
    
    msg = bot.send_message(chat_id, "🔄 Загрузка списка товаров...")
    
    if not wait_for_data(5):
        bot.edit_message_text("🔄 Данные загружаются, попробуйте через пару секунд", chat_id, msg.message_id)
        return
    
    data = get_cached_data()
    
    if not data:
        bot.edit_message_text("❌ Не удалось получить список товаров", chat_id, msg.message_id)
        return
    
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
    
    bot.edit_message_text(message_text, chat_id, msg.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['status'])
def status_command(message):
    chat_id = message.chat.id
    
    active_users = sum(1 for s in subscriptions.values() if s['items'] or s['weather'])
    
    message_text = "📊 **Статус бота:**\n\n"
    message_text += f"🟢 WebSocket: {'Подключён ✅' if websocket_connected else 'Отключён ❌'}\n"
    message_text += f"📦 Данные: {'Готовы ✅' if data_ready else 'Загружаются ⏳'}\n"
    message_text += f"👥 Активных пользователей: {active_users}\n"
    message_text += f"🕐 Последнее обновление: {last_update_time.strftime('%H:%M:%S') if last_update_time else 'Нет данных'}\n"
    message_text += f"📦 Товаров в базе: {len(current_global_stock)}\n"
    message_text += f"🌤 Текущая погода: {translate_weather(current_global_weather) if current_global_weather else 'Не активна'}\n\n"
    message_text += f"💡 Используйте /help для списка команд"
    
    bot.send_message(chat_id, message_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
🤖 **Magic Garden Shop Bot - Справка**

🌤 **Погода:**
/weather - Текущая погода
/subscribe_weather - Подписка на изменения погоды
/unsubscribe_weather - Отписка от погоды

🛒 **Магазин:**
/check - Проверить магазин
/items - Список всех товаров

📌 **Подписки на товары:**
/subscribe [товар] - Подписаться на товар
/subscribe * - Подписаться на ВСЕ товары
/unsubscribe [товар] - Отписаться
/unsubscribe * - Отписаться от всех

📋 **Управление:**
/mysubs - Мои подписки
/status - Статус бота
/start - Начало работы
/help - Эта справка

📢 **Бот отправляет уведомления о:**
• Появлении/исчезновении товаров
• Изменении количества товаров
• Начале/конце погодных событий
• Смене погоды

⚡ Данные обновляются автоматически в реальном времени!
"""
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# ============ ЗАПУСК ============

if __name__ == "__main__":
    print("🤖 Запуск бота...")
    print("🌐 Подключение к WebSocket...")
    
    # Запускаем WebSocket в отдельном потоке
    ws_thread = threading.Thread(target=run_websocket, daemon=True)
    ws_thread.start()
    
    # Ждём первого подключения и получения данных
    print("⏳ Ожидание загрузки данных...")
    if ready_event.wait(timeout=15):
        print("✅ Данные успешно загружены!")
    else:
        print("⚠️ Внимание: данные не загрузились в течение 15 секунд")
    
    print("✅ Бот готов к работе!")
    print("📊 Бот запущен и принимает команды...")
    
    # Запускаем бота
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            print(f"❌ Ошибка в polling: {e}")
            print("🔄 Перезапуск polling через 5 секунд...")
            time.sleep(5)