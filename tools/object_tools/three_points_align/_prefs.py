"""Tool preference properties and their addon-preferences UI.

preference_props: injected into the addon preferences by the framework.
Only Match Distance is persisted; the other alignment options were
removed. The addon preferences panel shows Colors, Sizes, and Hotkey.

scene_props: applied to bpy.types.Scene by the framework. Used for the
object pickers drawn on the N panel.
"""

import bpy
import rna_keymap_ui
from bpy.props import (
    BoolProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
)


# ============================================================
# Addon preference properties
# ============================================================
preference_props = {
    # Alignment option (only one)
    "match_scale": BoolProperty(name='Match Distance', default=False),

    # Colors
    "line_0_color": FloatVectorProperty(
        name="Line 1 Color", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(1, 1, 0, 1),
    ),
    "line_1_color": FloatVectorProperty(
        name="Line 2 Color", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(1, 0.5, 0, 1),
    ),
    "line_2_color": FloatVectorProperty(
        name="Line 3 Color", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(1, 0, 0, 1),
    ),
    "select_color": FloatVectorProperty(
        name="Selection Color", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(1, 1, 1, 1),
    ),
    "face_color": FloatVectorProperty(
        name="Face Color", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0, 0.65, 1, 0.2),
    ),

    # Sizes
    "snap_distance": IntProperty(name='Snap Distance (px)', min=1, default=20),
    "point_size": IntProperty(name='Point Size (px)', min=1, default=10),
    "cross_size": IntProperty(name='Cross Size (px)', min=1, default=50),
}


# ============================================================
# Scene-level properties (object pickers for the N panel)
# ============================================================
def _mesh_only(self, obj):
    return obj is not None and obj.type == 'MESH'


scene_props = {
    "three_points_align_source": PointerProperty(
        name="Source",
        description="Source mesh object to align from",
        type=bpy.types.Object,
        poll=_mesh_only,
    ),
    "three_points_align_target": PointerProperty(
        name="Target",
        description="Target mesh object to align to",
        type=bpy.types.Object,
        poll=_mesh_only,
    ),
}


# ============================================================
# Addon preference draw function
# ============================================================
def draw_preferences(layout, context, prefs):
    """Draw the tool's per-tool UI in the addon preferences panel."""
    # ---------- Colors ----------
    layout.label(text='Colors:')
    box_color = layout.box()
    split = box_color.split()
    left_col = split.column()
    right_col = split.column()
    left_col.label(text='Line 1 Color')
    prefs.prop(right_col, 'line_0_color', text='')
    left_col.label(text='Line 2 Color')
    prefs.prop(right_col, 'line_1_color', text='')
    left_col.label(text='Line 3 Color')
    prefs.prop(right_col, 'line_2_color', text='')
    left_col.label(text='Selection Color')
    prefs.prop(right_col, 'select_color', text='')
    left_col.label(text='Face Color')
    prefs.prop(right_col, 'face_color', text='')

    # ---------- Sizes ----------
    layout.label(text='Sizes:')
    box_sizes = layout.box()
    split = box_sizes.split()
    left_col = split.column()
    right_col = split.column()
    left_col.label(text='Snap Distance (px)')
    prefs.prop(right_col, 'snap_distance', text='')
    left_col.label(text='Point Size (px)')
    prefs.prop(right_col, 'point_size', text='')
    left_col.label(text='Cross Size (px)')
    prefs.prop(right_col, 'cross_size', text='')

    # ---------- Hotkey ----------
    box = layout.box()
    box.label(text='Hotkey')
    wm = context.window_manager
    if wm is None:
        return
    kc = wm.keyconfigs.user
    if kc is None:
        return
    km = kc.keymaps.get('3D View')
    if km is None:
        return
    kmi = km.keymap_items.get('three_points_align.check_selection')
    if kmi is None:
        return
    box.context_pointer_set("keymap", km)
    rna_keymap_ui.draw_kmi([], kc, km, kmi, box, 0)