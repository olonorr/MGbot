import telebot
import websockets
import json
import asyncio
import threading
import time
from datetime import datetime

bot = telebot.TeleBot("8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4")
uri = "wss://magicgarden.gg/version/311/api/rooms/7TWG/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22p_KWTb7ix7rFYy9yhS%22&version=%22311%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"

# Хранилище подписок: {chat_id: [список товаров]}
subscriptions = {}

# Последнее известное состояние товаров {chat_id: {товар: количество}}
last_stock_state = {}

# Флаг для остановки потоков
monitoring_threads = {}

async def fetch_shop_data():
    """Получает текущие данные магазина"""
    try:
        async with websockets.connect(uri) as websocket:
            while True:
                data = await websocket.recv()
                try:
                    json_data = json.loads(data)
                    if 'type' in json_data and json_data['type'] == 'Welcome':
                        shops = json_data['fullState']['child']['data']['shops']
                        inventory = shops['seed']['inventory']
                        
                        # Преобразуем в словарь {товар: количество}
                        stock_dict = {}
                        for item in inventory:
                            stock_dict[item['species']] = item['initialStock']
                        return stock_dict
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return None

def get_current_stock() -> dict:
    """Синхронная обёртка для получения данных"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(fetch_shop_data())
    except Exception as e:
        print(f"Ошибка получения данных: {e}")
        return None

def format_stock_message(stock_dict: dict) -> str:
    """Форматирует словарь с товарами в читаемое сообщение"""
    if not stock_dict:
        return "Не удалось получить данные о товарах"
    
    message = "📦 **Товары в магазине:**\n\n"
    # Сортируем по названию для удобства
    for item, count in sorted(stock_dict.items()):
        if count > 0:
            message += f"✅ {item} - {count}\n"
        else:
            message += f"❌ {item} - 0\n"
    return message

def format_change_message(item: str, old_count: int, new_count: int) -> str:
    """Форматирует сообщение об изменении количества товара"""
    if old_count == 0 and new_count > 0:
        return f"🎉 **{item}** появился в продаже!\n📊 Количество: {new_count}\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
    elif old_count > 0 and new_count == 0:
        return f"⚠️ **{item}** закончился в магазине!\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
    elif new_count > old_count:
        increase = new_count - old_count
        return f"📈 **{item}** добавлено в продажу!\n📊 Было: {old_count} → Стало: {new_count} (+{increase})\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
    elif new_count < old_count:
        decrease = old_count - new_count
        return f"📉 **{item}** купили!\n📊 Было: {old_count} → Осталось: {new_count} (-{decrease})\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
    return None

def monitor_shop(chat_id):
    """Функция для мониторинга магазина в отдельном потоке"""
    global last_stock_state
    
    # Инициализируем последнее состояние для этого чата
    if chat_id not in last_stock_state:
        last_stock_state[chat_id] = {}
    
    # Первая проверка для получения начального состояния
    initial_stock = get_current_stock()
    if initial_stock:
        last_stock_state[chat_id] = initial_stock.copy()
    
    while monitoring_threads.get(chat_id, False):
        current_stock = get_current_stock()
        
        if current_stock:
            # Получаем все товары (объединяем ключи из старого и нового состояния)
            all_items = set(last_stock_state[chat_id].keys()) | set(current_stock.keys())
            
            # Отслеживаем изменения для КАЖДОГО товара
            changes = []
            for item in all_items:
                old_count = last_stock_state[chat_id].get(item, 0)
                new_count = current_stock.get(item, 0)
                
                # Если количество изменилось
                if old_count != new_count:
                    changes.append((item, old_count, new_count))
            
            # Отправляем сообщения об изменениях
            for item, old_count, new_count in changes:
                # Проверяем подписки пользователя
                user_subs = subscriptions.get(chat_id, [])
                
                # Отправляем уведомление если:
                # 1. Пользователь подписан на этот товар, ИЛИ
                # 2. Пользователь подписан на "все товары" (специальный режим)
                if item in user_subs or "*" in user_subs:
                    change_msg = format_change_message(item, old_count, new_count)
                    if change_msg:
                        bot.send_message(chat_id, change_msg, parse_mode='Markdown')
            
            # Обновляем последнее состояние
            last_stock_state[chat_id] = current_stock.copy()
        
        # Проверяем каждые 15 секунд (чаще для отслеживания быстрых изменений)
        time.sleep(15)

@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    stock = get_current_stock()
    
    bot.send_message(chat_id, "🔄 Получение данных о магазине...")
    
    if stock:
        # Показываем ТОЛЬКО товары в наличии (с количеством > 0)
        available_items = {k: v for k, v in stock.items() if v > 0}
        if available_items:
            message_text = "✅ **Товары в наличии:**\n\n"
            for item, count in sorted(available_items.items()):
                message_text += f"• {item}: {count} шт.\n"
        else:
            message_text = "❌ В магазине нет товаров в наличии"
        
        message_text += f"\n📊 Всего товаров в магазине: {len(stock)}\n"
        message_text += f"📦 Доступно для покупки: {len(available_items)}\n\n"
        message_text += "💡 Используйте /help для списка команд"
        
        bot.send_message(chat_id, message_text)
    else:
        bot.send_message(chat_id, "❌ Не удалось получить данные о магазине. Попробуйте позже.")

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
            "Используйте `/items` для просмотра всех товаров"
        )
        return
    
    item_name = args[1].strip()
    
    # Проверка на подписку на все товары
    if item_name == "*":
        if chat_id not in subscriptions:
            subscriptions[chat_id] = []
        
        if "*" in subscriptions[chat_id]:
            bot.send_message(chat_id, "ℹ️ Вы уже подписаны на ВСЕ товары")
        else:
            subscriptions[chat_id].append("*")
            # Удаляем другие подписки, так как подписка на всё их заменяет
            subscriptions[chat_id] = ["*"]
            bot.send_message(
                chat_id,
                "✅ Вы подписались на **ВСЕ товары**!\n\n"
                "Бот будет присылать уведомления о ЛЮБЫХ изменениях:\n"
                "• Появление товара\n"
                "• Изменение количества\n"
                "• Исчезновение товара\n\n"
                "Используйте `/unsubscribe *` для отписки"
            )
            
            # Запускаем мониторинг
            if chat_id not in monitoring_threads or not monitoring_threads[chat_id]:
                monitoring_threads[chat_id] = True
                thread = threading.Thread(target=monitor_shop, args=(chat_id,), daemon=True)
                thread.start()
        return
    
    # Обычная подписка
    stock = get_current_stock()
    if stock and item_name not in stock:
        # Показываем похожие товары для подсказки
        similar = [name for name in stock.keys() if item_name.lower() in name.lower()][:5]
        hint = f"\n\nВозможно, вы имели в виду:\n" + "\n".join([f"• {s}" for s in similar]) if similar else ""
        
        bot.send_message(
            chat_id,
            f"❌ Товар '{item_name}' не найден.{hint}\n\n"
            f"Используйте `/items` для просмотра всех {len(stock)} товаров"
        )
        return
    
    if chat_id not in subscriptions:
        subscriptions[chat_id] = []
    
    # Проверяем, не подписан ли уже
    if item_name in subscriptions[chat_id]:
        bot.send_message(chat_id, f"ℹ️ Вы уже подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id].append(item_name)
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на товар **{item_name}**\n\n"
            f"Бот будет присылать уведомления, когда:\n"
            f"• Товар появится в продаже\n"
            f"• Количество товара изменится\n"
            f"• Товар закончится\n\n"
            f"Текущее количество: {stock.get(item_name, 0)} шт."
        )
        
        # Запускаем поток мониторинга для этого чата, если его ещё нет
        if chat_id not in monitoring_threads or not monitoring_threads[chat_id]:
            monitoring_threads[chat_id] = True
            thread = threading.Thread(target=monitor_shop, args=(chat_id,), daemon=True)
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
    
    if chat_id not in subscriptions:
        subscriptions[chat_id] = []
    
    if item_name not in subscriptions[chat_id]:
        bot.send_message(chat_id, f"ℹ️ Вы не подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id].remove(item_name)
        bot.send_message(chat_id, f"✅ Вы отписались от товара **{item_name}**")
        
        # Если больше нет подписок, останавливаем мониторинг
        if not subscriptions[chat_id]:
            monitoring_threads[chat_id] = False
            bot.send_message(chat_id, "🔕 Мониторинг остановлен (нет активных подписок)")

@bot.message_handler(commands=['mysubs'])
def list_subscriptions(message):
    """Показать все подписки пользователя"""
    chat_id = message.chat.id
    
    if chat_id not in subscriptions or not subscriptions[chat_id]:
        bot.send_message(
            chat_id, 
            "📭 У вас нет активных подписок.\n\n"
            "Используйте:\n"
            "`/subscribe НазваниеТовара` - подписка на товар\n"
            "`/subscribe *` - подписка на все товары\n"
            "`/items` - список товаров"
        )
        return
    
    subs_list = []
    for item in subscriptions[chat_id]:
        if item == "*":
            subs_list.append("🌟 **ВСЕ ТОВАРЫ**")
        else:
            subs_list.append(f"• {item}")
    
    bot.send_message(
        chat_id,
        f"📋 **Ваши подписки:**\n\n" + "\n".join(subs_list) + "\n\n"
        f"➖ Чтобы отписаться: `/unsubscribe НазваниеТовара`\n"
        f"➖ Чтобы проверить магазин: `/check`"
    )

@bot.message_handler(commands=['check'])
def check_shop(message):
    """Проверить текущее состояние магазина"""
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔄 Получение данных о магазине...")
    
    stock = get_current_stock()
    if stock:
        # Показываем все товары с количеством
        message_text = "🏪 **Текущее состояние магазина:**\n\n"
        
        # Товары в наличии
        available = {k: v for k, v in stock.items() if v > 0}
        if available:
            message_text += "✅ **В наличии:**\n"
            for item, count in sorted(available.items()):
                message_text += f"  • {item}: {count} шт.\n"
        else:
            message_text += "❌ Нет товаров в наличии\n"
        
        # Товары которых нет
        unavailable = {k: v for k, v in stock.items() if v == 0}
        if unavailable:
            message_text += f"\n❌ **Отсутствуют ({len(unavailable)}):**\n"
            message_text += "  " + ", ".join(sorted(unavailable.keys())[:10])
            if len(unavailable) > 10:
                message_text += f" и {len(unavailable) - 10} других"
        
        bot.send_message(chat_id, message_text)
    else:
        bot.send_message(chat_id, "❌ Не удалось получить данные. Попробуйте позже.")

@bot.message_handler(commands=['items'])
def list_items(message):
    """Показать список всех доступных товаров"""
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔄 Загрузка списка товаров...")
    
    stock = get_current_stock()
    
    if stock:
        # Группируем по наличию
        available = [item for item, count in stock.items() if count > 0]
        unavailable = [item for item, count in stock.items() if count == 0]
        
        message_text = f"📋 **Доступные товары ({len(stock)}):**\n\n"
        
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
        
        message_text += "\n\n💡 Используйте:\n"
        message_text += "`/subscribe НазваниеТовара` - подписаться на товар\n"
        message_text += "`/subscribe *` - подписаться на ВСЕ товары"
        
        bot.send_message(chat_id, message_text)
    else:
        bot.send_message(chat_id, "❌ Не удалось получить список товаров")

@bot.message_handler(commands=['status'])
def monitoring_status(message):
    """Показать статус мониторинга"""
    chat_id = message.chat.id
    is_monitoring = monitoring_threads.get(chat_id, False)
    subs_count = len(subscriptions.get(chat_id, []))
    
    if is_monitoring:
        status = "🟢 **Активен**"
    else:
        status = "🔴 **Остановлен**"
    
    bot.send_message(
        chat_id,
        f"📊 **Статус мониторинга:**\n\n"
        f"Состояние: {status}\n"
        f"Активных подписок: {subs_count}\n"
        f"Частота проверки: каждые 15 секунд\n\n"
        f"• `/check` - проверить магазин\n"
        f"• `/mysubs` - мои подписки\n"
        f"• `/subscribe *` - подписаться на всё"
    )

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
🤖 **Magic Garden Shop Bot - Справка**

📌 **Основные команды:**

/start - Начало работы, показать доступные товары
/check - Проверить текущее состояние магазина
/status - Статус мониторинга

📌 **Подписки:**

/subscribe [товар] - Подписаться на товар
   Пример: `/subscribe Carrot`
   
/subscribe * - Подписаться на ВСЕ товары
   Будет присылать уведомления о ЛЮБЫХ изменениях

/unsubscribe [товар] - Отписаться от товара
/unsubscribe * - Отписаться от всех товаров

/mysubs - Показать все активные подписки
/items - Показать список всех товаров

📌 **Что отслеживается:**

✅ Появление товара в продаже
📈 Увеличение количества товара
📉 Уменьшение количества (кто-то купил)
⚠️ Исчезновение товара из продажи

⏱️ **Частота проверки:** каждые 15 секунд

💡 **Совет:** Подпишитесь на `*` чтобы видеть все изменения в магазине
"""
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# Запуск бота
if __name__ == "__main__":
    print("🤖 Бот запущен...")
    print(f"📡 WebSocket URI: {uri[:50]}...")
    print("✅ Готов к работе!")
    bot.polling(non_stop=True)