"""Preview icon cache for addon preferences.

Blender's UILayout.operator() accepts an icon_value pointing to an
entry in a bpy.utils.previews collection. This module loads image
files lazily, caches their previews by path, and hands back the
integer icon_id for use in the UI.

Paths may be absolute, or relative to the plugin root directory
(e.g. "icons/patreon.png"). Missing or invalid files yield 0, which
Blender renders as "no icon" - callers should fall back to a text-
only button in that case.
"""

import os

import bpy


_PLUGIN_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

_previews = None
_cache = {}


def _get_previews():
    global _previews
    if _previews is None:
        _previews = bpy.utils.previews.new()
    return _previews


def _resolve(path):
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.join(_PLUGIN_ROOT, path)


def get_icon_id(path):
    """Return the preview icon_id for an image, or 0 on failure.

    Loads the image on first call and caches the result. Never raises.
    """
    if not path:
        return 0
    if path in _cache:
        return _cache[path]

    resolved = _resolve(path)
    if not os.path.isfile(resolved):
        print(f"[XNeko] icon not found: {resolved}")
        _cache[path] = 0
        return 0

    try:
        previews = _get_previews()
        key = f"xneko_icon::{path}"
        if key not in previews:
            previews.load(key, resolved, 'IMAGE')
        icon_id = previews[key].icon_id
        _cache[path] = icon_id
        return icon_id
    except Exception as e:
        print(f"[XNeko] failed to load icon {path}: {e}")
        _cache[path] = 0
        return 0


_IMAGE_EXTS = (
    ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff", ".webp",
)


def is_image_path(value):
    """True if value looks like an image file path."""
    if not value or not isinstance(value, str):
        return False
    return value.lower().endswith(_IMAGE_EXTS)


def clear():
    """Release all loaded previews. Called on plugin unregister."""
    global _previews, _cache
    if _previews is not None:
        try:
            bpy.utils.previews.remove(_previews)
        except Exception:
            pass
    _previews = None
    _cache = {}