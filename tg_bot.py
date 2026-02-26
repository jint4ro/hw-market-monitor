import os
from dotenv import load_dotenv
import asyncio
import psycopg2
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

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

# --- МАШИНА СОСТОЯНИЙ (ШАГИ ДИАЛОГА) ---
class GPUForm(StatesGroup):
    budget = State()  # Шаг 1: Ожидаем бюджет
    brand = State()   # Шаг 2: Ожидаем бренд

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
    
def get_db_advanced_search(max_price, brand):
    """Ищет карты по бюджету и названию бренда"""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()

        # ILIKE позволяет искать текст без учета регистра (msi = MSI)
        query = """
            SELECT product_name, price, link 
            FROM gpu_prices 
            WHERE price <= %s 
              AND product_name ILIKE %s 
              AND price IS NOT NULL 
            ORDER BY price ASC 
            LIMIT 3;
        """
        # Добавляем % вокруг бренда, чтобы искать его в любом месте названия
        cursor.execute(query, (max_price, f"%{brand}%"))
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()

        if not results:
            return f"😔 Не нашел карт бренда **{brand}** дешевле {max_price} руб."

        text = f"🎯 **ПОДБОРКА {brand.upper()} ДО {max_price} РУБ:**\n\n"
        for idx, row in enumerate(results, 1):
            text += f"{idx}. **{row[0]}**\n💸 Цена: {row[1]:,} руб.\n🔗 [Ссылка]({row[2]})\n\n".replace(',', ' ')
            
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

# 1. Пользователь пишет /find, бот включает состояние "Ожидание бюджета"
@dp.message(Command("find"))
async def start_find_dialog(message: types.Message, state: FSMContext):
    await message.answer("Давай подберем видеокарту! 🎮\n\nНапиши свой максимальный бюджет (только цифры):")
    await state.set_state(GPUForm.budget)

# 2. Бот ловит ответ (бюджет) и переключается на "Ожидание бренда"
@dp.message(GPUForm.budget)
async def process_budget(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Пожалуйста, введи только числа (например, 45000).")
        return
    
    await state.update_data(budget=int(message.text))
    
    # Создаем клавиатуру с брендами
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="MSI", callback_data="brand_msi"),
            InlineKeyboardButton(text="Palit", callback_data="brand_palit")
        ],
        [
            InlineKeyboardButton(text="Gigabyte", callback_data="brand_gigabyte"),
            InlineKeyboardButton(text="ASUS", callback_data="brand_asus")
        ],
        [
            InlineKeyboardButton(text="🎲 Любой бренд", callback_data="brand_any")
        ]
    ])
    
    await message.answer("Отлично. Какой бренд предпочитаешь?", reply_markup=keyboard)
    await state.set_state(GPUForm.brand)

# 3. Бот ловит бренд, достает бюджет из памяти и делает запрос в БД
# Фильтр F.data.startswith("brand_") ловит только нажатия на наши кнопки
@dp.callback_query(GPUForm.brand, F.data.startswith("brand_"))
async def process_brand_callback(callback: CallbackQuery, state: FSMContext):
    # Достаем название бренда из callback_data (например, из "brand_msi" достаем "msi")
    brand = callback.data.split("_")[1]
    
    # Если выбрали "Любой", передаем пустую строку, чтобы SQL-запрос нашел всё
    if brand == "any":
        brand = ""
        display_brand = "ЛЮБОЙ БРЕНД"
    else:
        display_brand = brand.upper()
    
    user_data = await state.get_data()
    max_price = user_data['budget']
    
    # Меняем текст сообщения с кнопками на статус поиска
    await callback.message.edit_text(f"⏳ Ищу карты **{display_brand}** до {max_price} руб...", parse_mode="Markdown")
    
    result_text = get_db_advanced_search(max_price, brand)
    await callback.message.answer(result_text, parse_mode="Markdown", disable_web_page_preview=True)
    
    await state.clear()
    await callback.answer() # Обязательно "отвечаем" телеграму, чтобы часики на кнопке перестали крутиться

# --- ЗАПУСК БОТА ---
async def main():
    print("🤖 Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())