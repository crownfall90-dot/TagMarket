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
    assert page.locator('.page-head [data-action="add"] .button-label').inner_text() == "Добавить счёт"
    page.evaluate("state.data=window.__smokeSavedData;delete window.__smokeSavedData;state.view='overview';render()")


def projects_ui(page, nav):
    page.locator(f'{nav} a[href="#projects"]').click()
    page.locator('.project-card').first.wait_for()
    assert page.locator(f'{nav} a[data-tab]').count() == 5
    assert page.locator('.project-card').count() == 3  # TagMarket плюс два preview-проекта
    assert 'Плюс за' in page.locator('.project-card.system-project').inner_text()
    glider_on_active(page, nav)
    fits(page)
    page.locator('a[href="#project/preview-home"]').click()
    page.locator('[data-action="project-edit"]').click()
    amount = page.locator('.project-form-account input[name^="account-amount-"]')
    assert amount.input_value() == '10000'
    assert page.locator('.project-form [name="currency"]').is_disabled()
    page.locator('.project-form [name="multi"]').check()
    assert amount.input_value() == '10000'
    page.locator('[data-action="project-form-add"]').click()
    page.locator('.project-form-account input[name^="account-amount-"]').nth(1).fill('3000')
    assert '13' in page.locator('.project-form-total').inner_text()
    assert page.locator('.project-account-name input[type="text"]').count() == 2
    page.locator('.project-form [name="multi"]').click()
    assert page.locator('.project-form [name="multi"]').is_checked()
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
    fits(page)
    close_dialog(page)
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
    assert not page.locator('.project-form [name="multi"]').is_checked()
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
            if((path==='/projects'||path==='/projects/ui-created')&&['POST','PATCH'].includes(options.method)){
                const d=JSON.parse(options.body);window.__projectUiSaved=d;
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
    page.locator('.project-form [name="multi"]').check()
    page.locator('[data-action="project-form-add"]').click()
    page.locator('.project-form-account input[name^="account-amount-"]').nth(1).fill('3000')
    page.locator('#dialog-submit').click()
    page.wait_for_function("window.__projectUiSaved?.multi && window.__projectUiSaved.accounts?.length === 2")
    page.locator('.project-account').first.wait_for()
    saved = page.evaluate('window.__projectUiSaved')
    assert saved['multi'] and saved['accounts'][0]['id'] == 'ui-account-0'
    assert [a['amount'] for a in saved['accounts']] == [10000, 3000]
    assert page.locator('.project-account').count() == 2
    page.locator('[data-action="project-delete"]').click()
    page.locator('#dialog-submit').click()
    page.wait_for_function("state.view==='projects'&&!state.projects.some(p=>p.id==='ui-created')")
    assert 'Ваши средства' in page.locator('.project-card').filter(has_text='Недвижимость').inner_text()
    assert 'Рабочий капитал' in page.locator('.project-card').filter(has_text='Private Invest').inner_text()
    assert 'Бонус активен' in page.locator('.project-card').filter(has_text='Private Invest').inner_text()
    private_card=page.locator('.project-card').filter(has_text='Private Invest')
    assert 'Бонус завершён' in private_card.inner_text(), private_card.inner_text()
    page.locator('a.forecast-link').click()
    page.locator('.forecast-result').wait_for()
    assert page.locator('.forecast-summary-values').count() == 1
    assert all(page.locator('.forecast-table thead th').all_inner_texts()[i] for i in range(7))
    result_text = page.locator('.forecast-result').inner_text()
    assert 'Среднее рассчитано по 23 торговым дням' in result_text, result_text
    assert 'статистика, а не обещание' in result_text
    assert page.locator('.forecast-tag-grid > div').count() == 4
    assert all('≈' in t for t in page.locator('.forecast-tag-grid b').all_inner_texts())
    fits(page)
    # мало истории: прогноз не строится, текущий капитал остаётся, сообщение понятное
    page.evaluate("state.forecast.tag={sufficient:false,days_used:3,min_days:5,multipliers:{}};render(true)")
    result_text = page.locator('.forecast-result').inner_text()
    assert 'Недостаточно истории для статистического прогноза TagMarket' in result_text
    assert page.locator('.forecast-tag-grid b').first.inner_text().strip()
    assert '≈' not in page.locator('.forecast-tag-grid').inner_text()
    page.evaluate("state.forecast.tag={error:'x'};render(true)")
    assert 'Прогноз TagMarket временно недоступен' in page.locator('.forecast-result').inner_text()
    page.evaluate('recalculateForecast()')
    page.wait_for_function("state.forecast.tag?.sufficient===true")
    summary=(page.locator('.forecast-mobile-cards .forecast-breakdown summary')
             if page.locator('.forecast-mobile-cards').is_visible()
             else page.locator('.forecast-table .forecast-breakdown summary'))
    summary.first.click()
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
    assert 'BYN' in page.locator('.forecast-mobile-card').first.inner_text()
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
    assert page.locator('.link-card .portal-link').get_attribute('target') == '_blank'
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
        assert 'M0,80 H640 V80' in markup
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
        page.wait_for_timeout(page.evaluate('refreshEvery()')+500)
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
                    fx_unavailable_ui(page)
                    # лента: четыре события предпросмотра, два из них не прочитаны
                    page.locator('#notifications').click()
                    assert page.locator('.notification-item').count() == 4
                    assert page.locator('.notification-item.unread').count() == 2
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
                    page.locator('.people-card summary').first.click()
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
                    projects_ui(page, nav)
                    compact_ui_and_quiet_refresh(page, url)
                    modal_scroll_and_deferred_refresh(page, url)
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
