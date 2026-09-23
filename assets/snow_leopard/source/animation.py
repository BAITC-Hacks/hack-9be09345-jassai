"""Snow leopard rig and seamless idle clips for Blender 5.2.

Usage::

    rig, actions = build_rig_and_actions(mesh_bindings, output_dir)
    # actions is {"Idle_Breathe": Action, "Idle_LookAround": Action}.
    # GLB: export_animation_mode='NLA_TRACKS', export_frame_range=False.

Bindings accept either one bone name for a rigid mesh or per-vertex weights:
``(mesh, {vertex_index: {bone_name: positive_weight, ...}, ...})``.
Weighted bindings must cover every vertex; weights are normalized internally.
Meshes are already in world space with transforms applied. Z is up; front is -Y.

Each clip has a repeated boundary key: 1..121 is exactly 120/24 = 5 seconds;
1..193 is exactly 192/24 = 8 seconds. Playback excludes the repeated last frame.
The eyes' rest bones point up (+Z world), so blink squash uses LOCAL Y.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import cos, isfinite, pi, radians, sin, tau
from pathlib import Path

import bpy

FPS = 24
CLIPS = {"Idle_Breathe": 120, "Idle_LookAround": 192}


def _bone_layout():
    # name, head, tail, parent. All coordinates are in the character's rest space.
    bones = [
        ("root", (0, 0, 0), (0, 0, .30), None),
        ("pelvis", (0, 0, 1.65), (0, 0, 2.05), "root"),
        ("spine", (0, 0, 2.05), (0, 0, 2.60), "pelvis"),
        ("chest", (0, 0, 2.60), (0, 0, 2.92), "spine"),
        ("head", (0, 0, 2.92), (0, 0, 3.63), "chest"),
    ]
    for suffix, side in (("L", 1), ("R", -1)):
        def position(x, y, z):
            return (side * x, y, z)

        bones.extend([
            (f"upper_arm.{suffix}", position(.52, 0, 2.65), position(.77, -.03, 2.18), "chest"),
            (f"forearm.{suffix}", position(.77, -.03, 2.18), position(.75, -.20, 1.83), f"upper_arm.{suffix}"),
            (f"hand.{suffix}", position(.75, -.20, 1.83), position(.76, -.24, 1.61), f"forearm.{suffix}"),
            (f"thigh.{suffix}", position(.23, 0, 1.85), position(.26, 0, 1.04), "pelvis"),
            (f"shin.{suffix}", position(.26, 0, 1.04), position(.27, 0, .26), f"thigh.{suffix}"),
            (f"foot.{suffix}", position(.27, 0, .26), position(.27, -.30, .12), f"shin.{suffix}"),
            (f"eye.{suffix}", position(.21, -.44, 3.40), position(.21, -.44, 3.52), "head"),
            (f"ear.{suffix}", position(.40, 0, 3.70), position(.47, 0, 3.94), "head"),
        ])
    tail = [(0, .30, 1.55), (.15, .55, 1.20), (.45, .67, .86),
            (.88, .57, .74), (1.25, .45, .91), (1.48, .35, 1.25), (1.46, .27, 1.60)]
    for index in range(6):
        bones.append((f"tail.{index + 1:02d}", tail[index], tail[index + 1],
                      "pelvis" if index == 0 else f"tail.{index:02d}"))
    return bones


def _validate_bindings(mesh_bindings, valid_bones):
    """Validate everything before adding modifiers or altering vertex groups."""
    result, seen = [], set()
    for mesh, binding in mesh_bindings:
        if mesh.type != "MESH":
            raise TypeError(f"Expected a mesh object, got {mesh.name!r} ({mesh.type})")
        if mesh.as_pointer() in seen:
            raise ValueError(f"Duplicate mesh binding: {mesh.name}")
        seen.add(mesh.as_pointer())
        if isinstance(binding, str):
            if binding not in valid_bones:
                raise ValueError(f"Unknown bone {binding!r} on {mesh.name}")
            result.append((mesh, binding))
            continue
        if not isinstance(binding, Mapping):
            raise TypeError(f"Invalid binding for {mesh.name}; use a bone name or vertex-weight mapping")
        required = set(range(len(mesh.data.vertices)))
        if set(binding) != required:
            raise ValueError(f"Weights for {mesh.name} must cover every vertex exactly")
        normalized = {}
        for index, influences in binding.items():
            if not isinstance(influences, Mapping) or not influences:
                raise ValueError(f"Missing influences on {mesh.name} vertex {index}")
            clean = {}
            for bone, weight in influences.items():
                if bone not in valid_bones:
                    raise ValueError(f"Unknown bone {bone!r} on {mesh.name}")
                weight = float(weight)
                if not isfinite(weight) or weight < 0:
                    raise ValueError(f"Invalid weight on {mesh.name} vertex {index}")
                if weight > 0:
                    clean[bone] = weight
            total = sum(clean.values())
            if total <= 0:
                raise ValueError(f"Zero total weight on {mesh.name} vertex {index}")
            normalized[index] = {bone: weight / total for bone, weight in clean.items()}
        result.append((mesh, normalized))
    return result


def _make_rig(layout):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    data = bpy.data.armatures.new("SnowLeopard_Skeleton")
    rig = bpy.data.objects.new("SnowLeopard_Rig", data)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    rig.show_in_front = True
    data.display_type = "OCTAHEDRAL"
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent_name in layout:
        bone = data.edit_bones.new(name)
        bone.head, bone.tail, bone.roll = head, tail, 0.0
        if parent_name:
            bone.parent = data.edit_bones[parent_name]
            bone.use_connect = (bone.head - bone.parent.tail).length < 1e-6
    bpy.ops.object.mode_set(mode="OBJECT")
    for bone in data.bones:
        # Upper-body volume changes should not scale the face, hands, or ears.
        bone.inherit_scale = "NONE"
    for bone in rig.pose.bones:
        bone.rotation_mode = "XYZ"
    rig["front_axis"] = "-Y"
    rig["up_axis"] = "+Z"
    rig["blink_axis"] = "eye.L/eye.R local scale Y (world Z in rest pose)"
    rig["loop_note"] = "Closing key is repeated: Breathe 1..121; LookAround 1..193 at 24 fps"
    return rig


def _bind_meshes(rig, mesh_bindings):
    bone_names = set(rig.data.bones.keys())
    for mesh, binding in mesh_bindings:
        world = mesh.matrix_world.copy()
        mesh.parent = rig
        mesh.matrix_parent_inverse = rig.matrix_world.inverted()
        mesh.matrix_world = world
        # Replace only rig groups; unrelated artist groups are left available.
        for group in list(mesh.vertex_groups):
            if group.name in bone_names:
                mesh.vertex_groups.remove(group)
        if isinstance(binding, str):
            group = mesh.vertex_groups.new(name=binding)
            if mesh.data.vertices:
                group.add(list(range(len(mesh.data.vertices))), 1.0, "REPLACE")
        else:
            groups = {name: mesh.vertex_groups.new(name=name)
                      for name in sorted({name for influences in binding.values() for name in influences})}
            for index, influences in binding.items():
                for name, weight in influences.items():
                    groups[name].add([index], weight, "REPLACE")
        modifier = mesh.modifiers.new("SnowLeopard_Deform", "ARMATURE")
        modifier.object = rig
        modifier.use_deform_preserve_volume = True
        modifier.use_vertex_groups = True


def _bump(phase, center, radius):
    """Compact periodic cosine pulse with no discontinuity at its boundaries."""
    distance = abs((phase - center + .5) % 1.0 - .5)
    return .5 + .5 * cos(pi * distance / radius) if distance < radius else 0.0


def _pose_values(phase, looking):
    angle = tau * phase
    breath = sin(angle * (2 if looking else 1))
    sway = sin(angle)
    # Vertical bones have local Y along world Z, so Y is the yaw axis.
    values = {
        "spine": ((.45 * breath, .40 * sway, .70 * sway), (1, 1, 1)),
        "chest": ((-.30 * breath, .55 * sway, -.25 * sway),
                  (1 + .007 * breath, 1 + .004 * breath, 1 + .010 * breath)),
        "head": ((.70 * breath, .60 * sway, -.40 * sway), (1, 1, 1)),
    }
    if looking:
        # Slow left/right scan with a brief glance down; still a periodic pose.
        values["spine"] = ((.50 * breath, 1.10 * sway, 1.25 * sway), (1, 1, 1))
        values["chest"] = ((-.30 * breath, 1.70 * sway, -.40 * sway), values["chest"][1])
        values["head"] = ((1.0 * breath + 2.0 * _bump(phase, .53, .13),
                           11.0 * sway + 1.4 * sin(2 * angle),
                           -1.6 * sway), (1, 1, 1))
    for suffix, side in (("L", 1), ("R", -1)):
        values[f"upper_arm.{suffix}"] = ((.8 * breath, 0, side * .65 * breath), (1, 1, 1))
        values[f"forearm.{suffix}"] = ((.6 * breath, 0, side * .25 * sway), (1, 1, 1))
        values[f"hand.{suffix}"] = ((.35 * breath, side * .30 * sway, 0), (1, 1, 1))
        twitch = _bump(phase, .68 if suffix == "L" else .72, .055)
        values[f"ear.{suffix}"] = ((-3.0 * twitch, 0, side * 2.0 * twitch), (1, 1, 1))
        blink = max(_bump(phase, .31 + .002 * (side < 0), .030 if looking else .043),
                    _bump(phase, .80 + .002 * (side < 0), .030 if looking else .043))
        values[f"eye.{suffix}"] = ((0, 0, 0), (1, max(.065, 1 - .935 * blink), 1))
    for index in range(6):
        delay = .53 * index
        # Traveling wave remains small at the base and slightly larger at tip.
        wave = sin(angle - delay)
        cross_wave = sin(angle - delay + .75)
        values[f"tail.{index + 1:02d}"] = (((1.1 + .28 * index) * wave,
                                          .45 * cross_wave,
                                          (1.0 + .30 * index) * cross_wave), (1, 1, 1))
    return values


def _action_curves(action):
    # Blender 4.4+ layered actions store curves in channel bags, not action.fcurves.
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type == "KEYFRAME":
                for channelbag in strip.channelbags:
                    yield from channelbag.fcurves


def _make_action(rig, clip_name, cycle_frames):
    action = bpy.data.actions.new(clip_name)
    action.use_fake_user = True
    rig.animation_data.action = action
    for bone in rig.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)
    for offset in range(cycle_frames + 1):
        # Use exactly the first phase again; avoid even tiny floating-point seams.
        phase = 0.0 if offset == cycle_frames else offset / cycle_frames
        for bone_name, (rotation, scale) in _pose_values(phase, clip_name == "Idle_LookAround").items():
            bone = rig.pose.bones[bone_name]
            bone.rotation_euler = tuple(radians(value) for value in rotation)
            bone.scale = scale
            bone.keyframe_insert(data_path="rotation_euler", frame=offset + 1, group=bone_name)
            bone.keyframe_insert(data_path="scale", frame=offset + 1, group=bone_name)
    action.use_frame_range = True
    action.frame_start, action.frame_end = 1, cycle_frames + 1
    action["cycle_frames"] = cycle_frames
    action["fps"] = FPS
    action["duration_seconds"] = cycle_frames / FPS
    action["seamless_loop"] = True
    for curve in _action_curves(action):
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"
        curve.modifiers.new("CYCLES")
    return action


def build_rig_and_actions(mesh_bindings, output_dir):
    """Bind supplied meshes and return ``(armature, actions_by_name)``.

    NLA tracks are named after each clip. They are muted for an unambiguous
    working viewport; the active action previews Idle_Breathe. Blender's GLB
    exporter exports both tracks with ``export_animation_mode='NLA_TRACKS'``.
    ``output_dir`` identifies the caller's destination; exports belong to caller.
    """
    if bpy.app.version < (5, 2, 0):
        raise RuntimeError("This rig builder requires Blender 5.2 or newer")
    layout = _bone_layout()
    bindings = _validate_bindings(mesh_bindings, {bone[0] for bone in layout})
    rig = _make_rig(layout)
    rig["output_directory"] = str(Path(output_dir))
    _bind_meshes(rig, bindings)
    rig.animation_data_create()
    rig.animation_data.use_nla = False
    actions = {name: _make_action(rig, name, frames) for name, frames in CLIPS.items()}
    rig.animation_data.action = None
    for name, action in actions.items():
        track = rig.animation_data.nla_tracks.new()
        track.name, track.mute = name, True
        strip = track.strips.new(name, 1, action)
        strip.action_slot = action.slots[0]
        strip.action_frame_start, strip.action_frame_end = action.frame_range
        strip.extrapolation = "NOTHING"
        strip.blend_type = "REPLACE"
        strip.use_auto_blend = False
    rig.animation_data.action = actions["Idle_Breathe"]
    rig.animation_data.action_slot = actions["Idle_Breathe"].slots[0]
    rig.animation_data.use_nla = True
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = FPS, 1.0
    scene.frame_start, scene.frame_end = 1, CLIPS["Idle_Breathe"]
    scene.frame_set(1)
    bpy.context.view_layer.objects.active = rig
    return rig, actions
