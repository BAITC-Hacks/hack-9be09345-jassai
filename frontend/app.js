import {createApi,ApiError} from './api.js';
import {escapeHtml as e,date} from './ui.js';
import {icon} from './icons.js';
import * as view from './views.js';
import {filterEvents} from './domain.js';
import {createBackendAdapter} from './backend.js';
import {companionView,companionCompletion} from './companion.js';
import {mountCompanionChat} from './companion-chat.js';

const main=document.querySelector('#main');
const preview=new URLSearchParams(location.search).get('preview');
const emptyCatalog=()=>({tab:'suitable',search:'',format:'',duration:'',skills:[]});
const emptyEmployees=()=>({search:'',department:'',role:'',grade:''});
const state={session:null,status:{},profile:null,gamification:null,completion:null,batch:null,routeVersion:0,importVersion:0,csrf:null,settings:null,catalog:emptyCatalog(),employees:null,employeeFilters:emptyEmployees(),overview:null,period:'all',reason:null,historyTab:'all',notifications:[]};
Object.assign(state,{companion:null,companionTab:'home',selectedSkill:null,previewItem:null,chatMessages:[],celebrateNext:false});
let mascot=null,chat=null,mountVersion=0,mascotManifest=null;
function disposeCompanion(){mountVersion++;chat?.dispose();chat=null;mascot?.dispose();mascot=null;}
async function mountCompanion(){
  const version=++mountVersion,host=main.querySelector('[data-mascot-stage]');
  chat=mountCompanionChat({getCsrf:()=>state.csrf,profile:state.profile,messages:state.chatMessages,onState:value=>mascot?.setState(value),onUnauthorized:()=>{resetPrivateState();renderRoute();},previewAnswer:preview?((message,context)=>previewChat(message,context)):null});
  if(!host)return;
  try{const [{mountMascot},manifest]=await Promise.all([import('./mascot-renderer.js'),mascotManifest??=(fetch('/static/mascot-assets.json',{cache:'no-cache'}).then(r=>r.ok?r.json():{}).catch(()=>({})))]);if(version!==mountVersion||!host.isConnected)return;mascot=mountMascot(host,{equipped:state.companion.equipped,wardrobe:state.companion.wardrobe,previewItem:state.previewItem,state:state.celebrateNext?'celebrate':'idle',modelUrl:manifest.modelUrl||null});state.celebrateNext=false;}
  catch{if(host.isConnected)host.innerHTML='<div class="mascot-loading"><p>3D пока недоступно на этом устройстве. Древо, гардероб и подсказки работают.</p></div>';}
}
function renderCompanion(){disposeCompanion();main.innerHTML=companionView(state.companion,state.profile,{tab:state.companionTab,selectedSkill:state.selectedSkill,previewItem:state.previewItem});mountCompanion();}
function previewChat(message,{event_id,skill_id}={}){
  const branches=state.companion?.tree.branches||[],q=message.toLowerCase();
  const branch=branches.find(b=>b.skill_id===skill_id)||branches.find(b=>b.current<b.required),activity=state.profile.available_steps.find(a=>a.event_id===event_id)||branch?.activities[0];
  let text,ids=[];
  if(/одежд|откро|наград|гардероб/.test(q)){const item=state.companion.next_unlock;text=item?`Следующее открытие — «${item.name}». ${item.requirement.label}: ${item.requirement.current} из ${item.requirement.target}.`:'В текущем гардеробе всё открыто.';if(!state.companion.enabled)text+=' Включите награды перед новым завершением.';}
  else if(/прогресс|цель|куда/.test(q))text=`Покрытие требований цели: ${state.companion.tree.coverage_pct??'не рассчитано'}${state.companion.tree.coverage_pct==null?'':'%'}. Это показатель навыков, решение о повышении принимается отдельно.`;
  else if(activity){const gains=branches.flatMap(b=>b.activities.filter(a=>a.event_id===activity.event_id).map(a=>`${b.name}: ${a.before} → ${a.after}`));text=`«${activity.title}» — ${activity.duration_hours} ч. После завершения: ${gains.join('; ')}. Откройте прогноз для влияния на цель.`;ids=[activity.event_id];}
  else text='Древо показывает навыки учебного профиля. Выберите цель или посмотрите условия открытия одежды.';
  return [{type:'delta',text:'Учебный пример. '+text+' Внешний AI не вызывается.'},{type:'done',source:'preview',event_ids:ids}];
}
let setupToken=new URLSearchParams(location.hash.slice(1)).get('setup_token');
if(setupToken)history.replaceState(null,'',location.pathname+location.search+'#setup');
let mock=null;
if(preview){const module=await import('./preview.js');mock=module.createPreview(preview);const banner=document.querySelector('#preview-banner');banner.hidden=false;banner.innerHTML='Предпросмотр · вымышленные данные, без вызовов AI <a href="?preview=employee">Сотрудник</a><a href="?preview=hr">HR</a><a href="?preview=setup">Первый запуск</a><a href="?preview=login">Вход</a>';}
const rawApi=createApi({getCsrf:()=>state.csrf,mock});
const api=preview?rawApi:createBackendAdapter(rawApi);
const route=()=>location.hash.slice(1)||'home';
const dialogs=()=>[...document.querySelectorAll('dialog')];
function closeDialogs(){for(const d of dialogs())if(d.open)d.close();}
function openDialog(id,html){closeDialogs();const d=document.querySelector('#'+id);d.innerHTML=html;d.showModal();}
function remembered(){try{return localStorage.getItem('cq:remembered-username')||'';}catch{return '';}}
function remember(value){try{if(value)localStorage.setItem('cq:remembered-username',value);else localStorage.removeItem('cq:remembered-username');}catch{/* Remembering the username is optional. */}}
let noticeTimer;
function notice(text,record=false){const target=document.querySelector('#notice');target.textContent=text;target.hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>target.hidden=true,6500);if(record){state.notifications.unshift({text,time:new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})});state.notifications=state.notifications.slice(0,10);}}
function keyFor(action,id){const key=`cq:pending:${state.session?.user_id}:${action}:${id}`;let value=sessionStorage.getItem(key);if(!value){value=crypto.randomUUID();sessionStorage.setItem(key,value);}return {value,clear:()=>sessionStorage.removeItem(key)};}
function resetPrivateState(){disposeCompanion();closeDialogs();for(const d of dialogs())d.innerHTML='';Object.assign(state,{session:null,csrf:null,profile:null,gamification:null,companion:null,companionTab:'home',selectedSkill:null,previewItem:null,chatMessages:[],celebrateNext:false,completion:null,batch:null,settings:null,employees:null,overview:null,catalog:emptyCatalog(),employeeFilters:emptyEmployees(),period:'all',reason:null,historyTab:'all',notifications:[]});state.routeVersion++;}
function setRoute(next){closeDialogs();history.pushState(null,'',location.pathname+location.search+'#'+next);return renderRoute();}
function landing(){history.replaceState(null,'',location.pathname+location.search+'#'+(state.session?.role==='hr'?'hr':'home'));}
function navigation(){
  const user=state.session,hr=user?.role==='hr',raw=route(),active=hr?(raw.startsWith('employee/')?'employees':raw==='home'?'hr':raw):(raw==='completion'?'history':raw==='achievements'?'companion':raw);
  document.body.classList.toggle('auth-mode',!user&&!state.status.setup_required);
  document.body.classList.toggle('setup-mode',state.status.setup_required===true);
  document.body.classList.toggle('has-preview',!!preview);
  const links=!user?[]:hr?[['hr','home','Обзор команды'],['employees','users','Сотрудники'],['import','upload','Импорт данных'],['settings','settings','Настройки AI']]:[['home','home','Мой путь'],['companion','sparkles','Спутник'],['skills','skills','Навыки'],['catalog','book','Активности'],['history','history','История']];
  document.querySelector('#navigation').innerHTML=links.map(([id,symbol,text])=>`<a href="#${id}" class="${active===id?'active':''}" ${active===id?'aria-current="page"':''}>${icon(symbol)}<span>${text}</span></a>`).join('');
  const fullName=!hr&&state.profile?.employee?.full_name||user?.display_name||user?.username||'',initials=fullName.split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase(),position=hr?'HR · Развитие команды':state.profile?.employee?`${state.profile.employee.role} · ${state.profile.employee.grade}`:'Личное пространство';
  document.querySelector('#identity').innerHTML=user?`<div class="identity"><span class="avatar">${e(initials)}</span><div><strong>${e(fullName)}</strong><small>${e(position)}</small></div></div>`:'';
  document.querySelector('#logout').hidden=!user;
  document.querySelector('#as-of').textContent=state.status.as_of_date?'Срез: '+date(state.status.as_of_date):'';
  document.querySelector('#breadcrumb').textContent=hr?'Развитие команды':'Личное пространство';
  const topAvatar=document.querySelector('#top-avatar'),topName=document.querySelector('#top-name');if(topAvatar)topAvatar.textContent=initials||'CQ';if(topName)topName.textContent=hr?'HR':fullName.split(' ')[0];
}
async function loadSession(){const result=await api('/api/auth/session');state.session=result.user;state.csrf=result.csrf_token;}
async function boot(){try{state.status=await api('/api/setup/status');if(!state.status.setup_required){try{await loadSession();}catch(error){if(error.status!==401)throw error;}}await renderRoute();}catch(error){navigation();main.innerHTML=view.heading('Halyk Career Quest','Не удалось открыть пространство','Проверьте, что локальный сервер запущен.')+view.errorView(error)+view.button('Повторить подключение','reconnect');}}
function requireRole(role){if(state.session?.role!==role)throw new ApiError('Этот раздел недоступен для вашей роли.',403);}
async function loadCompanion(){try{return await api('/api/me/companion');}catch(error){if(error.status===404)return null;throw error;}}
function requireGamification(){requireRole('employee');if(!state.gamification)throw new ApiError('Личные достижения доступны с подключённым серверным модулем.',404);}
function overviewPath(){if(state.period==='all'||!state.status.as_of_date)return '/api/hr/overview';const to=state.status.as_of_date,from=new Date(to+'T12:00:00Z');from.setUTCDate(from.getUTCDate()-Number(state.period)+1);return '/api/hr/overview?'+new URLSearchParams({date_from:from.toISOString().slice(0,10),date_to:to});}
function disableSettings(){if(preview){for(const field of main.querySelectorAll('.provider-form input,.provider-form button,#ai-policy-form input,#ai-policy-form select,#ai-policy-form button'))field.disabled=true;main.insertAdjacentHTML('afterbegin','<div class="info">Предпросмотр: API-ключи не принимаются.</div>');}}
async function renderRoute(){
  disposeCompanion();const version=++state.routeVersion;state.importVersion++;state.batch=null;navigation();main.innerHTML=view.loadingView();const raw=route();
  try{
    if(state.status.setup_required){main.innerHTML=view.setupView(state.status);return;}
    if(!state.session){main.innerHTML=view.loginView(remembered());return;}
    let html;
    if(raw==='setup'){requireRole('hr');html=view.setupView(state.status);}
    else if(raw==='settings'){requireRole('hr');let data;try{data=await api('/api/hr/settings/ai');}catch(error){if(error.status!==404)throw error;data={not_connected:true,ai_status:state.status.ai_status};}if(version!==state.routeVersion)return;state.settings=data;html=view.settingsView(data);}
    else if(raw==='employees'){requireRole('hr');const data=await api('/api/hr/employees');if(version!==state.routeVersion)return;state.employees=data;html=view.employeesView(data,state.employeeFilters);}
    else if(raw==='import'){requireRole('hr');html=view.importView(!state.status.dataset_loaded);}
    else if(raw==='hr'||raw==='home'&&state.session.role==='hr'){requireRole('hr');if(!state.status.dataset_loaded)html=view.setupView(state.status);else{const data=await api(overviewPath());if(version!==state.routeVersion)return;state.overview=data;state.status.as_of_date=data.as_of_date||state.status.as_of_date;html=view.hrView(data,{period:state.period,reason:state.reason});}}
    else if(raw.startsWith('employee/')){requireRole('hr');const profile=await api('/api/hr/employees/'+encodeURIComponent(decodeURIComponent(raw.slice(9))));if(version!==state.routeVersion)return;state.profile=profile;html=view.hrProfileView(profile);}
    else if(['home','skills','history','catalog','completion','achievements','companion'].includes(raw)){
      requireRole('employee');const session=state.session;
      const [profile,companion]=await Promise.all([api('/api/me'),loadCompanion()]);const gamification=companion;
      if(version!==state.routeVersion||session!==state.session)return;
      state.profile=profile;state.gamification=gamification;state.companion=companion;state.status.as_of_date=profile.as_of_date||state.status.as_of_date;
      html=['achievements','companion'].includes(raw)?companionView(companion,profile,{tab:state.companionTab,selectedSkill:state.selectedSkill,previewItem:state.previewItem}):raw==='catalog'?view.availableView(profile,state.catalog):raw==='completion'?(state.completion?view.completionView(state.completion)+companionCompletion(state.completion,companion):view.empty('Результат доступен в истории','Откройте завершённую активность в истории развития.','<a class="button" href="#history">Открыть историю</a>')):view.employeeView(profile,{section:raw,historyTab:state.historyTab,completion:state.completion,gamification});
    }
    else html=view.empty('Такой страницы нет','Вернитесь в своё рабочее пространство.','<a class="button" href="#home">На главную</a>');
    if(version!==state.routeVersion)return;main.innerHTML=html;navigation();main.focus({preventScroll:true});window.scrollTo(0,0);if(raw==='settings')disableSettings();if(['companion','achievements'].includes(raw))await mountCompanion();
  }catch(error){if(version!==state.routeVersion)return;if(error.status===401){resetPrivateState();navigation();main.innerHTML=view.loginView(remembered());notice('Сессия завершена. Войдите снова.');}else main.innerHTML=view.errorView(error)+`<div class="card-actions">${view.button('Повторить','reload')}<a class="button secondary" href="#home">На главную</a></div>`;}
}
async function recommend(){const version=state.routeVersion,target=document.querySelector('#recommendation-content');if(!target||target.getAttribute('aria-busy')==='true')return;requireRole('employee');target.setAttribute('aria-busy','true');target.innerHTML=view.loadingView('Подбираем шаги с учётом цели и истории…');try{const result=await api('/api/me/recommendations',{method:'POST',body:{refresh:true},timeout:11000});if(version!==state.routeVersion)return;state.profile.recommendations=result;main.innerHTML=view.employeeView(state.profile,{completion:state.completion,gamification:state.gamification});}catch(error){if(version===state.routeVersion)target.innerHTML=view.errorView(error)+`<div class="card-actions">${view.button('Повторить подбор','recommend')}<a class="button secondary" href="#catalog">Открыть доступные активности</a></div>`;}finally{target.removeAttribute('aria-busy');}}
function importStage(stage){for(const step of document.querySelectorAll('[data-import-step]')){const i=Number(step.dataset.importStep);step.classList.toggle('done',i<stage);step.classList.toggle('active',i===stage);if(i===stage)step.setAttribute('aria-current','step');else step.removeAttribute('aria-current');}}
function updateCatalog(){main.innerHTML=view.availableView(state.profile,state.catalog);}

