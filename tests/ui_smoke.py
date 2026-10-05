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
WIDTHS = tuple(int(w) for w in os.getenv("TAGMARKETS_UI_SMOKE_WIDTHS", "320,390,768,1280").split(","))


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
    assert box and box["y"] <= 12, f"панель уехала при прокрутке: {box}"   # плавающая «таблетка» с отступом 8 px сверху
    radius = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.topbar')).borderTopLeftRadius)")
    assert radius >= 20, f"верхняя панель должна быть скруглённой, как нижняя: {radius}"
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
    # оба нажатия — из страницы, с паузой 50 мс: время самих кликов Playwright не должно
    # сдвигать второе нажатие за конец ухода старого экрана
    page.evaluate("""([nav]) => new Promise(resolve => {
        document.querySelector(nav + ' a[href="#accounts"]').click();
        setTimeout(() => { document.querySelector(nav + ' a[href="#overview"]').click(); resolve(); }, 50);
    })""", [nav])
    page.wait_for_timeout(1200)
    renders, view = page.evaluate("[window.__renders, state.view]")
    page.evaluate("window.render = window.__realRender")
    assert view == "overview", f"открылся не последний раздел: {view}"
    assert renders == 1, f"быстрые нажатия дали {renders} отрисовки вместо одной"


def rapid_switching_stays_under_limit(page, nav):
    """Частые переключения разделов и периодов не упираются в лимит сервера
    (120 запросов в минуту): раньше каждое нажатие тянуло до 4 запросов, и
    через ~30 переключений приходило «Слишком много запросов. Подождите минуту»."""
    # фоновое обновление раз в 30-60 с — не переключение, в замер не входит
    page.evaluate("clearInterval(refreshTimer)")
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
    page.evaluate("""() => { clearTimeout(choiceTimer); cancelLoads(); viewCache.clear();
        window.__realRender = window.render; window.__renders = 0;
        window.render = (...a) => { window.__renders++; return window.__realRender(...a); };
        window.__calls = []; window.__origApi = window.__origApi || window.api; const real = window.__origApi;
        window.api = (...a) => { window.__calls.push(a[0]); return real(...a); }; }""")
    page.evaluate("""() => { for(const value of ['week','yesterday','month'])
        document.querySelector(`.chart-panel .segmented button[data-value="${value}"]`).click(); }""")
    page.wait_for_function("!document.body.classList.contains('is-loading')")
    page.wait_for_timeout(300)
    renders, calls, period = page.evaluate("[window.__renders, window.__calls, state.period]")
    page.evaluate("window.render = window.__realRender")
    reports = [c for c in calls if "/report?" in c]
    assert period == "month", period
    assert renders == 1, f"{renders} перерисовки на три быстрых нажатия"
    assert len(reports) == 1 and "period=month" in reports[0], reports
    active = page.evaluate("document.querySelector('.chart-panel .segmented button.active').dataset.value")
    assert active == "month", f"на экране подсвечен {active}"


def faq_opens_smoothly(page, url):
    """«Частые вопросы»: вопрос раскрывается и закрывается с анимацией
    высоты, скриншот открывается на весь экран."""
    page.goto(url + "#faq", wait_until="domcontentloaded")
    page.locator(".faq-page").wait_for()
    # раздел называется коротко, без мелкой «справки»; вопросы при входе закрыты (регистрация тоже)
    assert page.locator('.page-head h1').inner_text() == 'Вопросы и ответы'
    assert page.locator('.page-head .eyebrow').count() == 0 and page.locator('.page-head p').count() == 0
    assert page.locator('.faq-item[open]').count() == 0
    fits(page)
    item = page.locator(".faq-item").nth(1)          # «2. Верификация», закрыт
    assert not item.evaluate("el => el.open")
    item.locator("summary").click()
    animating = item.evaluate("el => el.querySelector('.faq-body').getAnimations().length")
    assert animating == 1, "вопрос открылся без анимации"
    page.wait_for_function("el => el.open && !el.querySelector('.faq-body').getAnimations().length", arg=item.element_handle())
    item.locator("summary").click()
    assert item.evaluate("el => el.querySelector('.faq-body').getAnimations().length") == 1
    page.wait_for_function("el => !el.open", arg=item.element_handle())
    strategies = page.locator('.faq-strategy')
    assert strategies.count() == 2
    assert page.get_by_role('heading', name='MetaTrader 5', exact=True).count() == 0
    assert page.locator('a[href*="metatrader"]').count() == 0
    assert page.locator('.faq-strategies.panel').count() == 0
    page.evaluate("window.__faqNode=document.querySelector('.faq-page')")
    for index in range(2):
        strategy = strategies.nth(index)
        assert not strategy.evaluate('el=>el.open')
        assert not strategy.locator('.faq-shots').is_visible()
        assert strategy.locator('.when-closed').is_visible()
        before = strategy.bounding_box()['height']
        strategy.locator('summary').click()
        page.wait_for_function("el=>el.open&&!el.querySelector('.faq-body').getAnimations().length", arg=strategy.element_handle())
        assert strategy.bounding_box()['height'] > before + 100
        assert strategy.locator('.when-open').is_visible()
        assert strategy.locator('.faq-facts li').count() == 6
        assert strategy.locator('img').first.get_attribute('loading') == 'lazy'
        assert strategy.locator('img').first.get_attribute('alt')
        fits(page)
        strategy.locator('.faq-shot').first.click()
        page.locator('#dialog[open] .faq-full').wait_for()
        fits(page)
        close_dialog(page)
        strategy.locator('summary').click()
        page.wait_for_function('el=>!el.open', arg=strategy.element_handle())
        assert abs(strategy.bounding_box()['height'] - before) < 2
    assert page.evaluate("document.querySelector('.faq-page')===window.__faqNode")
    page.emulate_media(reduced_motion='reduce')
    strategies.first.locator('summary').click()
    assert strategies.first.evaluate('el=>el.open&&!el.querySelector(".faq-body").getAnimations().length')
    strategies.first.locator('summary').click()
    page.emulate_media(reduced_motion='no-preference')
    if page.viewport_size['width'] == 390:
        page.evaluate('scrollTo(0,0)')
        page.wait_for_function("!document.querySelector('#main').getAnimations({subtree:true}).some(a=>a.playState==='running')")
        page.screenshot(path=str(Path(tempfile.gettempdir()) / 'tagmarkets-faq-compact-390.png'), full_page=True)
    page.goto(url + '#accounts', wait_until='domcontentloaded')
    page.locator('.page-head [data-action="add"]').click()
    assert page.locator('#dialog-title').inner_text() == 'Подключить счёт MT5'
    assert page.locator('#dialog-submit').inner_text() == 'Подключить'
    assert page.locator('#dialog input[name="password"]').get_attribute('type') == 'password'
    fits(page)
    page.locator('#dialog .account-help').click()
    page.wait_for_function("location.hash==='#faq/connect'&&!document.querySelector('#dialog').open")
    page.locator('#faq-connect').wait_for()
    assert page.locator('.faq-item[open]').count() == 1      # по ссылке «как подключить» регистрация раскрыта
    page.wait_for_function("document.querySelector('#faq-connect').getBoundingClientRect().top<150")
    assert page.locator('#faq-connect h2').inner_text() == 'Подключение по шагам'
    assert page.locator('#faq-connect .faq-item').first.evaluate('el=>el.open')
    assert not page.locator('#faq-connect .faq-item').nth(1).evaluate('el=>el.open')
    fits(page)


