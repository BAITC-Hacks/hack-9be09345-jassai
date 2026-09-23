import {escapeHtml as e} from './ui.js';
import {ApiError,errorMessage} from './api.js';

/** Decode NDJSON across arbitrary UTF-8/chunk boundaries, including a final line. */
export async function readChatStream(response,onEvent,signal){
  if(!response.ok){let body={};try{body=await response.json();}catch{}throw new ApiError(errorMessage(body,response.status),response.status);}
  if(!response.body)throw new Error('Поток ответа недоступен.');
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',terminal=false;
  const line=value=>{if(!value.trim())return;const event=JSON.parse(value);if(!['delta','status','done','error'].includes(event.type))return;if(terminal)return;onEvent(event);if(['done','error'].includes(event.type))terminal=true;};
  try{
    while(true){if(signal?.aborted)throw new DOMException('Остановлено','AbortError');const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done});if(buffer.length>64000)throw new Error('Ответ слишком длинный.');let end;while((end=buffer.indexOf('\n'))!==-1){line(buffer.slice(0,end));buffer=buffer.slice(end+1);}if(done)break;if(terminal){await reader.cancel();break;}}
    if(buffer.trim()&&!terminal)line(buffer);
    if(!terminal)throw new Error('Связь прервалась до завершения ответа.');
  }finally{reader.releaseLock();}
}

const sourceName=source=>({local:'По данным профиля',openai:'AI · OpenAI',nvidia:'AI · NVIDIA',preview:'Учебный пример'})[source]||'Спутник';

export function mountCompanionChat({getCsrf,profile,messages=[],onState=()=>{},onUnauthorized=()=>{},previewAnswer=null}){
  const container=document.querySelector('#companion-chat');if(!container)return null;
  const log=container.querySelector('#chat-messages'),form=container.querySelector('form'),input=form.elements.message,status=container.querySelector('#chat-status'),send=form.querySelector('button');
  const speech=document.querySelector('#mascot-speech-text'),source=document.querySelector('#mascot-speech-source');
  const stop=document.createElement('button');stop.type='button';stop.className='text-button companion-stop';stop.textContent='Остановить ответ';stop.hidden=true;form.after(stop);
  let active=null,disposed=false;
  function render(){
    log.innerHTML=messages.length?messages.slice(-12).map(m=>`<article class="companion-message ${m.role}"><span>${m.role==='user'?'Вы':e(sourceName(m.source))}</span><p>${e(m.content)}</p>${m.incomplete?'<small>Ответ не завершён</small>':''}${m.event_ids?.length?`<div class="card-actions">${m.event_ids.filter(id=>profile.available_steps?.some(a=>a.event_id===id)).map(id=>`<button type="button" class="text-button" data-action="event" data-id="${e(id)}">${e(profile.available_steps.find(a=>a.event_id===id)?.title||id)} →</button>`).join('')}</div>`:''}</article>`).join(''):'<p class="companion-chat-welcome">Расскажите своими словами, что хотите уметь или что пока не получается.</p>';
    log.scrollTop=log.scrollHeight;
  }
  function bubble(text,caption){if(speech)speech.textContent=text;if(source&&caption)source.textContent=caption;}
  async function ask(message,{event_id=null,skill_id=null}={}){
    if(active||disposed)return;message=String(message||'').trim().slice(0,2000);if(!message)return;
    const history=messages.filter(m=>!m.incomplete&&m.content).slice(-6).map(({role,content})=>({role,content}));
    messages.push({role:'user',content:message});const reply={role:'assistant',content:'',source:'local',incomplete:true};messages.push(reply);while(messages.length>24)messages.shift();render();input.value='';
    const controller=new AbortController();active=controller;send.disabled=true;stop.hidden=false;status.textContent='Спутник читает ваш вопрос…';onState('thinking');bubble('Сейчас разберёмся…','Спутник · читает вопрос');
    const start=performance.now();let first=null,terminal=false;
    const timeout=setTimeout(()=>controller.abort('timeout'),10000);
    const receive=event=>{
      if(disposed||active!==controller)return;
      if(event.type==='status'){reply.source=event.source;status.textContent=event.message;return;}
      if(event.type==='delta'){if(first===null){first=performance.now()-start;onState('speaking');}reply.content+=String(event.text||'');bubble(reply.content,sourceName(reply.source));const row=log.lastElementChild;if(row?.querySelector('p')){row.querySelector('p').textContent=reply.content;row.querySelector('span').textContent=sourceName(reply.source);log.scrollTop=log.scrollHeight;}return;}
      terminal=true;
      if(event.type==='error'){reply.incomplete=true;status.textContent=event.message;const text=reply.content||event.message;bubble(text,'Ответ не завершён');if(!reply.content)reply.content=event.message;render();return;}
      reply.incomplete=false;reply.source=event.source;reply.event_ids=event.event_ids||[];
      const timing=first===null?'':` · первый текст ${Math.round(first)} мс`;
      status.textContent=sourceName(event.source)+(event.cached?' · из кэша':'')+timing+(event.source==='local'?' · без вызова AI':event.source==='preview'?'':' · ответ AI, проверяйте прогноз в карточке');
      bubble(reply.content,sourceName(event.source));render();
    };
    try{
      if(previewAnswer){for(const item of previewAnswer(message,{event_id,skill_id}))receive(item);}
      else{const response=await fetch('/api/me/companion/chat',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/x-ndjson','X-CSRF-Token':getCsrf()||''},credentials:'same-origin',cache:'no-store',body:JSON.stringify({message,history,event_id,skill_id}),signal:controller.signal});await readChatStream(response,receive,controller.signal);}
    }catch(error){
      if(disposed)return;
      reply.incomplete=true;
      const reason=controller.signal.reason;
      const text=error.name==='AbortError'?(reason==='timeout'?'Ответ не успел завершиться. Попробуйте вопрос о конкретном навыке.':'Ответ остановлен. Можно задать другой вопрос.'):error.message;
      status.textContent=text;if(!reply.content)reply.content=text;bubble(reply.content,'Ответ не завершён');render();if(error.status===401)onUnauthorized();
    }finally{clearTimeout(timeout);if(active===controller)active=null;if(!disposed){send.disabled=false;stop.hidden=true;onState('idle');if(terminal)input.focus({preventScroll:true});}}
  }
  const submit=event=>{event.preventDefault();event.stopPropagation();ask(input.value);};
  const cancel=()=>active?.abort('user');
  form.addEventListener('submit',submit);stop.addEventListener('click',cancel);render();
  const last=messages.filter(m=>m.role==='assistant').at(-1);if(last)bubble(last.content,sourceName(last.source));
  return {ask,dispose(){disposed=true;active?.abort('navigation');form.removeEventListener('submit',submit);stop.removeEventListener('click',cancel);stop.remove();}};
}
