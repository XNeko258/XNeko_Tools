import bpy
from bpy.types import Operator
from bpy.props import BoolProperty
import bmesh
from mathutils import Matrix, Vector
from ._core import RAY_CAST, PARAM_UI, DRAW, LINE, MARK


TOOL_ID = "three_points_align"

global_tgt_obj_name = None

# The currently running modal operator, or None when idle.
_active_modal = None

_addon_keymaps = []


def _get_prefs():
    from ....preferences import get_tool_prefs
    return get_tool_prefs(TOOL_ID)


def is_modal_active():
    return _active_modal is not None


def register_keymap():
    wm = bpy.context.window_manager
    if wm is None:
        return
    kc = wm.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.get('3D View')
    if not km:
        km = kc.keymaps.new('3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new(
        idname='three_points_align.check_selection',
        type='T', value='PRESS', alt=True,
    )
    _addon_keymaps.append((km, kmi))


def unregister_keymap():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()


# ============================================================
# N panel entry point
# ============================================================
class THREE_POINTS_ALIGN_OT_start(Operator):
    """Enter the 3-point connection/alignment modal.

    While a modal is active this operator is disabled (see poll);
    the modal is exited with ESC or RMB.
    """

    bl_idname = "three_points_align.start"
    bl_label = "Connect & Align"
    bl_description = "Enter the 3-point connection and alignment modal"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if context.area is None or context.area.type != 'VIEW_3D':
            return False
        if is_modal_active():
            return False
        if context.mode != 'OBJECT':
            return False
        scene = context.scene
        src = scene.three_points_align_source
        tgt = scene.three_points_align_target
        return src is not None and tgt is not None and src != tgt

    def execute(self, context):
        scene = context.scene
        src = scene.three_points_align_source
        tgt = scene.three_points_align_target

        if src is None or tgt is None:
            self.report({'ERROR'}, "Pick both Source and Target objects")
            return {'CANCELLED'}
        if src == tgt:
            self.report({'ERROR'}, "Source and Target must be different")
            return {'CANCELLED'}
        if src.type != 'MESH' or tgt.type != 'MESH':
            self.report({'ERROR'}, "Both objects must be meshes")
            return {'CANCELLED'}

        area = context.area
        window_region = None
        for region in area.regions:
            if region.type == 'WINDOW':
                window_region = region
                break
        if window_region is None:
            self.report({'ERROR'}, "No 3D viewport found")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        src.select_set(True)
        tgt.select_set(True)
        context.view_layer.objects.active = src

        try:
            with bpy.context.temp_override(region=window_region):
                bpy.ops.three_points_align.check_selection('INVOKE_DEFAULT')
        except AttributeError:
            bpy.ops.three_points_align.check_selection('INVOKE_DEFAULT')

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'FINISHED'}


