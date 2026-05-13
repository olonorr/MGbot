import asyncio
import websockets
import json
import logging
from datetime import datetime
from typing import Dict, Set, List, Optional
from dataclasses import dataclass
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = "8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4"  # Замените на ваш токен
ROOM_CODE = "7TWG"
PLAYER_ID = "p_KWTb7ix7rFYy9yhS"  # Ваш ID игрока

# Хранилище подписок
class SubscriptionType(Enum):
    SEED = "seed"
    TOOL = "tool"
    EGG = "egg"
    DECOR = "decor"
    WEATHER = "weather"

@dataclass
class Subscription:
    user_id: int
    shop_type: SubscriptionType
    item_id: Optional[str] = None  # Для товаров - ID, для погоды None
    item_name: Optional[str] = None

class ShopNotifier:
    def __init__(self):
        self.subscriptions: Dict[int, Set[Subscription]] = {}  # user_id -> set of subscriptions
        self.last_shop_state: Dict[str, Dict] = {}  # shop_type -> {item_id: stock}
        self.last_weather = None
        
    def add_subscription(self, user_id: int, shop_type: SubscriptionType, item_id: str = None, item_name: str = None):
        if user_id not in self.subscriptions:
            self.subscriptions[user_id] = set()
        self.subscriptions[user_id].add(Subscription(user_id, shop_type, item_id, item_name))
        
    def remove_subscription(self, user_id: int, shop_type: SubscriptionType, item_id: str = None):
        if user_id in self.subscriptions:
            to_remove = [s for s in self.subscriptions[user_id] 
                        if s.shop_type == shop_type and (item_id is None or s.item_id == item_id)]
            for sub in to_remove:
                self.subscriptions[user_id].discard(sub)
                
    def get_user_subscriptions(self, user_id: int) -> List[Subscription]:
        return list(self.subscriptions.get(user_id, set()))
    
    async def check_for_updates(self, context: ContextTypes.DEFAULT_TYPE, game_data: dict):
        """Проверяет обновления в магазинах и погоде"""
        if not game_data or 'child' not in game_data or 'data' not in game_data['child']:
            return
            
        shops_data = game_data['child']['data'].get('shops', {})
        weather = game_data['child']['data'].get('weather')
        
        # Проверка погоды
        if weather != self.last_weather:
            if weather is not None:
                await self.notify_weather_change(context, weather)
            self.last_weather = weather
            
        # Проверка магазинов
        for shop_type in [SubscriptionType.SEED, SubscriptionType.TOOL, 
                         SubscriptionType.EGG, SubscriptionType.DECOR]:
            if shop_type.value in shops_data:
                await self.check_shop_updates(context, shop_type, shops_data[shop_type.value])
    
    async def check_shop_updates(self, context: ContextTypes.DEFAULT_TYPE, 
                                 shop_type: SubscriptionType, shop_data: dict):
        """Проверяет обновления в конкретном магазине"""
        current_state = {}
        notifications = []
        
        for item in shop_data.get('inventory', []):
            item_id = item.get('species') or item.get('toolId') or item.get('eggId') or item.get('decorId')
            stock = item.get('initialStock', 0)
            current_state[item_id] = stock
            
            # Проверяем, был ли товар в наличии раньше
            old_state = self.last_shop_state.get(f"{shop_type.value}_{item_id}", 0)
            if old_state == 0 and stock > 0:
                # Товар появился в наличии
                notifications.append((shop_type, item_id, stock))
                
        self.last_shop_state.update({f"{shop_type.value}_{k}": v for k, v in current_state.items()})
        
        # Отправляем уведомления
        for shop_type_notif, item_id, stock in notifications:
            await self.notify_item_available(context, shop_type_notif, item_id, stock)
    
    async def notify_item_available(self, context: ContextTypes.DEFAULT_TYPE, 
                                    shop_type: SubscriptionType, item_id: str, stock: int):
        """Уведомляет пользователей о появлении товара"""
        shop_names = {
            SubscriptionType.SEED: "🌱 Семена",
            SubscriptionType.TOOL: "🔧 Инструменты",
            SubscriptionType.EGG: "🥚 Яйца",
            SubscriptionType.DECOR: "🎨 Декор"
        }
        
        item_display = ''.join([' ' + char if char.isupper() else char for char in item_id]).strip()
        message = f"✨ {shop_names[shop_type]} ✨\n\nТовар появился в наличии!\n📦 {item_display}\n📊 В наличии: {stock} шт."
        
        for user_id, subs in self.subscriptions.items():
            for sub in subs:
                if sub.shop_type == shop_type and (sub.item_id is None or sub.item_id == item_id):
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
    
    async def notify_weather_change(self, context: ContextTypes.DEFAULT_TYPE, weather_data):
        """Уведомляет о смене погоды"""
        message = f"🌤️ <b>Погода изменилась!</b> 🌤️\n\n{json.dumps(weather_data, indent=2, ensure_ascii=False)}"
        
        for user_id, subs in self.subscriptions.items():
            for sub in subs:
                if sub.shop_type == SubscriptionType.WEATHER:
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

