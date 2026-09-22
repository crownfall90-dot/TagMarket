"""Browser smoke for preview layout and common mobile interactions.

Run locally: python tests/ui_smoke.py
Uses the installed Playwright Chromium and fictional web/preview.json only.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import os
import tempfile
from threading import Thread

from playwright.sync_api import sync_playwright


WEB = Path(__file__).resolve().parents[1] / "web"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def fits(page):
    width, viewport = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert width <= viewport + 1, f"horizontal overflow: {width}px in {viewport}px"


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(WEB)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = os.getenv("TAGMARKETS_UI_SMOKE_URL") or f"http://127.0.0.1:{server.server_port}/"
    url = base.rstrip("/") + "/?preview=1"
    screenshots = Path(tempfile.gettempdir())
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 390, 768, 1280):
                    page = browser.new_page(viewport={"width": width, "height": 844})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.route("https://telegram.org/js/telegram-web-app.js",
                               lambda route: route.fulfill(status=200,
                                   content_type="application/javascript", body=""))
                    page.goto(url + "#overview", wait_until="domcontentloaded")
                    page.locator(".hero").wait_for()
                    page.locator('#toast').evaluate("el => el.classList.remove('visible')")
                    assert page.get_by_text("Сегодня · все мои счета").count() == 1
                    page.locator('#notifications').click()
                    assert page.locator('.notification-item').count() == 1
                    page.locator('#dialog button[value="cancel"]').last.click()
                    today_result = page.locator('.chart-panel .result-pair b').inner_text()
                    assert page.locator('.chart-panel .chart-meta').get_by_text('1').count() >= 1
                    page.locator('.chart-panel [data-action="period"][data-value="month"]').click()
                    page.locator('.chart-panel [data-action="period"][data-value="month"].active').wait_for()
                    assert page.locator('.chart-panel .result-pair b').inner_text() != today_result
                    page.locator('.chart-panel [data-action="period"][data-value="today"]').click()
                    page.locator('.chart-panel [data-action="period"][data-value="today"].active').wait_for()
                    fits(page)
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-overview-smoke.png"), full_page=True)
                    page.locator('[data-action="strategy-info"]').click()
                    page.get_by_text('SONIC · стратегия и риски').wait_for()
                    assert page.get_by_text('РИСК И КОНТРОЛЬ').count() == 1
                    page.locator('#dialog button[value="cancel"]').last.click()

                    nav = "#mobile-nav" if width < 740 else "#desktop-nav"
                    page.locator(f'{nav} a[href="#deals"]').click()
                    page.locator(".deal-days").wait_for()
                    assert page.locator(".deal-row").count() == 8
                    assert page.locator(".deals-overview .result-pair small").count() == 1
                    fits(page)
                    if width == 390:
                        page.wait_for_timeout(550)
                        shot = screenshots / "tagmarkets-mobile-deals-smoke.png"
                        page.screenshot(path=str(shot), full_page=True)
                        print("Mobile screenshot:", shot)
                    page.locator('.deal-highlight[data-value="lastweek"]').click()
                    page.locator('.deal-highlight[data-value="lastweek"].active').wait_for()
                    assert page.locator('.deals-overview .result-pair b').count() == 1
                    page.locator('[data-action="kind"][data-value="archive"]').click()
                    page.locator('.archive-panel').wait_for()
                    page.locator('[data-action="kind"][data-value="moves"]').click()
                    page.locator('[data-action="kind"][data-value="moves"].active').wait_for()
                    page.locator('[data-action="kind"][data-value="trades"]').click()
                    fits(page)

                    page.locator(f'{nav} a[href="#accounts"]').click()
                    page.locator('.account-list').first.wait_for()
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-accounts-smoke.png"), full_page=True)
                    page.locator('[data-action="add"]').first.click()
                    choice = page.locator("#add-cabinet-choice")
                    choice.wait_for()
                    assert choice.locator("option").count() == 2
                    assert not page.locator("#add-new-cabinet").is_visible()
                    choice.select_option("new")
                    assert page.locator("#add-new-cabinet").is_visible()
                    assert page.locator('#add-new-cabinet input').is_enabled()
                    choice.select_option("CUDEMO1")
                    assert not page.locator("#add-new-cabinet").is_visible()
                    assert not page.locator('#add-new-cabinet input').is_enabled()
                    page.locator('#dialog button[value="cancel"]').last.click()
                    page.locator('a[href="#account/10001"]').first.click()
                    page.locator('.detail-hero').wait_for()
                    assert page.locator('.detail-identity span').count() == 4
                    assert page.locator('.detail-results .detail-result').count() == 3
                    assert page.locator('.detail-strategy').count() == 1
                    assert page.locator('.license-card .license-actions a').count() == 2
                    assert page.locator(f'{nav} a[href="#accounts"].active').count() == 1
                    sonic_result = page.locator('.detail-chart .result-pair b').inner_text()
                    page.locator('#account-select').select_option('10002')
                    page.locator('.detail-hero h1').get_by_text('NEO.FX').wait_for()
                    assert page.locator('.detail-chart .result-pair b').inner_text() != sonic_result
                    page.locator('#account-select').select_option('10001')
                    page.locator('.detail-hero h1').get_by_text('SONIC').wait_for()
                    page.locator('[data-action="account-settings"]').first.click()
                    assert page.locator('#dialog input[name="trades"]').count() == 1
                    page.locator('#dialog button[value="cancel"]').last.click()
                    fits(page)
                    if width == 390:
                        page.wait_for_timeout(400)
                        shot = screenshots / "tagmarkets-mobile-account-smoke.png"
                        page.screenshot(path=str(shot), full_page=True)
                        print("Mobile account screenshot:", shot)
                    page.locator(f'{nav} a[href="#settings"]').click()
                    page.locator('[data-action="broadcast"]').wait_for()
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-settings-smoke.png"), full_page=True)
                    page.locator('[data-action="shortcut"]').click()
                    assert page.locator('#dialog-title').inner_text() == 'Ярлык Tag Markets'
                    page.locator('#dialog button[value="cancel"]').last.click()
                    page.locator('[data-action="partner-link"]').click()
                    assert page.locator('#dialog input[name="url"]').count() == 1
                    page.locator('#dialog button[value="cancel"]').last.click()
                    page.locator('[data-action="broadcast"]').click()
                    area = page.locator('#dialog textarea[name="text"]')
                    area.wait_for()
                    area.fill('Обновление для пользователей')
                    assert page.locator('#compose-live').inner_text() == 'Обновление для пользователей'
                    assert page.locator('#compose-count').inner_text().startswith(
                        f'{len("Обновление для пользователей")} /')
                    area.evaluate('(el) => {el.selectionStart = 0; el.selectionEnd = 10;}')
                    page.locator('[data-format="bold"]').click()
                    assert page.locator('#compose-live b').count() == 1
                    page.locator('#dialog input[name="media"]').set_input_files({
                        "name": "photo.png", "mimeType": "image/png",
                        "buffer": base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9YbZT5cAAAAASUVORK5CYII=")})
                    assert "photo.png" in page.locator('#compose-file-name').inner_text()
                    page.locator('#dialog-submit').click()
                    page.get_by_text('Проверка рассылки').wait_for()
                    assert page.locator('.compose-preview-media img').count() == 1
                    assert page.locator('.compose-preview-media img').evaluate('(el) => el.complete && el.naturalWidth > 0')
                    if width == 390:
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-broadcast-smoke.png"))
                    fits(page)
                    page.locator('#dialog button[value="cancel"]').last.click()
                    page.locator(f'{nav} a[href="#people"]').click()
                    page.locator('.people-card').first.wait_for()
                    page.locator('[data-action="guest-detail"]').first.click()
                    page.get_by_text('Карточка гостя').wait_for()
                    page.locator('#dialog button[value="cancel"]').last.click()
                    page.locator('[data-action="invite"]').click()
                    assert page.locator('#dialog-title').inner_text() == 'Приглашение в Telegram'
                    page.locator('#dialog button[value="cancel"]').last.click()
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-people-smoke.png"), full_page=True)
                    fits(page)
                    # тем без гаммы (light) больше нет — приложение всегда тёмное;
                    # переключатель живёт в Настройках как выбор из трёх схем
                    page.locator(f'{nav} a[href="#settings"]').click()
                    page.locator('.scheme-picker').wait_for()
                    page.locator('.scheme[data-value="velvet"]').click()
                    assert page.locator('html').get_attribute('data-scheme') == 'velvet'
                    page.locator(f'{nav} a[href="#overview"]').click()
                    page.locator('.hero').wait_for()
                    assert page.locator('.chart-panel [data-value="today"].active').count() == 1
                    assert page.locator('.chart-panel .chart-meta span').first.locator('b').inner_text() == '1'
                    fits(page)
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-velvet-smoke.png"), full_page=True)
                    assert not errors, errors
                    page.close()
                print("UI smoke PASS: 320px, 390px, 768px and 1280px")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