def guest_with_shared_account_sees_home_and_opens_guide_on_demand(page):
    """Shared-счёт остаётся на обычной главной; короткая инструкция
    открывается вручную, а её CTA использует существующую форму добавления."""
    page.evaluate("""() => {
        window.__smokeSavedData = structuredClone(state.data);
        const shared = {...state.data.accounts[0], shared:true, shared_by:'1'};
        state.data.accounts = [shared]; state.data.totals = {};
        state.data.onboarding = {needed:true, later:false, progress:{}};
        state.view = 'overview'; render();
    }""")
    page.locator(".hero").wait_for()
    assert page.locator(".account-card").count() == 1
    assert page.locator(".resume-banner").count() == 1
    assert page.locator(".own-guide").count() == 0
    assert page.locator('.page-head [data-action="onboard-open"] .button-label').inner_text() == "Добавить свой счёт"
    page.locator('.page-head [data-action="onboard-open"]').click()
    page.locator(".own-guide").wait_for()
    assert page.evaluate("location.hash !== '#onboarding'")
    fits(page)
    page.locator('[data-action="onboard-close"]').click()
    page.locator(".hero").wait_for()
    page.locator('[data-action="onboard-open"]').first.click()
    page.locator(".own-guide").wait_for()
    assert page.locator(".own-step").count() == 3
    page.locator('[data-action="add"]').click()
    assert page.locator("#dialog-title").inner_text() == "Подключить счёт MT5"
    close_dialog(page)
    page.locator('[data-action="onboard-close"]').click()
    page.locator(".hero").wait_for()
    assert page.locator(".account-card").count() == 1
    page.evaluate("render()")
    assert page.locator(".own-guide").count() == 0
    page.evaluate("""() => {
        state.data.accounts = [{...state.data.accounts[0], shared:false, shared_by:null}];
        state.data.onboarding.needed = false;
        state.data.totals = {USD:{capital:321,pnl:0,month:0,today:0}};
        render();
    }""")
    assert page.locator(".hero").count() == 1
    assert page.locator(".resume-banner").count() == 0
    assert page.locator('.page-head [data-action="add"]').count() == 0  # на главной нет кнопки «Добавить счёт»
    page.evaluate("state.data=window.__smokeSavedData;delete window.__smokeSavedData;state.view='overview';render()")


