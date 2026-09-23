import test from 'node:test';
import assert from 'node:assert/strict';
import {createPreview} from '../frontend/preview.js';
import {hrProfileView,importView} from '../frontend/views-hr.js';
import {forecastView,activityDetail,historyDetail,employeeView} from '../frontend/views.js';

test('HR profile is read-only even when the employee has a completable activity',async()=>{
  const api=createPreview();await api('/api/me/activities',{body:{event_id:'DEMO_DESIGN'}});
  const profile=await api('/api/me');profile.employee.full_name='<img src=x onerror=alert(1)>';
  const html=hrProfileView(profile);
  assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));
  assert.ok(!/data-action="(?:start|complete|goal)"/.test(html));
  assert.ok(html.includes('Просмотр HR'));assert.ok(html.includes('Решения на основе данных'));
});

test('initial import requires four files; additional import accepts any supported subset',()=>{
  const fileInputs=html=>[...html.matchAll(/<input\b[^>]*type="file"[^>]*>/g)].map(match=>match[0]);
  const initial=fileInputs(importView(true)),additional=fileInputs(importView(false));
  assert.equal(initial.length,4);assert.ok(initial.every(input=>/\brequired\b/.test(input)));
  assert.equal(additional.length,4);assert.ok(additional.every(input=>!/\brequired\b/.test(input)));
  for(const name of ['employees.json','skills.json','events.json','activity_history.csv'])assert.ok(additional.some(input=>input.includes(`name="${name}"`)));
});

test('preview bootstrap and import reach loaded HR workspace without falsely configuring AI',async()=>{
  const api=createPreview('setup');assert.equal((await api('/api/setup/status')).setup_required,true);
  await api('/api/setup/bootstrap',{body:{username:'hr',password:'not-a-real-password'}});
  assert.equal((await api('/api/auth/session')).user.role,'hr');assert.equal((await api('/api/setup/status')).dataset_loaded,false);
  const validation=await api('/api/hr/import/validate',{body:new FormData()});assert.equal(validation.valid,true);
  await api('/api/hr/import/apply',{body:{batch_id:validation.batch_id}});
  const status=await api('/api/setup/status');assert.equal(status.setup_required,false);assert.equal(status.dataset_loaded,true);assert.equal(status.ai_status,'not_configured');assert.equal((await api('/api/hr/overview')).employee_count,4);
});

test('locked activity details and predicted unlocks cannot expose a start action',async()=>{
  const profile=await createPreview()('/api/me'),locked=activityDetail(profile,'DEMO_EXPERIMENT'),prediction=forecastView(profile,'DEMO_DESIGN');
  assert.ok(!/data-action="(?:start|complete)"/.test(locked));assert.match(locked,/Пока недоступно/);
  assert.ok(prediction.includes('Продуктовые эксперименты'));assert.ok(prediction.includes('Могут стать доступны'));
  const starts=[...prediction.matchAll(/<button\b[^>]*data-action="start"[^>]*>/g)].map(m=>m[0]);
  assert.equal(starts.length,1);assert.ok(starts[0].includes('DEMO_DESIGN'));assert.ok(!starts[0].includes('DEMO_EXPERIMENT'));
});

test('activity descriptions are escaped in the new detail drawer',async()=>{
  const profile=await createPreview()('/api/me'),evil='<img src=x onerror=alert(1)>';
  for(const list of [profile.catalog_events,profile.available_steps,profile.recommendations.items])list.find(e=>e.event_id==='DEMO_DESIGN').description=evil;
  const html=activityDetail(profile,'DEMO_DESIGN');assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));
});

test('history distinguishes an exact saved receipt from a reconstruction against current data',async()=>{
  const api=createPreview();await api('/api/me/activities',{body:{event_id:'DEMO_DESIGN'}});await api('/api/me/activities/DEMO_RECORD/complete');
  const profile=await api('/api/me'),exact=historyDetail(profile,'DEMO_RECORD');assert.match(exact,/Сохранённый результат/);
  delete profile.completion_results;const reconstructed=historyDetail(profile,'DEMO_RECORD');assert.match(reconstructed,/Расчёт по текущей цели/);assert.match(reconstructed,/Историческая цель и прежняя версия каталога не сохранены/);
});

test('a missing goal shows an explicit next action without invented zero progress',async()=>{
  const api=createPreview('hr'),profile=await api('/api/hr/employees/DEMO_NO_GOAL'),html=employeeView(profile);
  assert.match(html,/Цель пока не выбрана/);assert.ok(html.includes('data-action="goal"'));assert.ok(!html.includes('NaN'));assert.ok(!html.includes('aria-valuenow="0"'));
});
