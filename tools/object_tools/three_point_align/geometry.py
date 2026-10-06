"""Pure-math helpers used to compute the alignment transform."""

from mathutils import Matrix


def unit_or_none(vec):
    n = vec.length
    if n < 1e-9:
        return None
    return vec / n


def orthonormal_frame(origin, x_point, plane_point):
    """Return (x_axis, y_axis, z_axis) unit Vectors, or None if degenerate.

    x_axis runs from `origin` to `x_point`.
    z_axis is the normal of the plane (origin, x_point, plane_point).
    y_axis is the right-handed complement.
    """
    x_axis = unit_or_none(x_point - origin)
    if x_axis is None:
        return None

    z_axis = unit_or_none(x_axis.cross(plane_point - origin))
    if z_axis is None:
        return None

    y_axis = z_axis.cross(x_axis)
    return x_axis, y_axis, z_axis


def frame_matrix(x, y, z, origin):
    """Matrix whose columns are the three axes + origin."""
    return Matrix((
        (x.x, y.x, z.x, origin.x),
        (x.y, y.y, z.y, origin.y),
        (x.z, y.z, z.z, origin.z),
        (0.0, 0.0, 0.0, 1.0),
    ))


def build_alignment_matrix(session):
    """Return the 4x4 world matrix that puts the target object into the
    source frame.  Raises ValueError on a degenerate point selection.
    """
    src_world = [p.src_world for p in session.pairs]
    tgt_world = [p.tgt_world for p in session.pairs]

    obj = session.target_obj
    obj_inv = obj.matrix_world.inverted()
    tgt_local = [obj_inv @ p for p in tgt_world]

    src_frame = orthonormal_frame(src_world[0], src_world[1], src_world[2])
    tgt_frame = orthonormal_frame(tgt_local[0], tgt_local[1], tgt_local[2])
    if src_frame is None or tgt_frame is None:
        raise ValueError("三点共线或距离过近")

    sx, sy, sz = src_frame
    tx, ty, tz = tgt_frame

    if session.settings.keep_scale:
        k = (src_world[1] - src_world[0]).length \
            / (tgt_local[1] - tgt_local[0]).length
        sx, sy, sz = sx * k, sy * k, sz * k

    M_src = frame_matrix(sx, sy, sz, src_world[0])
    M_tgt = frame_matrix(tx, ty, tz, tgt_local[0])
    return M_src @ M_tgt.inverted()


def bake_matrix(obj, new_matrix):
    """Move `obj` to `new_matrix` while keeping every vertex fixed in world space."""
    old = obj.matrix_world.copy()
    inv = new_matrix.inverted()
    for v in obj.data.vertices:
        v.co = inv @ old @ v.co
    obj.matrix_world = new_matrix