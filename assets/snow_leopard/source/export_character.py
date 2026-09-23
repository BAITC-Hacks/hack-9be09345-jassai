"""Export one skinned GLB mesh while retaining the editable Blender objects."""

from pathlib import Path

import bpy


def export_optimized(rig, character_collection, filepath):
    """Join temporary mesh copies, export their rig/animations, then clean up.

    The original meshes, materials, vertex groups, transforms and rig animation
    data are retained. Shared materials become glTF primitives in a single mesh.
    Returns a small export summary; the caller owns saving the original .blend.
    """
    if rig.type != "ARMATURE":
        raise TypeError("rig must be an armature object")
    meshes = [obj for obj in character_collection.all_objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError("The character collection has no mesh objects")
    if any(mod.type != "ARMATURE" for obj in meshes for mod in obj.modifiers):
        raise ValueError("Apply non-armature geometry modifiers before optimized export")
    for obj in meshes:
        deformers = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
        if len(deformers) != 1 or deformers[0].object != rig:
            raise ValueError(f"{obj.name} must have exactly one modifier using the supplied rig")

    scene = bpy.context.scene
    if rig.name not in scene.objects:
        raise ValueError("The supplied rig must belong to the active scene")
    previous_active = bpy.context.view_layer.objects.active
    previous_selection = tuple(bpy.context.selected_objects)
    previous_mode = previous_active.mode if previous_active else "OBJECT"
    if previous_active and previous_mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    previous_frame, previous_subframe = scene.frame_current, scene.frame_subframe
    # Joining does not touch source objects. Pointer sets identify our temporary
    # datablocks even if Blender deletes some object copies during the join.
    old_objects = {obj.as_pointer() for obj in bpy.data.objects}
    old_meshes = {data.as_pointer() for data in bpy.data.meshes}
    temporary_collection = bpy.data.collections.new("_IRBIS_EXPORT_TEMP")
    scene.collection.children.link(temporary_collection)
    copies = []
    try:
        for source in meshes:
            duplicate = source.copy()
            duplicate.data = source.data.copy()
            duplicate.animation_data_clear()
            temporary_collection.objects.link(duplicate)
            duplicate.hide_viewport = False
            duplicate.hide_render = False
            duplicate.hide_set(False)
            duplicate.select_set(False)
            copies.append(duplicate)
        bpy.ops.object.select_all(action="DESELECT")
        for duplicate in copies:
            duplicate.select_set(True)
        bpy.context.view_layer.objects.active = copies[0]
        if len(copies) > 1:
            bpy.ops.object.join()
        combined = bpy.context.view_layer.objects.active
        combined.name = "IRBIS_Character"
        combined.data.name = "IRBIS_CharacterMesh"
        expected_vertices = sum(len(obj.data.vertices) for obj in meshes)
        expected_faces = sum(len(obj.data.polygons) for obj in meshes)
        if len(combined.data.vertices) != expected_vertices or len(combined.data.polygons) != expected_faces:
            raise RuntimeError("Joining changed the character's topology unexpectedly")
        valid_groups = {group.index for group in combined.vertex_groups if group.name in rig.data.bones}
        for vertex in combined.data.vertices:
            weight = sum(group.weight for group in vertex.groups if group.group in valid_groups)
            if abs(weight - 1) > 1e-4:
                raise RuntimeError(f"Unnormalized skin weights after joining: vertex {vertex.index}")
        materials = {slot.material.name for slot in combined.material_slots if slot.material}
        rig.select_set(True)
        combined.select_set(True)
        bpy.context.view_layer.objects.active = rig
        destination = Path(filepath).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = bpy.ops.export_scene.gltf(
            filepath=str(destination), export_format="GLB", use_selection=True,
            use_active_scene=True, export_animations=True,
            export_animation_mode="NLA_TRACKS", export_nla_strips=True,
            export_frame_range=False, export_force_sampling=True,
            export_skins=True, export_morph=True, export_apply=False,
        )
        if "FINISHED" not in result:
            raise RuntimeError("Blender did not complete the GLB export")
        return {"source_meshes": len(meshes), "export_meshes": 1,
                "material_primitives": len(materials), "vertices": expected_vertices,
                "faces": expected_faces, "bytes": destination.stat().st_size}
    finally:
        # Delete only datablocks created by this function; never purge orphans.
        for obj in list(bpy.data.objects):
            if obj.as_pointer() not in old_objects and obj.name in temporary_collection.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for data in list(bpy.data.meshes):
            if data.as_pointer() not in old_meshes and data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.collections.remove(temporary_collection)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in previous_selection:
            if obj.name in bpy.context.view_layer.objects:
                obj.select_set(True)
        if previous_active and previous_active.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = previous_active
            if previous_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=previous_mode)
        scene.frame_set(previous_frame, subframe=previous_subframe)
