/** Local Three.js room. The team supplies the character; no mascot is invented here. */
import * as THREE from './vendor/three.module.js';

const DEFAULT_EQUIPMENT={head:'cap_starter',body:'body_starter',accessory:'accessory_none',background:'room_starter'};
const ITEM_SLOTS={cap_starter:'head',cap_spark:'head',cap_quest:'head',body_starter:'body',body_explorer:'body',accessory_none:'accessory',accessory_notebook:'accessory',accessory_compass:'accessory',room_starter:'background',room_horizon:'background'};
const STATES=new Set(['idle','listening','thinking','speaking','celebrate']);
const MODEL_PATH='/static/assets/mascot/character.glb';
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
function material(color,extra={}){return new THREE.MeshStandardMaterial({color,roughness:.72,metalness:0,...extra});}
function mesh(geometry,mat,x=0,y=0,z=0){const item=new THREE.Mesh(geometry,mat);item.position.set(x,y,z);item.castShadow=true;item.receiveShadow=true;return item;}
function sphere(parent,mat,radius,x,y,z,scale=null){const item=mesh(new THREE.SphereGeometry(radius,28,20),mat,x,y,z);if(scale)item.scale.set(...scale);parent.add(item);return item;}
function box(parent,mat,size,x,y,z){const item=mesh(new THREE.BoxGeometry(...size),mat,x,y,z);parent.add(item);return item;}
function cylinder(parent,mat,top,bottom,height,x,y,z){const item=mesh(new THREE.CylinderGeometry(top,bottom,height,40),mat,x,y,z);parent.add(item);return item;}
function line(parent,points,color,radius=.009){const curve=new THREE.CatmullRomCurve3(points.map(point=>new THREE.Vector3(...point)));const item=mesh(new THREE.TubeGeometry(curve,20,radius,8,false),material(color));parent.add(item);return item;}

function disposeObject(object){
  const geometries=new Set(),materials=new Set(),textures=new Set();
  object.traverse(child=>{if(child.geometry)geometries.add(child.geometry);for(const mat of Array.isArray(child.material)?child.material:child.material?[child.material]:[])materials.add(mat);});
  for(const mat of materials){for(const value of Object.values(mat))if(value?.isTexture)textures.add(value);mat.dispose();}
  for(const texture of textures){texture.dispose();texture.source?.data?.close?.();}
  for(const geometry of geometries)geometry.dispose();
}
/** The shipped GLB has two real clips; other states reuse them without lip-sync claims. */
export function mapMascotAnimations(clips=[]){
  const named=Object.fromEntries(clips.map(clip=>[clip.name.toLowerCase(),clip]));
  const breathe=named.idle_breathe||named.idle||clips[0]||null;
  const look=named.idle_lookaround||breathe;
  return {idle:breathe,idleAlternate:look,listening:named.listening||look,
    thinking:named.thinking||look,speaking:named.speaking||breathe,celebrate:named.celebrate||look};
}

/** Keep the torso on the podium: an asymmetric tail must not move the body axis. */
export function normalizeMascot(model){
  model.updateMatrixWorld(true);
  const bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3());
  const anchor=model.getObjectByName('pelvis')||model.getObjectByName('root');
  const center=anchor?anchor.getWorldPosition(new THREE.Vector3()):bounds.getCenter(new THREE.Vector3());
  const scale=2.79/(size.y||2.79);
  model.scale.multiplyScalar(scale);
  model.position.set(-center.x*scale,.05-bounds.min.y*scale,-center.z*scale);
  model.updateMatrixWorld(true);
  return {scale,height:2.79,bodyCenter:center.toArray()};
}

