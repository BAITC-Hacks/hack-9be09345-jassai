import {createApi,ApiError} from './api.js';
import {escapeHtml as e,date} from './ui.js';
import * as view from './views.js';
import {createBackendAdapter} from './backend.js';

const main=document.querySelector('#main');
const params=new URLSearchParams(location.search);
const preview=params.get('preview');
const state={session:null,status:{},profile:null,completion:null,batch:null,routeVersion:0,importVersion:0,csrf:null,settings:null};
// The launcher opens /#setup_token=...; consume the token without retaining it in the URL.
let setupToken=new URLSearchParams(location.hash.slice(1)).get('setup_token');
if(setupToken) history.replaceState(null,'',location.pathname+location.search+'#setup');
let mock=null;
if(preview){const module=await import('./preview.js');mock=module.createPreview(preview);const banner=document.querySelector('#preview-banner');banner.hidden=false;banner.innerHTML='ПРЕДПРОСМОТР · вымышленные примеры, без сервера и вызовов AI. Изменения сбрасываются при обновлении. <a href="?preview=employee">Сотрудник</a><a href="?preview=hr">HR</a><a href="?preview=setup">Первый запуск</a><a href="?preview=login">Вход</a>';}
const rawApi=createApi({getCsrf:()=>state.csrf,mock});
const api=preview?rawApi:createBackendAdapter(rawApi);
let noticeTimer;
function notice(text){const target=document.querySelector('#notice');target.textContent=text;target.hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>target.hidden=true,7000);}
function formError(form,error){form.querySelector('.form-error').innerHTML=view.errorView(error);}
function keyFor(action,id){const key=`cq:pending:${state.session?.user_id}:${action}:${id}`;let value=sessionStorage.getItem(key);if(!value){value=crypto.randomUUID();sessionStorage.setItem(key,value);}return {value,clear:()=>sessionStorage.removeItem(key)};}
function resetPrivateState(){state.session=null;state.csrf=null;state.profile=null;state.settings=null;state.completion=null;state.batch=null;document.querySelector('#goal-dialog').close();document.querySelector('#goal-dialog').innerHTML='';}
function navigation(){
  const hr=state.session?.role==='hr';
  const links=state.session?(hr?[['hr','◎','Обзор команды'],['employees','♧','Профили и доступ'],['import','⇧','Импорт данных'],['settings','⚙','Настройки AI']]:[['home','▦','Мой путь'],['skills','◇','Мои навыки'],['catalog','↗','Доступные шаги'],['history','◷','История']]):[];
  const route=location.hash.slice(1)||'home';
  document.querySelector('#navigation').innerHTML=links.map(([id,icon,text])=>`<a href="#${id}" class="${route===id||(route==='home'&&id==='hr')?'active':''}" ${route===id?'aria-current="page"':''}><span class="nav-icon" aria-hidden="true">${icon}</span>${text}</a>`).join('');
  const user=state.session;
  document.querySelector('#identity').innerHTML=user?`<div class="identity"><div class="avatar">${e((user.display_name||user.username||'CQ').slice(0,2).toUpperCase())}</div><div>${e(user.display_name||user.username)}<small>${hr?'HR · обзор команды':'Личное пространство'}</small></div></div>`:'';
  document.querySelector('#logout').hidden=!user;
  document.querySelector('#as-of').textContent=state.status.as_of_date?'Срез: '+date(state.status.as_of_date):'';
  document.querySelector('#breadcrumb').textContent=hr?'Команда / Развитие':'Личное пространство / Развитие';
}
async function loadSession(){const session=await api('/api/auth/session');state.session=session.user;state.csrf=session.csrf_token;}
async function boot(){try{state.status=await api('/api/setup/status');if(!state.status.setup_required){try{await loadSession();}catch(error){if(error.status!==401)throw error;}}await renderRoute();}catch(error){navigation();main.innerHTML=view.heading('Career Quest','Не удалось открыть пространство','Проверьте, что локальный сервер запущен.')+view.errorView(error)+view.button('Повторить подключение','reconnect');}}
async function renderRoute(){
  const version=++state.routeVersion;state.importVersion++;state.batch=null;navigation();
  const raw=location.hash.slice(1)||'home';
  main.innerHTML='<div class="loading" role="status">Загружаем данные…</div>';
  try{
    if(state.status.setup_required){main.innerHTML=view.setupView(state.status);return;}
    if(!state.session){main.innerHTML=view.loginView();return;}
    const hr=state.session.role==='hr';
    let html;
    if(raw==='setup'){if(!hr)throw new ApiError('Настройка доступна HR.',403);html=view.setupView(state.status);}
    else if(raw==='settings'){if(!hr)throw new ApiError('Настройки доступны HR.',403);let data;try{data=await api('/api/hr/settings/ai');}catch(error){if(error.status!==404)throw error;data={not_connected:true};}if(version!==state.routeVersion)return;state.settings=data;html=view.settingsView(data);}
    else if(raw==='employees'){if(!hr)throw new ApiError('Профили доступны HR.',403);html=view.employeesView(await api('/api/hr/employees'));}
    else if(raw==='import'){if(!hr)throw new ApiError('Импорт доступен HR.',403);html=view.importView(!state.status.dataset_loaded);}
    else if((raw==='home'&&hr)||raw==='hr'){if(!hr)throw new ApiError('Обзор команды доступен HR.',403);if(!state.status.dataset_loaded){html=view.setupView(state.status);}else{const data=await api('/api/hr/overview');state.status.as_of_date=data.as_of_date||state.status.as_of_date;navigation();html=view.hrView(data);}}
    else if(raw.startsWith('employee/')){if(!hr)throw new ApiError('Просмотр других сотрудников доступен HR.',403);const id=decodeURIComponent(raw.slice(9));const profile=await api('/api/hr/employees/'+encodeURIComponent(id));if(version!==state.routeVersion)return;state.profile=profile;html=view.employeeView(profile,{readOnly:true});}
    else if(['home','skills','history','catalog'].includes(raw)){const profile=await api('/api/me');if(version!==state.routeVersion)return;state.profile=profile;state.status.as_of_date=profile.as_of_date||state.status.as_of_date;navigation();html=raw==='catalog'?view.availableView(profile):view.employeeView(profile,{section:raw,completion:state.completion});}
    else {html=view.empty('Такой страницы нет','Вернитесь в своё рабочее пространство.','<a class="button" href="#home">На главную</a>');}
    if(version===state.routeVersion){main.innerHTML=html;if(raw==='settings'&&(state.settings?.not_connected||preview)){if(state.settings?.not_connected)main.insertAdjacentHTML('afterbegin','<div class="info">Настройки AI пока недоступны на сервере. Подключение должен завершить администратор приложения.</div>');for(const field of main.querySelectorAll('.provider-form input,.provider-form button,#ai-policy-form button'))field.disabled=true;}}
  }catch(error){if(version!==state.routeVersion)return;if(error.status===401){resetPrivateState();navigation();main.innerHTML=view.loginView();notice('Сессия завершена. Войдите снова.');}else{main.innerHTML=view.errorView(error)+view.button('Повторить','reload');}}
}
async function recommend(){
  const version=state.routeVersion;
  const target=document.querySelector('#recommendation-content');
  if(!target)return;
  if(target.getAttribute('aria-busy')==='true')return;
  target.setAttribute('aria-busy','true');
  target.innerHTML='<div class="loading" role="status">Подбираем шаги с учётом цели и истории. До 10 секунд…</div>';
  try{const result=await api('/api/me/recommendations',{method:'POST',body:{refresh:true},timeout:11000});if(version!==state.routeVersion)return;state.profile.recommendations=result;main.innerHTML=view.employeeView(state.profile,{completion:state.completion});}
  catch(error){if(version===state.routeVersion)target.innerHTML=view.errorView(error)+view.button('Повторить подбор','recommend');}
  finally{target.removeAttribute('aria-busy');}
}

