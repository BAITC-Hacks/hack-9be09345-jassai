// Explicit synthetic fixtures. No organiser data, external calls, secrets or persistence.
import {ApiError} from './api.js';
import {normalizeProfile,normalizeOverview,normalizeRecommendations} from './backend.js';
import {forecast} from './domain.js';
import {createCompanionPreview} from './companion-preview.js';
export function createPreview(mode='employee'){
  const asof='2026-10-01',role='Product Analyst',req={analytics:4,sql:4,leadership:3,communication:3,feedback:3};
  let user=['login','setup'].includes(mode)?null:{user_id:'preview',username:'preview',display_name:mode==='hr'?'HR · пример':'Алиаскар · пример',role:mode==='hr'?'hr':'employee'};
  let setup=mode==='setup',loaded=!setup,rec=null;
  const skills=[['analytics','Продуктовая аналитика'],['sql','SQL'],['leadership','Лидерство'],['communication','Коммуникация'],['feedback','Обратная связь']].map(([skill_id,name])=>({skill_id,name,type:['analytics','sql'].includes(skill_id)?'hard':'soft',description:`Учебный пример навыка «${name}».`}));
  const event=(event_id,title,skill_id,duration_hours,extra={})=>({event_id,title,description:'Вымышленная активность для проверки интерфейса. Реальное обучение в предпросмотре не проводится.',type:'course',format:'self_paced',duration_hours,mandatory:false,target_roles:[role],target_grades:['Middle','Senior'],prerequisites:{},upcoming_sessions:[],develops_skills:[{skill_id,gain:1,max_level:4}],...extra});
  const events=[event('DEMO_DESIGN','Решения на основе данных','analytics',2),event('DEMO_MENTOR','Практика продуктового лидерства','leadership',2,{type:'workshop',format:'online',upcoming_sessions:[asof,'2026-10-08']}),event('DEMO_FEEDBACK','Обратная связь, которая помогает','feedback',1.5),event('DEMO_SQL','SQL: основы анализа','sql',3),event('DEMO_EXPERIMENT','Продуктовые эксперименты','analytics',4,{type:'workshop',prerequisites:{analytics:3}})];
  const catalog={as_of_date:asof,skills,events,role_profiles:[{role,grade:'Senior',required_skills:req,critical_skills:['analytics','leadership']},{role,grade:'Middle',required_skills:{analytics:2,sql:2,communication:2},critical_skills:['analytics']},{role:'Product Manager',grade:'Senior',required_skills:{analytics:3,leadership:4,communication:4,feedback:3},critical_skills:['leadership']}]};
  const main={employee_id:'DEMO_PERSON',full_name:'Алиаскар · пример',department:'Цифровые продукты',role,grade:'Middle',tenure_months:32,work_format:'hybrid',preferred_language:'ru',last_review_date:'2026-09-01',skills:{analytics:2,sql:2,leadership:1,communication:3,feedback:1},career_goal:{target_role:role,target_grade:'Senior'}};
  const people=[main,{...main,employee_id:'DEMO_NO_GOAL',full_name:'Мадина · пример',grade:'Lead',career_goal:null},{...main,employee_id:'DEMO_ACHIEVED',full_name:'Дана · пример',skills:{analytics:4,sql:4,leadership:3,communication:3,feedback:3}},{...main,employee_id:'DEMO_BLOCKED',full_name:'Тимур · пример',role:'Data Analyst',department:'Аналитика'}];
  const history=[{record_id:'OLD_SQL',employee_id:main.employee_id,event_id:'DEMO_SQL',date:'2026-09-18',status:'completed',completion_pct:100,source:'import'},{record_id:'OLD_FEEDBACK_DECLINED',employee_id:main.employee_id,event_id:'DEMO_FEEDBACK',date:'2026-08-20',status:'declined',completion_pct:0,source:'import'}];
  const outcomes=new Map();
  const gain=(levels,e)=>{const next={...levels};for(const g of e.develops_skills){const old=next[g.skill_id]||0;next[g.skill_id]=old+Math.max(0,Math.min(g.gain,g.max_level-old,5-old));}return next;};
  function rawProfile(person=main){
    const rows=history.filter(r=>r.employee_id===person.employee_id).sort((a,b)=>a.date.localeCompare(b.date)||a.record_id.localeCompare(b.record_id));let levels={...person.skills};
    for(const r of rows)if(r.status==='completed'&&r.date<=asof&&(r.date>person.last_review_date||r.date===person.last_review_date&&r.source==='application'))levels=gain(levels,events.find(e=>e.event_id===r.event_id));
    const target=catalog.role_profiles.find(r=>r.role===person.career_goal?.target_role&&r.grade===person.career_goal?.target_grade),requirements=target?.required_skills||{},critical=target?.critical_skills||[];
    const progress=Object.entries(requirements).map(([skill_id,required])=>({skill_id,name:skills.find(s=>s.skill_id===skill_id).name,current:levels[skill_id]||0,required,gap:Math.max(0,required-(levels[skill_id]||0)),critical:critical.includes(skill_id)}));
    const total=Object.values(requirements).reduce((a,b)=>a+b,0),coverage=total?Math.round(10000*progress.reduce((sum,s)=>sum+Math.min(s.current,s.required),0)/total)/100:null,available=[],reasons={};
    for(const e of events){
      const why=[],ongoing=rows.find(r=>r.event_id===e.event_id&&r.status==='in_progress'),completed=rows.some(r=>r.event_id===e.event_id&&r.status==='completed'),next=gain(levels,e);
      if(!e.target_roles.includes(person.role))why.push('role_not_eligible');if(!e.target_grades.includes(person.grade))why.push('grade_not_eligible');if(completed)why.push('already_completed');if(Object.entries(e.prerequisites).some(([id,value])=>(levels[id]||0)<value))why.push('prerequisites_not_met');if(!person.career_goal)why.push('goal_not_set');
      const gains=Object.keys(next).filter(id=>next[id]>(levels[id]||0)).map(skill_id=>({skill_id,before:levels[skill_id]||0,after:next[skill_id],gain:next[skill_id]-(levels[skill_id]||0),gap_closed:Math.min(Math.max(0,(requirements[skill_id]||0)-(levels[skill_id]||0)),next[skill_id]-(levels[skill_id]||0)),critical:critical.includes(skill_id)}));
      if(!gains.some(g=>g.gap_closed))why.push('no_target_gain');
      if(why.length){for(const reason of why)reasons[reason]=(reasons[reason]||0)+1;continue;}
      available.push({...e,expected_gains:gains,action:ongoing?'continue':'start',activity_record_id:ongoing?.record_id||null,next_session:ongoing?.date||e.upcoming_sessions.find(d=>d>=asof)||null});
    }
    return {employee:structuredClone(person),as_of_date:asof,trajectory:{effective_skills:levels,target:{goal:person.career_goal,source:person.career_goal?'explicit':'not_set',requirements,critical_skills:critical},skills:progress,coverage_pct:coverage,critical_gaps:progress.filter(s=>s.critical&&s.gap>0)},history:rows,available_steps:available,no_step_reasons:available.length?{}:reasons};
  }
  function recommendation(){const p=rawProfile(),wanted=['DEMO_DESIGN','DEMO_MENTOR','DEMO_FEEDBACK'];if(!p.available_steps.length)return {...normalizeProfile(p,catalog).recommendations,source:'preview'};const selection=p.available_steps.filter(e=>wanted.includes(e.event_id)).slice(0,3),chosen=selection.length?selection:p.available_steps.slice(0,3);const wire={mode:'preview',recommendations:chosen.map(e=>({event_id:e.event_id,event:e,reason:'Пример объяснения на синтетических данных.',factors:[{type:'skill_gap',text:`${skills.find(s=>s.skill_id===e.expected_gains[0].skill_id).name}: ${e.expected_gains[0].before} → ${e.expected_gains[0].after}; требование цели ${p.trajectory.target.requirements[e.expected_gains[0].skill_id]}.`},{type:'goal',text:`Подходит роли ${main.role} и грейду ${main.grade}.`},{type:'duration',text:`Продолжительность ${e.duration_hours} ч${e.format==='self_paced'?'; в удобное время':'; доступная дата '+e.next_session}.`}]}))};return {...normalizeRecommendations(wire,p,catalog),source:'preview'};}
  rec=recommendation();
  const profile=person=>({...normalizeProfile(rawProfile(person),catalog,person&&person!==main?null:rec),completion_results:Object.fromEntries(outcomes)});
  const companion=createCompanionPreview({getProfile:()=>rawProfile(),catalog});
  function overview(params){
    const rows=people.map(rawProfile),dateFrom=params.get('date_from'),dateTo=params.get('date_to')||asof,deficits=new Map();
    for(const row of rows)for(const s of row.trajectory.skills){if(!deficits.has(s.skill_id))deficits.set(s.skill_id,{skill_id:s.skill_id,name:s.name,target_population:0,employees_with_gap:0,critical_gaps:0});const d=deficits.get(s.skill_id);d.target_population++;d.employees_with_gap+=Number(s.gap>0);d.critical_gaps+=Number(s.critical&&s.gap>0);}
    const participation=events.map(e=>{const records=history.filter(r=>r.event_id===e.event_id&&r.date<=dateTo&&(!dateFrom||r.date>=dateFrom)),statuses=Object.fromEntries(['completed','in_progress','dropped','no_show','declined','overdue'].map(s=>[s,records.filter(r=>r.status===s).length]));return {event_id:e.event_id,title:e.title,statuses,records:records.length,completion_pct:records.length?100*statuses.completed/records.length:null};});
    return normalizeOverview({as_of_date:asof,employee_count:people.length,period:{from:dateFrom,to:dateTo},skill_deficits:[...deficits.values()].map(d=>({...d,gap_pct:Math.round(10000*d.employees_with_gap/d.target_population)/100})),employees_without_step:rows.filter(r=>!r.available_steps.length).map(r=>({...r.employee,goal:r.trajectory.target.goal,coverage_pct:r.trajectory.coverage_pct,reasons:r.no_step_reasons})),participation});
  }
  return async(path,{method='GET',body}={})=>{
    const url=new URL(path,'http://preview.local'),route=url.pathname;
    if(route==='/api/setup/status')return {setup_required:setup,dataset_loaded:loaded,as_of_date:asof,ai_status:'not_configured'};
    if(route==='/api/setup/bootstrap'){setup=false;loaded=false;user={user_id:'preview',username:'hr',display_name:'HR · пример',role:'hr'};return {};}
    if(route==='/api/auth/login'){user={user_id:'preview',username:body?.username||'preview',display_name:'Алиаскар · пример',role:'employee'};return {};}
    if(route==='/api/auth/logout'){user=null;return {};}
    if(route==='/api/auth/session'){if(!user)throw new ApiError('Войдите в приложение.',401);return {user,csrf_token:'preview-token'};}
    if(!user)throw new ApiError('Войдите в приложение.',401);
    if(route.startsWith('/api/me/companion')||route.startsWith('/api/me/gamification')){
      if(user.role!=='employee')throw new ApiError('У вашей учётной записи нет доступа.',403);
      if(route==='/api/me/companion'&&method==='GET')return companion.view();
      if(route==='/api/me/companion/equip'&&method==='POST')return companion.equip(body?.item_id);
      if(route==='/api/me/gamification'&&method==='GET')return companion.view();
      if(route==='/api/me/gamification'&&method==='PATCH')return companion.setEnabled(body?.enabled);
      if(route==='/api/me/gamification/quest'&&method==='POST')return companion.chooseQuest(body?.event_id);
      if(route==='/api/me/gamification/quest'&&method==='DELETE')return companion.clearQuest();
      throw new ApiError('Операция недоступна в предпросмотре.',404);
    }
    if(route==='/api/catalog')return structuredClone(catalog);
    if(route==='/api/me')return structuredClone(profile());
    if(/^\/api\/hr\/employees\/[^/]+$/.test(route)){const person=people.find(p=>p.employee_id===decodeURIComponent(route.split('/').at(-1)));if(!person)throw new ApiError('Профиль не найден в предпросмотре.',404);return structuredClone(profile(person));}
    if(route==='/api/me/goal'){main.career_goal=body;rec=null;return {};}
    if(route==='/api/me/recommendations'){rec=recommendation();return structuredClone(rec);}
    if(route==='/api/me/activities'){
      const id=body?.event_id||'DEMO_DESIGN',candidate=rawProfile().available_steps.find(e=>e.event_id===id);if(!candidate)throw new ApiError('Активность недоступна.',409);
      const old=history.find(r=>r.event_id===id&&r.employee_id===main.employee_id&&r.status==='in_progress');if(old)return {record:structuredClone(old),already_started:true};
      const record={record_id:id==='DEMO_DESIGN'?'DEMO_RECORD':`DEMO_RECORD_${id}`,employee_id:main.employee_id,event_id:id,date:candidate.next_session||asof,status:'in_progress',completion_pct:0,source:'application'};history.push(record);rec=recommendation();return {record:structuredClone(record),record_id:record.record_id,status:record.status};
    }
    if(route.endsWith('/complete')){
      const id=decodeURIComponent(route.split('/').at(-2));if(outcomes.has(id))return {...structuredClone(outcomes.get(id)),applied:false,already_applied:true};
      const row=history.find(r=>r.record_id===id&&r.employee_id===main.employee_id);if(!row||row.status!=='in_progress'||row.date>asof)throw new ApiError('Активность нельзя завершить.',409);
      const before=profile(),prediction=forecast(before,row.event_id);if(!prediction.available)throw new ApiError('Прогноз недоступен.',409);
      row.status='completed';row.completion_pct=100;row.session_date=row.date;row.date=asof;row.completed_at=asof;rec=null;
      const event=events.find(e=>e.event_id===row.event_id),reward=companion.award(event,row,prediction.changes);
      const after=profile(),previousIds=new Set(before.available_steps.map(e=>e.event_id));const result={...prediction,applied:true,event_id:row.event_id,record_id:id,title:event.title,target_before:before.goal,target_after:after.goal,goal_snapshot:after.goal,unlocks:after.available_steps.filter(e=>!previousIds.has(e.event_id)),record:structuredClone(row),reward,gamification:companion.view()};outcomes.set(id,result);return structuredClone(result);
    }
    if(route==='/api/hr/employees')return {employees:people.map(({employee_id,full_name,role,grade,department})=>({employee_id,full_name,role,grade,department}))};
    if(route==='/api/hr/users')return {user:{username:body.username,role:'employee',employee_id:body.employee_id}};
    if(route==='/api/hr/overview')return overview(url.searchParams);
    if(route==='/api/hr/import/validate')return {valid:true,batch_id:'DEMO_BATCH',counts:{added:1,updated:0,skipped:0},conflicts:[],errors:[]};
    if(route==='/api/hr/import/apply'){loaded=true;return {counts:{added:1,updated:0,skipped:0},employee_ids:['DEMO_PERSON'],account_instructions:'Это предпросмотр: реальные данные и аккаунты не создаются.'};}
    if(route==='/api/hr/settings/ai'&&method==='GET')return {providers:{openai:{configured:false},nvidia:{configured:false}},primary_provider:'openai',fallback_provider:'nvidia'};
    if(route.endsWith('/policy'))return {};
    throw new ApiError('Операция недоступна в предпросмотре.',404);
  };
}
