import bpy
import pkgutil
import importlib
import importlib.util
import sys
import gc
import os
import re
import json


# ============================================================
# Constants
# ============================================================
MAX_ICON_DIMENSION = 64
RECOMMENDED_ICON_DIMENSION = 32

IMAGE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff", ".webp",
)

TOOL_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")

REGISTRATION_OK = ""
REGISTRATION_MISSING_TOOL_ID = "missing_tool_id"
REGISTRATION_INVALID_TOOL_ID = "invalid_tool_id"
REGISTRATION_DUPLICATE_TOOL_ID = "duplicate_tool_id"

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "xneko_tools.log"
LOG_FILE_MAX_BYTES = 1024 * 1024


# ============================================================
# Plugin state
# ============================================================
class PluginState:
    def __init__(self):
        self.registered_groups = {}
        self.registration_issues = []
        self.icon_previews = None
        self.debug_fallback = False

    def reset_registration(self):
        self.registered_groups.clear()
        self.registration_issues = []

    def reset_previews(self):
        if self.icon_previews is not None:
            try:
                bpy.utils.previews.remove(self.icon_previews)
            except Exception as exc:
                log_debug(f"Failed to remove stale preview collection: {exc}")
            self.icon_previews = None

        self.icon_previews = bpy.utils.previews.new()

        for group_data in self.registered_groups.values():
            group_data["icon"] = None

    def clear(self):
        if self.icon_previews is not None:
            try:
                bpy.utils.previews.remove(self.icon_previews)
            except Exception as exc:
                log_debug(f"Failed to remove preview collection: {exc}")
            self.icon_previews = None

        self.registered_groups.clear()
        self.registration_issues = []

    def get_previews(self):
        if self.icon_previews is None:
            self.icon_previews = bpy.utils.previews.new()
        return self.icon_previews


_state = PluginState()


# ============================================================
# Category icon mapping (fallback)
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
# Tool id helpers
# ============================================================
def get_tool_id(module):
    """Return the explicit tool_id defined by the tool module."""
    return getattr(module, "tool_id", None)


def is_valid_tool_id(tool_id):
    """Return True if tool_id is safe to use as a property name prefix."""
    if not tool_id or not isinstance(tool_id, str):
        return False
    return bool(TOOL_ID_PATTERN.match(tool_id))


# ============================================================
# Logging
# ============================================================
def set_debug_fallback(enabled):
    _state.debug_fallback = bool(enabled)


def _is_debug_enabled():
    enabled = _state.debug_fallback
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        if addon is not None:
            enabled = bool(
                getattr(addon.preferences, "debug_registration", False)
            )
    except Exception:
        pass
    return enabled


def log_debug(message):
    if _is_debug_enabled():
        print(f"[XNeko_Tools] {message}")


# Writability probes are cached per folder. Directory writability does
# not change at runtime in normal use, so one probe per path is enough.
# The cache is cleared on rescan_tools() so permission changes are
# picked up without a restart.
_dir_writable_cache = {}


def _is_dir_writable(folder):
    """Best-effort check: can we create a file here? Cached per folder."""
    cached = _dir_writable_cache.get(folder)
    if cached is not None:
        return cached

    result = False
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_probe")
        with open(probe, "w") as handle:
            handle.write("")
        os.remove(probe)
        result = True
    except OSError:
        result = False

    _dir_writable_cache[folder] = result
    return result


def get_log_dir():
    addon_dir = os.path.join(os.path.dirname(__file__), LOG_DIR_NAME)
    if _is_dir_writable(addon_dir):
        return addon_dir

    return bpy.utils.user_resource(
        "CONFIG",
        path=os.path.join("xneko_tools", LOG_DIR_NAME),
        create=True,
    )


def get_log_file_path():
    return os.path.join(get_log_dir(), LOG_FILE_NAME)


def log_to_file(message):
    if not _is_debug_enabled():
        return
    try:
        path = get_log_file_path()
        if os.path.exists(path) and os.path.getsize(path) > LOG_FILE_MAX_BYTES:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


def _report_issue(line):
    print(line)
    log_to_file(line)


def get_plugin_version():
    try:
        from . import bl_info
        return ".".join(str(v) for v in bl_info["version"])
    except Exception:
        return "0.0.0"


