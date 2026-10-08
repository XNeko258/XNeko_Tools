"""Context helpers for calling bpy.ops safely inside the tool.

bpy.ops.object.mode_set / pose.* / select_all require an active
object and (for some) an active 3D viewport. In an N-panel button
callback the area is already VIEW_3D, but when the same code runs
from the Topbar > File > Import menu, context.area is TOPBAR and
some ops fail. ops_safe() hides that difference.
"""

from contextlib import contextmanager

import bpy


def _find_viewport_region():
    """Return (area, region, window) of the first 3D viewport, if any."""
    wm = bpy.context.window_manager
    if wm is None:
        return None, None, None
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return area, region, window
    return None, None, None


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@contextmanager
def ops_safe(mode=None):
    """Context manager that ensures a valid viewport and optionally
    switches the active object to the given mode before yielding.
    The previous mode is restored on exit.

    Usage:
        with ops_safe(mode="EDIT"):
            armature.edit_bones.new(...)
    """
    area, region, window = _find_viewport_region()

    previous_mode = None
    active = bpy.context.view_layer.objects.active
    if active is not None and hasattr(active, "mode"):
        previous_mode = active.mode

    if area is not None:
        override = bpy.context.temp_override(
            area=area, region=region, window=window,
        )
    else:
        override = _NullContext()

    with override:
        if mode is not None and active is not None:
            try:
                bpy.ops.object.mode_set(mode=mode)
            except Exception:
                pass
        try:
            yield
        finally:
            if (
                mode is not None
                and active is not None
                and previous_mode is not None
                and previous_mode != mode
            ):
                try:
                    bpy.ops.object.mode_set(mode=previous_mode)
                except Exception:
                    pass