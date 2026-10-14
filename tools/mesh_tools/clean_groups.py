import bpy
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
#
# Empty groups (no vertex assigned) are always removed. The option
# below extends that to zero-weight groups, which some rigs keep
# intentionally as reserved slots, so it defaults to off.
# ------------------------------------------------------------
scene_props = {
    "xneko_clean_groups_include_zero": BoolProperty(
        name="Zero-Weight Groups",
        description=(
            "Also remove groups whose vertices all have weight 0"
        ),
        default=False,
    ),
}


# ============================================================
# Helpers
# ============================================================
def _collect_referenced_groups(obj):
    """Return the set of vertex-group names referenced by this
    object's modifiers or shape keys.

    Collected in one pass so the removal loop can do O(1) lookups
    instead of rescanning modifiers per candidate group.
    """
    referenced = set()

    for mod in obj.modifiers:
        # Most deform modifiers expose 'vertex_group'; a few (e.g.
        # Smooth, Corrective Smooth) also expose 'vertex_group_mass'.
        # Empty string means "no group assigned".
        name = getattr(mod, "vertex_group", "")
        if name:
            referenced.add(name)
        name = getattr(mod, "vertex_group_mass", "")
        if name:
            referenced.add(name)

    sk = getattr(obj.data, "shape_keys", None)
    if sk is not None:
        for kb in sk.key_blocks:
            if kb.vertex_group:
                referenced.add(kb.vertex_group)

    return referenced


def _scan_group_usage(obj):
    """Return (empty_names, zero_weight_names) sets for obj.

    Reads weights from MeshVertex.groups instead of bmesh's deform
    layer. The deform layer drops explicit 0.0 assignments, which
    made zero-weight detection silently ineffective. MeshVertex
    .groups preserves them.
    """
    weight_map = {}
    for v in obj.data.vertices:
        for ge in v.groups:
            weight_map.setdefault(ge.group, []).append(ge.weight)

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

        meshes = [
            o for o in (context.selected_objects or [])
            if o.type == 'MESH'
        ]
        if not meshes:
            active = context.object
            if active is None or active.type != 'MESH':
                return False
            meshes = [active]

        # If every candidate has no groups at all, there is nothing
        # this operator could do.
        return any(len(o.vertex_groups) > 0 for o in meshes)

    def execute(self, context):
        scene = context.scene
        include_zero = bool(scene.xneko_clean_groups_include_zero)

        targets = [
            o for o in (context.selected_objects or [])
            if o.type == 'MESH'
        ]
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

            # Empty groups are always cleaned; zero-weight groups
            # only when the user opts in.
            to_remove = set(empty_names)
            if include_zero:
                to_remove |= zero_names

            if not to_remove:
                continue

            referenced = _collect_referenced_groups(obj)
            vg_map = {vg.name: vg for vg in obj.vertex_groups}

            removed = 0
            for name in to_remove:
                if name in referenced:
                    continue
                vg = vg_map.get(name)
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

        # Option first, so its effect on the button below is obvious.
        layout.prop(scene, "xneko_clean_groups_include_zero")

        layout.operator(
            "xneko.remove_empty_vertex_groups",
            text="Clean Empty Groups",
            icon='GROUP_VERTEX',
        )


classes = (
    Mesh_OT_remove_empty_vertex_groups,
    VIEW3D_PT_vertex_group_tools,
)