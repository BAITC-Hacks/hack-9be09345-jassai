"""Build the Irbis character in Blender 5.2. Run with Blender --background --python.

All geometry is original, procedural and editable. +Z up, -Y forward.
The reference is a visual guide only and is not embedded in the distributable.
"""
from pathlib import Path
import sys, math, random, json
import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
sys.path.insert(0, str(HERE))
from materials import build_materials
from animation import build_rig_and_actions
from export_character import export_optimized

random.seed(71)
SCENE_NAME = 'IRBIS | character studio'
previous = bpy.data.scenes.get(SCENE_NAME)
if previous:
    bpy.data.scenes.remove(previous)
scene = bpy.data.scenes.new(SCENE_NAME)
bpy.context.window.scene = scene
character = bpy.data.collections.new('IRBIS | skinned character')
studio = bpy.data.collections.new('STUDIO | excluded from GLB')
scene.collection.children.link(character)
scene.collection.children.link(studio)
mats = build_materials(OUT / 'textures')
bindings = []

def move_collection(obj, collection):
    for col in list(obj.users_collection): col.objects.unlink(obj)
    collection.objects.link(obj)

def active(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

def finish(obj, name, material, bone=None):
    obj.name = name
    if material: obj.data.materials.append(mats[material] if isinstance(material, str) else material)
    active(obj)
    if obj.type == 'CURVE': bpy.ops.object.convert(target='MESH')
    obj = bpy.context.object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for poly in obj.data.polygons: poly.use_smooth = True
    move_collection(obj, character)
    if bone is not None: bindings.append((obj, bone))
    return obj

def ellipsoid(name, loc, scale, material, bone, rotation=None, segments=40, rings=24):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=loc)
    obj = bpy.context.object
    obj.scale = scale
    if rotation: obj.rotation_euler = rotation
    return finish(obj, name, material, bone)

def mesh(name, verts, faces, material, bone=None, uv=None):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, [], faces); data.update()
    obj = bpy.data.objects.new(name, data); character.objects.link(obj)
    if uv:
        layer = data.uv_layers.new(name='UVMap')
        for p in data.polygons:
            for li in p.loop_indices: layer.data[li].uv = uv[data.loops[li].vertex_index]
    return finish(obj, name, material, bone)

def curve(name, points, radius, material, bone, radii=None):
    data = bpy.data.curves.new(name, 'CURVE'); data.dimensions='3D'
    data.resolution_u=12; data.bevel_depth=radius; data.bevel_resolution=3
    sp=data.splines.new('BEZIER'); sp.bezier_points.add(len(points)-1)
    for i,(p,co) in enumerate(zip(sp.bezier_points,points)):
        p.co=co; p.handle_left_type=p.handle_right_type='AUTO'
        if radii: p.radius=radii[i]
    ob=bpy.data.objects.new(name,data); character.objects.link(ob)
    return finish(ob,name,material,bone)

def catmull(points, steps=8):
    pts=[Vector(p) for p in points]; out=[]
    for i in range(len(pts)-1):
        a,b,c,d=pts[max(0,i-1)],pts[i],pts[i+1],pts[min(len(pts)-1,i+2)]
        for j in range(steps):
            t=j/steps
            out.append(.5*((2*b)+(-a+c)*t+(2*a-5*b+4*c-d)*t*t+(-a+3*b-3*c+d)*t*t*t))
    return out+[pts[-1]]

