"""Three-point alignment — XNeko Tools module.

Functionality inspired by the workflow of Barre Nick's
"3 Points Align" add-on. This is an independent implementation;
no source code from that project was used.
"""

import bpy

from . import shaders      # noqa: F401
from . import geometry     # noqa: F401
from . import raycaster    # noqa: F401
from . import overlay      # noqa: F401
from . import session      # noqa: F401
from . import settings
from . import operators


# ---------------------------------------------------------------
# Required by core.discover_tools()
# ---------------------------------------------------------------
classes = (
    settings.ThreePointAlignSettings,
    settings.XNEKO_PT_three_point_align_settings,
    operators.XNEKO_OT_tpa_pick_objects,
    operators.XNEKO_OT_tpa_run,
)

tool_name = "三点对齐"
tool_default_enabled = True


# ---------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------
SCENE_ATTR = 'xneko_tpa'
_keymaps = []


def on_load():
    # Attach the per-scene settings container
    if not hasattr(bpy.types.Scene, SCENE_ATTR):
        setattr(
            bpy.types.Scene,
            SCENE_ATTR,
            bpy.props.PointerProperty(type=settings.ThreePointAlignSettings),
        )

    # Register the Alt+T hotkey
    try:
        kc = bpy.context.window_manager.keyconfigs.addon
    except Exception:
        kc = None
    if kc is None:
        return

    km = kc.keymaps.get('3D View')
    if km is None:
        km = kc.keymaps.new('3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new(
        idname='xneko.tpa_pick_objects',
        type='T', value='PRESS', alt=True,
    )
    _keymaps.append((km, kmi))


def on_unload():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymaps.clear()

    if hasattr(bpy.types.Scene, SCENE_ATTR):
        try:
            delattr(bpy.types.Scene, SCENE_ATTR)
        except Exception:
            pass