'use strict';
const $ = (s, root = document) => root.querySelector(s);
const tg = window.Telegram?.WebApp;
const preview = new URLSearchParams(location.search).get('preview') === '1';
const state = {data:null, people:null, admin:null, report:null, reportError:'', priceChart:null, notifications:{items:[],unread:0}, view:'overview', login:null, period:'today', kind:'trades', offset:0, from:'', to:'', filters:{overview:{period:'today',from:'',to:''},account:{period:'today',from:'',to:''}}, busy:false, currency:null};
let generation = 0, refreshTimer, toastTimer, notificationsStarted = false, lastNotificationId = 0;
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
function money(value, cur='USD', signed=false){if(value==null||!Number.isFinite(Number(value)))return '—';const opts={maximumFractionDigits:2,signDisplay:signed?'exceptZero':'auto'};try{return new Intl.NumberFormat('ru-RU',{...opts,style:'currency',currency:cur||'USD'}).format(value);}catch{return `${new Intl.NumberFormat('ru-RU',{...opts,minimumFractionDigits:2}).format(value)} ${esc(cur)}`;}}
function number(value){return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value||0);}
function percent(value){return `${value>=0?'+':''}${new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:3}).format(value)}%`;}
function resultPair(value,cur,pct){return `<span class="result-pair ${signedClass(value)}"><b>${money(value,cur,true)}</b>${pct==null?'':`<small title="Доля от текущего вложенного капитала">${percent(pct)}</small>`}</span>`;}
function date(value, full=false){const raw=String(value||'');const iso=raw.length===10?raw+'T00:00:00Z':/(Z|[+-]\d{2}:\d{2})$/.test(raw)?raw:raw+'Z';return new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'short',...(full?{hour:'2-digit',minute:'2-digit',timeZone:'UTC'}:{})}).format(new Date(iso));}
function dayLabel(value){const text=new Intl.DateTimeFormat('ru-RU',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`));return text.charAt(0).toUpperCase()+text.slice(1);}
function signedClass(value){return value<0?'negative':'positive';}
function notice(text, warning=false){return `<div class="notice ${warning?'warning':''}">${esc(text)}</div>`;}
function toast(text){const el=$('#toast');el.classList.remove('has-event');el.textContent=text;el.classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('visible'),4500);}
function since(value){const raw=String(value||'');const t=Date.parse(/(Z|[+-]\d{2}:\d{2})$/.test(raw)?raw:raw+'Z');if(!Number.isFinite(t))return '';const sec=Math.max(0,(Date.now()-t)/1000);if(sec<60)return 'только что';if(sec<3600)return `${Math.floor(sec/60)} мин назад`;if(sec<86400)return `${Math.floor(sec/3600)} ч назад`;return date(value,true);}
function agoText(sec){if(sec==null)return 'нет данных';if(sec<60)return 'только что';if(sec<3600)return `${Math.floor(sec/60)} мин назад`;if(sec<86400)return `${Math.floor(sec/3600)} ч назад`;return `${Math.floor(sec/86400)} дн назад`;}
function eventKind(item){return ({trades:['Новая сделка','chart'],deposits:['Пополнение','up'],withdrawals:['Вывод','down'],registration:['Новый гость','people'],message:['Сообщение','bell']})[item.kind]||['Событие','bell'];}
function notificationTarget(item){const match=/^trade:(\d+):/.exec(item.event_key||'');if(match&&state.data?.accounts.some(a=>String(a.login)===match[1]))return {hash:'account/'+match[1],label:'Открыть счёт'};if(['trades','deposits','withdrawals'].includes(item.kind))return {hash:'accounts',label:'Открыть счета'};if(item.kind==='registration')return {hash:'people',label:'Открыть гостей'};return {hash:'',label:'Читать'};}
function eventToast(item,count){const el=$('#toast'),[kind,ico]=eventKind(item);el.innerHTML=`<div class="event-toast kind-${esc(item.kind||'other')}" role="alert"><button type="button" class="event-toast-main" data-action="notification-open" data-id="${esc(item.id)}"><span class="event-toast-icon">${icon(ico)}</span><span class="event-toast-copy"><b>${count>1?`${count} новых · `:''}${esc(item.title)}</b><span>${esc(item.body)}</span></span><span class="event-toast-go">${icon('arrow')}</span></button><button type="button" class="event-toast-close" data-action="toast-close" aria-label="Закрыть">×</button><i class="event-toast-timer"></i></div>`;el.classList.add('visible','has-event');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('visible'),6000);}
function button(action,text,style='secondary',ico='',attrs=''){return `<button type="button" class="button ${style}" data-action="${action}" ${attrs}>${ico?icon(ico):''}<span class="button-label">${esc(text)}</span></button>`;}
function broadcastPreview(text){return esc(text).replace(/&lt;(\/?)(b|i|code|blockquote)&gt;/g,'<$1$2>');}
function fileSize(bytes){return `${number(bytes/1024/1024)} МБ`;}
async function mediaKind(file){const b=new Uint8Array(await file.slice(0,12).arrayBuffer());if(b[0]===255&&b[1]===216&&b[2]===255)return 'photo';if([137,80,78,71,13,10,26,10].every((v,i)=>b[i]===v))return 'photo';if(b[4]===102&&b[5]===116&&b[6]===121&&b[7]===112)return 'video';return null;}
const tabs=[['overview','Обзор'],['accounts','Счета'],['people','Гости'],['settings','Настройки']];
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
 const active=state.view==='account'?'accounts':state.view==='faq'?'overview':state.view;
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
 const crumb=$('#crumb'),title=state.view==='account'?'Счета / Счёт':state.view==='faq'?'Частые вопросы':tabs.find(([id])=>id===state.view)?.[1]||'Счёт';
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
const VIEW_ORDER={overview:0,faq:.5,accounts:1,account:1.5,people:2,settings:3};
// Въезд — CSS-классом, который снимается по окончании: после WAAPI-анимации
// transform Chromium держал устаревшую карту попаданий, и первое нажатие в
// новом разделе уходило «мимо» кнопки, пока стиль #main не изменится
function enterView(direction){
 if(reducedMotion())return;
 const main=$('#main');
 main.classList.remove('view-enter');
 main.style.setProperty('--enter-x',direction?`${direction*18}px`:'0px');
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
 const shift=direction?`translateX(${-direction*12}px)`:'translateY(-5px)';
 const anim=main.animate([{opacity:1,transform:'none'},{opacity:0,transform:shift}],
                         {duration:260,easing:'cubic-bezier(.45,0,.55,1)',fill:'forwards'});
 // не ждём дольше самой анимации: если вкладка ушла в фон, finished не придёт
 return Promise.race([anim.finished.catch(()=>{}),new Promise(r=>setTimeout(r,320))])
  .then(()=>anim.cancel());
}
$('#main').addEventListener('animationend',event=>{if(event.target===event.currentTarget)event.currentTarget.classList.remove('view-enter');});
function header(title,subtitle='',action=''){return `<div class="page-head"><div><h1>${esc(title)}</h1>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div>${action}</div>`;}
function empty(title,text,action=''){return `<div class="empty">${icon('chart')}<h2>${esc(title)}</h2>${text?`<p>${esc(text)}</p>`:''}${action}</div>`;}
function skeleton(kind='list',rows=3){if(kind==='chart')return `<div class="skel skel-chart" aria-busy="true" aria-label="Загружаем"><i class="skel-line w40"></i><i class="skel-line w25 tall"></i><div class="skel-bars">${[40,62,35,78,52,90,44,66,30,58].map(h=>`<i style="height:${h}%"></i>`).join('')}</div></div>`;return `<div class="skel skel-list" aria-busy="true" aria-label="Загружаем">${Array.from({length:rows},()=>`<div class="skel-card"><i class="skel-ico"></i><span><i class="skel-line w55"></i><i class="skel-line w35"></i></span><i class="skel-line w20"></i></div>`).join('')}</div>`;}
function notificationItem(i){const [kind,ico]=eventKind(i),target=notificationTarget(i);return `<button type="button" data-action="notification-open" data-id="${esc(i.id)}" class="notification-item kind-${esc(i.kind||'other')} ${i.read_at?'':'unread'}"><span class="notification-dot">${icon(ico)}</span><span class="notification-copy"><small class="kicker">${esc(kind)}</small><b>${esc(i.title)}</b><span>${esc(i.body)}</span><small class="meta"><span>${esc(since(i.created_at))}</span><em>${esc(target.label)} ${icon('arrow')}</em></small></span></button>`;}
function notificationPanel(){const items=state.notifications?.items||[],unread=state.notifications?.unread||0;if(!items.length)return `<div class="notification-empty">${icon('bell')}<h3>Событий пока нет</h3></div>`;const today=new Date().toISOString().slice(0,10),yesterday=new Date(Date.now()-864e5).toISOString().slice(0,10),groups=[];for(const i of items){const d=String(i.created_at||'').slice(0,10),label=d===today?'Сегодня':d===yesterday?'Вчера':date(d),last=groups.at(-1);if(last&&last.label===label)last.items.push(i);else groups.push({label,items:[i]});}return `${unread?`<div class="notification-tools">${button('notifications-read','Прочитать всё','secondary small','check')}</div>`:''}<div class="notification-list">${groups.map(g=>`<section class="notification-group"><h3>${esc(g.label)}</h3>${g.items.map(notificationItem).join('')}</section>`).join('')}</div>`;}
function updateNotificationBadge(){const button=$('#notifications');const unread=state.notifications?.unread||0;button.classList.toggle('has-unread',unread>0);button.setAttribute('aria-label',unread?`Уведомления: ${unread} новых`:'Уведомления');}
async function openNotifications(){state.notifications=await api('/notifications');updateNotificationBadge();await dialog('Уведомления',notificationPanel(),'Закрыть');}
async function openNotification(id){const item=state.notifications.items.find(i=>i.id===Number(id));if(!item)return;const d=$('#dialog');if(d.open){const closed=new Promise(resolve=>d.addEventListener('close',resolve,{once:true}));d.close('cancel');await closed;}$('#toast').classList.remove('visible');if(!preview&&!item.read_at){state.notifications=await api('/notifications',{method:'POST',body:JSON.stringify({action:'read',ids:[item.id]})});updateNotificationBadge();}const target=notificationTarget(item);if(target.hash){location.hash=target.hash;return;}await dialog(item.title,`<div class="notification-detail">${esc(item.body).replace(/\n/g,'<br>')}</div>`,'Закрыть');}
async function readAllNotifications(){const ids=(state.notifications?.items||[]).filter(i=>!i.read_at).map(i=>i.id);if(!ids.length)return;if(!preview)state.notifications=await api('/notifications',{method:'POST',body:JSON.stringify({action:'read',ids})});else state.notifications={...state.notifications,unread:0,items:state.notifications.items.map(i=>({...i,read_at:i.read_at||new Date().toISOString()}))};updateNotificationBadge();const body=$('#dialog-body');if(body&&$('#dialog').open)body.innerHTML=notificationPanel();}
async function addShortcut(){const help='<p>Откройте мини-приложение из чата с ботом в Telegram. Нажмите ⋮ справа сверху и выберите «Добавить на главный экран», если этот пункт есть на устройстве.</p><a class="text-link" href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">Открыть бота в Telegram</a>';if(preview||!tg?.initData)return dialog('Ярлык Tag Markets',help,'Понятно');if(!tg?.addToHomeScreen)return dialog('Ярлык Tag Markets',help,'Понятно');try{if(tg.checkHomeScreenStatus)tg.checkHomeScreenStatus(s=>{if(s==='added')toast('Ярлык уже добавлен');else if(s==='unsupported')dialog('Ярлык Tag Markets',help,'Понятно');else tg.addToHomeScreen();});else tg.addToHomeScreen();}catch{return dialog('Ярлык Tag Markets',help,'Понятно');}}
function authScreen(){return `<main class="auth-screen"><div class="auth-glow"></div><div class="auth-brand"><div class="auth-mark"><svg viewBox="0 0 64 64" aria-hidden="true"><path class="logo-halo" d="M14.5 19a24 24 0 0 1 32-3M50.5 22a24 24 0 0 1-2 23M43 50.5a24 24 0 0 1-27-3"></path><path class="logo-letter" d="M20 22h24M32 22v22"></path><path class="logo-trend" d="m18 43 8-8 6 4 14-16"></path><circle class="logo-node" cx="46" cy="23" r="2.8"></circle><circle class="logo-seed" cx="18" cy="43" r="1.8"></circle></svg></div><span class="brand-wordmark"><strong>TAG</strong><small>MARKETS</small></span></div><span class="eyebrow">ЛИЧНЫЙ КАБИНЕТ · TELEGRAM MINI APP</span><h1>Ваш капитал<br><em>в одном ритме.</em></h1><p>Откройте приложение из чата с ботом, чтобы увидеть счета, сделки и гостей в защищённом личном пространстве.</p><a class="button primary auth-button" href="https://t.me/tagmarketgold_bot">Открыть бота в Telegram ${icon('arrow')}</a><small>Ссылка на приложение работает только внутри Telegram.</small></main>`;}
function accountBadge(a){return (a.shared?'<span class="badge">Для наблюдения</span>':'')+(!a.enabled?'<span class="badge">На паузе</span>':a.status==='pending'?'<span class="badge warning">Ожидаем данные счёта</span>':'');}
function accountCard(a,i=0,holder=true){const t=a.totals,cur=t?.cur||'USD';return `<a href="#account/${esc(a.login)}" class="panel account-card"><div class="strategy-icon ${i%2?'':'green'}">${icon('chart')}</div><div class="account-info"><h3>${esc(a.strategy||a.name)}</h3><p>${holder!==false?`${esc(a.holder||a.name)} · `:'MT5 '}${esc(a.login)}</p>${accountBadge(a)}</div><div class="account-money"><b>${t?money(t.now,cur):'—'}</b>${t?`<p class="${signedClass(t.month_net)}">${money(t.month_net,cur,true)} · ${percent(t.month_pct)}<em> мес.</em></p>`:'<p>Пока нет данных</p>'}</div>${icon('chevron','chevron')}</a>`;}
function countLabel(n,forms){const v=Math.abs(Number(n))%100;const n10=v%10;return `${n} ${v>10&&v<20?forms[2]:n10===1?forms[0]:n10>=2&&n10<=4?forms[1]:forms[2]}`;}
function strategyFamily(a){const name=String(a.strategy||a.name||'').trim();return /sonic|sonik/i.test(name)?'SONIC':/neo/i.test(name)?'NEO':name;}
function sonicStrategyCard(){
 const heading=`<div class="strategy-card-head"><div><span class="eyebrow">НАША СТРАТЕГИЯ</span><h3>SONIC</h3></div><span class="strategy-chip">XAUUSD · золото</span></div>`;
 return `<section class="panel strategy-card strategy-full">${heading}<div class="strategy-facts"><span><b>1–2</b><small>сделки в день</small></span><span><b>0,2–0,5%</b><small>депозита на вход</small></span><span><b>30%</b><small>комиссия с прибыли</small></span></div><div class="risk-line">${icon('shield')}<p>Торговый баланс с плечом можно потерять полностью. Прошлые результаты не гарантируют будущих.</p></div><a href="#faq" class="button secondary wide faq-link">${icon('chevron')}<span class="button-label">Частые вопросы</span></a></section>`;
}
const STRATEGY_FAQ=[
 ['Как это работает',[
  ['Что именно делает SONIC','Алгоритм торгует золотом (XAUUSD) на счёте Tag Markets Amplify: 1–2 сделки в день, вход 0,2–0,5% депозита за раз. Вы не торгуете сами — только пополняете счёт и следите за результатом здесь.'],
  ['Почему именно золото','Золото — самый ликвидный и предсказуемый по волатильности инструмент, что позволяет держать риск на сделку небольшим и стабильным.'],
  ['Что такое Amplify ×24','Брокер усиливает ваш торговый баланс плечом ×24: капитал = баланс счёта ÷ 24. Прибыль и убыток считаются от полного торгового баланса, поэтому итог для вашего капитала заметнее. Полные условия — на сайте брокера.','https://www.tagmarkets.com/amplify/','Условия Amplify'],
 ]],
 ['Деньги и комиссия',[
  ['Где физически мои деньги','На вашем личном счёте MT5 у брокера Tag Markets (T.M. Financials Ltd) — не у нас и не в общем пуле. Вы можете запросить вывод в любой момент через кабинет брокера.'],
  ['Какая комиссия и как она списывается','30% с прибыли, только когда стратегия заработала — без прибыли комиссии нет. Списывается автоматически на стороне брокера, в приложении видна отдельной строкой в «Движениях средств».'],
  ['Можно ли потерять деньги','Да — торговый баланс с плечом можно потерять полностью, это не гарантированный доход. Прошлые результаты не обещают будущих.'],
 ]],
 ['Как начать',[
  ['Что нужно, чтобы подключиться','Зарегистрироваться в партнёрском портале по вашей ссылке (раздел «Гости»), создать счёт Tag Markets, пополнить его и добавить сюда инвесторский пароль MT5 — дальше данные обновляются сами.'],
  ['Можно попробовать без своих денег','Да, в приложении есть демо-счёт «Копитрейдинг 45k» — он показывает реальную динамику стратегии, но не входит в ваш капитал.'],
  ['Где посмотреть мой счёт SONIC отдельно','В разделе «Счета» — там открытая история сделок и движений именно по нему.','#accounts','Мои счета'],
 ]],
 ['Брокер и лицензия',[
  ['Кто такой брокер Tag Markets','Tag Markets — торговое название «T.M. Financials Ltd» (регистрационный номер C185265). Регулируется Комиссией по финансовым услугам (FSC) как инвестиционный дилер, лицензия № GB21026474.','https://www.tagmarkets.com/','Сайт брокера'],
  ['При чём тут TM Financials SA','TM FINANCIALS SA (PTY) LTD (рег. № 2024/508189/07) — авторизованный поставщик финансовых услуг (FSP № 55237), регулируется Управлением по финансовому поведению (FSCA). Оказывает только маркетинговые услуги. Торговые счета ведёт, а торговые услуги и ликвидность предоставляет T.M. Financials Ltd.'],
 ]],
];
function strategyFaq(withHeading=true){return `<section class="panel strategy-faq">${withHeading?`<div class="panel-head"><h2>Частые вопросы</h2></div>`:''}${STRATEGY_FAQ.map(([group,items])=>`<div class="faq-group"><span class="eyebrow">${esc(group)}</span>${items.map(([q,a,href,label])=>`<details class="faq-item"><summary>${esc(q)}${icon('chevron')}</summary><p>${esc(a)}</p>${href?`<a class="text-link" href="${esc(href)}"${href.startsWith('#')?'':' target="_blank" rel="noopener"'}>${esc(label)} ${icon('arrow')}</a>`:''}</details>`).join('')}</div>`).join('')}</section>`;}
function faqView(){return `<a href="#overview" class="text-link back">${icon('back')} Обзор</a><div class="page-head"><div><span class="eyebrow">SONIC</span><h1>Частые вопросы</h1></div></div>${strategyFaq(false)}`;}
function sonicGuide(){return `<section class="panel license-card broker-card"><div class="license-card-head"><span class="license-icon">${icon('shield')}</span><div><span class="eyebrow">БРОКЕР И СЧЁТ</span><h2>Tag Markets</h2></div></div><p>Торговое название «T.M. Financials Ltd», регулируется FSC как инвестиционный дилер, лицензия № GB21026474.</p><div class="license-actions"><a class="button secondary" href="https://www.tagmarkets.com/" target="_blank" rel="noopener">Сайт брокера ${icon('arrow')}</a></div></section>`;}
function compactStrategy(a){const name=a.strategy||a.name;const sonic=/sonic|sonik/i.test(name),neo=/neo/i.test(name);return `<section class="panel detail-strategy"><span class="eyebrow">СТРАТЕГИЯ СЧЁТА</span><div><h2>${esc(name)}</h2><span class="badge">${sonic?'XAUUSD':neo?'NEO':'MT5'}</span></div></section>`;}
function chart(points,cur='USD',archived=false,scope='счёта'){if(!points?.length)return ['today','yesterday','week'].includes(state.period)&&isWeekendMsk()?chartEmpty(state.period):empty('Пока без сделок',`За выбранный период у ${scope} нет закрытых сделок.`);let total=0;const values=[0,...points.map(p=>total+=Number(p.value)||0)];const min=Math.min(...values),max=Math.max(...values),range=max-min||1;const coords=values.map((v,i)=>[i/(values.length-1)*640,140-(v-min)/range*120]);const d=coords.map((p,i)=>`${i?'L':'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');return `<div class="chart-wrap"><svg viewBox="0 0 640 160" preserveAspectRatio="none" role="img" aria-label="Накопленный результат закрытых сделок: ${esc(money(total,cur))}"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#b6da88" stop-opacity=".18"/><stop offset="100%" stop-color="#b6da88" stop-opacity="0"/></linearGradient></defs>${[20,60,100,140].map(y=>`<path class="chart-grid" d="M0 ${y}H640"/>`).join('')}<path class="chart-area" d="${d} L640,160 L0,160Z"/><path class="chart-line" d="${d}"/><circle cx="640" cy="${coords.at(-1)[1]}" r="3" fill="var(--accent)" stroke="var(--panel)" stroke-width="2"/></svg></div><div class="chart-meta"><span>${archived?'Дат на графике':'Дней с результатом'} <b>${number(points.length)}</b></span><span>Пик <b>${money(max,cur,true)}</b></span><span>Итог <b class="${signedClass(total)}">${money(total,cur,true)}</b></span></div><div class="chart-labels"><span>${date(points[0].day)}</span><span>${archived?'Архив и сделки':'Закрытые сделки'} · ${esc(cur)}</span><span>${date(points.at(-1).day)}</span></div>`;}
function stats(items){return `<div class="stats ${items.length===2?'stats-two':items.length===1?'stats-one':''}">${items.map(([title,value,note,cls,ico])=>`<div class="panel stat"><div class="stat-title">${esc(title)}${icon(ico||'chart')}</div><div class="stat-value ${cls||''}">${value}</div>${note?`<div class="stat-note">${esc(note)}</div>`:''}</div>`).join('')}</div>`;}
function currentAccount(){return state.data.accounts.find(a=>String(a.login)===String(state.login))||state.data.accounts.find(a=>!a.demo&&a.enabled)||state.data.accounts[0];}
function periodTabs(only){const short={today:'Сегодня',yesterday:'Вчера',week:'Неделя',month:'Месяц',all:'Всё'};const list=only?only.map(k=>[k,short[k]]):periods;return `<div class="segmented ${only?'compact':''}">${list.map(([key,label])=>`<button data-action="period" data-value="${key}" class="${state.period===key?'active':''}">${label}</button>`).join('')}</div>`;}
function isWeekendMsk(){const day=new Date().toLocaleString('en-US',{timeZone:'Europe/Moscow',weekday:'short'});return day==='Sat'||day==='Sun';}
function chartEmpty(period){if(['today','yesterday','week'].includes(period)&&isWeekendMsk())return `<div class="empty chart-empty weekend">${icon('clock')}<h2>Рынок закрыт на выходных</h2><p>Торги возобновятся в понедельник — тогда появится и график.</p></div>`;return `<div class="empty chart-empty">${icon('chart')}<h2>Пока без сделок</h2><p>За этот период движений ещё не было — график появится, как только они будут.</p></div>`;}
function spark(points,cur,period){const rows=(points||[]).slice(-30);
 // За «Сегодня»/«Вчера» в rep.chart физически не может быть больше одной
 // точки (там один день на всю выборку) — раньше это молча читалось как
 // «данных нет» и спорило со сводкой сверху, где сумма и число сделок уже
 // ненулевые. Пустое состояние — это rows.length===0, не <2.
 if(!rows.length)return chartEmpty(period);
 const max=Math.max(...rows.map(p=>Math.abs(Number(p.value)||0)),1e-9);return `<div class="spark" role="img" aria-label="Результат по дням">${rows.map(p=>{const v=Number(p.value)||0;return `<i class="${v<0?'neg':''}" style="height:${Math.max(8,Math.round(Math.abs(v)/max*100))}%" title="${esc(date(p.day))}: ${esc(money(v,cur,true))}"></i>`;}).join('')}</div>`;}
function dayExtremes(points,capital,cur){const rows=(points||[]).filter(p=>Number.isFinite(Number(p.value)));if(rows.length<2)return '';const best=rows.reduce((a,b)=>Number(b.value)>Number(a.value)?b:a),worst=rows.reduce((a,b)=>Number(b.value)<Number(a.value)?b:a);const tile=(label,p)=>`<div class="extreme"><small>${label}</small><span class="result-pair ${signedClass(p.value)}"><b>${money(p.value,cur,true)}</b>${capital>0?`<small>${percent(p.value/capital*100)}</small>`:''}</span><em>${esc(date(p.day))}</em></div>`;return `<div class="extremes">${tile('Лучший день',best)}${tile('Худший день',worst)}</div>`;}
function timeMsk(value){return `${String(value||'').slice(11,16)} МСК`;}
function periodBar(){return `<section class="report-controls panel"><div class="report-control report-period">${periodTabs()}</div></section>${customDates()}`;}
function customDates(){return state.period==='custom'?`<div class="custom-period"><div class="field-row"><label class="field">С даты<input type="date" id="from-date" value="${esc(state.from)}"></label><label class="field">По дату<input type="date" id="to-date" value="${esc(state.to)}"></label></div>${button('apply-period','Показать результат','secondary small')}</div>`:'';}
function onboardingCard(){const url=state.data?.onboarding?.registration_url,p=state.data?.onboarding?.progress||{};const step=(key,n,title,body,action)=>`<div class="onboarding-step ${p[key]?'is-done':''}"><div class="onboarding-visual"><b>${p[key]?'✓':n}</b></div><div><h3>${title}</h3><p>${body}</p>${action||''}</div></div>`;return `<section class="panel welcome-card onboarding-card"><span class="eyebrow">ПЕРВЫЙ ЗАПУСК</span><h2>Личный кабинет за 3 шага</h2><div class="onboarding-steps">${step('registered',1,'Регистрация','Создайте профиль в партнёрском портале по персональной ссылке.',url?`<div class="onboarding-actions"><a class="button primary" href="${esc(url)}" target="_blank" rel="noopener">Открыть регистрацию ${icon('arrow')}</a>${p.registered?'':button('onboard-step','Я зарегистрировался','secondary small','check','data-step="registered"')}</div>`:'<p class="muted">Ссылка регистрации ещё не настроена.</p>')}${step('verified',2,'Верификация','Подтвердите почту и пройдите проверку личности в портале.',p.registered?button('onboard-step','Верификация пройдена','secondary small','check','data-step="verified"'):'<small class="muted">Сначала завершите регистрацию</small>')}${step('broker_account',3,'Счёт и стратегия','Создайте счёт Tag Markets, пополните его и добавьте сюда инвесторский пароль MT5.',p.verified?button('onboard-step','Счёт создан','secondary small','check','data-step="broker_account"'):'<small class="muted">Сначала пройдите верификацию</small>')}</div><p class="stat-note">После подключения счёта этот экран исчезнет. Демо-наблюдение остаётся отдельно и не входит в ваш баланс.</p></section>`;}
function overview(){const d=state.data, curr=state.currency||Object.keys(d.totals)[0]||'USD', t=d.totals[curr]||{capital:0,pnl:0,month:0}, own=d.accounts.filter(a=>!a.demo&&!a.shared), demo=d.accounts.find(a=>a.demo&&a.enabled), rep=state.report;
 if(!own.length&&!demo)return header(`Добро пожаловать, ${d.user.name}`)+onboardingCard();
 if(d.onboarding?.needed)return header('Добро пожаловать')+onboardingCard()+sonicGuide();
 const dynamics=state.reportError?empty('Не удалось построить график',state.reportError):rep?`<div class="dynamics-main fade-swap">${resultPair(rep.summary.net_income,rep.currency,rep.summary.pct_capital)}<span class="muted">${countLabel(rep.summary.count,['сделка','сделки','сделок'])}</span></div>${spark(rep.chart,rep.currency,state.period)}${dayExtremes(rep.chart,t.capital,rep.currency)}`:skeleton('chart');
 return header('Мой кабинет','',button('add','Добавить счёт','secondary','plus'))+
  `<div class="dashboard-grid"><div><section class="panel hero"><div class="hero-top"><span class="eyebrow">Мой капитал</span><span class="hero-pill">${esc(curr)}</span></div><div class="hero-value">${money(t.capital,curr)}</div><div class="hero-bottom"><div><p>За месяц</p>${resultPair(t.month,curr,t.capital>0?t.month/t.capital*100:null)}</div><div class="separator"></div><div><p>Сегодня</p>${resultPair(t.today,curr,t.capital>0?t.today/t.capital*100:null)}</div></div></section>
 ${Object.keys(d.totals).length>1?`<div class="filterbar"><label class="field no-margin">Валюта сводки<select id="currency">${Object.keys(d.totals).map(c=>`<option ${curr===c?'selected':''}>${esc(c)}</option>`).join('')}</select></label></div>`:''}
  <section class="panel chart-panel dynamics"><div class="panel-head"><h2>Динамика</h2>${periodTabs(['today','yesterday','week','month','all'])}</div>${dynamics}</section>
  ${priceChart(state.priceChart)}</div>
 <aside class="side-stack">${sonicStrategyCard()}
 ${demo?`<section class="panel demo-panel"><span class="eyebrow">Публичная стратегия</span><h3>Копитрейдинг 45k</h3><div class="demo-number">${demo.totals?money(demo.totals.now,demo.totals.cur):'—'}</div><span class="badge demo">Не входит в ваш капитал</span><a class="button" href="#account/${esc(demo.login)}">Открыть ${icon('arrow')}</a></section>`:''}</aside></div>`;
}
function balanceCard(personal){const totals=state.data.totals||{},list=Object.keys(totals);if(!list.length)return '';return `<section class="panel balance-card">${list.map(c=>{const x=totals[c];return `<div class="balance-row"><div><span class="eyebrow">ОБЩИЙ БАЛАНС · ${esc(c)}</span><strong>${money(x.capital,c)}</strong><small>${countLabel(personal.length,['счёт','счёта','счетов'])}</small></div><div class="balance-side"><small>За месяц</small>${resultPair(x.month,c,x.capital>0?x.month/x.capital*100:null)}</div></div>`;}).join('')}</section>`;}
function accountsView(){const items=state.data.accounts,personal=items.filter(a=>!a.demo&&!a.shared),shared=items.filter(a=>a.shared&&!a.demo),demo=items.find(a=>a.demo),groups=[...new Set(personal.map(a=>a.cabinet||'Без кабинета'))];
 const group=c=>{const list=personal.filter(a=>(a.cabinet||'Без кабинета')===c);return `<section class="account-group"><div class="account-group-head"><div class="group-title"><h2>${esc(list[0]?.holder||c)}</h2><span class="cab-id">${esc(c)} · ${countLabel(list.length,['счёт','счёта','счетов'])}</span></div></div><div class="account-list">${list.map((a,i)=>accountCard(a,i,false)).join('')}</div></section>`;};
 return header('Счета','',button('add','Добавить счёт','primary','plus'))+(personal.length?balanceCard(personal):'')+groups.map(group).join('')
  +(shared.length?`<section class="account-group"><div class="account-group-head"><div class="group-title"><h2>Для просмотра</h2></div></div><div class="account-list">${shared.map((a,i)=>accountCard(a,i)).join('')}</div></section>`:'')
  +(demo?`<section class="account-group demo-account-group"><div class="account-group-head"><div class="group-title"><span class="eyebrow">ОБЩИЙ СЧЁТ · ПРОСМОТР</span></div>${button('account-settings','Настроить','secondary small','settings',`data-login="${esc(demo.login)}"`)}</div><div class="account-list">${accountCard(demo,1)}</div></section>`:'')
  +(!personal.length&&!shared.length?empty('Ваш первый шаг','Подключите счёт.',button('add','Подключить','primary','plus')):'');}
function pager(rep){return `<div class="inline-actions mt">${state.offset?button('prev','Назад','secondary small','back'):''}${rep.has_more?button('next','Ещё 50','secondary small','arrow'):''}</div>`;}
function groupByDay(rep){const days=new Map();for(const deal of rep.deals){const key=String(deal.time).slice(0,10);if(!days.has(key))days.set(key,[]);days.get(key).push(deal);}return days;}
function tradesTable(rep){
 if(!rep?.deals?.length)return rep?.archived?empty('Детали сохранены итогами','Для старых месяцев доступны суммы в истории по месяцам.'):empty('За этот период операций нет','');
 return `<div class="deal-days">${[...groupByDay(rep)].map(([day,rows])=>{const total=rep.day_totals?.[day];return `<section class="deal-day"><div class="deal-day-head"><div><span class="eyebrow">${countLabel(total?.count??rows.length,['операция','операции','операций'])}</span><h3>${esc(dayLabel(day))}</h3></div>${resultPair(total?.net,rep.currency,total?.pct_capital)}</div><div class="deal-day-list">${rows.map(r=>`<article class="deal-row"><div class="deal-symbol"><span class="deal-icon ${r.net_income<0?'loss':''}">${icon(r.net_income<0?'down':'up')}</span><div><b>${esc(r.symbol)}</b><small>${esc(r.side)} · ${number(r.volume)} лот · ${esc(timeMsk(r.time))}</small></div></div><div class="deal-result">${resultPair(r.net_income,rep.currency,r.pct_capital)}</div></article>`).join('')}</div></section>`;}).join('')}</div>${pager(rep)}`;
}
const MOVE={deposit:['Пополнение стратегии','up','in'],reinvest:['Реинвест профита в капитал','refresh','re'],profit_out:['Вывод профита на баланс Tag Markets','down','out'],profit_in:['Профит вернулся на стратегию','up','in'],capital_out:['Вывод капитала на баланс Tag Markets','down','out']};
function moveRow(r,cur){const [label,ico,dir]=MOVE[r.move]||['Движение средств','chart','in'];return `<article class="deal-row move-row ${dir}"><div class="deal-symbol"><span class="deal-icon move-${dir}">${icon(ico)}</span><div><b>${label}</b><small>${esc(timeMsk(r.time))}</small>${r.capital_now!=null?`<small class="flow">Капитал ${number(r.capital_was)} → <b>${money(r.capital_now,cur)}</b></small>`:''}</div></div><div class="deal-result"><span class="result-pair ${signedClass(r.net_income)}"><b>${money(r.net_income,cur,true)}</b></span></div></article>`;}
function movingAvg(values,period){const out=[];for(let i=0;i<values.length;i++){if(i<period-1){out.push(null);continue;}let sum=0;for(let j=i-period+1;j<=i;j++)sum+=values[j];out.push(sum/period);}return out;}
function priceChart(data){
 const rows=data?.candles||[];
 if(rows.length<2)return `<section class="panel price-chart-panel"><div class="panel-head"><div><span class="eyebrow">ЦЕНА · ${esc(data?.symbol||'XAUUSD')}</span><h2>График цены</h2></div></div>${empty('Пока нет данных','График появится, как только агент передаст котировки за этот период.')}</section>`;
 const closes=rows.map(r=>Number(r.close)),ma20=movingAvg(closes,20),ma50=movingAvg(closes,50);
 const lo=Math.min(...rows.map(r=>Number(r.low))),hi=Math.max(...rows.map(r=>Number(r.high))),range=hi-lo||1;
 const n=rows.length,w=640,h=220,pad=6,step=w/n;
 const x=i=>i*step+step/2,y=v=>pad+(hi-v)/range*(h-pad*2);
 const t0=Date.parse(rows[0].time),t1=Date.parse(rows.at(-1).time),span=Math.max(1,t1-t0);
 const xAt=iso=>{const t=Date.parse(iso);return Math.max(0,Math.min(w,(t-t0)/span*w));};
 const candles=rows.map((r,i)=>{const o=Number(r.open),c=Number(r.close),up=c>=o,color=up?'var(--accent)':'var(--negative)';const bodyTop=y(Math.max(o,c)),bodyBot=y(Math.min(o,c));return `<line x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${y(Number(r.high)).toFixed(1)}" y2="${y(Number(r.low)).toFixed(1)}" stroke="${color}" stroke-width="1"/><rect x="${(x(i)-step*.32).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${(step*.64).toFixed(1)}" height="${Math.max(1,bodyBot-bodyTop).toFixed(1)}" fill="${color}"/>`;}).join('');
 const line=(vals,color)=>{const pts=vals.map((v,i)=>v==null?null:`${x(i).toFixed(1)},${y(v).toFixed(1)}`).filter(Boolean);if(pts.length<2)return '';return `<polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.6" opacity=".85"/>`;};
 const markers=(data.trades||[]).map(m=>{const cx=xAt(m.time),up=m.kind==='in';return `<g class="price-marker ${up?'in':'out'}"><title>${esc(up?'Вход':'Выход')} · ${esc(m.side)} · ${esc(number(m.price))} · ${esc(date(m.time,true))} МСК</title><path d="M${cx.toFixed(1)},${up?h-2:2} l6,${up?10:-10} l-12,0 z"/></g>`;}).join('');
 return `<section class="panel price-chart-panel"><div class="panel-head"><div><span class="eyebrow">ЦЕНА · ${esc(data.symbol)}</span><h2>${esc(data.title||'График цены')}</h2></div><div class="price-legend"><span class="ma20">MA20</span><span class="ma50">MA50</span></div></div><div class="chart-wrap price-chart-wrap"><svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Свечной график ${esc(data.symbol)} со сделками стратегии">${candles}${line(ma20,'var(--purple)')}${line(ma50,'#e4bf7a')}${markers}</svg></div><div class="chart-labels"><span>${date(rows[0].time,true)}</span><span>${countLabel((data.trades||[]).length,['сделка','сделки','сделок'])} на графике</span><span>${date(rows.at(-1).time,true)}</span></div></section>`;
}
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
 const dynamics=`<section class="panel chart-panel detail-chart fade-swap"><div class="panel-head"><div><span class="eyebrow">ДИНАМИКА</span><h2>${esc(rep?.title||'')}</h2></div><span class="badge">${countLabel(rep?.summary.count,['сделка','сделки','сделок'])}</span></div><div class="chart-summary">${resultPair(rep?.summary.net_income,rep?.currency,rep?.summary.pct_capital)}</div>${chart(rep?.chart,rep?.currency,rep?.archived)}${dayExtremes(rep?.chart,t?.now,rep?.currency)}</section>`;
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
function linkCard(p){const partner=p.partner_url,share=p.link?`https://t.me/share/url?url=${encodeURIComponent(p.link)}&text=${encodeURIComponent('Приглашаю в Tag Markets')}`:'';return `<section class="panel link-card"><span class="eyebrow">ВАША ССЫЛКА-ПРИГЛАШЕНИЕ</span><div class="link-step ${partner?'done':'todo'}"><span class="step-n">${partner?'✓':'1'}</span><div><b>Партнёрская ссылка</b><small>${partner?'Сохранена':'IB Portal → Partner'}</small></div>${partner?button('partner-link','Изменить','secondary small'):''}</div>${partner?'':`<a class="button primary wide site-link" href="https://exfusion.ibportal.io" target="_blank" rel="noopener">Открыть партнёрский сайт ${icon('arrow')}</a>${button('partner-link','Вставить ссылку','secondary wide','link')}`}<div class="link-step ${p.link?'done':'todo'}"><span class="step-n">${p.link?'✓':'2'}</span><div><b>Ссылка для гостей</b><small>Одна и постоянная</small></div></div>${p.link?`<div class="invite-url">${esc(p.link)}</div><div class="link-actions">${button('copy','Скопировать','secondary','copy',`data-text="${esc(p.link)}"`)}<a class="button primary" href="${esc(share)}" target="_blank" rel="noopener">${icon('arrow')} Отправить</a>${button('renew-link','Обновить','secondary small','refresh')}</div>`:''}</section>`;}
function guestCard(g,p){const have=new Set(g.accounts.filter(a=>a.shared).map(a=>String(a.login))),canShare=(p.shareable||[]).filter(a=>!have.has(String(a.login)));return `<section class="panel people-card"><div class="person-head"><div class="avatar">${esc(g.name.slice(0,1).toUpperCase())}</div><div><h3>${esc(g.name)}</h3>${g.since?`<p>${esc(g.since)}</p>`:''}</div></div><p>${countLabel(g.accounts.length,['счёт','счёта','счетов'])}</p>${g.accounts.map(a=>`<div class="settings-row"><p>${esc(a.name)} <small>${a.shared?'Ваш счёт у гостя':'Личный счёт · только просмотр'}</small></p>${a.shared?button('take','Забрать','secondary small','',`data-guest="${esc(g.id)}" data-login="${esc(a.login)}"`):''}</div>`).join('')}<div class="actions">${canShare.length?button('share-accounts','Открыть счета','secondary small','plus',`data-guest="${esc(g.id)}"`):''}${button('guest-detail','Подробнее','secondary small','',`data-guest="${esc(g.id)}"`)}${button('revoke-guest','Убрать доступ','danger small','',`data-guest="${esc(g.id)}"`)}</div></section>`;}
function peopleView(){const p=state.people;if(!p)return header('Гости')+skeleton('list',2);return header('Гости')+linkCard(p)+`<div class="section-head"><h2>Приглашены <span class="muted">${p.guests.length}</span></h2></div>${p.guests.length?`<div class="cards-grid">${p.guests.map(g=>guestCard(g,p)).join('')}</div>`:empty('Гостей пока нет','')}`;}
function toggle(label,note,action,on,attrs=''){return `<div class="settings-row"><div><p>${esc(label)}</p>${note?`<small>${esc(note)}</small>`:''}</div><button class="switch" role="switch" aria-label="${esc(label)}" aria-checked="${!!on}" data-action="${action}" ${attrs}></button></div>`;}
const MACHINE_STATE={polling:['Опрашивает','ok'],waiting:['Готова','ok'],legacy:['Старый код','warning'],offline:['Офлайн','muted']};
function nextCheck(sec){if(sec==null)return '';const at=new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'}).format(new Date(Date.now()+sec*1000));const wait=sec<60?'меньше минуты':`${Math.ceil(sec/60)} мин`;return ` Следующая проверка через ${wait}, в ${at} МСК.`;}
function machineRow(m){const [label,cls]=MACHINE_STATE[m.state]||MACHINE_STATE.offline;return `<div class="machine-row state-${esc(m.state)}"><div class="machine-top"><b>${esc(m.host)}</b><span class="badge ${cls}">${label}</span></div><small>${m.role==='primary'?'Основная':m.role==='standby'?'Резервная':'Роль не определена'} · ${esc(agoText(m.idle))}${m.commit?` · <code>${esc(m.commit)}</code>`:''}</small>${m.blocked?`<p class="machine-warn">Обновление заблокировано: ${esc(m.blocked)}.${nextCheck(m.next_check)}</p>`:''}</div>`;}
function serviceSummary(machines){return machines.some(m=>m.state==='polling')?'':'<div class="service-status bad"><b>Терминал никто не опрашивает</b><span>Данные не обновляются</span></div>';}
function servicePanel(){const machines=state.admin?.machines||[];return `<section class="panel service-panel"><div class="service-head"><div><span class="eyebrow">ДЛЯ ВЛАДЕЛЬЦА</span><h2>Сервис</h2></div>${button('refresh','Обновить','secondary small','refresh')}</div>${state.admin?`${serviceSummary(machines)}<div class="machine-list">${machines.map(machineRow).join('')||'<p class="muted">Машины не отвечали.</p>'}</div>`:'<p class="muted mt">Загружаем состояние…</p>'}${toggle('Уведомления о сервисе','','alerts',state.data.update_alerts)}<div class="settings-row"><div><p>Сообщение пользователям</p></div>${button('broadcast','Написать','secondary small')}</div></section>`;}
const BRAND_SVG='<svg viewBox="0 0 64 64" aria-hidden="true"><path class="logo-halo" d="M14.5 19a24 24 0 0 1 32-3M50.5 22a24 24 0 0 1-2 23M43 50.5a24 24 0 0 1-27-3"></path><path class="logo-letter" d="M20 22h24M32 22v22"></path><path class="logo-trend" d="m18 43 8-8 6 4 14-16"></path><circle class="logo-node" cx="46" cy="23" r="2.8"></circle><circle class="logo-seed" cx="18" cy="43" r="1.8"></circle></svg>';
function schemePicker(){const cur=currentScheme();return `<div class="scheme-picker" role="radiogroup" aria-label="Цветовая гамма">${SCHEMES.map(([id,name,,sw])=>`<button type="button" role="radio" aria-checked="${cur===id}" class="scheme ${cur===id?'active':''}" data-action="scheme" data-value="${id}"><span class="swatch" style="background:${sw[0]}"><i style="background:${sw[1]}"></i><i style="background:${sw[2]}"></i></span><b>${name}</b></button>`).join('')}</div>`;}
function settingsView(){const personal=state.data.accounts.filter(a=>!a.demo&&!a.shared),demo=state.data.accounts.find(a=>a.demo);return header('Настройки')+`<div class="two-column"><section class="panel"><span class="eyebrow">ЦВЕТОВАЯ ГАММА</span>${schemePicker()}<button class="shortcut-card" type="button" data-action="shortcut"><span class="shortcut-tile">${BRAND_SVG}</span><span class="shortcut-copy"><b>Ярлык на экран</b><small>Открывать Tag Markets в один тап</small></span><span class="pill">Добавить</span></button></section><section class="panel"><h2>Мои счета</h2>${personal.map(a=>`<div class="settings-row"><div><p>${esc(a.holder||a.strategy||a.name)}</p><small>${esc(a.strategy||a.name)} · ${esc(a.cabinet||a.login)}</small></div>${button('account-settings','Настроить','secondary small','',`data-login="${esc(a.login)}"`)}</div>`).join('')||'<p class="muted mt">Счетов пока нет.</p>'}</section></div>${demo?`<section class="panel settings-demo" aria-label="Общий счёт копитрейдинга"><span class="settings-demo-icon">${icon('chart')}</span><div class="settings-demo-copy"><b>Копитрейдинг 45k</b><small><span class="settings-demo-sum">${demo.totals?money(demo.totals.now,demo.totals.cur):'—'}</span> · общий счёт, просмотр</small></div><div class="settings-demo-actions"><button type="button" class="icon-btn" data-action="account-settings" data-login="${esc(demo.login)}" aria-label="Уведомления общего счёта" title="Уведомления">${icon('bell')}</button><a class="icon-btn" href="#account/${esc(demo.login)}" aria-label="Открыть общий счёт" title="Открыть">${icon('arrow')}</a></div></section>`:''}${state.data.founder?servicePanel():`<section class="panel leave-card"><div><b>Доступ</b><small>Счета и данные будут удалены</small></div><button type="button" class="leave-btn" data-action="leave">${icon('exit')}<span>Отключить мой доступ</span></button></section>`}`;}
// отпечаток всего, из чего строится экран; server_time меняется на каждом
// запросе и на вид не влияет — без него одинаковые данные дают одинаковый ключ
let paintedKey='';
function paintKey(){const {server_time,...data}=state.data||{};return JSON.stringify([state.view,state.login,state.period,state.from,state.to,state.currency,state.kind,state.offset,data,state.report,state.reportError,state.priceChart,state.people,state.admin]);}
function render(){paintedKey='';nav();
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
 const views={overview,accounts:accountsView,account:accountView,people:peopleView,settings:settingsView,faq:faqView};$('#main').innerHTML=(preview?'<div class="preview-label">Демо-режим · вымышленные данные. Отправка сообщений и управление счетами работают только при запуске из <a href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">бота в Telegram</a>.</div>':'')+(views[state.view]||overview)()+(state.view==='settings'&&state.admin?.network?.length?networkView():'');$('#avatar').textContent=state.data.user.name.slice(0,1).toUpperCase();
 // сначала все замеры, потом все записи: чередование чтения и записи в одном
 // цикле заставляет браузер пересчитывать вёрстку на каждой полосе
 const centering=[];
 document.querySelectorAll('.segmented').forEach(strip=>{const active=strip.querySelector('.active');if(active)centering.push([strip,active.getBoundingClientRect().left-strip.getBoundingClientRect().left-(strip.clientWidth-active.clientWidth)/2]);});
 for(const [strip,shift] of centering)strip.scrollLeft+=shift;
 positionThumbs(prevThumbs);
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
 const overviewLast=d.overview_report.chart.at(-1).value;
 d.overview_report.chart[0].value=round(d.overview_report.chart[0].value-(totalToday-overviewLast));
 d.overview_report.chart.at(-1).value=round(totalToday);
 d.overview_report.chart.forEach(point=>{point.day=shifted(point.day)});
 return d;
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
 return {title:'Выбранный период',symbol:'XAUUSD',candles,
  trades:[{time:at(14),side:'buy',price:px(14),kind:'in',symbol:'XAUUSD'},{time:at(22),side:'buy',price:px(22),kind:'out',symbol:'XAUUSD'},
          {time:at(31),side:'sell',price:px(31),kind:'in',symbol:'XAUUSD'},{time:at(38),side:'sell',price:px(38),kind:'out',symbol:'XAUUSD'}]};
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
 return r;
}
async function api(path,options={}){
 if(preview){
  if(path==='/notifications'){const at=m=>new Date(Date.now()-m*60000).toISOString();return {items:[{id:4,kind:'trades',event_key:'trade:10001:123',title:'SONIC · новая сделка',body:'XAUUSD · результат +18,42 $',created_at:at(3),read_at:null},{id:3,kind:'deposits',title:'Пополнение',body:'На счёт NEO.FX зачислено 250,00 $',created_at:at(95),read_at:null},{id:2,kind:'message',title:'Сообщение от сервиса',body:'Завтра с 03:00 до 03:10 возможны короткие перерывы в обновлении данных.',created_at:at(60*30),read_at:at(60*20)},{id:1,kind:'registration',title:'Новый гость',body:'Виктория Орлова приняла приглашение',created_at:at(60*52),read_at:at(60*50)}],unread:2};}
  if(options.method&&options.method!=='GET')throw new Error('В предпросмотре изменения отключены');
  const d=previewData(await fetch('preview.json',{cache:'no-store'}).then(r=>r.json()));
  if(path==='/bootstrap')return d.bootstrap;
  if(path==='/people')return d.people;
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
 const response=await fetch(new URL('../api'+path,location.href),{...options,signal:AbortSignal.timeout(path==='/broadcast'?180000:20000),headers,cache:'no-store'});
 const d=await response.json().catch(()=>({error:'Сервер вернул некорректный ответ'}));
 if(!response.ok)throw new Error(d.error||`Ошибка ${response.status}`);
 return d;
}
async function loadReport(){const params=new URLSearchParams({period:state.period});if(state.period==='custom'){if(!state.from||!state.to)return null;params.set('from',state.from);params.set('to',state.to);}if(state.view==='overview'){params.set('currency',state.currency||Object.keys(state.data.totals)[0]||'USD');return api(`/overview/report?${params}`);}const acc=currentAccount();if(!acc)return null;state.login=acc.login;params.set('kind',state.kind);params.set('offset',state.offset);return api(`/accounts/${acc.login}/report?${params}`);}
// Данные самого раздела сверх общих /bootstrap: отчёт, график цены, гости,
// сервисная панель. Нужны и фоновому обновлению, и переходу между разделами
async function viewParts(){
 const out={};
 if(['overview','account'].includes(state.view)){try{out.report=await loadReport();out.reportError='';}catch(error){out.report=null;out.reportError=error.message;}}
 if(state.view==='overview'){const sonic=state.data.accounts.find(a=>!a.demo&&/sonic|sonik/i.test(`${a.strategy||''} ${a.name||''}`));out.priceChart=sonic?await api(`/accounts/${sonic.login}/candles?period=${state.period==='custom'?'week':state.period}`).catch(()=>null):null;}
 if(state.view==='people')out.people=await api('/people');
 if(state.view==='settings'&&state.data.founder)out.admin=await api('/admin');
 return out;
}
// Переход в раздел, где уже были, показывает запомненное сразу — без запроса
// к серверу и второй перерисовки: раньше каждый переход заново тянул все
// данные и перерисовывал экран, и раздел заметно «обновлялся» на глазах.
// Свежесть держит фоновое обновление; старше его интервала — грузим заново
const viewCache=new Map();
function viewKey(){return [state.view,state.login,state.period,state.from,state.to,state.currency,state.kind,state.offset].join('|');}
function remember(){viewCache.set(viewKey(),{report:state.report,reportError:state.reportError,priceChart:state.priceChart,at:Date.now()});}
function refreshEvery(){return Math.max(30,Number(state.data?.refresh_seconds)||60)*1000;}
const VIEW_NEEDS_DATA=view=>['overview','account','people'].includes(view)||(view==='settings'&&!!state.data?.founder);
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
async function refresh(quiet=false){
 if(state.busy){if(!quiet){state.pendingRefresh=true;generation++;}return;}
 state.busy=true;document.body.classList.add('is-loading');const gen=++generation;
 try{
  const data=await api('/bootstrap');if(gen!==generation)return;state.data=data;scheduleRefresh();
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
  else if(key!==paintedKey&&!document.querySelector('input:focus,textarea:focus,select:focus')){render();paintedKey=key;}
 }catch(error){
  if(!state.data){if(!preview&&!tg?.initData){$('#main').innerHTML=authScreen();}else $('#main').innerHTML=empty('Не удалось открыть кабинет',error.message,button('refresh','Попробовать снова','primary','refresh'));}
  else if(!quiet)toast('Не удалось обновить данные. Показаны последние полученные значения.');
 }finally{state.busy=false;document.body.classList.remove('is-loading');if(state.pendingRefresh){state.pendingRefresh=false;await refresh();}}
}
let navSeq=0;
async function navigate(){
 const seq=++navSeq;
 const [view,login]=location.hash.slice(1).split('/');
 const next=['overview','accounts','account','people','settings','faq'].includes(view)?view:'overview';
 const direction=Math.sign((VIEW_ORDER[next]??0)-(VIEW_ORDER[state.view]??0));
 const moved=next!==state.view||(!!login&&Number(login)!==state.login);
 // тот же раздел (повторное событие hashchange) — экран уже верный
 if(state.data&&!moved)return;
 clearTimeout(choiceTimer);if(state.data)cancelLoads();
 if(state.filters[state.view])state.filters[state.view]={period:state.period,from:state.from,to:state.to};
 if(next!==state.view&&state.filters[next])Object.assign(state,state.filters[next]);
 state.view=next;
 if(login)state.login=Number(login);
 state.offset=0;state.kind='trades';
 const cached=state.data&&viewCache.get(viewKey());
 const fresh=!!state.data&&(!VIEW_NEEDS_DATA(next)||(!!cached&&Date.now()-cached.at<refreshEvery()));
 state.report=cached?cached.report:null;state.reportError=cached?.reportError||'';
 if(cached&&next==='overview')state.priceChart=cached.priceChart;
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
 tg?.BackButton?.[state.view==='account'?'show':'hide']();
}
// [id, название, цвет шапки Telegram, образцы]. Фон у всех схем один —
// графитовый: гамма меняет только акценты, не всю тему
const SCHEMES=[['lime','Лайм','#111416',['#111416','#d0f29b','#b8a6e9']],['sapphire','Сапфир','#111416',['#111416','#5eb3ff','#b18bff']],['velvet','Золото','#111416',['#111416','#e8c576','#d999a8']]];
function currentScheme(){return document.documentElement.dataset.scheme||'lime';}
function setScheme(id,persist=true){const sc=SCHEMES.find(x=>x[0]===id)||SCHEMES[0],root=document.documentElement;root.dataset.scheme=sc[0];try{if(persist)localStorage.setItem('tag-scheme',sc[0]);}catch{}document.querySelector('meta[name="theme-color"]').content=sc[2];try{tg?.setHeaderColor(sc[2]);tg?.setBackgroundColor(sc[2]);}catch{}if(state.data&&state.view==='settings')render();}
function dialog(title,body,label='Сохранить'){return new Promise(resolve=>{const d=$('#dialog');$('#dialog-title').textContent=title;$('#dialog-body').innerHTML=body;$('#dialog-submit').textContent=label;const info=['Закрыть','Понятно','Готово'].includes(label);d.classList.toggle('info-only',info);d.onclick=e=>{if(info&&e.target===d)d.close('cancel');};d.returnValue='';d.onclose=()=>{const values=Object.fromEntries(new FormData($('form',d)));resolve(d.returnValue==='confirm'?values:null);};$('form',d).onsubmit=e=>{if(e.submitter?.value==='cancel')return;const fields=[...d.querySelectorAll('input,select,textarea')];if(!fields.every(f=>f.reportValidity()))e.preventDefault();};d.showModal();});}
async function confirm(title,text,label='Подтвердить'){return !!await dialog(title,`<p>${esc(text)}</p>`,label);}
async function mutate(path,data,method='POST'){await api(path,{method,body:data===undefined?undefined:JSON.stringify(data)});tg?.HapticFeedback?.notificationOccurred('success');toast('Сохранено. Изменения доступны и в боте.');await refresh();}
function field(label,name,type='text',value='',extra=''){return `<label class="field">${esc(label)}<input type="${type}" name="${name}" value="${esc(value)}" ${extra}></label>`;}
async function addAccount(){
 const known=[...new Set(state.data.accounts.filter(a=>!a.demo&&!a.shared).map(a=>a.cabinet).filter(Boolean))];
 const choice=known.length?`<label class="field">Кабинет<select name="cabinet_choice" id="add-cabinet-choice">${known.map(c=>{const owner=state.data.accounts.find(a=>a.cabinet===c)?.holder;return `<option value="${esc(c)}">${esc(owner?`${owner} · ${c}`:c)}</option>`;}).join('')}<option value="new">Другой кабинет…</option></select></label><div id="add-new-cabinet" hidden>${field('Customer Number нового кабинета','cabinet','text','','required disabled maxlength="32" placeholder="Например, CU228816"')}</div>`:field('Customer Number кабинета','cabinet','text','','required maxlength="32" placeholder="Например, CU228816"');
 const form=`<p>Используйте инвесторский пароль MT5: он даёт доступ к просмотру.</p>${choice}${field('Название стратегии','name','text','','required maxlength="48" placeholder="Например, SONIC или NEO"')}${field('Номер счёта MT5','login','number','','required min="1" step="1" placeholder="Например, 10001234"')}${field('Инвесторский пароль','password','password','','required maxlength="128" autocomplete="new-password" placeholder="Пароль инвестора MT5"')}<div class="auto-field"><span>Сервер и владелец</span><b>Определятся автоматически</b><small>После первой синхронизации с MT5</small></div>`;
 const data=await dialog('Подключить счёт MT5',form,'Подключить');if(!data)return;
 if(known.length){data.cabinet=data.cabinet_choice==='new'?data.cabinet:data.cabinet_choice;delete data.cabinet_choice;}
 await mutate('/accounts',data);location.hash='accounts';
}
async function configureAccount(login){const a=state.data.accounts.find(a=>Number(a.login)===Number(login));if(!a)return;const capital=!a.demo&&!a.shared?`${field('Капитал Invested','base','number',a.base??'','min="0" max="1000000000000" step="0.01"')}<p class="stat-note">Если указать сумму из портала, она станет основой расчёта капитала. Дальнейшие пополнения и выводы прибавятся автоматически.</p>${a.base!=null?'<label class="check"><input type="checkbox" name="reset_base"> Вернуть автоматический расчёт</label>':''}`:'';const body=`${a.demo?notice('Общий счёт для просмотра. Настройки уведомлений личные.'):field('Название стратегии','name','text',a.strategy||a.name,'required maxlength="48"')}<label class="check"><input type="checkbox" name="enabled" ${a.enabled?'checked':''}>${a.demo?'Показывать общий счёт':'Отслеживать счёт'}</label>${[['all','Все уведомления'],['trades','Сделки'],['deposits','Пополнения'],['withdrawals','Выводы']].map(([k,v])=>`<label class="check"><input type="checkbox" name="${k}" ${a.notify?.[k]!==false?'checked':''}>${v}</label>`).join('')}${capital}${!a.demo?`<div class="inline-actions mt">${button('delete-account','Удалить счёт из кабинета','danger small','',`data-login="${esc(a.login)}"`)}</div><p class="stat-note">Счёт у брокера и терминал останутся без изменений.</p>`:''}`;const values=await dialog('Настройки счёта',body);if(!values)return;const data={enabled:values.enabled==='on',notify:Object.fromEntries(['all','trades','deposits','withdrawals'].map(k=>[k,values[k]==='on']))};if(values.name)data.name=values.name;if(values.reset_base==='on')data.base=null;else if(values.base!==''&&values.base!==undefined&&Number(values.base)!==a.base)data.base=Number(values.base);await mutate(`/accounts/${a.login}`,data,'PATCH');}
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action]');if(!el)return;event.preventDefault();const action=el.dataset.action;if(el.disabled)return;el.disabled=true;try{
 if(action==='refresh')await refresh();
 else if(action==='notifications')await openNotifications();
 else if(action==='notification-open')await openNotification(el.dataset.id);
 else if(action==='notifications-read')await readAllNotifications();
 else if(action==='scheme')setScheme(el.dataset.value);
 else if(action==='renew-link'){if(await confirm('Обновить ссылку?','Прежняя перестанет работать. Уже вошедшие гости останутся.','Обновить')){const token=String(state.people.link||'').split('start=')[1];await api('/invites/'+token,{method:'DELETE'});await refresh();toast('Ссылка обновлена');}}
 else if(action==='share-accounts'){const g=state.people.guests.find(x=>x.id===el.dataset.guest),have=new Set(g.accounts.filter(a=>a.shared).map(a=>String(a.login))),list=(state.people.shareable||[]).filter(a=>!have.has(String(a.login)));const d=await dialog('Открыть счета гостю',`${list.map(a=>`<label class="check"><input name="login-${a.login}" type="checkbox">${esc(a.name)}${a.cabinet?` · ${esc(a.cabinet)}`:''}</label>`).join('')}<p class="stat-note">Гость увидит их только для просмотра.</p>`,'Открыть');if(d){const logins=Object.keys(d).filter(k=>k.startsWith('login-')).map(k=>Number(k.slice(6)));if(logins.length)await mutate('/guests/'+el.dataset.guest,{action:'share',logins});}}
 else if(action==='toast-close')$('#toast').classList.remove('visible');
 else if(action==='shortcut')await addShortcut();
 else if(action==='period'){if(state.period===el.dataset.value)return;state.period=el.dataset.value;state.offset=0;state.report=null;state.reportError='';if(state.period==='custom')render();else await showCached(el);}
 else if(action==='kind'){state.kind=el.dataset.value;state.offset=0;await showCached(el);}
 else if(action==='next'||action==='prev'){state.offset=Math.max(0,state.offset+(action==='next'?50:-50));await showCached();}
 else if(action==='apply-period'){state.from=$('#from-date').value;state.to=$('#to-date').value;if(!state.from||!state.to||state.from>state.to)throw new Error('Укажите корректные даты начала и конца');await showCached();}
 else if(action==='add')await addAccount();
 else if(action==='onboard-step')await mutate('/onboarding',{step:el.dataset.step,done:true});
 else if(action==='account-settings')await configureAccount(el.dataset.login);
 else if(action==='delete-account'){if($('#dialog').open)$('#dialog').close('cancel');if(await confirm('Удалить счёт?','Он исчезнет из вашего приложения и бота. Торговый счёт у брокера останется.','Удалить')){await mutate(`/accounts/${el.dataset.login}`,undefined,'DELETE');location.hash='accounts';}}
 else if(action==='restart'){if($('#dialog').open)$('#dialog').close('cancel');if(await confirm('Перезапустить терминал?','Это общий терминал агента. Опрос остальных счетов кратковременно прервётся.','Перезапустить'))await mutate('/actions',{action:'restart',login:Number(el.dataset.login)});}
 else if(action==='copy'){try{await navigator.clipboard.writeText(el.dataset.text);toast('Ссылка скопирована');}catch{throw new Error('Не удалось скопировать автоматически. Выделите и скопируйте ссылку.');}}
 else if(action==='guest-detail'){const r=await api('/guests/'+el.dataset.guest);await dialog('Карточка гостя',`<div class="report-text">${esc(r.report)}</div>`,'Готово');}
 else if(action==='revoke-guest'){if(await confirm('Закрыть доступ гостю?','Ваши переданные счета исчезнут у гостя. Его личные счета и доступ к собственному кабинету сохранятся.','Закрыть доступ'))await mutate('/guests/'+el.dataset.guest,{action:'revoke'});}
 else if(action==='take'){if(await confirm('Забрать счёт у гостя?','Остальные счета гостя сохранятся.'))await mutate('/guests/'+el.dataset.guest,{action:'take',login:Number(el.dataset.login)});}
 else if(action==='alerts')await mutate('/actions',{action:'update_alerts',value:!state.data.update_alerts});
 else if(action==='leave'){if(await confirm('Отключить доступ?','Счета и приглашения в боте будут удалены. Для возвращения понадобится новое приглашение.','Отключить')){await api('/actions',{method:'POST',body:JSON.stringify({action:'leave'})});state.data=null;await refresh();}}
 else if(action==='broadcast'){
  const users=state.admin?.users||[];
  if(!users.length)throw new Error('Пока нет приглашённых пользователей для рассылки');
  const d=await dialog('Сообщение пользователям',`<div class="composer"><div class="composer-intro"><span class="eyebrow">РАССЫЛКА</span><p>Подготовьте сообщение и проверьте его перед отправкой.</p></div><label class="field">Кому<select name="target"><option value="all">Все приглашённые · ${users.length}</option>${users.map(u=>`<option value="${esc(u.id)}">${esc(u.name)}</option>`).join('')}</select></label><div class="composer-editor"><div class="composer-editor-head"><b>Текст</b><span id="compose-count">0 / 4096</span></div><div class="compose-tools"><button type="button" class="format-btn" data-format="bold" aria-label="Жирный" title="Жирный"><b>Ж</b></button><button type="button" class="format-btn" data-format="italic" aria-label="Курсив" title="Курсив"><i>К</i></button><button type="button" class="format-btn" data-format="mono" aria-label="Моноширинный" title="Моноширинный"><code>М</code></button><button type="button" class="format-btn" data-format="quote" aria-label="Цитата" title="Цитата">❝</button><span>Выделите текст для оформления</span></div><textarea name="text" maxlength="4096" aria-label="Текст сообщения" placeholder="Напишите, что важно сообщить пользователям…"></textarea></div><label class="field composer-media">Фото или видео<input type="file" name="media" accept="image/jpeg,image/png,video/mp4"><small id="compose-file-name">JPG/PNG до 10 МБ · MP4 до 20 МБ</small></label><div class="composer-live"><span class="eyebrow">ПРЕДПРОСМОТР ТЕКСТА</span><div id="compose-live" class="compose-preview-text"><span class="muted">Сообщение появится здесь</span></div></div></div>`,'Проверить');
  if(!d)return;
  const file=d.media?.size?d.media:null;
  if(!String(d.text||'').trim()&&!file)throw new Error('Добавьте текст или файл');
  const kind=file?await mediaKind(file):null;
  if(file&&!kind)throw new Error('Выберите JPG, PNG или MP4');
  if(file&&file.size>(kind==='video'?20:10)*1024*1024)throw new Error('Фото до 10 МБ, видео до 20 МБ');
  const recipient=d.target==='all'?`все приглашённые (${users.length})`:users.find(u=>String(u.id)===String(d.target))?.name||'пользователь';
  const objectUrl=file?URL.createObjectURL(file):null;
  try{
   const media=file?`<div class="compose-preview-media">${kind==='photo'?`<img src="${esc(objectUrl)}" alt="Приложенное фото">`:`<video src="${esc(objectUrl)}" controls preload="metadata"></video>`}<small>${esc(file.name)} · ${fileSize(file.size)}</small></div>`:'';
   const body=`<p class="compose-recipient">Кому: <b>${esc(recipient)}</b></p>${media}<div class="compose-preview-text">${d.text?broadcastPreview(d.text):'<span class="muted">Без подписи</span>'}</div><p class="compose-footnote">Проверьте сообщение перед отправкой.</p>`;
   if(!await dialog('Проверка рассылки',body,'Отправить'))return;
  }finally{if(objectUrl)URL.revokeObjectURL(objectUrl);}
  if(preview){await dialog('Демо-режим',`<p>Макет показывает редактор и вложение, но не отправляет сообщения. Для настоящей рассылки откройте приложение из <a href="https://t.me/tagmarketgold_bot" target="_blank" rel="noopener">бота в Telegram</a>.</p>`,'Понятно');return;}
  const requestId=crypto.randomUUID();
  for(;;){
   const form=new FormData();form.append('target',d.target);form.append('text',d.text||'');form.append('request_id',requestId);if(file)form.append('media',file);
   let result;
   try{result=await api('/broadcast',{method:'POST',body:form});}
   catch(error){if(!await dialog('Отправка не завершена',`<p>${esc(error.message)}</p><p class="stat-note">Повтор с тем же сообщением не отправит его заново тем, кому оно уже доставлено.</p>`,'Проверить и повторить'))return;continue;}
   const done=`<div class="compose-status"><span>Доставлено</span><strong>${result.sent}</strong></div><div class="compose-status ${result.failed?'is-error':''}"><span>Ожидают повторной отправки</span><strong>${result.failed}</strong></div>`;
   if(!result.failed){await dialog('Сообщение отправлено',done,'Готово');return;}
   if(!await dialog('Отправлено частично',`${done}<p class="stat-note">Уже доставленные сообщения повторно не отправятся.</p>`,'Повторить недоставленным'))return;
  }
 }
 }catch(error){toast(error.message);}finally{el.disabled=false;}});
