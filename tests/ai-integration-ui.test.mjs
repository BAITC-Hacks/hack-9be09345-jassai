import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeRecommendations} from '../frontend/backend.js';
import {recommendationView,settingsView,setupView} from '../frontend/views.js';
import {errorMessage} from '../frontend/api.js';

const wire={status:'ok',mode:'ai',recommendations:[{event_id:'EV_A',reason:'Приоритет 1. Альтернатива EV_B: длительность 2 против 4 ч.',factors:[{type:'goal',text:'Цель'},{type:'skill_gap',text:'Разрыв'},{type:'history',text:'История'}],event:{event_id:'EV_A',title:'Course',format:'self_paced',expected_gains:[]}}]};

test('AI provider reason survives the adapter and appears in an accessible disclosure',()=>{
  const result=normalizeRecommendations(wire,{as_of_date:'2026-10-01'},{skills:[]});
  assert.equal(result.items[0].reason,wire.recommendations[0].reason);
  const html=recommendationView(result);
  assert.match(html,/<details class="recommendation-reason"><summary>/);
  assert.match(html,/Альтернатива EV_B: длительность 2 против 4 ч\./);
});

test('Recommendation explanation from the provider is always escaped',()=>{
  const evil='</p><img src=x onerror=alert(1)>';
  const result=normalizeRecommendations({...wire,recommendations:[{...wire.recommendations[0],reason:evil}]},{as_of_date:'2026-10-01'},{skills:[]});
  const html=recommendationView(result);
  assert.ok(!html.includes('<img'));
  assert.match(html,/&lt;img/);
});

test('Missing HTTP settings show the actual OpenAI launcher setup, without inactive provider forms',()=>{
  const html=settingsView({not_connected:true,ai_status:'not_configured'});
  assert.match(html,/OpenAI через launcher/);
  assert.match(html,/\.\\launcher\.cmd \/configure-ai/);
  assert.match(html,/Ctrl\+C/);
  assert.match(html,/\/disable-ai/);
  assert.ok(!html.includes('NVIDIA'));
  assert.ok(!html.includes('provider-form'));
  assert.ok(!html.includes('ai-policy-form'));
  assert.ok(!html.includes('type="password"'));
  assert.ok(!html.includes('Резерв при быстром отказе'));
});

test('Module connectivity does not claim verified credentials or credits',()=>{
  const html=settingsView({not_connected:true,ai_status:'connected'});
  assert.match(html,/AI-модуль подключён/);
  assert.match(html,/подтверждается успешным подбором рекомендаций/);
  assert.ok(!html.includes('Подключение проверено'));
});

test('Existing HTTP settings keep forms and never render a returned secret',()=>{
  const html=settingsView({providers:{openai:{configured:true,model_id:'model-from-api',api_key:'SECRET_MUST_NOT_RENDER'}}});
  assert.match(html,/provider-form/);
  assert.match(html,/ai-policy-form/);
  assert.match(html,/model-from-api/);
  assert.ok(!html.includes('SECRET_MUST_NOT_RENDER'));
});

test('Setup and missing-key error guide users to the available connection workflow',()=>{
  const setup=setupView({setup_required:false,dataset_loaded:true});
  assert.ok(!setup.includes('NVIDIA'));
  assert.match(setup,/Подключение AI/);
  const message=errorMessage({detail:{code:'ai_not_configured'}},503);
  assert.match(message,/launcher\.cmd \/configure-ai/);
  assert.match(message,/остановить приложение/);
  assert.ok(!message.includes('Настройте его в разделе HR'));
});
