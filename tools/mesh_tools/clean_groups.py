import bpy
import bmesh
from bpy.props import BoolProperty


tool_id = "clean_groups"
tool_name = "Clean Vertex Groups"
tool_default_enabled = True

# Version compatibility
blender_version_min = (4, 0, 0)
# blender_version_max = (4, 3, 0)   # optional


# ------------------------------------------------------------
# Scene properties: N-panel operation parameters.
#
# These are intentionally NOT preference_props, so they are not
# captured by or applied from presets. They describe what the
# current click of the button should do, not a persistent
# configuration.
# ------------------------------------------------------------
scene_props = {
    "xneko_clean_groups_empty": BoolProperty(
        name="Remove Empty Groups",
        description="Remove vertex groups that no vertex is assigned to",
        default=True,
    ),
    "xneko_clean_groups_zero": BoolProperty(
        name="Remove Zero-Weight Groups",
        description=(
            "Remove vertex groups whose assigned vertices all have weight 0"
        ),
        default=True,
    ),
}


# ============================================================
# Helpers
# ============================================================
def _is_group_referenced(obj, vg_name):
    for mod in obj.modifiers:
        if hasattr(mod, "vertex_group") and mod.vertex_group == vg_name:
            return True
        if hasattr(mod, "vertex_group_mass") and mod.vertex_group_mass == vg_name:
            return True

    sk = getattr(obj.data, "shape_keys", None)
    if sk is not None:
        for kb in sk.key_blocks:
            if kb.vertex_group == vg_name:
                return True
    return False


def _scan_group_usage(obj):
    """Return (empty_names, zero_weight_names) sets for obj."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    deform_layer = bm.verts.layers.deform.active
    weight_map = {}
    if deform_layer is not None:
        for v in bm.verts:
            for idx, weight in v[deform_layer].items():
                weight_map.setdefault(idx, []).append(weight)
    bm.free()

    empty, zero = set(), set()
    for vg in obj.vertex_groups:
        idx = vg.index
        if idx not in weight_map:
            empty.add(vg.name)
        elif all(w == 0.0 for w in weight_map[idx]):
            zero.add(vg.name)
    return empty, zero


# ============================================================
# Operator
# ============================================================
class Mesh_OT_remove_empty_vertex_groups(bpy.types.Operator):
    bl_idname = "xneko.remove_empty_vertex_groups"
    bl_label = "Clean Vertex Groups"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode not in {'OBJECT', 'EDIT_MESH', 'PAINT_WEIGHT'}:
            return False

        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            active = context.object
            if active is None or active.type != 'MESH':
                return False
            meshes = [active]

        if not any(len(o.vertex_groups) > 0 for o in meshes):
            return False

        scene = context.scene
        if not (scene.xneko_clean_groups_empty
                or scene.xneko_clean_groups_zero):
            return False
        return True

    def execute(self, context):
        scene = context.scene
        clean_empty = bool(scene.xneko_clean_groups_empty)
        clean_zero_weight = bool(scene.xneko_clean_groups_zero)
        if not (clean_empty or clean_zero_weight):
            self.report({'ERROR'}, "Enable at least one cleanup option")
            return {'CANCELLED'}

        targets = [o for o in context.selected_objects if o.type == 'MESH']
        if not targets:
            active = context.object
            if active is not None and active.type == 'MESH':
                targets = [active]
        if not targets:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        total_removed = 0
        total_objects = 0
        for obj in targets:
            empty_names, zero_names = _scan_group_usage(obj)
            to_remove = set()
            if clean_empty:
                to_remove |= empty_names
            if clean_zero_weight:
                to_remove |= zero_names

            removed = 0
            for name in to_remove:
                if _is_group_referenced(obj, name):
                    continue
                vg = obj.vertex_groups.get(name)
                if vg is not None:
                    obj.vertex_groups.remove(vg)
                    removed += 1

            if removed:
                total_objects += 1
                total_removed += removed
                print(f"[XNeko] {obj.name}: removed {removed} group(s)")

        self.report(
            {'INFO'},
            f"Removed {total_removed} group(s) from {total_objects} object(s)",
        )
        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_vertex_group_tools(bpy.types.Panel):
    bl_label = "Clean Vertex Groups"
    bl_idname = "VIEW3D_PT_xneko_vertex_group_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="Clean Options:", icon='TRASH')

        # scene is a real RNA object, so plain layout.prop is correct here.
        box.prop(scene, "xneko_clean_groups_empty")
        box.prop(scene, "xneko_clean_groups_zero")

        if not (scene.xneko_clean_groups_empty
                or scene.xneko_clean_groups_zero):
            row = box.row()
            row.alert = True
            row.label(text="Check at least one option", icon='INFO')

        layout.operator(
            "xneko.remove_empty_vertex_groups",
            text="Clean Groups",
            icon='GROUP_VERTEX',
        )


classes = (
    Mesh_OT_remove_empty_vertex_groups,
    VIEW3D_PT_vertex_group_tools,
)