document.addEventListener('click',event=>{const tool=event.target.closest('[data-format]');if(!tool)return;event.preventDefault();const area=$('#dialog textarea[name="text"]');if(!area)return;const start=area.selectionStart,end=area.selectionEnd,selected=area.value.slice(start,end);const tags={bold:['<b>','</b>'],italic:['<i>','</i>'],mono:['<code>','</code>'],quote:['<blockquote>','</blockquote>']}[tool.dataset.format];if(!tags)return;area.setRangeText(tags[0]+selected+tags[1],start,end,'end');area.focus();area.setSelectionRange(start+tags[0].length,start+tags[0].length+selected.length);area.dispatchEvent(new Event('input',{bubbles:true}));});
document.addEventListener('input',event=>{if(event.target.matches('#dialog textarea[name="text"]')){const area=event.target,preview=$('#compose-live'),count=$('#compose-count');if(preview)preview.innerHTML=area.value?broadcastPreview(area.value):'<span class="muted">Сообщение появится здесь</span>';if(count)count.textContent=`${area.value.length} / 4096`;}});
 document.addEventListener('change',async event=>{try{if(event.target.matches('#dialog input[name="media"]')){const info=$('#compose-file-name');if(info)info.textContent=event.target.files?.[0]?`${event.target.files[0].name} · ${fileSize(event.target.files[0].size)}`:'JPG/PNG до 10 МБ · MP4 до 20 МБ';}if(event.target.id==='add-cabinet-choice'){const fresh=$('#add-new-cabinet');fresh.hidden=event.target.value!=='new';fresh.querySelector('input').disabled=fresh.hidden;}if(event.target.id==='account-select'){state.login=Number(event.target.value);state.offset=0;if(state.view==='account'){location.hash='account/'+state.login;}else await refresh();}if(event.target.id==='currency'){state.currency=event.target.value;await showCached();}}catch(error){toast(error.message);}});
