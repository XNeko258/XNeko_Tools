import os
import sys
import json
import hashlib
import importlib
import bpy
from bpy.props import (
    StringProperty, BoolProperty, CollectionProperty, IntProperty,
    EnumProperty, PointerProperty,
)
from bpy_extras.io_utils import ImportHelper

from . import core
from .common import prefs_io, preset_store, session_store
from .common import error_reports as _reports
from .common import icon_store


__xneko_framework__ = True


def _is_property_like(value):
    """Best-effort check that `value` is a bpy.props.* property.

    In Blender 2.8+ bpy.props.XxxProperty() returns a _PropertyDeferred
    instance whose 'function' attribute holds the factory callable
    (e.g. BoolProperty itself), NOT a string. Older builds may return
    a bare RNA property descriptor. Accept either shape.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return False

    # Primary path: _PropertyDeferred exposes the factory as 'function'.
    fn = getattr(value, "function", None)
    if callable(fn):
        return True

    # Fallback: any object already shaped like an RNA property.
    try:
        return isinstance(value, bpy.types.Property)
    except Exception:
        return False


# ---------------- Link configuration ----------------
# Each entry: (label, url, icon, author)
#
# `icon` accepts three forms:
#   - Blender built-in icon name, e.g. "URL", "WORLD", "FILE_IMAGE"
#   - Image path relative to the plugin root, e.g. "icons/patreon.png"
#   - "" or None for no icon
LINKS = (
    # ("Patreon", "https://www.patreon.com/...", "icons/patreon.png", "XNeko"),
    ("Patreon", "https://www.patreon.com/c/XNeko_258",              "icons/Patreon.webp",   "XNeko"),
    ("X",       "https://x.com/XNeko_258",                          "icons/x.webp",         "XNeko"),
    ("Bluesky", "https://bsky.app/profile/xneko258.bsky.social",    "icons/bluesky.webp",   "XNeko"),
    ("Github",  "https://github.com/XNeko258",                      "icons/github.webp",    "XNeko"),

    ("Iwara",   "https://www.iwara.tv/profile/shaoqin",             "icons/iwara.webp",     "Shao qin"),
)


def _build_links_by_author():
    by_author = {}
    for label, url, icon, author in LINKS:
        by_author.setdefault(author, []).append((label, url, icon))
    return by_author


_links_by_author_cache = None


def _get_links_by_author():
    global _links_by_author_cache
    if _links_by_author_cache is None:
        _links_by_author_cache = _build_links_by_author()
    return _links_by_author_cache


# ==================================================
# Preset list cache
# ==================================================
_preset_cache = None


def _get_preset_list():
    global _preset_cache
    if _preset_cache is None:
        try:
            _preset_cache = preset_store.list_presets()
        except Exception as e:
            print(f"[XNeko] list_presets failed: {e}")
            _preset_cache = []
    return _preset_cache


def _invalidate_preset_cache():
    global _preset_cache
    _preset_cache = None


# Cached gid -> [toggle items] map for _draw_preferences. Rebuilt
# only when the toggle collection size changes, so panel redraws in
# a session with 500 tools do not rebuild it every frame.
_groups_cache = None
_groups_cache_key = None


def _get_groups(prefs_obj):
    global _groups_cache, _groups_cache_key
    key = tuple(it.tool_id for it in prefs_obj.tool_toggles)
    if _groups_cache_key == key and _groups_cache is not None:
        return _groups_cache

    groups = {}
    for item in prefs_obj.tool_toggles:
        tool = core._TOOL_REGISTRY.get(item.tool_id)
        gid = tool["group_id"] if tool else ""
        groups.setdefault(gid or "(root)", []).append(item)

    _groups_cache = groups
    _groups_cache_key = key
    return groups


def _invalidate_groups_cache():
    global _groups_cache, _groups_cache_key
    _groups_cache = None
    _groups_cache_key = None
    _invalidate_display_text_cache()


_display_text_cache = {}


def _get_display_text(gid):
    cached = _display_text_cache.get(gid)
    if cached is not None:
        return cached
    text = gid.replace(".", " / ").replace("_", " ").title()
    _display_text_cache[gid] = text
    return text


def _invalidate_display_text_cache():
    _display_text_cache.clear()


# ==================================================
# Module-level state for the Apply Preset dialog
# ==================================================
_ACTIVE_APPLY_OP = None


# ==================================================
# Session persistence
# --------------------------------------------------
# Tool enable flags and per-tool preference values are written to a
# session file whenever they change, and restored on plugin register.
# This makes the state survive Blender restarts without relying on
# the user explicitly saving preferences.
# ==================================================
_suppress_session_write = 0


def _push_suppress_session():
    global _suppress_session_write
    _suppress_session_write += 1


def _pop_suppress_session():
    global _suppress_session_write
    if _suppress_session_write > 0:
        _suppress_session_write -= 1


_session_dirty = False


def _write_session():
    """Mark the session dirty; flush runs via timer."""
    global _session_dirty
    if _suppress_session_write > 0:
        return
    _session_dirty = True
    if bpy.app.timers.is_registered(_flush_session_timer):
        return
    try:
        bpy.app.timers.register(_flush_session_timer, first_interval=0.5)
    except Exception:
        _flush_session_now()


def _flush_session_timer():
    global _session_dirty
    if _session_dirty:
        _session_dirty = False
        _flush_session_now()
    return None


def _flush_session_now():
    """Force an immediate session write."""
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return
    try:
        data = prefs_io.export_prefs(
            prefs.preferences, core, name="__session__",
        )
    except Exception as e:
        print(f"[XNeko] failed to build session data: {e}")
        return
    session_store.save_session(data)


def apply_session_if_any():
    """Restore tool states from the session file, if it exists.

    Called at register time after init_tool_toggles() and
    load_default_tools(), and again on load_post when the loaded
    .blend carries no project preferences.
    """
    data = session_store.load_session()
    if data is None:
        return
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return
    _push_suppress_session()
    try:
        prefs_io.import_prefs(prefs.preferences, core, data)
    except Exception as e:
        print(f"[XNeko] failed to apply session: {e}")
    finally:
        _pop_suppress_session()


# ==================================================
# Helpers
# ==================================================
_pref_prefix_map = {}
_registered_pg_classes = []
_build_generation = 0


def _reset_pref_prefixes():
    _pref_prefix_map.clear()


def _make_pref_attr(full_id):
    """Return a short, unique attribute name for a tool's PG pointer.

    XNekoPreferences holds one PointerProperty per tool. The full
    dotted module path can exceed Blender's 63-char RNA name limit,
    so each tool gets a sequential name like "t1", "t2", ...
    """
    cached = _pref_prefix_map.get(full_id)
    if cached is not None:
        return cached
    name = f"t{len(_pref_prefix_map) + 1}"
    _pref_prefix_map[full_id] = name
    return name


def _build_tool_pg_classes():
    """Create one PropertyGroup class per tool.

    Each class holds only that tool's preference_props, so no single
    RNA type accumulates annotations across tools. Returns a list of
    (pg_cls, attr_name, tool_record) tuples. Class names carry a
    build-generation suffix so successive rebuilds do not clash while
    the previous generation is still registered.
    """
    global _build_generation
    _build_generation += 1
    gen = _build_generation

    _reset_pref_prefixes()
    result = []

    for full_id, tool in core._TOOL_REGISTRY.items():
        actual_tool_id = tool.get("tool_id", full_id)
        props = tool.get("preference_props") or {}

        tool_annotations = {}
        for name, prop in props.items():
            if not _is_property_like(prop):
                core._state.registration_issues.append({
                    "type": "invalid_pref_prop",
                    "tool_id": actual_tool_id,
                    "paths": [f"{full_id}.preference_props['{name}']"],
                    "error": (
                        f"value is {type(prop).__name__}, expected a "
                        f"bpy.props property (e.g. BoolProperty())"
                    ),
                })
                print(
                    f"[XNeko] dropped preference_props['{name}'] of "
                    f"{actual_tool_id}: not a bpy.props property"
                )
                mod = tool.get("module")
                mod_file = getattr(mod, "__file__", None) if mod else None
                _reports.report_tool_error(
                    "invalid preference prop dropped",
                    extra={
                        "tool_id": actual_tool_id,
                        "name": name,
                        "value_type": type(prop).__name__,
                        "file": mod_file,
                        "field": "preference_props",
                        "line": core.find_assignment_line(
                            mod_file, "preference_props"
                        ),
                    },
                )
                continue
            tool_annotations[name] = prop

        if not tool_annotations:
            tool["_pref_pg_cls"] = None
            tool["_pref_pg_attr"] = None
            continue

        attr_name = _make_pref_attr(full_id)
        cls_name = f"XNekoToolPrefs_{attr_name}_g{gen}"
        pg_cls = type(
            cls_name,
            (bpy.types.PropertyGroup,),
            {"__annotations__": tool_annotations},
        )

        tool["_pref_pg_cls"] = pg_cls
        tool["_pref_pg_attr"] = attr_name
        result.append((pg_cls, attr_name, tool))

    return result


def _full_id_map():
    """Return {tool_id: full_id} for every registered tool."""
    return {
        tool["tool_id"]: fid
        for fid, tool in core._TOOL_REGISTRY.items()
    }


def _set_tool_enabled(tool_id, enabled):
    """Route to core.set_tool_enabled, which performs compatibility
    checks and syncs load/unload."""
    return bool(core.set_tool_enabled(tool_id, enabled))


def _redraw_view3d(context=None):
    # bpy.context during addon registration is a _RestrictContext that
    # has no 'screen'. Accessing it raises AttributeError. Since this
    # helper is called from property update callbacks that also fire
    # during init_tool_toggles(), every access must be defensive.
    screen = None
    if context is not None:
        try:
            screen = context.screen
        except Exception:
            screen = None
    if screen is None:
        try:
            screen = bpy.context.screen
        except Exception:
            return
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class _ToolPrefNamespace:
    """Thin wrapper around a tool's preference PropertyGroup."""

    def __init__(self, pg):
        object.__setattr__(self, "_pg", pg)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return getattr(self._pg, name)
        except AttributeError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name == "_pg":
            object.__setattr__(self, name, value)
        else:
            setattr(self._pg, name, value)

    def prop(self, layout, name, **kwargs):
        if not hasattr(self._pg, name):
            print(
                f"[XNeko] pref '{name}' not injected. "
                f"Restart Blender if you just added preference_props."
            )
            return None
        return layout.prop(self._pg, name, **kwargs)

    def __contains__(self, name):
        return hasattr(self._pg, name)

    def keys(self):
        return [
            k for k in self._pg.bl_rna.properties.keys()
            if k not in ("name", "rna_type")
        ]


