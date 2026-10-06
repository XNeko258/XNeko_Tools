# Development Guide

This guide explains how to create new tool modules for XNeko Tools.

XNeko Tools uses a modular discovery system. Each tool lives under `tools/` as either a single `.py` file or a package. The framework automatically registers operators, panels, preferences, scene properties, and lifecycle hooks declared by the module.

---

## Table of Contents

- [1. Directory Structure](#1-directory-structure)
- [2. Minimal Runnable Module](#2-minimal-runnable-module)
- [3. Metadata Reference](#3-metadata-reference)
- [4. Preferences](#4-preferences)
  - [4.1 Declaration](#41-declaration)
  - [4.2 Read / Write](#42-read--write)
  - [4.3 Drawing to UI](#43-drawing-to-ui)
  - [4.4 Custom Preference UI](#44-custom-preference-ui)
  - [4.5 Where Preferences Appear](#45-where-preferences-appear)
- [5. Version Compatibility](#5-version-compatibility)
- [6. Lifecycle Hooks](#6-lifecycle-hooks)
- [7. Scene Properties](#7-scene-properties)
- [8. Complex Modules (Packages)](#8-complex-modules-packages)
- [9. Shared Code](#9-shared-code)
- [10. Troubleshooting Checklist](#10-troubleshooting-checklist)

---

## 1. Directory Structure

```text
XNeko_Tools/
├── __init__.py
├── core.py
├── preferences.py
├── common/                    ← Shared code (not a tool)
│   ├── __init__.py
│   ├── prefs_io.py
│   └── preset_store.py
├── presets/                   ← Preset JSON files (not tools)
│   └── *.json
└── tools/                     ← Tool modules only
    ├── mesh_tools/
    │   └── clean_groups.py
    ├── bone_tools/
    │   └── quick_rotate.py
    └── object_tools/
        └── advanced_transform/    ← Complex modules use a package
            ├── __init__.py
            ├── _operators.py
            └── _panels.py
```

**Rules:**

- Each folder under `tools/` is a group. Groups appear as tabs in the add-on preferences.
- Multi-level nesting is supported: `tools/rig/constraints/xxx.py` → group name `Rig / Constraints`.
- Files or package names starting with `_` are skipped. They can be used as helper files.
- A `.py` file without a `classes` tuple is skipped. It can be used as a utility library.
- `common/` and `presets/` are never treated as tools.

---

## 2. Minimal Runnable Module

`tools/mesh_tools/my_tool.py`:

```python
import bpy


tool_name = "My Tool"
tool_default_enabled = True


class MY_OT_do_something(bpy.types.Operator):
    bl_idname = "xneko.my_tool_do"
    bl_label = "Do Something"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'INFO'}, "Hello!")
        return {'FINISHED'}


class VIEW3D_PT_my_tool(bpy.types.Panel):
    bl_label = "My Tool"
    bl_idname = "VIEW3D_PT_xneko_my_tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        self.layout.operator("xneko.my_tool_do", icon='PLAY')


classes = (
    MY_OT_do_something,
    VIEW3D_PT_my_tool,
)
```

Save the file, then cold restart Blender. The new module will appear in the N-panel.

> **Do not manually set `bl_category` or `bl_parent_id`.** The framework assigns them automatically during registration.

---

## 3. Metadata Reference

All metadata are module-level variables placed at the top of the file.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `classes` | `tuple` | — | **Required.** Blender classes to register. |
| `tool_name` | `str` | File name converted to Title Case | Display name. |
| `tool_default_enabled` | `bool` | `True` | Whether the tool is enabled by default on first install. |
| `blender_version_min` | `tuple` | None | Minimum Blender version, e.g. `(4, 0, 0)`. |
| `blender_version_max` | `tuple` | None | Maximum supported Blender version (inclusive). |
| `preference_props` | `dict` | `{}` | Preference properties for the tool. |
| `preference_classes` | `tuple` | `()` | PropertyGroup classes required by preference properties. |
| `preferences_in_addon` | `bool` | `True` | If `False`, preference UI only appears in the N-panel. |
| `draw_preferences` | `callable` | None | Custom preference UI. |
| `scene_props` | `dict` | `{}` | Properties attached to `bpy.types.Scene`. |
| `on_load` | `callable` | None | Called when the module is enabled. |
| `on_unload` | `callable` | None | Called when the module is disabled. Use this to clean up resources. |

---

## 4. Preferences

### 4.1 Declaration

```python
from bpy.props import StringProperty, BoolProperty, IntProperty

preference_props = {
    "prefix": StringProperty(name="Prefix", default="Bone_"),
    "auto_number": BoolProperty(name="Auto Number", default=True),
    "max_count": IntProperty(name="Max Count", default=10, min=1, max=100),
}
```

### 4.2 Read / Write

```python
import importlib

def _get_prefs():
    top = __name__.split(".")[0]
    try:
        mod = importlib.import_module(top + ".preferences")
    except ImportError:
        return None
    return mod.get_tool_prefs(__name__)

# Read
prefs = _get_prefs()
value = prefs.prefix          # "Bone_"

# Write
prefs.prefix = "Bone_"
```

### 4.3 Drawing to UI

**Correct:**

```python
prefs.prop(layout, "prefix")
prefs.prop(layout, "auto_number", text="Use Numbers", icon='SORTALPHA')
```

**Incorrect** (does not raise an error, but draws nothing):

```python
layout.prop(prefs, "prefix")   # ❌ prefs is not an RNA object
```

### 4.4 Custom Preference UI

```python
def draw_preferences(layout, context, prefs):
    col = layout.column(align=True)
    col.label(text="Naming:", icon='SORTALPHA')
    prefs.prop(col, "prefix")
    prefs.prop(col, "auto_number")
```

Once declared, `preference_props` is no longer expanded automatically. You are fully responsible for drawing the UI.

### 4.5 Where Preferences Appear

| Goal | Configuration |
| --- | --- |
| Show in the add-on preferences panel (default) | Nothing to write. |
| Show only in the N-panel | `preferences_in_addon = False` |
| Show in both places | Keep the default and call `prefs.prop(...)` inside `Panel.draw`. |

---

## 5. Version Compatibility

```python
blender_version_min = (4, 0, 0)     # At least 4.0
blender_version_max = (4, 3, 0)     # At most 4.3, optional
```

When the version condition is not met:

- The row in the add-on preferences is greyed out with a red explanation.
- The user cannot enable the tool.
- The tool does not appear in the N-panel.
- The console prints `[XNeko] ... refusing to load`.

If these two fields are omitted, the tool is compatible with all versions.

---

## 6. Lifecycle Hooks

```python
_timer_handle = None
_cache = {}

def on_load():
    global _timer_handle
    _timer_handle = bpy.app.timers.register(tick, persistent=True)

def on_unload():
    global _timer_handle
    if _timer_handle is not None:
        try:
            bpy.app.timers.unregister(_timer_handle)
        except Exception:
            pass
        _timer_handle = None
    _cache.clear()
```

**Important:** When a module is disabled, its Python module is removed from `sys.modules`, but timers, handlers, and singletons are not cleaned up automatically. You must release them yourself in `on_unload`.

---

## 7. Scene Properties

```python
from bpy.props import IntProperty

scene_props = {
    "xneko_my_setting": IntProperty(name="My Setting", default=0),
}
```

Access them with `context.scene.xneko_my_setting`. It is recommended to use the `xneko_` prefix to avoid conflicts. The framework cleans up these properties automatically when the module is disabled.

---

## 8. Complex Modules (Packages)

```text
tools/object_tools/advanced_transform/
├── __init__.py             ← Declares classes / tool_name and other metadata
├── _operators.py           ← Starts with _ = skipped
├── _panels.py              ← Skipped
└── _utils.py               ← Skipped
```

`__init__.py`:

```python
from ._operators import ADV_OT_do, ADV_OT_undo
from ._panels import ADV_PT_main

tool_name = "Advanced Transform"
tool_default_enabled = True

classes = (
    ADV_OT_do,
    ADV_OT_undo,
    ADV_PT_main,
)
```

**Convention:** When the package itself is a tool, all child files must start with `_`. Otherwise they will be treated as independent tools.

---

## 9. Shared Code

Code that needs to be reused across modules should be placed under `common/`:

```text
common/
├── __init__.py
├── math_helpers.py
└── ui_helpers.py
```

Import from a module:

```python
from ...common import math_helpers
```

> **Do not import one tool module from another.** When a module is disabled, it is unloaded, and references will become stale objects.

---

## 10. Troubleshooting Checklist

| Symptom | Check |
| --- | --- |
| Module does not appear | ① Does the file name start with `_`? ② Is there a `classes` tuple? ③ Did the console show `import failed`? ④ Was the version check rejected? |
| Panel appears at the top level instead of under its group | Check whether `bl_parent_id` / `bl_category` was set manually. |
| Preference checkbox does not appear | ① Did you use `layout.prop(prefs, ...)`? ② Did you cold restart Blender after changing `preference_props`? |
| Button should be greyed out but is not | Check the conditions under which `poll` returns `False`. |
| Code changes do not take effect | **Cold restart Blender** (not F8). |

---

## See Also

- [Preset Guide](PRESETS.md) — how to export, import, apply, and share presets, and how project-embedded preferences work.