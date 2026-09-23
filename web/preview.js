// Explicit, synthetic UI fixtures. Never activated on an API error.
// No organiser data, no real users, no external requests, no credentials.
import {ApiError} from './api.js';
export function createPreview(mode='employee'){
  let user=mode==='login'||mode==='setup'?null:{user_id:'preview',username:'preview',display_name:mode==='hr'?'HR · пример':'Алексей · пример',role:mode==='hr'?'hr':'employee'};
  let setup=mode==='setup',loaded=true,goal={target_role:'Backend Engineer',target_grade:'Senior',source:'explicit'};
  let completed=false,started=false;
  const options=[{target_role:'Backend Engineer',target_grade:'Senior'},{target_role:'Data Analyst',target_grade:'Middle'}];
  const recommendation=()=>({status:'ready',source:'preview',items:[{event_id:'DEMO_DESIGN',title:'Проектирование надёжных систем',format:'self_paced',duration_hours:6,action:started?'continue':'start',record_id:started?'DEMO_RECORD':null,can_complete:true,gains:[{name:'System Design',before:2,after:3}],factors:[{text:'System Design — критический навык для вашей цели Senior.'},{text:'Текущий уровень 2 при требуемом 4: шаг сокращает разрыв.'},{text:'Самостоятельный формат позволяет учесть пропуски очных встреч.'}]},{event_id:'DEMO_MENTOR',title:'Практика архитектурных решений',format:'online',duration_hours:2,session_date:'2026-10-08',action:'start',gains:[{name:'Problem Solving',before:3,after:4}],factors:[{text:'Навык входит в требования вашей целевой роли.'},{text:'Ваш текущий грейд соответствует аудитории встречи.'},{text:'Два часа позволяют совместить практику с основной работой.'}]},{event_id:'DEMO_FEEDBACK',title:'Обратная связь, которая помогает',format:'self_paced',duration_hours:3,action:'start',gains:[{name:'Feedback',before:2,after:3}],factors:[{text:'Навык обратной связи нужен на следующем грейде.'},{text:'Текущий уровень ниже требования цели на один уровень.'},{text:'Самостоятельный формат не требует ожидания сессии.'}]}]});
  let rec=recommendation();
  const profile=()=>({employee:{employee_id:'DEMO_PERSON',full_name:'Алексей · пример',role:'Backend Engineer',grade:'Middle',tenure_months:32},goal,goal_options:options,coverage_pct:completed?76:72,critical_gap_count:2,completed_count:completed?13:12,version:completed?2:1,skills:[{skill_id:'design',name:'System Design',current:completed?3:2,required:4,critical:true},{skill_id:'python',name:'Python',current:3,required:4,critical:true},{skill_id:'communication',name:'Communication',current:3,required:3,critical:false}],history:[...(started?[{record_id:'DEMO_RECORD',event_id:'DEMO_DESIGN',title:'Проектирование надёжных систем',date:'2026-10-01',status:completed?'completed':'in_progress',completion_pct:completed?100:0,can_complete:!completed}]:[]),{record_id:'OLD1',title:'Практика Python',date:'2026-09-22',status:'completed',completion_pct:100},{record_id:'OLD2',title:'Командная коммуникация',date:'2026-09-14',status:'completed',completion_pct:100}],recommendations:rec});
  return async(path,{method='GET',body}={})=>{
    if(path==='/api/setup/status')return {setup_required:setup,dataset_loaded:loaded,as_of_date:'2026-10-01',ai_status:'not_configured'};
    if(path==='/api/setup/bootstrap'){setup=false;loaded=false;user={user_id:'preview',username:'hr',display_name:'HR · пример',role:'hr'};return {};}
    if(path==='/api/auth/login'){user={user_id:'preview',username:'preview',display_name:'Алексей · пример',role:'employee'};return {};}
    if(path==='/api/auth/logout'){user=null;return {};}
    if(path==='/api/auth/session'){if(!user)throw new ApiError('Войдите в приложение.',401);return {user,csrf_token:'preview-token'};}
    if(!user)throw new ApiError('Войдите в приложение.',401);
    if(path==='/api/me'||path.startsWith('/api/hr/employees/'))return structuredClone(profile());
    if(path==='/api/me/goal'){goal={...body,source:'explicit'};rec=null;return {};}
    if(path==='/api/me/recommendations'){rec=recommendation();if(completed)rec.items=rec.items.slice(1);return structuredClone(rec);}
    if(path==='/api/me/activities'){started=true;rec=recommendation();return {record_id:'DEMO_RECORD',status:'in_progress'};}
    if(path.endsWith('/complete')){const applied=!completed;completed=true;return {applied,changes:[{name:'System Design',before:2,after:3}],coverage_before:72,coverage_after:76};}
    if(path==='/api/hr/overview')return {employee_count:8,no_step_count:2,period:{from:'2024-10-01',to:'2026-09-30'},skill_gaps:[{name:'System Design',count:3,denominator:5,percentage:60,critical_count:2},{name:'Communication',count:2,denominator:8,percentage:25,critical_count:0}],no_next_step:[{employee_id:'DEMO_PERSON',full_name:'Сотрудник · пример',goal_label:'Data Analyst · Middle',reason:'audience'}],participation:[{title:'Проектирование систем',completed:3,in_progress:2,dropped:1,no_show:0,declined:1,overdue:0,total:7}]};
    if(path==='/api/hr/import/validate')return {valid:true,batch_id:'DEMO_BATCH',counts:{added:1,updated:0,skipped:0},conflicts:[],errors:[]};
    if(path==='/api/hr/import/apply'){loaded=true;return {counts:{added:1,updated:0,skipped:0},employee_ids:['DEMO_PERSON'],account_instructions:'Это предпросмотр: реальные аккаунты не создаются.'};}
    if(path==='/api/hr/settings/ai'&&method==='GET')return {providers:{openai:{configured:false},nvidia:{configured:false}},primary_provider:'openai',fallback_provider:'nvidia'};
    if(path.endsWith('/policy'))return {};
    throw new ApiError('Операция недоступна в предпросмотре.',404);
  };
}
