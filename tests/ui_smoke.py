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


def glider_on_active(page, nav):
    """Подсветка вкладки доехала и стоит ровно под активной ссылкой панели."""
    page.wait_for_function(
        "nav => { const g = document.querySelector(nav + ' .nav-glider');"
        " return g && !g.classList.contains('is-hidden') && g.getAnimations().length === 0; }", arg=nav)
    glider, link = page.evaluate(
        "nav => [document.querySelector(nav + ' .nav-glider').getBoundingClientRect().toJSON(),"
        " document.querySelector(nav + ' a.active').getBoundingClientRect().toJSON()]", nav)
    for key in ("x", "y", "width", "height"):
        assert abs(glider[key] - link[key]) <= 1.5, (nav, key, glider, link)


def glider_survives_rerender(page, nav):
    """Фоновое обновление не должно трогать подсветку панели.

    render() идёт и по таймеру раз в 30-60 с. Пока nav() двигал подсветку
    на каждый такой проход, браузер пересчитывал вёрстку посреди кадра, в
    котором дальше целиком меняется #main, — отсюда рывки и подвисания.
    """
    # считаем не результат (он совпадёт в любом случае), а сами обращения к
    # offsetLeft: именно они заставляют браузер пересчитать вёрстку
    touched = page.evaluate(
        """nav => {
            const link = document.querySelector(nav + ' a.active');
            const proto = Object.getPrototypeOf(link);
            const original = Object.getOwnPropertyDescriptor(proto, 'offsetLeft');
            let reads = 0;
            Object.defineProperty(link, 'offsetLeft', {
                configurable: true,
                get() { reads++; return original.get.call(this); }});
            render();
            delete link.offsetLeft;
            return reads;
        }""", nav)
    assert touched == 0, (
        f"перерисовка без смены вкладки {touched} раз замерила вёрстку панели")


def topbar_sticks(page):
    """Верхняя панель остаётся на экране при прокрутке и получает тень."""
    page.evaluate("scrollTo(0, 400)")
    page.wait_for_function("document.body.classList.contains('is-scrolled')")
    box = page.locator(".topbar").bounding_box()
    assert box and box["y"] <= 1.5, f"панель уехала при прокрутке: {box}"
    page.evaluate("scrollTo(0, 0)")
    page.wait_for_function("!document.body.classList.contains('is-scrolled')")


def revisit_is_instant(page, nav):
    """Возврат в раздел, где уже были, не ходит на сервер и не перерисовывает
    экран второй раз — раньше каждый переход заново тянул все данные."""
    page.evaluate("""() => { window.__calls = [];
        window.__origApi = window.__origApi || window.api; const real = window.__origApi;
        window.api = (...a) => { window.__calls.push(a[0]); return real(...a); }; }""")
    page.locator(f'{nav} a[href="#accounts"]').click()
    page.locator('.account-list').first.wait_for()
    page.locator(f'{nav} a[href="#overview"]').click()
    page.locator('.hero').wait_for()
    page.wait_for_timeout(900)          # переход и возможная загрузка успели бы пройти
    calls = page.evaluate("window.__calls")
    assert calls == [], f"возврат в раздел снова загрузил данные: {calls}"


def quiet_refresh_keeps_screen(page):
    """Фоновое обновление с теми же данными не пересобирает экран."""
    page.evaluate("refresh(true)")
    page.wait_for_function("!state.busy")
    page.evaluate("document.querySelector('#main > *').__mark = 1")
    page.evaluate("refresh(true)")
    page.wait_for_function("!state.busy")
    kept = page.evaluate("document.querySelector('#main > *').__mark === 1")
    assert kept, "фоновое обновление без изменений перерисовало экран"


