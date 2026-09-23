import test from 'node:test';
import assert from 'node:assert/strict';
import {createBackendAdapter} from '../frontend/backend.js';
import {importView,importResult} from '../frontend/views-hr.js';
import {createPreview} from '../frontend/preview.js';

const report={valid:true,batch_id:'validated-batch',counts:{employees:{added:2,updated:0,skipped:1},history:{added:3,updated:0,skipped:0}},errors:[],conflicts:[]};
test('download suffixes are normalized by the four file slots without changing file contents',async()=>{
  const body=new FormData(),names=['employees.json','skills.json','events.json','activity_history.csv'],downloads=['employees (1).json','skills (1).json','events (2).json','activity_history (3).csv'];
  names.forEach((name,index)=>body.append(name,new Blob([`content-${index}`]),downloads[index]));body.set('mode','add');body.set('kind','initial');
  const api=createBackendAdapter(async(path,options)=>{
    assert.equal(path,'/api/hr/import/validate');assert.equal(options.method,'POST');assert.equal(options.body.get('mode'),'add');assert.equal(options.body.get('kind'),null);
    const files=options.body.getAll('files');assert.deepEqual(files.map(file=>file.name),names);assert.deepEqual(await Promise.all(files.map(file=>file.text())),names.map((_,index)=>`content-${index}`));return report;
  });
  await api('/api/hr/import/validate',{method:'POST',body});assert.deepEqual(names.map(name=>body.get(name).name),downloads);
});

test('partial additions skip empty optional slots and retain explicit update mode',async()=>{
  const body=new FormData();body.append('employees.json',new File([],''));body.append('skills.json',new File([],''));body.append('events.json',new File([],''));body.append('activity_history.csv',new Blob(['record_id\nNEW']),'activity_history (3).csv');body.set('mode','update');
  const api=createBackendAdapter(async(_path,options)=>{assert.equal(options.body.getAll('files').length,1);assert.equal(options.body.get('files').name,'activity_history.csv');assert.equal(options.body.get('mode'),'update');return report;});
  await api('/api/hr/import/validate',{method:'POST',body});
});

test('unknown slots keep their real names so server validation can reject unsupported files',async()=>{
  const body=new FormData();body.append('unexpected.json',new Blob(['{}']),'unrecognized (1).json');
  const api=createBackendAdapter(async(_path,options)=>{assert.equal(options.body.get('files').name,'unrecognized (1).json');return {valid:false,counts:{},errors:[{file:'unrecognized (1).json',message:'Unsupported file'}]};});
  const result=await api('/api/hr/import/validate',{body});assert.equal(result.valid,false);assert.ok(!importResult(result).includes('data-action="apply-import"'));
});

test('starter validation is a separate report; application sends only its confirmed batch id',async()=>{
  const calls=[];const api=createBackendAdapter(async(path,options)=>{calls.push({path,...options});return path.endsWith('/starter')?report:{report,employee_ids:['NEW']};});
  const result=await api('/api/hr/import/starter',{method:'POST',body:{}});
  assert.equal(calls.length,1);assert.deepEqual(result.counts,{added:5,updated:0,skipped:1});assert.deepEqual(result.entity_counts,report.counts);assert.equal(result.batch_id,'validated-batch');assert.match(importResult(result),/data-action="apply-import"/);
  const applied=await api('/api/hr/import/apply',{method:'POST',body:{batch_id:result.batch_id,mode:'add',employees:['must-not-send']}});
  assert.equal(calls[1].path,'/api/hr/import/apply');assert.deepEqual(calls[1].body,{batch_id:'validated-batch'});assert.deepEqual(applied.counts,{added:5,updated:0,skipped:1});
});

test('starter conflicts stay visible and cannot expose apply',async()=>{
  const api=createBackendAdapter(async()=>({...report,valid:false,batch_id:undefined,conflicts:['EMP001'],errors:[{message:'Conflicting existing ID EMP001'}]}));
  const result=await api('/api/hr/import/starter',{method:'POST',body:{}}),html=importResult(result);
  assert.match(html,/EMP001/);assert.ok(!html.includes('data-action="apply-import"'));
});

test('additive import explains preservation and renaming without claiming a fixed dataset size',()=>{
  const html=importView(false);assert.match(html,/существующие записи сохраняются/);assert.match(html,/Переименовывать скачанные файлы/);assert.match(html,/value="add">Добавить новые записи/);assert.match(html,/value="update">Обновить существующие по ID/);assert.match(html,/data-action="validate-starter-import"/);assert.ok(!/200|4256|4 256/.test(html));
  assert.ok(!/type="file"[^>]*required/.test(html));assert.equal((importView(true).match(/type="file"[^>]*required/g)||[]).length,4);
});

test('preview rejects bundled import honestly and leaves synthetic data unchanged',async()=>{
  const api=createPreview('hr'),before=await api('/api/hr/overview');
  await assert.rejects(()=>api('/api/hr/import/starter',{method:'POST'}),error=>error.status===409&&/локальному серверу/.test(error.message));
  assert.deepEqual(await api('/api/hr/overview'),before);
});
