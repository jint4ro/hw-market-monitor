import os
from dotenv import load_dotenv
import asyncio
import psycopg2
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject

# --- НАСТРОЙКИ (СЕКРЕТЫ) ---
# Загружаем данные из файла .env
load_dotenv()

# Берем токен из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Проверка, чтобы бот не запустился, если мы забыли создать .env
if not BOT_TOKEN:
    raise ValueError("❌ Токен не найден! Проверь файл .env")

DB_PARAMS = {
    "database": "postgres",
    "user": "postgres",
    "password": "1234",  # Пароль от БД тоже можно вынести в .env, но пока оставим так
    "host": "localhost",
    "port": "5432"
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_db_stats():
    """Возвращает общую аналитику из базы"""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM gpu_prices;")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT ROUND(AVG(price)) FROM gpu_prices WHERE price IS NOT NULL;")
        avg_price = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        text = f"📊 **СВОДКА ПО БАЗЕ**\n\n"
        text += f"🔹 Собранных цен: {total} шт.\n"
        if avg_price:
            text += f"🔹 Средняя цена: {int(avg_price):,} руб.\n".replace(',', ' ')
        return text
    except Exception as e:
        return f"❌ Ошибка БД: {e}"

def get_db_search(max_price):
    """Ищет топ-3 видеокарты дешевле max_price"""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()

        # SQL-запрос: ищем карты дешевле бюджета, сортируем по возрастанию цены, берем 3 штуки
        query = """
            SELECT product_name, price, link 
            FROM gpu_prices 
            WHERE price <= %s AND price IS NOT NULL 
            ORDER BY price ASC 
            LIMIT 3;
        """
        cursor.execute(query, (max_price,))
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()

        if not results:
            return f"😔 К сожалению, видеокарт дешевле {max_price} руб. не найдено."

        text = f"🔎 **ТОП-3 КАРТЫ ДО {max_price} РУБ:**\n\n"
        for idx, row in enumerate(results, 1):
            text += f"{idx}. **{row[0]}**\n💸 Цена: {row[1]:,} руб.\n🔗 [Ссылка]({row[2]})\n\n".replace(',', ' ')
            
        return text
    except Exception as e:
        return f"❌ Ошибка БД: {e}"

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я твой Data-ассистент. 🤖\n\n"
        "Доступные команды:\n"
        "📊 /stats — общая статистика\n"
        "🔎 /search [сумма] — найти видеокарты по бюджету (например: /search 40000)"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    await message.answer("⏳ Считаю статистику...")
    stats_text = get_db_stats()
    await message.answer(stats_text, parse_mode="Markdown")

# НОВЫЙ ОБРАБОТЧИК ДЛЯ ПОИСКА ПО БЮДЖЕТУ
@dp.message(Command("search"))
async def cmd_search(message: types.Message, command: CommandObject):
    # Если пользователь написал просто /search без цифр
    if command.args is None:
        await message.answer("⚠️ Укажи свой бюджет после команды.\nПример: `/search 40000`", parse_mode="Markdown")
        return

    # Проверяем, что ввели именно числа
    if not command.args.isdigit():
        await message.answer("⚠️ Бюджет должен быть числом!\nПример: `/search 40000`", parse_mode="Markdown")
        return

    max_price = int(command.args)
    await message.answer(f"⏳ Ищу лучшие варианты до {max_price} руб...")
    
    result_text = get_db_search(max_price)
    # disable_web_page_preview=True убирает огромные картинки-превью от ссылок
    await message.answer(result_text, parse_mode="Markdown", disable_web_page_preview=True)

# --- ЗАПУСК БОТА ---
async def main():
    print("🤖 Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())