def tube(name, points, radii, material, bone, sides=28, steps=6, uv_repeat=1):
    path=catmull(points,steps); vs=[]; uv=[]; faces=[]
    for i,p in enumerate(path):
        tangent=(path[min(i+1,len(path)-1)]-path[max(i-1,0)]).normalized()
        right=tangent.cross(Vector((0,1,0))).normalized()
        if right.length<.1: right=tangent.cross(Vector((1,0,0))).normalized()
        up=tangent.cross(right).normalized()
        index=min(len(radii)-2,i//steps); frac=min(1,(i-index*steps)/steps)
        ra=radii[index]; rb=radii[index+1]
        if not isinstance(ra,tuple): ra=(ra,ra)
        if not isinstance(rb,tuple): rb=(rb,rb)
        r=(ra[0]*(1-frac)+rb[0]*frac,ra[1]*(1-frac)+rb[1]*frac)
        for j in range(sides+1):
            a=2*math.pi*j/sides
            vs.append(tuple(p+right*(math.cos(a)*r[0])+up*(math.sin(a)*r[1])))
            uv.append((j/sides,i/(len(path)-1)*uv_repeat))
    for i in range(len(path)-1):
        for j in range(sides):
            q=i*(sides+1)+j; faces.append((q,q+1,q+sides+2,q+sides+1))
    faces.extend([tuple(range(sides,-1,-1)),tuple((len(path)-1)*(sides+1)+j for j in range(sides+1))])
    return mesh(name,vs,faces,material,bone,uv),path

def weights_height(obj, anchors):
    weights={}
    for v in obj.data.vertices:
        z=v.co.z
        if z<=anchors[0][0]: weights[v.index]={anchors[0][1]:1}; continue
        if z>=anchors[-1][0]: weights[v.index]={anchors[-1][1]:1}; continue
        for (za,ba),(zb,bb) in zip(anchors,anchors[1:]):
            if za<=z<=zb:
                t=(z-za)/(zb-za); weights[v.index]={ba:1-t,bb:t};break
    return weights

def change_binding(obj, weight):
    for i,(o,_) in enumerate(bindings):
        if o==obj: bindings[i]=(obj,weight);return
    bindings.append((obj,weight))

# Sweater and trousers: gently shaped rather than stacked perfect primitives.
ellipsoid('Sweater | body',(0,.018,2.24),(.405,.255,.65),'sweater','spine')
ellipsoid('Sweater | knitted hem',(0,-.008,1.78),(.395,.263,.11),'sweater','pelvis')
ellipsoid('Neck | visible ivory fur',(0,0,2.91),(.235,.213,.25),'muzzle','head')
for k in range(3):
    pts=[(.243*math.cos(a),.218*math.sin(a),2.788+k*.015) for a in [i*2*math.pi/32 for i in range(33)]]
    curve('Sweater | ribbed collar %02d'%k,pts,.013,'sweater','chest')
for x in [i*.021 for i in range(-14,15)]:
    y=-.25*math.sqrt(max(.1,1-(x/.43)**2))-.012
    curve('Sweater | fine cable rib',[(x,y,1.77),(x*.98,y-.008,2.18),(x*.86,y+.013,2.67)],.0026,'sweater','spine')
ellipsoid('Trousers | hip',(0,.05,1.78),(.365,.213,.25),'trousers','pelvis')
for s,side in [(1,'L'),(-1,'R')]:
    leg,path=tube('Trousers | tailored leg '+side,[(s*.213,.015,1.77),(s*.24,.014,1.42),(s*.26,.009,1.04),(s*.266,.005,.66),(s*.27,-.005,.29)],[.205,.185,.148,.137,.13],'trousers','thigh.'+side)
    change_binding(leg,weights_height(leg,[(.29,'shin.'+side),(1.04,'shin.'+side),(1.37,'thigh.'+side)]))
    tube('Trousers | turned cuff '+side,[(s*.27,-.005,.28),(s*.27,-.005,.345)],[.142,.144],'trousers','shin.'+side,sides=32,steps=2)
    curve('Trousers | pressed seam '+side,[(s*.27,-.143,.39),(s*.26,-.147,1.02),(s*.235,-.178,1.6)],.0035,'trousers','thigh.'+side)
    ellipsoid('Paw | foot '+side,(s*.27,-.115,.16),(.202,.315,.16),'fur','foot.'+side)
    for t in range(4):
        ellipsoid('Paw | toe '+side+str(t),(s*.27+(t-1.5)*.094,-.321,.115),(.060,.131,.104),'muzzle','foot.'+side,segments=24,rings=16)
    for t in range(3):
        x=s*.27+(t-1)*.094
        curve('Paw | toe crease '+side+str(t),[(x,-.437,.087),(x,-.428,.139),(x,-.379,.194)],.0028,'mouth','foot.'+side)

# Chapan, open along the front. Panels, lapels and hems have explicit cloth thickness.
coat_rings=[(1.26,.52,.34),(1.34,.515,.336),(1.69,.445,.30),(1.97,.427,.283),(2.29,.443,.285),(2.55,.496,.275),(2.69,.48,.253),(2.82,.255,.19)]
def coat_pos(z,rx,ry,theta,offset=0):
    return ((rx+offset)*math.sin(theta),(ry+offset)*math.cos(theta),z)
N=72; edge=math.pi-.49; verts=[];uv=[];faces=[]
for k,(z,rx,ry) in enumerate(coat_rings):
    for j in range(N+1):
        a=-edge+2*edge*j/N
        verts.append(coat_pos(z,rx,ry,a));uv.append((j/N,z*1.3))
for k in range(len(coat_rings)-1):
    for j in range(N):
        q=k*(N+1)+j;faces.append((q+N+1,q+N+2,q+1,q))
coat=mesh('Chapan | open tailored shell',verts,faces,'coat','spine',uv)
active(coat)
sub=coat.modifiers.new('Tailored curvature','SUBSURF');sub.levels=2
bpy.ops.object.modifier_apply(modifier=sub.name)
solid=coat.modifiers.new('Cloth thickness','SOLIDIFY');solid.thickness=.025
bpy.ops.object.modifier_apply(modifier=solid.name)
change_binding(coat,weights_height(coat,[(1.8,'pelvis'),(2.25,'spine'),(2.72,'chest')]))
for s,side in [(1,'L'),(-1,'R')]:
    vv=[];uu=[];ff=[]
    for k,(z,rx,ry) in enumerate(coat_rings):
        for j in range(7):
            a=s*(edge-.31*j/6)
            vv.append(coat_pos(z,rx,ry,a,.019));uu.append((j/6,(z-1.26)/1.56))
    for k in range(len(coat_rings)-1):
        for j in range(6):
            q=k*7+j;ff.append((q,q+1,q+8,q+7))
    trim=mesh('Chapan | embroidered lapel '+side,vv,ff,'trim','spine',uu)
    active(trim); mod=trim.modifiers.new('Soft lapel','SUBSURF');mod.levels=2;bpy.ops.object.modifier_apply(modifier=mod.name)
    change_binding(trim,weights_height(trim,[(1.8,'pelvis'),(2.25,'spine'),(2.72,'chest')]))
    for margin in [0,.31]:
        ob=curve('Chapan | lapel gold piping '+side+str(margin),[coat_pos(z,rx,ry,s*(edge-margin),.024) for z,rx,ry in coat_rings],.008,'gold','spine')
        change_binding(ob,weights_height(ob,[(1.8,'pelvis'),(2.25,'spine'),(2.72,'chest')]))
    sleeve,pa=tube('Chapan | sleeve '+side,[(s*.33,.015,2.59),(s*.48,.01,2.59),(s*.64,0,2.43),(s*.76,-.025,2.18),(s*.75,-.13,1.94),(s*.75,-.19,1.83)],[.17,.214,.20,.181,.155,.155],'coat','upper_arm.'+side,steps=6)
    change_binding(sleeve,weights_height(sleeve,[(1.85,'forearm.'+side),(2.14,'forearm.'+side),(2.4,'upper_arm.'+side)]))
    cuff,pa=tube('Chapan | embroidered cuff '+side,[(s*.75,-.15,1.94),(s*.75,-.19,1.83)],[.169,.17],'trim','forearm.'+side,steps=3)
    for loop in cuff.data.uv_layers.active.data:
        u,v=loop.uv;loop.uv=(v,u*.72)
    for z,y in [(1.94,-.15),(1.83,-.19)]:
        curve('Chapan | cuff piping '+side,[(s*.75+.174*math.cos(a),y+.147*math.sin(a),z-.042*math.sin(a)) for a in [i*2*math.pi/32 for i in range(33)]],.006,'gold','forearm.'+side)
    ellipsoid('Paw | palm '+side,(s*.754,-.23,1.668),(.135,.109,.198),'fur','hand.'+side,rotation=(0,s*.08,0))
    for t in range(4):
        x=s*.754+(t-1.5)*.057
        ellipsoid('Paw | rounded finger '+side+str(t),(x,-.251,1.53+abs(t-1.5)*.02),(.037,.070,.092),'fur','hand.'+side,segments=24,rings=16)
    ellipsoid('Paw | thumb '+side,(s*.625,-.257,1.68),(.064,.078,.112),'muzzle','hand.'+side,rotation=(0,s*.40,0),segments=24,rings=16)

# Embroidered lower hem follows the actual jacket surface.
vv=[];uu=[];ff=[]
for k,z in enumerate([1.279,1.335,1.395]):
    for j in range(N+1):
        a=-edge+2*edge*j/N
        vv.append(coat_pos(z,.519-(z-1.279)*.16,.345-(z-1.279)*.10,a,.012));uu.append((k/2,j/N*1.8))
for k in range(2):
    for j in range(N):
        q=k*(N+1)+j;ff.append((q,q+1,q+N+2,q+N+1))
mesh('Chapan | embroidered hem',vv,ff,'trim','pelvis',uu)
for z in [1.275,1.399]:
    curve('Chapan | lower gold border', [coat_pos(z,.519-(z-1.279)*.16,.345-(z-1.279)*.10,-edge+2*edge*j/64,.019) for j in range(65)],.007,'gold','pelvis')

# Thick, expressive snow-leopard tail: six deforming segments.
tail_points=[(0,.30,1.55),(.15,.55,1.2),(.45,.67,.86),(.88,.57,.74),(1.25,.45,.91),(1.48,.35,1.25),(1.46,.27,1.6)]
tail,path=tube('Tail | long snow leopard plume',tail_points,[.12,.145,.168,.177,.179,.173,.11],'fur',None,sides=32,steps=9,uv_repeat=1.2)
ellipsoid('Tail | rounded plush tip',(1.46,.27,1.56),(.141,.139,.164),'fur','tail.06')
tail_weights={}
for v in tail.data.vertices:
    row=v.index//33; t=row/9
    # Smooth crossfade around each joint, clamped to the six available bones.
    u=max(0,min(5,t-.5)); a=int(u);f=u-a
    tail_weights[v.index]={'tail.%02d'%(a+1):1-f}
    if f>0:tail_weights[v.index]['tail.%02d'%(min(5,a+1)+1)]=f
bindings.append((tail,tail_weights))

# Head proportions and face. The brow, cheeks and jaw are separate editable forms.
head=ellipsoid('Head | snow leopard',(0,-.012,3.352),(.508,.381,.551),'fur','head',segments=64,rings=40)
for v in head.data.vertices:
    zn=(v.co.z-3.352)/.551
    v.co.x*=1+.075*math.exp(-((zn+.28)/.28)**2)-.07*max(0,-zn)
ellipsoid('Face | soft chin',(0,-.29,3.027),(.279,.188,.17),'muzzle','head')
for s,side in [(1,'L'),(-1,'R')]:
    ellipsoid('Face | cheek '+side,(s*.354,-.171,3.185),(.176,.175,.235),'fur','head',rotation=(0,s*.16,s*.08))
    ellipsoid('Ear | outer '+side,(s*.401,.002,3.735),(.184,.108,.241),'fur','ear.'+side,rotation=(0,s*.25,0))
    ellipsoid('Ear | velvet rim '+side,(s*.417,-.09,3.75),(.130,.035,.175),'mouth','ear.'+side,rotation=(0,s*.25,0))
    ellipsoid('Ear | inner ivory '+side,(s*.417,-.12,3.746),(.101,.024,.141),'inner_ear','ear.'+side,rotation=(0,s*.25,0))
    ellipsoid('Ear | down '+side,(s*.411,-.137,3.715),(.065,.011,.073),'muzzle','ear.'+side)
    # Eye socket stays on the head while the visible eye compresses into a closed line.
    ellipsoid('Eye | dark almond rim '+side,(s*.211,-.329,3.427),(.161,.080,.162),'mouth','eye.'+side,rotation=(0,s*.09,s*.07))
    ellipsoid('Eye | warm sclera '+side,(s*.211,-.345,3.428),(.148,.073,.150),'eye_white','eye.'+side)
    ellipsoid('Eye | jade iris '+side,(s*.199,-.408,3.423),(.093,.025,.111),'iris','eye.'+side,segments=48,rings=28)
    ellipsoid('Eye | pupil '+side,(s*.199,-.429,3.426),(.052,.014,.077),'pupil','eye.'+side,segments=40,rings=24)
    ellipsoid('Eye | catchlight '+side,(s*.199-.029,-.443,3.471),(.022,.009,.024),'eye_white','eye.'+side,segments=20,rings=12)
    ellipsoid('Eye | lower glint '+side,(s*.199+.023,-.442,3.395),(.008,.005,.010),'eye_white','eye.'+side,segments=16,rings=10)
    curve('Face | upper eyelid '+side,[(s*.068,-.367,3.468),(s*.13,-.376,3.554),(s*.232,-.345,3.585),(s*.338,-.295,3.526)],.022,'muzzle','head',radii=[.45,1,1,.4])
    curve('Face | expressive eyebrow '+side,[(s*.070,-.326,3.638),(s*.16,-.339,3.672),(s*.269,-.283,3.65),(s*.34,-.215,3.596)],.025,'mouth','head',radii=[.35,1,.85,.15])
    ellipsoid('Muzzle | whisker pad '+side,(s*.124,-.391,3.134),(.172,.164,.135),'muzzle','head')
    # Fine freckles and gently tapered whiskers, never painted across the eyes.
    for i,(x,z) in enumerate([(.15,3.165),(.215,3.13),(.137,3.099),(.23,3.086),(.267,3.135)]):
        y=-.526 + (x-.12)*.20
        ellipsoid('Muzzle | whisker follicle '+side+str(i),(s*x,y,z),(.008,.004,.007),'mouth','head',segments=12,rings=8)
    for i in range(4):
        z=3.102+i*.036
        curve('Whisker | '+side+str(i),[(s*.22,-.51,z),(s*.40,-.535,z+.025*(i-1)),(s*(.65+.025*i),-.49,z+.055*(i-1))],.0021,'whisker','head',radii=[.8,.55,.06])
    curve('Face | smiling mouth '+side,[(0,-.548,3.097),(s*.085,-.540,3.047),(s*.174,-.505,3.048),(s*.232,-.447,3.095)],.008,'mouth','head',radii=[1,1,.8,.2])

# Rounded triangular nose, with a soft bevel and two nostrils.
verts=[(-.118,-.523,3.247),(.118,-.523,3.247),(.07,-.56,3.179),(0,-.571,3.135),(-.07,-.56,3.179),(-.093,-.584,3.233),(.093,-.584,3.233),(0,-.607,3.166)]
nose=mesh('Nose | rounded rose charcoal leather',verts,[(0,1,6,5),(5,6,7),(1,2,3,7,6),(3,4,0,5,7),(0,4,3,2,1)],'nose','head')
active(nose);mod=nose.modifiers.new('Soft nose edges','BEVEL');mod.width=.025;mod.segments=3;bpy.ops.object.modifier_apply(modifier=mod.name)
mod=nose.modifiers.new('Nose surface','SUBSURF');mod.levels=2;bpy.ops.object.modifier_apply(modifier=mod.name)
for s in [-1,1]:
    ellipsoid('Nose | nostril',(s*.076,-.574,3.197),(.027,.011,.014),'mouth','head',rotation=(0,s*.25,0),segments=20,rings=12)
curve('Muzzle | philtrum',[(0,-.577,3.159),(0,-.566,3.12),(0,-.546,3.088)],.007,'mouth','head')

# Short geometric guard-hair tufts around cheeks/forehead; no opaque fur shells.
# Vertex UVs follow the underlying head so the rosettes remain coherent in GLB.
vs=[];fs=[];uv=[]
for i in range(6500):
    az=random.uniform(0,2*math.pi); zz=random.uniform(-.86,.92)
    rr=math.sqrt(1-zz*zz)
    n=Vector((rr*math.cos(az),rr*math.sin(az),zz))
    p=Vector((n.x*.51,n.y*.383-.012,3.352+n.z*.552))
    if n.y<-.40 and abs(p.x)<.395 and p.z<3.66: continue
    tangent=Vector((n.x*.3,n.y*.2,-.8));tangent=(tangent-n*tangent.dot(n)).normalized()
    side=n.cross(tangent).normalized()
    length=random.uniform(.018,.047);width=random.uniform(.0015,.0035)
    q=len(vs)
    vs.extend([tuple(p-side*width),tuple(p+side*width),tuple(p+tangent*length+n*.012)])
    fs.append((q,q+1,q+2))
    u=(az/(2*math.pi)+.5)%1;v=math.acos(-zz)/math.pi
    uv.extend([(u,v)]*3)
mesh('Fur | fine silhouette tufts',vs,fs,'fur','head',uv)

# Control spot scale per anatomical part instead of wrapping the entire atlas
# around each small finger and ear. All coordinates remain ordinary glTF UVs.
for obj in character.objects:
    if obj.type!='MESH' or not obj.data.uv_layers:continue
    if mats['fur'] not in list(obj.data.materials):continue
    scale=.63 if obj.name.startswith('Head |') else .42
    if obj.name.startswith('Fur |'):scale=.63
    if obj.name.startswith('Tail | long'):scale=.8
    for loop in obj.data.uv_layers.active.data:loop.uv*=scale

rig,actions=build_rig_and_actions(bindings,OUT)
move_collection(rig,character)
rig.name='IRBIS_Rig'
rig['character']='Irbis — Snow Leopard / Career Quest'
rig['reference']='User-provided concept, 23 September 2026'
rig['front_axis']='-Y';rig['up_axis']='+Z'
rig['animations']='Idle_Breathe (5 sec), Idle_LookAround (8 sec)'

# Studio lighting, seamless warm background, feet stay planted at Z=0.
def flat_mat(name,color,roughness=.6,metallic=0):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
    p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=roughness;p.inputs['Metallic'].default_value=metallic
    return m
floor_mat=flat_mat('Studio | warm porcelain',(.72,.75,.70),.82)
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.012));floor=bpy.context.object;floor.name='Studio floor';floor.data.materials.append(floor_mat);move_collection(floor,studio)
def area(name,loc,power,color,size,target=(0,0,2)):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.color=color;data.shape='DISK';data.size=size
    obj=bpy.data.objects.new(name,data);studio.objects.link(obj);obj.location=loc;obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
