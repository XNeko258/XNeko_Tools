# Development Guide

This guide describes how to write tool modules for XNeko Tools.

The framework discovers tool modules under `tools/` and registers their
operators and panels automatically. Every module must declare a unique
`tool_id`. Modules with missing or invalid `tool_id`, or with a `tool_id`
that collides with another module, are skipped and reported in the
add-on preferences.

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
├── logs/                      ← debug log output (not a tool)
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
- Multi-level nesting is supported. `tools/rig/constraints/xxx.py` maps
  to the group `Rig / Constraints`.
- Files or packages starting with `_` are skipped. Use this for helpers.
- A `.py` file without a `classes` tuple is skipped. Use this for utility
  libraries.
- `common/`, `presets/`, and `logs/` are never treated as tools.

---

## 2. Required Metadata

Every tool module must define a module-level `tool_id` string and a
module-level `classes` tuple. Both are required.

```python
import bpy


tool_id = "clean_groups"
tool_name = "Clean Vertex Groups"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


class XNEKO_OT_clean_groups(bpy.types.Operator):
    bl_idname = "xneko.clean_groups"
    bl_label = "Clean Vertex Groups"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'INFO'}, "Done")
        return {'FINISHED'}


class VIEW3D_PT_xneko_clean_groups(bpy.types.Panel):
    bl_label = "Clean Vertex Groups"
    bl_idname = "VIEW3D_PT_xneko_clean_groups"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        self.layout.operator("xneko.clean_groups")


classes = (
    XNEKO_OT_clean_groups,
    VIEW3D_PT_xneko_clean_groups,
)
```

Save the file, then cold restart Blender. The tool appears in the
N-panel.

> **Do not set `bl_category` or `bl_parent_id` manually.** The framework
> assigns them during registration.

---

## 3. `tool_id` Rules

`tool_id` is the primary identity of a tool. It is used as:

- the preset key when exporting or importing presets
- the prefix of the tool's preference property names
- the collision key for detecting duplicate tools

**Allowed characters:** lowercase letters, digits, and underscores. The
pattern is `^[a-z0-9_]+$`.

**Examples of valid `tool_id`:**

```python
tool_id = "clean_groups"
tool_id = "quick_rotate"
tool_id = "vgb_generate"
```

**Examples of invalid `tool_id`** (all cause the module to be skipped):

```python
tool_id = "Clean Groups"     # spaces and uppercase
tool_id = "quick-rotate"     # hyphen
tool_id = "clean.groups"     # dot
tool_id = ""                 # empty
```

**Global uniqueness:** two modules must never declare the same
`tool_id`. If they do:

- both modules are disabled
- the console prints a collision report with both file paths
- the add-on preferences show a red warning box listing the conflict

**Portability:** `tool_id` determines the preset key. As long as it stays
the same, a tool can:

- move between group folders
- be renamed on disk
- be shared with another user who installs it under a different folder

and presets remain valid.

---

## 4. Metadata Reference

All metadata are module-level variables placed at the top of the file.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `tool_id` | `str` | — | **Required.** Unique short id. `^[a-z0-9_]+$`. |
| `classes` | `tuple` | — | **Required.** Blender classes to register. |
| `tool_name` | `str` | Title Case of file name | Display name. |
| `tool_default_enabled` | `bool` | `True` | Whether the tool starts enabled on a fresh install. |
| `blender_version_min` | `tuple` | None | Minimum Blender version, e.g. `(4, 0, 0)`. |
| `blender_version_max` | `tuple` | None | Maximum Blender version (inclusive). |
| `preference_props` | `dict` | `{}` | Per-tool settings shown in the add-on preferences. Captured by presets. |
| `preference_classes` | `tuple` | `()` | PropertyGroups required by preference properties. |
| `preferences_in_addon` | `bool` | `True` | If `False`, the per-tool settings UI is not shown in the add-on preferences. |
| `draw_preferences` | `callable` | None | Custom preference UI. |
| `scene_props` | `dict` | `{}` | Properties attached to `bpy.types.Scene`. Never touched by presets. |
| `on_load` | `callable` | None | Called when the module is enabled. |
| `on_unload` | `callable` | None | Called when the module is disabled. Use for cleanup. |

---

## 5. Choosing Between `preference_props` and `scene_props`

This distinction determines what a preset captures.

**Use `preference_props` when:**

- the value is a persistent user configuration for the tool
- the value should survive across sessions and machines
- the value should travel with a preset
- the value is edited from the add-on preferences panel

**Use `scene_props` when:**

- the value is a per-operation parameter, e.g. "remove empty groups this
  time"
- the value should be scoped to the scene or project
- the value should not follow the user across projects or presets

Presets capture the enabled state and the values of `preference_props`
for every tool. They never read or write `scene_props`.

Do not put temporary operation parameters into `preference_props`. They
will be captured by presets and travel to other machines.

---

## 6. Preferences

### 6.1 Declaration

```python
from bpy.props import StringProperty, BoolProperty, IntProperty

preference_props = {
    "prefix": StringProperty(name="Prefix", default="Bone_"),
    "auto_number": BoolProperty(name="Auto Number", default=True),
    "max_count": IntProperty(name="Max Count", default=10, min=1, max=100),
}
```

### 6.2 Read / Write

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

### 6.3 Drawing

**Correct**

```python
prefs.prop(layout, "prefix")
prefs.prop(layout, "auto_number", text="Use Numbers", icon='SORTALPHA')
```

**Incorrect** — does not raise an error, but draws nothing:

