import bpy, gpu
import blf
from gpu_extras.batch import batch_for_shader

# bgl was removed in Blender 4.0. Only referenced on the < 4.0 code paths.
try:
    import bgl
except ImportError:
    bgl = None

from bpy_extras import view3d_utils
from ._shaders import (
    color_3d_vertex_shader,
    simple_fragment_shader,
    point_fragment_shader,
    cross_fragment_shader,
)
from time import time
import random as rd  # kept for parity with the original module


class RAY_CAST:
    def __init__(self, snap_distance=20):
        self.region = bpy.context.region
        self.rv3d = bpy.context.region_data
        self.snap_distance = snap_distance

    def vector_3d_to_2d(self, vector):
        return view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, vector)

    def obj_ray_cast(self, obj, matrix, ray_origin, ray_target):
        """Wrapper for ray casting that moves the ray into object space"""
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv @ ray_origin
        ray_target_obj = matrix_inv @ ray_target
        ray_direction_obj = ray_target_obj - ray_origin_obj
        success, location, normal, face_index = obj.ray_cast(ray_origin_obj, ray_direction_obj)
        if success:
            return location, normal, face_index
        else:
            return None, None, None

    def visible_objects_and_duplis(self, context, obj_names):
        depsgraph = context.evaluated_depsgraph_get()
        for dup in depsgraph.object_instances:
            if dup.is_instance:  # Real dupli instance
                obj = dup.instance_object
            else:  # Usual object
                obj = dup.object
            if obj.name in obj_names:
                yield (obj, obj.matrix_world.copy())

    def ray_cast(self, context, event, obj_names):
        coord = event.mouse_region_x, event.mouse_region_y
        view_vector = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, coord)
        ray_target = ray_origin + view_vector
        best_obj = None
        best_hit = None
        best_face_index = None
        for obj, matrix in self.visible_objects_and_duplis(context, obj_names):
            hit, _, face_index = self.obj_ray_cast(obj, matrix, ray_origin, ray_target)
            if not hit:
                continue
            hit_world = matrix @ hit
            length_squared = (hit_world - ray_origin).length_squared
            if best_obj is None or length_squared < best_length_squared:
                best_length_squared = length_squared
                best_obj = obj
                best_hit = hit_world
                best_face_index = face_index
        if not best_hit:
            return None, None, None
        return best_obj, best_face_index, best_hit

    def get_closest_vert(self, obj, face_index, hit):
        best_vert = None
        mesh = obj.data
        verts_ids = mesh.polygons[face_index].vertices
        verts = [mesh.vertices[i] for i in verts_ids]
        hit_2d = self.vector_3d_to_2d(hit)
        if not hit_2d:
            return None, None
        min_dist_to_vert = None
        best_vert = None
        for vert in verts:
            vert_vec_2d = self.vector_3d_to_2d(obj.matrix_world @ vert.co)
            if not vert_vec_2d:
                continue
            current_dist = (hit_2d - vert_vec_2d).length
            if min_dist_to_vert is None or current_dist < min_dist_to_vert:
                if current_dist <= self.snap_distance:
                    min_dist_to_vert = current_dist
                    best_vert = vert
        if not best_vert:
            return None, None
        return best_vert, obj.matrix_world @ best_vert.co


class PARAM_UI:
    def __init__(self, name='未命名', color=(1, 1, 1, 1)):
        self.name = name
        self.color = color
        self.ui_enable = False
        self.state_label_on = '已设置'
        self.state_label_off = '未设置'
        self.state_color_on = (0, 1, 0, 1)
        self.state_color_off = (0.5, 0.5, 0.5, 1)

    @property
    def state_label(self):
        return self.state_label_on if self.ui_enable else self.state_label_off

    @property
    def state_color(self):
        return self.state_color_on if self.ui_enable else self.state_color_off