$('#notifications').innerHTML=icon('bell');$('#refresh').innerHTML=icon('refresh');$('#refresh').addEventListener('click',()=>refresh());
let savedScheme;try{savedScheme=localStorage.getItem('tag-scheme');}catch{}setScheme(savedScheme||'lime',false);
try{tg?.ready();tg?.expand();tg?.BackButton?.onClick(()=>{location.hash='accounts';});tg?.onEvent('homeScreenAdded',()=>toast('Ярлык Tag Markets добавлен на экран'));tg?.onEvent('homeScreenChecked',e=>{if(e?.status==='added')toast('Ярлык уже добавлен');});tg?.onEvent('homeScreenFailed',()=>toast('Telegram не смог добавить ярлык'));}catch{}
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
 function scheduleRefresh(){const every=refreshEvery();if(scheduleRefresh.every===every)return;scheduleRefresh.every=every;clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden&&!$('#dialog').open&&state.period!=='custom')refresh(true);},every);}
 navigate();scheduleRefresh();

function networkView(){return `<div class="section-head"><h2>Доход партнёрской сети</h2></div><section class="panel"><p class="stat-note">По событиям портала · последние 30 дней с начислениями · валюта портала</p><div class="table-wrap"><table class="table"><thead><tr><th>Дата</th><th>Сделок сети</th><th>Начислено</th></tr></thead><tbody>${state.admin.network.map(d=>`<tr><td>${esc(d.day)}</td><td>${number(d.trades)}</td><td class="positive">${number(d.income)}</td></tr>`).join('')}</tbody></table></div></section>`;}
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action="partner-link"]');if(!el)return;event.preventDefault();const current=state.data?.onboarding?.partner_url||'';const body=`<p>Откройте <a href="https://exfusion.ibportal.io" target="_blank" rel="noopener">IB Portal</a>, внизу справа откройте блок <b>Partner</b>, скопируйте свою персональную ссылку и вставьте её сюда.</p><label class="field">Партнёрская ссылка<input name="url" type="url" value="${esc(current)}" required placeholder="https://exfusion.ibportal.io/auth/register?..." /></label>`;const values=await dialog('Моя партнёрская ссылка',body,'Сохранить');if(!values)return;if(preview){await dialog('Демо-режим','<p>Персональная ссылка сохранится после входа через бота в Telegram. Здесь можно проверить вид формы без изменения вашего кабинета.</p>','Понятно');return;}try{const saved=await api('/profile/partner-link',{method:'PUT',body:JSON.stringify({url:values.url})});state.data.onboarding.partner_url=saved.url;toast('Партнёрская ссылка сохранена');render();}catch(error){toast('Ссылка не принята: проверьте адрес из блока Partner.');}});




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
