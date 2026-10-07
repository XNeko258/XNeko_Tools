"""Session persistence for XNeko preferences.

Stores the last-known tool enable flags and per-tool preference values
in a JSON file under the user config directory, independent of
Blender's own userpref save/load cycle.

This makes the plugin state survive Blender restarts even when the
user never explicitly runs "Save Preferences", and gives the
load_post handler a baseline to fall back on when the loaded .blend
carries no project preferences.
"""

import os
import json

import bpy


SESSION_FILE_NAME = "session.json"


def _session_dir():
    return bpy.utils.user_resource(
        "CONFIG",
        path=os.path.join("xneko_tools"),
        create=True,
    )


def session_path():
    """Return the absolute path of the session file."""
    return os.path.join(_session_dir(), SESSION_FILE_NAME)


def has_session():
    return os.path.isfile(session_path())


def load_session():
    """Return the parsed session dict, or None when missing/corrupt."""
    path = session_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[XNeko] failed to load session: {e}")
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_session(data):
    """Write the session dict to disk. Never raises."""
    path = session_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[XNeko] failed to save session: {e}")


def clear_session():
    path = session_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except Exception as e:
            print(f"[XNeko] failed to clear session: {e}")