# ==================================================
# UI scale helpers
# ==================================================
_ui_scale_cache = None


def _get_ui_scale():
    global _ui_scale_cache
    if _ui_scale_cache is not None:
        return _ui_scale_cache
    try:
        _ui_scale_cache = bpy.context.preferences.system.ui_scale
    except Exception:
        _ui_scale_cache = 1.0
    return _ui_scale_cache


def _get_usable_width(context):
    width = None
    try:
        screen = context.screen
        if screen is not None:
            for area in screen.areas:
                if area.type == 'PREFERENCES':
                    width = area.width
                    break
            if width is None and screen.areas:
                width = screen.areas[0].width
    except Exception:
        pass

    if not width:
        try:
            width = context.window.width
        except Exception:
            width = 900

    return max(150, width - 130)


def _estimate_tab_px(display_text):
    scale = _get_ui_scale()
    return int((len(display_text) * 8 + 38) * scale)


# ==================================================
# Base operators
# ==================================================
class XNEKO_OT_set_active_category(bpy.types.Operator):
    bl_idname = "xneko.set_active_category"
    bl_label = "Set Active Category"
    bl_options = {'INTERNAL'}

    category: StringProperty()

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if not prefs:
            return {'CANCELLED'}
        prefs.preferences.active_category = self.category
        return {'FINISHED'}


class XNEKO_OT_shift_tab_page(bpy.types.Operator):
    bl_idname = "xneko.shift_tab_page"
    bl_label = "Shift Tab Page"
    bl_options = {'INTERNAL'}

    delta: IntProperty()

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if not prefs:
            return {'CANCELLED'}
        p = prefs.preferences
        new_page = p.tab_page + self.delta
        if new_page < 0:
            new_page = 0
        p.tab_page = new_page
        return {'FINISHED'}


# ==================================================
# Per-tool toggle
# ==================================================
class XNekoToolToggle(bpy.types.PropertyGroup):
    tool_id: StringProperty()
    display_name: StringProperty()
    enabled: BoolProperty(
        default=True,
        update=lambda self, ctx: _on_toggle(self, ctx),
    )
    expanded: BoolProperty(default=False)


# ==================================================
# One row in the Apply Preset dialog
# ==================================================
class XNEKO_ApplyPresetEntry(bpy.types.PropertyGroup):
    tool_id: StringProperty()
    short_id: StringProperty()
    display_name: StringProperty()
    detail: StringProperty()
    selected: BoolProperty(default=True)
    compatible: BoolProperty(default=True)
    currently_enabled: BoolProperty(default=False)
    target_enabled: BoolProperty(default=True)


# ==================================================
# Preset enumerator
# ==================================================
# Sentinel identifier for "no preset selected". Always present in
# _preset_items so EnumProperty never fails to resolve its current
# value. sanitize_name rejects any name starting with "__", so a
# user-supplied preset can never collide with this sentinel.
NONE_PRESET_ID = "__none__"


