from collections.abc import Collection
from typing import cast

import bpy
from bpy.types import PoseBone, bpy_prop_collection
from mathutils import Quaternion, Vector


def bytes_to_str(in_bytes: bytes) -> str:
    return in_bytes.rstrip(b"\x00").decode()


def first(target, expr, default=None):
    if not target:
        return None
    filtered = filter(expr, target)
    return next(filtered, default)


def best(target, expr, goal, default=None):
    if not target:
        return None

    for item in target:
        if expr(item) == goal:
            return item

    for item in target:
        if expr(item) in goal:
            return item

    return default


def make_axis_vector(vec_in: Vector) -> Vector:
    vec_out = Vector()
    x, y, z = vec_in

    if abs(x) > abs(y):
        if abs(x) > abs(z):
            vec_out.x = 1 if x >= 0 else -1
        else:
            vec_out.z = 1 if z >= 0 else -1
    elif abs(y) > abs(z):
        vec_out.y = 1 if y >= 0 else -1
    else:
        vec_out.z = 1 if z >= 0 else -1

    return vec_out


def get_case_insensitive(
    source: bpy_prop_collection, string: str,
) -> PoseBone | None:
    string = string.lower()
    source_ = cast(Collection[PoseBone], source)

    for item in source_:
        if item.name.lower() == string:
            return item

    return None


def get_active_armature() -> bpy.types.Object | None:
    obj = bpy.context.object

    if obj is None:
        return None

    if obj.type == "ARMATURE":
        return obj
    elif obj.type == "MESH":
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE":
                return modifier.object

    return None


def get_armature_mesh(obj):
    if obj.type == 'ARMATURE' and len(obj.children) > 0:
        for child in obj.children:
            if child.type == "MESH":
                return child

    if obj.type == 'MESH':
        return obj
    return None


def disable_constraints(
    armature: bpy.types.Object,
) -> list[bpy.types.Constraint]:
    constraints_muted = []
    for bone in armature.pose.bones:
        for constraint in bone.constraints:
            if not constraint.mute:
                constraint.mute = True
                constraints_muted.append(constraint)
    return constraints_muted


def bone_hierarchy_has_vertex_groups(bone, vertex_groups):
    if bone.name in vertex_groups:
        return True
    children = bone.children_recursive
    for child in children:
        if child.name in vertex_groups:
            return True
    return False


def bone_has_parent(child, parent):
    if child == parent:
        return True
    return parent in child.parent_recursive


def bone_roll(bone: bpy.types.EditBone, roll: float):
    if 'orig_roll' in bone:
        raise RuntimeError(
            f"bone_roll: 'orig_roll' already set on {bone.name!r}"
        )
    bone['orig_roll'] = bone.roll
    bone.roll = roll


def bone_tail(bone: bpy.types.EditBone, tail):
    if 'orig_tail' in bone:
        raise RuntimeError(
            f"bone_tail: 'orig_tail' already set on {bone.name!r}"
        )
    bone['orig_tail'] = bone.tail
    bone.tail = tail


def bone_head(bone: bpy.types.EditBone, head):
    if 'orig_head' in bone:
        raise RuntimeError(
            f"bone_head: 'orig_head' already set on {bone.name!r}"
        )
    bone['orig_head'] = bone.head
    bone.head = head


def bone_parent(child: bpy.types.EditBone, parent_to: bpy.types.EditBone):
    if child == parent_to:
        raise RuntimeError(
            f"bone_parent: cannot parent {child.name!r} to itself"
        )
    if child.parent:
        if 'orig_parent' in child:
            raise RuntimeError(
                f"bone_parent: 'orig_parent' already set on {child.name!r}"
            )
        child['orig_parent'] = child.parent.name
    child.parent = parent_to


def bone_swap_properties(
    all_bones: bpy.types.ArmatureEditBones, bone: bpy.types.EditBone,
):
    if orig_roll := bone.get('orig_roll'):
        curr_roll = bone.roll
        bone.roll = orig_roll
        bone['orig_roll'] = curr_roll

    if orig_tail := bone.get('orig_tail'):
        curr_tail = bone.tail.copy()
        bone.tail = orig_tail
        bone['orig_tail'] = curr_tail

    if orig_head := bone.get('orig_head'):
        curr_head = bone.head.copy()
        bone.head = orig_head
        bone['orig_head'] = curr_head

    if orig_parent := bone.get('orig_parent'):
        curr_bone_parent_name = bone.parent.name if bone.parent else None
        bone.parent = all_bones.get(orig_parent)
        bone['orig_parent'] = curr_bone_parent_name


def bone_swap_orig_parents(armature_obj: bpy.types.Object):
    original_mode = bpy.context.active_object.mode
    original_selected_object = bpy.context.active_object
    try:
        bpy.context.view_layer.objects.active = armature_obj
        edit_bones = armature_obj.data.edit_bones
        bpy.ops.object.mode_set(mode='EDIT')
        for edit_bone in edit_bones:
            bone_swap_properties(edit_bones, edit_bone)
    finally:
        bpy.ops.object.mode_set(mode=original_mode)
        bpy.context.view_layer.objects.active = original_selected_object


def make_quat(rot):
    return Quaternion((rot[3], rot[0], rot[1], rot[2]))


def make_vector(vec):
    return Vector((vec[0], vec[1], vec[2]))


def has_vertex_weights(obj, vertex_group):
    mesh = obj.data
    return any(
        vertex_group.index in [g.group for g in v.groups]
        for v in mesh.vertices
    )