import test from 'node:test';
import assert from 'node:assert/strict';
import {forecast,eventById,filterEvents,skillTimeline,historyResult} from '../frontend/domain.js';
import {normalizeOverview,createBackendAdapter} from '../frontend/backend.js';
import {createPreview} from '../frontend/preview.js';

test('preview forecast matches real fixture completion and unlocks only a simulated event',async()=>{
  const api=createPreview(),profile=await api('/api/me');
  assert.equal(profile.coverage_pct,58.82);
  const result=forecast(profile,'DEMO_DESIGN');
  assert.equal(result.coverage_before,58.82);assert.equal(result.coverage_after,64.71);
  assert.deepEqual(result.changes,[{skill_id:'analytics',name:'Продуктовая аналитика',before:2,after:3}]);
  assert.deepEqual(result.unlocks.map(e=>e.event_id),['DEMO_EXPERIMENT']);
  assert.equal(result.unlocks[0].action,undefined);assert.equal(result.unlocks[0].eligible,false);
  await api('/api/me/activities',{method:'POST',body:{event_id:'DEMO_DESIGN'}});
  const actual=await api('/api/me/activities/DEMO_RECORD/complete',{method:'POST'});
  assert.equal(actual.coverage_after,result.coverage_after);assert.deepEqual(actual.changes,result.changes);
  const after=await api('/api/me');assert.equal(after.coverage_pct,64.71);
  assert.equal(eventById(after,'DEMO_EXPERIMENT').action,'start');
  const duplicate=await api('/api/me/activities/DEMO_RECORD/complete',{method:'POST'});
  assert.equal(duplicate.applied,false);assert.equal((await api('/api/me')).coverage_pct,64.71);
});
test('locked, mandatory and completed events never gain an action from a local forecast',async()=>{
  const p=await createPreview()('/api/me');
  assert.equal(forecast(p,'DEMO_EXPERIMENT').available,false);
  assert.ok(forecast(p,'DEMO_EXPERIMENT').reasons.includes('prerequisites_not_met'));
  assert.equal(eventById(p,'DEMO_EXPERIMENT').action,undefined);
  assert.equal(eventById(p,'DEMO_SQL').action,undefined);
  p.catalog_events.find(e=>e.event_id==='DEMO_EXPERIMENT').mandatory=true;
  assert.ok(!filterEvents(p,{tab:'all'}).some(e=>e.event_id==='DEMO_EXPERIMENT'));
});
test('fallback forecast uses capped gains, never reduces an above-cap skill or exceeds level five',async()=>{
  const p=await createPreview()('/api/me'),event=p.available_steps.find(e=>e.event_id==='DEMO_DESIGN');
  delete event.expected_gains;event.develops_skills=[{skill_id:'analytics',gain:4,max_level:3},{skill_id:'sql',gain:4,max_level:2}];
  let result=forecast(p,event);assert.equal(result.available,true);assert.equal(result.changes.find(s=>s.skill_id==='analytics').after,3);assert.ok(!result.changes.some(s=>s.skill_id==='sql'));
  p.effective_skills.analytics=4;event.develops_skills=[{skill_id:'analytics',gain:4,max_level:5},{skill_id:'leadership',gain:1,max_level:3}];
  result=forecast(p,event);assert.equal(result.changes.find(s=>s.skill_id==='analytics').after,5);
});
test('no target gain and incomplete profile do not fabricate a useful forecast',async()=>{
  const p=await createPreview()('/api/me');p.effective_skills.analytics=4;
  const event=p.available_steps.find(e=>e.event_id==='DEMO_DESIGN');delete event.expected_gains;
  assert.equal(forecast(p,event).available,false);assert.ok(forecast(p,event).reasons.includes('no_target_gain'));
  p.effective_skills=null;const result=forecast(p,event);assert.equal(result.coverage_after,null);assert.equal(result.critical_after,null);
});
test('ongoing events remain visible when a changed goal removes target gain',async()=>{
  const api=createPreview();await api('/api/me/activities',{body:{event_id:'DEMO_DESIGN'}});const p=await api('/api/me');
  p.available_steps=[];p.effective_skills.analytics=4;
  const ongoing=filterEvents(p,{tab:'ongoing'});assert.equal(ongoing[0].record_id,'DEMO_RECORD');assert.equal(ongoing[0].action,'continue');
  assert.equal(filterEvents(p,{tab:'suitable'}).length,0);
});
test('history replay excludes assessment-covered activity and duplicate records, includes same-day application',async()=>{
  const p=await createPreview()('/api/me');const row=p.raw_history.find(r=>r.record_id==='OLD_SQL');p.raw_history.push({...row});
  p.raw_history.push({...row,record_id:'BEFORE',date:'2026-08-15'},{...row,record_id:'SAME_IMPORT',date:'2026-09-01'}, {...row,record_id:'SAME_APP',date:'2026-09-01',source:'application'});
  const timeline=skillTimeline(p,'sql');assert.equal(timeline[0].after,2);
  assert.deepEqual(timeline.filter(s=>s.kind==='activity').map(s=>s.record_id),['SAME_APP','OLD_SQL']);
  assert.equal(timeline.at(-1).after,4);assert.equal(historyResult(p,'BEFORE').available,false);
  const actual=historyResult(p,'OLD_SQL');assert.equal(actual.changes[0].before,3);assert.equal(actual.changes[0].after,4);assert.equal(actual.source,'reconstructed');
});
test('filters use format, duration and skills together without changing eligibility',async()=>{
  const p=await createPreview()('/api/me');const rows=filterEvents(p,{tab:'all',format:'self_paced',duration:'2',skills:['analytics'],search:'данных'});
  assert.deepEqual(rows.map(e=>e.event_id),['DEMO_DESIGN']);assert.equal(rows[0].eligible,true);
});
test('history replay uses backend ASCII ordering for same-day mixed-case record IDs',()=>{
  const profile={
    employee:{skills:{S:1},last_review_date:'2026-09-10'},as_of_date:'2026-10-01',
    goal:{target_role:'Engineer',target_grade:'Senior'},
    raw_trajectory:{target:{requirements:{S:5},critical_skills:['S']}},
    effective_skills:{S:5},skill_names:{S:'Architecture'},
    catalog_events:[
      {event_id:'E_BIG',title:'Big step',develops_skills:[{skill_id:'S',gain:3,max_level:4}]},
      {event_id:'E_SMALL',title:'Small step',develops_skills:[{skill_id:'S',gain:1,max_level:5}]},
    ],
    raw_history:[
      {record_id:'A',event_id:'E_BIG',date:'2026-09-20',status:'completed'},
      {record_id:'a',event_id:'E_SMALL',date:'2026-09-20',status:'completed'},
    ],
  };
  const timeline=skillTimeline(profile,'S');
  assert.deepEqual(timeline.filter(item=>item.kind==='activity').map(item=>[item.record_id,item.before,item.after]),[['A',1,4],['a',4,5]]);
  assert.equal(timeline.at(-1).after,profile.effective_skills.S);
  const result=historyResult(profile,'A');
  assert.deepEqual(result.changes,[{skill_id:'S',name:'Architecture',before:1,after:4}]);
  assert.equal(result.coverage_before,20);assert.equal(result.coverage_after,80);
});
function coverageFixture(total,covered){
  const requirements={},levels={};let remaining=covered;
  for(let i=0;i<Math.ceil(total/5);i++){
    const id=`S${i}`,required=Math.min(5,total-i*5);
    requirements[id]=required;levels[id]=Math.min(required,remaining);remaining-=levels[id];
  }
  const skill=Object.keys(requirements).find(id=>levels[id]<requirements[id]);
  const event={event_id:'E',title:'Step',format:'self_paced',mandatory:false,target_roles:['Engineer'],target_grades:['Middle'],prerequisites:{},upcoming_sessions:[],develops_skills:[{skill_id:skill,gain:1,max_level:requirements[skill]}],expected_gains:[{skill_id:skill,before:levels[skill],after:levels[skill]+1}]};
  return {employee:{role:'Engineer',grade:'Middle'},goal:{target_role:'Engineer',target_grade:'Senior'},as_of_date:'2026-10-01',effective_skills:levels,raw_trajectory:{target:{requirements,critical_skills:[]}},raw_history:[],catalog_events:[event],available_steps:[event]};
}
test('forecast coverage matches Python ties-to-even at .125 and .625 percent',()=>{
  const before=forecast(coverageFixture(32,25),'E');
  assert.equal(before.coverage_before,78.12);assert.equal(before.coverage_after,81.25);
  const after=forecast(coverageFixture(32,12),'E');
  assert.equal(after.coverage_before,37.5);assert.equal(after.coverage_after,40.62);
});
test('forecast rounds the original binary float like Python, not a prematurely scaled value',()=>{
  const result=forecast(coverageFixture(4000,106),'E');
  assert.equal(result.coverage_before,2.65);assert.equal(result.coverage_after,2.67);
});
test('forecast uses authoritative current coverage from the API when provided',()=>{
  const profile=coverageFixture(32,25);profile.coverage_pct=78.12;
  assert.equal(forecast(profile,'E').coverage_before,profile.coverage_pct);
});
test('HR categories separate no goal and goal covered from help and count people once per reason',()=>{
  const goal={target_role:'Analyst',target_grade:'Senior'};
  const r=normalizeOverview({employees_without_step:[{employee_id:'a',goal:null,reasons:{goal_not_set:40}},{employee_id:'b',goal,coverage_pct:100,reasons:{no_target_gain:40}},{employee_id:'c',goal,coverage_pct:70,reasons:{prerequisites_not_met:20,no_available_session:10,mandatory:3}},{employee_id:'d',goal,coverage_pct:50,reasons:{prerequisites_not_met:10}}]});
  assert.equal(r.no_goal_count,1);assert.equal(r.achieved_count,1);assert.equal(r.needs_help_count,2);
  assert.equal(r.help_groups.find(g=>g.code==='prerequisites_not_met').count,2);assert.equal(r.help_groups.length,2);
  assert.deepEqual(r.help_groups.find(g=>g.code==='no_available_session').employee_ids,['c']);
});
test('overview period query reaches actual API and preview filters participation only',async()=>{
  let received;const adapter=createBackendAdapter(async path=>{received=path;return {employees_without_step:[]};});
  const query='/api/hr/overview?date_from=2026-09-20&date_to=2026-10-01';await adapter(query);assert.equal(received,query);
  const api=createPreview('hr'),all=await api('/api/hr/overview'),filtered=await api(query);
  assert.equal(all.participation.reduce((s,r)=>s+r.total,0),2);assert.equal(filtered.participation.reduce((s,r)=>s+r.total,0),0);assert.equal(all.needs_help_count,filtered.needs_help_count);assert.equal(filtered.no_goal_count,1);assert.equal(filtered.achieved_count,1);
});