area('Key | large softbox',(-3.5,-4.5,6.5),850,(1,.90,.77),5)
area('Fill | cool softbox',(4,-2.0,4.5),630,(.79,.91,1),4)
area('Rim | fur separation',(1,3.0,5.5),1000,(1,.93,.79),3)
world=bpy.data.worlds.new('Studio ambience');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.72,.78,.80,1);world.node_tree.nodes['Background'].inputs[1].default_value=.35;scene.world=world
data=bpy.data.cameras.new('Portrait camera');cam=bpy.data.objects.new('Portrait camera',data);studio.objects.link(cam)
cam.location=(5.3,-10,4.65);target=Vector((.20,0,2.0));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();data.type='ORTHO';data.ortho_scale=4.72;scene.camera=cam
scene.render.engine='CYCLES';scene.cycles.samples=48;scene.cycles.use_denoising=True
try:
    pref=bpy.context.preferences.addons['cycles'].preferences
    pref.compute_device_type='OPTIX';pref.get_devices()
    for device in pref.devices:device.use=device.type=='OPTIX'
    if any(d.type=='OPTIX' for d in pref.devices):scene.cycles.device='GPU'
except Exception:pass
scene.render.resolution_x=1000;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
scene.view_settings.view_transform='AgX'
scene.render.fps=24;scene.frame_start=1;scene.frame_end=120;scene.frame_set(1)
scene['Notes']='Original procedural stylized interpretation. Packed textures; two seamless skeletal idle loops. Studio objects are excluded from GLB.'
for image in bpy.data.images:
    if image.source=='FILE' and image.filepath:
        try:image.pack()
        except RuntimeError:pass
