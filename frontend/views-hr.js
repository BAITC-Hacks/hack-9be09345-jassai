import {escapeHtml as e,number as n,date,label} from './ui.js';
import {icon} from './icons.js';

const heading=(title,text,actions='')=>`<div class="page-heading"><div><h1>${e(title)}</h1><p class="heading-sub">${e(text)}</p></div>${actions}</div>`;
const empty=(title,text)=>`<div class="empty"><h3>${e(title)}</h3><p>${e(text)}</p></div>`;
const profileLink=(id,text)=>`<a href="#employee/${encodeURIComponent(id)}">${e(text||id)}</a>`;
const reasons={no_goal:'Цель не выбрана',goal_not_set:'Цель не выбрана',goal_achieved:'Требования цели покрыты',no_candidates:'Нет подходящей активности',no_available_session:'Нет будущей сессии',no_sessions:'Нет будущей сессии',prerequisites_not_met:'Нужна предварительная подготовка',prerequisites:'Нужна предварительная подготовка',no_target_gain:'Нет прироста для цели',no_gain:'Нет прироста для цели',goal_outside_catalog:'Цель вне каталога',audience:'Ограничения роли или грейда'};
const reasonText=code=>reasons[code]||label(code);
const meter=(value,title)=>`<div class="meter" role="meter" aria-label="${e(title)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(100,Math.max(0,Number(value)||0))}"><div class="meter-fill" style="width:${Math.min(100,Math.max(0,Number(value)||0))}%"></div></div>`;
const goalLabel=goal=>goal?.target_role?`${goal.target_role} · ${goal.target_grade}`:null;
function reasonCodes(row){
  const source=row.reason_codes||row.no_step_reasons||row.reasons;
  if(Array.isArray(source))return source.map(r=>typeof r==='string'?r:r.code).filter(Boolean);
  if(source&&typeof source==='object')return Object.keys(source);
  return row.reason?[row.reason]:[];
}
function rowState(row){
  const codes=reasonCodes(row);
  if(codes.includes('no_goal')||codes.includes('goal_not_set')||(Object.hasOwn(row,'goal')&&!row.goal))return 'no_goal';
  if(row.coverage_pct===100||codes.includes('goal_achieved'))return 'goal_achieved';
  return 'needs_help';
}
function table(headers,rows,title='Пока нет данных',text='Здесь появятся данные после импорта.'){
  return rows.length?`<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th scope="col">${e(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:empty(title,text);
}
function countCard(title,count,note,tone='',action=null){
  return `<article class="stat"><div class="stat-label">${e(title)}</div><div class="stat-value ${tone}">${n(count)}</div><div class="stat-note">${e(note)}</div>${action?`<button class="button text small" data-action="hr-reason" data-id="${e(action)}">Посмотреть ${icon('arrow-right')}</button>`:''}</article>`;
}

export function hrView(data,{period='all',reason=null}={}){
  const rows=data.no_next_step||[];
  const needsHelp=rows.filter(row=>rowState(row)==='needs_help');
  const noGoal=rows.filter(row=>rowState(row)==='no_goal');
  const achieved=rows.filter(row=>rowState(row)==='goal_achieved');
  const fallbackGroups=new Map();
  for(const row of needsHelp)for(const code of new Set(reasonCodes(row).length?reasonCodes(row):['no_candidates']))fallbackGroups.set(code,(fallbackGroups.get(code)||0)+1);
  const rawGroups=Array.isArray(data.help_groups)?data.help_groups:[...fallbackGroups].map(([reason,count])=>({reason,count}));
  const groups=rawGroups.map(group=>({...group,reason:group.reason||group.code,label:group.label||reasonText(group.reason||group.code)}));
  const selectedRows=!reason?needsHelp:reason==='no_goal'?noGoal:reason==='goal_achieved'?achieved:reason==='needs_help'?needsHelp:needsHelp.filter(row=>reasonCodes(row).includes(reason)||(reason==='no_candidates'&&!reasonCodes(row).length));
  const selectedTitle=reason==='no_goal'?'Сотрудники без цели':reason==='goal_achieved'?'Требования цели покрыты':reason&&reason!=='needs_help'?reasonText(reason):'Сотрудники, которым нужна помощь';
  const periodLabel=data.period?.from?`${date(data.period.from)} — ${date(data.period.to)}`:`Вся история${data.period?.to?' до '+date(data.period.to):''}`;
  return `${heading('Обзор команды','Помогайте сотрудникам двигаться к карьерным целям.',`<a class="button secondary" href="#employees">${icon('users')} Сотрудники</a>`)}
    <div class="stats hr-stats">
      ${countCard('Сотрудников',data.employee_count,'В текущем срезе')}
      ${countCard('Нужна помощь',data.needs_help_count??needsHelp.length,'Нет доступного шага','warn','needs_help')}
      ${countCard('Без цели',data.no_goal_count??noGoal.length,'Нужно выбрать направление','','no_goal')}
      ${countCard('Цель покрыта',data.achieved_count??achieved.length,'Все требования выполнены','success','goal_achieved')}
    </div>
    <section class="panel table-panel"><div class="section-heading"><div><h2>Где нужна помощь</h2><p class="muted">Один сотрудник может встречаться в нескольких группах.</p></div></div>
      ${table(['Причина','Сотрудников','Действие'],groups.map(group=>[e(group.label),n(group.count),`<button class="button text small" data-action="hr-reason" data-id="${e(group.reason)}">Посмотреть ${icon('arrow-right')}</button>`]),needsHelp.length?'Причины пока не представлены':'Нет препятствий для следующего шага',needsHelp.length?'Откройте профиль сотрудника, чтобы посмотреть доступные данные.':'Сотрудники с выбранной и ещё не покрытой целью имеют доступные активности.')}
    </section>
    <section class="panel table-panel"><div class="section-heading"><div><h2>${e(selectedTitle)}</h2><p class="muted">${n(selectedRows.length)} в текущем списке</p></div>${reason?'<button class="button text small" data-action="hr-reason" data-id="">Сбросить фильтр</button>':''}</div>
      ${table(['Сотрудник','Карьерная цель','Состояние'],selectedRows.map(row=>[profileLink(row.employee_id,row.full_name||row.employee_id),e(row.goal_label||goalLabel(row.goal)||(rowState(row)==='no_goal'?'Не выбрана':'Не указана в списке')),e(row.reason_message||(rowState(row)==='needs_help'?reasonCodes(row).map(reasonText).join(' · ')||'Нет доступного шага':reasonText(rowState(row))))]),'Сотрудников в этой группе нет','Выберите другую причину или откройте общий список сотрудников.')}
    </section>
    <section class="panel table-panel"><div class="section-heading"><div><h2>Дефициты навыков</h2><p class="muted">Разрывы между текущими навыками и требованиями цели.</p></div></div>
      ${table(['Навык','С разрывом','Доля сотрудников','Критический разрыв'],(data.skill_gaps||[]).map(gap=>[e(gap.name||gap.skill_id),`${n(gap.count)} <span class="muted">из ${n(gap.denominator)}</span>`,`<div class="table-progress"><span>${n(gap.percentage)}%</span>${meter(gap.percentage,`Доля сотрудников с разрывом: ${gap.name||gap.skill_id}`)}</div>`,gap.critical_count?`<span class="pill warn">${n(gap.critical_count)} чел.</span>`:'<span class="muted">Нет</span>']))}
      <p class="explanation">Доля рассчитана среди сотрудников, которым этот навык нужен для выбранной цели.</p>
    </section>
    <section class="panel table-panel"><div class="section-heading"><div><h2>Участие в активностях</h2><p class="muted">${e(periodLabel)}</p></div><label class="field compact-field">Период участия<select id="hr-period" name="period"><option value="all" ${String(period)==='all'?'selected':''}>Вся история</option><option value="30" ${String(period)==='30'?'selected':''}>30 дней</option><option value="90" ${String(period)==='90'?'selected':''}>90 дней</option></select></label></div>
      ${table(['Активность','Завершено','В процессе','Прервано','Пропуск','Отказ','Просрочено','Всего'],(data.participation||[]).map(row=>[e(row.title||row.event_id),...['completed','in_progress','dropped','no_show','declined','overdue','total'].map(key=>n(row[key]))]),'В этом периоде нет записей','Выберите другой период, чтобы посмотреть участие сотрудников.')}
      <p class="explanation">Период применяется только к участию. Карьерные цели и дефициты показаны на дату текущего среза. Повторные посещения учитываются отдельно.</p>
    </section>`;
}

function selectOptions(values,selected,allLabel){
  return `<option value="">${e(allLabel)}</option>${[...new Set(values.filter(value=>value!==undefined&&value!==null&&String(value).trim()))].sort((a,b)=>String(a).localeCompare(String(b),'ru')).map(value=>`<option value="${e(value)}" ${String(value)===String(selected)?'selected':''}>${e(value)}</option>`).join('')}`;
}
export function employeesView(data,{search='',department='',role='',grade=''}={}){
  const employees=data.employees||[];
  const query=search.trim().toLocaleLowerCase('ru');
  const shown=employees.filter(person=>(!query||`${person.full_name||''} ${person.employee_id||''}`.toLocaleLowerCase('ru').includes(query))&&(!department||person.department===department)&&(!role||person.role===role)&&(!grade||String(person.grade)===String(grade)));
  return `${heading('Сотрудники','Профили, карьерные цели и доступ к личному пространству.',`<button class="button" data-action="create-access" ${employees.length?'':'disabled'}>${icon('plus')} Создать доступ</button>`)}
    <section class="panel table-panel"><form id="employee-filters" class="filterbar"><label class="field search-field">Имя или ID<input type="search" name="search" value="${e(search)}" placeholder="Найти сотрудника" maxlength="120"></label><label class="field">Отдел<select name="department">${selectOptions(employees.map(person=>person.department),department,'Все отделы')}</select></label><label class="field">Роль<select name="role">${selectOptions(employees.map(person=>person.role),role,'Все роли')}</select></label><label class="field">Грейд<select name="grade">${selectOptions(employees.map(person=>person.grade),grade,'Все грейды')}</select></label><button type="submit" class="button secondary">${icon('search')} Найти</button></form>
    <div class="section-heading"><p class="muted">Найдено ${n(shown.length)} из ${n(employees.length)}</p>${query||department||role||grade?'<button class="button text small" data-action="reset-employees">Очистить фильтры</button>':''}</div>
    ${table(['Сотрудник','Роль','Грейд','Отдел','Цель','Действие'],shown.map(person=>[`<strong>${profileLink(person.employee_id,person.full_name)}</strong><div class="muted">${e(person.employee_id)}</div>`,e(person.role),e(person.grade),e(person.department),e(goalLabel(person.career_goal||person.goal)||person.goal_label||'Не указана в списке'),`<a class="button text small" href="#employee/${encodeURIComponent(person.employee_id)}">Открыть ${icon('arrow-right')}</a>`]),employees.length?'Ничего не найдено':'Пока нет сотрудников',employees.length?'Измените имя или фильтры.':'Импортируйте данные, чтобы открыть профили и создать доступ.')}</section>`;
}

export function createAccessForm(employees=[]){
  return `<p class="muted">Привяжите личную учётную запись к профилю сотрудника.</p><form id="create-user-form"><div class="stack"><label class="field">Сотрудник<select name="employee_id" required>${employees.map(person=>`<option value="${e(person.employee_id)}">${e(person.full_name)} · ${e(person.employee_id)}</option>`).join('')}</select></label><label class="field">Логин<input name="username" autocomplete="off" required minlength="3" maxlength="120" placeholder="Не менее 3 символов"></label><label class="field">Пароль<input name="password" type="password" autocomplete="new-password" required minlength="10"><small>Не менее 10 символов. Передайте пароль сотруднику лично.</small></label></div><div class="form-error"></div><div class="form-actions"><button type="submit" class="button" ${employees.length?'':'disabled'}>Создать доступ</button></div></form>`;
}

export function hrProfileView(profile){
  const person=profile.employee||{};
  const goal=goalLabel(profile.goal);
  const skills=profile.skills||[];
  const gaps=skills.filter(skill=>Number(skill.current)<Number(skill.required));
  const covered=skills.filter(skill=>Number(skill.current)>=Number(skill.required));
  const codes=reasonCodes(profile).length?reasonCodes(profile):reasonCodes(profile.recommendations||{});
  const coverage=profile.coverage_pct;
  const knownCoverage=coverage!==null&&coverage!==undefined&&Number.isFinite(Number(coverage));
  const records=profile.history||[];
  const needsHelp=goal&&knownCoverage&&Number(coverage)<100&&!(profile.available_steps||[]).length;
  const warning=!goal?'<div class="info">Карьерная цель ещё не выбрана. Сотрудник может выбрать её в своём личном пространстве.</div>':knownCoverage&&Number(coverage)===100?'<div class="info">Требования выбранной цели покрыты. Это результат развития навыков; решение о повышении принимается отдельно.</div>':needsHelp?`<div class="info"><strong>${icon('alert-circle')} Для цели нет доступного шага</strong><p>${codes.length?codes.map(code=>e(reasonText(code))).join(' · '):'В текущем каталоге нет подходящей активности. Обсудите с сотрудником возможные варианты развития.'}</p></div>`:'';
  return `<a class="button text small" href="#employees">${icon('arrow-left')} К сотрудникам</a>${heading(person.full_name||person.employee_id||'Профиль сотрудника',[person.role,person.grade,person.department].filter(Boolean).join(' · '),'<span class="pill neutral">Просмотр HR</span>')}
    <section class="panel"><div class="section-heading"><div><h2>Карьерная цель</h2><p class="goal-title">${e(goal||'Пока не выбрана')}</p></div><span class="pill neutral">${e(person.employee_id)}</span></div><div class="coverage-summary"><strong>${knownCoverage?n(coverage)+'%':'—'}</strong><span class="muted"> требований цели покрыто</span></div>${knownCoverage?meter(coverage,'Покрытие требований карьерной цели'):''}<p class="muted">${n(gaps.length)} навыков требуют развития · ${n(covered.length)} требований покрыто</p></section>
    ${warning}
    <section class="panel table-panel"><div class="section-heading"><div><h2>Навыки для цели</h2><p class="muted">Текущие уровни и оставшиеся разрывы.</p></div></div>${table(['Навык','Текущий уровень','Требование','Состояние'],[...gaps,...covered].map(skill=>[e(skill.name||skill.skill_id),n(skill.current),n(skill.required),Number(skill.current)>=Number(skill.required)?`<span class="pill success">${icon('check-circle')} Покрыто</span>`:`<span class="pill ${skill.critical?'danger':'warn'}">${skill.critical?'Критический разрыв · ':''}не хватает ${n(Number(skill.required)-Number(skill.current))}</span>`]),'Требования не заданы','После выбора цели здесь появятся нужные навыки.')}</section>
    <section class="panel"><div class="section-heading"><div><h2>История развития</h2><p class="muted">Все записи участия · ${n(records.length)}</p></div></div>${records.length?`<div class="history-list">${records.map(record=>`<article class="history-item"><span class="history-icon">${icon(record.status==='completed'?'check-circle':'clock')}</span><div class="history-content"><div class="section-heading"><h3>${e(record.title||record.event_id)}</h3><span class="pill ${record.status==='completed'?'success':record.status==='in_progress'?'neutral':'warn'}">${e(label(record.status))}</span></div><p class="muted">${e(date(record.date))}${record.completion_pct!==undefined?' · выполнено '+n(record.completion_pct)+'%':''}</p>${Array.isArray(record.changes)&&record.changes.length?`<p>${record.changes.map(change=>`${e(change.name||change.skill_id)}: ${n(change.before)} → ${n(change.after)}`).join(' · ')}</p>`:''}</div></article>`).join('')}</div>`:empty('История пока пуста','Начатые и завершённые активности появятся здесь.')}</section>`;
}

const fileDescriptions={'employees.json':'Профили сотрудников и карьерные цели','skills.json':'Навыки и требования к ролям','events.json':'Каталог активностей','activity_history.csv':'История участия и выполнения'};
export function importView(initial=true){
  const files=initial?['employees.json','skills.json','events.json','activity_history.csv']:['employees.json','activity_history.csv'];
  return `${initial?'':heading('Импорт данных','Добавьте профили или обновите историю участия.')}<section class="panel"><h2>${initial?'Загрузите стартовые данные':'Выберите файлы'}</h2><div id="import-stepper" class="steps" aria-label="Этапы импорта">${['Выбор файлов','Проверка','Применение','Результат'].map((text,index)=>`<span class="step ${index===0?'active':''}" data-import-step="${index+1}" ${index===0?'aria-current="step"':''}><span>${index+1}</span> ${text}</span>`).join('')}</div><p class="muted">${initial?'Выберите четыре файла из распакованного набора career_quest_dataset.':'Можно загрузить employees.json, activity_history.csv или оба файла вместе.'}</p><form id="import-form" data-initial="${initial}"><div class="form-grid import-files">${files.map(file=>`<label class="field file-card">${icon('file')}<strong>${file}</strong><span class="muted">${fileDescriptions[file]}</span><input type="file" name="${file}" accept="${file.endsWith('.csv')?'.csv':'.json'}" ${initial?'required':''}></label>`).join('')}</div><label class="field">Режим импорта<select name="mode"><option value="add">Добавить новые записи</option>${initial?'':'<option value="update">Обновить существующие по ID</option>'}</select><small>Проверка покажет изменения до их применения. Существующие сотрудники не удаляются.</small></label><div class="form-error"></div><div class="form-actions"><button type="submit" class="button">${icon('check-circle')} Проверить файлы</button></div></form><div id="import-result" aria-live="polite"></div></section>`;
}
export function importResult(result,applied=false){
  const errors=result.errors||[];
  const conflicts=result.conflicts||[];
  const counts=result.counts||{};
  return `<div class="stack import-report" data-import-state="${applied?'applied':result.valid?'valid':'error'}"><div class="info"><strong>${icon(applied||result.valid?'check-circle':'alert-circle')} ${applied?'Данные загружены':result.valid?'Файлы прошли проверку':'Проверьте данные в файлах'}</strong><div class="summary-row"><span>${applied?'Добавлено':'Будет добавлено'}: <b>${n(counts.added)}</b></span><span>${applied?'Обновлено':'Будет обновлено'}: <b>${n(counts.updated)}</b></span><span>Пропущено: <b>${n(counts.skipped)}</b></span></div></div>${errors.length?`<div class="error" role="alert"><strong>Исправьте ошибки и повторите проверку</strong><ul>${errors.map(error=>`<li>${e(error.file||'')} ${e(error.row??error.object??'')} ${e(error.field||error.loc?.join('.')||'')}: ${e(error.message||error.msg||'Ошибка данных')}</li>`).join('')}</ul></div>`:''}${conflicts.length?`<div class="error" role="alert"><strong>Конфликты идентификаторов</strong><ul>${conflicts.map(conflict=>`<li>${e(conflict.id??conflict)} ${e(conflict.message||'')}</li>`).join('')}</ul><p>Проверьте ID и при необходимости явно выберите режим обновления.</p></div>`:''}${applied?`${result.employee_ids?.length?`<p>Открыть профиль: ${result.employee_ids.map(id=>profileLink(id,id)).join(' · ')}</p>`:''}<p class="muted">${e(result.account_instructions||'Для нового сотрудника создайте учётную запись в разделе «Сотрудники».')}</p><div class="form-actions"><a class="button" href="#employees">К сотрудникам ${icon('arrow-right')}</a><a class="button secondary" href="#hr">Обзор команды</a></div>`:result.valid&&result.batch_id?'<div class="form-actions"><button class="button" data-action="apply-import">Применить изменения</button></div>':''}</div>`;
}

export function settingsView(data={}){
  return `${heading('Настройки AI','Подключите провайдеров и выберите порядок обращений.')}<div class="provider-grid">${['openai','nvidia'].map(provider=>{
    const details=data.providers?.[provider]||{};
    const failed=details.status==='error'||Boolean(details.error);
    const status=failed?'Ошибка подключения':details.configured?'Ключ настроен':'Не настроен';
    return `<section class="panel"><div class="section-heading"><h2>${provider==='openai'?'OpenAI':'NVIDIA NIM'}</h2><span class="pill ${failed?'danger':details.configured?'success':'neutral'}" data-provider-status>${icon(failed?'alert-circle':details.configured?'check-circle':'settings')} ${status}</span></div><form class="provider-form" data-provider="${provider}"><label class="field">Модель<input name="model_id" value="${e(details.model_id||'')}" placeholder="Идентификатор модели" required maxlength="200" autocomplete="off"><small>Используйте Model ID, доступный в вашем аккаунте провайдера.</small></label><label class="field">API-ключ<input name="api_key" type="password" autocomplete="off" ${details.configured?'':'required'} placeholder="${details.configured?'Оставьте пустым, чтобы сохранить текущий':'Введите ключ провайдера'}"><small>Ключ передаётся локальному серверу и не сохраняется в браузере.</small></label><label class="check-row"><input type="checkbox" name="persist">Сохранить защищённо на этом компьютере</label><div class="form-error">${failed?`<div class="error">${e(typeof details.error==='string'?details.error:'Проверьте модель и ключ, затем повторите подключение.')}</div>`:''}</div><div class="form-actions"><button type="submit" class="button">Проверить подключение</button></div><div class="provider-result muted" role="status">${details.latency_ms!==undefined?'Последняя проверка: '+n(details.latency_ms)+' мс':'Подключение ещё не проверено в этой сессии.'}</div></form></section>`;
  }).join('')}</div><section class="panel"><div class="section-heading"><div><h2>Порядок обращения</h2><p class="muted">Резервный провайдер помогает при быстром отказе основного.</p></div></div><form id="ai-policy-form"><div class="form-grid"><label class="field">Основной провайдер<select name="primary_provider"><option value="openai" ${data.primary_provider==='openai'?'selected':''}>OpenAI</option><option value="nvidia" ${data.primary_provider==='nvidia'?'selected':''}>NVIDIA NIM</option></select></label><label class="field">Резервный провайдер<select name="fallback_provider"><option value="">Без резервного API</option><option value="openai" ${data.fallback_provider==='openai'?'selected':''}>OpenAI</option><option value="nvidia" ${data.fallback_provider==='nvidia'?'selected':''}>NVIDIA NIM</option></select></label></div><p class="explanation">Общий лимит ожидания рекомендации — 10 секунд, включая резерв. Скорость проверки подключения показана отдельно от скорости подбора. Если используется подбор по правилам, сотрудник увидит соответствующую отметку.</p><div class="form-error"></div><div class="form-actions"><button type="submit" class="button secondary">Сохранить режим</button></div></form></section><p class="muted">Баланс и лимиты доступны в личных кабинетах OpenAI и NVIDIA. Приложение не получает эти данные.</p>`;
}