# ============================================================
# Version compatibility
# ============================================================
def _check_tool_compatibility(module):
    """Return (compatible, reason)."""
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
_TOOL_REGISTRY = {}
_GROUP_PANELS = {}
_GROUP_PANEL_CLASSES = []


# ------------------------------------------------------------
# Registry helpers
# ------------------------------------------------------------
def get_short_id(full_id):
    """Single source of truth for full_id -> short_id.

    Used by both preferences.py and common/prefs_io.py so the mapping
    can no longer drift between modules. Falls back to the dotted path
    when a tool is not registered or lacks a tool_id.
    """
    tool = _TOOL_REGISTRY.get(full_id)
    if tool is not None:
        tid = tool.get("tool_id")
        if tid:
            return tid
    return full_id.split(".tools.", 1)[-1] if ".tools." in full_id else full_id


# ============================================================
# Discovery
# ============================================================
def discover_tools(package_name, package_path):
    _TOOL_REGISTRY.clear()
    _state.registration_issues = []

    prefix = f"{package_name}."
    for info in pkgutil.walk_packages(package_path, prefix=prefix):
        short = info.name.rsplit(".", 1)[-1]
        if short.startswith("_"):
            continue

        try:
            module = importlib.import_module(info.name)
        except Exception as e:
            _state.registration_issues.append({
                "type": "import_failed",
                "tool_id": "",
                "paths": [info.name],
                "error": str(e),
            })
            _report_issue(f"[XNeko] import failed {info.name}: {e}")
            continue

        classes = getattr(module, "classes", None)
        if not classes:
            continue

        tool_id = get_tool_id(module)
        module_path = getattr(module, "__file__", info.name)

        if not tool_id:
            _state.registration_issues.append({
                "type": "missing_tool_id",
                "tool_id": "",
                "paths": [module_path],
            })
            _report_issue(
                f"[XNeko] Module missing required tool_id: {module_path}. "
                f"Skipped."
            )
            continue

        if not is_valid_tool_id(tool_id):
            _state.registration_issues.append({
                "type": "invalid_tool_id",
                "tool_id": tool_id,
                "paths": [module_path],
            })
            _report_issue(
                f"[XNeko] Invalid tool_id: '{tool_id}' in {module_path}. "
                f"Only lowercase letters, digits, and underscores are "
                f"allowed. Skipped."
            )
            continue

        rel = info.name[len(prefix):]
        rel_parts = rel.split(".")
        dir_parts = rel_parts[:-1]

        if dir_parts and dir_parts[0] == "tools":
            group_id = ".".join(dir_parts[1:])
        else:
            group_id = ".".join(dir_parts)

        if dir_parts:
            group_path = os.path.join(package_path[0], *dir_parts)
        else:
            group_path = package_path[0]

        # Version bounds are cached on the tool record so they survive
        # tool unload (which sets module to None).
        min_v = getattr(module, "blender_version_min", None)
        max_v = getattr(module, "blender_version_max", None)

        _TOOL_REGISTRY[info.name] = {
            "module_name": info.name,
            "tool_id": tool_id,
            "module": module,
            "group_id": group_id,
            "group_path": group_path,
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

            # Persisted version bounds (module-independent).
            "version_min": list(min_v[:3]) if min_v else None,
            "version_max": list(max_v[:3]) if max_v else None,

            "compatible": True,
            "incompatible_reason": "",

            "loaded": False,
        }

        tool = _TOOL_REGISTRY[info.name]
        ok, reason = _check_tool_compatibility(module)
        tool["compatible"] = ok
        tool["incompatible_reason"] = reason
        if not ok:
            print(f"[XNeko] {info.name}: {reason}")

        log_debug(f"Discovered tool module: {info.name} (tool_id={tool_id})")


def collect_registration_issues():
    by_id = {}
    for full_id, tool in _TOOL_REGISTRY.items():
        by_id.setdefault(tool["tool_id"], []).append((full_id, tool))

    collisions_to_remove = []

    for tool_id, entries in by_id.items():
        if len(entries) > 1:
            paths = [
                getattr(t["module"], "__file__", full_id)
                for full_id, t in entries
            ]
            _state.registration_issues.append({
                "type": "collision",
                "tool_id": tool_id,
                "paths": paths,
            })
            _report_issue(
                f"[XNeko] Tool id collision detected: '{tool_id}'. "
                f"All conflicting tools are disabled."
            )
            for path in paths:
                _report_issue(f"[XNeko]   {path}")
            for full_id, _ in entries:
                collisions_to_remove.append(full_id)

    for full_id in collisions_to_remove:
        _TOOL_REGISTRY.pop(full_id, None)

    return list(_state.registration_issues)