document.addEventListener('click',async event=>{
  if(event.target.closest('.skip')){event.preventDefault();main.focus();return;}
  const control=event.target.closest('[data-action]');if(!control)return;
  const action=control.dataset.action;
  if(action==='close-goal'){document.querySelector('#goal-dialog').close();return;}
  if(action==='goal'){document.querySelector('#goal-dialog').innerHTML=view.goalForm(state.profile);document.querySelector('#goal-dialog').showModal();return;}
  control.disabled=true;
  try{
    if(action==='reconnect')await boot();
    if(action==='reload')await renderRoute();
    if(action==='recommend')await recommend();
    if(action==='start'||action==='complete'){
      const id=control.dataset.id,key=keyFor(action,id);
      const result=await api(action==='start'?'/api/me/activities':`/api/me/activities/${encodeURIComponent(id)}/complete`,{method:'POST',idempotencyKey:key.value,body:action==='start'?{event_id:id,session_date:control.dataset.session||null}:{}});
      key.clear();
      if(action==='complete')state.completion=result;
      notice(action==='start'?'Активность начата. Она доступна в вашей истории.':result.applied===false?'Это выполнение уже учтено.':'Выполнение сохранено. Обновляем траекторию.');
      await renderRoute();
      if(action==='complete'&&(!location.hash||location.hash==='#home'))await recommend();
    }
    if(action==='apply-import'){
      if(!state.batch)throw new ApiError('Проверьте файлы перед применением.');
      const batch=state.batch,key=keyFor('import',batch.batch_id);
      const result=await api('/api/hr/import/apply',{method:'POST',body:{batch_id:batch.batch_id,mode:batch.mode},idempotencyKey:key.value,timeout:20000});
      key.clear();state.batch=null;
      const target=document.querySelector('#import-result');if(target)target.innerHTML=view.importResult(result,true);
      state.status={...state.status,...await api('/api/setup/status')};navigation();notice('Импорт завершён.');
    }
  }catch(error){notice(error.message);if(error.status===401){resetPrivateState();await renderRoute();}}
  finally{if(control.isConnected)control.disabled=false;}
});

