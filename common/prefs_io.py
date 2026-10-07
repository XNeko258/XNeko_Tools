"""Serialization + project-file sync for XNeko preferences."""

import os
import json
import bpy


FORMAT_TAG = "xneko_prefs"

PROJECT_KEY = "xneko_project_prefs"


# ============================================================
# Introspection helpers
# ============================================================
def _short_id(core, full_id):
    """Return the preset key for a registered tool.

    Delegates to core.get_short_id so the mapping lives in exactly one
    place across the whole codebase.
    """
    return core.get_short_id(full_id)


def _iter_all_tools(core):
    """Yield (short_id, full_id, tool_dict) for every registered tool."""
    for full_id, tool in core._TOOL_REGISTRY.items():
        yield _short_id(core, full_id), full_id, tool


def _plugin_version():
    try:
        from .. import bl_info
        return ".".join(str(x) for x in bl_info.get("version", (0, 0, 0)))
    except Exception:
        return "unknown"


def _blender_version():
    return ".".join(str(x) for x in bpy.app.version[:3])


def _tool_version_bounds(tool):
    """Return (min, max) version bounds for a tool.

    Prefer the bounds cached on the tool record at discovery time.
    Unloaded tools (module=None) previously exported null bounds and
    lost compatibility checks. The live-module read is kept as a
    fallback for external callers.
    """
    minv = tool.get("version_min")
    maxv = tool.get("version_max")
    if minv is not None or maxv is not None:
        return (
            list(minv) if minv else None,
            list(maxv) if maxv else None,
        )

    module = tool.get("module")
    if module is None:
        return None, None

    minv = getattr(module, "blender_version_min", None)
    maxv = getattr(module, "blender_version_max", None)
    return (
        list(minv) if minv else None,
        list(maxv) if maxv else None,
    )


def _set_tool_enabled(core, tool_id, enabled):
    fn = getattr(core, "set_tool_enabled", None)
    if callable(fn):
        fn(tool_id, enabled)
    elif enabled:
        core.load_tool(tool_id)
    else:
        core.unload_tool(tool_id)


# ============================================================
# Preference value collection
# ============================================================
def _collect_tool_preferences(prefs_obj, tool):
    names = tool.get("_pref_names") or {}
    if not names:
        return {}

    out = {}
    for local_name, full_attr in names.items():
        if not hasattr(prefs_obj, full_attr):
            continue
        try:
            value = getattr(prefs_obj, full_attr)
            json.dumps(value)
            out[local_name] = value
        except Exception:
            continue
    return out


def _apply_tool_preferences(prefs_obj, tool, values):
    if not values:
        return

    names = tool.get("_pref_names") or {}
    if not names:
        return

    for local_name, value in values.items():
        full_attr = names.get(local_name)
        if not full_attr or not hasattr(prefs_obj, full_attr):
            continue
        try:
            setattr(prefs_obj, full_attr, value)
        except Exception as e:
            print(
                f"[XNeko] failed to apply pref '{local_name}' "
                f"for '{tool.get('tool_id', '?')}': {e}"
            )


# ============================================================
# Export
# ============================================================
def export_prefs(prefs_obj, core, name=""):
    enabled_map = {
        it.tool_id: bool(it.enabled) for it in prefs_obj.tool_toggles
    }

    data = {
        "format": FORMAT_TAG,
        "name": name,
        "plugin_version": _plugin_version(),
        "blender_version": _blender_version(),
        "tools": {},
    }

    for short, full_id, tool in _iter_all_tools(core):
        minv, maxv = _tool_version_bounds(tool)
        entry = {
            "__enabled__": enabled_map.get(
                full_id, bool(tool.get("enabled_by_default", True))
            ),
            "__version_min__": minv,
            "__version_max__": maxv,
        }

        prefs_values = _collect_tool_preferences(prefs_obj, tool)
        if prefs_values:
            entry["preferences"] = prefs_values

        data["tools"][short] = entry

    return data


# ============================================================
# Compatibility preview (dry-run)
# ============================================================
def _classify(core, data):
    if data.get("format") != FORMAT_TAG:
        raise ValueError("Not an XNeko preferences file")

    bv = tuple(bpy.app.version[:3])
    saved_tools = data.get("tools", {})

    available = {}
    for short, _full, tool in _iter_all_tools(core):
        available[short] = tool

    applied = []
    skipped = []

    for short, saved in saved_tools.items():
        tool = available.get(short)
        if tool is None:
            skipped.append((short, "Module not installed"))
            continue

        if not tool.get("compatible", True):
            skipped.append(
                (short, tool.get("incompatible_reason", "Incompatible"))
            )
            continue

        minv = saved.get("__version_min__")
        maxv = saved.get("__version_max__")
        if minv and bv < tuple(minv):
            skipped.append(
                (short, f"Requires Blender {'.'.join(map(str, minv))}+")
            )
            continue
        if maxv and bv > tuple(maxv):
            skipped.append(
                (short,
                 f"Supports Blender up to {'.'.join(map(str, maxv))}")
            )
            continue

        target = bool(saved.get("__enabled__", True))
        applied.append((short, "enable" if target else "disable"))

    return applied, skipped


def preview_compatibility(core, data):
    return _classify(core, data)


# ============================================================
# Import (apply)
# ============================================================
def import_prefs(prefs_obj, core, data, only_tools=None):
    applied, skipped = _classify(core, data)

    saved_tools = data.get("tools", {})

    short_to_full = {}
    for short, full, _tool in _iter_all_tools(core):
        short_to_full[short] = full

    toggles = {it.tool_id: it for it in prefs_obj.tool_toggles}

    applied_out = []
    skipped_out = list(skipped)

    for short, info in applied:
        if only_tools is not None and short not in only_tools:
            skipped_out.append((short, "Deselected"))
            continue

        full_id = short_to_full.get(short)
        if full_id is None:
            continue

        saved_entry = saved_tools.get(short, {})
        target = bool(saved_entry.get("__enabled__", True))

        item = toggles.get(full_id)
        if item is not None and item.enabled != target:
            item.enabled = target
        else:
            _set_tool_enabled(core, full_id, target)

        values = saved_entry.get("preferences")
        if values:
            tool = core._TOOL_REGISTRY.get(full_id)
            if tool is not None:
                _apply_tool_preferences(prefs_obj, tool, values)

        applied_out.append((short, info))

    return applied_out, skipped_out


# ============================================================
# File I/O
# ============================================================
def save_to_file(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_from_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# Project-file storage (Scene custom property)
# ============================================================
def get_project_data():
    """Return (data_dict_or_None, present_bool)."""
    scene = bpy.context.scene
    if scene is None:
        return None, False
    raw = scene.get(PROJECT_KEY)
    if not raw:
        return None, False
    try:
        return json.loads(raw), True
    except Exception as e:
        print(f"[XNeko] failed to parse project prefs: {e}")
        return None, False


def set_project_data(data):
    scene = bpy.context.scene
    if scene is None:
        return
    if data is None:
        scene.pop(PROJECT_KEY, None)
    else:
        scene[PROJECT_KEY] = json.dumps(data, ensure_ascii=False)


def clear_project_data():
    scene = bpy.context.scene
    if scene is not None:
        scene.pop(PROJECT_KEY, None)