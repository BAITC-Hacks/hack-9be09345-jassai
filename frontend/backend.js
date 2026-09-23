// Adapter for teammate A's published API_CONTRACT.md v1.0.
// UI representations only: skills, eligibility and aggregate metrics come from A.
import {label} from './ui.js';
export function normalizeProfile(raw,catalog,rec=null){
  const skills=new Map((catalog.skills||[]).map(s=>[s.skill_id,s.name]));
  const events=new Map((catalog.events||[]).map(e=>[e.event_id,e]));
  const t=raw.trajectory, target=t.target;
  const history=[...raw.history].reverse().map(r=>{const event=events.get(r.event_id);return {...r,title:event?.title||r.event_id,can_complete:!!event&&!event.mandatory&&r.status==='in_progress'&&(event.format==='self_paced'||r.date<=raw.as_of_date)};});
  const emptyStatus=!target.goal?'no_goal':t.coverage_pct===100?'goal_achieved':!raw.available_steps.length?'no_candidates':null;
  return {employee:raw.employee,as_of_date:raw.as_of_date,goal:target.goal?{...target.goal,source:target.source==='suggested_next_grade'?'suggested':target.source}:null,
    goal_options:(catalog.role_profiles||[]).map(r=>({target_role:r.role,target_grade:r.grade})),
    coverage_pct:t.coverage_pct,critical_gap_count:t.critical_gaps.length,completed_count:raw.history.filter(r=>r.status==='completed').length,
    skills:t.skills,history,available_steps:raw.available_steps.map(event=>({...event,record_id:event.activity_record_id,session_date:event.next_session,can_complete:!event.mandatory&&(event.format==='self_paced'||event.next_session<=raw.as_of_date),gains:event.expected_gains||[]})),recommendations:rec||(emptyStatus?{status:emptyStatus,source:'none',reasons:Object.keys(raw.no_step_reasons||{})}:null),
    skill_names:Object.fromEntries(skills)};
}
export function normalizeRecommendations(raw,profile,catalog){
  const names=new Map((catalog.skills||[]).map(s=>[s.skill_id,s.name]));
  if(raw.status==='no_candidates')return {status:!profile.trajectory.target.goal?'no_goal':profile.trajectory.coverage_pct===100?'goal_achieved':'no_candidates',source:'none',reasons:Object.keys(raw.reasons||{})};
  return {status:'ready',source:raw.mode==='ai'?'ai':'fallback',cached:raw.cached,reason:raw.reason,items:(raw.recommendations||[]).map(r=>{const event=r.event;return {...event,event_id:r.event_id,factors:r.factors,alternative:r.alternative,session_date:event.next_session,record_id:event.activity_record_id,can_complete:event.format==='self_paced'||event.next_session<=profile.as_of_date,gains:(event.expected_gains||[]).map(g=>({...g,name:names.get(g.skill_id)||g.skill_id}))};})};
}
export function sumCounts(counts={}){return Object.values(counts).reduce((sum,row)=>({added:sum.added+(row.added||0),updated:sum.updated+(row.updated||0),skipped:sum.skipped+(row.skipped||0)}),{added:0,updated:0,skipped:0});}
export function normalizeOverview(raw){
  const rows=raw.employees_without_step||[];
  return {...raw,no_step_count:rows.length,skill_gaps:(raw.skill_deficits||[]).map(r=>({...r,count:r.employees_with_gap,denominator:r.target_population,percentage:r.gap_pct,critical_count:r.critical_gaps})),no_next_step:rows.map(r=>({...r,goal_label:r.goal?`${r.goal.target_role} · ${r.goal.target_grade}`:'Цель не выбрана',reason_message:!r.goal?'Цель не задана':r.coverage_pct===100?'Требования цели покрыты':Object.keys(r.reasons||{}).map(label).join(' · ')})),participation:(raw.participation||[]).map(r=>({...r,...r.statuses,total:r.records}))};
}
export function createBackendAdapter(rawApi){
  let catalog=null,lastProfile=null,recommendationCache=null,profileSignature=null;
  const getCatalog=async()=>catalog||(catalog=await rawApi('/api/catalog'));
  const clear=()=>{catalog=null;lastProfile=null;recommendationCache=null;profileSignature=null;};
  return async(path,options={})=>{
    if(path==='/api/setup/status'){const r=await rawApi('/ready');return {...r,ai_status:r.ai_configured?'connected':'not_configured'};}
    if(path==='/api/setup/bootstrap'){
      const b=options.body;await rawApi('/api/setup',{method:'POST',body:{token:b.setup_token,username:b.username,password:b.password}});
      return rawApi('/api/auth/login',{method:'POST',body:{username:b.username,password:b.password}});
    }
    if(path==='/api/auth/session'){const r=await rawApi(path,options);return {...r,user:{...r.user,user_id:r.user.username,display_name:r.user.username}};}
    if(path==='/api/auth/login'||path==='/api/auth/logout'){clear();return rawApi(path,options);}
    if(path==='/api/me'||/^\/api\/hr\/employees\/[^/]+$/.test(path)){
      const [raw,cat]=await Promise.all([rawApi(path,options),getCatalog()]);
      const signature=JSON.stringify(raw)+JSON.stringify(cat);
      if(signature!==profileSignature)recommendationCache=null;
      profileSignature=signature;lastProfile=raw;
      return normalizeProfile(raw,cat,recommendationCache);
    }
    if(path==='/api/me/goal'){recommendationCache=null;return rawApi(path,{...options,body:{career_goal:options.body}});}
    if(path==='/api/me/recommendations'){
      const expected=profileSignature,profile=lastProfile,cat=await getCatalog();
      const result=normalizeRecommendations(await rawApi(path,options),profile,cat);
      if(expected===profileSignature)recommendationCache=result;return result;
    }
    if(path==='/api/me/activities'){
      recommendationCache=null;const body=options.body;
      return rawApi(`/api/me/activities/${encodeURIComponent(body.event_id)}/start`,{...options,body:body.session_date?{session_date:body.session_date}:{}});
    }
    if(/^\/api\/me\/activities\/[^/]+\/complete$/.test(path)){
      const id=decodeURIComponent(path.split('/')[4]);const record=lastProfile?.history.find(r=>r.record_id===id);
      if(!record)throw new Error('Запись участия не найдена. Обновите профиль.');
      const before=lastProfile.trajectory.coverage_pct;
      const result=await rawApi(`/api/me/activities/${encodeURIComponent(record.event_id)}/complete`,{...options,body:{activity_record_id:id}});
      recommendationCache=null;lastProfile=result.profile;
      const cat=await getCatalog(),names=new Map(cat.skills.map(s=>[s.skill_id,s.name]));
      return {applied:result.applied!==false,changes:result.changes.map(g=>({...g,name:names.get(g.skill_id)||g.skill_id})),coverage_before:before,coverage_after:result.profile.trajectory.coverage_pct,reward:result.reward,gamification:result.gamification};
    }
    if(path==='/api/hr/overview')return normalizeOverview(await rawApi(path,options));
    if(path==='/api/hr/import/validate'){
      const body=new FormData();for(const [key,value] of options.body.entries()){if(value instanceof File)body.append('files',value,value.name);else if(key==='mode')body.set('mode',value);}
      const r=await rawApi(path,{...options,body});return {...r,counts:sumCounts(r.counts),entity_counts:r.counts};
    }
    if(path==='/api/hr/import/apply'){
      const r=await rawApi(path,{...options,body:{batch_id:options.body.batch_id}});clear();
      return {...r,counts:sumCounts(r.report.counts),account_instructions:'Создайте сотруднику учётную запись в разделе «Профили и доступ», затем войдите под ней.'};
    }
    return rawApi(path,options);
  };
}
