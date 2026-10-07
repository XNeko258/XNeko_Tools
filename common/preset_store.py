"""Preset file management.

Write target is always the user resource directory, so user presets
survive addon updates and reinstalls. The addon-local folder is still
scanned as a legacy source, so presets written by earlier versions
remain readable and deletable. New presets are never written into the
addon folder.
"""

import os
import bpy

from . import prefs_io


# ============================================================
# Directory resolution
# ============================================================
def _addon_preset_dir():
    try:
        from .. import __path__ as addon_path
        return os.path.join(addon_path[0], "presets")
    except Exception:
        return None


# The user preset directory is resolved once per session. Repeated
# calls (list_presets, preset_exists, load_preset, delete_preset)
# would otherwise trigger makedirs on every redraw.
_user_preset_dir_cache = None


def _user_preset_dir():
    """Primary preset folder. Always writable, update-safe."""
    global _user_preset_dir_cache
    if _user_preset_dir_cache is None:
        _user_preset_dir_cache = bpy.utils.user_resource(
            'SCRIPTS',
            path=os.path.join("presets", "XNeko_Tools"),
            create=True,
        )
    return _user_preset_dir_cache


def _all_preset_dirs():
    """Directories to scan when listing / reading presets.

    User dir first (new location), legacy addon dir second (so existing
    installs keep working).
    """
    dirs = [_user_preset_dir()]
    addon_dir = _addon_preset_dir()
    if addon_dir and os.path.isdir(addon_dir):
        dirs.append(addon_dir)
    return dirs


def get_preset_dir():
    """Return the directory used for writing new presets."""
    return _user_preset_dir()


def get_preset_path(name):
    """Path used for writing new presets.

    Reads should use _find_preset_path() so legacy presets in the
    addon folder are still found.
    """
    return os.path.join(_user_preset_dir(), name + ".json")


def _find_preset_path(name):
    """Return the first existing path for `name`, or None."""
    for folder in _all_preset_dirs():
        candidate = os.path.join(folder, name + ".json")
        if os.path.isfile(candidate):
            return candidate
    return None


# ============================================================
# Listing
# ============================================================
def list_presets():
    names = set()
    for folder in _all_preset_dirs():
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if fn.endswith(".json"):
                names.add(fn[:-5])
    return sorted(names, key=lambda s: s.lower())


def preset_exists(name):
    return _find_preset_path(name) is not None


# ============================================================
# Load / save / delete
# ============================================================
def load_preset(name):
    path = _find_preset_path(name)
    if path is None:
        raise FileNotFoundError(name)
    return prefs_io.load_from_file(path)


def save_preset(name, data):
    data = dict(data)
    data["name"] = name
    # Always writes into the user directory.
    prefs_io.save_to_file(get_preset_path(name), data)


def delete_preset(name):
    # Delete from wherever it actually lives (user or legacy).
    path = _find_preset_path(name)
    if path is not None:
        os.remove(path)


# ============================================================
# Name sanitisation
# ============================================================
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_name(name):
    """Normalise a user-supplied preset name.

    - strips path separators and shell-hostile characters
    - strips leading/trailing whitespace and trailing dots
    - prefixes Windows reserved basenames with "_"
    - truncates overly long names
    - returns "" for inputs that sanitise to nothing
    """
    if not name:
        return ""
    bad = set('\\/:*?"<>|')
    cleaned = "".join(c for c in name if c not in bad).strip()
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        return ""
    if cleaned.upper().split(".", 1)[0] in _WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    return cleaned