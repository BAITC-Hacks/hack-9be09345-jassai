// Adapter for teammate A's published API_CONTRACT.md v1.0.
// UI representations only: skills, eligibility and aggregate metrics come from A.
import {label} from './ui.js';
export function normalizeProfile(raw,catalog,rec=null){
  const skills=new Map((catalog.skills||[]).map(s=>[s.skill_id,s.name]));
  const events=new Map((catalog.events||[]).map(e=>[e.event_id,e]));
  const t=raw.trajectory, target=t.target;
  const history=[...raw.history].reverse().map(r=>{const event=events.get(r.event_id);return {...r,title:event?.title||r.event_id,mandatory:!!event?.mandatory,can_complete:!!event&&!event.mandatory&&r.status==='in_progress'&&(event.format==='self_paced'||r.date<=raw.as_of_date)};});
  const emptyStatus=!target.goal?'no_goal':t.coverage_pct===100?'goal_achieved':!raw.available_steps.length?'no_candidates':null;
  const enrich=event=>({...events.get(event.event_id),...event,description:event.description||events.get(event.event_id)?.description||'',record_id:event.activity_record_id,session_date:event.next_session,can_complete:!(event.mandatory??events.get(event.event_id)?.mandatory)&&(event.format==='self_paced'||!!event.next_session&&event.next_session<=raw.as_of_date),gains:(event.expected_gains||[]).map(g=>({...g,name:skills.get(g.skill_id)||g.skill_id})),develops_skills:(event.develops_skills||events.get(event.event_id)?.develops_skills||[]).map(g=>({...g,name:skills.get(g.skill_id)||g.skill_id})),prerequisite_details:Object.entries(event.prerequisites||events.get(event.event_id)?.prerequisites||{}).map(([id,required])=>({skill_id:id,name:skills.get(id)||id,required,current:t.effective_skills?.[id]??0}))});
  return {employee:raw.employee,as_of_date:raw.as_of_date,goal:target.goal?{...target.goal,source:target.source==='suggested_next_grade'?'suggested':target.source}:null,
    catalog_events:(catalog.events||[]).map(enrich),all_skills:catalog.skills||[],role_profiles:catalog.role_profiles||[],effective_skills:t.effective_skills??null,raw_trajectory:t,raw_history:[...raw.history],no_step_reasons:raw.no_step_reasons||{},
    goal_options:(catalog.role_profiles||[]).map(r=>({target_role:r.role,target_grade:r.grade})),
    coverage_pct:t.coverage_pct,critical_gap_count:t.critical_gaps.length,completed_count:raw.history.filter(r=>r.status==='completed').length,
    skills:t.skills,history,available_steps:raw.available_steps.map(enrich),recommendations:rec||(emptyStatus?{status:emptyStatus,source:'none',reasons:Object.keys(raw.no_step_reasons||{})}:null),
    skill_names:Object.fromEntries(skills)};
}
export function normalizeRecommendations(raw,profile,catalog){
  const names=new Map((catalog.skills||[]).map(s=>[s.skill_id,s.name]));
  if(raw.status==='no_candidates')return {status:!profile.trajectory.target.goal?'no_goal':profile.trajectory.coverage_pct===100?'goal_achieved':'no_candidates',source:'none',reasons:Object.keys(raw.reasons||{})};
  return {status:'ready',source:raw.mode==='ai'?'ai':'fallback',cached:raw.cached,reason:raw.reason,items:(raw.recommendations||[]).map(r=>{const event=r.event;return {...event,event_id:r.event_id,factors:r.factors,alternative:r.alternative,session_date:event.next_session,record_id:event.activity_record_id,can_complete:!event.mandatory&&(event.format==='self_paced'||event.next_session<=profile.as_of_date),gains:(event.expected_gains||[]).map(g=>({...g,name:names.get(g.skill_id)||g.skill_id}))};})};
}
export function sumCounts(counts={}){return Object.values(counts).reduce((sum,row)=>({added:sum.added+(row.added||0),updated:sum.updated+(row.updated||0),skipped:sum.skipped+(row.skipped||0)}),{added:0,updated:0,skipped:0});}
export function normalizeOverview(raw){
  const rows=raw.employees_without_step||[];
  const needsHelp=rows.filter(r=>r.goal&&r.coverage_pct!==100),groups=new Map();
  for(const employee of needsHelp){for(const code of Object.keys(employee.reasons||{})){if(code==='mandatory'||code==='already_completed'||code==='goal_not_set')continue;if(!groups.has(code))groups.set(code,new Set());groups.get(code).add(employee.employee_id);}}
  return {...raw,no_step_count:rows.length,needs_help_count:needsHelp.length,no_goal_count:rows.filter(r=>!r.goal).length,achieved_count:rows.filter(r=>r.goal&&r.coverage_pct===100).length,help_groups:[...groups].map(([code,ids])=>({code,reason:code,label:label(code),count:ids.size,employee_ids:[...ids]})),help_groups_note:'Один сотрудник может входить в несколько групп причин; суммы групп не равны числу сотрудников.',skill_gaps:(raw.skill_deficits||[]).map(r=>({...r,count:r.employees_with_gap,denominator:r.target_population,percentage:r.gap_pct,critical_count:r.critical_gaps})),no_next_step:rows.map(r=>({...r,needs_help:!!r.goal&&r.coverage_pct!==100,goal_label:r.goal?`${r.goal.target_role} · ${r.goal.target_grade}`:'Цель не выбрана',reason_message:!r.goal?'Цель не задана':r.coverage_pct===100?'Требования цели покрыты':Object.keys(r.reasons||{}).map(label).join(' · ')})),participation:(raw.participation||[]).map(r=>({...r,...r.statuses,total:r.records}))};
}
export function createBackendAdapter(rawApi){
  let catalog=null,lastProfile=null,recommendationCache=null,profileSignature=null,sessionEpoch=0;const completionReceipts=new Map();
  const getCatalog=async()=>{if(catalog)return catalog;const epoch=sessionEpoch,result=await rawApi('/api/catalog');if(epoch===sessionEpoch)catalog=result;return result;};
  const clear=()=>{sessionEpoch++;catalog=null;lastProfile=null;recommendationCache=null;profileSignature=null;completionReceipts.clear();};
  return async(path,options={})=>{
    const epoch=sessionEpoch;
    if(path==='/api/setup/status'){const r=await rawApi('/ready');return {...r,ai_status:r.ai_configured?'connected':'not_configured',ai_status_note:'Наличие подключённого модуля AI; доступность ключа и модели проверяется отдельно.'};}
    if(path==='/api/setup/bootstrap'){
      const b=options.body;await rawApi('/api/setup',{method:'POST',body:{token:b.setup_token,username:b.username,password:b.password}});
      return rawApi('/api/auth/login',{method:'POST',body:{username:b.username,password:b.password}});
    }
    if(path==='/api/auth/session'){const r=await rawApi(path,options);return {...r,user:{...r.user,user_id:r.user.username,display_name:r.user.username}};}
    if(path==='/api/auth/login'||path==='/api/auth/logout'){clear();return rawApi(path,options);}
    if(path==='/api/me'||/^\/api\/hr\/employees\/[^/]+$/.test(path)){
      const [raw,cat]=await Promise.all([rawApi(path,options),getCatalog()]);
      if(epoch!==sessionEpoch)return normalizeProfile(raw,cat);
      const signature=JSON.stringify(raw)+JSON.stringify(cat);
      if(signature!==profileSignature)recommendationCache=null;
      profileSignature=signature;lastProfile=raw;
      const normalized=normalizeProfile(raw,cat,recommendationCache),recordIds=new Set(raw.history.map(r=>r.record_id));
      normalized.completion_results=Object.fromEntries([...completionReceipts].filter(([id])=>recordIds.has(id)).map(([id,receipt])=>{const {profile:ignored,...result}=receipt;return [id,result];}));
      return normalized;
    }
    if(path==='/api/me/goal'){recommendationCache=null;return rawApi(path,{...options,body:{career_goal:options.body}});}
    if(path==='/api/me/recommendations'){
      const expected=profileSignature,profile=lastProfile,cat=await getCatalog();
      const result=normalizeRecommendations(await rawApi(path,options),profile,cat);
      if(epoch===sessionEpoch&&expected===profileSignature)recommendationCache=result;return result;
    }
    if(path==='/api/me/activities'){
      recommendationCache=null;const body=options.body;
      return rawApi(`/api/me/activities/${encodeURIComponent(body.event_id)}/start`,{...options,body:body.session_date?{session_date:body.session_date}:{}});
    }
    if(/^\/api\/me\/activities\/[^/]+\/complete$/.test(path)){
      const id=decodeURIComponent(path.split('/')[4]);const record=lastProfile?.history.find(r=>r.record_id===id);
      if(!record)throw new Error('Запись участия не найдена. Обновите профиль.');
      const before=lastProfile.trajectory.coverage_pct,beforeCritical=lastProfile.trajectory.critical_gaps.length,beforeIds=new Set(lastProfile.available_steps.map(e=>e.event_id));
      const result=await rawApi(`/api/me/activities/${encodeURIComponent(record.event_id)}/complete`,{...options,body:{activity_record_id:id}});
      if(epoch!==sessionEpoch)throw new Error('Операция завершилась в предыдущей сессии. Обновите профиль.');
      recommendationCache=null;lastProfile=result.profile;
      const cat=await getCatalog(),names=new Map(cat.skills.map(s=>[s.skill_id,s.name]));
      if(epoch!==sessionEpoch)throw new Error('Сессия изменилась. Обновите профиль.');
      if(completionReceipts.has(id))return {...completionReceipts.get(id),applied:false,already_applied:true,profile:normalizeProfile(result.profile,cat)};
      const goalSnapshot=result.profile.trajectory.target.goal?{...result.profile.trajectory.target.goal}:null;
      const receipt={...result,applied:result.applied??!(result.already_applied||record.status==='completed'),event_id:record.event_id,record_id:result.record?.record_id||id,title:cat.events.find(e=>e.event_id===record.event_id)?.title||record.event_id,target_before:goalSnapshot,target_after:goalSnapshot,goal_snapshot:goalSnapshot,changes:result.changes.map(g=>({...g,name:names.get(g.skill_id)||g.skill_id})),coverage_before:before,coverage_after:result.profile.trajectory.coverage_pct,critical_before:beforeCritical,critical_after:result.profile.trajectory.critical_gaps.length,unlocks:result.profile.available_steps.filter(e=>!beforeIds.has(e.event_id)),reward:result.reward,gamification:result.gamification,profile:normalizeProfile(result.profile,cat)};
      completionReceipts.set(id,receipt);return receipt;
    }
    if(path==='/api/hr/overview'||path.startsWith('/api/hr/overview?'))return normalizeOverview(await rawApi(path,options));
    if(path==='/api/hr/import/validate'){
      const body=new FormData();for(const [key,value] of options.body.entries()){if(value instanceof File){if(value.name||value.size)body.append('files',value,value.name);}else if(key==='mode')body.set('mode',value);}
      const r=await rawApi(path,{...options,body});return {...r,counts:sumCounts(r.counts),entity_counts:r.counts};
    }
    if(path==='/api/hr/import/apply'){
      const r=await rawApi(path,{...options,body:{batch_id:options.body.batch_id}});clear();
      return {...r,counts:sumCounts(r.report.counts),account_instructions:'Создайте сотруднику учётную запись в разделе «Сотрудники», затем войдите под ней.'};
    }
    return rawApi(path,options);
  };
}
