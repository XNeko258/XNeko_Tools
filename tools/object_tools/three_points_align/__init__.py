import bpy
from bpy.props import BoolProperty, IntProperty, FloatVectorProperty


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_name = "3 Points Align"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Preferences (colors + sizes)
# ------------------------------------------------------------
# These appear in Edit > Preferences > Add-ons > XNeko Tools.
# Redo-menu defaults live on the Scene instead (per-file).
# ============================================================
preference_props = {
    "tpa_line_0_color": FloatVectorProperty(
        name="Line 1 Color",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 0.0, 1.0),
    ),
    "tpa_line_1_color": FloatVectorProperty(
        name="Line 2 Color",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.5, 0.0, 1.0),
    ),
    "tpa_line_2_color": FloatVectorProperty(
        name="Line 3 Color",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.0, 0.0, 1.0),
    ),
    "tpa_select_color": FloatVectorProperty(
        name="Selection Color",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    ),
    "tpa_face_color": FloatVectorProperty(
        name="Face Color",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.65, 1.0, 0.2),
    ),
    "tpa_snap_distance": IntProperty(
        name="Snap Distance (px)", min=1, default=20,
    ),
    "tpa_point_size": IntProperty(
        name="Point Size (px)", min=1, default=10,
    ),
    "tpa_cross_size": IntProperty(
        name="Cross Size (px)", min=1, default=50,
    ),
}


# ============================================================
# Scene properties (redo-menu defaults)
# ============================================================
scene_props = {
    "xneko_tpa_show_origin": BoolProperty(
        name="Show Origin", default=False,
    ),
    "xneko_tpa_match_scale": BoolProperty(
        name="Match Scale", default=False,
    ),
    "xneko_tpa_origin_to_source": BoolProperty(
        name="Origin to Center 2", default=False,
    ),
    "xneko_tpa_set_transforms": BoolProperty(
        name="Recalculate Transform", default=False,
    ),
    "xneko_tpa_invert_x": BoolProperty(name="Invert X", default=False),
    "xneko_tpa_invert_y": BoolProperty(name="Invert Y", default=False),
    "xneko_tpa_invert_z": BoolProperty(name="Invert Z", default=False),
}


# ============================================================
# Imports (after metadata so classes can reference scene/pref names)
# ============================================================
from ._operators import (          # noqa: E402
    XNEKO_TPA_OT_check_selection,
    XNEKO_TPA_OT_align,
    XNEKO_TPA_OT_pick_line_colors,
    XNEKO_TPA_OT_pick_face_color,
    VIEW3D_PT_xneko_tpa,
)


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_TPA_OT_check_selection,
    XNEKO_TPA_OT_align,
    XNEKO_TPA_OT_pick_line_colors,
    XNEKO_TPA_OT_pick_face_color,
    VIEW3D_PT_xneko_tpa,
)


# ============================================================
# Draw function for the addon preferences panel
# ------------------------------------------------------------
# This is where the RED box from your screenshot lives:
#   colors + sizes + hotkey. All stored on the addon
#   preferences, not on the Scene.
# ============================================================
def draw_preferences(layout, context, prefs):
    import rna_keymap_ui

    # -------- Colors --------
    layout.label(text="Colors:", icon='COLOR')
    box = layout.box()
    col = box.column(align=True)
    prefs.prop(col, "tpa_line_0_color")
    prefs.prop(col, "tpa_line_1_color")
    prefs.prop(col, "tpa_line_2_color")
    prefs.prop(col, "tpa_select_color")
    prefs.prop(col, "tpa_face_color")

    # -------- Sizes --------
    layout.separator()
    layout.label(text="Sizes:", icon='FULLSCREEN_ENTER')
    box = layout.box()
    col = box.column(align=True)
    prefs.prop(col, "tpa_snap_distance")
    prefs.prop(col, "tpa_point_size")
    prefs.prop(col, "tpa_cross_size")

    # -------- Hotkey --------
    layout.separator()
    layout.label(text="Hotkey:", icon='KEYINGSET')
    box = layout.box()

    wm = context.window_manager
    kc = wm.keyconfigs.user
    km = kc.keymaps.get('3D View') if kc else None
    kmi = km.keymap_items.get('xneko.tpa_check_selection') if km else None

    if km and kmi:
        box.context_pointer_set("keymap", km)
        rna_keymap_ui.draw_kmi([], kc, km, kmi, box, 0)
    else:
        box.label(text="Keymap not registered", icon='ERROR')


# ============================================================
# Lifecycle
# ============================================================
_ADDON_KEYMAPS = []


def _register_hotkey():
    wm = bpy.context.window_manager
    if wm is None:
        return
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    km = kc.keymaps.get('3D View')
    if not km:
        km = kc.keymaps.new('3D View', space_type='VIEW_3D')

    if km.keymap_items.get('xneko.tpa_check_selection') is not None:
        return

    kmi = km.keymap_items.new(
        idname='xneko.tpa_check_selection',
        type='T', value='PRESS', alt=True,
    )
    _ADDON_KEYMAPS.append((km, kmi))


def _unregister_hotkey():
    for km, kmi in _ADDON_KEYMAPS:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _ADDON_KEYMAPS.clear()


def on_load():
    _register_hotkey()


def on_unload():
    _unregister_hotkey()
    try:
        from ._core import DRAW
        DRAW().handle_remove_all()
    except Exception:
        pass