def rapid_taps_render_once(page, nav):
    """Два нажатия подряд, пока старый экран ещё уезжает: отрисовывается
    только последний раздел, и один раз — раньше новый экран мигал дважды."""
    # оба раздела уже открывались: данные в памяти, догрузки не будет
    page.evaluate("""() => { window.__realRender = window.render; window.__renders = 0;
        window.render = (...a) => { window.__renders++; return window.__realRender(...a); }; }""")
    page.locator(f'{nav} a[href="#accounts"]').click()
    page.wait_for_timeout(80)          # второе нажатие, пока старый экран уезжает
    page.locator(f'{nav} a[href="#overview"]').click()
    page.wait_for_timeout(1200)
    renders, view = page.evaluate("[window.__renders, state.view]")
    page.evaluate("window.render = window.__realRender")
    assert view == "overview", f"открылся не последний раздел: {view}"
    assert renders == 1, f"быстрые нажатия дали {renders} отрисовки вместо одной"


def rapid_switching_stays_under_limit(page, nav):
    """Частые переключения разделов и периодов не упираются в лимит сервера
    (120 запросов в минуту): раньше каждое нажатие тянуло до 4 запросов, и
    через ~30 переключений приходило «Слишком много запросов. Подождите минуту»."""
    page.evaluate("""() => { window.__calls = []; window.__origApi = window.__origApi || window.api; const real = window.__origApi;
        window.api = (...a) => { window.__calls.push(a[0]); return real(...a); }; }""")
    for _ in range(10):
        page.locator(f'{nav} a[href="#accounts"]').click()
        page.locator('.account-list').first.wait_for()
        page.locator(f'{nav} a[href="#overview"]').click()
        page.locator('.hero').wait_for()
    for _ in range(10):
        for value in ("yesterday", "today"):
            page.locator(f'.segmented button[data-value="{value}"]').first.click()
            page.wait_for_function("!document.body.classList.contains('is-loading')")
    calls = page.evaluate("window.__calls")
    # 40 нажатий: догружается только «Вчера» в первый раз (отчёт и график)
    assert len(calls) <= 4, f"{len(calls)} запросов на 40 нажатий: {calls}"


