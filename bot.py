import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Optional
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import threading
import time
import websockets

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Замените на ваш токен

version = 310

async def get_data():
    global global_json_data
    global version
    #version = 310
    
    while True:
        uri = f"wss://magicgarden.gg/version/{version}/api/rooms/7TWG/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22p_KWTb7ix7rFYy9yhS%22&version=%22{version}%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"
        
        try:
            async with websockets.connect(uri, close_timeout=1) as websocket:
                # print(f"Пробуем версию {version}...")
                
                # Бесконечно получаем обновления
                while True:
                    if version > 400:
                        version = 310
                    try:
                        data = await asyncio.wait_for(websocket.recv(), timeout=1)
                        json_data = json.loads(data)
                        
                        # Обновляем глобальную переменную
                        if 'type' in json_data:
                            if (json_data['type'] == 'Welcome'):
                                global_json_data = json_data
                        
                        # print(f"Данные обновлены (версия {version}): {json_data}")
                        version = version - 1
                        return json_data
                    except asyncio.TimeoutError:
                        print(f"Таймаут ожидания данных (версия {version})")
                    except json.JSONDecodeError as e:
                        print(f"Ошибка декодирования JSON: {e}")
                        
        except websockets.exceptions.ConnectionClosedError as e:
            #print(f"Версия {version} не подходит или соединение закрыто: {e}")
            version += 1
        except asyncio.TimeoutError:
            #print(f"Таймаут подключения для версии {version}")
            version += 1
        except Exception as e:
            #print(f"Ошибка для версии {version}: {e}")
            version += 1

