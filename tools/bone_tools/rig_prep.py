import bpy
from mathutils import Vector
from bpy.props import (
    PointerProperty, StringProperty, BoolProperty,
    CollectionProperty, IntProperty,
)


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "rig_prep"
tool_name = "Rig Prep"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Name autofill state
# ------------------------------------------------------------
# Remembers the last auto-generated value so we can tell whether
# the current name was typed by the user or produced by us.
# Module-level rather than a PropertyGroup field: it does not need
# to be serialized, exposed to RNA, or preserved across sessions.
# ============================================================
_last_auto_name = ""


def _auto_name_for(arm):
    return f"{arm.name}_deform"


# ============================================================
# UI PropertyGroup (WindowManager)
# ============================================================
def _poll_mesh(self, obj):
    return obj.type == 'MESH'


def _poll_armature(self, obj):
    return obj.type == 'ARMATURE'


def _on_src_arm_change(self, context):
    """React to source armature changes.

    If the name field still holds the previous auto-generated
    value (or is empty), overwrite it with the new source's auto
    name. If the user has customized it, leave it alone.
    """
    global _last_auto_name
    if not self.src_arm:
        return
    if not self.new_name or self.new_name == _last_auto_name:
        auto = _auto_name_for(self.src_arm)
        self.new_name = auto
        _last_auto_name = auto


def _on_new_name_change(self, context):
    """React to manual edits of the name field.

    Emptying the field snaps it back to the current source's auto
    name. Any other edit is treated as a user customization and
    left untouched.
    """
    global _last_auto_name
    if not self.new_name and self.src_arm:
        auto = _auto_name_for(self.src_arm)
        self.new_name = auto
        _last_auto_name = auto


class XNEKO_RigPrepRef(bpy.types.PropertyGroup):
    obj: PointerProperty(
        name="Object",
        type=bpy.types.Object,
        poll=_poll_mesh,
    )


class XNEKO_RigPrepUI(bpy.types.PropertyGroup):
    src_arm: PointerProperty(
        name="Source",
        description="Armature to extract deform bones from",
        type=bpy.types.Object,
        poll=_poll_armature,
        update=_on_src_arm_change,
    )
    references: CollectionProperty(type=XNEKO_RigPrepRef)
    active_ref_index: bpy.props.IntProperty(default=0)
    new_name: StringProperty(
        name="Name",
        description=(
            "Name for the extracted armature. Clear the field to "
            "reset to the source name plus suffix"
        ),
        default="",
        update=_on_new_name_change,
    )
    switch_mesh: BoolProperty(
        name="Switch Mesh Modifiers",
        description=(
            "Repoint every selected mesh bound to the source "
            "armature so it binds to the new one instead"
        ),
        default=True,
    )


def _ui(context):
    return context.window_manager.xneko_rig_prep_ui


def _reference_meshes(ui):
    """Return every mesh referenced by the list, in list order.

    Dead entries (object was deleted) and duplicates are skipped
    so downstream helpers never have to guard against them.
    """
    meshes = []
    seen = set()
    for item in ui.references:
        obj = item.obj
        if obj is None or obj.name in seen:
            continue
        meshes.append(obj)
        seen.add(obj.name)
    return meshes


def _is_ready(ui):
    return ui.src_arm is not None and bool(_reference_meshes(ui))


def _is_bound(ui):
    """Return True if any reference mesh is bound to the source."""
    for mesh in _reference_meshes(ui):
        for mod in mesh.modifiers:
            if (mod.type == 'ARMATURE'
                    and mod.object == ui.src_arm
                    and mod.use_vertex_groups):
                return True
    return False


def _deform_bone_names(ui):
    """Vertex-group names that match a bone on the source armature.

    Merges the vertex-group sets of every reference mesh, so a rig
    whose deform bones are split across several meshes is captured
    in full.
    """
    if not _is_ready(ui):
        return []
    bone_names = {b.name for b in ui.src_arm.data.bones}
    vg_names = set()
    for mesh in _reference_meshes(ui):
        vg_names.update(vg.name for vg in mesh.vertex_groups)
    return sorted(vg_names & bone_names)


