import test from 'node:test';
import assert from 'node:assert/strict';
import {createPreview} from '../frontend/preview.js';
import {createCompanionPreview} from '../frontend/companion-preview.js';

const get=api=>api('/api/me/companion');
const enable=(api,enabled=true)=>api('/api/me/gamification',{method:'PATCH',body:{enabled}});
const equip=(api,item_id)=>api('/api/me/companion/equip',{method:'POST',body:{item_id}});
const quest=(api,event_id)=>api('/api/me/gamification/quest',{method:'POST',body:{event_id}});
const item=(state,id)=>state.wardrobe.find(i=>i.id===id);
async function complete(api,event_id='DEMO_DESIGN'){
  const started=await api('/api/me/activities',{method:'POST',body:{event_id}});
  return api(`/api/me/activities/${started.record.record_id}/complete`,{method:'POST'});
}

test('preview starts with four starter items, imported skill progress and no retroactive XP',async()=>{
  const api=createPreview(),state=await get(api),profile=await api('/api/me');
  assert.equal(state.enabled,false);assert.equal(state.xp,0);assert.equal(state.wardrobe.length,10);
  assert.equal(state.wardrobe.filter(i=>i.unlocked).length,4);
  assert.equal(state.tree.branches.find(b=>b.skill_id==='sql').current,3);
  assert.equal(state.tree.coverage_pct,profile.coverage_pct);
  assert.equal(state.next_unlock.id,'cap_spark');assert.deepEqual(state.recent_rewards,[]);
});

test('preview tree has five real level nodes and excludes unavailable courses',async()=>{
  const api=createPreview(),state=await get(api),profile=await api('/api/me');
  const branch=state.tree.branches.find(b=>b.skill_id==='analytics');
  assert.deepEqual(branch.nodes.map(n=>n.status),['earned','earned','next','locked','locked']);
  assert.ok(branch.nodes[2].event_ids.includes('DEMO_DESIGN'));
  assert.ok(!branch.activities.some(e=>e.event_id==='DEMO_EXPERIMENT'));
  const allowed=new Set(profile.available_steps.map(e=>e.event_id));
  assert.ok(state.tree.branches.flatMap(b=>b.activities).every(e=>allowed.has(e.event_id)));
  assert.equal(branch.activities.find(e=>e.event_id==='DEMO_DESIGN').coverage_after,64.71);
});

test('opt-in rewarded completion opens clothing and completes a selected quest exactly once',async()=>{
  const api=createPreview();await enable(api);await quest(api,'DEMO_DESIGN');
  const result=await complete(api),state=await get(api);
  assert.deepEqual(result.reward,{awarded:true,xp:30,gained_levels:1,reason:'awarded'});
  assert.equal(state.xp,30);assert.equal(state.completed_count,1);assert.equal(state.quest.status,'completed');
  assert.ok(item(state,'cap_spark').unlocked);assert.ok(item(state,'cap_quest').unlocked);
  assert.equal(state.equipped.head,'cap_starter');
  assert.deepEqual(result.gamification,state);
  const repeated=await api('/api/me/activities/DEMO_RECORD/complete',{method:'POST'});
  assert.equal(repeated.already_applied,true);assert.deepEqual(await get(api),state);
});

test('disabled rewards never backfill past completions when re-enabled',async()=>{
  const api=createPreview(),result=await complete(api);
  assert.equal(result.reward.reason,'disabled');assert.equal(result.reward.awarded,false);
  const state=await enable(api);assert.equal(state.xp,0);assert.ok(!item(state,'cap_spark').unlocked);
  assert.equal(state.tree.branches.find(b=>b.skill_id==='analytics').current,3);
});

test('three distinct actual completions open explorer clothing with factual progress',async()=>{
  const api=createPreview();await enable(api);
  for(const id of ['DEMO_DESIGN','DEMO_FEEDBACK','DEMO_MENTOR'])await complete(api,id);
  const state=await get(api);
  assert.equal(state.xp,90);assert.equal(state.skill_levels_gained,3);assert.equal(state.level,2);
  assert.equal(item(state,'body_explorer').requirement.current,3);assert.ok(item(state,'body_explorer').unlocked);
  assert.ok(item(state,'accessory_notebook').unlocked);assert.ok(!item(state,'accessory_compass').unlocked);
});

