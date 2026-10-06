import bpy
from bpy.props import BoolProperty

# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_name = "Swap Shapekey with Basis"
tool_default_enabled = True
blender_version_min = (4, 1, 0)  # Requires ShapeKey.points

preference_props = {
    "reset_values_after_swap": BoolProperty(
        name="Reset Values After Swap",
        description="Set all shape key values to 0 after swapping",
        default=True,
    ),
}


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _get_prefs():
    """Return this tool's preference namespace, or None."""
    import importlib
    top = __name__.split(".")[0]
    try:
        prefs_mod = importlib.import_module(top + ".preferences")
    except ImportError:
        return None
    return prefs_mod.get_tool_prefs(__name__)


def _find_active_shape_key(obj):
    """
    Return the currently selected non-Basis shape key,
    or None if no valid selection exists.
    """
    sk = obj.data.shape_keys
    if sk is None:
        return None

    key_blocks = sk.key_blocks
    if len(key_blocks) < 2:
        return None

    # Try the official active index first
    idx = obj.active_shape_key_index
    if 0 < idx < len(key_blocks):
        return key_blocks[idx]

    # Fallback: scan for the key with the highest value > 0
    best = None
    best_val = 0.0
    for kb in key_blocks[1:]:  # skip Basis
        if kb.value > best_val:
            best_val = kb.value
            best = kb
    return best


# ------------------------------------------------------------
# Operator
# ------------------------------------------------------------
class MESH_OT_swap_shapekey_with_basis(bpy.types.Operator):
    bl_idname = "xneko.swap_shapekey_with_basis"
    bl_label = "Swap Shapekey with Basis"
    bl_description = (
        "Swap the vertex data of the selected shape key with the Basis. "
        "The selected key becomes the new basis shape, "
        "and the old basis becomes the selected key"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            return False
        if obj.data.shape_keys is None:
            return False
        if len(obj.data.shape_keys.key_blocks) < 2:
            return False
        return _find_active_shape_key(obj) is not None

    def execute(self, context):
        obj = context.object
        shape_keys = obj.data.shape_keys
        key_blocks = shape_keys.key_blocks

        # ---------- Resolve target ----------
        basis = key_blocks[0]
        target = _find_active_shape_key(obj)

        if target is None:
            self.report({'ERROR'}, "Please select a non-Basis shape key")
            return {'CANCELLED'}

        target_name = target.name

        # ---------- Validation ----------
        vertex_count = len(basis.data)
        if vertex_count == 0:
            self.report({'ERROR'}, "Mesh has no vertices")
            return {'CANCELLED'}

        if vertex_count != len(target.data):
            self.report(
                {'ERROR'},
                "Vertex count mismatch between Basis and target",
            )
            return {'CANCELLED'}

        # ---------- Fast bulk swap via ShapeKey.points ----------
        flat_len = vertex_count * 3
        basis_coords = [0.0] * flat_len
        target_coords = [0.0] * flat_len

        # ShapeKey.points is optimized for foreach_get/set in Blender 4.1+
        basis.points.foreach_get("co", basis_coords)
        target.points.foreach_get("co", target_coords)

        basis.points.foreach_set("co", target_coords)
        target.points.foreach_set("co", basis_coords)

        # ---------- Optionally reset values ----------
        prefs = _get_prefs()
        if prefs and prefs.reset_values_after_swap:
            for kb in key_blocks:
                kb.value = 0.0

        obj.data.update_tag()

        # ---------- Rebuild reference mesh ----------
        self._rebuild_reference_mesh(context, obj)

        self.report({'INFO'}, f"Swapped Basis with '{target_name}'")
        return {'FINISHED'}

    @staticmethod
    def _rebuild_reference_mesh(context, obj):
        """Force Blender to rebuild its internal reference mesh.

        Without this, newly added shape keys would inherit the ORIGINAL
        mesh data instead of the current Basis.
        """
        view_layer = context.view_layer

        if obj.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except RuntimeError:
                pass

        prev_active = view_layer.objects.active
        changed_active = prev_active != obj

        if changed_active:
            view_layer.objects.active = obj

        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass

        if changed_active and prev_active is not None:
            try:
                view_layer.objects.active = prev_active
            except Exception:
                pass


# ------------------------------------------------------------
# UI List
# ------------------------------------------------------------
class SHAPEKEY_UL_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "value", text="")
            row.prop(item, "name", text="", emboss=False,
                     icon='SHAPEKEY_DATA')
            row.prop(item, "mute", text="")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='SHAPEKEY_DATA')


# ------------------------------------------------------------
# Panel
# ------------------------------------------------------------
class VIEW3D_PT_shapekey_apply_to_basis(bpy.types.Panel):
    bl_label = "Swap Shapekey with Basis"
    bl_idname = "VIEW3D_PT_shapekey_apply_to_basis"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    # No poll -> the panel header is always visible.

    def draw(self, context):
        layout = self.layout
        obj = context.object

        # Case 1: nothing selected / no active object
        if obj is None:
            box = layout.box()
            box.label(text="No object selected", icon='INFO')
            return

        # Case 2: selected object is not a mesh
        if obj.type != 'MESH':
            box = layout.box()
            box.label(text="Not a mesh object", icon='INFO')
            return

        # Case 3: mesh without shape keys
        if obj.data.shape_keys is None:
            box = layout.box()
            box.label(text="No shape keys", icon='INFO')
            return

        # Case 4: normal — mesh with shape keys
        key_blocks = obj.data.shape_keys.key_blocks

        row = layout.row()
        row.template_list(
            "SHAPEKEY_UL_list", "shapekey_list",
            obj.data.shape_keys, "key_blocks",
            obj, "active_shape_key_index",
            rows=4,
        )

        layout.separator()

        target = _find_active_shape_key(obj)
        box = layout.box()
        if target is not None:
            box.label(text=f"Selected: {target.name}", icon='SHAPEKEY_DATA')
            box.label(text="Will be swapped with Basis",
                      icon='ARROW_LEFTRIGHT')
        else:
            box.label(text="Select a non-Basis shape key", icon='INFO')

        layout.separator()
        layout.operator(
            "xneko.swap_shapekey_with_basis",
            text="Swap with Basis",
            icon='ARROW_LEFTRIGHT',
        )


classes = (
    SHAPEKEY_UL_list,
    MESH_OT_swap_shapekey_with_basis,
    VIEW3D_PT_shapekey_apply_to_basis,
)