def _preset_items(self, context):
    items = [(NONE_PRESET_ID, "(No preset)", "No preset selected")]
    items += [(n, n, f"Preset: {n}") for n in _get_preset_list()]
    return items


# ==================================================
# Preference IO operators
# ==================================================
class XNEKO_OT_export_prefs(bpy.types.Operator):
    bl_idname = "xneko.export_prefs"
    bl_label = "Export Preferences"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(
        name="Preset Name",
        description="Name to save this preset under",
        default="",
    )
    overwrite: BoolProperty(name="Overwrite", default=False)

    def invoke(self, context, event):
        if not self.preset_name:
            existing = set(_get_preset_list())
            name = "Preset"
            if name in existing:
                n = 2
                while f"Preset_{n}" in existing:
                    n += 1
                name = f"Preset_{n}"
            self.preset_name = name
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "preset_name")
        name = preset_store.sanitize_name(self.preset_name)
        if name and preset_store.preset_exists(name):
            box = layout.box()
            box.alert = True
            box.label(text=f"'{name}' already exists", icon='ERROR')
            box.prop(self, "overwrite")

    def execute(self, context):
        name = preset_store.sanitize_name(self.preset_name)
        if not name:
            self.report({'ERROR'}, "Name cannot be empty")
            return {'CANCELLED'}
        if preset_store.preset_exists(name) and not self.overwrite:
            self.report({'ERROR'}, "Preset exists; enable Overwrite")
            return {'CANCELLED'}
        prefs_obj = context.preferences.addons[__package__].preferences
        data = prefs_io.export_prefs(prefs_obj, core, name=name)
        preset_store.save_preset(name, data)
        _invalidate_preset_cache()
        self.report({'INFO'}, f"Saved preset '{name}'")
        return {'FINISHED'}


