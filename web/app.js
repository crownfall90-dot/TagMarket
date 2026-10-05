'use strict';
const $ = (s, root = document) => root.querySelector(s);
const tg = window.Telegram?.WebApp;
const preview = new URLSearchParams(location.search).get('preview') === '1';
const state = {data:null, people:null, admin:null, report:null, reportError:'', priceChart:null, notifications:{items:[],unread:0}, view:'overview', login:null, period:'today', kind:'trades', offset:0, from:'', to:'', filters:{overview:{period:'today',from:'',to:''},account:{period:'today',from:'',to:''}}, busy:false, currency:null};
try{state.displayCurrency=localStorage.getItem('tag-display-currency')||'USD';}catch{state.displayCurrency='USD';}
let generation = 0, refreshTimer, toastTimer, notificationsStarted = false, lastNotificationId = 0;
state.projects=null;state.projectsError='';state.projectId=null;try{state.assetMode=localStorage.getItem('tag-asset-mode')||'tag';}catch{state.assetMode='tag';}state.forecast={horizon:'1m',until:'',bonus:true,selected:null,result:null,tag:null};
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
function date(value, full=false){const raw=String(value||'');const iso=raw.length===10?raw+'T00:00:00Z':/(Z|[+-]\d{2}:\d{2})$/.test(raw)?raw:raw+'Z';return new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'short',...(full?{hour:'2-digit',minute:'2-digit',timeZone:'UTC'}:{})}).format(new Date(iso));}
function dayLabel(value){const text=new Intl.DateTimeFormat('ru-RU',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`));return text.charAt(0).toUpperCase()+text.slice(1);}
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
function notificationTarget(item){const match=/^trade:(\d+):/.exec(item.event_key||'');if(match&&state.data?.accounts.some(a=>String(a.login)===match[1]))return {hash:'account/'+match[1],label:'Открыть счёт'};if(['trades','deposits','withdrawals'].includes(item.kind))return {hash:'accounts',label:'Открыть счета'};if(item.kind==='registration')return {hash:'people',label:'Открыть гостей'};return {hash:'',label:'Читать'};}
function eventToast(item,count){const el=$('#toast'),[kind,ico]=eventKind(item);el.innerHTML=`<div class="event-toast kind-${esc(item.kind||'other')}" role="alert"><button type="button" class="event-toast-main" data-action="notification-open" data-id="${esc(item.id)}"><span class="event-toast-icon">${icon(ico)}</span><span class="event-toast-copy"><b>${count>1?`${count} новых · `:''}${esc(item.title)}</b><span>${esc(notificationParts(item).amount||notificationParts(item).lines[0]||'')}</span></span><span class="event-toast-go">${icon('arrow')}</span></button><button type="button" class="event-toast-close" data-action="toast-close" aria-label="Закрыть">×</button><i class="event-toast-timer"></i></div>`;el.classList.add('visible','has-event');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('visible'),6000);}
function button(action,text,style='secondary',ico='',attrs=''){return `<button type="button" class="button ${style}" data-action="${action}" ${attrs}>${ico?icon(ico):''}<span class="button-label">${esc(text)}</span></button>`;}
// Длина считается по видимому тексту: теги форматирования (<b>, <i>, <code>, <blockquote>) — не символы
function broadcastLength(value){return String(value||'').replace(/<\/?(?:b|i|code|blockquote)>/gi,'').length;}
function broadcastPreview(text){return esc(text).replace(/&lt;(\/?)(b|i|code|blockquote)&gt;/g,'<$1$2>');}
function fileSize(bytes){return `${number(bytes/1024/1024)} МБ`;}
async function mediaKind(file){const b=new Uint8Array(await file.slice(0,12).arrayBuffer());if(b[0]===255&&b[1]===216&&b[2]===255)return 'photo';if([137,80,78,71,13,10,26,10].every((v,i)=>b[i]===v))return 'photo';if(b[4]===102&&b[5]===116&&b[6]===121&&b[7]===112)return 'video';return null;}
paths.projects='M3 7h7l2 2h9v11H3z M3 7V4h7l2 3 M7 13h10 M7 16h6';
const tabs=[['overview','Обзор'],['accounts','Счета'],['projects','Проекты'],['people','Гости'],['settings','Настройки']];
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
 const active=state.view==='account'?'accounts':state.view==='project'||state.view==='forecast'?'projects':state.view==='faq'?'overview':state.view;
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
 const crumb=$('#crumb'),title=state.view==='project'?'Проекты / Проект':state.view==='account'?'Счета / Счёт':state.view==='faq'?'Вопросы и ответы':state.view==='onboarding'?'Как добавить свой счёт':tabs.find(([id])=>id===state.view)?.[1]||'Счёт';
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
const VIEW_ORDER={overview:0,onboarding:.25,faq:.5,accounts:1,account:1.5,projects:2,project:2.5,forecast:2.7,people:3,settings:4};
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
async function addShortcut(){const help='<p>Откройте мини-приложение из чата с ботом в Telegram. Нажмите ⋮ справа сверху и выберите «Добавить на главный экран», если этот пункт есть на устройстве.</p><a class="text-link" href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">Открыть бота в Telegram</a>';if(preview||!tg?.initData)return dialog('Ярлык Tag Markets',help,'Понятно');if(!tg?.addToHomeScreen)return dialog('Ярлык Tag Markets',help,'Понятно');try{if(tg.checkHomeScreenStatus)tg.checkHomeScreenStatus(s=>{if(s==='added')toast('Ярлык уже добавлен');else if(s==='unsupported')dialog('Ярлык Tag Markets',help,'Понятно');else tg.addToHomeScreen();});else tg.addToHomeScreen();}catch{return dialog('Ярлык Tag Markets',help,'Понятно');}}
function authScreen(){return `<main class="auth-screen"><div class="auth-glow"></div><div class="auth-brand"><div class="auth-mark"><svg viewBox="0 0 64 64" aria-hidden="true"><path class="logo-halo" d="M14.5 19a24 24 0 0 1 32-3M50.5 22a24 24 0 0 1-2 23M43 50.5a24 24 0 0 1-27-3"></path><path class="logo-letter" d="M20 22h24M32 22v22"></path><path class="logo-trend" d="m18 43 8-8 6 4 14-16"></path><circle class="logo-node" cx="46" cy="23" r="2.8"></circle><circle class="logo-seed" cx="18" cy="43" r="1.8"></circle></svg></div><span class="brand-wordmark"><strong>TAG</strong><small>MARKETS</small></span></div><span class="eyebrow">ЛИЧНЫЙ КАБИНЕТ · TELEGRAM MINI APP</span><h1>Ваш капитал<br><em>в одном ритме.</em></h1><p>Откройте приложение из чата с ботом, чтобы увидеть счета, сделки и гостей в защищённом личном пространстве.</p><a class="button primary auth-button" href="https://t.me/tagmarketgold_bot">Открыть бота в Telegram ${icon('arrow')}</a><small>Ссылка на приложение работает только внутри Telegram.</small></main>`;}
function accountBadge(a){return (a.shared?'<span class="badge">Для наблюдения</span>':'')+(!a.enabled?'<span class="badge">На паузе</span>':a.status==='pending'?'<span class="badge warning">Ожидаем данные счёта</span>':'');}
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
 return `<a href="#overview" class="text-link back">${icon('back')} Обзор</a><div class="page-head"><div><h1>Вопросы и ответы</h1></div></div><div class="faq-page">${strategies}${connect}${money_}${partner}${license}</div>`;
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
function currentAccount(){if(state.view==='account'&&state.login)return state.data.accounts.find(a=>String(a.login)===String(state.login))||null;return state.data.accounts.find(a=>String(a.login)===String(state.login))||state.data.accounts.find(a=>!a.demo&&a.enabled)||state.data.accounts[0];}
function periodTabs(only){const short={today:'Сегодня',yesterday:'Вчера',week:'Неделя',month:'Месяц',all:'Всё'};const list=only?only.map(k=>[k,short[k]]):periods;return `<div class="segmented ${only?'compact':''}">${list.map(([key,label])=>`<button data-action="period" data-value="${key}" class="${state.period===key?'active':''}">${label}</button>`).join('')}</div>`;}
// Динамика доходности лентой дней: новые сверху, полоска — доля от самого
// крупного дня, справа результат дня и накопленный итог периода. Дни без
// сделок (выходные) не выводим, но учитываем в итоге.
function dayFeed(rep,capital){const cur=rep.currency||'USD',rows=(rep.timeline?.length?rep.timeline:rep.chart||[]).map(p=>({day:p.day,value:Number(p.value)||0}));let total=0;const days=rows.map(p=>({...p,total:(total+=p.value)})).filter(p=>p.value!==0).slice(-180);if(!days.length)return empty('Пока нет закрытых сделок','Результат по дням появится после первой сделки за период.');const best=days.reduce((a,b)=>b.value>a.value?b:a),worst=days.reduce((a,b)=>b.value<a.value?b:a),peak=Math.max(...days.map(p=>Math.abs(p.value))),wins=days.filter(p=>p.value>0).length,avg=days.reduce((a,p)=>a+p.value,0)/days.length;
 const weekday=d=>new Intl.DateTimeFormat('ru-RU',{weekday:'short',timeZone:'UTC'}).format(new Date(`${d}T00:00:00Z`));
 const span=Math.max(...days.map(p=>p.value>0?p.value:0),0)+Math.max(...days.map(p=>p.value<0?-p.value:0),0)||1,negShare=Math.max(...days.map(p=>p.value<0?-p.value:0),0)/span*100;
 const info=p=>JSON.stringify([`${date(p.day)} · ${weekday(p.day)}`,money(p.value,cur,true),capital>0?percent(p.value/capital*100):'',`с начала периода ${money(p.total,cur,true)}${capital>0?` · ${percent(p.total/capital*100)}`:''}`,p.value>0?1:-1]);
 const cube=(p,k)=>`<button type="button" class="cube ${p.value>0?'up':'down'}${k===days.length-1?' active':''}" style="--h:${Math.max(5,Math.abs(p.value)/span*100).toFixed(1)}%" data-cube="${esc(info(p))}" aria-label="${esc(`${date(p.day)}: ${money(p.value,cur,true)}`)}"></button>`;
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
function showAccountGuide(open){state.view=open?'onboarding':'overview';nav();render();window.scrollTo(0,0);}
function fxBreakdown(all){const sums={};const add=(cur,v)=>{cur=cur||'USD';sums[cur]=(sums[cur]||0)+Number(v||0);};add('USD',state.data.totals.USD?.capital||0);if(all)for(const p of state.projects||[])add(p.currency,p.current_total??p.total);return Object.entries(sums);}
function fxWarning(){const d=state.data;if(d.fx_error)return `${d.fx_error}. Суммы без доступной конвертации показаны в исходной валюте.`;if(!d.fx&&state.displayCurrency!=='USD')return `Конвертация в ${state.displayCurrency} временно недоступна. Суммы показаны в исходной валюте.`;return '';}
function heroCapital(all,portfolio){const own=all?portfolio.own:portfolio.tag;if(own!=null&&!(all&&portfolio.partial))return {value:money(own,state.displayCurrency),partial:false,breakdown:[]};const parts=fxBreakdown(all);if(parts.length===1)return {value:money(parts[0][1],parts[0][0]),partial:false,breakdown:[]};return {value:'Частично рассчитан',partial:true,breakdown:parts};}
function portfolioTotals(){const tag=state.data.totals.USD?.capital||0,projects=state.projects||[];let own=displayAmount(tag,'USD'),bonus=0,partial=own==null;for(const p of projects){const personal=displayAmount(p.current_total??p.total,p.currency),activeBonus=displayAmount(p.bonus_total||0,p.currency);if(personal==null||activeBonus==null)partial=true;else{own+=personal;bonus+=activeBonus;}}return {tag:displayAmount(tag,'USD'),own,working:own==null?null:own+bonus,bonus,partial};}
function overview(){const d=state.data, curr='USD', t=d.totals[curr]||{capital:0,pnl:0,month:0,today:0}, own=d.accounts.filter(a=>!a.demo&&!a.shared), demo=d.accounts.find(a=>a.demo&&a.enabled), rep=state.report;
 const dynamics=state.reportError?empty('Не удалось построить график',state.reportError):rep?`<div class="dynamics-main fade-swap">${resultPair(rep.summary.net_income,rep.currency,rep.summary.pct_capital)}<span class="muted">${countLabel(rep.summary.count,['сделка','сделки','сделок'])}</span></div>${dayFeed(rep,t.capital)}`:skeleton('chart');
 const shared=d.accounts.filter(a=>a.shared&&!a.demo);
 const portfolio=portfolioTotals(),all=state.assetMode==='all',hero=heroCapital(all,portfolio),warning=fxWarning();
 return header('Мой кабинет','',own.length?'':button('onboard-open','Добавить свой счёт','secondary','plus'))+
  `<div class="dashboard-grid"><div><section class="panel hero"><div class="hero-top"><span class="eyebrow">${all?'Все активы':'Мой капитал'}</span><div class="segmented asset-mode"><button data-action="asset-mode" data-value="tag" class="${!all?'active':''}">TagMarket</button><button data-action="asset-mode" data-value="all" class="${all?'active':''}">Все активы</button></div></div><div class="hero-value ${hero.partial?'hero-partial':''}">${hero.value}</div>${hero.breakdown.length?`<div class="fx-breakdown">${hero.breakdown.map(([c,v])=>`<span>${esc(c)} · ${number(v)}</span>`).join('')}</div>`:''}${all&&!hero.partial?`<div class="hero-bottom"><div><p>TagMarket</p><b>${portfolio.tag==null?'—':money(portfolio.tag,state.displayCurrency)}</b></div><div><p>Проекты · ваши средства</p><b>${portfolio.own==null?'—':money(portfolio.own-(portfolio.tag||0),state.displayCurrency)}</b></div>${portfolio.bonus?`<div><p>С бонусами работает</p><b>${money(portfolio.working,state.displayCurrency)}</b></div>`:''}</div>`:!hero.partial?`<div class="hero-bottom"><div><p>За месяц</p>${resultPair(t.month,curr,t.capital>0?t.month/t.capital*100:null)}</div><div class="separator"></div><div><p>Сегодня</p>${resultPair(t.today,curr,t.capital>0?t.today/t.capital*100:null)}</div></div>`:''}${d.fx?fxNote(d.fx):''}${warning?`<small class="stat-note warn-text fx-warning">${esc(warning)}</small>`:''}</section>
  ${shared.length?`<section class="account-group shared-overview"><div class="account-list">${shared.map((a,i)=>accountCard(a,i)).join('')}</div></section>`:''}
  <section class="panel chart-panel dynamics"><div class="panel-head"><h2>Динамика доходности</h2>${periodTabs(['today','yesterday','week','month','all'])}</div>${dynamics}</section>
  ${priceChart(state.priceChart)}</div>
 <aside class="side-stack">${sonicStrategyCard()}
 ${demo?`<section class="panel demo-panel"><span class="eyebrow">Публичная стратегия</span><h3>Копитрейдинг 45k</h3><div class="demo-number">${demo.totals?money(demo.totals.now,demo.totals.cur):'—'}</div><span class="badge demo">Не входит в ваш капитал</span><a class="button" href="#account/${esc(demo.login)}">Открыть ${icon('arrow')}</a></section>`:''}</aside></div>`+
  (d.onboarding?.needed&&shared.length?resumeBanner():'');
}
function balanceCard(personal){const totals=state.data.totals||{},list=Object.keys(totals);if(!list.length)return '';return `<section class="panel balance-card">${list.map(c=>{const x=totals[c];return `<div class="balance-row"><div><span class="eyebrow">ОБЩИЙ БАЛАНС · ${esc(c)}</span><strong>${money(x.capital,c)}</strong><small>${countLabel(personal.length,['счёт','счёта','счетов'])}</small></div><div class="balance-side"><div><small>Сегодня</small>${resultPair(x.today,c,x.capital>0?x.today/x.capital*100:null)}</div><div><small>За месяц</small>${resultPair(x.month,c,x.capital>0?x.month/x.capital*100:null)}</div></div></div>`;}).join('')}</section>`;}
function accountsView(){const items=state.data.accounts,personal=items.filter(a=>!a.demo&&!a.shared),shared=items.filter(a=>a.shared&&!a.demo),demo=items.find(a=>a.demo),groups=[...new Set(personal.map(a=>a.cabinet||'Без кабинета'))];
 const group=c=>{const list=personal.filter(a=>(a.cabinet||'Без кабинета')===c);return `<section class="account-group"><div class="account-group-head"><div class="group-title"><h2>${esc(list[0]?.holder||c)}</h2><span class="cab-id">${esc(c)} · ${countLabel(list.length,['счёт','счёта','счетов'])}</span></div></div><div class="account-list">${list.map((a,i)=>accountCard(a,i,false)).join('')}</div></section>`;};
 return header('Счета','',button('add','Добавить счёт','primary','plus'))+(personal.length?balanceCard(personal):'')+groups.map(group).join('')
  +(shared.length?`<section class="account-group"><div class="account-group-head"><div class="group-title"><h2>Для просмотра</h2></div></div><div class="account-list">${shared.map((a,i)=>accountCard(a,i)).join('')}</div></section>`:'')
  +(demo?`<section class="account-group demo-account-group"><div class="account-group-head"><div class="group-title"><span class="eyebrow">ОБЩИЙ СЧЁТ · ПРОСМОТР</span></div></div><div class="account-list">${accountCard(demo,1)}</div></section>`:'')
  +(!personal.length&&!shared.length?empty('Ваш первый шаг','Подключите счёт MT5 — здесь появятся баланс, сделки и результат по дням.',button('add','Подключить','primary','plus')):'');}
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
 const ticks=[0,.25,.5,.75,1].map(f=>{const i=Math.round(f*(n-1));return `<span style="left:${pct(x(i),w)}">${fmt.format(new Date(rows[i].time))}</span>`;}).join('');
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
 const tag=a.demo?'<span class="badge demo">Общий счёт</span>':a.shared?'<span class="badge">Только просмотр</span>':'';
 const cell=(label,value,pctv,extra='')=>`<div class="detail-cell"><small>${esc(label)}</small>${resultPair(value,cur,pctv)}${extra}</div>`;
 const intro=`<div class="detail-top"><a href="#accounts" class="text-link back">${icon('back')} Все счета</a>${button('account-settings','Настроить','secondary small','settings',`data-login="${esc(a.login)}"`)}</div>`
  +`<section class="panel detail-hero"><div class="detail-hero-top"><div class="strategy-icon green">${icon('chart')}</div><div class="detail-hero-name"><h1>${esc(a.strategy||a.name)}</h1><span class="cab-id">${esc(a.holder||'—')} · ${esc(a.login)}</span></div>${tag}</div>`
  +`<div class="detail-balance"><small>Мой капитал</small><strong>${t?money(t.now,cur):'—'}</strong></div>`
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
function linkCard(p){const partner=p.partner_url,share=p.link?`https://t.me/share/url?url=${encodeURIComponent(p.link)}&text=${encodeURIComponent('Приглашаю в Tag Markets')}`:'';return `<section class="panel link-card"><span class="eyebrow">ВАША ССЫЛКА-ПРИГЛАШЕНИЕ</span><div class="link-step ${partner?'done':'todo'}"><span class="step-n">${partner?'✓':'1'}</span><div><b>Партнёрская ссылка</b><small>${partner?'Сохранена':'Найдите свою партнёрскую ссылку в IB Portal и вставьте её сюда.'}</small></div>${partner?button('partner-link','Изменить','secondary small'):''}</div>${partner?'':button('partner-link','Вставить ссылку','primary wide','link')}<div class="link-step ${p.link?'done':'todo'}"><span class="step-n">${p.link?'✓':'2'}</span><div><b>Ссылка для гостей</b><small>Одна и постоянная</small></div></div>${p.link?`<div class="invite-url">${esc(p.link)}</div><div class="link-actions">${button('copy','Скопировать','secondary','copy',`data-text="${esc(p.link)}"`)}<a class="button primary" href="${esc(share)}" target="_blank" rel="noopener">${icon('arrow')} Отправить</a>${button('renew-link','Обновить','secondary small','refresh')}</div>`:''}</section>`;}
function guestHue(name){let h=0;for(const c of String(name))h=(h*31+c.codePointAt(0))%360;return h;}
function guestCard(g,p){
 const have=new Set(g.accounts.filter(a=>a.shared).map(a=>String(a.login))),canShare=(p.shareable||[]).filter(a=>!have.has(String(a.login))),mine=g.accounts.filter(a=>a.shared).length,own=g.accounts.length-mine;
 const sub=[countLabel(g.accounts.length,['счёт','счёта','счетов']),mine?`${mine} ваш${mine===1?'':'их'}`:'',own?`${own} личн${own===1?'ый':'ых'}`:'',g.since?`с ${g.since}`:''].filter(Boolean).join(' · ');
 return `<details class="panel people-card guest-card" data-ui-key="guest-${esc(g.id)}" style="--hue:${guestHue(g.name)}"><summary class="person-head"><span class="avatar guest-avatar">${esc(g.name.slice(0,1).toUpperCase())}</span><span class="person-copy"><b>${esc(g.name)}</b><small class="guest-sub">${esc(sub)}</small></span>${icon('chevron')}</summary><div class="faq-body">${g.accounts.map(a=>`<div class="guest-account ${a.shared?'is-shared':''}"><span class="ga-ico">${icon(a.shared?'link':'chart')}</span><div><b>${esc(a.name)}</b><small>${a.shared?'Ваш счёт у гостя':'Личный · только просмотр'}</small></div>${a.shared?button('take','Забрать','secondary small','',`data-guest="${esc(g.id)}" data-login="${esc(a.login)}"`):''}</div>`).join('')||'<p class="guest-empty">Счетов пока нет — откройте гостю один из своих.</p>'}<div class="actions guest-actions">${canShare.length?button('share-accounts','Открыть счета','secondary small','plus',`data-guest="${esc(g.id)}"`):''}${button('guest-detail','Подробнее','secondary small','',`data-guest="${esc(g.id)}"`)}${button('revoke-guest','Убрать доступ','danger small','',`data-guest="${esc(g.id)}"`)}</div></div></details>`;
}

function peopleView(){const p=state.people;if(!p)return header('Гости')+skeleton('list',2);return header('Гости')+linkCard(p)+`<div class="section-head"><h2>Приглашены <span class="muted">${p.guests.length}</span></h2></div>${p.guests.length?`<div class="cards-grid">${p.guests.map(g=>guestCard(g,p)).join('')}</div>`:empty('Гостей пока нет','')}`;}
function toggle(label,note,action,on,attrs=''){return `<div class="settings-row"><div><p>${esc(label)}</p>${note?`<small>${esc(note)}</small>`:''}</div><button class="switch" role="switch" aria-label="${esc(label)}" aria-checked="${!!on}" data-action="${action}" ${attrs}></button></div>`;}
const MACHINE_STATE={polling:['Опрашивает','ok'],waiting:['Готова','ok'],legacy:['Старый код','warning'],offline:['Офлайн','muted']};
function nextCheck(sec){if(sec==null)return '';const at=new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'}).format(new Date(Date.now()+sec*1000));const wait=sec<60?'меньше минуты':`${Math.ceil(sec/60)} мин`;return ` Следующая проверка через ${wait}, в ${at} МСК.`;}
function machineRow(m){const [label,cls]=MACHINE_STATE[m.state]||MACHINE_STATE.offline;return `<div class="machine-row state-${esc(m.state)}"><div class="machine-top"><b>${esc(m.host)}</b><span class="badge ${cls}">${label}</span></div><small>${m.role==='primary'?'Основная':m.role==='standby'?'Резервная':'Роль не определена'} · ${esc(agoText(m.idle))}${m.commit?` · <code>${esc(m.commit)}</code>`:''}</small>${m.blocked?`<p class="machine-warn">Обновление заблокировано: ${esc(m.blocked)}.${nextCheck(m.next_check)}</p>`:''}</div>`;}
function serviceSummary(machines){return machines.some(m=>m.state==='polling')?'':'<div class="service-status bad"><b>Терминал никто не опрашивает</b><span>Данные не обновляются</span></div>';}
function servicePanel(){const machines=state.admin?.machines||[];return `<section class="panel service-panel"><div class="service-head"><div><span class="eyebrow">ДЛЯ ВЛАДЕЛЬЦА</span><h2>Сервис</h2></div>${button('refresh','Обновить','secondary small','refresh')}</div>${state.admin?`${serviceSummary(machines)}<div class="machine-list">${machines.map(machineRow).join('')||'<p class="muted">Машины не отвечали.</p>'}</div>`:'<p class="muted mt">Загружаем состояние…</p>'}${toggle('Уведомления о сервисе','','alerts',state.data.update_alerts)}<div class="settings-row"><div><p>Сообщение пользователям</p></div>${button('broadcast','Написать','secondary small')}</div></section>`;}
const BRAND_SVG='<svg viewBox="0 0 64 64" aria-hidden="true"><path class="logo-halo" d="M14.5 19a24 24 0 0 1 32-3M50.5 22a24 24 0 0 1-2 23M43 50.5a24 24 0 0 1-27-3"></path><path class="logo-letter" d="M20 22h24M32 22v22"></path><path class="logo-trend" d="m18 43 8-8 6 4 14-16"></path><circle class="logo-node" cx="46" cy="23" r="2.8"></circle><circle class="logo-seed" cx="18" cy="43" r="1.8"></circle></svg>';
// Значок гаммы — мини-превью интерфейса в её цветах: карточка с графиком
// доходности в акценте, заливка под линией, плашка второго цвета, свечение.
// Две точки на тёмном прямоугольнике не говорили, как будет выглядеть приложение
function schemeSwatch(id,[bg,accent,second]){
 const g=`sw-${id}`;
 return `<svg class="swatch" viewBox="0 0 100 60" aria-hidden="true"><defs><radialGradient id="${g}-glow" cx="85%" cy="10%" r="70%"><stop offset="0" stop-color="${accent}" stop-opacity=".35"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></radialGradient><linearGradient id="${g}-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${accent}" stop-opacity=".38"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></linearGradient></defs><rect width="100" height="60" rx="9" fill="${bg}"/><rect width="100" height="60" rx="9" fill="url(#${g}-glow)"/><rect x="8" y="8" width="84" height="44" rx="7" fill="#1a1e21" stroke="#ffffff14"/><rect x="14" y="14" width="20" height="5" rx="2.5" fill="${second}"/><rect x="14" y="22" width="32" height="3" rx="1.5" fill="#ffffff2e"/><path d="M14 45 L25 39 L36 42 L48 31 L60 34 L72 23 L86 26 L86 48 L14 48Z" fill="url(#${g}-fill)"/><path d="M14 45 L25 39 L36 42 L48 31 L60 34 L72 23 L86 26" fill="none" stroke="${accent}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="86" cy="26" r="3" fill="${accent}" stroke="#1a1e21" stroke-width="1.5"/><rect x="66" y="13" width="20" height="7" rx="3.5" fill="${accent}"/></svg>`;
}
function schemePicker(){const cur=currentScheme();return `<div class="scheme-picker" role="radiogroup" aria-label="Цветовая гамма">${SCHEMES.map(([id,name,,sw])=>`<button type="button" role="radio" aria-checked="${cur===id}" class="scheme ${cur===id?'active':''}" data-action="scheme" data-value="${id}" style="--sw:${sw[1]}">${schemeSwatch(id,sw)}<b>${name}</b><span class="scheme-check" aria-hidden="true">${icon('check')}</span></button>`).join('')}</div>`;}
function settingsView(){const personal=state.data.accounts.filter(a=>!a.demo&&!a.shared),demo=state.data.accounts.find(a=>a.demo);return header('Настройки')+`<div class="two-column"><section class="panel"><span class="eyebrow">ЦВЕТОВАЯ ГАММА</span>${schemePicker()}<button class="shortcut-card" type="button" data-action="shortcut"><span class="shortcut-tile">${BRAND_SVG}</span><span class="shortcut-copy"><b>Ярлык на экран</b><small>Открывать Tag Markets в один тап</small></span><span class="pill">Добавить</span></button></section><section class="panel"><div class="panel-head"><h2>Мои счета</h2><span class="badge">${personal.length}</span></div>${personal.map(a=>`<button type="button" class="settings-row settings-account-row compact-row" data-ui-key="account-${esc(a.login)}" data-action="account-settings" data-login="${esc(a.login)}"><span class="settings-account-info"><b>${esc(a.strategy||a.name)}</b><small>${esc(a.cabinet||'Без кабинета')}${a.holder?` · ${esc(a.holder)}`:''}</small></span><span class="settings-balance">${a.totals?money(a.totals.now,a.totals.cur):'—'}</span>${icon('chevron')}</button>`).join('')||'<p class="muted mt">Счетов пока нет.</p>'}</section></div>${demo?`<section class="panel settings-demo" aria-label="Общий счёт копитрейдинга"><span class="settings-demo-icon">${icon('chart')}</span><div class="settings-demo-copy"><b>Копитрейдинг 45k</b><small><span class="settings-demo-sum">${demo.totals?money(demo.totals.now,demo.totals.cur):'—'}</span> · общий счёт, просмотр</small></div><div class="settings-demo-actions"><button type="button" class="icon-btn" data-action="account-settings" data-login="${esc(demo.login)}" aria-label="Уведомления общего счёта" title="Уведомления">${icon('bell')}</button><a class="icon-btn" href="#account/${esc(demo.login)}" aria-label="Открыть общий счёт" title="Открыть">${icon('arrow')}</a></div></section>`:''}${state.data.founder?servicePanel():`<section class="panel leave-card"><div><b>Доступ</b><small>Счета и данные будут удалены</small></div><button type="button" class="leave-btn" data-action="leave">${icon('exit')}<span>Отключить мой доступ</span></button></section>`}`;}
// отпечаток всего, из чего строится экран; server_time меняется на каждом
// запросе и на вид не влияет — без него одинаковые данные дают одинаковый ключ
let paintedKey='';
function paintKey(){const {server_time,...data}=state.data||{};return JSON.stringify([state.view,state.login,state.projectId,state.projects,state.projectsError,state.tagStats,state.period,state.from,state.to,state.currency,state.displayCurrency,state.assetMode,state.forecast,state.kind,state.offset,data,state.report,state.reportError,state.priceChart,state.people,state.admin]);}
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
 const views={overview,accounts:accountsView,account:accountView,projects:projectsView,project:projectView,forecast:forecastView,people:peopleView,settings:settingsView,faq:faqView,onboarding:welcomeView};$('#main').innerHTML=(preview?'<div class="preview-label">Демо-режим · вымышленные данные. Отправка сообщений и управление счетами работают только при запуске из <a href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">бота в Telegram</a>.</div>':'')+(views[state.view]||overview)()+(state.view==='settings'&&state.admin?.network?.length?networkView():'');$('#avatar').textContent=state.data.user.name.slice(0,1).toUpperCase();
 // сначала все замеры, потом все записи: чередование чтения и записи в одном
 // цикле заставляет браузер пересчитывать вёрстку на каждой полосе
 const centering=[];
 document.querySelectorAll('.segmented').forEach(strip=>{const active=strip.querySelector('.active');if(active)centering.push([strip,active.getBoundingClientRect().left-strip.getBoundingClientRect().left-(strip.clientWidth-active.clientWidth)/2]);});
 for(const [strip,shift] of centering)strip.scrollLeft+=shift;
 positionThumbs(prevThumbs);
 restoreUiState(snapshot);
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
 const shifted=day=>new Date(Date.parse(`${day}T00:00:00Z`)+delta).toISOString().slice(0,10);
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
 for(const account of d.bootstrap.accounts){if(!account.totals)continue;account.totals.today_net=round(dealToday*account.totals.month_net/d.report.summary.net_income);if(!account.demo&&!account.shared)totalToday+=account.totals.today_net;}
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
  if(path==='/bootstrap')return d.bootstrap;
  if(path==='/people')return d.people;
  if(path.startsWith('/tagmarket/forecast')){const until=new URLSearchParams(path.split('?')[1]||'').get('until'),start=new Date(`${projectToday()}T00:00:00Z`),count=(end)=>{let n=0;for(let t=start.getTime()+864e5;t<=Date.parse(`${end}T00:00:00Z`);t+=864e5)if(![0,6].includes(new Date(t).getUTCDay()))n++;return n;},add=n=>new Date(start.getTime()+n*864e5).toISOString().slice(0,10),month=(()=>{const m=new Date(start);m.setUTCMonth(m.getUTCMonth()+1);return m.toISOString().slice(0,10);})(),average=.0042,days={day:count(add(1)),week:count(add(7)),month:count(month),selected:count(until)};return {sufficient:true,days_used:23,min_days:5,window_days:30,average_daily_return:average,average_daily_profit:null,until,trading_days:days,multipliers:Object.fromEntries(Object.entries(days).map(([k,n])=>[k,(1+average)**n])),model:'compound_average_daily_return'};}
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
async function loadReport(){const params=new URLSearchParams({period:state.period});if(state.period==='custom'){if(!state.from||!state.to)return null;params.set('from',state.from);params.set('to',state.to);}if(state.view==='overview')return api(`/overview/report?${params}`);const acc=currentAccount();if(!acc)return null;state.login=acc.login;params.set('kind',state.kind);params.set('offset',state.offset);return api(`/accounts/${acc.login}/report?${params}`);}
// Данные самого раздела сверх общих /bootstrap: отчёт, график цены, гости,
// сервисная панель. Нужны и фоновому обновлению, и переходу между разделами
async function viewParts(){
 // независимые запросы идут одновременно: раньше отчёт, свечи, проекты и
 // прогноз TagMarket ждали друг друга по очереди, и раздел открывался на их сумму
 const out={},jobs=[];
 if(['overview','account'].includes(state.view))jobs.push((async()=>{try{out.report=await loadReport();out.reportError='';}catch(error){out.report=null;out.reportError=error.message;}})());
 if(state.view==='overview'){const sonic=state.data.accounts.find(a=>!a.demo&&/sonic|sonik/i.test(`${a.strategy||''} ${a.name||''}`));jobs.push((async()=>{out.priceChart=sonic?await api(`/accounts/${sonic.login}/candles?period=${state.period==='custom'?'week':state.period}`).catch(()=>null):null;})());}
 if(state.view==='people')jobs.push((async()=>{out.people=await api('/people');})());
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
function viewKey(){return [state.view,state.login,state.projectId,state.period,state.from,state.to,state.currency,state.kind,state.offset].join('|');}
function remember(){viewCache.set(viewKey(),{report:state.report,reportError:state.reportError,priceChart:state.priceChart,projects:state.projects,projectsError:state.projectsError,at:Date.now()});}
function refreshEvery(){return Math.max(30,Number(state.data?.refresh_seconds)||60)*1000;}
const VIEW_NEEDS_DATA=view=>['overview','account','people','projects','project','forecast'].includes(view)||(view==='settings'&&!!state.data?.founder);
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
 if(c&&Date.now()-c.at<refreshEvery()){state.report=c.report;state.reportError=c.reportError||'';if(state.view==='overview')state.priceChart=c.priceChart;render();return;}
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
 const data=await api('/bootstrap');if(gen!==generation)return;state.data=data;lastOkAt=Date.now();setOffline(false);state.displayCurrency=data.display_currency||state.displayCurrency;$('#display-currency').value=state.displayCurrency;syncCurrencyUi();scheduleRefresh();
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
 const [view,login]=location.hash.slice(1).split('/');
 const next=['overview','accounts','account','projects','project','forecast','people','settings','faq'].includes(view)?view:'overview';
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
 if(cached&&next==='overview')state.priceChart=cached.priceChart;
 if(cached&&['projects','project','forecast'].includes(next)){state.projects=cached.projects;state.projectsError=cached.projectsError||'';}
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
async function dialog(title,body,label='Сохранить'){const current=$('#dialog');if(current.open||modalLock){const closed=new Promise(resolve=>current.addEventListener('close',resolve,{once:true}));if(current.open&&!await requestDialogExit(current))return null;await closed;}return new Promise(resolve=>{const d=$('#dialog');$('#dialog-title').textContent=title;$('#dialog-body').innerHTML=body;$('#dialog-submit').textContent=label;const info=['Закрыть','Понятно','Готово'].includes(label);d.classList.toggle('info-only',info);d.onclick=e=>{if(info&&e.target===d)requestDialogExit(d);};d.returnValue='';d.onclose=()=>{const values=Object.fromEntries(new FormData($('form',d)));resolve(d.returnValue==='confirm'?values:null);};const form=$('form',d);form.querySelectorAll('select[name="capitalization"]').forEach(select=>{const date=form.querySelector('input[name="capitalization_from"]');if(date)date.disabled=select.value==='inherit';});form.onsubmit=e=>{if(e.submitter?.value==='cancel'){e.preventDefault();requestDialogExit(d);return;}const fields=[...d.querySelectorAll('input,select,textarea')];if(!fields.every(f=>f.reportValidity()))e.preventDefault();};lockDialog();d.showModal();dialogBack();});}
function dialogHasChanges(d){return [...d.querySelectorAll('input,select,textarea')].some(f=>{if(f.type==='file')return f.files?.length>0;if(f.type==='checkbox'||f.type==='radio')return f.checked!==f.defaultChecked;if(f.tagName==='SELECT')return f.value!==([...f.options].find(o=>o.defaultSelected)?.value??f.options[0]?.value);return f.value!==f.defaultValue;});}
// Выбор файла: системное окно выбора шлёт «cancel» (всплывает до диалога), на телефоне — ещё и «назад»
// Telegram. Пока окно выбора открыто и сразу после него закрытие диалога не принимаем.
let filePickerUntil=0;
const filePickerGuard=()=>Date.now()<filePickerUntil;
document.addEventListener('click',event=>{if(event.target.closest?.('.cmp-attach,input[type=file]'))filePickerUntil=Date.now()+60000;},true);
for(const type of ['change','cancel'])document.addEventListener(type,event=>{if(event.target.matches?.('input[type=file]'))filePickerUntil=Date.now()+600;},true);
const filePickerReturned=()=>{if(filePickerUntil>Date.now())filePickerUntil=Math.min(filePickerUntil,Date.now()+600);};
window.addEventListener('focus',filePickerReturned);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)filePickerReturned();});
function requestDialogExit(d){if(filePickerGuard())return Promise.resolve(false);if(!dialogHasChanges(d)){d.close('cancel');return Promise.resolve(true);}return new Promise(resolve=>{const finish=ok=>{if(ok&&d.open)d.close('cancel');resolve(ok);};if(tg?.showConfirm)tg.showConfirm('Выйти без сохранения изменений?',finish);else finish(window.confirm('Выйти без сохранения изменений?'));});}
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
function projectFinance(p,{detail=false}={}){return `<div class="project-finance"><div class="project-finance-row"><small>Ваши средства</small><b>${projectMoney(p.total,p.currency)}</b></div>${projectHasCapitalization(p)?`<div class="project-finance-row"><small>Расчётная сумма сейчас</small><b>${projectMoney(p.current_total,p.currency)}</b></div>`:''}${projectBonusLine(p)|| (detail?'<div class="project-finance-row"><small>Бонусы</small><b>Нет активных</b></div>':'')}<div class="project-finance-row working-capital"><small>Рабочий капитал</small><b>${projectMoney(p.working_total,p.currency)}</b></div>${detail?`<div class="project-finance-row project-period-income"><small>${projectRateLabel(p)}</small><b>${p.calculation_limited?'—':projectIncome(p)}</b></div>`:''}</div>`;}
function projectPeriodDays(period){if(period==='day')return 1;if(period==='week')return 7;const [y,m]=projectToday().split('-').map(Number);return new Date(Date.UTC(y,m,0)).getUTCDate();}
function projectDailyRate(p){return p.daily_rate_percent??p.rate_percent/projectPeriodDays(p.period);}
function projectDailyIncome(p){return p.daily_income??(p.expected_income==null?null:p.expected_income/projectPeriodDays(p.period));}
function projectIncome(p){const v=projectDailyIncome(p);return v==null?'—':`≈ ${v>0?'+':''}${projectMoney(v,p.currency)} / день`;}
function projectRateLabel(p){return `${p.income_mode==='fixed'?projectMoney(projectDailyIncome(p),p.currency)+' фикс.':number(projectDailyRate(p))+'%'} / день${p.period==='day'&&p.business_days_only?' · по будням':''}`;}
function tagStatsOk(){const t=state.tagStats;return !!(t&&t.sufficient&&t.average_daily_return!=null);}
function tagDailyRate(){const t=state.tagStats,ok=tagStatsOk(),capital=displayAmount(state.data.totals.USD?.capital||0,'USD'),income=ok&&capital!=null?capital*t.average_daily_return:null;return `<div class="project-rate"><span>${ok?`${number(Math.round(t.average_daily_return*10000)/100)}% / день`:'Доходность / день'} · только по будням</span><b>${ok&&income!=null?`≈ ${income>0?'+':''}${money(income,state.displayCurrency)} / день`:'—'}</b></div>`;}
function tagTradingDayLine(){const t=state.data.totals.USD||{},value=t.trading_day_net==null?null:displayAmount(t.trading_day_net,'USD');return t.trading_day?`<div class="project-rate tag-trading-day"><span>Плюс за ${esc(date(t.trading_day))}</span><b>${value==null||t.trading_day_partial?'—':money(value,state.displayCurrency,true)}</b></div>`:'';}
function projectCard(p){if(p.system)return `<a href="#accounts" class="panel project-card system-project"><div class="project-card-head"><span class="project-icon">${icon('chart')}</span><h2>TagMarket</h2>${icon('arrow')}</div><b class="project-total">${p.total==null?'—':money(p.total,state.displayCurrency)}</b><small>${countLabel(p.accounts.length,['торговый счёт','торговых счёта','торговых счетов'])}</small>${tagTradingDayLine()}${tagDailyRate()}</a>`;return `<a href="#project/${esc(p.id)}" class="panel project-card" data-ui-key="project-${esc(p.id)}"><div class="project-card-head"><span class="project-icon">${icon('projects')}</span><h2>${esc(p.name)}</h2>${icon('arrow')}</div>${p.multi?`<small class="project-count">${countLabel(p.accounts.length,['аккаунт','аккаунта','аккаунтов'])}</small>`:''}${projectFinance(p)}<div class="project-rate"><span>${projectRateLabel(p)}</span><b>${p.calculation_limited?'—':projectIncome(p)}</b></div></a>`;}
// Динамика по всем проектам: доля каждого в рабочем капитале портфеля и
// ожидаемый доход в день, суммы приведены к валюте отображения.
function projectsDynamics(portfolio){const cur=state.displayCurrency,rows=[],tagOk=tagStatsOk(),tagCap=portfolio.tag;let partial=portfolio.tag==null;
 if(tagCap!=null)rows.push({name:'TagMarket',href:'#accounts',work:tagCap,daily:tagOk?tagCap*state.tagStats.average_daily_return:null,note:tagOk?`${number(Math.round(state.tagStats.average_daily_return*10000)/100)}% / день`:'Нет истории'});
 for(const p of state.projects||[]){const work=displayAmount(p.working_total??p.total,p.currency),inc=projectDailyIncome(p),daily=p.calculation_limited||inc==null?null:displayAmount(inc,p.currency);if(work==null)partial=true;rows.push({name:p.name,href:`#project/${p.id}`,work,daily,note:projectRateLabel(p)});}
 const known=rows.filter(r=>r.work!=null),total=known.reduce((a,r)=>a+r.work,0);if(!known.length||total<=0)return '';
 known.sort((a,b)=>b.work-a.work);const withIncome=known.filter(r=>r.daily!=null),daily=withIncome.reduce((a,r)=>a+r.daily,0),peak=Math.max(...known.map(r=>r.work));
 const row=r=>`<li><div class="feed-day pd"><span class="feed-date"><b>${esc(r.name)}</b><small>${esc(r.note)}</small></span><span class="feed-bar"><i style="--w:${Math.max(3,r.work/peak*100).toFixed(1)}%"></i></span><span class="feed-sum"><b>${money(r.work,cur)}</b><small>${(r.work/total*100).toFixed(1).replace('.',',')}% портфеля${r.daily==null?'':` · ≈ ${money(r.daily,cur,true)} / день`}</small></span></div></li>`;
 return `<section class="panel project-dynamics"><div class="panel-head"><div><span class="eyebrow">ДИНАМИКА</span><h2>По всем проектам</h2></div><span class="badge">${countLabel(known.length,['проект','проекта','проектов'])}</span></div><div class="pd-summary"><div><small>Доход в день</small><b class="${daily<0?'negative':'positive'}">${withIncome.length?`≈ ${money(daily,cur,true)}`:'—'}</b></div><div><small>За 30 дней</small><b class="${daily<0?'negative':'positive'}">${withIncome.length?`≈ ${money(daily*30,cur,true)}`:'—'}</b></div></div><ol class="feed pd-list">${known.map(row).join('')}</ol>${partial||withIncome.length<known.length?'<p class="feed-note">Часть проектов не вошла в сумму: нет курса валют или расчёт ограничен.</p>':''}</section>`;}
function projectsView(){
 const head=header('Проекты','',state.projects?.length===0?'':button('project-create','Добавить проект','primary','plus'));
 if(state.projects===null)return `<div class="project-space">${head}${state.projectsError?empty('Не удалось загрузить проекты',state.projectsError,button('refresh','Попробовать снова')):'<p class="muted">Загружаем проекты…</p>'}</div>`;
 const portfolio=portfolioTotals();
 return `<div class="project-space">${head}${state.projectsError?notice('Не удалось обновить проекты. Показаны последние данные.',true):''}<section class="panel project-summary"><div class="ps-main"><span class="eyebrow">Мои активы</span><b class="ps-total">${portfolio.own==null?'—':money(portfolio.own,state.displayCurrency)}</b><small>Ваш капитал</small></div><div class="ps-stats"><div class="ps-stat"><small>Рабочий капитал с бонусами</small><b>${portfolio.working==null?'—':money(portfolio.working,state.displayCurrency)}</b></div><div class="ps-stat"><small>TagMarket + проекты</small><b>${countLabel(state.projects.length,['проект','проекта','проектов'])}</b></div></div><a class="button secondary forecast-link" href="#forecast"><span>Прогноз</span> ${icon('arrow')}</a></section>${projectsDynamics(portfolio)}<div class="project-grid">${projectCard({id:'tagmarket-system',name:'TagMarket',total:portfolio.tag,currency:state.displayCurrency,rate_percent:0,period:'month',multi:true,accounts:state.data.accounts.filter(a=>!a.demo&&!a.shared),system:true})}${state.projects.map(projectCard).join('')}</div>${!state.projects.length?empty('Добавьте первый проект','Ручной учёт вкладов и других финансовых проектов.',button('project-create','Добавить проект','primary','plus')):''}</div>`;
}
function projectView(){
 const p=state.projects?.find(p=>p.id===state.projectId),back='<a href="#projects" class="button secondary small back">← Проекты</a>';
 if(!p)return `<div class="project-space">${back}${state.projects===null?empty('Загружаем проект',state.projectsError||''):empty('Проект не найден','Возможно, он был удалён.')}</div>`;
 const workTotal=p.accounts.reduce((sum,a)=>sum+(Number(a.working_amount)||0),0),
  accounts=p.accounts.map((a,i)=>{
   const num=a.position||i+1,share=workTotal>0?Math.max(3,(Number(a.working_amount)||0)/workTotal*100):0,
    rate=p.income_mode==='fixed'?'':`${number(projectDailyRate(a.daily_rate_percent!=null?a:{...p,rate_percent:a.rate_percent??p.rate_percent}))}% / день`,
    tags=[rate&&`<i>${rate}</i>`,a.rate_percent!=null&&p.income_mode!=='fixed'?'<i class="own">своя ставка</i>':'',a.capitalization_active?'<i class="cap">капитализация</i>':'',a.bonus_capitalization?'<i class="cap">капитализация бонуса</i>':'',a.fixed_income?`<i class="fix">фикс. +${projectMoney(a.fixed_income,p.currency)} за ${PROJECT_PERIODS[p.period]}</i>`:'',
     a.bonus_status==='active'?`<i class="bonus">Бонус ${projectMoney(a.bonus_current_amount,p.currency)}${a.bonus_expires_at?` · до ${esc(date(a.bonus_expires_at))}`:''}</i>`:'',
     a.bonus_status==='expired'?`<i class="expired">Бонус завершён${a.bonus_expires_at?` · ${esc(date(a.bonus_expires_at))}`:''}</i>`:''].filter(Boolean).join(''),
    now=a.current_amount!=null&&a.current_amount!==a.amount?` · сейчас ${projectMoney(a.current_amount,p.currency)}`:'';
   return `<button type="button" class="project-account pa-card" data-ui-key="project-account-${esc(a.id)}" data-action="project-account-edit" data-id="${esc(p.id)}" data-account="${esc(a.id)}"><span class="pa-top">${p.accounts.length>1?`<span class="pa-grip" role="button" aria-label="Перетащить аккаунт" title="Потяните, чтобы изменить порядок"><svg class="pa-grip-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/></svg></span><span class="project-account-number">${num}</span>`:''}<span class="pa-title"><b>${esc(a.name||`Аккаунт ${i+1}`)}</b><small>Ваши ${projectMoney(a.amount,p.currency)}${now}</small></span><span class="pa-work"><b>${projectMoney(a.working_amount,p.currency)}</b><small>работает</small></span>${icon('chevron')}</span>${p.accounts.length>1?`<span class="pa-bar" aria-hidden="true"><i style="--w:${share.toFixed(1)}%"></i></span>`:''}${tags?`<span class="pa-tags">${tags}</span>`:''}<span class="pa-income">${a.expected_income==null?'—':projectIncome({...p,expected_income:a.expected_income,daily_income:a.daily_income})}</span></button>`;}).join('');
 return `<div class="project-space">${back}${header(p.name,projectRateLabel(p),button('project-edit','Редактировать','secondary','',`data-id="${esc(p.id)}"`))}${state.projectsError?notice('Не удалось обновить проект. Показаны последние данные.',true):''}<section class="panel project-detail-summary" data-ui-key="project-summary-${esc(p.id)}">${projectFinance(p,{detail:true})}</section><section class="panel"><div class="project-accounts-head"><h2>${countLabel(p.accounts.length,['аккаунт','аккаунта','аккаунтов'])}</h2></div>${accounts}${button('project-account-add','Добавить аккаунт','secondary pa-add','plus',`data-id="${esc(p.id)}"`)}</section><div class="actions">${button('project-delete','Удалить проект','danger small','',`data-id="${esc(p.id)}"`)}</div></div>`;
}
const TAG_ID='tagmarket-system';
function tagSelected(){const sel=state.forecast.selected;return sel===null||sel.includes(TAG_ID);}
function forecastBase(){const from=state.forecast.from;return from&&from>projectToday()?from:projectToday();}
function forecastDate(horizon,base=projectToday()){const [y,m,day]=base.split('-').map(Number),offset={'1m':1,'3m':3,'6m':6,'1y':12}[horizon]||0;if(offset){const month=m-1+offset,year=y+Math.floor(month/12),index=month%12+1,last=new Date(Date.UTC(year,index,0)).getUTCDate();return new Date(Date.UTC(year,index-1,Math.min(day,last))).toISOString().slice(0,10);}const d=new Date(Date.UTC(y,m-1,day));d.setUTCDate(d.getUTCDate()+(horizon==='1d'?1:horizon==='1w'?7:0));return d.toISOString().slice(0,10);}
async function fetchForecast(projects=state.projects,untilOverride=''){const f=state.forecast,until=untilOverride||(f.horizon==='custom'?f.until:forecastDate(f.horizon,forecastBase())),params=new URLSearchParams({until,bonus:f.bonus?'1':'0'});if(f.selected!==null){params.set('all','0');for(const id of f.selected)if(id!==TAG_ID)params.append('id',id);}return (await api(`/projects/forecast?${params}`)).projects;}
async function fetchTagForecast(untilOverride=''){const f=state.forecast,until=untilOverride||(f.horizon==='custom'?f.until:forecastDate(f.horizon,forecastBase()));try{return await api(`/tagmarket/forecast?until=${until}`);}catch(error){return {error:error.message||'Прогноз TagMarket временно недоступен'};}}
function tagMultiplier(key,tag=state.forecast.tag){const t=tag;return key==='now'?1:t?.sufficient?(t.multipliers?.[key]??1):1;}
function forecastCell(cp,currency,key){return cp?.calculation_limited||cp?.[key]==null?'—':money(cp[key],currency);}
function forecastPortfolioTotal(result,key,tag=state.forecast.tag){let value=0,partial=false;for(const p of result||[]){const cp=key==='now'?p.current:p.checkpoints?.[key];if(!cp||cp.total==null){partial=true;continue;}const amount=displayAmount(cp.total,p.currency);if(amount==null)partial=true;else value+=amount;}if(tagSelected()){const tagValue=displayAmount((state.data.totals.USD?.capital||0)*tagMultiplier(key,tag),'USD');if(tagValue==null)partial=true;else value+=tagValue;}return {value,partial};}
function forecastAccountDetail(current,projected,currency){return `<div class="forecast-account-detail"><b>${esc(projected.name||'Аккаунт')}</b><small>Ваши средства · ${money(current.current_personal,currency)} → ${money(projected.personal,currency)}</small><small>Бонус · ${money(current.current_bonus,currency)} → ${money(projected.bonus,currency)}</small>${projected.fixed>0?`<small>Фикс. доплаты · +${money(projected.fixed,currency)}</small>`:''}<small>Рабочий капитал · ${money(current.current_working,currency)} → ${money(projected.working,currency)}</small><small>Прирост · ${money(projected.growth,currency,true)}${projected.personal_capitalization?' · капитализация личных':''}${projected.bonus_capitalization?' · капитализация бонуса':''}</small></div>`;}
function forecastBreakdown(project,result){const now=result.current?.accounts||[],end=result.checkpoints?.selected?.accounts||[];return `<details class="forecast-breakdown"><summary>Счета · ${countLabel(end.length,['аккаунт','аккаунта','аккаунтов'])}</summary>${end.map(account=>forecastAccountDetail(now.find(x=>x.account_id===account.account_id)||account,account,project.currency)).join('')}</details>`;}
function forecastGrowth(result,until,tagRows,fromResult=null){const cur=state.displayCurrency,rows=[];
 for(const r of result||[]){const p=(state.projects||[]).find(x=>x.id===r.project_id),sel=r.checkpoints?.selected,now=fromResult?fromResult.find(x=>x.project_id===r.project_id)?.checkpoints?.selected?.total:r.current?.total;if(!sel||sel.total==null||now==null||sel.calculation_limited)continue;const g=displayAmount(sel.total-now,r.currency),base=displayAmount(now,r.currency);if(g==null||base==null)continue;rows.push({name:p?.name||'Проект',g,pct:base>0?g/base*100:null,total:displayAmount(sel.total,r.currency)});}
 for(const t of tagRows||[])rows.push(t);
 if(!rows.length)return '';rows.sort((a,b)=>b.g-a.g);const peak=Math.max(...rows.map(r=>Math.abs(r.g)),0.01);
 return `<div class="forecast-growth"><div class="fg-head"><b>Прирост по проектам</b><small>к ${esc(date(until))}</small></div><ol class="feed">${rows.map(r=>`<li class="feed-day ${r.g<0?'down':'up'}"><span class="feed-date"><b>${esc(r.name)}</b><small>${r.total==null?'':`к ${esc(date(until))}: ${money(r.total,cur)}`}</small></span><span class="feed-bar"><i style="--w:${Math.max(3,Math.abs(r.g)/peak*100).toFixed(1)}%"></i></span><span class="feed-sum"><b class="${signedClass(r.g)}">${money(r.g,cur,true)}</b>${r.pct==null?'':`<small>${percent(r.pct)}</small>`}</span></li>`).join('')}</ol></div>`;}
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
 const f=state.forecast,projects=state.projects||[],until=f.until||forecastDate(f.horizon,forecastBase()),result=f.result,selected=f.selected;
 const horizons=[['now','Сейчас'],['day','День'],['week','Неделя'],['month','Месяц'],['selected',`На ${date(until)}`]],keyFor=['now','day','week','month','selected'];
 const totals=keyFor.map(key=>forecastPortfolioTotal(result,key)),fromMode=!!(f.from&&f.from>projectToday()&&f.fromResult),startTotal=fromMode?forecastPortfolioTotal(f.fromResult,'selected',f.fromTag):totals[0],startLabel=fromMode?`На ${date(f.from)}`:'Сейчас',growth=totals.at(-1).value-startTotal.value;const horizonDays=Math.round((Date.parse(until)-Date.parse(forecastBase()))/864e5);
 const tagCapital=state.data.totals.USD?.capital||0,tf=f.tag,tagOk=!!tf?.sufficient,tagOn=tagSelected(),
  tagShown=key=>{const v=displayAmount(tagCapital*tagMultiplier(key),'USD');return v==null?money(tagCapital*tagMultiplier(key),'USD'):money(v,state.displayCurrency);},
  tagCells=keyFor.map(key=>`${tagOk&&key!=='now'?'≈ ':''}${tagShown(key)}`),
  tagGrowth=(()=>{const a=displayAmount(tagCapital*tagMultiplier('selected'),'USD'),b=displayAmount(tagCapital,'USD');return a==null||b==null?'—':money(a-b,state.displayCurrency,true);})(),
  tagNote=!tf?'':tf.error?'Прогноз временно недоступен':tagOk?`${number(Math.round(tf.average_daily_return*10000)/100)}% / день · ${countLabel(tf.days_used,['торговый день','торговых дня','торговых дней'])}`:'Недостаточно истории для прогноза',
  tagRate=tagOk?`${number(Math.round(tf.average_daily_return*10000)/100)}% / день`:'Доходность / день';
 const projectRows=(result||[]).map(r=>{const p=projects.find(x=>x.id===r.project_id),name=p?.name||'Проект',cp=r.checkpoints||{};return `<tr><th scope="row">${esc(name)}</th>${keyFor.map(key=>`<td>${forecastCell(key==='now'?r.current:cp[key],r.currency,'total')}</td>`).join('')}<td>${forecastCell(cp.selected,r.currency,'growth')}</td></tr><tr class="forecast-detail-row"><td colspan="7">${p?forecastBreakdown(p,r):''}</td></tr>`;}).join('');
 const tagRow=tagOn?`<tr><th scope="row">TagMarket<small>${tagNote}</small></th>${tagCells.map(c=>`<td>${c}</td>`).join('')}<td>${tagGrowth}</td></tr><tr class="forecast-detail-row"><td colspan="7"></td></tr>`:'';
 const mobile=(result?result.map(r=>{const p=projects.find(x=>x.id===r.project_id),cp=r.checkpoints||{};return `<article class="forecast-mobile-card"><h3>${esc(p?.name||'Проект')}</h3><div class="forecast-mobile-grid">${horizons.map(([key,label])=>`<div><small>${label}</small><b>${forecastCell(key==='now'?r.current:cp[key],r.currency,'total')}</b></div>`).join('')}</div>${p?forecastBreakdown(p,r):''}</article>`;}).join(''):'');
 const tagMobile=result&&tagOn?`<article class="forecast-mobile-card"><h3>TagMarket</h3><small class="forecast-note">${tagNote}</small><div class="forecast-mobile-grid">${horizons.map(([,label],i)=>`<div><small>${label}</small><b>${tagCells[i]}</b></div>`).join('')}</div></article>`:'';
 const row=(id,name,meta,checked,extra='')=>`<label class="forecast-project-row ${extra}"><input type="checkbox" name="forecast-project" value="${esc(id)}" ${checked?'checked':''}><span><b>${esc(name)}</b><small>${meta}</small></span></label>`;
 const tagMeta=`${tagRate} · Ваши средства ${money(displayAmount(tagCapital,'USD')??tagCapital,displayAmount(tagCapital,'USD')==null?'USD':state.displayCurrency)}`;
 const horizonButtons=[['1d','1 день'],['1w','1 неделя'],['1m','1 месяц'],['3m','3 месяца'],['6m','6 месяцев'],['1y','1 год']].map(([id,label])=>`<button data-action="forecast-horizon" data-value="${id}" class="${f.horizon===id&&f.horizon!=='custom'?'active':''}">${label}</button>`).join('');
 return `<div class="project-space forecast-space">${header('Прогноз','',button('forecast-back','Проекты','secondary small','back'))}<section class="panel forecast-controls"><div class="forecast-horizons segmented">${horizonButtons}</div><div class="forecast-dates"><label class="field">Считать с<input id="forecast-from" type="date" min="${projectToday()}" value="${esc(forecastBase())}"></label><label class="field">По дату<input id="forecast-date" type="date" min="${esc(forecastBase())}" value="${esc(until)}"></label></div><div class="segmented forecast-bonus"><button data-action="forecast-bonus" data-value="1" class="${f.bonus?'active':''}">С бонусами</button><button data-action="forecast-bonus" data-value="0" class="${!f.bonus?'active':''}">Только мои средства</button></div></section><section class="panel forecast-projects"><div class="panel-head"><h2>Проекты</h2><span class="badge">${countLabel(projects.length+1,['проект','проекта','проектов'])}</span></div>${row(TAG_ID,'TagMarket',tagMeta,tagOn,'forecast-tag-row')}${projects.map(p=>row(p.id,p.name,`${projectRateLabel(p)} · Ваши средства ${projectMoney(p.total,p.currency)}${f.bonus&&p.bonus_total?` · бонус ${projectMoney(p.bonus_total,p.currency)}`:''}`,selected===null||selected.includes(p.id))).join('')}</section>${result?`<section class="panel forecast-result"><span class="eyebrow">${fromMode?`ПОРТФЕЛЬ · ${esc(date(f.from))} → ${esc(date(until))}`:`ПОРТФЕЛЬ НА ${esc(date(until))}`}</span><div class="forecast-summary-values"><div><small>${startLabel}</small><strong>${startTotal.partial?'Частично рассчитан':money(startTotal.value,state.displayCurrency)}</strong></div><div><small>На выбранную дату</small><strong>${totals.at(-1).partial?'Частично рассчитан':money(totals.at(-1).value,state.displayCurrency)}</strong></div><div><small>${fromMode?'Прирост за период':'Расчётный прирост'}</small><strong class="${growth<0?'negative':'positive'}">${startTotal.partial||totals.at(-1).partial?'—':money(growth,state.displayCurrency,true)}</strong>${startTotal.partial||totals.at(-1).partial||!(startTotal.value>0)?'':`<small class="fs-sub">${percent(growth/startTotal.value*100)}${horizonDays>0?` · ≈ ${money(growth/horizonDays,state.displayCurrency,true)} в день`:''}</small>`}</div></div>${forecastMilestones(totals,until,fromMode?{from:f.from,start:startTotal}:null)}${forecastEvents(result,until,fromMode?f.from:null)}${forecastGrowth(result,until,tagOn&&tagOk?[(()=>{const a=displayAmount(tagCapital*tagMultiplier('selected'),'USD'),b=displayAmount(tagCapital*(fromMode?tagMultiplier('selected',f.fromTag):1),'USD');return a==null||b==null?null:{name:'TagMarket',g:a-b,pct:b>0?(a-b)/b*100:null,total:a};})()].filter(Boolean):[],fromMode?f.fromResult:null)}<div class="forecast-table-wrap"><table class="forecast-table"><thead><tr><th>Проект</th>${horizons.map(([,label])=>`<th>${label}</th>`).join('')}<th>Прирост</th></tr></thead><tbody>${tagRow}${projectRows||(tagRow?'':'<tr><td colspan="7">Выберите проекты выше.</td></tr>')}<tr class="forecast-total-row"><th>Итого</th>${totals.map(t=>`<td>${t.partial?'Частично рассчитан':money(t.value,state.displayCurrency)}</td>`).join('')}<td>${totals.some(t=>t.partial)?'—':money(totals.at(-1).value-totals[0].value,state.displayCurrency,true)}</td></tr></tbody></table></div><div class="forecast-mobile-cards">${tagMobile+mobile||'<p class="muted">Выберите проекты выше.</p>'}</div></section>`:''}${result&&totals.some(t=>t.partial)?notice('Часть сумм нельзя перевести по текущему курсу. Недоступные проекты показаны в исходной валюте.',true):''}<p class="stat-note forecast-foot">Расчёт по текущим ставкам и средней доходности TagMarket. Это не гарантия результата.</p></div>`;
}
function localDateTime(iso){if(!iso)return '';const d=new Date(iso);return Number.isFinite(d.getTime())?new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16):'';}
function projectFormAccount(a={},index=0){const seq=++projectFormSeq;return `<div class="project-form-account" data-index="${seq}" ${a.id?`data-id="${esc(a.id)}"`:''}><div class="project-form-account-head"><b>Аккаунт ${index+1}</b></div><div class="project-account-name">${field('Название аккаунта (необязательно)',`account-name-${seq}`,'text',a.name||'','maxlength="96"')}</div>${field('Личный баланс',`account-amount-${seq}`,'number',a.amount??'','required min="0.01" max="1000000000000" step="0.01" inputmode="decimal"')}<div class="project-account-rate">${field('Своя ставка, % (необязательно)',`account-rate-${seq}`,'number',a.rate_percent??'','min="0" max="1000" step="0.0001" inputmode="decimal"')}</div><div class="project-account-fixed">${field('Доплата аккаунту за период, фикс. (необязательно)',`account-fixed-${seq}`,'number',a.fixed_income??'','min="0" max="1000000000000" step="0.01" inputmode="decimal" placeholder="Сверх процента"')}</div><label class="field project-account-cap">Капитализация личного баланса<select name="account-cap-${seq}"><option value="inherit" ${a.capitalization==null?'selected':''}>Как в проекте</option><option value="on" ${a.capitalization===true?'selected':''}>Включена</option><option value="off" ${a.capitalization===false?'selected':''}>Выключена</option></select></label><div class="project-account-cap-date" ${a.capitalization===false?'hidden':''}>${field('Начать с даты',`account-cap-from-${seq}`,'date',a.capitalization_from||'')}</div><label class="check bonus-toggle"><input type="checkbox" data-bonus-toggle ${a.bonus_amount?'checked':''}>Бонусный баланс</label><div class="bonus-fields" ${a.bonus_amount?'':'hidden'}>${field('Сумма бонуса',`account-bonus-${seq}`,'number',a.bonus_amount??'','min="0" max="1000000000000" step="0.01" inputmode="decimal"')}<div>${field('Бонус действует до',`account-bonus-expiry-${seq}`,'datetime-local',localDateTime(a.bonus_expires_at),'')}</div><label class="check"><input type="checkbox" name="account-bonus-cap-${seq}" ${a.bonus_capitalization?'checked':''}>Капитализация бонуса</label></div></div>`;}
function projectFormTotals(){const form=$('.project-form');if(!form)return;const currency=$('[name="currency"]',form)?.value||'USD',capitalization=$('[name="capitalization"]',form),dateField=$('[name="capitalization_from"]',form);let total=0;for(const row of form.querySelectorAll('.project-form-account')){total+=Number($('input[name^="account-amount-"]',row).value)||0;const cap=$('select[name^="account-cap-"]',row),date=$('input[name^="account-cap-from-"]',row);if(cap){const enabled=cap.value==='on'||(cap.value==='inherit'&&capitalization.checked);row.querySelector('.project-account-cap-date').hidden=!enabled;date.disabled=cap.value==='inherit';}}const fixed=$('[name="income_mode"]',form).value==='fixed';form.classList.toggle('fixed',fixed);$('[name="rate_percent"]',form).required=!fixed;$('[name="fixed_income"]',form).required=fixed;dateField.disabled=!capitalization.checked||fixed;dateField.parentElement.hidden=!capitalization.checked||fixed;if(form.querySelector('.project-form-account'))$('.project-form-total',form).innerHTML=`<div><small>Вложено</small><b>${projectMoney(total,currency)}</b></div>`;}

function acceptProject(p){state.projects=state.projects?.some(x=>x.id===p.id)?state.projects.map(x=>x.id===p.id?p:x):[...(state.projects||[]),p];state.projectsError='';viewCache.clear();render();}
async function projectEditor(original=null){
 let draft=original?structuredClone(original):{name:'',currency:'USD',rate_percent:'',income_mode:'percent',fixed_income:'',period:'month',business_days_only:false,multi:false,capitalization:false,capitalization_from:new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk'}).format(new Date()),accounts:[{name:'',amount:'',capitalization:null}]},error='';
 while(true){
  const body=`<div class="project-form">${error?notice(error,true):''}${field('Название','name','text',draft.name,'required maxlength="96"')}${original?'':`<label class="field">Валюта<select name="currency">${['USD','RUB','BYN'].map(cur=>`<option ${cur===draft.currency?'selected':''}>${cur}</option>`).join('')}</select></label>`}<label class="field">Доходность задана<select name="income_mode"><option value="percent" ${draft.income_mode!=='fixed'?'selected':''}>Процентом</option><option value="fixed" ${draft.income_mode==='fixed'?'selected':''}>Фиксированной суммой</option></select></label><div class="field-row"><div class="income-percent">${field('Доходность, %','rate_percent','number',draft.rate_percent,'min="0" max="1000" step="0.0001" inputmode="decimal"')}</div><div class="income-fixed">${field('Сумма за период','fixed_income','number',draft.fixed_income??'','min="0.01" max="1000000000000" step="0.01" inputmode="decimal"')}</div><label class="field">Период<select name="period">${Object.entries(PROJECT_PERIODS).map(([id,label])=>`<option value="${id}" ${id===draft.period?'selected':''}>В ${label}</option>`).join('')}</select></label></div><label class="field daily-accrual-setting" ${draft.period==='day'?'':'hidden'}>Начисление<select name="business_days_only"><option value="0" ${!draft.business_days_only?'selected':''}>Каждый день</option><option value="1" ${draft.business_days_only?'selected':''}>Только по будням</option></select></label><label class="check cap-row"><input type="checkbox" name="capitalization" ${draft.capitalization?'checked':''}>Капитализация проекта</label><div class="project-cap-from">${field('Начать с даты','capitalization_from','date',draft.capitalization_from||'')}</div>${original?`<p class="project-form-note">Аккаунты проекта редактируются в разделе «Аккаунты» на странице проекта.</p><div class="project-form-total" aria-live="polite"><div><small>Вложено</small><b>${projectMoney(original.total,original.currency)}</b></div><div><small>Аккаунтов</small><b>${original.accounts.length}</b></div></div>`:`<div class="project-form-accounts">${draft.accounts.map((a,i)=>projectFormAccount({...a,capitalization_from:a.capitalization_from||(a.capitalization===true?draft.capitalization_from:'')},i)).join('')}</div><p class="project-form-note">Остальные аккаунты можно добавить на странице проекта.</p><div class="project-form-total" aria-live="polite"></div>`}</div>`;
  const pending=dialog(original?'Редактировать проект':'Добавить проект',body);projectFormTotals();const values=await pending;if(!values)return;
  draft={name:values.name,currency:original?original.currency:values.currency,income_mode:values.income_mode==='fixed'?'fixed':'percent',fixed_income:values.income_mode==='fixed'?Number(values.fixed_income):null,rate_percent:values.income_mode==='fixed'?0:Number(values.rate_percent),period:values.period,business_days_only:values.business_days_only==='1',multi:original?original.multi:false,capitalization:values.capitalization==='on',capitalization_from:values.capitalization_from||original?.capitalization_from||new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk'}).format(new Date()),accounts:original?undefined:[...document.querySelectorAll('.project-form-account')].map(row=>({...(row.dataset.id?{id:row.dataset.id}:{}),name:values[`account-name-${row.dataset.index}`]||'',amount:Number(values[`account-amount-${row.dataset.index}`]),rate_percent:values[`account-rate-${row.dataset.index}`]===''?null:Number(values[`account-rate-${row.dataset.index}`]),fixed_income:values[`account-fixed-${row.dataset.index}`]===''?null:Number(values[`account-fixed-${row.dataset.index}`]),capitalization:values[`account-cap-${row.dataset.index}`]==='inherit'?null:values[`account-cap-${row.dataset.index}`]==='on',capitalization_from:values[`account-cap-${row.dataset.index}`]==='inherit'?null:values[`account-cap-from-${row.dataset.index}`]||null}))};
  if(!original)draft.accounts=draft.accounts.map((account,index)=>{const row=document.querySelectorAll('.project-form-account')[index],seq=row?.dataset.index,amount=Number($(`input[name="account-bonus-${seq}"]`,row)?.value||0),expires=$(`input[name="account-bonus-expiry-${seq}"]`,row)?.value;return {...account,bonus_amount:amount>0?amount:null,bonus_expires_at:expires?new Date(expires).toISOString():null,bonus_capitalization:$(`input[name="account-bonus-cap-${seq}"]`,row)?.checked||false,bonus_activated_at:original?.accounts.find(a=>a.id===account.id)?.bonus_activated_at||null};});
  try{const p=await api('/projects'+(original?'/'+original.id:''),{method:original?'PATCH':'POST',body:JSON.stringify(draft)});acceptProject(p);location.hash='project/'+p.id;toast('Проект сохранён');return;}catch(exc){error=exc.message;}
 }
}
async function projectAccountEditor(p,a=null){let draft=a?{capOn:a.capitalization??p.capitalization,name:a.name,amount:a.amount,rate_percent:a.rate_percent??'',capitalization:a.capitalization,capitalization_from:a.capitalization_from||'',fixed_income:a.fixed_income??'',bonus_amount:a.bonus_amount??'',bonus_expires_at:localDateTime(a.bonus_expires_at),bonus_capitalization:!!a.bonus_capitalization}:{capOn:!!p.capitalization,name:'',amount:'',rate_percent:'',fixed_income:'',bonus_amount:'',bonus_expires_at:'',bonus_capitalization:false,capitalization:null,capitalization_from:new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk'}).format(new Date())},error='';while(true){const body=`${error?notice(error,true):''}${field('Название (необязательно)','name','text',draft.name,'maxlength="96"')}${field(`Сумма, ${p.currency}`,'amount','number',draft.amount,'required min="0.01" max="1000000000000" step="0.01" inputmode="decimal"')}${field('Своя ставка, % (необязательно)','rate_percent','number',draft.rate_percent,`min="0" max="1000" step="0.0001" inputmode="decimal" placeholder="Ставка проекта: ${number(p.rate_percent)}%"`)}${field(`Доплата за ${PROJECT_PERIODS[p.period]}, ${p.currency} (необязательно)`,'fixed_income','number',draft.fixed_income,'min="0" max="1000000000000" step="0.01" inputmode="decimal" placeholder="Сверх процента"')}<label class="check cap-switch"><input type="checkbox" name="capitalization" ${draft.capOn?'checked':''}>Капитализация</label><div class="account-cap-date" data-needs="${(!p.capitalization||(a&&a.capitalization===true))?'1':'0'}" ${draft.capOn&&(!p.capitalization||(a&&a.capitalization===true))?'':'hidden'}>${field('Начать с даты','capitalization_from','date',draft.capitalization_from||p.capitalization_from)}</div>${`<label class="check bonus-toggle"><input type="checkbox" data-bonus-toggle ${draft.bonus_amount?'checked':''}>Бонусный баланс</label><div class="bonus-fields" ${draft.bonus_amount?'':'hidden'}>${field('Сумма бонуса','bonus_amount','number',draft.bonus_amount,'min="0" max="1000000000000" step="0.01" inputmode="decimal"')}<div>${field('Бонус действует до','bonus_expires_at','datetime-local',draft.bonus_expires_at,'')}</div><label class="check"><input type="checkbox" name="bonus_capitalization" ${draft.bonus_capitalization?'checked':''}>Капитализация бонуса</label></div>`}${a&&p.accounts.length>1?`<div class="guest-danger">${button('project-account-delete','Удалить аккаунт','danger small','',`data-id="${esc(p.id)}" data-account="${esc(a.id)}"`)}</div>`:''}`;const values=await dialog(a?'Редактировать аккаунт':'Добавить аккаунт',body);if(!values)return;draft={name:values.name,amount:Number(values.amount),rate_percent:values.rate_percent===''?null:Number(values.rate_percent),fixed_income:values.fixed_income===''?null:Number(values.fixed_income),bonus_amount:Number(values.bonus_amount)>0?Number(values.bonus_amount):null,bonus_expires_at:values.bonus_expires_at||'',bonus_capitalization:values.bonus_capitalization==='on',capitalization:null,capitalization_from:null};const capOn=values.capitalization==='on',initialOn=a?(a.capitalization??p.capitalization):!!p.capitalization;if(a&&capOn===!!initialOn){draft.capitalization=a.capitalization;draft.capitalization_from=a.capitalization===true?(values.capitalization_from||a.capitalization_from||projectToday()):null;}else if(capOn===!!p.capitalization){draft.capitalization=null;draft.capitalization_from=null;}else{draft.capitalization=capOn;draft.capitalization_from=capOn?(values.capitalization_from||projectToday()):null;}draft.capOn=capOn;try{const expires=draft.bonus_expires_at?new Date(draft.bonus_expires_at):null;if(expires&&Number.isNaN(expires.getTime()))throw new Error('Некорректная дата окончания бонуса');const payload={...draft,capOn:undefined,bonus_expires_at:draft.bonus_amount&&expires?expires.toISOString():null,bonus_activated_at:draft.bonus_amount?(a?.bonus_activated_at||null):null,bonus_capitalization:draft.bonus_amount?draft.bonus_capitalization:false};const saved=await api(`/projects/${p.id}/accounts${a?'/'+a.id:''}`,{method:a?'PATCH':'POST',body:JSON.stringify(payload)});acceptProject(saved);toast('Аккаунт сохранён');return;}catch(exc){error=exc.message;}}}
async function projectAction(action,el){
  if(action==='project-create')return projectEditor();
 const p=state.projects?.find(p=>p.id===el.dataset.id);if(!p)throw new Error('Проект не найден');
 if(action==='project-edit')return projectEditor(p);
 if(action==='project-delete'){if(await confirm(`Удалить проект «${p.name}»?`,'Проект и его аккаунты исчезнут из вашего списка.','Удалить')){await api('/projects/'+p.id,{method:'DELETE'});state.projects=state.projects.filter(x=>x.id!==p.id);viewCache.clear();location.hash='projects';render();toast('Проект удалён');}return;}
 if(action==='project-account-add'){el.hidden=true;try{await projectAccountEditor(p);}finally{el.hidden=false;}return;}
 const a=p.accounts.find(a=>a.id===el.dataset.account);if(!a)throw new Error('Аккаунт не найден');
 if(action==='project-account-edit')return projectAccountEditor(p,a);
 if(action==='project-account-delete'){if($('#dialog').open&&!await requestDialogExit($('#dialog')))return;if(p.accounts.length===1)throw new Error('Последний аккаунт удаляется вместе с проектом');const title=a.name||`Аккаунт ${p.accounts.indexOf(a)+1}`;if(await confirm(`Удалить аккаунт «${title}»?`,'Итог проекта будет пересчитан.','Удалить'))acceptProject(await api(`/projects/${p.id}/accounts/${a.id}`,{method:'DELETE'}));}
}
document.addEventListener('input',event=>{if(event.target.closest('.project-form'))projectFormTotals();});
document.addEventListener('change',event=>{if(event.target.matches('.project-form [name="period"]'))event.target.closest('.project-form').querySelector('.daily-accrual-setting').hidden=event.target.value!=='day';if(event.target.matches('.project-form [name="capitalization"]')&&event.target.checked)event.target.closest('.project-form').querySelector('[name="capitalization_from"]').value=projectToday();if(event.target.matches('.project-form select[name^="account-cap-"]')&&event.target.value==='on')event.target.closest('.project-form-account').querySelector('.project-account-cap-date input').value=projectToday();if(event.target.matches('.project-form select,.project-form input,.project-form [name="period"]'))projectFormTotals();if(event.target.matches('#dialog .cap-switch input')){const box=$('#dialog .account-cap-date');if(box){box.hidden=!(event.target.checked&&box.dataset.needs==='1');const date=box.querySelector('input');if(event.target.checked&&date&&!date.value)date.value=projectToday();}}});
async function addAccount(){
 const known=[...new Set(state.data.accounts.filter(a=>!a.demo&&!a.shared).map(a=>a.cabinet).filter(Boolean))];
 const choice=known.length?`<label class="field">Кабинет<select name="cabinet_choice" id="add-cabinet-choice">${known.map(c=>{const owner=state.data.accounts.find(a=>a.cabinet===c)?.holder;return `<option value="${esc(c)}">${esc(owner?`${owner} · ${c}`:c)}</option>`;}).join('')}<option value="new">Другой кабинет…</option></select></label><div id="add-new-cabinet" hidden>${field('Customer Number нового кабинета','cabinet','text','','required disabled maxlength="32" placeholder="Например, CU228816"')}</div>`:field('Customer Number кабинета','cabinet','text','','required maxlength="32" placeholder="Например, CU228816"');
 const form=`<p>Используйте инвесторский пароль MT5: он даёт доступ к просмотру.</p>${choice}${field('Название стратегии','name','text','','required maxlength="48" placeholder="Например, SONIC или NEO"')}${field('Номер счёта MT5','login','number','','required min="1" step="1" placeholder="Например, 10001234"')}${field('Инвесторский пароль','password','password','','required maxlength="128" autocomplete="new-password" placeholder="Пароль инвестора MT5"')}<div class="auto-field"><span>Сервер и владелец</span><b>Определятся автоматически</b><small>После первой синхронизации с MT5</small></div><a class="text-link account-help" href="#faq/connect" data-action="account-help">Как открыть счёт ${icon('arrow')}</a>`;
 const data=await dialog('Подключить счёт MT5',form,'Подключить');if(!data)return;
 if(known.length){data.cabinet=data.cabinet_choice==='new'?data.cabinet:data.cabinet_choice;delete data.cabinet_choice;}
 await mutate('/accounts',data);location.hash='accounts';
}
async function configureAccount(login){const a=state.data.accounts.find(a=>Number(a.login)===Number(login));if(!a)return;const capital=!a.demo&&!a.shared?`${field('Капитал Invested','base','number',a.base??'','min="0" max="1000000000000" step="0.01"')}<p class="stat-note">Если указать сумму из портала, она станет основой расчёта капитала. Дальнейшие пополнения и выводы прибавятся автоматически.</p>${a.base!=null?'<label class="check"><input type="checkbox" name="reset_base"> Вернуть автоматический расчёт</label>':''}`:'';const body=`${a.demo?notice('Общий счёт для просмотра. Настройки уведомлений личные.'):field('Название стратегии','name','text',a.strategy||a.name,'required maxlength="48"')}<label class="check"><input type="checkbox" name="enabled" ${a.enabled?'checked':''}>${a.demo?'Показывать общий счёт':'Отслеживать счёт'}</label>${[['all','Все уведомления'],['trades','Сделки'],['deposits','Пополнения'],['withdrawals','Выводы']].map(([k,v])=>`<label class="check"><input type="checkbox" name="${k}" ${a.notify?.[k]!==false?'checked':''}>${v}</label>`).join('')}${capital}${!a.demo?`<div class="inline-actions mt">${button('delete-account','Удалить счёт из кабинета','danger small','',`data-login="${esc(a.login)}"`)}</div><p class="stat-note">Счёт у брокера и терминал останутся без изменений.</p>`:''}`;const values=await dialog('Настройки счёта',body);if(!values)return;const data={enabled:values.enabled==='on',notify:Object.fromEntries(['all','trades','deposits','withdrawals'].map(k=>[k,values[k]==='on']))};if(values.name)data.name=values.name;if(values.reset_base==='on')data.base=null;else if(values.base!==''&&values.base!==undefined&&Number(values.base)!==a.base)data.base=Number(values.base);await mutate(`/accounts/${a.login}`,data,'PATCH');}
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action]');if(!el)return;event.preventDefault();const action=el.dataset.action;if(el.disabled)return;el.disabled=true;try{
 if(action.startsWith('project-'))await projectAction(action,el);
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
 else if(action==='onboard-later'){if(!preview)await api('/onboarding',{method:'POST',body:JSON.stringify({step:'later',done:true})});state.data.onboarding.later=true;location.hash='overview';}
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
  const d=await dialog('Сообщение пользователям',`<div class="composer">
   <div class="composer-intro"><span class="eyebrow">РАССЫЛКА</span><p>Напишите сообщение, посмотрите, как оно выглядит у получателя, и проверьте перед отправкой.</p></div>
   <div class="cmp-block"><span class="cmp-label">Кому</span><div class="segmented cmp-seg" role="group" aria-label="Получатели"><button type="button" class="active" data-cmp-target="all">Всем · ${users.length}</button><button type="button" data-cmp-target="one">Одному</button></div>
    <label class="field cmp-one" hidden>Пользователь<select name="target"><option value="all" selected>Все приглашённые · ${users.length}</option>${users.map(u=>`<option value="${esc(u.id)}">${esc(u.name)}</option>`).join('')}</select></label></div>
   <div class="cmp-block"><span class="cmp-label">Быстрый старт</span><div class="cmp-chips">${[['maintenance','Технические работы'],['feature','Новая функция'],['reminder','Напоминание'],['thanks','Благодарность']].map(([id,label])=>`<button type="button" class="cmp-chip" data-template="${id}">${label}</button>`).join('')}</div></div>
   <div class="composer-editor"><div class="composer-editor-head"><b>Текст</b><span id="compose-count">0 / 4096</span></div><div class="cmp-meter" aria-hidden="true"><i id="compose-meter"></i></div>
    <div class="compose-tools"><button type="button" class="format-btn" data-format="bold" aria-label="Жирный" title="Жирный"><b>Ж</b></button><button type="button" class="format-btn" data-format="italic" aria-label="Курсив" title="Курсив"><i>К</i></button><button type="button" class="format-btn" data-format="mono" aria-label="Моноширинный" title="Моноширинный"><code>М</code></button><button type="button" class="format-btn" data-format="quote" aria-label="Цитата" title="Цитата">❝</button><span>Выделите текст для оформления</span><button type="button" class="cmp-clear" data-cmp-clear hidden>Очистить</button><label class="format-btn cmp-attach" title="Фото или видео" aria-label="Прикрепить фото или видео"><input type="file" name="media" accept="image/jpeg,image/png,video/mp4" class="cmp-file-input"><svg class="cmp-clip" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5 12.6 19.9a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"/></svg></label></div>
    <textarea name="text" aria-label="Текст сообщения" placeholder="Напишите, что важно сообщить пользователям…"></textarea><div class="cmp-file" hidden><svg class="cmp-clip" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5 12.6 19.9a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"/></svg><small id="compose-file-name">JPG/PNG до 10 МБ · MP4 до 20 МБ</small><button type="button" class="cmp-file-clear" data-cmp-file-clear aria-label="Убрать файл">×</button></div></div><div class="cmp-block"><label class="check"><input type="checkbox" name="with_button" data-cmp-button>Кнопка «Открыть приложение»</label><div class="cmp-button-field" hidden>${field('Текст на кнопке','button_text','text','Открыть приложение','maxlength="40"')}</div></div>
   <div class="composer-live"><span class="eyebrow">ТАК УВИДЯТ ПОЛЬЗОВАТЕЛИ</span><div class="cmp-bubble"><b class="cmp-bubble-name">Tag Markets</b><div id="compose-live" class="compose-preview-text"><span class="muted">Сообщение появится здесь</span></div><small class="cmp-bubble-time">сейчас</small></div><div class="cmp-bubble-btn" id="compose-btn-preview" hidden></div></div></div>`,'Проверить');
  if(!d)return;
  const file=d.media?.size?d.media:null;
  if(broadcastLength(d.text)>4096)throw new Error('Текст длиннее 4096 символов — сократите сообщение');
  if(!String(d.text||'').trim()&&!file)throw new Error('Добавьте текст или файл');
  const kind=file?await mediaKind(file):null;
  if(file&&!kind)throw new Error('Выберите JPG, PNG или MP4');
  if(file&&file.size>(kind==='video'?20:10)*1024*1024)throw new Error('Фото до 10 МБ, видео до 20 МБ');
  const buttonText=d.with_button==='on'?(String(d.button_text||'').trim()||'Открыть приложение').slice(0,40):'';
  const recipient=d.target==='all'?`все приглашённые (${users.length})`:users.find(u=>String(u.id)===String(d.target))?.name||'пользователь';
  const objectUrl=file?URL.createObjectURL(file):null;
  try{
   const media=file?`<div class="compose-preview-media">${kind==='photo'?`<img src="${esc(objectUrl)}" alt="Приложенное фото">`:`<video src="${esc(objectUrl)}" controls preload="metadata"></video>`}<small>${esc(file.name)} · ${fileSize(file.size)}</small></div>`:'';
   const body=`<p class="compose-recipient">Кому: <b>${esc(recipient)}</b></p><div class="cmp-bubble cmp-review"><b class="cmp-bubble-name">Tag Markets</b>${media}<div class="compose-preview-text">${d.text?broadcastPreview(d.text):'<span class="muted">Без подписи</span>'}</div><small class="cmp-bubble-time">сейчас</small></div>${buttonText?`<div class="cmp-bubble-btn">${esc(buttonText)}</div>`:''}<p class="compose-footnote">Проверьте сообщение перед отправкой: после неё его нельзя отозвать.</p>`;
   if(!await dialog('Проверка рассылки',body,'Отправить'))return;
  }finally{if(objectUrl)URL.revokeObjectURL(objectUrl);}
  if(preview){await dialog('Демо-режим',`<p>Макет показывает редактор и вложение, но не отправляет сообщения. Для настоящей рассылки откройте приложение из <a href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">бота в Telegram</a>.</p>`,'Понятно');return;}
  const requestId=crypto.randomUUID();
  for(;;){
   const form=new FormData();form.append('target',d.target);form.append('text',d.text||'');form.append('request_id',requestId);if(buttonText)form.append('button_text',buttonText);if(file)form.append('media',file);
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
$('#notifications').innerHTML=icon('bell');$('#refresh').innerHTML=icon('refresh');$('#refresh').addEventListener('click',()=>refresh());
let savedScheme;try{savedScheme=localStorage.getItem('tag-scheme');}catch{}setScheme(savedScheme||'lime',false);
try{tg?.ready();tg?.expand();tg?.BackButton?.onClick(()=>{if($('#dialog').open){requestDialogExit($('#dialog'));return;}location.hash=state.view==='project'?'projects':'accounts';});tg?.onEvent('homeScreenAdded',()=>toast('Ярлык Tag Markets добавлен на экран'));tg?.onEvent('homeScreenChecked',e=>{if(e?.status==='added')toast('Ярлык уже добавлен');});tg?.onEvent('homeScreenFailed',()=>toast('Telegram не смог добавить ярлык'));}catch{}
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
 feature:'<b>Новое в Tag Markets</b>\n\nДобавили … Откройте приложение и посмотрите в разделе «…».',
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
