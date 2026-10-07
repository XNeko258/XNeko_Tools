import bpy
from mathutils import Vector


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "vertex_group_to_bones"
tool_name = "Vertex Group to Bones"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Constants
# ============================================================
DIRECTION_MIN_WEIGHT = 1e-6


# ============================================================
# Data storage
# ============================================================
class XNEKO_VGBGroupItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    selected: bpy.props.BoolProperty(default=False)


def _armature_poll(self, obj):
    return obj is not None and obj.type == 'ARMATURE'


class XNEKO_VGBProperties(bpy.types.PropertyGroup):
    armature: bpy.props.PointerProperty(
        name="Target Armature",
        description=(
            "Armature to receive the generated bones. "
            "Leave empty to create a new one"
        ),
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    threshold: bpy.props.FloatProperty(
        name="Head Threshold",
        description=(
            "Only vertices above this weight contribute to the "
            "computed head position"
        ),
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
    )
    bone_length: bpy.props.FloatProperty(
        name="Bone Length",
        description="Length of every generated bone",
        default=0.1, min=0.001,
    )
    collection_name: bpy.props.StringProperty(
        name="New Collection",
        description="Collection that receives the auto-created armature",
        default="GeneratedBones",
    )
    show_in_front: bpy.props.BoolProperty(
        name="Show In Front",
        description="Set the armature to display in front after generation",
        default=True,
    )

    target_object: bpy.props.StringProperty(default="")
    groups: bpy.props.CollectionProperty(type=XNEKO_VGBGroupItem)
    active_group_index: bpy.props.IntProperty(default=0)


# ============================================================
# Sync vertex group list
# ============================================================
def _sync_vertex_groups(obj, props):
    current_names = [vg.name for vg in obj.vertex_groups]

    # Target object changed -> reset
    if props.target_object != obj.name:
        props.groups.clear()
        props.target_object = obj.name

    # Same name list -> nothing to do
    if [item.name for item in props.groups] == current_names:
        return

    # Preserve existing selection state, then rebuild
    old_state = {item.name: item.selected for item in props.groups}
    props.groups.clear()
    for name in current_names:
        item = props.groups.add()
        item.name = name
        item.selected = old_state.get(name, False)

    if len(props.groups) == 0:
        props.active_group_index = 0
    else:
        props.active_group_index = min(
            props.active_group_index, len(props.groups) - 1
        )


# ============================================================
# Depsgraph handler
# ------------------------------------------------------------
# Guard prevents the handler from re-entering itself while it
# mutates the props collection (which would trigger another
# depsgraph update in some Blender builds).
# ============================================================
_sync_guard = {"busy": False}


def _xneko_vgb_depsgraph_handler(scene, *args):
    if _sync_guard["busy"]:
        return

    props = getattr(scene, "xneko_vgb_props", None)
    if props is None:
        return

    obj = bpy.context.active_object

    # No mesh selected -> clear list
    if obj is None or obj.type != 'MESH':
        if props.target_object or len(props.groups) > 0:
            props.target_object = ""
            props.groups.clear()
        return

    _sync_guard["busy"] = True
    try:
        _sync_vertex_groups(obj, props)
    except Exception as e:
        print(f"[XNeko] vgb sync error: {e}")
    finally:
        _sync_guard["busy"] = False


# ============================================================
# Operators
# ============================================================
class XNEKO_OT_vgb_generate(bpy.types.Operator):
    bl_idname = "xneko.vgb_generate"
    bl_label = "Generate Bones"
    bl_description = (
        "Create one bone per selected vertex group. "
        "Head position is the weighted centroid of vertices above "
        "the threshold; tail direction points toward the lowest-"
        "weight vertex"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return False
        props = getattr(context.scene, "xneko_vgb_props", None)
        if props is None:
            return False
        return any(item.selected for item in props.groups)

    def execute(self, context):
        props = context.scene.xneko_vgb_props
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object first")
            return {'CANCELLED'}

        threshold = props.threshold
        bone_length = props.bone_length

        selected_names = [item.name for item in props.groups if item.selected]
        if not selected_names:
            self.report({'WARNING'}, "No vertex groups selected")
            return {'CANCELLED'}

        if context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # ---------- Target armature ----------
        arm_obj = props.armature
        newly_created = False

        if arm_obj is None:
            col_name = props.collection_name.strip() or "GeneratedBones"
            coll = bpy.data.collections.get(col_name)
            if coll is None:
                coll = bpy.data.collections.new(col_name)
                context.scene.collection.children.link(coll)
            else:
                if coll.name not in [c.name
                                     for c in context.scene.collection.children]:
                    context.scene.collection.children.link(coll)

            arm_data = bpy.data.armatures.new(obj.name + "_Armature")
            arm_obj = bpy.data.objects.new(obj.name + "_Armature", arm_data)
            coll.objects.link(arm_obj)

            props.armature = arm_obj
            newly_created = True

        arm_data = arm_obj.data
        arm_obj.show_in_front = props.show_in_front

        # ---------- Enter Edit mode ----------
        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')

        created = 0
        skipped = 0
        try:
            inv_arm = arm_obj.matrix_world.inverted()
            inv_arm_3x3 = inv_arm.to_3x3()

            group_members = {vg.index: [] for vg in obj.vertex_groups}
            for v in obj.data.vertices:
                world_pos = obj.matrix_world @ v.co
                for g in v.groups:
                    if g.weight > 0.0 and g.group in group_members:
                        group_members[g.group].append(
                            (g.weight, world_pos.copy())
                        )

            for vg in obj.vertex_groups:
                if vg.name not in selected_names:
                    continue

                if vg.name in arm_data.edit_bones:
                    skipped += 1
                    continue

                members = group_members.get(vg.index, [])
                if not members:
                    continue

                high = [(w, p) for w, p in members if w >= threshold]
                if not high:
                    continue

                total_w = sum(w for w, _ in high)
                if total_w <= 0.0:
                    head_world = high[0][1].copy()
                else:
                    head_world = sum(
                        (p * w for w, p in high),
                        Vector((0.0, 0.0, 0.0)),
                    ) / total_w

                direction_candidates = [
                    (w, p) for w, p in members if w > DIRECTION_MIN_WEIGHT
                ]
                if not direction_candidates:
                    direction_candidates = members

                _, lowest_pos = min(direction_candidates, key=lambda x: x[0])
                direction_world = lowest_pos - head_world
                if direction_world.length < 1e-6:
                    direction_world = Vector((0.0, 0.0, 1.0))
                else:
                    direction_world.normalize()

                head_local = inv_arm @ head_world
                dir_local = (inv_arm_3x3 @ direction_world).normalized()

                bone = arm_data.edit_bones.new(vg.name)
                bone.head = head_local
                bone.tail = head_local + dir_local * bone_length
                created += 1

        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

        msg = f"Generated {created} bone(s)"
        if newly_created:
            msg += f" -> created '{arm_obj.name}'"
        else:
            msg += f" -> appended to '{arm_obj.name}'"
        if skipped:
            msg += f" (skipped {skipped} duplicate(s))"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class XNEKO_OT_vgb_select(bpy.types.Operator):
    bl_idname = "xneko.vgb_select"
    bl_label = "Selection Action"
    bl_options = {'INTERNAL'}

    action: bpy.props.EnumProperty(items=[
        ('SELECT', 'Select', ''),
        ('DESELECT', 'Deselect', ''),
        ('INVERT', 'Invert', ''),
    ])

    def execute(self, context):
        props = context.scene.xneko_vgb_props
        for item in props.groups:
            if self.action == 'SELECT':
                item.selected = True
            elif self.action == 'DESELECT':
                item.selected = False
            else:
                item.selected = not item.selected
        return {'FINISHED'}


class XNEKO_OT_vgb_clear_armature(bpy.types.Operator):
    bl_idname = "xneko.vgb_clear_armature"
    bl_label = "Clear Target Armature"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.xneko_vgb_props.armature = None
        return {'FINISHED'}


# ============================================================
# UI List
# ============================================================
class XNEKO_UL_vgb_groups(bpy.types.UIList):
    def draw_item(self, context, layout, data, item,
                  icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "selected", text="")
            row.label(text=item.name, icon='GROUP_VERTEX')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.prop(item, "selected", text="")


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_xneko_vgb(bpy.types.Panel):
    bl_label = "Vertex Group to Bones"
    bl_idname = "VIEW3D_PT_xneko_vgb"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    # No poll -> the panel header is always visible.

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # Case 1: no object selected at all
        if obj is None:
            box = layout.box()
            box.label(text="Select a mesh object", icon='INFO')
            return

        # Case 2: not a mesh
        if obj.type != 'MESH':
            box = layout.box()
            box.label(text="Not a mesh object", icon='INFO')
            return

        props = context.scene.xneko_vgb_props

        # Case 3: mesh without vertex groups
        if len(obj.vertex_groups) == 0:
            box = layout.box()
            box.label(text="This mesh has no vertex groups", icon='INFO')
            return

        # Case 4: normal
        # ---------- Target armature ----------
        box = layout.box()
        box.label(text="Target Armature", icon='ARMATURE_DATA')

        row = box.row(align=True)
        row.prop(props, "armature", text="")
        sub = row.row(align=True)
        sub.enabled = props.armature is not None
        sub.operator("xneko.vgb_clear_armature", text="", icon='X')

        if props.armature is None:
            box.label(text="Empty -> Create new armature", icon='INFO')
            box.prop(props, "collection_name")
        else:
            box.label(
                text=f"Bones will be appended to: {props.armature.name}",
                icon='CHECKMARK',
            )

        layout.separator()

        # ---------- Parameters ----------
        col = layout.column(align=True)
        col.prop(props, "threshold")
        col.prop(props, "bone_length")
        col.prop(props, "show_in_front")

        layout.separator()

        # ---------- Vertex group list ----------
        box = layout.box()
        box.label(text="Vertex Groups (check to generate)",
                  icon='GROUP_VERTEX')

        if len(props.groups) == 0:
            box.label(text="(No vertex groups)", icon='INFO')
        else:
            checked = sum(1 for it in props.groups if it.selected)
            box.label(text=f"{checked} / {len(props.groups)} selected")

            box.template_list(
                "XNEKO_UL_vgb_groups", "xneko_vgb_groups",
                props, "groups",
                props, "active_group_index",
                rows=6,
            )

            row = box.row(align=True)
            row.operator("xneko.vgb_select", text="All").action = 'SELECT'
            row.operator("xneko.vgb_select", text="None").action = 'DESELECT'
            row.operator("xneko.vgb_select", text="Invert").action = 'INVERT'

        # ---------- Generate button ----------
        has_selected = any(item.selected for item in props.groups)
        row = layout.row()
        row.scale_y = 1.5
        row.enabled = has_selected
        row.operator("xneko.vgb_generate", icon='BONE_DATA')

        if not has_selected:
            layout.label(text="Select at least one vertex group", icon='INFO')


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_VGBGroupItem,
    XNEKO_VGBProperties,
    XNEKO_UL_vgb_groups,
    XNEKO_OT_vgb_generate,
    XNEKO_OT_vgb_select,
    XNEKO_OT_vgb_clear_armature,
    VIEW3D_PT_xneko_vgb,
)

scene_props = {
    "xneko_vgb_props": bpy.props.PointerProperty(type=XNEKO_VGBProperties),
}


# ============================================================
# Lifecycle
# ============================================================
def on_load():
    """Attach the depsgraph handler when the tool is enabled."""
    if _xneko_vgb_depsgraph_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(
            _xneko_vgb_depsgraph_handler
        )


def on_unload():
    """Detach the depsgraph handler when the tool is disabled."""
    try:
        bpy.app.handlers.depsgraph_update_post.remove(
            _xneko_vgb_depsgraph_handler
        )
    except Exception:
        pass