def rapid_period_taps_load_once(page):
    """Быстрые нажатия фильтров динамики: одна перерисовка и одна загрузка
    последнего выбора. Раньше каждое нажатие давало две перерисовки (каркас,
    потом данные) и свой запрос — динамика мигала много раз подряд."""
    page.evaluate("""() => { viewCache.clear();
        window.__realRender = window.render; window.__renders = 0;
        window.render = (...a) => { window.__renders++; return window.__realRender(...a); };
        window.__calls = []; window.__origApi = window.__origApi || window.api; const real = window.__origApi;
        window.api = (...a) => { window.__calls.push(a[0]); return real(...a); }; }""")
    for value in ("week", "yesterday", "month"):
        page.locator(f'.segmented button[data-value="{value}"]').first.click()
        page.wait_for_timeout(60)
    page.wait_for_function("!document.body.classList.contains('is-loading')")
    page.wait_for_timeout(300)
    renders, calls, period = page.evaluate("[window.__renders, window.__calls, state.period]")
    page.evaluate("window.render = window.__realRender")
    reports = [c for c in calls if "/report?" in c]
    assert period == "month", period
    assert renders == 1, f"{renders} перерисовки на три быстрых нажатия"
    assert len(reports) == 1 and "period=month" in reports[0], reports
    active = page.evaluate("document.querySelector('.segmented button.active').dataset.value")
    assert active == "month", f"на экране подсвечен {active}"


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
                    # подсветка переезжает сразу, цифры приходят следом — ждём загрузку
                    page.wait_for_function("!document.body.classList.contains('is-loading')")
                    assert result.inner_text() != today_result
                    page.locator('.chart-panel [data-action="period"][data-value="today"]').click()
                    page.locator('.chart-panel [data-action="period"][data-value="today"].active').wait_for()
                    page.wait_for_function("!document.body.classList.contains('is-loading')")
                    # график цены SONIC: свечи и отметки сделок
                    page.locator('.price-chart-panel svg').wait_for()
                    # сделки как в MT5: стрелка входа, кольцо выхода, пунктир между ними
                    assert page.locator('.price-chart-panel .trade-in').count() == 3
                    assert page.locator('.price-chart-panel .trade-out').count() == 3
                    assert page.locator('.price-chart-panel .trade-link').count() == 3
                    # отметки стоят на цене сделки внутри графика, а не прибиты к краю
                    inside = page.evaluate("""() => { const box = document.querySelector('.price-chart-wrap').getBoundingClientRect();
                        return [...document.querySelectorAll('.trade-layer i')].every(el => { const r = el.getBoundingClientRect();
                            const cy = r.top + r.height / 2; return cy > box.top + 4 && cy < box.bottom - 4; }); }""")
                    assert inside, "отметки сделок вышли за график"
                    # вход подписан «Покупка/Продажа», выход — сделкой, которой закрыли
                    tags = page.locator('.trade-layer .trade-tag').all_inner_texts()
                    assert any(t.startswith('Покупка') for t in tags) and any(t.startswith('Продажа') for t in tags), tags
                    assert page.locator('.trade-list li').count() == 3
                    assert page.locator('.time-axis span').count() == 5
                    # масштаб и листание: окно свечей меняется, отметки остаются
                    full = page.evaluate("chartView.count")
                    page.locator('[data-action="chart-zoom"][data-value="in"]').click()
                    page.wait_for_function("c => chartView.count < c", arg=full)
                    zoomed_start = page.evaluate("chartView.start")
                    page.locator('.price-chart-wrap').scroll_into_view_if_needed()
                    box = page.locator('.price-chart-wrap').bounding_box()
                    page.mouse.move(box["x"] + box["width"] * .3, box["y"] + box["height"] / 2)
                    page.mouse.down()
                    page.mouse.move(box["x"] + box["width"] * .6, box["y"] + box["height"] / 2, steps=5)
                    page.mouse.up()
                    page.wait_for_function("s => chartView.start < s", arg=zoomed_start)
                    page.locator('[data-action="chart-zoom"][data-value="reset"]').click()
                    page.wait_for_function("c => chartView.count === c", arg=full)
                    assert page.locator('.price-chart-panel .trade-in').count() == 3
                    circle = page.locator('.trade-layer .trade-out').first.bounding_box()
                    assert abs(circle["width"] - circle["height"]) < 0.5, f"кольцо выхода сплющено: {circle}"
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
                    glider_on_active(page, nav)
                    glider_survives_rerender(page, nav)
                    topbar_sticks(page)
                    revisit_is_instant(page, nav)
                    quiet_refresh_keeps_screen(page)
                    rapid_taps_render_once(page, nav)
                    page.locator('.hero').wait_for()
                    rapid_switching_stays_under_limit(page, nav)
                    rapid_period_taps_load_once(page)
                    page.locator('.segmented button[data-value="today"]').first.click()
                    page.wait_for_function("!document.body.classList.contains('is-loading')")
                    page.locator(f'{nav} a[href="#accounts"]').click()
                    page.locator('.account-list').first.wait_for()
                    glider_on_active(page, nav)
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
                    glider_on_active(page, nav)
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
                    glider_on_active(page, nav)
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
                    glider_on_active(page, nav)
                    # «уменьшить движение» в системе: подсветка и экран меняются без анимаций
                    page.emulate_media(reduced_motion="reduce")
                    page.locator(f'{nav} a[href="#people"]').click()
                    page.locator('.people-card').first.wait_for()
                    assert page.evaluate(
                        "nav => document.querySelector(nav + ' .nav-glider').getAnimations().length"
                        " + document.querySelector('#main').getAnimations().length", nav) == 0
                    glider_on_active(page, nav)
                    page.emulate_media(reduced_motion="no-preference")
                    page.locator(f'{nav} a[href="#overview"]').click()
                    page.locator('.hero').wait_for()
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