def register_tool_module(module, registry):
    """Public API for external packages and tests.

    This function is not called anywhere inside XNeko Tools itself.
    It exists so that external code (a companion package, a test
    harness, a one-off script) can register a single tool module
    without re-running the whole discovery pipeline.

    `registry` must be a mapping shaped like core._TOOL_REGISTRY
    ({full_module_name: tool_dict}). Pass core._TOOL_REGISTRY directly
    unless you have a specific reason not to.

    Returns (success, reason) where reason is one of the
    REGISTRATION_* constants.
    """
    tool_id = get_tool_id(module)
    module_name = getattr(module, "__name__", "")
    module_path = getattr(module, "__file__", module_name)

    if not tool_id:
        _report_issue(
            f"[XNeko] Module missing required tool_id: {module_path}. "
            f"Skipped."
        )
        return False, REGISTRATION_MISSING_TOOL_ID

    if not is_valid_tool_id(tool_id):
        _report_issue(
            f"[XNeko] Invalid tool_id: '{tool_id}' in {module_path}. "
            f"Only lowercase letters, digits, and underscores are allowed. "
            f"Skipped."
        )
        return False, REGISTRATION_INVALID_TOOL_ID

    for existing in registry.values():
        if existing.get("tool_id") == tool_id:
            log_debug(f"Tool id already registered: '{tool_id}'")
            return False, REGISTRATION_DUPLICATE_TOOL_ID

    rel_parts = module_name.split(".")
    dir_parts = rel_parts[:-1]
    if dir_parts and dir_parts[0] == "tools":
        group_id = ".".join(dir_parts[1:])
    else:
        group_id = ".".join(dir_parts)

    short = module_name.rsplit(".", 1)[-1]
    min_v = getattr(module, "blender_version_min", None)
    max_v = getattr(module, "blender_version_max", None)
    ok, reason = _check_tool_compatibility(module)

    registry[module_name] = {
        "module_name": module_name,
        "tool_id": tool_id,
        "module": module,
        "group_id": group_id,
        "group_path": "",
        "display_name": getattr(
            module, "tool_name", short.replace("_", " ").title()
        ),
        "enabled_by_default": getattr(module, "tool_default_enabled", True),
        "classes": tuple(getattr(module, "classes", ())),
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
        "version_min": list(min_v[:3]) if min_v else None,
        "version_max": list(max_v[:3]) if max_v else None,
        "compatible": ok,
        "incompatible_reason": reason,
        "loaded": False,
    }

    log_debug(f"Registered tool: {tool_id} from {module_name}")
    return True, REGISTRATION_OK


# ============================================================
# Icon resolution
# ============================================================
def is_image_path(value):
    if not value or not isinstance(value, str):
        return False
    return value.lower().endswith(IMAGE_EXTENSIONS)


def is_builtin_icon(name):
    if not name or not isinstance(name, str):
        return False

    enum_items = None
    try:
        enum_items = (
            bpy.types.UILayout.bl_rna.functions["label"]
            .parameters["icon"].enum_items
        )
    except Exception:
        enum_items = None

    if enum_items is None:
        try:
            enum_items = bpy.types.UILayout.bl_rna.properties["icon"].enum_items
        except Exception:
            enum_items = None

    if enum_items is None:
        return False

    try:
        return name in enum_items
    except Exception:
        return False


