"""3 Points Align tool for XNeko Tools.

Original addon: "3 Points Align" by Barre Nick (汉化: GJJ).
Reproduced 1:1 inside the XNeko Tools framework.

Integration notes:
  - Addon preference properties live in _prefs.py (preference_props).
  - Scene-level object pickers live in _prefs.py (scene_props). The
    framework applies them to bpy.types.Scene.
  - N panel (object pickers + start button + Default Restore Menu)
    lives in _panel.py.
  - The addon preferences panel shows Colors, Sizes, Hotkey.
  - The hotkey is registered on tool load and released on unload.
  - Submodules use a leading underscore so the framework's package
    walker skips them; only this file imports them.
"""

tool_id = "three_points_align"
tool_name = "3 Points Align"
tool_default_enabled = True

from . import _operators
from . import _panel
from . import _prefs

preference_props = _prefs.preference_props
scene_props = _prefs.scene_props
draw_preferences = _prefs.draw_preferences

classes = (
    _operators.THREE_POINTS_ALIGN_OT_start,
    _operators.THREE_POINTS_ALIGN_OT_check_selection,
    _operators.THREE_POINTS_ALIGN_OT_align,
    _panel.THREE_POINTS_ALIGN_PT_settings,
)


def on_load():
    _operators.register_keymap()


def on_unload():
    _operators.unregister_keymap()