def projects_ui(page, nav):
    page.locator(f'{nav} a[href="#projects"]').click()
    page.locator('.project-card').first.wait_for()
    assert page.locator(f'{nav} a[data-tab]').count() == 5
    assert page.locator('.project-card').count() == 3  # TagMarket плюс два preview-проекта
    assert 'Плюс за' in page.locator('.project-card.system-project').inner_text()
    # доходность проекта: процент или фиксированная сумма
    page.locator('[data-action="project-create"]').first.click()
    page.locator('.project-form [name="income_mode"]').wait_for()
    assert page.locator('.project-form .income-percent').is_visible()
    assert not page.locator('.project-form .income-fixed').is_visible()
    page.locator('.project-form [name="income_mode"]').select_option('fixed')
    assert page.locator('.project-form .income-fixed').is_visible()
    assert not page.locator('.project-form .income-percent').is_visible()
    close_dialog(page)
    glider_on_active(page, nav)
    fits(page)
    page.locator('a[href="#project/preview-home"]').click()
    page.locator('[data-action="project-edit"]').click()
    # в окне проекта — только настройки проекта: аккаунты правятся на странице проекта
    assert page.locator('.project-form-account').count() == 0
    assert page.locator('[data-action="project-form-add"]').count() == 0
    assert '10' in page.locator('.project-form-total').inner_text()
    assert page.locator('.project-form [name="currency"]').count() == 0   # валюту проекта не меняют — поля нет
    assert page.locator('.project-form [name="multi"]').count() == 0      # режима «несколько аккаунтов» нет
    fits(page)
    close_dialog(page)
    page.locator('a.back[href="#projects"]').click()
    page.locator('a[href="#project/preview-private"]').click()
    page.locator('.project-account').first.wait_for()
    assert page.locator('.project-account').count() == 3
    page.locator('[data-action="project-account-add"]').click()
    page.locator('#dialog input[name="amount"]').fill('999999999999.99')
    fits(page)
    close_dialog(page)
    page.locator('[data-action="project-account-edit"]').nth(1).click()
    assert page.locator('#dialog input[name="amount"]').input_value() == '3000'
    # капитализация аккаунта — переключатель; по умолчанию как в проекте (здесь выключена)
    assert page.locator('#dialog select[name="capitalization"]').count() == 0
    assert not page.locator('#dialog .cap-switch input').is_checked()
    assert page.locator('#dialog .account-cap-date').is_hidden()
    page.locator('#dialog .cap-switch input').check()
    assert page.locator('#dialog .account-cap-date').is_visible()      # у проекта выключена: нужна дата начала
    assert page.locator('#dialog input[name="capitalization_from"]').input_value() != ''
    page.locator('#dialog .cap-switch input').uncheck()
    assert page.locator('#dialog .account-cap-date').is_hidden()
    # капитализация стоит перед бонусом и без пояснения «по умолчанию как в проекте»
    assert 'По умолчанию' not in page.locator('#dialog').inner_text()
    assert page.evaluate("(() => { const c = document.querySelector('#dialog .cap-switch'), b = document.querySelector('#dialog .bonus-toggle'); return !!(c.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING); })()")
    assert '(необязательно)' not in page.locator('#dialog .bonus-fields').inner_text()
    # бонус спрятан за пунктом «Бонусный баланс»: у аккаунта без бонуса поля скрыты
    assert not page.locator('#dialog [data-bonus-toggle]').is_checked()
    assert page.locator('#dialog .bonus-fields').is_hidden()
    # фиксированная доплата аккаунту: поле в окне и метка в карточке
    assert page.locator('#dialog input[name="fixed_income"]').input_value() == '60'
    assert page.locator('.pa-card .pa-tags i.fix').count() == 1
    # порядок аккаунтов: номер в списке и выбор позиции в окне редактирования
    assert page.locator('.project-account-number').count() == 3
    assert page.locator('#dialog select[name="position"]').count() == 0  # порядок меняют перетаскиванием
    fits(page)
    close_dialog(page)

    page.evaluate(r"""() => { window.__reorderCalls = []; window.__ordApi = window.api;
        window.api = async (path, options = {}) => {
          if (path.endsWith('/accounts/reorder')) { __reorderCalls.push(JSON.parse(options.body));
            return structuredClone(state.projects.find(x => x.id === 'preview-private')); }
          return __ordApi(path, options); }; }""")
    # перетаскивание: третью карточку (Резерв) ставим на первое место
    grips = page.locator('.pa-card .pa-grip')
    assert grips.count() == 3
    grips.nth(2).scroll_into_view_if_needed()
    third = grips.nth(2).bounding_box()
    first = page.locator('.pa-card').first.bounding_box()
    page.mouse.move(third['x'] + third['width'] / 2, third['y'] + third['height'] / 2)
    page.mouse.down()
    page.mouse.move(third['x'] + 4, first['y'] + 8, steps=12)
    assert page.locator('.pa-card.is-dragging').count() == 1
    page.mouse.up()
    page.wait_for_function('__reorderCalls.length === 1')
    assert page.evaluate('__reorderCalls[0].position') == 1
    assert page.locator('#dialog[open]').count() == 0  # отпускание ручки не открывает окно аккаунта
    # клавиатура: Alt+↓ на первой карточке сдвигает её на вторую позицию
    page.locator('.pa-card').first.focus()
    page.keyboard.press('Alt+ArrowDown')
    page.wait_for_function('__reorderCalls.length === 2')
    assert page.evaluate('__reorderCalls[1].position') == 2
    page.evaluate('window.api = __ordApi; void 0')
    page.locator('[data-action="project-account-edit"]').nth(2).click()
    page.locator('[data-action="project-account-delete"]').click()
    page.wait_for_function("document.querySelector('#dialog-title').textContent.includes('Удалить аккаунт')")
    assert 'Резерв' in page.locator('#dialog-title').inner_text()
    close_dialog(page)
    page.locator('[data-action="project-delete"]').click()
    assert 'Private Invest' in page.locator('#dialog-title').inner_text()
    close_dialog(page)
    page.locator('a.back[href="#projects"]').click()
    page.locator('[data-action="project-create"]').click()
    assert page.locator('.project-form [name="multi"]').count() == 0
    assert page.locator('.project-form-account').count() == 1
    assert page.locator('[data-action="project-form-add"]').count() == 0
    assert page.locator('.project-form [name="currency"] option').all_text_contents() == ['USD', 'RUB', 'BYN']
    page.locator('.project-form input[name="name"]').fill('Long project name ' * 4)
    page.locator('.project-form [name="rate_percent"]').fill('2.5')
    page.locator('.project-form-account input[name^="account-amount-"]').fill('10000')
    page.locator('.project-form [name="period"]').select_option('day')
    assert page.locator('.daily-accrual-setting').is_visible()
    page.locator('.project-form [name="business_days_only"]').select_option('1')
    page.locator('.project-form [name="capitalization"]').check()
    start = page.locator('.project-form [name="capitalization_from"]').input_value()
    yesterday = page.evaluate("d=>new Date(Date.parse(d+'T00:00:00Z')-86400000).toISOString().slice(0,10)", start)
    page.locator('.project-form [name="capitalization_from"]').fill(yesterday)
    total_preview = page.locator('.project-form-total').inner_text()
    assert 'Вложено' in total_preview and '10' in total_preview, total_preview
    fits(page)
    # Только ответы UI-теста: реальная безопасность и расчёты проверяются API-тестами.
    page.evaluate("""() => { window.__projectUiApi=window.api;
        window.api=async (path,options={}) => {
            if(path==='/projects'&&!options.method)return {projects:state.projects};
            if(path==='/projects/ui-created/accounts'&&options.method==='POST'){
                const d=JSON.parse(options.body);window.__accountUiSaved=d;
                const prev=structuredClone(state.projects.find(p=>p.id==='ui-created'));
                prev.accounts.push({...d,id:'ui-account-1',project_id:'ui-created',position:prev.accounts.length+1,current_amount:d.amount,bonus_active:false,bonus_status:null,bonus_current_amount:0,working_amount:d.amount,expected_income:0});
                return prev;
            }
            if((path==='/projects'||path==='/projects/ui-created')&&['POST','PATCH'].includes(options.method)){
                const raw=JSON.parse(options.body);window.__projectUiSaved=raw;
                const d=options.method==='PATCH'?{...structuredClone(state.projects.find(p=>p.id==='ui-created')),...raw}:raw;
                const total=d.accounts.reduce((s,a)=>s+a.amount,0);
                const current_total=d.capitalization?total*(1+d.rate_percent/100):total;
                return {...d,id:'ui-created',accounts:d.accounts.map((a,i)=>({...a,id:a.id||'ui-account-'+i,project_id:'ui-created',current_amount:d.capitalization?a.amount*(1+d.rate_percent/100):a.amount,bonus_active:false,bonus_status:null,bonus_current_amount:0,working_amount:a.amount,expected_income:a.amount*d.rate_percent/100})),total,current_total,personal_total:current_total,bonus_total:0,expired_bonus_total:0,working_total:current_total,has_capitalization:current_total!==total,calculation_limited:false,expected_income:current_total*d.rate_percent/100};
            }
            if(path==='/projects/ui-created'&&options.method==='DELETE')return {ok:true};
            return window.__projectUiApi(path,options);
        };
    }""")
    page.locator('#dialog-submit').click()
    page.wait_for_function("state.view==='project'&&state.projectId==='ui-created'")
    page.locator('[data-action="project-edit"]').wait_for()
    assert 'Расчётная сумма сейчас' in page.locator('.project-detail-summary').inner_text()
    saved = page.evaluate('window.__projectUiSaved')
    assert saved['accounts'][0]['amount'] == 10000 and not saved['multi'] and saved['capitalization']
    assert saved['business_days_only']
    page.locator('[data-action="project-edit"]').click()
    page.locator('.project-form input[name="name"]').fill('Renamed project')
    page.locator('#dialog-submit').click()
    page.wait_for_function("window.__projectUiSaved?.name === 'Renamed project'")
    page.locator('.project-account').first.wait_for()
    saved = page.evaluate('window.__projectUiSaved')
    assert 'accounts' not in saved and saved['currency'] == 'USD'   # правка проекта не трогает аккаунты и валюту
    assert page.locator('[data-action="project-account-add"]').count() == 1
    assert page.locator('.project-accounts-head [data-action="project-account-add"]').count() == 0   # кнопка под списком
    # второй аккаунт добавляется на странице проекта, вместе с бонусом
    page.locator('[data-action="project-account-add"]').click()
    page.locator('#dialog[open]').wait_for()
    assert page.locator('[data-action="project-account-add"]').count() == 1
    assert page.locator('[data-action="project-account-add"]').is_hidden()   # пока аккаунт заполняют, второй кнопки нет
    page.locator('#dialog input[name="amount"]').fill('3000')
    assert page.locator('#dialog .bonus-fields').is_hidden()
    page.locator('#dialog [data-bonus-toggle]').check()
    assert page.locator('#dialog .bonus-fields').is_visible()
    assert page.evaluate("document.activeElement?.name !== 'bonus_amount'")   # клавиатура на телефоне сама не открывается
    page.locator('#dialog input[name="bonus_amount"]').fill('500')
    page.locator('#dialog input[name="bonus_expires_at"]').fill('2031-01-01T12:00')
    page.locator('#dialog input[name="bonus_capitalization"]').check()
    page.locator('#dialog-submit').click()
    page.wait_for_function("window.__accountUiSaved")
    account = page.evaluate('window.__accountUiSaved')
    assert account['amount'] == 3000 and account['bonus_amount'] == 500 and account['bonus_capitalization']
    assert account['bonus_expires_at'].startswith('2031-01-01')
    page.wait_for_function("document.querySelectorAll('.project-account').length === 2")
    page.locator('[data-action="project-delete"]').click()
    page.locator('#dialog-submit').click()
    page.wait_for_function("state.view==='projects'&&!state.projects.some(p=>p.id==='ui-created')")
    assert 'Ваши средства' in page.locator('.project-card').filter(has_text='Недвижимость').inner_text()
    assert 'Рабочий капитал' in page.locator('.project-card').filter(has_text='Private Invest').inner_text()
    assert 'Бонус активен' in page.locator('.project-card').filter(has_text='Private Invest').inner_text()
    private_card=page.locator('.project-card').filter(has_text='Private Invest')
    assert 'Бонус завершён' in private_card.inner_text(), private_card.inner_text()
    # доходность везде в день, в том числе у TagMarket
    cards = page.locator('.project-card')
    for i in range(cards.count()):
        assert '/ день' in cards.nth(i).inner_text(), cards.nth(i).inner_text()
    assert 'Открыть счета' not in page.locator('.system-project').inner_text()
    assert 'только по будням' in page.locator('.system-project').inner_text()
    page.locator('a.forecast-link').click()
    page.locator('.forecast-result').wait_for()
    assert page.locator('.forecast-summary-values').count() == 1
    assert page.locator('[data-action="forecast-calculate"]').count() == 0   # пересчёт идёт сам
    assert page.locator('.forecast-milestones .feed-day').count() >= 2
    # период «с — по»: считаем со стартовой даты, а не с сегодняшнего дня
    start = page.evaluate("forecastDate('1w')")
    page.locator('#forecast-from').fill(start)
    page.wait_for_function("v => state.forecast.from === v && !!state.forecast.fromResult", arg=start)
    page.wait_for_function("document.querySelector('.forecast-summary-values')?.innerText.includes('Прирост за период')")
    assert page.locator('.forecast-milestones .feed-day').count() == 2
    assert page.locator('#forecast-date').get_attribute('min') == start
    page.locator('#forecast-from').fill(page.evaluate("projectToday()"))
    page.wait_for_function("state.forecast.from === '' && !state.forecast.fromResult")
    page.wait_for_function("document.querySelector('.forecast-summary-values')?.innerText.includes('Расчётный прирост')")
    # бонус заканчивается 17 декабря: на горизонте «3 месяца» это событие по дороге, на «1 месяц» — нет
    page.locator('[data-action="forecast-horizon"][data-value="3m"]').click()
    page.wait_for_function("document.querySelectorAll('.forecast-events li').length >= 1")
    assert 'Закончится бонус' in page.locator('.forecast-events').inner_text()
    page.locator('[data-action="forecast-horizon"][data-value="1m"]').click()
    page.wait_for_function("state.forecast.horizon==='1m'&&document.querySelectorAll('.forecast-events li').length===0")
    assert page.locator('.forecast-table, .forecast-table-wrap').count() == 0          # таблицы нет: карточки проектов
    assert page.locator('.fc-card').count() >= 3 and page.locator('.fc-card .fc-steps span').count() >= 9
    # TagMarket — такой же проект в списке, таблице и карточках, без отдельного блока
    assert page.locator('.forecast-tag, .forecast-tag-grid').count() == 0
    assert page.locator('input[name="forecast-project"][value="tagmarket-system"]').is_checked()
    assert '% / день' in page.locator('.fc-card').first.inner_text()
    tag_view = page.locator('.fc-card').first
    result_text = tag_view.inner_text()
    assert 'TagMarket' in result_text and '23 торговых дня' in result_text, result_text
    assert '≈' in result_text
    assert 'статистика, а не обещание' not in page.locator('.forecast-space').inner_text()
    fits(page)
    # снятая галочка убирает TagMarket из расчёта
    page.locator('.forecast-tag-row').click()
    page.wait_for_function("state.forecast.selected&&!state.forecast.selected.includes('tagmarket-system')")
    page.wait_for_function("!document.querySelector('.forecast-result')?.innerText.includes('TagMarket')")
    page.locator('.forecast-tag-row').click()
    page.wait_for_function("state.forecast.selected===null&&document.querySelector('.forecast-result')?.innerText.includes('TagMarket')")
    # мало истории: прогноз не строится, текущий капитал остаётся, сообщение понятное
    page.evaluate("state.forecast.tag={sufficient:false,days_used:3,min_days:5,multipliers:{}};render(true)")
    page.wait_for_function("document.querySelector('.forecast-result')?.innerText.includes('Недостаточно истории для прогноза')")
    result_text = page.locator('.forecast-result').inner_text()
    assert '≈' not in page.locator('.fc-card').first.inner_text()
    page.evaluate("state.forecast.tag={error:'x'};render(true)")
    assert 'Прогноз временно недоступен' in page.locator('.forecast-result').inner_text()
    page.evaluate('recalculateForecast()')
    page.wait_for_function("state.forecast.tag?.sufficient===true")
    page.locator('.fc-card .forecast-breakdown summary').first.click()
    assert page.locator('.forecast-account-detail').count() >= 1
    # анимация входа и раскрытия деталей должна завершиться: иначе кнопка
    # ещё едет, и клик попадает в соседний слой
    page.wait_for_function("!document.querySelector('#main').getAnimations({subtree:true}).some(a=>a.playState==='running')")
    page.locator('[data-action="forecast-horizon"][data-value="1d"]').click()
    page.wait_for_function("state.forecast.horizon==='1d'")
    custom_date=page.evaluate("()=>{const d=new Date(projectToday()+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+8);return d.toISOString().slice(0,10)}")
    page.locator('#forecast-date').fill(custom_date)
    page.wait_for_function("value=>state.forecast.until===value",arg=custom_date)
    page.locator('[data-action="forecast-bonus"][data-value="0"]').click()
    page.wait_for_function("state.forecast.bonus===false")
    if page.viewport_size['width'] == 390:
        assert page.locator('.forecast-mobile-card').first.is_visible()
        assert page.locator('.forecast-table-wrap').is_hidden()
    fits(page)
    page.evaluate("state.projects[0].currency='BYN';state.displayCurrency='RUB';state.data.fx=null;state.forecast.selected=null")
    page.evaluate('recalculateForecast()')
    page.wait_for_function("document.querySelector('.forecast-result')?.innerText.includes('Частично рассчитан')")
    assert 'BYN' in page.locator('.forecast-mobile-card').filter(has_not_text='TagMarket').first.inner_text()
    fits(page)
    page.locator('[data-action="forecast-back"]').click()
    page.locator('.project-card').first.wait_for()
    page.evaluate("window.api=window.__projectUiApi;state.projects[0].total=999999999999.99;state.projects[0].currency='BYN';state.projects[0].name='x'.repeat(96);render()")
    assert page.locator('.project-summary b').count() == 3
    fits(page)
    if page.viewport_size['width'] == 390:
        page.wait_for_function("!document.querySelector('#main').getAnimations({subtree:true}).some(a=>a.playState==='running')")
        page.screenshot(path=str(Path(tempfile.gettempdir()) / 'tagmarkets-mobile-projects.png'), full_page=True)
    page.evaluate("state.projects=[];render()")
    assert page.locator('.project-card').count() == 1  # торговые счета остаются отдельной карточкой
    assert page.locator('[data-action="project-create"]').count() == 1
    fits(page)



