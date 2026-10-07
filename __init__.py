# ============================================================
# Add-on metadata
# ============================================================
bl_info = {
    "name": "XNeko Tools",
    "author": "XNeko, Shao qin",
    "version": (0, 7, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > XNeko Tools",
    "description": (
        "This is a toolbox, you can freely modify any of its "
        "functions yourself, good luck"
    ),
    "category": "System",
}


import json

import bpy

from . import core
from . import preferences


def _register_preference_classes():
    for tool in core._TOOL_REGISTRY.values():
        for cls in tool.get("preference_classes", ()):
            if not isinstance(cls, type):
                continue
            try:
                bpy.utils.register_class(cls)
            except Exception as e:
                print(f"[XNeko] preference class {cls.__name__} failed: {e}")


def _unregister_preference_classes():
    for tool in reversed(list(core._TOOL_REGISTRY.values())):
        for cls in reversed(tool.get("preference_classes", ())):
            if not isinstance(cls, type):
                continue
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass


#   3. Build XNekoPreferences dynamically (props must be in
def register():
    # ---- 1. Discovery + issue collection ----
    core._initialize_tools()

    # ---- 2. Tool-owned PropertyGroups used by preferences ----
    _register_preference_classes()

    # ---- 3. Base operator / property classes ----
    bpy.utils.register_class(preferences.XNEKO_OT_set_active_category)
    bpy.utils.register_class(preferences.XNEKO_OT_shift_tab_page)
    bpy.utils.register_class(preferences.XNekoToolToggle)
    bpy.utils.register_class(preferences.XNEKO_ApplyPresetEntry)

    # ---- 4. Build XNekoPreferences with dynamic per-tool props ----
    preferences.XNekoPreferences = preferences.build_preferences_class()
    bpy.utils.register_class(preferences.XNekoPreferences)

    # ---- 5. Write registration issues + plugin version into prefs ----
    try:
        prefs = bpy.context.preferences.addons[__name__].preferences
        prefs.registration_issues = json.dumps(core._state.registration_issues)
        prefs.plugin_version = core.get_plugin_version()
    except Exception as e:
        print(f"[XNeko] failed to write prefs metadata: {e}")

    # ---- 6. Panels ----
    core.register_group_panels()
    core.attach_panels_to_groups()

    # ---- 7. Toggles + category + defaults ----
    preferences.init_tool_toggles()
    preferences.refresh_panel_category()
    core.load_default_tools()

    # ---- 7b. Restore last session state, if any ----
    # Overrides the defaults that were just applied, so the user's
    # last-known tool enable flags survive Blender restarts.
    preferences.apply_session_if_any()

    # ---- 8. Preference IO operators ----
    for name in (
        "XNEKO_OT_export_prefs",
        "XNEKO_OT_import_prefs",
        "XNEKO_OT_confirm_overwrite",
        "XNEKO_OT_apply_preset",
        "XNEKO_OT_apply_preset_select_all",
        "XNEKO_OT_delete_preset",
        "XNEKO_OT_refresh_presets",
        "XNEKO_OT_apply_project_prefs",
        "XNEKO_OT_clear_project_prefs",
        "XNEKO_OT_rescan_tools",
        "XNEKO_OT_open_log_folder",
    ):
        cls = getattr(preferences, name, None)
        if cls is None:
            print(f"[XNeko] missing operator: {name}")
            continue
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"[XNeko] register {name} failed: {e}")

    # ---- 9. Handlers ----
    bpy.app.handlers.load_post.append(preferences._on_load_post)
    bpy.app.handlers.save_pre.append(preferences._on_save_pre)


def unregister():
    # ---- 0. Handlers first ----
    try:
        bpy.app.handlers.save_pre.remove(preferences._on_save_pre)
    except Exception:
        pass
    try:
        bpy.app.handlers.load_post.remove(preferences._on_load_post)
    except Exception:
        pass

    # ---- 1. Preference IO operators ----
    for name in (
        "XNEKO_OT_clear_project_prefs",
        "XNEKO_OT_apply_project_prefs",
        "XNEKO_OT_refresh_presets",
        "XNEKO_OT_delete_preset",
        "XNEKO_OT_apply_preset",
        "XNEKO_OT_apply_preset_select_all",
        "XNEKO_OT_confirm_overwrite",
        "XNEKO_OT_import_prefs",
        "XNEKO_OT_export_prefs",
        "XNEKO_OT_rescan_tools",
        "XNEKO_OT_open_log_folder",
    ):
        cls = getattr(preferences, name, None)
        if cls is None:
            continue
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    # ---- 2. Unload every loaded tool ----
    core.unload_all_tools()

    # ---- 3. Clear toggle list ----
    preferences.clear_tool_toggles()

    # ---- 4. Remove group panels ----
    core.unregister_group_panels()

    # ---- 5. Base classes (reverse of registration) ----
    if preferences.XNekoPreferences is not None:
        try:
            bpy.utils.unregister_class(preferences.XNekoPreferences)
        except Exception:
            pass
        preferences.XNekoPreferences = None

    bpy.utils.unregister_class(preferences.XNEKO_ApplyPresetEntry)
    bpy.utils.unregister_class(preferences.XNekoToolToggle)
    bpy.utils.unregister_class(preferences.XNEKO_OT_shift_tab_page)
    bpy.utils.unregister_class(preferences.XNEKO_OT_set_active_category)

    # ---- 6. Preference helper PropertyGroups ----
    _unregister_preference_classes()

    # ---- 7. Clear plugin state ----
    core._state.clear()