class DRAW:
    draw_handle_list = []

    def __init__(self, draw_type='TEXT', draw_args=(), text='', center_text=True,
                 size=18, color=(1, 1, 1, 1), line_width=1.5, coords=None,
                 coords_2d=None, *args, **kwargs):
        self.draw_type = draw_type
        self.draw_args = draw_args
        self.draw_type_dict = {
            'TEXT': (self.draw_text, 'POST_PIXEL'),
            'POINTS': (self.draw_points, 'POST_VIEW'),
            'LINE': (self.draw_line, 'POST_VIEW'),
            'LINE_2D': (self.draw_line_2d, 'POST_PIXEL'),
            'FACE': (self.draw_face, 'POST_VIEW'),
            'FACE_2D': (self.draw_face_2d, 'POST_PIXEL'),
            'PARAMS': (self.draw_params, 'POST_PIXEL'),
        }
        self.text = text
        self.size = size
        self.center_text = center_text
        self.color = color
        self.line_width = line_width
        self.coords = [] if coords is None else coords
        self.coords_2d = [150, 150] if coords_2d is None else coords_2d
        self.region = bpy.context.region
        self.rv3d = bpy.context.region_data
        self.blender_version = bpy.app.version
        self.start_time = time()

    def region_2d_to_3d(self, vector):
        ray_origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, vector)
        view_vector = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, vector)
        return ray_origin + view_vector

    def vector_3d_to_2d(self, vector):
        return view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, vector)

    @property
    def co(self):
        return self.coords

    @co.setter
    def co(self, value):
        self.coords = value

    @property
    def co_2d(self):
        return self.coords_2d

    @co_2d.setter
    def co_2d(self, value):
        self.coords_2d = value

    def draw_text(self):
        font_id = 0
        if self.blender_version < (4, 0, 0):
            blf.size(font_id, self.size, 72)
        else:
            blf.size(font_id, self.size)
        if self.center_text:
            text_width = blf.dimensions(font_id, self.text)[0]
            blf.position(font_id, self.coords_2d[0] / 2 - text_width / 2, self.coords_2d[1], 0)
        else:
            blf.position(font_id, self.coords_2d[0], self.coords_2d[1], 0)
        blf.color(font_id, *self.color)
        blf.draw(font_id, self.text)

    def draw_points(self, type='point'):
        if self.blender_version < (4, 0, 0):
            bgl.glPointSize(self.size)
            bgl.glEnable(bgl.GL_BLEND)
        else:
            gpu.state.point_size_set(self.size)
            gpu.state.blend_set("ALPHA")
        if type == 'point':
            shader = gpu.types.GPUShader(color_3d_vertex_shader(), point_fragment_shader())
        elif type == 'cross':
            shader = gpu.types.GPUShader(color_3d_vertex_shader(), cross_fragment_shader())
        batch = batch_for_shader(shader, 'POINTS', {"pos": self.co})
        shader.bind()
        matrix = bpy.context.region_data.perspective_matrix
        shader.uniform_float('viewProjectionMatrix', matrix)
        shader.uniform_float('color', self.color)
        if type == 'cross':
            shader.uniform_float('u_time', time() - self.start_time)
        batch.draw(shader)

    def draw_line(self):
        if self.blender_version < (4, 0, 0):
            bgl.glLineWidth(self.line_width)
        else:
            gpu.state.line_width_set(self.line_width)
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR' if bpy.app.version < (4, 0, 0) else 'UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": self.co})
        shader.bind()
        shader.uniform_float("color", self.color)
        batch.draw(shader)

    def draw_line_2d(self):
        if self.blender_version < (4, 0, 0):
            bgl.glLineWidth(self.line_width)
        else:
            gpu.state.line_width_set(self.line_width)
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR' if bpy.app.version < (4, 0, 0) else 'UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {'pos': self.co_2d})
        shader.bind()
        shader.uniform_float("color", self.color)
        batch.draw(shader)

    def draw_face(self):
        if self.blender_version < (4, 0, 0):
            bgl.glEnable(bgl.GL_BLEND)
        else:
            gpu.state.blend_set("ALPHA")
        shader = gpu.types.GPUShader(color_3d_vertex_shader(), simple_fragment_shader())
        batch = batch_for_shader(shader, 'TRIS', {'pos': self.co})
        shader.bind()
        matrix = bpy.context.region_data.perspective_matrix
        shader.uniform_float('viewProjectionMatrix', matrix)
        shader.uniform_float('color', self.color)
        batch.draw(shader)

    def draw_face_2d(self):
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR' if bpy.app.version < (4, 0, 0) else 'UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRIS', {'pos': self.co})
        shader.uniform_float("color", self.color)
        shader.bind()
        batch.draw(shader)

    def draw_params(self, *params):
        font_id = 0
        if self.blender_version < (4, 0, 0):
            blf.size(font_id, 18, 72)
        else:
            blf.size(font_id, 18)
        param_max_width = max(list(blf.dimensions(font_id, param.name)[0] for param in params))
        spacer_char = " :  "
        colon_width = blf.dimensions(font_id, spacer_char)[0]
        row_height = (blf.dimensions(font_id, "jM")[1] * 1.45)
        left, bottom = self.coords_2d
        bottom_offset = 0
        for param in params[::-1]:
            blf.position(font_id, left, bottom + bottom_offset, 0)
            blf.color(font_id, *param.color)
            blf.draw(font_id, param.name)
            blf.position(font_id, left + param_max_width, bottom + bottom_offset, 0)
            blf.color(font_id, *param.color)
            blf.draw(font_id, spacer_char)
            blf.position(font_id, left + param_max_width + colon_width, bottom + bottom_offset, 0)
            blf.color(font_id, *param.state_color)
            blf.draw(font_id, param.state_label)
            bottom_offset += row_height

    def handle_add(self):
        self.draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_type_dict[self.draw_type][0],
            self.draw_args,
            'WINDOW',
            self.draw_type_dict[self.draw_type][1],
        )
        self.draw_handle_list.append(self.draw_handle)

    def handle_remove(self):
        if self.draw_handle and "RNA_HANDLE_REMOVED" not in str(self.draw_handle):
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, 'WINDOW')
            self.draw_handle_list.remove(self.draw_handle)

    def handle_remove_all(self):
        if self.draw_handle_list:
            for draw_handle in self.draw_handle_list:
                bpy.types.SpaceView3D.draw_handler_remove(draw_handle, 'WINDOW')
            self.draw_handle_list.clear()

    @staticmethod
    def update_3d_view():
        for area in bpy.context.window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class LINE(DRAW, PARAM_UI):
    draw_handle_list = []

    def __init__(self, id=0, *args, **kwargs):
        DRAW.__init__(self, *args, **kwargs)
        PARAM_UI.__init__(self, *args, **kwargs)
        self.draw_type = 'LINE'
        self.id = id
        self.exist = False
        self.is_done = False
        self.reverse = False
        self.obj_start = None
        self.obj_end = None
        self.vert_start = None
        self.vert_end = None
        self.vec_start = None
        self.vec_end = None
        self.handle_add()

    @property
    def co(self):
        self.coords.clear()
        for vec in (self.vec_start, self.vec_end):
            if not vec:
                continue
            self.coords.append(vec)
        return self.coords

    @property
    def co_2d(self):
        self.coords.clear()
        for vec in (self.vec_start, self.vec_end):
            if not vec:
                continue
            self.coords.append(vec)
        return self.coords

    @property
    def vecs(self):
        return self.vec_start, self.vec_end

    def center(self):
        return (self.vec_start + self.vec_end) / 2 if self.vec_start and self.vec_end else None

    def hide(self):
        self.exist = False
        self.is_done = False
        self.obj_start, self.obj_end = None, None
        self.vert_start, self.vert_end = None, None
        self.vec_start, self.vec_end = None, None


class MARK(DRAW):
    def __init__(self, size=40, *agrs, **kwargs):
        super().__init__(size=size, *agrs, **kwargs)
        self.draw_type = 'POINTS'
        self.draw_args = ('cross',)
        self.exist = False
        self.obj = None
        self.vert = None
        self.vec = None
        self.handle_add()

    def hide(self):
        self.exist = False
        self.obj = None
        self.vert = None
        self.vec = None
        self.coords.clear()

    def draw_mark(self):
        if not self.vec:
            self.hide()
            return
        self.coords.append(self.vec)
        self.exist = True