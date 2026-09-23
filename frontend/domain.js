// Read-only previews of published server rules. Never authorizes an API action.
const number=value=>typeof value==='number'&&Number.isFinite(value);
const ordered=rows=>[...rows].sort((a,b)=>String(a.date).localeCompare(String(b.date))||String(a.completed_at||'').localeCompare(String(b.completed_at||''))||String(a.record_id).localeCompare(String(b.record_id)));
const history=profile=>profile.raw_history||profile.history||[];
const catalog=profile=>profile.catalog_events||[];
const names=profile=>profile.skill_names||Object.fromEntries((profile.all_skills||[]).map(s=>[s.skill_id,s.name]));
const requirements=profile=>profile.raw_trajectory?.target?.requirements;
const critical=profile=>profile.raw_trajectory?.target?.critical_skills||(profile.skills||[]).filter(s=>s.critical).map(s=>s.skill_id);
const level=(levels,id)=>levels[id]??0;
function validLevels(levels){return levels&&typeof levels==='object'&&Object.values(levels).every(v=>number(v)&&v>=0&&v<=5);}
function hasTarget(profile){const req=requirements(profile);return !!profile.goal&&req&&Object.keys(req).length>0&&Object.values(req).every(v=>number(v)&&v>=0&&v<=5);}
function metrics(profile,levels){
  const req=requirements(profile),total=Object.values(req||{}).reduce((a,b)=>a+b,0);
  return {coverage:total?Math.round(10000*Object.entries(req).reduce((sum,[id,value])=>sum+Math.min(level(levels,id),value),0)/total)/100:null,critical:critical(profile).filter(id=>level(levels,id)<(req?.[id]??0)).length};
}
function capped(levels,event){
  const after={...levels};
  if(!Array.isArray(event.develops_skills))return null;
  for(const item of event.develops_skills){
    if(!item.skill_id||!number(item.gain)||!number(item.max_level)||item.gain<0||item.max_level<0||item.max_level>5)return null;
    const old=level(after,item.skill_id);after[item.skill_id]=old+Math.max(0,Math.min(item.gain,item.max_level-old,5-old));
  }
  return after;
}
function eligibility(profile,event,levels,rows=history(profile),{target=true}={}){
  const reasons=[],employee=profile.employee||{},asof=profile.as_of_date;
  if(event.mandatory)reasons.push('mandatory');
  if(!Array.isArray(event.target_roles)||!Array.isArray(event.target_grades)||!event.prerequisites||!asof||!employee.role||!employee.grade)reasons.push('incomplete_data');
  else {
    if(!event.target_roles.includes(employee.role))reasons.push('role_not_eligible');
    if(!event.target_grades.includes(employee.grade))reasons.push('grade_not_eligible');
    if(Object.entries(event.prerequisites).some(([id,value])=>level(levels,id)<value))reasons.push('prerequisites_not_met');
  }
  const completed=rows.filter(r=>r.event_id===event.event_id&&r.status==='completed');
  if(completed.length&&event.event_id!=='EV_036')reasons.push('already_completed');
  const ongoing=rows.some(r=>r.event_id===event.event_id&&r.status==='in_progress');
  const completedDates=new Set(completed.map(r=>r.session_date||r.date));
  if(event.format!=='self_paced'&&!ongoing&&!(event.upcoming_sessions||[]).some(d=>d>=asof&&!completedDates.has(d)))reasons.push('no_available_session');
  if(target){
    if(!hasTarget(profile))reasons.push('goal_not_set');
    else {const after=capped(levels,event),req=requirements(profile);if(!after)reasons.push('incomplete_data');else if(!Object.keys(req).some(id=>level(levels,id)<req[id]&&level(after,id)>level(levels,id)))reasons.push('no_target_gain');}
  }
  return [...new Set(reasons)];
}
function enrich(profile,event){
  const skillNames=names(profile);
  return {...event,description:event.description||'',develops_skills:(event.develops_skills||[]).map(g=>({...g,name:skillNames[g.skill_id]||g.skill_id})),prerequisite_details:Object.entries(event.prerequisites||{}).map(([id,required])=>({skill_id:id,name:skillNames[id]||id,required,current:level(profile.effective_skills||{},id)})),gains:(event.expected_gains||event.gains||[]).map(g=>({...g,name:skillNames[g.skill_id]||g.name||g.skill_id}))};
}
export function eventById(profile,id){
  const entry=catalog(profile).find(e=>e.event_id===id),available=(profile.available_steps||[]).find(e=>e.event_id===id),rec=profile.recommendations?.items?.find(e=>e.event_id===id);
  if(!entry&&!available&&!rec)return null;
  const event=enrich(profile,{...entry,...rec,...available,event_id:id});
  const ongoing=history(profile).find(r=>r.event_id===id&&r.status==='in_progress');
  // Only genuine server entries/records can provide an action. Forecast unlocks cannot.
  if(available){event.action=available.action;event.record_id=available.record_id||available.activity_record_id;if(!Object.hasOwn(available,'expected_gains'))delete event.expected_gains;}
  else if(ongoing&&!event.mandatory){event.action='continue';event.record_id=ongoing.record_id;event.can_complete=validLevels(profile.effective_skills)&&!eligibility(profile,event,profile.effective_skills,history(profile),{target:false}).length&&(event.format==='self_paced'||ongoing.date<=profile.as_of_date);}
  else {delete event.action;delete event.record_id;event.can_complete=false;}
  const reasons=validLevels(profile.effective_skills)?eligibility(profile,event,profile.effective_skills):['incomplete_data'];
  return {...event,eligible:!!available,reasons:available?[]:reasons};
}
const unavailable=reason=>({available:false,reason,reasons:[reason],coverage_before:null,coverage_after:null,critical_before:null,critical_after:null,changes:[],unlocks:[]});
function delta(profile,before,after){const skillNames=names(profile);return Object.keys(after).filter(id=>level(after,id)!==level(before,id)).map(id=>({skill_id:id,name:skillNames[id]||id,before:level(before,id),after:level(after,id)}));}
function newlyAvailable(profile,before,after,rows){
  const previous=new Set(catalog(profile).filter(e=>!eligibility(profile,e,before,history(profile)).length).map(e=>e.event_id));
  return catalog(profile).filter(e=>!previous.has(e.event_id)&&!eligibility(profile,e,after,rows).length).map(e=>({...enrich(profile,e),eligible:false,simulated:true,action:undefined,record_id:undefined,can_complete:false}));
}
export function forecast(profile,input){
  const event=typeof input==='string'?eventById(profile,input):eventById(profile,input?.event_id);
  if(!event||!validLevels(profile.effective_skills)||!hasTarget(profile))return unavailable('incomplete_data');
  const ongoing=history(profile).some(r=>r.event_id===event.event_id&&r.status==='in_progress');
  const reasons=eligibility(profile,event,profile.effective_skills,history(profile),{target:!ongoing});
  if(reasons.length)return {...unavailable(reasons[0]),reasons};
  // An entry that would be suitable locally still cannot become an actionable server recommendation.
  if(!event.eligible&&!ongoing)return unavailable('not_available');
  const before={...profile.effective_skills};let after;
  if(Array.isArray(event.expected_gains)){
    after={...before};
    for(const gain of event.expected_gains){if(gain.before!==level(before,gain.skill_id)||!number(gain.after)||gain.after<gain.before||gain.after>5)return unavailable('stale_forecast');after[gain.skill_id]=gain.after;}
  }else after=capped(before,event);
  if(!after)return unavailable('incomplete_data');
  const initial=metrics(profile,before),final=metrics(profile,after);
  const rows=history(profile).filter(r=>!(r.event_id===event.event_id&&r.status==='in_progress')).concat({event_id:event.event_id,status:'completed',date:event.session_date||profile.as_of_date});
  return {available:true,reason:null,reasons:[],coverage_before:initial.coverage,coverage_after:final.coverage,critical_before:initial.critical,critical_after:final.critical,changes:delta(profile,before,after),unlocks:newlyAvailable(profile,before,after,rows)};
}
export function filterEvents(profile,{tab='suitable',search='',format='',duration='',skills=[]}={}){
  let ids=tab==='ongoing'?history(profile).filter(r=>r.status==='in_progress').map(r=>r.event_id):tab==='all'?catalog(profile).filter(e=>!e.mandatory).map(e=>e.event_id):(profile.available_steps||[]).map(e=>e.event_id);
  const query=search.toLocaleLowerCase().trim(),limit=Number(String(duration).replace(/[^\d.]/g,''));
  return [...new Set(ids)].map(id=>eventById(profile,id)).filter(Boolean).filter(e=>!e.mandatory&&(!query||[e.title,e.description,...e.develops_skills.map(g=>g.name)].join(' ').toLocaleLowerCase().includes(query))&&(!format||e.format===format||e.type===format)&&(!limit||e.duration_hours<=limit)&&(!skills.length||skills.some(id=>e.develops_skills.some(g=>g.skill_id===id))));
}
function replay(profile){
  const employee=profile.employee||{};
  if(!employee.last_review_date||!profile.as_of_date||!validLevels(employee.skills))return {available:false,reason:'assessment_unavailable'};
  let levels={...employee.skills};const rows=[],seen=new Set();
  for(const record of ordered(history(profile))){
    if(seen.has(record.record_id))continue;seen.add(record.record_id);
    if(record.status!=='completed'||record.date>profile.as_of_date||!(record.date>employee.last_review_date||(record.date===employee.last_review_date&&record.source==='application')))continue;
    const event=catalog(profile).find(e=>e.event_id===record.event_id),before={...levels},after=event?capped(levels,event):null;
    if(!after)return {available:false,reason:'event_history_unavailable',rows};
    rows.push({record,event,before,after});levels=after;
  }
  return {available:true,base:{...employee.skills},rows,levels};
}
export function skillTimeline(profile,skillId){
  const result=replay(profile),employee=profile.employee||{};
  if(!result.available)return [{kind:'unavailable',date:null,title:'История расчёта недоступна',before:null,after:null,gain:null,source:'unknown',explanation:result.reason}];
  const base=level(result.base,skillId),items=[{kind:'assessment',date:employee.last_review_date,title:'Базовая оценка',before:null,after:base,gain:null,source:'assessment'}];
  for(const {record,event,before,after} of result.rows){if(level(after,skillId)===level(before,skillId))continue;items.push({kind:'activity',date:record.date,title:event.title,record_id:record.record_id,event_id:event.event_id,before:level(before,skillId),after:level(after,skillId),gain:level(after,skillId)-level(before,skillId),source:record.source||'import'});}
  items.push({kind:'current',date:profile.as_of_date,title:'Уровень на дату среза',before:null,after:level(result.levels,skillId),gain:null,source:'calculated'});return items;
}
export function historyResult(profile,recordId){
  const exact=profile.completion_results?.[recordId];if(exact)return {...exact,available:true,source:'completion'};
  const result=replay(profile);if(!result.available)return unavailable(result.reason);
  const step=result.rows.find(r=>r.record.record_id===recordId);
  if(!step)return unavailable('included_in_assessment_or_not_completed');
  const before=hasTarget(profile)?metrics(profile,step.before):{coverage:null,critical:null},after=hasTarget(profile)?metrics(profile,step.after):{coverage:null,critical:null};
  return {available:true,source:'reconstructed',event_id:step.event.event_id,record_id:recordId,title:step.event.title,changes:delta(profile,step.before,step.after),coverage_before:before.coverage,coverage_after:after.coverage,critical_before:before.critical,critical_after:after.critical,unlocks:[],explanation:'Расчёт по текущему каталогу и текущей цели. Историческая цель и прежняя версия каталога не сохранены.'};
}
