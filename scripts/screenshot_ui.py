"""截取当前前端UI各页面截图"""

from playwright.sync_api import sync_playwright
import os

os.makedirs("/tmp/ui_screenshots", exist_ok=True)

pages_to_capture = [
    ("/", "home_stocklist"),
    ("/backtest", "backtest"),
    ("/portfolio", "portfolio"),
]

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        channel="chrome",
    )
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    for path, name in pages_to_capture:
        page.goto(f"http://localhost:3001{path}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        page.screenshot(path=f"/tmp/ui_screenshots/{name}.png", full_page=True)
        print(f"captured: {name}")

    browser.close()
    print("done")
