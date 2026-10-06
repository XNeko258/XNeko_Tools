# Development Guide

This guide describes how to write tool modules for XNeko Tools.

The framework discovers tool modules under `tools/` and registers their
operators and panels automatically. Tool enable/disable state is stored by
the framework and can be exported as a preset.

---

## 1. Directory Structure

```text
XNeko_Tools/
├── __init__.py
├── core.py
├── preferences.py
├── common/                    ← shared code (not a tool)
│   ├── __init__.py
│   ├── prefs_io.py
│   └── preset_store.py
├── presets/                   ← preset JSON (not a tool)
│   └── *.json
└── tools/                     ← tool modules only
    ├── mesh_tools/
    │   └── clean_groups.py
    ├── bone_tools/
    │   └── quick_rotate.py
    └── object_tools/
        └── advanced_transform/    ← packages are allowed
            ├── __init__.py
            ├── _operators.py
            └── _panels.py
```

**Rules**

- Each folder under `tools/` becomes a group. Groups appear as tabs in
  the add-on preferences.
- Multi-level nesting is supported. `tools/rig/constraints/xxx.py` maps to
  the group `Rig / Constraints`.
- Files or packages starting with `_` are skipped. Use this for helpers.
- A `.py` file without a `classes` tuple is skipped. Use this for utility
  libraries.
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

Save, then cold restart Blender. The tool appears in the N-panel.

> **Do not set `bl_category` or `bl_parent_id` manually.** The framework
> assigns them during registration.

---

## 3. Metadata Reference

All metadata are module-level variables placed at the top of the file.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `classes` | `tuple` | — | **Required.** Blender classes to register. |
| `tool_name` | `str` | Title Case of file name | Display name. |
| `tool_default_enabled` | `bool` | `True` | Whether the tool starts enabled on a fresh install. |
| `blender_version_min` | `tuple` | None | Minimum Blender version, e.g. `(4, 0, 0)`. |
| `blender_version_max` | `tuple` | None | Maximum Blender version (inclusive). |
| `preference_props` | `dict` | `{}` | Per-tool settings shown in the add-on preferences. |
| `preference_classes` | `tuple` | `()` | PropertyGroups required by preference properties. |
| `preferences_in_addon` | `bool` | `True` | If `False`, the per-tool settings UI is not shown in the add-on preferences. |
| `draw_preferences` | `callable` | None | Custom preference UI. |
| `scene_props` | `dict` | `{}` | Properties attached to `bpy.types.Scene`. |
| `on_load` | `callable` | None | Called when the module is enabled. |
| `on_unload` | `callable` | None | Called when the module is disabled. Use for cleanup. |

---

## 4. Choosing Between `preference_props` and `scene_props`

This distinction matters because presets only record the enabled/disabled
state of tools, not the value of their settings.

**Use `preference_props` when:**

- the value is a persistent configuration for the tool
- the value should survive across sessions
- the value is edited from the add-on preferences panel

**Use `scene_props` when:**

- the value is a per-operation parameter, such as "clean empty groups this time"
- the value should be scoped to the scene / project
- the value should not follow the user across projects

Do not put temporary operation parameters into `preference_props`.

> The old advice to set `preferences_in_addon = False` to hide the UI in
> the add-on panel also removed the properties from the add-on preferences
> store, which prevented the preset system from reaching them. Avoid
> `preferences_in_addon = False` in new modules. If you want a clean
> add-on preferences panel, define an empty `draw_preferences` instead.

---

## 5. Preferences

### 5.1 Declaration

```python
from bpy.props import StringProperty, BoolProperty, IntProperty

preference_props = {
    "prefix": StringProperty(name="Prefix", default="Bone_"),
    "auto_number": BoolProperty(name="Auto Number", default=True),
    "max_count": IntProperty(name="Max Count", default=10, min=1, max=100),
}
```

### 5.2 Read / Write

```python
import importlib


def _get_prefs():
    top = __name__.split(".")[0]
    try:
        mod = importlib.import_module(top + ".preferences")
    except ImportError:
        return None
    return mod.get_tool_prefs(__name__)


prefs = _get_prefs()
value = prefs.prefix          # read
prefs.prefix = "Bone_"        # write
```

### 5.3 Drawing

**Correct**

```python
prefs.prop(layout, "prefix")
prefs.prop(layout, "auto_number", text="Use Numbers", icon='SORTALPHA')
```

**Incorrect** — does not raise an error, but draws nothing:

```python
layout.prop(prefs, "prefix")   # prefs is not an RNA object
```

### 5.4 Custom preference UI

```python
def draw_preferences(layout, context, prefs):
    col = layout.column(align=True)
    col.label(text="Naming:", icon='SORTALPHA')
    prefs.prop(col, "prefix")
    prefs.prop(col, "auto_number")
```

Declaring `draw_preferences` disables the automatic expansion of
`preference_props` in the add-on preferences panel. You are then fully
responsible for drawing the UI.

Use an empty function to keep the panel clean while keeping the
properties registered:

```python
def draw_preferences(layout, context, prefs):
    pass
```

---

## 6. Version Compatibility

```python
blender_version_min = (4, 0, 0)
blender_version_max = (4, 3, 0)   # optional
```

When the current Blender version falls outside these bounds:

- the tool is greyed out in the add-on preferences with a red reason
- the user cannot enable it
- the tool does not appear in the N-panel
- the console prints `[XNeko] ... refusing to load`

Omitting both fields means the tool is compatible with all versions.

---

## 7. Lifecycle Hooks

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

When a module is disabled, its Python module is removed from
`sys.modules`, but timers, handlers and singletons are not cleaned up
automatically. Release them in `on_unload`.

---

## 8. Scene Properties

```python
from bpy.props import IntProperty

scene_props = {
    "xneko_my_setting": IntProperty(name="My Setting", default=0),
}
```

Access them as `context.scene.xneko_my_setting`. Use the `xneko_` prefix
to avoid conflicts. The framework clears them when the module is disabled.

---

## 9. Complex Modules (Packages)

```text
tools/object_tools/advanced_transform/
├── __init__.py             ← declares classes / tool_name and other metadata
├── _operators.py           ← starts with _ = skipped
├── _panels.py              ← skipped
└── _utils.py               ← skipped
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

**Convention** — when the package itself is a tool, all child files must
start with `_`. Otherwise they are discovered as independent tools.

---

## 10. Shared Code

Reusable code lives under `common/`:

```text
common/
├── __init__.py
├── math_helpers.py
└── ui_helpers.py
```

Import from a tool:

```python
from ...common import math_helpers
```

> **Do not import one tool module from another.** When a module is
> disabled it is unloaded, and cross-module references become stale.

---

## 11. Troubleshooting Checklist

| Symptom | Check |
| ------- | ----- |
| Module does not appear | ① file name starts with `_`? ② is there a `classes` tuple? ③ did the console print `import failed`? ④ was the version check rejected? |
| Panel appears at the top level instead of under its group | Did you set `bl_parent_id` / `bl_category` manually? |
| Preference widget does not appear | Did you use `layout.prop(prefs, ...)` instead of `prefs.prop(layout, ...)`? |
| Button should be greyed out but is not | Check the conditions under which `poll` returns `False`. |
| Code changes do not take effect | Cold restart Blender (not F8). |
| Preset does not affect a tool | Is the tool installed, compatible, and checked in the Apply dialog? |

---

## See Also

- [Preset Guide](PRESETS.md) — how presets and project-embedded preferences work.
- [Group Folder Guide](GROUPS.md) — how to name folders under `tools/`