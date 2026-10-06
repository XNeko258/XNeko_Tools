import bpy
import pkgutil
import importlib
import sys
import gc


# ============================================================
# Category icon mapping
# ------------------------------------------------------------
# Used by the preferences tab bar.
# Keyed by keyword found in the category folder name.
# Case-insensitive; first hit wins.
# ============================================================
_GROUP_ICON_MAP = (
    ("shapekey",   "SHAPEKEY_DATA"),
    ("shape_key",  "SHAPEKEY_DATA"),
    ("bone",       "BONE_DATA"),
    ("armature",   "ARMATURE_DATA"),
    ("pose",       "POSE_HLT"),
    ("rig",        "ARMATURE_DATA"),
    ("constraint", "CONSTRAINT"),
    ("vertex",     "GROUP_VERTEX"),
    ("mesh",       "MESH_DATA"),
    ("uv",         "UV"),
    ("modifier",   "MODIFIER"),
    ("sculpt",     "SCULPTMODE_HLT"),
    ("object",     "OBJECT_DATA"),
    ("collection", "OUTLINER_COLLECTION"),
    ("scene",      "SCENE_DATA"),
    ("world",      "WORLD_DATA"),
    ("camera",     "CAMERA_DATA"),
    ("light",      "LIGHT"),
    ("material",   "MATERIAL"),
    ("texture",    "TEXTURE_DATA"),
    ("node",       "NODETREE"),
    ("shader",     "NODE_MATERIAL"),
    ("animation",  "ANIM_DATA"),
    ("anim",       "ANIM_DATA"),
    ("keyframe",   "KEYFRAME_HLT"),
    ("driver",     "DRIVER"),
    ("curve",      "CURVE_DATA"),
    ("image",      "IMAGE_DATA"),
    ("text",       "TEXT"),
    ("particle",   "PARTICLE_DATA"),
    ("physics",    "PHYSICS"),
    ("hair",       "HAIR"),
    ("grease",     "GREASEPENCIL"),
    ("asset",      "ASSET_MANAGER"),
    ("library",    "LIBRARY_DATA_DIRECT"),
    ("file",       "FILE"),
)


def _get_group_icon(group_id):
    """Return a Blender icon name for the given category id."""
    key = group_id.lower().replace(" ", "_").replace("-", "_")
    for token, icon in _GROUP_ICON_MAP:
        if token in key:
            return icon
    return "FILE_FOLDER"


# ============================================================
# Version compatibility
# ============================================================
def _check_tool_compatibility(module):
    """Return (compatible, reason).

    A tool module may declare:

        blender_version_min = (4, 0, 0)   # inclusive lower bound
        blender_version_max = (4, 3, 0)   # inclusive upper bound

    Either may be omitted. Compared as 3-tuples.
    """
    bv = tuple(bpy.app.version)[:3]
    current = ".".join(str(v) for v in bv)

    min_v = getattr(module, "blender_version_min", None)
    max_v = getattr(module, "blender_version_max", None)

    if min_v is not None and bv < tuple(min_v)[:3]:
        req = ".".join(str(v) for v in min_v[:3])
        return False, f"Requires Blender {req}+ (current {current})"

    if max_v is not None and bv > tuple(max_v)[:3]:
        req = ".".join(str(v) for v in max_v[:3])
        return False, f"Supports Blender up to {req} (current {current})"

    return True, ""


# ============================================================
# Registries
# ============================================================
_TOOL_REGISTRY = {}          # full module name -> tool dict
_GROUP_PANELS = {}
_GROUP_PANEL_CLASSES = []