document.addEventListener('click',async event=>{
  if(event.target.closest('.skip')){event.preventDefault();main.focus();return;}
  const control=event.target.closest('[data-action]');if(!control)return;const action=control.dataset.action,id=control.dataset.id;
  if(action==='close-dialog'||action==='close-goal'){closeDialogs();return;}
  const account=state.session?.user_id,session=state.session;control.disabled=true;
  try{
    if(action==='companion-tab'){requireRole('employee');state.companionTab=id;state.previewItem=null;renderCompanion();}
    else if(action==='companion-skill'){state.selectedSkill=id;state.companionTab='tree';renderCompanion();}
    else if(action==='wardrobe-preview'){state.previewItem=id;state.companionTab='wardrobe';renderCompanion();}
    else if(action==='wardrobe-equip'){requireRole('employee');const data=await api('/api/me/companion/equip',{method:'POST',body:{item_id:id}});if(session!==state.session)return;state.companion=data;state.gamification=data;state.previewItem=null;if(['companion','achievements'].includes(route()))renderCompanion();notice('Образ сохранён.',true);}
    else if(action==='companion-ask'){requireRole('employee');if(state.companionTab!=='home'){state.companionTab='home';renderCompanion();}chat?.ask(control.dataset.question,{skill_id:control.dataset.skill||null,event_id:control.dataset.event||null});}
    else if(action==='goal'){requireRole('employee');openDialog('goal-dialog',view.goalForm(state.profile));}
    else if(action==='event'||action==='forecast'||action==='skill'||action==='history-result'){requireRole('employee');openDialog('detail-dialog',action==='event'?view.activityDetail(state.profile,id):action==='forecast'?view.forecastView(state.profile,id):action==='skill'?view.skillDetail(state.profile,id):view.historyDetail(state.profile,id));}
    else if(action==='compare'){requireRole('employee');openDialog('overlay-dialog',view.compareView(state.profile));}
    else if(action==='filters'){requireRole('employee');openDialog('detail-dialog',view.filtersView(state.profile,state.catalog));}
    else if(action==='catalog-tab'){state.catalog.tab=id;updateCatalog();}
    else if(action==='history-tab'){state.historyTab=id;main.innerHTML=view.employeeView(state.profile,{section:'history',historyTab:id,gamification:state.gamification});}
    else if(action==='reset-catalog'){closeDialogs();state.catalog=emptyCatalog();if(route()!=='catalog')await setRoute('catalog');else updateCatalog();}
    else if(action==='reset-employees'){state.employeeFilters=emptyEmployees();main.innerHTML=view.employeesView(state.employees,state.employeeFilters);}
    else if(action==='hr-reason'){state.reason=id||null;main.innerHTML=view.hrView(state.overview,{period:state.period,reason:state.reason});}
    else if(action==='create-access'){requireRole('hr');const version=state.routeVersion;if(!state.employees){const employees=await api('/api/hr/employees');if(version!==state.routeVersion||account!==state.session?.user_id)return;state.employees=employees;}openDialog('overlay-dialog',`<div class="dialog-head"><h2 id="overlay-title">Создать доступ</h2><button class="icon-button" data-action="close-dialog" aria-label="Закрыть">${icon('close')}</button></div><div class="dialog-body">${view.createAccessForm(state.employees.employees||[])}</div>`);}
    else if(action==='forgot-password')openDialog('overlay-dialog',view.infoDialog('Восстановление доступа','Обратитесь к HR или администратору локального приложения. Самостоятельный сброс пароля пока не подключён.'));
    else if(action==='language')openDialog('overlay-dialog',view.infoDialog('Язык интерфейса','Русский — текущий язык. Қазақша — перевод интерфейса ещё не подготовлен.'));
    else if(action==='notifications')openDialog('overlay-dialog',view.infoDialog('События пространства',state.notifications.length?`<div class="history-list">${state.notifications.map(x=>`<div class="history-item"><span>${e(x.text)}</span><small class="muted">${e(x.time)}</small></div>`).join('')}</div><p class="muted">События текущей сессии.</p>`:'<p class="muted">В этой сессии пока нет новых событий.</p>',{html:true}));
    else if(action==='reconnect')await boot();
    else if(action==='reload')await renderRoute();
    else if(action==='recommend')await recommend();
    else if(action==='next-step'){await setRoute('home');await recommend();}
    else if(action==='gamification-toggle'){
      requireGamification();const enabled=control.dataset.enabled==='true';
      await api('/api/me/gamification',{method:'PATCH',body:{enabled}});
      if(session!==state.session)return;
      await renderRoute();if(session===state.session)notice(enabled?'Достижения включены. Новые завершения принесут личный опыт.':'Достижения приостановлены. Награды сохранены.',true);
    }else if(action==='quest-clear'){
      requireGamification();await api('/api/me/gamification/quest',{method:'DELETE'});
      if(session!==state.session)return;
      await renderRoute();if(session===state.session)notice('Квест снят. Вы можете выбрать другой шаг.',true);
    }
    else if(action==='start'||action==='complete'){
      requireRole('employee');const key=keyFor(action,id),result=await api(action==='start'?'/api/me/activities':`/api/me/activities/${encodeURIComponent(id)}/complete`,{method:'POST',idempotencyKey:key.value,body:action==='start'?{event_id:id,session_date:control.dataset.session||null}:{}});key.clear();if(account!==state.session?.user_id)return;
      closeDialogs();notice(action==='start'?'Активность начата. Она появилась в истории.':result.applied===false?'Это выполнение уже учтено.':'Активность завершена. Прогресс сохранён.',true);
      if(action==='complete'){const after=await loadCompanion();if(session!==state.session)return;const before=new Set((state.companion?.wardrobe||[]).filter(i=>i.unlocked).map(i=>i.id));result.wardrobe_unlocked=(after?.wardrobe||[]).filter(i=>i.unlocked&&!before.has(i.id));state.completion=result;if(result.applied!==false){const gains=(result.changes||[]).filter(g=>g.after>g.before).map(g=>`${g.name||g.skill_id}: ${g.before} → ${g.after}`);state.chatMessages.push({role:'assistant',source:'local',content:`Шаг завершён. ${gains.join('; ')}.${result.wardrobe_unlocked.length?' Открыто: '+result.wardrobe_unlocked.map(i=>i.name).join(', ')+'. Примерим новый образ?':''}`});state.celebrateNext=gains.length>0;}await setRoute('completion');}else await renderRoute();
    }else if(action==='apply-import'){
      requireRole('hr');if(!state.batch)throw new ApiError('Сначала проверьте выбранные файлы.');const version=state.routeVersion,wasInitial=!state.status.dataset_loaded,batch=state.batch,key=keyFor('import',batch.batch_id);const result=await api('/api/hr/import/apply',{method:'POST',body:{batch_id:batch.batch_id,mode:batch.mode},idempotencyKey:key.value,timeout:20000});key.clear();if(account!==state.session?.user_id)return;state.batch=null;state.status={...state.status,...await api('/api/setup/status')};notice('Импорт завершён.',true);
      if(version!==state.routeVersion)return;
      if(wasInitial||route()==='setup'){await setRoute('setup');}else{const target=document.querySelector('#import-result');if(target)target.innerHTML=view.importResult(result,true);importStage(4);navigation();}
    }
  }catch(error){if((action==='gamification-toggle'||action==='quest-clear')&&session!==state.session)return;notice(error.message);if(action==='apply-import'&&error.status===409){state.batch=null;const target=document.querySelector('#import-result');if(target)target.innerHTML=view.errorView(error);importStage(1);}if(error.status===401){resetPrivateState();await renderRoute();}}
  finally{if(control.isConnected)control.disabled=false;}
});

