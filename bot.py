import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Optional
from collections import defaultdict
import threading
import websockets

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_BOT_TOKEN = "8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4"  # Замените на ваш токен


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
        # Структура: {user_id: {'seed': {'Carrot', 'Cabbage'}, 'tool': {'WateringCan'}, 'weather': {'weather'}}}
        
        self.application = application
        self.update_lock = threading.Lock()
        self.last_weather = None
        
    def set_application(self, application: Application):
        """Устанавливает экземпляр приложения для отправки сообщений"""
        self.application = application
        
    def update_data(self, new_data: dict):
        """Метод для обновления данных (вызывается извне)"""
        with self.update_lock:
            old_data = self.global_json_data
            self.global_json_data = new_data
            
            # Проверяем изменения в магазинах и погоде
            if old_data is not None:
                # Запускаем проверку в асинхронном режиме
                if self.application:
                    asyncio.create_task(self.check_all_changes_async(old_data, new_data))
    
    def get_shop_inventory(self, data: dict, shop_type: str) -> Dict[str, int]:
        """Получает инвентарь магазина определенного типа"""
        inventory = {}
        try:
            shops = data.get('fullState', {}).get('child', {}).get('data', {}).get('shops', {})
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
    
    def get_weather(self, data: dict) -> Optional[str]:
        """Получает текущую погоду"""
        try:
            weather = data.get('fullState', {}).get('child', {}).get('data', {}).get('weather')
            return weather
        except Exception as e:
            logger.error(f"Error getting weather: {e}")
            return None
    
    async def check_all_changes_async(self, old_data: dict, new_data: dict):
        """Асинхронная проверка всех изменений"""
        # Проверяем изменения в магазинах
        shop_types = ['seed', 'tool', 'egg', 'decor']
        for shop_type in shop_types:
            old_available = self.get_available_items(old_data, shop_type)
            new_available = self.get_available_items(new_data, shop_type)
            
            # Находим новые товары
            new_items = new_available - old_available
            # Находим товары, которые закончились
            removed_items = old_available - new_available
            
            if new_items:
                logger.info(f"New items in {shop_type} shop: {new_items}")
                await self.notify_all_subscribers(shop_type, new_items, is_new=True)
            
            if removed_items:
                logger.info(f"Items removed in {shop_type} shop: {removed_items}")
                await self.notify_all_subscribers(shop_type, removed_items, is_new=False)
        
        # Проверяем изменения погоды
        old_weather = self.get_weather(old_data)
        new_weather = self.get_weather(new_data)
        
        if old_weather != new_weather and new_weather is not None:
            logger.info(f"Weather changed: {old_weather} -> {new_weather}")
            await self.notify_weather_subscribers(old_weather, new_weather)
    
    async def notify_all_subscribers(self, shop_type: str, items: Set[str], is_new: bool = True):
        """Отправляет уведомления всем подписчикам о товарах"""
        if not self.application:
            logger.error("Application not set, cannot send notifications")
            return
            
        for user_id in list(self.user_subscriptions.keys()):
            await self.send_shop_notification_to_user(user_id, shop_type, items, is_new)
    
    async def send_shop_notification_to_user(self, user_id: int, shop_type: str, items: Set[str], is_new: bool = True):
        """Отправляет уведомление конкретному пользователю о товарах"""
        if user_id not in self.user_subscriptions:
            return
        
        subscriptions = self.user_subscriptions[user_id]
        items_to_notify = set()
        
        # Проверяем подписки
        if shop_type in subscriptions:
            if "*" in subscriptions[shop_type]:
                # Подписан на все товары в категории
                items_to_notify = items
            else:
                # Подписан на конкретные товары
                items_to_notify = items.intersection(subscriptions[shop_type])
        
        if items_to_notify:
            if is_new:
                status_emoji = "🎉"
                status_text = "появились в наличии"
            else:
                status_emoji = "😢"
                status_text = "закончились"
            
            message = f"{status_emoji} **Изменения в магазине!**\n\n"
            message += f"Категория: {self.get_category_name(shop_type)}\n"
            message += f"Товары которые {status_text}:\n"
            for item in items_to_notify:
                message += f"  {'✅' if is_new else '❌'} {item}\n"
            message += f"\nИспользуйте /shop, чтобы посмотреть актуальный магазин"
            
            try:
                await self.application.bot.send_message(
                    chat_id=user_id, 
                    text=message, 
                    parse_mode='Markdown'
                )
                logger.info(f"Sent shop notification to user {user_id} about {items_to_notify}")
            except Exception as e:
                logger.error(f"Failed to send notification to {user_id}: {e}")
    
    async def notify_weather_subscribers(self, old_weather: Optional[str], new_weather: str):
        """Отправляет уведомления подписчикам на погоду"""
        if not self.application:
            logger.error("Application not set, cannot send notifications")
            return
        
        
        message = f"🌤️ **Погода изменилась!**\n\n"
        
        for user_id, subscriptions in self.user_subscriptions.items():
            if 'weather' in subscriptions and ('*' in subscriptions['weather'] or 'weather' in subscriptions['weather']):
                try:
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    logger.info(f"Sent weather notification to user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to send weather notification to {user_id}: {e}")
    
    def get_category_name(self, category: str) -> str:
        """Получить русское название категории"""
        names = {
            'seed': '🌱 Семена',
            'tool': '🛠️ Инструменты',
            'egg': '🥚 Яйца',
            'decor': '🏠 Декор',
            'weather': '🌤️ Погода'
        }
        return names.get(category, category)