test('equipment requires unlocked items and survives opt-out and goal changes',async()=>{
  const api=createPreview();await assert.rejects(()=>equip(api,'cap_spark'),e=>e.status===409);
  await assert.rejects(()=>equip(api,'unknown'),e=>e.status===404);
  await enable(api);await complete(api);await equip(api,'cap_spark');await enable(api,false);
  await api('/api/me/goal',{method:'PATCH',body:{target_role:'Product Manager',target_grade:'Senior'}});
  const state=await get(api);assert.equal(state.enabled,false);assert.equal(state.equipped.head,'cap_spark');
  assert.ok(item(state,'cap_spark').unlocked);assert.equal(state.xp,30);
  await equip(api,'cap_starter');assert.equal((await get(api)).equipped.head,'cap_starter');
});

test('quest selection needs opt-in and eligibility, supports pause and cancellation',async()=>{
  const api=createPreview();await assert.rejects(()=>quest(api,'DEMO_DESIGN'),e=>e.status===409);
  await enable(api);await assert.rejects(()=>quest(api,'DEMO_EXPERIMENT'),e=>e.status===409);
  await quest(api,'DEMO_DESIGN');assert.equal((await get(api)).quest.status,'active');
  await enable(api,false);assert.equal((await get(api)).quest.status,'paused');
  await enable(api);assert.equal((await get(api)).quest.status,'active');
  await api('/api/me/gamification/quest',{method:'DELETE'});assert.equal((await get(api)).quest,null);
});

test('a goal change makes a selected quest unavailable without erasing it',async()=>{
  const api=createPreview();await enable(api);await quest(api,'DEMO_DESIGN');
  await api('/api/me/goal',{method:'PATCH',body:null});
  const state=await get(api);assert.equal(state.quest.status,'unavailable');
  assert.equal(state.quest.event_id,'DEMO_DESIGN');assert.equal(state.tree.empty_reason,'goal_not_set');
  assert.equal(state.tree.coverage_pct,null);
});

test('reward pause retains gear but does not grant XP for new activity',async()=>{
  const api=createPreview();await enable(api);await complete(api);await equip(api,'cap_spark');await enable(api,false);
  const result=await complete(api,'DEMO_FEEDBACK');assert.equal(result.reward.reason,'disabled');
  const state=await enable(api);assert.equal(state.xp,30);assert.equal(state.equipped.head,'cap_spark');
});

test('new preview sessions do not share rewards and returned objects are detached',async()=>{
  const api=createPreview();await enable(api);await complete(api);
  const returned=await get(api);returned.wardrobe[0].name='MODIFIED';returned.equipped.head='invented';
  assert.notEqual((await get(api)).wardrobe[0].name,'MODIFIED');
  assert.equal((await get(api)).equipped.head,'cap_starter');
  assert.equal((await get(createPreview())).xp,0);
});

test('HR and anonymous previews cannot access private companion endpoints',async()=>{
  for(const [mode,status] of [['hr',403],['login',401]]){
    const api=createPreview(mode);await assert.rejects(()=>get(api),e=>e.status===status);
    await assert.rejects(()=>equip(api,'body_starter'),e=>e.status===status);
    await assert.rejects(()=>enable(api),e=>e.status===status);
  }
});

test('direct preview ledger rejects imported, mandatory, no-gain and duplicate awards',async()=>{
  const api=createPreview(),normalized=await api('/api/me'),catalog=await api('/api/catalog');
  const store=createCompanionPreview({getProfile:()=>({trajectory:normalized.raw_trajectory,available_steps:normalized.available_steps}),catalog});
  store.setEnabled(true);const event=catalog.events[0],record={record_id:'TEST_RECORD',source:'application',date:'2026-10-01'};
  assert.equal(store.award(event,{...record,source:'import'},[{before:2,after:3}]).reason,'imported_history');
  assert.equal(store.award({...event,mandatory:true},record,[{before:2,after:3}]).reason,'mandatory');
  assert.equal(store.award(event,record,[]).reason,'no_skill_gain');
  assert.equal(store.view().xp,0);
  assert.equal(store.award(event,record,[{before:2,after:3}]).xp,30);
  assert.equal(store.award(event,record,[{before:2,after:3}]).reason,'already_awarded');
  assert.equal(store.view().xp,30);
});

test('preview actions never use a network or AI provider',async()=>{
  const original=globalThis.fetch;globalThis.fetch=()=>{throw new Error('Network forbidden in preview');};
  try{
    const api=createPreview();await get(api);await enable(api);await quest(api,'DEMO_DESIGN');
    await complete(api);await equip(api,'cap_spark');
    await assert.rejects(()=>api('/api/me/companion/chat',{method:'POST',body:{message:'Привет'}}),e=>e.status===404);
  }finally{globalThis.fetch=original;}
});
