/** Local Three.js room. The team supplies the character; no mascot is invented here. */
import * as THREE from './vendor/three.module.js';

const DEFAULT_EQUIPMENT={head:'cap_starter',body:'body_starter',accessory:'accessory_none',background:'room_starter'};
const ITEM_SLOTS={cap_starter:'head',cap_spark:'head',cap_quest:'head',body_starter:'body',body_explorer:'body',accessory_none:'accessory',accessory_notebook:'accessory',accessory_compass:'accessory',room_starter:'background',room_horizon:'background'};
const STATES=new Set(['idle','listening','thinking','speaking','celebrate']);
const MATERIALS={skin:'#f1d7aa',green:'#087b5a',greenDark:'#285449',cream:'#f7f3df',ink:'#273d31',yellow:'#edba43',blue:'#5a72b5',notebook:'#688bc7',gold:'#c19645',terra:'#be7254'};
const MODEL_PATH='/static/assets/mascot/character.glb';
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
function material(color,extra={}){return new THREE.MeshStandardMaterial({color,roughness:.72,metalness:0,...extra});}
function mesh(geometry,mat,x=0,y=0,z=0){const item=new THREE.Mesh(geometry,mat);item.position.set(x,y,z);item.castShadow=true;item.receiveShadow=true;return item;}
function sphere(parent,mat,radius,x,y,z,scale=null){const item=mesh(new THREE.SphereGeometry(radius,28,20),mat,x,y,z);if(scale)item.scale.set(...scale);parent.add(item);return item;}
function box(parent,mat,size,x,y,z){const item=mesh(new THREE.BoxGeometry(...size),mat,x,y,z);parent.add(item);return item;}
function cylinder(parent,mat,top,bottom,height,x,y,z){const item=mesh(new THREE.CylinderGeometry(top,bottom,height,40),mat,x,y,z);parent.add(item);return item;}
function capsule(parent,mat,radius,length,x,y,z){const item=mesh(new THREE.CapsuleGeometry(radius,length,8,20),mat,x,y,z);parent.add(item);return item;}
function line(parent,points,color,radius=.009){const curve=new THREE.CatmullRomCurve3(points.map(point=>new THREE.Vector3(...point)));const item=mesh(new THREE.TubeGeometry(curve,20,radius,8,false),material(color));parent.add(item);return item;}

function buildDisplayStand(){
  const group=new THREE.Group(),headSlot=new THREE.Group(),bodySlot=new THREE.Group(),accessorySlot=new THREE.Group(),stand=new THREE.Group();
  headSlot.position.y=1.22;group.add(headSlot,bodySlot,accessorySlot,stand);
  group.userData={headSlot,bodySlot,accessorySlot,stand,shirt:material(MATERIALS.green)};
  return group;
}