/** Costume geometry is authored in the GLB rest space, then attached to real bones. */
export function attachIrbisWardrobe(model){
  const bone=name=>model.getObjectByName(name)||model.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(name));
  const head=bone('head'),chest=bone('chest');
  const hand=bone('hand.R')||bone('hand.L');
  if(!head||!chest||!hand)return null;
  const groups={},coats=[];
  model.traverse(node=>{for(const mat of Array.isArray(node.material)?node.material:node.material?[node.material]:[]){
    if(mat.name==='CQ_SnowLeopard_coat'&&!coats.some(entry=>entry.material===mat))coats.push({material:mat,color:mat.color.clone()});
  }});
  function attach(id,bone,build){
    const group=new THREE.Group();group.name='wardrobe_'+id;build(group);model.add(group);
    model.updateMatrixWorld(true);bone.attach(group);groups[id]=group;group.visible=false;
  }
  attach('cap_spark',head,group=>{
    const cap=material('#e3b345');
    const crown=mesh(new THREE.SphereGeometry(.40,32,20,0,Math.PI*2,0,Math.PI/2),cap,0,3.73,.015);
    crown.scale.set(1,.65,.92);group.add(crown);
    const brim=sphere(group,cap,.30,0,3.745,.34,[1.30,.085,.86]);brim.rotation.x=.045;
    line(group,[[0,3.995,.015],[0,3.95,.20],[0,3.75,.38]],'#b5852d',.008);
    sphere(group,material('#c29436'),.032,0,3.995,.015,[1,.55,1]);
  });
  attach('cap_quest',head,group=>{
    const wool=material('#be7254'),band=material('#9b553e');
    const crown=mesh(new THREE.SphereGeometry(.40,32,20,0,Math.PI*2,0,Math.PI*.54),wool,0,3.76,.005);
    crown.scale.set(1,.87,.89);group.add(crown);
    const rim=mesh(new THREE.TorusGeometry(.379,.047,10,48),band,0,3.745,.005);
    rim.rotation.x=Math.PI/2;rim.scale.y=.89;group.add(rim);
    sphere(group,wool,.079,0,4.145,.005);
    for(let index=0;index<16;index++){
      const angle=index/16*Math.PI*2;
      line(group,[[Math.cos(angle)*.385,3.72,.005+Math.sin(angle)*.345],
        [Math.cos(angle)*.385,3.78,.005+Math.sin(angle)*.345]],'#c38468',.005);
    }
  });
  attach('accessory_notebook',hand,group=>{
    const book=new THREE.Group();book.position.set(-.79,1.51,.32);book.rotation.z=-.10;book.rotation.y=-.14;group.add(book);
    const cover=material('#557bb6'),paper=material('#f4ecd7');
    box(book,cover,[.31,.42,.077],0,0,0);box(book,paper,[.267,.375,.079],.012,0,0);
    box(book,cover,[.31,.42,.012],0,0,.047);
    line(book,[[-.095,.11,.055],[.096,.11,.055]],'#e0dbb8',.007);
    line(book,[[-.095,.057,.055],[.055,.057,.055]],'#c9d9ef',.006);
    for(let y=-.13;y<.17;y+=.08)line(book,[[-.155,y,.012],[-.17,y,.052],[-.12,y,.056]],'#d5ba76',.006);
  });
  attach('accessory_compass',chest,group=>{
    line(group,[[-.17,2.82,.23],[-.20,2.63,.37],[0,2.31,.385],[.20,2.63,.37],[.17,2.82,.23]],'#b8954d',.009);
    const outer=mesh(new THREE.CylinderGeometry(.115,.115,.027,40),material('#c7a157',{metalness:.5,roughness:.4}),0,2.32,.395);
    outer.rotation.x=Math.PI/2;group.add(outer);
    const face=mesh(new THREE.CylinderGeometry(.093,.093,.031,40),material('#f2e8c7'),0,2.32,.40);
    face.rotation.x=Math.PI/2;group.add(face);
    const needle=mesh(new THREE.ConeGeometry(.021,.115,3),material('#a54938'),0,2.325,.425);
    needle.rotation.z=-.30;group.add(needle);
  });
  const base=new THREE.Color('#0a4133'),blue=new THREE.Color('#365b98');
  const ratio=new THREE.Color(blue.r/base.r,blue.g/base.g,blue.b/base.b);
  function apply(equipment){
    for(const [id,group] of Object.entries(groups))group.visible=equipment[ITEM_SLOTS[id]]===id;
    for(const entry of coats){entry.material.color.copy(entry.color);if(equipment.body==='body_explorer')entry.material.color.multiply(ratio);}
  }
  return {apply,groups,coats};
}

