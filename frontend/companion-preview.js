// Synthetic, in-memory counterpart of app/companion.py. No storage or network.
import {ApiError} from './api.js';

const defaults={head:'cap_starter',body:'body_starter',accessory:'accessory_none',background:'room_starter'};
const items=[
  ['cap_starter','Без головного убора','head','Базовый образ вашего напарника.','starter',0,'Доступно с самого начала','#F3D49B','sparkles'],
  ['body_starter','Зелёная футболка','body','Первый образ для нового пути.','starter',0,'Доступно с самого начала','#087B5A','shirt'],
  ['accessory_none','Без аксессуара','accessory','Ничего лишнего — только ваш напарник.','starter',0,'Доступно с самого начала','#C6D1CA','circle'],
  ['room_starter','Светлая студия','background','Спокойное место, чтобы планировать следующий шаг.','starter',0,'Доступно с самого начала','#E5F1E9','home'],
  ['cap_spark','Кепка первого шага','head','За первую активность, которая действительно развила навык.','completed_count',1,'Завершить 1 добровольную активность с наградой','#EDBA43','star'],
  ['accessory_notebook','Блокнот открытий','accessory','Сохраняет память о первых заметных изменениях.','gained_levels',2,'Получить суммарно 2 уровня навыков с наградами','#688BC7','book-open'],
  ['body_explorer','Худи исследователя','body','За три разных опыта на вашем пути.','distinct_events',3,'Завершить 3 разные активности с наградами','#5A72B5','shirt'],
  ['accessory_compass','Компас роста','accessory','Пять полученных уровней навыков — уже заметный путь.','gained_levels',5,'Получить суммарно 5 уровней навыков с наградами','#C19645','compass'],
  ['cap_quest','Шапка личного квеста','head','За завершение квеста, который вы выбрали сами.','quest_count',1,'Завершить 1 личный квест с наградой','#BE7254','flag'],
  ['room_horizon','Комната с горизонтом','background','Новый вид за окном отмечает накопленный опыт.','xp',150,'Накопить 150 XP','#B2CFDD','sunrise'],
];
const levels=[[0,'Начало пути'],[60,'Первые шаги'],[150,'Новый ритм'],[300,'Широкий горизонт'],[500,'Длинный путь']];
const badges=[['first_step','Первый шаг','Завершить добровольную активность с приростом навыка после включения достижений.'],['three_steps','Три направления','Завершить три разных добровольных мероприятия с приростом навыков.'],['skill_builder','Рост в деталях','Получить суммарно пять уровней навыков за добровольные активности.'],['personal_quest','Свой выбор','Завершить выбранный личный квест с приростом навыка.']];
const rules=[
  'Участие добровольное: включайте и выключайте достижения в любое время.',
  '20 XP за завершение добровольной активности с реальным ростом навыков и ещё 10 XP за каждый полученный уровень навыка.',
  'Награды начисляются только за действия в приложении после включения. Импортированная история не выдаёт XP.',
  'Обязательные мероприятия, повторы одного выполнения и занятия без прироста навыков не дают XP.',
  'Квест можно заменить или отменить. Сроков, штрафов и потери накопленных XP нет.',
  'Уровень пути — личное достижение; он не заменяет грейд и не влияет на AI-рекомендации.',
];

function tree(profile,catalog){
  const t=profile.trajectory,requirements=t.target.requirements,skillNames=new Map(catalog.skills.map(s=>[s.skill_id,s]));
  const targetSkills=[...t.skills].sort((a,b)=>Number(b.critical)-Number(a.critical)||b.gap-a.gap||a.skill_id.localeCompare(b.skill_id));
  const ids=[...targetSkills.map(s=>s.skill_id),...Object.keys(t.effective_skills).filter(id=>t.effective_skills[id]>0&&!Object.hasOwn(requirements,id)).sort()];
  const total=Object.values(requirements).reduce((a,b)=>a+b,0);
  const branches=ids.map(id=>{
    const current=t.effective_skills[id]||0;
    const activities=profile.available_steps.flatMap(event=>{
      const gain=event.expected_gains.find(g=>g.skill_id===id);if(!gain)return [];
      const after={...t.effective_skills};for(const g of event.expected_gains)after[g.skill_id]=g.after;
      return [{event_id:event.event_id,title:event.title,type:event.type,format:event.format,duration_hours:event.duration_hours,action:event.action,activity_record_id:event.activity_record_id,next_session:event.next_session,before:gain.before,after:gain.after,gap_closed:gain.gap_closed,critical:gain.critical,coverage_after:total?Math.round(10000*Object.entries(requirements).reduce((sum,[sid,required])=>sum+Math.min(after[sid]||0,required),0)/total)/100:null}];
    });
    return {skill_id:id,name:skillNames.get(id)?.name||id,category:skillNames.get(id)?.category||'',current,required:requirements[id]??null,critical:t.target.critical_skills.includes(id),nodes:Array.from({length:5},(_,index)=>{const level=index+1;return {level,status:level<=current?'earned':level===current+1?'next':'locked',event_ids:activities.filter(e=>current<level&&level<=e.after).map(e=>e.event_id)};}),activities};
  });
  return {goal:structuredClone(t.target.goal),goal_source:t.target.source,coverage_pct:t.coverage_pct,critical_gap_count:t.critical_gaps.length,branches,empty_reason:!t.target.goal?'goal_not_set':!total?'target_profile_missing':!profile.available_steps.length?(t.coverage_pct===100?'goal_covered':'no_available_steps'):null};
}

