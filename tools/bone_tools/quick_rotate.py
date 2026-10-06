import bpy
import math
from mathutils import Vector, Matrix
from bpy.props import EnumProperty, FloatProperty, BoolProperty


tool_name = "Quick Bone Rotate"
tool_default_enabled = True


_settings = {
    "orientation": 'GLOBAL',
    "axis": 'X',
    "pivot": 'HEAD',
    "angle": 90.0,
    "return_to_pose": False,
}

_orient_items = [('GLOBAL', "Global", ""), ('NORMAL', "Normal", "")]
_axis_items = [('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")]
_pivot_items = [
    ('HEAD',   "Bone Origin", "Rotate around each bone's head"),
    ('TAIL',   "Bone Tail",   "Rotate around each bone's tail"),
    ('CENTER', "Bone Center", "Rotate around each bone's center"),
]

_WORLD_AXES = {
    'X': Vector((1.0, 0.0, 0.0)),
    'Y': Vector((0.0, 1.0, 0.0)),
    'Z': Vector((0.0, 0.0, 1.0)),
}


def _on_orientation_change(ui_self):
    _settings["orientation"] = ui_self.orientation
    if ui_self.orientation == 'NORMAL' and ui_self.pivot != 'HEAD':
        ui_self.pivot = 'HEAD'


def _bone_local_axes(eb):
    """Return (x_axis, y_axis, z_axis) of an edit bone in armature space.

    Follows Blender's vec_roll_to_mat3 convention.
    """
    y_vec = eb.tail - eb.head
    if y_vec.length < 1e-10:
        y_vec = Vector((0.0, 1.0, 0.0))
    else:
        y_vec = y_vec.normalized()

    nx, ny, nz = y_vec.x, y_vec.y, y_vec.z

    theta = 1.0 + ny
    if theta < 1e-5:
        x0 = Vector((-1.0, 0.0, 0.0))
        z0 = Vector((0.0, 0.0, 1.0))
    else:
        f1 = 1.0 / theta
        f2 = nz * f1
        f3 = nx * f2
        x0 = Vector((1.0 - nx * nx * f1, -nx, -f3)).normalized()
        z0 = Vector((-f3, -nz, 1.0 - nz * nz * f1)).normalized()

    cos_r = math.cos(eb.roll)
    sin_r = math.sin(eb.roll)

    x_vec = (x0 * cos_r - z0 * sin_r).normalized()
    z_vec = (x0 * sin_r + z0 * cos_r).normalized()

    return x_vec, y_vec, z_vec


class QuickRotateUI(bpy.types.PropertyGroup):
    orientation: EnumProperty(
        name="Space",
        items=_orient_items,
        default='GLOBAL',
        update=lambda self, ctx: _on_orientation_change(self),
    )
    axis: EnumProperty(
        name="Axis",
        items=_axis_items,
        default='X',
        update=lambda self, ctx: _settings.update(axis=self.axis),
    )
    pivot: EnumProperty(
        name="Pivot",
        items=_pivot_items,
        default='HEAD',
        update=lambda self, ctx: _settings.update(pivot=self.pivot),
    )
    angle: FloatProperty(
        name="Angle",
        default=90.0,
        update=lambda self, ctx: _settings.update(angle=self.angle),
    )
    return_to_pose: BoolProperty(
        name="Return to Pose Mode",
        default=False,
        update=lambda self, ctx: _settings.update(return_to_pose=self.return_to_pose),
    )


class RIG_OT_quick_edit_bone_rotate(bpy.types.Operator):
    bl_idname = "rig.quick_edit_bone_rotate"
    bl_label = "Rotate Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'ARMATURE':
            return False
        mode = context.mode
        if mode == 'POSE':
            return bool(context.selected_pose_bones)
        if mode == 'EDIT_ARMATURE':
            return any(eb.select for eb in obj.data.edit_bones)
        return False

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select an armature object")
            return {'CANCELLED'}

        mode = context.mode
        return_to_pose = _settings["return_to_pose"]

        if mode == 'POSE':
            bone_names = [pb.name for pb in context.selected_pose_bones]
            if not bone_names:
                self.report({'ERROR'}, "No bones selected")
                return {'CANCELLED'}

            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')

            for eb in obj.data.edit_bones:
                selected = eb.name in bone_names
                eb.select = selected
                eb.select_head = selected
                eb.select_tail = selected

        elif mode == 'EDIT_ARMATURE':
            if not any(eb.select for eb in obj.data.edit_bones):
                self.report({'ERROR'}, "No bones selected")
                return {'CANCELLED'}
        else:
            self.report({'ERROR'}, "Use in Pose or Edit mode")
            return {'CANCELLED'}

        axis = _settings["axis"]
        orient = _settings["orientation"]
        pivot_mode = _settings["pivot"]
        angle_rad = math.radians(_settings["angle"])

        # NORMAL space: pivot must be HEAD
        if orient == 'NORMAL':
            pivot_mode = 'HEAD'

        # NORMAL + Y: just adjust roll
        if orient == 'NORMAL' and axis == 'Y':
            count = 0
            for eb in obj.data.edit_bones:
                if eb.select:
                    eb.roll += angle_rad
                    count += 1
            obj.data.update_tag()
            self.report({'INFO'},
                        f"Adjusted Roll of {count} bone(s) by {_settings['angle']} degrees")
        else:
            arm_rot_inv = obj.matrix_world.to_3x3().inverted()
            count = 0

            for eb in obj.data.edit_bones:
                if not eb.select:
                    continue

                head_a = eb.head.copy()
                tail_a = eb.tail.copy()

                # Pivot in armature space
                if pivot_mode == 'TAIL':
                    pivot_a = tail_a.copy()
                elif pivot_mode == 'CENTER':
                    pivot_a = (head_a + tail_a) * 0.5
                else:
                    pivot_a = head_a.copy()

                # Current local axes (armature space)
                bx, by, bz = _bone_local_axes(eb)

                # Axis direction in armature space
                if orient == 'GLOBAL':
                    axis_a = (arm_rot_inv @ _WORLD_AXES[axis]).normalized()
                else:  # NORMAL
                    if axis == 'X':
                        axis_a = bx
                    elif axis == 'Y':
                        axis_a = by
                    else:
                        axis_a = bz

                # Rotation matrix
                rot_mat = Matrix.Rotation(angle_rad, 3, axis_a)

                # New head / tail
                new_head = rot_mat @ (head_a - pivot_a) + pivot_a
                new_tail = rot_mat @ (tail_a - pivot_a) + pivot_a

                # New local Z (rotated, still in armature space)
                new_z = (rot_mat @ bz).normalized()

                # Apply new position and re-align roll for continuity
                eb.head = new_head
                eb.tail = new_tail
                eb.align_roll(new_z)

                count += 1

            obj.data.update_tag()
            self.report({'INFO'},
                        f"Rotated {count} bone(s) around {axis} by {_settings['angle']} degrees")

        if mode == 'POSE' and return_to_pose:
            bpy.ops.object.mode_set(mode='POSE')

        return {'FINISHED'}


class VIEW3D_PT_quick_edit_bone_rotate(bpy.types.Panel):
    bl_label = "Quick Bone Rotate"
    bl_idname = "VIEW3D_PT_quick_edit_bone_rotate"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        ui = context.scene.quick_rotate_ui

        col = layout.column(align=True)
        col.prop(ui, "orientation")
        col.prop(ui, "axis")

        # Pivot row: grey out in NORMAL space
        pivot_row = col.row()
        pivot_row.enabled = (ui.orientation == 'GLOBAL')
        pivot_row.prop(ui, "pivot")

        col.prop(ui, "angle", text="Angle")
        col.prop(ui, "return_to_pose")

        layout.separator()
        layout.operator(
            "rig.quick_edit_bone_rotate",
            icon='DRIVER_ROTATIONAL_DIFFERENCE',
        )


classes = (
    QuickRotateUI,
    RIG_OT_quick_edit_bone_rotate,
    VIEW3D_PT_quick_edit_bone_rotate,
)

scene_props = {
    "quick_rotate_ui": bpy.props.PointerProperty(type=QuickRotateUI),
}