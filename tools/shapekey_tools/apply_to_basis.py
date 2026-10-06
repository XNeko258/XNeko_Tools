import bpy


tool_name = "Swap Shapekey with Basis"
tool_default_enabled = True


# ---------------- UI List ----------------
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


# ---------------- Operator ----------------
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
        key_blocks = obj.data.shape_keys.key_blocks
        if len(key_blocks) < 2:
            return False
        idx = obj.active_shape_key_index
        return 0 < idx < len(key_blocks)

    def execute(self, context):
        obj = context.object
        shape_keys = obj.data.shape_keys
        key_blocks = shape_keys.key_blocks
        active_index = obj.active_shape_key_index

        # ---------- Defensive checks ----------
        if not 0 < active_index < len(key_blocks):
            self.report({'ERROR'}, "Please select a non-Basis shape key")
            return {'CANCELLED'}

        basis = key_blocks[0]
        target = key_blocks[active_index]
        target_name = target.name

        vertex_count = len(basis.data)
        if vertex_count == 0:
            self.report({'ERROR'}, "Mesh has no vertices")
            return {'CANCELLED'}

        if vertex_count != len(target.data):
            self.report({'ERROR'},
                        "Vertex count mismatch between Basis and target")
            return {'CANCELLED'}

        # ---------- Fast bulk swap ----------
        flat_len = vertex_count * 3
        basis_coords = [0.0] * flat_len
        target_coords = [0.0] * flat_len

        basis.data.foreach_get("co", basis_coords)
        target.data.foreach_get("co", target_coords)

        basis.data.foreach_set("co", target_coords)
        target.data.foreach_set("co", basis_coords)

        # ---------- Reset values so visible shape = new Basis ----------
        for kb in key_blocks:
            kb.value = 0.0

        obj.data.update_tag()

        # ---------- Rebuild Blender's internal reference mesh ----------
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

        # Make sure we are in Object mode before toggling
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


# ---------------- Panel ----------------
class VIEW3D_PT_shapekey_apply_to_basis(bpy.types.Panel):
    bl_label = "Swap Shapekey with Basis"
    bl_idname = "VIEW3D_PT_shapekey_apply_to_basis"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None
            and obj.type == 'MESH'
            and obj.data.shape_keys is not None
        )

    def draw(self, context):
        layout = self.layout
        obj = context.object
        key_blocks = obj.data.shape_keys.key_blocks

        # ---------- Shape key list (synced with Properties panel) ----------
        row = layout.row()
        row.template_list(
            "SHAPEKEY_UL_list", "shapekey_list",
            obj.data.shape_keys, "key_blocks",
            obj, "active_shape_key_index",
            rows=4,
        )

        layout.separator()

        # ---------- Selected info ----------
        active_index = obj.active_shape_key_index
        box = layout.box()
        if 0 < active_index < len(key_blocks):
            box.label(
                text=f"Selected: {key_blocks[active_index].name}",
                icon='SHAPEKEY_DATA',
            )
            box.label(text="Will be swapped with Basis",
                      icon='ARROW_LEFTRIGHT')
        else:
            box.label(text="Select a non-Basis shape key", icon='INFO')

        # ---------- Swap button ----------
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