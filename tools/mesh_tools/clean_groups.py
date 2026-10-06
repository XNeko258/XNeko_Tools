import bpy
import bmesh


tool_name = "Clean Vertex Groups"
tool_default_enabled = True


def _is_group_referenced(obj, vg_name):
    """Return True if the vertex group is used by a modifier or a shape key."""
    for mod in obj.modifiers:
        if hasattr(mod, "vertex_group") and mod.vertex_group == vg_name:
            return True
        if hasattr(mod, "vertex_group_mass") and mod.vertex_group_mass == vg_name:
            return True
    if obj.data.shape_keys:
        for kb in obj.data.shape_keys.key_blocks:
            if kb.vertex_group == vg_name:
                return True
    return False


class Mesh_OT_remove_empty_vertex_groups(bpy.types.Operator):
    bl_idname = "rig.remove_empty_vertex_groups"
    bl_label = "Remove Empty Vertex Groups"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        targets = [o for o in context.selected_objects if o.type == 'MESH']

        if not targets:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        total_removed = 0
        total_objects = 0

        for obj in targets:
            removed = 0

            bm = bmesh.new()
            bm.from_mesh(obj.data)
            deform_layer = bm.verts.layers.deform.active
            used_indices = set()
            if deform_layer is not None:
                for v in bm.verts:
                    for group_index, weight in v[deform_layer].items():
                        if weight > 0.0:
                            used_indices.add(group_index)
            bm.free()

            for vg in reversed(obj.vertex_groups[:]):
                if vg.index not in used_indices:
                    if _is_group_referenced(obj, vg.name):
                        continue
                    obj.vertex_groups.remove(vg)
                    removed += 1

            if removed > 0:
                total_objects += 1
                total_removed += removed
                print(f"[XNeko] {obj.name}: removed {removed} empty group(s)")

        self.report(
            {'INFO'},
            f"Removed {total_removed} empty group(s) from {total_objects} object(s)",
        )
        return {'FINISHED'}


class VIEW3D_PT_vertex_group_tools(bpy.types.Panel):
    bl_label = "Clean Vertex Groups"
    bl_idname = "VIEW3D_PT_vertex_group_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        layout.operator(
            "rig.remove_empty_vertex_groups",
            text="Remove Empty",
            icon='GROUP_VERTEX',
        )


classes = (
    Mesh_OT_remove_empty_vertex_groups,
    VIEW3D_PT_vertex_group_tools,
)