import telebot
import websockets
import json
import asyncio
import threading
import time
from datetime import datetime
from collections import defaultdict

bot = telebot.TeleBot("8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4")
uri = "wss://magicgarden.gg/version/311/api/rooms/7TWG/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22p_KWTb7ix7rFYy9yhS%22&version=%22311%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"

# Глобальные данные для всех пользователей
current_global_stock = {}
current_global_weather = None
last_update_time = None

# Подписки пользователей: {chat_id: {'items': set(), 'weather': bool}}
subscriptions = defaultdict(lambda: {'items': set(), 'weather': False})

# Флаг для WebSocket потока
websocket_running = True
websocket_lock = threading.Lock()

# Кэш для быстрых ответов (обновляется каждые 5 секунд)
data_cache = {
    'stock': {},
    'weather': None,
    'timestamp': 0
}

# Словарь для перевода названий погоды
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
        return "🌤 Стандартная"
    return f"🌤 {weather_en}"
    # return weather_translations.get(weather_en, f"🌤 {weather_en}")

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

async def websocket_listener():
    """Глобальный WebSocket слушатель - один на всех"""
    global current_global_stock, current_global_weather, last_update_time, data_cache
    
    while websocket_running:
        try:
            async with websockets.connect(uri) as websocket:
                print("✅ WebSocket подключён")
                
                while websocket_running:
                    try:
                        data = await websocket.recv()
                        json_data = json.loads(data)
                        
                        if 'type' in json_data and json_data['type'] == 'Welcome':
                            # Обновляем данные магазина
                            shops = json_data['fullState']['child']['data']['shops']
                            inventory = shops['seed']['inventory']
                            
                            new_stock = {}
                            for item in inventory:
                                new_stock[item['species']] = item['initialStock']
                            
                            # Обновляем погоду
                            new_weather = json_data['fullState']['child']['data'].get('weather')
                            
                            # Обновляем кэш
                            with websocket_lock:
                                old_stock = current_global_stock.copy()
                                old_weather = current_global_weather
                                
                                current_global_stock = new_stock
                                current_global_weather = new_weather
                                last_update_time = datetime.now()
                                
                                data_cache['stock'] = new_stock.copy()
                                data_cache['weather'] = new_weather
                                data_cache['timestamp'] = time.time()
                            
                            # Отправляем уведомления подписчикам
                            notify_subscribers(old_stock, new_stock, old_weather, new_weather)
                            
                    except json.JSONDecodeError as e:
                        print(f"Ошибка парсинга JSON: {e}")
                        continue
                    except Exception as e:
                        print(f"Ошибка обработки сообщения: {e}")
                        continue
                        
        except Exception as e:
            print(f"❌ Ошибка WebSocket: {e}")
            print("🔄 Переподключение через 5 секунд...")
            await asyncio.sleep(5)

def notify_subscribers(old_stock, new_stock, old_weather, new_weather):
    """Отправляет уведомления всем подписчикам об изменениях"""
    
    # Проверяем изменения товаров
    all_items = set(old_stock.keys()) | set(new_stock.keys())
    stock_changes = []
    
    for item in all_items:
        old_count = old_stock.get(item, 0)
        new_count = new_stock.get(item, 0)
        if old_count != new_count:
            stock_changes.append((item, old_count, new_count))
    
    # Проверяем изменения погоды
    weather_changed = old_weather != new_weather
    
    # Если нет изменений - выходим
    if not stock_changes and not weather_changed:
        return
    
    # Отправляем уведомления каждому пользователю
    for chat_id, subs in subscriptions.items():
        if not subs['items'] and not subs['weather']:
            continue
        
        # Уведомления о товарах
        for item, old_count, new_count in stock_changes:
            if item in subs['items'] or '*' in subs['items']:
                try:
                    msg = format_stock_change_message(item, old_count, new_count)
                    if msg:
                        bot.send_message(chat_id, msg, parse_mode='Markdown')
                        time.sleep(0.1)  # Небольшая задержка чтобы не флудить
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {chat_id}: {e}")
        
        # Уведомление о погоде
        if subs['weather'] and weather_changed:
            try:
                msg = format_weather_change_message(old_weather, new_weather)
                if msg:
                    bot.send_message(chat_id, msg, parse_mode='Markdown')
            except Exception as e:
                print(f"Ошибка отправки уведомления о погоде пользователю {chat_id}: {e}")

def get_cached_data():
    """Возвращает кэшированные данные (мгновенно)"""
    with websocket_lock:
        if data_cache['timestamp'] > 0:
            return {
                'stock': data_cache['stock'].copy(),
                'weather': data_cache['weather']
            }
        return None

