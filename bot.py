import asyncio
import websockets
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import time

# Токен вашего бота (замените на свой)
BOT_TOKEN = "8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4"

# Параметры подключения к WebSocket
ROOM_ID = "7TWG"
PLAYER_ID = "p_KWTb7ix7rFYy9yhS"

# Глобальная переменная для хранения рабочей версии
current_version = None
version_found = False

async def test_version(version):
    """Тестирование конкретной версии"""
    version_str = str(version)
    uri = f"wss://magicgarden.gg/version/{version_str}/api/rooms/{ROOM_ID}/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22{PLAYER_ID}%22&version=%22{version_str}%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"
    
    try:
        async with websockets.connect(uri, close_timeout=2) as websocket:
            print(f"🔄 Пробуем версию {version_str}...")
            data = await asyncio.wait_for(websocket.recv(), timeout=3)
            json_data = json.loads(data)
            
            # Проверяем, что данные содержат информацию о магазинах
            if json_data and "child" in json_data and "data" in json_data["child"]:
                print(f"✅ Найдена рабочая версия: {version_str}")
                return version_str
            else:
                print(f"⚠️ Версия {version_str} не содержит данных магазина")
                return None
                
    except websockets.exceptions.ConnectionClosedError:
        print(f"❌ Версия {version_str} - соединение закрыто")
        return None
    except asyncio.TimeoutError:
        print(f"⏰ Таймаут для версии {version_str}")
        return None
    except Exception as e:
        print(f"❌ Версия {version_str} ошибка: {str(e)[:50]}")
        return None

async def find_working_version_async(update=None):
    """Асинхронный поиск рабочей версии"""
    global current_version, version_found
    
    # Если уже нашли версию, просто возвращаем её
    if current_version is not None:
        return current_version
    
    version = 310
    
    # Отправляем сообщение о начале поиска, если есть update
    if update:
        await update.message.reply_text("🔍 Поиск рабочей версии... Это может занять некоторое время.")
    
    # Пробуем версии с 310 по 330 сначала (ограничим диапазон для скорости)
    for version in range(310, 331):
        working_version = await test_version(version)
        if working_version:
            current_version = working_version
            version_found = True
            if update:
                await update.message.reply_text(f"✅ Найдена рабочая версия: {current_version}\n🔄 Получаю данные...")
            return current_version
    
    # Если не нашли в диапазоне 310-330, продолжаем дальше но с большим интервалом
    version = 331
    while True:
        working_version = await test_version(version)
        if working_version:
            current_version = working_version
            version_found = True
            if update:
                await update.message.reply_text(f"✅ Найдена рабочая версия: {current_version}\n🔄 Получаю данные...")
            return current_version
        version += 1
        await asyncio.sleep(0.3)  # Небольшая задержка
        
        # Ограничим поиск для теста (можно убрать или увеличить)
        if version > 350:  # Временно ограничим поиск 350 версией для теста
            print("⚠️ Достигнут лимит поиска версий")
            return None

async def get_shop_data(update=None):
    """Получение данных магазина через WebSocket с использованием рабочей версии"""
    global current_version
    
    # Если версия еще не найдена, ищем её
    if current_version is None:
        current_version = await find_working_version_async(update)
        if current_version is None:
            return None
    
    uri = f"wss://magicgarden.gg/version/{current_version}/api/rooms/{ROOM_ID}/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22{PLAYER_ID}%22&version=%22{current_version}%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"
    
    try:
        async with websockets.connect(uri, close_timeout=3) as websocket:
            print(f"📡 Использую версию {current_version}...")
            data = await asyncio.wait_for(websocket.recv(), timeout=5)
            return json.loads(data)
    except Exception as e:
        print(f"❌ Ошибка при получении данных с версией {current_version}: {e}")
        # Если текущая версия перестала работать, сбрасываем её и ищем новую
        current_version = None
        return await get_shop_data(update)