for screen in bpy.data.screens:
    for a in screen.areas:
        if a.type=='VIEW_3D':
            a.spaces.active.region_3d.view_distance=6.3
            a.spaces.active.region_3d.view_location=(0,0,2)
            a.spaces.active.region_3d.view_rotation=cam.rotation_euler.to_quaternion()
            a.spaces.active.shading.type='MATERIAL'
            a.spaces.active.overlay.show_overlays=False
active(rig)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'Irbis_SnowLeopard.blend'))
# Export only the character, with two named NLA animations and all images embedded.
bpy.ops.object.select_all(action='DESELECT')
for obj in character.objects: obj.select_set(True)
bpy.context.view_layer.objects.active=rig
export_report=export_optimized(rig,character,OUT/'Irbis_SnowLeopard.glb')
scene.render.filepath=str(OUT/'previews'/'Irbis_portrait.png')
bpy.ops.render.render(write_still=True)
report={'blend':'Irbis_SnowLeopard.blend','glb':'Irbis_SnowLeopard.glb','mesh_objects':sum(o.type=='MESH' for o in character.objects),'vertices':sum(len(o.data.vertices) for o in character.objects if o.type=='MESH'),'bones':len(rig.data.bones),'actions':list(actions), 'generator':'source/build_character.py','glb_export':export_report}
(OUT/'model_info.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('IRBIS_BUILD_COMPLETE',json.dumps(report))