# ============================================================
# UIList
# ============================================================
class XNEKO_UL_rig_prep_refs(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        obj = item.obj
        if obj is None:
            layout.label(text="(missing)", icon='ERROR')
            return
        layout.label(text=obj.name, icon='MESH_DATA')


# ============================================================
# Extraction
# ============================================================
def _gather_bone_data(arm, keep_names):
    """Collect head/tail/roll and deform-ancestor parent info.

    Reads from armature.data.bones (Bone objects) rather than
    edit_bones: Bone data is available in any mode, EditBone data
    is only valid while the armature is in EDIT mode.

    Bone does not expose a 'roll' attribute -- only EditBone does.
    The rest orientation is recovered from Bone.matrix_local:
    its third column is the bone's Z axis in armature space,
    which EditBone.align_roll() can consume directly.
    """
    bones = arm.data.bones
    keep_set = set(keep_names)
    data = {}
    for name in keep_names:
        bone = bones.get(name)
        if bone is None:
            continue

        # Nearest deform ancestor. Bones not in keep_set are
        # controllers or helpers and get skipped.
        parent_name = None
        p = bone.parent
        while p is not None:
            if p.name in keep_set:
                parent_name = p.name
                break
            p = p.parent

        # use_connect survives only when the ORIGINAL direct parent
        # is also kept. Otherwise the new parent's tail does not
        # coincide with this bone's head, and connect would snap
        # the head and destroy the rest pose.
        keep_connect = (
            bone.use_connect
            and bone.parent is not None
            and bone.parent.name in keep_set
        )

        # Third column of the rest matrix is the bone's Z axis in
        # armature space. This is what align_roll wants.
        m3 = bone.matrix_local.to_3x3()
        z_axis = (m3 @ Vector((0.0, 0.0, 1.0))).normalized()

        data[name] = {
            "head": bone.head_local.copy(),
            "tail": bone.tail_local.copy(),
            "z_axis": z_axis,
            "parent": parent_name,
            "use_connect": keep_connect,
        }
    return data


def _build_bones(new_obj, new_data, src_arm, bone_data):
    """Populate new_data with edit bones matching bone_data.

    Handles its own edit-mode lifecycle and always exits in
    OBJECT mode. Does NOT save or restore selection: the caller
    (_extract) owns that, because the caller is the one that
    knows what to restore.
    """
    try:
        new_data.display_type = src_arm.data.display_type
        new_data.axes_position = src_arm.data.axes_position
    except Exception:
        pass

    if (bpy.context.object is not None
            and bpy.context.object.mode != 'OBJECT'):
        bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.select_all(action='DESELECT')
    new_obj.select_set(True)
    bpy.context.view_layer.objects.active = new_obj

    bpy.ops.object.mode_set(mode='EDIT')
    try:
        new_edit_bones = new_data.edit_bones

        created = {}
        for name, info in bone_data.items():
            new_eb = new_edit_bones.new(name)
            new_eb.head = info["head"]
            new_eb.tail = info["tail"]
            # Bone.roll is not available on Bone objects. Restore
            # the orientation by aligning the Z axis, which is
            # exactly what roll encodes internally.
            new_eb.align_roll(info["z_axis"])
            new_eb.use_deform = True
            created[name] = new_eb

        for name, info in bone_data.items():
            parent_name = info["parent"]
            if parent_name is None:
                continue
            new_eb = created[name]
            new_eb.parent = created[parent_name]
            if info["use_connect"]:
                new_eb.use_connect = True
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')


def _extract(src_arm, keep_names, new_name):
    """Create a new armature containing only the named bones.

    Source data is read from Bone objects (mode-independent) and
    written into the new armature's EditBones. Parent chains skip
    any bone not in keep_names. Object world transform is copied
    so the new armature occupies the same space as the source.
    The armature is placed in a dedicated collection at scene
    root so it does not mix into the active collection.

    If new_name collides with an existing datablock, Blender
    appends .001, .002, ... on its own.
    """
    bone_data = _gather_bone_data(src_arm, keep_names)
    if not bone_data:
        raise RuntimeError("No bone data gathered")

    src_matrix = src_arm.matrix_world.copy()

    # Capture the user's selection BEFORE anything below changes
    # it. _switch_modifiers in the operator relies on the current
    # selection, so losing it here would break the flow.
    saved_selection = list(bpy.context.selected_objects)
    saved_active = bpy.context.view_layer.objects.active

    new_collection = bpy.data.collections.new(new_name)
    bpy.context.scene.collection.children.link(new_collection)

    new_data = bpy.data.armatures.new(new_name)
    new_obj = bpy.data.objects.new(new_name, new_data)
    new_collection.objects.link(new_obj)
    new_obj.matrix_world = src_matrix

    success = False
    try:
        _build_bones(new_obj, new_data, src_arm, bone_data)
        success = True
    except Exception:
        # Roll back: unlink and remove everything we just added so
        # the scene is left exactly as it was before this call.
        try:
            new_collection.objects.unlink(new_obj)
        except Exception:
            pass
        try:
            bpy.context.scene.collection.children.unlink(new_collection)
        except Exception:
            pass
        try:
            bpy.data.objects.remove(new_obj, do_unlink=True)
        except Exception:
            pass
        try:
            bpy.data.armatures.remove(new_data)
        except Exception:
            pass
        try:
            bpy.data.collections.remove(new_collection)
        except Exception:
            pass
        raise
    finally:
        # Restore the user's selection regardless of outcome. On
        # success, append the new armature as active so the
        # operator can chain into _switch_modifiers immediately.
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except Exception:
            pass
        for obj in saved_selection:
            try:
                obj.select_set(True)
            except Exception:
                pass
        if success:
            try:
                new_obj.select_set(True)
                bpy.context.view_layer.objects.active = new_obj
            except Exception:
                pass
        else:
            try:
                bpy.context.view_layer.objects.active = saved_active
            except Exception:
                pass

    return new_obj


def _switch_modifiers(src_arm, new_arm):
    """Repoint selected meshes bound to src_arm at new_arm.

    Only touches objects that are currently selected. Objects
    bound to the source but not selected are left as-is, so the
    user can control exactly which skins follow the new armature.
    """
    count = 0
    for obj in bpy.context.selected_objects:
        if obj.type != 'MESH':
            continue
        for mod in obj.modifiers:
            if (mod.type == 'ARMATURE'
                    and mod.object == src_arm
                    and mod.use_vertex_groups):
                mod.object = new_arm
                count += 1
    return count


# ============================================================
# Operator
# ============================================================
class XNEKO_OT_rig_prep_add_selected(bpy.types.Operator):
    bl_idname = "xneko.rig_prep_add_selected"
    bl_label = "Add Selected Meshes"
    bl_description = "Add every selected mesh to the reference list"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ui = _ui(context)
        existing = {it.obj for it in ui.references if it.obj is not None}
        added = 0
        for obj in (context.selected_objects or []):
            if obj.type != 'MESH' or obj in existing:
                continue
            item = ui.references.add()
            item.obj = obj
            added += 1
        if added == 0:
            self.report({'INFO'}, "No new mesh to add")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Added {added} reference(s)")
        return {'FINISHED'}


class XNEKO_OT_rig_prep_remove_ref(bpy.types.Operator):
    bl_idname = "xneko.rig_prep_remove_ref"
    bl_label = "Remove Reference"
    bl_options = {'INTERNAL'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        ui = _ui(context)
        if 0 <= self.index < len(ui.references):
            ui.references.remove(self.index)
            if ui.active_ref_index >= len(ui.references):
                ui.active_ref_index = max(0, len(ui.references) - 1)
        return {'FINISHED'}


class XNEKO_OT_rig_prep_clear_refs(bpy.types.Operator):
    bl_idname = "xneko.rig_prep_clear_refs"
    bl_label = "Clear References"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ui = _ui(context)
        ui.references.clear()
        ui.active_ref_index = 0
        return {'FINISHED'}


class XNEKO_OT_rig_prep_extract(bpy.types.Operator):
    bl_idname = "xneko.rig_prep_extract"
    bl_label = "Extract Deform Skeleton"
    bl_description = (
        "Create a new armature containing only the bones that are "
        "referenced by the reference mesh's vertex groups"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ui = _ui(context)
        return _is_ready(ui) and _is_bound(ui)

    def execute(self, context):
        ui = _ui(context)
        src_arm = ui.src_arm
        keep = _deform_bone_names(ui)

        if not keep:
            self.report({'ERROR'}, "No deform bones identified")
            return {'CANCELLED'}

        name = ui.new_name.strip() or _auto_name_for(src_arm)

        try:
            if (context.object is not None
                    and context.object.mode != 'OBJECT'):
                bpy.ops.object.mode_set(mode='OBJECT')

            new_arm = _extract(src_arm, keep, name)

            switched = 0
            if ui.switch_mesh:
                switched = _switch_modifiers(src_arm, new_arm)
        except Exception as e:
            self.report({'ERROR'}, f"Extraction failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        print("=" * 60)
        print(f"[XNeko rig_prep] Extracted from {src_arm.name}")
        print("=" * 60)
        print(f"New armature      : {new_arm.name}")
        print(f"Bones kept        : {len(keep)}")
        print(f"Bones dropped     : {len(src_arm.data.bones) - len(keep)}")
        print(f"Modifiers switched: {switched}")
        print("=" * 60)

        self.report(
            {'INFO'},
            f"Created {new_arm.name} "
            f"({len(keep)} bones, {switched} switched)",
        )

        # Append the new armature to the current selection instead
        # of collapsing the selection to just the new object. Users
        # often want to keep the meshes selected so they can chain
        # another operation right away.
        new_arm.select_set(True)
        context.view_layer.objects.active = new_arm

        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_xneko_rig_prep(bpy.types.Panel):
    bl_label = "Rig Prep"
    bl_idname = "VIEW3D_PT_xneko_rig_prep"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        ui = _ui(context)

        # ---- Pickers ----
        box = layout.box()
        box.prop(ui, "src_arm", text="Source", icon='ARMATURE_DATA')

        box.label(text="References:")

        row = box.row()

        col = row.column()
        col.template_list(
            "XNEKO_UL_rig_prep_refs", "",
            ui, "references",
            ui, "active_ref_index",
            rows=4,
        )

        col = row.column(align=True)
        col.operator(
            "xneko.rig_prep_add_selected",
            text="", icon='ADD',
        )
        col.operator(
            "xneko.rig_prep_remove_ref",
            text="", icon='REMOVE',
        ).index = ui.active_ref_index
        col.separator()
        col.operator(
            "xneko.rig_prep_clear_refs",
            text="", icon='TRASH',
        )

        # ---- Gate: both picked ----
        if not _is_ready(ui):
            hint = layout.box()
            hint.label(
                text="Pick a source armature and a reference mesh",
                icon='INFO',
            )
            return

        # ---- Gate: bound ----
        if not _is_bound(ui):
            warn = layout.box()
            warn.alert = True
            warn.label(
                text="Reference mesh is not bound to the source",
                icon='ERROR',
            )
            return

        # ---- Settings ----
        settings = layout.box()
        settings.prop(ui, "new_name", text="Name")
        settings.prop(ui, "switch_mesh")

        if ui.switch_mesh:
            n_selected = sum(
                1 for o in bpy.context.selected_objects
                if o.type == 'MESH'
            )
            hint = settings.row()
            hint.enabled = False
            if n_selected:
                hint.label(
                    text=f"Will switch {n_selected} selected mesh(es)",
                    icon='INFO',
                )
            else:
                hint.alert = True
                hint.label(
                    text="No mesh selected; modifiers will not switch",
                    icon='ERROR',
                )

        # ---- Status ----
        keep = _deform_bone_names(ui)
        total = len(ui.src_arm.data.bones)

        status = layout.box()
        status.label(text=f"Source bones: {total}")
        status.label(text=f"Deform bones: {len(keep)}")

        # ---- Action ----
        layout.separator()
        layout.operator(
            "xneko.rig_prep_extract",
            icon='DUPLICATE',
        )


# ============================================================
# Registration
# ============================================================
classes = (
    XNEKO_RigPrepRef,
    XNEKO_RigPrepUI,
    XNEKO_UL_rig_prep_refs,
    XNEKO_OT_rig_prep_add_selected,
    XNEKO_OT_rig_prep_remove_ref,
    XNEKO_OT_rig_prep_clear_refs,
    XNEKO_OT_rig_prep_extract,
    VIEW3D_PT_xneko_rig_prep,
)


def on_load():
    if hasattr(bpy.types.WindowManager, "xneko_rig_prep_ui"):
        try:
            del bpy.types.WindowManager.xneko_rig_prep_ui
        except Exception:
            pass
    bpy.types.WindowManager.xneko_rig_prep_ui = (
        PointerProperty(type=XNEKO_RigPrepUI)
    )


def on_unload():
    if hasattr(bpy.types.WindowManager, "xneko_rig_prep_ui"):
        try:
            del bpy.types.WindowManager.xneko_rig_prep_ui
        except Exception:
            pass