# ============================================================
# Modal: check selection
# ============================================================
class THREE_POINTS_ALIGN_OT_check_selection(Operator):
    bl_idname = 'three_points_align.check_selection'
    bl_label = '3 Points Align'

    @classmethod
    def poll(cls, context):
        return _active_modal is None

    def invoke(self, context, event):
        global _active_modal
        _active_modal = self

        self.run_align = False
        self.skip_opeator = True
        self._force_exit = False

        self.src_param = PARAM_UI('源网格')
        self.tgt_param = PARAM_UI('目标网格')

        self.params_table = DRAW(draw_type='PARAMS', draw_args=(self.src_param, self.tgt_param))
        self.params_table.handle_add()

        width = context.area.width
        self.msg_bottom = DRAW(draw_type='TEXT', coords_2d=[width, 25])
        self.msg_bottom.handle_add()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'RUNNING_MODAL'}

    def obj_selection_validator(self, context):
        objs = context.selected_objects

        mesh_objs = 0
        for obj in objs:
            if obj.type == 'MESH' and obj.mode == 'OBJECT':
                mesh_objs += 1

        if len(objs) == 0:
            return False, False, '1. 选择两个需要对齐的网格'
        elif len(objs) > 2 and mesh_objs == 0:
            return False, False, '只需要选择两个网格'
        elif len(objs) > 2 and mesh_objs > 0:
            return True, False, '只需要选择两个网格'
        elif len(objs) == 2 and mesh_objs == 0:
            return False, False, '仅应选择多边形网格'
        elif len(objs) == 2 and mesh_objs == 1:
            return True, False, '仅应选择多边形网格'
        elif len(objs) == 1 and mesh_objs == 0:
            return False, False, '仅应选择多边形网格'
        elif len(objs) == 1 and mesh_objs == 1:
            return True, False, '2. 按住 Shift 选择源网格'
        elif len(objs) == 2 and mesh_objs == 2 and context.active_object not in (objs):
            return True, False, '其中一个选定网格应为活动状态'
        elif len(objs) == 2 and mesh_objs == 2 and context.active_object in objs:
            return True, True, '按 [空格/回车] 创建线路'
        else:
            return False, False, '意外情况'

    def modal(self, context, event):
        if getattr(self, '_force_exit', False):
            self._force_exit = False
            self.run_align = False
            self.destructor(context)
            return {'CANCELLED'}

        DRAW.update_3d_view()

        if (event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}) or \
                (True in {event.shift, event.ctrl, event.alt} and event.value == 'PRESS'):
            return {'PASS_THROUGH'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.destructor(context)
            return {'CANCELLED'}

        elif event.type == 'LEFTMOUSE':
            return {'PASS_THROUGH'}

        elif event.type == 'TIMER':
            return {'RUNNING_MODAL'}

        self.tgt_param.ui_enable, self.src_param.ui_enable, self.msg_bottom.text = \
            self.obj_selection_validator(context)
        if self.tgt_param.ui_enable and self.src_param.ui_enable:
            if self.skip_opeator:
                self.run_align = True
                self.destructor(context)
                return {'FINISHED'}

            elif event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                self.run_align = True
                self.destructor(context)
                return {'FINISHED'}

        self.skip_opeator = False
        return {'RUNNING_MODAL'}

    def destructor(self, context=None):
        global _active_modal
        _active_modal = None

        ctx = context if context is not None else bpy.context

        try:
            ctx.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass

        self.params_table.handle_remove()
        self.msg_bottom.handle_remove()

        if self.run_align:
            bpy.ops.three_points_align.align('INVOKE_DEFAULT')

        try:
            for area in ctx.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        except Exception:
            pass


# ============================================================
# Modal: align
# ============================================================
class THREE_POINTS_ALIGN_OT_align(Operator):
    '''3 Points Align'''
    bl_idname = 'three_points_align.align'
    bl_label = '3 Points Align'
    bl_options = {'REGISTER', 'UNDO'}

    match_scale: BoolProperty(name='Match Distance', default=False)

    def save_props(self, context):
        prefs = _get_prefs()
        if prefs is None:
            return
        prefs.match_scale = self.match_scale

    def load_props(self, context):
        prefs = _get_prefs()
        if prefs is None:
            return
        self.match_scale = prefs.match_scale

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.prop(self, 'match_scale', text='Match Distance')

        # Persist the current value back into the addon preferences.
        self.save_props(context)

    def invoke(self, context, event):
        global global_tgt_obj_name, _active_modal
        _active_modal = self
        self._force_exit = False

        self.load_props(context)
        prefs = _get_prefs()
        if prefs is None:
            return {'CANCELLED'}

        self.face_0 = DRAW(draw_type='FACE', color=prefs.face_color, coords=[(0, 0, 0)] * 3)
        self.face_1 = DRAW(draw_type='FACE', color=prefs.face_color, coords=[(0, 0, 0)] * 3)
        self.face_0.handle_add()
        self.face_1.handle_add()

        self.line_0 = LINE(name='线路1', id=0, color=prefs.line_0_color)
        self.line_1 = LINE(name='线路2', id=1, color=prefs.line_1_color)
        self.line_2 = LINE(name='线路3', id=2, color=prefs.line_2_color)
        self.line_dist_0 = LINE(name='距离', id=3)
        self.line_dist_1 = LINE(name='距离', id=4)
        self.mark_0 = MARK(color=prefs.select_color, size=prefs.cross_size)
        self.mark_1 = MARK(color=prefs.select_color, size=prefs.cross_size)

        self.all_lines = [self.line_0, self.line_1, self.line_2]
        self.line_id = 0

        self.points_0 = DRAW(draw_type='POINTS', color=prefs.line_0_color, size=prefs.point_size)
        self.points_1 = DRAW(draw_type='POINTS', color=prefs.line_1_color, size=prefs.point_size)
        self.points_2 = DRAW(draw_type='POINTS', color=prefs.line_2_color, size=prefs.point_size)
        self.points_3 = DRAW(draw_type='POINTS', color=prefs.select_color, size=prefs.point_size)
        self.points_0.handle_add()
        self.points_1.handle_add()
        self.points_2.handle_add()
        self.points_3.handle_add()

        self.all_points = [self.points_0, self.points_1, self.points_2, self.points_3]

        self.params_table = DRAW(draw_type='PARAMS', draw_args=(self.line_0, self.line_1, self.line_2))
        self.params_table.handle_add()

        width = context.area.width
        self.msg_bottom = DRAW(draw_type='TEXT', text='在目标网格和源网格之间连接3个顶点', coords_2d=[width, 25])
        self.msg_bottom.handle_add()

        self.msg_distance_0 = DRAW(draw_type='TEXT', color=(1, 1, 1, 0.75), size=14, center_text=False)
        self.msg_distance_1 = DRAW(draw_type='TEXT', color=(1, 1, 1, 0.75), size=14, center_text=False)
        self.msg_distance_0.handle_add()
        self.msg_distance_1.handle_add()

        self.ray_cast = RAY_CAST(prefs.snap_distance)

        src_obj, self.tgt_obj = self.get_source_and_target_objects(context)
        if not self.tgt_obj:
            return {'CANCELLED'}
        global_tgt_obj_name = self.tgt_obj.name

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

    def get_next_vert_by_edge_length(self, vert, found_edges, length, accuracy=0.01):
        edges = vert.link_edges
        best_edge = None
        min_length_diff = None

        for edge in edges:
            if edge.index in found_edges:
                continue
            edge_len = edge.calc_length()
            length_diff = abs(edge_len - length)
            if length_diff > accuracy:
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
        edges = vert.link_edges
        for edge in edges:
            next_vert = vert
            cylinder_verts = [vert]
            found_edges = set()
            length = edge.calc_length()

            while True:
                next_vert = self.get_next_vert_by_edge_length(next_vert, found_edges, length)
                if not next_vert:
                    break
                cylinder_verts.append(next_vert)

            if len(cylinder_verts[:-1]) % 2 == 0 and cylinder_verts[0] == cylinder_verts[-1]:
                middle_index = int(len(cylinder_verts[:-1]) / 2)
                vert_index = cylinder_verts[middle_index].index
                return obj, mesh.vertices[vert_index], obj.matrix_world @ mesh.vertices[vert_index].co

        return None, None, None

    def pre_execute(self):
        self.tgt_vec_x = (self.line_1.co[0] - self.line_0.co[0]).normalized()
        self.tgt_vec_z = self.tgt_vec_x.cross(self.line_2.co[0] - self.line_0.co[0]).normalized()
        self.tgt_vec_y = self.tgt_vec_z.cross(self.tgt_vec_x).normalized()

        self.src_vec_x = (self.line_1.co[1] - self.line_0.co[1]).normalized()
        self.src_vec_z = self.src_vec_x.cross(self.line_2.co[1] - self.line_0.co[1]).normalized()
        self.src_vec_y = self.src_vec_z.cross(self.src_vec_x).normalized()

        self.scale_dif = (self.line_1.co[1] - self.line_0.co[1]).length / \
                         (self.line_1.co[0] - self.line_0.co[0]).length
        self.src_snap_point = self.line_0.co[1]
        self.tgt_snap_point = self.tgt_obj.matrix_world.inverted() @ self.line_0.co[0]
        self.tgt_obj_matrix_world = self.tgt_obj.matrix_world.copy()
        self.tgt_obj_location = self.tgt_obj.location.copy()

    def execute(self, context):
        tgt_obj = context.view_layer.objects.get(global_tgt_obj_name)
        if not tgt_obj:
            return {'CANCELLED'}

        M_tgt = self.create_matrix_4x4(
            self.tgt_vec_x, self.tgt_vec_y, self.tgt_vec_z, self.tgt_obj_location,
        )

        M_src = self.create_matrix_4x4(
            self.src_vec_x, self.src_vec_y, self.src_vec_z, self.src_snap_point,
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

        bpy.ops.object.select_all(action='DESELECT')
        context.view_layer.objects.active = tgt_obj
        tgt_obj.select_set(True)

        return {'FINISHED'}

    def modal(self, context, event):
        if getattr(self, '_force_exit', False):
            self._force_exit = False
            self.destructor(context)
            return {'CANCELLED'}

        DRAW.update_3d_view()

        if event.type == 'TIMER':
            if self.line_dist_0.is_done and self.line_dist_1.is_done:
                coords_2d_0 = self.line_dist_0.vector_3d_to_2d(self.line_dist_0.center())
                coords_2d_1 = self.line_dist_1.vector_3d_to_2d(self.line_dist_1.center())
                if coords_2d_0 and coords_2d_1:
                    self.msg_distance_0.coords_2d = coords_2d_0
                    self.msg_distance_0.text = '距离 1'
                    self.msg_distance_1.coords_2d = coords_2d_1
                    self.msg_distance_1.text = '距离 2'
            else:
                self.msg_distance_0.coords_2d = (0, 0)
                self.msg_distance_0.text = ''
                self.msg_distance_1.coords_2d = (0, 0)
                self.msg_distance_1.text = ''

            if self.mark_0.exist:
                self.mark_0.draw_mark()
            if self.mark_1.exist:
                self.mark_1.draw_mark()

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} or event.alt:
            return {'PASS_THROUGH'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            line = self.all_lines[self.line_id]
            if line.exist and not line.is_done:
                points = self.all_points[self.line_id]
                if not line.reverse:
                    del self.used_verts[(line.obj_start.name, line.vert_start.index)]
                else:
                    del self.used_verts[(line.obj_end.name, line.vert_end.index)]
                self.line_id = max(self.line_id - 1, 0)
                line.hide()
                points.co.clear()
                self.msg_bottom.text = ''
            else:
                self.destructor(context)
                return {'CANCELLED'}

        elif event.type == 'MOUSEMOVE':
            line = self.all_lines[self.line_id]
            self.obj, face_index, hit = self.ray_cast.ray_cast(context, event, self.obj_names)
            self.vert = None

            if hit:
                self.vert, self.vert_vec = self.ray_cast.get_closest_vert(self.obj, face_index, hit)

                if self.vert_vec:
                    self.points_3.co = [self.vert_vec]
                    vec = self.vert_vec
                else:
                    self.points_3.co.clear()
                    vec = hit
            else:
                self.points_3.co.clear()
                vec = line.region_2d_to_3d((event.mouse_region_x, event.mouse_region_y))

            if line.exist and not line.is_done:
                if not line.reverse:
                    line.vec_end = vec
                else:
                    line.vec_start = vec

        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not self.vert:
                return {'RUNNING_MODAL'}

            if (self.obj.name, self.vert.index) in self.used_verts and \
                    all(line.is_done for line in self.all_lines if line.exist):
                self.line_id = self.used_verts[(self.obj.name, self.vert.index)]
            elif not all(line.is_done for line in self.all_lines if line.exist):
                self.line_id = [line.id for line in self.all_lines if line.exist and not line.is_done][0]
            else:
                line_ids = [line.id for line in self.all_lines if not line.exist]
                self.line_id = line_ids[0] if line_ids else len(self.all_lines) - 1

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
                self.used_verts[(self.obj.name, self.vert.index)] = line.id
                points.co.append(self.vert_vec)
                self.msg_bottom.text = '线路{}正在连接...'.format(line.id + 1)

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
                        self.msg_bottom.text = "无法在自网格上划线"

                    if line.is_done:
                        line.is_done = True
                        line.ui_enable = True
                        self.used_verts[(self.obj.name, self.vert.index)] = line.id
                        points.co.append(self.vert_vec)
                        done_lines = len([line for line in self.all_lines if line.is_done]) + 1
                        if done_lines <= 3:
                            self.msg_bottom.text = '线路{}已连接。构建线路 {}'.format(line.id + 1, done_lines)
                else:
                    self.msg_bottom.text = "此处无法连接，此顶点已被使用"

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
                self.msg_bottom.text = '行｛｝编辑...'.format(line.id + 1)

            if {True, False} == {self.line_0.is_done, self.line_1.is_done}:
                line = self.line_0 if self.line_0.is_done else self.line_1
                if not self.mark_0.exist:
                    self.mark_0.obj, self.mark_0.vert, self.mark_0.vec = \
                        self.get_diameter(line.obj_start, line.vert_start.index)
                    if self.mark_0.vec:
                        self.mark_0.draw_mark()
                if not self.mark_1.exist:
                    self.mark_1.obj, self.mark_1.vert, self.mark_1.vec = \
                        self.get_diameter(line.obj_end, line.vert_end.index)
                    if self.mark_1.vec:
                        self.mark_1.draw_mark()
            else:
                if self.mark_0.exist:
                    self.mark_0.hide()
                if self.mark_1.exist:
                    self.mark_1.hide()

            if self.line_0.is_done and self.line_1.is_done and self.line_2.is_done:
                self.face_0.co = [self.line_0.co[0], self.line_1.co[0], self.line_2.co[0]]
                self.face_1.co = [self.line_0.co[1], self.line_1.co[1], self.line_2.co[1]]
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
            line = self.line_0 if not self.line_0.is_done else self.line_1
            self.msg_bottom.text = '发现2个直径。按[空格/回车]构建直线 {}'.format(line.id + 1)
            if event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                line.obj_start = self.mark_0.obj
                line.obj_end = self.mark_1.obj
                line.vert_start = self.mark_0.vert
                line.vert_end = self.mark_1.vert
                line.vec_start = self.mark_0.vec
                line.vec_end = self.mark_1.vec
                line.exist = True
                line.is_done = True
                self.used_verts[(line.obj_start.name, line.vert_start.index)] = line.id
                self.used_verts[(line.obj_end.name, line.vert_end.index)] = line.id
                line.ui_enable = True
                self.all_points[line.id].co = [self.mark_0.vec, self.mark_1.vec]
                self.mark_0.hide()
                self.mark_1.hide()
                if self.line_0.exist and self.line_1.exist and self.line_2.exist:
                    self.face_0.co = [self.line_0.co[0], self.line_1.co[0], self.line_2.co[0]]
                    self.face_1.co = [self.line_0.co[1], self.line_1.co[1], self.line_2.co[1]]
                self.msg_bottom.text = '线路{}已连接。构建线路 3'.format(line.id + 1)

        elif self.line_0.is_done and self.line_1.is_done and self.line_2.is_done:
            self.msg_bottom.text = '按[空格/回车]对齐'
            if event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                self.pre_execute()
                success = self.execute(context)
                self.destructor(context)
                return success

        return {'RUNNING_MODAL'}

    def destructor(self, context):
        global _active_modal
        _active_modal = None

        self.points_0.handle_remove_all()
        self.line_0.handle_remove_all()
        self.msg_bottom.handle_remove()
        self.params_table.handle_remove()
        DRAW.update_3d_view()
        wm = context.window_manager
        try:
            wm.event_timer_remove(self._timer)
        except Exception:
            pass

        try:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        except Exception:
            pass