function buildRoom(){
  const group=new THREE.Group(),floor=material('#dce6ca'),podiumMat=material('#edf1dc'),wall=material('#e4ebd7');
  const floorMesh=box(group,floor,[6,.12,5],0,-.22,0);floorMesh.castShadow=false;
  const backWall=box(group,wall,[6,3.6,.12],0,1.52,-2.25);backWall.castShadow=false;
  const sideWall=box(group,wall,[.12,3.6,5],-2.95,1.52,.19);sideWall.castShadow=false;
  const platform=cylinder(group,podiumMat,1.17,1.23,.19,0,-.055,0);platform.receiveShadow=true;
  const ring=mesh(new THREE.TorusGeometry(1.16,.014,8,72),material('#b7c99d'),0,.047,0);ring.rotation.x=Math.PI/2;group.add(ring);
  const frame=material('#bdcca8'),glass=material('#f8f7d8',{emissive:'#e8efc1',emissiveIntensity:.16});
  const windowGroup=new THREE.Group();windowGroup.position.set(.95,1.85,-2.16);group.add(windowGroup);
  box(windowGroup,frame,[1.51,1.51,.075],0,0,0);const windowFill=box(windowGroup,glass,[1.36,1.36,.08],0,0,.014);box(windowGroup,frame,[.038,1.36,.1],0,0,.07);box(windowGroup,frame,[1.36,.038,.1],0,-.04,.07);
  box(group,material('#a8b59b'),[1.58,.10,.32],.96,1.04,-2.10);
  const desk=material('#c7d4b5');box(group,desk,[1.20,.075,.47],-1.86,.89,-1.47);box(group,desk,[.075,1.06,.36],-2.34,.31,-1.47);box(group,desk,[.075,1.06,.36],-1.38,.31,-1.47);
  const books=[['#839c74',.16,.29],['#debd6e',.13,.36],['#739488',.14,.32]];books.forEach(([color,width,height],i)=>{const book=box(group,material(color),[width,height,.25],-2.22+i*.16,.94+height/2,-1.50);book.rotation.z=i===2?-.12:0;});
  const plant=new THREE.Group();plant.position.set(1.78,-.13,-.87);group.add(plant);cylinder(plant,material('#c4a477'),.26,.20,.42,0,.21,0);cylinder(plant,material('#a58864'),.27,.27,.05,0,.44,0);
  const stem=material('#5e7950');cylinder(plant,stem,.018,.021,.77,0,.79,0);
  [[-.16,.79,0,-.8],[.19,1.04,.01,.8],[-.14,1.25,.01,-.6],[.12,1.4,0,.4]].forEach(([x,y,z,rotation])=>{const leaf=sphere(plant,material(y>1?'#658451':'#779361'),.22,x,y,z,[.60,1,.20]);leaf.rotation.z=rotation;});
  group.userData={floor,wall,windowFill,glass,plant};return group;
}

function updateRoom(room,equipment,scene){
  const horizon=equipment.background==='room_horizon';
  room.userData.floor.color.set(horizon?'#d7e7e2':'#dce6ca');room.userData.wall.color.set(horizon?'#d8e8eb':'#e4ebd7');room.userData.glass.color.set(horizon?'#a5c7db':'#f8f7d8');room.userData.glass.emissive.set(horizon?'#8db6ce':'#e8efc1');scene.background=new THREE.Color(horizon?'#dcecef':'#eaf1dd');
}

/**
 * mountMascot(host, options) returns an independent scene, never writes progress.
 * options: {equipped, previewItem: item|id|null, modelUrl?: same-origin .glb, state}
 * update accepts the same partial options. dispose is required before route replacement.
 */