def start_websocket_thread():
    """Запускает WebSocket слушатель в отдельном потоке"""
    def run_websocket():
        asyncio.run(websocket_listener())
    
    thread = threading.Thread(target=run_websocket, daemon=True)
    thread.start()
    return thread

@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    data = get_cached_data()
    
    if not data:
        bot.send_message(chat_id, "🔄 Данные загружаются, пожалуйста, подождите 5 секунд...")
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
    bot.send_message(chat_id, message_text)

@bot.message_handler(commands=['weather'])
def weather_command(message):
    chat_id = message.chat.id
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
    
    bot.send_message(chat_id, message_text)

@bot.message_handler(commands=['subscribe_weather'])
def subscribe_weather(message):
    chat_id = message.chat.id
    
    if subscriptions[chat_id]['weather']:
        bot.send_message(chat_id, "ℹ️ Вы уже подписаны на уведомления о погоде")
    else:
        subscriptions[chat_id]['weather'] = True
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на уведомления о погоде!\n\n"
            f"Текущая погода: {translate_weather(current_global_weather) if current_global_weather else 'Не активна'}"
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
            "Для погоды: `/subscribe_weather`"
        )
        return
    
    item_name = args[1].strip()
    
    if item_name == "*":
        subscriptions[chat_id]['items'] = {'*'}
        bot.send_message(
            chat_id,
            "✅ Вы подписались на **ВСЕ товары**!\n\n"
            "Бот будет присылать уведомления о любых изменениях в магазине."
        )
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
        bot.send_message(chat_id, f"ℹ️ Вы уже подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id]['items'].add(item_name)
        current_count = stock.get(item_name, 0)
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на товар **{item_name}**\n\n"
            f"Текущее количество: {current_count} шт."
        )

@bot.message_handler(commands=['unsubscribe'])
def unsubscribe_command(message):
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(chat_id, "❌ Укажите название товара.\nПример: `/unsubscribe Carrot`")
        return
    
    item_name = args[1].strip()
    
    if item_name == "*":
        subscriptions[chat_id]['items'].clear()
        bot.send_message(chat_id, "✅ Вы отписались от всех товаров")
        return
    
    if item_name not in subscriptions[chat_id]['items']:
        bot.send_message(chat_id, f"ℹ️ Вы не подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id]['items'].discard(item_name)
        bot.send_message(chat_id, f"✅ Вы отписались от товара **{item_name}**")

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
    
    bot.send_message(chat_id, message_text)

@bot.message_handler(commands=['check'])
def check_command(message):
    chat_id = message.chat.id
    data = get_cached_data()
    
    if not data:
        bot.send_message(chat_id, "🔄 Данные загружаются, попробуйте через пару секунд")
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
    
    message_text += f"\n\n🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}"
    
    bot.send_message(chat_id, message_text)

@bot.message_handler(commands=['items'])
def items_command(message):
    chat_id = message.chat.id
    data = get_cached_data()
    
    if not data:
        bot.send_message(chat_id, "🔄 Данные загружаются, попробуйте через пару секунд")
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
    
    bot.send_message(chat_id, message_text)

@bot.message_handler(commands=['status'])
def status_command(message):
    chat_id = message.chat.id
    
    message_text = "📊 **Статус бота:**\n\n"
    message_text += f"🟢 WebSocket: {'Подключён' if current_global_stock else 'Ожидание...'}\n"
    message_text += f"👥 Активных пользователей: {len([s for s in subscriptions.values() if s['items'] or s['weather']])}\n"
    message_text += f"🕐 Последнее обновление: {last_update_time.strftime('%H:%M:%S') if last_update_time else 'Нет данных'}\n"
    message_text += f"📦 Товаров в базе: {len(current_global_stock)}\n"
    message_text += f"🌤 Текущая погода: {translate_weather(current_global_weather) if current_global_weather else 'Не активна'}\n\n"
    message_text += f"💡 Используйте /help для списка команд"
    
    bot.send_message(chat_id, message_text)

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

# Запуск бота
if __name__ == "__main__":
    print("🤖 Запуск бота...")
    print("🌐 Подключение к WebSocket...")
    
    # Запускаем глобальный WebSocket слушатель
    websocket_thread = start_websocket_thread()
    
    # Даём время на первое подключение
    time.sleep(3)
    
    print("✅ Бот готов к работе!")
    print(f"📊 Статистика: Отслеживается {len(current_global_stock)} товаров")
    
    # Запускаем бота
    bot.polling(non_stop=True)