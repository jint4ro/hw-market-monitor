import time
import psycopg2
from selenium import webdriver 
from selenium.webdriver.common.by import By
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
        upsert_query = """
            INSERT INTO gpu_prices (product_name, price, link, parsed_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (link) 
            DO UPDATE SET
                price = EXCLUDED.price,
                parsed_at = EXCLUDED.parsed_at;
        """
        cursor.execute(upsert_query, (name, price, link))
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False

def init_driver(): 
    options = webdriver.ChromeOptions()  
    
    # Для Windows оставляем только маскировку от ботов и полный экран
    options.add_argument('--start-maximized')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60) 
    return driver

print("🚀 Запускаю локальный парсер (с сохранением в удаленную БД)...")
driver = init_driver() 
wait = WebDriverWait(driver, 20)

try:
    target_url = "https://www.dns-shop.ru/search/?q=RTX+4060"
    print(f"🌐 Открываю сайт: {target_url}")
    driver.get(target_url)
    
    print("⏳ Даю сайту 5 секунд. Если вылезет защита (Qrator) — у тебя есть время решить ее мышкой!")
    time.sleep(5)
    
    page_number = 1
    
    while True:
        print(f"\n📄 --- ОБРАБАТЫВАЮ СТРАНИЦУ {page_number} ---")
        
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.catalog-product")))
        time.sleep(3) # Ждем подгрузки цен
        
        products = driver.find_elements(By.CSS_SELECTOR, "div.catalog-product")
        print(f"📦 Найдено товаров на странице: {len(products)}")
        
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
                    print(f"✅ Ушло в БД на сервер: {name[:25]}... | {final_price} руб.")
                
            except Exception:
                continue
                
        # --- ПАГИНАЦИЯ ---
        try:
            next_button = driver.find_element(By.CSS_SELECTOR, "a.pagination-widget__page-link_next")
            
            if "disabled" in next_button.get_attribute("class"):
                print("🛑 Достигнута последняя страница. Завершаю работу.")
                break
                
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            time.sleep(1) 
            
            print("➡️ Перехожу на следующую страницу...")
            next_button.click()
            page_number += 1
            time.sleep(3) 
            
        except Exception as e:
            print("🛑 Кнопка 'Дальше' не найдена. Похоже, это последняя страница.")
            break

    print("\n🎉 ВЕСЬ КАТАЛОГ УСПЕШНО СОБРАН И ОТПРАВЛЕН НА СЕРВЕР!")

except Exception as e:
    print(f"❌ Критическая ошибка: {e}")

finally:
    driver.quit()