class XNEKO_OT_import_prefs(bpy.types.Operator, ImportHelper):
    bl_idname = "xneko.import_prefs"
    bl_label = "Import Preferences"
    bl_options = {'INTERNAL'}

    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    filename_ext = ".json"

    def execute(self, context):
        try:
            data = prefs_io.load_from_file(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        if data.get("format") != prefs_io.FORMAT_TAG:
            self.report({'ERROR'}, "Not an XNeko preferences file")
            return {'CANCELLED'}

        base = os.path.basename(self.filepath)
        target = base[:-5] if base.endswith(".json") else base
        target = preset_store.sanitize_name(target) or "Imported"

        if preset_store.preset_exists(target):
            wm = context.window_manager
            wm["xneko_pending_import_data"] = json.dumps(
                data, ensure_ascii=False
            )
            wm["xneko_pending_import_name"] = target
            bpy.ops.xneko.confirm_overwrite('INVOKE_DEFAULT')
            return {'FINISHED'}

        preset_store.save_preset(target, data)
        _invalidate_preset_cache()
        self.report({'INFO'}, f"Imported as '{target}'")
        return {'FINISHED'}


class XNEKO_OT_confirm_overwrite(bpy.types.Operator):
    bl_idname = "xneko.confirm_overwrite"
    bl_label = "Preset Already Exists"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        name = context.window_manager.get("xneko_pending_import_name", "")
        box = self.layout.box()
        box.alert = True
        box.label(text=f"'{name}' already exists", icon='ERROR')
        self.layout.label(text="Overwrite it?")

    def execute(self, context):
        wm = context.window_manager
        name = wm.get("xneko_pending_import_name", "")
        raw = wm.get("xneko_pending_import_data", "")
        if not name or not raw:
            return {'CANCELLED'}
        try:
            data = json.loads(raw)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        preset_store.save_preset(name, data)
        _invalidate_preset_cache()
        wm["xneko_pending_import_name"] = ""
        wm["xneko_pending_import_data"] = ""
        self.report({'INFO'}, f"Overwritten '{name}'")
        return {'FINISHED'}

    def cancel(self, context):
        wm = context.window_manager
        wm["xneko_pending_import_name"] = ""
        wm["xneko_pending_import_data"] = ""


class XNEKO_OT_apply_preset(bpy.types.Operator):
    bl_idname = "xneko.apply_preset"
    bl_label = "Apply Preset"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty()

    entries: CollectionProperty(type=XNEKO_ApplyPresetEntry)

    _preview_data = None

    def invoke(self, context, event):
        global _ACTIVE_APPLY_OP
        if not self.preset_name:
            self.report({'ERROR'}, "No preset selected")
            return {'CANCELLED'}
        try:
            data = preset_store.load_preset(self.preset_name)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        if data.get("format") != prefs_io.FORMAT_TAG:
            self.report({'ERROR'}, "Not an XNeko preferences file")
            return {'CANCELLED'}

        self._preview_data = data
        self._build_entries(context, data)
        _ACTIVE_APPLY_OP = self
        return context.window_manager.invoke_props_dialog(self, width=520)

    def _build_entries(self, context, data):
        self.entries.clear()

        prefs_obj = context.preferences.addons[__package__].preferences
        current = {it.tool_id: it.enabled for it in prefs_obj.tool_toggles}
        short_to_full = _full_id_map()

        for short_id, saved in (data.get("tools") or {}).items():
            row = self.entries.add()
            row.short_id = short_id
            row.target_enabled = bool(saved.get("__enabled__", True))

            full_id = short_to_full.get(short_id)
            tool = core._TOOL_REGISTRY.get(full_id) if full_id else None

            if tool is None:
                row.tool_id = short_id
                row.display_name = short_id
                row.detail = "Not installed"
                row.compatible = False
                row.selected = False
                continue

            row.tool_id = full_id
            row.display_name = tool["display_name"]
            row.currently_enabled = bool(current.get(full_id, False))

            if not tool.get("compatible", True):
                row.detail = tool.get("incompatible_reason", "Incompatible")
                row.compatible = False
                row.selected = False
            else:
                row.compatible = True
                row.selected = True

    def draw(self, context):
        layout = self.layout
        data = self._preview_data
        if data is None:
            layout.label(text="No data", icon='ERROR')
            return

        meta = layout.box()
        meta.label(text=f"Preset: {data.get('name', '?')}", icon='PRESET')
        row = meta.row()
        row.label(text=f"Plugin: {data.get('plugin_version', '?')}")
        row.label(text=f"Blender: {data.get('blender_version', '?')}")

        layout.separator()

        header = layout.row(align=True)
        header.label(text="Select modules to apply:")
        header.operator(
            "xneko.apply_preset_select_all", text="All",
        ).state = True
        header.operator(
            "xneko.apply_preset_select_all", text="None",
        ).state = False

        box = layout.box()
        for row in self.entries:
            if not row.compatible:
                r = box.row()
                r.enabled = False
                r.label(
                    text=f"{row.display_name}  ({row.detail})",
                    icon='ERROR',
                )
                continue

            r = box.row(align=True)
            r.prop(row, "selected", text="")

            if row.currently_enabled == row.target_enabled:
                tag = "(no change)"
            elif row.target_enabled:
                tag = "\u2192 enable"
            else:
                tag = "\u2192 disable"
            r.label(text=f"{row.display_name}   {tag}")

    def execute(self, context):
        global _ACTIVE_APPLY_OP
        data = self._preview_data
        self._preview_data = None
        _ACTIVE_APPLY_OP = None

        if data is None:
            return {'CANCELLED'}

        prefs_obj = context.preferences.addons[__package__].preferences
        toggles = {it.tool_id: it for it in prefs_obj.tool_toggles}

        applied = 0
        skipped = 0
        for row in self.entries:
            if not row.compatible or not row.selected:
                skipped += 1
                continue

            item = toggles.get(row.tool_id)
            if item is not None and item.enabled != row.target_enabled:
                item.enabled = row.target_enabled
            else:
                _set_tool_enabled(row.tool_id, row.target_enabled)
            applied += 1

        _redraw_view3d(context)
        _write_session()
        self.report(
            {'INFO'},
            f"Applied {applied}, skipped {skipped}",
        )
        return {'FINISHED'}

    def cancel(self, context):
        global _ACTIVE_APPLY_OP
        _ACTIVE_APPLY_OP = None
        self._preview_data = None


class XNEKO_OT_apply_preset_select_all(bpy.types.Operator):
    bl_idname = "xneko.apply_preset_select_all"
    bl_label = "Select All / None"
    bl_options = {'INTERNAL'}

    state: BoolProperty()

    def execute(self, context):
        op = _ACTIVE_APPLY_OP
        if op is None or not hasattr(op, "entries"):
            return {'CANCELLED'}
        for row in op.entries:
            if row.compatible:
                row.selected = self.state
        return {'FINISHED'}


class XNEKO_OT_delete_preset(bpy.types.Operator):
    bl_idname = "xneko.delete_preset"
    bl_label = "Delete Preset"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty()

    def invoke(self, context, event):
        if not self.preset_name:
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not self.preset_name:
            return {'CANCELLED'}
        preset_store.delete_preset(self.preset_name)
        _invalidate_preset_cache()
        self.report({'INFO'}, f"Deleted '{self.preset_name}'")
        return {'FINISHED'}


class XNEKO_OT_refresh_presets(bpy.types.Operator):
    bl_idname = "xneko.refresh_presets"
    bl_label = "Refresh Presets"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _invalidate_preset_cache()
        return {'FINISHED'}


class XNEKO_OT_apply_project_prefs(bpy.types.Operator):
    bl_idname = "xneko.apply_project_prefs"
    bl_label = "Apply Project Preferences"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        prefs_obj = context.preferences.addons[__package__].preferences
        data, present = prefs_io.get_project_data()
        if not present:
            self.report({'WARNING'}, "Project has no saved preferences")
            return {'CANCELLED'}
        applied, skipped = prefs_io.import_prefs(prefs_obj, core, data)
        _redraw_view3d(context)
        _write_session()
        self.report(
            {'INFO'},
            f"Project prefs: applied {len(applied)}, skipped {len(skipped)}",
        )
        return {'FINISHED'}


class XNEKO_OT_clear_project_prefs(bpy.types.Operator):
    bl_idname = "xneko.clear_project_prefs"
    bl_label = "Clear Project Preferences"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        prefs_io.clear_project_data()
        self.report({'INFO'}, "Project preferences cleared")
        return {'FINISHED'}


class XNEKO_OT_rescan_tools(bpy.types.Operator):
    bl_idname = "xneko.rescan_tools"
    bl_label = "Hot Reload Tools"
    bl_description = (
        "Unload every tool, re-read the tools/ folder from disk, "
        "and rebuild the preferences class. Use this after editing "
        "a tool's .py file instead of restarting Blender"
    )
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ok, msg = hot_reload_tools()
        if ok:
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        self.report({'ERROR'}, msg)
        return {'CANCELLED'}


class XNEKO_OT_open_user_reports_folder(bpy.types.Operator):
    bl_idname = "xneko.open_user_reports_folder"
    bl_label = "Open Tool Reports"
    bl_description = "Open the folder holding tool-module error reports"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        path = _reports.user_reports_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            self.report({'ERROR'}, f"Cannot create folder: {e}")
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


class XNEKO_OT_open_critical_reports_folder(bpy.types.Operator):
    bl_idname = "xneko.open_critical_reports_folder"
    bl_label = "Open Critical Reports"
    bl_description = "Open the folder holding critical error reports"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        path = _reports.critical_reports_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            self.report({'ERROR'}, f"Cannot create folder: {e}")
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


class XNEKO_OT_clear_user_reports(bpy.types.Operator):
    bl_idname = "xneko.clear_user_reports"
    bl_label = "Clear Tool Reports"
    bl_description = "Delete all tool-module error reports"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        removed = _reports.clear_user_reports()
        self.report({'INFO'}, f"Removed {removed} report(s)")
        return {'FINISHED'}


class XNEKO_OT_clear_critical_reports(bpy.types.Operator):
    bl_idname = "xneko.clear_critical_reports"
    bl_label = "Clear Critical Reports"
    bl_description = "Delete all critical error reports"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        removed = _reports.clear_critical_reports()
        self.report({'INFO'}, f"Removed {removed} critical report(s)")
        return {'FINISHED'}


# ==================================================
# Toggle / handler callbacks
# ==================================================
def _on_use_project_prefs_toggle(self, context):
    """Apply the loaded .blend's stored prefs when the user opts in.

    Note: unchecking 'Use Project Preferences' does NOT roll back the
    current state. It only means the next .blend load will skip the
    project-prefs branch and fall back to the session state.
    """
    if not self.use_project_prefs:
        return
    data, present = prefs_io.get_project_data()
    if not present:
        return
    prefs_io.import_prefs(self, core, data)
    _redraw_view3d(context)
    _write_session()


@bpy.app.handlers.persistent
def _on_load_post(dummy):
    """Restore preferences when a .blend is loaded.

    Order of precedence:
      1. If Use Project Preferences is enabled AND the loaded file
         carries project prefs, apply those.
      2. Otherwise fall back to the last session state (the state at
         the time Blender was last closed).

    The session fallback is important: without it, loading a .blend
    that carries no prefs would leave the tool states exactly as the
    previously loaded file left them, rather than as the user last
    configured them.
    """
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        if not addon:
            return
        p = addon.preferences

        if p.use_project_prefs:
            data, present = prefs_io.get_project_data()
            if present:
                applied, skipped = prefs_io.import_prefs(p, core, data)
                print(f"[XNeko] Loaded project prefs: applied "
                      f"{len(applied)}, skipped {len(skipped)}")
                for short, reason in skipped:
                    print(f"[XNeko]   skipped {short}: {reason}")
                _redraw_view3d()
                return

        # No project prefs (or the option is off): restore session.
        apply_session_if_any()
        _redraw_view3d()
    except Exception as exc:
        print(f"[XNeko] load_post handler failed: {exc}")


@bpy.app.handlers.persistent
def _on_save_pre(dummy):
    """Persist preferences when a .blend is saved.

    Always refreshes the session file (so the state is retained even
    if the user never saves preferences explicitly). Additionally,
    writes the prefs into the .blend when Save Preferences to .blend
    is enabled.
    """
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        if not addon:
            return
        p = addon.preferences

        _flush_session_now()

        if p.save_to_project:
            project_data = prefs_io.export_prefs(p, core, name="__project__")
            prefs_io.set_project_data(project_data)
    except Exception as exc:
        print(f"[XNeko] save_pre handler failed: {exc}")


# ==================================================
# Addon preferences draw function
# ==================================================
def _draw_preferences(self, context):
    layout = self.layout

    core.draw_registration_issues(self, layout)

    layout.prop(self, "panel_category")

    row = layout.row(align=True)
    row.operator("xneko.rescan_tools", icon='FILE_REFRESH')

    # ---------- Project File (collapsible) ----------
    layout.separator()

    _data, present = prefs_io.get_project_data()

    header = layout.row(align=True)
    arrow = 'TRIA_DOWN' if self.project_section_expanded else 'TRIA_RIGHT'
    header.prop(self, "project_section_expanded",
                text="", icon=arrow, emboss=False)
    header.label(text="Project File:", icon='FILE_BLEND')

    spacer = header.row(align=True)
    spacer.alignment = 'RIGHT'
    clear_row = spacer.row(align=True)
    clear_row.enabled = present
    clear_row.operator("xneko.clear_project_prefs", text="", icon='TRASH')

    if self.project_section_expanded:
        box = layout.box()
        col = box.column(align=True)
        col.prop(self, "save_to_project")
        col.prop(self, "use_project_prefs")

        info_row = box.row()
        info_row.enabled = False
        if present:
            info_row.label(text="This project carries preferences",
                           icon='CHECKMARK')
        else:
            info_row.label(text="No preferences in this project", icon='INFO')

    # ---------- Presets (collapsible) ----------
    layout.separator()

    header = layout.row(align=True)
    arrow = (
        'TRIA_DOWN' if self.presets_section_expanded
        else 'TRIA_RIGHT'
    )
    header.prop(
        self, "presets_section_expanded",
        text="", icon=arrow, emboss=False,
    )
    header.label(text="Presets:", icon='PRESET')

    if self.presets_section_expanded:
        # If the stored preset vanished (deleted from disk, or a preset
        # from an older install), fall back to the sentinel instead of
        # writing "" which EnumProperty cannot resolve.
        if (self.selected_preset
                and self.selected_preset != NONE_PRESET_ID
                and self.selected_preset not in _get_preset_list()):
            self.selected_preset = NONE_PRESET_ID

        row = layout.row(align=True)
        row.prop(self, "selected_preset", text="")

        has_preset = bool(
            self.selected_preset
            and self.selected_preset != NONE_PRESET_ID
        )

        sub = row.row(align=True)
        sub.scale_x = 0.45
        sub.enabled = has_preset
        sub.operator(
            "xneko.apply_preset", text="Apply", icon='CHECKMARK',
        ).preset_name = self.selected_preset
        sub.operator(
            "xneko.delete_preset", text="Delete", icon='TRASH',
        ).preset_name = self.selected_preset

        row = layout.row(align=True)
        row.operator("xneko.export_prefs", text="Export", icon='EXPORT')
        row.operator("xneko.import_prefs", text="Import", icon='IMPORT')
        row.operator("xneko.refresh_presets", text="", icon='FILE_REFRESH')

    # ---------- Tools (collapsible) ----------
    layout.separator()

    header = layout.row(align=True)
    arrow = 'TRIA_DOWN' if self.tools_section_expanded else 'TRIA_RIGHT'
    header.prop(
        self, "tools_section_expanded",
        text="", icon=arrow, emboss=False,
    )
    header.label(text="Tools:")

    if self.tools_section_expanded:
        groups = _get_groups(self)

        if not groups:
            layout.label(text="No tools found", icon='INFO')
        else:
            if self.active_category not in groups:
                self.active_category = list(groups.keys())[0]

            all_gids = list(groups.keys())
            total = len(all_gids)

            usable_px = _get_usable_width(context)

            widest_tab_px = 1
            for gid in all_gids:
                w = _estimate_tab_px(_get_display_text(gid))
                if w > widest_tab_px:
                    widest_tab_px = w

            TABS_PER_PAGE = max(1, usable_px // widest_tab_px)
            if TABS_PER_PAGE > total:
                TABS_PER_PAGE = total

            page_count = max(1, (total + TABS_PER_PAGE - 1) // TABS_PER_PAGE)
            if self.tab_page >= page_count:
                self.tab_page = page_count - 1
            if self.tab_page < 0:
                self.tab_page = 0

            start = self.tab_page * TABS_PER_PAGE
            end = min(start + TABS_PER_PAGE, total)
            visible_gids = all_gids[start:end]

            tab_row = layout.row(align=True)

            left = tab_row.row(align=True)
            left.enabled = self.tab_page > 0
            left.operator(
                "xneko.shift_tab_page", text="", icon='TRIA_LEFT',
            ).delta = -1

            for gid in visible_gids:
                display = _get_display_text(gid)
                is_active = (self.active_category == gid)

                group_data = core._state.registered_groups.get(gid)
                icon_info = group_data["icon"] if group_data else None

                prefix = ""
                if icon_info is None:
                    icon_name = core._get_group_icon(gid)
                elif icon_info["type"] == "builtin":
                    icon_name = icon_info["value"]
                elif icon_info["type"] == "text":
                    icon_name = "FILE_FOLDER"
                    prefix = f"{icon_info['value']} "
                else:
                    icon_name = "FILE_FOLDER"

                tab_row.operator(
                    "xneko.set_active_category",
                    text=f"{prefix}{display}",
                    icon=icon_name,
                    depress=is_active,
                ).category = gid

            right = tab_row.row(align=True)
            right.enabled = self.tab_page < page_count - 1
            right.operator(
                "xneko.shift_tab_page", text="", icon='TRIA_RIGHT',
            ).delta = 1

            main_box = layout.box()
            for item in groups[self.active_category]:
                tool = core._TOOL_REGISTRY.get(item.tool_id)

                if tool and not tool.get("compatible", True):
                    row = main_box.row(align=True)
                    row.enabled = False
                    row.label(text="", icon='BLANK1')
                    row.prop(item, "enabled", text=item.display_name)
                    warn = main_box.row()
                    warn.alert = True
                    warn.label(text=tool["incompatible_reason"], icon='ERROR')
                    continue

                has_props = bool(tool.get("preference_props")) if tool else False
                has_draw = callable(tool.get("draw_preferences")) if tool else False
                can_expand = (
                    tool is not None
                    and item.enabled
                    and tool.get("preferences_in_addon") is not False
                    and (has_props or has_draw)
                )

                row = main_box.row(align=True)
                if can_expand:
                    arrow = 'TRIA_DOWN' if item.expanded else 'TRIA_RIGHT'
                    row.prop(item, "expanded", text="", icon=arrow, emboss=False)
                else:
                    row.label(text="", icon='BLANK1')
                row.prop(item, "enabled", text=item.display_name)

                if not can_expand or not item.expanded:
                    continue

                ns = _make_tool_namespace(tool)
                if ns is None:
                    continue

                sub_box = main_box.box()
                if has_draw:
                    try:
                        tool["draw_preferences"](sub_box, context, ns)
                    except Exception as e:
                        sub_box.label(text=f"Prefs error: {e}", icon='ERROR')
                else:
                    for name in tool["preference_props"]:
                        ns.prop(sub_box, name)

    # ---------- Diagnostics (collapsible) ----------
    layout.separator()

    header = layout.row(align=True)
    arrow = (
        'TRIA_DOWN' if self.diagnostics_section_expanded
        else 'TRIA_RIGHT'
    )
    header.prop(
        self, "diagnostics_section_expanded",
        text="", icon=arrow, emboss=False,
    )
    header.label(text="Diagnostics:", icon='TEXT')

    if self.diagnostics_section_expanded:
        box = layout.box()

        # ---- Optional: tool-module reports ----
        box.prop(self, "enable_error_report")

        user_row = box.row(align=True)
        user_row.operator(
            "xneko.open_user_reports_folder",
            text="Open Tool Reports", icon='FILE_FOLDER',
        )
        user_row.operator(
            "xneko.clear_user_reports", text="Clear", icon='TRASH',
        )

        # ---- Forced: critical reports ----
        box.separator()

        crit_note = box.row()
        crit_note.enabled = False
        crit_note.label(
            text="Critical errors are always logged.",
            icon='ERROR',
        )

        crit_row = box.row(align=True)
        crit_row.operator(
            "xneko.open_critical_reports_folder",
            text="Open Critical Reports", icon='FILE_FOLDER',
        )
        crit_row.operator(
            "xneko.clear_critical_reports", text="Clear", icon='TRASH',
        )

    # ---------- Links (collapsible) ----------
    layout.separator()

    header = layout.row(align=True)
    arrow = 'TRIA_DOWN' if self.links_section_expanded else 'TRIA_RIGHT'
    header.prop(
        self, "links_section_expanded",
        text="", icon=arrow, emboss=False,
    )
    header.label(text="Links:", icon='BOOKMARKS')

    if self.links_section_expanded:
        for author, items in _get_links_by_author().items():
            box = layout.box()
            box.label(text=author, icon='USER')
            grid = box.grid_flow(row_major=True, columns=2, even_columns=True)
            for label, url, icon in items:
                # Image path -> icon_value (preview icon_id)
                if icon_store.is_image_path(icon):
                    icon_id = icon_store.get_icon_id(icon)
                    if icon_id:
                        grid.operator(
                            "wm.url_open", text=label, icon_value=icon_id,
                        ).url = url
                    else:
                        # Image failed to load; fall back to no icon.
                        grid.operator(
                            "wm.url_open", text=label,
                        ).url = url
                # Built-in icon name
                elif icon:
                    grid.operator(
                        "wm.url_open", text=label, icon=icon,
                    ).url = url
                # No icon
                else:
                    grid.operator(
                        "wm.url_open", text=label,
                    ).url = url


# ==================================================
# Dynamic preferences class builder
# ==================================================
XNekoPreferences = None


def build_preferences_class(include_tool_props=True):
    """Build the dynamic AddonPreferences class.

    Returns (prefs_cls, pg_classes). The caller is responsible for
    registering pg_classes before prefs_cls. When include_tool_props
    is False, per-tool PG classes are skipped entirely and every
    tool's _pref_pg_cls is reset to None.
    """
    annotations = {
        "panel_category": StringProperty(
            name="N Panel Category",
            description=(
                "Category name shown in the N panel sidebar. "
                "Use the same name as another add-on to merge them."
            ),
            default="XNeko Tools",
        ),
        "active_category": StringProperty(default=""),
        "tab_page": IntProperty(default=0),
        "tool_toggles": CollectionProperty(type=XNekoToolToggle),

        "project_section_expanded": BoolProperty(default=False),
        "presets_section_expanded": BoolProperty(default=False),
        "tools_section_expanded": BoolProperty(default=False),
        "links_section_expanded": BoolProperty(default=False),

        "save_to_project": BoolProperty(
            name="Save Preferences to .blend",
            description=(
                "When saving the .blend, also store the current "
                "preferences inside the project file"
            ),
            default=False,
        ),
        "use_project_prefs": BoolProperty(
            name="Use Project Preferences",
            description=(
                "When loading a .blend that stores preferences, "
                "apply them instead of using the current session state"
            ),
            default=False,
            update=lambda self, ctx: _on_use_project_prefs_toggle(self, ctx),
        ),

        "selected_preset": EnumProperty(
            name="Preset",
            items=_preset_items,
            description="Preset to apply",
            default=0,
        ),

        "diagnostics_section_expanded": BoolProperty(default=False),

        "enable_error_report": BoolProperty(
            name="Enable Error Reporting",
            description=(
                "When enabled, tool-module errors (import failures, "
                "invalid declarations, dropped preference props, "
                "panel attach failures) are written to "
                "logs/reports/. Disabled by default. Errors inside "
                "the addon itself always write to logs/critical/ "
                "regardless of this setting."
            ),
            default=False,
        ),
        "registration_issues": StringProperty(
            name="Registration Issues",
            default="",
            options={'HIDDEN'},
        ),
        "plugin_version": StringProperty(
            name="Plugin Version",
            default="",
        ),
    }

    pg_classes = []

    if include_tool_props:
        pg_entries = _build_tool_pg_classes()
        for pg_cls, attr_name, _tool in pg_entries:
            annotations[attr_name] = PointerProperty(type=pg_cls)
            pg_classes.append(pg_cls)
    else:
        for _tool in core._TOOL_REGISTRY.values():
            _tool["_pref_pg_cls"] = None
            _tool["_pref_pg_attr"] = None

    prefs_cls = type(
        "XNekoPreferences",
        (bpy.types.AddonPreferences,),
        {
            "bl_idname": __package__,
            "__annotations__": annotations,
            "draw": _draw_preferences,
        },
    )

    return prefs_cls, pg_classes


def install_preferences():
    """Build and register XNekoPreferences plus every tool PG class.

    Returns the registered prefs class, or None when no usable class
    could be registered.
    """
    global XNekoPreferences, _registered_pg_classes

    uninstall_preferences()
    _invalidate_prefs_cache()

    prefs_cls, pg_classes = build_preferences_class()

    registered_pg = []
    for pg_cls in pg_classes:
        try:
            bpy.utils.register_class(pg_cls)
            registered_pg.append(pg_cls)
        except Exception as e:
            print(f"[XNeko] PG class {pg_cls.__name__} failed: {e}")

    _registered_pg_classes = registered_pg

    try:
        bpy.utils.register_class(prefs_cls)
    except Exception as e:
        print(f"[XNeko] XNekoPreferences registration failed: {e}")
        print("[XNeko] retrying without per-tool preference props")
        _reports.report_critical_error(
            "XNekoPreferences registration failed",
            exc=e,
            extra={"fallback": "include_tool_props=False"},
        )
        for pg_cls in reversed(registered_pg):
            try:
                bpy.utils.unregister_class(pg_cls)
            except Exception:
                pass
        _registered_pg_classes = []
        _invalidate_prefs_cache()

        prefs_cls2, _ = build_preferences_class(include_tool_props=False)
        try:
            bpy.utils.register_class(prefs_cls2)
            XNekoPreferences = prefs_cls2
            return prefs_cls2
        except Exception as e2:
            print(f"[XNeko] fallback registration also failed: {e2}")
            XNekoPreferences = None
            return None

    XNekoPreferences = prefs_cls
    return prefs_cls


def uninstall_preferences():
    """Unregister XNekoPreferences and every tool PG class."""
    global XNekoPreferences, _registered_pg_classes

    if XNekoPreferences is not None:
        try:
            bpy.utils.unregister_class(XNekoPreferences)
        except Exception:
            pass
        XNekoPreferences = None

    for pg_cls in reversed(_registered_pg_classes):
        try:
            bpy.utils.unregister_class(pg_cls)
        except Exception:
            pass
    _registered_pg_classes = []
    _invalidate_prefs_cache()


_cached_prefs_obj = None


def _get_prefs_obj():
    global _cached_prefs_obj
    if _cached_prefs_obj is not None:
        return _cached_prefs_obj
    addon = bpy.context.preferences.addons.get(__package__)
    if not addon:
        return None
    _cached_prefs_obj = addon.preferences
    return _cached_prefs_obj


def _invalidate_prefs_cache():
    global _cached_prefs_obj
    _cached_prefs_obj = None


def _make_tool_namespace(tool):
    prefs_obj = _get_prefs_obj()
    if prefs_obj is None:
        return None
    attr = tool.get("_pref_pg_attr")
    if not attr:
        return None
    pg = getattr(prefs_obj, attr, None)
    if pg is None:
        return None
    return _ToolPrefNamespace(pg)


def get_tool_prefs(tool_id):
    """Public accessor for tools to read/write their own prefs."""
    for tool in core._TOOL_REGISTRY.values():
        if tool.get("tool_id") == tool_id:
            return _make_tool_namespace(tool)
    return None


# ==================================================
# Callbacks
# ==================================================
_toggle_in_progress = False


def _on_toggle(item, context=None):
    global _toggle_in_progress
    if _toggle_in_progress:
        return
    if core.is_toggle_suppressed():
        # Fired during init_tool_toggles() or a batch import, which
        # only reset toggle values. Actual load/unload is driven
        # separately by load_enabled_tools() / import_prefs().
        return
    _toggle_in_progress = True
    try:
        tool = core._TOOL_REGISTRY.get(item.tool_id)
        if tool is None:
            return
        if item.enabled and not tool.get("compatible", True):
            item.enabled = False
            print(f"[XNeko] {item.tool_id} cannot be enabled: "
                  f"{tool['incompatible_reason']}")
            # The re-entrant call triggered by the line above was
            # suppressed by the guard, so persist the rejection here.
            _write_session()
            return
        ok = _set_tool_enabled(item.tool_id, item.enabled)
        if not ok and item.enabled:
            # Load failed: flip the checkbox back so the UI never
            # shows "enabled" for a tool that is not running.
            item.enabled = False
            print(f"[XNeko] {item.tool_id} failed to load; "
                  f"toggle reverted")
        _redraw_view3d(context)
        _write_session()
    finally:
        _toggle_in_progress = False


def _drop_tool_submodules():
    """Evict every non-framework module under the addon package."""
    prefix = __package__ + "."
    dropped = 0
    for name in list(sys.modules.keys()):
        if not name.startswith(prefix):
            continue
        mod = sys.modules.get(name)
        if mod is None:
            continue
        if getattr(mod, "__xneko_framework__", False):
            continue
        sys.modules.pop(name, None)
        dropped += 1
    return dropped


def register_tool_preference_classes():
    """Register every tool's preference_classes.

    Single source of truth: called from __init__ at addon register
    and from hot_reload_tools after a re-discovery. Keeping this in
    one place means the register/unregister logic can no longer
    drift between callers.
    """
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


def unregister_tool_preference_classes():
    """Reverse of register_tool_preference_classes."""
    for tool in reversed(list(core._TOOL_REGISTRY.values())):
        for cls in reversed(tool.get("preference_classes", ())):
            if not isinstance(cls, type):
                continue
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass


def hot_reload_tools():
    """Hot-reload every tool module and rebuild the dynamic
    XNekoPreferences class.

    This is the heavy version of core.rescan_tools: it drops the
    Python module cache for the tools/ subtree, unloads every loaded
    tool, rebuilds the dynamic XNekoPreferences class (so newly added
    or removed preference_props take effect), and re-applies the
    previous state.

    Returns (success: bool, message: str).
    """

    addon = bpy.context.preferences.addons.get(__package__)
    if addon is None:
        return False, "Add-on is not loaded"

    old_prefs = addon.preferences
    if old_prefs is None:
        return False, "Add-on preferences are not available"

    # 1. Snapshot tool state (enabled flags + per-tool props).
    try:
        tool_snapshot = prefs_io.export_prefs(
            old_prefs, core, name="__hot_reload__",
        )
    except Exception as e:
        print(f"[XNeko] hot reload: tool snapshot failed: {e}")
        _reports.report_critical_error(
            "hot reload: tool snapshot failed",
            exc=e,
            extra={"effect": "tool states reset to defaults after reload"},
        )
        tool_snapshot = None

    # UI state is not covered by prefs_io.export_prefs, so collect
    # every scalar property on the preferences instance. Excluding
    # collection and metadata fields is enough.
    ui_snapshot = {}
    _SKIP = {
        "name", "rna_type",
        "tool_toggles", "registration_issues", "plugin_version",
    }
    try:
        for prop in old_prefs.bl_rna.properties:
            ident = prop.identifier
            if ident.startswith("rna_") or ident in _SKIP:
                continue
            if prop.type not in {'BOOLEAN', 'INT', 'FLOAT',
                                 'STRING', 'ENUM'}:
                continue
            try:
                ui_snapshot[ident] = getattr(old_prefs, ident)
            except Exception:
                pass
    except Exception as e:
        print(f"[XNeko] hot reload: ui snapshot failed: {e}")

    expanded_snapshot = {}
    try:
        for it in old_prefs.tool_toggles:
            expanded_snapshot[it.tool_id] = bool(it.expanded)
    except Exception:
        pass

    # 2. Unload every loaded tool.
    try:
        core.unload_all_tools()
    except Exception as e:
        print(f"[XNeko] hot reload: unload_all_tools failed: {e}")

    # 3. Drop the module cache and invalidate import caches.
    try:
        _drop_tool_submodules()
        importlib.invalidate_caches()
    except Exception as e:
        print(f"[XNeko] hot reload: module cache drop failed: {e}")

    # 4. Unregister the old tool-owned preference classes.
    try:
        unregister_tool_preference_classes()
    except Exception as e:
        print(f"[XNeko] hot reload: pref class teardown failed: {e}")

    # 5. Re-discover every tool.
    #
    # A failure here leaves the registry in whatever state discovery
    # reached (possibly empty). Do not abort: continue to rebuild
    # preferences so the user sees the current state in the UI and
    # can hot-reload again after fixing the underlying issue,
    # instead of being forced to restart Blender.
    try:
        core._initialize_tools()
    except Exception as e:
        print(f"[XNeko] hot reload: discovery failed: {e}")
        _reports.report_critical_error(
            "hot reload: discovery failed",
            exc=e,
            extra={
                "effect": (
                    "tool registry may be empty or partial; "
                    "fix the issue and hot-reload again"
                ),
            },
        )

    # 6. Register the new tool-owned preference classes.
    register_tool_preference_classes()

    # 7. Rebuild the dynamic XNekoPreferences class and tool PG classes.
    new_cls = install_preferences()
    if new_cls is None:
        return False, "Preferences rebuild failed"

    # 8. Post-rebuild steps.
    #
    # Each sub-step is wrapped so a late failure does not crash the
    # operator or leave the addon half-broken.
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        if addon is None or addon.preferences is None:
            return False, "Preferences instance missing after rebuild"
        new_prefs = addon.preferences

        # 8a. Restore UI state onto the fresh instance.
        for attr, value in ui_snapshot.items():
            try:
                setattr(new_prefs, attr, value)
            except Exception:
                pass

        # 8b. Rebuild panels under the restored category.
        try:
            core.register_group_panels()
            core.attach_panels_to_groups()
        except Exception as e:
            print(f"[XNeko] hot reload: panel rebuild failed: {e}")

        try:
            refresh_panel_category(force=True)
        except Exception as e:
            print(f"[XNeko] hot reload: category refresh failed: {e}")

        # 8c. Re-init toggles, then restore per-tool state.
        init_tool_toggles()

        for it in new_prefs.tool_toggles:
            if it.tool_id in expanded_snapshot:
                try:
                    it.expanded = expanded_snapshot[it.tool_id]
                except Exception:
                    pass

        core.load_default_tools()

        if tool_snapshot is not None:
            try:
                prefs_io.import_prefs(new_prefs, core, tool_snapshot)
            except Exception as e:
                print(f"[XNeko] hot reload: state restore failed: {e}")

        # 8d. Refresh the issue blob on the new instance.
        try:
            new_prefs.registration_issues = json.dumps(
                core._state.registration_issues
            )
            new_prefs.plugin_version = core.get_plugin_version()
        except Exception:
            pass
    except Exception as e:
        print(f"[XNeko] hot reload: post-rebuild step failed: {e}")
        return False, f"Post-rebuild failed: {e}"

    _reports.reset_dedup()

    return True, "Tools hot-reloaded"


def init_tool_toggles():
    """Populate the toggle list from the registry defaults.

    Both session write and per-toggle load are suppressed during this
    pass: the values here are provisional, and the actual load/unload
    is driven by load_enabled_tools() right after.
    """
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return
    _push_suppress_session()
    core.push_toggle_suppress()
    try:
        p = prefs.preferences
        p.tool_toggles.clear()
        for tool_id, tool in core._TOOL_REGISTRY.items():
            item = p.tool_toggles.add()
            item.tool_id = tool_id
            item.display_name = tool["display_name"]
            if tool.get("compatible", True):
                item.enabled = tool["enabled_by_default"]
            else:
                item.enabled = False
    finally:
        core.pop_toggle_suppress()
        _pop_suppress_session()
    _invalidate_groups_cache()


def load_enabled_tools():
    """Load every tool whose toggle is currently enabled."""
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return
    for item in prefs.preferences.tool_toggles:
        if item.enabled:
            core.set_tool_enabled(item.tool_id, True)


def clear_tool_toggles():
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return
    prefs.preferences.tool_toggles.clear()
    _invalidate_groups_cache()


# ==================================================
# Panel category refresh (with rollback)
# ==================================================
def _reset_panel_category_cache():
    global _last_category
    _last_category = None


_last_category = None


def refresh_panel_category(force=False):
    global _last_category
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return

    new_category = (
        prefs.preferences.panel_category or "XNeko Tools"
    ).strip() or "XNeko Tools"

    if not force and new_category == _last_category:
        return
    _last_category = new_category

    all_panels = list(core._GROUP_PANEL_CLASSES)
    for tool in core._TOOL_REGISTRY.values():
        if tool["loaded"]:
            for cls in tool["classes"]:
                if isinstance(cls, type) and issubclass(cls, bpy.types.Panel):
                    all_panels.append(cls)

    if not all_panels:
        return

    old_categories = {
        cls: getattr(cls, "bl_category", "XNeko Tools")
        for cls in all_panels
    }

    for cls in all_panels:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    for cls in all_panels:
        cls.bl_category = new_category

    for cls in all_panels:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"[XNeko] re-register {cls.__name__} failed: {e}")
            cls.bl_category = old_categories[cls]
            try:
                bpy.utils.register_class(cls)
            except Exception as e2:
                print(f"[XNeko]   rollback also failed: {e2}")


def iter_preference_operators():
    """Yield every Operator class defined in this module."""
    mod = sys.modules[__name__]
    for _name, obj in list(vars(mod).items()):
        if not isinstance(obj, type):
            continue
        try:
            if not issubclass(obj, bpy.types.Operator):
                continue
        except TypeError:
            continue
        if obj is bpy.types.Operator:
            continue
        if getattr(obj, "__module__", None) != __name__:
            continue
        yield obj