# ============================================================
# Add-on metadata
# ============================================================
bl_info = {
    "name": "XNeko Tools",
    "author": "XNeko, Shao qin",
    "version": (0, 9, 8),
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
    # 1. Discover tools and collect any registration issues.
    core._initialize_tools()

    # 2. Register every tool-owned PropertyGroup used by preferences.
    preferences.register_tool_preference_classes()

    # 3. Register the base property groups.
    bpy.utils.register_class(preferences.XNekoToolToggle)
    bpy.utils.register_class(preferences.XNEKO_ApplyPresetEntry)

    # 4. Build and register the dynamic XNekoPreferences class and
    #    every per-tool preference PropertyGroup. install_preferences
    #    handles the fallback path internally if a prop slips past
    #    the duck-typed filter.
    preferences.install_preferences()

    # 5. Flush tool reports queued during discovery.
    #
    # Discovery runs before preferences are registered, so reports
    # raised there are buffered. Now that XNekoPreferences exists,
    # the user toggle can be read and pending reports written. No-op
    # if the queue is empty or the toggle is off.
    _reports.flush_pending()

    # 6. Write registration issues and plugin version into prefs.
    try:
        prefs = bpy.context.preferences.addons[__name__].preferences
        prefs.registration_issues = json.dumps(core._state.registration_issues)
        prefs.plugin_version = core.get_plugin_version()
    except Exception as e:
        print(f"[XNeko] failed to write prefs metadata: {e}")

    # 7. Register the group panels and attach tool panels to them.
    core.register_group_panels()
    core.attach_panels_to_groups()

    # 8. Populate the toggle list and apply the panel category.
    preferences.init_tool_toggles()
    preferences.refresh_panel_category()

    # 9. Overlay the session state before loading anything, so tools
    #    that are on by default but disabled in the session never load.
    preferences.apply_session_if_any()

    # 10. Load every tool whose toggle is currently on.
    preferences.load_enabled_tools()

    # 11. Register the preference IO operators.
    for cls in preferences.iter_preference_operators():
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"[XNeko] register {cls.__name__} failed: {e}")

    # 12. Register the app handlers.
    bpy.app.handlers.load_post.append(preferences._on_load_post)
    bpy.app.handlers.save_pre.append(preferences._on_save_pre)


def unregister():
    # 1. Flush any pending session write and drop the icon cache.
    try:
        preferences._flush_session_now()
    except Exception:
        pass

    try:
        from .common import icon_store as _icon_store
        _icon_store.clear()
    except Exception:
        pass

    # 2. Remove the app handlers.
    try:
        bpy.app.handlers.save_pre.remove(preferences._on_save_pre)
    except Exception:
        pass
    try:
        bpy.app.handlers.load_post.remove(preferences._on_load_post)
    except Exception:
        pass

    # 3. Unregister the preference IO operators.
    for cls in reversed(list(preferences.iter_preference_operators())):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    # 4. Unload every loaded tool.
    core.unload_all_tools()

    # 5. Clear the toggle list.
    preferences.clear_tool_toggles()

    # 6. Remove the group panels.
    core.unregister_group_panels()

    # 7. Unregister the dynamic XNekoPreferences class and every
    #    per-tool preference PropertyGroup.
    preferences.uninstall_preferences()

    # 8. Unregister the base property groups.
    try:
        bpy.utils.unregister_class(preferences.XNEKO_ApplyPresetEntry)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(preferences.XNekoToolToggle)
    except Exception:
        pass

    # 9. Unregister tool-owned preference classes.
    preferences.unregister_tool_preference_classes()

    # 10. Clear the plugin state.
    #
    # _state.clear() resets groups / issues / previews but deliberately
    # leaves _TOOL_REGISTRY alone (discover_tools re-clears it on the
    # next register). Clear it here too so a disabled addon does not
    # expose a stale registry to external code.
    core._state.clear()
    core._TOOL_REGISTRY.clear()
    preferences._reset_panel_category_cache()