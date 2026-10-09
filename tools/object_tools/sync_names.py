import bpy


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "sync_names"
tool_name = "Sync Data Names"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Operator
# ============================================================
class XNEKO_OT_sync_data_names(bpy.types.Operator):
    bl_idname = "xneko.sync_data_names"
    bl_label = "Sync Data Names to Objects"
    bl_description = "Rename mesh data blocks to match their object names"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        targets = context.selected_objects
        if not targets:
            self.report({'ERROR'}, "No objects selected")
            return {'CANCELLED'}

        total = 0

        for obj in targets:
            data = obj.data
            if data is None:
                continue

            if data.name != obj.name:
                data.name = obj.name
                total += 1

            if hasattr(data, "shape_keys") and data.shape_keys is not None:
                if data.shape_keys.name != obj.name:
                    data.shape_keys.name = obj.name

        self.report({'INFO'}, f"Synced {total} data block name(s)")
        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_xneko_sync_data_names(bpy.types.Panel):
    bl_label = "Sync Data Names"
    bl_idname = "VIEW3D_PT_xneko_sync_data_names"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout

        mismatch_count = 0
        for obj in context.selected_objects:
            data = obj.data
            if data is not None and data.name != obj.name:
                mismatch_count += 1

        box = layout.box()
        if mismatch_count:
            box.label(
                text=f"{mismatch_count} object(s) need syncing",
                icon='INFO',
            )
        else:
            box.label(text="All data names are in sync", icon='CHECKMARK')

        layout.operator(
            "xneko.sync_data_names",
            text="Sync Data Names",
            icon='OBJECT_DATA',
        )


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_OT_sync_data_names,
    VIEW3D_PT_xneko_sync_data_names,
)
