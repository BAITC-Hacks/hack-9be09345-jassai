"""Render the actual rigged character, including both full idle cycles.

Run: blender --background Irbis_SnowLeopard.blend --python source/render_previews.py
Frames are temporary, under the repository's ignored .runtime directory.
MP4 videos are encoded with ffmpeg if it is available in PATH.
"""
from pathlib import Path
import bpy, json, shutil, subprocess
from mathutils import Vector

OUT=Path(__file__).resolve().parent.parent
scene=bpy.data.scenes['IRBIS | character studio']
bpy.context.window.scene=scene
rig=bpy.data.objects['IRBIS_Rig']
scene.render.engine='BLENDER_EEVEE'
scene.render.resolution_x=600;scene.render.resolution_y=720
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.fps=24
temp=OUT/'.runtime'/'irbis-animation-frames'
ffmpeg=shutil.which('ffmpeg')
reports=[]
for clip,count in [('Idle_Breathe',120),('Idle_LookAround',192)]:
    action=bpy.data.actions[clip]
    rig.animation_data.action=action
    rig.animation_data.action_slot=action.slots[0]
    rig.animation_data.use_nla=False
    directory=temp/clip;directory.mkdir(parents=True,exist_ok=True)
    scene.frame_start=1;scene.frame_end=count
    # Render one loop with no duplicate end frame. Each frame is an actual pose.
    for frame in range(1,count+1):
        scene.frame_set(frame)
        scene.render.filepath=str(directory/f'{frame:04d}.png')
        bpy.ops.render.render(write_still=True)
    target=OUT/'previews'/f'{clip}.mp4'
    if ffmpeg:
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-framerate','24','-i',str(directory/'%04d.png'),'-c:v','libx264','-crf','19','-preset','medium','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],check=True)
        # GIF previews work in viewers that cannot play local MP4 files.
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(target),'-filter_complex','fps=12,scale=400:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=192[p];[s1][p]paletteuse=dither=sierra2_4a','-loop','0',str(target.with_suffix('.gif'))],check=True)
    reports.append({'name':clip,'fps':24,'frames':count,'duration':count/24,'mp4':target.name if ffmpeg else None})
    print('IRBIS_PREVIEW_CLIP',clip,flush=True)

# Turnaround stills use the same packed asset and a neutral pose.
rig.animation_data.action=bpy.data.actions['Idle_Breathe']
rig.animation_data.action_slot=rig.animation_data.action.slots[0]
scene.frame_set(1)
scene.render.engine='CYCLES';scene.cycles.samples=32
scene.render.resolution_x=800;scene.render.resolution_y=1000
for name,position in [('Irbis_front',(0,-10,3.5)),('Irbis_back',(0,10,3.6)),('Irbis_side',(10,-.2,3.3))]:
    scene.camera.location=position
    scene.camera.rotation_euler=(Vector((.18,0,2))-scene.camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(OUT/'previews'/f'{name}.png')
    bpy.ops.render.render(write_still=True)
(OUT/'previews'/'clips.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
print('IRBIS_ALL_PREVIEWS_COMPLETE',flush=True)
