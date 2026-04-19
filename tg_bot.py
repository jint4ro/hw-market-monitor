import os
import re
import asyncio
import psycopg2
import joblib
import pandas as pd
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# --- НАСТРОЙКИ (СЕКРЕТЫ) ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ Токен не найден! Проверь файл .env")

DB_PARAMS = {
    "database": "postgres",
    "user": "postgres",
    "password": "QklXiC.>8S{aT5&",
    "host": "localhost",
    "port": "5432"
}

# --- МАШИНА СОСТОЯНИЙ ---
class GPUForm(StatesGroup):
    budget = State()
    brand = State()
    vram = State()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ЗАГРУЗКА ML-МОДЕЛИ ---
try:
    pipeline = joblib.load('gpu_price_pipeline.joblib')
    print("✅ ML-модель (pipeline) успешно загружена в память бота!")
except Exception as e:
    print(f"⚠️ Ошибка загрузки модели: {e}")
    pipeline = None

# --- ФУНКЦИИ БАЗЫ ДАННЫХ И ML ---

def extract_features_for_ml(name):
    """Превращает сырое название видеокарты в словарь признаков для ML"""
    series_match = re.search(r'(4060|5070|5080|5090)', name)
    series = series_match.group(1) if series_match else 'Unknown'
    
    vram_match = re.search(r'(\d+)\s*ГБ', name)
    vram_gb = int(vram_match.group(1)) if vram_match else 8
    
    brand = 'Other'
    for b in ['MSI', 'Palit', 'Gigabyte', 'ASUS', 'INNO3D', 'KFA2', 'ZOTAC', 'Colorful']:
        if b.lower() in name.lower():
            brand = b
            break
            
    is_ti = 1 if ' ti ' in name.lower() or 'ti' in name.lower().split() else 0
    return {'brand': brand, 'is_ti': is_ti, 'vram_gb': vram_gb, 'series': series}

def get_ai_deals(limit=5):
    """Ищет карты, цена которых ниже предсказанной моделью ML"""
    if pipeline is None:
        return "❌ Модель ИИ временно недоступна на сервере."

    try:
        conn = psycopg2.connect(**DB_PARAMS)
        query = """
            SELECT DISTINCT ON (g.id) 
                g.product_name, g.link, p.price 
            FROM gpu_info g
            JOIN price_history p ON g.id = p.gpu_id
            WHERE p.parsed_at >= CURRENT_TIMESTAMP - INTERVAL '1 day'
              AND p.price IS NOT NULL
            ORDER BY g.id, p.parsed_at DESC;
        """
        df_market = pd.read_sql(query, conn)
        conn.close()

        if df_market.empty:
            return "📭 В базе сейчас нет видеокарт в наличии для анализа."

        # 1. Готовим фичи
        features_list = df_market['product_name'].apply(extract_features_for_ml).tolist()
        df_features = pd.DataFrame(features_list)

        # 2. Делаем массовое предсказание
        df_market['predicted_price'] = pipeline.predict(df_features)

        # 3. Считаем выгоду
        df_market['benefit'] = df_market['predicted_price'] - df_market['price']
        df_market['benefit_pct'] = df_market['benefit'] / df_market['predicted_price']

        # 4. Фильтруем: выгода больше 0, но меньше 40% (отсекаем неадекватные выбросы ИИ)
        good_deals = df_market[(df_market['benefit'] > 0) & (df_market['benefit_pct'] < 0.40)]
        good_deals = good_deals.sort_values(by='benefit', ascending=False).head(limit)

        if good_deals.empty:
            return "🤖 ИИ проанализировал рынок. Сейчас нет карт, продающихся ниже их 'справедливой' стоимости."

        text = "🤖 **ТОП ВЫГОДНЫХ КАРТ ПО ОЦЕНКЕ ИИ:**\n\n"
        for idx, row in good_deals.iterrows():
            text += f"🔹 **{row['product_name']}**\n"
            text += f"🧠 Оценка алгоритма: {row['predicted_price']:,.0f} руб.\n".replace(',', ' ')
            text += f"💰 Реальная цена: **{row['price']:,.0f} руб.**\n".replace(',', ' ')
            text += f"🔥 Выгода: {row['benefit']:,.0f} руб.\n"
            text += f"🔗 [Купить]({row['link']})\n\n"
            
        return text
    except Exception as e:
        return f"❌ Ошибка ИИ-анализа: {e}"