def fx_unavailable_ui(page):
    """Курс недоступен: суммы в исходной валюте, одно предупреждение, откат без reload."""
    page.evaluate("""()=>{window.__fxBackup=JSON.stringify({fx:state.data.fx,e:state.data.fx_error,d:state.displayCurrency,m:state.assetMode,p:state.projects});
      state.displayCurrency='RUB';state.assetMode='tag';state.data.fx=null;state.data.fx_error='Не удалось обновить курс НБРБ на MYFIN';render();}""")
    page.locator('.hero .fx-warning').wait_for()
    text = page.locator('#main').inner_text()
    assert 'курс недоступен' not in text, 'приписка внутри суммы'
    assert page.locator('.fx-warning').count() == 1, 'предупреждение дублируется'
    assert 'USD' in page.locator('.hero-value').inner_text() and '₽' not in page.locator('.hero-value').inner_text()
    assert 'Суммы без доступной конвертации показаны в исходной валюте' in page.locator('.fx-warning').inner_text()
    assert page.locator('.fx-warning').evaluate("el=>getComputedStyle(el).color") != 'rgb(242, 153, 153)'
    fits(page)
    # несколько валют: не складываем USD и BYN
    page.evaluate("""()=>{state.assetMode='all';state.projects=[{id:'p',name:'P',currency:'BYN',total:3200,current_total:3200,bonus_total:0}];render();}""")
    hero = page.locator('.hero').inner_text()
    assert 'Частично рассчитан' in hero and 'BYN · 3' in hero and 'USD ·' in hero, hero
    assert page.locator('.fx-warning').count() == 1
    fits(page)
    # восстановление курса без перезагрузки и смены экрана
    page.evaluate("""()=>{const b=JSON.parse(window.__fxBackup);state.data.fx={source:'MYFIN · НБРБ',provider:'myfin',stale:false,byn_per_unit:{BYN:1,USD:3,RUB:0.03}};
      state.data.fx_error='';state.assetMode='tag';state.projects=b.p;render();}""")
    assert page.locator('.fx-warning').count() == 0
    assert '₽' in page.locator('.hero-value').inner_text()
    assert page.evaluate("location.hash") == '#overview'
    # сохранённый курс — тихое предупреждение, суммы по курсу
    page.evaluate("state.data.fx={...state.data.fx,provider:'cache',stale:true,updated_at:'2026-10-02T11:20:00Z'};render()")
    assert 'последний доступный курс' in page.locator('.fx-stale').inner_text()
    fits(page)
    page.evaluate("""()=>{const b=JSON.parse(window.__fxBackup);state.data.fx=b.fx;state.data.fx_error=b.e;state.displayCurrency=b.d;state.assetMode=b.m;state.projects=b.p;render();}""")


