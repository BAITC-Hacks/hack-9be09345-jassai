import test from 'node:test';
import assert from 'node:assert/strict';
import {readChatStream} from '../frontend/companion-chat.js';

const response=(text,{terminal=true,split=1}={})=>{
  const bytes=new TextEncoder().encode(text);let offset=0;
  return new Response(new ReadableStream({pull(controller){if(offset>=bytes.length){controller.close();return;}controller.enqueue(bytes.slice(offset,offset+split));offset+=split;}}),{headers:{'Content-Type':'application/x-ndjson'}});
};
test('NDJSON keeps Cyrillic intact across single byte boundaries and final no-newline',async()=>{
  const events=[];await readChatStream(response('{"type":"delta","text":"Привет 🌱"}\n{"type":"done","source":"local"}'),item=>events.push(item));
  assert.equal(events[0].text,'Привет 🌱');assert.equal(events[1].type,'done');
});
test('stream interruption is not silently presented as a complete answer',async()=>{
  const events=[];await assert.rejects(readChatStream(response('{"type":"delta","text":"Начало"}\n'),event=>events.push(event)),/прервалась/);assert.equal(events.length,1);
});
test('ignores unknown events and stops after terminal frame',async()=>{
  const events=[];await readChatStream(response('{"type":"heartbeat"}\n{"type":"done"}\n{"type":"delta","text":"late"}\n',{split:512}),item=>events.push(item));assert.deepEqual(events,[{type:'done'}]);
});
test('HTTP auth error keeps status for session reset',async()=>{
  await assert.rejects(readChatStream(new Response('{}',{status:401}),()=>{}),error=>error.status===401);
});
test('provider error is a terminal event, not a parser failure',async()=>{
  const events=[];await readChatStream(response('{"type":"error","code":"busy","message":"Занят"}\n'),e=>events.push(e));assert.equal(events[0].code,'busy');
});
test('abort is observable and stops consumer',async()=>{
  const controller=new AbortController();controller.abort();await assert.rejects(readChatStream(response('{"type":"done"}'),()=>{},controller.signal),error=>error.name==='AbortError');
});
