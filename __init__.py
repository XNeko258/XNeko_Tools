# ============================================================
# Add-on metadata
# ============================================================
bl_info = {
    "name": "XNeko Tools",
    "author": "XNeko, Shao qin",
    "version": (0, 8, 5),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > XNeko Tools",
    "description": (
        "This is a toolbox, you can freely modify any of its "
        "functions yourself, good luck"
    ),
    "doc_url": "https://github.com/XNeko258/XNeko_Tools",
    "tracker_url": "https://github.com/XNeko258/XNeko_Tools/issues",
    "category": "System",
}


import json

import bpy

from . import core
from . import preferences
from .common import error_reports as _reports


def _register_preference_classes():
    for tool in core._TOOL_REGISTRY.values():
        for cls in tool.get("preference_classes", ()):
            if not isinstance(cls, type):
                continue
            try:
                bpy.utils.register_class(cls)
            except Exception as e:
                print(
                    f"[XNeko] preference class {cls.__name__} failed: {e}"
                )
                _reports.report_tool_error(
                    f"preference class failed: {cls.__name__}",
                    exc=e,
                )


def _unregister_preference_classes():
    for tool in reversed(list(core._TOOL_REGISTRY.values())):
        for cls in reversed(tool.get("preference_classes", ())):
            if not isinstance(cls, type):
                continue
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass


def register():
    """Top-level register entry.

    Wraps _register_impl so any unexpected exception is written to
    logs/critical/ before propagation. The exception is still
    re-raised so Blender knows the addon failed to load.
    """
    try:
        _register_impl()
    except Exception as e:
        _reports.report_critical_error(
            "addon register() failed", exc=e,
        )
        raise


def _register_impl():
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
    # The duck-type filter in build_preferences_class catches the vast
    # majority of bad props, but it is not a full RNA validation. If a
    # prop still slips through and makes the class unregisterable, we
    # rebuild without per-tool props so the addon itself stays alive.
    preferences.XNekoPreferences = preferences.build_preferences_class()
    try:
        bpy.utils.register_class(preferences.XNekoPreferences)
    except Exception as e:
        print(f"[XNeko] XNekoPreferences registration failed: {e}")
        print("[XNeko] retrying without per-tool preference props")
        # Addon infrastructure failure: always-on critical channel.
        _reports.report_critical_error(
            "XNekoPreferences registration failed",
            exc=e,
            extra={"fallback": "include_tool_props=False"},
        )
        preferences.XNekoPreferences = (
            preferences.build_preferences_class(include_tool_props=False)
        )
        bpy.utils.register_class(preferences.XNekoPreferences)

    # ---- 4b. Flush tool reports queued during discovery ----
    # Discovery runs before preferences are registered, so tool
    # reports raised there are buffered. Now that XNekoPreferences
    # exists, the user toggle can be read and pending reports
    # written. No-op if the queue is empty or the toggle is off.
    _reports.flush_pending()

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
        "XNEKO_OT_open_user_reports_folder",
        "XNEKO_OT_open_critical_reports_folder",
        "XNEKO_OT_clear_user_reports",
        "XNEKO_OT_clear_critical_reports",
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
    from .common import icon_store as _icon_store
    _icon_store.clear()

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
        "XNEKO_OT_open_user_reports_folder",
        "XNEKO_OT_open_critical_reports_folder",
        "XNEKO_OT_clear_user_reports",
        "XNEKO_OT_clear_critical_reports",
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
    # _state.clear() resets groups / issues / previews but deliberately
    # leaves _TOOL_REGISTRY alone (discover_tools re-clears it on the
    # next register). Clear it here too so a disabled addon does not
    # expose a stale registry to external code.
    core._TOOL_REGISTRY.clear()