```python
layout.prop(prefs, "prefix")   # prefs is not an RNA object
```

### 6.4 Custom preference UI

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
properties registered and captured by presets:

```python
def draw_preferences(layout, context, prefs):
    pass
```

> Avoid `preferences_in_addon = False` in new modules. That flag removes
> the preference UI **and** keeps the properties out of the add-on
> preferences store, which prevents presets from capturing them. Use an
> empty `draw_preferences` instead.

---

## 7. Version Compatibility

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

## 8. Lifecycle Hooks

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
`sys.modules`, but timers, handlers, and singletons are not cleaned up
automatically. Release them in `on_unload`.

---

## 9. Scene Properties

```python
from bpy.props import IntProperty

scene_props = {
    "xneko_my_setting": IntProperty(name="My Setting", default=0),
}
```

Access them as `context.scene.xneko_my_setting`. Use the `xneko_` prefix
to avoid conflicts. The framework clears them when the module is
disabled.

`scene_props` are stored per `.blend` file and never travel with a
preset.

---

## 10. Group Icons

Each group can define an icon in its `tools/<group>/__init__.py`:

```python
group_icon = "MESH_DATA"      # built-in Blender icon name
group_icon = "icon.png"       # image file, relative to the group folder
group_icon = "(^_^)"          # text symbol
group_icon = "🧰"             # emoji
```

Resolution order:

1. If the value ends with an image extension, it is treated as an image
   file.
2. Otherwise, if the value matches a built-in Blender icon name, it is
   used directly.
3. Otherwise, it is treated as a text symbol and drawn as a label
   prefix.

Image files must include an extension. Files without extensions are
never treated as images.

If a group does not define `group_icon`, the framework falls back to a
built-in icon derived from the group folder name. See `docs/GROUPS.md`
for details.

---

## 11. Complex Modules (Packages)

```text
tools/object_tools/advanced_transform/
├── __init__.py             ← declares tool_id / classes / tool_name
├── _operators.py           ← starts with _ = skipped
├── _panels.py              ← skipped
└── _utils.py               ← skipped
```

`__init__.py`:

```python
from ._operators import ADV_OT_do, ADV_OT_undo
from ._panels import ADV_PT_main

tool_id = "advanced_transform"
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

## 12. Shared Code

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
> disabled, it is unloaded, and cross-module references become stale.

---

## 13. Manual Registration

For external packages, conditional registration, or tests, a public API
is available:

```python
from XNeko_Tools import core

success, reason = core.register_tool_module(module, registry)
```

- `success` is a bool.
- `reason` is one of the `core.REGISTRATION_*` constants:
  - `REGISTRATION_OK` — success
  - `REGISTRATION_MISSING_TOOL_ID`
  - `REGISTRATION_INVALID_TOOL_ID`
  - `REGISTRATION_DUPLICATE_TOOL_ID`

The automatic discovery path uses the same validation rules.

---

## 14. Registration Issues Panel

When a module has a registration problem, the add-on preferences panel
shows a red warning listing the cause and the file path:

- **Missing required `tool_id`** — the module has no `tool_id`.
- **Invalid `tool_id`** — the `tool_id` contains disallowed characters.
- **Tool id collision** — two modules declared the same `tool_id`.
  Both are disabled.

The N-panel shows a compact warning when issues exist. Open the add-on
preferences for details.

Registration issues are detected once when the add-on is enabled. After
editing tool files, use the `Rescan Tools` button to refresh.

---

## 15. Rescan

The `Rescan Tools` button in the add-on preferences re-runs discovery
and icon resolution, and refreshes the registration issue panel.

`Rescan Tools` **does not reimport already loaded Python modules.** If
you change a `classes` tuple or add a new Blender class inside an
already-loaded tool file, cold restart Blender to pick up the change.

---

## 16. Debug Logging

Registration debug logging is off by default. Enable it with the
`Registration Debug Log` toggle in the add-on preferences.

When enabled, the log is written to:

- `<addon>/logs/xneko_tools.log` when the add-on folder is writable
- otherwise, the user config directory under `xneko_tools/logs/`

The log file is truncated when it exceeds 1 MB. Use the `Open Log Folder`
button in the add-on preferences to open the directory directly.

Console output for registration issues is always printed, regardless of
this toggle.

---

## 17. Troubleshooting Checklist

| Symptom | Check |
| ------- | ----- |
| Module does not appear | ① is `tool_id` present? ② does it match `^[a-z0-9_]+$`? ③ is the file name free of a leading `_`? ④ is there a `classes` tuple? ⑤ did the console print `import failed`? ⑥ was the version check rejected? |
| Red warning in add-on preferences | A registration issue exists. Read the listed paths and fix the `tool_id`. |
| Panel appears at the top level instead of under its group | Did you set `bl_parent_id` / `bl_category` manually? |
| Preference widget does not appear | Did you use `layout.prop(prefs, ...)` instead of `prefs.prop(layout, ...)`? |
| Button should be greyed out but is not | Check the conditions under which `poll` returns `False`. |
| Code changes do not take effect | Cold restart Blender, or use `Rescan Tools` for file-level changes only. |
| Preset does not affect a tool | Is the tool installed, compatible, and checked in the Apply dialog? |
| Group icon shows the wrong icon | Check the `group_icon` value and its resolution order in `docs/GROUPS.md`. |

---

## See Also

- [Preset Guide](PRESETS.md) — how presets capture state, and how
  project-embedded preferences work.
- [Group Folder Guide](GROUPS.md) — how group folders and group icons
  work.