def compact_ui_and_quiet_refresh(page, url):
    page.goto(url+'#settings', wait_until='domcontentloaded')
    page.locator('.settings-account-row').first.wait_for()
    page.evaluate("""() => { const a=state.data.accounts.find(a=>!a.demo&&!a.shared);
      state.data.accounts=Array.from({length:8},(_,i)=>({...a,login:90000+i,name:'SONIC',strategy:'Long strategy '.repeat(4),cabinet:'CU'.repeat(20),totals:i===7?null:{...a.totals,now:123456.78,cur:['USD','RUB','BYN'][i%3]}})).concat(state.data.accounts.filter(a=>a.demo||a.shared));render(); }""")
    assert page.locator('.settings-account-row').count() == 8
    assert page.locator('.settings-account-row .settings-balance').last.inner_text() == '—'
    for index in range(3):
        expected = page.evaluate("i=>money(123456.78,['USD','RUB','BYN'][i])", index)
        assert page.locator('.settings-account-row .settings-balance').nth(index).inner_text() == expected
    fits(page)
    page.locator('.settings-account-row').first.click()
    page.locator('#dialog[open]').wait_for()
    assert page.locator('#dialog-title').inner_text() == 'Настройки счёта'
    assert page.locator('#dialog input[name="name"]').input_value().startswith('Long strategy')
    close_dialog(page)
    page.goto(url+'#people', wait_until='domcontentloaded')
    page.locator('.people-card').first.wait_for()
    page.evaluate("""() => {
      window.__uxApi=window.api;window.__guestCalls=[];window.__uxMutate=window.mutate;
      const own=state.people.shareable[0];
      window.__people=structuredClone(state.people);
      __people.guests=[0,1,6].map((n,i)=>({id:'test-'+i,name:'Длинное имя гостя '.repeat(i===2?4:1),since:'18 сентября',accounts:Array.from({length:n},(_,j)=>({...own,login:j?70000+j:own.login,name:'SONIC '+j,shared:j===0}))}));
      state.people=structuredClone(__people);render();
      window.mutate=async(path,data)=>{__guestCalls.push({path,data});};
      window.api=async(path,...args)=>{if(path==='/people')return structuredClone(__people);const d=await __uxApi(path,...args);if(path==='/bootstrap')d.user.name+=' updated';return d;};
    }""")
    assert page.locator('.people-card').count() == 3
    for i in range(3):
        card = page.locator('.people-card').nth(i)
        assert not card.evaluate('el=>el.open')
        assert not card.locator('.faq-body').is_visible()
        card.locator('summary').click()
    page.evaluate("__people.guests[1].accounts.push({...__people.guests[1].accounts[0],login:88888,shared:false,name:'Новый счёт'});refresh(true)")
    page.wait_for_function('!state.busy')
    assert page.locator('.people-card[open]').count() == 3
    assert page.get_by_text('Новый счёт', exact=True).is_visible()
    fits(page)
    page.locator('.people-card').nth(1).locator('[data-action="take"]').click()
    page.locator('#dialog-submit').click()
    page.wait_for_function('__guestCalls.length===1')
    assert page.evaluate('__guestCalls[0].data.action') == 'take'
    page.locator('.people-card').first.locator('[data-action="share-accounts"]').click()
    page.locator('#dialog input[type="checkbox"]').first.check()
    page.locator('#dialog-submit').click()
    page.wait_for_function('__guestCalls.length===2')
    assert page.evaluate('__guestCalls[1].data.action') == 'share'
    page.locator('.people-card').first.locator('[data-action="revoke-guest"]').click()
    page.locator('#dialog-submit').click()
    page.wait_for_function('__guestCalls.length===3')
    assert page.evaluate('__guestCalls[2].data.action') == 'revoke'
    page.locator('.people-card').first.locator('summary').click()
    page.wait_for_function("!document.querySelector('.people-card').open")
    fits(page)
    assert page.locator('.link-card .portal-link, .link-card .site-link').count() == 0
    page.evaluate('window.api=__uxApi;window.mutate=__uxMutate;void 0')
    page.goto(url+'#faq', wait_until='domcontentloaded')
    page.locator('.faq-strategy').first.wait_for()
    page.locator('.faq-strategy summary').nth(0).click()
    page.locator('.faq-strategy summary').nth(1).click()
    question=page.locator('.faq-item').nth(1)
    question.locator('summary').click()
    page.wait_for_function("[...document.querySelectorAll('.faq-body')].every(el=>!el.getAnimations().length)")
    page.evaluate("window.__uxApi=api;window.api=async(...a)=>{const d=await __uxApi(...a);if(a[0]==='/bootstrap')d.user.name+=' refreshed';return d;};scrollTo(0,450)")
    before=page.evaluate('scrollY')
    page.evaluate('refresh(true)')
    page.wait_for_function('!state.busy')
    assert page.locator('.faq-strategy[open]').count() == 2
    assert question.evaluate('el=>el.open')
    assert abs(page.evaluate('scrollY')-before) < 3
    assert page.evaluate("!document.querySelector('#main').getAnimations({subtree:true}).some(a=>a.playState==='running')")
    page.evaluate('window.api=__uxApi;void 0')
    # Every empty period has a real graphical container and no invented deals.
    for period in ('today','yesterday','week','lastweek','month','lastmonth','all','custom'):
        markup=page.evaluate("p=>{state.period=p;return chart([], 'USD', false, 'счёта', [{day:'2026-10-01',value:0,balance:10000},{day:'2026-10-02',value:0,balance:10000}]);}",period)
        assert 'chart-line' in markup and 'Баланс:' in markup
        assert 'M0,90 H640' in markup
    unknown=page.evaluate("chart([], 'USD', false, 'счёта', [{day:'2026-10-01',value:0,balance:null}])")
    assert 'Нет данных о состоянии счёта за этот период' in unknown