# Глобальный экземпляр уведомителя
notifier = ShopNotifier()

async def listen_and_notify(context: ContextTypes.DEFAULT_TYPE):
    """Подключается к WebSocket и обрабатывает данные"""
    versions_to_try = ["312", "313", "314", "315"]
    
    for version in versions_to_try:
        uri = f"wss://magicgarden.gg/version/{version}/api/rooms/7TWG/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22p_KWTb7ix7rFYy9yhS%22&version=%22{version}%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"
        
        try:
            async with websockets.connect(uri, close_timeout=3) as websocket:
                print(f"Подключено с версией {version}")
                logger.info(f"Подключено с версией {version}")
                
                while True:
                    try:
                        data = await asyncio.wait_for(websocket.recv(), timeout=30)
                        json_data = json.loads(data)
                        
                        # Проверяем обновления
                        await notifier.check_for_updates(context, json_data)
                        
                    except asyncio.TimeoutError:
                        print("Ожидание данных...")
                        logger.info("Ожидание данных...")
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        print("Соединение закрыто, переподключение...")
                        logger.warning("Соединение закрыто, переподключение...")
                        break
                    except Exception as e:
                        print(f"Ошибка обработки: {e}")
                        logger.error(f"Ошибка обработки: {e}")
                        
        except Exception as e:
            print(f"Ошибка с версией {version}: {e}")
            logger.error(f"Ошибка с версией {version}: {e}")
            continue

async def game_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    """Job для мониторинга игры"""
    await listen_and_notify(context)

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение"""
    welcome_text = """
🌿 <b>Magic Garden Shop Monitor Bot</b> 🌿

Я слежу за магазинами и погодой в игре Magic Garden!

<b>Доступные команды:</b>
/subscribe_seed - Подписаться на семена
/subscribe_tool - Подписаться на инструменты  
/subscribe_egg - Подписаться на яйца
/subscribe_decor - Подписаться на декор
/subscribe_weather - Подписаться на погоду

/unsubscribe - Отписаться от категории
/my_subscriptions - Мои подписки

При появлении товара или смене погоды я пришлю уведомление!
"""
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def show_shop_items(update: Update, context: ContextTypes.DEFAULT_TYPE, shop_type: SubscriptionType, shop_name: str):
    """Показывает доступные товары в магазине для подписки"""
    # Здесь нужно получить актуальный список товаров из последних данных
    # Для демонстрации используем примерные данные
    items = {
        SubscriptionType.SEED: ["Carrot", "Cabbage", "Strawberry", "Aloe", "Beet", "Tomato", "Pumpkin"],
        SubscriptionType.TOOL: ["WateringCan", "PlanterPot", "CropCleanser", "Shovel"],
        SubscriptionType.EGG: ["CommonEgg", "UncommonEgg", "RareEgg"],
        SubscriptionType.DECOR: ["SmallRock", "MediumRock", "WoodBench", "StoneBench"]
    }
    
    keyboard = []
    for item in items.get(shop_type, []):
        keyboard.append([InlineKeyboardButton(item, callback_data=f"sub_{shop_type.value}_{item}")])
    keyboard.append([InlineKeyboardButton("🔔 Подписаться на все", callback_data=f"sub_{shop_type.value}_all")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Выберите товар в категории <b>{shop_name}</b>:", 
                                   parse_mode='HTML', reply_markup=reply_markup)

async def subscribe_seed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_shop_items(update, context, SubscriptionType.SEED, "Семена")

async def subscribe_tool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_shop_items(update, context, SubscriptionType.TOOL, "Инструменты")

async def subscribe_egg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_shop_items(update, context, SubscriptionType.EGG, "Яйца")

async def subscribe_decor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_shop_items(update, context, SubscriptionType.DECOR, "Декор")

async def subscribe_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписка на погоду"""
    user_id = update.effective_user.id
    notifier.add_subscription(user_id, SubscriptionType.WEATHER)
    await update.message.reply_text("🌤️ Вы подписались на уведомления о погоде!")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка callback кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "back_to_menu":
        await query.edit_message_text(
            "Выберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌱 Семена", callback_data="menu_seed")],
                [InlineKeyboardButton("🔧 Инструменты", callback_data="menu_tool")],
                [InlineKeyboardButton("🥚 Яйца", callback_data="menu_egg")],
                [InlineKeyboardButton("🎨 Декор", callback_data="menu_decor")],
                [InlineKeyboardButton("🌤️ Погода", callback_data="menu_weather")],
                [InlineKeyboardButton("📋 Мои подписки", callback_data="menu_my_subs")]
            ])
        )
    elif data.startswith("sub_"):
        parts = data.split("_")
        shop_type_str = parts[1]
        item_id = "_".join(parts[2:]) if len(parts) > 2 else None
        
        shop_type = {
            "seed": SubscriptionType.SEED,
            "tool": SubscriptionType.TOOL,
            "egg": SubscriptionType.EGG,
            "decor": SubscriptionType.DECOR
        }.get(shop_type_str)
        
        if shop_type:
            if item_id == "all":
                notifier.add_subscription(user_id, shop_type)
                await query.edit_message_text(f"✅ Вы подписались на все товары в категории {shop_type_str}!")
            else:
                notifier.add_subscription(user_id, shop_type, item_id)
                await query.edit_message_text(f"✅ Вы подписались на товар {item_id}!")
    
    elif data.startswith("menu_"):
        action = data[5:]
        if action == "seed":
            await show_shop_items_from_callback(query, SubscriptionType.SEED, "Семена")
        elif action == "tool":
            await show_shop_items_from_callback(query, SubscriptionType.TOOL, "Инструменты")
        elif action == "egg":
            await show_shop_items_from_callback(query, SubscriptionType.EGG, "Яйца")
        elif action == "decor":
            await show_shop_items_from_callback(query, SubscriptionType.DECOR, "Декор")
        elif action == "weather":
            notifier.add_subscription(user_id, SubscriptionType.WEATHER)
            await query.edit_message_text("🌤️ Вы подписались на уведомления о погоде!")
        elif action == "my_subs":
            await show_user_subscriptions(query, user_id)

