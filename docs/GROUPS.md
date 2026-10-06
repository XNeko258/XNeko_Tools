# Group Folder Guide

This guide explains how to create folders under `tools/` for XNeko Tools. Every folder becomes a **group** in the N-panel and in the add-on preferences. The folder name determines the tab label, the icon, and the preset key used for sharing configurations.

---

## 1. One-Line Rule

Each folder under `tools/` must be named after a **keyword** from the table in Section 2, optionally followed by `_tools`.

Both forms are equivalent:

- `mesh_tools` — recommended
- `mesh` — also accepted

These are **not** allowed:

- `meshes`
- `meshTools`
- `mesh-tools`
- `my_mesh_tools`

---

## 2. Allowed Folder Names

The following keywords are recognised. Use one of them as the top-level folder name under `tools/`.

| Keyword | Icon | Typical use |
| --- | --- | --- |
| `shapekey` / `shape_key` | SHAPEKEY_DATA | Shape key tools |
| `bone` | BONE_DATA | Bone tools |
| `armature` | ARMATURE_DATA | Armature tools |
| `pose` | POSE_HLT | Pose mode tools |
| `rig` | ARMATURE_DATA | Rigging tools |
| `constraint` | CONSTRAINT | Constraint tools |
| `vertex` | GROUP_VERTEX | Vertex group tools |
| `mesh` | MESH_DATA | Mesh tools |
| `uv` | UV | UV tools |
| `modifier` | MODIFIER | Modifier tools |
| `sculpt` | SCULPTMODE_HLT | Sculpt tools |
| `object` | OBJECT_DATA | Object tools |
| `collection` | OUTLINER_COLLECTION | Collection tools |
| `scene` | SCENE_DATA | Scene tools |
| `world` | WORLD_DATA | World tools |
| `camera` | CAMERA_DATA | Camera tools |
| `light` | LIGHT | Light tools |
| `material` | MATERIAL | Material tools |
| `texture` | TEXTURE_DATA | Texture tools |
| `node` | NODETREE | Node tree tools |
| `shader` | NODE_MATERIAL | Shader tools |
| `animation` / `anim` | ANIM_DATA | Animation tools |
| `keyframe` | KEYFRAME_HLT | Keyframe tools |
| `driver` | DRIVER | Driver tools |
| `curve` | CURVE_DATA | Curve tools |
| `image` | IMAGE_DATA | Image tools |
| `text` | TEXT | Text tools |
| `particle` | PARTICLE_DATA | Particle tools |
| `physics` | PHYSICS | Physics tools |
| `hair` | HAIR | Hair tools |
| `grease` | GREASEPENCIL | Grease pencil tools |
| `asset` | ASSET_MANAGER | Asset tools |
| `library` | LIBRARY_DATA_DIRECT | Library tools |
| `file` | FILE | File tools |

If the folder name does not match any keyword, the tool still loads, but:

- the console prints an unknown-group warning
- the group icon falls back to `FILE_FOLDER`
- the preset key becomes unpredictable

---

## 3. Why a Whitelist Matters

Presets use the folder path as a key. For example:

```json
{
  "tools": {
    "mesh_tools.clean_groups": { "__enabled__": true },
    "bone_tools.quick_rotate": { "__enabled__": true }
  }
}
```

- If you use `mesh_tools/` and another contributor also uses `mesh_tools/`, presets can be shared.
- If you use `meshes/` and they use `mesh_tools/`, the keys do not match. After sharing, tools appear as "not installed".

Folder names are therefore a compatibility concern, not just a style choice.

---

## 4. Creating a Group Folder in Three Steps

### Step 1 — Choose a keyword

Pick the keyword from Section 2 that best matches the tool's purpose.

**Decision order:**

1. Does the tool work on a specific data type? → use the matching `*_tools` folder (e.g. `bone_tools`).
2. Does it operate at the object or scene level? → `object_tools` or `scene_tools`.
3. Is it related to rendering or nodes? → `node_tools`, `shader_tools`, or `material_tools`.

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

Save the file, then **cold restart Blender**. A `Mesh Tools` group appears in the N-panel with the mesh icon.

---

## 5. Nested Folders

If a group grows large, you may add subfolders. Only the **first** folder under `tools/` must match the whitelist.

```text
tools/
└── rig_tools/
    ├── bones/
    │   └── rename.py
    ├── constraints/
    │   └── quick_add.py
    └── drivers/
        └── auto_setup.py
```

Resulting tabs:

- `Rig Tools / Bones`
- `Rig Tools / Constraints`
- `Rig Tools / Drivers`

Keep subfolder names short and lowercase.

---

## 6. Helper Files

Files or folders starting with `_` are skipped by discovery and can be used for helper code.

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

> **Do not import one tool module from another.** Modules are unloaded when disabled, and cross-references become stale.

---

## 7. What Happens If You Get It Wrong

| Situation | Result |
| --- | --- |
| Folder name not in the whitelist | Console warning, generic folder icon, unpredictable preset key |
| Folder name starts with `_` | Entire folder is ignored |
| Module has no `classes` tuple | File is ignored and can be used as a library |
| Folder name contains uppercase or hyphens | No error, but the group id contains hyphens and preset keys become hard to align |

---

## 8. Quick Reference

```text
Goal                              Folder to use
───────────────────────────────   ────────────────────
Rename bones / edit hierarchy     bone_tools
Edit shape keys                   shapekey_tools
Edit vertex group weights         vertex_tools
Edit mesh topology                mesh_tools
Edit UVs                          uv_tools
Add / remove modifiers            modifier_tools
Edit object transforms            object_tools
Edit collections                  collection_tools
Edit scene settings               scene_tools
Edit lights                       light_tools
Edit cameras                      camera_tools
Edit materials                    material_tools
Edit node trees                   node_tools
Edit animation / keyframes        animation_tools
Edit drivers                      driver_tools
Edit constraints                  constraint_tools
```

---

## 9. Adding a New Keyword

If you genuinely need a group that is not covered by the table, add both the keyword and the icon to `_GROUP_ICON_MAP` in `core.py`.

```python
_GROUP_ICON_MAP = (
    ...
    ("your_keyword", "YOUR_ICON_NAME"),
)
```

Rules:

- Insert the new entry **before** any broader keyword it might collide with. The first match wins.
- The icon name must be a valid Blender icon enum member. Find valid names in Blender's Python console:

  ```python
  import bpy
  bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items
  ```

- Cold restart Blender for the change to take effect.
- Update Section 2 of this document so other contributors know the new group exists.

---

## 10. Pre-Submission Checklist

- [ ] Folder name is in the whitelist and spelled correctly (lowercase with underscores)
- [ ] Folder name ends with `_tools` (recommended) or is a bare keyword
- [ ] The tool file contains a `classes` tuple
- [ ] The tool's `bl_idname` uses the `xneko.` prefix
- [ ] `bl_category` and `bl_parent_id` are not set manually
- [ ] No cross-imports between tool modules
- [ ] Cold restart Blender and verify the tool appears in the N-panel
- [ ] If a new keyword was added, `_GROUP_ICON_MAP` was updated and this document was updated

---

## See Also

- [Development Guide](DEVELOPMENT.md) — full module authoring rules
- [Preset Guide](PRESETS.md) — how presets use folder paths as keys
