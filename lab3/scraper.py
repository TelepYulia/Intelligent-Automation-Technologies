import re
import pandas as pd
from playwright.sync_api import Response, Route, sync_playwright

# Глобальний масив для збереження зібраних товарів
collected_items = []


def extract_memory(title: str) -> str:
    if not title:
        return "Н/Д"
    match = re.search(r"\b(\d+\s*(?:GB|TB|ГБ|ТБ))\b", title, re.IGNORECASE)
    return match.group(1).upper() if match else "Н/Д"


#Блокування медіа-трафіку
def route_filter(route: Route):
    blocked_types = ["image", "media", "font"]
    if route.request.resource_type in blocked_types:
        route.abort()
    else:
        route.continue_()


#Асинхронне перехоплення API-відповідей
def handle_network_response(response: Response):
    if ("catalog-api.rozetka.com.ua" in response.url or "details?" in response.url) and response.status == 200:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = response.json()
                data_block = payload.get("data", {})

                if isinstance(data_block, dict):
                    raw_items = data_block.get("goods", [])
                elif isinstance(data_block, list):
                    raw_items = data_block
                else:
                    raw_items = []

                if isinstance(raw_items, list) and len(raw_items) > 0:
                    for item in raw_items:
                        title = item.get("title") or item.get("name") or ""
                        if not title:
                            continue

                        price = item.get("price", "Н/Д")
                        old_price = item.get("old_price", 0)
                        old_price_str = "Без знижки" if (not old_price or old_price == price) else str(old_price)

                        collected_items.append({
                            "Бренд/Модель": title.strip(),
                            "Ціна зі знижкою": price,
                            "Стара ціна": old_price_str,
                            "Обсяг пам'яті": extract_memory(title)
                        })
                    print(f"[+] Перехоплено чергову пачку з API: {len(raw_items)} товарів")
            except Exception:
                pass


def main():
    with sync_playwright() as p:
        #Налаштування контексту браузера та маскування автоматизації
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = context.new_page()

        #Підключення мережевих фільтрів та слухача 
        page.route("**/*", route_filter)
        page.on("response", handle_network_response)

        start_url = "https://rozetka.com.ua/ua/mobile-phones/c80003/preset=smartfon/"

        #Ініціалізація навігації без зависання
        print(f"[*] Відкриваємо каталог: {start_url}")
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        #Емуляція плавного скролу для тригера Lazy Loading
        print("[*] Поступовий скрол сторінки вниз для виклику XHR-запитів...")
        for _ in range(6):
            page.evaluate("window.scrollBy(0, 900)")
            page.wait_for_timeout(1500)

        page.evaluate("window.scrollTo(0, document.body.scrollHeight - 800)")
        page.wait_for_timeout(2000)

        # Резервний DOM-парсинг (якщо перша сторінка була відрендерена через SSR)
        if not collected_items:
            print("[i] XHR не згенеровано (SSR). Застосовуємо резервні DOM-локатори...")
            tiles = page.locator(".goods-tile, .catalog-grid__cell").all()
            for tile in tiles:
                try:
                    title_elem = tile.locator(".goods-tile__title, a.goods-tile__heading").first
                    if not title_elem.is_visible():
                        continue
                    title = title_elem.inner_text().strip()
                    if not title:
                        continue

                    price_elem = tile.locator(".goods-tile__price-value").first
                    price = price_elem.inner_text().strip().replace("\xa0", "").replace(" ", "") if price_elem.is_visible() else "Н/Д"

                    old_price_elem = tile.locator(".goods-tile__price--old").first
                    old_price = old_price_elem.inner_text().strip().replace("\xa0", "").replace(" ", "") if old_price_elem.is_visible() else "Без знижки"

                    collected_items.append({
                        "Бренд/Модель": title,
                        "Ціна зі знижкою": price,
                        "Стара ціна": old_price,
                        "Обсяг пам'яті": extract_memory(title)
                    })
                except Exception:
                    continue

        #Взаємодія з пагінацією через механізм Actionability Checks
        show_more_btn = page.locator("button:has-text('Показати ще'), a:has-text('Показати ще'), .show-more").first

        if show_more_btn.is_visible():
            print("[*] Клікаємо на 'Показати ще' для довантаження наступної сторінки...")
            show_more_btn.click()
            page.wait_for_timeout(3000)

            #Прокручуємо нову порцію довантажених карток
            for _ in range(5):
                page.evaluate("window.scrollBy(0, 900)")
                page.wait_for_timeout(1500)
        else:
            print("[!] Кнопку 'Показати ще' не знайдено, перевіряємо перемикач сторінок...")
            page_2_btn = page.locator("a[href*='page=2'], a[href*='page-2']").or_(page.get_by_role("link", name="2")).first
            if page_2_btn.is_visible():
                print("[*] Клікаємо на сторінку 2...")
                page_2_btn.click()
                page.wait_for_timeout(4000)
                for _ in range(5):
                    page.evaluate("window.scrollBy(0, 900)")
                    page.wait_for_timeout(1500)

        browser.close()

    #Усунення дублікатів та експорт даних у CSV
    target_csv = "smartphones.csv"
    if collected_items:
        df = pd.DataFrame(collected_items)
        df = df.dropna(subset=["Бренд/Модель"])
        df = df.drop_duplicates(subset=["Бренд/Модель"])
        
        #Мапінг колонок відповідно до варіанта
        df = df[["Бренд/Модель", "Ціна зі знижкою", "Стара ціна", "Обсяг пам'яті"]]

        df.to_csv(target_csv, index=False, encoding="utf-8-sig")
        print(f"\n[✓] Успішно зібрано унікальних записів: {len(df)}")
        print(f"[✓] Артефакт збережено у файл: {target_csv}")
    else:
        print("[-] Помилка: товари не знайдено.")


if __name__ == "__main__":
    main()
