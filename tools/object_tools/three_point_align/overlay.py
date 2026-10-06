"""Viewport overlay elements for the three-point align tool.

Each element owns one draw-handler. `OverlayHost` keeps them together
so the operator only has to call `host.release_all()` when it exits.
"""

import time

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from . import shaders


# ---------------------------------------------------------------------
# Host
# ---------------------------------------------------------------------

class OverlayHost:
    def __init__(self):
        self._elements = []

    def adopt(self, element):
        self._elements.append(element)
        return element

    def release_all(self):
        for el in self._elements:
            try:
                el.release()
            except Exception:
                pass
        self._elements.clear()

    @staticmethod
    def redraw():
        screen = bpy.context.screen
        if not screen:
            return
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class _Element:
    """Base class owning a single draw-handler."""

    def __init__(self, render_fn, args, kind):
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            render_fn, args, 'WINDOW', kind)

    def release(self):
        if self._handle is None:
            return
        try:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        except Exception:
            pass
        self._handle = None


# ---------------------------------------------------------------------
# 2D text
# ---------------------------------------------------------------------

class ScreenText(_Element):
    """Fixed-position 2D text over the viewport."""

    def __init__(self, host, x=10, y=10, size=16, color=(1, 1, 1, 1),
                 center=False):
        self.x = x
        self.y = y
        self.size = size
        self.color = tuple(color)
        self.center = center
        self.body = ""
        _Element.__init__(self, self._render, (), 'POST_PIXEL')
        host.adopt(self)

    def _render(self):
        if not self.body:
            return
        font = 0
        if bpy.app.version < (4, 0, 0):
            blf.size(font, self.size, 72)
        else:
            blf.size(font, self.size)
        x = self.x
        if self.center:
            x -= blf.dimensions(font, self.body)[0] * 0.5
        blf.position(font, x, self.y, 0)
        blf.color(font, *self.color)
        blf.draw(font, self.body)


class StatusPanel(_Element):
    """A right-aligned table of `label → state` rows."""

    ROW_SPACER = "   :   "

    def __init__(self, host, x=14, y=14, size=16):
        self.x = x
        self.y = y
        self.size = size
        self._rows = []
        _Element.__init__(self, self._render, (), 'POST_PIXEL')
        host.adopt(self)

    def set_rows(self, rows):
        """`rows` is an iterable of (label, label_color, state, state_color)."""
        self._rows = list(rows)

    def _render(self):
        if not self._rows:
            return
        font = 0
        if bpy.app.version < (4, 0, 0):
            blf.size(font, self.size, 72)
        else:
            blf.size(font, self.size)

        label_w = max(blf.dimensions(font, r[0])[0] for r in self._rows)
        spacer_w = blf.dimensions(font, self.ROW_SPACER)[0]
        row_h = blf.dimensions(font, "Mg")[1] * 1.45

        y = self.y
        for label, lab_col, state, st_col in reversed(self._rows):
            blf.position(font, self.x, y, 0)
            blf.color(font, *lab_col)
            blf.draw(font, label)

            blf.position(font, self.x + label_w, y, 0)
            blf.color(font, *lab_col)
            blf.draw(font, self.ROW_SPACER)

            blf.position(font, self.x + label_w + spacer_w, y, 0)
            blf.color(font, *st_col)
            blf.draw(font, state)

            y += row_h


# ---------------------------------------------------------------------
# 3D primitives
# ---------------------------------------------------------------------

class WorldLines(_Element):
    def __init__(self, host, color=(1, 1, 1, 1), width=2.0):
        self.color = tuple(color)
        self.width = width
        self._verts = []
        _Element.__init__(self, self._render, (), 'POST_VIEW')
        host.adopt(self)

    def set_segments(self, segments):
        """`segments` = iterable of (a, b) world-space Vector pairs."""
        self._verts = []
        for a, b in segments:
            if a is None or b is None:
                continue
            self._verts.append(tuple(a))
            self._verts.append(tuple(b))

    def clear(self):
        self._verts = []

    def _render(self):
        if len(self._verts) < 2:
            return
        gpu.state.line_width_set(self.width)
        name = '3D_UNIFORM_COLOR' if bpy.app.version < (4, 0, 0) else 'UNIFORM_COLOR'
        shader = gpu.shader.from_builtin(name)
        batch = batch_for_shader(shader, 'LINES', {'pos': self._verts})
        shader.bind()
        shader.uniform_float('color', self.color)
        batch.draw(shader)


class WorldDots(_Element):
    def __init__(self, host, color=(1, 1, 1, 1), size=10):
        self.color = tuple(color)
        self.size = size
        self._points = []
        _Element.__init__(self, self._render, (), 'POST_VIEW')
        host.adopt(self)

    def set_points(self, points):
        self._points = [tuple(p) for p in points if p is not None]

    def clear(self):
        self._points = []

    def _render(self):
        if not self._points:
            return
        gpu.state.point_size_set(self.size)
        gpu.state.blend_set('ALPHA')
        shader = shaders.round_point_3d()
        batch = batch_for_shader(shader, 'POINTS', {'position': self._points})
        shader.bind()
        shader.uniform_float('viewProjection',
                             bpy.context.region_data.perspective_matrix)
        shader.uniform_float('baseColor', self.color)
        batch.draw(shader)


class WorldTriangle(_Element):
    def __init__(self, host, color=(0.1, 0.7, 1.0, 0.2)):
        self.color = tuple(color)
        self._verts = [None, None, None]
        _Element.__init__(self, self._render, (), 'POST_VIEW')
        host.adopt(self)

    def set_vertices(self, a, b, c):
        self._verts = [a, b, c]

    def clear(self):
        self._verts = [None, None, None]

    def _render(self):
        if any(v is None for v in self._verts):
            return
        gpu.state.blend_set('ALPHA')
        shader = shaders.solid_3d()
        data = [tuple(v) for v in self._verts]
        batch = batch_for_shader(shader, 'TRIS', {'position': data})
        shader.bind()
        shader.uniform_float('viewProjection',
                             bpy.context.region_data.perspective_matrix)
        shader.uniform_float('baseColor', self.color)
        batch.draw(shader)


class CrossMarker(_Element):
    def __init__(self, host, color=(1, 1, 1, 1), size=48):
        self.color = tuple(color)
        self.size = size
        self._position = None
        self._t0 = time.time()
        _Element.__init__(self, self._render, (), 'POST_VIEW')
        host.adopt(self)

    def show_at(self, world_co):
        self._position = tuple(world_co)

    def hide(self):
        self._position = None

    def _render(self):
        if self._position is None:
            return
        gpu.state.point_size_set(self.size)
        gpu.state.blend_set('ALPHA')
        shader = shaders.pulsing_cross_3d()
        batch = batch_for_shader(shader, 'POINTS',
                                 {'position': [self._position]})
        shader.bind()
        shader.uniform_float('viewProjection',
                             bpy.context.region_data.perspective_matrix)
        shader.uniform_float('baseColor', self.color)
        shader.uniform_float('time', time.time() - self._t0)
        batch.draw(shader)