# Создаем глобальный экземпляр трекера
shop_tracker = ShopTrackerBot()

# Функция для внешнего обновления данных
def update_game_data(new_data: dict):
    shop_tracker.update_data(new_data)

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        f"Я бот для отслеживания товаров в магазине и погоды.\n\n"
        f"Доступные команды:\n"
        f"/shop - просмотр текущих товаров\n"
        f"/weather - текущая погода\n"
        f"/subscribe - подписаться на товары или погоду\n"
        f"/unsubscribe - отписаться от товаров или погоды\n"
        f"/mysubscriptions - мои подписки\n"
        f"/help - помощь"
    )

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущую погоду"""
    if shop_tracker.global_json_data is None:
        await update.message.reply_text("Данные о погоде еще не загружены. Попробуйте позже.")
        return
    
    current_weather = shop_tracker.get_weather(shop_tracker.global_json_data)
    
    if current_weather:
        
        message = f"**Текущая погода:** Необычная"
        
        keyboard = [[
            InlineKeyboardButton("🔔 Подписаться на погоду", callback_data="sub_weather")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.message.reply_text("Сейчас небо чистое")

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
                if unavailable:
                    message += "\n".join(unavailable) + "\n"
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
            message += "**Нет в наличии:**\n" + "\n".join(unavailable)
        
        # Добавляем кнопки для подписки на категорию или конкретные товары
        keyboard = [
            [InlineKeyboardButton("🔔 Подписаться на всю категорию", callback_data=f"sub_{category}")],
            [InlineKeyboardButton("🔧 Подписаться на конкретные товары", callback_data=f"sub_specific_{category}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            message, 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    await query.edit_message_text(message, parse_mode='Markdown')

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписка на товары или погоду"""
    keyboard = [
        [InlineKeyboardButton("🌱 Семена", callback_data="sub_seed")],
        [InlineKeyboardButton("🛠️ Инструменты", callback_data="sub_tool")],
        [InlineKeyboardButton("🥚 Яйца", callback_data="sub_egg")],
        [InlineKeyboardButton("🏠 Декор", callback_data="sub_decor")],
        [InlineKeyboardButton("🌤️ Погода", callback_data="sub_weather")],
        [InlineKeyboardButton("🔧 Выбрать конкретные товары", callback_data="sub_specific")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите категорию для подписки:\n"
        "Вы будете получать уведомления об изменениях",
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
        
        if category == "weather":
            # Подписка на погоду
            shop_tracker.user_subscriptions[user_id]['weather'].add('weather')
            await query.edit_message_text(
                f"✅ Вы подписались на уведомления о погоде!\n"
                f"Вы будете получать сообщения при изменении погоды."
            )
            return
        
        # Подписка на всю категорию товаров
        shop_tracker.user_subscriptions[user_id][category].add("*")
        
        await query.edit_message_text(
            f"✅ Вы подписались на категорию '{shop_tracker.get_category_name(category)}'!\n"
            f"Вы будете получать уведомления о появлении или исчезновении товаров."
        )

async def show_item_selection(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать выбор конкретных товаров для подписки"""
    keyboard = []
    categories = ['seed', 'tool', 'egg', 'decor']
    
    # Кнопки для выбора категории сначала
    for category in categories:
        keyboard.append([
            InlineKeyboardButton(
                f"📂 {shop_tracker.get_category_name(category)}",
                callback_data=f"show_items_{category}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_subscribe")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "Сначала выберите категорию, затем конкретные товары:",
        reply_markup=reply_markup
    )

async def show_category_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать товары выбранной категории для подписки"""
    query = update.callback_query
    await query.answer()
    
    category = query.data.replace("show_items_", "")
    
    if not shop_tracker.global_json_data:
        await query.edit_message_text("Данные еще не загружены.")
        return
    
    inventory = shop_tracker.get_shop_inventory(shop_tracker.global_json_data, category)
    
    if not inventory:
        await query.edit_message_text(f"Нет данных о товарах в категории {shop_tracker.get_category_name(category)}")
        return
    
    keyboard = []
    # Показываем все товары с возможностью подписки на каждый
    for item in sorted(inventory.keys())[:]:  # Ограничиваем 30 товарами
        keyboard.append([
            InlineKeyboardButton(
                f"🔔 {item}",
                callback_data=f"sub_item_{category}_{item}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад к выбору категории", callback_data="sub_specific")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Выберите товары в категории {shop_tracker.get_category_name(category)} для подписки:",
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
        f"✅ Вы подписались на товар '{item}' в категории '{shop_tracker.get_category_name(category)}'!\n"
        f"Вы получите уведомление, когда он появится или исчезнет из магазина."
    )

async def my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие подписки пользователя"""
    user_id = update.effective_user.id
    
    if user_id not in shop_tracker.user_subscriptions or not shop_tracker.user_subscriptions[user_id]:
        await update.message.reply_text("У вас нет активных подписок.")
        return
    
    subscriptions = shop_tracker.user_subscriptions[user_id]
    message = "📋 **Ваши подписки:**\n\n"
    
    for category, items in subscriptions.items():
        category_name = shop_tracker.get_category_name(category)
        if category == 'weather':
            message += f"**{category_name}:**\n"
            message += "  • Изменения погоды\n\n"
        else:
            message += f"**{category_name}:**\n"
            if "*" in items:
                message += "  • Все товары в категории\n"
            else:
                for item in items:
                    message += f"  • {item}\n"
            message += "\n"
    
    # Добавляем кнопку для быстрой отписки
    keyboard = [[InlineKeyboardButton("❌ Отписаться", callback_data="unsub_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отписка от товаров или погоды"""
    user_id = update.effective_user.id
    
    if user_id not in shop_tracker.user_subscriptions or not shop_tracker.user_subscriptions[user_id]:
        await update.message.reply_text("У вас нет активных подписок.")
        return
    
    keyboard = []
    
    for category, items in shop_tracker.user_subscriptions[user_id].items():
        if category == 'weather':
            keyboard.append([
                InlineKeyboardButton(
                    f"📛 Отписаться от погоды",
                    callback_data=f"unsub_weather"
                )
            ])
        else:
            if "*" in items:
                keyboard.append([
                    InlineKeyboardButton(
                        f"📛 Отписаться от {shop_tracker.get_category_name(category)} (все)",
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
    
    if action == "unsub_weather":
        if 'weather' in shop_tracker.user_subscriptions[user_id]:
            del shop_tracker.user_subscriptions[user_id]['weather']
        await query.edit_message_text("✅ Вы отписались от уведомлений о погоде.")
        return
    
    parts = action.split("_")
    if len(parts) >= 3:
        if parts[1] == "category":
            category = parts[2]
            if category in shop_tracker.user_subscriptions[user_id]:
                del shop_tracker.user_subscriptions[user_id][category]
            await query.edit_message_text(f"✅ Вы отписались от категории '{shop_tracker.get_category_name(category)}'.")
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
        "/weather - Текущая погода\n"
        "/subscribe - Подписаться на товары или погоду\n"
        "/unsubscribe - Отписаться от товаров или погоды\n"
        "/mysubscriptions - Мои подписки\n"
        "/help - Показать эту справку\n\n"
        "**Как это работает:**\n"
        "1. Бот отслеживает изменения в магазине и погоде\n"
        "2. Вы подписываетесь на нужные товары или погоду\n"
        "3. Когда товар появляется/исчезает или меняется погода - бот пришлет уведомление",
        parse_mode='Markdown'
    )

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🛒 Показать магазин", callback_data="shop_main")],
        [InlineKeyboardButton("🌤️ Погода", callback_data="weather_main")],
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

async def back_to_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору категории для подписки"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🌱 Семена", callback_data="sub_seed")],
        [InlineKeyboardButton("🛠️ Инструменты", callback_data="sub_tool")],
        [InlineKeyboardButton("🥚 Яйца", callback_data="sub_egg")],
        [InlineKeyboardButton("🏠 Декор", callback_data="sub_decor")],
        [InlineKeyboardButton("🌤️ Погода", callback_data="sub_weather")],
        [InlineKeyboardButton("🔧 Выбрать конкретные товары", callback_data="sub_specific")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "Выберите категорию для подписки:",
        reply_markup=reply_markup
    )

async def my_subs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для показа подписок"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in shop_tracker.user_subscriptions or not shop_tracker.user_subscriptions[user_id]:
        await query.edit_message_text("У вас нет активных подписок.")
        return
    
    subscriptions = shop_tracker.user_subscriptions[user_id]
    message = "📋 **Ваши подписки:**\n\n"
    
    for category, items in subscriptions.items():
        category_name = shop_tracker.get_category_name(category)
        if category == 'weather':
            message += f"**{category_name}:**\n"
            message += "  • Изменения погоды\n\n"
        else:
            message += f"**{category_name}:**\n"
            if "*" in items:
                message += "  • Все товары в категории\n"
            else:
                for item in items:
                    message += f"  • {item}\n"
            message += "\n"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)

async def weather_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для показа погоды"""
    query = update.callback_query
    await query.answer()
    
    if shop_tracker.global_json_data is None:
        await query.edit_message_text("Данные о погоде еще не загружены.")
        return
    
    current_weather = shop_tracker.get_weather(shop_tracker.global_json_data)
    
    if current_weather:
        
        message = f"**Текущая погода:** Необычная"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await query.edit_message_text("Сейчас небо чистое")

def get_category_icon(category: str) -> str:
    """Получить иконку категории"""
    icons = {
        'seed': '🌱',
        'tool': '🛠️',
        'egg': '🥚',
        'decor': '🏠',
        'weather': '🌤️'
    }
    return icons.get(category, '📦')

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Устанавливаем приложение в трекер
    shop_tracker.set_application(application)
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("weather", weather))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("mysubscriptions", my_subscriptions))
    application.add_handler(CommandHandler("help", help_command))
    
    # Регистрируем обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(show_shop_category, pattern="^shop_"))
    application.add_handler(CallbackQueryHandler(handle_subscription, pattern="^sub_"))
    application.add_handler(CallbackQueryHandler(show_category_items, pattern="^show_items_"))
    application.add_handler(CallbackQueryHandler(subscribe_to_item, pattern="^sub_item_"))
    application.add_handler(CallbackQueryHandler(handle_unsubscribe, pattern="^unsub_"))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern="^back_to_start$"))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern="^shop_main$"))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern="^sub_main$"))
    application.add_handler(CallbackQueryHandler(my_subs_callback, pattern="^my_subs$"))
    application.add_handler(CallbackQueryHandler(unsubscribe, pattern="^unsub_main$"))
    application.add_handler(CallbackQueryHandler(back_to_subscribe, pattern="^back_to_subscribe$"))
    application.add_handler(CallbackQueryHandler(weather_callback, pattern="^weather_main$"))
    
    # Запускаем бота
    print("Бот запущен...")
    print("Доступные команды: /start, /shop, /weather, /subscribe, /unsubscribe, /mysubscriptions, /help")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import threading
    
    def data_updater():
        import time
        
        while True:
            update_game_data(asyncio.run(get_data()))
            time.sleep(5)
    
    # Запускаем поток обновления данных
    updater_thread = threading.Thread(target=data_updater, daemon=True)
    updater_thread.start()
    
    main()