async def show_shop_items_from_callback(query, shop_type: SubscriptionType, shop_name: str):
    """Показывает товары из callback"""
    items = {
        SubscriptionType.SEED: ["Carrot", "Cabbage", "Strawberry", "Aloe", "Beet", "Tomato", "Pumpkin"],
        SubscriptionType.TOOL: ["WateringCan", "PlanterPot", "CropCleanser", "Shovel"],
        SubscriptionType.EGG: ["CommonEgg", "UncommonEgg", "RareEgg"],
        SubscriptionType.DECOR: ["SmallRock", "MediumRock", "WoodBench", "StoneBench"]
    }
    
    keyboard = []
    for item in items.get(shop_type, []):
        keyboard.append([InlineKeyboardButton(item, callback_data=f"sub_{shop_type.value}_{item}")])
    keyboard.append([InlineKeyboardButton("🔔 Подписаться на все", callback_data=f"sub_{shop_type.value}_all")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"Выберите товар в категории <b>{shop_name}</b>:", 
                                 parse_mode='HTML', reply_markup=reply_markup)

async def show_user_subscriptions(query, user_id: int):
    """Показывает текущие подписки пользователя"""
    subs = notifier.get_user_subscriptions(user_id)
    
    if not subs:
        text = "У вас нет активных подписок."
    else:
        text = "📋 <b>Ваши подписки:</b>\n\n"
        for sub in subs:
            if sub.shop_type == SubscriptionType.WEATHER:
                text += "🌤️ Погода\n"
            else:
                item_display = sub.item_id if sub.item_id else "все товары"
                text += f"• {sub.shop_type.value}: {item_display}\n"
        text += "\nДля отписки используйте /unsubscribe"
    
    await query.edit_message_text(text, parse_mode='HTML')

async def unsubscribe_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню отписки"""
    user_id = update.effective_user.id
    subs = notifier.get_user_subscriptions(user_id)
    
    if not subs:
        await update.message.reply_text("У вас нет активных подписок.")
        return
    
    keyboard = []
    for sub in subs:
        if sub.shop_type == SubscriptionType.WEATHER:
            name = "🌤️ Погода"
        else:
            name = f"{sub.shop_type.value}: {sub.item_id if sub.item_id else 'все'}"
        keyboard.append([InlineKeyboardButton(name, callback_data=f"unsub_{sub.shop_type.value}_{sub.item_id or 'all'}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите подписку для отмены:", reply_markup=reply_markup)

async def my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подписки пользователя"""
    user_id = update.effective_user.id
    subs = notifier.get_user_subscriptions(user_id)
    
    if not subs:
        text = "У вас нет активных подписок."
    else:
        text = "📋 <b>Ваши подписки:</b>\n\n"
        for sub in subs:
            if sub.shop_type == SubscriptionType.WEATHER:
                text += "🌤️ Погода\n"
            else:
                item_display = sub.item_id if sub.item_id else "все товары"
                text += f"• {sub.shop_type.value}: {item_display}\n"
    
    await update.message.reply_text(text, parse_mode='HTML')

def main():
    """Запуск бота"""
    # Создание приложения
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавление обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe_seed", subscribe_seed))
    application.add_handler(CommandHandler("subscribe_tool", subscribe_tool))
    application.add_handler(CommandHandler("subscribe_egg", subscribe_egg))
    application.add_handler(CommandHandler("subscribe_decor", subscribe_decor))
    application.add_handler(CommandHandler("subscribe_weather", subscribe_weather))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_menu))
    application.add_handler(CommandHandler("my_subscriptions", my_subscriptions))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Добавление задачи мониторинга (каждые 10 секунд)
    job_queue = application.job_queue
    job_queue.run_repeating(game_monitor_job, interval=10, first=1)
    
    # Запуск бота
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()