"""Tool preferences + scene property install/uninstall for the
XNeko Tools integration.

UFSettings (the per-scene import configuration) lives in
_importer/options.py. This module handles the toolbox-level
preferences and the scene property lifecycle.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty

from ._importer.options import UFSettings


# ============================================================
# Tool preferences (diagnostics toggles)
# ============================================================
preference_props = {
    "show_import_popup": BoolProperty(
        name="Show Import Time Popup",
        description=(
            "Show a popup with the import duration after each import. "
            "Intended for measuring performance; leave off for normal use"
        ),
        default=False,
    ),
    "profile_import": BoolProperty(
        name="Log Import Profile",
        description=(
            "Print a per-step timing breakdown to the console after each "
            "import. Intended for diagnosing slow imports"
        ),
        default=False,
    ),
}


def draw_preferences(layout, context, prefs) -> None:
    """Draw the diagnostics UI in the toolbox preferences panel."""
    box = layout.box()
    box.label(text="Diagnostics", icon="CONSOLE")
    prefs.prop(box, "show_import_popup")
    prefs.prop(box, "profile_import")


def get_diagnostics() -> tuple[bool, bool]:
    """Return (show_popup, profile_import) from the tool preferences."""
    try:
        from ....preferences import get_tool_prefs
        prefs = get_tool_prefs("ueformat")
    except Exception:
        return False, False
    if prefs is None:
        return False, False
    try:
        return bool(prefs.show_import_popup), bool(prefs.profile_import)
    except Exception:
        return False, False


# ============================================================
# Scene-level property polls and callbacks
# ============================================================
def _armature_only(self, obj):
    return obj is not None and obj.type == "ARMATURE"


def _on_pose_skeleton_changed(self, context):
    root = getattr(self, "ueformat_pose_root_bone", None)
    if root is None:
        return
    armature = getattr(self, "ueformat_pose_skeleton", None)
    if armature is None or root.id_data != armature.data:
        self.ueformat_pose_root_bone = None


# ============================================================
# Scene property definitions and install/uninstall
# ============================================================
_SCENE_PROPS = {
    "ueformat_settings": bpy.props.PointerProperty(type=UFSettings),

    "ueformat_anim_skeleton": bpy.props.PointerProperty(
        name="Override Skeleton",
        description="Armature to apply the animation to",
        type=bpy.types.Object,
        poll=_armature_only,
    ),
    "ueformat_pose_skeleton": bpy.props.PointerProperty(
        name="Override Skeleton",
        description="Armature to apply the pose to",
        type=bpy.types.Object,
        poll=_armature_only,
        update=_on_pose_skeleton_changed,
    ),
    "ueformat_pose_root_bone": bpy.props.StringProperty(
        name="Root Bone",
        description="Leave empty to use the armature's first bone",
        default="",
    ),
}


def install_scene_props() -> None:
    for name, prop in _SCENE_PROPS.items():
        if hasattr(bpy.types.Scene, name):
            continue
        try:
            setattr(bpy.types.Scene, name, prop)
        except Exception as e:
            print(f"[XNeko/UEFORMAT] failed to install scene prop "
                  f"{name}: {e}")


def uninstall_scene_props() -> None:
    for name in _SCENE_PROPS:
        if hasattr(bpy.types.Scene, name):
            try:
                delattr(bpy.types.Scene, name)
            except Exception:
                pass