def get_db_stats():
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM gpu_info;")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT ROUND(AVG(price)) FROM price_history WHERE price IS NOT NULL;")
        avg_price = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        text = f"📊 **СВОДКА ПО БАЗЕ**\n\n"
        text += f"🔹 Отслеживаемых карт: {total} шт.\n"
        if avg_price:
            text += f"🔹 Средняя цена: {int(avg_price):,} руб.\n".replace(',', ' ')
        return text
    except Exception as e:
        return f"❌ Ошибка БД: {e}"

def get_db_advanced_search(max_price, brand, vram):
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        query = """
            WITH LatestPrices AS (
                SELECT DISTINCT ON (gpu_id) gpu_id, price
                FROM price_history
                WHERE price IS NOT NULL
                ORDER BY gpu_id, parsed_at DESC
            )
            SELECT g.product_name, l.price, g.link 
            FROM gpu_info g
            JOIN LatestPrices l ON g.id = l.gpu_id
            WHERE l.price <= %s 
              AND g.product_name ILIKE %s 
              AND g.product_name ILIKE %s
            ORDER BY l.price ASC 
            LIMIT 3;
        """
        cursor.execute(query, (max_price, f"%{brand}%", f"%{vram}%"))
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        display_brand = brand.upper() if brand else "ЛЮБОГО БРЕНДА"
        display_vram = vram if vram else "ЛЮБЫМ ОБЪЕМОМ ПАМЯТИ"

        if not results:
            return f"😔 Не нашел карт **{display_brand}** ({display_vram}) дешевле {max_price} руб."

        text = f"🎯 **ПОДБОРКА {display_brand} | {display_vram} | ДО {max_price} РУБ:**\n\n"
        for idx, row in enumerate(results, 1):
            text += f"{idx}. **{row[0]}**\n💸 Цена: {row[1]:,} руб.\n🔗 [Ссылка]({row[2]})\n\n".replace(',', ' ')
            
        return text
    except Exception as e:
        return f"❌ Ошибка БД: {e}"

