import bpy


tool_name = "Sync Data Names"
tool_default_enabled = True


class OBJ_OT_sync_data_names(bpy.types.Operator):
    bl_idname = "xneko.sync_data_names"
    bl_label = "Sync Data Names to Objects"
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


class VIEW3D_PT_data_name_tools(bpy.types.Panel):
    bl_label = "Sync Data Names"
    bl_idname = "VIEW3D_PT_data_name_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        layout.operator("xneko.sync_data_names", text="Sync Data Names")


classes = (
    OBJ_OT_sync_data_names,
    VIEW3D_PT_data_name_tools,
)