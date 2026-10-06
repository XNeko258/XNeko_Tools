# Preset Guide

XNeko Tools saves and restores **which modules are enabled**. Presets do not
carry per-tool settings; they only describe the on/off state of every
installed tool.

---

## 1. What a Preset Stores

A preset is a JSON file that records, for every tool:

- whether the tool should be enabled or disabled
- the tool's Blender version bounds, so old presets can be filtered

Per-tool configuration values (`preference_props`) are **not** part of a
preset. If a tool needs parameters that should change with a preset, that
is out of scope for the current format.

---

## 2. Preset Locations

### User presets

Written to the add-on folder when it is writable:

```text
XNeko_Tools/presets/*.json
```

If the add-on is installed from a read-only location (for example, an
extension platform), the add-on falls back to Blender's user resource
directory:

| System  | Path |
| ------- | ---- |
| Windows | `%APPDATA%\Blender Foundation\Blender\4.x\scripts\presets\XNeko_Tools\` |
| Linux   | `~/.config/blender/4.x/scripts/presets/XNeko_Tools/` |
| macOS   | `~/Library/Application Support/Blender/4.x/scripts/presets/XNeko_Tools/` |

### Built-in presets

Built-in presets live in `XNeko_Tools/presets/*.json` and ship with the
add-on. Users can see and apply them. Manage them through git.

To check the directory currently in use:

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
  "blender_version": "4.5.13",
  "tools": {
    "mesh_tools.clean_groups": {
      "__enabled__": true,
      "__version_min__": [4, 0, 0],
      "__version_max__": null
    },
    "bone_tools.quick_rotate": {
      "__enabled__": false,
      "__version_min__": null,
      "__version_max__": null
    }
  }
}
```

**Field reference**

| Field | Description |
| ----- | ----------- |
| `format` | Fixed value `"xneko_prefs"`. Used to identify the file type. |
| `version` | Data structure version. Currently `1`. |
| `name` | Preset name. |
| `plugin_version` | Add-on version at export time. |
| `blender_version` | Blender version at export time. |
| `tools` | One entry per tool, keyed by short id. |
| `tools.<id>.__enabled__` | `true` to enable the tool, `false` to disable it. |
| `tools.<id>.__version_min__` | Lower Blender version bound. Optional. |
| `tools.<id>.__version_max__` | Upper Blender version bound. Optional. |

**Notes on hand-editing**

- The key must be the tool short id (`mesh_tools.clean_groups`), without the
  add-on name prefix.
- `format` must be present. Files without it are rejected on import.

---

## 4. Interface

Open `Edit > Preferences > Add-ons > XNeko Tools` and find the **Presets:**
section.

```text
Presets:
[Dropdown ▾]  [✓ Apply]  [🗑 Delete]
[Export]  [Import]  [🔄 Refresh]
```

### 4.1 Export

1. Click **Export**.
2. Enter a name in the dialog.
3. If a preset with the same name exists, enable **Overwrite** and confirm.
4. The file is saved to `presets/<name>.json`.

### 4.2 Import

1. Click **Import**.
2. Pick any `.json` file.
3. If a preset with the same name already exists, a confirmation dialog
   appears.
4. The file is copied into the preset folder. Current settings are not
   changed by the import itself.

### 4.3 Apply

1. Select a preset from the dropdown.
2. Click **✓ Apply**.
3. A dialog opens showing every tool in the preset:

```text
Preset: Rigging
Plugin: 0.6.0      Blender: 4.5.13

Select modules to apply:
  [✓] Clean Vertex Groups     → enable
  [✓] Quick Rotate            → disable
  [ ] Constraint Helper  (Requires Blender 4.3.0+)
```

- **Enabled / disabled / no change** is shown next to each tool.
- Incompatible tools are greyed out and cannot be selected.
- Use **All** / **None** to toggle the whole list.
- Only checked entries are applied.

4. Click **OK**. The console prints `Applied N, skipped M`.

### 4.4 Delete

1. Select a preset from the dropdown.
2. Click **🗑 Delete**.
3. Confirm.

### 4.5 Refresh

If you drop a new `.json` into the preset folder manually, click **🔄** to
rescan.

---

## 5. Project File Sync

The **Project File:** section controls preferences embedded inside `.blend`
files. Only the enable/disable state of tools is stored.

```text
▸ Project File:                            [🗑]
  ┌──────────────────────────────────────┐
  │ ☐ Save Preferences to .blend         │
  │ ☐ Use Project Preferences            │
  │ ℹ No preferences in this project     │
  └──────────────────────────────────────┘
```

### 5.1 Save Preferences to .blend

When enabled, `Ctrl+S` writes the current tool enable states into the
`.blend` file as a custom property. The file grows by a few KB.

### 5.2 Use Project Preferences

When enabled, opening a `.blend` file that contains preferences applies
them automatically. When disabled, the local configuration is always used.

Priority:

```text
Open .blend
    ↓
use_project_prefs enabled?
    ├─ No  → use local preferences
    └─ Yes → does the .blend carry preferences?
                ├─ Yes → apply them (skip incompatible tools)
                └─ No  → use local preferences
```

### 5.3 Status messages

| Message | Meaning |
| ------- | ------- |
| ✓ This project carries preferences | The `.blend` contains preference data. |
| ℹ No preferences in this project | The `.blend` does not contain preference data. |

### 5.4 Clear

The 🗑 button in the section header is only clickable when the project
actually carries data. Clicking it removes the embedded data without
touching your local preferences.

---

## 6. Typical Workflows

**Switching setups on one machine**
1. Enable the tools you want and export as `Rigging`.
2. Change the selection and export as `Animation`.
3. Pick a preset from the dropdown and click **Apply** to switch.

**Sharing with a colleague**
1. Export `MyConfig` to obtain `MyConfig.json`.
2. Send the file.
3. The recipient clicks **Import**, then **Apply**.

**Project-specific tool set**
1. Enable the tools the project needs.
2. Enable **Save Preferences to .blend** and press `Ctrl+S`.
3. Send the `.blend` file.
4. The recipient enables **Use Project Preferences**, then opens it.

---

## 7. FAQ

**Q: I cannot find the exported file.**
A: Run `from XNeko_Tools.common import preset_store; print(preset_store.get_preset_dir())` in the console to see the actual path.

**Q: Import fails with `Not an XNeko preferences file`.**
A: The JSON is missing `"format": "xneko_prefs"` or was not produced by this add-on.

**Q: Applying a preset does not affect some tools.**
A: Three possibilities:
1. The tool is incompatible with the current Blender version — it is greyed out in the dialog.
2. The tool was unchecked in the dialog.
3. The tool is not installed.

**Q: Project preferences and presets conflict.**
A: `Use Project Preferences` has priority when opening a `.blend`. If it is off, nothing is applied on load and you can use presets freely.

**Q: How do I strip preferences from a `.blend`?**
A: Enable **Use Project Preferences**, open the file, click the 🗑 next to `Project File:`, then save the `.blend`.

**Q: Will presets be lost when the add-on is updated?**
A: Presets stored in `XNeko_Tools/presets/` can be lost if the add-on folder is replaced. Export important presets elsewhere as a backup.