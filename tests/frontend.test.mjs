import test from 'node:test';
import assert from 'node:assert/strict';
import {createApi,ApiError} from '../web/api.js';
import {escapeHtml,pct,validRecommendation,sourceLabel} from '../web/ui.js';
import {employeeView,recommendationView,settingsView,importResult} from '../web/views.js';
import {createPreview} from '../web/preview.js';

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
