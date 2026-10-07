import bpy
from bpy.types import Operator, Panel
from bpy.props import BoolProperty
import bmesh
from mathutils import Matrix, Vector
from bpy_extras import view3d_utils

from ._core import RAY_CAST, PARAM_UI, DRAW, LINE, MARK


# ============================================================
# Helpers
# ============================================================
_GLOBAL_TGT_OBJ_NAME = None


def _get_prefs():
    """Return this tool's preference namespace, or None."""
    import importlib
    top = __package__.split(".")[0]
    try:
        prefs_mod = importlib.import_module(top + ".preferences")
    except ImportError:
        return None
    return prefs_mod.get_tool_prefs(__package__)


def _to_rgba(v):
    try:
        return tuple(v)
    except Exception:
        return v


def _set_cursor(context, cursor):
    """Set the mouse cursor, with a fallback for older Blender builds."""
    try:
        context.window.cursor_set(cursor)
    except TypeError:
        try:
            context.window.cursor_set('PAINT_BRUSH')
        except Exception:
            pass


def _ray_cast_to_object(context, event):
    """Return the object under the cursor, or None."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    if region.type != 'WINDOW':
        return None

    coord = (event.mouse_region_x, event.mouse_region_y)
    try:
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    except Exception:
        return None

    depsgraph = context.evaluated_depsgraph_get()
    try:
        result = context.scene.ray_cast(
            depsgraph, origin, direction, distance=1e10,
        )
    except Exception:
        return None

    if result[0]:
        return result[4]  # object
    return None


# ============================================================
# Eyedropper - pick line colors from a viewport object
# ------------------------------------------------------------
# Modal: cursor turns into an eyedropper. Left click on any
# object samples its viewport display color and applies it to
# all three line colors. RMB / ESC cancels.
# ============================================================
class XNEKO_TPA_OT_pick_line_colors(Operator):
    bl_idname = "xneko.tpa_pick_line_colors"
    bl_label = "Pick Line Colors from Viewport"
    bl_description = (
        "Click an object in the 3D viewport to sample its color "
        "and apply it to all three line colors"
    )
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Requires a 3D viewport")
            return {'CANCELLED'}
        _set_cursor(context, 'EYEDROPPER')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return self._cleanup(context, cancelled=True)

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            obj = _ray_cast_to_object(context, event)
            if obj is None:
                self.report({'WARNING'}, "No object under cursor")
                return {'RUNNING_MODAL'}

            color = _to_rgba(obj.color)
            prefs = _get_prefs()
            if prefs is None:
                return self._cleanup(context, cancelled=True)

            try:
                prefs.tpa_line_0_color = color
                prefs.tpa_line_1_color = color
                prefs.tpa_line_2_color = color
            except Exception as e:
                self.report({'ERROR'}, f"Cannot apply color: {e}")
                return self._cleanup(context, cancelled=True)

            self.report({'INFO'}, f"Picked line colors from '{obj.name}'")
            return self._cleanup(context, cancelled=False)

        return {'RUNNING_MODAL'}

    def _cleanup(self, context, cancelled):
        _set_cursor(context, 'DEFAULT')
        return {'CANCELLED' if cancelled else 'FINISHED'}


# ============================================================
# Eyedropper - pick face color from a viewport object
# ============================================================
class XNEKO_TPA_OT_pick_face_color(Operator):
    bl_idname = "xneko.tpa_pick_face_color"
    bl_label = "Pick Face Color from Viewport"
    bl_description = (
        "Click an object in the 3D viewport to sample its color "
        "and apply it to the face overlay color"
    )
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Requires a 3D viewport")
            return {'CANCELLED'}
        _set_cursor(context, 'EYEDROPPER')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return self._cleanup(context, cancelled=True)

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            obj = _ray_cast_to_object(context, event)
            if obj is None:
                self.report({'WARNING'}, "No object under cursor")
                return {'RUNNING_MODAL'}

            color = _to_rgba(obj.color)
            prefs = _get_prefs()
            if prefs is None:
                return self._cleanup(context, cancelled=True)

            try:
                prefs.tpa_face_color = color
            except Exception as e:
                self.report({'ERROR'}, f"Cannot apply color: {e}")
                return self._cleanup(context, cancelled=True)

            self.report({'INFO'}, f"Picked face color from '{obj.name}'")
            return self._cleanup(context, cancelled=False)

        return {'RUNNING_MODAL'}

    def _cleanup(self, context, cancelled):
        _set_cursor(context, 'DEFAULT')
        return {'CANCELLED' if cancelled else 'FINISHED'}


# ============================================================
# Check-selection modal operator
# ============================================================
class XNEKO_TPA_OT_check_selection(Operator):
    bl_idname = "xneko.tpa_check_selection"
    bl_label = "3 Points Align"

    def invoke(self, context, event):
        self.run_align = False
        self.skip_opeator = True
        self.src_param = PARAM_UI('Source Mesh')
        self.tgt_param = PARAM_UI('Target Mesh')

        self.params_table = DRAW(
            draw_type='PARAMS',
            draw_args=(self.src_param, self.tgt_param),
        )
        self.params_table.handle_add()

        width = context.area.width
        self.msg_bottom = DRAW(
            draw_type='TEXT', coords_2d=[width, 25],
        )
        self.msg_bottom.handle_add()

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def obj_selection_validator(self, context):
        objs = context.selected_objects
        mesh_objs = sum(
            1 for o in objs if o.type == 'MESH' and o.mode == 'OBJECT'
        )

        if len(objs) == 0:
            return False, False, '1. Select two meshes to align'
        elif len(objs) > 2 and mesh_objs == 0:
            return False, False, 'Select only two meshes'
        elif len(objs) > 2 and mesh_objs > 0:
            return True, False, 'Select only two meshes'
        elif len(objs) == 2 and mesh_objs == 0:
            return False, False, 'Only mesh objects are supported'
        elif len(objs) == 2 and mesh_objs == 1:
            return True, False, 'Only mesh objects are supported'
        elif len(objs) == 1 and mesh_objs == 0:
            return False, False, 'Only mesh objects are supported'
        elif len(objs) == 1 and mesh_objs == 1:
            return True, False, '2. Shift-select the source mesh'
        elif (len(objs) == 2 and mesh_objs == 2
              and context.active_object not in objs):
            return True, False, 'One selected mesh must be active'
        elif (len(objs) == 2 and mesh_objs == 2
              and context.active_object in objs):
            return True, True, 'Press [Space/Enter] to start linking'
        else:
            return False, False, 'Unexpected state'

    def modal(self, context, event):
        DRAW.update_3d_view()
        if (
            event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
            or (True in {event.shift, event.ctrl, event.alt}
                and event.value == 'PRESS')
        ):
            return {'PASS_THROUGH'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.destructor()
            return {'CANCELLED'}
        elif event.type == 'LEFTMOUSE':
            return {'PASS_THROUGH'}

        (self.tgt_param.ui_enable, self.src_param.ui_enable,
         self.msg_bottom.text) = self.obj_selection_validator(context)

        if self.tgt_param.ui_enable and self.src_param.ui_enable:
            if self.skip_opeator:
                self.run_align = True
                self.destructor()
                return {'FINISHED'}
            elif (event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'}
                  and event.value == 'PRESS'):
                self.run_align = True
                self.destructor()
                return {'FINISHED'}

        self.skip_opeator = False
        return {'RUNNING_MODAL'}

    def destructor(self):
        self.params_table.handle_remove()
        self.msg_bottom.handle_remove()
        if self.run_align:
            bpy.ops.xneko.tpa_align('INVOKE_DEFAULT')


# ============================================================
# Align operator
# ============================================================
class XNEKO_TPA_OT_align(Operator):
    '''3 Points Align'''
    bl_idname = "xneko.tpa_align"
    bl_label = "3 Points Align"
    bl_options = {'REGISTER', 'UNDO'}

    show_origin: BoolProperty(name='Show Origin', default=False)
    match_scale: BoolProperty(name='Match Scale', default=False)
    origin_to_source: BoolProperty(
        name='Origin to Center 2', default=False,
    )
    set_transforms: BoolProperty(
        name='Recalculate Transform', default=False,
    )
    invert_x: BoolProperty(name='X', default=False)
    invert_y: BoolProperty(name='Y', default=False)
    invert_z: BoolProperty(name='Z', default=False)

    def save_props(self, context):
        scene = context.scene
        scene.xneko_tpa_show_origin = self.show_origin
        scene.xneko_tpa_match_scale = self.match_scale
        scene.xneko_tpa_origin_to_source = self.origin_to_source
        scene.xneko_tpa_set_transforms = self.set_transforms
        scene.xneko_tpa_invert_x = self.invert_x
        scene.xneko_tpa_invert_y = self.invert_y
        scene.xneko_tpa_invert_z = self.invert_z

    def load_props(self, context):
        scene = context.scene
        self.show_origin = scene.xneko_tpa_show_origin
        self.match_scale = scene.xneko_tpa_match_scale
        self.origin_to_source = scene.xneko_tpa_origin_to_source
        self.set_transforms = scene.xneko_tpa_set_transforms
        self.invert_x = scene.xneko_tpa_invert_x
        self.invert_y = scene.xneko_tpa_invert_y
        self.invert_z = scene.xneko_tpa_invert_z

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        split = row.split(factor=0.55)
        left_col = split.column(align=True)
        right_col = split.column(align=True)
        left_col.alignment = 'RIGHT'
        right_col.alignment = 'CENTER'

        left_col.label(text='Show Origin')
        right_col.prop(self, 'show_origin', text='')
        left_col.label(text='Match Scale')
        right_col.prop(self, 'match_scale', text='')
        left_col.label(text='Origin to Center 2')
        right_col.prop(self, 'origin_to_source', text='')
        left_col.label(text='Recalculate Transform')
        right_col.prop(self, 'set_transforms', text='')

        left_col.label(text='Invert Origin')
        row = right_col.row(align=True)
        row.enabled = self.set_transforms
        row.prop(self, 'invert_x', text='X')
        row.prop(self, 'invert_y', text='Y')
        row.prop(self, 'invert_z', text='Z')

        self.save_props(context)

    def invoke(self, context, event):
        global _GLOBAL_TGT_OBJ_NAME

        self.load_props(context)
        prefs = _get_prefs()

        face_color = _to_rgba(prefs.tpa_face_color) if prefs else (0, 0.65, 1, 0.2)
        line_0_color = _to_rgba(prefs.tpa_line_0_color) if prefs else (1, 1, 0, 1)
        line_1_color = _to_rgba(prefs.tpa_line_1_color) if prefs else (1, 0.5, 0, 1)
        line_2_color = _to_rgba(prefs.tpa_line_2_color) if prefs else (1, 0, 0, 1)
        select_color = _to_rgba(prefs.tpa_select_color) if prefs else (1, 1, 1, 1)
        cross_size = prefs.tpa_cross_size if prefs else 50
        point_size = prefs.tpa_point_size if prefs else 10
        snap_distance = prefs.tpa_snap_distance if prefs else 20

        self.face_0 = DRAW(draw_type='FACE', color=face_color,
                           coords=[(0, 0, 0)] * 3)
        self.face_1 = DRAW(draw_type='FACE', color=face_color,
                           coords=[(0, 0, 0)] * 3)
        self.face_0.handle_add()
        self.face_1.handle_add()

        self.line_0 = LINE(name='Line 1', id=0, color=line_0_color)
        self.line_1 = LINE(name='Line 2', id=1, color=line_1_color)
        self.line_2 = LINE(name='Line 3', id=2, color=line_2_color)
        self.line_dist_0 = LINE(name='Distance', id=3)
        self.line_dist_1 = LINE(name='Distance', id=4)
        self.mark_0 = MARK(color=select_color, size=cross_size)
        self.mark_1 = MARK(color=select_color, size=cross_size)

        self.all_lines = [self.line_0, self.line_1, self.line_2]
        self.line_id = 0

        self.points_0 = DRAW(draw_type='POINTS', color=line_0_color,
                             size=point_size)
        self.points_1 = DRAW(draw_type='POINTS', color=line_1_color,
                             size=point_size)
        self.points_2 = DRAW(draw_type='POINTS', color=line_2_color,
                             size=point_size)
        self.points_3 = DRAW(draw_type='POINTS', color=select_color,
                             size=point_size)
        self.points_0.handle_add()
        self.points_1.handle_add()
        self.points_2.handle_add()
        self.points_3.handle_add()

        self.all_points = [
            self.points_0, self.points_1, self.points_2, self.points_3,
        ]

        self.params_table = DRAW(
            draw_type='PARAMS',
            draw_args=(self.line_0, self.line_1, self.line_2),
        )
        self.params_table.handle_add()

        width = context.area.width
        self.msg_bottom = DRAW(
            draw_type='TEXT',
            text='Connect 3 vertices between target and source mesh',
            coords_2d=[width, 25],
        )
        self.msg_bottom.handle_add()

        self.msg_distance_0 = DRAW(
            draw_type='TEXT', color=(1, 1, 1, 0.75),
            size=14, center_text=False,
        )
        self.msg_distance_1 = DRAW(
            draw_type='TEXT', color=(1, 1, 1, 0.75),
            size=14, center_text=False,
        )
        self.msg_distance_0.handle_add()
        self.msg_distance_1.handle_add()

        self.ray_cast = RAY_CAST(snap_distance)

        src_obj, self.tgt_obj = self.get_source_and_target_objects(context)
        if not self.tgt_obj:
            return {'CANCELLED'}
        _GLOBAL_TGT_OBJ_NAME = self.tgt_obj.name

        self.obj_names = {self.tgt_obj.name, src_obj.name}
        self.used_verts = {}

        context.window_manager.modal_handler_add(self)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.005, window=context.window)
        return {'RUNNING_MODAL'}

    def get_source_and_target_objects(self, context):
        objs = context.selected_objects
        src_obj = context.active_object
        tgt_obj = (set(objs) - {src_obj}).pop()
        return src_obj, tgt_obj

    def create_matrix_4x4(self, x, y, z, w):
        M = Matrix()
        w1 = w.copy()
        w1.resize_4d()
        M[0], M[1], M[2], M[3] = x.resized(4), y.resized(4), z.resized(4), w1
        M.transpose()
        return M

    def adopt_basis_axis_to_world(self, x, y):
        w_x = (Vector((1, 0, 0)), 'X')
        w_y = (Vector((0, 1, 0)), 'Y')
        w_z = (Vector((0, 0, 1)), 'Z')

        result = {}
        for vec in (x, y):
            best_dot = 0
            best_axis = None
            invert = False
            for w_vec, axis_name in (w_x, w_y, w_z):
                if axis_name in result:
                    continue
                dot_product = vec.dot(w_vec)
                if abs(dot_product) > best_dot:
                    best_dot = abs(dot_product)
                    best_axis = axis_name
                    invert = dot_product <= 0
            result[best_axis] = vec * -1 if invert else vec

        if 'X' not in result:
            result['X'] = result['Y'].cross(result['Z']).normalized()
        elif 'Y' not in result:
            result['Y'] = result['Z'].cross(result['X']).normalized()
        elif 'Z' not in result:
            result['Z'] = result['X'].cross(result['Y']).normalized()
        return result['X'], result['Y'], result['Z']

    def get_next_vert_by_edge_length(self, vert, found_edges, length,
                                     accuracy=0.01):
        best_edge = None
        min_length_diff = None
        for edge in vert.link_edges:
            if edge.index in found_edges:
                continue
            edge_len = edge.calc_length()
            if abs(edge_len - length) > accuracy:
                continue
            if min_length_diff is None or min_length_diff > abs(edge_len - length):
                min_length_diff = abs(edge_len - length)
                best_edge = edge
        if not best_edge:
            return None
        found_edges.add(best_edge.index)
        return best_edge.other_vert(vert)

    def get_diameter(self, obj, vert_index):
        bm = bmesh.new()
        mesh = obj.data
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        vert = bm.verts[vert_index]
        for edge in vert.link_edges:
            next_vert = vert
            cylinder_verts = [vert]
            found_edges = set()
            length = edge.calc_length()
            while True:
                next_vert = self.get_next_vert_by_edge_length(
                    next_vert, found_edges, length,
                )
                if not next_vert:
                    break
                cylinder_verts.append(next_vert)
            if (len(cylinder_verts[:-1]) % 2 == 0
                    and cylinder_verts[0] == cylinder_verts[-1]):
                middle_index = int(len(cylinder_verts[:-1]) / 2)
                vidx = cylinder_verts[middle_index].index
                return obj, mesh.vertices[vidx], (
                    obj.matrix_world @ mesh.vertices[vidx].co
                )
        return None, None, None

    def pre_execute(self):
        self.tgt_vec_x = (self.line_1.co[0] - self.line_0.co[0]).normalized()
        self.tgt_vec_z = self.tgt_vec_x.cross(
            self.line_2.co[0] - self.line_0.co[0],
        ).normalized()
        self.tgt_vec_y = self.tgt_vec_z.cross(self.tgt_vec_x).normalized()

        self.src_vec_x = (self.line_1.co[1] - self.line_0.co[1]).normalized()
        self.src_vec_z = self.src_vec_x.cross(
            self.line_2.co[1] - self.line_0.co[1],
        ).normalized()
        self.src_vec_y = self.src_vec_z.cross(self.src_vec_x).normalized()

        self.scale_dif = (
            (self.line_1.co[1] - self.line_0.co[1]).length
            / (self.line_1.co[0] - self.line_0.co[0]).length
        )
        self.src_snap_point = self.line_0.co[1]
        self.tgt_snap_point = (
            self.tgt_obj.matrix_world.inverted() @ self.line_0.co[0]
        )
        self.tgt_obj_matrix_world = self.tgt_obj.matrix_world.copy()
        self.tgt_obj_location = self.tgt_obj.location.copy()
        self.distance_1_center = 0.5 * (
            self.line_0.co[1] + self.line_1.co[1]
        )

    def execute(self, context):
        tgt_obj = context.view_layer.objects.get(_GLOBAL_TGT_OBJ_NAME)
        if not tgt_obj:
            return {'CANCELLED'}

        M_tgt = self.create_matrix_4x4(
            self.tgt_vec_x, self.tgt_vec_y, self.tgt_vec_z,
            self.tgt_obj_location,
        )
        M_src = self.create_matrix_4x4(
            self.src_vec_x, self.src_vec_y, self.src_vec_z,
            self.src_snap_point,
        )
        M_res = M_src @ M_tgt.inverted() @ self.tgt_obj_matrix_world

        if self.match_scale:
            M_res.transpose()
            M_res[0].xyz *= self.scale_dif
            M_res[1].xyz *= self.scale_dif
            M_res[2].xyz *= self.scale_dif
            M_res.transpose()

        offset = M_res.to_translation() - M_res @ self.tgt_snap_point
        M_offset = Matrix().Translation(offset)
        tgt_obj.matrix_world = M_offset @ M_res

        if self.origin_to_source:
            M_trans = tgt_obj.matrix_world.copy()
            M_trans[0][3], M_trans[1][3], M_trans[2][3] = self.distance_1_center
            for vert in tgt_obj.data.vertices:
                vert.co = M_trans.inverted() @ tgt_obj.matrix_world @ vert.co
            tgt_obj.matrix_world = M_trans

        if self.set_transforms:
            x, y, z = self.adopt_basis_axis_to_world(
                M_src.transposed()[0].xyz,
                M_src.transposed()[1].xyz,
            )
            if self.invert_x:
                x *= -1
            if self.invert_y:
                y *= -1
            if self.invert_z:
                z *= -1

            w = tgt_obj.matrix_world.to_translation()
            scale = tgt_obj.matrix_world.to_scale()
            M_trans = self.create_matrix_4x4(
                x * scale.x, y * scale.y, z * scale.z, w,
            )
            for vert in tgt_obj.data.vertices:
                vert.co = M_trans.inverted() @ tgt_obj.matrix_world @ vert.co
            tgt_obj.matrix_world = M_trans

        bpy.context.scene.tool_settings.use_transform_data_origin = self.show_origin

        bpy.ops.object.select_all(action='DESELECT')
        context.view_layer.objects.active = tgt_obj
        tgt_obj.select_set(True)

        return {'FINISHED'}

    def modal(self, context, event):
        DRAW.update_3d_view()

        if event.type == 'TIMER':
            if self.line_dist_0.is_done and self.line_dist_1.is_done:
                coords_2d_0 = self.line_dist_0.vector_3d_to_2d(
                    self.line_dist_0.center(),
                )
                coords_2d_1 = self.line_dist_1.vector_3d_to_2d(
                    self.line_dist_1.center(),
                )
                if coords_2d_0 and coords_2d_1:
                    self.msg_distance_0.coords_2d = coords_2d_0
                    self.msg_distance_0.text = 'Distance 1'
                    self.msg_distance_1.coords_2d = coords_2d_1
                    self.msg_distance_1.text = 'Distance 2'
            else:
                self.msg_distance_0.coords_2d = (0, 0)
                self.msg_distance_0.text = ''
                self.msg_distance_1.coords_2d = (0, 0)
                self.msg_distance_1.text = ''

            if self.mark_0.exist:
                self.mark_0.draw_mark()
            if self.mark_1.exist:
                self.mark_1.draw_mark()

        if (event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
                or event.alt):
            return {'PASS_THROUGH'}

        elif (event.type in {'RIGHTMOUSE', 'ESC'}
              and event.value == 'PRESS'):
            line = self.all_lines[self.line_id]
            if line.exist and not line.is_done:
                points = self.all_points[self.line_id]
                if not line.reverse:
                    del self.used_verts[
                        (line.obj_start.name, line.vert_start.index)
                    ]
                else:
                    del self.used_verts[
                        (line.obj_end.name, line.vert_end.index)
                    ]
                self.line_id = max(self.line_id - 1, 0)
                line.hide()
                points.co.clear()
                self.msg_bottom.text = ''
            else:
                self.destructor(context)
                return {'CANCELLED'}

        elif event.type == 'MOUSEMOVE':
            line = self.all_lines[self.line_id]
            self.obj, face_index, hit = self.ray_cast.ray_cast(
                context, event, self.obj_names,
            )
            self.vert = None

            if hit:
                self.vert, self.vert_vec = self.ray_cast.get_closest_vert(
                    self.obj, face_index, hit,
                )
                if self.vert_vec:
                    self.points_3.co = [self.vert_vec]
                    vec = self.vert_vec
                else:
                    self.points_3.co.clear()
                    vec = hit
            else:
                self.points_3.co.clear()
                vec = line.region_2d_to_3d(
                    (event.mouse_region_x, event.mouse_region_y),
                )

            if line.exist and not line.is_done:
                if not line.reverse:
                    line.vec_end = vec
                else:
                    line.vec_start = vec

        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not self.vert:
                return {'RUNNING_MODAL'}

            if ((self.obj.name, self.vert.index) in self.used_verts
                    and all(line.is_done for line in self.all_lines
                            if line.exist)):
                self.line_id = self.used_verts[
                    (self.obj.name, self.vert.index)
                ]
            elif not all(line.is_done for line in self.all_lines
                         if line.exist):
                self.line_id = [
                    line.id for line in self.all_lines
                    if line.exist and not line.is_done
                ][0]
            else:
                line_ids = [line.id for line in self.all_lines
                            if not line.exist]
                self.line_id = (line_ids[0]
                                if line_ids else len(self.all_lines) - 1)

            line = self.all_lines[self.line_id]
            points = self.all_points[self.line_id]

            if not line.exist:
                if self.obj.name == self.tgt_obj.name:
                    line.obj_start = self.obj
                    line.vert_start = self.vert
                    line.vec_start = self.vert_vec
                    line.reverse = False
                else:
                    line.obj_end = self.obj
                    line.vert_end = self.vert
                    line.vec_end = self.vert_vec
                    line.reverse = True
                line.exist = True
                self.used_verts[
                    (self.obj.name, self.vert.index)
                ] = line.id
                points.co.append(self.vert_vec)
                self.msg_bottom.text = (
                    'Line {} connecting...'.format(line.id + 1)
                )

            elif line.exist and not line.is_done:
                if (self.obj.name, self.vert.index) not in self.used_verts:
                    if not line.reverse and self.obj != line.obj_start:
                        line.obj_end = self.obj
                        line.vert_end = self.vert
                        line.vec_end = self.vert_vec
                        line.reverse = False
                        line.is_done = True
                    elif line.reverse and self.obj != line.obj_end:
                        line.obj_start = self.obj
                        line.vert_start = self.vert
                        line.vec_start = self.vert_vec
                        line.reverse = True
                        line.is_done = True
                    else:
                        self.msg_bottom.text = (
                            "Cannot draw on the same mesh"
                        )

                    if line.is_done:
                        line.ui_enable = True
                        self.used_verts[
                            (self.obj.name, self.vert.index)
                        ] = line.id
                        points.co.append(self.vert_vec)
                        done_lines = len(
                            [ln for ln in self.all_lines if ln.is_done]
                        ) + 1
                        if done_lines <= 3:
                            self.msg_bottom.text = (
                                'Line {} connected. '
                                'Construct line {}'.format(
                                    line.id + 1, done_lines,
                                )
                            )
                else:
                    self.msg_bottom.text = (
                        "Cannot connect: vertex already used"
                    )

            elif line.is_done and self.vert_vec in line.vecs:
                if line.obj_end == self.obj:
                    line.obj_end = None
                    line.vec_end = None
                    line.reverse = False
                else:
                    line.obj_start = None
                    line.vert_start = None
                    line.vec_start = None
                    line.reverse = True
                line.is_done = False
                line.ui_enable = False
                del self.used_verts[(self.obj.name, self.vert.index)]
                points.co.remove(self.vert_vec)
                self.line_dist_0.hide()
                self.line_dist_1.hide()
                self.msg_bottom.text = 'Line {} editing...'.format(
                    line.id + 1,
                )

            if {True, False} == {self.line_0.is_done, self.line_1.is_done}:
                line = (self.line_0 if self.line_0.is_done
                        else self.line_1)
                if not self.mark_0.exist:
                    (self.mark_0.obj, self.mark_0.vert,
                     self.mark_0.vec) = self.get_diameter(
                        line.obj_start, line.vert_start.index,
                    )
                    if self.mark_0.vec:
                        self.mark_0.draw_mark()
                if not self.mark_1.exist:
                    (self.mark_1.obj, self.mark_1.vert,
                     self.mark_1.vec) = self.get_diameter(
                        line.obj_end, line.vert_end.index,
                    )
                    if self.mark_1.vec:
                        self.mark_1.draw_mark()
            else:
                if self.mark_0.exist:
                    self.mark_0.hide()
                if self.mark_1.exist:
                    self.mark_1.hide()

            if (self.line_0.is_done and self.line_1.is_done
                    and self.line_2.is_done):
                self.face_0.co = [
                    self.line_0.co[0], self.line_1.co[0], self.line_2.co[0],
                ]
                self.face_1.co = [
                    self.line_0.co[1], self.line_1.co[1], self.line_2.co[1],
                ]
            else:
                self.face_0.co = [(0, 0, 0)] * 3
                self.face_1.co = [(0, 0, 0)] * 3

        if not self.line_dist_0.is_done and not self.line_dist_1.is_done:
            if self.line_0.is_done and self.line_1.is_done:
                self.line_dist_0.obj_start = self.line_0.obj_start
                self.line_dist_0.vec_start = self.line_0.vec_start
                self.line_dist_0.obj_end = self.line_1.obj_start
                self.line_dist_0.vec_end = self.line_1.vec_start
                self.line_dist_0.is_done = True

                self.line_dist_1.obj_start = self.line_0.obj_end
                self.line_dist_1.vec_start = self.line_0.vec_end
                self.line_dist_1.obj_end = self.line_1.obj_end
                self.line_dist_1.vec_end = self.line_1.vec_end
                self.line_dist_1.is_done = True
            else:
                self.line_dist_0.hide()
                self.line_dist_1.hide()

        if self.mark_0.exist and self.mark_1.exist:
            line = (self.line_0 if not self.line_0.is_done
                    else self.line_1)
            self.msg_bottom.text = (
                'Found 2 diameters. Press [Space/Enter] '
                'to build line {}'.format(line.id + 1)
            )
            if (event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'}
                    and event.value == 'PRESS'):
                line.obj_start = self.mark_0.obj
                line.obj_end = self.mark_1.obj
                line.vert_start = self.mark_0.vert
                line.vert_end = self.mark_1.vert
                line.vec_start = self.mark_0.vec
                line.vec_end = self.mark_1.vec
                line.exist = True
                line.is_done = True
                self.used_verts[
                    (line.obj_start.name, line.vert_start.index)
                ] = line.id
                self.used_verts[
                    (line.obj_end.name, line.vert_end.index)
                ] = line.id
                line.ui_enable = True
                self.all_points[line.id].co = [
                    self.mark_0.vec, self.mark_1.vec,
                ]
                self.mark_0.hide()
                self.mark_1.hide()
                if (self.line_0.exist and self.line_1.exist
                        and self.line_2.exist):
                    self.face_0.co = [
                        self.line_0.co[0], self.line_1.co[0],
                        self.line_2.co[0],
                    ]
                    self.face_1.co = [
                        self.line_0.co[1], self.line_1.co[1],
                        self.line_2.co[1],
                    ]
                self.msg_bottom.text = (
                    'Line {} connected. Build line 3'.format(line.id + 1)
                )

        elif (self.line_0.is_done and self.line_1.is_done
              and self.line_2.is_done):
            self.msg_bottom.text = 'Press [Space/Enter] to align'
            if (event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'}
                    and event.value == 'PRESS'):
                self.pre_execute()
                success = self.execute(context)
                self.destructor(context)
                return success

        return {'RUNNING_MODAL'}

    def destructor(self, context):
        self.points_0.handle_remove_all()
        self.line_0.handle_remove_all()
        self.msg_bottom.handle_remove()
        self.params_table.handle_remove()
        DRAW.update_3d_view()
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


# ============================================================
# Panel (always visible)
# ------------------------------------------------------------
# N panel content:
#   - Status hint
#   - "Enter Linking Mode" button
#   - Default Align Options (GREEN box -> Scene stored)
#   - Two eyedropper buttons (yellow box replacement)
#
# Colors and sizes are NOT shown here; they live in the addon
# preferences (RED box).
# ============================================================
class VIEW3D_PT_xneko_tpa(Panel):
    bl_label = "3 Points Align"
    bl_idname = "VIEW3D_PT_xneko_tpa"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # -------- Current selection state --------
        selected = [o for o in context.selected_objects if o.type == 'MESH']
        box = layout.box()
        if len(selected) == 2 and context.active_object in selected:
            box.label(
                text="Ready to align (2 meshes selected)",
                icon='CHECKMARK',
            )
        elif len(selected) == 1:
            box.label(text="Shift-select source mesh", icon='INFO')
        else:
            box.label(
                text="Select exactly two mesh objects",
                icon='INFO',
            )

        # -------- Enter linking mode --------
        row = layout.row()
        row.scale_y = 1.4
        row.operator(
            "xneko.tpa_check_selection",
            text="Enter Linking Mode",
            icon='STICKY_UVS_LOC',
        )

        layout.separator()

        # -------- Default redo-menu options (per-file) --------
        box = layout.box()
        box.label(text="Default Align Options:", icon='PREFERENCES')

        col = box.column(align=True)
        col.prop(scene, "xneko_tpa_show_origin")
        col.prop(scene, "xneko_tpa_match_scale")
        col.prop(scene, "xneko_tpa_origin_to_source")
        col.prop(scene, "xneko_tpa_set_transforms")

        row = box.row(align=True)
        row.enabled = scene.xneko_tpa_set_transforms
        row.label(text="Invert Origin:")
        row.prop(scene, "xneko_tpa_invert_x", toggle=True)
        row.prop(scene, "xneko_tpa_invert_y", toggle=True)
        row.prop(scene, "xneko_tpa_invert_z", toggle=True)

        layout.separator()

        # -------- Eyedroppers --------
        # Click one of these, then click any object in the viewport
        # to sample its viewport display color.
        box = layout.box()
        box.label(text="Sample Color from Viewport:", icon='EYEDROPPER')

        col = box.column(align=True)
        col.operator(
            "xneko.tpa_pick_line_colors",
            text="Line Colors",
            icon='EYEDROPPER',
        )
        col.operator(
            "xneko.tpa_pick_face_color",
            text="Face Color",
            icon='EYEDROPPER',
        )

        # -------- Hint --------
        hint = layout.row()
        hint.enabled = False
        hint.label(
            text="Colors & sizes: Addon Preferences",
            icon='INFO',
        )