# ============================================================
# Discovery
# ============================================================
def discover_tools(package_name, package_path):
    """Recursively scan the package for tool modules.

    A module counts as a tool if it declares a module-level
    `classes` tuple. Modules without it are treated as plain
    helper files and skipped.

    Optional module attributes read here:

        tool_name              str   display name
        tool_default_enabled   bool  default state of the toggle
        classes                tuple classes to register on load
        preference_classes     tuple PropertyGroups needed *before*
                                     XNekoPreferences is registered
        preference_props       dict  {name: Property} -> injected
                                     into XNekoPreferences
        preferences_in_addon   bool  if False, skip per-tool prefs UI
                                     in the addon preferences panel
        draw_preferences       fn(layout, context, prefs)  optional
                                     custom prefs UI
        scene_props            dict  {name: Property} -> Scene
        blender_version_min    tuple inclusive lower bound
        blender_version_max    tuple inclusive upper bound
        on_load / on_unload    callables
    """
    _TOOL_REGISTRY.clear()

    prefix = f"{package_name}."
    for info in pkgutil.walk_packages(package_path, prefix=prefix):
        short = info.name.rsplit(".", 1)[-1]
        if short.startswith("_"):
            continue

        try:
            module = importlib.import_module(info.name)
        except Exception as e:
            print(f"[XNeko] import failed {info.name}: {e}")
            continue

        classes = getattr(module, "classes", None)
        if not classes:
            continue

        # group id = dotted folder path under tools/ (e.g. "bone_tools")
        rel = info.name[len(prefix):]
        parts = rel.split(".")[:-1]
        if parts and parts[0] == "tools":
            parts = parts[1:]
        group_id = ".".join(parts)

        _TOOL_REGISTRY[info.name] = {
            "module_name": info.name,
            "module": module,
            "group_id": group_id,
            "display_name": getattr(
                module, "tool_name", short.replace("_", " ").title()
            ),
            "enabled_by_default": getattr(module, "tool_default_enabled", True),
            "classes": tuple(classes),
            "preference_classes": tuple(
                getattr(module, "preference_classes", ())
            ),
            "preference_props": dict(
                getattr(module, "preference_props", {})
            ),
            "preferences_in_addon": getattr(
                module, "preferences_in_addon", True
            ),
            "draw_preferences": getattr(module, "draw_preferences", None),
            "scene_props": dict(getattr(module, "scene_props", {})),
            "on_load": getattr(module, "on_load", None),
            "on_unload": getattr(module, "on_unload", None),

            # Version compatibility
            "compatible": True,
            "incompatible_reason": "",

            "loaded": False,
        }

        # Version check right after building the record
        tool = _TOOL_REGISTRY[info.name]
        ok, reason = _check_tool_compatibility(module)
        tool["compatible"] = ok
        tool["incompatible_reason"] = reason
        if not ok:
            print(f"[XNeko] {info.name}: {reason}")


# ============================================================
# Group panels
# ============================================================
def _make_group_panel(group_id, display_name, category):
    """Create a collapsible Panel class for the given group."""
    safe = group_id.replace(".", "_").replace(" ", "_")
    bl_idname = f"VIEW3D_PT_xneko_grp_{safe}"

    def _poll(cls, context):
        # Show only if at least one tool in this group is loaded
        for tool in _TOOL_REGISTRY.values():
            if tool["group_id"] == group_id and tool["loaded"]:
                return True
        return False

    return type(
        f"XNekoGroupPanel_{safe}",
        (bpy.types.Panel,),
        {
            "bl_label": display_name,
            "bl_idname": bl_idname,
            "bl_space_type": 'VIEW_3D',
            "bl_region_type": 'UI',
            "bl_category": category,
            "bl_options": {'DEFAULT_CLOSED'},
            "poll": classmethod(_poll),
            "draw": lambda self, ctx: None,
        },
    )


def register_group_panels(category="XNeko Tools"):
    """Create and register one panel per discovered group."""
    # Ensure idempotency if called twice in a row
    unregister_group_panels()

    groups = {}
    for tool in _TOOL_REGISTRY.values():
        gid = tool["group_id"]
        if gid:
            groups.setdefault(
                gid,
                gid.replace(".", " / ").replace("_", " ").title(),
            )

    for gid, display in groups.items():
        cls = _make_group_panel(gid, display, category)
        _GROUP_PANELS[gid] = cls
        _GROUP_PANEL_CLASSES.append(cls)
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"[XNeko] group panel {gid} failed: {e}")