function receiptFixture(){
  const goal={target_role:'Analyst',target_grade:'Senior'},catalog={skills:[{skill_id:'S',name:'Analysis'}],events:[{event_id:'E',title:'Analysis practice',format:'self_paced'}],role_profiles:[]};
  const before={employee:{employee_id:'P'},as_of_date:'2026-10-01',trajectory:{coverage_pct:50,critical_gaps:[{skill_id:'S'}],target:{goal,requirements:{S:4},critical_skills:['S']},skills:[{skill_id:'S',current:2,required:4}]},history:[{record_id:'R',event_id:'E',status:'in_progress'}],available_steps:[],no_step_reasons:{}};
  const after=structuredClone(before);after.trajectory.coverage_pct=75;after.history[0].status='completed';
  return {catalog,before,after,response:{record:after.history[0],changes:[{skill_id:'S',before:2,after:3}],profile:after}};
}
test('exact completion survives profile refresh with the original goal and cleared receipts on logout',async()=>{
  const f=receiptFixture();let current=f.before;
  const api=createBackendAdapter(async path=>{if(path==='/api/catalog')return f.catalog;if(path==='/api/me')return current;if(path.endsWith('/complete')){current=f.after;return f.response;}return {};});
  await api('/api/me');await api('/api/me/activities/R/complete',{method:'POST'});
  current=structuredClone(f.after);current.trajectory.target.goal={target_role:'Manager',target_grade:'Senior'};
  const refreshed=await api('/api/me'),receipt=historyResult(refreshed,'R');
  assert.equal(receipt.source,'completion');assert.equal(receipt.coverage_before,50);assert.equal(receipt.coverage_after,75);assert.deepEqual(receipt.goal_snapshot,{target_role:'Analyst',target_grade:'Senior'});
  await api('/api/auth/logout');assert.deepEqual((await api('/api/me')).completion_results,{});
});
test('a delayed profile from the previous session cannot restore private adapter state after logout',async()=>{
  const f=receiptFixture();let release,pending=true,mutations=0;
  const api=createBackendAdapter(async path=>{if(path==='/api/catalog')return f.catalog;if(path==='/api/me'){if(pending)return new Promise(resolve=>release=resolve);return f.before;}if(path.endsWith('/complete')){mutations++;return f.response;}return {};});
  const request=api('/api/me');await api('/api/auth/logout');pending=false;release(f.before);await request;
  await assert.rejects(()=>api('/api/me/activities/R/complete',{method:'POST'}),/Запись участия не найдена/);assert.equal(mutations,0);
  assert.deepEqual((await api('/api/me')).completion_results,{});
});
