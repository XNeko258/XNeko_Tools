# XNeko Tools

A modular Blender add-on framework for building and managing focused tool
sets with shared preferences and portable presets.

XNeko Tools provides a lightweight module system for Blender. Each tool
lives in its own file or package, declares a unique `tool_id`, and
registers its own operators and panels. The framework handles discovery,
registration, presets, group icons, and conflict reporting.

Target audience: add-on developers. Users are expected to write or install
tool modules, not just consume a fixed tool set.

## Features

- Modular tool discovery: drop a `.py` file or package under `tools/` and
  it becomes a tool group.
- Automatic registration of operators, panels, preferences, and scene
  properties.
- Required `tool_id` per module, with collision detection and a visible
  registration issue panel.
- Per-tool preference properties with optional custom UI.
- Preset system: export, import, and apply JSON presets.
- Per-tool `preference_props` values are captured by presets.
  `scene_props` values are never touched by presets.
- Project preferences: save and apply preference state inside `.blend`
  files.
- Group icons: built-in Blender icon name, image file, or text symbol
  (emoji / kaomoji).
- Blender version compatibility checks per tool.
- Lifecycle hooks for timers, handlers, and cleanup.
- `Hot Reload Tools` button: reloads tool modules from disk, rebuilds
  the dynamic preferences class, and preserves the current UI and
  enabled state. Editing a tool's `.py` file no longer requires a
  restart.
- Automatic session persistence: tool enable flags and per-tool
  preference values survive restarts without a manual save.
- Two-channel error reporting: optional tool reports in
  `logs/reports/`, always-on critical reports in `logs/critical/`.
- Shared code under `common/` for cross-tool utilities.

## Requirements

- Blender 4.0 or newer.
- Individual tools may declare stricter version ranges.

## Installation

### From a release ZIP

1. Download the latest `XNeko_Tools.zip` from the Releases page.
2. Open Blender.
3. Go to `Edit > Preferences > Add-ons`.
4. Click `Install from Disk...` or `Install...` depending on your
   Blender version.
5. Select the ZIP file.
6. Enable `XNeko Tools` in the add-on list.
7. Restart Blender after installation or updates.

### From source

1. Clone this repository into your Blender add-ons directory, or install
   it as a ZIP.
2. Make sure the folder is named `XNeko_Tools`.
3. Restart Blender.
4. Enable `XNeko Tools` in `Edit > Preferences > Add-ons`.

> Cold restart Blender after changing framework code (`core.py`,
> `preferences.py`, `common/*`). Edits under `tools/` can be applied
> with `Hot Reload Tools`.

## Quick Start

1. Open the 3D Viewport.
2. Press `N` to open the sidebar.
3. Find the `XNeko Tools` tab.
4. Open a tool group and use the available operators.
5. Open `Edit > Preferences > Add-ons > XNeko Tools` to configure tools
   and manage presets.

If the add-on preferences show a red warning at the top, one or more tool
modules have a registration problem. See `docs/DEVELOPMENT.md` for the
cause and fix.

## Documentation

- [Development Guide](docs/DEVELOPMENT.md) — how to write tool modules,
  metadata fields, `tool_id` rules, group icons, error reporting, and
  version compatibility.
- [Preset Guide](docs/PRESETS.md) — how to export, import, and apply
  presets, how preference values are captured, and how project-embedded
  preferences work.
- [Group Folder Guide](docs/GROUPS.md) — how group folders are named,
  how group icons are resolved, and how presets interact with group
  structure.

## Project Structure

```text
XNeko_Tools/
├── __init__.py
├── core.py
├── preferences.py
├── common/
│   ├── __init__.py
│   ├── error_reports.py
│   ├── icon_store.py
│   ├── prefs_io.py
│   ├── preset_store.py
│   └── session_store.py
├── logs/                       ← created on first report write
│   ├── reports/
│   └── critical/
├── presets/                    ← legacy, read-only
│   └── *.json
└── tools/
    ├── mesh_tools/
    │   └── clean_groups.py
    ├── bone_tools/
    │   └── quick_rotate.py
    └── object_tools/
        └── advanced_transform/
            ├── __init__.py
            ├── _operators.py
            └── _panels.py
```

## Creating a Tool

A minimal tool module looks like this:

```python
import bpy

tool_id = "my_tool"
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

Save the file under `tools/<group>/<tool_name>.py`, then either cold
restart Blender or click `Hot Reload Tools` in the add-on preferences.
The tool appears in the N-panel.

`tool_id` is required. Modules without it are skipped and reported.

See the [Development Guide](docs/DEVELOPMENT.md) for the full metadata
reference.

## Presets

XNeko Tools can export and import tool state as JSON presets. Presets
capture, per tool:

- the enabled / disabled state
- the values of `preference_props`

Presets never touch `scene_props`. Those describe the current operation
and are tied to the project, not the user's configuration.

New presets are always written to Blender's user preset directory:

| System  | Path |
| ------- | ---- |
| Windows | `%APPDATA%\Blender Foundation\Blender\4.x\scripts\presets\XNeko_Tools\` |
| Linux   | `~/.config/blender/4.x/scripts/presets/XNeko_Tools/` |
| macOS   | `~/Library/Application Support/Blender/4.x/scripts/presets/XNeko_Tools/` |

The add-on's own `presets/` folder is still scanned as a legacy
source, so presets written by earlier versions remain readable and
deletable. New presets are never written there.

Use the `Presets:` section in `Edit > Preferences > Add-ons > XNeko Tools`
to export, import, apply, delete, or refresh presets.

See the [Preset Guide](docs/PRESETS.md) for the file format and
workflows.

## Project Preferences

You can save the current preference state inside a `.blend` file and
optionally apply it when opening that file.

- `Save Preferences to .blend` writes preferences into the project file.
- `Use Project Preferences` applies preferences stored in the project
  file when the file is opened.

Project preferences have the highest priority when enabled. Only
`preference_props` values are stored; `scene_props` remain per-scene as
usual.

## Session State

Tool enable flags and per-tool preference values are written
automatically to a session file under the user config directory:

    <config>/xneko_tools/session.json

This happens on every toggle change and every preference edit. On
startup, the session state is applied after defaults and before
project preferences. You do not need to save preferences manually
for tool state to survive a restart.

The session file is overwritten on the next state change. To clear
it entirely, delete the file.

## Error Reporting

Two channels:

- **Tool Reports** — optional. Written to `logs/reports/` when
  `Enable Error Reporting` is on in the add-on preferences. Covers
  tool-module failures: import errors, invalid declarations, dropped
  preference properties, panel attach errors.
- **Critical Reports** — always on. Written to `logs/critical/`.
  Reserved for the add-on's own infrastructure failures. Cannot be
  disabled; the user toggle never suppresses them.

Each directory keeps the newest 10 files. The add-on folder is used
when writable; otherwise the log root falls back to the user config
directory under `xneko_tools/logs/`.

Use `Open Tool Reports` / `Open Critical Reports` in the add-on
preferences to open either folder, and `Clear` to empty it.

## Compatibility

- Base add-on: Blender 4.0+.
- Individual tools can declare `blender_version_min` and
  `blender_version_max`.
- Incompatible tools are disabled and skipped during preset application.

## Contributing

Issues and pull requests are welcome. For larger changes, please open an
issue first to discuss the design.

## License

See the `LICENSE` file in this repository.

## Credits

Created and maintained by the XNeko Tools contributors.