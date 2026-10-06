# Preset Guide

XNeko Tools can export and import tool preferences as JSON presets. Presets let you back up your configuration, share it with others, switch between different setups, and ship default configurations with the add-on.

---

## Table of Contents

- [1. What Is a Preset?](#1-what-is-a-preset)
- [2. Preset Locations](#2-preset-locations)
- [3. Preset File Format](#3-preset-file-format)
- [4. Interface Operations](#4-interface-operations)
  - [4.1 Export](#41-export)
  - [4.2 Import](#42-import)
  - [4.3 Apply](#43-apply)
  - [4.4 Delete](#44-delete)
  - [4.5 Refresh](#45-refresh)
- [5. Project File Sync](#5-project-file-sync)
  - [5.1 Save Preferences to .blend](#51-save-preferences-to-blend)
  - [5.2 Use Project Preferences](#52-use-project-preferences)
  - [5.3 Status Messages](#53-status-messages)
  - [5.4 Clear](#54-clear)
- [6. Typical Workflows](#6-typical-workflows)
- [7. FAQ](#7-faq)

---

## 1. What Is a Preset?

A preset is a JSON file that records the current values of all tool preference properties. Uses include:

- **Backup** — export before switching computers.
- **Sharing** — send your configuration to a colleague.
- **Switching** — keep separate work and personal configurations.
- **Default startup** — place a preset in the add-on directory to use it as an out-of-the-box default.

---

## 2. Preset Locations

### User-Exported Presets

Presets are stored in the add-on directory first:

```text
XNeko_Tools/presets/*.json
```

If the add-on directory is read-only, for example when installed from an extension platform, the add-on automatically falls back to:

| System | Path |
| --- | --- |
| Windows | `%APPDATA%\Blender Foundation\Blender\4.x\scripts\presets\XNeko_Tools\` |
| Linux | `~/.config/blender/4.x/scripts/presets/XNeko_Tools/` |
| macOS | `~/Library/Application Support/Blender/4.x/scripts/presets/XNeko_Tools/` |

### Built-in Presets

Built-in presets are placed in `XNeko_Tools/presets/*.json` and distributed with the add-on. Users can see and apply them, but they cannot be deleted from the user directory. The current implementation uses a single directory, so built-in presets can also be deleted by users. If this is a concern, manage built-in presets only through git.

To check the actual directory currently in use:

```python
from XNeko_Tools.common import preset_store
print(preset_store.get_preset_dir())
```

---

## 3. Preset File Format

```json
{
  "format": "xneko_prefs",
  "version": 1,
  "name": "Rigging",
  "plugin_version": "0.6.0",
  "blender_version": "4.0.0",
  "tools": {
    "mesh_tools.clean_groups": {
      "__version_min__": [4, 0, 0],
      "__version_max__": null,
      "clean_empty": true,
      "clean_zero_weight": false
    },
    "bone_tools.quick_rotate": {
      "__version_min__": [4, 0, 0],
      "__version_max__": null,
      "angle": 90,
      "use_local_axis": true
    }
  }
}
```

**Field reference:**

| Field | Description |
| --- | --- |
| `format` | Fixed value `"xneko_prefs"`. Used to identify the file type. |
| `version` | Data structure version. Currently `1`. |
| `name` | Preset name. |
| `plugin_version` | Add-on version at export time. |
| `blender_version` | Blender version at export time. |
| `tools` | One key per tool. The value is a dictionary of properties. |
| `__version_min__` / `__version_max__` | Tool version constraints used for compatibility checks. |

**When writing a preset by hand:**

- The key must be the tool short ID, such as `mesh_tools.clean_groups`, without the add-on name prefix.
- Property names must be the names chosen by the module author, such as `clean_empty`, without the `t_xxx_` prefix.
- `format` must be present, otherwise the import will be rejected.

---

## 4. Interface Operations

Open `Edit > Preferences > Add-ons > XNeko Tools` and find the **Presets:** section.

```text
Presets:
[Dropdown ▾]  [✓ Apply]  [🗑 Delete]
[Export]  [Import]  [🔄 Refresh]
```

### 4.1 Export

1. Click **Export**.
2. A naming dialog appears.
3. Enter a name, for example `Rigging`.
4. If a preset with the same name already exists, you will be prompted to overwrite it. Enable the checkbox and confirm.
5. The preset is saved to `presets/Rigging.json`.

### 4.2 Import

1. Click **Import**.
2. In the system file browser, select a `.json` file from any location.
3. If a preset with the same name already exists, a confirmation dialog appears.
4. After confirming, the file is copied into the preset folder.

Importing does **not** change the current settings. It only copies the file into the preset folder. To use it, apply the preset in the next step.

### 4.3 Apply

1. Select the target preset in the dropdown.
2. Click **✓ Apply**.
3. A preview dialog appears:

```text
Preset: Rigging
Plugin: 0.6.0      Blender: 4.0.0

✓ Will apply (3):
  • mesh_tools.clean_groups  (2 settings)
  • bone_tools.quick_rotate  (2 settings)
  • object_tools.align       (1 setting)

⚠ Will skip (1):
  • rig_tools.constraint_helper: Requires Blender 4.3.0+ (current 4.2.0)
```

After confirmation:

- Settings for compatible modules are overwritten.
- Settings for incompatible modules keep their current values.
- Installed modules that are not present in the JSON keep their current values.
- The console prints `Applied N, skipped M`.

### 4.4 Delete

1. Select the target preset in the dropdown.
2. Click **🗑 Delete**.
3. A confirmation dialog appears.
4. After confirming, the file is deleted.

### 4.5 Refresh

If you manually place a new `.json` file in the `presets/` directory, click **🔄 Refresh** to make the dropdown rescan the folder.

---

## 5. Project File Sync

The **Project File:** section controls preferences embedded in `.blend` files.

```text
▸ Project File:                            [🗑]
  ┌──────────────────────────────────────┐
  │ ☐ Save Preferences to .blend         │
  │ ☐ Use Project Preferences            │
  │ ℹ No preferences in this project     │
  └──────────────────────────────────────┘
```

### 5.1 Save Preferences to .blend

When enabled, every time you save the `.blend` file with `Ctrl+S`, the current preferences are written into the project file as a custom property.

**Use case:** package a project together with the preferences it was created with and send it to someone else.

**Side effect:** the `.blend` file becomes slightly larger, typically by a few KB.

### 5.2 Use Project Preferences

When enabled, opening a `.blend` file that contains preferences automatically applies the preferences stored in it.

When disabled, your local preferences are always used, regardless of whose project you open.

**Priority:**

```text
Open .blend
    ↓
Is use_project_prefs enabled?
    ├─ No → Use local preferences
    └─ Yes → Does the .blend contain preference data?
                ├─ Yes → Apply it (skip incompatible modules)
                └─ No  → Use local preferences
```

### 5.3 Status Messages

| Message | Meaning |
| --- | --- |
| ✓ This project carries preferences | The `.blend` file contains preference data. |
| ℹ No preferences in this project | The `.blend` file does not contain preference data. |

### 5.4 Clear

The 🗑 button at the right side of the title row is only clickable when the project actually contains data. Clicking it:

1. Opens a confirmation dialog.
2. Removes the preference data from the `.blend` file.
3. Does **not** affect local preferences.

---

## 6. Typical Workflows

### Scenario A: Personal Use, Switching Configurations Locally

1. Configure a setup and export it as `Rigging`.
2. Change settings and export them as `Animation`.
3. Later, select a preset in the dropdown and apply it.

### Scenario B: Sharing with a Colleague

1. Export `MyConfig` to produce `MyConfig.json`.
2. Send it to your colleague via chat, cloud storage, or email.
3. Your colleague clicks **Import**, selects the file, and clicks **Apply**.

### Scenario C: Project-Specific Configuration

1. Configure all settings inside the project.
2. Enable **Save Preferences to .blend**.
3. Press `Ctrl+S`.
4. Send the `.blend` file to a collaborator.
5. In their Blender:
   - Enable **Use Project Preferences**.
   - Open the `.blend` file.
   - The project configuration is applied automatically.

### Scenario D: Compatibility Across Blender Versions

1. Export a configuration from Blender 4.3 and open it in Blender 4.0.
2. When applying, the preview dialog shows which modules are skipped, for example `Requires Blender 4.3.0+`.
3. Compatible modules are applied as usual. Incompatible modules keep their current values.

---

## 7. FAQ

**Q: I exported a preset but cannot find the file.**

A: Run the following in the console to see the actual path:

```python
from XNeko_Tools.common import preset_store
print(preset_store.get_preset_dir())
```

**Q: Importing a JSON file shows `Not an XNeko preferences file`.**

A: The file is missing the `"format": "xneko_prefs"` field, or it was not exported by this add-on.

**Q: After applying a preset, some tool settings did not change.**

A: There are three possibilities:

1. The module is incompatible with the current Blender version. Check the `Will skip` section in the preview dialog.
2. The JSON file does not contain an entry for that module. Its current value is kept.
3. The module is not installed. It is ignored.

**Q: What happens if project preferences and presets conflict?**

A: `use_project_prefs` has the highest priority. When opening a `.blend` file:

- If enabled, project preferences overwrite all current settings.
- If disabled, nothing is affected, and you can apply presets manually.

**Q: The `.blend` file contains preferences. How do I remove them completely?**

A: Enable **Use Project Preferences**, open the file, click the 🗑 button to the right of `Project File:`, then save the `.blend` file.

**Q: A built-in preset was deleted by the user. How do I restore it?**

A: Run `git pull` again or reinstall the add-on. Alternatively, import it from a backup `.json` file.

**Q: The preset folder is inside the add-on directory. Will presets be lost when the add-on is updated?**

A: If user presets are written to `XNeko_Tools/presets/`, they can be lost when the add-on directory is replaced or reinstalled. It is recommended to export important presets elsewhere as a backup. If the add-on is installed in a read-only directory, such as an extension platform, presets automatically fall back to the user directory and are not affected by add-on updates.

---

## See Also

- [Development Guide](DEVELOPMENT.md) — how to create new tool modules, metadata fields, preferences, lifecycle hooks, and version compatibility.