def modal_scroll_and_deferred_refresh(page, url):
    page.goto(url+'#overview', wait_until='domcontentloaded')
    page.locator('.hero').wait_for()
    page.evaluate("document.querySelector('#main').style.minHeight='2400px';window.__uxApi=api;window.__bootstrapCalls=0;window.api=async(...a)=>{if(a[0]==='/bootstrap')__bootstrapCalls++;return __uxApi(...a)};void 0")
    cases=['addAccount()', 'projectEditor()', "projectEditor({...state.projects?.[0],id:'modal-project',name:'Private',currency:'USD',rate_percent:1,period:'week',multi:true,accounts:Array.from({length:5},(_,i)=>({id:'m'+i,name:'Аккаунт '+i,amount:1000}))})", 'configureAccount(state.data.accounts[0].login)', "confirm('Удалить проект?', 'Проверка подтверждения', 'Удалить')"]
    for expression in cases:
        page.evaluate('scrollTo(0,400)')
        position=page.evaluate('scrollY')
        top=page.locator('#main').bounding_box()['y']
        page.evaluate("void "+expression)
        page.locator('#dialog[open]').wait_for()
        assert page.evaluate("document.querySelector('#dialog').contains(document.activeElement)")
        assert page.evaluate("document.documentElement.classList.contains('modal-open')")
        assert abs(page.locator('#main').bounding_box()['y']-top) < 2
        page.mouse.move(2,2)
        page.mouse.wheel(0,900)
        page.wait_for_timeout(100)
        assert abs(page.locator('#main').bounding_box()['y']-top) < 2
        dialog=page.locator('#dialog')
        if dialog.evaluate('el=>el.scrollHeight>el.clientHeight'):
            dialog.evaluate('el=>el.scrollTop=el.scrollHeight')
            assert dialog.evaluate('el=>el.scrollTop') > 0
            page.mouse.move(dialog.bounding_box()['x']+20,dialog.bounding_box()['y']+20)
            page.mouse.wheel(0,1000)
            page.wait_for_timeout(100)
            assert abs(page.locator('#main').bounding_box()['y']-top) < 2
        for _ in range(5):
            page.keyboard.press('Tab')
            assert page.evaluate("document.querySelector('#dialog').contains(document.activeElement)||document.activeElement===document.body")
        page.keyboard.press('Escape')
        page.wait_for_function("!document.querySelector('#dialog').open&&!document.documentElement.classList.contains('modal-open')")
        assert abs(page.evaluate('scrollY')-position) < 2
        page.evaluate('scrollTo(0,450)')
        assert page.evaluate('scrollY') == 450
    page.evaluate('void addAccount()')
    page.locator('#dialog input[name="name"]').fill('Незавершённый ввод')
    calls=page.evaluate('__bootstrapCalls')
    page.evaluate('refresh(true)')
    assert page.locator('#dialog input[name="name"]').input_value() == 'Незавершённый ввод'
    assert page.evaluate('__bootstrapCalls') == calls
    if page.viewport_size['width'] == 390:
        # настоящий интервал — 30+ секунд; сжимаем его, чтобы дождаться именно фонового тика таймера
        page.evaluate("window.__refreshEvery = refreshEvery; refreshEvery = () => 1200; scheduleRefresh();")
        page.wait_for_timeout(1900)
        page.evaluate("refreshEvery = window.__refreshEvery; scheduleRefresh();")
        assert page.locator('#dialog[open]').count() == 1
        assert page.locator('#dialog input[name="name"]').input_value() == 'Незавершённый ввод'
        assert page.evaluate('__bootstrapCalls') == calls
    close_dialog(page)
    page.wait_for_function('!state.busy&&!quietPending&&__bootstrapCalls>0')
    page.evaluate('window.api=__uxApi;void 0')
    page.goto(url+'#projects', wait_until='domcontentloaded')
    page.locator('.project-card').first.wait_for()
    page.locator('a[href="#project/preview-private"]').click()
    page.locator('.project-account').first.wait_for()
    page.evaluate("window.__uxApi=api;window.api=async(...a)=>{const d=await __uxApi(...a);if(a[0]==='/projects')d.projects[1].accounts[0].name='Обновлённый аккаунт';return d;};scrollTo(0,200)")
    route=page.evaluate('[location.hash,state.projectId,state.period]')
    page.evaluate('refresh(true)')
    page.wait_for_function('!state.busy')
    assert page.evaluate('[location.hash,state.projectId,state.period]') == route
    page.locator('.project-account').filter(has_text='Обновлённый аккаунт').wait_for(state='visible')
    page.evaluate('window.api=__uxApi;void 0')


