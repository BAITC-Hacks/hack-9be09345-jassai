import test from 'node:test';
import assert from 'node:assert/strict';
import {createApi,ApiError} from '../frontend/api.js';
import {escapeHtml,pct,validRecommendation,sourceLabel} from '../frontend/ui.js';
import {employeeView,recommendationView,settingsView,importResult} from '../frontend/views.js';
import {createPreview} from '../frontend/preview.js';
import {createBackendAdapter,normalizeProfile,normalizeOverview,normalizeRecommendations} from '../frontend/backend.js';

test('Imported strings cannot inject HTML into recommendation cards',()=>{
  const evil='<img src=x onerror=alert(1)>';
  const html=recommendationView({source:'ai',items:[{event_id:'x" onclick="alert(1)',title:evil,factors:[evil,'b','c'],gains:[],format:'self_paced'}]});
  assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('data-id="x" onclick='));
});
test('Recommendations without three factors are not presented as valid cards',()=>{
  assert.equal(validRecommendation({event_id:'x',factors:['a','b']}),false);
  assert.ok(!recommendationView({source:'ai',items:[{event_id:'x',factors:['a','b']}]}).includes('class="card'));
});
test('Fallback and preview cannot claim a successful AI answer',()=>{
  assert.match(sourceLabel({source:'fallback'}),/без AI/);
  assert.match(sourceLabel({source:'preview'}),/Пример/);
  assert.match(sourceLabel({source:'ai',cached:true}),/сохранённый/);
});
test('Unknown coverage is distinct from zero; progress HTML cannot inject styles',()=>{
  assert.equal(pct(null),null);assert.equal(pct(0),0);assert.equal(pct('bad'),null);assert.equal(pct(120),100);
  assert.equal(escapeHtml('"<script>'), '&quot;&lt;script&gt;');
});
test('Settings never render server-returned API secrets',()=>{
  const html=settingsView({providers:{openai:{configured:true,api_key:'SHOULD_NOT_RENDER',model_id:'model'}}});
  assert.ok(!html.includes('SHOULD_NOT_RENDER'));assert.ok(html.includes('type="password"'));
});
test('API keeps credentials same-origin, adds CSRF/idempotency, serializes JSON',async()=>{
  let captured;
  const api=createApi({getCsrf:()=> 'csrf',fetchImpl:async(path,options)=>{captured={path,options};return new Response('{"ok":true}',{status:200});}});
  assert.deepEqual(await api('/api/test',{method:'POST',body:{a:1},idempotencyKey:'stable'}),{ok:true});
  assert.equal(captured.options.credentials,'same-origin');assert.equal(captured.options.headers['X-CSRF-Token'],'csrf');assert.equal(captured.options.headers['Idempotency-Key'],'stable');assert.equal(captured.options.body,'{"a":1}');
});
test('Multipart uploads retain browser boundary; validation details reach the form',async()=>{
  const form=new FormData();form.set('employees.json',new Blob(['{}']),'employees.json');
  const api=createApi({fetchImpl:async(path,options)=>{assert.ok(!options.headers['Content-Type']);assert.equal(options.body,form);return new Response(JSON.stringify({errors:[{field:'id',message:'unknown'}]}),{status:422});}});
  await assert.rejects(()=>api('/api/test',{method:'POST',body:form}),err=>err instanceof ApiError&&err.status===422&&err.details[0].field==='id');
});
test('API times out without silently replacing data with fixtures',async()=>{
  const api=createApi({fetchImpl:async(path,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError'))))});
  await assert.rejects(()=>api('/api/test',{timeout:5}),error=>error.status===408);
});
test('Non-JSON response gives a controlled error',async()=>{
  const api=createApi({fetchImpl:async()=>new Response('<html>server failed</html>',{status:502})});
  await assert.rejects(()=>api('/api/test'),error=>error.status===502&&error.message.includes('формата'));
});
test('HR profile has no employee mutation controls',async()=>{
  const mock=createPreview();const profile=await mock('/api/me');
  const html=employeeView(profile,{readOnly:true});
  assert.ok(!html.includes('data-action="complete"'));assert.ok(!html.includes('data-action="start"'));assert.ok(!html.includes('data-action="goal"'));
});
test('Import errors and conflicting IDs are escaped',()=>{
  const html=importResult({valid:false,errors:[{field:'<script>',message:'<img>'}],conflicts:['<iframe>']});
  assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img>'));assert.ok(!html.includes('<iframe>'));assert.ok(!html.includes('data-action="apply-import"'));
});
test('Preview completion is separate from real API and can refresh cards',async()=>{
  const mock=createPreview();await mock('/api/me/activities',{method:'POST',body:{}});
  const completed=await mock('/api/me/activities/DEMO_RECORD/complete',{method:'POST'});
  const repeated=await mock('/api/me/activities/DEMO_RECORD/complete',{method:'POST'});
  assert.equal(completed.applied,true);assert.equal(repeated.applied,false);
  const rec=await mock('/api/me/recommendations',{method:'POST'});assert.equal(rec.source,'preview');assert.equal(rec.items.length,2);
});

const wireCatalog={skills:[{skill_id:'SK_A',name:'Architecture'}],role_profiles:[{role:'Engineer',grade:'Senior'}],events:[{event_id:'EV_A',title:'Architecture course',format:'self_paced'}]};
const wireProfile={employee:{employee_id:'E1',full_name:'Test',role:'Engineer',grade:'Middle'},as_of_date:'2026-10-01',trajectory:{coverage_pct:50,critical_gaps:[{}],target:{goal:{target_role:'Engineer',target_grade:'Senior'},source:'suggested_next_grade'},skills:[{skill_id:'SK_A',current:2,required:4,critical:true}]},history:[{record_id:'R1',event_id:'EV_A',status:'in_progress',date:'2026-10-01'}],available_steps:[{event_id:'EV_A'}],no_step_reasons:{}};
test('Published backend profile preserves server values and maps goal/history',()=>{
  const result=normalizeProfile(wireProfile,wireCatalog);assert.equal(result.coverage_pct,50);assert.equal(result.goal.source,'suggested');assert.equal(result.history[0].title,'Architecture course');assert.equal(result.history[0].can_complete,true);assert.deepEqual(result.skills,wireProfile.trajectory.skills);
});
test('Backend recommendation facts come from event, not generated numbers',()=>{
  const result=normalizeRecommendations({mode:'ai',recommendations:[{event_id:'EV_A',factors:['one','two','three'],event:{event_id:'EV_A',format:'online',next_session:'2026-10-10',activity_record_id:'R1',expected_gains:[{skill_id:'SK_A',before:2,after:3}]}}]},wireProfile,wireCatalog);
  assert.equal(result.items[0].can_complete,false);assert.equal(result.items[0].record_id,'R1');assert.equal(result.items[0].gains[0].name,'Architecture');assert.equal(result.source,'ai');
});
test('HR adapter preserves denominators/statuses and separates goal absence',()=>{
  const result=normalizeOverview({employees_without_step:[{employee_id:'E1',goal:null,reasons:{goal_not_set:4}}],skill_deficits:[{employees_with_gap:2,target_population:8,gap_pct:25,critical_gaps:1}],participation:[{records:5,statuses:{completed:3}}]});
  assert.equal(result.skill_gaps[0].denominator,8);assert.equal(result.participation[0].completed,3);assert.equal(result.no_next_step[0].reason_message,'Цель не задана');
});
test('Backend adapter uses actual setup/login routes and completion event ID',async()=>{
  const calls=[];const raw=async(path,options={})=>{calls.push({path,...options});if(path==='/api/catalog')return wireCatalog;if(path==='/api/me')return wireProfile;if(path.endsWith('/complete'))return {changes:[{skill_id:'SK_A',before:2,after:3}],profile:wireProfile};return {};};
  const api=createBackendAdapter(raw);await api('/api/setup/bootstrap',{body:{setup_token:'t',username:'hr',password:'test-only'}});assert.equal(calls[0].path,'/api/setup');assert.equal(calls[0].body.token,'t');assert.equal(calls[1].path,'/api/auth/login');
  await api('/api/me');await api('/api/me/activities/R1/complete',{method:'POST',idempotencyKey:'fixed'});const request=calls.at(-1);assert.equal(request.path,'/api/me/activities/EV_A/complete');assert.deepEqual(request.body,{activity_record_id:'R1'});assert.equal(request.idempotencyKey,'fixed');
});
test('Backend multipart uses repeated files and aggregates nested report counts',async()=>{
  const api=createBackendAdapter(async(path,options)=>{assert.equal(options.body.getAll('files').length,2);assert.equal(options.body.get('mode'),'add');return {valid:true,counts:{employees:{added:2},history:{added:3,skipped:1}}};});
  const body=new FormData();body.append('employees.json',new Blob(['{}']),'employees.json');body.append('activity_history.csv',new Blob(['a']),'activity_history.csv');body.set('mode','add');
  const result=await api('/api/hr/import/validate',{body});assert.deepEqual(result.counts,{added:5,updated:0,skipped:1});
});