def unregister_group_panels():
    """Unregister every group panel."""
    for cls in reversed(_GROUP_PANEL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _GROUP_PANELS.clear()
    _GROUP_PANEL_CLASSES.clear()


def attach_panels_to_groups(tool=None):
    """Attach a tool's Panel classes to its group panel and collapse
    them by default.

    When `tool` is None, iterate over every registered tool.
    Callers may pass a single tool dict to re-attach after a hot
    reload of that module.
    """
    tools = _TOOL_REGISTRY.values() if tool is None else (tool,)

    for t in tools:
        gid = t["group_id"]
        parent_cls = _GROUP_PANELS.get(gid)
        if parent_cls is None:
            continue

        parent_id = parent_cls.bl_idname
        for cls in t["classes"]:
            if not isinstance(cls, type) or not issubclass(cls, bpy.types.Panel):
                continue

            cls.bl_parent_id = parent_id

            # getattr: Panel classes without an explicit bl_options
            # raise AttributeError on direct access
            existing = set(getattr(cls, "bl_options", set()))
            if 'DEFAULT_CLOSED' not in existing:
                cls.bl_options = existing | {'DEFAULT_CLOSED'}


# ============================================================
# Load / unload
# ============================================================
def load_tool(tool_id):
    """Register the classes and scene props of a single tool."""
    tool = _TOOL_REGISTRY.get(tool_id)
    if not tool or tool["loaded"]:
        return

    # Refuse to load version-incompatible tools
    if not tool.get("compatible", True):
        print(f"[XNeko] refusing to load {tool_id}: "
              f"{tool['incompatible_reason']}")
        return

    # Hot reload path: re-import the module if a previous unload
    # evicted it from sys.modules.
    if tool["module"] is None:
        try:
            module = importlib.import_module(tool["module_name"])
        except Exception as e:
            print(f"[XNeko] re-import {tool['module_name']} failed: {e}")
            return

        tool["module"] = module
        tool["classes"] = tuple(getattr(module, "classes", ()))
        tool["scene_props"] = dict(getattr(module, "scene_props", {}))
        tool["on_load"] = getattr(module, "on_load", None)
        tool["on_unload"] = getattr(module, "on_unload", None)

    # ------------------------------------------------------------
    # IMPORTANT: set bl_parent_id / bl_options BEFORE register_class.
    # Blender reads these at registration time; changing them after
    # registration has no effect on the UI.
    # ------------------------------------------------------------
    attach_panels_to_groups(tool)

    # PropertyGroups must exist before other classes reference them
    for cls in tool["classes"]:
        if isinstance(cls, type) and issubclass(cls, bpy.types.PropertyGroup):
            try:
                bpy.utils.register_class(cls)
            except Exception as e:
                print(f"[XNeko] register PropertyGroup {cls.__name__} failed: {e}")

    # Then everything else
    for cls in tool["classes"]:
        if isinstance(cls, type) and not issubclass(cls, bpy.types.PropertyGroup):
            try:
                bpy.utils.register_class(cls)
            except Exception as e:
                print(f"[XNeko] register {cls.__name__} failed: {e}")

    # Attach scene-level properties
    for name, prop in tool["scene_props"].items():
        setattr(bpy.types.Scene, name, prop)

    # Optional load callback
    if callable(tool["on_load"]):
        try:
            tool["on_load"]()
        except Exception as e:
            print(f"[XNeko] on_load for {tool_id} failed: {e}")

    tool["loaded"] = True


def unload_tool(tool_id):
    """Unregister the classes and scene props of a single tool,
    then release the underlying Python module.
    """
    tool = _TOOL_REGISTRY.get(tool_id)
    if not tool or not tool["loaded"]:
        return

    # Optional unload callback (before removing classes)
    if callable(tool["on_unload"]):
        try:
            tool["on_unload"]()
        except Exception as e:
            print(f"[XNeko] on_unload for {tool_id} failed: {e}")

    # Remove scene properties
    for name in tool["scene_props"]:
        try:
            delattr(bpy.types.Scene, name)
        except Exception:
            pass

    # Unregister classes in reverse order
    for cls in reversed(tool["classes"]):
        if isinstance(cls, type):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass

    # ------------------------------------------------------------
    # True release of the module
    # ------------------------------------------------------------
    module_name = tool["module_name"]

    # 1. Drop the registry's strong reference to the module object
    tool["module"] = None

    # 2. Remove it from sys.modules so Python allows re-importing
    sys.modules.pop(module_name, None)

    # 3. Clear cached references to the old class objects
    tool["classes"] = ()
    tool["scene_props"] = {}
    tool["on_load"] = None
    tool["on_unload"] = None

    # 4. Collect now (optional)
    gc.collect()

    tool["loaded"] = False


def set_tool_enabled(tool_id, enabled):
    """Set a tool's enabled state and sync load/unload.

    Used by:
      - addon preferences tool toggles
      - preset application
      - project-file preference application

    Returns True if the change was applied, False otherwise.
    """
    tool = _TOOL_REGISTRY.get(tool_id)
    if tool is None:
        return False

    if enabled and not tool.get("compatible", True):
        print(f"[XNeko] cannot enable {tool_id}: "
              f"{tool['incompatible_reason']}")
        return False

    if enabled:
        load_tool(tool_id)
    else:
        unload_tool(tool_id)
    return True


def load_default_tools():
    """Load every tool whose `tool_default_enabled` is True."""
    for tool_id, tool in _TOOL_REGISTRY.items():
        if tool["enabled_by_default"]:
            set_tool_enabled(tool_id, True)


def unload_all_tools():
    """Unload every currently loaded tool."""
    for tool_id in tuple(_TOOL_REGISTRY):
        unload_tool(tool_id)