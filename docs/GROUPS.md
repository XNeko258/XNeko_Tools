# Group Folder Guide

This guide explains how folders under `tools/` become **groups** in the
N-panel and in the add-on preferences, and how group icons are resolved.

Folder names determine the tab label and the default fallback icon. The
group name no longer affects preset keys: presets are keyed by
`tool_id`, so tools remain portable across folder renames.

---

## 1. Folder Names Are Free

Any folder name under `tools/` is accepted. There is no whitelist.

Recommended naming convention:

- lowercase English letters, digits, and underscores
- a short, meaningful name for the group
- suffix with `_tools` for clarity, e.g. `mesh_tools`, `bone_tools`

Recommended:

```text
tools/mesh_tools/
tools/bone_tools/
tools/object_tools/
```

Also accepted:

```text
tools/mesh/
tools/my_custom_group/
```

Discouraged (still works, but hurts readability and sharing):

```text
tools/aaa/
tools/test1/
tools/temp/
```

Names are not enforced, but they appear as tab labels in the add-on
preferences. Keeping them meaningful helps users and contributors.

---

## 2. How Groups Are Formed

Each folder under `tools/` becomes one group. Multi-level nesting is
supported.

```text
tools/
└── rig/
    ├── bones/
    │   └── rename.py
    ├── constraints/
    │   └── quick_add.py
    └── drivers/
        └── auto_setup.py
```

Resulting tabs:

- `Rig / Bones`
- `Rig / Constraints`
- `Rig / Drivers`

Keep subfolder names short and lowercase.

---

## 3. Group Icons

Each group can define its own icon in the group's `__init__.py`:

```python
group_icon = "MESH_DATA"      # built-in Blender icon name
group_icon = "icon.png"       # image file, relative to the group folder
group_icon = "(^_^)"          # text symbol
group_icon = "🧰"             # emoji
```

### Resolution Order

1. If the value ends with an image extension, it is treated as an image
   file.
2. Otherwise, if the value matches a built-in Blender icon name, it is
   used directly.
3. Otherwise, it is treated as a text symbol and drawn as a label
   prefix.

### Image Files

Supported extensions: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tga`, `.tif`,
`.tiff`, `.webp`.

- Recommended size: 32x32 pixels, square.
- Maximum size: 64x64 pixels. Larger images are rejected and the group
  falls back to the default icon.
- Place the image inside the group folder and reference it by relative
  path, e.g. `group_icon = "icon.png"`.
- Absolute paths also work, but are not recommended for portability.

### Text Symbols

`group_icon` can be an emoji or a kaomoji. Text symbols are drawn as a
label prefix, not as a real icon. Cross-platform rendering depends on
the system UI font and is not guaranteed. For stable display, prefer a
built-in icon name or an image file.

### Fallback

If a group does not define `group_icon`, the framework picks a built-in
icon from `_GROUP_ICON_MAP` in `core.py`, based on keywords found in the
group folder name. If no keyword matches, `FILE_FOLDER` is used.

---

## 4. Creating a Group Folder in Three Steps

### Step 1 — Choose a name

Pick a short, meaningful name for the group. Use lowercase with
underscores if you want a consistent look with built-in examples.

### Step 2 — Create the folder

```text
tools/
└── mesh_tools/          ← new folder
    └── my_tool.py
```

### Step 3 — Write the module

```python
# tools/mesh_tools/my_tool.py
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


classes = (MY_OT_do_something,)
```

Save the file, then cold restart Blender. The group appears in the
N-panel.

To set a group icon, add a `__init__.py` inside the group folder:

```python
# tools/mesh_tools/__init__.py
group_icon = "MESH_DATA"
```

---

## 5. Helper Files

Files or folders starting with `_` are skipped by discovery and can be
used for helper code.

```text
tools/
└── mesh_tools/
    ├── _shared.py            ← skipped, importable
    ├── clean_groups.py
    └── merge_by_distance.py