document.addEventListener('submit',async event=>{
  const form=event.target;if(!(form instanceof HTMLFormElement))return;
  event.preventDefault();const submit=form.querySelector('button[type=submit]');
  if(submit?.disabled)return;if(submit)submit.disabled=true;
  if(form.querySelector('.form-error'))form.querySelector('.form-error').innerHTML='';
  const fields=new FormData(form);
  try{
    if(form.id==='login-form'){
      const password=form.elements.password.value;form.elements.password.value='';
      await api('/api/auth/login',{method:'POST',body:{username:fields.get('username'),password}});
      await loadSession();state.completion=null;await renderRoute();
    }
    if(form.id==='bootstrap-form'){
      if(!setupToken&&!preview)throw new ApiError('Откройте приложение через launcher: нужен одноразовый токен настройки.');
      const password=form.elements.password.value;form.elements.password.value='';
      await api('/api/setup/bootstrap',{method:'POST',body:{username:fields.get('username'),password,setup_token:setupToken}});
      setupToken=null;state.status=await api('/api/setup/status');await loadSession();location.hash='setup';await renderRoute();
    }
    if(form.id==='goal-form'){
      const goal=state.profile.goal_options[Number(fields.get('goal_index'))];
      if(!goal)throw new ApiError('Выберите цель из списка.');
      await api('/api/me/goal',{method:'PATCH',body:{target_role:goal.target_role,target_grade:goal.target_grade}});
      document.querySelector('#goal-dialog').close();state.completion=null;
      await renderRoute();notice('Цель обновлена. Рекомендации будут подобраны заново.');
      if(!location.hash||location.hash==='#home')await recommend();
    }
    if(form.id==='employee-search'){location.hash='employee/'+encodeURIComponent(fields.get('employee_id').trim());}
    if(form.id==='create-user-form'){
      const password=form.elements.password.value;form.elements.password.value='';
      await api('/api/hr/users',{method:'POST',body:{username:fields.get('username'),password,role:'employee',employee_id:fields.get('employee_id')}});
      form.reset();notice('Аккаунт сотрудника создан. Теперь можно войти под его логином.');
    }
    if(form.id==='import-form'){
      const validationVersion=++state.importVersion;
      state.batch=null;document.querySelector('#import-result').innerHTML='<div class="loading" role="status">Проверяем файлы и связи…</div>';
      fields.set('kind',form.dataset.initial==='true'?'initial':'additional');
      const result=await api('/api/hr/import/validate',{method:'POST',body:fields,timeout:20000});
      if(validationVersion!==state.importVersion||!form.isConnected)return;
      state.batch=result.valid?{batch_id:result.batch_id,mode:fields.get('mode')}:null;
      document.querySelector('#import-result').innerHTML=view.importResult(result);
    }
    if(form.classList.contains('provider-form')){
      if(preview)throw new ApiError('В предпросмотре API-ключи не принимаются. Подключите сервер приложения.');
      const apiKey=form.elements.api_key.value;form.elements.api_key.value='';
      const body={provider:form.dataset.provider,model_id:fields.get('model_id').trim(),persist:fields.get('persist')==='on'};
      if(apiKey)body.api_key=apiKey;
      const result=await api('/api/hr/settings/ai',{method:'POST',body,timeout:11000});
      if(result.valid!==true)throw new ApiError(result.message||'Провайдер не подтвердил подключение.');
      form.querySelector('.provider-result').textContent=`Подключение проверено · ${result.latency_ms??'—'} мс. Скорость рекомендации измеряется отдельно.`;
      form.elements.api_key.required=false;notice('Провайдер подключён.');
    }
    if(form.id==='ai-policy-form'){
      const primary=fields.get('primary_provider'),fallback=fields.get('fallback_provider')||null;
      if(primary===fallback)throw new ApiError('Основной и резервный провайдер должны различаться.');
      await api('/api/hr/settings/ai/policy',{method:'PATCH',body:{primary_provider:primary,fallback_provider:fallback,total_timeout_ms:10000}});notice('Режим рекомендаций сохранён.');
    }
  }catch(error){if(form.isConnected&&form.querySelector('.form-error'))formError(form,error);else notice(error.message);if(form.id==='import-form'){state.batch=null;document.querySelector('#import-result').innerHTML='';}if(error.status===401&&form.id!=='login-form'){resetPrivateState();await renderRoute();}}
  finally{if(form.classList.contains('provider-form'))form.elements.api_key.value='';if(submit?.isConnected)submit.disabled=false;}
});

document.addEventListener('change',event=>{if(event.target.closest('#import-form')){state.importVersion++;state.batch=null;document.querySelector('#import-result').innerHTML='';}});
document.querySelector('#logout').addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST',body:{}});resetPrivateState();await renderRoute();}catch(error){notice(error.message);}});
window.addEventListener('hashchange',()=>{document.querySelector('#goal-dialog').close();renderRoute();});
await boot();
