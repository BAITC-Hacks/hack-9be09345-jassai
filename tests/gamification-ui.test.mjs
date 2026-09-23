import test from 'node:test';
import assert from 'node:assert/strict';
import {gamificationCard,gamificationView,rewardFeedback} from '../frontend/gamification.js';
import {createBackendAdapter,normalizeProfile} from '../frontend/backend.js';
import {employeeView,setupView} from '../frontend/views.js';
import {createPreview} from '../frontend/preview.js';

const progress={enabled:false,xp:0,level:1,level_name:'Первый шаг',level_progress:{current:0,required:100},completed_count:0,skill_levels_gained:0,badges:[{id:'first',title:'Первый шаг',description:'Завершите активность',earned:false,earned_at:null}],quest:null,recent_rewards:[],rules:['20 XP за завершение с приростом'],privacy:'Достижения видны только вам.'};
const profile={available_steps:[{event_id:'EV_OK',title:'Архитектура',duration_hours:2},{event_id:'EV_MAND',title:'Обязательное',mandatory:true}],skill_names:{SK_A:'Архитектура'}};

test('Achievements are opt-in: no quest selection or invented XP while disabled',()=>{
  const html=gamificationView(progress,profile);
  assert.match(html,/data-enabled="true"/);
  assert.match(html,/Достижения выключены/);
  assert.ok(!html.includes('id="quest-form"'));
  assert.ok(!html.includes('value="EV_OK"'));
  assert.match(gamificationCard(progress),/Добровольно, без рейтингов и штрафов/);
  assert.equal(gamificationCard(null),'');
});

test('Quest choices use only non-mandatory available steps and do not start an activity',()=>{
  const html=gamificationView({...progress,enabled:true},profile);
  assert.match(html,/value="EV_OK"/);
  assert.ok(!html.includes('value="EV_MAND"'));
  assert.ok(!html.includes('data-action="start"'));
  assert.match(html,/id="quest-form"/);
  assert.match(html,/data-enabled="false"/);
});

test('Completed, paused and unavailable quests remain understandable and can be cleared',()=>{
  for(const [status,title] of [['completed','Завершён'],['paused','На паузе'],['unavailable','Сейчас недоступен']]){
    const html=gamificationView({...progress,quest:{event_id:'EV_OK',title:'Квест',status,expected_gains:[],unavailable_reasons:status==='unavailable'?['no_target_gain']:[]}},profile);
    assert.ok(html.includes(title));
    assert.match(html,/data-action="quest-clear"/);
    assert.ok(!html.includes('Перейти к активности'));
  }
});

test('Gamification content is escaped across quests, badges, rules and rewards',()=>{
  const evil='<img src=x onerror=alert(1)>';
  const html=gamificationView({...progress,enabled:true,level_name:evil,privacy:evil,rules:[evil],quest:{event_id:'EV_OK',title:evil,status:'active',expected_gains:[],unavailable_reasons:[evil]},badges:[{title:evil,description:evil,earned:true}],recent_rewards:[{title:evil,xp:30,gained_levels:1}]},{available_steps:[{event_id:'x" onclick="alert(1)',title:evil}]});
  assert.ok(!html.includes('<img'));
  assert.match(html,/&lt;img/);
  assert.ok(!html.includes('value="x" onclick='));
});

test('Maximum level avoids infinite progress; XP only appears when the server awarded it',()=>{
  const html=gamificationView({...progress,enabled:true,level:5,level_progress:{current:500,required:null}},profile);
  assert.match(html,/Все уровни открыты/);
  assert.ok(!html.includes('Infinity'));
  assert.ok(!html.includes('NaN'));
  assert.equal(rewardFeedback({awarded:false,xp:999}), '');
  assert.match(rewardFeedback({awarded:true,xp:30,gained_levels:1}),/\+30 XP/);
});

test('HR profile never displays personal gamification even if it is passed to the view',async()=>{
  const employee=await createPreview()('/api/me');
  const html=employeeView(employee,{readOnly:true,gamification:{...progress,enabled:true,level_name:'PRIVATE_PROGRESS'}});
  assert.ok(!html.includes('PRIVATE_PROGRESS'));
  assert.ok(!html.includes('#achievements'));
  assert.ok(!html.includes('data-action="gamification-toggle"'));
});

test('A callable AI module is not presented as a verified provider',async()=>{
  const api=createBackendAdapter(async()=>({ai_configured:true}));
  const state=await api('/api/setup/status');
  assert.equal(state.ai_status,'connected');
  assert.match(setupView(state),/AI-модуль подключён/);
  assert.ok(!setupView(state).includes('Подключение проверено'));
});

const catalog={events:[{event_id:'EV_OK',format:'self_paced',mandatory:false},{event_id:'EV_MAND',format:'self_paced',mandatory:true}],skills:[],role_profiles:[]};
const rawProfile={employee:{},as_of_date:'2026-10-01',history:[{record_id:'OK',event_id:'EV_OK',status:'in_progress'},{record_id:'MAND',event_id:'EV_MAND',status:'in_progress'},{record_id:'UNKNOWN',event_id:'EV_MISSING',status:'in_progress',date:'2026-01-01'}],trajectory:{target:{goal:null},coverage_pct:0,skills:[],critical_gaps:[]},available_steps:[]};

test('Mandatory and unknown activities cannot be completed through history controls',()=>{
  const mapped=normalizeProfile(rawProfile,catalog);
  assert.equal(mapped.history.find(r=>r.record_id==='OK').can_complete,true);
  assert.equal(mapped.history.find(r=>r.record_id==='MAND').can_complete,false);
  assert.equal(mapped.history.find(r=>r.record_id==='UNKNOWN').can_complete,false);
});

test('Completion adapter preserves server rewards and gamification snapshot',async()=>{
  const reward={awarded:true,xp:30,gained_levels:1,reason:'awarded'};
  const api=createBackendAdapter(async path=>path==='/api/catalog'?catalog:path==='/api/me'?rawProfile:{profile:rawProfile,changes:[],reward,gamification:progress});
  await api('/api/me');
  const result=await api('/api/me/activities/OK/complete',{method:'POST',body:{}});
  assert.deepEqual(result.reward,reward);
  assert.deepEqual(result.gamification,progress);
});

test('Gamification API mutations retain methods and explicit boolean opt-in',async()=>{
  const calls=[];
  const api=createBackendAdapter(async(path,options)=>{calls.push({path,...options});return progress;});
  await api('/api/me/gamification',{method:'PATCH',body:{enabled:true}});
  await api('/api/me/gamification/quest',{method:'POST',body:{event_id:'EV_OK'}});
  await api('/api/me/gamification/quest',{method:'DELETE'});
  assert.deepEqual(calls,[{path:'/api/me/gamification',method:'PATCH',body:{enabled:true}},{path:'/api/me/gamification/quest',method:'POST',body:{event_id:'EV_OK'}},{path:'/api/me/gamification/quest',method:'DELETE'}]);
});
