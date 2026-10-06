"""Project the mouse into the 3D viewport and snap onto nearby vertices."""

import bpy
from bpy_extras import view3d_utils


class ViewportRaycaster:
    """Casts a ray from the mouse into the scene and finds vertices.

    Bound to a specific 3D-View region; reuse one instance for the
    whole session.
    """

    __slots__ = ('_region', '_rv3d', '_snap_radius')

    def __init__(self, region, rv3d, snap_radius=20):
        self._region = region
        self._rv3d = rv3d
        self._snap_radius = snap_radius

    # ---- projection helpers ---------------------------------------------

    def to_screen(self, world_co):
        return view3d_utils.location_3d_to_region_2d(
            self._region, self._rv3d, world_co)

    def to_view_plane(self, mouse_xy):
        """Return a world-space point on the view plane at the mouse."""
        origin = view3d_utils.region_2d_to_origin_3d(
            self._region, self._rv3d, mouse_xy)
        direction = view3d_utils.region_2d_to_vector_3d(
            self._region, self._rv3d, mouse_xy)
        return origin + direction

    # ---- main query -----------------------------------------------------

    def hit(self, context, mouse_xy, allowed_names):
        """Return (obj, face_index, world_hit) or (None, None, None)."""
        origin = view3d_utils.region_2d_to_origin_3d(
            self._region, self._rv3d, mouse_xy)
        direction = view3d_utils.region_2d_to_vector_3d(
            self._region, self._rv3d, mouse_xy)
        target = origin + direction

        depsgraph = context.evaluated_depsgraph_get()
        best = None  # (dist2, obj, face_index, world_hit)

        for inst in depsgraph.object_instances:
            obj = inst.instance_object if inst.is_instance else inst.object
            if obj.name not in allowed_names:
                continue

            world = obj.matrix_world
            inv = world.inverted()
            local_o = inv @ origin
            local_t = inv @ target

            ok, loc, _n, fi = obj.ray_cast(local_o, local_t - local_o)
            if not ok:
                continue

            hit_world = world @ loc
            d2 = (hit_world - origin).length_squared
            if best is None or d2 < best[0]:
                best = (d2, obj, fi, hit_world)

        if best is None:
            return None, None, None
        return best[1], best[2], best[3]

    def snap_vertex(self, obj, face_index, world_hit):
        """Return the closest vertex of `face_index` to `world_hit`,
        in screen space, or (None, None).
        """
        mesh = obj.data
        world = obj.matrix_world

        hit_2d = self.to_screen(world_hit)
        if hit_2d is None:
            return None, None

        face_verts = mesh.polygons[face_index].vertices
        best_vert = None
        best_dist = self._snap_radius

        for vid in face_verts:
            v = mesh.vertices[vid]
            v_2d = self.to_screen(world @ v.co)
            if v_2d is None:
                continue
            d = (hit_2d - v_2d).length
            if d <= best_dist:
                best_dist = d
                best_vert = v

        if best_vert is None:
            return None, None
        return best_vert, world @ best_vert.co