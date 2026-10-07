import bpy
import math
from mathutils import Vector, Matrix
from bpy.props import EnumProperty, FloatProperty, BoolProperty


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "quick_rotate"
tool_name = "Quick Bone Rotate"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Enum items
# ============================================================
_ORIENT_ITEMS = [
    ('GLOBAL', "Global", "Rotate around world axes"),
    ('NORMAL', "Normal", "Rotate around each bone's local axes"),
]

_AXIS_ITEMS = [
    ('X', "X", "Local X axis"),
    ('Y', "Y", "Local Y axis"),
    ('Z', "Z", "Local Z axis"),
]

_PIVOT_ITEMS = [
    ('HEAD',   "Bone Origin", "Rotate around each bone's head"),
    ('TAIL',   "Bone Tail",   "Rotate around each bone's tail"),
    ('CENTER', "Bone Center", "Rotate around each bone's center"),
]

_WORLD_AXES = {
    'X': Vector((1.0, 0.0, 0.0)),
    'Y': Vector((0.0, 1.0, 0.0)),
    'Z': Vector((0.0, 0.0, 1.0)),
}


# ============================================================
# Math helpers
# ============================================================
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


# ============================================================
# UI PropertyGroup
# ------------------------------------------------------------
# All settings persist per scene. The PropertyGroup itself is the
# source of truth -- no shadow copy in a module-level dict.
# ============================================================
def _on_orientation_change(self, context):
    # NORMAL space requires pivot == HEAD
    if self.orientation == 'NORMAL' and self.pivot != 'HEAD':
        self.pivot = 'HEAD'


class XNEKO_QuickRotateUI(bpy.types.PropertyGroup):
    orientation: EnumProperty(
        name="Space",
        items=_ORIENT_ITEMS,
        default='GLOBAL',
        update=_on_orientation_change,
    )
    axis: EnumProperty(
        name="Axis",
        items=_AXIS_ITEMS,
        default='X',
    )
    pivot: EnumProperty(
        name="Pivot",
        items=_PIVOT_ITEMS,
        default='HEAD',
    )
    angle: FloatProperty(
        name="Angle",
        default=90.0,
    )
    return_to_pose: BoolProperty(
        name="Return to Pose Mode",
        description=(
            "After rotating, switch back to Pose mode if the "
            "operator was started from Pose mode"
        ),
        default=False,
    )


# ============================================================
# Operator
# ============================================================
class XNEKO_OT_quick_rotate(bpy.types.Operator):
    bl_idname = "xneko.quick_rotate"
    bl_label = "Rotate Selected Bones"
    bl_description = (
        "Rotate selected bones around a chosen axis and pivot. "
        "Works in Pose mode and Edit Armature mode"
    )
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

        ui = context.scene.xneko_quick_rotate_ui
        mode = context.mode
        return_to_pose = ui.return_to_pose

        # ---- Ensure we have a valid selection in EDIT mode ----
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

        axis = ui.axis
        orient = ui.orientation
        pivot_mode = ui.pivot
        angle_rad = math.radians(ui.angle)

        # NORMAL space: pivot is always the bone head
        if orient == 'NORMAL':
            pivot_mode = 'HEAD'

        # ------------------------------------------------------------
        # NORMAL + Y: pure roll adjustment
        # ------------------------------------------------------------
        if orient == 'NORMAL' and axis == 'Y':
            count = 0
            for eb in obj.data.edit_bones:
                if eb.select:
                    eb.roll += angle_rad
                    count += 1
            obj.data.update_tag()
            self.report(
                {'INFO'},
                f"Adjusted Roll of {count} bone(s) "
                f"by {ui.angle} degrees",
            )

        # ------------------------------------------------------------
        # General case: rotate heads/tails around the pivot
        # ------------------------------------------------------------
        else:
            arm_rot_inv = obj.matrix_world.to_3x3().inverted()
            count = 0

            for eb in obj.data.edit_bones:
                if not eb.select:
                    continue

                head_a = eb.head.copy()
                tail_a = eb.tail.copy()

                if pivot_mode == 'TAIL':
                    pivot_a = tail_a.copy()
                elif pivot_mode == 'CENTER':
                    pivot_a = (head_a + tail_a) * 0.5
                else:
                    pivot_a = head_a.copy()

                bx, by, bz = _bone_local_axes(eb)

                if orient == 'GLOBAL':
                    axis_a = (arm_rot_inv @ _WORLD_AXES[axis]).normalized()
                else:  # NORMAL
                    if axis == 'X':
                        axis_a = bx
                    elif axis == 'Y':
                        axis_a = by
                    else:
                        axis_a = bz

                rot_mat = Matrix.Rotation(angle_rad, 3, axis_a)

                new_head = rot_mat @ (head_a - pivot_a) + pivot_a
                new_tail = rot_mat @ (tail_a - pivot_a) + pivot_a
                new_z = (rot_mat @ bz).normalized()

                eb.head = new_head
                eb.tail = new_tail
                eb.align_roll(new_z)

                count += 1

            obj.data.update_tag()
            self.report(
                {'INFO'},
                f"Rotated {count} bone(s) around {axis} "
                f"by {ui.angle} degrees",
            )

        if return_to_pose:
            try:
                bpy.ops.object.mode_set(mode='POSE')
            except RuntimeError:
                pass

        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_xneko_quick_rotate(bpy.types.Panel):
    bl_label = "Quick Bone Rotate"
    bl_idname = "VIEW3D_PT_xneko_quick_rotate"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    # No poll -> header always visible.

    def draw(self, context):
        layout = self.layout
        obj = context.object

        # Case 1: no object selected
        if obj is None:
            box = layout.box()
            box.label(text="No object selected", icon='INFO')
            return

        # Case 2: not an armature
        if obj.type != 'ARMATURE':
            box = layout.box()
            box.label(text="Not an armature object", icon='INFO')
            return

        # Case 3: wrong mode
        if context.mode not in {'POSE', 'EDIT_ARMATURE'}:
            box = layout.box()
            box.label(text="Use in Pose or Edit mode", icon='INFO')
            return

        ui = context.scene.xneko_quick_rotate_ui

        col = layout.column(align=True)
        col.prop(ui, "orientation")
        col.prop(ui, "axis")

        # Pivot is only meaningful in GLOBAL space
        pivot_row = col.row()
        pivot_row.enabled = (ui.orientation == 'GLOBAL')
        pivot_row.prop(ui, "pivot")

        col.prop(ui, "angle", text="Angle")
        col.prop(ui, "return_to_pose")

        layout.separator()
        layout.operator(
            "xneko.quick_rotate",
            icon='DRIVER_ROTATIONAL_DIFFERENCE',
        )


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_QuickRotateUI,
    XNEKO_OT_quick_rotate,
    VIEW3D_PT_xneko_quick_rotate,
)

scene_props = {
    "xneko_quick_rotate_ui": bpy.props.PointerProperty(
        type=XNEKO_QuickRotateUI,
    ),
}