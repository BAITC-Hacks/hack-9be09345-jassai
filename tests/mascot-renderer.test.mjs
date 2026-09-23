import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import * as THREE from '../frontend/vendor/three.module.js';
import {GLTFLoader} from '../frontend/vendor/GLTFLoader.js';
import {mapMascotAnimations,normalizeMascot,attachIrbisWardrobe} from '../frontend/mascot-renderer.js';

// Parse the actual shipping model without decoding browser-only image bitmaps.
// Geometry, skeleton, materials and animation tracks remain the real GLB data.
async function character(){
  const bytes=await readFile(new URL('../assets/snow_leopard/Irbis_SnowLeopard.glb',import.meta.url));
  const jsonSize=bytes.readUInt32LE(12),json=JSON.parse(bytes.subarray(20,20+jsonSize).toString());
  const binaryOffset=20+jsonSize,binary=bytes.subarray(binaryOffset+8);
  function omitTextures(value){
    for(const key of Object.keys(value)){
      if(/texture$/i.test(key))delete value[key];
      else if(value[key]&&typeof value[key]==='object')omitTextures(value[key]);
    }
  }
  json.materials.forEach(omitTextures);delete json.images;delete json.textures;delete json.samplers;
  const encoded=Buffer.from(JSON.stringify(json)),padding=(4-encoded.length%4)%4;
  const payload=Buffer.concat([encoded,Buffer.alloc(padding,32)]),result=Buffer.alloc(28+payload.length+binary.length);
  result.write('glTF');result.writeUInt32LE(2,4);result.writeUInt32LE(result.length,8);
  result.writeUInt32LE(payload.length,12);result.writeUInt32LE(0x4e4f534a,16);payload.copy(result,20);
  result.writeUInt32LE(binary.length,20+payload.length);result.writeUInt32LE(0x004e4942,24+payload.length);binary.copy(result,28+payload.length);
  return new GLTFLoader().parseAsync(result.buffer.slice(result.byteOffset,result.byteOffset+result.byteLength),'');
}

test('real shipped clips map to idle and the alternate movement without fictional talking animation',async()=>{
  const gltf=await character(),clips=mapMascotAnimations(gltf.animations);
  assert.equal(clips.idle.name,'Idle_Breathe');assert.equal(clips.idleAlternate.name,'Idle_LookAround');
  assert.equal(clips.speaking,clips.idle);assert.equal(clips.thinking,clips.idleAlternate);
  const mixer=new THREE.AnimationMixer(gltf.scene),head=gltf.scene.getObjectByName('head');
  const before=head.quaternion.clone();mixer.clipAction(clips.idleAlternate).play();mixer.update(2);
  assert.ok(before.angleTo(head.quaternion)>0.005,'real look-around moves the head');
});

test('tail does not shift the torso from the podium center and the character is grounded',async()=>{
  const {scene}=await character(),result=normalizeMascot(scene);
  const pelvis=scene.getObjectByName('pelvis').getWorldPosition(new THREE.Vector3());
  assert.ok(Math.abs(pelvis.x)<1e-5);assert.ok(Math.abs(pelvis.z)<1e-5);
  const box=new THREE.Box3().setFromObject(scene);
  assert.ok(Math.abs(box.min.y-.05)<1e-4);assert.ok(Math.abs(box.max.y-box.min.y-2.79)<1e-4);
  assert.ok(result.scale>0&&result.scale<1);
});

test('all unlocked wearable IDs have real geometry or a reversible coat material change',async()=>{
  const {scene}=await character();normalizeMascot(scene);
  const wardrobe=attachIrbisWardrobe(scene);assert.ok(wardrobe,'sanitized GLTF bone names are supported');
  assert.equal(Object.keys(wardrobe.groups).length,4);assert.ok(wardrobe.coats.length);
  const original=wardrobe.coats[0].material.color.clone();
  wardrobe.apply({head:'cap_spark',body:'body_explorer',accessory:'accessory_notebook'});
  assert.equal(wardrobe.groups.cap_spark.visible,true);assert.equal(wardrobe.groups.cap_quest.visible,false);
  assert.equal(wardrobe.groups.accessory_notebook.visible,true);assert.equal(wardrobe.groups.accessory_compass.visible,false);
  assert.notDeepEqual(wardrobe.coats[0].material.color.toArray(),original.toArray());
  assert.equal(wardrobe.groups.cap_spark.parent.name,'head');
  assert.match(wardrobe.groups.accessory_notebook.parent.name,/hand/);
  const capPoint=wardrobe.groups.cap_spark.children[0],before=capPoint.getWorldPosition(new THREE.Vector3());
  scene.getObjectByName('head').rotation.z+=.15;scene.updateMatrixWorld(true);
  assert.ok(before.distanceTo(capPoint.getWorldPosition(new THREE.Vector3()))>.005,'cap follows the animated head bone');
  wardrobe.apply({head:'cap_quest',body:'body_starter',accessory:'accessory_compass'});
  assert.equal(wardrobe.groups.cap_spark.visible,false);assert.equal(wardrobe.groups.cap_quest.visible,true);
  assert.equal(wardrobe.groups.accessory_notebook.visible,false);assert.equal(wardrobe.groups.accessory_compass.visible,true);
  assert.deepEqual(wardrobe.coats[0].material.color.toArray(),original.toArray());
  wardrobe.apply({head:'cap_starter',body:'body_starter',accessory:'accessory_none'});
  assert.ok(Object.values(wardrobe.groups).every(group=>!group.visible));
});

test('unknown models without attachment bones do not invent a successful wardrobe adapter',()=>{
  assert.equal(attachIrbisWardrobe(new THREE.Group()),null);
  assert.equal(mapMascotAnimations([]).idle,null);
});