```

If the helper is used by more than one group, place it under `common/`:

```text
common/
├── math_helpers.py
└── ui_helpers.py
```

Import from a tool:

```python
from ...common import math_helpers
```

> **Do not import one tool module from another.** Modules are unloaded
> when disabled, and cross-references become stale.

---

## 6. Preset Interaction

Presets use `tool_id` as the key, not folder paths. This means:

- moving a tool to a different group does not invalidate presets
- renaming a group folder does not invalidate presets
- two users with different folder layouts can share presets, as long as
  the `tool_id` values match

Group folders still matter for:

- the tab label in the add-on preferences
- the default group icon
- user-facing organization

They no longer matter for preset compatibility.

---

## 7. What Happens If You Get It Wrong

| Situation | Result |
| --- | --- |
| Folder name uses mixed case or hyphens | Works. Only the tab label is affected. |
| Folder name starts with `_` | Entire folder is ignored. |
| Module has no `classes` tuple | File is ignored and can be used as a library. |
| Module has no `tool_id` | Module is skipped and reported in the add-on preferences. |
| Two modules share a `tool_id` | Both modules are disabled and reported. |
| Image icon exceeds 64x64 | Image is rejected, fallback icon is used. |

---

## 8. Fallback Icon Reference

When a group does not define `group_icon`, the framework uses the first
matching keyword from the group folder name. Case-insensitive. First
match wins.

| Keyword | Fallback icon |
| --- | --- |
| `shapekey` / `shape_key` | SHAPEKEY_DATA |
| `bone` | BONE_DATA |
| `armature` | ARMATURE_DATA |
| `pose` | POSE_HLT |
| `rig` | ARMATURE_DATA |
| `constraint` | CONSTRAINT |
| `vertex` | GROUP_VERTEX |
| `mesh` | MESH_DATA |
| `uv` | UV |
| `modifier` | MODIFIER |
| `sculpt` | SCULPTMODE_HLT |
| `object` | OBJECT_DATA |
| `collection` | OUTLINER_COLLECTION |
| `scene` | SCENE_DATA |
| `world` | WORLD_DATA |
| `camera` | CAMERA_DATA |
| `light` | LIGHT |
| `material` | MATERIAL |
| `texture` | TEXTURE_DATA |
| `node` | NODETREE |
| `shader` | NODE_MATERIAL |
| `animation` / `anim` | ANIM_DATA |
| `keyframe` | KEYFRAME_HLT |
| `driver` | DRIVER |
| `curve` | CURVE_DATA |
| `image` | IMAGE_DATA |
| `text` | TEXT |
| `particle` | PARTICLE_DATA |
| `physics` | PHYSICS |
| `hair` | HAIR |
| `grease` | GREASEPENCIL |
| `asset` | ASSET_MANAGER |
| `library` | LIBRARY_DATA_DIRECT |
| `file` | FILE |

The fallback icon is used only when the group does not define its own
`group_icon`.

---

## 9. Adding a New Fallback Keyword

If you want a group name to resolve to a specific fallback icon, add
both the keyword and the icon name to `_GROUP_ICON_MAP` in `core.py`:

```python
_GROUP_ICON_MAP = (
    ...
    ("your_keyword", "YOUR_ICON_NAME"),
)
```

Rules:

- Insert the new entry **before** any broader keyword it might collide
  with. The first match wins.
- The icon name must be a valid Blender icon enum member. Find valid
  names in Blender's Python console:

  ```python
  import bpy
  bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items
  ```

- Cold restart Blender for the change to take effect.
- Update Section 8 of this document so contributors know the keyword
  exists.

Note: this only affects the fallback icon. A group that defines its own
`group_icon` is unaffected.

---

## 10. Pre-Submission Checklist

- [ ] Folder name is lowercase, meaningful, and free of leading `_`
- [ ] The tool file declares `tool_id` matching `^[a-z0-9_]+$`
- [ ] The tool file contains a `classes` tuple
- [ ] `tool_id` is not used by another module
- [ ] The tool's `bl_idname` uses the `xneko.` prefix
- [ ] `bl_category` and `bl_parent_id` are not set manually
- [ ] No cross-imports between tool modules
- [ ] Cold restart Blender and verify the tool appears in the N-panel
- [ ] If a group icon is set, verify its type and size

---

## See Also

- [Development Guide](DEVELOPMENT.md) — full module authoring rules
- [Preset Guide](PRESETS.md) — how presets capture state