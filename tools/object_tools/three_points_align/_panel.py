"""N panel for the 3 Points Align tool.

Layout:
  - Object pickers (Source / Target) with eyedropper
  - "Connect & Align" button
  - Options: Match Distance (the only remaining alignment option)

The framework attaches this panel under the object_tools group panel
and applies the configured N panel category.
"""

import bpy

from . import _operators


def _get_prefs():
    from ....preferences import get_tool_prefs
    return get_tool_prefs("three_points_align")


class THREE_POINTS_ALIGN_PT_settings(bpy.types.Panel):
    bl_label = "3 Points Align"
    bl_idname = "THREE_POINTS_ALIGN_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XNeko Tools"

    def draw(self, context):
        layout = self.layout
        prefs = _get_prefs()
        if prefs is None:
            layout.label(text="Tool preferences unavailable", icon='ERROR')
            return

        scene = context.scene
        modal_active = _operators.is_modal_active()

        # ---------- Object pickers ----------
        box = layout.box()
        box.label(text="Objects:")
        col = box.column(align=True)
        col.prop(scene, "three_points_align_source", text="Source")
        col.prop(scene, "three_points_align_target", text="Target")

        # ---------- Start button ----------
        row = box.row()
        row.scale_y = 1.4
        if modal_active:
            row.enabled = False
            row.operator(
                "three_points_align.start",
                text="Connection Mode Active",
                icon='LOCKED',
            )
            hint = box.row()
            hint.alignment = 'CENTER'
            hint.label(text="Press ESC or RMB to exit", icon='INFO')
        else:
            row.operator(
                "three_points_align.start",
                text="Connect & Align",
                icon='PLAY',
            )

        layout.separator()

        # ---------- Options ----------
        layout.label(text='Options:')
        box = layout.box()
        row = box.row()
        prefs.prop(row, 'match_scale', text='Match Distance')