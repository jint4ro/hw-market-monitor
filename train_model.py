import pandas as pd
import psycopg2
import re
import joblib
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

# --- 1. НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД ---
# Используем порт 5433 (наш SSH-туннель)
DB_PARAMS = {
    "database": "postgres",
    "user": "postgres",
    "password": "QklXiC.>8S{aT5&", # Твой пароль
    "host": "localhost",
    "port": "5433"
}

# --- 2. ФУНКЦИЯ ИЗВЛЕЧЕНИЯ ПРИЗНАКОВ (Точная копия из tg_bot.py!) ---
# Это КРИТИЧЕСКИ важно для целостности: модель должна учиться на тех же правилах, 
# по которым бот будет готовить для нее новые данные.
def extract_features_for_ml(name):
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

def main():
    print("⏳ Подключаюсь к БД и выгружаю свежие цены...")
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        # Выгружаем только САМУЮ СВЕЖУЮ цену для каждой уникальной видеокарты
        query = """
            SELECT DISTINCT ON (g.id) 
                g.product_name, p.price 
            FROM gpu_info g
            JOIN price_history p ON g.id = p.gpu_id
            WHERE p.price IS NOT NULL
            ORDER BY g.id, p.parsed_at DESC;
        """
        df_raw = pd.read_sql(query, conn)
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")
        return

    print(f"📦 Выгружено {len(df_raw)} актуальных предложений. Готовлю фичи...")

    # --- 3. ПОДГОТОВКА ДАННЫХ ---
    # Применяем нашу функцию ко всем названиям
    features_list = df_raw['product_name'].apply(extract_features_for_ml).tolist()
    df_features = pd.DataFrame(features_list)
    
    # Добавляем целевую переменную (цену)
    df_features['price'] = df_raw['price']

    X = df_features.drop('price', axis=1)
    y = df_features['price']

    # --- 4. НАСТРОЙКА ПАЙПЛАЙНА ---
    categorical_features = ['brand', 'series']
    categorical_transformer = OneHotEncoder(handle_unknown='ignore')

    preprocessor = ColumnTransformer(
        transformers=[
            ('cat', categorical_transformer, categorical_features)
        ],
        remainder='passthrough'
    )

    # Используем Случайный Лес вместо Линейной регрессии
    pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('regressor', RandomForestRegressor(n_estimators=100, random_state=42))
    ])

    # --- 5. ОЦЕНКА ТОЧНОСТИ МОДЕЛИ ---
    # Разбиваем данные на тренировочные (80%) и тестовые (20%) чтобы проверить ИИ
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    pipeline.fit(X_train, y_train)
    predictions = pipeline.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    
    print(f"🎯 Модель протестирована. Средняя ошибка в предсказании цены: ±{mae:,.0f} руб.")

    # --- 6. ФИНАЛЬНОЕ ОБУЧЕНИЕ И СОХРАНЕНИЕ ---
    # Теперь обучаем модель на ВСЕХ 100% данных, чтобы она была максимально умной
    print("🧠 Обучаю финальную модель на всех данных...")
    pipeline.fit(X, y)

    model_filename = 'gpu_price_pipeline.joblib'
    joblib.dump(pipeline, model_filename)
    print(f"✅ Готово! Файл '{model_filename}' перезаписан и готов для Telegram-бота.")

if __name__ == "__main__":
    main()