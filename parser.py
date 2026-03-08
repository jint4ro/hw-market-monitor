import time
import psycopg2
from selenium import webdriver 
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DB_PARAMS = {
    "database": "postgres",
    "user": "postgres",
    "password": "1234", 
    "host": "localhost",
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
        return False

def init_driver(): 
    options = webdriver.ChromeOptions()  
    options.add_argument('--no-zygote')
    options.add_argument('--disable-software-rasterizer') 
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' \
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    # ----------------------------------
    
    # Запускаем официальный драйвер (версию указывать больше не нужно!)
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60) 
    return driver

print("🚀 Запускаю мега-парсер с пагинацией...")
driver = init_driver() 
wait = WebDriverWait(driver, 20)

try:
    target_url = "https://www.dns-shop.ru/search/?q=RTX+4060"
    print(f"🌐 Иду прямо по ссылке: {target_url}")
    driver.get(target_url)
    
    print("⏳ Жду 5 секунд для прогрузки JS...")
    time.sleep(5)
    
    page_number = 1 # Счетчик страниц для логов, чтобы видеть прогресс
    
    while True:
        print(f"\n📄 --- ОБРАБАТЫВАЮ СТРАНИЦУ {page_number} ---")
        
        # Ждем появления именно товаров
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.catalog-product")))
        time.sleep(3) # Ждем подгрузки цен
    
    # Бесконечный цикл, который прервется только когда закончатся страницы
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
                    print(f"✅ Ушло в БД: {name[:25]}... | {final_price} руб.")
                    
            except Exception:
                continue
                
        # --- ПАГИНАЦИЯ (Переход на следующую страницу) ---
        try:
            # Ищем кнопку "Следующая страница" (в ДНС это обычно стрелочка вправо)
            # Селектор ищет элемент с классом, содержащим 'pagination' и 'next'
            next_button = driver.find_element(By.CSS_SELECTOR, "a.pagination-widget__page-link_next")
            
            # Проверяем, не стала ли кнопка неактивной (дошли до последней страницы)
            if "disabled" in next_button.get_attribute("class"):
                print("🛑 Достигнута последняя страница. Завершаю работу.")
                break
                
            # Прокручиваем страницу вниз до кнопки, иначе Selenium не сможет на нее нажать
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            time.sleep(1) # Даем время на плавную прокрутку
            
            print("➡️ Перехожу на следующую страницу...")
            next_button.click()
            page_number += 1
            
            # Ждем пару секунд, чтобы ДНС не забанил нас за слишком быстрые клики
            time.sleep(3) 
            
        except Exception as e:
            # Если кнопку не нашли вообще (например, товар всего на 1 странице)
            print("🛑 Кнопка 'Дальше' не найдена. Похоже, это последняя страница.")
            break

    print("\n🎉 ВЕСЬ КАТАЛОГ УСПЕШНО СОБРАН!")

except Exception as e:
    print(f"❌ Критическая ошибка: {e}")
    driver.save_screenshot("error_screenshot.png")
    print("📸 Скриншот сохранен как 'error_screenshot.png' для диагностики.")

finally:
    driver.quit()