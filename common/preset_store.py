"""Preset file management.

Presets are stored inside the addon at:
    XNeko_Tools/presets/*.json

If the addon folder is read-only (e.g. installed as a Blender
extension zip), the module silently falls back to the user
resource directory.
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


def _is_writable(folder):
    """Best-effort check: can we create a file here?"""
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_probe")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def get_preset_dir():
    """Primary preset folder. Prefers the addon-local folder."""
    addon_dir = _addon_preset_dir()
    if addon_dir and _is_writable(addon_dir):
        return addon_dir

    # Fallback: user resource directory (always writable)
    return bpy.utils.user_resource(
        'SCRIPTS',
        path=os.path.join("presets", "XNeko_Tools"),
        create=True,
    )


def get_preset_path(name):
    return os.path.join(get_preset_dir(), name + ".json")


# ============================================================
# Listing
# ============================================================
def list_presets():
    folder = get_preset_dir()
    if not os.path.isdir(folder):
        return []
    names = [fn[:-5] for fn in os.listdir(folder) if fn.endswith(".json")]
    return sorted(names, key=lambda s: s.lower())


def preset_exists(name):
    return os.path.isfile(get_preset_path(name))


# ============================================================
# Load / save / delete
# ============================================================
def load_preset(name):
    path = get_preset_path(name)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return prefs_io.load_from_file(path)


def save_preset(name, data):
    data = dict(data)
    data["name"] = name
    prefs_io.save_to_file(get_preset_path(name), data)


def delete_preset(name):
    path = get_preset_path(name)
    if os.path.isfile(path):
        os.remove(path)


def sanitize_name(name):
    bad = set('\\/:*?"<>|')
    return "".join(c for c in name if c not in bad).strip()