class ShopTrackerBot:
    def __init__(self, application: Application = None):
        self.global_json_data = None
        self.user_subscriptions: Dict[int, Dict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.application = application
        self.update_lock = threading.Lock()
        
    def set_application(self, application: Application):
        """Устанавливает экземпляр приложения для отправки сообщений"""
        self.application = application
        
    def update_data(self, new_data: dict):
        """Метод для обновления данных (вызывается извне)"""
        with self.update_lock:
            old_data = self.global_json_data
            self.global_json_data = new_data
            
            # Проверяем изменения в магазинах
            if old_data is not None:
                # Запускаем проверку в асинхронном режиме
                if self.application:
                    asyncio.create_task(self.check_shop_changes_async(old_data, new_data))
    
    def get_shop_inventory(self, data: dict, shop_type: str) -> Dict[str, int]:
        """Получает инвентарь магазина определенного типа"""
        inventory = {}
        try:
            shops = data.get('child', {}).get('data', {}).get('shops', {})
            shop_data = shops.get(shop_type, {})
            
            for item in shop_data.get('inventory', []):
                if shop_type == 'seed':
                    item_name = item.get('species')
                elif shop_type == 'tool':
                    item_name = item.get('toolId')
                elif shop_type == 'egg':
                    item_name = item.get('eggId')
                elif shop_type == 'decor':
                    item_name = item.get('decorId')
                else:
                    continue
                    
                if item_name:
                    inventory[item_name] = item.get('initialStock', 0)
        except Exception as e:
            logger.error(f"Error getting shop inventory: {e}")
            
        return inventory
    
    def get_available_items(self, data: dict, shop_type: str) -> Set[str]:
        """Возвращает товары, которые есть в наличии (stock > 0)"""
        inventory = self.get_shop_inventory(data, shop_type)
        return {item for item, stock in inventory.items() if stock > 0}
    
    async def check_shop_changes_async(self, old_data: dict, new_data: dict):
        """Асинхронная проверка изменений в магазинах"""
        shop_types = ['seed', 'tool', 'egg', 'decor']
        
        for shop_type in shop_types:
            old_available = self.get_available_items(old_data, shop_type)
            new_available = self.get_available_items(new_data, shop_type)
            
            # Находим новые товары
            new_items = new_available - old_available
            
            if new_items:
                logger.info(f"New items in {shop_type} shop: {new_items}")
                # Отправляем уведомления всем подписчикам
                await self.notify_all_subscribers(shop_type, new_items)
    
    async def notify_all_subscribers(self, shop_type: str, new_items: Set[str]):
        """Отправляет уведомления всем подписчикам"""
        if not self.application:
            logger.error("Application not set, cannot send notifications")
            return
            
        for user_id in list(self.user_subscriptions.keys()):
            await self.send_notification_to_user(user_id, shop_type, new_items)
    
    async def send_notification_to_user(self, user_id: int, shop_type: str, new_items: Set[str]):
        """Отправляет уведомление конкретному пользователю"""
        if user_id not in self.user_subscriptions:
            return
        
        subscriptions = self.user_subscriptions[user_id]
        items_to_notify = set()
        
        # Проверяем подписки
        if shop_type in subscriptions:
            if "*" in subscriptions[shop_type]:
                # Подписан на все
                items_to_notify = new_items
            else:
                # Подписан на конкретные товары
                items_to_notify = new_items.intersection(subscriptions[shop_type])
        
        if items_to_notify:
            message = f"🎉 **Новые товары в магазине!**\n\n"
            message += f"Категория: {self.get_category_name(shop_type)}\n"
            message += f"Появились в наличии:\n"
            for item in items_to_notify:
                message += f"  ✅ {item}\n"
            message += f"\nИспользуйте /shop, чтобы посмотреть магазин"
            
            try:
                await self.application.bot.send_message(
                    chat_id=user_id, 
                    text=message, 
                    parse_mode='Markdown'
                )
                logger.info(f"Sent notification to user {user_id} about {items_to_notify}")
            except Exception as e:
                logger.error(f"Failed to send notification to {user_id}: {e}")
    
    def get_category_name(self, category: str) -> str:
        """Получить русское название категории"""
        names = {
            'seed': 'Семена',
            'tool': 'Инструменты',
            'egg': 'Яйца',
            'decor': 'Декор'
        }
        return names.get(category, category)

# Инициализация трекера
shop_tracker = ShopTrackerBot()

# Функция для обновления данных (может вызываться из другого потока)
def update_game_data():
    """Внешняя функция для обновления данных"""
    shop_tracker.update_data(asyncio.run(get_data()))

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        f"Я бот для отслеживания товаров в магазине.\n\n"
        f"Доступные команды:\n"
        f"/shop - просмотр текущих товаров\n"
        f"/subscribe - подписаться на товары\n"
        f"/unsubscribe - отписаться от товаров\n"
        f"/mysubscriptions - мои подписки\n"
        f"/help - помощь"
    )

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие товары в магазине"""
    if shop_tracker.global_json_data is None:
        await update.message.reply_text("Данные магазина еще не загружены. Попробуйте позже.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🌱 Семена", callback_data="shop_seed")],
        [InlineKeyboardButton("🛠️ Инструменты", callback_data="shop_tool")],
        [InlineKeyboardButton("🥚 Яйца", callback_data="shop_egg")],
        [InlineKeyboardButton("🏠 Декор", callback_data="shop_decor")],
        [InlineKeyboardButton("📊 Все товары", callback_data="shop_all")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите категорию товаров:", 
        reply_markup=reply_markup
    )

async def show_shop_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать товары определенной категории"""
    query = update.callback_query
    await query.answer()
    
    category = query.data.replace("shop_", "")
    
    if shop_tracker.global_json_data is None:
        await query.edit_message_text("Данные магазина еще не загружены.")
        return
    
    if category == "all":
        message = "📦 **Все товары в магазине:**\n\n"
        for shop_type in ['seed', 'tool', 'egg', 'decor']:
            inventory = shop_tracker.get_shop_inventory(
                shop_tracker.global_json_data, shop_type
            )
            if inventory:
                shop_names = {
                    'seed': '🌱 Семена',
                    'tool': '🛠️ Инструменты',
                    'egg': '🥚 Яйца',
                    'decor': '🏠 Декор'
                }
                message += f"\n**{shop_names[shop_type]}:**\n"
                available = []
                unavailable = []
                for item, stock in inventory.items():
                    if stock > 0:
                        available.append(f"  ✅ {item}: {stock}")
                    else:
                        unavailable.append(f"  ❌ {item}: {stock}")
                
                if available:
                    message += "\n".join(available) + "\n"
                if unavailable and len(unavailable) <= 10:  # Показываем только если не слишком много
                    message += "\n".join(unavailable[:5]) + "\n"
                if len(unavailable) > 10:
                    message += f"  ... и {len(unavailable) - 5} других\n"
    else:
        shop_names = {
            'seed': '🌱 Семена',
            'tool': '🛠️ Инструменты',
            'egg': '🥚 Яйца',
            'decor': '🏠 Декор'
        }
        
        inventory = shop_tracker.get_shop_inventory(
            shop_tracker.global_json_data, category
        )
        
        if not inventory:
            await query.edit_message_text(f"Нет данных о {shop_names[category]}")
            return
        
        message = f"**{shop_names[category]}:**\n\n"
        available = []
        unavailable = []
        
        for item, stock in inventory.items():
            if stock > 0:
                available.append(f"✅ **{item}**: {stock} шт.")
            else:
                unavailable.append(f"❌ {item}: {stock} шт.")
        
        if available:
            message += "**В наличии:**\n" + "\n".join(available) + "\n\n"
        else:
            message += "❌ Нет товаров в наличии\n\n"
        
        if unavailable:
            message += "**Нет в наличии:**\n" + "\n".join(unavailable[:20])
            if len(unavailable) > 20:
                message += f"\n... и {len(unavailable) - 20} других"
        
        # Добавляем кнопку для подписки
        keyboard = [[
            InlineKeyboardButton("🔔 Подписаться на эту категорию", 
                               callback_data=f"sub_{category}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            message, 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    await query.edit_message_text(message, parse_mode='Markdown')

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписка на товары"""
    keyboard = [
        [InlineKeyboardButton("🌱 Семена", callback_data="sub_seed")],
        [InlineKeyboardButton("🛠️ Инструменты", callback_data="sub_tool")],
        [InlineKeyboardButton("🥚 Яйца", callback_data="sub_egg")],
        [InlineKeyboardButton("🏠 Декор", callback_data="sub_decor")],
        [InlineKeyboardButton("🔧 Выбрать конкретные товары", callback_data="sub_specific")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите категорию для подписки:\n"
        "Вы будете получать уведомления, когда появятся новые товары в наличии",
        reply_markup=reply_markup
    )

async def handle_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подписки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = query.data
    
    if action.startswith("sub_"):
        category = action.replace("sub_", "")
        
        if category == "specific":
            await show_item_selection(query, context)
            return
        
        # Подписка на всю категорию
        shop_tracker.user_subscriptions[user_id][category].add("*")
        
        await query.edit_message_text(
            f"✅ Вы подписались на категорию '{get_category_name(category)}'!\n"
            f"Вы будете получать уведомления о появлении новых товаров."
        )

async def show_item_selection(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать выбор конкретных товаров для подписки"""
    user_id = query.from_user.id
    
    keyboard = []
    categories = ['seed', 'tool', 'egg', 'decor']
    for category in categories:
        if shop_tracker.global_json_data:
            inventory = shop_tracker.get_shop_inventory(
                shop_tracker.global_json_data, category
            )
            if inventory:
                # Показываем только первые 10 товаров
                items = list(inventory.keys())[:10]
                for item in items:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_category_icon(category)} {item}",
                            callback_data=f"sub_item_{category}_{item}"
                        )
                    ])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_subscribe")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "Выберите конкретные товары для подписки:",
        reply_markup=reply_markup
    )

