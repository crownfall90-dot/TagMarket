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


def close_dialog(page):
    """Закрыть диалог крестиком в шапке: у информационных окон кнопка
    «Отмена» спрятана, а крестик есть у всех."""
    page.locator('#dialog .dialog-head button[value="cancel"]').click()
    page.locator('#dialog[open]').wait_for(state="detached")


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
                    page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                    page.route("https://telegram.org/js/telegram-web-app.js",
                               lambda route: route.fulfill(status=200,
                                   content_type="application/javascript", body=""))
                    page.goto(url + "#overview", wait_until="domcontentloaded")
                    page.locator(".hero").wait_for()
                    page.locator('#toast').evaluate("el => el.classList.remove('visible')")
                    assert page.locator(".hero .hero-value").inner_text().strip()
                    # лента: четыре события предпросмотра, два из них не прочитаны
                    page.locator('#notifications').click()
                    assert page.locator('.notification-item').count() == 4
                    assert page.locator('.notification-item.unread').count() == 2
                    close_dialog(page)
                    # динамика: другой период — другой итог
                    result = page.locator('.chart-panel .dynamics-main .result-pair b')
                    today_result = result.inner_text()
                    page.locator('.chart-panel [data-action="period"][data-value="month"]').click()
                    page.locator('.chart-panel [data-action="period"][data-value="month"].active').wait_for()
                    assert result.inner_text() != today_result
                    page.locator('.chart-panel [data-action="period"][data-value="today"]').click()
                    page.locator('.chart-panel [data-action="period"][data-value="today"].active').wait_for()
                    # график цены SONIC: свечи и отметки сделок
                    page.locator('.price-chart-panel svg').wait_for()
                    assert page.locator('.price-chart-panel .price-marker').count() == 4
                    fits(page)
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-overview-smoke.png"), full_page=True)
                    # частые вопросы о стратегии — отдельный экран с возвратом
                    page.locator('a.faq-link').click()
                    page.locator('.strategy-faq').wait_for()
                    assert page.locator('.faq-item').count() >= 8
                    page.locator('a.back[href="#overview"]').click()
                    page.locator('.hero').wait_for()

                    nav = "#mobile-nav" if width < 740 else "#desktop-nav"
                    page.locator(f'{nav} a[href="#accounts"]').click()
                    page.locator('.account-list').first.wait_for()
                    # два личных кабинета и общий счёт для наблюдения
                    assert page.locator('.account-group').count() == 3
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-accounts-smoke.png"), full_page=True)
                    page.locator('[data-action="add"]').first.click()
                    choice = page.locator("#add-cabinet-choice")
                    choice.wait_for()
                    assert choice.locator("option").count() == 3
                    assert not page.locator("#add-new-cabinet").is_visible()
                    choice.select_option("new")
                    assert page.locator("#add-new-cabinet").is_visible()
                    assert page.locator('#add-new-cabinet input').is_enabled()
                    choice.select_option("CUDEMO1")
                    assert not page.locator("#add-new-cabinet").is_visible()
                    assert not page.locator('#add-new-cabinet input').is_enabled()
                    close_dialog(page)
                    page.locator('a[href="#account/10001"]').first.click()
                    page.locator('.detail-hero').wait_for()
                    assert page.locator('.detail-identity span').count() == 2
                    assert page.locator('.detail-cells .detail-cell').count() == 3
                    assert page.locator(f'{nav} a[href="#accounts"].active').count() == 1
                    # сделки, движения и месяцы живут на самой странице счёта:
                    # отдельного раздела «Сделки» больше нет
                    page.locator(".deal-days").wait_for()
                    assert page.locator(".deal-row").count() > 0
                    page.locator('[data-action="kind"][data-value="archive"]').click()
                    page.locator('.archive-panel').wait_for()
                    page.locator('[data-action="kind"][data-value="moves"]').click()
                    page.locator('[data-action="kind"][data-value="moves"].active').wait_for()
                    page.locator('.capital-panel').wait_for()
                    assert page.locator('.move-row').count() >= 3
                    assert page.locator('.fee-card').count() == 1
                    page.locator('[data-action="kind"][data-value="trades"]').click()
                    page.locator(".deal-days").wait_for()
                    fits(page)
                    sonic_result = page.locator('.detail-chart .result-pair b').first.inner_text()
                    page.locator(f'{nav} a[href="#accounts"]').click()
                    page.locator('a[href="#account/10002"]').first.click()
                    page.locator('.detail-hero h1').get_by_text('NEO.FX').wait_for()
                    assert page.locator('.detail-chart .result-pair b').first.inner_text() != sonic_result
                    page.locator(f'{nav} a[href="#accounts"]').click()
                    page.locator('a[href="#account/10001"]').first.click()
                    page.locator('.detail-hero h1').get_by_text('SONIC').wait_for()
                    page.locator('[data-action="account-settings"]').first.click()
                    assert page.locator('#dialog input[name="trades"]').count() == 1
                    close_dialog(page)
                    fits(page)
                    if width == 390:
                        page.wait_for_timeout(400)
                        shot = screenshots / "tagmarkets-mobile-account-smoke.png"
                        page.screenshot(path=str(shot), full_page=True)
                        print("Mobile account screenshot:", shot)
                    page.locator(f'{nav} a[href="#settings"]').click()
                    page.locator('[data-action="broadcast"]').wait_for()
                    page.locator('.machine-row').first.wait_for()     # /admin подгружается следом
                    assert page.locator('.machine-row').count() == 2
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-settings-smoke.png"), full_page=True)
                    page.locator('[data-action="shortcut"]').click()
                    assert page.locator('#dialog-title').inner_text() == 'Ярлык Tag Markets'
                    close_dialog(page)
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
                    close_dialog(page)
                    page.locator(f'{nav} a[href="#people"]').click()
                    page.locator('.people-card').first.wait_for()
                    page.locator('[data-action="guest-detail"]').first.click()
                    page.get_by_text('Карточка гостя').wait_for()
                    close_dialog(page)
                    # ссылка-приглашение и партнёрская ссылка — в карточке раздела «Гости»
                    assert page.locator('.link-card .invite-url').inner_text().startswith('https://t.me/')
                    page.locator('[data-action="partner-link"]').first.click()
                    assert page.locator('#dialog input[name="url"]').count() == 1
                    close_dialog(page)
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
