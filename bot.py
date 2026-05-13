import telebot
import websockets
import json
import asyncio
import threading
import time

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
    for item, count in stock_dict.items():
        if count > 0:
            message += f"✅ {item} - {count}\n"
        else:
            message += f"❌ {item} - {count}\n"
    return message

def monitor_shop(chat_id):
    """Функция для мониторинга магазина в отдельном потоке"""
    global last_stock_state
    
    # Инициализируем последнее состояние для этого чата
    if chat_id not in last_stock_state:
        last_stock_state[chat_id] = {}
    
    while monitoring_threads.get(chat_id, False):
        current_stock = get_current_stock()
        
        if current_stock:
            # Проверяем подписки пользователя
            user_subs = subscriptions.get(chat_id, [])
            
            for item in user_subs:
                old_count = last_stock_state[chat_id].get(item, 0)
                new_count = current_stock.get(item, 0)
                
                # Если товара не было, а теперь появился (количество > 0)
                if old_count == 0 and new_count > 0:
                    bot.send_message(
                        chat_id,
                        f"🎉 **{item}** появился в продаже!\nКоличество: {new_count}\nСпешите купить!"
                    )
                # Если количество увеличилось с 0 до чего-то (альтернативная проверка)
                elif new_count > 0 and old_count == 0:
                    bot.send_message(
                        chat_id,
                        f"🎉 **{item}** теперь доступен для покупки!\nКоличество: {new_count}"
                    )
            
            # Обновляем последнее состояние
            last_stock_state[chat_id] = current_stock.copy()
        
        # Проверяем каждые 30 секунд
        time.sleep(30)

@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    stock = get_current_stock()
    
    if stock:
        bot.send_message(chat_id, format_stock_message(stock))
    else:
        bot.send_message(chat_id, "❌ Не удалось получить данные о магазине. Попробуйте позже.")

@bot.message_handler(commands=['subscribe'])
def subscribe_command(message):
    """Подписка на товар: /subscribe Carrot"""
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(
            chat_id,
            "❌ Укажите название товара.\nПример: `/subscribe Carrot`\n\n📋 Доступные товары:\n" +
            "\n".join(get_item_list()[:20])
        )
        return
    
    item_name = args[1].strip()
    
    # Получаем список всех доступных товаров
    stock = get_current_stock()
    if stock and item_name not in stock:
        bot.send_message(
            chat_id,
            f"❌ Товар '{item_name}' не найден.\n\nДоступные товары:\n" +
            "\n".join(list(stock.keys())[:30])
        )
        return
    
    # Добавляем подписку
    if chat_id not in subscriptions:
        subscriptions[chat_id] = []
    
    if item_name in subscriptions[chat_id]:
        bot.send_message(chat_id, f"ℹ️ Вы уже подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id].append(item_name)
        bot.send_message(
            chat_id,
            f"✅ Вы подписались на товар **{item_name}**\n"
            f"Бот пришлёт уведомление, когда он появится в продаже."
        )
        
        # Запускаем поток мониторинга для этого чата, если его ещё нет
        if chat_id not in monitoring_threads or not monitoring_threads[chat_id]:
            monitoring_threads[chat_id] = True
            thread = threading.Thread(target=monitor_shop, args=(chat_id,), daemon=True)
            thread.start()

@bot.message_handler(commands=['unsubscribe'])
def unsubscribe_command(message):
    """Отписка от товара: /unsubscribe Carrot"""
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(
            chat_id,
            "❌ Укажите название товара.\nПример: `/unsubscribe Carrot`"
        )
        return
    
    item_name = args[1].strip()
    
    if chat_id not in subscriptions or item_name not in subscriptions[chat_id]:
        bot.send_message(chat_id, f"ℹ️ Вы не подписаны на товар **{item_name}**")
    else:
        subscriptions[chat_id].remove(item_name)
        bot.send_message(chat_id, f"✅ Вы отписались от товара **{item_name}**")
        
        # Если больше нет подписок, можно остановить мониторинг
        if not subscriptions[chat_id]:
            monitoring_threads[chat_id] = False

@bot.message_handler(commands=['mysubs'])
def list_subscriptions(message):
    """Показать все подписки пользователя"""
    chat_id = message.chat.id
    
    if chat_id not in subscriptions or not subscriptions[chat_id]:
        bot.send_message(chat_id, "📭 У вас нет активных подписок.\nИспользуйте `/subscribe НазваниеТовара`")
    else:
        subs_list = "\n".join([f"• {item}" for item in subscriptions[chat_id]])
        bot.send_message(
            chat_id,
            f"📋 **Ваши подписки:**\n\n{subs_list}\n\n"
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
        bot.send_message(chat_id, format_stock_message(stock))
    else:
        bot.send_message(chat_id, "❌ Не удалось получить данные. Попробуйте позже.")

@bot.message_handler(commands=['items'])
def list_items(message):
    """Показать список всех доступных товаров"""
    chat_id = message.chat.id
    stock = get_current_stock()
    
    if stock:
        items_list = "\n".join([f"• {item}" for item in sorted(stock.keys())])
        bot.send_message(
            chat_id,
            f"📋 **Доступные товары для подписки:**\n\n{items_list}\n\n"
            f"💡 Используйте: `/subscribe НазваниеТовара`"
        )
    else:
        bot.send_message(chat_id, "❌ Не удалось получить список товаров")

def get_item_list():
    """Возвращает список доступных товаров для подсказки"""
    stock = get_current_stock()
    return list(stock.keys()) if stock else []

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
🤖 **Доступные команды:**

/start - Показать текущее состояние магазина
/check - Проверить магазин (обновлённые данные)
/subscribe [товар] - Подписаться на появление товара
/unsubscribe [товар] - Отписаться от товара
/mysubs - Показать ваши подписки
/items - Показать список всех доступных товаров
/help - Показать эту справку

📝 **Пример:**
`/subscribe Carrot` - бот пришлёт уведомление, когда морковь появится в продаже

⚠️ Бот проверяет магазин каждые 30 секунд
"""
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# Запуск бота
if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(non_stop=True)