def load_group_icon_preview(group_name, group_path, icon_value):
    if not is_image_path(icon_value):
        return None

    image_path = icon_value
    if not os.path.isabs(image_path):
        image_path = os.path.join(group_path, image_path)

    if not os.path.exists(image_path):
        log_debug(f"Group icon image not found for {group_name}: {image_path}")
        return None

    probe = None
    try:
        probe = bpy.data.images.load(image_path, check_existing=False)
        width, height = probe.size
    except Exception as exc:
        log_debug(f"Failed to probe group icon image for {group_name}: {exc}")
        return None
    finally:
        if probe is not None:
            try:
                bpy.data.images.remove(probe)
            except Exception:
                pass

    if width <= 0 or height <= 0:
        log_debug(
            f"Invalid group icon image size for {group_name}: "
            f"{width}x{height}"
        )
        return None

    if width > MAX_ICON_DIMENSION or height > MAX_ICON_DIMENSION:
        log_debug(
            f"Group icon image too large for {group_name}: "
            f"{width}x{height} (max {MAX_ICON_DIMENSION})"
        )
        return None

    previews = _state.get_previews()
    key = f"xneko_group_{group_name}"
    if key in previews:
        return key

    try:
        previews.load(key, image_path, "IMAGE")
    except Exception as exc:
        log_debug(f"Failed to load group icon image for {group_name}: {exc}")
        return None

    return key


def resolve_group_icon(group_name, group_path):
    init_file = os.path.join(group_path, "__init__.py")
    raw_value = None

    if os.path.exists(init_file):
        spec = importlib.util.spec_from_file_location(
            "xneko_group_init", init_file
        )
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                raw_value = getattr(mod, "group_icon", None)
            except Exception as exc:
                log_debug(f"Failed to read group icon from {init_file}: {exc}")

    if not raw_value:
        return {"type": "builtin", "value": _get_group_icon(group_name)}

    preview_key = load_group_icon_preview(group_name, group_path, raw_value)
    if preview_key:
        return {"type": "image", "value": preview_key}

    if is_builtin_icon(raw_value):
        return {"type": "builtin", "value": raw_value}

    return {"type": "text", "value": raw_value}


def build_group_registry(groups, registered_groups):
    for group_name, group_path in groups.items():
        icon_info = resolve_group_icon(group_name, group_path)
        registered_groups[group_name] = {
            "path": group_path,
            "icon": icon_info,
        }
        log_debug(
            f"Group '{group_name}' icon resolved: "
            f"type={icon_info['type']}, value={icon_info['value']}"
        )


# ============================================================
# Initialization / rescan
# ============================================================
def _initialize_tools():
    package_name = __package__
    package_path = sys.modules[package_name].__path__

    _state.reset_registration()
    discover_tools(package_name, package_path)
    issues = collect_registration_issues()

    groups = {}
    for tool in _TOOL_REGISTRY.values():
        gid = tool["group_id"]
        if gid and gid not in groups:
            groups[gid] = tool["group_path"]
    build_group_registry(groups, _state.registered_groups)

    return issues


def rescan_tools():
    _state.reset_previews()
    _initialize_tools()

    # Clear the folder writability cache so permission changes (e.g.
    # the user made the addon folder writable) are picked up without
    # a restart.
    _dir_writable_cache.clear()

    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        prefs.registration_issues = json.dumps(_state.registration_issues)
    except Exception:
        pass


# ============================================================
# Group panels
# ============================================================
def _make_group_panel(group_id, display_name, category):
    safe = group_id.replace(".", "_").replace(" ", "_")
    bl_idname = f"VIEW3D_PT_xneko_grp_{safe}"

    def _poll(cls, context):
        for tool in _TOOL_REGISTRY.values():
            if tool["group_id"] == group_id and tool["loaded"]:
                return True
        return False

    def _draw(self, ctx):
        pass

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
            "draw": _draw,
        },
    )