document.addEventListener('submit',async event=>{
  const form=event.target;if(!(form instanceof HTMLFormElement))return;event.preventDefault();const submit=form.querySelector('button[type="submit"]');if(submit?.disabled)return;if(submit)submit.disabled=true;const errorTarget=form.querySelector('.form-error');if(errorTarget)errorTarget.innerHTML='';const fields=new FormData(form),session=state.session;let submittedImportVersion=null;
  try{
    if(form.id==='login-form'){
      const password=form.elements.password.value;form.elements.password.value='';await api('/api/auth/login',{method:'POST',body:{username:fields.get('username'),password}});remember(fields.get('remember')?fields.get('username'):'');await loadSession();state.completion=null;state.gamification=null;landing();await renderRoute();
    }else if(form.id==='bootstrap-form'){
      if(!setupToken&&!preview)throw new ApiError('Для первой настройки нужен одноразовый токен из окна запуска приложения.');const password=form.elements.password.value;form.elements.password.value='';await api('/api/setup/bootstrap',{method:'POST',body:{username:fields.get('username'),password,setup_token:setupToken}});setupToken=null;state.status=await api('/api/setup/status');await loadSession();await setRoute('setup');
    }else if(form.id==='goal-form'){
      requireRole('employee');if(fields.get('goal_index')===null)throw new ApiError('Выберите цель.');const goal=state.profile.goal_options[Number(fields.get('goal_index'))];if(!goal)throw new ApiError('Выберите цель из списка.');await api('/api/me/goal',{method:'PATCH',body:{target_role:goal.target_role,target_grade:goal.target_grade}});closeDialogs();state.completion=null;state.chatMessages=[];await renderRoute();notice('Карьерная цель обновлена.',true);if(route()==='home')await recommend();
    }else if(form.id==='quest-form'){
      requireGamification();if(!state.gamification.enabled)throw new ApiError('Включите достижения, чтобы выбрать личный квест.');
      const eventId=String(fields.get('event_id')||'').trim();if(!eventId)throw new ApiError('Выберите доступную активность.');
      await api('/api/me/gamification/quest',{method:'POST',body:{event_id:eventId}});
      if(session!==state.session)return;
      await renderRoute();if(session===state.session)notice('Личный квест выбран. Начать активность можно в каталоге.',true);
    }else if(form.id==='activity-search'){state.catalog.search=String(fields.get('search')||'');updateCatalog();}
    else if(form.id==='activity-filters'){state.catalog={...state.catalog,format:String(fields.get('format')||''),duration:String(fields.get('duration')||''),skills:fields.getAll('skills').map(String)};closeDialogs();updateCatalog();}
    else if(form.id==='employee-filters'){state.employeeFilters=Object.fromEntries(['search','department','role','grade'].map(k=>[k,String(fields.get(k)||'')]));main.innerHTML=view.employeesView(state.employees,state.employeeFilters);}
    else if(form.id==='employee-search')await setRoute('employee/'+encodeURIComponent(String(fields.get('employee_id')).trim()));
    else if(form.id==='create-user-form'){
      requireRole('hr');const password=form.elements.password.value;form.elements.password.value='';await api('/api/hr/users',{method:'POST',body:{username:fields.get('username'),password,role:'employee',employee_id:fields.get('employee_id')}});closeDialogs();notice('Аккаунт создан. Сотрудник может войти под своим логином.',true);
    }else if(form.id==='import-form'){
      requireRole('hr');const version=++state.importVersion;submittedImportVersion=version;state.batch=null;const clean=new FormData();let files=0;for(const [key,value] of fields){if(value instanceof File){if(value.name&&value.size){clean.append(key,value);files++;}}else clean.append(key,value);}if(!files)throw new ApiError('Выберите хотя бы один файл для импорта.');clean.set('kind',form.dataset.initial==='true'?'initial':'additional');document.querySelector('#import-result').innerHTML=view.loadingView('Проверяем файлы и связи…');importStage(2);const result=await api('/api/hr/import/validate',{method:'POST',body:clean,timeout:20000});if(version!==state.importVersion||!form.isConnected)return;state.batch=result.valid?{batch_id:result.batch_id,mode:fields.get('mode')||'add'}:null;document.querySelector('#import-result').innerHTML=view.importResult(result);importStage(result.valid?3:2);
    }else if(form.classList.contains('provider-form')){
      requireRole('hr');if(preview)throw new ApiError('В предпросмотре API-ключи не принимаются.');if(state.settings?.not_connected)throw new ApiError('Веб-форма настройки недоступна. Настройте AI командой launcher.cmd /configure-ai после остановки приложения.');const apiKey=form.elements.api_key.value;form.elements.api_key.value='';const body={provider:form.dataset.provider,model_id:String(fields.get('model_id')||'').trim(),persist:fields.get('persist')==='on'};if(apiKey)body.api_key=apiKey;const result=await api('/api/hr/settings/ai',{method:'POST',body,timeout:11000});if(result.valid!==true)throw new ApiError(result.message||'Подключение не подтверждено.');state.status={...state.status,...await api('/api/setup/status')};await renderRoute();notice(`Подключение проверено: ${result.latency_ms??'—'} мс. Скорость рекомендаций измеряется отдельно.`,true);
    }else if(form.id==='ai-policy-form'){
      requireRole('hr');if(preview)throw new ApiError('Настройки AI недоступны в предпросмотре.');if(state.settings?.not_connected)throw new ApiError('В этой версии сервера подключение AI настраивается через launcher.cmd /configure-ai.');const primary=fields.get('primary_provider'),fallback=fields.get('fallback_provider')||null;if(primary===fallback)throw new ApiError('Основной и резервный провайдер должны различаться.');await api('/api/hr/settings/ai/policy',{method:'PATCH',body:{primary_provider:primary,fallback_provider:fallback,total_timeout_ms:10000}});notice('Режим рекомендаций сохранён.',true);
    }
  }catch(error){if(form.id==='quest-form'&&session!==state.session)return;if(form.id==='import-form'&&(submittedImportVersion!==state.importVersion||!form.isConnected))return;if(form.isConnected&&errorTarget)errorTarget.innerHTML=view.errorView(error);else notice(error.message);if(form.id==='import-form'){state.batch=null;const target=document.querySelector('#import-result');if(target)target.innerHTML=view.errorView(error);importStage(2);}if(error.status===401&&form.id!=='login-form'){resetPrivateState();await renderRoute();}}
  finally{if(form.classList.contains('provider-form')&&form.elements.api_key)form.elements.api_key.value='';if(submit?.isConnected)submit.disabled=false;}
});
document.addEventListener('change',async event=>{
  if(event.target.closest('#import-form')){state.importVersion++;state.batch=null;const result=document.querySelector('#import-result');if(result)result.innerHTML='';importStage(1);if(event.target.type==='file'){const card=event.target.closest('.file-card');if(card){card.classList.toggle('uploaded',event.target.files.length>0);const status=card.querySelector('.file-status');if(status)status.textContent=event.target.files[0]?.name||'Файл не выбран';}}}
  if(event.target.id==='hr-period'){state.period=event.target.value;await renderRoute();}
  const filter=event.target.closest('#activity-filters');if(filter){const f=new FormData(filter),values={...state.catalog,format:String(f.get('format')||''),duration:String(f.get('duration')||''),skills:f.getAll('skills').map(String)};const submit=filter.querySelector('button[type="submit"]');if(submit)submit.textContent='Показать '+filterEvents(state.profile,values).length;}
});
for(const dialog of dialogs())dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();});
document.querySelector('#logout').addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST',body:{}});resetPrivateState();history.replaceState(null,'',location.pathname+location.search+'#home');await renderRoute();}catch(error){notice(error.message);}});
window.addEventListener('hashchange',()=>{closeDialogs();renderRoute();});
await boot();