def get_db_search(max_price):
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        query = """
            WITH LatestPrices AS (
                SELECT DISTINCT ON (gpu_id) gpu_id, price
                FROM price_history
                WHERE price IS NOT NULL
                ORDER BY gpu_id, parsed_at DESC
            )
            SELECT g.product_name, l.price, g.link 
            FROM gpu_info g
            JOIN LatestPrices l ON g.id = l.gpu_id
            WHERE l.price <= %s 
            ORDER BY l.price ASC 
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
    
def get_db_discounts():
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        query = """
        WITH PriceDynamics AS (
            SELECT 
                g.product_name,
                p.price AS current_price,
                LAG(p.price) OVER (PARTITION BY g.id ORDER BY p.parsed_at) AS old_price,
                g.link
            FROM price_history p
            JOIN gpu_info g ON p.gpu_id = g.id
        )
        SELECT product_name, old_price, current_price, (old_price - current_price) AS discount, link
        FROM PriceDynamics
        WHERE old_price IS NOT NULL AND current_price < old_price
        ORDER BY discount DESC
        LIMIT 5;
        """
        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        if not results:
            return "📉 Пока никаких скидок не зафиксировано. Цены стоят на месте или растут!"

        text = "🔥 **ТОП-5 ПОДЕШЕВЕВШИХ ВИДЕОКАРТ:**\n\n"
        for idx, row in enumerate(results, 1):
            name, old_price, current_price, discount, link = row
            text += f"{idx}. **{name}**\n"
            text += f"📉 Скидка: **{discount:,} руб.**\n".replace(',', ' ')
            text += f"💸 Было: {old_price:,} руб. ➡️ Стало: {current_price:,} руб.\n".replace(',', ' ')
            text += f"🔗 [Купить]({link})\n\n"
            
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
        "🔎 /search [сумма] — найти карты по бюджету\n"
        "🎮 /find — интерактивный подбор\n"
        "🔥 /discounts — посмотреть скидки\n"
        "🧠 /ai — умный поиск недооцененных карт (Machine Learning)"
    )

@dp.message(Command("ai"))
async def cmd_ai(message: types.Message):
    await message.answer("🧠 ИИ анализирует рынок и предсказывает цены. Жду...")
    result_text = get_ai_deals()
    await message.answer(result_text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    await message.answer("⏳ Считаю статистику...")
    stats_text = get_db_stats()
    await message.answer(stats_text, parse_mode="Markdown")

@dp.message(Command("search"))
async def cmd_search(message: types.Message, command: CommandObject):
    if command.args is None or not command.args.isdigit():
        await message.answer("⚠️ Укажи свой бюджет числом!\nПример: `/search 40000`", parse_mode="Markdown")
        return

    max_price = int(command.args)
    await message.answer(f"⏳ Ищу лучшие варианты до {max_price} руб...")
    result_text = get_db_search(max_price)
    await message.answer(result_text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("find"))
async def start_find_dialog(message: types.Message, state: FSMContext):
    await message.answer("Давай подберем видеокарту! 🎮\n\nНапиши свой максимальный бюджет (только цифры):")
    await state.set_state(GPUForm.budget)

@dp.message(GPUForm.budget)
async def process_budget(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Пожалуйста, введи только числа (например, 45000).")
        return
    
    await state.update_data(budget=int(message.text))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="MSI", callback_data="brand_msi"), InlineKeyboardButton(text="Palit", callback_data="brand_palit")],
        [InlineKeyboardButton(text="Gigabyte", callback_data="brand_gigabyte"), InlineKeyboardButton(text="ASUS", callback_data="brand_asus")],
        [InlineKeyboardButton(text="🎲 Любой бренд", callback_data="brand_any")]
    ])
    await message.answer("Отлично. Какой бренд предпочитаешь?", reply_markup=keyboard)
    await state.set_state(GPUForm.brand)

@dp.callback_query(GPUForm.brand, F.data.startswith("brand_"))
async def process_brand_callback(callback: CallbackQuery, state: FSMContext):
    brand = callback.data.split("_")[1]
    if brand == "any": brand = ""
    await state.update_data(brand=brand)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="8 ГБ", callback_data="vram_8"), InlineKeyboardButton(text="12 ГБ", callback_data="vram_12")],
        [InlineKeyboardButton(text="16 ГБ", callback_data="vram_16"), InlineKeyboardButton(text="🎲 Любой", callback_data="vram_any")]
    ])
    await callback.message.edit_text("Принято! Сколько нужно видеопамяти?", reply_markup=keyboard)
    await state.set_state(GPUForm.vram)
    await callback.answer()

@dp.callback_query(GPUForm.vram, F.data.startswith("vram_"))
async def process_vram_callback(callback: CallbackQuery, state: FSMContext):
    vram_data = callback.data.split("_")[1]
    vram = "" if vram_data == "any" else f"{vram_data} ГБ"
        
    user_data = await state.get_data()
    max_price, brand = user_data['budget'], user_data['brand']
    
    display_brand = brand.upper() if brand else "ЛЮБОЙ БРЕНД"
    display_vram = vram if vram else "ЛЮБОЙ ОБЪЕМ"
    
    await callback.message.edit_text(f"⏳ Ищу: **{display_brand}** | **{display_vram}** | до **{max_price}** руб...", parse_mode="Markdown")
    
    result_text = get_db_advanced_search(max_price, brand, vram)
    await callback.message.answer(result_text, parse_mode="Markdown", disable_web_page_preview=True)
    
    await state.clear()
    await callback.answer()

@dp.message(Command("discounts"))
async def cmd_discounts(message: types.Message):
    await message.answer("⏳ Ищу самые сочные скидки в базе...")
    result_text = get_db_discounts()
    await message.answer(result_text, parse_mode="Markdown", disable_web_page_preview=True)

# --- ЗАПУСК БОТА ---
async def main():
    print("🤖 Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())