import time
import psycopg2
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

        # Шаг 1: Записываем карту в справочник (или просто получаем ее ID, если она уже там есть)
        # Хитрый трюк: DO UPDATE нужен только для того, чтобы сработал RETURNING id
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

# Настройки
options = uc.ChromeOptions()
options.add_argument("--disable-notifications")
prefs = {"profile.default_content_setting_values.geolocation": 2}
options.add_experimental_option("prefs", prefs)

print("🚀 Запускаю мега-парсер с пагинацией...")
driver = uc.Chrome(version_main=145, options=options, use_subprocess=True)
wait = WebDriverWait(driver, 20)

try:
    driver.get("https://www.dns-shop.ru/")
    
    driver.get("https://www.dns-shop.ru/")
    
    # Ищем строку поиска
    search_box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder*='Поиск']")))
    search_box.click()
    search_box.send_keys("RTX 4060")
    time.sleep(1)
    search_box.send_keys(Keys.RETURN)
    
    # Ждем появления хотя бы первых товаров
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.catalog-product")))
    time.sleep(3) 

    print("\n🔄 Начинаю прокрутку страницы для подгрузки всех товаров...")
    
    last_count = 0
    retries = 0 # Защита на случай долгой загрузки элементов
    
    # Цикл прокрутки страницы до самого низа
    while True:
        # Крутим в самый низ
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3) # Ждем, пока отработают скрипты сайта и подтянут новые товары
        
        products = driver.find_elements(By.CSS_SELECTOR, "div.catalog-product")
        current_count = len(products)
        
        print(f"📦 Загружено товаров на данный момент: {current_count}")
        
        if current_count == last_count:
            retries += 1
            # Если два раза крутанули, а новых товаров нет — значит, это точно конец списка
            if retries >= 2:
                print("🛑 Достигнут конец списка. Подгрузка завершена.")
                break
        else:
            retries = 0 # Сбрасываем счетчик, если нашли новые товары
            
        last_count = current_count

    print(f"\n📄 --- НАЧИНАЮ СБОР ДАННЫХ И ОТПРАВКУ В БД ({last_count} шт.) ---")
    
    # Теперь, когда все карточки прогружены в DOM, парсим их
    for item in products:
        try:
            name_tag = item.find_element(By.CSS_SELECTOR, "a.catalog-product__name")
            name = name_tag.text
            link = name_tag.get_attribute("href")
            
            try:
                price_tag = item.find_element(By.CSS_SELECTOR, "div.product-buy__price")
                clean_price_str = price_tag.text.replace("₽", "").replace(" ", "").strip()
                final_price = int(clean_price_str) if clean_price_str.isdigit() else None
            except:
                final_price = None
            
            if save_to_db(name, final_price, link):
                print(f"✅ Ушло в БД: {name[:25]}... | {final_price} руб.")
                
        except Exception:
            continue

    print("\n🎉 ВЕСЬ КАТАЛОГ УСПЕШНО СОБРАН!")

except Exception as e:
    print(f"❌ Критическая ошибка: {e}")

finally:
    driver.quit()