export function createCompanionPreview({getProfile,catalog}){
  let enabled=false,quest=null;const rewards=[],equipped={...defaults};
  function view(){
    const profile=getProfile(),metrics={starter:0,completed_count:0,distinct_events:0,gained_levels:0,quest_count:0,xp:0},earned={},earnedBadges={},seen=new Set();
    for(const reward of rewards){
      seen.add(reward.event_id);metrics.completed_count++;metrics.distinct_events=seen.size;metrics.gained_levels+=reward.gained_levels;metrics.quest_count+=Number(reward.quest_completed);metrics.xp+=reward.xp;
      for(const [id,,,,kind,target] of items)if(kind!=='starter'&&metrics[kind]>=target)earned[id]??=reward.earned_at;
      for(const [id,condition] of Object.entries({first_step:true,three_steps:seen.size>=3,skill_builder:metrics.gained_levels>=5,personal_quest:reward.quest_completed}))if(condition)earnedBadges[id]??=reward.earned_at;
    }
    const wardrobe=items.map(([id,name,slot,description,kind,target,label,color,icon])=>({id,name,slot,description,unlocked:kind==='starter'||Object.hasOwn(earned,id),equipped:equipped[slot]===id,earned_at:earned[id]||null,requirement:{kind,target,current:metrics[kind],label},style:{color,icon}}));
    const locked=wardrobe.filter(i=>!i.unlocked),ratio=i=>(i.requirement.target-i.requirement.current)/i.requirement.target;
    const next_unlock=locked.reduce((best,item)=>!best||ratio(item)<ratio(best)?item:best,null);
    const index=levels.findLastIndex(([minimum])=>metrics.xp>=minimum),next=levels[index+1]?.[0]??null;
    const candidate=quest&&profile.available_steps.find(e=>e.event_id===quest.event_id),event=quest&&catalog.events.find(e=>e.event_id===quest.event_id);
    const status=quest?.completed?'completed':!enabled?'paused':candidate?'active':'unavailable';
    return structuredClone({enabled,xp:metrics.xp,level:index+1,level_name:levels[index][1],level_progress:{current:metrics.xp-levels[index][0],required:next===null?null:next-levels[index][0]},completed_count:metrics.completed_count,skill_levels_gained:metrics.gained_levels,badges:badges.map(([id,title,description])=>({id,title,description,earned:Object.hasOwn(earnedBadges,id),earned_at:earnedBadges[id]||null})),quest:quest?{event_id:quest.event_id,title:event?.title||quest.event_id,status,expected_gains:candidate?.expected_gains||[],unavailable_reasons:status==='unavailable'?['not_available']:[]}:null,recent_rewards:rewards.slice(-10).reverse().map(({record_id,event_id,title,xp,gained_levels,earned_at})=>({record_id,event_id,title,xp,gained_levels,earned_at})),rules,privacy:'Достижения видны только вам. Публичных рейтингов и доступа HR к вашим XP нет.',wardrobe,equipped,tree:tree(profile,catalog),next_unlock});
  }
  return {
    view,
    setEnabled(value){if(typeof value!=='boolean')throw new ApiError('Ожидается значение true или false.',422);enabled=value;return view();},
    chooseQuest(eventId){if(!enabled)throw new ApiError('Сначала включите личные достижения.',409);if(!getProfile().available_steps.some(e=>e.event_id===eventId))throw new ApiError('Выберите доступный шаг, который помогает карьерной цели.',409);if(quest?.event_id!==eventId||quest.completed)quest={event_id:eventId,completed:false};return view();},
    clearQuest(){quest=null;return view();},
    equip(itemId){const item=view().wardrobe.find(i=>i.id===itemId);if(!item)throw new ApiError('Такого предмета нет в гардеробе.',404);if(!item.unlocked)throw new ApiError('Сначала выполните условие открытия предмета.',409);equipped[item.slot]=item.id;return view();},
    award(event,record,changes){
      const gained=changes.reduce((sum,c)=>sum+Math.max(0,c.after-c.before),0),none=reason=>({awarded:false,xp:0,gained_levels:gained,reason});
      if(rewards.some(r=>r.record_id===record.record_id))return none('already_awarded');
      if(!enabled)return none('disabled');if(event.mandatory)return none('mandatory');if(record.source!=='application')return none('imported_history');
      const questCompleted=quest?.event_id===event.event_id&&!quest.completed;if(questCompleted)quest.completed=true;
      if(!gained)return none('no_skill_gain');const xp=20+10*gained;
      rewards.push({record_id:record.record_id,event_id:event.event_id,title:event.title,xp,gained_levels:gained,quest_completed:!!questCompleted,earned_at:record.completed_at||record.date});
      return {awarded:true,xp,gained_levels:gained,reason:'awarded'};
    },
  };
}
