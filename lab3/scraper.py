import pandas as pd
from playwright.sync_api import Response, Route, sync_playwright

# Глобальний масив для збереження зібраних товарів
collected_items = []


# Оптимізація ресурсів та блокування медіа-трафіку
def route_filter(route: Route):
    blocked_types = ["image", "media", "font"]
    if route.request.resource_type in blocked_types:
        route.abort()
    else:
        route.continue_()


# Асинхронне перехоплення API-відповідей 
def handle_network_response(response: Response):
    # Патерн API-ендпоінта Розетки
    target_pattern = "catalog-api.rozetka.com.ua"

    if target_pattern in response.url and response.status == 200:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = response.json()
                data_block = payload.get("data", {})

                # Адаптація під структуру JSON
                if isinstance(data_block, dict):
                    raw_items = data_block.get("goods", [])
                elif isinstance(data_block, list):
                    raw_items = data_block
                else:
                    raw_items = []

                if isinstance(raw_items, list) and len(raw_items) > 0:
                    print(
                        f"[+] Перехоплено чергову пачку: {len(raw_items)} товарів з API"
                    )
                    for item in raw_items:
                        collected_items.append(
                            {
                                "id": item.get("id"),
                                "title": item.get("title") or item.get("name"),
                                "brand": item.get("brand")
                                or item.get("brand_title"),
                                "price": item.get("price"),
                                "old_price": item.get("old_price"),
                                "href": item.get("href"),
                            }
                        )
            except Exception as err:
                print(f"[-] Помилка парсингу JSON: {err}")


def main():
    target_csv = "smartphones.csv"
    start_url = (
        "https://rozetka.com.ua/ua/mobile-phones/c80003/preset=smartfon/"
    )

    with sync_playwright() as p:
        # Налаштування контексту браузера та маскування автоматизації
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Підключення мережевого фільтра та асинхронного слухача
        page.route("**/*", route_filter)
        page.on("response", handle_network_response)

        # Ініціалізація навігації без зависання
        print(f"[*] Відкриваємо каталог: {start_url}")
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # Емуляція плавного скролу для тригера Lazy Loading
        print(
            "[*] Поступовий скрол сторінки вниз для виклику XHR-запитів..."
        )
        for _ in range(6):
            page.evaluate("window.scrollBy(0, 900)")
            page.wait_for_timeout(1500)

        page.evaluate("window.scrollTo(0, document.body.scrollHeight - 800)")
        page.wait_for_timeout(2000)

        # Взаємодія з пагінацією через механізм Actionability Checks
        show_more_btn = page.locator(
            "button:has-text('Показати ще'), a:has-text('Показати ще'), .show-more"
        ).first

        if show_more_btn.is_visible():
            print(
                "[*] Клікаємо на 'Показати ще' для довантаження наступної сторінки..."
            )
            show_more_btn.click()
            page.wait_for_timeout(3000)

            # Прокручуємо нову порцію довантажених карток
            for _ in range(5):
                page.evaluate("window.scrollBy(0, 900)")
                page.wait_for_timeout(1500)
        else:
            print(
                "[!] Кнопку 'Показати ще' не знайдено, перевіряємо перемикач сторінок..."
            )
            page_2_btn = page.locator(
                "a[href*='page=2'], a[href*='page-2']"
            ).or_(page.get_by_role("link", name="2")).first
            if page_2_btn.is_visible():
                print("[*] Клікаємо на сторінку 2...")
                page_2_btn.click()
                page.wait_for_timeout(4000)
                for _ in range(5):
                    page.evaluate("window.scrollBy(0, 900)")
                    page.wait_for_timeout(1500)

        browser.close()

    # Усунення дублікатів та експорт даних у структурований CSV
    if collected_items:
        df = pd.DataFrame(collected_items)
        df.dropna(subset=["title"], inplace=True)
        df.drop_duplicates(subset=["id"], inplace=True)

        df.to_csv(target_csv, index=False, encoding="utf-8-sig")
        print(f"\n[✓] Успішно зібрано унікальних записів: {len(df)}")
        print(f"[✓] Артефакт збережено у файл: {target_csv}")
    else:
        print("[-] Помилка: товари не знайдено.")


if __name__ == "__main__":
    main()
