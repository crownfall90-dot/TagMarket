'use strict';
const $ = (s, root = document) => root.querySelector(s);
const tg = window.Telegram?.WebApp;
const preview = new URLSearchParams(location.search).get('preview') === '1';
const state = {data:null, people:null, admin:null, report:null, reportError:'', priceChart:null, notifications:{items:[],unread:0}, view:'overview', login:null, period:'today', kind:'trades', offset:0, from:'', to:'', filters:{tagmarket:{period:'today',from:'',to:''},account:{period:'today',from:'',to:''}}, busy:false, currency:null};
try{state.displayCurrency=localStorage.getItem('tag-display-currency')||'USD';}catch{state.displayCurrency='USD';}
let generation = 0, refreshTimer, toastTimer, notificationsStarted = false, lastNotificationId = 0;
state.projects=null;state.projectsError='';state.banks=null;state.banksError='';state.spend=null;state.spendError='';state.spendSpan='month';state.income=null;state.incomeError='';state.goals=null;state.friends=null;state.friendsError='';state.projectId=null;try{state.assetMode=localStorage.getItem('tag-asset-mode')||'tag';}catch{state.assetMode='tag';}state.forecast={horizon:'1m',until:'',bonus:true,selected:null,result:null,tag:null};
const paths = {overview:'M3 10l9-7 9 7v10H3z M9 20v-7h6v7',accounts:'M3 7h18v14H3z M3 7V4h14v3 M16 12h5v5h-5z',deals:'M4 5h16 M4 12h16 M4 19h16 M8 2v6 M16 9v6 M9 16v6',people:'M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3 M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M17 3a4 4 0 0 1 0 8 M22 21v-3a4 4 0 0 0-3-4',settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',plus:'M12 5v14 M5 12h14',arrow:'M5 12h14 M14 7l5 5-5 5',up:'M7 17 17 7 M7 7h10v10',down:'M7 7l10 10 M7 17h10V7',refresh:'M20 7A8 8 0 0 0 6 5L3 8 M3 3v5h5 M4 17a8 8 0 0 0 14 2l3-3 M21 21v-5h-5',sun:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 1v2 M12 21v2 M1 12h2 M21 12h2 M4 4l2 2 M18 18l2 2 M4 20l2-2 M18 6l2-2',chevron:'M9 5l7 7-7 7',chart:'M3 19h18 M4 15l5-5 5 3 6-9',check:'m5 12 4 4L19 6',clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2',link:'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',back:'M19 12H5 M10 7l-5 5 5 5',shield:'M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6z M8 12l3 3 5-6',copy:'M8 8h13v13H8z M16 8V3H3v13h5'};
paths.bell='M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4';paths.exit='M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9';paths.palette='M12 3a9 9 0 1 0 0 18c1.4 0 2-.9 2-1.8 0-1.4-1.2-1.6-1.2-2.8 0-.9.7-1.4 1.6-1.4H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z';
Object.assign(paths,{
 overview:'M4 10.5 12 4l8 6.5V19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z M9 21v-7h6v7',
 accounts:'M4 6h15a2 2 0 0 1 2 2v12H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h13 M16 12h5v5h-5a2 2 0 0 1 0-5z',
 deals:'M4 19h16 M7 16V9 M12 16V5 M17 16v-5 M5 9h4 M10 5h4 M15 11h4',
 people:'M8.5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M2 20v-2a5 5 0 0 1 5-5h3a5 5 0 0 1 5 5v2z M17 4a3.5 3.5 0 0 1 0 7 M18 13a4 4 0 0 1 4 4v3',
 settings:'M4 6h16 M4 12h16 M4 18h16 M9 4v4 M16 10v4 M9 16v4',
 chart:'M3 20h18 M5 16l5-5 4 3 5-7 M16 7h3v3',
 refresh:'M20 8a8 8 0 0 0-14-3L3 8 M3 3v5h5 M4 16a8 8 0 0 0 14 3l3-3 M21 21v-5h-5',
 bell:'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4'
});
function icon(name, cls=''){return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.chart}"/></svg>`;}
function esc(value){return String(value??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
// Код валюты приходит из терминала: Intl принимает только трёхбуквенный ISO,
// а «USDT» или «XXXXX» бросали RangeError прямо из render() — пустой экран
function displayAmount(value,cur){if(cur===state.displayCurrency)return value;const rates=state.data?.fx?.byn_per_unit;if(!rates||!rates[cur]||!rates[state.displayCurrency])return null;return Number(value)*rates[cur]/rates[state.displayCurrency];}
function money(value, cur='USD', signed=false){if(value==null||!Number.isFinite(Number(value)))return '—';const source=cur||'USD',converted=displayAmount(Number(value),source);if(converted==null)return `${signed&&Number(value)>0?'+':''}${number(value)} ${esc(source)}`;const opts={maximumFractionDigits:2,signDisplay:signed?'exceptZero':'auto'};try{return `${source===state.displayCurrency?'':'≈ '}${new Intl.NumberFormat('ru-RU',{...opts,style:'currency',currency:state.displayCurrency||source}).format(converted)}`;}catch{return `${source===state.displayCurrency?'':'≈ '}${new Intl.NumberFormat('ru-RU',{...opts,minimumFractionDigits:2}).format(converted)} ${esc(state.displayCurrency||source)}`;}}
function number(value){return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value||0);}
function percent(value){return `${value>=0?'+':''}${new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:3}).format(value)}%`;}
function resultPair(value,cur,pct){return `<span class="result-pair ${signedClass(value)}"><b>${money(value,cur,true)}</b>${pct==null?'':`<small title="Доля от текущего вложенного капитала">${percent(pct)}</small>`}</span>`;}
// Некорректная дата (пустое поле, чужой формат) не должна ронять весь экран:
// Intl.format и toISOString на ней бросают «Invalid time value»
function validDate(d){return d instanceof Date&&Number.isFinite(d.getTime());}
function isoOrNull(value){if(!value)return null;const d=new Date(value);return validDate(d)?d.toISOString():null;}
function fmtDate(fmt,d){return validDate(d)?fmt.format(d):'';}
function date(value, full=false){const raw=String(value||'');const iso=raw.length===10?raw+'T00:00:00Z':/(Z|[+-]\d{2}:\d{2})$/.test(raw)?raw:raw+'Z';return fmtDate(new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'short',...(full?{hour:'2-digit',minute:'2-digit',timeZone:'UTC'}:{})}),new Date(iso));}
function dayLabel(value){const text=fmtDate(new Intl.DateTimeFormat('ru-RU',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}),new Date(`${value}T12:00:00Z`));return text.charAt(0).toUpperCase()+text.slice(1);}
function signedClass(value){return value<0?'negative':'positive';}
function notice(text, warning=false){return `<div class="notice ${warning?'warning':''}">${esc(text)}</div>`;}
function toast(text){const el=$('#toast');el.classList.remove('has-event');el.textContent=text;el.classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('visible'),4500);}
function weekdayOf(value){const raw=String(value||'');const iso=raw.length===10?raw+'T12:00:00Z':/(Z|[+-]\d{2}:\d{2})$/.test(raw)?raw:raw+'Z';const d=new Date(iso);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat('ru-RU',{weekday:'short',timeZone:raw.length===10?'UTC':'Europe/Minsk'}).format(d):'';}
function since(value){const raw=String(value||'');const t=Date.parse(/(Z|[+-]\d{2}:\d{2})$/.test(raw)?raw:raw+'Z');if(!Number.isFinite(t))return '';const sec=Math.max(0,(Date.now()-t)/1000);if(sec<60)return 'только что';if(sec<3600)return `${Math.floor(sec/60)} мин назад`;if(sec<86400)return `${Math.floor(sec/3600)} ч назад`;return date(value,true);}
function agoText(sec){if(sec==null)return 'нет данных';if(sec<60)return 'только что';if(sec<3600)return `${Math.floor(sec/60)} мин назад`;if(sec<86400)return `${Math.floor(sec/3600)} ч назад`;return `${Math.floor(sec/86400)} дн назад`;}
// Название события — последняя часть заголовка «Стратегия · Событие»; по нему выбираем значок и тон.
function notificationTitleParts(item){const title=String(item.title||''),at=title.lastIndexOf(' · ');return at<0?{strategy:'',event:title}:{strategy:title.slice(0,at),event:title.slice(at+3)};}
function eventKind(item){
 const event=notificationTitleParts(item).event.toLowerCase();
 const byTitle=[['сделка в плюс',['Сделка','chart','good']],['сделка в минус',['Сделка','chart','bad']],['реинвест',['Реинвест','refresh','good']],['вывод профита',['Вывод','down','warn']],['вывод капитала',['Вывод','down','warn']],['пополнение стратегии',['Пополнение','up','good']],['пополнение баланса',['Пополнение','up','good']],['плата платформы',['Плата','down','warn']]].find(([key])=>event.includes(key));
 if(byTitle)return byTitle[1];
 return ({trades:['Сделка','chart','neutral'],deposits:['Пополнение','up','good'],withdrawals:['Вывод','down','warn'],registration:['Новый гость','people','good'],message:['Сообщение','bell','neutral']})[item.kind]||['Событие','bell','neutral'];
}
// Из текста события достаём главную сумму (крупно справа) и пару строк пояснения.
function notificationParts(item){
 const lines=String(item.body||'').split('\n').map(x=>x.trim()).filter(Boolean),money=/^[+\-−]?\d[\d\s\u202f.,]*\s?(?:\$|₽|Br|USD|RUB|BYN)/;
 const at=lines.findIndex(line=>money.test(line)),amount=at>=0?lines[at].split(/\s+(?:чистыми|к капиталу)/)[0]:'';
 const rest=lines.filter((_,k)=>k!==at).filter(line=>!/^🔢/.test(line)||true);
 return {amount,lines:rest};
}
function notificationTarget(item){const match=/^trade:(\d+):/.exec(item.event_key||'');if(match&&state.data?.accounts.some(a=>String(a.login)===match[1]))return {hash:'account/'+match[1],label:'Открыть счёт'};if(['trades','deposits','withdrawals'].includes(item.kind))return {hash:'accounts',label:'Открыть счета'};if(item.kind==='registration')return {hash:'people',label:'Открыть друзей'};return {hash:'',label:'Читать'};}
function eventToast(item,count){const el=$('#toast'),[kind,ico]=eventKind(item);el.innerHTML=`<div class="event-toast kind-${esc(item.kind||'other')}" role="alert"><button type="button" class="event-toast-main" data-action="notification-open" data-id="${esc(item.id)}"><span class="event-toast-icon">${icon(ico)}</span><span class="event-toast-copy"><b>${count>1?`${count} новых · `:''}${esc(item.title)}</b><span>${esc(notificationParts(item).amount||notificationParts(item).lines[0]||'')}</span></span><span class="event-toast-go">${icon('arrow')}</span></button><button type="button" class="event-toast-close" data-action="toast-close" aria-label="Закрыть">×</button><i class="event-toast-timer"></i></div>`;el.classList.add('visible','has-event');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('visible'),6000);}
function button(action,text,style='secondary',ico='',attrs=''){return `<button type="button" class="button ${style}" data-action="${action}" ${attrs}>${ico?icon(ico):''}<span class="button-label">${esc(text)}</span></button>`;}
// Длина считается по видимому тексту: теги форматирования (<b>, <i>, <code>, <blockquote>) — не символы
function broadcastLength(value){return String(value||'').replace(/<\/?(?:b|i|code|blockquote)>/gi,'').length;}
// Окно «Сообщение пользователям»: состояние (draft) живёт отдельно от окна, поэтому «Назад» из проверки,
// ошибка проверки и повторное открытие ничего не теряют: текст, файл, получатель, кнопка.
function composerBody(users,draft){const one=draft.target&&draft.target!=='all';return `<div class="composer">${draft.error?`<div class="dialog-error" role="alert">${esc(draft.error)}</div>`:''}
   <div class="composer-intro"><span class="eyebrow">РАССЫЛКА</span><p>Напишите сообщение, посмотрите, как оно выглядит у получателя, и проверьте перед отправкой.</p></div>
   <div class="cmp-block"><span class="cmp-label">Кому</span><div class="segmented cmp-seg" role="group" aria-label="Получатели"><button type="button" class="${one?'':'active'}" data-cmp-target="all">Всем · ${users.length}</button><button type="button" class="${one?'active':''}" data-cmp-target="one">Одному</button></div>
    <label class="field cmp-one" ${one?'':'hidden'}>Пользователь<select name="target"><option value="all" ${one?'hidden':'selected'}>Все приглашённые · ${users.length}</option>${users.map(u=>`<option value="${esc(u.id)}" ${String(u.id)===String(draft.target)?'selected':''}>${esc(u.name)}</option>`).join('')}</select></label></div>
   <div class="cmp-block"><span class="cmp-label">Быстрый старт</span><div class="cmp-chips">${[['maintenance','Технические работы'],['feature','Новая функция'],['reminder','Напоминание'],['thanks','Благодарность']].map(([id,label])=>`<button type="button" class="cmp-chip" data-template="${id}">${label}</button>`).join('')}</div></div>
   <div class="composer-editor"><div class="composer-editor-head"><b>Текст</b><span id="compose-count">0 / 4096</span></div><div class="cmp-meter" aria-hidden="true"><i id="compose-meter"></i></div>
    <div class="compose-tools"><button type="button" class="format-btn" data-format="bold" aria-label="Жирный" title="Жирный"><b>Ж</b></button><button type="button" class="format-btn" data-format="italic" aria-label="Курсив" title="Курсив"><i>К</i></button><button type="button" class="format-btn" data-format="mono" aria-label="Моноширинный" title="Моноширинный"><code>М</code></button><button type="button" class="format-btn" data-format="quote" aria-label="Цитата" title="Цитата">❝</button><span>Выделите текст для оформления</span><button type="button" class="cmp-clear" data-cmp-clear hidden>Очистить</button><label class="format-btn cmp-attach" title="Фото или видео" aria-label="Прикрепить фото или видео"><input type="file" name="media" accept="image/jpeg,image/png,video/mp4" class="cmp-file-input"><svg class="cmp-clip" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5 12.6 19.9a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"/></svg></label></div>
    <textarea name="text" aria-label="Текст сообщения" placeholder="Напишите, что важно сообщить пользователям…">${esc(draft.text)}</textarea><div class="cmp-file" hidden><svg class="cmp-clip" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5 12.6 19.9a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"/></svg><small id="compose-file-name">JPG/PNG до 10 МБ · MP4 до 20 МБ</small><button type="button" class="cmp-file-clear" data-cmp-file-clear aria-label="Убрать файл">×</button></div></div><div class="cmp-block"><label class="check"><input type="checkbox" name="with_button" data-cmp-button ${draft.buttonOn?'checked':''}>Кнопка «Открыть приложение»</label><div class="cmp-button-field" ${draft.buttonOn?'':'hidden'}>${field('Текст на кнопке','button_text','text',draft.buttonText,'maxlength="40"')}</div></div>
   <div class="composer-live"><span class="eyebrow">ТАК УВИДЯТ ПОЛЬЗОВАТЕЛИ</span><div class="cmp-bubble"><b class="cmp-bubble-name">Platformer</b><div id="compose-live" class="compose-preview-text"><span class="muted">Сообщение появится здесь</span></div><small class="cmp-bubble-time">сейчас</small></div><div class="cmp-bubble-btn" id="compose-btn-preview" hidden></div></div></div>`;}
function composerRestore(draft){
 const area=$('#dialog textarea[name="text"]');if(area)area.dispatchEvent(new Event('input',{bubbles:true}));
 const input=$('#dialog input[name="media"]');
 if(input&&draft.file){try{const transfer=new DataTransfer();transfer.items.add(draft.file);input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));}catch{}}
 cmpButtonPreview();
 const d=$('#dialog');if(d)d.dataset.dirty=(draft.text||draft.file)?'1':'';
}
function composerValidate(values){
 const file=values.media?.size?values.media:null,text=String(values.text||'');
 if(broadcastLength(text)>4096)return 'Текст длиннее 4096 символов — сократите сообщение';
 if(!text.trim()&&!file)return 'Добавьте текст или файл';
 if(file){const type=String(file.type||'').toLowerCase(),name=String(file.name||'').toLowerCase(),video=type==='video/mp4'||name.endsWith('.mp4'),photo=['image/jpeg','image/png'].includes(type)||/\.(jpe?g|png)$/.test(name);
  if(!video&&!photo)return 'Выберите JPG, PNG или MP4';
  if(file.size>(video?20:10)*1024*1024)return 'Фото до 10 МБ, видео до 20 МБ';}
 return '';
}
function broadcastPreview(text){return esc(text).replace(/&lt;(\/?)(b|i|code|blockquote)&gt;/g,'<$1$2>');}
function fileSize(bytes){return `${number(bytes/1024/1024)} МБ`;}
async function mediaKind(file){const b=new Uint8Array(await file.slice(0,12).arrayBuffer());if(b[0]===255&&b[1]===216&&b[2]===255)return 'photo';if([137,80,78,71,13,10,26,10].every((v,i)=>b[i]===v))return 'photo';if(b[4]===102&&b[5]===116&&b[6]===121&&b[7]===112)return 'video';return null;}
paths.minus='M5 12h14';
paths.repeat='M17 2l3 3-3 3 M4 11V9a4 4 0 0 1 4-4h12 M7 22l-3-3 3-3 M20 13v2a4 4 0 0 1-4 4H4';
paths.upload='M12 15V4 M7 9l5-5 5 5 M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4';
paths.projects='M3 7h7l2 2h9v11H3z M3 7V4h7l2 3 M7 13h10 M7 16h6';
paths.activity='M3 12h4l3-8 4 16 3-8h4';paths.lists='M12 21s-7-4.4-9.3-9A5.2 5.2 0 0 1 12 6.6 5.2 5.2 0 0 1 21.3 12C19 16.6 12 21 12 21z';paths.calendar='M4 6h16v14H4z M4 10h16 M8 3v5 M16 3v5';paths.note='M5 3h10l4 4v14H5z M15 3v4h4 M8 12h8 M8 16h6';paths.bank='M3 10l9-6 9 6 M5 10v8 M9.5 10v8 M14.5 10v8 M19 10v8 M3 20h18';paths.plans='M4 6h16v14H4z M4 10h16 M8 3v5 M16 3v5 M9 15l2 2 4-4';paths.circle='M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9z M12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z';
// Platformer: разделы жизни — главная, финансы (проекты и TagMarket), активности, вишлисты, друзья.
// Настройки открываются по аватару в шапке
const tabs=[['overview','Главная'],['projects','Финансы'],['activity','Активности'],['plans','Планы'],['people','Друзья']];
const periods=[['today','Сегодня'],['yesterday','Вчера'],['week','Эта неделя'],['lastweek','Прошлая неделя'],['month','Этот месяц'],['lastmonth','Прошлый месяц'],['all','Всё время'],['custom','Свои даты']];
// Панель навигации строится один раз и дальше только переключает активную
// вкладку: если пересобирать разметку на каждый render(), подсветке не из
// чего «перетечь» — узлы каждый раз новые. Подсветка — отдельный слой
// .nav-glider под ссылками; он едет к новой вкладке, передний край чуть
// впереди заднего, как капля. Одна функция обслуживает и нижнюю панель
// телефона (горизонтальную), и боковую на десктопе (вертикальную).
const NAV_ROOTS=['#desktop-nav','#mobile-nav'];
function reducedMotion(){return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;}
function nav(){
 document.body.classList.toggle('onboarding-only',onboardingOnly());
 const active=['account','accounts','project','forecast','tagmarket','onboarding','banks','spend','income'].includes(state.view)?'projects':['faq','circle'].includes(state.view)?'overview':state.view;
 for(const selector of NAV_ROOTS){
  const root=$(selector);
  if(!root.dataset.ready){
   root.innerHTML='<span class="nav-glider" aria-hidden="true"></span>'+tabs.map(([id,label])=>`<a href="#${id}" data-tab="${id}" aria-label="${label}">${icon(id,'nav-icon')}<span>${label}</span></a>`).join('');
   root.dataset.ready='1';root.classList.add('has-glider');
  }
  // вкладка та же и подсветка уже стоит — не трогаем ничего: render() идёт и
  // на фоновом обновлении раз в 30-60 с, а moveGlider синхронно читает
  // offsetLeft/getBoundingClientRect и этим заставляет браузер пересчитать
  // вёрстку посреди кадра, в котором дальше целиком меняется #main.
  // _rect пуст у панели, скрытой в момент смены вкладки (на телефоне это
  // боковая): её подсветку ставим, когда она появится
  if(root.dataset.active===active&&root.querySelector('.nav-glider')?._rect)continue;
  root.dataset.active=active;
  root.querySelectorAll('a[data-tab]').forEach(link=>{const on=link.dataset.tab===active;link.classList.toggle('active',on);if(on)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
  moveGlider(root);
 }
 const crumb=$('#crumb'),title={project:'Финансы / Проект',account:'Финансы / Счёт',accounts:'Финансы / Счета',tagmarket:'Финансы / TagMarket',forecast:'Финансы / Прогноз',faq:'Вопросы и ответы',onboarding:'Как добавить свой счёт',settings:'Настройки',circle:'Главная / Круг жизни',banks:'Финансы / Банки'}[state.view]||tabs.find(([id])=>id===state.view)?.[1]||'Главная';
 // анимируем только настоящую смену: render() идёт и на фоновом обновлении,
 // где заголовок тот же и мигать ему незачем
 if(crumb.textContent!==title){
  crumb.textContent=title;
  crumb.classList.remove('is-changing');void crumb.offsetWidth;crumb.classList.add('is-changing');
 }
}
function moveGlider(root,instant=false){
 const glider=root.querySelector('.nav-glider'),link=root.querySelector('a.active');
 if(!glider)return;
 // скрытая панель (нижняя на десктопе, боковая на телефоне) размеров не имеет —
 // её подсветку поставим на место, когда панель появится (ResizeObserver ниже)
 if(!link||!root.offsetWidth){glider.classList.toggle('is-hidden',!link);glider._rect=null;return;}
 const to={x:link.offsetLeft,y:link.offsetTop,w:link.offsetWidth,h:link.offsetHeight};
 let from=glider._rect;
 // нажали новую вкладку, пока подсветка ещё едет: продолжаем с того места,
 // где она сейчас, а не прыгаем в конец прежнего пути
 if(from&&glider.getAnimations().length){const r=glider.getBoundingClientRect(),o=root.getBoundingClientRect();from={x:r.left-o.left-root.clientLeft,y:r.top-o.top-root.clientTop,w:r.width,h:r.height};}
 const place=r=>({transform:`translate(${r.x}px,${r.y}px)`,width:`${r.w}px`,height:`${r.h}px`});
 glider.getAnimations().forEach(a=>a.cancel());
 glider._rect=to;glider.classList.remove('is-hidden');Object.assign(glider.style,place(to));
 if(instant||!from||reducedMotion()||(from.x===to.x&&from.y===to.y&&from.w===to.w&&from.h===to.h))return;
 // середина пути: ведущий край прошёл 80%, отстающий — 25%, поэтому подсветка
 // на миг вытягивается в сторону движения и догоняет себя у цели
 const edge=(a,b,A,B)=>{const ahead=b>=a;return [a+(b-a)*(ahead?.25:.8),A+(B-A)*(ahead?.8:.25)];};
 const [x0,x1]=edge(from.x,to.x,from.x+from.w,to.x+to.w),[y0,y1]=edge(from.y,to.y,from.y+from.h,to.y+to.h);
 glider.animate([place(from),{...place({x:x0,y:y0,w:x1-x0,h:y1-y0}),offset:.42},place(to)],{duration:560,easing:'cubic-bezier(.3,.75,.25,1)'});
}
// Порядок разделов для направления перехода: вглубь и вправо по панели —
// новый экран въезжает справа, назад — слева
const VIEW_ORDER={banks:1.1,income:1.05,spend:1.08,overview:0,faq:.5,projects:1,tagmarket:1.2,onboarding:1.25,accounts:1.3,account:1.5,project:1.6,activity:3,plans:4,circle:.2,forecast:1.7,people:5,settings:6};
// Въезд — CSS-классом, который снимается по окончании: после WAAPI-анимации
// transform Chromium держал устаревшую карту попаданий, и первое нажатие в
// новом разделе уходило «мимо» кнопки, пока стиль #main не изменится
function enterView(direction){
 if(reducedMotion())return;
 const main=$('#main');
 main.classList.remove('view-enter');
 main.style.setProperty('--enter-x',direction?`${direction*12}px`:'0px');
 main.style.setProperty('--enter-y',direction?'0px':'10px');
 void main.offsetWidth;      // перезапуск, если прошлый въезд ещё идёт
 main.classList.add('view-enter');
}
// Уход старого экрана: без него переход был односторонним — старое исчезало
// мгновенно, новое въезжало, и глаз читал это как рывок. Уезжаем в ту же
// сторону, куда потом въедет новое. Короче въезда почти вдвое: уход — только
// подготовка, главное — как новый экран садится на место
function leaveView(direction){
 if(reducedMotion())return Promise.resolve();
 const main=$('#main');
 main.classList.remove('view-enter');
 const shift=direction?`translateX(${-direction*8}px)`:'translateY(-3px)';
 const anim=main.animate([{opacity:1,transform:'none'},{opacity:0,transform:shift}],
                         {duration:120,easing:'cubic-bezier(.45,0,.55,1)',fill:'forwards'});
 // не ждём дольше самой анимации: если вкладка ушла в фон, finished не придёт
 return Promise.race([anim.finished.catch(()=>{}),new Promise(r=>setTimeout(r,170))])
  .then(()=>anim.cancel());
}
$('#main').addEventListener('animationend',event=>{if(event.target===event.currentTarget)event.currentTarget.classList.remove('view-enter');});
function secHero(tone,title,sub='',actions='',eyebrow=''){return `<div class="page-head sec-hero tone-${tone}"><div class="sec-glow" aria-hidden="true"><i></i><i></i><i></i></div><div>${eyebrow?`<span class="sec-eyebrow">${esc(eyebrow)}</span>`:''}<h1>${esc(title)}</h1>${sub?`<p>${sub}</p>`:''}</div>${actions}</div>`;}
function header(title,subtitle='',action=''){return `<div class="page-head"><div><h1>${esc(title)}</h1>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div>${action}</div>`;}
function empty(title,text,action=''){return `<div class="empty">${icon('chart')}<h2>${esc(title)}</h2>${text?`<p>${esc(text)}</p>`:''}${action}</div>`;}
function skeleton(kind='list',rows=3){if(kind==='chart')return `<div class="skel skel-chart" aria-busy="true" aria-label="Загружаем"><i class="skel-line w40"></i><i class="skel-line w25 tall"></i><div class="skel-bars">${[40,62,35,78,52,90,44,66,30,58].map(h=>`<i style="height:${h}%"></i>`).join('')}</div></div>`;return `<div class="skel skel-list" aria-busy="true" aria-label="Загружаем">${Array.from({length:rows},()=>`<div class="skel-card"><i class="skel-ico"></i><span><i class="skel-line w55"></i><i class="skel-line w35"></i></span><i class="skel-line w20"></i></div>`).join('')}</div>`;}
function notificationItem(i){
 const [kind,ico,tone]=eventKind(i),target=notificationTarget(i),parts=notificationParts(i),title=notificationTitleParts(i);
 const login=/^trade:(\d+):/.exec(i.event_key||'')?.[1],account=login&&state.data?.accounts.find(a=>String(a.login)===login),who=account?[login,account.holder].filter(Boolean).join(' · '):'';
 return `<button type="button" data-action="notification-open" data-id="${esc(i.id)}" class="notification-item kind-${esc(i.kind||'other')} tone-${tone} ${i.read_at?'':'unread'}"><span class="notification-dot">${icon(ico)}</span><span class="notification-copy"><span class="nt-top"><small class="kicker">${esc([title.strategy||kind,who].filter(Boolean).join(' · '))}</small><small class="nt-time">${esc(Date.now()-Date.parse(/(Z|[+-]\d{2}:\d{2})$/.test(String(i.created_at))?i.created_at:i.created_at+'Z')>=864e5?`${weekdayOf(i.created_at)}, ${date(i.created_at,true)}`:since(i.created_at))}</small></span><span class="nt-main"><b>${esc(title.event||i.title)}</b>${parts.amount?`<strong class="nt-amount">${esc(parts.amount)}</strong>`:''}</span>${parts.lines.length?`<span class="nt-lines">${parts.lines.slice(0,3).map(esc).join('<br>')}</span>`:''}${target.hash?`<small class="meta"><em>${esc(target.label)} ${icon('arrow')}</em></small>`:''}</span></button>`;
}
const NOTIF_FILTERS=[['all','Все'],['trades','Сделки'],['money','Деньги'],['other','Прочее']];
function notificationGroup(item){return item.kind==='trades'?'trades':['deposits','withdrawals'].includes(item.kind)?'money':'other';}
function notificationPanel(){
 const all=state.notifications?.items||[],unread=state.notifications?.unread||0,filter=state.notifFilter||'all';
 if(!all.length)return `<div class="notification-empty">${icon('bell')}<h3>Событий пока нет</h3><p>Здесь появятся сделки, пополнения, выводы и сообщения сервиса.</p></div>`;
 const items=filter==='all'?all:all.filter(x=>notificationGroup(x)===filter);
 const counts=Object.fromEntries(NOTIF_FILTERS.map(([id])=>[id,id==='all'?all.length:all.filter(x=>notificationGroup(x)===id).length]));
 const tabs=`<div class="nt-filters segmented" role="tablist">${NOTIF_FILTERS.filter(([id])=>id==='all'||counts[id]).map(([id,label])=>`<button type="button" role="tab" aria-selected="${filter===id}" class="${filter===id?'active':''}" data-action="notif-filter" data-value="${id}">${label}<em>${counts[id]}</em></button>`).join('')}</div>`;
 const today=new Date().toISOString().slice(0,10),yesterday=new Date(Date.now()-864e5).toISOString().slice(0,10),groups=[];
 for(const i of items){const d=String(i.created_at||'').slice(0,10),label=d===today?`Сегодня · ${weekdayOf(d)}`:d===yesterday?`Вчера · ${weekdayOf(d)}`:`${weekdayOf(d)}, ${date(d)}`,last=groups.at(-1);if(last&&last.label===label)last.items.push(i);else groups.push({label,items:[i]});}
 return `<div class="nt-bar">${tabs}${unread?button('notifications-read','Прочитать всё','secondary small','check'):''}</div>${items.length?`<div class="notification-list">${groups.map(g=>`<section class="notification-group"><h3>${esc(g.label)}</h3>${g.items.map(notificationItem).join('')}</section>`).join('')}</div>`:`<div class="notification-empty"><h3>В этом разделе пусто</h3></div>`}`;
}
function updateNotificationBadge(){const button=$('#notifications');const unread=state.notifications?.unread||0;button.classList.toggle('has-unread',unread>0);button.setAttribute('aria-label',unread?`Уведомления: ${unread} новых`:'Уведомления');}
async function openNotifications(){state.notifications=await api('/notifications');updateNotificationBadge();await dialog('Уведомления',notificationPanel(),'Закрыть');}
async function openNotification(id){
 const item=state.notifications.items.find(i=>i.id===Number(id));if(!item)return;
 const target=notificationTarget(item);
 if(!target.hash){
  // читать больше нечего: текст уже виден в списке — только отмечаем прочитанным и оставляем список открытым
  if(!preview&&!item.read_at){state.notifications=await api('/notifications',{method:'POST',body:JSON.stringify({action:'read',ids:[item.id]})});}
  else if(preview&&!item.read_at){state.notifications={...state.notifications,unread:Math.max(0,state.notifications.unread-1),items:state.notifications.items.map(x=>x.id===item.id?{...x,read_at:new Date().toISOString()}:x)};}
  updateNotificationBadge();const body=$('#dialog-body');if(body&&$('#dialog').open)body.innerHTML=notificationPanel();return;
 }
 const d=$('#dialog');if(d.open){const closed=new Promise(resolve=>d.addEventListener('close',resolve,{once:true}));d.close('cancel');await closed;}
 $('#toast').classList.remove('visible');
 if(!preview&&!item.read_at){state.notifications=await api('/notifications',{method:'POST',body:JSON.stringify({action:'read',ids:[item.id]})});updateNotificationBadge();}
 location.hash=target.hash;
}
async function readAllNotifications(){const ids=(state.notifications?.items||[]).filter(i=>!i.read_at).map(i=>i.id);if(!ids.length)return;if(!preview)state.notifications=await api('/notifications',{method:'POST',body:JSON.stringify({action:'read',ids})});else state.notifications={...state.notifications,unread:0,items:state.notifications.items.map(i=>({...i,read_at:i.read_at||new Date().toISOString()}))};updateNotificationBadge();const body=$('#dialog-body');if(body&&$('#dialog').open)body.innerHTML=notificationPanel();}
async function addShortcut(){const help='<p>Откройте мини-приложение из чата с ботом в Telegram. Нажмите ⋮ справа сверху и выберите «Добавить на главный экран», если этот пункт есть на устройстве.</p><a class="text-link" href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">Открыть бота в Telegram</a>';if(preview||!tg?.initData)return dialog('Ярлык Platformer',help,'Понятно');if(!tg?.addToHomeScreen)return dialog('Ярлык Platformer',help,'Понятно');try{if(tg.checkHomeScreenStatus)tg.checkHomeScreenStatus(s=>{if(s==='added')toast('Ярлык уже добавлен');else if(s==='unsupported')dialog('Ярлык Platformer',help,'Понятно');else tg.addToHomeScreen();});else tg.addToHomeScreen();}catch{return dialog('Ярлык Platformer',help,'Понятно');}}
function authScreen(){return `<main class="auth-screen"><div class="auth-glow"></div><div class="auth-brand"><span class="brand-wordmark"><strong>PLATFORMER</strong><small>PERSONAL SPACE</small></span></div><span class="eyebrow">ЛИЧНОЕ ПРОСТРАНСТВО · TELEGRAM MINI APP</span><h1>Вся жизнь<br><em>в одном ритме.</em></h1><p>Откройте приложение из чата с ботом, чтобы увидеть финансы, активности, вишлисты и друзей в защищённом личном пространстве.</p><a class="button primary auth-button" href="https://t.me/tagmarketgold_bot">Открыть бота в Telegram ${icon('arrow')}</a><small>Ссылка на приложение работает только внутри Telegram.</small></main>`;}
// выданный счёт выглядит как свой, только мелкая подпись: кто и когда его выдал
function sharedNote(a){if(!a.shared)return '';const who=a.shared_by_name?`Выдал ${esc(a.shared_by_name)}`:'Выдан по приглашению';return `<small class="shared-note">${who}${a.shared_at?` · ${esc(date(a.shared_at))}`:''}</small>`;}
function accountBadge(a){return sharedNote(a)+(!a.enabled?'<span class="badge">На паузе</span>':a.status==='pending'?'<span class="badge warning">Ожидаем данные счёта</span>':'');}
function accountCard(a,i=0,holder=true){const t=a.totals,cur=t?.cur||'USD';return `<a href="#account/${esc(a.login)}" class="panel account-card"><div class="strategy-icon ${i%2?'':'green'}">${icon('chart')}</div><div class="account-info"><h3>${esc(a.strategy||a.name)}</h3><p>${holder!==false?`${esc(a.holder||a.name)} · `:'MT5 '}${esc(a.login)}</p>${accountBadge(a)}</div><div class="account-money"><b>${t?money(t.now,cur):'—'}</b>${t?`<p class="${signedClass(t.month_net)}">${money(t.month_net,cur,true)} · ${percent(t.month_pct)}<em> мес.</em></p>${t.today_net?`<p class="account-today ${signedClass(t.today_net)}">${money(t.today_net,cur,true)}<em> сегодня</em></p>`:''}`:'<p>Пока нет данных</p>'}</div>${icon('chevron','chevron')}</a>`;}
function countLabel(n,forms){const v=Math.abs(Number(n))%100;const n10=v%10;return `${n} ${v>10&&v<20?forms[2]:n10===1?forms[0]:n10>=2&&n10<=4?forms[1]:forms[2]}`;}
function strategyFamily(a){const name=String(a.strategy||a.name||'').trim();return /sonic|sonik/i.test(name)?'SONIC':/neo/i.test(name)?'NEO':name;}
function sonicStrategyCard(){
 const heading=`<div class="strategy-card-head"><div><span class="eyebrow">НАША СТРАТЕГИЯ</span><h3>SONIC</h3></div><span class="strategy-chip">XAUUSD · золото</span></div>`;
 return `<section class="panel strategy-card strategy-full">${heading}<div class="strategy-facts"><span><b>1–2</b><small>сделки в день</small></span><span><b>0,2–0,5%</b><small>депозита на вход</small></span><span><b>30%</b><small>комиссия с прибыли</small></span></div><div class="risk-line">${icon('shield')}<p>Торговый баланс с плечом можно потерять полностью. Прошлые результаты не гарантируют будущих.</p></div><a href="#faq" class="button secondary wide faq-link">${icon('chevron')}<span class="button-label">Вопросы и ответы</span></a></section>`;
}
// Раздел «Вопросы и ответы»: стратегии, подключение по шагам, вывод, партнёрка,
// MetaTrader 5, лицензия. Источник — инструкции канала (t.me/pro_procent1/523);
// чужая реферальная ссылка и личные контакты оттуда не берутся — регистрация
// идёт по партнёрской ссылке владельца этого кабинета
const FAQ_IMG=(src,alt)=>`<button type="button" class="faq-shot" data-action="faq-image" data-src="${src}" data-alt="${esc(alt)}"><img src="${src}" alt="${esc(alt)}" loading="lazy" decoding="async"></button>`;
// Шаги регистрации и подключения — общие для «Частых вопросов» и экрана
// знакомства новичка: одна копия текста, чтобы они не разошлись
const REG_STEPS=[
'Откройте ссылку регистрации <b>в браузере</b> — скопируйте и вставьте, не открывайте из Telegram или WhatsApp.',
   'Заполните все поля латиницей. Телефон и адрес не важны.',
   'Подтвердите почту в письме от IB-портала и снова войдите в портал.',
   'Нажмите «Tag Registration» — личный кабинет Tag Markets создастся сам, пароль придёт на ту же почту.',
   '<b>Важно:</b> нажмите «Confirm Email» в письме от Tag Markets — только после этого регистрация завершена.'];
function copySteps(){const code=v=>`<code class="faq-code">${esc(v)}</code>`;return [
'Зайдите на платформу Tag Markets и пополните депозит.',
   'Вверху справа нажмите меню (четыре линии), пролистайте вниз и выберите «CopyX».',
   `В поиске введите ${code('NEO')} и выберите NEO.FX (или SONIC).`,
   'Нажмите «Details», затем «Connect».',
   'В поле «Invest» введите сумму, которую хотите инвестировать.',
   `Раскройте «Community Token», в поле «Code» введите ${code('#NEO')} и нажмите «Verify» — <b>это нужно для бонуса ×24</b>.`,
   `В поле «HASH/GU-ID» введите ровно шесть нулей ${code('000000')} и нажмите «Submit».`,
   'Отметьте две галочки и нажмите «Copy Now» — стратегия запущена.'];}
function faqStrategy(name,tag,facts,text,shots,link){
 return `<details class="faq-strategy" data-ui-key="strategy-${esc(name)}"><summary class="faq-strategy-head"><span class="faq-strategy-mark">${esc(tag)}</span><span class="faq-strategy-title"><h3>${esc(name)}</h3><small>${esc(facts[0])}</small></span><span class="faq-strategy-toggle"><span class="when-closed">Развернуть</span><span class="when-open">Свернуть</span>${icon('chevron')}</span></summary><div class="faq-body"><ul class="faq-facts">${facts.slice(1).map(([k,v])=>`<li><small>${esc(k)}</small><b>${esc(v)}</b></li>`).join('')}</ul><p>${esc(text)}</p><div class="faq-shots">${shots.map(([s,a])=>FAQ_IMG(s,a)).join('')}</div>${link||''}<p class="faq-note">Цифры — из карточек стратегий у брокера. Прошлые результаты не гарантируют будущих: торговый баланс с плечом можно потерять.</p></div></details>`;
}
function faqSteps(steps){return `<ol class="faq-steps">${steps.map(s=>`<li><span>${s}</span></li>`).join('')}</ol>`;}
function faqItem(q,body,open=false){return `<details class="faq-item" data-ui-key="faq-${esc(q)}"${open?' open':''}><summary><span>${esc(q)}</span>${icon('chevron')}</summary><div class="faq-body">${body}</div></details>`;}
function faqGroup(eyebrow,title,ico,items,id='',classes='panel faq-card'){return `<section class="${classes}"${id?` id="${id}"`: ''}><div class="faq-card-head"><span class="faq-card-icon">${icon(ico)}</span><div><span class="eyebrow">${esc(eyebrow)}</span><h2>${esc(title)}</h2></div></div>${items}</section>`;}
function faqView(){
 const reg=state.data?.onboarding?.registration_url||'';
 const ext=(href,label)=>`<a class="text-link" href="${esc(href)}" target="_blank" rel="noopener">${esc(label)} ${icon('arrow')}</a>`;
 const code=v=>`<code class="faq-code">${esc(v)}</code>`;
 const strategies=faqGroup('СТРАТЕГИИ','NEO и SONIC','chart',
  faqStrategy('SONIC','XAU',['Алгоритм + трейдер · золото (XAUUSD)',['Подписчиков','140 000+'],['Доходность','~20% в месяц'],['Макс. просадка','0,26%'],['Прибыльных сделок','≈ 89%'],['Комиссия','30% от прибыли'],['Минимум','10 $']],
   'Входит в сделку на 0,2–0,5% депозита, в среднем 1–2 сделки в день. Одиночные ордера с коротким стоп-лоссом и тейк-профитом, сделки не держит долго: зашёл — вышел.',
   [['faq-sonic-card.jpg','Карточка стратегии SONIC в CopyX'],['faq-sonic-stats.jpg','Статистика SONIC: ROI, винрейт, просадка']])
  +faqStrategy('NEO.FX','EUR',['Трейдер вручную · евро/доллар (EURUSD)',['Подписчиков','27 000+'],['Доходность','~10% в месяц'],['Макс. просадка','0,9%'],['Прибыльных сделок','≈ 88%'],['Комиссия','30% от прибыли'],['Депозитов','27 млн $+']],
   'Строго одна сделка в день на 0,5% депозита, с коротким стоп-лоссом и тейк-профитом. В дни без подходящей ситуации на рынке пропускает торговлю. Очень консервативен: сохранность депозита важнее доходности.',
   [['faq-neo-card.jpg','Карточка стратегии NEO.FX в CopyX'],['faq-neo-stats.jpg','Статистика NEO.FX: ROI, винрейт, просадка'],['faq-neo-myfxbook.jpg','Статистика NEO на myfxbook']],
   `<div class="faq-links">${ext('https://www.myfxbook.com/members/WordSmithyFx/neofx/11800152','NEO на myfxbook с октября 2025')}${ext('https://www.myfxbook.com/members/WordSmithyFx/neo-fx/11779491','Тестовый период март–ноябрь 2025')}</div>`)
  ,'','faq-strategies');
 const connect=faqGroup('КАК НАЧАТЬ','Подключение по шагам','plus',
  faqItem('1. Регистрация',faqSteps(REG_STEPS)
   +(reg?`<a class="button primary faq-cta" href="${esc(reg)}" target="_blank" rel="noopener">Открыть регистрацию ${icon('arrow')}</a>`:'<p class="faq-note">Ссылку на регистрацию даст тот, кто вас пригласил.</p>'),!!state.faqDeep)
  +faqItem('2. Верификация',`<p>После регистрации пройдите верификацию личности в кабинете Tag Markets — без неё недоступны пополнение и вывод.</p>`)
  +faqItem('3. Пополнение и подключение к копитрейдингу',faqSteps(copySteps())
   +`<div class="faq-shots">${FAQ_IMG('faq-neo-card.jpg','Кнопка Connect в карточке стратегии')}</div>`)
  +faqItem('Можно попробовать без своих денег',`<p>Да — в приложении есть демо-счёт «Копитрейдинг 45k». Он показывает реальную динамику стратегии, но не входит в ваш капитал.</p>`)
  +faqItem('Как добавить свой счёт в это приложение',`<p>Добавьте счёт в разделе «Счета» с инвесторским паролем MT5 — дальше сделки и баланс обновляются сами.</p><a class="text-link" href="#accounts">Мои счета ${icon('arrow')}</a>`),'faq-connect');
 const money_=faqGroup('ДЕНЬГИ','Вывод и комиссия','accounts',
  faqItem('Как вывести доход',`<p>Через кабинет брокера. Выбирайте сеть USDT BEP-20 — у неё минимальный порог.</p><ul class="faq-chips"><li><b>USDT BEP-20</b><small>от 10 $ · рекомендуем</small></li><li><b>USDT TRC-20</b><small>от 50 $</small></li></ul>${ext('https://portal.tagmarkets.com/','Кабинет Tag Markets')}`)
  +faqItem('Какая комиссия',`<p>30% с прибыли — и только когда стратегия заработала. Списывается автоматически у брокера, в приложении видна отдельной строкой в «Движениях средств».</p>`)
  +faqItem('Что такое Amplify ×24',`<p>Брокер усиливает торговый баланс плечом ×24: капитал = баланс счёта ÷ 24. Прибыль считается от полного торгового баланса, поэтому для вашего капитала она заметнее. Бонус включается кодом ${code('#NEO')} при подключении.</p>${ext('https://www.tagmarkets.com/amplify/','Условия Amplify')}`)
  +faqItem('Где физически мои деньги',`<p>На вашем личном счёте MT5 у брокера Tag Markets — не у нас и не в общем пуле. Вывод можно запросить в любой момент через кабинет брокера.</p>`));
 const partner=faqGroup('ПАРТНЁРАМ','Партнёрская программа','people',
  faqItem('Где взять реферальную ссылку',`<p>IB Portal → Profile → Partner Referral Links.</p>${ext('https://exfusion.ibportal.io/profile','Открыть IB Portal')}`)
  +faqItem('Когда выплачиваются вознаграждения',`<p>Вечером каждого воскресенья. Вывод — через кабинет Tag Markets; сети и минимальные суммы указаны выше в разделе «Вывод и комиссия».</p>${ext('https://portal.tagmarkets.com/','Кабинет Tag Markets')}`));
 const license=faqGroup('БРОКЕР','Tag Markets и лицензия','shield',
  faqItem('Кто такой брокер Tag Markets',`<p>Tag Markets (tagmarkets.com) принадлежит T.M. Financials Ltd — компании, зарегистрированной на Маврикии (рег. № C185265). Регулируется Комиссией по финансовым услугам Маврикия (FSC) как инвестиционный дилер, лицензия № GB21026474. На рынке 3 года, около 700 000 клиентов.</p><div class="faq-shots">${FAQ_IMG('faq-license.jpg','Лицензия FSC Маврикия')}</div><div class="faq-links">${ext('https://opr.fscmauritius.org/ords/opr/r/fsc-opr/fsc-online-public-register-opr','Реестр лицензий FSC')}${ext('https://www.tagmarkets.com/','Сайт брокера')}</div>`)
  +faqItem('При чём тут TM Financials SA',`<p>TM FINANCIALS SA (PTY) LTD (рег. № 2024/508189/07) — авторизованный поставщик финансовых услуг (FSP № 55237), регулируется FSCA. Оказывает только маркетинговые услуги; торговые счета и ликвидность — у T.M. Financials Ltd.</p>`));
 return `<a href="#tagmarket" class="text-link back">${icon('back')} TagMarket</a><div class="page-head"><div><h1>Вопросы и ответы</h1></div></div><div class="faq-page">${strategies}${connect}${money_}${partner}${license}</div>`;
}
// скриншот проявляется, когда загрузился: до этого — тёмная заглушка в тон
// карточки. Inline onload запрещён политикой безопасности — слушаем здесь
document.addEventListener('load',e=>{if(e.target.matches?.('.faq-shot img'))e.target.classList.add('is-loaded');},true);
// Плавное раскрытие вопросов в обе стороны: у <details> браузер открывает и
// закрывает содержимое мгновенно, поэтому высоту анимируем сами
document.addEventListener('click',event=>{
 const summary=event.target.closest('.faq-item > summary, .faq-strategy > summary, .people-card > summary');if(!summary)return;
 const item=summary.parentElement,body=item.querySelector('.faq-body');if(!body||reducedMotion())return;
 event.preventDefault();
 if(item._anim){item._anim.cancel();item._anim=null;}
 const opening=!item.open||item.classList.contains('is-closing');
 const from=body.getBoundingClientRect().height;
 if(opening){item.classList.remove('is-closing');item.open=true;}
 else item.classList.add('is-closing');
 const to=opening?body.scrollHeight:0;
 const anim=body.animate([{height:`${from}px`,opacity:opening?Math.min(1,from/Math.max(1,to)):1},{height:`${to}px`,opacity:opening?1:0}],{duration:opening?340:260,easing:'cubic-bezier(.22,1,.36,1)'});
 item._anim=anim;
 anim.onfinish=()=>{item._anim=null;if(!opening){item.open=false;item.classList.remove('is-closing');}};
});
function sonicGuide(){return `<section class="panel license-card broker-card"><div class="license-card-head"><span class="license-icon">${icon('shield')}</span><div><span class="eyebrow">БРОКЕР И СЧЁТ</span><h2>Tag Markets</h2></div></div><p>Торговое название «T.M. Financials Ltd», регулируется FSC как инвестиционный дилер, лицензия № GB21026474.</p><div class="license-actions"><a class="button secondary" href="https://www.tagmarkets.com/" target="_blank" rel="noopener">Сайт брокера ${icon('arrow')}</a></div></section>`;}
function compactStrategy(a){const name=a.strategy||a.name;const sonic=/sonic|sonik/i.test(name),neo=/neo/i.test(name);return `<section class="panel detail-strategy"><span class="eyebrow">СТРАТЕГИЯ СЧЁТА</span><div><h2>${esc(name)}</h2><span class="badge">${sonic?'XAUUSD':neo?'NEO':'MT5'}</span></div></section>`;}
let dynSeq=0,dynActive=null;
function smoothPath(p){const f=v=>Math.round(v*10)/10,n=p.length,d=[],m=[];for(let i=0;i<n-1;i++)d.push((p[i+1][1]-p[i][1])/(p[i+1][0]-p[i][0]));m[0]=d[0];m[n-1]=d[n-2];for(let i=1;i<n-1;i++)m[i]=d[i-1]*d[i]<=0?0:(d[i-1]+d[i])/2;for(let i=0;i<n-1;i++){if(!d[i]){m[i]=m[i+1]=0;continue;}const a=m[i]/d[i],b=m[i+1]/d[i],q=a*a+b*b;if(q>9){const t=3/Math.sqrt(q);m[i]=t*a*d[i];m[i+1]=t*b*d[i];}}let out=`M${f(p[0][0])},${f(p[0][1])}`;for(let i=0;i<n-1;i++){const dx=(p[i+1][0]-p[i][0])/3;out+=` C${f(p[i][0]+dx)},${f(p[i][1]+m[i]*dx)} ${f(p[i+1][0]-dx)},${f(p[i+1][1]-m[i+1]*dx)} ${f(p[i+1][0])},${f(p[i+1][1])}`;}return out;}
// График динамики: линия от уровня начала периода через итог каждого дня,
// под ней столбики результата дня. mode 'result' — накопленная доходность
// (без пополнений и выводов), иначе баланс, если он восстановлен за все дни.
function chart(points,cur='USD',archived=false,scope='счёта',timeline=null,opts={}){
 const rows=timeline||points||[];
 if(!rows.length)return `<div class="chart-wrap chart-unavailable">${empty('Нет данных о состоянии счёта за этот период','')}</div>`;
 const result=opts.mode==='result',balance=!result&&rows.every(p=>Number.isFinite(p.balance)),capital=Number(opts.capital)||0;let total=0;
 const raw=rows.map(p=>{const value=Number(p.value)||0;total+=value;return {day:p.day,value,v:balance?Number(p.balance):total};});
 const start=balance?raw[0].v-raw[0].value:0,k=Math.ceil(raw.length/180),items=[];
 for(let i=0;i<raw.length;i+=k){const g=raw.slice(i,i+k);items.push({day:g[0].day,end:g.at(-1).day,value:g.reduce((a,x)=>a+x.value,0),v:g.at(-1).v});}
 const n=items.length,vals=[start,...items.map(x=>x.v)],min=Math.min(...vals),max=Math.max(...vals),range=max-min||1,flat=max===min;
 const Y=v=>flat?90:166-(v-min)/range*150,f=v=>Math.round(v*10)/10;
 const line=flat?`M0,90 H640`:smoothPath(vals.map((v,j)=>[j/n*640,Y(v)]));
 const last=vals.at(-1),tone=last>=start?'up':'down',id=`dyn-fill-${++dynSeq}`,label=result?'Доходность':balance?'Баланс':'Накопленный результат';
 const peak=Math.max(...items.map(x=>Math.abs(x.value)),0),span=x=>x.day===x.end?date(x.day):`${date(x.day)} – ${date(x.end)}`;
 const level=v=>result?`${money(v,cur,true)}${capital>0?` · ${percent(v/capital*100)}`:''}`:money(v,cur);
 const tips=items.map((x,i)=>[span(x),level(x.v),money(x.value,cur,true),+((i+1)/n*100).toFixed(2),+(Y(x.v)/180*100).toFixed(2),Math.sign(x.value)]);
 const active=raw.filter(x=>x.value!==0),wins=active.filter(x=>x.value>0).length;
  const meta=result?[['Прибыльных дней',active.length?`${wins} из ${active.length}`:'—'],['Средний день',active.length?money(active.reduce((a,x)=>a+x.value,0)/active.length,cur,true):'—']]
  :[['На начало',money(start,cur)],['Сейчас',money(last,cur)],['Прибыльных дней',active.length?`${wins} из ${active.length}`:'—']];
 return `<div class="dyn dyn-${tone}"><div class="dyn-plot" data-dyn="${esc(JSON.stringify(tips))}"><svg class="dyn-svg" viewBox="0 0 640 180" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" class="dyn-stop" stop-opacity=".3"/><stop offset="100%" class="dyn-stop" stop-opacity="0"/></linearGradient></defs>${[16,91,166].map(y=>`<path class="chart-grid" vector-effect="non-scaling-stroke" d="M0 ${y}H640"/>`).join('')}${flat?'':`<path class="dyn-base" vector-effect="non-scaling-stroke" d="M0 ${f(Y(start))}H640"/>`}<path class="dyn-area" fill="url(#${id})" d="${line} L640,180 L0,180Z"/><path class="chart-line dyn-line" vector-effect="non-scaling-stroke" d="${line}"/></svg>${flat?'':`<span class="dyn-axis" style="top:${f(16/1.8)}%">${money(max,cur,result)}</span><span class="dyn-axis" style="top:${f(166/1.8)}%">${money(min,cur,result)}</span>`}<span class="dyn-now" style="top:${f(Y(last)/1.8)}%"></span><div class="dyn-cursor" hidden><i></i><span class="dyn-cursor-dot"></span><div class="dyn-tip"></div></div></div><div class="dyn-bars" style="--gap:${n>60?1:3}px" aria-hidden="true">${items.map(x=>`<i class="${x.value>0?'up':x.value<0?'down':''}" style="--h:${peak&&x.value?Math.max(8,Math.abs(x.value)/peak*100).toFixed(1):8}%"></i>`).join('')}</div><ol class="dyn-sr">${items.map(x=>`<li>${esc(span(x))} · ${label}: ${esc(level(x.v))} · Результат: ${esc(money(x.value,cur,true))}</li>`).join('')}</ol>${balance||result?'':'<p class="chart-data-note">Нет данных о состоянии счёта за этот период. Показан накопленный результат; ежедневный баланс не восстановлен.</p>'}<div class="chart-labels"><span>${date(rows[0].day)}</span><span>${archived?'Архив и сделки':label} · ${esc(cur)}</span><span>${date(rows.at(-1).day)}</span></div><div class="dyn-meta">${meta.map(([t,v])=>`<span><small>${t}</small><b>${v}</b></span>`).join('')}</div></div>`;
}
function dynHide(plot){const c=plot.querySelector('.dyn-cursor');if(c)c.hidden=true;plot.parentElement?.querySelectorAll('.dyn-bars i.active').forEach(b=>b.classList.remove('active'));}
function dynMove(e){const plot=e.target.closest?.('.dyn-plot,.dyn-bars')?.closest('.dyn')?.querySelector('.dyn-plot');if(!plot){if(dynActive){dynHide(dynActive);dynActive=null;}return;}if(dynActive&&dynActive!==plot)dynHide(dynActive);dynActive=plot;const pts=plot._pts||(plot._pts=JSON.parse(plot.dataset.dyn)),r=plot.getBoundingClientRect(),n=pts.length,i=Math.max(0,Math.min(n-1,Math.floor((e.clientX-r.left)/r.width*n))),[day,val,res,x,y,sign]=pts[i],c=plot.querySelector('.dyn-cursor');c.hidden=false;c.style.setProperty('--x',`${x}%`);c.style.setProperty('--y',`${y}%`);c.classList.toggle('edge-l',x<24);c.classList.toggle('edge-r',x>76);c.querySelector('.dyn-tip').innerHTML=`<small>${esc(day)}</small><b>${esc(val)}</b><span class="${sign>0?'positive':sign<0?'negative':'muted'}">${esc(res)} за день</span>`;plot.parentElement.querySelectorAll('.dyn-bars i').forEach((b,k)=>b.classList.toggle('active',k===i));}
document.addEventListener('pointermove',dynMove);document.addEventListener('pointerdown',dynMove);
document.addEventListener('pointerup',e=>{if(e.pointerType==='mouse'||!dynActive)return;const plot=dynActive;setTimeout(()=>{if(dynActive===plot){dynHide(plot);dynActive=null;}},1800);});

function stats(items){return `<div class="stats ${items.length===2?'stats-two':items.length===1?'stats-one':''}">${items.map(([title,value,note,cls,ico])=>`<div class="panel stat"><div class="stat-title">${esc(title)}${icon(ico||'chart')}</div><div class="stat-value ${cls||''}">${value}</div>${note?`<div class="stat-note">${esc(note)}</div>`:''}</div>`).join('')}</div>`;}
function currentAccount(){if(state.view==='account'&&state.login)return state.data.accounts.find(a=>String(a.login)===String(state.login))||null;return state.data.accounts.find(a=>String(a.login)===String(state.login))||state.data.accounts.find(a=>a.enabled)||state.data.accounts[0];}
function periodTabs(only){const short={today:'Сегодня',yesterday:'Вчера',week:'Неделя',month:'Месяц',all:'Всё'};const list=only?only.map(k=>[k,short[k]]):periods;return `<div class="segmented ${only?'compact':''}">${list.map(([key,label])=>`<button data-action="period" data-value="${key}" class="${state.period===key?'active':''}">${label}</button>`).join('')}</div>`;}
// Динамика доходности лентой дней: новые сверху, полоска — доля от самого
// крупного дня, справа результат дня и накопленный итог периода. Дни без
// сделок (выходные) не выводим, но учитываем в итоге.
function dayFeed(rep,capital){const cur=rep.currency||'USD',rows=(rep.timeline?.length?rep.timeline:rep.chart||[]).map(p=>({day:p.day,value:Number(p.value)||0}));let total=0;const days=rows.map(p=>({...p,total:(total+=p.value)})).filter(p=>p.value!==0).slice(-180);if(!days.length)return empty('Пока нет закрытых сделок','Результат по дням появится после первой сделки за период.');const best=days.reduce((a,b)=>b.value>a.value?b:a),worst=days.reduce((a,b)=>b.value<a.value?b:a),peak=Math.max(...days.map(p=>Math.abs(p.value))),wins=days.filter(p=>p.value>0).length,avg=days.reduce((a,p)=>a+p.value,0)/days.length;
 const weekday=d=>fmtDate(new Intl.DateTimeFormat('ru-RU',{weekday:'short',timeZone:'UTC'}),new Date(`${d}T00:00:00Z`));
 const span=Math.max(...days.map(p=>p.value>0?p.value:0),0)+Math.max(...days.map(p=>p.value<0?-p.value:0),0)||1,negShare=Math.max(...days.map(p=>p.value<0?-p.value:0),0)/span*100;
 const info=p=>JSON.stringify([`${date(p.day)} · ${weekday(p.day)}`,money(p.value,cur,true),capital>0?percent(p.value/capital*100):'',`с начала периода ${money(p.total,cur,true)}${capital>0?` · ${percent(p.total/capital*100)}`:''}`,p.value>0?1:-1]);
 const bestDay=days.reduce((a,b)=>b.value>a.value?b:a),worstDay=days.reduce((a,b)=>b.value<a.value?b:a);
 const cube=(p,k)=>`<button type="button" class="cube ${p.value>0?'up':'down'}${k===days.length-1?' active':''}${p===bestDay&&p.value>0?' best':''}${p===worstDay&&p.value<0?' worst':''}" style="--h:${Math.max(5,Math.abs(p.value)/span*100).toFixed(1)}%;--i:${Math.min(k,40)}" data-cube="${esc(info(p))}" aria-label="${esc(`${date(p.day)}: ${money(p.value,cur,true)}`)}"></button>`;
 const detail=info(days.at(-1));
 const show=(d)=>{const [day,val,pct,total,sign]=JSON.parse(d);return `<b>${esc(day)}</b><strong class="${sign>0?'positive':'negative'}">${esc(val)}</strong>${pct?`<em class="${sign>0?'positive':'negative'}">${esc(pct)}</em>`:''}<small>${esc(total)}</small>`;};
 return `<div class="cubes" style="--base:${negShare.toFixed(1)}%"><div class="cubes-scroll"><div class="cubes-row" role="list" style="--n:${days.length}">${days.map(cube).join('')}</div></div></div><div class="cube-detail" aria-live="polite">${show(detail)}</div><div class="cube-axis"><span>${esc(date(days[0].day))}</span><span>${esc(date(days.at(-1).day))}</span></div><div class="feed-meta"><span><small>Прибыльных дней</small><b>${wins} из ${days.length}</b></span><span><small>Средний день</small><b class="${signedClass(avg)}">${money(avg,cur,true)}</b></span>${days.length>1?`<span><small>Лучший день · ${esc(date(best.day))}</small><b class="positive">${money(best.value,cur,true)}${capital>0?` <em>${percent(best.value/capital*100)}</em>`:''}</b></span><span><small>Худший день · ${esc(date(worst.day))}</small><b class="${signedClass(worst.value)}">${money(worst.value,cur,true)}${capital>0?` <em>${percent(worst.value/capital*100)}</em>`:''}</b></span>`:''}</div>`;}
function fxNote(fx){if(fx.stale){const at=new Date(fx.updated_at);const time=isNaN(at)?'':' от '+new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit'}).format(at);return `<small class="stat-note warn-text fx-stale">Используется последний доступный курс${time}</small>`;}return '';}
function timeMsk(value){return `${String(value||'').slice(11,16)} МСК`;}
function periodBar(){return `<section class="report-controls panel"><div class="report-control report-period">${periodTabs()}</div></section>${customDates()}`;}
function customDates(){return state.period==='custom'?`<div class="custom-period"><div class="field-row"><label class="field">С даты<input type="date" id="from-date" value="${esc(state.from)}"></label><label class="field">По дату<input type="date" id="to-date" value="${esc(state.to)}"></label></div>${button('apply-period','Показать результат','secondary small')}</div>`:'';}
// Инструкция открывается только явным переходом на отдельный экран.
function onboardingOnly(){return state.view==='onboarding';}
function welcomeView(){
 const step=(n,title,text)=>`<article class="own-step"><span>${n}</span><div><b>${title}</b><p>${text}</p></div></article>`;
 return header('Как добавить свой счёт','',button('onboard-close','Назад','secondary small','back'))+
  `<section class="own-guide"><p class="muted">Это займёт несколько шагов. К инструкции можно вернуться позже.</p>
  <div class="own-steps">${step(1,'Откройте кабинет Tag Markets','Зарегистрируйтесь и пройдите проверку личности.')}${step(2,'Подготовьте данные','Нужны Customer Number кабинета, название стратегии, логин MT5 и инвесторский пароль. Сервер определится автоматически.')}${step(3,'Добавьте счёт в TagMarket','Используйте инвесторский пароль — он даёт доступ только для просмотра.')}</div>
  ${button('add','Добавить свой счёт','primary','plus')}</section>`;
}
// Карточка с инструкцией показывается только пока нет личного счёта.
function resumeBanner(){return `<section class="panel resume-banner"><span class="faq-card-icon">${icon('plus')}</span><div><b>Добавить свой счёт</b><small>Хотите подключить личный счёт? Посмотрите, как это сделать.</small></div>${button('onboard-open','Как открыть счёт','secondary small','arrow')}</section>`;}
function showAccountGuide(open){state.view=open?'onboarding':'tagmarket';nav();render();window.scrollTo(0,0);}
// проект на паузе виден в списке, но в суммы, динамику и прогноз не входит
// TagMarket показывается балансом: капитал вместе с результатом сделок, который ещё не вывели
function tagBalance(){const t=state.data.totals.USD;return t?.balance??t?.capital??0;}
function activeProjects(){return (state.projects||[]).filter(p=>!p.paused);}
function fxBreakdown(all){const sums={};const add=(cur,v)=>{cur=cur||'USD';sums[cur]=(sums[cur]||0)+Number(v||0);};add('USD',tagBalance());if(all)for(const p of activeProjects())add(p.currency,p.current_total??p.total);return Object.entries(sums);}
function fxWarning(){const d=state.data;if(d.fx_error)return `${d.fx_error}. Суммы без доступной конвертации показаны в исходной валюте.`;if(!d.fx&&state.displayCurrency!=='USD')return `Конвертация в ${state.displayCurrency} временно недоступна. Суммы показаны в исходной валюте.`;return '';}
function heroCapital(all,portfolio){const own=all?portfolio.own:portfolio.tag;if(own!=null&&!(all&&portfolio.partial))return {value:money(own,state.displayCurrency),partial:false,breakdown:[]};const parts=fxBreakdown(all);if(parts.length===1)return {value:money(parts[0][1],parts[0][0]),partial:false,breakdown:[]};return {value:'Частично рассчитан',partial:true,breakdown:parts};}
function bankTotal(){let sum=0,partial=false;for(const a of state.banks?.accounts||[]){if(!a.counted)continue;const v=displayAmount(a.balance,a.currency);if(v==null)partial=true;else sum+=v;}return {sum,partial};}
function portfolioTotals(){const tag=tagBalance(),projects=activeProjects(),banks=bankTotal();let own=displayAmount(tag,'USD'),bonus=0,partial=own==null||banks.partial;if(own!=null)own+=banks.sum;for(const p of projects){const personal=displayAmount(p.current_total??p.total,p.currency),activeBonus=displayAmount(p.bonus_total||0,p.currency);if(personal==null||activeBonus==null)partial=true;else{own+=personal;bonus+=activeBonus;}}return {tag:displayAmount(tag,'USD'),banks:banks.sum,own,working:own==null?null:own+bonus,bonus,partial};}
// TagMarket — проект раздела «Финансы»: аккаунты (кабинеты брокера) и их счета MT5,
// баланс, динамика и график цены. Подключить счёт можно отсюда же, но никто не обязан
function tagAccountGroups(){const items=state.data.accounts,groups=[...new Set(items.map(a=>a.cabinet||'Без кабинета'))];
 return groups.map(c=>{const list=items.filter(a=>(a.cabinet||'Без кабинета')===c),sum=list.reduce((acc,a)=>acc+(a.totals&&displayAmount(a.totals.now,a.totals.cur)||0),0);return `<section class="account-group tag-account" data-ui-key="tag-account-${esc(c)}"><div class="account-group-head"><div class="group-title"><span class="eyebrow">АККАУНТ</span><h2>${esc(list[0]?.holder||c)}</h2><span class="cab-id">${esc(c)} · ${countLabel(list.length,['счёт','счёта','счетов'])}</span></div><b class="tag-account-sum">${money(sum,state.displayCurrency)}</b></div><div class="account-list">${list.map((a,i)=>accountCard(a,i,false)).join('')}</div></section>`;}).join('');}
function tagmarketView(){const d=state.data, curr='USD', t=d.totals[curr]||{capital:0,pnl:0,month:0,today:0}, own=d.accounts, rep=state.report;
 const back='<a href="#projects" class="button secondary small back">← Финансы</a>';
 const addRow=`<div class="tag-add">${button('add','Добавить счёт','secondary small','plus')}${button('onboard-open','Как подключить','ghost small')}</div>`;
 if(!own.length)return `<div class="project-space">${back}${header('TagMarket','Счета MT5 у брокера Tag Markets')}<section class="panel tag-empty"><span class="tag-empty-icon">${icon('chart')}</span><div><b>Счетов пока нет</b><p>Если у вас есть счёт в Tag Markets, добавьте его — здесь появятся баланс, сделки и результат по дням. Это необязательно: остальные разделы работают и без него.</p></div>${addRow}</section></div>`;
 const dynamics=state.reportError?empty('Не удалось построить график',state.reportError):rep?`<div class="dynamics-main fade-swap">${resultPair(rep.summary.net_income,rep.currency,rep.summary.pct_capital)}<span class="muted">${countLabel(rep.summary.count,['сделка','сделки','сделок'])}</span></div>${dayFeed(rep,t.capital)}`:skeleton('chart');
 const portfolio=portfolioTotals(),hero=heroCapital(false,portfolio),warning=fxWarning();
 return `<div class="project-space">${back}</div>`+secHero('fin','TagMarket',esc(countLabel(own.length,['счёт','счёта','счетов']))+' · стратегии у брокера')+
  `<div class="dashboard-grid"><div><section class="panel hero tag-hero"><span class="tag-hero-glow" aria-hidden="true"><i></i><i></i></span><div class="hero-top"><span class="eyebrow">Баланс</span></div><div class="hero-value ${hero.partial?'hero-partial':''}">${hero.value}</div>${hero.breakdown.length?`<div class="fx-breakdown">${hero.breakdown.map(([c,v])=>`<span>${esc(c)} · ${number(v)}</span>`).join('')}</div>`:''}${!hero.partial?`<div class="hero-bottom"><div><p>За месяц</p>${resultPair(t.month,curr,t.capital>0?t.month/t.capital*100:null)}</div><div class="separator"></div><div><p>Сегодня</p>${resultPair(t.today,curr,t.capital>0?t.today/t.capital*100:null)}</div></div>`:''}${d.fx?fxNote(d.fx):''}${warning?`<small class="stat-note warn-text fx-warning">${esc(warning)}</small>`:''}</section>
  ${tagAccountGroups()}${addRow}
  <section class="panel chart-panel dynamics"><div class="panel-head"><h2>Динамика доходности</h2>${periodTabs(['today','yesterday','week','month','all'])}</div>${dynamics}</section>
  ${priceChart(state.priceChart)}</div>
 <aside class="side-stack">${sonicStrategyCard()}</aside></div>`;
}
function balanceCard(personal){const totals=state.data.totals||{},list=Object.keys(totals);if(!list.length)return '';return `<section class="panel balance-card">${list.map(c=>{const x=totals[c];return `<div class="balance-row"><div><span class="eyebrow">ОБЩИЙ БАЛАНС · ${esc(c)}</span><strong>${money(x.balance??x.capital,c)}</strong><small>${countLabel(personal.length,['счёт','счёта','счетов'])}</small></div><div class="balance-side"><div><small>Сегодня</small>${resultPair(x.today,c,x.capital>0?x.today/x.capital*100:null)}</div><div><small>За месяц</small>${resultPair(x.month,c,x.capital>0?x.month/x.capital*100:null)}</div></div></div>`;}).join('')}</section>`;}
function accountsView(){const items=state.data.accounts,personal=items,groups=[...new Set(personal.map(a=>a.cabinet||'Без кабинета'))];
 const group=c=>{const list=personal.filter(a=>(a.cabinet||'Без кабинета')===c);return `<section class="account-group"><div class="account-group-head"><div class="group-title"><h2>${esc(list[0]?.holder||c)}</h2><span class="cab-id">${esc(c)} · ${countLabel(list.length,['счёт','счёта','счетов'])}</span></div></div><div class="account-list">${list.map((a,i)=>accountCard(a,i,false)).join('')}</div></section>`;};
 return header('Счета','',button('add','Добавить счёт','primary','plus'))+(personal.length?balanceCard(personal):'')+groups.map(group).join('')
  +(!personal.length?empty('Ваш первый шаг','Подключите счёт MT5 — здесь появятся баланс, сделки и результат по дням.',button('add','Подключить','primary','plus')):'');}
function pager(rep){return `<div class="inline-actions mt">${state.offset?button('prev','Назад','secondary small','back'):''}${rep.has_more?button('next','Ещё 50','secondary small','arrow'):''}</div>`;}
function groupByDay(rep){const days=new Map();for(const deal of rep.deals){const key=String(deal.time).slice(0,10);if(!days.has(key))days.set(key,[]);days.get(key).push(deal);}return days;}
function tradesTable(rep){
 if(!rep?.deals?.length)return rep?.archived?empty('Детали сохранены итогами','Для старых месяцев доступны суммы в истории по месяцам.'):empty('За этот период операций нет','');
 return `<div class="deal-days">${[...groupByDay(rep)].map(([day,rows])=>{const total=rep.day_totals?.[day];return `<section class="deal-day"><div class="deal-day-head"><div><span class="eyebrow">${countLabel(total?.count??rows.length,['операция','операции','операций'])}</span><h3>${esc(dayLabel(day))}</h3></div>${resultPair(total?.net,rep.currency,total?.pct_capital)}</div><div class="deal-day-list">${rows.map(r=>`<article class="deal-row"><div class="deal-symbol"><span class="deal-icon ${r.net_income<0?'loss':''}">${icon(r.net_income<0?'down':'up')}</span><div><b>${esc(r.symbol)}</b><small>${esc(r.side)} · ${number(r.volume)} лот · ${esc(timeMsk(r.time))}</small></div></div><div class="deal-result">${resultPair(r.net_income,rep.currency,r.pct_capital)}</div></article>`).join('')}</div></section>`;}).join('')}</div>${pager(rep)}`;
}
const MOVE={deposit:['Пополнение стратегии','up','in'],reinvest:['Реинвест профита в капитал','refresh','re'],profit_out:['Вывод профита на баланс Tag Markets','down','out'],profit_in:['Профит вернулся на стратегию','up','in'],capital_out:['Вывод капитала на баланс Tag Markets','down','out']};
function moveRow(r,cur){const [label,ico,dir]=MOVE[r.move]||['Движение средств','chart','in'];return `<article class="deal-row move-row ${dir}"><div class="deal-symbol"><span class="deal-icon move-${dir}">${icon(ico)}</span><div><b>${label}</b><small>${esc(timeMsk(r.time))}</small>${r.capital_now!=null?`<small class="flow">Капитал ${number(r.capital_was)} → <b>${money(r.capital_now,cur)}</b></small>`:''}</div></div><div class="deal-result"><span class="result-pair ${signedClass(r.net_income)}"><b>${money(r.net_income,cur,true)}</b></span></div></article>`;}
// Окно графика — какие свечи видны. Живёт вне перерисовки экрана: фоновое
// обновление не сбрасывает масштаб, новая свеча не сбивает позицию, если
// смотрят на самый конец. Новый период или счёт — окно по умолчанию
const chartView={key:'',start:0,count:0,total:0},CHART_MIN=16,CHART_DEFAULT=120;
function chartWindow(total,key){
 const v=chartView;
 if(v.key!==key){v.key=key;v.count=Math.min(total,CHART_DEFAULT);v.start=total-v.count;}
 else if(v.start+v.count>=v.total)v.start+=total-v.total;      // были в конце — едем с новыми свечами
 v.total=total;
 v.count=Math.round(Math.max(Math.min(CHART_MIN,total),Math.min(total,v.count)));
 v.start=Math.round(Math.max(0,Math.min(total-v.count,v.start)));
 return v;
}
function priceChart(data){
 const all=data?.candles||[];
 if(all.length<2)return `<section class="panel price-chart-panel"><div class="panel-head"><div><span class="eyebrow">ЦЕНА · ${esc(data?.symbol||'XAUUSD')}</span><h2>График цены</h2></div></div>${empty('Пока нет данных','График появится, как только агент передаст котировки за этот период.')}</section>`;
 const part=priceChartParts(data);
 return `<section class="panel price-chart-panel"><div class="panel-head"><div><span class="eyebrow">ЦЕНА · ${esc(data.symbol)}</span><h2>${esc(data.title||'График цены')}</h2></div><div class="chart-tools" role="group" aria-label="Масштаб графика"><button type="button" class="icon-btn" data-action="chart-zoom" data-value="out" aria-label="Отдалить">−</button><button type="button" class="icon-btn" data-action="chart-zoom" data-value="in" aria-label="Приблизить">+</button><button type="button" class="icon-btn" data-action="chart-zoom" data-value="reset" aria-label="Весь период" title="Весь период">⟲</button></div></div><div class="chart-wrap price-chart-wrap">${part.plot}</div><div class="time-axis">${part.ticks}</div></section>`;
}
function priceChartParts(data){
 const all=data.candles,key=[state.view,state.login,state.period,state.from,state.to,all[0].time].join('|');
 const {start,count}=chartWindow(all.length,key),rows=all.slice(start,start+count);
 const n=rows.length,w=640,h=220,pad=8,step=w/n;
 const t0=Date.parse(rows[0].time),t1=Date.parse(rows.at(-1).time),span=Math.max(1,t1-t0);
 const lo0=Math.min(...rows.map(r=>Number(r.low))),hi0=Math.max(...rows.map(r=>Number(r.high))),margin=(hi0-lo0)*.1||1;
 const lo=lo0-margin,hi=hi0+margin,range=hi-lo;
 const x=i=>i*step+step/2,y=v=>pad+(hi-v)/range*(h-pad*2);
 const pct=(v,of)=>(v/of*100).toFixed(2)+'%';
 // свечи: зелёная — рост, красная — падение; тело с мягким градиентом, закруглённое, тень тонкая
 const up='#2fcf8a',down='#f0586a';
 const defs=`<defs><linearGradient id="cd-up" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${up}"/><stop offset="1" stop-color="#1e9a66"/></linearGradient><linearGradient id="cd-down" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff7384"/><stop offset="1" stop-color="#c8394c"/></linearGradient></defs>`;
 const candles=rows.map((r,i)=>{const o=Number(r.open),c=Number(r.close),rise=c>=o,color=rise?up:down,bodyTop=y(Math.max(o,c)),bodyBot=y(Math.min(o,c)),bw=Math.max(1.2,step*.62);return `<line x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${y(Number(r.high)).toFixed(1)}" y2="${y(Number(r.low)).toFixed(1)}" stroke="${color}" stroke-width="1.3" stroke-linecap="round" vector-effect="non-scaling-stroke"/><rect x="${(x(i)-bw/2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1.4,bodyBot-bodyTop).toFixed(1)}" rx="${Math.min(2,bw/3).toFixed(1)}" fill="url(#cd-${rise?'up':'down'})"/>`;}).join('');
 // шкала цен справа и текущая цена, как в терминале
 const last=Number(rows.at(-1).close),grid=[.15,.38,.62,.85].map(f=>hi-range*f);
 const under=grid.map(v=>`<line class="price-grid" x1="0" x2="${w}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>`).join('')
  +`<line class="price-now-line" x1="0" x2="${w}" y1="${y(last).toFixed(1)}" y2="${y(last).toFixed(1)}"/>`;
 const axis=grid.map(v=>`<span class="price-level" style="top:${pct(y(v),h)}">${number(v)}</span>`).join('')
  +`<span class="price-now" style="top:${pct(y(last),h)}">${number(last)}</span>`;
 // Ось времени снизу. Время в данных уже МСК, поэтому формат — в UTC
 const long=span>36*3600e3,hm={hour:'2-digit',minute:'2-digit',timeZone:'UTC'};
 const fmt=new Intl.DateTimeFormat('ru-RU',long?{day:'numeric',month:'short',timeZone:'UTC'}:hm);
 const ticks=[0,.25,.5,.75,1].map(f=>{const i=Math.round(f*(n-1));return `<span style="left:${pct(x(i),w)}">${fmtDate(fmt,new Date(rows[i].time))}</span>`;}).join('');
 const plot=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Свечной график ${esc(data.symbol)}">${defs}${under}${candles}</svg><div class="price-axis">${axis}</div>`;
 return {plot,ticks};
}
// Подписи сделок, налезающие на уже показанные или на край, прячем: их
// размеры известны только после отрисовки. При приближении места больше —
// подписи возвращаются; время и цены всегда есть в списке под графиком
// Перерисовка только графика — при листании и масштабе. Контейнер
// .price-chart-wrap не пересоздаётся: на нём держится захват пальца
function redrawChart(){
 const panel=document.querySelector('.price-chart-panel');
 if(!panel||!panel.querySelector('.price-chart-wrap')||!(state.priceChart?.candles?.length>1))return;
 const part=priceChartParts(state.priceChart);
 panel.querySelector('.price-chart-wrap').innerHTML=part.plot;
 panel.querySelector('.time-axis').innerHTML=part.ticks;
 }
let chartFrame=0;
function scheduleChart(){if(!chartFrame)chartFrame=requestAnimationFrame(()=>{chartFrame=0;redrawChart();});}
// масштаб вокруг точки: anchor — доля ширины графика под пальцем или курсором
function chartZoom(factor,anchor=.5){
 const v=chartView,center=v.start+anchor*v.count;
 v.count=Math.max(Math.min(CHART_MIN,v.total),Math.min(v.total,v.count*factor));
 v.start=center-anchor*v.count;
 scheduleChart();
}
// Жесты: один палец или мышь — листать, два пальца — масштаб вокруг точки
// между ними, колесо — масштаб вокруг курсора. Вертикальную прокрутку
// страницы не трогаем (touch-action: pan-y в стилях)
(function chartGestures(){
 const fingers=new Map();let base=null;
 const plotOf=wrap=>{const r=wrap.getBoundingClientRect();return {left:r.left,width:Math.max(1,r.width-52)};};
 const snapshot=wrap=>{const pts=[...fingers.values()],p=plotOf(wrap);base={start:chartView.start,count:chartView.count,x:pts.reduce((a,b)=>a+b,0)/pts.length,dist:pts.length>1?Math.abs(pts[0]-pts[1]):0,...p};};
 document.addEventListener('pointerdown',e=>{
  const wrap=e.target.closest?.('.price-chart-wrap');if(!wrap||e.button>0)return;
  fingers.set(e.pointerId,e.clientX);try{wrap.setPointerCapture(e.pointerId);}catch{}
  snapshot(wrap);wrap.classList.add('is-dragging');
 });
 document.addEventListener('pointermove',e=>{
  if(!fingers.has(e.pointerId)||!base)return;
  fingers.set(e.pointerId,e.clientX);
  const pts=[...fingers.values()],mid=pts.reduce((a,b)=>a+b,0)/pts.length,v=chartView;
  if(pts.length>1&&base.dist>0){
   const count=Math.max(Math.min(CHART_MIN,v.total),Math.min(v.total,base.count*base.dist/Math.max(1,Math.abs(pts[0]-pts[1]))));
   const f=(base.x-base.left)/base.width;
   v.count=count;v.start=base.start+f*base.count-f*count-(mid-base.x)/base.width*count;
  }else v.start=base.start-(mid-base.x)/base.width*base.count;
  scheduleChart();
 });
 const lift=e=>{
  if(!fingers.delete(e.pointerId))return;
  const wrap=document.querySelector('.price-chart-wrap');
  if(fingers.size&&wrap)snapshot(wrap);else{base=null;wrap?.classList.remove('is-dragging');}
 };
 document.addEventListener('pointerup',lift);document.addEventListener('pointercancel',lift);
 document.addEventListener('wheel',e=>{
  const wrap=e.target.closest?.('.price-chart-wrap');if(!wrap)return;
  e.preventDefault();const p=plotOf(wrap);
  chartZoom(e.deltaY>0?1.15:1/1.15,Math.max(0,Math.min(1,(e.clientX-p.left)/p.width)));
 },{passive:false});
})();

async function fetchForecastStart(){const from=state.forecast.from;if(!from||from<=projectToday())return {fromResult:null,fromTag:null};const [fromResult,fromTag]=await Promise.all([fetchForecast(undefined,from),fetchTagForecast(from)]);return {fromResult,fromTag};}
async function recalculateForecast(){document.querySelector('.forecast-result')?.classList.add('is-stale');const [result,tag,start]=await Promise.all([fetchForecast(),fetchTagForecast(),fetchForecastStart()]);Object.assign(state.forecast,start,{result,tag});render(true);}
document.addEventListener('click',async event=>{
 const el=event.target.closest('[data-action]');if(!el)return;
 if(el.dataset.action==='asset-mode'){const prevMode=state.assetMode;state.assetMode=el.dataset.value==='all'?'all':'tag';try{localStorage.setItem('tag-asset-mode',state.assetMode);}catch{}render(true);heroSwap(prevMode,state.assetMode);}
 if(el.dataset.action==='forecast-back')location.hash='projects';
 if(el.dataset.action==='forecast-horizon'){state.forecast.horizon=el.dataset.value;state.forecast.until='';try{await recalculateForecast();}catch(error){toast(error.message);}}
 if(el.dataset.action==='forecast-bonus'){state.forecast.bonus=el.dataset.value==='1';try{await recalculateForecast();}catch(error){toast(error.message);}}
});
document.addEventListener('change',async event=>{
 if(event.target.id==='display-currency'){
  const currency=event.target.value;if(!['USD','BYN','RUB'].includes(currency))return;
  state.displayCurrency=currency;try{localStorage.setItem('tag-display-currency',currency);}catch{}
  if(!preview)try{await api('/preferences/display-currency',{method:'PUT',body:JSON.stringify({currency})});}catch(error){toast(error.message);}
  render(true);await refresh(false);
 }
 if(event.target.id==='forecast-from'){
  const value=event.target.value,today=projectToday();state.forecast.from=value&&value>today?value:'';
  const base=forecastBase();if(state.forecast.horizon==='custom'&&state.forecast.until&&state.forecast.until<base)state.forecast.until=base;
  try{await recalculateForecast();}catch(error){toast(error.message);}
 }
 if(event.target.id==='forecast-date'){
  state.forecast.horizon='custom';state.forecast.until=event.target.value&&event.target.value<forecastBase()?forecastBase():event.target.value;
  try{await recalculateForecast();}catch(error){toast(error.message);}
 }
 if(event.target.matches('[name="forecast-project"]')){
  const selected=[...document.querySelectorAll('[name="forecast-project"]:checked')].map(input=>input.value),all=[...document.querySelectorAll('[name="forecast-project"]')];
  state.forecast.selected=selected.length===all.length?null:selected;
  try{await recalculateForecast();}catch(error){toast(error.message);}
 }
});
function stepChart(series){const v=series.map(p=>Number(p.capital)),n=v.length,min=Math.min(...v),max=Math.max(...v),range=max-min||1,x=i=>i/(n-1)*640,y=val=>128-(val-min)/range*100;let d=`M${x(0)},${y(v[0])}`;for(let i=1;i<n;i++)d+=` H${x(i)} V${y(v[i])}`;return `<div class="chart-wrap"><svg viewBox="0 0 640 150" preserveAspectRatio="none" role="img" aria-label="Изменение капитала стратегии"><path class="chart-area" d="${d} V150 H0Z"/><path class="chart-line" d="${d}"/>${v.map((val,i)=>`<circle cx="${x(i)}" cy="${y(val)}" r="3.5" fill="var(--accent)" stroke="var(--panel)" stroke-width="2"/>`).join('')}</svg></div><div class="chart-labels"><span>${date(series[0].time)}</span><span>${countLabel(n-1,['изменение','изменения','изменений'])}</span><span>${date(series.at(-1).time)}</span></div>`;}
function capitalPanel(rep){const s=rep.capital_series||[];if(s.length<2)return '';const first=Number(s[0].capital),last=Number(s.at(-1).capital);return `<section class="panel capital-panel"><div class="panel-head"><div><span class="eyebrow">БАЛАНС СТРАТЕГИИ</span><h2>${money(last,rep.currency)}</h2></div><span class="result-pair ${signedClass(last-first)}"><b>${money(last-first,rep.currency,true)}</b>${first>0?`<small>${percent((last-first)/first*100)}</small>`:''}</span></div>${stepChart(s)}</section>`;}
function siteMoves(rep){if(!rep.site_moves?.length)return '';return `<section class="panel site-moves"><div class="panel-head"><h2>На сайте Tag Markets</h2></div>${rep.site_moves.map(m=>`<article class="deal-row move-row in"><div class="deal-symbol"><span class="deal-icon move-in">${icon('up')}</span><div><b>Пополнение кабинета</b><small>${esc(date(m.time,true))} МСК</small></div></div><div class="deal-result"><span class="result-pair positive"><b>${money(m.amount,m.currency,true)}</b></span></div></article>`).join('')}</section>`;}
function movesView(rep){const cur=rep.currency,fee=rep.commission_count?`<section class="panel fee-card"><div><span class="eyebrow">КОМИССИЯ БРОКЕРА · 30%</span><b>${money(rep.commission_total,cur)}</b></div><small>${countLabel(rep.commission_count,['удержание','удержания','удержаний'])}</small></section>`:'';const list=rep.deals?.length?`<div class="deal-days">${[...groupByDay(rep)].map(([day,rows])=>`<section class="deal-day"><div class="deal-day-head"><div><h3>${esc(dayLabel(day))}</h3></div></div><div class="deal-day-list">${rows.map(r=>moveRow(r,cur)).join('')}</div></section>`).join('')}</div>${pager(rep)}`:empty('За этот период движений нет','');return fee+capitalPanel(rep)+siteMoves(rep)+`<div class="section-head"><h2>Движения средств</h2></div>`+list;}
function archive(rep){const max=Math.max(1,...rep.months.map(m=>Math.abs(m.net)));return `<section class="panel archive-panel"><div class="archive-head"><div><span class="eyebrow">ИСТОРИЯ</span><h2>Результат по месяцам</h2></div><span class="badge">${rep.months.length} мес.</span></div><div class="archive-bars">${rep.months.map(m=>`<div class="archive-item"><div class="archive-month"><b>${esc(new Intl.DateTimeFormat('ru-RU',{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(`${m.month}-01T12:00:00Z`)))}</b>${resultPair(m.net,rep.currency,m.pct_capital)}</div><div class="archive-track ${m.net<0?'is-negative':''}"><progress value="${Math.abs(m.net)}" max="${max}" aria-label="Результат ${esc(m.month)}"></progress></div></div>`).join('')}</div>${!rep.months.length?empty('История ещё не накоплена','Месячные итоги появятся после первой синхронизации.'):''}</section>`;}
function accountView(){
 const a=currentAccount();
 if(!a)return empty('Счёт не найден','Возможно, владелец отозвал доступ.');
 const t=a.totals,rep=state.report,cur=t?.cur||'USD';
 const pct=value=>t?.now>0?Number(value||0)/t.now*100:null;
 // владелец и номер счёта уже в подзаголовке — в реквизитах только то, чего там нет
 const meta=[['Кабинет',a.cabinet||'—'],['Сервер',a.server||'—']]
   .map(([k,v])=>`<span><small>${esc(k)}</small><b>${esc(v)}</b></span>`).join('');
 const tag='';
 const cell=(label,value,pctv,extra='')=>`<div class="detail-cell"><small>${esc(label)}</small>${resultPair(value,cur,pctv)}${extra}</div>`;
 const intro=`<div class="detail-top"><a href="#accounts" class="text-link back">${icon('back')} Все счета</a>${button('account-settings','Настроить','secondary small','settings',`data-login="${esc(a.login)}"`)}</div>`
  +`<section class="panel detail-hero"><div class="detail-hero-top"><div class="strategy-icon green">${icon('chart')}</div><div class="detail-hero-name"><h1>${esc(a.strategy||a.name)}</h1><span class="cab-id">${esc(a.holder||'—')} · ${esc(a.login)}</span>${sharedNote(a)}</div>${tag}</div>`
  +`<div class="detail-balance"><small>Баланс</small><strong>${t?money(t.now,cur):'—'}</strong></div>`
  +(t?`<div class="detail-cells">${cell('Сегодня',t.today_net,pct(t.today_net))}${cell('Этот месяц',t.month_net,pct(t.month_net))}${cell('Всё время',t.pnl,pct(t.pnl),`<em>ROI ${percent(t.roi)}</em>`)}</div>`:'')
  +`<div class="detail-identity">${meta}</div></section>`;
 const dynamics=`<section class="panel chart-panel detail-chart fade-swap"><div class="panel-head"><div><span class="eyebrow">ДИНАМИКА</span><h2>${esc(rep?.title||'')}</h2></div><span class="badge">${countLabel(rep?.summary.count,['сделка','сделки','сделок'])}</span></div><div class="chart-summary">${resultPair(rep?.summary.net_income,rep?.currency,rep?.summary.pct_capital)}</div>${rep?dayFeed(rep,t?.now):''}</section>`;
 // сделки, движения средств и месячные итоги живут здесь же: отдельного
 // раздела «Сделки» больше нет, счёт открывается со всей своей историей
 const switches=`<div class="deal-switches">${[['trades','Сделки'],['moves','Движения средств'],['archive','По месяцам']].map(([key,label])=>`<button type="button" class="${state.kind===key?'active':''}" data-action="kind" data-value="${key}">${label}</button>`).join('')}</div>`;
 // ленивая: rep здесь ещё может быть null (первая загрузка), а archive()
 // и tradesTable() читают его поля — считаем только в ветке, где он есть
 const history=()=>state.kind==='archive'?archive(rep)
  :state.kind==='moves'?movesView(rep)
  :(rep.archived?notice('Ранние сделки сохранены итогами по месяцам.'):'')+tradesTable(rep);
 const report=state.reportError?empty('Не удалось открыть историю',state.reportError)
  :rep?.pending?empty('Ожидаем первые данные','Как только терминал прочитает счёт, данные появятся здесь.')
  :rep?dynamics+switches+history()
  :state.period==='custom'&&!state.from?empty('Выберите даты','Укажите начало и конец периода, чтобы построить отчёт.')
  :`<section class="panel">${skeleton('chart')}</section>`;
 return intro+(a.status==='pending'?notice('Счёт подключён. Ожидаем первые данные из MT5.'):'')+periodBar()+report;
}
function linkCard(p){const partner=p.partner_url,share=p.link?`https://t.me/share/url?url=${encodeURIComponent(p.link)}&text=${encodeURIComponent('Приглашаю в Platformer — финансы, активности и планы в одном месте')}`:'';return `<section class="panel link-card"><span class="eyebrow">ВАША ССЫЛКА-ПРИГЛАШЕНИЕ</span><div class="link-step ${partner?'done':'todo'}"><span class="step-n">${partner?'✓':'1'}</span><div><b>Партнёрская ссылка</b><small>${partner?'Сохранена':'Найдите свою партнёрскую ссылку в IB Portal и вставьте её сюда.'}</small></div>${partner?button('partner-link','Изменить','secondary small'):''}</div>${partner?'':button('partner-link','Вставить ссылку','primary wide','link')}<div class="link-step ${p.link?'done':'todo'}"><span class="step-n">${p.link?'✓':'2'}</span><div><b>Ссылка для гостей</b><small>Одна и постоянная</small></div></div>${p.link?`<div class="invite-url">${esc(p.link)}</div><div class="link-actions">${button('copy','Скопировать','secondary','copy',`data-text="${esc(p.link)}"`)}<a class="button primary" href="${esc(share)}" target="_blank" rel="noopener">${icon('arrow')} Отправить</a>${button('renew-link','Обновить','secondary small','refresh')}</div>`:''}</section>`;}
function guestHue(name){let h=0;for(const c of String(name))h=(h*31+c.codePointAt(0))%360;return h;}
function guestCard(g,p){
 const have=new Set(g.accounts.filter(a=>a.shared).map(a=>String(a.login))),canShare=(p.shareable||[]).filter(a=>!have.has(String(a.login))),mine=g.accounts.filter(a=>a.shared).length,own=g.accounts.length-mine;
 const sub=[countLabel(g.accounts.length,['счёт','счёта','счетов']),mine?`${mine} ваш${mine===1?'':'их'}`:'',own?`${own} личн${own===1?'ый':'ых'}`:'',g.since?`с ${g.since}`:''].filter(Boolean).join(' · ');
 return `<details class="panel people-card guest-card" data-ui-key="guest-${esc(g.id)}" style="--hue:${guestHue(g.name)}"><summary class="person-head"><span class="avatar guest-avatar">${esc(g.name.slice(0,1).toUpperCase())}</span><span class="person-copy"><b>${esc(g.name)}</b><small class="guest-sub">${esc(sub)}</small></span>${icon('chevron')}</summary><div class="faq-body">${g.accounts.map(a=>`<div class="guest-account ${a.shared?'is-shared':''}"><span class="ga-ico">${icon(a.shared?'link':'chart')}</span><div><b>${esc(a.name)}</b><small>${a.shared?'Ваш счёт у гостя':'Личный · только просмотр'}</small></div>${a.shared?button('take','Забрать','secondary small','',`data-guest="${esc(g.id)}" data-login="${esc(a.login)}"`):''}</div>`).join('')||'<p class="guest-empty">Счетов пока нет — откройте гостю один из своих.</p>'}<div class="actions guest-actions">${canShare.length?button('share-accounts','Открыть счета','secondary small','plus',`data-guest="${esc(g.id)}"`):''}${button('guest-detail','Подробнее','secondary small','',`data-guest="${esc(g.id)}"`)}${button('revoke-guest','Убрать доступ','danger small','',`data-guest="${esc(g.id)}"`)}</div></div></details>`;
}

function peopleView(){const p=state.people;if(!p)return secHero('people','Друзья')+skeleton('list',2);return secHero('people','Друзья',p.guests.length?`${esc(countLabel(p.guests.length,['человек','человека','человек']))} уже с вами`:'Пригласите по ссылке — у каждого свой Platformer')+friendsSection()+linkCard(p)+`<div class="section-head"><h2>Приглашены <span class="muted">${p.guests.length}</span></h2></div>${p.guests.length?`<div class="cards-grid">${p.guests.map(g=>guestCard(g,p)).join('')}</div>`:empty('Гостей пока нет','')}`;}
function toggle(label,note,action,on,attrs=''){return `<div class="settings-row"><div><p>${esc(label)}</p>${note?`<small>${esc(note)}</small>`:''}</div><button class="switch" role="switch" aria-label="${esc(label)}" aria-checked="${!!on}" data-action="${action}" ${attrs}></button></div>`;}
const MACHINE_STATE={polling:['Опрашивает','ok'],waiting:['Готова','ok'],legacy:['Старый код','warning'],offline:['Офлайн','muted']};
function nextCheck(sec){if(sec==null)return '';const at=new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'}).format(new Date(Date.now()+sec*1000));const wait=sec<60?'меньше минуты':`${Math.ceil(sec/60)} мин`;return ` Следующая проверка через ${wait}, в ${at} МСК.`;}
function machineRow(m){const [label,cls]=MACHINE_STATE[m.state]||MACHINE_STATE.offline;return `<div class="machine-row state-${esc(m.state)}"><div class="machine-top"><b>${esc(m.host)}</b><span class="badge ${cls}">${label}</span></div><small>${m.role==='primary'?'Основная':m.role==='standby'?'Резервная':'Роль не определена'} · ${esc(agoText(m.idle))}${m.commit?` · <code>${esc(m.commit)}</code>`:''}</small>${m.blocked?`<p class="machine-warn">Обновление заблокировано: ${esc(m.blocked)}.${nextCheck(m.next_check)}</p>`:''}</div>`;}
function serviceSummary(machines){return machines.some(m=>m.state==='polling')?'':'<div class="service-status bad"><b>Терминал никто не опрашивает</b><span>Данные не обновляются</span></div>';}
function servicePanel(){const machines=state.admin?.machines||[];return `<section class="panel service-panel"><div class="service-head"><div><span class="eyebrow">ДЛЯ ВЛАДЕЛЬЦА</span><h2>Сервис</h2></div>${button('refresh','Обновить','secondary small','refresh')}</div>${state.admin?`${serviceSummary(machines)}<div class="machine-list">${machines.map(machineRow).join('')||'<p class="muted">Машины не отвечали.</p>'}</div>`:'<p class="muted mt">Загружаем состояние…</p>'}${toggle('Уведомления о сервисе','','alerts',state.data.update_alerts)}<div class="settings-row"><div><p>Сообщение пользователям</p></div>${button('broadcast','Написать','secondary small')}</div></section>`;}
// Значок гаммы — мини-превью интерфейса в её цветах: карточка с графиком
// доходности в акценте, заливка под линией, плашка второго цвета, свечение.
// Две точки на тёмном прямоугольнике не говорили, как будет выглядеть приложение
function schemeSwatch(id,[bg,accent,second]){
 const g=`sw-${id}`;
 return `<svg class="swatch" viewBox="0 0 100 60" aria-hidden="true"><defs><radialGradient id="${g}-glow" cx="85%" cy="10%" r="70%"><stop offset="0" stop-color="${accent}" stop-opacity=".35"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></radialGradient><linearGradient id="${g}-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${accent}" stop-opacity=".38"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></linearGradient></defs><rect width="100" height="60" rx="9" fill="${bg}"/><rect width="100" height="60" rx="9" fill="url(#${g}-glow)"/><rect x="8" y="8" width="84" height="44" rx="7" fill="#1a1e21" stroke="#ffffff14"/><rect x="14" y="14" width="20" height="5" rx="2.5" fill="${second}"/><rect x="14" y="22" width="32" height="3" rx="1.5" fill="#ffffff2e"/><path d="M14 45 L25 39 L36 42 L48 31 L60 34 L72 23 L86 26 L86 48 L14 48Z" fill="url(#${g}-fill)"/><path d="M14 45 L25 39 L36 42 L48 31 L60 34 L72 23 L86 26" fill="none" stroke="${accent}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="86" cy="26" r="3" fill="${accent}" stroke="#1a1e21" stroke-width="1.5"/><rect x="66" y="13" width="20" height="7" rx="3.5" fill="${accent}"/></svg>`;
}
function schemePicker(){const cur=currentScheme();return `<div class="scheme-picker" role="radiogroup" aria-label="Цветовая гамма">${SCHEMES.map(([id,name,,sw])=>`<button type="button" role="radio" aria-checked="${cur===id}" class="scheme ${cur===id?'active':''}" data-action="scheme" data-value="${id}" style="--sw:${sw[1]}">${schemeSwatch(id,sw)}<b>${name}</b><span class="scheme-check" aria-hidden="true">${icon('check')}</span></button>`).join('')}</div>`;}
function settingsView(){const personal=state.data.accounts;return secHero('set','Настройки','Тема и счета')+`<div class="two-column"><section class="panel"><span class="eyebrow">ЦВЕТОВАЯ ГАММА</span>${schemePicker()}<button class="shortcut-card" type="button" data-action="shortcut"><span class="shortcut-tile">${icon('overview')}</span><span class="shortcut-copy"><b>Ярлык на экран</b><small>Открывать Platformer в один тап</small></span><span class="pill">Добавить</span></button></section><section class="panel"><div class="panel-head"><h2>Мои счета</h2><span class="badge">${personal.length}</span></div>${personal.map(a=>`<button type="button" class="settings-row settings-account-row compact-row" data-ui-key="account-${esc(a.login)}" data-action="account-settings" data-login="${esc(a.login)}"><span class="settings-account-info"><b>${esc(a.strategy||a.name)}</b><small>${esc(a.cabinet||'Без кабинета')}${a.holder?` · ${esc(a.holder)}`:''}</small></span><span class="settings-balance">${a.totals?money(a.totals.now,a.totals.cur):'—'}</span>${icon('chevron')}</button>`).join('')||'<p class="muted mt">Счетов пока нет.</p>'}</section></div>${state.data.founder?servicePanel():`<section class="panel leave-card"><div><b>Доступ</b><small>Счета и данные будут удалены</small></div><button type="button" class="leave-btn" data-action="leave">${icon('exit')}<span>Отключить мой доступ</span></button></section>`}`;}
// отпечаток всего, из чего строится экран; server_time меняется на каждом
// запросе и на вид не влияет — без него одинаковые данные дают одинаковый ключ
let paintedKey='';
function paintKey(){const {server_time,...data}=state.data||{};return JSON.stringify([state.view,state.login,state.projectId,state.projects,state.projectsError,state.tagStats,state.period,state.from,state.to,state.currency,state.displayCurrency,state.assetMode,state.forecast,state.kind,state.offset,data,state.report,state.reportError,state.priceChart,state.people,state.admin,state.banks,state.spend,state.spendSpan,state.income,state.goals,state.friends,state.activity,state.lists,state.events,state.circle,state.listsTab,state.calDay,state.calMonth,state.activityDays]);}
function captureUiState(){
 const nodes=[...document.querySelectorAll('#main [data-ui-key]')];
 const anchor=nodes.filter(el=>{const r=el.getBoundingClientRect();return r.bottom>90&&r.top<innerHeight;}).sort((a,b)=>Math.abs(a.getBoundingClientRect().top-100)-Math.abs(b.getBoundingClientRect().top-100))[0];
 const focus=document.activeElement,root=focus?.closest('[data-ui-key]');
 return {route:location.hash,key:viewKey(),y:scrollY,x:scrollX,anchor:anchor?.dataset.uiKey,offset:anchor?.getBoundingClientRect().top,
  details:[...document.querySelectorAll('#main details[data-ui-key]')].map(el=>[el.dataset.uiKey,el.open&&!el.classList.contains('is-closing')]),
  strips:[...document.querySelectorAll('#main .segmented')].map(el=>[[...el.querySelectorAll('button')].map(b=>b.dataset.value).join('|'),el.scrollLeft]),
  focus:root?{key:root.dataset.uiKey,summary:focus.tagName==='SUMMARY'}:null};
}
function restoreUiState(s){
 if(!s||s.route!==location.hash||s.key!==viewKey())return;
 const find=key=>document.querySelector(`#main [data-ui-key="${CSS.escape(key)}"]`);
 for(const [key,open] of s.details){const el=find(key);if(el)el.open=open;}
 for(const [key,left] of s.strips){const el=[...document.querySelectorAll('#main .segmented')].find(el=>[...el.querySelectorAll('button')].map(b=>b.dataset.value).join('|')===key);if(el)el.scrollLeft=left;}
 if(s.focus){let el=find(s.focus.key);if(s.focus.summary)el=el?.querySelector('summary');el?.focus({preventScroll:true});}
 const anchor=s.anchor&&find(s.anchor);window.scrollTo(s.x,anchor?scrollY+anchor.getBoundingClientRect().top-s.offset:s.y);
}
// Переключатель «TagMarket / Все активы» перерисовывает главную целиком, поэтому
// после перерисовки плавно проявляем содержимое карточки со сдвигом в сторону переключения.
function heroSwap(from,to){if(from===to||matchMedia('(prefers-reduced-motion:reduce)').matches)return;const dx=to==='all'?14:-14;document.querySelectorAll('.hero .eyebrow,.hero .hero-value,.hero .fx-breakdown,.hero .hero-bottom>div,.hero .fx-note,.hero .stat-note').forEach((el,i)=>el.animate([{opacity:0,transform:`translateX(${dx}px)`},{opacity:1,transform:'none'}],{duration:380,delay:i*35,easing:'cubic-bezier(.16,1,.3,1)',fill:'backwards'}));}
// Плавающая «+» живёт вне #main: у #main при смене экрана transform-анимация, а fixed внутри
// трансформированного предка уезжал бы вместе с ним. Несколько действий — меню по нажатию.
const FABS={plans:()=>{const [a,l]=PLAN_ADD[state.listsTab]||PLAN_ADD.tasks;return [[a,l,'plus']];},
 projects:()=>[['bank-add','Счёт или карта','bank'],['goal-add','Цель накоплений','target'],...(incomeFull()?[]:[['income-add','Зарплата на карту','plus']]),['spend-add','Трата или подписка','minus'],['project-create','Проект','projects']],
 spend:()=>[['spend-add','Новая трата','plus']],
 income:()=>incomeFull()?[]:[['income-add','Зачисление','plus']]};
function paintFab(){
 const root=$('#fab-root');if(!root)return;
 const items=state.data?FABS[state.view]?.()||[]:[],key=items.map(i=>i[0]).join(',');
 if(root.dataset.key===key)return;
 root.dataset.key=key;root.classList.remove('open');
 root.innerHTML=!items.length?'':items.length===1?`<button type="button" class="fab" data-action="${items[0][0]}" aria-label="${esc(items[0][1])}">${icon('plus')}</button>`:`<div class="fab-menu"></div><button type="button" class="fab" data-action="fab-toggle" aria-expanded="false" aria-label="Добавить">${icon('plus')}</button>`;
}
function fabToggle(force){
 const root=$('#fab-root'),menu=root?.querySelector('.fab-menu');if(!menu)return;
 const open=force??!root.classList.contains('open');
 // пункты меню появляются только при открытии: скрытые кнопки не путаются с кнопками страницы
 menu.innerHTML=open?(FABS[state.view]?.()||[]).map(([a,l,ico],i)=>`<button type="button" class="fab-item" style="--i:${i}" data-action="${a}">${icon(ico)}<span>${esc(l)}</span></button>`).join(''):'';
 root.classList.toggle('open',open);root.querySelector('.fab').setAttribute('aria-expanded',String(open));
 if(open)tg?.HapticFeedback?.selectionChanged?.();
}
document.addEventListener('click',event=>{if(!$('#fab-root')?.classList.contains('open'))return;if(event.target.closest?.('.fab-item')||!event.target.closest?.('#fab-root'))setTimeout(()=>fabToggle(false));},true);
function render(preserve=false){const snapshot=preserve?captureUiState():null;$('#main').classList.toggle('quiet-paint',preserve);paintedKey='';nav();
 // FLIP: #main.innerHTML заменяется целиком на каждый render(), поэтому
 // .segmented-thumb каждый раз новый DOM-узел без истории — обычный CSS
 // transition не увидел бы «откуда» ехать. Снимаем позицию активной кнопки
 // ДО замены и сопоставляем со следующим кадром по «отпечатку» набора
 // кнопок (их data-value), а не по индексу: на разных экранах .segmented
 // могут отличаться количеством и порядком (периоды на Обзоре — не то же,
 // что периоды на Счёте), и по индексу thumb ехал бы с чужой позиции.
 const prevThumbs=new Map();
 document.querySelectorAll('.segmented').forEach(strip=>{
  const active=strip.querySelector('button.active');
  if(!active)return;
  const fingerprint=[...strip.querySelectorAll('button')].map(b=>b.dataset.value||b.textContent).join('|');
  prevThumbs.set(fingerprint, {left:active.offsetLeft, width:active.offsetWidth});
 });
 const views={overview,tagmarket:tagmarketView,activity:activityView,plans:listsView,circle:circleView,banks:banksView,accounts:accountsView,account:accountView,projects:projectsView,spend:spendView,income:incomeView,project:projectView,forecast:forecastView,people:peopleView,settings:settingsView,faq:faqView,onboarding:welcomeView};$('#main').innerHTML=(preview?'<div class="preview-label">Демо-режим · вымышленные данные. Отправка сообщений и управление счетами работают только при запуске из <a href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">бота в Telegram</a>.</div>':'')+(views[state.view]||overview)()+(state.view==='settings'&&state.admin?.network?.length?networkView():'');$('#avatar').textContent=state.data.user.name.slice(0,1).toUpperCase();
 // сначала все замеры, потом все записи: чередование чтения и записи в одном
 // цикле заставляет браузер пересчитывать вёрстку на каждой полосе
 const centering=[];
 document.querySelectorAll('.segmented').forEach(strip=>{const active=strip.querySelector('.active');if(active)centering.push([strip,active.getBoundingClientRect().left-strip.getBoundingClientRect().left-(strip.clientWidth-active.clientWidth)/2]);});
 for(const [strip,shift] of centering)strip.scrollLeft+=shift;
 positionThumbs(prevThumbs);
 paintFab();
 restoreUiState(snapshot);
 if(!preserve)animateCounts();
}
function positionThumbs(prevThumbs=new Map()){
 const toAnimate=[];
 document.querySelectorAll('.segmented').forEach(strip=>{
  const active=strip.querySelector('button.active');
  if(!active)return;
  let thumb=strip.querySelector('.segmented-thumb');
  if(!thumb){thumb=document.createElement('i');thumb.className='segmented-thumb';strip.prepend(thumb);}
  const fingerprint=[...strip.querySelectorAll('button')].map(b=>b.dataset.value||b.textContent).join('|');
  const prev=prevThumbs.get(fingerprint);
  const target={left:active.offsetLeft-3,width:active.offsetWidth};
  if(prev){
   thumb.style.transition='none';
   thumb.style.width=prev.width+'px';
   thumb.style.transform=`translateX(${prev.left-3}px)`;
   toAnimate.push([thumb,target]);
  }else{
   thumb.style.transition='none';
   thumb.style.width=target.width+'px';
   thumb.style.transform=`translateX(${target.left}px)`;
  }
 });
 if(toAnimate.length)requestAnimationFrame(()=>requestAnimationFrame(()=>{
  toAnimate.forEach(([thumb,target])=>{thumb.style.transition='';thumb.style.width=target.width+'px';thumb.style.transform=`translateX(${target.left}px)`;});
 }));
}
function previewData(d){
 const now=new Date(Date.now()+3*3600000),today=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate()));
 const source=new Date('2026-09-16T00:00:00Z'),delta=today-source;
 const shifted=day=>{const d=new Date(Date.parse(`${day}T00:00:00Z`)+delta);return validDate(d)?d.toISOString().slice(0,10):day;};
 const round=value=>Math.round(value*100)/100;
 const dealToday=round(d.report.deals.reduce((sum,row)=>sum+row.net_income,0));
 const originalLast=d.report.chart.at(-1).value;
 d.report.chart[0].value=round(d.report.chart[0].value-(dealToday-originalLast));
 d.report.chart.at(-1).value=dealToday;
 d.report.chart.forEach(point=>{point.day=shifted(point.day)});
 d.report.deals.forEach(row=>{row.time=shifted(row.time.slice(0,10))+row.time.slice(10)});
 d.report.day_totals={[shifted('2026-09-16')]:{count:d.report.deals.length,net:dealToday}};
 d.report.months.forEach(month=>{const [year,index]=month.month.split('-').map(Number);const next=new Date(Date.UTC(today.getUTCFullYear(),today.getUTCMonth()+(year-2026)*12+index-9,1));month.month=next.toISOString().slice(0,7)});
 let totalToday=0;
 for(const account of d.bootstrap.accounts){if(account.totals&&!account.totals.days)account.totals.days=Array.from({length:14},(_,i)=>Math.round((account.totals.month_net/14)*(1+Math.sin(i*1.3+Number(account.login)%7)*.9)*100)/100);if(!account.totals)continue;account.totals.today_net=round(dealToday*account.totals.month_net/d.report.summary.net_income);totalToday+=account.totals.today_net;}
 d.bootstrap.totals.USD.today=round(totalToday);
 d.bootstrap.totals.USD.trading_day=shifted('2026-09-16');
 d.bootstrap.totals.USD.trading_day_net=round(totalToday);
 d.bootstrap.totals.USD.trading_day_partial=false;
 const overviewLast=d.overview_report.chart.at(-1).value;
 d.overview_report.chart[0].value=round(d.overview_report.chart[0].value-(totalToday-overviewLast));
 d.overview_report.chart.at(-1).value=round(totalToday);
 d.overview_report.chart.forEach(point=>{point.day=shifted(point.day)});
 for(const p of d.projects||[])for(const a of p.accounts||[])if(a.bonus_expires_at)a.bonus_expires_at=shifted(a.bonus_expires_at.slice(0,10))+a.bonus_expires_at.slice(10);
 return d;
}
// Synthetic preview only. Real project projections are calculated by /api/projects/forecast.
function previewProjectForecast(p,until,includeBonus){
 const point=(at)=>{const start=Date.parse(`${projectToday()}T00:00:00Z`),end=Date.parse(`${at}T00:00:00Z`),span=Math.max(0,(end-start)/86400000),n=p.period==='day'&&p.business_days_only?Array.from({length:span},(_,i)=>new Date(start+(i+1)*86400000).getUTCDay()).filter(day=>day>0&&day<6).length:p.period==='day'?span:p.period==='week'?span/7:span/30;let personal=0,bonus=0,total=0,growth=0;const accounts=p.accounts.map(a=>{const rate=(a.rate_percent??p.rate_percent)/100,base=a.current_amount??a.amount,pcap=a.capitalization??p.capitalization,amount=base*(pcap?Math.pow(1+rate,n):1+rate*n),active=includeBonus&&a.bonus_active&&(!a.bonus_expires_at||a.bonus_expires_at.slice(0,10)>at),b0=active?(a.bonus_current_amount||a.bonus_amount||0):0,bcap=!!a.bonus_capitalization,bonusValue=active?b0*(bcap?Math.pow(1+rate,n):1+rate*n):0,working=amount+bonusValue,baseWorking=base+(includeBonus&&a.bonus_active?(a.bonus_current_amount||a.bonus_amount||0):0),item={account_id:a.id,name:a.name,current_personal:base,current_bonus:includeBonus&&a.bonus_active?(a.bonus_current_amount||a.bonus_amount||0):0,current_working:baseWorking,personal:amount,bonus:bonusValue,working,growth:working-baseWorking,personal_capitalization:!!pcap,bonus_capitalization:bcap,bonus_expires_at:a.bonus_expires_at,bonus_active:!!(includeBonus&&a.bonus_active)};personal+=amount;bonus+=bonusValue;total+=working;growth+=working-baseWorking;return item;});return {until:at,currency:p.currency,personal,bonus,total,growth,calculation_limited:false,accounts};};
 const addDays=n=>new Date(Date.parse(`${projectToday()}T00:00:00Z`)+n*86400000).toISOString().slice(0,10),today=projectToday(),month=(()=>{const d=new Date(`${today}T00:00:00Z`);d.setUTCMonth(d.getUTCMonth()+1);return d.toISOString().slice(0,10);})();
 const checkpoints={now:point(today),day:point(addDays(1)),week:point(addDays(7)),month:point(month),selected:point(until)},current=checkpoints.now,selected=checkpoints.selected;
 return {project_id:p.id,currency:p.currency,until,includes_bonus:includeBonus,current,checkpoints,accounts:selected.accounts,total:selected.total,income:selected.growth,calculation_limited:false};
}
function previewBounds(period,params){
 const now=new Date(Date.now()+3*3600000),day=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate()));
 const key=value=>value.toISOString().slice(0,10),move=(date,n)=>new Date(date.getTime()+n*86400000);
 const monday=move(day,-(day.getUTCDay()+6)%7),month=new Date(Date.UTC(day.getUTCFullYear(),day.getUTCMonth(),1));
 if(period==='today')return [key(day),key(day)];
 if(period==='yesterday')return [key(move(day,-1)),key(move(day,-1))];
 if(period==='week')return [key(monday),key(day)];
 if(period==='lastweek')return [key(move(monday,-7)),key(move(monday,-1))];
 if(period==='month')return [key(month),key(day)];
 if(period==='lastmonth')return [key(new Date(Date.UTC(day.getUTCFullYear(),day.getUTCMonth()-1,1))),key(move(month,-1))];
 if(period==='custom')return [params.get('from')||'9999-12-31',params.get('to')||'0000-01-01'];
 return ['0000-01-01','9999-12-31'];
}
function previewCandles(){
 // сетка 15 минут и детерминированный шум: с Date.now() и Math.random() демо-график
 // менялся на каждом фоновом обновлении и перерисовывал экран без причины
 const n=48,step=15*60000,now=Math.floor(Date.now()/step)*step,start=now-n*step;
 let price=2400,candles=[];
 for(let i=0;i<n;i++){const drift=Math.sin(i/9)*3,noise=(Math.sin(i*7)+Math.sin(i*2.3))*1.2;const open=price;price=2400+drift+noise+i*0.15;const close=price;const high=Math.max(open,close)+(1+Math.sin(i*12.9))*.75;const low=Math.min(open,close)-(1+Math.cos(i*7.7))*.75;candles.push({time:new Date(start+i*step).toISOString(),open,high,low,close});}
 const at=i=>candles[i].time,px=i=>candles[i].close;
 const pair=(a,b,side)=>({side,in_time:at(a),in_price:px(a),out_time:at(b),out_price:px(b),net:(side==='BUY'?1:-1)*(px(b)-px(a))*10,volume:.02});
 return {title:'Выбранный период',symbol:'XAUUSD',candles,
  trades:[{time:at(14),side:'buy',price:px(14),kind:'in',symbol:'XAUUSD'},{time:at(22),side:'buy',price:px(22),kind:'out',symbol:'XAUUSD'},
          {time:at(31),side:'sell',price:px(31),kind:'in',symbol:'XAUUSD'},{time:at(38),side:'sell',price:px(38),kind:'out',symbol:'XAUUSD'}],
  pairs:[pair(14,22,'BUY'),pair(31,38,'SELL'),pair(40,45,'BUY')]};
}
function previewReport(d,path,overview){
 const params=new URLSearchParams(path.split('?')[1]),period=params.get('period')||'today';
 const r=structuredClone(overview?d.overview_report:d.report);
 const account=overview?null:d.bootstrap.accounts.find(a=>String(a.login)===path.match(/accounts\/(\d+)/)?.[1]);
 const scale=account?.totals?account.totals.month_net/d.report.summary.net_income:1;
 const capital=overview?d.bootstrap.totals.USD.capital:account?.totals?.now||0;
 const monthNet=overview?d.overview_report.summary.net_income:account?.totals?.month_net||d.report.summary.net_income;
 const allNet=overview?d.bootstrap.totals.USD.pnl:account?.totals?.pnl||d.report.months.reduce((sum,item)=>sum+item.net,0);
 const archivedBase=d.report.months.slice(0,-1).reduce((sum,item)=>sum+item.net,0);
 r.months=d.report.months.map((item,index)=>{const net=index===d.report.months.length-1?monthNet:(allNet-monthNet)*item.net/archivedBase;return {month:item.month,count:item.count*(overview?2:1),net:Math.round(net*100)/100,pct_capital:capital>0?Math.round(net/capital*1000)/10:null}});
 if(!overview){
  r.chart.forEach(point=>{point.value=Math.round(point.value*scale*100)/100});
  r.deals.forEach(row=>{row.net_income=Math.round(row.net_income*scale*100)/100;row.pct_capital=capital>0?Math.round(row.net_income/capital*10000)/100:null;row.ticket+=Number(account?.login||10001)-10001;if(account?.login===10002)row.symbol='EURUSD'});
 }
 const sourceChart=[...r.chart];
 const insight=key=>{const [begin,end]=previewBounds(key,params);const net=key==='all'?allNet:Math.round(sourceChart.filter(point=>point.day>=begin&&point.day<=end).reduce((sum,point)=>sum+point.value,0)*100)/100;return {available:true,net,pct_capital:capital>0?Math.round(net/capital*1000)/10:null}};
 if(!overview)r.insights=Object.fromEntries(['week','lastweek','month','all'].map(key=>[key,insight(key)]));
 const [from,to]=previewBounds(period,params);
 r.chart=r.chart.filter(point=>point.day>=from&&point.day<=to);
 if(period==='lastmonth'&&!r.chart.length){const month=r.months?.find(item=>item.month===from.slice(0,7));if(month)r.chart=[{day:to,value:month.net}];}
 if(period==='all'&&r.months){const older=r.months.slice(0,-1).map(item=>({day:`${item.month}-28`,value:item.net}));r.chart=[...older,...r.chart];}
 if(!overview){
  r.deals=r.deals.filter(row=>row.time.slice(0,10)>=from&&row.time.slice(0,10)<=to);
  r.day_totals=r.deals.length?{[r.deals[0].time.slice(0,10)]:{count:r.deals.length,net:Math.round(r.deals.reduce((sum,row)=>sum+row.net_income,0)*100)/100}}:{};
  for(const item of Object.values(r.day_totals))item.pct_capital=capital>0?Math.round(item.net/capital*1000)/10:null;
  if(params.get('kind')==='moves'){const day=n=>new Date(Date.now()+3*3600000-n*864e5).toISOString().slice(0,10);r.deals=[{ticket:9,time:`${day(1)}T14:32:10Z`,is_balance:true,move:'reinvest',net_income:6.92,capital_was:1280.14,capital_now:1287.06},{ticket:8,time:`${day(3)}T09:05:41Z`,is_balance:true,move:'deposit',net_income:250,capital_was:1030.14,capital_now:1280.14},{ticket:7,time:`${day(6)}T18:20:00Z`,is_balance:true,move:'profit_out',net_income:-40.5}];r.day_totals={};r.commission_total=48.6;r.commission_count=3;r.capital_series=[{time:`${day(6)}T00:00:00Z`,capital:1030.14},{time:`${day(3)}T09:05:41Z`,capital:1280.14},{time:`${day(1)}T14:32:10Z`,capital:1287.06}];r.site_moves=[{kind:'deposit',amount:250,currency:'USD',time:`${day(3)}T09:04:12Z`}];}
  r.archived=period==='all'||(r.chart.length>0&&!r.deals.length);
 }
 const net=period==='all'?allNet:Math.round(r.chart.reduce((sum,point)=>sum+point.value,0)*100)/100;
 r.summary.net_income=net;
 r.summary.pct_capital=capital>0?Math.round(net/capital*1000)/10:null;
 r.summary.count=period==='today'?(overview?d.report.deals.length*2:r.deals.length):period==='lastmonth'?r.months.at(-2)?.count||0:period==='all'?r.months.reduce((sum,item)=>sum+item.count,0):Math.round((overview?d.overview_report.summary.count:d.report.summary.count)*r.chart.length/(overview?d.overview_report.chart.length:d.report.chart.length));
 r.title=Object.fromEntries(periods)[period]||'Выбранный период';
 const first=period==='all'?(r.chart[0]?.day||new Date(Date.now()+3*3600000).toISOString().slice(0,10)):from;
 const last=period==='all'?new Date(Date.now()+3*3600000).toISOString().slice(0,10):to;
 const days=new Map(r.chart.map(p=>[p.day,p.value]));let running=capital-r.chart.reduce((sum,p)=>sum+p.value,0);
 r.timeline=[];for(let stamp=Date.parse(first);stamp<=Date.parse(last)&&r.timeline.length<=10000;stamp+=864e5){const day=new Date(stamp).toISOString().slice(0,10),value=days.get(day)||0;running+=value;r.timeline.push({day,value,balance:Math.round(running*100)/100});}
 return r;
}
async function api(path,options={}){
 if(preview){
  if(path==='/notifications'){const at=m=>new Date(Date.now()-m*60000).toISOString();return {items:[{id:5,kind:'withdrawals',event_key:'trade:10001:124',title:'SONIC · Вывод профита',body:'−11,14 $\n➡️ Профит списан со стратегии на баланс Tag Markets\n💰 Капитал стратегии: 2 500,00 $ (не изменился)',created_at:at(2),read_at:null},{id:4,kind:'trades',event_key:'trade:10001:123',title:'SONIC · Сделка в плюс',body:'+18,42 $ чистыми +0,15%\n🔢 Третья сделка за день\nXAUUSD SELL · до комиссии +26,31\n💵 За день: +61,20 $ (3 сделки)',created_at:at(3),read_at:null},{id:3,kind:'deposits',event_key:'trade:10002:55',title:'NEO.FX · Пополнение стратегии',body:'+250,00 $\n⬅️ Заведено на стратегию — капитал вырос\n💰 Капитал: было 4 950,00 $ → стало 5 200,00 $',created_at:at(95),read_at:null},{id:2,kind:'message',title:'Сообщение от сервиса',body:'Завтра с 03:00 до 03:10 возможны короткие перерывы в обновлении данных.',created_at:at(60*30),read_at:at(60*20)},{id:1,kind:'registration',title:'Новый гость',body:'Виктория Орлова приняла приглашение',created_at:at(60*52),read_at:at(60*50)}],unread:3};}
  if(options.method&&options.method!=='GET')throw new Error('В предпросмотре изменения отключены');
  const d=previewData(await fetch('preview.json',{cache:'no-store'}).then(r=>r.json()));
  if(path==='/bootstrap')return {...d.bootstrap,fx:d.bootstrap.fx||{source:'MYFIN · НБРБ',provider:'myfin',stale:false,currency:'USD',byn_per_unit:{BYN:1,USD:3,RUB:0.03,EUR:3.4},byn_per_usd:3,byn_per_100_rub:3,updated_at:PREVIEW_STAMP},insights:previewInsights()};
  if(path==='/insights')return previewInsights();
  if(path==='/people')return d.people;
  if(path.startsWith('/tagmarket/forecast')){const until=new URLSearchParams(path.split('?')[1]||'').get('until'),start=new Date(`${projectToday()}T00:00:00Z`),count=(end)=>{let n=0;for(let t=start.getTime()+864e5;t<=Date.parse(`${end}T00:00:00Z`);t+=864e5)if(![0,6].includes(new Date(t).getUTCDay()))n++;return n;},add=n=>new Date(start.getTime()+n*864e5).toISOString().slice(0,10),month=(()=>{const m=new Date(start);m.setUTCMonth(m.getUTCMonth()+1);return m.toISOString().slice(0,10);})(),average=.0042,days={day:count(add(1)),week:count(add(7)),month:count(month),selected:count(until)};return {sufficient:true,days_used:23,min_days:5,window_days:30,average_daily_return:average,average_daily_profit:null,until,trading_days:days,multipliers:Object.fromEntries(Object.entries(days).map(([k,n])=>[k,(1+average)**n])),model:'compound_average_daily_return'};}
  if(path==='/banks')return previewBanks();
  if(path==='/projects')return {projects:d.projects||[]};
  if(path.startsWith('/projects/forecast')){const q=new URLSearchParams(path.split('?')[1]||''),ids=q.getAll('id'),until=q.get('until'),all=q.get('all')!=='0',include=q.get('bonus')!=='0';return {projects:(state.projects||d.projects||[]).filter(p=>all||ids.includes(p.id)).map(p=>previewProjectForecast(p,until,include))};}
  if(path.startsWith('/projects/'))return (d.projects||[]).find(p=>p.id===path.split('/')[2])||null;
  if(path==='/admin')return d.admin;
  if(path.startsWith('/guests/'))return {report:'Виктория Орлова\n\nСчета гостя\n• SONIC 2 · 2 840,00 $\n\nЗаработок без демо-счёта\nСегодня  +42,18 $\nНеделя   +186,40 $\nМесяц    +312,66 $\n\nДемо-счёт в расчёт не входит.'};
  if(path.startsWith('/cabinets/'))return {report:'Отчёт кабинета · CU-1\n\nЛичные стратегии: 2\nРезультат после комиссии: +684,32 $\nДемо-счёт исключён из итога.'};
  if(path.startsWith('/overview/report'))return previewReport(d,path,true);
  if(path.includes('/candles'))return previewCandles();
  if(path.includes('/report'))return previewReport(d,path,false);
  throw new Error('Этот раздел недоступен в предпросмотре');
 }
 const isForm=options.body instanceof FormData;
 const headers={'X-Telegram-Init-Data':tg?.initData||'',...options.headers};
 if(!isForm&&!headers['Content-Type'])headers['Content-Type']='application/json';
 const attempt=async()=>{
  const response=await fetch(new URL('../api'+path,location.href),{...options,signal:AbortSignal.timeout(path==='/broadcast'?180000:20000),headers,cache:'no-store'});
  const d=await response.json().catch(()=>({error:'Сервер вернул некорректный ответ'}));
  if(!response.ok){const error=new Error(d.error||`Ошибка ${response.status}`);error.status=response.status;throw error;}
  return d;
 };
 // чтение безопасно повторить: один повтор после короткой паузы закрывает
 // обрыв сети и перезапуск сервера, не показывая пользователю ошибку.
 // Изменения (POST/PUT/PATCH/DELETE) не повторяем — они могли дойти до сервера
 if(options.method&&options.method!=='GET')return attempt();
 try{return await attempt();}
 catch(error){
  const transient=error.status===undefined||[502,503,504].includes(error.status);
  if(!transient||document.hidden)throw error;
  await new Promise(resolve=>setTimeout(resolve,700));
  return attempt();
 }
}
async function loadReport(){const params=new URLSearchParams({period:state.period});if(state.period==='custom'){if(!state.from||!state.to)return null;params.set('from',state.from);params.set('to',state.to);}if(state.view==='tagmarket')return api(`/overview/report?${params}`);const acc=currentAccount();if(!acc)return null;state.login=acc.login;params.set('kind',state.kind);params.set('offset',state.offset);return api(`/accounts/${acc.login}/report?${params}`);}
// Данные самого раздела сверх общих /bootstrap: отчёт, график цены, гости,
// сервисная панель. Нужны и фоновому обновлению, и переходу между разделами
async function viewParts(){
 // независимые запросы идут одновременно: раньше отчёт, свечи, проекты и
 // прогноз TagMarket ждали друг друга по очереди, и раздел открывался на их сумму
 const out={},jobs=[];
 if(['tagmarket','account'].includes(state.view))jobs.push((async()=>{try{out.report=await loadReport();out.reportError='';}catch(error){out.report=null;out.reportError=error.message;}})());
 if(state.view==='tagmarket'){const sonic=state.data.accounts.find(a=>/sonic|sonik/i.test(`${a.strategy||''} ${a.name||''}`));jobs.push((async()=>{out.priceChart=sonic?await api(`/accounts/${sonic.login}/candles?period=${state.period==='custom'?'week':state.period}`).catch(()=>null):null;})());}
 if(state.view==='people')jobs.push((async()=>{out.people=await api('/people');})());
 if(['projects','spend','income'].includes(state.view))jobs.push((async()=>{try{out.spend=preview?{...previewSpend(),span:state.view==='spend'?state.spendSpan:'month'}:await api('/spend'+(state.view==='spend'&&state.spendSpan==='year'?'?span=year':''));out.spendError='';}catch(error){out.spend=state.spend;out.spendError=error.message;}})());
 if(state.view==='projects')jobs.push((async()=>{try{out.goals=preview?previewGoals():await api('/goals');}catch(error){out.goals=state.goals;}})());
 if(state.view==='people')jobs.push((async()=>{try{out.friends=preview?previewFriends():await api('/friends');out.friendsError='';}catch(error){out.friends=state.friends;out.friendsError=error.message;}})());
 if(['projects','income'].includes(state.view))jobs.push((async()=>{try{out.income=preview?previewIncome():await api('/income');out.incomeError='';}catch(error){out.income=state.income;out.incomeError=error.message;}})());
 if(['overview','projects','banks','income'].includes(state.view))jobs.push((async()=>{try{out.banks=preview?previewBanks():await api('/banks');out.banksError='';}catch(error){out.banks=state.banks;out.banksError=error.message;}})());
 if(['overview','activity'].includes(state.view))jobs.push((async()=>{try{out.activity=preview?previewActivity(state.activityDays):await api(`/activity?days=${state.view==='overview'?7:state.activityDays}`);out.activityError='';}catch(error){out.activity=state.activity;out.activityError=error.message;}})());
 if(['overview','plans'].includes(state.view))jobs.push((async()=>{try{const [from,to]=monthBounds(state.calMonth);const [lists,events]=await Promise.all([preview?previewLists():api('/lists'),state.view==='plans'?(preview?previewLists():api(`/events?from=${from}&to=${to}`)):Promise.resolve(state.events)]);out.lists=lists;out.events=events;out.listsError='';}catch(error){out.lists=state.lists;out.listsError=error.message;}})());
 if(state.view==='projects')jobs.push((async()=>{const tag=await fetchTagForecast();if(!tag.error)out.tagStats=tag;})());
 if(['projects','project','overview','forecast'].includes(state.view))jobs.push((async()=>{try{out.projects=(await api('/projects')).projects;out.projectsError='';if(state.view==='forecast'){const [result,tag]=await Promise.all([fetchForecast(out.projects),fetchTagForecast()]);out.forecast={...state.forecast,result,tag,...await fetchForecastStart()};}}catch(error){out.projects=state.projects;out.projectsError=error.message;}})());
 if(state.view==='settings'&&state.data.founder)jobs.push((async()=>{out.admin=await api('/admin');})());
 await Promise.all(jobs);
 return out;
}
// Переход в раздел, где уже были, показывает запомненное сразу — без запроса
// к серверу и второй перерисовки: раньше каждый переход заново тянул все
// данные и перерисовывал экран, и раздел заметно «обновлялся» на глазах.
// Свежесть держит фоновое обновление; старше его интервала — грузим заново
const viewCache=new Map();
function viewKey(){return [state.view,state.login,state.projectId,state.period,state.from,state.to,state.currency,state.kind,state.offset,state.view==='activity'?state.activityDays:'',state.view==='plans'?state.calMonth:'',state.view==='spend'?state.spendSpan:''].join('|');}
function remember(){viewCache.set(viewKey(),{report:state.report,reportError:state.reportError,priceChart:state.priceChart,projects:state.projects,projectsError:state.projectsError,banks:state.banks,spend:state.spend,income:state.income,goals:state.goals,friends:state.friends,activity:state.activity,lists:state.lists,events:state.events,at:Date.now()});}
function refreshEvery(){return Math.max(30,Number(state.data?.refresh_seconds)||60)*1000;}
const VIEW_NEEDS_DATA=view=>['overview','tagmarket','activity','plans','circle','banks','spend','income','account','people','projects','project','forecast'].includes(view)||(view==='settings'&&!!state.data?.founder);
// Смена периода, вкладки истории, страницы, валюты: то же, что переход —
// из памяти, если свежее, иначе догружаем только отчёт раздела. Раньше каждое
// такое нажатие перегружало всё (4 запроса), и частые переключения упирались
// в лимит сервера — «Слишком много запросов. Подождите минуту»
// Данных в памяти нет: подсветка переезжает на нажатую кнопку сразу, а экран
// со старыми цифрами стоит, пока не придёт новый отчёт, — одна перерисовка
// вместо двух (каркас-заглушка, потом данные). Быстрые нажатия подряд
// сливаются: грузится только последний выбор
let choiceTimer=0;
function markChoice(el){
 const strip=el?.closest('.segmented');if(!strip)return;
 const old=strip.querySelector('button.active'),prev=new Map();
 if(old)prev.set([...strip.querySelectorAll('button')].map(b=>b.dataset.value||b.textContent).join('|'),{left:old.offsetLeft,width:old.offsetWidth});
 strip.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b===el));
 positionThumbs(prev);
}
function showCached(el){
 clearTimeout(choiceTimer);cancelLoads();
 const c=viewCache.get(viewKey());
 if(c&&Date.now()-c.at<refreshEvery()){state.report=c.report;state.reportError=c.reportError||'';if(state.view==='tagmarket')state.priceChart=c.priceChart;render();return;}
 if(!el?.closest('.segmented')){render();return loadView();}
 markChoice(el);
 document.body.classList.add('is-loading');
 choiceTimer=setTimeout(loadView,220);
}
// Переключение отменяет загрузки, которые ещё в пути: иначе ответ по прежнему
// периоду или разделу, пришедший позже, лёг бы под новую подпись
function cancelLoads(){generation++;document.body.classList.remove('is-loading');}
async function loadView(){
 const gen=++generation,key=viewKey();document.body.classList.add('is-loading');
 try{const parts=await viewParts();if(gen!==generation||key!==viewKey())return;Object.assign(state,parts);remember();render();}
 catch(error){if(gen===generation)toast('Не удалось обновить данные. Показаны последние полученные значения.');}
 finally{if(gen===generation)document.body.classList.remove('is-loading');}
}
let quietPending=false,quietFlushTimer=0;
function uiEditing(){return $('#dialog').open||!!document.querySelector('input:focus,textarea:focus,select:focus')||[...document.querySelectorAll('#main input,#main textarea,#main select')].some(el=>el.type==='checkbox'?el.checked!==el.defaultChecked:el.tagName==='SELECT'?el.value!==([...el.options].find(o=>o.defaultSelected)||el.options[0])?.value:el.value!==el.defaultValue);}
function flushQuiet(){clearTimeout(quietFlushTimer);quietFlushTimer=setTimeout(()=>{if(quietPending&&!uiEditing()&&!state.busy){quietPending=false;refresh(true);}},0);}
document.addEventListener('focusout',flushQuiet);document.querySelector('#dialog').addEventListener('close',flushQuiet);
let lastOkAt=Date.now();
function setOffline(offline){let bar=$('#offline-bar');if(!offline){bar?.remove();return;}const time=new Date(lastOkAt).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});if(!bar){bar=document.createElement('div');bar.id='offline-bar';bar.setAttribute('role','status');document.body.prepend(bar);}bar.innerHTML=`<span>Нет связи с сервером · данные от ${esc(time)}</span><button type="button" class="text-link" data-action="refresh">Повторить</button>`;}
window.addEventListener('online',()=>{if($('#offline-bar'))refresh(true);});
async function refresh(quiet=false){
 if(quiet&&uiEditing()){quietPending=true;return;}
 if(state.busy){if(quiet)quietPending=true;else {state.pendingRefresh=true;generation++;}return;}
 if(quiet)quietPending=false;
 state.busy=true;document.body.classList.add('is-loading');const gen=++generation;
 try{
 const data=await api('/bootstrap');if(gen!==generation)return;state.data=data;state.circle=null;lastOkAt=Date.now();setOffline(false);state.displayCurrency=data.display_currency||state.displayCurrency;$('#display-currency').value=state.displayCurrency;syncCurrencyUi();scheduleRefresh();
  const parts=await viewParts();
  const notifications=await api('/notifications').catch(()=>state.notifications);
  if(gen!==generation)return;
  // явное обновление (кнопка, сохранение, отзыв гостя) — данные могли
  // измениться везде, запомненное в других разделах больше не верно
  if(!quiet)viewCache.clear();
  Object.assign(state,parts);remember();
  state.notifications=notifications;updateNotificationBadge();
  const newest=notifications.items?.[0];
  if(newest&&notifications.unread&&(!notificationsStarted||newest.id>lastNotificationId))
   eventToast(newest,notifications.unread);
  notificationsStarted=true;lastNotificationId=Math.max(lastNotificationId,newest?.id||0);
  // фоновое обновление перерисовывает экран, только если данные изменились:
  // раньше раз в 30-60 с весь #main пересобирался с теми же цифрами — экран
  // мигал, анимации перезапускались, полосы периодов теряли прокрутку
  const key=quiet?paintKey():'';
  if(!quiet)render();
  else if(key!==paintedKey){if(uiEditing())quietPending=true;else {render(true);paintedKey=key;}}
 }catch(error){
  if(!state.data){if(!preview&&!tg?.initData){$('#main').innerHTML=authScreen();}else $('#main').innerHTML=empty('Не удалось открыть кабинет',error.message,button('refresh','Попробовать снова','primary','refresh'));}
  else{setOffline(true);if(!quiet)toast('Не удалось обновить данные. Показаны последние полученные значения.');}
 }finally{state.busy=false;document.body.classList.remove('is-loading');if(state.pendingRefresh){state.pendingRefresh=false;await refresh();}else if(quietPending&&!uiEditing())flushQuiet();}
}
let navSeq=0;
async function navigate(){
 const seq=++navSeq;
 let [view,login]=location.hash.slice(1).split('/');
 if(view==='lists'){view='plans';login='notes';}   // прежняя ссылка на списки
 if(view==='plans'){if(['tasks','calendar','notes'].includes(login))state.listsTab=login;login=undefined;}
 const next=['overview','tagmarket','activity','plans','circle','banks','spend','income','accounts','account','projects','project','forecast','people','settings','faq'].includes(view)?view:'overview';
 const direction=Math.sign((VIEW_ORDER[next]??0)-(VIEW_ORDER[state.view]??0));
 const moved=next!==state.view||(!!login&&(next==='project'?login!==state.projectId:Number(login)!==state.login));
 // тот же раздел (повторное событие hashchange) — экран уже верный
 if(state.data&&!moved)return;
 clearTimeout(choiceTimer);if(state.data)cancelLoads();
 if(state.filters[state.view])state.filters[state.view]={period:state.period,from:state.from,to:state.to};
 if(next!==state.view&&state.filters[next])Object.assign(state,state.filters[next]);
 state.view=next;state.faqDeep=next==='faq'&&login==='connect';   // «Как подключить» открывает регистрацию, обычный вход в раздел — нет
 if(login){if(next==='project')state.projectId=login;else if(next!=='faq')state.login=Number(login);}
 state.offset=0;state.kind='trades';
 const cached=state.data&&viewCache.get(viewKey());
 const fresh=!!state.data&&(!VIEW_NEEDS_DATA(next)||(!!cached&&Date.now()-cached.at<refreshEvery()));
 state.report=cached?cached.report:null;state.reportError=cached?.reportError||'';
 if(cached&&next==='tagmarket')state.priceChart=cached.priceChart;
 if(cached&&['projects','project','forecast','overview'].includes(next)){state.projects=cached.projects;state.projectsError=cached.projectsError||'';}
 if(cached&&['projects','income'].includes(next))state.income=cached.income??state.income;
 if(cached&&next==='projects')state.goals=cached.goals??state.goals;
 if(cached&&next==='people')state.friends=cached.friends??state.friends;
 if(cached&&['overview','projects','banks','income'].includes(next))state.banks=cached.banks??state.banks;
 if(cached&&['projects','spend'].includes(next))state.spend=cached.spend??state.spend;
 if(cached&&['overview','activity','plans'].includes(next)){state.activity=cached.activity??state.activity;state.lists=cached.lists??state.lists;state.events=cached.events??state.events;}
 // подсветка панели едет сразу по нажатию, а старый экран уходит параллельно:
 // ждать отрисовки нового значило бы показать задержку на самом заметном месте
 nav();
 if(state.data){
  if(moved)await leaveView(direction);
  // пока старый экран уезжал, нажали другой раздел: отрисует тот переход,
  // иначе новый экран появлялся дважды подряд
  if(seq!==navSeq)return;
  if(moved)window.scrollTo(0,0);
  render();
  if(moved)enterView(direction);
 }
 if(!state.data)await refresh();
 else if(!fresh)await loadView();
 if(seq===navSeq&&next==='faq'&&login==='connect')$('#faq-connect')?.scrollIntoView({block:'start'});
 dialogBack();
}
// [id, название, цвет шапки Telegram, образцы]. Фон у всех схем один —
// графитовый: гамма меняет только акценты, не всю тему
const SCHEMES=[['lime','Лайм','#111416',['#111416','#d0f29b','#b8a6e9']],['sapphire','Сапфир','#111416',['#111416','#5eb3ff','#b18bff']],['velvet','Золото','#111416',['#111416','#e8c576','#d999a8']]];
function currentScheme(){return document.documentElement.dataset.scheme||'lime';}
function setScheme(id,persist=true){const sc=SCHEMES.find(x=>x[0]===id)||SCHEMES[0],root=document.documentElement;root.dataset.scheme=sc[0];try{if(persist)localStorage.setItem('tag-scheme',sc[0]);}catch{}document.querySelector('meta[name="theme-color"]').content=sc[2];try{tg?.setHeaderColor(sc[2]);tg?.setBackgroundColor(sc[2]);}catch{}if(state.data&&state.view==='settings')render();}
let modalLock=null;
function dialogBack(){tg?.BackButton?.[($('#dialog').open||['account','project'].includes(state.view))?'show':'hide']();}
function lockDialog(){if(modalLock)return;modalLock={x:scrollX,y:scrollY};document.documentElement.classList.add('modal-open');document.body.style.setProperty('--modal-top',`${-modalLock.y}px`);dialogBack();}
document.querySelector('#dialog').addEventListener('close',()=>{if($('#dialog').open||!modalLock)return;const pos=modalLock;modalLock=null;document.documentElement.classList.remove('modal-open');document.body.style.removeProperty('--modal-top');window.scrollTo(pos.x,pos.y);dialogBack();});
async function dialog(title,body,label='Сохранить',opts={}){const current=$('#dialog');if(current.open||modalLock){const closed=new Promise(resolve=>current.addEventListener('close',resolve,{once:true}));if(current.open&&!await requestDialogExit(current))return null;await closed;}return new Promise(resolve=>{const d=$('#dialog');$('#dialog-title').textContent=title;$('#dialog-body').innerHTML=body;$('#dialog-submit').textContent=label;const info=['Закрыть','Понятно','Готово'].includes(label);d.classList.toggle('info-only',info);d.onclick=e=>{if(info&&e.target===d)requestDialogExit(d);};d.returnValue='';d.onclose=()=>{d.dataset.dirty='';const cancelButton=d.querySelector('.dialog-actions button[value="cancel"]');if(cancelButton)cancelButton.textContent='Отмена';const values=Object.fromEntries(new FormData($('form',d)));resolve(d.returnValue==='confirm'?values:null);};const form=$('form',d);form.querySelectorAll('select[name="capitalization"]').forEach(select=>{const date=form.querySelector('input[name="capitalization_from"]');if(date)date.disabled=select.value==='inherit';});const cancelButton=d.querySelector('.dialog-actions button[value="cancel"]');if(cancelButton)cancelButton.textContent=opts.cancelLabel||'Отмена';
  form.oninput=()=>d.querySelector('.dialog-error')?.remove();
  form.onsubmit=e=>{if(e.submitter?.value==='cancel'){e.preventDefault();requestDialogExit(d,true);return;}const fields=[...d.querySelectorAll('input,select,textarea')];if(!fields.every(f=>f.reportValidity())){e.preventDefault();return;}
   // своя проверка: окно остаётся открытым, ошибка видна внутри него, введённое не теряется
   if(opts.validate){const message=opts.validate(Object.fromEntries(new FormData(form)));if(message){e.preventDefault();dialogError(d,message);}}};
  lockDialog();d.showModal();dialogBack();opts.onOpen?.(d);});}
function dialogError(d,message){d.querySelector('.dialog-error')?.remove();const box=document.createElement('div');box.className='dialog-error';box.setAttribute('role','alert');box.textContent=message;$('#dialog-body').prepend(box);d.scrollTo?.({top:0,behavior:'smooth'});}
function dialogHasChanges(d){return d.dataset.dirty==='1'||[...d.querySelectorAll('input,select,textarea')].some(f=>{if(f.type==='file')return f.files?.length>0;if(f.type==='checkbox'||f.type==='radio')return f.checked!==f.defaultChecked;if(f.tagName==='SELECT')return f.value!==([...f.options].find(o=>o.defaultSelected)?.value??f.options[0]?.value);return f.value!==f.defaultValue;});}
// Выбор файла: системное окно выбора шлёт «cancel» (всплывает до диалога), на телефоне — ещё и «назад»
// Telegram. Пока окно выбора открыто и сразу после него закрытие диалога не принимаем.
let filePickerUntil=0;
const filePickerGuard=()=>Date.now()<filePickerUntil;
document.addEventListener('click',event=>{if(event.target.closest?.('.cmp-attach,input[type=file]'))filePickerUntil=Date.now()+60000;},true);
for(const type of ['change','cancel'])document.addEventListener(type,event=>{if(event.target.matches?.('input[type=file]'))filePickerUntil=Date.now()+600;},true);
const filePickerReturned=()=>{if(filePickerUntil>Date.now())filePickerUntil=Math.min(filePickerUntil,Date.now()+600);};
window.addEventListener('focus',filePickerReturned);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)filePickerReturned();});
// explicit — нажата наша кнопка «Отмена»/«Назад»/крестик: это решение человека, а не «cancel» окна выбора файла
function requestDialogExit(d,explicit=false){if(!explicit&&filePickerGuard())return Promise.resolve(false);if(!dialogHasChanges(d)){d.close('cancel');return Promise.resolve(true);}return new Promise(resolve=>{const finish=ok=>{if(ok&&d.open)d.close('cancel');resolve(ok);};if(tg?.showConfirm)tg.showConfirm('Выйти без сохранения изменений?',finish);else finish(window.confirm('Выйти без сохранения изменений?'));});}
$('#dialog').addEventListener('cancel',event=>{if(event.target!==event.currentTarget)return;event.preventDefault();requestDialogExit(event.currentTarget);});
window.addEventListener('beforeunload',event=>{if($('#dialog').open&&dialogHasChanges($('#dialog'))){event.preventDefault();event.returnValue='';}});
async function confirm(title,text,label='Подтвердить'){return !!await dialog(title,`<p>${esc(text)}</p>`,label);}
async function mutate(path,data,method='POST'){await api(path,{method,body:data===undefined?undefined:JSON.stringify(data)});tg?.HapticFeedback?.notificationOccurred('success');toast('Сохранено. Изменения доступны и в боте.');await refresh();}
function field(label,name,type='text',value='',extra=''){return `<label class="field">${esc(label)}<input type="${type}" name="${name}" value="${esc(value)}" ${extra}></label>`;}
const PROJECT_PERIODS={day:'день',week:'неделю',month:'месяц'};
let projectFormSeq=0;
function projectMoney(value,currency){return money(value,currency);}
function projectToday(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk'}).format(new Date());}
function projectHasCapitalization(p){return !!p.has_capitalization;}
function projectBonusLine(p){const dates=[...new Set(p.accounts.filter(a=>a.bonus_active&&a.bonus_expires_at).map(a=>date(a.bonus_expires_at)))];return `${p.bonus_total>0?`<div class="project-finance-row bonus-line"><small>Бонус активен${dates.length===1?` · до ${esc(dates[0])}`:dates.length>1?' · разные сроки':''}</small><b>+ ${projectMoney(p.bonus_total,p.currency)}</b></div>`:''}${p.expired_bonus_total>0?`<div class="project-finance-row bonus-expired"><small>Бонус завершён</small><b>${projectMoney(p.expired_bonus_total,p.currency)}</b></div>`:''}`;}
function projectStatus(p){const parts=[];if(p.paused)parts.push('<i class="paused">На паузе — не входит в итоги</i>');else if(p.income_starts)parts.push(`<i class="starts">Начисления с ${esc(date(p.income_starts))}</i>`);if(!p.paused&&p.paused_accounts)parts.push(`<i class="paused">${countLabel(p.paused_accounts,['аккаунт','аккаунта','аккаунтов'])} на паузе</i>`);return parts.length?`<span class="pa-tags project-status">${parts.join('')}</span>`:'';}
function projectFinance(p,{detail=false}={}){return `${projectStatus(p)}<div class="project-finance"><div class="project-finance-row"><small>Ваши средства</small><b>${projectMoney(p.total,p.currency)}</b></div>${p.accrued_income?`<div class="project-finance-row"><small>Начислено</small><b class="${p.accrued_income<0?'negative':'positive'}">${money(p.accrued_income,p.currency,true)}</b></div><div class="project-finance-row"><small>Баланс сейчас</small><b>${projectMoney(p.current_total,p.currency)}</b></div>`:projectHasCapitalization(p)?`<div class="project-finance-row"><small>Баланс сейчас</small><b>${projectMoney(p.current_total,p.currency)}</b></div>`:''}${projectBonusLine(p)|| (detail?'<div class="project-finance-row"><small>Бонусы</small><b>Нет активных</b></div>':'')}<div class="project-finance-row working-capital"><small>Рабочий капитал</small><b>${projectMoney(p.working_total,p.currency)}</b></div>${detail?`<div class="project-finance-row project-period-income"><small>${projectRateLabel(p)}</small><b>${p.calculation_limited?'—':projectIncome(p)}</b></div>`:''}</div>`;}
function projectPeriodDays(period){if(period==='day')return 1;if(period==='week')return 7;const [y,m]=projectToday().split('-').map(Number);return new Date(Date.UTC(y,m,0)).getUTCDate();}
function projectDailyRate(p){return p.daily_rate_percent??p.rate_percent/projectPeriodDays(p.period);}
function projectDailyIncome(p){return p.daily_income??(p.expected_income==null?null:p.expected_income/projectPeriodDays(p.period));}
function projectIncome(p){const v=projectDailyIncome(p);return v==null?'—':`≈ ${v>0?'+':''}${projectMoney(v,p.currency)} / день`;}
function projectRateLabel(p){return `${p.income_mode==='fixed'?projectMoney(projectDailyIncome(p),p.currency)+' фикс.':number(projectDailyRate(p))+'%'} / день${p.period==='day'&&p.business_days_only?' · по будням':''}`;}
function tagStatsOk(){const t=state.tagStats;return !!(t&&t.sufficient&&t.average_daily_return!=null);}
function tagDailyRate(){const t=state.tagStats,ok=tagStatsOk(),capital=displayAmount(tagBalance(),'USD'),income=ok&&capital!=null?capital*t.average_daily_return:null;return `<div class="project-rate"><span>${ok?`${number(Math.round(t.average_daily_return*10000)/100)}% / день`:'Доходность / день'} · только по будням</span><b>${ok&&income!=null?`≈ ${income>0?'+':''}${money(income,state.displayCurrency)} / день`:'—'}</b></div>`;}
// Три карточки Финансов — один каркас (значок, название, строки, строка дохода), но у каждой своя
// живая картинка: у проектов — кольцо доли портфеля, у TagMarket — столбики дней, у банков — полоса долей.
function shareRing(p){
 const portfolio=portfolioTotals(),total=portfolio.working??portfolio.own,mine=displayAmount(p.working_total??p.total,p.currency);
 if(!total||total<=0||mine==null||p.paused)return '';
 const share=Math.max(0,Math.min(1,mine/total));
 return `<span class="share-ring" title="Доля в портфеле: ${Math.round(share*100)}%">${ring(share,1,38,'Доля в портфеле')}<b>${Math.round(share*100)}%</b></span>`;
}
function tagSpark(){
 const byIndex=[];
 for(const a of state.data.accounts){const days=a.totals?.days||[];days.forEach((v,i)=>{const x=displayAmount(v,a.totals.cur||'USD');if(x!=null)byIndex[i]=(byIndex[i]||0)+x;});}
 const vals=byIndex.filter(v=>v!=null).slice(-14);
 if(vals.length<2)return '';
 const max=Math.max(...vals.map(Math.abs),1e-9);
 return `<div class="spark" role="img" aria-label="Результат по дням">${vals.map((v,i)=>`<i class="${v<0?'neg':'pos'}${i===vals.length-1?' last':''}" style="--h:${Math.max(8,Math.abs(v)/max*100).toFixed(1)}%;--d:${i*45}ms" title="${esc(money(v,state.displayCurrency,true))}"></i>`).join('')}</div>`;
}
function tagMonthRow(){const t=state.data.totals.USD||{},v=t.month==null?null:displayAmount(t.month,'USD');return v==null?'':`<div class="project-finance-row"><small>За месяц</small><b class="${v<0?'negative':'positive'}">${money(v,state.displayCurrency,true)}</b></div>`;}
function tagTradingDayRow(){const t=state.data.totals.USD||{},value=t.trading_day_net==null?null:displayAmount(t.trading_day_net,'USD');return t.trading_day?`<div class="project-finance-row tag-trading-day"><small>Плюс за ${esc(date(t.trading_day))}</small><b class="${value!=null&&value<0?'negative':'positive'}">${value==null||t.trading_day_partial?'—':money(value,state.displayCurrency,true)}</b></div>`:'';}
function projectCard(p){if(p.system)return `<a href="#tagmarket" class="panel project-card system-project tag-card" data-ui-key="project-tagmarket"><div class="project-card-head"><span class="project-icon">${icon('chart')}</span><h2>TagMarket</h2>${icon('arrow')}</div><small class="project-count">${countLabel(p.accounts.length,['торговый счёт','торговых счёта','торговых счетов'])}</small><div class="project-finance"><div class="project-finance-row working-capital"><small>Баланс</small><b>${p.total==null?'—':money(p.total,state.displayCurrency)}</b></div>${tagMonthRow()}${tagTradingDayRow()}</div>${tagSpark()}${tagDailyRate()}</a>`;return `<a href="#project/${esc(p.id)}" class="panel project-card proj${p.paused?' is-paused':''}" style="--ph:${hashHue(p.id+p.name)}" data-ui-key="project-${esc(p.id)}">${projectArt(p)}<div class="project-card-head"><span class="project-icon">${icon('projects')}</span><h2>${esc(p.name)}</h2>${shareRing(p)}${icon('arrow')}</div>${p.multi?`<small class="project-count">${countLabel(p.accounts.length,['аккаунт','аккаунта','аккаунтов'])}</small>`:''}${projectFinance(p)}<div class="project-rate"><span>${projectRateLabel(p)}</span><b>${p.calculation_limited?'—':projectIncome(p)}</b></div></a>`;}
// Динамика по всем проектам: доля каждого в рабочем капитале портфеля и
// ожидаемый доход в день, суммы приведены к валюте отображения.
function projectsDynamics(portfolio){const cur=state.displayCurrency,rows=[],tagOk=tagStatsOk(),tagCap=portfolio.tag;let partial=portfolio.tag==null;
 if(tagCap!=null)rows.push({name:'TagMarket',href:'#tagmarket',work:tagCap,daily:tagOk?tagCap*state.tagStats.average_daily_return:null,note:tagOk?`${number(Math.round(state.tagStats.average_daily_return*10000)/100)}% / день`:'Нет истории'});
 for(const p of activeProjects()){const work=displayAmount(p.working_total??p.total,p.currency),inc=projectDailyIncome(p),daily=p.calculation_limited||inc==null?null:displayAmount(inc,p.currency);if(work==null)partial=true;rows.push({name:p.name,href:`#project/${p.id}`,work,daily,note:projectRateLabel(p)});}
 const known=rows.filter(r=>r.work!=null),total=known.reduce((a,r)=>a+r.work,0);if(!known.length||total<=0)return '';
 known.sort((a,b)=>b.work-a.work);const withIncome=known.filter(r=>r.daily!=null),daily=withIncome.reduce((a,r)=>a+r.daily,0),peak=Math.max(...known.map(r=>r.work));
 const row=r=>`<li><div class="feed-day pd"><span class="feed-date"><b>${esc(r.name)}</b><small>${esc(r.note)}</small></span><span class="feed-bar"><i style="--w:${Math.max(3,r.work/peak*100).toFixed(1)}%"></i></span><span class="feed-sum"><b>${money(r.work,cur)}</b><small>${(r.work/total*100).toFixed(1).replace('.',',')}% портфеля${r.daily==null?'':` · ≈ ${money(r.daily,cur,true)} / день`}</small></span></div></li>`;
 return `<section class="project-dynamics"><div class="panel-head"><div><span class="eyebrow">ДОХОД</span><h2>По всем проектам</h2></div><span class="badge">${countLabel(known.length,['проект','проекта','проектов'])}</span></div><div class="pd-summary"><div><small>Доход в день</small><b class="${daily<0?'negative':'positive'}">${withIncome.length?`≈ ${money(daily,cur,true)}`:'—'}</b></div><div><small>За 30 дней</small><b class="${daily<0?'negative':'positive'}">${withIncome.length?`≈ ${money(daily*30,cur,true)}`:'—'}</b></div></div><ol class="feed pd-list">${known.map(row).join('')}</ol>${partial||withIncome.length<known.length?'<p class="feed-note">Часть проектов не вошла в сумму: нет курса валют или расчёт ограничен.</p>':''}</section>`;}
// ── Траты: подписки, регулярные списания и покупки ──
// Регулярная трата знает период и дату — следующее списание сервер считает сам.
const SPEND_BRANDS=[[/netflix|нетфликс/i,'#e50914','#5c0307'],[/spotify|спотифай/i,'#1db954','#0b4f22'],[/youtube|ютуб/i,'#ff0033','#6b0012'],[/apple|icloud|айклауд/i,'#8e9aa6','#2e3338'],[/яндекс|yandex/i,'#fc3f1d','#7a1606'],[/telegram|телеграм/i,'#2aabee','#0d5a85'],[/chatgpt|openai/i,'#10a37f','#064a39'],[/claude|anthropic/i,'#d97757','#6b3220'],[/google|гугл/i,'#4285f4','#163e8a'],[/кинопоиск|kinopoisk/i,'#ff6600','#7a3000'],[/okko|окко/i,'#5b2be0','#24106b'],[/ivi|иви/i,'#ea003d','#66001b'],[/steam/i,'#2a475e','#101c27'],[/xbox/i,'#107c10','#053b05'],[/playstation|psn/i,'#0070d1','#00285c'],[/мтс|mts/i,'#e30611','#6b0307'],[/a1|а1/i,'#e2001a','#66000c'],[/life|лайф/i,'#7a2fa8','#32104a']];
const SPEND_CATS={subs:'Подписки',connect:'Связь и интернет',home:'Жильё и ЖКУ',transport:'Транспорт',food:'Еда',shopping:'Покупки',health:'Здоровье',fun:'Развлечения',learn:'Обучение',other:'Другое'};
const SPEND_PERIODS={week:'раз в неделю',month:'раз в месяц',year:'раз в год'};
function spendLogo(title,small=false){const hit=SPEND_BRANDS.find(([re])=>re.test(title)),h=hashHue(title);const [c1,c2]=hit?[hit[1],hit[2]]:[`hsl(${h} 60% 50%)`,`hsl(${(h+40)%360} 55% 22%)`];return `<span class="sp-logo${small?' small':''}" style="--c1:${c1};--c2:${c2}" aria-hidden="true">${esc(String(title||'?').trim().slice(0,1).toUpperCase())}</span>`;}
function sumIn(totals){let sum=0,partial=false;for(const [c,v] of Object.entries(totals||{})){const x=displayAmount(v,c);if(x==null)partial=true;else sum+=x;}return {sum,partial};}
function spendWhen(u){return u.in_days===0?'сегодня':u.in_days===1?'завтра':dueLabel(u.date);}
function spendSection(){
 const d=state.spend,cur=state.displayCurrency;
 if(!d)return '';
 const head=`<div class="sec-row"><h2>Траты</h2><a class="text-link" href="#spend">Все ${icon('chevron')}</a></div>`;
 if(!d.items.length)return `<section class="fin-spend" data-ui-key="fin-spend">${head}<a href="#spend" class="spend-sum empty"><span class="sp-orb">${icon('repeat')}</span><span><b>Подписки и покупки</b><small>Запишите — Platformer покажет, сколько уходит в месяц и что скоро спишется</small></span>${icon('chevron')}</a></section>`;
 const m=sumIn(d.monthly),t=sumIn(d.this_month),next=d.upcoming[0],subs=d.items.filter(i=>i.kind==='recurring'&&i.active);
 return `<section class="fin-spend" data-ui-key="fin-spend">${head}<a href="#spend" class="spend-sum"><span class="sp-glow" aria-hidden="true"></span><span class="ss-main"><small>Регулярно в месяц</small><b>${m.partial&&!m.sum?'—':countUp(m.sum,`money:${cur}`)}</b><em>в этом месяце всего ${money(t.sum,cur)}</em></span>${subs.length?`<span class="ss-logos">${subs.slice(0,5).map(i=>spendLogo(i.title,true)).join('')}${subs.length>5?`<i>+${subs.length-5}</i>`:''}</span>`:''}${next?`<span class="ss-next">${spendLogo(next.title,true)}<span><b>${esc(next.title)}</b><small>${esc(spendWhen(next))}</small></span><b>${esc(bankMoney(next.amount,next.currency))}</b></span>`:''}</a></section>`;
}
function spendView(){
 const back='<a href="#projects" class="button secondary small back">← Финансы</a>',d=state.spend,cur=state.displayCurrency;
 const m=d?sumIn(d.monthly):null,t=d?sumIn(d.this_month):null,year=state.spendSpan==='year';
 const spans=`<div class="segmented spend-span" role="tablist" aria-label="Период">${[['month','Месяц'],['year','Год']].map(([id,l])=>`<button type="button" role="tab" class="${state.spendSpan===id?'active':''}" aria-selected="${state.spendSpan===id}" data-action="spend-span" data-span="${id}">${l}</button>`).join('')}</div>`;
 const hero=`<div class="project-space">${back}</div><div class="page-head sec-hero tone-spend spend-head"><div class="sec-glow" aria-hidden="true"><i></i><i></i><i></i></div><div><span class="sec-eyebrow">Регулярно в месяц</span><b class="spend-total">${!d?'…':countUp(m.sum,`money:${cur}`)}</b><p>${d?`${year?'В этом году':'В этом месяце'} всего ${esc(money(t.sum,cur))}${m.partial||t.partial?' · часть без курса валют':''}`:'Подписки, платежи и покупки'}</p></div><div class="head-actions">${button('spend-add','Трата','primary head-primary','plus')}</div></div>${!d||d.items.length?spans:''}`;
 if(!d)return hero+(state.spendError?sectionError(state.spendError,'spend-reload'):skeleton('list'));
 if(!d.items.length)return hero+`<section class="lists-empty spend-empty"><span class="empty-orb">${icon('repeat')}</span><b>Запишите первую трату</b><p>Подписки и регулярные платежи — Platformer сам посчитает, когда и сколько спишется. Разовые покупки — чтобы видеть, куда уходят деньги.</p>${button('spend-add','Добавить трату','primary','plus')}</section>`;
 const cats=d.by_category.map(c=>({...c,v:sumIn(c.totals).sum})).filter(c=>c.v>0),whole=cats.reduce((n,c)=>n+c.v,0),[yy,mm]=d.month.split('-').map(Number);
 const catBlock=whole?`<section class="spend-cats" data-ui-key="spend-cats"><div class="sec-row"><h2>Куда уходит</h2><small class="muted">${year?`${yy} год`:MONTH_NAMES[mm-1]}</small></div><div class="fin-alloc">${cats.map((c,i)=>`<i class="cat-${esc(c.category)}" style="--w:${(c.v/whole*100).toFixed(1)}%;--d:${i*110}ms"></i>`).join('')}</div><div class="fin-legend">${cats.map(c=>`<span><i class="cat-${esc(c.category)}"></i>${esc(c.label)} <em>${money(c.v,cur)}</em></span>`).join('')}</div></section>`:'';
 const up=d.upcoming.length?`<section class="spend-upcoming" data-ui-key="spend-upcoming"><div class="sec-row"><h2>Скоро спишется</h2></div><div class="sp-timeline">${d.upcoming.map((u,i)=>{const [,um,ud]=u.date.split('-').map(Number);return `<button type="button" class="sp-up${u.in_days<=1?' soon':''}" style="--i:${i}" data-action="spend-edit" data-id="${esc(u.id)}"><span class="sp-when"><b>${ud}</b><small>${MONTH_NAMES[um-1].slice(0,3).toLowerCase()}</small></span>${spendLogo(u.title)}<span class="sp-body"><b>${esc(u.title)}</b><small>${esc(spendWhen(u))}</small></span><b class="sp-amount">${esc(bankMoney(u.amount,u.currency))}</b></button>`;}).join('')}</div></section>`:'';
 const rec=d.items.filter(i=>i.kind==='recurring').sort((a,b)=>(b.active-a.active)||String(a.next||'').localeCompare(String(b.next||'')));
 const row=r=>`<button type="button" class="sp-row${r.active?'':' off'}" data-action="spend-edit" data-id="${esc(r.id)}">${spendLogo(r.title)}<span class="sp-body"><b>${esc(r.title)}</b><small>${r.active?`${esc(r.period_label)} · ${esc(dueLabel(r.next).toLowerCase())}`:'на паузе'} · ${esc(r.category_label)}</small></span><span class="sp-right"><b>${esc(bankMoney(r.amount,r.currency))}</b>${r.active&&r.period!=='month'?`<small>≈ ${esc(bankMoney(r.monthly,r.currency))} в мес</small>`:''}</span></button>`;
 const recList=rec.length?`<section class="spend-list" data-ui-key="spend-recurring"><div class="sec-row"><h2>Подписки и регулярные</h2><span class="badge">${rec.filter(r=>r.active).length}</span></div>${rec.map(row).join('')}</section>`:'';
 const once=d.items.filter(i=>i.kind==='once'),inSpan=i=>year?i.day.slice(0,4)===d.month.slice(0,4):i.day.slice(0,7)===d.month,now=once.filter(inSpan),older=once.filter(i=>!inSpan(i));
 const buy=i=>`<button type="button" class="sp-row" data-action="spend-edit" data-id="${esc(i.id)}">${spendLogo(i.title)}<span class="sp-body"><b>${esc(i.title)}</b><small>${esc(shortDay(i.day))} · ${esc(i.category_label)}</small></span><span class="sp-right"><b>${esc(bankMoney(i.amount,i.currency))}</b></span></button>`;
 const buys=now.length||older.length?`<section class="spend-list" data-ui-key="spend-once"><div class="sec-row"><h2>Покупки</h2><small class="muted">${year?`${yy} год`:`${MONTH_NAMES[mm-1].toLowerCase()} ${yy}`}</small></div>${now.map(buy).join('')||`<p class="muted sp-none">${year?'В этом году':'В этом месяце'} покупок нет.</p>`}${older.length?`<details class="sp-older"><summary>Ранее · ${older.length}</summary>${older.slice(0,60).map(buy).join('')}</details>`:''}</section>`:'';
 return hero+up+catBlock+recList+buys;
}
async function spendEditor(item=null){
 const cats=state.spend?.categories||SPEND_CATS,periods=state.spend?.periods||SPEND_PERIODS,currencies=state.spend?.currencies||['USD','EUR','RUB','BYN'];
 let error='',draft=item?{...item}:{kind:'recurring',title:'',amount:'',currency:currencies.includes(state.displayCurrency)?state.displayCurrency:'USD',category:'subs',period:'month',day:projectToday(),note:'',active:true};
 while(true){
  const rec=draft.kind==='recurring';
  const body=`${error?notice(error,true):''}<div class="sp-kind segmented" role="radiogroup" aria-label="Тип траты">${[['recurring','Регулярно'],['once','Покупка']].map(([id,l])=>`<label class="${draft.kind===id?'active':''}"><input type="radio" name="kind" value="${id}" ${draft.kind===id?'checked':''} data-spend-kind>${l}</label>`).join('')}</div>${field('Название','title','text',draft.title,'required maxlength="80" placeholder="Netflix, телефон, кроссовки…" autocomplete="off"')}<div class="field-row">${field('Сумма','amount','text',draft.amount===''?'':String(draft.amount).replace('.',','),'required inputmode="decimal" placeholder="0,00" autocomplete="off"')}<label class="field">Валюта<select name="currency">${currencies.map(c=>`<option ${c===draft.currency?'selected':''}>${c}</option>`).join('')}</select></label></div><div class="field-row"><label class="field sp-only-rec" ${rec?'':'hidden'}>Как часто<select name="period">${Object.entries(periods).map(([id,l])=>`<option value="${id}" ${id===(draft.period||'month')?'selected':''}>${esc(l)}</option>`).join('')}</select></label><label class="field"><span data-spend-day>${rec?'Ближайшее списание':'Дата покупки'}</span><input type="date" name="day" value="${esc(draft.day||projectToday())}" required></label></div><label class="field">Категория<select name="category">${Object.entries(cats).map(([id,l])=>`<option value="${id}" ${id===draft.category?'selected':''}>${esc(l)}</option>`).join('')}</select></label>${field('Заметка (необязательно)','note','text',draft.note||'','maxlength="300"')}${item&&rec?`<label class="check sp-only-rec"><input type="checkbox" name="active" ${draft.active?'checked':''}>Подписка активна — учитывать в тратах</label>`:''}${item?`<div class="guest-danger">${button('spend-delete','Удалить трату','danger small','',`data-id="${esc(item.id)}"`)}</div>`:''}`;
  const values=await dialog(item?(rec?'Регулярная трата':'Покупка'):'Новая трата',body);if(!values)return;
  const kind=values.kind==='once'?'once':'recurring';
  draft={...draft,kind,title:values.title,amount:values.amount,currency:values.currency,category:values.category,period:values.period||'month',day:values.day,note:values.note||'',active:item&&kind==='recurring'?values.active==='on':true};
  const payload={title:draft.title,amount:String(draft.amount).replace(/\s/g,'').replace(',','.'),currency:draft.currency,category:draft.category,kind,day:draft.day,note:draft.note,active:draft.active};if(kind==='recurring')payload.period=draft.period;
  if(preview){toast('В демо-режиме траты не сохраняются');return;}
  try{await api('/spend'+(item?'/'+item.id:''),{method:item?'PATCH':'POST',body:JSON.stringify(payload)});tg?.HapticFeedback?.notificationOccurred('success');toast('Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
// переключатель «Регулярно / Покупка» в окне траты: период нужен только регулярной
document.addEventListener('change',event=>{const r=event.target.closest?.('[data-spend-kind]');if(!r)return;const d=$('#dialog'),rec=r.value==='recurring';d.querySelectorAll('.sp-only-rec').forEach(x=>x.hidden=!rec);const label=d.querySelector('[data-spend-day]');if(label)label.textContent=rec?'Ближайшее списание':'Дата покупки';d.querySelectorAll('.sp-kind label').forEach(l=>l.classList.toggle('active',l.contains(r)));});
async function spendAction(action,el){
 if(action==='spend-add')return spendEditor();
 if(action==='spend-reload')return sectionReload();
 if(action==='spend-span'){if(state.spendSpan===el.dataset.span)return;state.spendSpan=el.dataset.span;state.spend=null;render();return sectionReload();}
 if(action==='spend-edit')return spendEditor(state.spend?.items.find(i=>i.id===el.dataset.id));
 if(action==='spend-delete'){if(!await closeDialogFirst())return;if(await confirm('Удалить трату?','Она исчезнет из сумм и ближайших списаний.','Удалить')){if(!preview)await api('/spend/'+el.dataset.id,{method:'DELETE'});await sectionReload();}return;}
}
function previewSpend(){
 const t=projectToday(),mk=(id,title,amount,currency,category,kind,day,period=null,active=true)=>({id,title,amount,currency,category,category_label:SPEND_CATS[category],kind,period,period_label:period?SPEND_PERIODS[period]:undefined,day,active,note:'',next:kind==='recurring'&&active?day:null,monthly:period==='week'?amount*52/12:period==='year'?amount/12:amount});
 const items=[mk('p1','Netflix',12.99,'EUR','subs','recurring',addDaysIso(t,1),'month'),mk('p2','Spotify',5.99,'USD','subs','recurring',addDaysIso(t,4),'month'),mk('p3','МТС',25,'BYN','connect','recurring',addDaysIso(t,9),'month'),mk('p4','Спортзал',30,'USD','health','recurring',addDaysIso(t,2),'week'),mk('p5','iCloud',119,'USD','subs','recurring',addDaysIso(t,140),'year'),mk('p6','YouTube Premium',4.99,'USD','subs','recurring',addDaysIso(t,20),'month',false),mk('p7','Кроссовки',89.5,'USD','shopping','once',t),mk('p8','Ужин в ресторане',64,'BYN','food','once',addDaysIso(t,-3)),mk('p9','Наушники',120,'USD','shopping','once',addDaysIso(t,-40))];
 const up=items.filter(i=>i.next&&i.next<=addDaysIso(t,30)).map(i=>({id:i.id,title:i.title,amount:i.amount,currency:i.currency,category:i.category,date:i.next,in_days:Math.round((Date.parse(i.next)-Date.parse(t))/864e5)})).sort((a,b)=>a.date.localeCompare(b.date));
 return {items,monthly:{EUR:12.99,USD:5.99+30*52/12+119/12,BYN:25},this_month:{EUR:12.99,USD:5.99+120+89.5,BYN:89},by_category:[{category:'shopping',label:'Покупки',totals:{USD:89.5}},{category:'health',label:'Здоровье',totals:{USD:120}},{category:'subs',label:'Подписки',totals:{EUR:12.99,USD:5.99}},{category:'food',label:'Еда',totals:{BYN:64}},{category:'connect',label:'Связь и интернет',totals:{BYN:25}}],upcoming:up,categories:SPEND_CATS,periods:SPEND_PERIODS,currencies:['USD','EUR','RUB','BYN'],month:t.slice(0,7)};
}
// Зарплата: до трёх зачислений в месяц — аванс, зарплата, премия. Месяц рисуется
// дорожкой с отметками дней выплат: прошедшие уже на карте, впереди — ждём
const INCOME_KINDS={advance:'Аванс',salary:'Зарплата',bonus:'Премия'};
function incomeFull(){const d=state.income;return !!d&&d.items.length>=d.limit;}
function incomeMonthly(){return sumIn(state.income?.monthly);}
function incomeAccount(i){const a=i.account;if(!a)return 'только учёт';return `${a.kind==='cash'?'наличные':a.bank}${a.last4?` •• ${a.last4}`:''}`;}
function incomeTrack(d){
 const t=projectToday(),[yy,mm,dd]=t.split('-').map(Number),last=new Date(Date.UTC(yy,mm,0)).getUTCDate(),pos=day=>((Math.min(day,last)-.5)/last*100).toFixed(2);
 const marks=d.items.filter(i=>i.active).map((i,n)=>{const day=Math.min(i.day,last),got=day<=dd;return `<button type="button" class="inc-mark k-${esc(i.kind)}${got?' got':''}" style="--x:${pos(day)}%;--i:${n}" data-action="income-edit" data-id="${esc(i.id)}" aria-label="${esc(`${i.title}, ${day}-го: ${bankMoney(i.amount,i.currency)}`)}"><i></i><b>${day}</b><small>${esc(i.title)}</small></button>`;}).join('');
 return `<div class="inc-track" role="group" aria-label="${esc(MONTH_NAMES[mm-1])}: дни выплат"><span class="inc-line"><span class="inc-fill" style="--w:${(dd/last*100).toFixed(1)}%"></span></span><span class="inc-today" style="--x:${pos(dd)}%" aria-hidden="true"></span>${marks}</div><div class="inc-scale" aria-hidden="true"><span>1</span><span>${MONTH_NAMES[mm-1].toLowerCase()}</span><span>${last}</span></div>`;
}
function incomeRow(i){return `<button type="button" class="inc-row k-${esc(i.kind)}${i.active?'':' off'}" data-action="income-edit" data-id="${esc(i.id)}"><span class="inc-day"><b>${i.day}</b><small>число</small></span><span class="sp-body"><b>${esc(i.title)}</b><small>${i.active?`${esc(dueLabel(i.next))} · ${esc(incomeAccount(i))}${i.account&&i.credit?' · сам зачислит':''}`:'на паузе'}</small></span><b class="sp-amount">+${esc(bankMoney(i.amount,i.currency))}</b></button>`;}
function incomeBody(d,full=false){
 const cur=state.displayCurrency,m=incomeMonthly(),got=sumIn(d.received),wait=sumIn(d.expected),spendM=sumIn(state.spend?.monthly);
 const free=state.spend&&!m.partial&&!spendM.partial&&spendM.sum>0?`<span class="inc-free">после подписок и регулярных трат ≈ <b>${money(m.sum-spendM.sum,cur)}</b></span>`:'';
 return `<div class="inc-sum"><span class="ss-main"><small>Доход в месяц</small><b>${m.partial&&!m.sum?'—':countUp(m.sum,`money:${cur}`)}</b><em>≈ ${money(m.sum*12/365,cur)} в день</em></span><span class="inc-split"><span><small>Пришло</small><b>${money(got.sum,cur)}</b></span><span><small>Ждём</small><b>${money(wait.sum,cur)}</b></span></span></div>${free}${incomeTrack(d)}${full?'':`<div class="inc-rows">${d.items.map(incomeRow).join('')}</div>`}`;
}
function incomeSection(){
 const d=state.income;if(!d)return '';
 const head=`<div class="sec-row"><h2>Зарплата</h2>${d.items.length?`<a class="text-link" href="#income">Подробнее ${icon('chevron')}</a>`:''}</div>`;
 if(!d.items.length)return `<section class="fin-income" data-ui-key="fin-income">${head}<button type="button" class="spend-sum empty inc-empty" data-action="income-add"><span class="sp-orb">${icon('plus')}</span><span><b>Зачисление зарплаты</b><small>Аванс, зарплата и премия — до трёх дат в месяц. В день выплаты сумма сама придёт на карту и войдёт в доход</small></span>${icon('chevron')}</button></section>`;
 return `<section class="fin-income" data-ui-key="fin-income">${head}<div class="inc-card"><span class="sp-glow" aria-hidden="true"></span>${incomeBody(d)}${d.items.length<d.limit?`<button type="button" class="text-link inc-add" data-action="income-add">${icon('plus')} ${esc(Object.entries(INCOME_KINDS).filter(([k])=>!d.items.some(i=>i.kind===k)).map(([,l])=>l).join(' или '))}</button>`:''}</div></section>`;
}
function incomeView(){
 const back='<a href="#projects" class="button secondary small back">← Финансы</a>',d=state.income,cur=state.displayCurrency,m=incomeMonthly();
 const hero=`<div class="project-space">${back}</div><div class="page-head sec-hero tone-income inc-head"><div class="sec-glow" aria-hidden="true"><i></i><i></i><i></i></div><div><span class="sec-eyebrow">Зарплата в месяц</span><b class="spend-total">${!d?'…':countUp(m.sum,`money:${cur}`)}</b><p>${d?`≈ ${esc(money(m.sum*12/365,cur))} в день — считается в доходе`:'Аванс, зарплата и премия'}</p></div><div class="head-actions">${d&&d.items.length<d.limit?button('income-add','Зачисление','primary head-primary','plus'):''}</div></div>`;
 if(!d)return hero+(state.incomeError?sectionError(state.incomeError,'income-reload'):skeleton('list'));
 if(!d.items.length)return hero+`<section class="lists-empty spend-empty"><span class="empty-orb">${icon('plus')}</span><b>Добавьте зарплату</b><p>До трёх дат в месяц: аванс, зарплата и премия, каждая на любое число. Выберите карту — в день выплаты Platformer сам прибавит сумму к её балансу.</p>${button('income-add','Добавить зачисление','primary','plus')}</section>`;
 return hero+`<section class="inc-page" data-ui-key="income-month"><div class="inc-card">${incomeBody(d,true)}</div></section><section class="spend-list" data-ui-key="income-list"><div class="sec-row"><h2>Зачисления</h2><span class="badge">${d.items.length} из ${d.limit}</span></div>${d.items.map(incomeRow).join('')}<p class="muted inc-hint">Если карта уже обновляется из SMS банка, выключите «зачислять на карту» — иначе сумма придёт дважды.</p></section>`;
}
async function incomeEditor(item=null){
 const d=state.income,accs=state.banks?.accounts||[],currencies=d?.currencies||['USD','EUR','RUB','BYN'],kinds=d?.kinds||INCOME_KINDS;
 const used=new Set((d?.items||[]).filter(i=>i.id!==item?.id).map(i=>i.kind));
 const free=Object.keys(kinds).find(k=>!used.has(k));
 if(!item&&!free){toast('Уже есть все три: аванс, зарплата и премия');return;}
 const fallbackDay={advance:5,salary:20,bonus:28};
 let error='',draft=item?{...item,amount:item.amount}:{kind:free,amount:'',currency:currencies.includes(state.displayCurrency)?state.displayCurrency:'USD',day:fallbackDay[free],account_id:accs.find(a=>a.kind==='card')?.id||accs[0]?.id||'',credit:true,active:true};
 while(true){
  const card=!!draft.account_id;
  const body=`${error?notice(error,true):''}<div class="sp-kind segmented inc-kind" role="radiogroup" aria-label="Что приходит">${Object.entries(kinds).map(([id,l])=>`<label class="${draft.kind===id?'active':''}${used.has(id)?' taken':''}"><input type="radio" name="kind" value="${id}" ${draft.kind===id?'checked':''} ${used.has(id)?'disabled':''} data-income-kind>${esc(l)}</label>`).join('')}</div><div class="field-row">${field('Сумма','amount','text',draft.amount===''?'':String(draft.amount).replace('.',','),'required inputmode="decimal" placeholder="0,00" autocomplete="off"')}${field('Число месяца','day','text',String(draft.day||''),'required inputmode="numeric" pattern="[0-9]*" maxlength="2" placeholder="1–31" autocomplete="off"')}</div><label class="field">На карту<select name="account_id" data-income-account><option value="">Без карты — только учёт дохода</option>${accs.map(a=>`<option value="${esc(a.id)}" ${a.id===draft.account_id?'selected':''}>${esc(`${a.kind==='cash'?'Наличные':a.bank}${a.title?` · ${a.title}`:''}${a.last4?` •• ${a.last4}`:''} · ${a.currency}`)}</option>`).join('')}</select></label><label class="field inc-only-free" ${card?'hidden':''}>Валюта<select name="currency">${currencies.map(c=>`<option ${c===draft.currency?'selected':''}>${c}</option>`).join('')}</select></label><label class="check inc-only-card" ${card?'':'hidden'}><input type="checkbox" name="credit" ${draft.credit?'checked':''}>Зачислять на карту в этот день</label>${item?`<label class="check"><input type="checkbox" name="active" ${draft.active?'checked':''}>Учитывать в доходе</label>`:''}<p class="muted inc-note">31-е в коротком месяце — последний день. Прошедшие даты задним числом не зачисляются.</p>${item?`<div class="guest-danger">${button('income-delete','Удалить зачисление','danger small','',`data-id="${esc(item.id)}"`)}</div>`:''}`;
  const values=await dialog(item?item.title:'Зачисление зарплаты',body);if(!values)return;
  draft={...draft,kind:values.kind||draft.kind,amount:values.amount,day:values.day,account_id:values.account_id||'',currency:values.currency||draft.currency,credit:values.credit==='on',active:item?values.active==='on':true};
  const payload={kind:draft.kind,amount:String(draft.amount).replace(/\s/g,'').replace(',','.'),day:Number(String(draft.day).trim())||0,account_id:draft.account_id||null,credit:draft.credit,active:draft.active};if(!draft.account_id)payload.currency=draft.currency;
  if(preview){toast('В демо-режиме зачисления не сохраняются');return;}
  try{await api('/income'+(item?'/'+item.id:''),{method:item?'PATCH':'POST',body:JSON.stringify(payload)});tg?.HapticFeedback?.notificationOccurred('success');toast('Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
// карта выбрана — валюта берётся из неё и появляется «зачислять на карту»
document.addEventListener('change',event=>{const t=event.target;const d=$('#dialog');if(t.closest?.('[data-income-account]')){const card=!!t.value;d.querySelectorAll('.inc-only-free').forEach(x=>x.hidden=card);d.querySelectorAll('.inc-only-card').forEach(x=>x.hidden=!card);}else if(t.closest?.('[data-income-kind]'))d.querySelectorAll('.inc-kind label').forEach(l=>l.classList.toggle('active',l.contains(t)));});
async function incomeAction(action,el){
 if(action==='income-add')return incomeEditor();
 if(action==='income-reload')return sectionReload();
 if(action==='income-edit')return incomeEditor(state.income?.items.find(i=>i.id===el.dataset.id));
 if(action==='income-delete'){if(!await closeDialogFirst())return;if(await confirm('Удалить зачисление?','Оно перестанет считаться в доходе. Уже зачисленные суммы останутся на карте.','Удалить')){if(!preview)await api('/income/'+el.dataset.id,{method:'DELETE'});await sectionReload();}return;}
}
function previewIncome(){
 const t=projectToday(),dd=Number(t.slice(8)),acc={bank:'Альфа-Банк',title:'Зарплатная',last4:'9490',kind:'card'};
 const mk=(id,kind,amount,day)=>{const [y,m]=t.split('-').map(Number),last=new Date(Date.UTC(y,m,0)).getUTCDate(),d=Math.min(day,last);const next=d>=dd?`${t.slice(0,8)}${String(d).padStart(2,'0')}`:addDaysIso(`${t.slice(0,8)}01`,last+d-1);return {id,kind,kind_label:INCOME_KINDS[kind],title:INCOME_KINDS[kind],amount,currency:'BYN',day,account_id:'b1',account:acc,credit:true,active:true,next};};
 const items=[mk('i1','advance',900,5),mk('i2','salary',1400,20),mk('i3','bonus',350,28)];
 const got={},wait={};for(const i of items)(Math.min(i.day,31)<=dd?got:wait).BYN=((Math.min(i.day,31)<=dd?got:wait).BYN||0)+i.amount;
 return {items,monthly:{BYN:2650},received:got,expected:wait,upcoming:[],kinds:INCOME_KINDS,currencies:['USD','EUR','RUB','BYN'],limit:3};
}
// ── Сводка месяца, цели накоплений, первый запуск ──
paths.target='M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M12 12h.01';
paths.split='M12 3v18 M5 8h5 M14 16h5 M6 21l-3-3 3-3 M18 3l3 3-3 3';
// доход месяца в валюте отображения: зарплата по датам + проекты (в день × прошедшие дни) + TagMarket за месяц
function goalCard(g,i){
 const cur=state.displayCurrency,pct=Math.round(g.progress*100);
 return `<button type="button" class="goal-card${g.done?' done':''}" style="--i:${i};--p:${pct}" data-action="goal-edit" data-id="${esc(g.id)}"><span class="goal-ring" aria-hidden="true"><span>${esc(g.emoji||'🎯')}</span></span><span class="goal-body"><b>${esc(g.title)}</b><small>${esc(bankMoney(g.saved,g.currency))} из ${esc(bankMoney(g.target,g.currency))}</small><em>${g.done?'Накоплено 🎉':g.per_month?`${g.late?'срок прошёл · ':''}${esc(bankMoney(g.per_month,g.currency))} в мес${g.deadline?` до ${esc(shortDay(g.deadline).toLowerCase())}`:''}`:'без срока'}</em></span><span class="goal-pct">${pct}%</span></button>`;
}
function goalsSection(){
 const d=state.goals;if(!d)return '';
 const head=`<div class="sec-row"><h2>Цели</h2>${d.items.length?`<button type="button" class="text-link head-primary-link" data-action="goal-add">${icon('plus')} Цель</button>`:''}</div>`;
 if(!d.items.length)return `<section class="fin-goals" data-ui-key="fin-goals">${head}<button type="button" class="spend-sum empty goal-empty" data-action="goal-add"><span class="sp-orb">${icon('target')}</span><span><b>Цель накоплений</b><small>Машина, отпуск, подушка — Platformer посчитает, сколько откладывать в месяц</small></span>${icon('chevron')}</button></section>`;
 return `<section class="fin-goals" data-ui-key="fin-goals">${head}<div class="goal-list">${d.items.map(goalCard).join('')}</div></section>`;
}
const GOAL_EMOJI=['🎯','🚗','✈️','🏠','🛡️','💻','📱','🎓','💍','🏖️','🎁','💰'];
async function goalEditor(goal=null){
 const currencies=state.goals?.currencies||['USD','EUR','RUB','BYN'];
 let error='',draft=goal?{...goal}:{title:'',emoji:'🎯',target:'',saved:'',currency:currencies.includes(state.displayCurrency)?state.displayCurrency:'USD',deadline:''};
 while(true){
  const body=`${error?notice(error,true):''}${field('На что копим','title','text',draft.title,'required maxlength="64" placeholder="Машина, отпуск, подушка…" autocomplete="off"')}<div class="emoji-pick" role="radiogroup" aria-label="Значок">${GOAL_EMOJI.map(e=>`<label><input type="radio" name="emoji" value="${e}" ${e===draft.emoji?'checked':''}><span>${e}</span></label>`).join('')}</div><div class="field-row">${field('Нужно','target','text',draft.target===''?'':String(draft.target).replace('.',','),'required inputmode="decimal" placeholder="0,00" autocomplete="off"')}<label class="field">Валюта<select name="currency">${currencies.map(c=>`<option ${c===draft.currency?'selected':''}>${c}</option>`).join('')}</select></label></div><div class="field-row">${field('Уже отложено','saved','text',draft.saved===''||draft.saved==null?'':String(draft.saved).replace('.',','),'inputmode="decimal" placeholder="0" autocomplete="off"')}${field('К какому сроку','deadline','date',draft.deadline||'')}</div>${goal?`<div class="inline-actions">${button('goal-add-money','Отложить','primary small','plus',`data-id="${esc(goal.id)}"`)}${button('goal-take-money','Забрать','secondary small','minus',`data-id="${esc(goal.id)}"`)}</div><div class="guest-danger">${button('goal-delete','Удалить цель','danger small','',`data-id="${esc(goal.id)}"`)}</div>`:''}`;
  const values=await dialog(goal?goal.title:'Новая цель',body);if(!values)return;
  draft={...draft,title:values.title,emoji:values.emoji||'',target:values.target,saved:values.saved,currency:values.currency,deadline:values.deadline||''};
  const num=v=>String(v||'').replace(/\s/g,'').replace(',','.');
  const payload={title:draft.title,emoji:draft.emoji,target:num(draft.target),saved:num(draft.saved)||0,currency:draft.currency,deadline:draft.deadline||null};
  if(preview){toast('В демо-режиме цели не сохраняются');return;}
  try{await api('/goals'+(goal?'/'+goal.id:''),{method:goal?'PATCH':'POST',body:JSON.stringify(payload)});tg?.HapticFeedback?.notificationOccurred('success');toast('Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
async function goalMoney(goal,sign){
 if(!goal||!await closeDialogFirst())return;
 let error='';
 while(true){
  const values=await dialog(sign>0?`Отложить на «${goal.title}»`:`Забрать из «${goal.title}»`,`${error?notice(error,true):''}${field('Сумма, '+goal.currency,'amount','text','','required inputmode="decimal" placeholder="0,00" autocomplete="off"')}<p class="muted">Отложено ${esc(bankMoney(goal.saved,goal.currency))} из ${esc(bankMoney(goal.target,goal.currency))}</p>`,sign>0?'Отложить':'Забрать');
  if(!values)return;
  if(preview){toast('В демо-режиме цели не сохраняются');return;}
  try{const g=await api(`/goals/${goal.id}/add`,{method:'POST',body:JSON.stringify({amount:(sign<0?'-':'')+String(values.amount).replace(/\s/g,'').replace(',','.')})});tg?.HapticFeedback?.notificationOccurred('success');toast(g.done?'Цель достигнута 🎉':'Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
async function goalAction(action,el){
 const goal=state.goals?.items.find(g=>g.id===el.dataset.id);
 if(action==='goal-add')return goalEditor();
 if(action==='goal-edit')return goalEditor(goal);
 if(action==='goal-add-money')return goalMoney(goal,1);
 if(action==='goal-take-money')return goalMoney(goal,-1);
 if(action==='goal-delete'){if(!await closeDialogFirst())return;if(await confirm('Удалить цель?','Отложенные деньги никуда не денутся — исчезнет только сама цель.','Удалить')){if(!preview)await api('/goals/'+el.dataset.id,{method:'DELETE'});await sectionReload();}return;}
}
// Первый запуск Финансов: три шага, пока не сделаны (или пока не скрыли)
function finOnboarding(){
 if(!state.banks||!state.income||!state.spend)return '';
 let hidden=false;try{hidden=localStorage.getItem('fin-onboard-hidden')==='1';}catch{}
 if(hidden)return '';
 const steps=[['bank-add','Карта или счёт','Баланс всех карт в одном месте',!!state.banks.accounts?.length],['income-add','Зарплата','Даты зачислений — сама придёт на карту',!!state.income.items?.length],['spend-add','Подписки и траты','Сколько уходит в месяц',!!state.spend.items?.length]];
 const done=steps.filter(s=>s[3]).length;if(done===steps.length)return '';
 return `<section class="fin-onboard" data-ui-key="fin-onboard"><div class="fo-head"><div><span class="sec-eyebrow">Начало · ${done} из ${steps.length}</span><h2>Настройте финансы за минуту</h2></div><button type="button" class="icon-btn small" data-action="onboard-hide" aria-label="Скрыть">×</button></div><span class="fo-meter" aria-hidden="true"><i style="--w:${done/steps.length*100}%"></i></span>${steps.map(([a,t,s,ok],i)=>ok?`<div class="fo-step done"><span class="fo-n">${icon('check')}</span><span><b>${t}</b><small>${s}</small></span></div>`:`<button type="button" class="fo-step" data-action="${a}"><span class="fo-n">${i+1}</span><span><b>${t}</b><small>${s}</small></span>${icon('chevron')}</button>`).join('')}</section>`;
}
function previewGoals(){const t=projectToday(),y=Number(t.slice(0,4));return {items:[{id:'g1',title:'Машина',emoji:'🚗',target:6000,saved:2150,left:3850,currency:'USD',deadline:`${y+1}-06-01`,progress:.358,done:false,per_month:481.25,months_left:8,late:false},{id:'g2',title:'Отпуск на море',emoji:'🏖️',target:1500,saved:1120,left:380,currency:'USD',deadline:`${y+1}-03-01`,progress:.747,done:false,per_month:95,months_left:4,late:false},{id:'g3',title:'Наушники',emoji:'🎧',target:300,saved:300,left:0,currency:'USD',deadline:null,progress:1,done:true,per_month:null,months_left:null,late:false}],per_month:{USD:576.25},saved:{USD:3570},currencies:['USD','EUR','RUB','BYN']};}
// ── Друзья: общие траты и кто кому должен ──
function debtText(bal){const e=Object.entries(bal||{});if(!e.length)return '';return e.map(([c,v])=>`${v>0?'должен вам':'вы должны'} ${bankMoney(Math.abs(v),c)}`).join(' · ');}
function friendInitial(n){return esc(String(n||'?').trim().slice(0,1).toUpperCase());}
function friendCard(f,i){
 const bal=Object.entries(f.balance||{}),owes=bal.some(([,v])=>v>0),owe=bal.some(([,v])=>v<0);
 const debt=bal.length?`<button type="button" class="fc-debt ${owes?'plus':owe?'minus':''}" data-action="friend-settle" data-id="${esc(f.id)}" aria-label="Рассчитаться: ${esc(debtText(f.balance))}"><span>${esc(debtText(f.balance))}</span>${icon('chevron')}</button>`:`<small class="muted">${f.former?'больше не в кругу':'долгов нет'}</small>`;
 return `<section class="friend-card${f.former?' former':''}" style="--i:${i};--h:${hashHue(f.name)}" data-ui-key="friend-${esc(f.id)}"><span class="fc-avatar">${friendInitial(f.name)}</span><div class="fc-info"><b>${esc(f.name)}</b>${debt}</div></section>`;
}
function splitRow(x){
 const cur=x.currency;
 return `<div class="split-row${x.kind==='settle'?' settle':''}"><span class="sp-when"><b>${Number(x.day.slice(8))}</b><small>${MONTH_NAMES[Number(x.day.slice(5,7))-1].slice(0,3).toLowerCase()}</small></span><span class="sp-body"><b>${esc(x.kind==='settle'?`${x.payer_name} → ${x.members[0]?.name}`:x.title)}</b><small>${x.kind==='settle'?'возврат долга':`платил${x.payer_name==='Вы'?'и вы':` ${esc(x.payer_name)}`} · ${esc(x.members.map(m=>m.name).join(', '))} · по ${esc(bankMoney(x.share,cur))}`}</small></span><b class="sp-amount">${esc(bankMoney(x.amount,cur))}</b>${x.mine?`<button type="button" class="icon-btn small" data-action="split-delete" data-id="${esc(x.id)}" aria-label="Удалить запись">×</button>`:''}</div>`;
}
function friendsSection(){
 const d=state.friends;
 if(!d)return state.friendsError?notice(state.friendsError,true):'';
 if(!d.friends.length)return `<section class="friends-empty" data-ui-key="friends-empty"><span class="empty-orb">${icon('people')}</span><b>Здесь появятся друзья</b><p>Кого вы пригласили и кто пригласил вас. С ними можно делить траты — Platformer посчитает, кто кому сколько должен.</p></section>`;
 const totals={};for(const f of d.friends)for(const [c,v] of Object.entries(f.balance||{}))totals[c]=(totals[c]||0)+v;
 const t=sumIn(totals),cur=state.displayCurrency;
 const sum=Object.keys(totals).length?`<div class="debt-sum ${t.sum>=0?'plus':'minus'}"><small>${t.sum>=0?'Вам должны':'Вы должны'}</small><b>${money(Math.abs(t.sum),cur)}</b></div>`:'';
 return `<section class="friends-block" data-ui-key="friends">${sum}<button type="button" class="split-cta" data-action="split-add"><span class="split-cta-icon">${icon('split')}</span><span class="split-cta-text"><b>Общая трата</b><small>Поделить поровну с друзьями</small></span>${icon('plus')}</button><div class="sec-row"><h2>Ваш круг</h2></div><div class="friend-list">${d.friends.map(friendCard).join('')}</div></section><section class="split-block spend-list" data-ui-key="split"><div class="sec-row"><h2>Общие траты</h2>${d.split.length?`<span class="badge">${d.split.length}</span>`:''}</div>${d.split.length?d.split.map(splitRow).join(''):'<p class="muted">Записали, кто за что платил, — Platformer посчитает, кто кому должен.</p>'}</section>`;
}
async function splitEditor(){
 const d=state.friends;if(!d?.friends.length){toast('Сначала пригласите друзей');return;}
 const people=[{id:d.me,name:'Вы'},...d.friends.filter(f=>!f.former).map(f=>({id:f.id,name:f.name}))],currencies=d.currencies||['USD','EUR','RUB','BYN'];
 let error='',draft={title:'',amount:'',currency:currencies.includes(state.displayCurrency)?state.displayCurrency:'USD',payer:d.me,members:people.map(p=>p.id),day:projectToday()};
 while(true){
  const body=`${error?notice(error,true):''}${field('За что','title','text',draft.title,'required maxlength="80" placeholder="Пицца, такси, дача…" autocomplete="off"')}<div class="field-row">${field('Сумма','amount','text',draft.amount,'required inputmode="decimal" placeholder="0,00" autocomplete="off"')}<label class="field">Валюта<select name="currency">${currencies.map(c=>`<option ${c===draft.currency?'selected':''}>${c}</option>`).join('')}</select></label></div><div class="field-row"><label class="field">Кто платил<select name="payer">${people.map(p=>`<option value="${esc(p.id)}" ${p.id===draft.payer?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label>${field('Когда','day','date',draft.day)}</div><span class="eyebrow">Делим поровну между</span><div class="split-members">${people.map(p=>`<label class="split-member"><input type="checkbox" name="m_${esc(p.id)}" ${draft.members.includes(p.id)?'checked':''}><span class="fc-avatar" style="--h:${hashHue(p.name)}">${friendInitial(p.name)}</span>${esc(p.name)}</label>`).join('')}</div>`;
  const values=await dialog('Общая трата',body,'Записать');if(!values)return;
  draft={...draft,title:values.title,amount:values.amount,currency:values.currency,payer:values.payer,day:values.day,members:people.filter(p=>values['m_'+p.id]==='on').map(p=>p.id)};
  if(preview){toast('В демо-режиме траты не сохраняются');return;}
  try{state.friends=await api('/friends/split',{method:'POST',body:JSON.stringify({title:draft.title,amount:String(draft.amount).replace(/\s/g,'').replace(',','.'),currency:draft.currency,payer:draft.payer,members:draft.members,day:draft.day})});tg?.HapticFeedback?.notificationOccurred('success');toast('Записано');render(true);return;}catch(exc){error=exc.message;}
 }
}
async function settleEditor(friend){
 if(!friend)return;
 const entries=Object.entries(friend.balance||{});if(!entries.length)return;
 let error='',[cur,val]=entries[0];
 while(true){
  const theyOwe=val>0;
  const body=`${error?notice(error,true):''}<p>${theyOwe?`${esc(friend.name)} возвращает вам`:`Вы возвращаете ${esc(friend.name)}`}</p>${entries.length>1?`<label class="field">Валюта<select name="currency">${entries.map(([c])=>`<option ${c===cur?'selected':''}>${c}</option>`).join('')}</select></label>`:`<input type="hidden" name="currency" value="${esc(cur)}">`}${field('Сумма','amount','text',String(Math.abs(val)).replace('.',','),'required inputmode="decimal" autocomplete="off"')}`;
  const values=await dialog('Рассчитаться',body,'Записать возврат');if(!values)return;
  cur=values.currency||cur;val=friend.balance[cur]??val;
  if(preview){toast('В демо-режиме траты не сохраняются');return;}
  const me=state.friends.me,payload={kind:'settle',from:val>0?friend.id:me,to:val>0?me:friend.id,amount:String(values.amount).replace(/\s/g,'').replace(',','.'),currency:cur};
  try{state.friends=await api('/friends/split',{method:'POST',body:JSON.stringify(payload)});toast('Записано');render(true);return;}catch(exc){error=exc.message;}
 }
}
async function friendAction(action,el){
 if(action==='split-add')return splitEditor();
 if(action==='friend-settle')return settleEditor(state.friends?.friends.find(f=>f.id===el.dataset.id));
 if(action==='split-delete'){if(await confirm('Удалить запись?','Долги пересчитаются без неё.','Удалить')){if(preview)return;state.friends=await api('/friends/split/'+el.dataset.id,{method:'DELETE'});render(true);}return;}
}
function previewFriends(){
 const t=projectToday();
 return {me:'1',currencies:['USD','EUR','RUB','BYN'],friends:[
  {id:'2',name:'Лена',balance:{BYN:24.5}},
  {id:'3',name:'Максим',balance:{BYN:-12}},
  {id:'4',name:'Ира',balance:{}}],
  split:[{id:'s1',kind:'expense',title:'Пицца',amount:73.5,currency:'BYN',payer:'1',payer_name:'Вы',members:[{id:'1',name:'Вы'},{id:'2',name:'Лена'},{id:'3',name:'Максим'}],share:24.5,day:t,mine:true},{id:'s2',kind:'expense',title:'Такси',amount:24,currency:'BYN',payer:'3',payer_name:'Максим',members:[{id:'1',name:'Вы'},{id:'3',name:'Максим'}],share:12,day:addDaysIso(t,-2),mine:false}]};
}
// Цвета карт: у известных банков — фирменные, у остальных — свой оттенок по названию
const BANK_BRANDS=[[/альфа|alfa/i,'#ef3124','#8f1015'],[/приор/i,'#f6c500','#a77c00'],[/бнб|bnb/i,'#1fae6c','#0b5c3a'],[/беларусбанк|belarusbank/i,'#1c9a52','#0b4f2a'],[/белагро/i,'#0b8f4a','#044a26'],[/белинвест/i,'#00a3e0','#00557a'],[/белвэб|belveb/i,'#0a6fc2','#063b69'],[/мтб|mtb/i,'#e30613','#6d0309'],[/сбер|sber/i,'#21a038','#0c5a1e'],[/т-банк|т банк|тинькофф|tinkoff|t-bank/i,'#ffdd2d','#2f2f2f'],[/втб|vtb/i,'#1b4fd8','#0a2468'],[/revolut/i,'#2f3542','#0d0f14'],[/wise/i,'#9fe870','#1f4d12'],[/наличн|cash/i,'#6f7f69','#2b3329']];
function hashHue(text){let h=0;for(const ch of String(text||''))h=(h*31+ch.codePointAt(0))%360;return h;}
function bankColors(a){
 const name=a.kind==='cash'?'наличные':a.bank;
 const hit=BANK_BRANDS.find(([re])=>re.test(name));
 const [c1,c2]=hit?[hit[1],hit[2]]:[`hsl(${hashHue(name)} 62% 46%)`,`hsl(${(hashHue(name)+38)%360} 55% 20%)`];
 const light=hit&&/^#(f|9f)/i.test(c1);
 return `--c1:${c1};--c2:${c2};--ink:${light?'#17180f':'#fff'}`;
}
function walletCard(a,i){
 const kind=BANK_KINDS[a.kind]||a.kind_label||'';
 return `<button type="button" class="pcard k-${esc(a.kind)}${a.counted?'':' off'}" style="${bankColors(a)};--i:${i}" data-action="bank-edit" data-id="${esc(a.id)}" aria-label="${esc(`${a.bank}, ${a.title||kind}: ${bankMoney(a.balance,a.currency)}`)}"><span class="pc-shine" aria-hidden="true"></span><span class="pc-top"><b>${esc(a.kind==='cash'?'Наличные':a.bank)}</b><i>${esc(kind)}</i></span>${a.kind==='cash'?'<span class="pc-coins" aria-hidden="true"><i></i><i></i><i></i></span>':'<span class="pc-chip" aria-hidden="true"></span>'}<span class="pc-bal">${esc(bankMoney(a.balance,a.currency))}</span><span class="pc-bottom"><span>${esc(a.title||kind)}</span><span>${a.last4?`•••• ${esc(a.last4)}`:a.source==='sms'?'из SMS':''}</span></span>${a.source==='sms'?'<span class="pc-live" title="Обновляется из SMS"><i></i>авто</span>':''}</button>`;
}
function walletSection(){
 const b=state.banks,accs=b?.accounts||[],t=bankTotal(),inbox=b?.inbox?.length||0;
 const sorted=[...accs].sort((x,y)=>(y.counted-x.counted)||((displayAmount(y.balance,y.currency)||0)-(displayAmount(x.balance,x.currency)||0)));
 const sum=`<a href="#banks" class="wallet-sum bank-summary" data-ui-key="wallet-sum"><span class="ws-main"><small>На счетах</small><b>${!b?'…':accs.length?(t.partial?'—':countUp(t.sum,`money:${state.displayCurrency}`)):'Пока пусто'}</b></span><span class="ws-meta">${accs.length?countLabel(accs.length,['счёт','счёта','счетов']):'Карты, счета, вклады и наличные'}${inbox?` · <em>${inbox} ${inbox%10===1&&inbox%100!==11?'ждёт':'ждут'} подтверждения</em>`:''}${icon('chevron')}</span>${bankStack()}</a>`;
 const cards=b?sorted.map(walletCard).join(''):'';
 return `<section class="wallet" data-ui-key="wallet"><div class="sec-row"><h2>Банки и счета</h2><a class="text-link" href="#banks">Все ${icon('chevron')}</a></div>${sum}<div class="wallet-cards" role="list">${cards}<button type="button" class="pcard add" data-action="bank-add">${icon('plus')}<span>${accs.length?'Добавить':'Добавить карту или счёт'}</span></button></div></section>`;
}
// Обложка проекта: свой рисунок из пятен цвета, посчитанный по id — у каждого проекта он свой
function projectArt(p){
 let seed=0;for(const ch of String(p.id))seed=(seed*33+ch.codePointAt(0))>>>0;
 const rnd=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
 return `<span class="proj-art" aria-hidden="true">${Array.from({length:3},(_,i)=>`<i class="b${i}" style="left:${(30+rnd()*55).toFixed(0)}%;top:${(-30+rnd()*60).toFixed(0)}%;--s:${(110+rnd()*120).toFixed(0)}px;--dx:${(rnd()*30-15).toFixed(0)}px;--dy:${(rnd()*24-12).toFixed(0)}px;--t:${(9+rnd()*8).toFixed(1)}s"></i>`).join('')}</span>`;
}
function projectsView(){
 const cur=state.displayCurrency;
 if(state.projects===null)return `<div class="project-space fin">${header('Финансы','Банки, проекты и TagMarket')}${state.projectsError?empty('Не удалось загрузить проекты',state.projectsError,button('refresh','Попробовать снова')):'<p class="muted">Загружаем…</p>'}</div>`;
 const portfolio=portfolioTotals();
 let daily=0,known=false;for(const p of activeProjects()){const inc=projectDailyIncome(p),v=inc==null||p.calculation_limited?null:displayAmount(inc,p.currency);if(v!=null){daily+=v;known=true;}}
 if(tagStatsOk()&&portfolio.tag!=null){daily+=portfolio.tag*state.tagStats.average_daily_return;known=true;}
 const pay=incomeMonthly();if(pay.sum>0){daily+=pay.sum*12/365;known=true;}
 const projSum=activeProjects().reduce((n,p)=>n+(displayAmount(p.current_total??p.total,p.currency)||0),0);
 const parts=[['Банки',portfolio.banks||0,'banks'],['Проекты',projSum,'projects'],['TagMarket',portfolio.tag||0,'tag']].filter(x=>x[1]>0),whole=parts.reduce((n,x)=>n+x[1],0);
 const alloc=whole>0?`<div class="fin-alloc" role="img" aria-label="Из чего состоят активы">${parts.map(([l,v,k],i)=>`<i class="fa-${k}" style="--w:${(v/whole*100).toFixed(1)}%;--d:${i*120}ms"></i>`).join('')}</div><div class="fin-legend">${parts.map(([l,v,k])=>`<span><i class="fa-${k}"></i>${l} <em>${Math.round(v/whole*100)}%</em></span>`).join('')}</div>`:'';
 const hero=`<div class="page-head sec-hero tone-fin fin-hero" data-ui-key="fin-hero"><div class="sec-glow" aria-hidden="true"><i></i><i></i><i></i></div><div class="fin-main"><span class="sec-eyebrow">Все активы</span><b class="fin-total">${portfolio.own==null?'—':countUp(portfolio.own,`money:${cur}`)}</b><p class="fin-sub"><b class="${daily<0?'negative':'positive'}">${known?`≈ ${money(daily,cur,true)}`:'—'}</b> в день · рабочий капитал <b>${portfolio.working==null?'—':money(portfolio.working,cur)}</b></p></div><a class="button secondary forecast-link" href="#forecast">${icon('chart')}<span>Прогноз</span></a></div>${alloc}`;
 const projects=state.projects.length?`<div class="project-grid">${projectCard({id:'tagmarket-system',name:'TagMarket',total:portfolio.tag,currency:cur,rate_percent:0,period:'month',multi:true,accounts:state.data.accounts,system:true})}${state.projects.map(projectCard).join('')}</div>`:`<div class="project-grid">${projectCard({id:'tagmarket-system',name:'TagMarket',total:portfolio.tag,currency:cur,rate_percent:0,period:'month',multi:true,accounts:state.data.accounts,system:true})}</div><section class="lists-empty fin-empty"><span class="empty-orb">${icon('projects')}</span><b>Добавьте первый проект</b><p>Вклад, инвестиции или любой доход с процентом — Platformer сам посчитает начисления каждый день.</p>${button('project-create','Добавить проект','primary','plus')}</section>`;
 return `<div class="project-space fin">${hero}${state.projectsError?notice('Не удалось обновить проекты. Показаны последние данные.',true):''}${finOnboarding()}${walletSection()}${incomeSection()}${goalsSection()}<section class="fin-projects" data-ui-key="fin-projects"><div class="sec-row"><h2>Проекты</h2>${state.projects.length?`<button type="button" class="text-link head-primary-link" data-action="project-create">${icon('plus')} Проект</button>`:''}</div>${projects}</section>${spendSection()}${projectsDynamics(portfolio)}</div>`;
}
function projectView(){
 const p=state.projects?.find(p=>p.id===state.projectId),back='<a href="#projects" class="button secondary small back">← Проекты</a>';
 if(!p)return `<div class="project-space">${back}${state.projects===null?empty('Загружаем проект',state.projectsError||''):empty('Проект не найден','Возможно, он был удалён.')}</div>`;
 const workTotal=p.accounts.reduce((sum,a)=>sum+(Number(a.working_amount)||0),0),
  accounts=p.accounts.map((a,i)=>{
   const num=a.position||i+1,share=workTotal>0?Math.max(3,(Number(a.working_amount)||0)/workTotal*100):0,
    rate=p.income_mode==='fixed'?'':`${number(projectDailyRate(a.daily_rate_percent!=null?a:{...p,rate_percent:a.rate_percent??p.rate_percent}))}% / день`,
    tags=[a.paused?'<i class="paused">на паузе</i>':'',a.income_starts?`<i class="starts">начисления с ${esc(date(a.income_starts))}</i>`:'',rate&&`<i>${rate}</i>`,a.rate_percent!=null&&p.income_mode!=='fixed'?'<i class="own">своя ставка</i>':'',a.capitalization_active?'<i class="cap">капитализация</i>':'',a.bonus_capitalization?'<i class="cap">капитализация бонуса</i>':'',a.fixed_income?`<i class="fix">фикс. +${projectMoney(a.fixed_income,p.currency)} за ${PROJECT_PERIODS[p.period]}</i>`:'',
     a.bonus_status==='active'?`<i class="bonus">Бонус ${projectMoney(a.bonus_current_amount,p.currency)}${a.bonus_expires_at?` · до ${esc(date(a.bonus_expires_at))}`:''}</i>`:'',
     a.bonus_status==='expired'?`<i class="expired">Бонус завершён${a.bonus_expires_at?` · ${esc(date(a.bonus_expires_at))}`:''}</i>`:''].filter(Boolean).join(''),
    now=a.current_amount!=null&&a.current_amount!==a.amount?` · сейчас ${projectMoney(a.current_amount,p.currency)}`:'';
   return `<button type="button" class="project-account pa-card${a.paused?' is-paused':''}" data-ui-key="project-account-${esc(a.id)}" data-action="project-account-edit" data-id="${esc(p.id)}" data-account="${esc(a.id)}"><span class="pa-top">${p.accounts.length>1?`<span class="pa-grip" role="button" aria-label="Перетащить аккаунт" title="Потяните, чтобы изменить порядок"><svg class="pa-grip-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/></svg></span><span class="project-account-number">${num}</span>`:''}<span class="pa-title"><b>${esc(a.name||`Аккаунт ${i+1}`)}</b><small>Ваши ${projectMoney(a.amount,p.currency)}${now}</small></span><span class="pa-work"><b>${projectMoney(a.working_amount,p.currency)}</b><small>работает</small></span>${icon('chevron')}</span>${p.accounts.length>1?`<span class="pa-bar" aria-hidden="true"><i style="--w:${share.toFixed(1)}%"></i></span>`:''}${tags?`<span class="pa-tags">${tags}</span>`:''}<span class="pa-income">${a.expected_income==null?'—':projectIncome({...p,expected_income:a.expected_income,daily_income:a.daily_income})}</span></button>`;}).join('');
 return `<div class="project-space">${back}${header(p.name,projectRateLabel(p),button('project-pause',p.paused?'Возобновить':'На паузу','secondary','',`data-id="${esc(p.id)}"`)+button('project-edit','Редактировать','secondary','',`data-id="${esc(p.id)}"`))}${state.projectsError?notice('Не удалось обновить проект. Показаны последние данные.',true):''}<section class="panel project-detail-summary" data-ui-key="project-summary-${esc(p.id)}">${projectFinance(p,{detail:true})}</section><section class="panel"><div class="project-accounts-head"><h2>${countLabel(p.accounts.length,['аккаунт','аккаунта','аккаунтов'])}</h2></div>${accounts}${button('project-account-add','Добавить аккаунт','secondary pa-add','plus',`data-id="${esc(p.id)}"`)}</section><div class="actions">${button('project-delete','Удалить проект','danger small','',`data-id="${esc(p.id)}"`)}</div></div>`;
}
// ── Platformer: главная, «Активности» и «Вишлисты» (списки желаний, заметки, календарь) ──
// Показатели здоровья приходят с телефона сами (см. activity.py: автосинхронизация),
// вручную можно добавить или поправить что угодно. Что показывать — настройки пользователя
// на сервере (state.data.station), одинаковые на всех устройствах.
// Шаги, сон и пульс убраны: их должен присылать телефон, а вводить руками — не дело.
const ACT_KINDS={steps:['Шаги','шагов','activity']};   // шаги приходят только с телефона
const ACT_DAYS=[[7,'7 дней'],[30,'30 дней'],[90,'90 дней']];
const NOTE_COLORS=[['accent','Акцент'],['green','Зелёный'],['purple','Сиреневый'],['orange','Оранжевый'],['pink','Розовый'],['blue','Синий']];
const REPEATS=[['none','Не повторять'],['weekly','Каждую неделю'],['monthly','Каждый месяц'],['yearly','Каждый год']];
const MONTH_NAMES=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const HOME_CARDS={circle:'Круг жизни',finance:'Финансы',activity:'Активности',tasks:'Дела на сегодня',events:'Ближайшие события',notes:'Заметки'};
const STATION_DEFAULTS={home:Object.keys(HOME_CARDS),metrics:Object.keys(ACT_KINDS)};
state.activity=null;state.activityError='';state.activityDays=30;
state.lists=null;state.listsError='';state.events=null;state.listsTab='tasks';state.circle=null;
state.calMonth=projectToday().slice(0,7);state.calDay=projectToday();
function stationPrefs(){return {...STATION_DEFAULTS,...(state.data?.station||{})};}
async function saveStationPrefs(patch){
 if(preview){state.data.station={...stationPrefs(),...patch};render();toast('В предпросмотре настройки не сохраняются');return;}
 state.data.station=await api('/preferences/station',{method:'PUT',body:JSON.stringify(patch)});viewCache.clear();render();toast('Настройки сохранены');
}
function addDaysIso(day,n){const d=new Date(Date.parse(`${day}T00:00:00Z`)+n*864e5);return validDate(d)?d.toISOString().slice(0,10):'';}
function monthBounds(month){const [y,m]=month.split('-').map(Number),last=new Date(Date.UTC(y,m,0)).getUTCDate();return [`${month}-01`,`${month}-${String(last).padStart(2,'0')}`];}
function shiftMonth(month,n){const [y,m]=String(month||'').split('-').map(Number),d=new Date(Date.UTC(y,m-1+n,1));return validDate(d)?d.toISOString().slice(0,7):projectToday().slice(0,7);}
function shortDay(day){if(!day)return '';const today=projectToday();if(day===today)return 'Сегодня';if(day===addDaysIso(today,1))return 'Завтра';if(day===addDaysIso(today,-1))return 'Вчера';return fmtDate(new Intl.DateTimeFormat('ru-RU',{weekday:'short',day:'numeric',month:'short',timeZone:'UTC'}),new Date(`${String(day).slice(0,10)}T00:00:00Z`));}
function actValue(kind,value){if(value==null)return '—';const unit=ACT_KINDS[kind]?.[1]||'';return `${number(kind==='steps'?Math.round(value):value)} ${unit}`;}
function sectionError(text,retry){return `<section class="panel">${empty('Не удалось загрузить',text,button(retry,'Попробовать снова','secondary','refresh'))}</section>`;}
function agoText(iso){const at=Date.parse(iso||'');if(!Number.isFinite(at))return '';const min=Math.max(0,Math.round((Date.now()-at)/60000));if(min<1)return 'только что';if(min<60)return `${min} мин назад`;const h=Math.round(min/60);if(h<24)return `${h} ч назад`;return `${shortDay(new Date(at+3*36e5).toISOString().slice(0,10)).toLowerCase()}`;}
function mskMinutes(){const t=new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Europe/Moscow'}).format(new Date()).split(':');return Number(t[0])*60+Number(t[1]);}
function mskHour(){return Number(new Intl.DateTimeFormat('ru-RU',{hour:'numeric',hour12:false,timeZone:'Europe/Moscow'}).format(new Date()));}
// Серия дней подряд с выполненной целью: сегодня ещё не закончился и серию не рвёт

// Числа «набегают» при входе в раздел; при «уменьшить движение» — сразу итог
function countUp(value,format){return `<span class="count-up" data-to="${Number(value)||0}" data-format="${esc(format)}">${esc(formatCount(value,format))}</span>`;}
function formatCount(value,format){const [kind,cur]=String(format).split(':');return kind==='money'?money(value,cur):number(kind==='int'?Math.round(value):Math.round(value*10)/10);}
function animateCounts(){if(reducedMotion())return;document.querySelectorAll('#main .count-up').forEach(el=>{const to=Number(el.dataset.to);if(!to)return;const start=performance.now(),dur=900;const step=now=>{const t=Math.min(1,(now-start)/dur),e=1-Math.pow(1-t,3);el.textContent=formatCount(to*e,el.dataset.format);if(t<1&&el.isConnected)requestAnimationFrame(step);};requestAnimationFrame(step);});}

// Кольцо прогресса и графики без библиотек
function ring(value,goal,size=88,label=''){const r=size/2-7,c=2*Math.PI*r,pct=goal?Math.min(1,(value||0)/goal):0;return `<svg class="ring${pct>=1?' done':''}" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" style="width:${size}px;height:${size}px" role="img" aria-label="${esc(label)}: ${Math.round(pct*100)}%"><circle class="ring-bg" cx="${size/2}" cy="${size/2}" r="${r}"/><circle class="ring-fg" cx="${size/2}" cy="${size/2}" r="${r}" style="--c:${c.toFixed(1)};--o:${(c*(1-pct)).toFixed(1)}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c*(1-pct)).toFixed(1)}"/></svg>`;}
function actBars(series,{goal=null,days=30,kind='steps'}={}){
 const end=projectToday(),points=Array.from({length:days},(_,i)=>{const day=addDaysIso(end,i-days+1);return {day,value:series.find(p=>p.day===day)?.value||0};});
 const max=Math.max(goal||0,...points.map(p=>p.value),1);
 const bars=points.map((p,i)=>`<i class="bar${goal&&p.value>=goal?' hit':''}${p.value?'':' zero'}${p.day===end?' today':''}" style="--h:${(p.value/max*100).toFixed(1)}%;--d:${Math.min(i,60)*12}ms" title="${esc(shortDay(p.day))}: ${esc(actValue(kind,p.value))}"></i>`).join('');
 return `<div class="act-bars${days>45?' dense':''}" role="img" aria-label="${esc(ACT_KINDS[kind]?.[0]||'')} по дням">${goal?`<span class="act-goal" style="--y:${(goal/max*100).toFixed(1)}%"><em>цель ${number(goal)}</em></span>`:''}${bars}</div><div class="act-axis"><span>${esc(shortDay(points[0].day))}</span><span>${esc(shortDay(end))}</span></div>`;
}
// ── Главная ──
function dayIcon(hour){
 if(hour>=6&&hour<19)return `<svg class="sky sun" viewBox="0 0 48 48" aria-hidden="true"><g class="rays">${Array.from({length:8},(_,i)=>`<line x1="24" y1="4" x2="24" y2="9" transform="rotate(${i*45} 24 24)"/>`).join('')}</g><circle cx="24" cy="24" r="9"/></svg>`;
 return `<svg class="sky moon" viewBox="0 0 48 48" aria-hidden="true"><path d="M30 8a16 16 0 1 0 10 28A13 13 0 0 1 30 8z"/><circle class="star s1" cx="10" cy="12" r="1.4"/><circle class="star s2" cx="40" cy="10" r="1.1"/><circle class="star s3" cx="16" cy="40" r="1"/></svg>`;
}
function overview(){
 const d=state.data,p=stationPrefs(),name=(d.user?.name||'').split(' ')[0],portfolio=portfolioTotals(),act=state.activity?.summary,lists=state.lists,hour=mskHour();
 const greeting=hour<5?'Доброй ночи':hour<12?'Доброе утро':hour<18?'Добрый день':'Добрый вечер';
 const today=new Intl.DateTimeFormat('ru-RU',{weekday:'long',day:'numeric',month:'long',timeZone:'Europe/Moscow'}).format(new Date());
 const todayEvents=(lists?.upcoming||[]).filter(e=>e.date===projectToday());
 const hints=[];
 if(todayEvents.length)hints.push(`сегодня ${countLabel(todayEvents.length,['событие','события','событий'])}`);
 const sub=hints.length?hints.join(' · ').replace(/^./,c=>c.toUpperCase()):'Хорошего дня!';
 const openTasks=(lists?.tasks||[]).filter(t=>!t.done),today3=projectToday();
 const dueToday=openTasks.filter(t=>t.due&&t.due<=today3).length;
 const minutes=mskMinutes(),dayPct=Math.round(minutes/14.4)/100;
 const stats=[];
 if(p.home.includes('finance'))stats.push(`<a href="#projects" class="greet-stat"><span class="greet-stat-icon">${icon('projects')}</span><span><b>${portfolio.own==null?'—':countUp(portfolio.own,`money:${state.displayCurrency}`)}</b><small>все активы</small></span></a>`);
 stats.push(`<a href="#plans/tasks" class="greet-stat" data-action="lists-open" data-value="tasks"><span class="greet-stat-icon">${icon('plans')}</span><span><b>${countUp(dueToday,'int')}</b><small>${dueToday?`${countLabel(dueToday,['дело','дела','дел']).split(' ').slice(1).join(' ')} на сегодня`:'дел на сегодня'}</small></span></a>`);
 stats.push(`<a href="#plans/calendar" class="greet-stat" data-action="lists-open" data-value="calendar"><span class="greet-stat-icon">${icon('calendar')}</span><span><b>${countUp(todayEvents.length,'int')}</b><small>${countLabel(todayEvents.length,['событие','события','событий']).split(' ').slice(1).join(' ')} сегодня</small></span></a>`);
 const hero=`<section class="greet" data-ui-key="greet"><div class="greet-aurora" aria-hidden="true"><i></i><i></i><i></i></div><span class="greet-sheen" aria-hidden="true"></span><div class="greet-top"><span class="greet-sky">${dayIcon(hour)}</span><span class="greet-date">${esc(today.charAt(0).toUpperCase()+today.slice(1))}</span></div><h1 class="greet-title">${greeting}${name?`,<br><em>${esc(name)}</em>`:''}</h1><p class="greet-sub">${esc(sub)}</p><div class="greet-day" aria-hidden="true" title="Сколько дня прошло"><i style="--p:${dayPct}"></i></div><div class="greet-stats">${stats.join('')}</div></section>`;
 const cards={
  circle:()=>circleCard(),
  tasks:()=>tasksCard(),
  finance:()=>`<a href="#projects" class="panel home-card home-finance" data-ui-key="home-finance"><div class="home-card-head"><span class="home-icon">${icon('projects')}</span><span class="eyebrow">Финансы</span>${icon('arrow')}</div><b class="home-big">${portfolio.own==null?'—':countUp(portfolio.own,`money:${state.displayCurrency}`)}</b><small>${state.projects?countLabel(activeProjects().length,['проект','проекта','проектов']):'Проекты'}${d.accounts.length?` · TagMarket ${portfolio.tag==null?'—':money(portfolio.tag,state.displayCurrency)}`:''}</small>${projectsIncomeLine()}</a>`,
  activity:()=>`<a href="#activity" class="panel home-card home-activity" data-ui-key="home-activity"><div class="home-card-head"><span class="home-icon">${icon('activity')}</span><span class="eyebrow">Шаги</span>${icon('arrow')}</div>${act?(stepsLive()?`<div class="home-steps">${ring(act.steps.today||0,state.activity?.goals?.steps||10000,74,'Шаги')}<div><b class="home-big">${countUp(act.steps.today||0,'int')} <small>шагов</small></b><small><i class="live-tag"><i></i>${esc(agoText(state.activity?.sync?.last_sync)||'с телефона')}</i></small></div></div>`:`<small class="steps-off-line">${esc(stepsNote())}</small>`):state.activityError?'<small>Не удалось загрузить</small>':skeleton('list',1)}</a>`,
  events:()=>{const upcoming=lists?.upcoming||[];return `<section class="panel home-card home-events" data-ui-key="home-events"><div class="home-card-head"><span class="home-icon">${icon('calendar')}</span><span class="eyebrow">Ближайшее</span><button type="button" class="icon-btn small" data-action="event-add" aria-label="Добавить событие">${icon('plus')}</button></div>${upcoming.length?`<ul class="home-events-list">${upcoming.map(e=>`<li><button type="button" data-action="lists-open" data-value="calendar" data-day="${esc(e.date)}"><span class="ev-dot c-${esc(e.color)}"></span><b>${esc(e.title)}</b><small>${esc(shortDay(e.date))}${e.time?` · ${esc(e.time)}`:''}</small></button></li>`).join('')}</ul>`:'<p class="muted home-empty">На ближайшие две недели ничего не запланировано.</p>'}</section>`;},
  notes:()=>{const all=lists?.notes||[],pinned=all.filter(n=>n.pinned).slice(0,3);return `<a href="#plans/notes" class="panel home-card home-wish" data-ui-key="home-notes" data-action="lists-open" data-value="notes"><div class="home-card-head"><span class="home-icon">${icon('note')}</span><span class="eyebrow">Заметки</span>${icon('arrow')}</div><b class="home-big">${all.length} <small>${countLabel(all.length,['заметка','заметки','заметок']).split(' ').slice(1).join(' ')}</small></b>${pinned.length?`<span class="home-notes">${pinned.map(n=>`<i class="c-${esc(n.color)}">${esc(n.title||n.body.slice(0,60))}</i>`).join('')}</span>`:'<small>Идеи и списки — всё под рукой</small>'}</a>`;}};
 const grid=p.home.filter(id=>cards[id]).map(id=>cards[id]()).join('');
 return `<div class="home">${hero}${grid?`<div class="home-grid">${grid}</div>`:''}</div>`;
}
function projectsIncomeLine(){const cur=state.displayCurrency;let daily=0,known=false;for(const p of activeProjects()){const inc=projectDailyIncome(p),v=inc==null||p.calculation_limited?null:displayAmount(inc,p.currency);if(v!=null){daily+=v;known=true;}}return known&&daily?`<small class="positive">≈ ${money(daily,cur,true)} в день по проектам</small>`:'';}
function stepsLive(){const st=state.activity?.summary?.steps;return !!st&&(st.series||[]).length>0;}
function stepsNote(){const sync=state.activity?.sync,p=String(tg?.platform||'').toLowerCase();
 if(sync?.connected&&!sync.last_sync)return 'Ждём шаги с телефона';
 return /tdesktop|macos|web|unigram/.test(p)?'На компьютере шаги не обновляются':'На вашем устройстве шаги не обновляются автоматически';}
function syncDot(){const s=state.activity?.sync;if(!s?.connected)return '';const fresh=s.last_sync&&Date.now()-Date.parse(s.last_sync)<36*36e5;return `<span class="sync-dot${fresh?' on':''}" title="${fresh?`Синхронизировано ${esc(agoText(s.last_sync))}`:'Ждём синхронизацию с телефона'}"></span>`;}

// ── Активности ──
function activityView(){
 const sum=state.activity?.summary,st=sum?.steps;
 const line=!sum?'Шаги с телефона':stepsLive()?`${number(st.today||0)} шагов сегодня`:stepsNote();
 const head=secHero('act','Шаги',esc(line));
 if(!state.activity)return head+(state.activityError?sectionError(state.activityError,'activity-reload'):skeleton('chart'));
 const a=state.activity,days=a.days,g0=a.goals?.steps||10000;
 if(!stepsLive())return head+`<section class="steps-empty"><span class="empty-orb">${icon('activity')}</span><b>Шаги появятся сами</b><p>${esc(stepsNote())}. Когда приложение получит данные с телефона, здесь будут шаги за сегодня и динамика по дням.</p></section>`;
 const tabs=`<div class="segmented act-days">${ACT_DAYS.map(([n,label])=>`<button type="button" data-action="activity-days" data-value="${n}" class="${state.activityDays===n?'active':''}">${label}</button>`).join('')}</div>`;
 const pct=Math.min(100,Math.round((st.today||0)/g0*100));
 const hero=`<section class="steps-hero${pct>=100?' done':''}" data-ui-key="steps-hero"><span class="steps-glow" aria-hidden="true"></span><span class="steps-ring">${ring(st.today||0,g0,132,'Шаги')}<span class="steps-ring-in"><b>${countUp(st.today||0,'int')}</b><small>из ${number(g0)}</small></span></span><span class="steps-meta"><i class="live-tag"><i></i>${esc(agoText(a.sync?.last_sync)||'с телефона')}</i>${st.week_avg!=null?`<small>в среднем ${number(Math.round(st.week_avg))} в день</small>`:''}<small>${pct>=100?'Цель выполнена':`${pct}% дневной цели`}</small></span></section>`;
 const chart=st.series.length>1?`<section class="act-chart" data-ui-key="act-chart-steps"><div class="sec-row"><h2>По дням</h2>${tabs}</div>${actBars(st.series,{goal:g0,days,kind:'steps'})}</section>`:'';
 return head+hero+chart;
}
async function ensureActivity(){if(!state.activity)state.activity=preview?previewActivity(7):await api('/activity?days=7');}
let syncKeyShown=null;
function syncGuide(link,mode='bank'){
 if(mode==='steps')return `<div class="sync-link"><span class="eyebrow">Ссылка для HC Webhook</span>${link?`<code class="sync-code">${esc(link)}</code><div class="inline-actions">${button('copy','Скопировать ссылку','secondary small','copy',`data-text="${esc(link)}"`)}</div><small class="muted">Личный ключ — не показывайте его другим.</small>`:`<p class="muted">Ссылка показывается один раз. Новая отключит прежнюю — и для шагов, и для SMS банка.</p>${button('sync-key-create','Создать новую ссылку','secondary small','refresh','data-mode="steps"')}`}</div>`;
 const sample=`{"text": "Карта *1234: Покупка 25,40 BYN, остаток 1 340,10 BYN"}`;
 const ios=`<li>Откройте <b>Команды</b> → <b>Автоматизация</b> → <b>+</b> → <b>Сообщение</b>. В «Сообщение содержит» укажите слово из SMS банка, например <b>остаток</b> или название банка, и выберите «Запускать сразу».</li><li>Добавьте действие <b>«Получить содержимое URL»</b>: ссылка ниже, метод <b>POST</b>, тело — JSON, поле <code>text</code> = <b>«Содержимое сообщения»</b>.</li><li>Готово: каждое SMS от банка обновит баланс. Сообщения, которые Platformer не понял, будут ждать вас в «Банках и счетах».</li><li>Пуши из приложения банка iPhone автоматизациям не отдаёт — работают только SMS. Включите SMS-уведомления в банке.</li>`;
 const android=`<li>Нужен автоматизатор с событиями <b>SMS</b> и <b>уведомлений</b> и отправкой HTTP-запроса — Tasker или MacroDroid.</li><li>Событие: «SMS получено» от отправителя-банка (или «Уведомление» от приложения банка).</li><li>Действие: <b>HTTP POST</b> на ссылку ниже, тело JSON с полем <code>text</code> — текст сообщения (в Tasker это %SMSRB, в MacroDroid — {sms_message}).</li><li>Баланс счёта обновится сам, а непонятные сообщения подождут вас в приложении.</li>`;
 return `<div class="sync-tabs segmented"><button type="button" class="active" data-sync-os="ios">iPhone</button><button type="button" data-sync-os="android">Android</button></div>
 <ol class="sync-steps" data-sync-guide="ios">${ios}</ol>
 <ol class="sync-steps" data-sync-guide="android" hidden>${android}</ol>
 <div class="sync-link"><span class="eyebrow">Ваша ссылка</span>${link?`<code class="sync-code">${esc(link)}</code><div class="inline-actions">${button('copy','Скопировать ссылку','secondary small','copy',`data-text="${esc(link)}"`)}</div><small class="muted">Это личный ключ: не показывайте его другим. Он виден только сейчас — потеряете, просто создайте новый.</small>`:`<p class="muted">Ссылка с ключом показывается один раз при создании. Новая ссылка отключает прежнюю — её придётся поставить во всех автоматизациях.</p>${button('sync-key-create','Создать новую ссылку','secondary small','refresh','data-mode="bank"')}`}</div>
 <details class="sync-more"><summary>Формат данных</summary><p>JSON или форма с полем text (или message, sms, body) — текст сообщения банка целиком.</p><code class="sync-code">${esc(sample)}</code></details>`;
}
async function activitySync(mode='bank'){
 mode=mode==='steps'?'steps':'bank';
 if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;
 await ensureActivity();
 let status=state.activity?.sync||{connected:false};
 if(!status.connected&&!syncKeyShown){
  if(preview){syncKeyShown={url:new URL('../api/activity/sync',location.href).href,key:'preview-key-preview-key'};}
  else{const made=await api('/activity/sync/key',{method:'POST'});syncKeyShown=made;status=made;}
 }
 const base=syncKeyShown?(mode==='steps'?syncKeyShown.url:syncKeyShown.url.replace('/activity/sync','/banks/sync')):'',link=syncKeyShown?`${base}?key=${encodeURIComponent(syncKeyShown.key)}`:'';
 const head=status.connected?`<div class="sync-status on">${icon('check')}<span><b>Подключено</b><small>${status.last_sync?`Последняя синхронизация ${esc(agoText(status.last_sync))}${status.last_saved?` · ${esc(status.last_saved)}`:''}`:'Ждём первую отправку с телефона'}</small></span></div>`:'';
 await dialog(mode==='steps'?'Шаги с телефона':'Обновление из SMS банка',`<div class="sync-dialog">${head}<p class="pref-hint">${mode==='steps'?'Шаги приходят сами из HC Webhook на телефоне.':'Platformer не заходит в банк и не хранит пароли. Банк присылает SMS — телефон пересылает текст сюда, а Platformer сам вытаскивает остаток и сумму.'}</p>${syncGuide(link,mode)}${status.connected?`<div class="guest-danger">${button('sync-key-delete','Отключить синхронизацию','danger small')}</div>`:''}</div>`,'Готово');
 await sectionReload();
}
document.addEventListener('click',event=>{const tab=event.target.closest?.('[data-sync-os]');if(!tab)return;event.preventDefault();const box=tab.closest('.sync-dialog');box.querySelectorAll('[data-sync-os]').forEach(b=>b.classList.toggle('active',b===tab));box.querySelectorAll('[data-sync-guide]').forEach(g=>g.hidden=g.dataset.syncGuide!==tab.dataset.syncOs);});

// ── Вишлисты, заметки, календарь ──
const PLAN_TABS=[['tasks','Задачи','check'],['calendar','Календарь','calendar'],['notes','Заметки','note']];
const PLAN_ADD={tasks:['task-add','Новая задача'],calendar:['event-add','Новое событие'],notes:['note-add','Новая заметка']};
function listsView(){
 const tab=state.listsTab,L=state.lists,today=projectToday();
 const open=(L?.tasks||[]).filter(t=>!t.done),dueNow=open.filter(t=>t.due&&t.due<=today).length,eventsNow=(L?.upcoming||[]).filter(e=>e.date===today).length;
 const counts={tasks:open.length,calendar:(L?.upcoming||[]).length,notes:(L?.notes||[]).length};
 const day=new Intl.DateTimeFormat('ru-RU',{weekday:'long',day:'numeric',month:'long',timeZone:'Europe/Moscow'}).format(new Date());
 const line=!L?'':[dueNow?`${countLabel(dueNow,['дело','дела','дел'])} на сегодня`:'На сегодня дел нет',eventsNow?countLabel(eventsNow,['событие','события','событий']):''].filter(Boolean).join(' · ');
 const [addAction,addLabel]=PLAN_ADD[tab]||PLAN_ADD.tasks;
 const actions=`<div class="head-actions">${tab==='notes'?button('note-import','Импорт','secondary','upload','aria-label="Импортировать заметки с телефона"'):''}${button(addAction,addLabel,'primary head-primary','plus')}</div>`;
 const hero=`<div class="page-head plans-hero" data-ui-key="plans-hero"><div class="plans-glow" aria-hidden="true"><i></i><i></i><i></i></div><div><span class="plans-date">${esc(day.charAt(0).toUpperCase()+day.slice(1))}</span><h1>Планы</h1>${line?`<p>${esc(line)}</p>`:''}</div>${actions}</div>`;
 const tabs=`<div class="plan-tabs lists-tabs" role="tablist" aria-label="Разделы планов">${PLAN_TABS.map(([id,label,ico])=>`<button type="button" role="tab" aria-selected="${tab===id}" data-action="lists-tab" data-value="${id}" class="${tab===id?'active':''}"><span class="pt-icon">${icon(ico)}</span><span class="pt-label">${label}</span>${L&&counts[id]?`<i class="pt-count">${counts[id]}</i>`:''}</button>`).join('')}</div>`;
 if(!L)return `<div class="plans">${hero}${tabs}${state.listsError?sectionError(state.listsError,'lists-reload'):skeleton('list')}</div>`;
 return `<div class="plans plans-${tab}">${hero}${tabs}<div class="lists-pane fade-swap">${tab==='notes'?notesTab():tab==='calendar'?calendarTab():tasksTab()}</div></div>`;
}
// ── Задачи ──
function dueLabel(due){if(!due)return '';const t=projectToday();return due===t?'Сегодня':due===addDaysIso(t,1)?'Завтра':due===addDaysIso(t,-1)?'Вчера':shortDay(due);}
function taskRow(t,areas){return `<li class="task a-${esc(t.area)}${t.done?' done':''}" data-ui-key="task-${esc(t.id)}"><button type="button" class="wish-check" data-action="task-toggle" data-id="${esc(t.id)}" aria-label="${t.done?'Вернуть в работу':'Отметить выполненной'}" aria-pressed="${t.done}">${icon('check')}</button><button type="button" class="wish-title" data-action="task-edit" data-id="${esc(t.id)}"><b>${esc(t.title)}</b><small><i class="area-chip a-${esc(t.area)}">${esc(areas[t.area]||t.area)}</i>${t.note?`<span class="task-note">${esc(t.note)}</span>`:''}</small></button>${t.due?`<span class="due${!t.done&&t.due<projectToday()?' late':''}">${esc(dueLabel(t.due))}</span>`:''}</li>`;}
function tasksTab(){
 const tasks=state.lists.tasks||[],areas=state.lists.areas||{},today=projectToday(),soonEnd=addDaysIso(today,7);
 const open=tasks.filter(t=>!t.done),done=tasks.filter(t=>t.done);
 const groups=[['Просрочено',open.filter(t=>t.due&&t.due<today),'late'],['Сегодня',open.filter(t=>t.due===today),'today'],['На этой неделе',open.filter(t=>t.due&&t.due>today&&t.due<=soonEnd),'week'],['Позже',open.filter(t=>t.due&&t.due>soonEnd),'later'],['Без срока',open.filter(t=>!t.due),'nodue']].filter(g=>g[1].length);
 const quick=`<form class="task-quick" data-task-quick><span class="tq-icon" aria-hidden="true">${icon('plus')}</span><input name="title" maxlength="200" placeholder="Добавить задачу…" aria-label="Новая задача" autocomplete="off" enterkeyhint="done"><button type="submit" class="tq-send" aria-label="Добавить задачу">${icon('arrow')}</button></form>`;
 if(!tasks.length)return quick+`<section class="lists-empty"><span class="empty-orb">${icon('plans')}</span><b>Дел пока нет</b><p>Напишите первую задачу выше. Срок и сферу можно добавить потом.</p></section>`;
 const late=open.filter(t=>t.due&&t.due<today).length,doneToday=done.filter(t=>String(t.done_at||'').slice(0,10)===today).length,todayOpen=open.filter(t=>t.due===today).length,todayAll=todayOpen+doneToday;
 const pct=todayAll?doneToday/todayAll:0,R=26,C=2*Math.PI*R;
 const summary=`<div class="task-summary" data-ui-key="task-summary"><span class="ts-ring" aria-hidden="true"><svg viewBox="0 0 64 64"><circle class="ts-track" cx="32" cy="32" r="${R}"/>${pct>0?`<circle class="ts-fill" cx="32" cy="32" r="${R}" stroke-dasharray="${(C*pct).toFixed(1)} ${C.toFixed(1)}" style="--c:${C.toFixed(1)}"/>`:''}</svg><b>${todayAll?Math.round(pct*100)+'%':'—'}</b></span><span class="ts-text"><b>${todayAll?`Сегодня ${doneToday} из ${todayAll}`:'Сегодня без сроков'}</b><small>${countLabel(open.length,['открытое дело','открытых дела','открытых дел'])}${late?` · <em class="late">${late} просрочено</em>`:''}</small></span></div>`;
 return quick+summary+groups.map(([title,list,cls])=>`<section class="task-group ${cls}" data-ui-key="tasks-${esc(title)}"><h2 class="tg-head"><i class="tg-dot" aria-hidden="true"></i>${title}<span class="tg-count">${list.length}</span></h2><ul class="task-list">${list.map(t=>taskRow(t,areas)).join('')}</ul></section>`).join('')+(done.length?`<details class="task-group done-group" data-ui-key="tasks-done"><summary class="tg-head"><i class="tg-dot" aria-hidden="true"></i>Выполнено<span class="tg-count">${done.length}</span>${icon('chevron','tg-chevron')}</summary><ul class="task-list">${done.map(t=>taskRow(t,areas)).join('')}</ul></details>`:'');
}
async function taskEditor(task=null){
 const areas=state.lists?.areas||{personal:'Личное',work:'Работа',home:'Дом',study:'Учёба'};
 let error='',draft=task||{title:'',note:'',due:'',area:'personal'};
 while(true){
  const body=`${error?notice(error,true):''}${field('Что нужно сделать','title','text',draft.title,'required maxlength="200"')}<div class="field-row">${field('Срок','due','date',draft.due||'','')}<label class="field">Сфера<select name="area">${Object.entries(areas).map(([id,label])=>`<option value="${id}" ${id===draft.area?'selected':''}>${esc(label)}</option>`).join('')}</select></label></div><div class="due-chips" role="group" aria-label="Быстрый срок">${[['Сегодня',0],['Завтра',1],['Через неделю',7]].map(([l,n])=>`<button type="button" class="home-chip" data-due-set="${addDaysIso(projectToday(),n)}">${l}</button>`).join('')}<button type="button" class="home-chip" data-due-set="">Без срока</button></div>${field('Заметка (необязательно)','note','text',draft.note||'','maxlength="2000"')}${task?`<div class="guest-danger">${button('task-delete','Удалить задачу','danger small','',`data-id="${esc(task.id)}"`)}</div>`:''}`;
  const values=await dialog(task?'Задача':'Новая задача',body);if(!values)return;
  draft={title:values.title,due:values.due||null,area:values.area||'personal',note:values.note||''};
  try{await api('/tasks'+(task?'/'+task.id:''),{method:task?'PATCH':'POST',body:JSON.stringify(draft)});tg?.HapticFeedback?.notificationOccurred('success');toast('Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
document.addEventListener('click',event=>{const chip=event.target.closest?.('[data-due-set]');if(!chip)return;event.preventDefault();const input=$('#dialog input[name="due"]');if(input){input.value=chip.dataset.dueSet;input.dispatchEvent(new Event('input',{bubbles:true}));$('#dialog').dataset.dirty='1';}});
document.addEventListener('submit',async event=>{const form=event.target.closest?.('[data-task-quick]');if(!form)return;event.preventDefault();const input=form.elements.title,title=input.value.trim();if(!title)return;input.disabled=true;try{await api('/tasks',{method:'POST',body:JSON.stringify({title})});tg?.HapticFeedback?.impactOccurred('light');await sectionReload();$('[data-task-quick] input')?.focus();}catch(error){toast(error.message);input.disabled=false;}});
// ── Импорт заметок с телефона: файлы (.txt, .md, Google Keep .json/.html) или вставленный текст ──
const NOTE_FILES='.txt,.md,.markdown,.json,.html,.htm,text/plain,text/markdown,application/json,text/html';
function noteFromText(text,name=''){
 const clean=String(text||'').replace(/\r\n?/g,'\n').trim();if(!clean)return null;
 const lines=clean.split('\n'),first=lines[0].replace(/^#+\s*/,'').trim(),base=name.replace(/\.[^.]+$/,'').trim();
 if(base&&!/^(note|notes|заметка|заметки|untitled|без названия|новая заметка)[\s_-]*\d*$/i.test(base))return {title:base.slice(0,120),body:clean};
 return lines.length>1&&first.length<=120?{title:first,body:lines.slice(1).join('\n').trim()}:{title:'',body:clean};
}
function notesFromJson(data){
 const list=Array.isArray(data)?data:Array.isArray(data?.notes)?data.notes:[data];
 return list.filter(n=>n&&typeof n==='object'&&!n.isTrashed).map(n=>{
  const checks=Array.isArray(n.listContent)?n.listContent.map(i=>`${i.isChecked?'☑':'☐'} ${i.text||''}`).join('\n'):'';
  const body=String(n.textContent??n.body??n.text??n.content??'').trim();
  return {title:String(n.title||'').trim().slice(0,120),body:[body,checks].filter(Boolean).join('\n')};
 });
}
function noteFromHtml(html,name){
 const doc=new DOMParser().parseFromString(html,'text/html');doc.querySelectorAll('script,style,head').forEach(e=>e.remove());
 const title=(doc.querySelector('.title')?.textContent||'').trim(),content=doc.querySelector('.content')||doc.body;if(!content)return null;
 content.querySelectorAll('br').forEach(b=>b.replaceWith('\n'));content.querySelectorAll('p,div,li,h1,h2,h3').forEach(b=>b.append('\n'));
 const body=(content.textContent||'').replace(/[ \t]+\n/g,'\n').replace(/\n{3,}/g,'\n\n').trim();
 return title?{title:title.slice(0,120),body}:noteFromText(body,name);
}
async function notesFromFiles(files){
 const out=[];
 for(const f of files){const text=await f.text(),n=f.name.toLowerCase();
  if(n.endsWith('.json')||f.type==='application/json'){try{out.push(...notesFromJson(JSON.parse(text)));continue;}catch{}}
  out.push(/\.html?$/.test(n)||f.type==='text/html'?noteFromHtml(text,f.name):noteFromText(text,f.name));}
 return out.filter(x=>x&&(x.title||x.body));
}
function notesFromPaste(text){return String(text||'').replace(/\r\n?/g,'\n').split(/\n[ \t]*(?:-{3,}|={3,})[ \t]*\n/).map(c=>noteFromText(c)).filter(Boolean);}
async function notesImport(){
 let picked=[];
 const body=`<p class="pref-hint">Перенесите заметки с телефона одним движением. Те, что уже есть, второй раз не появятся.</p>
 <label class="note-drop"><input type="file" name="files" multiple accept="${NOTE_FILES}"><span class="note-drop-icon">${icon('upload')}</span><b data-note-pick>Выбрать файлы</b><small>.txt, .md, Google Keep (.json, .html)</small></label>
 <label class="field">Или вставьте текст<textarea name="text" placeholder="Скопируйте заметку и вставьте сюда. Несколько — разделите строкой ---"></textarea></label>
 <p class="note-import-count" data-note-count aria-live="polite"></p>
 <details class="sync-more"><summary>Как выгрузить с телефона</summary><p><b>iPhone, «Заметки»:</b> откройте заметку → «Поделиться» → «Скопировать» и вставьте сюда. Файлы .txt и .md из приложения «Файлы» тоже подойдут — можно выбрать сразу несколько.</p><p><b>Android, Google Keep:</b> на takeout.google.com выберите только Keep, скачайте архив, распакуйте и выберите здесь файлы .json (или .html).</p><p><b>Samsung Notes и другие:</b> «Поделиться» → «Текстовый файл» или скопируйте текст.</p></details>`;
 const count=async d=>{const text=d.querySelector('textarea[name="text"]').value,n=(await notesFromFiles(picked)).length+notesFromPaste(text).length,el=d.querySelector('[data-note-count]');el.textContent=n?`Найдено ${countLabel(n,['заметка','заметки','заметок'])}`:'';el.classList.toggle('on',n>0);};
 const values=await dialog('Импорт заметок',body,'Импортировать',{onOpen:d=>{const input=d.querySelector('input[name="files"]'),label=d.querySelector('[data-note-pick]');input.addEventListener('change',()=>{picked=[...input.files];label.textContent=picked.length?countLabel(picked.length,['файл','файла','файлов']):'Выбрать файлы';d.dataset.dirty=picked.length?'1':'';count(d);});d.querySelector('textarea[name="text"]').addEventListener('input',()=>count(d));}});
 if(!values)return;
 const notes=[...await notesFromFiles(picked),...notesFromPaste(values.text)];
 if(!notes.length){toast('Не нашли заметок — выберите файлы или вставьте текст');return;}
 try{
  let result;
  if(preview){const have=new Set(state.lists.notes.map(n=>n.title+'\n'+n.body)),stamp=new Date().toISOString(),fresh=notes.filter(n=>!have.has(n.title+'\n'+n.body));state.lists.notes=[...fresh.map((n,i)=>({id:'imp'+Date.now()+i,title:n.title,body:n.body,pinned:false,color:'accent',created_at:stamp,updated_at:stamp})),...state.lists.notes];result={imported:fresh.length,skipped:notes.length-fresh.length};}
  else{result=await api('/notes/import',{method:'POST',body:JSON.stringify({notes:notes.slice(0,500)})});state.lists.notes=result.notes;}
  tg?.HapticFeedback?.notificationOccurred('success');
  toast(result.imported?`Импортировано: ${countLabel(result.imported,['заметка','заметки','заметок'])}${result.skipped?` · ${result.skipped} уже были`:''}`:'Все эти заметки уже есть');
  state.listsTab='notes';render();
 }catch(exc){toast(exc.message);}
}
function notesTab(){
 const notes=state.lists.notes;
 if(!notes.length)return `<section class="lists-empty"><span class="empty-orb">${icon('note')}</span><b>Заметок пока нет</b><p>Идеи, списки покупок, мысли — всё в одном месте. Важное можно закрепить сверху.</p>${button('note-add','Новая заметка','primary','plus')}${button('note-import','Импортировать с телефона','ghost small','upload')}</section>`;
 return `<div class="notes-grid">${notes.map((n,k)=>`<button type="button" class="note-card c-${esc(n.color)}${n.pinned?' pinned':''}" style="--k:${k}" data-action="note-edit" data-id="${esc(n.id)}" data-ui-key="note-${esc(n.id)}">${n.pinned?`<span class="note-pin">📌 Закреплено</span>`:''}${n.title?`<b>${esc(n.title)}</b>`:''}${n.body?`<p>${esc(n.body.length>320?n.body.slice(0,320)+'…':n.body)}</p>`:''}<small>${esc(date(n.updated_at))}</small></button>`).join('')}</div>`;
}
function calendarTab(){
 const month=state.calMonth,[first]=monthBounds(month),[y,m]=month.split('-').map(Number),days=new Date(Date.UTC(y,m,0)).getUTCDate(),lead=(new Date(`${first}T00:00:00Z`).getUTCDay()+6)%7,today=projectToday();
 const events=state.events?.events||[],byDay={};for(const e of events)(byDay[e.date]=byDay[e.date]||[]).push(e);
 const cells=[...Array(lead).fill('<span class="cal-cell empty"></span>'),...Array.from({length:days},(_,i)=>{const day=`${month}-${String(i+1).padStart(2,'0')}`,list=byDay[day]||[],weekend=(lead+i)%7>=5;return `<button type="button" class="cal-cell${day===today?' today':''}${day===state.calDay?' selected':''}${weekend?' weekend':''}" data-action="cal-day" data-value="${day}" aria-label="${esc(shortDay(day))}${list.length?`, событий: ${list.length}`:''}"><b>${i+1}</b><span class="cal-dots">${list.slice(0,3).map(e=>`<i class="c-${esc(e.color)}"></i>`).join('')}</span></button>`;})].join('');
 const chosen=byDay[state.calDay]||[];
 const list=chosen.length?`<div class="cal-timeline">${chosen.map(e=>`<button type="button" class="cal-event c-${esc(e.color)}" data-action="event-edit" data-id="${esc(e.id)}"><span class="ce-time">${e.time?esc(e.time):'весь<br>день'}</span><span class="ce-bar" aria-hidden="true"></span><span class="ce-body"><b>${esc(e.title)}</b>${e.repeat!=='none'||e.note?`<small>${e.repeat!=='none'?esc(REPEATS.find(r=>r[0]===e.repeat)?.[1]||''):''}${e.repeat!=='none'&&e.note?' · ':''}${e.note?esc(e.note):''}</small>`:''}</span>${icon('chevron')}</button>`).join('')}</div>`:'<p class="cal-free">Свободный день — ничего не запланировано.</p>';
 return `<section class="calendar" data-ui-key="calendar"><div class="cal-head"><button type="button" class="icon-btn" data-action="cal-month" data-value="-1" aria-label="Предыдущий месяц">‹</button><h2>${MONTH_NAMES[m-1]} <span>${y}</span></h2><button type="button" class="icon-btn" data-action="cal-month" data-value="1" aria-label="Следующий месяц">›</button></div><div class="cal-week">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(d=>`<span>${d}</span>`).join('')}</div><div class="cal-grid">${cells}</div>${month!==today.slice(0,7)?`<button type="button" class="text-link cal-today" data-action="cal-today">Вернуться к сегодня</button>`:''}</section><section class="cal-day-panel"><div class="cdp-head"><h2>${esc(shortDay(state.calDay))}</h2><button type="button" class="cdp-add" data-action="event-add" data-day="${esc(state.calDay)}" aria-label="Добавить событие на этот день">${icon('plus')}</button></div>${list}</section>`;
}
function colorPicker(current){return `<div class="note-colors" role="radiogroup" aria-label="Цвет">${NOTE_COLORS.map(([id,label])=>`<label class="note-color c-${id}" title="${label}"><input type="radio" name="color" value="${id}" ${id===current?'checked':''} aria-label="${label}"><i></i></label>`).join('')}</div>`;}
async function noteEditor(note=null){
 let error='',draft=note||{title:'',body:'',pinned:false,color:'accent'};
 while(true){
  const body=`${error?notice(error,true):''}${field('Заголовок','title','text',draft.title,'maxlength="120"')}<label class="field">Текст<textarea name="body" rows="8" maxlength="20000">${esc(draft.body)}</textarea></label>${colorPicker(draft.color)}<label class="check"><input type="checkbox" name="pinned" ${draft.pinned?'checked':''}>Закрепить сверху</label>${note?`<div class="guest-danger">${button('note-delete','Удалить заметку','danger small','',`data-id="${esc(note.id)}"`)}</div>`:''}`;
  const values=await dialog(note?'Заметка':'Новая заметка',body);if(!values)return;
  draft={title:values.title||'',body:values.body||'',pinned:values.pinned==='on',color:values.color||'accent'};
  try{await api('/notes'+(note?'/'+note.id:''),{method:note?'PATCH':'POST',body:JSON.stringify(draft)});toast('Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
async function eventEditor(item=null,day=state.calDay||projectToday()){
 let error='',draft=item?{...item,day:item.original_day||item.day}:{day,time:'',title:'',note:'',color:'accent',repeat:'none'};
 while(true){
  const body=`${error?notice(error,true):''}${field('Что','title','text',draft.title,'required maxlength="120" placeholder="День рождения, встреча, оплата…"')}<div class="field-row">${field('Дата','day','date',draft.day,'required')}${field('Время','time','time',draft.time||'','')}</div><label class="field">Повтор<select name="repeat">${REPEATS.map(([id,label])=>`<option value="${id}" ${id===draft.repeat?'selected':''}>${label}</option>`).join('')}</select></label>${field('Заметка (необязательно)','note','text',draft.note||'','maxlength="2000"')}${colorPicker(draft.color)}${item?`<div class="guest-danger">${button('event-delete','Удалить событие','danger small','',`data-id="${esc(item.id)}"`)}</div>`:''}`;
  const values=await dialog(item?'Событие':'Новое событие',body);if(!values)return;
  draft={day:values.day,time:values.time||null,title:values.title,note:values.note||'',color:values.color||'accent',repeat:values.repeat||'none'};
  try{await api('/events'+(item?'/'+item.id:''),{method:item?'PATCH':'POST',body:JSON.stringify(draft)});state.calDay=draft.day;state.calMonth=draft.day.slice(0,7);toast('Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
// Данные раздела после изменения: тот же набор, что грузит переход в раздел
async function sectionReload(){const key=viewKey(),[parts,circle]=await Promise.all([viewParts(),preview?Promise.resolve(null):api('/insights').catch(()=>null)]);if(key!==viewKey())return;Object.assign(state,parts);if(circle)state.circle=circle;remember();render();}
async function closeDialogFirst(){return !$('#dialog').open||await requestDialogExit($('#dialog'));}
async function sectionAction(action,el){
 if(action==='activity-sync')return activitySync('steps');
  if(action==='activity-reload'||action==='lists-reload')return sectionReload();
 if(action==='activity-days'){state.activityDays=Number(el.dataset.value)||30;markChoice(el);return sectionReload();}
 if(action==='lists-tab'){state.listsTab=el.dataset.value;markChoice(el);render();return;}
 if(action==='task-add')return taskEditor();
 if(action==='task-edit')return taskEditor(state.lists?.tasks.find(t=>t.id===el.dataset.id));
 if(action==='task-toggle'){const t=state.lists?.tasks.find(x=>x.id===el.dataset.id);if(!t)return;el.closest('li')?.classList.toggle('done');await api('/tasks/'+t.id,{method:'PATCH',body:JSON.stringify({done:!t.done})});if(!t.done)tg?.HapticFeedback?.notificationOccurred('success');await sectionReload();return;}
 if(action==='task-delete'){if(!await closeDialogFirst())return;await api('/tasks/'+el.dataset.id,{method:'DELETE'});await sectionReload();return;}
 if(action==='lists-open'){state.listsTab=el.dataset.value||'tasks';if(el.dataset.day){state.calDay=el.dataset.day;state.calMonth=el.dataset.day.slice(0,7);}if(location.hash!=='#plans'){location.hash='plans/'+state.listsTab;}else render();return;}
 if(action==='cal-month'||action==='cal-today'){state.calMonth=action==='cal-today'?projectToday().slice(0,7):shiftMonth(state.calMonth,Number(el.dataset.value));state.calDay=state.calMonth===projectToday().slice(0,7)?projectToday():`${state.calMonth}-01`;state.events=null;render();return sectionReload();}
 if(action==='cal-day'){state.calDay=el.dataset.value;render();return;}
 if(action==='note-add')return noteEditor();
 if(action==='note-import')return notesImport();
 if(action==='note-edit')return noteEditor(state.lists?.notes.find(n=>n.id===el.dataset.id));
 if(action==='note-delete'){if(!await closeDialogFirst())return;if(await confirm('Удалить заметку?','Восстановить её не получится.','Удалить')){await api('/notes/'+el.dataset.id,{method:'DELETE'});await sectionReload();}return;}
 if(action==='event-add')return eventEditor(null,el.dataset.day||state.calDay||projectToday());
 if(action==='event-edit')return eventEditor((state.events?.events||[]).find(e=>e.id===el.dataset.id));
 if(action==='event-delete'){if(!await closeDialogFirst())return;if(await confirm('Удалить событие?','Если оно повторяется, удалятся все повторы.','Удалить')){await api('/events/'+el.dataset.id,{method:'DELETE'});await sectionReload();}return;}
}
async function stationAction(action,el){
 if(action==='sync-key-create'){if(preview){syncKeyShown={url:new URL('../api/activity/sync',location.href).href,key:'preview-key-preview-key'};}else syncKeyShown=await api('/activity/sync/key',{method:'POST'});$('#dialog').close('cancel');return activitySync(el.dataset.mode);}
 if(action==='sync-key-delete'){if(!await closeDialogFirst())return;if(await confirm('Отключить синхронизацию?','Ссылка перестанет работать. Уже записанные данные останутся.','Отключить')){if(!preview)await api('/activity/sync/key',{method:'DELETE'});syncKeyShown=null;toast('Синхронизация отключена');await sectionReload();}return;}
}

// ── Круг жизни: всё, что вас окружает и влияет, и живые выводы по вашим данным ──
function circleData(){return state.circle||state.data?.insights||null;}
function scoreTone(score){return score==null?'none':score>=70?'good':score>=40?'mid':'low';}
function circleRing(c,{size=340,compact=false}={}){
 const h=Math.round(size*.84),cx=size/2,cy=h/2,r=size*.255,w=compact?13:18,n=c.spheres.length||1,step=360/n,sweep=step-(compact?9:7);
 const C=2*Math.PI*r,seg=C*sweep/360,labelR=r+w/2+(compact?13:17);
 const segs=c.spheres.map((sp,i)=>{
  const start=-90+i*step+(step-sweep)/2,mid=start+sweep/2,rad=mid*Math.PI/180;
  const tx=cx+labelR*Math.cos(rad),ty=cy+labelR*Math.sin(rad)+4,fill=sp.score==null?0:seg*sp.score/100;
  const anchor=Math.abs(Math.cos(rad))<.3?'middle':Math.cos(rad)>0?'start':'end';
  return `<a href="${esc(sp.href)}" class="circle-seg tone-${scoreTone(sp.score)}" style="--i:${i}" aria-label="${esc(sp.label)}: ${sp.score==null?'нет данных':sp.score+' из 100'}. ${esc(sp.status)}"><circle class="seg-track${sp.score==null?' empty':''}" cx="${cx}" cy="${cy}" r="${r}" stroke-width="${w}" stroke-dasharray="${seg.toFixed(2)} ${(C-seg).toFixed(2)}" transform="rotate(${start} ${cx} ${cy})"/>${fill?`<circle class="seg-fill" cx="${cx}" cy="${cy}" r="${r}" stroke-width="${w}" stroke-dasharray="${fill.toFixed(2)} ${(C-fill).toFixed(2)}" style="--f:${fill.toFixed(2)}" transform="rotate(${start} ${cx} ${cy})"/>`:''}<text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}" class="seg-label">${esc(sp.label)}</text></a>`;}).join('');
 const dots=Array.from({length:n},(_,i)=>{const a=(-90+i*step)*Math.PI/180;return `<circle class="circle-tick" cx="${(cx+(r+w/2+5)*Math.cos(a)).toFixed(1)}" cy="${(cy+(r+w/2+5)*Math.sin(a)).toFixed(1)}" r="1.4"/>`;}).join('');
 return `<div class="circle-ring${compact?' compact':''}"><span class="circle-glow" aria-hidden="true"></span><svg viewBox="0 0 ${size} ${h}" role="group" aria-label="Круг жизни"><circle class="circle-orbit" cx="${cx}" cy="${cy}" r="${(r+w/2+7).toFixed(1)}" style="--o:${(2*Math.PI*(r+w/2+7)).toFixed(1)}"/><g class="circle-ticks">${dots}</g>${segs}</svg><div class="circle-core"><span class="core-pulse" aria-hidden="true"></span><b>${c.overall==null?'—':countUp(c.overall,'int')}</b><small>баланс жизни</small></div></div>`;
}
function insightList(c,limit=8){
 const items=c.insights.slice(0,limit);
 if(!items.length)return '<p class="muted">Пока всё спокойно — выводы появятся, когда накопятся данные.</p>';
 return `<ul class="insight-list">${items.map((i,k)=>`<li style="--k:${k}"><a href="${esc(i.href)}" class="insight tone-${esc(i.tone)}"><span class="insight-dot" aria-hidden="true">${i.tone==='good'?icon('check'):i.tone==='warn'?'!':'·'}</span><span>${esc(i.text)}</span>${icon('chevron')}</a></li>`).join('')}</ul>`;
}
function circleView(){
 const c=circleData(),back='<a href="#overview" class="button secondary small back">← Главная</a>';
 if(!c)return `<div class="project-space">${back}${header('Круг жизни','')}${skeleton('chart')}</div>`;
 const known=c.spheres.filter(s=>s.score!=null).length,low=c.spheres.filter(s=>s.score!=null&&s.score<40).map(s=>s.label.toLowerCase()),best=[...c.spheres].filter(s=>s.score!=null).sort((a,b)=>b.score-a.score)[0];
 const verdict=known<2?'Добавьте данные в разные разделы — круг станет полнее':low.length?`Больше всего внимания: ${low.join(', ')}`:best?`Сильнее всего сейчас — ${best.label.toLowerCase()}`:'';
 return `<div class="project-space">${back}</div>${secHero('circle','Круг жизни','Всё, что вас окружает и влияет, — в одном месте')}<section class="circle-hero" data-ui-key="circle-hero">${circleRing(c)}<p class="circle-verdict">${esc(verdict)}</p></section><section class="panel circle-spheres" data-ui-key="circle-spheres">${c.spheres.map(sp=>`<a href="${esc(sp.href)}" class="sphere-row tone-${scoreTone(sp.score)}"><span class="sphere-name"><b>${esc(sp.label)}</b><small>${esc(sp.status)}</small></span><span class="sphere-meter" aria-hidden="true"><i style="--w:${sp.score||0}%"></i></span><b class="sphere-score">${sp.score==null?'—':sp.score}</b></a>`).join('')}</section><section class="panel circle-insights" data-ui-key="circle-insights"><div class="panel-head"><div><span class="eyebrow">СЕЙЧАС</span><h2>Что происходит</h2></div><span class="badge live"><i></i>в реальном времени</span></div>${insightList(c)}</section><p class="feed-note">Оценки считаются по вашим данным правилами, а не «оценкой жизни»: нет данных — нет оценки. Всё обновляется само, как только вы что-то меняете.</p>`;
}
function circleCard(){
 const c=circleData();
 if(!c)return `<section class="panel home-card home-circle" data-ui-key="home-circle">${skeleton('chart')}</section>`;
 return `<section class="panel home-card home-circle" data-ui-key="home-circle"><div class="home-card-head"><span class="home-icon">${icon('circle')}</span><span class="eyebrow">Круг жизни</span><a class="text-link" href="#circle">Подробнее</a></div><div class="home-circle-body">${circleRing(c,{size:300,compact:true})}<div class="home-circle-side"><span class="eyebrow">СЕЙЧАС</span>${insightList(c,4)}</div></div></section>`;
}
function tasksCard(){
 const tasks=(state.lists?.tasks||[]).filter(t=>!t.done),today=projectToday(),late=tasks.filter(t=>t.due&&t.due<today),now=tasks.filter(t=>t.due===today),show=[...late,...now,...tasks.filter(t=>!t.due||t.due>today)].slice(0,4);
 return `<section class="panel home-card home-tasks" data-ui-key="home-tasks"><div class="home-card-head"><span class="home-icon">${icon('plans')}</span><span class="eyebrow">Дела</span><button type="button" class="icon-btn small" data-action="task-add" aria-label="Добавить задачу">${icon('plus')}</button></div>${state.lists?`<b class="home-big">${now.length+late.length} <small>${late.length?`на сегодня, ${late.length} просрочено`:'на сегодня'}</small></b>${show.length?`<ul class="home-events-list">${show.map(t=>`<li><button type="button" data-action="task-toggle" data-id="${esc(t.id)}" class="home-task"><span class="wish-check" aria-hidden="true">${icon('check')}</span><b>${esc(t.title)}</b><small class="${t.due&&t.due<today?'late':''}">${esc(t.due?dueLabel(t.due):'')}</small></button></li>`).join('')}</ul>`:'<p class="muted home-empty">Открытых задач нет — отличный день.</p>'}`:skeleton('list',1)}</section>`;
}
// ── Банки и счета: свои карты, счета и вклады в общем балансе ──
// Баланс вводится вручную или обновляется сам: SMS/пуш банка пересылает телефон по тому же
// личному ключу, что и шаги. Пароли от интернет-банка Platformer не просит и не хранит.
const BANK_KINDS={card:'Карта',current:'Счёт',deposit:'Вклад',savings:'Накопительный',cash:'Наличные'};
const BANK_NAMES=['Альфа-Банк','БНБ-Банк','Беларусбанк','Приорбанк','МТБанк','БелВЭБ Банк','Белагропромбанк','Белинвестбанк','Сбербанк','Т-Банк','ВТБ','Revolut','Wise'];
// Подсказки названия банка появляются только после первой введённой буквы:
// сначала свои банки, затем известные, по совпадению с началом и с серединой слова.
function bankSuggestions(){
 const own=[...new Set((state.banks?.accounts||[]).map(a=>a.bank).filter(Boolean))],low=own.map(n=>n.toLowerCase());
 return [...own,...BANK_NAMES.filter(n=>!low.includes(n.toLowerCase()))];
}
function bankSuggestInit(d){
 const input=d.querySelector('input[name="bank"]'),list=d.querySelector('#bank-suggest');if(!input||!list)return;
 let items=[],pick=-1;
 const close=()=>{items=[];pick=-1;list.hidden=true;list.innerHTML='';input.setAttribute('aria-expanded','false');};
 const mark=()=>{[...list.children].forEach((li,i)=>{li.classList.toggle('on',i===pick);li.setAttribute('aria-selected',i===pick?'true':'false');});};
 const render=()=>{
  const q=input.value.trim().toLowerCase();if(!q)return close();
  const all=bankSuggestions(),starts=all.filter(n=>n.toLowerCase().startsWith(q)),inside=all.filter(n=>!n.toLowerCase().startsWith(q)&&n.toLowerCase().includes(q));
  items=[...starts,...inside].slice(0,6);
  if(!items.length||(items.length===1&&items[0].toLowerCase()===q))return close();
  pick=-1;list.innerHTML=items.map(n=>`<li role="option" aria-selected="false">${esc(n)}</li>`).join('');list.hidden=false;input.setAttribute('aria-expanded','true');
 };
 const choose=i=>{if(i<0||i>=items.length)return;input.value=items[i];d.dataset.dirty='1';close();input.focus();};
 input.addEventListener('input',render);
 input.addEventListener('keydown',e=>{
  if(list.hidden)return;
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();pick=(pick+(e.key==='ArrowDown'?1:items.length-1)+(pick<0&&e.key==='ArrowUp'?1:0))%items.length;mark();}
  else if(e.key==='Enter'&&pick>=0){e.preventDefault();choose(pick);}
  else if(e.key==='Escape'){e.stopPropagation();close();}
 });
 input.addEventListener('blur',()=>setTimeout(close,120));
 list.addEventListener('mousedown',e=>{const li=e.target.closest('li');if(!li)return;e.preventDefault();choose([...list.children].indexOf(li));});
}
function bankMoney(value,cur){return new Intl.NumberFormat('ru-RU',{style:'currency',currency:cur,maximumFractionDigits:2}).format(value);}
function bankAgo(a){const src=a.source==='sms'?'из SMS':'вручную';return `${src} · ${agoText(a.updated_at)||'только что'}`;}
function bankShares(){
 const by={};for(const a of state.banks?.accounts||[]){if(!a.counted)continue;const v=displayAmount(a.balance,a.currency);if(v!=null&&v>0)by[a.bank]=(by[a.bank]||0)+v;}
 const entries=Object.entries(by).sort((a,b)=>b[1]-a[1]),sum=entries.reduce((n,[,v])=>n+v,0);
 return {entries,sum};
}
function bankStack(max=4){
 const {entries,sum}=bankShares();if(!sum)return '';
 const top=entries.slice(0,max),rest=entries.slice(max).reduce((n,[,v])=>n+v,0),parts=rest>0?[...top,['Другие',rest]]:top;
 return `<div class="bank-stack" role="img" aria-label="Доли банков в балансе">${parts.map(([name,v],i)=>`<i class="seg-${i%5}" style="--w:${(v/sum*100).toFixed(1)}%;--d:${i*110}ms" title="${esc(name)}: ${Math.round(v/sum*100)}%"></i>`).join('')}</div><div class="bank-legend">${parts.map(([name,v],i)=>`<span><i class="seg-${i%5}"></i>${esc(name)} <em>${Math.round(v/sum*100)}%</em></span>`).join('')}</div>`;
}
function bankSummaryCard(){
 const b=state.banks,accs=b?.accounts||[],t=bankTotal(),upd=accs.map(a=>a.updated_at).sort().at(-1),auto=accs.some(a=>a.source==='sms');
 const head=`<div class="project-card-head"><span class="project-icon">${icon('bank')}</span><h2>Банки и счета</h2>${icon('arrow')}</div>`;
 if(!accs.length)return `<a href="#banks" class="panel project-card system-project bank-summary" data-ui-key="project-banks">${head}<small class="project-count">Пока пусто</small><div class="project-finance"><div class="project-finance-row"><small>Карты, счета, вклады</small><b>—</b></div></div><div class="project-rate"><span>Введите баланс сами или обновляйте из SMS банка</span><b>Добавить счёт</b></div></a>`;
 const counted=accs.filter(a=>a.counted).length;
 return `<a href="#banks" class="panel project-card system-project bank-summary" data-ui-key="project-banks">${head}<small class="project-count">${countLabel(accs.length,['счёт','счёта','счетов'])}</small><div class="project-finance"><div class="project-finance-row working-capital"><small>На счетах</small><b>${t.partial?'—':money(t.sum,state.displayCurrency)}</b></div>${counted<accs.length?`<div class="project-finance-row"><small>Не в общем балансе</small><b>${accs.length-counted}</b></div>`:''}${b.inbox?.length?`<div class="project-finance-row attention"><small>Сообщения банка</small><b>${b.inbox.length} ${b.inbox.length%10===1&&b.inbox.length%100!==11?'ждёт':'ждут'} подтверждения</b></div>`:''}</div>${bankStack()}<div class="project-rate"><span>${upd?`Обновлено ${esc(agoText(upd))}`:'Баланс вручную'}</span><b>${auto?'из SMS · авто':'вручную'}</b></div></a>`;
}
function banksView(){
 const back='<a href="#projects" class="button secondary small back">← Финансы</a>',actions=`<div class="head-actions">${button('bank-sync','','secondary icon-only','refresh','aria-label="Автообновление из SMS"')}${button('bank-add','Счёт','primary','plus')}</div>`,t0=bankTotal();
 const head=`<div class="project-space">${back}</div><div class="page-head sec-hero tone-bank bank-head"><div class="sec-glow" aria-hidden="true"><i></i><i></i><i></i></div><div><span class="sec-eyebrow">Банки и счета</span><b class="bank-total">${!state.banks?'…':t0.partial?'—':countUp(t0.sum,`money:${state.displayCurrency}`)}</b><p>${state.banks?.accounts?.length?`${countLabel(state.banks.accounts.length,['счёт','счёта','счетов'])} · ${Object.entries(state.banks.totals).map(([c,v])=>esc(bankMoney(v,c))).join(' · ')}`:'Карты, счета, вклады и наличные — в общем балансе'}</p></div>${actions}</div>`;
 const b=state.banks;
 if(!b)return head+(state.banksError?sectionError(state.banksError,'bank-reload'):skeleton('list'));
 const t=bankTotal(),inboxCard=b.inbox.length?`<section class="bank-inbox" data-ui-key="bank-inbox"><div class="panel-head"><div><span class="eyebrow">ЖДУТ ВАС</span><h2>Сообщения банка</h2></div><span class="badge">${b.inbox.length}</span></div><p class="pref-hint">Не удалось понять, к какому счёту относится. Выберите — и следующие такие сообщения привяжутся сами.</p>${b.inbox.map(m=>{const p=m.parsed;return `<div class="inbox-item" data-ui-key="inbox-${esc(m.id)}"><p class="inbox-text">${esc(m.text)}</p><div class="inbox-facts">${p.last4?`<i>•••• ${esc(p.last4)}</i>`:''}${p.balance?`<i>остаток ${esc(p.balance)} ${esc(p.currency||'')}</i>`:''}${p.amount?`<i>${Number(p.amount)>0?'+':''}${esc(p.amount)} ${esc(p.currency||'')}</i>`:''}</div><div class="inbox-actions">${button('bank-inbox-assign','К счёту','secondary small','arrow',`data-id="${esc(m.id)}"`)}${button('bank-inbox-create','Новый счёт','primary small','plus',`data-id="${esc(m.id)}"`)}${button('bank-inbox-dismiss','Скрыть','ghost small','',`data-id="${esc(m.id)}"`)}</div></div>`;}).join('')}</section>`:'';
 if(!b.accounts.length)return head+inboxCard+`<section class="lists-empty bank-empty"><span class="empty-orb">${icon('bank')}</span><b>Добавьте первый счёт</b><p>Карта, счёт, вклад или наличные — введите баланс сами. А если пересылать SMS от банка, баланс будет обновляться без вашего участия.</p>${button('bank-add','Добавить счёт','primary','plus')}${button('bank-sync','Как обновлять из SMS','ghost small','refresh')}</section>`;
 const totals=Object.entries(b.totals),byBank={};for(const a of b.accounts)(byBank[a.bank]=byBank[a.bank]||[]).push(a);
 const hero=`<section class="bank-hero" data-ui-key="bank-hero">${bankStack(6)}</section>`;
 const groups=Object.entries(byBank).map(([bank,list],g)=>{const sum=list.filter(a=>a.counted).reduce((acc,a)=>acc+(displayAmount(a.balance,a.currency)||0),0);return `<section class="bank-group" style="${bankColors(list[0])};--g:${g}" data-ui-key="bank-${esc(bank)}"><div class="bank-group-head"><span class="bank-logo" aria-hidden="true">${esc((list[0].kind==='cash'?'₽':bank.trim().slice(0,1)).toUpperCase())}</span><h2>${esc(bank)}</h2><b class="bank-sum">${list.some(a=>a.counted)?money(sum,state.displayCurrency):'не в балансе'}</b></div><div class="bank-stack-cards">${list.map((a,i)=>`<button type="button" class="bank-account pcard k-${esc(a.kind)}${a.counted?'':' off'}" style="${bankColors(a)};--i:${i}" data-action="bank-edit" data-id="${esc(a.id)}" data-ui-key="bank-account-${esc(a.id)}"><span class="pc-shine" aria-hidden="true"></span><span class="pc-top"><b>${esc(a.title||a.kind_label)}</b><i>${esc(a.kind_label)}</i></span>${a.kind==='cash'?'<span class="pc-coins" aria-hidden="true"><i></i><i></i><i></i></span>':'<span class="pc-chip" aria-hidden="true"></span>'}<span class="pc-bal ${a.balance<0?'negative':''}">${esc(bankMoney(a.balance,a.currency))}</span><span class="pc-bottom"><span>${esc(bankAgo(a))}${a.counted?'':' · не в балансе'}</span><span>${a.last4?`•••• ${esc(a.last4)}`:a.currency!==state.displayCurrency&&displayAmount(a.balance,a.currency)!=null?money(a.balance,a.currency):''}</span></span></button>`).join('')}</div></section>`;}).join('');
 return head+inboxCard+hero+groups+`<p class="feed-note">Platformer не заходит в банк за вас и не хранит пароли: баланс — то, что вы ввели, или остаток из SMS, который вы сами пересылаете.</p>`;
}
async function bankEditor(acc=null,seed={}){
 let error='',draft=acc?{...acc}:{bank:'',title:'',kind:'card',currency:state.displayCurrency in {USD:1,RUB:1,BYN:1}?state.displayCurrency:'BYN',balance:'',last4:'',counted:true,...seed};
 while(true){
  const body=`${error?notice(error,true):''}<label class="field">Банк<span class="suggest"><input name="bank" value="${esc(draft.bank)}" required maxlength="48" placeholder="Начните вводить название" autocomplete="off" role="combobox" aria-expanded="false" aria-autocomplete="list" aria-controls="bank-suggest"><ul class="suggest-list" id="bank-suggest" role="listbox" hidden></ul></span></label>${field('Название (необязательно)','title','text',draft.title||'','maxlength="64" placeholder="Зарплатная, Накопления…"')}<div class="field-row"><label class="field">Тип<select name="kind">${Object.entries(BANK_KINDS).map(([id,l])=>`<option value="${id}" ${id===draft.kind?'selected':''}>${l}</option>`).join('')}</select></label><label class="field">Валюта<select name="currency" ${acc?'disabled':''}>${['BYN','USD','RUB'].map(c=>`<option ${c===draft.currency?'selected':''}>${c}</option>`).join('')}</select></label></div>${field(acc?'Баланс сейчас':'Баланс','balance','number',draft.balance===''?'':draft.balance,'required step="0.01" inputmode="decimal"')}${field('Последние 4 цифры карты (необязательно)','last4','text',draft.last4||'','maxlength="4" inputmode="numeric" pattern="[0-9]{4}" placeholder="1234"')}<p class="project-form-note">По цифрам SMS от банка сами найдут этот счёт и обновят баланс.</p><label class="check"><input type="checkbox" name="counted" ${draft.counted?'checked':''}>Учитывать в общем балансе</label>${acc?`<div class="inline-actions mt">${button('bank-ops','История изменений','secondary small','clock',`data-id="${esc(acc.id)}"`)}</div><div class="guest-danger">${button('bank-delete','Удалить счёт','danger small','',`data-id="${esc(acc.id)}"`)}</div>`:''}`;
  const values=await dialog(acc?'Счёт':'Новый счёт',body,'Сохранить',{onOpen:bankSuggestInit});if(!values)return;
  draft={...draft,bank:values.bank,title:values.title||'',kind:values.kind,currency:acc?acc.currency:values.currency,balance:values.balance,last4:values.last4||'',counted:values.counted==='on'};
  const payload={bank:draft.bank,title:draft.title,kind:draft.kind,balance:Number(draft.balance),last4:draft.last4||null,counted:draft.counted};if(!acc)payload.currency=draft.currency;
  try{await api('/banks'+(acc?'/'+acc.id:''),{method:acc?'PATCH':'POST',body:JSON.stringify(payload)});tg?.HapticFeedback?.notificationOccurred('success');toast('Сохранено');await sectionReload();return;}catch(exc){error=exc.message;}
 }
}
async function bankAction(action,el){
 const acc=id=>state.banks?.accounts.find(a=>a.id===id),msg=id=>state.banks?.inbox.find(m=>m.id===id);
 if(action==='bank-add')return bankEditor();
 if(action==='bank-reload')return sectionReload();
 if(action==='bank-edit')return bankEditor(acc(el.dataset.id));
 if(action==='bank-sync')return activitySync();
 if(action==='bank-delete'){if(!await closeDialogFirst())return;if(await confirm('Удалить счёт?','Он исчезнет из общего баланса вместе с историей.','Удалить')){await api('/banks/'+el.dataset.id,{method:'DELETE'});await sectionReload();}return;}
 if(action==='bank-ops'){const r=await api(`/banks/${el.dataset.id}/ops`);if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;const a=acc(el.dataset.id);await dialog('История',`<div class="ops-list">${r.operations.map(o=>`<div class="op-row"><span><b>${esc(o.note||'Операция')}</b><small>${esc(date(o.at,true))}${o.source==='sms'?' · из SMS':''}</small></span><span class="op-values">${o.amount!=null?`<b class="${o.amount<0?'negative':'positive'}">${o.amount>0?'+':''}${esc(bankMoney(o.amount,a.currency))}</b>`:''}${o.balance!=null?`<small>остаток ${esc(bankMoney(o.balance,a.currency))}</small>`:''}</span></div>`).join('')||'<p class="muted">Пока пусто.</p>'}</div>`,'Готово');return;}
 if(action==='bank-inbox-dismiss'){await api('/banks/inbox/'+el.dataset.id,{method:'DELETE'});await sectionReload();return;}
 if(action==='bank-inbox-create'){const m=msg(el.dataset.id);return bankEditor(null,{currency:m.parsed.currency||'BYN',balance:m.parsed.balance??'',last4:m.parsed.last4||''}).then(async()=>{});}
 if(action==='bank-inbox-assign'){
  const m=msg(el.dataset.id),list=state.banks.accounts.filter(a=>!m.parsed.currency||a.currency===m.parsed.currency||!['USD','RUB','BYN'].includes(m.parsed.currency));
  if(!list.length){toast('Нет подходящего счёта — создайте новый');return bankEditor(null,{currency:m.parsed.currency||'BYN',balance:m.parsed.balance??'',last4:m.parsed.last4||''});}
  const values=await dialog('К какому счёту?',`<p class="inbox-text">${esc(m.text)}</p><label class="field">Счёт<select name="account">${list.map(a=>`<option value="${esc(a.id)}">${esc(`${a.bank} · ${a.title||a.kind_label} · ${a.currency}`)}</option>`).join('')}</select></label>`,'Привязать');
  if(!values)return;await api('/banks/inbox/'+m.id,{method:'POST',body:JSON.stringify({account_id:values.account})});toast('Баланс обновлён');await sectionReload();return;}
}
// Предпросмотр без сервера: правдоподобные вымышленные записи разделов
function previewActivity(days){
 const end=projectToday(),steps=[];
 for(let i=0;i<days;i++)steps.push({day:addDaysIso(end,-i),value:Math.round(8200+(Math.sin(i*1.7)+Math.cos(i*.6))*2600)});
 steps.reverse();
 const week=steps.filter(p=>p.day>=addDaysIso(end,-6));
 return {days,entries:[],goals:{steps:10000},
  summary:{steps:{today:steps.at(-1)?.value??null,week_avg:week.reduce((n,p)=>n+p.value,0)/(week.length||1),series:steps}},
  sync:{connected:true,last_sync:new Date(Date.parse(PREVIEW_STAMP)-12*6e4).toISOString().replace(/\.\d+Z$/,'Z'),last_saved:'steps'}};
}
const PREVIEW_STAMP=new Date(Math.floor(Date.now()/36e5)*36e5).toISOString().replace(/\.\d+Z$/,'Z');
function previewBanks(){const t=new Date(Date.parse(PREVIEW_STAMP)-2*36e5).toISOString().replace(/\.\d+Z$/,'Z'),mk=(id,bank,title,kind,currency,balance,last4,source='manual',counted=true)=>({id,bank,title,kind,kind_label:BANK_KINDS[kind],currency,balance,last4,counted,updated_at:t,source});const accounts=[mk('b1','Альфа-Банк','Зарплатная','card','BYN',4210.55,'1234','sms'),mk('b2','Альфа-Банк','Накопления','savings','BYN',12000,null),mk('b3','БНБ-Банк','Вклад на год','deposit','USD',3500,null),mk('b4','Приорбанк','Валютная','card','USD',860.2,'9876','sms'),mk('b5','Наличные','Кошелёк','cash','RUB',15000,null,'manual',false)];return {accounts,totals:{BYN:16210.55,USD:4360.2},inbox:[{id:'m1',received_at:t,text:'Покупка 12,00 USD *7777, остаток 88,00 USD',parsed:{last4:'7777',currency:'USD',balance:'88.00',amount:'-12.00',op:'out'}}],kinds:BANK_KINDS,currencies:['BYN','RUB','USD'],sync:{connected:true,last_sync:t}};}
function previewTasks(){const t=projectToday(),mk=(id,title,due,area,done=false)=>({id:'t'+id,title,note:'',due,area,done,done_at:done?`${addDaysIso(t,-1)}T10:00:00Z`:null,created_at:`${addDaysIso(t,-5)}T09:00:00Z`});return [mk(1,'Сдать квартальный отчёт',addDaysIso(t,-1),'work'),mk(2,'Позвонить в банк',t,'personal'),mk(3,'Записаться к стоматологу',addDaysIso(t,3),'personal'),mk(4,'Заменить лампочку в коридоре',addDaysIso(t,9),'home'),mk(5,'Выбрать курс по английскому',null,'study'),mk(6,'Оплатить интернет',addDaysIso(t,-2),'home',true)];}
function previewInsights(){return {overall:65,spheres:[{id:'finance',label:'Финансы',href:'#projects',score:88,status:'на счетах 9 764 $ · ≈ 118 $ в день'},{id:'tasks',label:'Дела',href:'#plans/tasks',score:52,status:'просрочено 1'},{id:'plans',label:'Планы',href:'#plans/calendar',score:75,status:'4 события на неделе'},{id:'dreams',label:'Мечты',href:'#projects',score:46,status:'3 цели накоплений'}],insights:[{sphere:'finance',tone:'info',text:'На банковских счетах: 9 764 $',href:'#banks'},{sphere:'tasks',tone:'warn',text:'Просрочено: 1 задача — «Сдать квартальный отчёт»',href:'#plans/tasks'},{sphere:'plans',tone:'info',text:'Сегодня в 19:00: Звонок маме',href:'#plans/calendar'},{sphere:'finance',tone:'good',text:'Проекты приносят ≈ 118,91 $ в день — около 3 567 $ за месяц',href:'#projects'},{sphere:'dreams',tone:'good',text:'«Штатив» за 700 $ — это ≈ 6 дней дохода проектов',href:'#plans/wish'}]};}
function previewLists(){
 const t=projectToday(),ev=(n,title,color,time=null,repeat='none')=>({id:'e'+n,day:addDaysIso(t,n),date:addDaysIso(t,n),original_day:addDaysIso(t,n),time,title,color,repeat,note:''});
 const upcoming=[ev(0,'Звонок маме','pink','19:00'),ev(2,'ДР Саши','purple',null,'yearly'),ev(5,'Оплата интернета','orange','09:00','monthly'),ev(9,'Стоматолог','blue','11:30')];
 return {notes:[{id:'n1',title:'Идеи на выходные',body:'Поход в горы\nНовый ресторан на набережной',pinned:true,color:'green',updated_at:`${t}T09:00:00Z`},{id:'n2',title:'Покупки',body:'Кофе, овсянка, батарейки',pinned:false,color:'orange',updated_at:`${addDaysIso(t,-1)}T18:30:00Z`}],
  tasks:previewTasks(),areas:{personal:'Личное',work:'Работа',home:'Дом',study:'Учёба'},upcoming,events:upcoming};
}
const TAG_ID='tagmarket-system';
function tagSelected(){const sel=state.forecast.selected;return sel===null||sel.includes(TAG_ID);}
function forecastBase(){const from=state.forecast.from;return from&&from>projectToday()?from:projectToday();}
function forecastDate(horizon,base=projectToday()){const [y,m,day]=base.split('-').map(Number),offset={'1m':1,'3m':3,'6m':6,'1y':12}[horizon]||0;if(offset){const month=m-1+offset,year=y+Math.floor(month/12),index=month%12+1,last=new Date(Date.UTC(year,index,0)).getUTCDate();return new Date(Date.UTC(year,index-1,Math.min(day,last))).toISOString().slice(0,10);}const d=new Date(Date.UTC(y,m-1,day));d.setUTCDate(d.getUTCDate()+(horizon==='1d'?1:horizon==='1w'?7:0));return d.toISOString().slice(0,10);}
async function fetchForecast(projects=state.projects,untilOverride=''){const f=state.forecast,until=untilOverride||(f.horizon==='custom'?f.until:forecastDate(f.horizon,forecastBase())),params=new URLSearchParams({until,bonus:f.bonus?'1':'0'});if(f.selected!==null){params.set('all','0');for(const id of f.selected)if(id!==TAG_ID)params.append('id',id);}return (await api(`/projects/forecast?${params}`)).projects;}
async function fetchTagForecast(untilOverride=''){const f=state.forecast,until=untilOverride||(f.horizon==='custom'?f.until:forecastDate(f.horizon,forecastBase()));try{return await api(`/tagmarket/forecast?until=${until}`);}catch(error){return {error:error.message||'Прогноз TagMarket временно недоступен'};}}
function tagMultiplier(key,tag=state.forecast.tag){const t=tag;return key==='now'?1:t?.sufficient?(t.multipliers?.[key]??1):1;}
function forecastCell(cp,currency,key){return cp?.calculation_limited||cp?.[key]==null?'—':money(cp[key],currency);}
function forecastPortfolioTotal(result,key,tag=state.forecast.tag){let value=0,partial=false;for(const p of result||[]){const cp=key==='now'?p.current:p.checkpoints?.[key];if(!cp||cp.total==null){partial=true;continue;}const amount=displayAmount(cp.total,p.currency);if(amount==null)partial=true;else value+=amount;}if(tagSelected()){const tagValue=displayAmount((tagBalance())*tagMultiplier(key,tag),'USD');if(tagValue==null)partial=true;else value+=tagValue;}return {value,partial};}
function forecastAccountDetail(current,projected,currency){
 const tone=Number(projected.growth)<0?'negative':'positive',tags=[
  projected.personal_capitalization?'<i class="cap">капитализация</i>':'',
  projected.bonus_active&&Number(projected.bonus)>0?`<i class="bonus">бонус ${money(projected.bonus,currency)}</i>`:'',
  projected.bonus_capitalization&&projected.bonus_active?'<i class="cap">кап. бонуса</i>':'',
  Number(projected.fixed)>0?`<i class="fix">фикс. +${money(projected.fixed,currency)}</i>`:''].filter(Boolean).join('');
 return `<div class="forecast-account-detail"><div class="fa-head"><b>${esc(projected.name||'Аккаунт')}</b><span class="fa-growth ${tone}">${money(projected.growth,currency,true)}</span></div><div class="fa-flow"><span>${money(current.current_working,currency)}</span><i aria-hidden="true">→</i><b>${money(projected.working,currency)}</b></div>${tags?`<div class="fa-tags">${tags}</div>`:''}</div>`;
}
function forecastBreakdown(project,result){const now=result.current?.accounts||[],end=result.checkpoints?.selected?.accounts||[];return `<details class="forecast-breakdown"><summary>Счета · ${countLabel(end.length,['аккаунт','аккаунта','аккаунтов'])}</summary>${end.map(account=>forecastAccountDetail(now.find(x=>x.account_id===account.account_id)||account,account,project.currency)).join('')}</details>`;}
// Прогноз: этапы пути портфеля (сейчас → завтра → неделя → месяц → выбранная дата) лентой,
// чтобы видеть не только итог, но и как он растёт со временем.
function forecastMilestones(totals,until,period=null){
 const today=period?period.from:projectToday(),dates=period?[today,until]:[today,forecastDate('1d'),forecastDate('1w'),forecastDate('1m'),until],labels=period?[`Старт`,null]:['Сейчас','Завтра','Через неделю','Через месяц',null],rows=[],seen=new Set();
 const list=period?[period.start,totals.at(-1)]:totals;
 dates.forEach((day,i)=>{const t=list[i];if(!t||t.partial||(!period&&i<4&&day>until)||seen.has(day))return;seen.add(day);rows.push({label:i===dates.length-1?date(day):labels[i],day,total:t.value});});
 if(rows.length<2)return '';
 const base=rows[0].total,growths=rows.map(r=>r.total-base),peak=Math.max(...growths.map(Math.abs),0.01),cur=state.displayCurrency;
 return `<div class="forecast-milestones"><div class="fg-head"><b>Рост по этапам</b><small>от ${esc(date(today))}</small></div><ol class="feed fm-list">${rows.map((r,i)=>{const g=growths[i],pct=base>0?g/base*100:null;return `<li class="feed-day ${g<0?'down':'up'}"><span class="feed-date"><b>${esc(r.label)}</b><small>${i===0?'старт':esc(date(r.day))}</small></span><span class="feed-bar"><i style="--w:${i===0?3:Math.max(3,Math.abs(g)/peak*100).toFixed(1)}%"></i></span><span class="feed-sum"><b>${money(r.total,cur)}</b><small>${i===0?'текущий капитал':`${money(g,cur,true)}${pct==null?'':` · ${percent(pct)}`}`}</small></span></li>`;}).join('')}</ol></div>`;
}
// События по дороге: бонус заканчивается — после этой даты прирост замедлится
function forecastEvents(result,until,from=null){
 const today=from||projectToday(),events=[];
 for(const r of result||[]){const project=(state.projects||[]).find(x=>x.id===r.project_id);for(const a of r.current?.accounts||[]){if(!a.bonus_active||!a.bonus_expires_at||!(a.current_bonus>0))continue;const day=a.bonus_expires_at.slice(0,10);if(day>=today&&day<=until)events.push({day,text:`Закончится бонус ${money(a.current_bonus,r.currency)} · ${project?.name||'Проект'}${a.name?` · ${a.name}`:''}`});}}
 if(!events.length)return '';events.sort((x,y)=>x.day<y.day?-1:1);
 return `<div class="forecast-events"><div class="fg-head"><b>По дороге</b><small>что повлияет на прирост</small></div><ul>${events.slice(0,6).map(e=>`<li><span>${esc(date(e.day))}</span><p>${esc(e.text)}. После этой даты прирост по аккаунту замедлится.</p></li>`).join('')}</ul></div>`;
}
function forecastView(){
 const f=state.forecast,projects=activeProjects(),until=f.until||forecastDate(f.horizon,forecastBase()),result=f.result,selected=f.selected;
 const horizons=[['now','Сейчас'],['day','День'],['week','Неделя'],['month','Месяц'],['selected',`На ${date(until)}`]],keyFor=['now','day','week','month','selected'];
 const totals=keyFor.map(key=>forecastPortfolioTotal(result,key)),fromMode=!!(f.from&&f.from>projectToday()&&f.fromResult),startTotal=fromMode?forecastPortfolioTotal(f.fromResult,'selected',f.fromTag):totals[0],startLabel=fromMode?`На ${date(f.from)}`:'Сейчас',growth=totals.at(-1).value-startTotal.value;const horizonDays=Math.round((Date.parse(until)-Date.parse(forecastBase()))/864e5);
 const tagCapital=tagBalance(),tf=f.tag,tagOk=!!tf?.sufficient,tagOn=tagSelected(),
  tagShown=key=>{const v=displayAmount(tagCapital*tagMultiplier(key),'USD');return v==null?money(tagCapital*tagMultiplier(key),'USD'):money(v,state.displayCurrency);},
  tagCells=keyFor.map(key=>`${tagOk&&key!=='now'?'≈ ':''}${tagShown(key)}`),
  tagGrowth=(()=>{const a=displayAmount(tagCapital*tagMultiplier('selected'),'USD'),b=displayAmount(tagCapital,'USD');return a==null||b==null?'—':money(a-b,state.displayCurrency,true);})(),
  tagNote=!tf?'':tf.error?'Прогноз временно недоступен':tagOk?`${number(Math.round(tf.average_daily_return*10000)/100)}% / день · ${countLabel(tf.days_used,['торговый день','торговых дня','торговых дней'])}`:'Недостаточно истории для прогноза',
  tagRate=tagOk?`${number(Math.round(tf.average_daily_return*10000)/100)}% / день`:'Доходность / день';
 // карточка проекта: «сейчас → на дату», прирост, этапы чипами и счета свёрнуто
 const fcCard=({name,note,now,end,growth,pct,steps,accounts,extra=''})=>`<article class="fc-card forecast-mobile-card ${extra}"><header><h3>${esc(name)}</h3>${note?`<small>${note}</small>`:''}</header><div class="fc-values"><div><small>Сейчас</small><b>${now}</b></div><i aria-hidden="true">→</i><div><small>На ${esc(date(until))}</small><b>${end}</b></div><div class="fc-growth"><small>Прирост</small><b>${growth}</b>${pct?`<em>${pct}</em>`:''}</div></div><div class="fc-steps">${steps.map(([label,value])=>`<span><small>${label}</small><b>${value}</b></span>`).join('')}</div>${accounts||''}</article>`;
 const projectCards=(result||[]).map(r=>{
  const p=projects.find(x=>x.id===r.project_id),cp=r.checkpoints||{},cur=r.currency,now=forecastCell(r.current,cur,'total'),end=forecastCell(cp.selected,cur,'total'),g=cp.selected?.growth,base=r.current?.total;
  return fcCard({name:p?.name||'Проект',note:p?projectRateLabel(p):'',now,end,growth:forecastCell(cp.selected,cur,'growth'),pct:g!=null&&base>0?percent(g/base*100):'',
   steps:[['День',forecastCell(cp.day,cur,'total')],['Неделя',forecastCell(cp.week,cur,'total')],['Месяц',forecastCell(cp.month,cur,'total')]],accounts:p?forecastBreakdown(p,r):''});}).join('');
 const tagCard=tagOn&&result?fcCard({name:'TagMarket',note:tagNote,now:tagCells[0],end:tagCells.at(-1),growth:tagGrowth,pct:'',steps:[['День',tagCells[1]],['Неделя',tagCells[2]],['Месяц',tagCells[3]]],extra:'fc-tag'}):'';
 const row=(id,name,meta,checked,extra='')=>`<label class="forecast-project-row ${extra}"><input type="checkbox" name="forecast-project" value="${esc(id)}" ${checked?'checked':''}><span><b>${esc(name)}</b><small>${meta}</small></span></label>`;
 const tagMeta=`${tagRate} · Ваши средства ${money(displayAmount(tagCapital,'USD')??tagCapital,displayAmount(tagCapital,'USD')==null?'USD':state.displayCurrency)}`;
 const horizonButtons=[['1d','1 день'],['1w','1 неделя'],['1m','1 месяц'],['3m','3 месяца'],['6m','6 месяцев'],['1y','1 год']].map(([id,label])=>`<button data-action="forecast-horizon" data-value="${id}" class="${f.horizon===id&&f.horizon!=='custom'?'active':''}">${label}</button>`).join('');
 return `<div class="project-space forecast-space">${header('Прогноз','',button('forecast-back','Проекты','secondary small','back'))}<section class="panel forecast-controls"><div class="forecast-horizons segmented">${horizonButtons}</div><div class="forecast-dates"><label class="field">Считать с<input id="forecast-from" type="date" min="${projectToday()}" value="${esc(forecastBase())}"></label><label class="field">По дату<input id="forecast-date" type="date" min="${esc(forecastBase())}" value="${esc(until)}"></label></div><div class="segmented forecast-bonus"><button data-action="forecast-bonus" data-value="1" class="${f.bonus?'active':''}">С бонусами</button><button data-action="forecast-bonus" data-value="0" class="${!f.bonus?'active':''}">Только мои средства</button></div></section><section class="panel forecast-projects"><div class="panel-head"><h2>Проекты</h2><span class="badge">${countLabel(projects.length+1,['проект','проекта','проектов'])}</span></div>${row(TAG_ID,'TagMarket',tagMeta,tagOn,'forecast-tag-row')}${projects.map(p=>row(p.id,p.name,`${projectRateLabel(p)} · Ваши средства ${projectMoney(p.total,p.currency)}${f.bonus&&p.bonus_total?` · бонус ${projectMoney(p.bonus_total,p.currency)}`:''}`,selected===null||selected.includes(p.id))).join('')}</section>${result?`<section class="panel forecast-result"><span class="eyebrow">${fromMode?`ПОРТФЕЛЬ · ${esc(date(f.from))} → ${esc(date(until))}`:`ПОРТФЕЛЬ НА ${esc(date(until))}`}</span><div class="forecast-summary-values"><div><small>${startLabel}</small><strong>${startTotal.partial?'Частично рассчитан':money(startTotal.value,state.displayCurrency)}</strong></div><div><small>На выбранную дату</small><strong>${totals.at(-1).partial?'Частично рассчитан':money(totals.at(-1).value,state.displayCurrency)}</strong></div><div><small>${fromMode?'Прирост за период':'Расчётный прирост'}</small><strong class="${growth<0?'negative':'positive'}">${startTotal.partial||totals.at(-1).partial?'—':money(growth,state.displayCurrency,true)}</strong>${startTotal.partial||totals.at(-1).partial||!(startTotal.value>0)?'':`<small class="fs-sub">${percent(growth/startTotal.value*100)}${horizonDays>0?` · ≈ ${money(growth/horizonDays,state.displayCurrency,true)} в день`:''}</small>`}</div></div>${forecastMilestones(totals,until,fromMode?{from:f.from,start:startTotal}:null)}${forecastEvents(result,until,fromMode?f.from:null)}<div class="fc-grid forecast-mobile-cards">${tagCard+projectCards||'<p class="muted">Выберите проекты выше.</p>'}</div></section>`:''}${result&&totals.some(t=>t.partial)?notice('Часть сумм нельзя перевести по текущему курсу. Недоступные проекты показаны в исходной валюте.',true):''}<p class="stat-note forecast-foot">Расчёт по текущим ставкам и средней доходности TagMarket. Это не гарантия результата.</p></div>`;
}
function localDateTime(iso){if(!iso)return '';const d=new Date(iso);return Number.isFinite(d.getTime())?new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16):'';}
function projectFormAccount(a={},index=0){const seq=++projectFormSeq;return `<div class="project-form-account" data-index="${seq}" ${a.id?`data-id="${esc(a.id)}"`:''}><div class="project-form-account-head"><b>Аккаунт ${index+1}</b></div><div class="project-account-name">${field('Название аккаунта (необязательно)',`account-name-${seq}`,'text',a.name||'','maxlength="96"')}</div>${field('Личный баланс',`account-amount-${seq}`,'number',a.amount??'','required min="0.01" max="1000000000000" step="0.01" inputmode="decimal"')}<div class="project-account-rate">${field('Своя ставка, % (необязательно)',`account-rate-${seq}`,'number',a.rate_percent??'','min="0" max="1000" step="0.0001" inputmode="decimal"')}</div><div class="project-account-fixed">${field('Доплата аккаунту за период, фикс. (необязательно)',`account-fixed-${seq}`,'number',a.fixed_income??'','min="0" max="1000000000000" step="0.01" inputmode="decimal" placeholder="Сверх процента"')}</div><label class="field project-account-cap">Капитализация личного баланса<select name="account-cap-${seq}"><option value="inherit" ${a.capitalization==null?'selected':''}>Как в проекте</option><option value="on" ${a.capitalization===true?'selected':''}>Включена</option><option value="off" ${a.capitalization===false?'selected':''}>Выключена</option></select></label><div class="project-account-cap-date" ${a.capitalization===false?'hidden':''}>${field('Начать с даты',`account-cap-from-${seq}`,'date',a.capitalization_from||'')}</div><label class="check bonus-toggle"><input type="checkbox" data-bonus-toggle ${a.bonus_amount?'checked':''}>Бонусный баланс</label><div class="bonus-fields" ${a.bonus_amount?'':'hidden'}>${field('Сумма бонуса',`account-bonus-${seq}`,'number',a.bonus_amount??'','min="0" max="1000000000000" step="0.01" inputmode="decimal"')}<div>${field('Бонус действует до',`account-bonus-expiry-${seq}`,'datetime-local',localDateTime(a.bonus_expires_at),'')}</div><label class="check"><input type="checkbox" name="account-bonus-cap-${seq}" ${a.bonus_capitalization?'checked':''}>Капитализация бонуса</label></div></div>`;}
function projectFormTotals(){const form=$('.project-form');if(!form)return;const currency=$('[name="currency"]',form)?.value||'USD',capitalization=$('[name="capitalization"]',form),dateField=$('[name="capitalization_from"]',form);let total=0;for(const row of form.querySelectorAll('.project-form-account')){total+=Number($('input[name^="account-amount-"]',row).value)||0;const cap=$('select[name^="account-cap-"]',row),date=$('input[name^="account-cap-from-"]',row);if(cap){const enabled=cap.value==='on'||(cap.value==='inherit'&&capitalization.checked);row.querySelector('.project-account-cap-date').hidden=!enabled;date.disabled=cap.value==='inherit';}}const fixed=$('[name="income_mode"]',form).value==='fixed';form.classList.toggle('fixed',fixed);$('[name="rate_percent"]',form).required=!fixed;$('[name="fixed_income"]',form).required=fixed;dateField.disabled=!capitalization.checked||fixed;dateField.parentElement.hidden=!capitalization.checked||fixed;if(form.querySelector('.project-form-account'))$('.project-form-total',form).innerHTML=`<div><small>Вложено</small><b>${projectMoney(total,currency)}</b></div>`;}

function acceptProject(p){state.projects=state.projects?.some(x=>x.id===p.id)?state.projects.map(x=>x.id===p.id?p:x):[...(state.projects||[]),p];state.projectsError='';viewCache.clear();render();}
async function projectEditor(original=null){
 let draft=original?structuredClone(original):{name:'',currency:'USD',rate_percent:'',income_mode:'percent',fixed_income:'',period:'month',business_days_only:false,multi:false,capitalization:false,capitalization_from:new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk'}).format(new Date()),income_from:'',accounts:[{name:'',amount:'',capitalization:null}]},error='';
 while(true){
  const body=`<div class="project-form">${error?notice(error,true):''}${field('Название','name','text',draft.name,'required maxlength="96"')}${original?'':`<label class="field">Валюта<select name="currency">${['USD','RUB','BYN'].map(cur=>`<option ${cur===draft.currency?'selected':''}>${cur}</option>`).join('')}</select></label>`}<label class="field">Доходность задана<select name="income_mode"><option value="percent" ${draft.income_mode!=='fixed'?'selected':''}>Процентом</option><option value="fixed" ${draft.income_mode==='fixed'?'selected':''}>Фиксированной суммой</option></select></label><div class="field-row"><div class="income-percent">${field('Доходность, %','rate_percent','number',draft.rate_percent,'min="0" max="1000" step="0.0001" inputmode="decimal"')}</div><div class="income-fixed">${field('Сумма за период','fixed_income','number',draft.fixed_income??'','min="0.01" max="1000000000000" step="0.01" inputmode="decimal"')}</div><label class="field">Период<select name="period">${Object.entries(PROJECT_PERIODS).map(([id,label])=>`<option value="${id}" ${id===draft.period?'selected':''}>В ${label}</option>`).join('')}</select></label></div><label class="field daily-accrual-setting" ${draft.period==='day'?'':'hidden'}>Начисление<select name="business_days_only"><option value="0" ${!draft.business_days_only?'selected':''}>Каждый день</option><option value="1" ${draft.business_days_only?'selected':''}>Только по будням</option></select></label><label class="check cap-row"><input type="checkbox" name="capitalization" ${draft.capitalization?'checked':''}>Капитализация проекта</label><div class="project-cap-from">${field('Начать с даты','capitalization_from','date',draft.capitalization_from||'')}</div><div class="project-income-from">${field('Начисления с даты (необязательно)','income_from','date',draft.income_from||'')}<p class="project-form-note">До этой даты доход не прибавляется к балансу. Можно выбрать будущую дату.</p></div>${original?`<p class="project-form-note">Аккаунты проекта редактируются в разделе «Аккаунты» на странице проекта.</p><div class="project-form-total" aria-live="polite"><div><small>Вложено</small><b>${projectMoney(original.total,original.currency)}</b></div><div><small>Аккаунтов</small><b>${original.accounts.length}</b></div></div>`:`<div class="project-form-accounts">${draft.accounts.map((a,i)=>projectFormAccount({...a,capitalization_from:a.capitalization_from||(a.capitalization===true?draft.capitalization_from:'')},i)).join('')}</div><p class="project-form-note">Остальные аккаунты можно добавить на странице проекта.</p><div class="project-form-total" aria-live="polite"></div>`}</div>`;
  const pending=dialog(original?'Редактировать проект':'Добавить проект',body);projectFormTotals();const values=await pending;if(!values)return;
  draft={name:values.name,currency:original?original.currency:values.currency,income_mode:values.income_mode==='fixed'?'fixed':'percent',fixed_income:values.income_mode==='fixed'?Number(values.fixed_income):null,rate_percent:values.income_mode==='fixed'?0:Number(values.rate_percent),period:values.period,business_days_only:values.business_days_only==='1',multi:original?original.multi:false,capitalization:values.capitalization==='on',income_from:values.income_from||null,capitalization_from:values.capitalization_from||original?.capitalization_from||new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk'}).format(new Date()),accounts:original?undefined:[...document.querySelectorAll('.project-form-account')].map(row=>({...(row.dataset.id?{id:row.dataset.id}:{}),name:values[`account-name-${row.dataset.index}`]||'',amount:Number(values[`account-amount-${row.dataset.index}`]),rate_percent:values[`account-rate-${row.dataset.index}`]===''?null:Number(values[`account-rate-${row.dataset.index}`]),fixed_income:values[`account-fixed-${row.dataset.index}`]===''?null:Number(values[`account-fixed-${row.dataset.index}`]),capitalization:values[`account-cap-${row.dataset.index}`]==='inherit'?null:values[`account-cap-${row.dataset.index}`]==='on',capitalization_from:values[`account-cap-${row.dataset.index}`]==='inherit'?null:values[`account-cap-from-${row.dataset.index}`]||null}))};
  if(!original)draft.accounts=draft.accounts.map((account,index)=>{const row=document.querySelectorAll('.project-form-account')[index],seq=row?.dataset.index,amount=Number($(`input[name="account-bonus-${seq}"]`,row)?.value||0),expires=$(`input[name="account-bonus-expiry-${seq}"]`,row)?.value;return {...account,bonus_amount:amount>0?amount:null,bonus_expires_at:isoOrNull(expires),bonus_capitalization:$(`input[name="account-bonus-cap-${seq}"]`,row)?.checked||false,bonus_activated_at:original?.accounts.find(a=>a.id===account.id)?.bonus_activated_at||null};});
  try{const p=await api('/projects'+(original?'/'+original.id:''),{method:original?'PATCH':'POST',body:JSON.stringify(draft)});acceptProject(p);location.hash='project/'+p.id;toast('Проект сохранён');return;}catch(exc){error=exc.message;}
 }
}
async function projectAccountEditor(p,a=null){let draft=a?{capOn:a.capitalization??p.capitalization,name:a.name,amount:a.amount,rate_percent:a.rate_percent??'',capitalization:a.capitalization,capitalization_from:a.capitalization_from||'',fixed_income:a.fixed_income??'',income_from:a.income_from||'',bonus_amount:a.bonus_amount??'',bonus_expires_at:localDateTime(a.bonus_expires_at),bonus_capitalization:!!a.bonus_capitalization}:{capOn:!!p.capitalization,name:'',amount:'',rate_percent:'',fixed_income:'',income_from:'',bonus_amount:'',bonus_expires_at:'',bonus_capitalization:false,capitalization:null,capitalization_from:new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk'}).format(new Date())},error='';while(true){const body=`${error?notice(error,true):''}${field('Название (необязательно)','name','text',draft.name,'maxlength="96"')}${field(`Сумма, ${p.currency}`,'amount','number',draft.amount,'required min="0.01" max="1000000000000" step="0.01" inputmode="decimal"')}${field('Своя ставка, % (необязательно)','rate_percent','number',draft.rate_percent,`min="0" max="1000" step="0.0001" inputmode="decimal" placeholder="Ставка проекта: ${number(p.rate_percent)}%"`)}${field(`Доплата за ${PROJECT_PERIODS[p.period]}, ${p.currency} (необязательно)`,'fixed_income','number',draft.fixed_income,'min="0" max="1000000000000" step="0.01" inputmode="decimal" placeholder="Сверх процента"')}${field('Начисления с даты (необязательно)','income_from','date',draft.income_from,'')}<p class="project-form-note">Пусто — как у проекта${p.income_from?` (${esc(date(p.income_from))})`:''}.</p><label class="check cap-switch"><input type="checkbox" name="capitalization" ${draft.capOn?'checked':''}>Капитализация</label><div class="account-cap-date" data-needs="${(!p.capitalization||(a&&a.capitalization===true))?'1':'0'}" ${draft.capOn&&(!p.capitalization||(a&&a.capitalization===true))?'':'hidden'}>${field('Начать с даты','capitalization_from','date',draft.capitalization_from||p.capitalization_from)}</div>${`<label class="check bonus-toggle"><input type="checkbox" data-bonus-toggle ${draft.bonus_amount?'checked':''}>Бонусный баланс</label><div class="bonus-fields" ${draft.bonus_amount?'':'hidden'}>${field('Сумма бонуса','bonus_amount','number',draft.bonus_amount,'min="0" max="1000000000000" step="0.01" inputmode="decimal"')}<div>${field('Бонус действует до','bonus_expires_at','datetime-local',draft.bonus_expires_at,'')}</div><label class="check"><input type="checkbox" name="bonus_capitalization" ${draft.bonus_capitalization?'checked':''}>Капитализация бонуса</label></div>`}${a?`<div class="pa-pause">${button('project-account-pause',a.paused?'Возобновить аккаунт':'Поставить аккаунт на паузу','secondary small','',`data-id="${esc(p.id)}" data-account="${esc(a.id)}"`)}<small>${a.paused?`На паузе с ${esc(date(a.paused_at))}: не входит в баланс и доход проекта`:'Пауза исключает аккаунт из баланса и дохода, начисления стоят'}</small></div>`:''}${a&&p.accounts.length>1?`<div class="guest-danger">${button('project-account-delete','Удалить аккаунт','danger small','',`data-id="${esc(p.id)}" data-account="${esc(a.id)}"`)}</div>`:''}`;const values=await dialog(a?'Редактировать аккаунт':'Добавить аккаунт',body);if(!values)return;draft={name:values.name,amount:Number(values.amount),rate_percent:values.rate_percent===''?null:Number(values.rate_percent),fixed_income:values.fixed_income===''?null:Number(values.fixed_income),income_from:values.income_from||null,bonus_amount:Number(values.bonus_amount)>0?Number(values.bonus_amount):null,bonus_expires_at:values.bonus_expires_at||'',bonus_capitalization:values.bonus_capitalization==='on',capitalization:null,capitalization_from:null};const capOn=values.capitalization==='on',initialOn=a?(a.capitalization??p.capitalization):!!p.capitalization;if(a&&capOn===!!initialOn){draft.capitalization=a.capitalization;draft.capitalization_from=a.capitalization===true?(values.capitalization_from||a.capitalization_from||projectToday()):null;}else if(capOn===!!p.capitalization){draft.capitalization=null;draft.capitalization_from=null;}else{draft.capitalization=capOn;draft.capitalization_from=capOn?(values.capitalization_from||projectToday()):null;}draft.capOn=capOn;try{const expires=draft.bonus_expires_at?new Date(draft.bonus_expires_at):null;if(expires&&Number.isNaN(expires.getTime()))throw new Error('Некорректная дата окончания бонуса');const payload={...draft,capOn:undefined,bonus_expires_at:draft.bonus_amount&&expires?expires.toISOString():null,bonus_activated_at:draft.bonus_amount?(a?.bonus_activated_at||null):null,bonus_capitalization:draft.bonus_amount?draft.bonus_capitalization:false};const saved=await api(`/projects/${p.id}/accounts${a?'/'+a.id:''}`,{method:a?'PATCH':'POST',body:JSON.stringify(payload)});acceptProject(saved);toast('Аккаунт сохранён');return;}catch(exc){error=exc.message;}}}
async function projectAction(action,el){
  if(action==='project-create')return projectEditor();
 const p=state.projects?.find(p=>p.id===el.dataset.id);if(!p)throw new Error('Проект не найден');
 if(action==='project-edit')return projectEditor(p);
 if(action==='project-pause'){acceptProject(await api(`/projects/${p.id}/pause`,{method:'POST',body:JSON.stringify({paused:!p.paused})}));toast(p.paused?'Проект снова считается':'Проект на паузе');return;}
 if(action==='project-delete'){if(await confirm(`Удалить проект «${p.name}»?`,'Проект и его аккаунты исчезнут из вашего списка.','Удалить')){await api('/projects/'+p.id,{method:'DELETE'});state.projects=state.projects.filter(x=>x.id!==p.id);viewCache.clear();location.hash='projects';render();toast('Проект удалён');}return;}
 if(action==='project-account-add'){el.hidden=true;try{await projectAccountEditor(p);}finally{el.hidden=false;}return;}
 const a=p.accounts.find(a=>a.id===el.dataset.account);if(!a)throw new Error('Аккаунт не найден');
 if(action==='project-account-edit')return projectAccountEditor(p,a);
 if(action==='project-account-pause'){if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;acceptProject(await api(`/projects/${p.id}/accounts/${a.id}/pause`,{method:'POST',body:JSON.stringify({paused:!a.paused})}));toast(a.paused?'Аккаунт снова считается':'Аккаунт на паузе');return;}
 if(action==='project-account-delete'){if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;if(p.accounts.length===1)throw new Error('Последний аккаунт удаляется вместе с проектом');const title=a.name||`Аккаунт ${p.accounts.indexOf(a)+1}`;if(await confirm(`Удалить аккаунт «${title}»?`,'Итог проекта будет пересчитан.','Удалить'))acceptProject(await api(`/projects/${p.id}/accounts/${a.id}`,{method:'DELETE'}));}
}
document.addEventListener('input',event=>{if(event.target.closest('.project-form'))projectFormTotals();});
document.addEventListener('change',event=>{if(event.target.matches('.project-form [name="period"]'))event.target.closest('.project-form').querySelector('.daily-accrual-setting').hidden=event.target.value!=='day';if(event.target.matches('.project-form [name="capitalization"]')&&event.target.checked)event.target.closest('.project-form').querySelector('[name="capitalization_from"]').value=projectToday();if(event.target.matches('.project-form select[name^="account-cap-"]')&&event.target.value==='on')event.target.closest('.project-form-account').querySelector('.project-account-cap-date input').value=projectToday();if(event.target.matches('.project-form select,.project-form input,.project-form [name="period"]'))projectFormTotals();if(event.target.matches('#dialog .cap-switch input')){const box=$('#dialog .account-cap-date');if(box){box.hidden=!(event.target.checked&&box.dataset.needs==='1');const date=box.querySelector('input');if(event.target.checked&&date&&!date.value)date.value=projectToday();}}});
async function addAccount(){
 const known=[...new Set(state.data.accounts.filter(a=>!a.shared).map(a=>a.cabinet).filter(Boolean))];
 const choice=known.length?`<label class="field">Кабинет<select name="cabinet_choice" id="add-cabinet-choice">${known.map(c=>{const owner=state.data.accounts.find(a=>a.cabinet===c)?.holder;return `<option value="${esc(c)}">${esc(owner?`${owner} · ${c}`:c)}</option>`;}).join('')}<option value="new">Другой кабинет…</option></select></label><div id="add-new-cabinet" hidden>${field('Customer Number нового кабинета','cabinet','text','','required disabled maxlength="32" placeholder="Например, CU228816"')}</div>`:field('Customer Number кабинета','cabinet','text','','required maxlength="32" placeholder="Например, CU228816"');
 const form=`<p>Используйте инвесторский пароль MT5: он даёт доступ к просмотру.</p>${choice}${field('Название стратегии','name','text','','required maxlength="48" placeholder="Например, SONIC или NEO"')}${field('Номер счёта MT5','login','number','','required min="1" step="1" placeholder="Например, 10001234"')}${field('Инвесторский пароль','password','password','','required maxlength="128" autocomplete="new-password" placeholder="Пароль инвестора MT5"')}<div class="auto-field"><span>Сервер и владелец</span><b>Определятся автоматически</b><small>После первой синхронизации с MT5</small></div><a class="text-link account-help" href="#faq/connect" data-action="account-help">Как открыть счёт ${icon('arrow')}</a>`;
 const data=await dialog('Подключить счёт MT5',form,'Подключить');if(!data)return;
 if(known.length){data.cabinet=data.cabinet_choice==='new'?data.cabinet:data.cabinet_choice;delete data.cabinet_choice;}
 await mutate('/accounts',data);location.hash='accounts';
}
async function configureAccount(login){const a=state.data.accounts.find(a=>Number(a.login)===Number(login));if(!a)return;const capital=!a.shared?`${field('Капитал Invested','base','number',a.base??'','min="0" max="1000000000000" step="0.01"')}<p class="stat-note">Если указать сумму из портала, она станет основой расчёта капитала. Дальнейшие пополнения и выводы прибавятся автоматически.</p>${a.base!=null?'<label class="check"><input type="checkbox" name="reset_base"> Вернуть автоматический расчёт</label>':''}`:'';const body=`${field('Название стратегии','name','text',a.strategy||a.name,'required maxlength="48"')}${a.shared?'':`<label class="check"><input type="checkbox" name="enabled" ${a.enabled?'checked':''}>Отслеживать счёт</label>`}${[['all','Все уведомления'],['trades','Сделки'],['deposits','Пополнения'],['withdrawals','Выводы']].map(([k,v])=>`<label class="check"><input type="checkbox" name="${k}" ${a.notify?.[k]!==false?'checked':''}>${v}</label>`).join('')}${capital}<div class="inline-actions mt">${button('delete-account','Удалить счёт из кабинета','danger small','',`data-login="${esc(a.login)}"`)}</div><p class="stat-note">Счёт у брокера и терминал останутся без изменений.</p>`;const values=await dialog('Настройки счёта',body);if(!values)return;const data={...(a.shared?{}:{enabled:values.enabled==='on'}),notify:Object.fromEntries(['all','trades','deposits','withdrawals'].map(k=>[k,values[k]==='on']))};if(values.name)data.name=values.name;if(values.reset_base==='on')data.base=null;else if(values.base!==''&&values.base!==undefined&&Number(values.base)!==a.base)data.base=Number(values.base);await mutate(`/accounts/${a.login}`,data,'PATCH');}
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action]');if(!el)return;event.preventDefault();const action=el.dataset.action;if(el.disabled)return;el.disabled=true;try{
 if(action.startsWith('project-'))await projectAction(action,el);
 else if(/^(activity|lists|cal|note|event|task)-/.test(action))await sectionAction(action,el);
 else if(/^(home|sync)-/.test(action))await stationAction(action,el);
 else if(action.startsWith('bank-'))await bankAction(action,el);
 else if(action.startsWith('spend-'))await spendAction(action,el);
 else if(action.startsWith('income-'))await incomeAction(action,el);
 else if(action.startsWith('goal-'))await goalAction(action,el);
 else if(/^(friend|split)-/.test(action))await friendAction(action,el);
 else if(action==='onboard-hide'){try{localStorage.setItem('fin-onboard-hidden','1');}catch{}render(true);}
 else if(action==='fab-toggle')fabToggle();
 else if(action==='refresh')await refresh();
 else if(action==='notifications')await openNotifications();
 else if(action==='notification-open')await openNotification(el.dataset.id);
 else if(action==='notifications-read')await readAllNotifications(); else if(action==='notif-filter'){state.notifFilter=el.dataset.value||'all';const body=$('#dialog-body');if(body&&$('#dialog').open)body.innerHTML=notificationPanel();}
 else if(action==='scheme')setScheme(el.dataset.value);
 else if(action==='renew-link'){if(await confirm('Обновить ссылку?','Прежняя перестанет работать. Уже вошедшие гости останутся.','Обновить')){const token=String(state.people.link||'').split('start=')[1];await api('/invites/'+token,{method:'DELETE'});await refresh();toast('Ссылка обновлена');}}
 else if(action==='share-accounts'){const g=state.people.guests.find(x=>x.id===el.dataset.guest),have=new Set(g.accounts.filter(a=>a.shared).map(a=>String(a.login))),list=(state.people.shareable||[]).filter(a=>!have.has(String(a.login)));const d=await dialog('Открыть счета гостю',`${list.map(a=>{const acc=state.data.accounts.find(x=>String(x.login)===String(a.login));return `<label class="check share-row"><input name="login-${a.login}" type="checkbox"><span><b>${esc(a.name)} · ${esc(a.login)}</b><small>${esc([acc?.holder,a.cabinet].filter(Boolean).join(' · '))}</small></span></label>`;}).join('')}<p class="stat-note">Гость увидит их только для просмотра.</p>`,'Открыть');if(d){const logins=Object.keys(d).filter(k=>k.startsWith('login-')).map(k=>Number(k.slice(6)));if(logins.length)await mutate('/guests/'+el.dataset.guest,{action:'share',logins});}}
 else if(action==='toast-close')$('#toast').classList.remove('visible');
 else if(action==='shortcut')await addShortcut();
 else if(action==='onboard-open'||action==='onboard-resume')showAccountGuide(true);
 else if(action==='onboard-close')showAccountGuide(false);
 else if(action==='onboard-later'){if(!preview)await api('/onboarding',{method:'POST',body:JSON.stringify({step:'later',done:true})});state.data.onboarding.later=true;location.hash='tagmarket';}
 else if(action==='faq-image'){await dialog(el.dataset.alt||'Скриншот',`<img class="faq-full" src="${esc(el.dataset.src)}" alt="${esc(el.dataset.alt||'')}">`,'Закрыть');}
 else if(action==='chart-zoom'){const v=el.dataset.value;if(v==='reset'){chartView.key='';scheduleChart();}else chartZoom(v==='in'?.7:1/.7);}
 else if(action==='period'){if(state.period===el.dataset.value)return;state.period=el.dataset.value;state.offset=0;state.report=null;state.reportError='';if(state.period==='custom')render();else await showCached(el);}
 else if(action==='kind'){state.kind=el.dataset.value;state.offset=0;await showCached(el);}
 else if(action==='next'||action==='prev'){state.offset=Math.max(0,state.offset+(action==='next'?50:-50));await showCached();}
 else if(action==='apply-period'){state.from=$('#from-date').value;state.to=$('#to-date').value;if(!state.from||!state.to||state.from>state.to)throw new Error('Укажите корректные даты начала и конца');await showCached();}
 else if(action==='account-help'){if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;location.hash='faq/connect';}
 else if(action==='add')await addAccount();
 else if(action==='onboard-step')await mutate('/onboarding',{step:el.dataset.step,done:true});
 else if(action==='account-settings')await configureAccount(el.dataset.login);
 else if(action==='delete-account'){if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;if(await confirm('Удалить счёт?','Он исчезнет из вашего приложения и бота. Торговый счёт у брокера останется.','Удалить')){await mutate(`/accounts/${el.dataset.login}`,undefined,'DELETE');location.hash='accounts';}}
 else if(action==='restart'){if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;if(await confirm('Перезапустить терминал?','Это общий терминал агента. Опрос остальных счетов кратковременно прервётся.','Перезапустить'))await mutate('/actions',{action:'restart',login:Number(el.dataset.login)});}
 else if(action==='copy'){try{await navigator.clipboard.writeText(el.dataset.text);toast('Ссылка скопирована');}catch{throw new Error('Не удалось скопировать автоматически. Выделите и скопируйте ссылку.');}}
 else if(action==='guest-detail'){const r=await api('/guests/'+el.dataset.guest);await dialog('Карточка гостя',`<div class="report-text">${esc(r.report)}</div>`,'Готово');}
 else if(action==='revoke-guest'){if(await confirm('Закрыть доступ гостю?','Ваши переданные счета исчезнут у гостя. Его личные счета и доступ к собственному кабинету сохранятся.','Закрыть доступ'))await mutate('/guests/'+el.dataset.guest,{action:'revoke'});}
 else if(action==='take'){if(await confirm('Забрать счёт у гостя?','Остальные счета гостя сохранятся.'))await mutate('/guests/'+el.dataset.guest,{action:'take',login:Number(el.dataset.login)});}
 else if(action==='alerts')await mutate('/actions',{action:'update_alerts',value:!state.data.update_alerts});
 else if(action==='leave'){if(await confirm('Отключить доступ?','Счета и приглашения в боте будут удалены. Для возвращения понадобится новое приглашение.','Отключить')){await api('/actions',{method:'POST',body:JSON.stringify({action:'leave'})});state.data=null;await refresh();}}
 else if(action==='broadcast'){
  const users=state.admin?.users||[];
  if(!users.length)throw new Error('Пока нет приглашённых пользователей для рассылки');
  let draft={target:'all',text:'',buttonOn:false,buttonText:'Открыть приложение',file:null,error:''},kind=null;
  for(;;){
   const d=await dialog('Сообщение пользователям',composerBody(users,draft),'Проверить',{validate:composerValidate,onOpen:()=>composerRestore(draft)});
   if(!d)return;
   const file=d.media?.size?d.media:null;
   draft={target:d.target||'all',text:d.text||'',buttonOn:d.with_button==='on',buttonText:String(d.button_text||'').trim()||'Открыть приложение',file,error:''};
   kind=file?await mediaKind(file):null;
   if(file&&!kind){draft={...draft,file:null,error:'Выберите JPG, PNG или MP4 (файл не похож на фото или видео)'};continue;}
   const buttonLabel=draft.buttonOn?draft.buttonText.slice(0,40):'';
   const recipient=draft.target==='all'?`все приглашённые (${users.length})`:users.find(u=>String(u.id)===String(draft.target))?.name||'пользователь';
   const objectUrl=file?URL.createObjectURL(file):null;
   let confirmed;
   try{
    const media=file?`<div class="compose-preview-media">${kind==='photo'?`<img src="${esc(objectUrl)}" alt="Приложенное фото">`:`<video src="${esc(objectUrl)}" controls preload="metadata"></video>`}<small>${esc(file.name)} · ${fileSize(file.size)}</small></div>`:'';
    const body=`<p class="compose-recipient">Кому: <b>${esc(recipient)}</b></p><div class="cmp-bubble cmp-review"><b class="cmp-bubble-name">Platformer</b>${media}<div class="compose-preview-text">${draft.text?broadcastPreview(draft.text):'<span class="muted">Без подписи</span>'}</div><small class="cmp-bubble-time">сейчас</small></div>${buttonLabel?`<div class="cmp-bubble-btn">${esc(buttonLabel)}</div>`:''}<p class="compose-footnote">Проверьте сообщение перед отправкой: после неё его нельзя отозвать.</p>`;
    confirmed=await dialog('Проверка рассылки',body,'Отправить',{cancelLabel:'Назад'});
   }finally{if(objectUrl)URL.revokeObjectURL(objectUrl);}
   if(confirmed)break;       // «Назад» (или закрытие окна проверки) возвращает в сообщение с тем же текстом, файлом и выбором
  }
  const file=draft.file,buttonText=draft.buttonOn?draft.buttonText.slice(0,40):'';
  if(preview){await dialog('Демо-режим',`<p>Макет показывает редактор и вложение, но не отправляет сообщения. Для настоящей рассылки откройте приложение из <a href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">бота в Telegram</a>.</p>`,'Понятно');return;}
  const requestId=crypto.randomUUID();
  for(;;){
   const form=new FormData();form.append('target',draft.target);form.append('text',draft.text||'');form.append('request_id',requestId);if(buttonText)form.append('button_text',buttonText);if(file)form.append('media',file);
   let result;
   try{result=await api('/broadcast',{method:'POST',body:form});}
   catch(error){if(!await dialog('Отправка не завершена',`<p>${esc(error.message)}</p><p class="stat-note">Повтор с тем же сообщением не отправит его заново тем, кому оно уже доставлено.</p>`,'Проверить и повторить'))return;continue;}
   const blocked=(result.unreachable||[]),done=`<div class="compose-status"><span>Доставлено</span><strong>${result.sent}</strong></div>${result.failed?`<div class="compose-status is-error"><span>Ожидают повторной отправки</span><strong>${result.failed}</strong></div>`:''}${blocked.length?`<div class="compose-status is-warn"><span>Не получили: заблокировали бота</span><strong>${blocked.length}</strong></div><p class="stat-note">${blocked.map(b=>esc(b.name)).join(', ')}. Пока человек не разблокирует бота, сообщение до него не дойдёт — повторять отправку не нужно.</p>`:''}`;
   if(!result.failed){await dialog('Сообщение отправлено',done,'Готово');return;}
   if(!await dialog('Отправлено частично',`${done}<p class="stat-note">Уже доставленные сообщения повторно не отправятся.</p>`,'Повторить недоставленным'))return;
  }
 }
 }catch(error){toast(error.message);}finally{el.disabled=false;}});
document.addEventListener('click',event=>{const tool=event.target.closest('[data-format]');if(!tool)return;event.preventDefault();const area=$('#dialog textarea[name="text"]');if(!area)return;const start=area.selectionStart,end=area.selectionEnd,selected=area.value.slice(start,end);const tags={bold:['<b>','</b>'],italic:['<i>','</i>'],mono:['<code>','</code>'],quote:['<blockquote>','</blockquote>']}[tool.dataset.format];if(!tags)return;area.setRangeText(tags[0]+selected+tags[1],start,end,'end');area.focus();area.setSelectionRange(start+tags[0].length,start+tags[0].length+selected.length);area.dispatchEvent(new Event('input',{bubbles:true}));});
document.addEventListener('input',event=>{if(event.target.matches('#dialog textarea[name="text"]')){const area=event.target,preview=$('#compose-live'),count=$('#compose-count');if(preview)preview.innerHTML=area.value?broadcastPreview(area.value):'<span class="muted">Сообщение появится здесь</span>';const length=broadcastLength(area.value);if(count){count.textContent=`${length} / 4096`;count.classList.toggle('over',length>4096);}const meter=$('#compose-meter');if(meter){meter.style.width=`${Math.min(100,length/4096*100).toFixed(1)}%`;meter.classList.toggle('warn',length>3600);}const clear=$('[data-cmp-clear]');if(clear)clear.hidden=!area.value;}});
 document.addEventListener('change',async event=>{try{if(event.target.matches('#dialog input[name="media"]')){const info=$('#compose-file-name');if(info)info.textContent=event.target.files?.[0]?`${event.target.files[0].name} · ${fileSize(event.target.files[0].size)}`:'JPG/PNG до 10 МБ · MP4 до 20 МБ';}if(event.target.id==='add-cabinet-choice'){const fresh=$('#add-new-cabinet');fresh.hidden=event.target.value!=='new';fresh.querySelector('input').disabled=fresh.hidden;}if(event.target.id==='account-select'){state.login=Number(event.target.value);state.offset=0;if(state.view==='account'){location.hash='account/'+state.login;}else await refresh();}if(event.target.id==='currency'){state.currency=event.target.value;await showCached();}}catch(error){toast(error.message);}});
$('#notifications').innerHTML=icon('bell');$('#settings-link').innerHTML=icon('settings');$('#refresh').innerHTML=icon('refresh');$('#refresh').addEventListener('click',()=>refresh());
let savedScheme;try{savedScheme=localStorage.getItem('tag-scheme');}catch{}setScheme(savedScheme||'lime',false);
try{tg?.ready();tg?.expand();tg?.BackButton?.onClick(()=>{if($('#dialog').open){requestDialogExit($('#dialog'));return;}location.hash=state.view==='project'?'projects':'accounts';});tg?.onEvent('homeScreenAdded',()=>toast('Ярлык Platformer добавлен на экран'));tg?.onEvent('homeScreenChecked',e=>{if(e?.status==='added')toast('Ярлык уже добавлен');});tg?.onEvent('homeScreenFailed',()=>toast('Telegram не смог добавить ярлык'));}catch{}
window.addEventListener('hashchange',navigate);
// подсветка вкладки следует за размерами панели: смена ориентации, переход
// через 740px (боковая ↔ нижняя), свёрнутая боковая панель — без анимации
if(window.ResizeObserver){const watcher=new ResizeObserver(entries=>entries.forEach(e=>moveGlider(e.target,true)));NAV_ROOTS.forEach(s=>watcher.observe($(s)));}
else window.addEventListener('resize',()=>NAV_ROOTS.forEach(s=>moveGlider($(s),true)));
// лёгкий отклик Telegram на смену вкладки — как у родных панелей
document.addEventListener('click',event=>{const link=event.target.closest('nav a[data-tab]');if(link&&!link.classList.contains('active'))try{tg?.HapticFeedback?.selectionChanged();}catch{}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh(true);});
 // интервал фонового обновления задаёт сервер (refresh_seconds в /api/bootstrap);
 // не чаще раза в 30 секунд — каждый круг это четыре запроса и перерисовка
 function scheduleRefresh(){const every=refreshEvery();if(scheduleRefresh.every===every)return;scheduleRefresh.every=every;clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden){if($('#dialog').open)quietPending=true;else refresh(true);}},every);}
 navigate();scheduleRefresh();

function networkView(){return `<div class="section-head"><h2>Доход партнёрской сети</h2></div><section class="panel"><p class="stat-note">По событиям портала · последние 30 дней с начислениями · валюта портала</p><div class="table-wrap"><table class="table"><thead><tr><th>Дата</th><th>Сделок сети</th><th>Начислено</th></tr></thead><tbody>${state.admin.network.map(d=>`<tr><td>${esc(d.day)}</td><td>${number(d.trades)}</td><td class="positive">${number(d.income)}</td></tr>`).join('')}</tbody></table></div></section>`;}
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action="partner-link"]');if(!el)return;event.preventDefault();const current=state.data?.onboarding?.partner_url||'';const body=`<div class="pl-dialog"><div class="pl-hero"><span class="pl-hero-ico">${icon('link')}</span><div><b>Ваша партнёрская ссылка</b><small>По ней гости регистрируются в IB Portal и попадают к вам</small></div></div><ol class="pl-steps"><li><span>1</span><div><b>Откройте IB Portal</b><small>Войдите в личный кабинет партнёра</small></div></li><li><span>2</span><div><b>Раздел Partner</b><small>Скопируйте свою партнёрскую ссылку</small></div></li><li><span>3</span><div><b>Вставьте ссылку ниже</b><small>И нажмите «Сохранить»</small></div></li></ol><a class="button primary wide pl-portal" href="https://exfusion.ibportal.io" target="_blank" rel="noopener">Открыть IB Portal ${icon('arrow')}</a><label class="field pl-field"><span>Партнёрская ссылка</span><span class="pl-input"><input name="url" type="url" value="${esc(current)}" required autocomplete="off" inputmode="url" placeholder="https://exfusion.ibportal.io/auth/register?..." /><button type="button" class="pl-paste" aria-label="Вставить из буфера">${icon('copy')}<span>Вставить</span></button></span><small class="pl-hint" aria-live="polite"></small></label></div>`;const values=await dialog('Моя партнёрская ссылка',body,'Сохранить');if(!values)return;if(preview){await dialog('Демо-режим','<p>Персональная ссылка сохранится после входа через бота в Telegram. Здесь можно проверить вид формы без изменения вашего кабинета.</p>','Понятно');return;}try{const saved=await api('/profile/partner-link',{method:'PUT',body:JSON.stringify({url:values.url})});state.data.onboarding.partner_url=saved.url;toast('Партнёрская ссылка сохранена');render();}catch(error){toast('Ссылка не принята: проверьте адрес из блока Partner.');}});




// Тень под верхней панелью — только когда под неё что-то уехало. Следим
// маячком через IntersectionObserver, а не обработчиком scroll: тот на каждый
// кадр прокрутки спрашивал бы позицию и заставлял пересчитывать вёрстку.
(function watchScroll(){
 const bar=document.querySelector('.topbar');
 if(!bar||!window.IntersectionObserver)return;
 const mark=document.createElement('span');
 mark.setAttribute('aria-hidden','true');
 mark.style.cssText='position:absolute;top:0;left:0;width:1px;height:1px;pointer-events:none';
 bar.parentNode.insertBefore(mark,bar);
 new IntersectionObserver(([e])=>document.body.classList.toggle('is-scrolled',!e.isIntersecting))
  .observe(mark);
})();

document.addEventListener('click',async event=>{const btn=event.target.closest('.pl-paste');if(!btn)return;const input=btn.closest('.pl-input')?.querySelector('input');if(!input)return;try{const text=(await navigator.clipboard.readText()).trim();if(!text)throw new Error('empty');input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();}catch{toast('Не удалось прочитать буфер. Вставьте ссылку в поле вручную.');input.focus();}});
document.addEventListener('input',event=>{const input=event.target.closest?.('.pl-field input');if(!input)return;const hint=input.closest('.pl-field').querySelector('.pl-hint'),value=input.value.trim();let state='',text='';if(value){let ok=false;try{ok=/(^|\.)ibportal\.io$/i.test(new URL(value).hostname);}catch{}state=ok?'ok':'warn';text=ok?'Похоже на ссылку IB Portal':'Это не похоже на ссылку IB Portal — проверьте адрес';}hint.textContent=text;hint.dataset.state=state;});

// Порядок аккаунтов проекта: карточку берут за ручку и перетаскивают. Pointer events —
// работает и мышью, и пальцем; остальные карточки расступаются, при отпускании порядок
// сохраняется одним запросом. Для клавиатуры: Alt+↑ / Alt+↓ на карточке.
let paDrag=null;
async function paSave(card,position){
 try{const saved=await api(`/projects/${card.dataset.id}/accounts/reorder`,{method:'POST',body:JSON.stringify({account_id:card.dataset.account,position})});acceptProject(saved);}
 catch(error){toast(error.message||'Не удалось изменить порядок');render(true);}
}
function paFrame(){
 const d=paDrag;if(!d)return;
 const dy=(d.lastY+scrollY)-(d.startY+d.scroll0),height=d.rects[d.index].height,slot=d.slot;
 d.card.style.transform=`translateY(${dy}px)`;
 const center=d.centers[d.index]+dy;let target=0;
 d.centers.forEach((c,i)=>{if(i!==d.index&&c<center)target++;});
 d.target=target;
 d.cards.forEach((c,i)=>{if(i===d.index)return;const shift=i>d.index&&i<=target?-slot:i<d.index&&i>=target?slot:0;c.style.transform=shift?`translateY(${shift}px)`:'';});
 // у края экрана страница прокручивается сама
 const edge=70,y=d.lastY;if(y<edge)scrollBy(0,-12);else if(y>innerHeight-edge)scrollBy(0,12);
 d.raf=requestAnimationFrame(paFrame);
}
function paFinish(commit){
 const d=paDrag;if(!d)return;paDrag=null;cancelAnimationFrame(d.raf);
 d.cards.forEach(c=>{c.style.transition='none';c.style.transform='';c.classList.remove('is-dragging');});
 document.body.classList.remove('pa-dragging');
 requestAnimationFrame(()=>d.cards.forEach(c=>{c.style.transition='';}));
 d.swallowClickUntil=Date.now()+120;paLastDrag=d;
 if(commit&&d.target!==d.index){
  const list=d.card.parentElement,others=d.cards.filter(c=>c!==d.card);
  list.insertBefore(d.card,others[d.target]||others[d.target-1]?.nextSibling||null);   // порядок на экране сразу, не дожидаясь сервера
  paSave(d.card,d.target+1);
 }
}
let paLastDrag=null;
document.addEventListener('pointerdown',event=>{
 const grip=event.target.closest?.('.pa-grip');if(!grip||paDrag||(event.pointerType==='mouse'&&event.button!==0))return;
 const card=grip.closest('.pa-card'),cards=[...document.querySelectorAll('.pa-card')];if(!card||cards.length<2)return;
 event.preventDefault();
 const rects=cards.map(c=>c.getBoundingClientRect()),index=cards.indexOf(card),scroll0=scrollY;
 const slot=index<cards.length-1?rects[index+1].top-rects[index].top:rects[index].top-rects[index-1].top;
 paDrag={card,cards,index,target:index,rects,slot,scroll0,startY:event.clientY,lastY:event.clientY,pointer:event.pointerId,raf:0,
  centers:rects.map(r=>r.top+scroll0+r.height/2)};
 grip.setPointerCapture?.(event.pointerId);
 card.classList.add('is-dragging');document.body.classList.add('pa-dragging');
 try{tg?.HapticFeedback?.impactOccurred('light');}catch{}
 paDrag.raf=requestAnimationFrame(paFrame);
});
document.addEventListener('pointermove',event=>{if(paDrag&&event.pointerId===paDrag.pointer){paDrag.lastY=event.clientY;event.preventDefault();}},{passive:false});
document.addEventListener('pointerup',event=>{if(paDrag&&event.pointerId===paDrag.pointer)paFinish(true);});
document.addEventListener('pointercancel',event=>{if(paDrag&&event.pointerId===paDrag.pointer)paFinish(false);});
// ручка — не кнопка редактирования: отпускание над ней не должно открывать окно аккаунта
document.addEventListener('click',event=>{if(event.target.closest?.('.pa-grip')||(paLastDrag&&Date.now()<paLastDrag.swallowClickUntil&&event.target.closest?.('.pa-card')===paLastDrag.card)){event.preventDefault();event.stopImmediatePropagation();}},true);
document.addEventListener('keydown',event=>{
 const card=event.target.closest?.('.pa-card');if(!card||!event.altKey||!['ArrowUp','ArrowDown'].includes(event.key))return;
 const cards=[...document.querySelectorAll('.pa-card')],index=cards.indexOf(card),position=index+(event.key==='ArrowUp'?-1:1)+1;
 if(position<1||position>cards.length)return;
 event.preventDefault();paSave(card,position);
});

// Выбор валюты отображения: кнопка в верхней панели и всплывающее меню вместо системного списка.
// Скрытый select остаётся источником значения: на нём уже висит сохранение выбора.
const CURRENCY_INFO=[['USD','Доллар США','$'],['BYN','Белорусский рубль','Br'],['RUB','Российский рубль','₽']];
function syncCurrencyUi(){
 const select=$('#display-currency');if(!select)return;
 const code=select.value||state.displayCurrency||'USD',info=CURRENCY_INFO.find(c=>c[0]===code)||CURRENCY_INFO[0];
 $('#currency-code').textContent=info[0];$('#currency-sym').textContent=info[2];
 document.querySelectorAll('#currency-menu [data-currency]').forEach(item=>{const on=item.dataset.currency===info[0];item.classList.toggle('active',on);item.setAttribute('aria-selected',String(on));});
}
function currencyMenuOpen(open,{focus=false}={}){
 const menu=$('#currency-menu'),button=$('#currency-btn');if(!menu||!button)return;
 if(open&&!menu.children.length)menu.innerHTML=CURRENCY_INFO.map(([code,name,sym])=>`<button type="button" role="option" class="currency-item" data-currency="${code}"><span class="cur-sym">${sym}</span><span class="cur-text"><b>${code}</b><small>${name}</small></span>${icon('check')}</button>`).join('');
 menu.hidden=!open;button.setAttribute('aria-expanded',String(open));
 if(open){syncCurrencyUi();if(focus)(menu.querySelector('.active')||menu.firstElementChild)?.focus();}
}
function currencyPick(code){
 const select=$('#display-currency');if(!select||select.value===code){currencyMenuOpen(false);return;}
 select.value=code;select.dispatchEvent(new Event('change',{bubbles:true}));syncCurrencyUi();currencyMenuOpen(false);$('#currency-btn')?.focus({preventScroll:true});
 try{tg?.HapticFeedback?.selectionChanged();}catch{}
}
document.addEventListener('click',event=>{
 const button=event.target.closest?.('#currency-btn');
 if(button){currencyMenuOpen($('#currency-menu').hidden);return;}
 const item=event.target.closest?.('#currency-menu [data-currency]');
 if(item){currencyPick(item.dataset.currency);return;}
 if(!event.target.closest?.('#currency-picker'))currencyMenuOpen(false);
});
document.addEventListener('keydown',event=>{
 const menu=$('#currency-menu');if(!menu||menu.hidden)return;
 const items=[...menu.querySelectorAll('[data-currency]')],at=items.indexOf(document.activeElement);
 if(event.key==='Escape'){event.preventDefault();currencyMenuOpen(false);$('#currency-btn').focus();}
 else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();items[(at+(event.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}
});
syncCurrencyUi();

// Редактор рассылки: получатели, шаблоны, очистка, вложение
const CMP_TEMPLATES={
 maintenance:'<b>Технические работы</b>\n\nС 03:00 до 03:10 по МСК возможны короткие перерывы в обновлении данных. Торговля на счетах не затрагивается — всё продолжит работать само.',
 feature:'<b>Новое в Platformer</b>\n\nДобавили … Откройте приложение и посмотрите в разделе «…».',
 reminder:'<b>Напоминание</b>\n\n…\n\nЕсли нужна помощь — просто ответьте на это сообщение.',
 thanks:'Спасибо, что вы с нами. Мы продолжаем улучшать приложение и будем держать вас в курсе важных изменений.'
};
function cmpArea(){return $('#dialog textarea[name="text"]');}
document.addEventListener('click',event=>{
 const seg=event.target.closest?.('[data-cmp-target]');
 if(seg){event.preventDefault();const form=seg.closest('.composer'),select=form.querySelector('select[name="target"]'),one=seg.dataset.cmpTarget==='one';
  form.querySelectorAll('[data-cmp-target]').forEach(b=>b.classList.toggle('active',b===seg));
  const box=form.querySelector('.cmp-one');box.hidden=!one;
  [...select.options].forEach(o=>{o.hidden=one&&o.value==='all';});
  select.value=one?(select.options[1]?.value||'all'):'all';return;}
 const chip=event.target.closest?.('[data-template]');
 if(chip){event.preventDefault();const area=cmpArea();if(!area)return;const text=CMP_TEMPLATES[chip.dataset.template]||'';
  area.value=area.value.trim()?`${area.value.replace(/\s+$/,'')}\n\n${text}`:text;area.dispatchEvent(new Event('input',{bubbles:true}));area.focus();area.setSelectionRange(area.value.length,area.value.length);return;}
 if(event.target.closest?.('[data-cmp-clear]')){event.preventDefault();const area=cmpArea();if(area){area.value='';area.dispatchEvent(new Event('input',{bubbles:true}));area.focus();}return;}
 if(event.target.closest?.('[data-cmp-file-clear]')){event.preventDefault();event.stopPropagation();const input=$('#dialog input[name="media"]');if(input){input.value='';input.dispatchEvent(new Event('change',{bubbles:true}));}}
},true);
document.addEventListener('change',event=>{
 if(event.target.matches?.('#dialog input[name="media"]')){const chip=$('#dialog .cmp-file');if(chip)chip.hidden=!event.target.files?.length;$('#dialog .cmp-attach')?.classList.toggle('active',!!event.target.files?.length);}
 if(event.target.matches?.('[data-cmp-button]')){const box=$('#dialog .cmp-button-field');if(box)box.hidden=!event.target.checked;cmpButtonPreview();}
});
function cmpButtonPreview(){const on=$('#dialog [data-cmp-button]')?.checked,preview=$('#compose-btn-preview');if(!preview)return;preview.hidden=!on;preview.textContent=(String($('#dialog input[name="button_text"]')?.value||'').trim()||'Открыть приложение').slice(0,40);}
document.addEventListener('input',event=>{if(event.target.matches?.('#dialog input[name="button_text"]'))cmpButtonPreview();});

// Бонусный баланс: пункт-переключатель. Выключен — полей нет и бонуса нет; выключили — введённое очищается.
document.addEventListener('change',event=>{
 const toggle=event.target.closest?.('[data-bonus-toggle]');if(!toggle)return;
 const box=toggle.closest('label').nextElementSibling;if(!box||!box.classList.contains('bonus-fields'))return;
 box.hidden=!toggle.checked;
 if(!toggle.checked)box.querySelectorAll('input').forEach(input=>{if(input.type==='checkbox')input.checked=false;else input.value='';});
 
});

// Динамика кубиками: выбранный день показывается строкой под рядом
function cubeSelect(cube){
 const box=cube.closest('.cubes')?.parentElement;if(!box)return;
 const detail=box.querySelector('.cube-detail');if(!detail)return;
 let data;try{data=JSON.parse(cube.dataset.cube);}catch{return;}
 box.querySelectorAll('.cube.active').forEach(c=>c.classList.remove('active'));cube.classList.add('active');
 const [day,val,pct,total,sign]=data,tone=sign>0?'positive':'negative';
 detail.innerHTML=`<b>${esc(day)}</b><strong class="${tone}">${esc(val)}</strong>${pct?`<em class="${tone}">${esc(pct)}</em>`:''}<small>${esc(total)}</small>`;
}
document.addEventListener('click',event=>{const cube=event.target.closest?.('.cube');if(cube)cubeSelect(cube);});
document.addEventListener('pointerover',event=>{if(event.pointerType!=='mouse')return;const cube=event.target.closest?.('.cube');if(cube&&!cube.classList.contains('active'))cubeSelect(cube);});
document.addEventListener('focusin',event=>{const cube=event.target.closest?.('.cube');if(cube&&!cube.classList.contains('active'))cubeSelect(cube);});
