# XNeko Tools

A modular Blender add-on framework for building and managing small, focused tools with shared preferences and portable presets.

XNeko Tools provides a lightweight module system for Blender. Each tool lives in its own file or package, registers its own operators and panels, and automatically appears in the N-panel and add-on preferences. Tools can define their own preferences, scene properties, lifecycle hooks, and version constraints. A built-in preset system lets you export, import, share, and apply tool configurations, including project-embedded preferences stored inside `.blend` files.

## Features

- Modular tool discovery: drop a `.py` file or package under `tools/` and it becomes a tool group.
- Automatic registration of operators, panels, preferences, and scene properties.
- Per-tool preference properties with optional custom UI.
- Preset system: export, import, apply, and share JSON presets.
- Project preferences: save and apply preferences inside `.blend` files.
- Blender version compatibility checks per tool.
- Lifecycle hooks for timers, handlers, and cleanup.
- Shared code under `common/` for cross-tool utilities.

## Requirements

- Blender 4.0 or newer.
- Individual tools may declare stricter version ranges.

## Installation

### From a release ZIP

1. Download the latest `XNeko_Tools.zip` from the Releases page.
2. Open Blender.
3. Go to `Edit > Preferences > Add-ons`.
4. Click `Install from Disk...` or `Install...` depending on your Blender version.
5. Select the ZIP file.
6. Enable `XNeko Tools` in the add-on list.
7. Restart Blender after installation or updates.

### From source

1. Clone this repository into your Blender add-ons directory, or install it as a ZIP.
2. Make sure the folder is named `XNeko_Tools`.
3. Restart Blender.
4. Enable `XNeko Tools` in `Edit > Preferences > Add-ons`.

> Cold restart Blender after changing add-on code. Reloading scripts with `F8` is not enough for module changes.

## Quick Start

1. Open the 3D Viewport.
2. Press `N` to open the sidebar.
3. Find the `XNeko Tools` tab.
4. Open a tool group and use the available operators.
5. Open `Edit > Preferences > Add-ons > XNeko Tools` to configure tools and manage presets.

## Documentation

- [Development Guide](docs/DEVELOPMENT.md) — how to create new tool modules, metadata fields, preferences, lifecycle hooks, and version compatibility.
- [Preset Guide](docs/PRESETS.md) — how to export, import, apply, and share presets, and how project-embedded preferences work.
- [Group Folder Guide](docs/GROUPS.md) — how to name folders under `tools/`, which folder names are allowed, and how icons are chosen.

## Project Structure

```text
XNeko_Tools/
├── __init__.py
├── core.py
├── preferences.py
├── common/
│   ├── __init__.py
│   ├── prefs_io.py
│   └── preset_store.py
├── presets/
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

Save the file under `tools/<group>/<tool_name>.py`, then cold restart Blender. The tool will appear in the N-panel.

See the [Development Guide](docs/DEVELOPMENT.md) for the full metadata reference.

## Presets

XNeko Tools can export and import tool preferences as JSON presets. Presets are stored in `XNeko_Tools/presets/` when the add-on directory is writable, otherwise they fall back to Blender's user presets directory.

Use the `Presets:` section in `Edit > Preferences > Add-ons > XNeko Tools` to:

- Export the current configuration.
- Import a preset from any location.
- Apply a preset with a compatibility preview.
- Delete or refresh presets.

See the [Preset Guide](docs/PRESETS.md) for file format and workflows.

## Project Preferences

You can save the current tool preferences inside a `.blend` file and optionally apply them when opening that file.

- `Save Preferences to .blend` writes preferences into the project file.
- `Use Project Preferences` applies preferences stored in the project file.

Project preferences have the highest priority when enabled.

## Compatibility

- Base add-on: Blender 4.0+.
- Individual tools can declare `blender_version_min` and `blender_version_max`.
- Incompatible tools are disabled and skipped during preset application.

## Contributing

Issues and pull requests are welcome. For larger changes, please open an issue first to discuss the design.

## License

See the `LICENSE` file in this repository.

## Credits

Created and maintained by the XNeko Tools contributors.