def format_shop_info(data):
    """Форматирование информации о магазине для вывода в Telegram"""
    if not data:
        return "❌ Не удалось получить данные магазина"
    
    try:
        # Извлекаем данные магазинов
        shops = data.get("child", {}).get("data", {}).get("shops", {})
        
        result = f"🏪 **Информация о магазинах Magic Garden** 🏪\n"
        if current_version:
            result += f"📌 Версия протокола: {current_version}\n\n"
        else:
            result += "\n"
        
        # Магазин семян
        seed_shop = shops.get("seed", {})
        if seed_shop:
            result += f"🌱 **Магазин семян**\n"
            result += f"⏰ Перезагрузка через: {seed_shop.get('secondsUntilRestock', 0)} сек.\n"
            
            seed_inventory = seed_shop.get("inventory", [])
            available_seeds = [item for item in seed_inventory if item.get("initialStock", 0) > 0]
            
            if available_seeds:
                result += "📦 В наличии:\n"
                for seed in available_seeds[:10]:
                    species = seed.get("species", "Unknown")
                    stock = seed.get("initialStock", 0)
                    result += f"  • {species}: {stock} шт.\n"
                if len(available_seeds) > 10:
                    result += f"  ... и еще {len(available_seeds) - 10} видов\n"
            else:
                result += "  ❌ Нет семян в наличии\n"
            result += "\n"
        
        # Магазин инструментов
        tool_shop = shops.get("tool", {})
        if tool_shop:
            result += f"🔧 **Магазин инструментов**\n"
            result += f"⏰ Перезагрузка через: {tool_shop.get('secondsUntilRestock', 0)} сек.\n"
            
            tool_inventory = tool_shop.get("inventory", [])
            available_tools = [item for item in tool_inventory if item.get("initialStock", 0) > 0]
            
            if available_tools:
                result += "📦 В наличии:\n"
                for tool in available_tools[:5]:
                    tool_id = tool.get("toolId", tool.get("decorId", "Unknown"))
                    stock = tool.get("initialStock", 0)
                    item_type = tool.get("itemType", "Tool")
                    result += f"  • {tool_id} ({item_type}): {stock} шт.\n"
            else:
                result += "  ❌ Нет инструментов в наличии\n"
            result += "\n"
        
        # Магазин яиц
        egg_shop = shops.get("egg", {})
        if egg_shop:
            result += f"🥚 **Магазин яиц**\n"
            result += f"⏰ Перезагрузка через: {egg_shop.get('secondsUntilRestock', 0)} сек.\n"
            
            egg_inventory = egg_shop.get("inventory", [])
            available_eggs = [item for item in egg_inventory if item.get("initialStock", 0) > 0]
            
            if available_eggs:
                result += "📦 В наличии:\n"
                for egg in available_eggs[:5]:
                    egg_id = egg.get("eggId", "Unknown")
                    stock = egg.get("initialStock", 0)
                    result += f"  • {egg_id}: {stock} шт.\n"
            else:
                result += "  ❌ Нет яиц в наличии\n"
            result += "\n"
        
        # Магазин декора
        decor_shop = shops.get("decor", {})
        if decor_shop:
            result += f"🎨 **Магазин декора**\n"
            result += f"⏰ Перезагрузка через: {decor_shop.get('secondsUntilRestock', 0)} сек.\n"
            
            decor_inventory = decor_shop.get("inventory", [])
            available_decor = [item for item in decor_inventory if item.get("initialStock", 0) > 0]
            
            if available_decor:
                result += "📦 В наличии:\n"
                for decor in available_decor[:5]:
                    decor_id = decor.get("decorId", "Unknown")
                    stock = decor.get("initialStock", 0)
                    result += f"  • {decor_id}: {stock} шт.\n"
                if len(available_decor) > 5:
                    result += f"  ... и еще {len(available_decor) - 5} предметов\n"
            else:
                result += "  ❌ Нет декора в наличии\n"
        
        # Добавляем информацию о комнате
        room_data = data.get("data", {})
        result += f"\n📊 **Статус комнаты**\n"
        result += f"🎮 Игра: {room_data.get('selectedGame', 'Unknown')}\n"
        
        timer = room_data.get("timer", {})
        if timer.get("isRunning", False):
            result += f"⏲️ Таймер: {timer.get('secondsRemaining', 0)} сек.\n"
        
        players = room_data.get("players", [])
        result += f"👥 Игроков: {len(players)}\n"
        
        return result
        
    except Exception as e:
        return f"❌ Ошибка при форматировании данных: {e}"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    # Отправляем начальное сообщение
    message = await update.message.reply_text("🔄 Получаю информацию о магазинах Magic Garden...\n🔍 Поиск актуальной версии протокола...")
    
    # Получаем данные
    data = await get_shop_data(update)
    
    if data:
        # Форматируем и отправляем информацию
        shop_info = format_shop_info(data)
        await message.edit_text(shop_info, parse_mode='Markdown')
    else:
        await message.edit_text("❌ Не удалось получить данные. Попробуйте позже.\n\nВозможные причины:\n• Сервер недоступен\n• Неверный ID комнаты\n• Технические работы")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
🤖 **Помощь по боту Magic Garden**

Доступные команды:
/start - Показать актуальную информацию о магазинах
/help - Показать это сообщение
/shop - Показать информацию о магазинах (алиас /start)
/version - Показать текущую используемую версию протокола
/reset - Сбросить версию и найти новую

📊 Бот показывает:
• Ассортимент и количество товаров в каждом магазине
• Время до следующей перезагрузки магазинов
• Статус комнаты и количество игроков
• Используемую версию протокола

🔄 Особенности:
• Бот автоматически ищет рабочую версию
• При сбое текущей версии автоматически ищет новую
• Версия сохраняется между запросами для быстрой работы
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Алиас для команды /start"""
    await start_command(update, context)

async def version_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущую используемую версию"""
    global current_version
    if current_version:
        await update.message.reply_text(f"📌 Текущая используемая версия протокола: **{current_version}**", parse_mode='Markdown')
    else:
        await update.message.reply_text("🔍 Версия еще не определена. Используйте /start для поиска рабочей версии.")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбросить версию и найти новую"""
    global current_version
    current_version = None
    await update.message.reply_text("🔄 Версия сброшена. При следующем запросе будет выполнен поиск новой версии.\nИспользуйте /start для обновления информации.")

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("version", version_command))
    application.add_handler(CommandHandler("reset", reset_command))
    
    # Запускаем бота
    print("🤖 Бот запущен...")
    print("🔍 Бот будет автоматически искать рабочие версии протокола")
    print("📝 Логи поиска будут отображаться в консоли")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()