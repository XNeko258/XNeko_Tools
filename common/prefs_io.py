"""Serialization + project-file sync for XNeko preferences."""

import os
import json
import bpy


__xneko_framework__ = True

FORMAT_TAG = "xneko_prefs"

PROJECT_KEY = "xneko_project_prefs"


# ============================================================
# Introspection helpers
# ============================================================
def _normalize_version(v):
    """Coerce a version sequence to a 3-tuple of ints."""
    if not v:
        return None
    t = tuple(int(x) for x in tuple(v)[:3])
    return t + (0,) * (3 - len(t))


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
    minv = _normalize_version(tool.get("version_min"))
    maxv = _normalize_version(tool.get("version_max"))
    if minv is not None or maxv is not None:
        return (
            list(minv) if minv else None,
            list(maxv) if maxv else None,
        )

    module = tool.get("module")
    if module is None:
        return None, None

    minv = _normalize_version(getattr(module, "blender_version_min", None))
    maxv = _normalize_version(getattr(module, "blender_version_max", None))
    return (
        list(minv) if minv else None,
        list(maxv) if maxv else None,
    )


def _set_tool_enabled(core, tool_id, enabled):
    fn = getattr(core, "set_tool_enabled", None)
    if callable(fn):
        return bool(fn(tool_id, enabled))
    if enabled:
        core.load_tool(tool_id)
    else:
        core.unload_tool(tool_id)
    return True


# ============================================================
# Preference value collection
# ============================================================
def _json_safe(value):
    """Snapshot a preference value as plain Python data.

    RNA array views (bpy_prop_array) hold a pointer into the owning
    PropertyGroup's C-side storage. Storing one of those in the
    hot-reload snapshot and then rebuilding the PG class leaves a
    dangling pointer, which crashes pyrna the next time setattr()
    reads it. Converting to a plain list here severs the reference.
    """
    to_list = getattr(value, "to_list", None)
    if callable(to_list):
        try:
            return list(to_list())
        except Exception:
            pass
    if hasattr(value, "__iter__") and not isinstance(
            value, (str, bytes, dict)):
        try:
            return [_json_safe(v) for v in value]
        except Exception:
            pass
    return value


def _collect_tool_preferences(prefs_obj, tool):
    attr = tool.get("_pref_pg_attr")
    if not attr:
        return {}
    pg = getattr(prefs_obj, attr, None)
    if pg is None:
        return {}

    out = {}
    for local_name in (tool.get("preference_props") or {}):
        try:
            value = getattr(pg, local_name)
        except Exception:
            continue
        out[local_name] = _json_safe(value)
    return out


def _validate_pref_value(pg, local_name, value):
    """Return True if `value` can safely be assigned to pg.local_name.

    Blender 4.5 hard-crashes (EXCEPTION_ACCESS_VIOLATION inside
    RNA_property_array_dimension -> validate_array_type) when a
    malformed sequence is handed to an array RNA property. Python's
    try/except cannot catch that, so every array value is checked
    here and anything with the wrong length or element types is
    refused before it reaches pyrna.

    This also serves as a second line of defence for values that
    come from a stale session.json or a shared preset written by an
    older version.
    """
    try:
        prop = pg.bl_rna.properties.get(local_name)
    except Exception:
        return False
    if prop is None:
        return False

    try:
        array_len = prop.array_length
    except Exception:
        array_len = 0

    # Scalar property: accept as-is.
    if array_len <= 0:
        return True

    # Array property: must be a sequence of the exact expected
    # length, with numeric elements.
    if value is None:
        return False
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return False
    try:
        seq = list(value)
    except TypeError:
        return False

    if len(seq) != array_len:
        print(
            f"[XNeko] refusing malformed array for '{local_name}': "
            f"expected {array_len} items, got {len(seq)}"
        )
        return False

    if prop.type == 'BOOLEAN':
        return all(isinstance(x, (bool, int)) for x in seq)
    if prop.type in {'INT', 'FLOAT'}:
        return all(
            isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in seq
        )
    return True


def _apply_tool_preferences(prefs_obj, tool, values):
    if not values:
        return

    attr = tool.get("_pref_pg_attr")
    if not attr:
        return
    pg = getattr(prefs_obj, attr, None)
    if pg is None:
        return

    for local_name, value in values.items():
        if not hasattr(pg, local_name):
            continue
        if not _validate_pref_value(pg, local_name, value):
            continue
        try:
            setattr(pg, local_name, value)
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

        minv = _normalize_version(saved.get("__version_min__"))
        maxv = _normalize_version(saved.get("__version_max__"))
        if minv and bv < minv:
            skipped.append(
                (short, f"Requires Blender {'.'.join(map(str, minv))}+")
            )
            continue
        if maxv and bv > maxv:
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
        if item is None:
            _set_tool_enabled(core, full_id, target)
        elif item.enabled != target:
            ok = _set_tool_enabled(core, full_id, target)
            if ok:
                core.push_toggle_suppress()
                try:
                    item.enabled = target
                finally:
                    core.pop_toggle_suppress()

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
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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