async def subscribe_to_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписка на конкретный товар"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    _, _, category, item = query.data.split("_", 3)
    
    shop_tracker.user_subscriptions[user_id][category].add(item)
    
    await query.edit_message_text(
        f"✅ Вы подписались на товар '{item}' в категории '{get_category_name(category)}'!\n"
        f"Вы получите уведомление, когда он появится в наличии."
    )

async def my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие подписки пользователя"""
    user_id = update.effective_user.id
    
    if user_id not in shop_tracker.user_subscriptions:
        await update.message.reply_text("У вас нет активных подписок.")
        return
    
    subscriptions = shop_tracker.user_subscriptions[user_id]
    message = "📋 **Ваши подписки:**\n\n"
    
    for category, items in subscriptions.items():
        category_name = get_category_name(category)
        message += f"**{category_name}:**\n"
        if "*" in items:
            message += "  • Все товары\n"
        else:
            for item in items:
                message += f"  • {item}\n"
        message += "\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отписка от товаров"""
    user_id = update.effective_user.id
    
    if user_id not in shop_tracker.user_subscriptions:
        await update.message.reply_text("У вас нет активных подписок.")
        return
    
    keyboard = []
    for category, items in shop_tracker.user_subscriptions[user_id].items():
        if "*" in items:
            keyboard.append([
                InlineKeyboardButton(
                    f"📛 Отписаться от {get_category_name(category)}",
                    callback_data=f"unsub_category_{category}"
                )
            ])
        else:
            for item in items:
                keyboard.append([
                    InlineKeyboardButton(
                        f"📛 {get_category_icon(category)} {item}",
                        callback_data=f"unsub_item_{category}_{item}"
                    )
                ])
    
    keyboard.append([InlineKeyboardButton("🔴 Отписаться от всего", callback_data="unsub_all")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите подписку для отмены:",
        reply_markup=reply_markup
    )

async def handle_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка отписки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = query.data
    
    if action == "unsub_all":
        shop_tracker.user_subscriptions[user_id].clear()
        await query.edit_message_text("✅ Вы отписались от всех уведомлений.")
        return
    
    parts = action.split("_")
    if len(parts) >= 3:
        if parts[1] == "category":
            category = parts[2]
            if category in shop_tracker.user_subscriptions[user_id]:
                del shop_tracker.user_subscriptions[user_id][category]
            await query.edit_message_text(f"✅ Вы отписались от категории '{get_category_name(category)}'.")
        elif parts[1] == "item":
            category = parts[2]
            item = "_".join(parts[3:])
            if category in shop_tracker.user_subscriptions[user_id]:
                shop_tracker.user_subscriptions[user_id][category].discard(item)
                if not shop_tracker.user_subscriptions[user_id][category]:
                    del shop_tracker.user_subscriptions[user_id][category]
            await query.edit_message_text(f"✅ Вы отписались от товара '{item}'.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    await update.message.reply_text(
        "📖 **Помощь по командам:**\n\n"
        "/start - Начать работу с ботом\n"
        "/shop - Просмотр товаров в магазине\n"
        "/subscribe - Подписаться на товары\n"
        "/unsubscribe - Отписаться от товаров\n"
        "/mysubscriptions - Мои подписки\n"
        "/help - Показать эту справку\n\n"
        "**Как это работает:**\n"
        "1. Бот отслеживает изменения в магазине\n"
        "2. Вы подписываетесь на нужные товары\n"
        "3. Когда товар появляется в наличии - бот пришлет уведомление",
        parse_mode='Markdown'
    )

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🛒 Показать магазин", callback_data="shop_main")],
        [InlineKeyboardButton("🔔 Подписаться", callback_data="sub_main")],
        [InlineKeyboardButton("📋 Мои подписки", callback_data="my_subs")],
        [InlineKeyboardButton("❌ Отписаться", callback_data="unsub_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🏠 **Главное меню**\n\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

def get_category_name(category: str) -> str:
    """Получить русское название категории"""
    names = {
        'seed': 'Семена',
        'tool': 'Инструменты',
        'egg': 'Яйца',
        'decor': 'Декор'
    }
    return names.get(category, category)

def get_category_icon(category: str) -> str:
    """Получить иконку категории"""
    icons = {
        'seed': '🌱',
        'tool': '🛠️',
        'egg': '🥚',
        'decor': '🏠'
    }
    return icons.get(category, '📦')

async def send_notifications(bot, user_id: int, shop_type: str, new_items: Set[str]):
    """Отправить уведомления пользователю"""
    if user_id not in shop_tracker.user_subscriptions:
        return
    
    subscriptions = shop_tracker.user_subscriptions[user_id]
    items_to_notify = set()
    
    # Проверяем подписки
    if shop_type in subscriptions:
        if "*" in subscriptions[shop_type]:
            # Подписан на все
            items_to_notify = new_items
        else:
            # Подписан на конкретные товары
            items_to_notify = new_items.intersection(subscriptions[shop_type])
    
    if items_to_notify:
        message = f"🎉 **Новые товары в магазине!**\n\n"
        message += f"Категория: {get_category_name(shop_type)}\n"
        message += f"Появились в наличии:\n"
        for item in items_to_notify:
            message += f"  ✅ {item}\n"
        message += f"\nИспользуйте /shop, чтобы посмотреть магазин"
        
        try:
            await bot.send_message(chat_id=user_id, text=message, parse_mode='Markdown')
            logger.info(f"Sent notification to user {user_id} about {items_to_notify}")
        except Exception as e:
            logger.error(f"Failed to send notification to {user_id}: {e}")

# Функция для периодической проверки (если данные обновляются не событийно)
async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка изменений (если нужно)"""
    # Здесь можно реализовать проверку, если данные обновляются не через update_data
    pass

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("mysubscriptions", my_subscriptions))
    application.add_handler(CommandHandler("help", help_command))
    
    # Регистрируем обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(show_shop_category, pattern="^shop_"))
    application.add_handler(CallbackQueryHandler(handle_subscription, pattern="^sub_"))
    application.add_handler(CallbackQueryHandler(subscribe_to_item, pattern="^sub_item_"))
    application.add_handler(CallbackQueryHandler(handle_unsubscribe, pattern="^unsub_"))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern="^back_to_start"))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern="^shop_main"))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern="^sub_main"))
    application.add_handler(CallbackQueryHandler(my_subscriptions, pattern="^my_subs"))
    application.add_handler(CallbackQueryHandler(unsubscribe, pattern="^unsub_main"))
    
    # Запускаем периодическую проверку (опционально)
    # job_queue = application.job_queue
    # job_queue.run_repeating(periodic_check, interval=5, first=1)
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# Функция для внешнего обновления данных с отправкой уведомлений
async def update_data_and_notify(new_data: dict, bot):
    """Обновляет данные и отправляет уведомления"""
    old_data = shop_tracker.global_json_data
    shop_tracker.global_json_data = new_data
    
    if old_data is not None:
        shop_types = ['seed', 'tool', 'egg', 'decor']
        for shop_type in shop_types:
            old_available = shop_tracker.get_available_items(old_data, shop_type)
            new_available = shop_tracker.get_available_items(new_data, shop_type)
            new_items = new_available - old_available
            
            if new_items:
                # Отправляем уведомления всем пользователям
                for user_id in shop_tracker.user_subscriptions:
                    await send_notifications(bot, user_id, shop_type, new_items)

if __name__ == "__main__":
    # Если нужно запустить с внешним циклом событий
    # main()
    
    # Или с возможностью обновления данных из другого потока
    import threading
    
    def data_updater():
        """Пример функции для имитации обновления данных"""
        import time
        import random
        
        while True:
            shop_tracker.update_data(asyncio.run(get_data()))
            # Здесь должна быть ваша логика получения данных
            # Например, из WebSocket, API или другого источника
            time.sleep(5)  # Проверка каждые 10 секунд
            # new_data = get_data_from_source()
            # shop_tracker.update_data(new_data)
    
    # Запускаем поток обновления данных
    updater_thread = threading.Thread(target=data_updater, daemon=True)
    updater_thread.start()
    
    main()