export function mountMascot(host,options={}){
  const inert=status=>({update(){},setState(){},getState(){return {status,modelLoaded:false};},dispose(){}});
  if(!host)return inert('unmounted');
  let renderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});}
  catch{
    host.dataset.modelState='unsupported';host.setAttribute('aria-busy','false');
    host.innerHTML='<div class="mascot-model-error" role="status"><strong>3D недоступно на этом устройстве</strong><p>Браузер не смог запустить WebGL. Древо навыков, гардероб и разговор со спутником продолжают работать.</p></div>';
    return inert('unsupported');
  }
  let disposed=false,raf=0,visible=true,state='idle',stateStart=0,lastFrame=0;
  let previewItem=options.previewItem||null,equipped={...DEFAULT_EQUIPMENT,...options.equipped};
  let yaw=0,targetYaw=0,loadVersion=0,currentUrl=null,modelStatus='loading';
  let model=null,mixer=null,animations={},activeClip=null,wardrobeAdapter=null,externalSlots={};
  let idleElapsed=0,celebrationDots=null,celebrationTimer=0,userPaused=false,idleMode='auto';
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),scene=new THREE.Scene();
  const camera=new THREE.PerspectiveCamera(32,1,.1,100);
  const room=buildRoom(),modelRoot=new THREE.Group();scene.add(room,modelRoot);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.04;
  const canvas=renderer.domElement;canvas.tabIndex=0;canvas.setAttribute('role','img');
  canvas.setAttribute('aria-label','Ирбис — снежный барс в чапане. Стрелки влево и вправо поворачивают персонажа; Home возвращает исходный вид.');
  const loading=document.createElement('div');loading.className='mascot-model-status';loading.setAttribute('role','status');
  const loadingText=document.createElement('p');loading.append(loadingText);
  const retry=document.createElement('button');retry.type='button';retry.className='button secondary small';retry.textContent='Повторить загрузку';retry.hidden=true;loading.append(retry);
  const controls=document.createElement('div');controls.className='mascot-motion-controls';controls.setAttribute('aria-label','Движения Ирбиса');
  const pause=document.createElement('button');pause.type='button';pause.textContent='Пауза';pause.setAttribute('aria-label','Пауза анимации');pause.setAttribute('aria-pressed','false');
  const movement=document.createElement('button');movement.type='button';movement.textContent='Оглянуться';movement.setAttribute('aria-label','Показать движение: Ирбис оглядывается');controls.append(pause,movement);
  host.replaceChildren(canvas,loading,controls);
  const ambient=new THREE.HemisphereLight('#ffffed','#8da290',1.9);scene.add(ambient);
  const key=new THREE.DirectionalLight('#fff5e6',2.7);key.position.set(-3.5,6,5);key.castShadow=true;
  key.shadow.mapSize.set(512,512);key.shadow.camera.left=-4;key.shadow.camera.right=4;key.shadow.camera.top=5;key.shadow.camera.bottom=-4;
  key.shadow.normalBias=.025;key.shadow.bias=-.0006;key.shadow.radius=4;scene.add(key);
  const fill=new THREE.DirectionalLight('#e1efff',1.0);fill.position.set(4,2,1);scene.add(fill);
  function status(next,text=''){
    modelStatus=next;host.dataset.modelState=next;host.setAttribute('aria-busy',String(next==='loading'));
    loading.hidden=next==='ready';loadingText.textContent=text;retry.hidden=next!=='error';
    controls.hidden=next!=='ready';
    const note=host.closest('.companion-room')?.querySelector('[data-mascot-model-note]');
    if(note)note.textContent=next==='ready'?'Ирбис · перетащите мышью или используйте ← → для поворота':next==='loading'?'Загружаем 3D-модель Ирбиса…':'Древо навыков, гардероб и чат доступны без 3D';
    options.onStatus?.(next);
  }
  function visualEquipment(){
    const result={...equipped},id=typeof previewItem==='string'?previewItem:previewItem?.id;
    if(ITEM_SLOTS[id])result[ITEM_SLOTS[id]]=id;
    return result;
  }
  function applyEquipment(){
    const outfit=visualEquipment();updateRoom(room,outfit,scene);wardrobeAdapter?.apply(outfit);
    for(const [name,node] of Object.entries(externalSlots))node.visible=Object.values(outfit).includes(name.slice(5));
    host.dataset.previewItem=typeof previewItem==='string'?previewItem:previewItem?.id||'';
  }
  function render(){if(!disposed)renderer.render(scene,camera);}
  function resize(){
    if(disposed)return;const width=Math.max(1,host.clientWidth),height=Math.max(1,host.clientHeight);
    renderer.setSize(width,height,false);camera.aspect=width/height;
    const halfFov=Math.tan(THREE.MathUtils.degToRad(camera.fov)/2);
    const distance=Math.max(3.37/(2*halfFov),2.85/(2*halfFov*camera.aspect));
    camera.position.set(distance*.10,1.48+distance*.065,distance);camera.lookAt(.10,1.48,0);
    camera.updateProjectionMatrix();render();
  }
  function playClip(clip){
    if(!mixer||!clip||clip===activeClip)return;
    if(activeClip)mixer.clipAction(activeClip).fadeOut(.35);
    mixer.clipAction(clip).reset().fadeIn(.35).play();activeClip=clip;
    host.dataset.animation=clip.name;
  }
  function updateMotionControls(){
    const paused=userPaused||reduced.matches;host.dataset.motionPaused=String(paused);
    pause.setAttribute('aria-pressed',String(paused));pause.disabled=reduced.matches;
    pause.textContent=reduced.matches?'Без анимации':userPaused?'Продолжить':'Пауза';
    pause.setAttribute('aria-label',reduced.matches?'Анимации отключены в настройках устройства':userPaused?'Продолжить анимацию':'Пауза анимации');
    movement.disabled=paused;movement.textContent=idleMode==='lookaround'?'Спокойно':'Оглянуться';
    movement.setAttribute('aria-label',idleMode==='lookaround'?'Показать спокойное дыхание':'Показать движение: Ирбис оглядывается');
  }
  function setMotion(mode){
    idleMode=['breathe','lookaround'].includes(mode)?mode:'auto';idleElapsed=0;
    if(state==='idle')playClip(idleMode==='lookaround'?animations.idleAlternate:animations.idle);
    updateMotionControls();render();start();
  }
  function setState(next){
    if(disposed)return;clearTimeout(celebrationTimer);state=STATES.has(next)?next:'idle';stateStart=performance.now();idleElapsed=0;host.dataset.state=state;
    playClip(state==='idle'&&idleMode==='lookaround'?animations.idleAlternate:animations[state]||animations.idle);
    if(state==='celebrate'){makeCelebration();celebrationTimer=setTimeout(()=>{if(!disposed&&state==='celebrate')setState('idle');},2200);}
    else removeCelebration();
    render();start();
  }
  function removeCelebration(){if(celebrationDots){scene.remove(celebrationDots);disposeObject(celebrationDots);celebrationDots=null;}}
  function makeCelebration(){
    removeCelebration();if(reduced.matches||userPaused)return;celebrationDots=new THREE.Group();
    for(let index=0;index<16;index++){
      const dot=mesh(new THREE.BoxGeometry(.035,.075,.018),material(['#e6b34b','#087b5a','#6a8db4'][index%3]),0,2,0);
      dot.userData={angle:index/16*Math.PI*2,speed:.6+(index%4)*.15,lift:2.5+(index%5)*.14};celebrationDots.add(dot);
    }
    scene.add(celebrationDots);
  }
  function tick(now){
    raf=0;if(disposed||!visible||document.hidden)return;
    if(now-lastFrame<32){raf=requestAnimationFrame(tick);return;}
    const delta=lastFrame?Math.min((now-lastFrame)/1000,.075):0;lastFrame=now;
    if(mixer&&!reduced.matches&&!userPaused){
      mixer.update(delta);
      if(state==='idle'){
        idleElapsed+=delta;
        const clip=idleMode==='lookaround'?animations.idleAlternate:idleMode==='breathe'?animations.idle:idleElapsed%21<13?animations.idle:animations.idleAlternate;
        playClip(clip);
      }
    }
    yaw=reduced.matches?targetYaw:yaw+(targetYaw-yaw)*.15;modelRoot.rotation.y=yaw;
    if(celebrationDots){
      const elapsed=(now-stateStart)/1000;
      celebrationDots.children.forEach((dot,index)=>{const {angle,speed,lift}=dot.userData;dot.position.set(Math.cos(angle)*speed*elapsed,lift+elapsed*.6-elapsed*elapsed*.65,Math.sin(angle)*speed*elapsed);dot.rotation.set(elapsed*3+index,elapsed*2,elapsed*4);});
    }
    render();
    if((!reduced.matches&&!userPaused&&((mixer&&activeClip)||celebrationDots))||Math.abs(targetYaw-yaw)>.002)raf=requestAnimationFrame(tick);
  }
  function start(){if(!disposed&&!raf&&visible&&!document.hidden)raf=requestAnimationFrame(tick);}
  function pointerMove(event){if(event.buttons===1&&event.pointerType==='mouse'){targetYaw=clamp(targetYaw+(event.movementX||0)*.012,-Math.PI,Math.PI);start();}}
  function keyDown(event){
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();targetYaw=clamp(targetYaw+(event.key==='ArrowLeft'?-.22:.22),-Math.PI,Math.PI);start();}
    if(event.key==='Home'){event.preventDefault();targetYaw=0;start();}
  }
  function visibility(){if(!document.hidden){lastFrame=0;start();}else if(raf){cancelAnimationFrame(raf);raf=0;}}
  function motionChange(){
    if(reduced.matches){removeCelebration();if(mixer){mixer.stopAllAction();activeClip=null;playClip(animations.idle);mixer.setTime(0);}yaw=targetYaw;}
    updateMotionControls();lastFrame=0;render();start();
  }
  const togglePause=()=>{userPaused=!userPaused;if(userPaused)removeCelebration();updateMotionControls();lastFrame=0;render();start();};
  const changeMovement=()=>setMotion(idleMode==='lookaround'?'breathe':'lookaround');
  pause.addEventListener('click',togglePause);movement.addEventListener('click',changeMovement);
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(host);
  const observer=new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting!==false;if(visible){lastFrame=0;start();}else if(raf){cancelAnimationFrame(raf);raf=0;}},{threshold:0});observer.observe(host);
  canvas.addEventListener('pointermove',pointerMove);canvas.addEventListener('keydown',keyDown);
  document.addEventListener('visibilitychange',visibility);reduced.addEventListener('change',motionChange);
  async function loadModel(url){
    if(disposed)return;let resolved;
    try{resolved=new URL(url,location.href);if(resolved.origin!==location.origin||!resolved.pathname.endsWith('.glb'))throw new Error('Invalid model URL');}
    catch{status('error','Не удалось открыть файл модели. Остальные разделы работают.');return;}
    currentUrl=url;const version=++loadVersion;status('loading','Загружаем Ирбиса…');
    try{
      const {GLTFLoader}=await import('./vendor/GLTFLoader.js');
      const gltf=await new GLTFLoader().loadAsync(resolved.href,event=>{
        if(disposed||version!==loadVersion)return;
        const percent=event.total>0?Math.min(99,Math.round(event.loaded/event.total*100)):null;
        loadingText.textContent=percent===null?'Загружаем Ирбиса…':`Загружаем Ирбиса… ${percent}%`;
      });
      if(disposed||version!==loadVersion){disposeObject(gltf.scene);return;}
      mixer?.stopAllAction();if(model){modelRoot.remove(model);disposeObject(model);}
      model=gltf.scene;normalizeMascot(model);
      model.traverse(node=>{if(node.isMesh){node.castShadow=true;node.receiveShadow=true;node.frustumCulled=false;}});
      modelRoot.add(model);wardrobeAdapter=attachIrbisWardrobe(model);
      externalSlots={};model.traverse(node=>{if(node.name.startsWith('item_'))externalSlots[node.name]=node;});
      animations=mapMascotAnimations(gltf.animations);activeClip=null;mixer=new THREE.AnimationMixer(model);
      applyEquipment();setState(state);if(reduced.matches)mixer.setTime(0);
      status('ready');resize();start();
    }catch{
      if(disposed||version!==loadVersion)return;
      status('error','Ирбис не загрузился. Повторите попытку — навыки, награды и чат работают.');
    }
  }
  const retryLoad=()=>{if(currentUrl)loadModel(currentUrl);};retry.addEventListener('click',retryLoad);
  function update(next={}){
    if(disposed)return;
    if(next.equipped)equipped={...DEFAULT_EQUIPMENT,...next.equipped};
    if(Object.hasOwn(next,'previewItem'))previewItem=next.previewItem;
    applyEquipment();status(modelStatus,loadingText.textContent);if(next.state)setState(next.state);
    if(next.modelUrl&&next.modelUrl!==currentUrl)loadModel(next.modelUrl);render();start();
  }
  applyEquipment();updateMotionControls();resize();setState(options.state||'idle');
  if(options.modelUrl)loadModel(options.modelUrl);else status('error','Файл модели пока не подключён. Остальные разделы работают.');
  return {update,setState,setMotion,getState(){return {status:modelStatus,modelLoaded:!!model,animation:activeClip?.name||null,paused:userPaused||reduced.matches,idleMode,equipped:{...equipped},previewItem};},dispose(){
    if(disposed)return;disposed=true;host.dataset.modelState='disposed';loadVersion++;
    clearTimeout(celebrationTimer);cancelAnimationFrame(raf);resizeObserver.disconnect();observer.disconnect();
    canvas.removeEventListener('pointermove',pointerMove);canvas.removeEventListener('keydown',keyDown);retry.removeEventListener('click',retryLoad);
    pause.removeEventListener('click',togglePause);movement.removeEventListener('click',changeMovement);
    document.removeEventListener('visibilitychange',visibility);reduced.removeEventListener('change',motionChange);
    mixer?.stopAllAction();disposeObject(scene);renderer.dispose();renderer.forceContextLoss();canvas.remove();loading.remove();controls.remove();
  }};
}

export const mascotAssetContract={defaultModelUrl:MODEL_PATH,states:[...STATES],equipmentSlots:Object.keys(DEFAULT_EQUIPMENT),itemIds:Object.keys(ITEM_SLOTS)};