function disposeObject(object){object.traverse(child=>{child.geometry?.dispose();if(child.material){for(const mat of Array.isArray(child.material)?child.material:[child.material]){for(const value of Object.values(mat))if(value?.isTexture)value.dispose();mat.dispose();}}});}
function clearGroup(group){for(const child of [...group.children]){group.remove(child);disposeObject(child);}}
function dressDisplay(character,equipment,previewItem){
  const {headSlot,bodySlot,accessorySlot,shirt,stand}=character.userData;
  clearGroup(headSlot);clearGroup(bodySlot);clearGroup(accessorySlot);clearGroup(stand);
  const previewId=typeof previewItem==='string'?previewItem:previewItem?.id,slot=ITEM_SLOTS[previewId];
  if(!previewId||slot==='background'||previewId==='cap_starter'||previewId==='accessory_none')return;
  equipment={...DEFAULT_EQUIPMENT,[slot]:previewId};
  cylinder(stand,material('#b8c5a6'),.035,.05,1.25,0,.67,0);
  cylinder(stand,material('#c5d0b3'),.40,.46,.085,0,.10,0);
  shirt.color.set(equipment.body==='body_explorer'?MATERIALS.blue:MATERIALS.green);
  if(slot==='body'){
    const torso=capsule(bodySlot,shirt.clone(),.43,.58,0,1.28,0);torso.scale.set(1.12,1,.45);
    const left=capsule(bodySlot,shirt.clone(),.17,.22,-.47,1.56,0),right=capsule(bodySlot,shirt.clone(),.17,.22,.47,1.56,0);left.rotation.z=-.65;right.rotation.z=.65;
    line(bodySlot,[[-.40,1.75,0],[0,1.94,0],[.40,1.75,0]],'#9f895d',.024);
    line(bodySlot,[[0,1.94,0],[0,2.07,0],[.09,2.1,0],[.11,2.02,0]],'#9f895d',.019);
  }
  if(equipment.head==='cap_spark'){
    const cap=material(MATERIALS.yellow);
    const crown=mesh(new THREE.SphereGeometry(.54,32,16,0,Math.PI*2,0,Math.PI*.49),cap,0,.24,0);crown.scale.set(1.04,1,.96);headSlot.add(crown);
    const brim=sphere(headSlot,cap,.36,0,.29,.39,[1.12,.10,.80]);brim.rotation.x=.08;
    line(headSlot,[[0,.80,0],[0,.72,.31],[0,.35,.52]],'#b78d29',.009);
  }else if(equipment.head==='cap_quest'){
    const beanie=material(MATERIALS.terra),band=material('#a85d42');
    const crown=mesh(new THREE.SphereGeometry(.55,32,18,0,Math.PI*2,0,Math.PI*.56),beanie,0,.28,0);crown.scale.set(1.035,1.05,.98);headSlot.add(crown);
    const rim=mesh(new THREE.TorusGeometry(.505,.065,10,40),band,0,.25,0);rim.rotation.x=Math.PI/2;headSlot.add(rim);sphere(headSlot,beanie,.10,0,.87,0);
  }
  if(slot==='body'&&equipment.body==='body_explorer'){
    const hoodie=material(MATERIALS.blue),string=material('#e2e5f1');
    const hood=mesh(new THREE.TorusGeometry(.31,.115,14,28,Math.PI*1.15),hoodie,0,1.78,-.055);hood.rotation.z=-Math.PI*.075;hood.rotation.x=.6;bodySlot.add(hood);
    line(bodySlot,[[-.10,1.71,.335],[-.10,1.54,.37]],'#dbe2f5',.012);line(bodySlot,[[.10,1.71,.335],[.10,1.54,.37]],'#dbe2f5',.012);
    const pocket=box(bodySlot,material('#4c64a0'),[.36,.16,.025],0,1.10,.366);pocket.rotation.x=-.05;
    sphere(bodySlot,string,.018,-.10,1.53,.37);sphere(bodySlot,string,.018,.10,1.53,.37);
  }
  if(equipment.accessory==='accessory_notebook'){
    const book=new THREE.Group();book.position.set(0,1.44,.03);book.scale.setScalar(1.8);book.rotation.y=.17;accessorySlot.add(book);
    box(book,material(MATERIALS.notebook),[.36,.48,.10],0,0,0);box(book,material('#f3efd9'),[.30,.43,.104],.02,0,0);box(book,material(MATERIALS.notebook),[.36,.48,.017],0,0,.063);
    line(book,[[-.09,.13,.075],[.10,.13,.075]],'#cfddf1',.009);line(book,[[-.09,.065,.075],[.065,.065,.075]],'#cfddf1',.009);
  }else if(equipment.accessory==='accessory_compass'){
    line(accessorySlot,[[-.16,1.75,.29],[-.19,1.39,.38],[0,1.12,.41],[.19,1.39,.38],[.16,1.75,.29]],'#b59149',.012);
    const outer=mesh(new THREE.CylinderGeometry(.145,.145,.045,32),material(MATERIALS.gold,{metalness:.4,roughness:.4}),0,1.16,.43);outer.rotation.x=Math.PI/2;accessorySlot.add(outer);
    const face=mesh(new THREE.CylinderGeometry(.119,.119,.048,32),material('#f7edcf'),0,1.16,.435);face.rotation.x=Math.PI/2;accessorySlot.add(face);
    const needle=mesh(new THREE.ConeGeometry(.025,.14,3),material('#a44d3c'),0,1.185,.469);needle.rotation.z=-.30;accessorySlot.add(needle);
  }
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
  if(!host)return {update(){},setState(){},dispose(){}};
  let renderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});}catch(_){
    host.innerHTML='<div class="mascot-model-error"><strong>Мастерская в 3D недоступна</strong><p>Браузер не смог запустить WebGL. Древо навыков, гардероб и разговор со спутником продолжают работать.</p></div>';
    return {update(){},setState(){},dispose(){}};
  }
  let disposed=false,raf=0,visible=true,state='idle',stateStart=0,lastFrame=0,previewItem=options.previewItem||null,equipped={...DEFAULT_EQUIPMENT,...options.equipped},yaw=.06,targetYaw=.06,pointerX=0,pointerY=0;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),scene=new THREE.Scene();scene.background=new THREE.Color('#eaf1dd');
  const camera=new THREE.PerspectiveCamera(32,1,.1,100);camera.position.set(3.6,2.7,6.8);camera.lookAt(0,1.13,0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.6));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
  const canvas=renderer.domElement;canvas.tabIndex=0;canvas.setAttribute('role','img');canvas.setAttribute('aria-label','3D-комната и примерочная. Стрелки влево и вправо поворачивают образ; Home возвращает исходный вид.');host.replaceChildren(canvas);
  const ambient=new THREE.HemisphereLight('#ffffe8','#aeb995',2.3);scene.add(ambient);
  const key=new THREE.DirectionalLight('#fff5d7',3.3);key.position.set(-3.5,6,5);key.castShadow=true;key.shadow.mapSize.set(512,512);key.shadow.camera.left=-4;key.shadow.camera.right=4;key.shadow.camera.top=5;key.shadow.camera.bottom=-4;key.shadow.normalBias=.035;key.shadow.bias=-.0006;key.shadow.radius=4;scene.add(key);
  const fill=new THREE.DirectionalLight('#d6eae7',.9);fill.position.set(4,2,1);scene.add(fill);
  const room=buildRoom(),modelRoot=new THREE.Group(),placeholder=buildDisplayStand();scene.add(room,modelRoot);modelRoot.add(placeholder);modelRoot.rotation.y=yaw;
  let model=placeholder,mixer=null,animations={},activeClip=null,externalSlots=null,loadVersion=0,celebrationDots=null,celebrationTimer=0;
  function visualEquipment(){const result={...equipped};const id=typeof previewItem==='string'?previewItem:previewItem?.id,slot=typeof previewItem==='object'?previewItem?.slot:ITEM_SLOTS[id];if(id&&slot&&ITEM_SLOTS[id])result[slot]=id;return result;}
  function applyEquipment(){
    const outfit=visualEquipment();dressDisplay(placeholder,outfit,previewItem);updateRoom(room,outfit,scene);
    if(externalSlots){for(const [name,node] of Object.entries(externalSlots)){if(name.startsWith('item_'))node.visible=Object.values(outfit).includes(name.slice(5));}}
    const note=host.closest('.companion-room')?.querySelector('[data-mascot-model-note]');if(note)note.textContent=model===placeholder?'Модель спутника появится после подключения':'3D-маскот команды · используйте стрелки для поворота';
  }
  function render(){if(!disposed)renderer.render(scene,camera);}
  function resize(){if(disposed)return;const width=Math.max(1,host.clientWidth),height=Math.max(1,host.clientHeight);renderer.setSize(width,height,false);camera.aspect=width/height;camera.position.z=camera.aspect<.8?7.8:6.8;camera.updateProjectionMatrix();render();}
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(host);
  const observer=new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting!==false;if(visible){lastFrame=0;start();}},{threshold:0});observer.observe(host);
  function setState(next){clearTimeout(celebrationTimer);state=STATES.has(next)?next:'idle';stateStart=performance.now();host.dataset.state=state;
    const clip=animations[state]||animations.idle;if(mixer&&clip&&clip!==activeClip){if(activeClip)mixer.clipAction(activeClip).fadeOut(.18);mixer.clipAction(clip).reset().fadeIn(.18).play();activeClip=clip;}
    if(state==='celebrate'){makeCelebration();celebrationTimer=setTimeout(()=>{if(!disposed&&state==='celebrate')setState('idle');},2200);}else removeCelebration();render();start();
  }
  function removeCelebration(){if(celebrationDots){scene.remove(celebrationDots);disposeObject(celebrationDots);celebrationDots=null;}}
  function makeCelebration(){removeCelebration();if(reduced.matches)return;celebrationDots=new THREE.Group();for(let i=0;i<16;i++){const dot=mesh(new THREE.BoxGeometry(.035,.075,.018),material(['#e6b34b','#087b5a','#6a8db4'][i%3]),0,2,0);dot.userData={angle:i/16*Math.PI*2,speed:.6+(i%4)*.15,lift:2.5+(i%5)*.14};celebrationDots.add(dot);}scene.add(celebrationDots);}
  function tick(now){raf=0;if(disposed||!visible||document.hidden)return;if(now-lastFrame<32){raf=requestAnimationFrame(tick);return;}const delta=lastFrame?Math.min((now-lastFrame)/1000,.05):0,last=now/1000;lastFrame=now;
    if(mixer)mixer.update(delta);
    yaw+=(targetYaw-yaw)*.13;modelRoot.rotation.y=yaw;
    if(celebrationDots){const elapsed=(now-stateStart)/1000;celebrationDots.children.forEach((dot,i)=>{const {angle,speed,lift}=dot.userData;dot.position.set(Math.cos(angle)*speed*elapsed,lift+elapsed*.6-elapsed*elapsed*.65,Math.sin(angle)*speed*elapsed);dot.rotation.set(elapsed*3+i,elapsed*2,elapsed*4);});}
    render();if((!reduced.matches&&((mixer&&activeClip)||celebrationDots))||Math.abs(targetYaw-yaw)>.002)raf=requestAnimationFrame(tick);
  }
  function start(){if(!disposed&&!raf&&visible&&!document.hidden)raf=requestAnimationFrame(tick);}
  function pointerMove(event){const rect=canvas.getBoundingClientRect();pointerX=clamp((event.clientX-rect.left)/rect.width*2-1,-1,1);pointerY=clamp((event.clientY-rect.top)/rect.height*2-1,-1,1);if(event.buttons===1&&event.pointerType==='mouse')targetYaw=clamp(targetYaw+(event.movementX||0)*.012,-1.4,1.4);start();}
  function pointerLeave(){pointerX=0;pointerY=0;start();}
  function keyDown(event){if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();targetYaw=clamp(targetYaw+(event.key==='ArrowLeft'?-.22:.22),-1.4,1.4);start();}if(event.key==='Home'){event.preventDefault();targetYaw=.06;start();}}
  function visibility(){if(!document.hidden){lastFrame=0;start();}else if(raf){cancelAnimationFrame(raf);raf=0;}}
  function motionChange(){render();start();}
  canvas.addEventListener('pointermove',pointerMove);canvas.addEventListener('pointerleave',pointerLeave);canvas.addEventListener('keydown',keyDown);document.addEventListener('visibilitychange',visibility);reduced.addEventListener('change',motionChange);
  async function loadModel(url){
    if(!url)return;let resolved;try{resolved=new URL(url,window.location.href);if(resolved.origin!==location.origin||!resolved.pathname.endsWith('.glb'))return;}catch{return;}
    const version=++loadVersion;
    try{const {GLTFLoader}=await import('./vendor/GLTFLoader.js');const gltf=await new GLTFLoader().loadAsync(resolved.href);if(disposed||version!==loadVersion){disposeObject(gltf.scene);return;}
      if(model!==placeholder){modelRoot.remove(model);disposeObject(model);}
      modelRoot.remove(placeholder);model=gltf.scene;
      const bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3()),scale=2.79/(size.y||2.79);model.scale.multiplyScalar(scale);model.position.set(-center.x*scale,-bounds.min.y*scale,-center.z*scale);model.traverse(node=>{if(node.isMesh){node.castShadow=true;node.receiveShadow=true;}});modelRoot.add(model);
      externalSlots={};model.traverse(node=>{if(node.name.startsWith('item_'))externalSlots[node.name]=node;});animations=Object.fromEntries(gltf.animations.map(clip=>[clip.name.toLowerCase(),clip]));mixer=new THREE.AnimationMixer(model);applyEquipment();setState(state);render();
    }catch(_){if(disposed||version!==loadVersion)return;const note=host.closest('.companion-room')?.querySelector('[data-mascot-model-note]');if(note)note.textContent='Модель команды пока недоступна · комната и гардероб работают';}
  }
  function update(next={}){if(disposed)return;if(next.equipped)equipped={...DEFAULT_EQUIPMENT,...next.equipped};if(Object.hasOwn(next,'previewItem'))previewItem=next.previewItem;applyEquipment();if(next.state)setState(next.state);if(next.modelUrl)loadModel(next.modelUrl);render();start();}
  applyEquipment();resize();setState(options.state||'idle');if(options.modelUrl)loadModel(options.modelUrl);
  return {update,setState,dispose(){if(disposed)return;disposed=true;loadVersion++;clearTimeout(celebrationTimer);cancelAnimationFrame(raf);resizeObserver.disconnect();observer.disconnect();canvas.removeEventListener('pointermove',pointerMove);canvas.removeEventListener('pointerleave',pointerLeave);canvas.removeEventListener('keydown',keyDown);document.removeEventListener('visibilitychange',visibility);reduced.removeEventListener('change',motionChange);mixer?.stopAllAction();disposeObject(scene);if(model!==placeholder)disposeObject(placeholder);placeholder.userData.shirt.dispose();renderer.dispose();renderer.forceContextLoss();canvas.remove();}};
}

export const mascotAssetContract={defaultModelUrl:MODEL_PATH,states:[...STATES],equipmentSlots:Object.keys(DEFAULT_EQUIPMENT),itemIds:Object.keys(ITEM_SLOTS)};
