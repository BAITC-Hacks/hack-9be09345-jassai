import test from 'node:test';
import assert from 'node:assert/strict';
import {companionView,companionCard,companionCompletion} from '../frontend/companion.js';

const profile={goal:{target_role:'Engineer',target_grade:'Senior'},available_steps:[{event_id:'COURSE',title:'Архитектура решений',duration_hours:2}],recommendations:{items:[{event_id:'COURSE'}]}};
const data={enabled:true,level:2,wardrobe:[{id:'body_starter',name:'Зелёная футболка',slot:'body',unlocked:true,equipped:true,requirement:{target:0,current:0,label:'Доступно с самого начала'},style:{color:'#087b5a'}},{id:'cap_spark',name:'Кепка первого шага',slot:'head',unlocked:false,equipped:false,requirement:{target:1,current:0,label:'Завершить 1 активность с наградой'},style:{color:'#edba43'}}],equipped:{body:'body_starter'},next_unlock:{id:'cap_spark',name:'Кепка первого шага',slot:'head',requirement:{target:1,current:0,label:'Завершить 1 активность с наградой'}},tree:{goal:profile.goal,coverage_pct:40,branches:[{skill_id:'ARCH',name:'Архитектура',current:2,required:4,critical:true,nodes:[1,2,3,4,5].map(level=>({level,status:level<3?'earned':level===3?'next':'locked',event_ids:level<=4?['COURSE']:[]})),activities:[{event_id:'COURSE',title:'Архитектура решений',type:'course',duration_hours:2,before:2,after:4,critical:true}]}]}};

test('companion ties one real course to its skill and goal without claiming predicted progress as earned',()=>{
  const html=companionView(data,profile);
  assert.match(html,/Архитектура решений/);assert.match(html,/2 → 4/);assert.match(html,/Engineer · Senior/);
  assert.match(html,/data-action="event" data-id="COURSE"/);assert.match(html,/data-action="companion-ask"[^>]*data-event="COURSE"/);
  assert.match(html,/40% требований покрыто/);assert.ok(!html.includes('100% требований покрыто'));
  assert.match(html,/id="companion-chat-form"/);assert.match(html,/name="message"/);
});

test('locked clothing is previewable but cannot expose an equip action',()=>{
  const html=companionView(data,profile,{tab:'wardrobe',previewItem:'cap_spark'});
  assert.match(html,/data-action="wardrobe-preview" data-id="cap_spark"/);
  assert.ok(!/data-action="wardrobe-equip" data-id="cap_spark"/.test(html));
  assert.match(html,/Примерка:/);assert.match(html,/ещё не открыто/);assert.match(html,/Завершить 1 активность с наградой/);
});

test('earned equipment remains accessible while reward accrual is paused',()=>{
  const html=companionView({...data,enabled:false},profile,{tab:'wardrobe'});
  assert.match(html,/Включить награды/);assert.match(html,/data-action="wardrobe-equip" data-id="body_starter" disabled/);
  assert.match(html,/Гардероб/);assert.match(html,/Древо навыков/);
});

test('skill nodes retain actual levels and future levels are not executable activities',()=>{
  const html=companionView(data,profile,{tab:'tree',selectedSkill:'ARCH'});
  assert.match(html,/Архитектура, уровень 2, освоен/);assert.match(html,/Архитектура, уровень 3, следующий шаг/);
  assert.match(html,/Архитектура, уровень 4, впереди, требование цели/);
  assert.ok(!/data-action="(?:start|complete)"/.test(html));assert.match(html,/data-action="forecast" data-id="COURSE"/);
});

test('untrusted profile, wardrobe, and context questions are escaped',()=>{
  const hostile=structuredClone(data),attack='<img src=x onerror="alert(1)">';
  hostile.tree.branches[0].name=attack;hostile.tree.branches[0].activities[0].title=attack;hostile.wardrobe[0].name=attack;hostile.wardrobe[0].style.color='red;background:url(https://example.com)';
  for(const tab of ['home','tree','wardrobe']){const html=companionView(hostile,profile,{tab});assert.ok(!html.includes('<img'));assert.ok(!html.includes('url(https://example.com)'));assert.ok(html.includes('&lt;img'));}
});

test('quest selection stays reachable for the quest clothing reward and excludes mandatory activities',()=>{
  const html=companionView(data,{...profile,available_steps:[...profile.available_steps,{event_id:'MANDATORY',title:'Mandatory',mandatory:true}]});
  assert.match(html,/id="quest-form"/);assert.match(html,/name="event_id"/);assert.match(html,/<option value="COURSE"/);assert.ok(!html.includes('<option value="MANDATORY"'));
});

test('no profile, no tree, and no goal produce recoverable states rather than made-up progress',()=>{
  assert.match(companionView(null,profile),/Спутник скоро появится/);
  const empty=companionView({...data,tree:{goal:null,coverage_pct:null,branches:[]}},profile,{tab:'tree'});
  assert.match(empty,/Выберите цель развития/);assert.match(empty,/Дерево начинается с ваших навыков/);
  assert.ok(!empty.includes('100%'));assert.ok(!empty.includes('NaN'));
});

test('completion celebrates only actual increases and explicit unlock payloads',()=>{
  assert.equal(companionCompletion({changes:[{skill_id:'ARCH',before:2,after:2}]}),'');
  const html=companionCompletion({changes:[{skill_id:'ARCH',name:'Архитектура',before:2,after:4}]});
  assert.match(html,/Архитектура: 2 → 4/);assert.ok(!html.includes('Открыто:'));
  assert.match(companionCard(data),/href="#companion"/);
});