def register_group_panels(category="XNeko Tools"):
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
    for cls in reversed(_GROUP_PANEL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _GROUP_PANELS.clear()
    _GROUP_PANEL_CLASSES.clear()


def attach_panels_to_groups(tool=None):
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

            existing = set(getattr(cls, "bl_options", set()))
            if 'DEFAULT_CLOSED' not in existing:
                cls.bl_options = existing | {'DEFAULT_CLOSED'}


# ============================================================
# Load / unload
# ============================================================
def load_tool(tool_id):
    tool = _TOOL_REGISTRY.get(tool_id)
    if not tool or tool["loaded"]:
        return

    if not tool.get("compatible", True):
        print(f"[XNeko] refusing to load {tool_id}: "
              f"{tool['incompatible_reason']}")
        return

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

    attach_panels_to_groups(tool)

    for cls in tool["classes"]:
        if isinstance(cls, type) and issubclass(cls, bpy.types.PropertyGroup):
            try:
                bpy.utils.register_class(cls)
            except Exception as e:
                print(f"[XNeko] register PropertyGroup "
                      f"{cls.__name__} failed: {e}")

    for cls in tool["classes"]:
        if isinstance(cls, type) and not issubclass(cls, bpy.types.PropertyGroup):
            try:
                bpy.utils.register_class(cls)
                log_debug(
                    f"Registered class: {cls.__name__} "
                    f"(bl_idname={getattr(cls, 'bl_idname', 'N/A')})"
                )
            except Exception as e:
                print(f"[XNeko] register {cls.__name__} failed: {e}")

    for name, prop in tool["scene_props"].items():
        setattr(bpy.types.Scene, name, prop)

    if callable(tool["on_load"]):
        try:
            tool["on_load"]()
        except Exception as e:
            print(f"[XNeko] on_load for {tool_id} failed: {e}")

    tool["loaded"] = True
    log_debug(
        f"Tool registration complete: {tool_id}, "
        f"classes={len(tool['classes'])}"
    )


def unload_tool(tool_id):
    tool = _TOOL_REGISTRY.get(tool_id)
    if not tool or not tool["loaded"]:
        return

    if callable(tool["on_unload"]):
        try:
            tool["on_unload"]()
        except Exception as e:
            print(f"[XNeko] on_unload for {tool_id} failed: {e}")

    for name in tool["scene_props"]:
        try:
            delattr(bpy.types.Scene, name)
        except Exception:
            pass

    for cls in reversed(tool["classes"]):
        if isinstance(cls, type):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass

    module_name = tool["module_name"]

    tool["module"] = None
    sys.modules.pop(module_name, None)

    tool["classes"] = ()
    tool["scene_props"] = {}
    tool["on_load"] = None
    tool["on_unload"] = None

    gc.collect()

    tool["loaded"] = False


def set_tool_enabled(tool_id, enabled):
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
    for tool_id, tool in _TOOL_REGISTRY.items():
        if tool["enabled_by_default"]:
            set_tool_enabled(tool_id, True)


def unload_all_tools():
    for tool_id in tuple(_TOOL_REGISTRY):
        unload_tool(tool_id)


# ============================================================
# UI helpers
# ============================================================
def draw_registration_issues(self, layout):
    issues = _state.registration_issues
    if not issues and getattr(self, "registration_issues", ""):
        try:
            issues = json.loads(self.registration_issues)
        except Exception:
            issues = []

    if not issues:
        return

    box = layout.box()
    box.alert = True
    box.label(text="Tool registration issues detected:", icon="ERROR")
    box.label(text="Resolve by giving each tool a unique tool_id.")

    for issue in issues:
        issue_type = issue.get("type", "")

        if issue_type == "missing_tool_id":
            box.label(text="Missing required tool_id:")
        elif issue_type == "invalid_tool_id":
            box.label(text=f"Invalid tool_id: {issue['tool_id']}")
        elif issue_type == "import_failed":
            box.label(
                text=f"Import failed: {issue.get('error', 'unknown error')}"
            )
        else:
            box.label(text=f"Tool id collision: {issue['tool_id']}")

        for path in issue["paths"]:
            box.label(text=f"  {path}")


def draw_npanel_registration_warning(layout):
    if not _state.registration_issues:
        return

    box = layout.box()
    box.alert = True
    box.label(
        text=f"{len(_state.registration_issues)} tool registration issue(s).",
        icon="ERROR",
    )
    box.label(text="See add-on preferences for details.")


def draw_group_header(layout, group_name, registered_groups):
    group_data = registered_groups.get(group_name)
    if not group_data or not group_data.get("icon"):
        layout.label(text=group_name, icon="FILE_FOLDER")
        return

    icon_info = group_data["icon"]
    icon_type = icon_info["type"]
    icon_value = icon_info["value"]

    if icon_type == "builtin":
        layout.label(text=group_name, icon=icon_value)

    elif icon_type == "image":
        previews = _state.get_previews()
        preview = previews.get(icon_value)
        if preview is not None:
            layout.label(text=group_name, icon_value=preview.icon_id)
        else:
            layout.label(text=group_name, icon="FILE_FOLDER")

    else:
        layout.label(text=f"{icon_value} {group_name}")