def close_dialog(page):
    """Закрыть диалог крестиком в шапке: у информационных окон кнопка
    «Отмена» спрятана, а крестик есть у всех. Изменённые поля подтверждаем."""
    dirty = page.evaluate("""() => [...document.querySelectorAll('#dialog input,#dialog select,#dialog textarea')].some(f =>
        f.type==='file' ? f.files.length>0 : f.type==='checkbox'||f.type==='radio' ? f.checked!==f.defaultChecked :
        f.tagName==='SELECT' ? f.value!==([...f.options].find(o=>o.defaultSelected)?.value??f.options[0]?.value) : f.value!==f.defaultValue)""")
    if dirty:
        page.evaluate("""() => { window.__exitPrompts=[]; window.requestDialogExit=d=>{window.__exitPrompts.push('Выйти без сохранения изменений?');if(d.open)d.close('cancel');return Promise.resolve(true);}; }""")
        page.locator('#dialog .dialog-head button[value="cancel"]').click()
        assert page.evaluate("window.__exitPrompts") == ["Выйти без сохранения изменений?"]
    else:
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
                for width in WIDTHS:
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
                    # выбор валюты: кнопка и меню вместо системного списка, значение берёт скрытый select
                    assert page.locator('#currency-menu').is_hidden()
                    page.locator('#currency-btn').click()
                    assert page.locator('#currency-menu [data-currency]').count() == 3
                    page.locator('#currency-menu [data-currency="BYN"]').click()
                    page.wait_for_function("state.displayCurrency==='BYN'")
                    assert page.locator('#currency-code').inner_text() == 'BYN'
                    assert page.locator('#currency-menu').is_hidden()
                    page.locator('#currency-btn').click()
                    page.keyboard.press('Escape')
                    assert page.locator('#currency-menu').is_hidden()
                    page.locator('#currency-btn').click()
                    page.locator('#currency-menu [data-currency="USD"]').click()
                    page.wait_for_function("state.displayCurrency==='USD'")
                    fits(page)
                    # динамика доходности лентой дней: строки с результатом и сводка
                    # динамика кубиками: по кубику на день, выше кубик — больше доходность за день
                    page.locator('[data-action="period"][data-value="month"]').first.click()
                    page.wait_for_function("document.querySelectorAll('.chart-panel .cube').length >= 3")
                    heights = page.evaluate("[...document.querySelectorAll('.chart-panel .cube')].map(c => [parseFloat(c.style.getPropertyValue('--h')), c.dataset.cube])")
                    assert all(h > 0 for h, _ in heights)
                    fits(page)          # длинный период не раздвигает страницу: ряд кубиков прокручивается внутри блока
                    page.locator('[data-action="period"][data-value="all"]').first.click()
                    page.wait_for_function("document.querySelectorAll('.chart-panel .cube').length >= 10")
                    fits(page)
                    page.locator('[data-action="period"][data-value="month"]').first.click()
                    page.wait_for_function("document.querySelectorAll('.chart-panel .cube').length >= 3")
                    biggest = max(heights, key=lambda x: x[0])
                    assert biggest[0] > min(h for h, _ in heights), heights
                    # выбор дня показывает его сумму и процент строкой под рядом
                    page.locator('.chart-panel .cube').first.click()
                    assert page.locator('.chart-panel .cube.active').count() == 1
                    assert '$' in page.locator('.chart-panel .cube-detail').inner_text()
                    page.locator('[data-action="period"][data-value="today"]').first.click()
                    page.wait_for_function("document.querySelectorAll('.chart-panel .cube').length >= 1")
                    assert page.locator('.chart-panel .feed-meta span').count() in (2, 4)
                    assert 'MYFIN' not in page.locator('.hero').inner_text()
                    fx_unavailable_ui(page)
                    # лента: четыре события предпросмотра, два из них не прочитаны
                    page.locator('#notifications').click()
                    assert page.locator('.notification-item').count() == 5
                    assert page.locator('.notification-item.unread').count() == 3
                    # рядом с датой — день недели: в заголовках групп и у старых событий
                    assert any(',' in h or '·' in h for h in page.locator('.notification-group > h3').all_inner_texts())
                    # первая группа — «Сегодня», а в первые минуты после полуночи UTC события двухминутной давности уже «Вчера»
                    assert page.locator('.notification-group > h3').first.inner_text().lower().startswith(('сегодня ·', 'вчера ·'))
                    # главная сумма события вынесена вправо, а название события — отдельно от стратегии
                    assert page.locator('.notification-item .nt-amount').count() >= 3
                    assert 'Сделка в плюс' in page.locator('.notification-item.tone-good').first.inner_text()
                    # у сообщения сервиса нет перехода: ни ссылки «Читать», ни второго окна с тем же текстом
                    message = page.locator('.notification-item.kind-message')
                    assert message.count() == 1 and message.locator('.meta').count() == 0
                    # рядом с номером счёта — владелец счёта
                    assert '10001 · ' in page.locator('.notification-item.kind-trades .kicker').first.inner_text()
                    # фильтры по разделам: «Деньги» оставляют пополнение и вывод
                    page.locator('[data-action="notif-filter"][data-value="money"]').click()
                    assert page.locator('.notification-item').count() == 2
                    page.locator('[data-action="notif-filter"][data-value="all"]').click()
                    assert page.locator('.notification-item').count() == 5
                    close_dialog(page)
                    # динамика: другой период — другой итог
                    result = page.locator('.chart-panel .dynamics-main .result-pair b')
                    today_result = result.inner_text()
                    page.locator('.chart-panel [data-action="period"][data-value="all"]').click()
                    page.locator('.chart-panel [data-action="period"][data-value="all"].active').wait_for()
                    # подсветка переезжает сразу, цифры приходят следом — ждём загрузку
                    page.wait_for_function("!document.body.classList.contains('is-loading')")
                    assert result.inner_text() != today_result
                    page.locator('.chart-panel [data-action="period"][data-value="today"]').click()
                    page.locator('.chart-panel [data-action="period"][data-value="today"].active').wait_for()
                    page.wait_for_function("!document.body.classList.contains('is-loading')")
                    # график цены SONIC: только красно-зелёные свечи, без средних и подписей сделок
                    page.locator('.price-chart-panel svg').wait_for()
                    assert page.locator('.price-chart-panel svg rect[fill="url(#cd-up)"]').count() >= 1
                    assert page.locator('.price-chart-panel svg rect[fill="url(#cd-down)"]').count() >= 1
                    assert page.locator('.price-chart-panel polyline').count() == 0          # линий MA20/MA50 нет
                    for gone in ('.price-legend', '.trade-layer', '.trade-list', '.trade-tag', '.chart-hint'):
                        assert page.locator(f'.price-chart-panel {gone}').count() == 0, gone
                    assert 'MA20' not in page.locator('.price-chart-panel').inner_text()
                    assert page.locator('.time-axis span').count() == 5
                    # масштаб и листание: окно свечей меняется
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
                    fits(page)
                    if width == 390:
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-overview-smoke.png"), full_page=True)
                    # частые вопросы о стратегии — отдельный экран с возвратом
                    page.locator('a.faq-link').click()
                    page.locator('.faq-page').wait_for()
                    assert page.locator('.faq-item').count() >= 12
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
                    guest_with_shared_account_sees_home_and_opens_guide_on_demand(page)
                    faq_opens_smoothly(page, url)
                    page.goto(url + "#overview", wait_until="domcontentloaded")
                    page.locator('.hero').wait_for()
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
                    # жидкое стекло: переключателя в настройках нет, размытие у верхней панели всегда
                    assert page.locator('[data-action="glass"]').count() == 0
                    assert page.evaluate("getComputedStyle(document.querySelector('.topbar')).backdropFilter") != 'none'
                    page.locator('[data-action="shortcut"]').click()
                    assert page.locator('#dialog-title').inner_text() == 'Ярлык Tag Markets'
                    close_dialog(page)
                    page.locator('[data-action="broadcast"]').click()
                    area = page.locator('#dialog textarea[name="text"]')
                    area.wait_for()
                    # «Проверить» с пустым сообщением: ошибка внутри окна, окно остаётся
                    page.locator('#dialog-submit').click()
                    page.locator('#dialog .dialog-error').wait_for()
                    assert 'Добавьте текст или файл' in page.locator('#dialog .dialog-error').inner_text()
                    assert page.locator('#dialog[open]').count() == 1
                    # отмена выбора файла не закрывает окно: «cancel» поля файла всплывает до диалога
                    page.evaluate("document.querySelector('#dialog input[name=\"media\"]').dispatchEvent(new Event('cancel', {bubbles: true}))")
                    page.wait_for_timeout(150)
                    assert page.locator('#dialog[open]').count() == 1
                    # и «назад» Telegram сразу после выбора файла
                    page.evaluate("filePickerUntil = Date.now() + 5000")
                    assert page.evaluate("requestDialogExit(document.querySelector('#dialog'))") is not None
                    page.wait_for_timeout(150)
                    assert page.locator('#dialog[open]').count() == 1
                    page.evaluate("filePickerUntil = 0")
                    # получатели: «Всем» по умолчанию, «Одному» открывает выбор пользователя
                    assert page.locator('#dialog select[name="target"]').input_value() == 'all'
                    assert page.locator('.cmp-one').is_hidden()
                    page.locator('[data-cmp-target="one"]').click()
                    assert page.locator('.cmp-one').is_visible()
                    assert page.locator('#dialog select[name="target"]').input_value() != 'all'
                    page.locator('[data-cmp-target="all"]').click()
                    assert page.locator('#dialog select[name="target"]').input_value() == 'all'
                    # шаблон подставляет текст и форматирование, «Очистить» возвращает пустой редактор
                    page.locator('[data-template="maintenance"]').click()
                    assert 'Технические работы' in page.locator('#compose-live').inner_text()
                    assert page.locator('#compose-live b').count() == 1
                    page.locator('[data-cmp-clear]').click()
                    assert area.input_value() == ''
                    assert page.locator('#compose-live').inner_text() == 'Сообщение появится здесь'
                    area.fill('Обновление для пользователей')
                    assert page.locator('#compose-live').inner_text() == 'Обновление для пользователей'
                    assert page.locator('#compose-count').inner_text().startswith(
                        f'{len("Обновление для пользователей")} /')
                    area.evaluate('(el) => {el.selectionStart = 0; el.selectionEnd = 10;}')
                    page.locator('[data-format="bold"]').click()
                    assert page.locator('#compose-live b').count() == 1
                    # теги форматирования не считаются символами: счётчик остался прежним
                    assert page.locator('#compose-count').inner_text().startswith(f'{len("Обновление для пользователей")} /')
                    assert page.locator('#dialog textarea[name="text"]').get_attribute('maxlength') is None
                    page.locator('#dialog input[name="media"]').set_input_files({
                        "name": "photo.png", "mimeType": "image/png",
                        "buffer": base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9YbZT5cAAAAASUVORK5CYII=")})
                    page.wait_for_timeout(700)      # короткая защита окна после выбора файла прошла
                    assert "photo.png" in page.locator('#compose-file-name').inner_text()
                    assert page.locator('.cmp-drop').count() == 0          # файл — скрепкой в панели текста
                    assert page.locator('.cmp-file').is_visible()
                    page.locator('[data-cmp-file-clear]').click()
                    assert page.locator('.cmp-file').is_hidden()
                    assert 'photo.png' not in page.locator('#compose-file-name').inner_text()
                    page.locator('#dialog input[name="media"]').set_input_files({
                        "name": "photo.png", "mimeType": "image/png",
                        "buffer": base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9YbZT5cAAAAASUVORK5CYII=")})
                    page.wait_for_timeout(700)      # короткая защита окна после выбора файла прошла
                    # кнопка «Открыть приложение»: своё название, предпросмотр под сообщением
                    assert page.locator('#compose-btn-preview').is_hidden()
                    page.locator('#dialog [data-cmp-button]').check()
                    page.locator('#dialog input[name="button_text"]').fill('Смотреть отчёт')
                    assert page.locator('#compose-btn-preview').inner_text() == 'Смотреть отчёт'
                    page.locator('#dialog-submit').click()
                    page.get_by_text('Проверка рассылки').wait_for()
                    assert page.locator('#dialog .cmp-bubble-btn').inner_text() == 'Смотреть отчёт'
                    assert page.locator('.compose-preview-media img').count() == 1
                    assert page.locator('.compose-preview-media img').evaluate('(el) => el.complete && el.naturalWidth > 0')
                    if width == 390:
                        page.screenshot(path=str(screenshots / "tagmarkets-mobile-broadcast-smoke.png"))
                    fits(page)
                    # «Назад» возвращает в сообщение: текст, файл, получатель и кнопка на месте
                    assert page.locator('#dialog .dialog-actions button[value="cancel"]').inner_text() == 'Назад'
                    page.locator('#dialog .dialog-actions button[value="cancel"]').click()
                    page.wait_for_function("document.querySelector('#dialog-title').textContent === 'Сообщение пользователям'")
                    assert page.locator('#dialog textarea[name="text"]').input_value().startswith('<b>Обновление</b>') or 'Обновление для пользователей' in page.locator('#dialog textarea[name="text"]').input_value()
                    assert 'photo.png' in page.locator('#compose-file-name').inner_text()
                    assert page.locator('#dialog [data-cmp-button]').is_checked()
                    assert page.locator('#dialog input[name="button_text"]').input_value() == 'Смотреть отчёт'
                    # снова на проверку и закрываем целиком (в окне сообщения «Отмена» снова просто «Отмена»)
                    page.locator('#dialog-submit').click()
                    page.get_by_text('Проверка рассылки').wait_for()
                    page.locator('#dialog .dialog-actions button[value="cancel"]').click()
                    page.wait_for_function("document.querySelector('#dialog-title').textContent === 'Сообщение пользователям'")
                    assert page.locator('#dialog .dialog-actions button[value="cancel"]').inner_text() == 'Отмена'
                    page.evaluate("document.querySelector('#dialog').dataset.dirty = ''")
                    close_dialog(page)
                    page.locator(f'{nav} a[href="#people"]').click()
                    page.locator('.people-card').first.wait_for()
                    glider_on_active(page, nav)
                    page.locator('.people-card summary').first.click()
                    page.locator('[data-action="guest-detail"]').first.click()
                    page.get_by_text('Карточка гостя').wait_for()
                    close_dialog(page)
                    # ссылка-приглашение и партнёрская ссылка — в карточке раздела «Гости»
                    assert page.locator('.link-card .invite-url').inner_text().startswith('https://t.me/')
                    page.locator('[data-action="partner-link"]').first.click()
                    assert page.locator('#dialog input[name="url"]').count() == 1
                    assert page.locator('#dialog .pl-portal').get_attribute('target') == '_blank'
                    assert page.locator('#dialog .pl-steps li').count() == 3
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
                    projects_ui(page, nav)
                    compact_ui_and_quiet_refresh(page, url)
                    modal_scroll_and_deferred_refresh(page, url)
                    assert not errors, errors
                    page.close()
                print("UI smoke PASS: " + ", ".join(f"{w}px" for w in WIDTHS))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


def run_parallel():
    """Каждая ширина — отдельный процесс со своим сервером и браузером: те же проверки, в ~3 раза быстрее."""
    import subprocess
    import sys
    sys.stdout.reconfigure(errors="replace")  # консоль Windows (cp1251) не должна ронять прогон на выводе
    procs = [(w, subprocess.Popen([sys.executable, __file__], env={**os.environ, "TAGMARKETS_UI_SMOKE_WIDTHS": str(w), "PYTHONIOENCODING": "utf-8"},
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"))
             for w in WIDTHS]
    retry = []
    for width, proc in procs:
        output, _ = proc.communicate()
        if proc.returncode:
            retry.append(width)
            print(f"UI smoke {width}px: failed under parallel load, re-running alone")
        else:
            print(output, end="")
    # проверки быстрых нажатий и фоновых обновлений завязаны на тайминг: под
    # нагрузкой четырёх браузеров они изредка ложно падают. Ширина считается
    # проваленной, только если падает и в одиночном прогоне.
    failed = []
    for width in retry:
        proc = subprocess.run([sys.executable, __file__], env={**os.environ, "TAGMARKETS_UI_SMOKE_WIDTHS": str(width), "PYTHONIOENCODING": "utf-8"},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        print(proc.stdout, end="")
        if proc.returncode:
            failed.append(width)
    if failed:
        sys.exit(f"UI smoke FAIL: {', '.join(f'{w}px' for w in failed)}")


if __name__ == "__main__":
    if os.getenv("TAGMARKETS_UI_SMOKE_WIDTHS") or "--serial" in __import__("sys").argv:
        main()
    else:
        run_parallel()
