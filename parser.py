import time
import psycopg2
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

DB_PARAMS = {
    "database": "postgres",
    "user": "postgres",
    "password": "1234", 
    "host": "85.198.69.218", 
    "port": "5432"
}

def save_to_db(name, price, link):
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        conn.autocommit = True
        cursor = conn.cursor()

        # Шаг 1: Записываем карту в справочник (или обновляем)
        cursor.execute("""
            INSERT INTO gpu_info (product_name, link)
            VALUES (%s, %s)
            ON CONFLICT (link) DO UPDATE 
            SET product_name = EXCLUDED.product_name
            RETURNING id;
        """, (name, link))
        
        gpu_id = cursor.fetchone()[0]

        # Шаг 2: Записываем свежую цену в историю
        if price is not None:
            cursor.execute("""
                INSERT INTO price_history (gpu_id, price, parsed_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP);
            """, (gpu_id, price))

        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")
        return False

# СПИСОК ЖЕЛАЕМЫХ ВИДЕОКАРТ
target_gpus = [
    "RTX 4060", 
    "RTX 5070", 
    "RTX 5080", 
    "RTX 5090"
]

# Настройки браузера
options = uc.ChromeOptions()
options.add_argument("--disable-notifications")
prefs = {"profile.default_content_setting_values.geolocation": 2}
options.add_experimental_option("prefs", prefs)

print("🚀 Запускаю мульти-парсер NVIDIA...")
driver = uc.Chrome(version_main=146, options=options, use_subprocess=True)
wait = WebDriverWait(driver, 15)

try:
    for gpu_model in target_gpus:
        print(f"\n=========================================")
        print(f"🔍 НАЧИНАЮ ПОИСК: {gpu_model}")
        print(f"=========================================")
        
        # Заходим на главную ДНС перед каждым новым поиском для сброса состояния
        driver.get("https://www.dns-shop.ru/")
        time.sleep(2)
        
        try:
            # Ищем строку поиска
            search_box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder*='Поиск']")))
            
            # Надежная очистка строки поиска (через Ctrl+A -> Delete)
            search_box.send_keys(Keys.CONTROL + "a")
            search_box.send_keys(Keys.BACKSPACE)
            time.sleep(1)
            
            search_box.send_keys(gpu_model)
            time.sleep(1)
            search_box.send_keys(Keys.RETURN)
            
            # Ждем появления товаров или сообщения "Ничего не найдено"
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.catalog-product")))
            time.sleep(3) 
            
        except TimeoutException:
            print(f"⚠️ По запросу {gpu_model} ничего не найдено или сайт завис. Пропускаю...")
            continue # Переходим к следующей модели в списке

        print("🔄 Начинаю прокрутку страницы для подгрузки всех товаров...")
        last_count = 0
        retries = 0 
        
        # Цикл прокрутки страницы до самого низа (Infinite Scroll)
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3) 
            
            products = driver.find_elements(By.CSS_SELECTOR, "div.catalog-product")
            current_count = len(products)
            print(f"📦 Загружено товаров: {current_count}")
            
            if current_count == last_count:
                retries += 1
                if retries >= 2:
                    print("🛑 Достигнут конец списка.")
                    break
            else:
                retries = 0 
                
            last_count = current_count

        print(f"\n📄 --- НАЧИНАЮ СБОР ДАННЫХ ({last_count} шт.) ---")
        
        for item in products:
            try:
                name_tag = item.find_element(By.CSS_SELECTOR, "a.catalog-product__name")
                name = name_tag.text
                link = name_tag.get_attribute("href")
                
                # Защита от попадания в выборку мусора (аксессуаров, кабелей и тд)
                if gpu_model.split()[1] not in name: # Проверяем, есть ли цифры (4060, 5070) в названии
                    continue

                try:
                    price_tag = item.find_element(By.CSS_SELECTOR, "div.product-buy__price")
                    clean_price_str = price_tag.text.replace("₽", "").replace(" ", "").strip()
                    final_price = int(clean_price_str) if clean_price_str.isdigit() else None
                except:
                    final_price = None
                
                if save_to_db(name, final_price, link):
                    print(f"✅ В БД: {name[:25]}... | {final_price} руб.")
                    
            except Exception:
                continue
                
        print(f"⏳ Сбор по {gpu_model} завершен. Делаю паузу перед следующим запросом...")
        time.sleep(5) # Пауза, чтобы не выглядеть как DDoS-атака

    print("\n🎉 ВСЕ ЗАДАННЫЕ ЛИНЕЙКИ УСПЕШНО СОБРАНЫ И ОТПРАВЛЕНЫ В БД!")

except Exception as e:
    print(f"❌ Критическая ошибка выполнения: {e}")

finally:
    driver.quit()