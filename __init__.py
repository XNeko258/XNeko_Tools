# ============================================================
# Add-on metadata
# ------------------------------------------------------------
# bl_info is read by Blender when scanning the add-ons folder.
# It defines the entry shown in Edit > Preferences > Add-ons.
# ============================================================
bl_info = {
    "name": "XNeko Tools",
    "author": "XNeko, Shao qin",
    "version": (0, 5, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > XNeko Tools",
    "description": (
        "This is a toolbox, you can freely modify any of its "
        "functions yourself, good luck"
    ),
    "category": "System",
}


import bpy

# Local submodules of this package
from . import core         # engine: discovery, registration, grouping
from . import preferences  # add-on preferences UI and per-tool toggles


# ============================================================
# register()
# ------------------------------------------------------------
# Called by Blender when the add-on is enabled.
#
# Order matters:
#   1. PropertyGroups must exist before anything references them.
#   2. Tools must be discovered before group panels are built.
#   3. Group panels must be registered before tool panels are
#      attached to them as children.
#   4. Tool toggles must be initialised before the category is
#      refreshed, so the tab list is complete.
#   5. Default tools are loaded last, once everything is ready.
# ============================================================
def register():
    # ---- 1. Base classes (PropertyGroups + preferences) ----
    bpy.utils.register_class(preferences.XNEKO_OT_set_active_category)
    bpy.utils.register_class(preferences.XNEKO_OT_shift_tab_page)
    bpy.utils.register_class(preferences.XNekoToolToggle)
    bpy.utils.register_class(preferences.XNekoPreferences)

    # ---- 2. Discover all tool modules under tools/ ----
    # Populates core._TOOL_REGISTRY from the file system.
    core.discover_tools(__name__, __path__)

    # ---- 3. Build collapsible group panels (one per category) ----
    core.register_group_panels()

    # ---- 4. Attach each tool's Panel to its group panel ----
    # Also forces all child panels to be collapsed by default.
    core.attach_panels_to_groups()

    # ---- 5. Populate the per-tool toggle list in preferences ----
    # Must happen after discovery, before any refresh calls.
    preferences.init_tool_toggles()

    # ---- 6. Apply the category name to every registered panel ----
    preferences.refresh_panel_category()

    # ---- 7. Load the tools that are enabled by default ----
    core.load_default_tools()


# ============================================================
# unregister()
# ------------------------------------------------------------
# Called by Blender when the add-on is disabled.
#
# Reverse order of register():
#   1. Unload every tool (removes its classes + scene props).
#   2. Clear stored toggle list from preferences.
#   3. Remove group panels.
#   4. Unregister the base classes last.
# ============================================================
def unregister():
    # ---- 1. Unload every tool currently loaded ----
    core.unload_all_tools()

    # ---- 2. Wipe the stored toggle list ----
    preferences.clear_tool_toggles()

    # ---- 3. Remove all group (category) panels ----
    core.unregister_group_panels()

    # ---- 4. Unregister base classes (reverse of register order) ----
    bpy.utils.unregister_class(preferences.XNekoPreferences)
    bpy.utils.unregister_class(preferences.XNekoToolToggle)
    bpy.utils.unregister_class(preferences.XNEKO_OT_shift_tab_page) 
    bpy.utils.unregister_class(preferences.XNEKO_OT_set_active_category)