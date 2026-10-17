# Tool Reference

Why each tool exists, and what it does. One short section per tool.
Authoring rules live in [DEVELOPMENT.md](DEVELOPMENT.md).

---

## Quick Bone Rotate

- **tool_id:** `quick_rotate`
- **What it does:** Rotate selected bones around a chosen axis and
pivot, in Pose mode or Edit Armature mode. Batch-edits every
selected bone in one undoable step.
- **Why it exists:** Models extracted from games often have bone tails
positioned in ways that do not match the rigging workflow. Fixing
hundreds of bones one at a time in Edit Mode is impractical, so
this tool batch-edits them by a fixed angle around a common pivot.

## Clean Vertex Groups

- **tool_id**: `clean_groups`
- **What it does**:
  Removes unused vertex groups from mesh objects. Empty groups are
  always cleaned; check `Zero-Weight Groups` to also remove groups
  whose vertices all have weight 0. Groups referenced by modifiers
  or shape keys are kept.
- **Why it exists**:
  Merged and imported meshes pile up dead vertex groups. This clears
  them in one click, without breaking deform setups.

## Vertex Group to Bones

- **tool_id**: `vertex_group_to_bones`
- **What it does**:
  Creates one bone per selected vertex group, at the weighted
  centroid of its high-weight vertices. Groups matching an
  existing bone name are hidden.
- **Why it exists**:
  Imported meshes often carry vertex groups but no matching
  armature. This rebuilds the skeleton directly from the weights.

## Sync Data Names

- **tool_id**: `sync_names`
- **What it does**:
  Renames each selected object's data block to match the object name.
  Shape key data is renamed too, so the whole chain stays consistent.
- **Why it exists**:
  Duplicated objects often keep stale data names, which is confusing
  in the outliner and in exports. This aligns them in one click.

## Rename Modifiers

- **tool_id**: `rename_modifiers`
- **What it does**:
  Batch-renames modifiers on selected objects. Armature, Hook, and
  Mask modifiers can follow their target object or vertex group;
  Geometry Nodes modifiers can follow their node group. Other types
  use a default label. A custom name overrides all.
- **Why it exists**:
  Many modifiers with inconsistent names are hard to scan. This
  normalizes them in one click.

## Swap Shape Key with Basis

- **tool_id**: `apply_to_basis`
- **What it does**:
  Exchanges the active shape key with the basis: coordinates and
  names are swapped, and every key value is reset to 0. Mesh
  vertices are updated to match the new basis so future keys start
  from the correct shape.
- **Why it exists**:
  Blender cannot reorder shape keys, so promoting a key to the basis
  normally means deleting and recreating them by hand. This swaps
  them in place in one click. Inspired by the "Apply Selected
  Shapekey to Basis" feature from
  [Cats Blender Plugin](https://github.com/teamneoneko/Cats-Blender-Plugin).

## Rig Prep

- **tool_id**: `rig_prep`
- **What it does**:
  Extracts a deform-only armature from a source armature. Bones are
  kept if their name matches a vertex group on a reference mesh;
  parent chains skip dropped control bones. Rest pose, connect
  flags, and object transform are preserved.
- **Why it exists**:
  Game-ripped armatures ship with many controller bones that do not
  deform anything. This extracts a clean deform skeleton in one
  click, without touching the original rig.

## Shape Key Plus

- **tool_id:** `shape_key_plus`
- **What it does:** Adds GRIP handles, multi-select, batch remove /
  lock / mute, an R/L rename suite, and a mouse-wheel reorder mode to
  the built-in Shape Keys panel.
- **Why it exists:** Large shape-key sets are impractical to manage one
  key at a time in the stock panel.

## Vertex Groups Plus

- **tool_id:** `vertex_groups_plus`
- **What it does:** Brings the same batch-select, batch remove / lock,
  R/L rename, and reorder workflow to the built-in Vertex Groups panel.
- **Why it exists:** Vertex-group management hits the same bottleneck
  once a rig has more than a handful of groups.

## Driver Cleaner

- **tool_id:** `driver_cleaner`
- **What it does:** Lists invalid and duplicate drivers on selected objects only — object itself, 
  its data, shape keys / key blocks, bones, pose bones, and materials. 
  Each problem item can be checked individually, or cleaned by category with **Clean All Invalid** / **Clean All Dup**. 
  Duplicate detection uses `(data_path, array_index, expression)` as the signature and keeps the first driver.
- **Why it exists:** Edited armatures often carry dead and duplicated drivers that cause heavy viewport lag. 
  This tool finds and clears them on the selection in one click, without touching unrelated data.

## Quick Eye Bone

- **tool_id:** `quick_eye_bone`

- **What it does:**
One-click modal placement to instantly generate a complete eye rig.
- - **Symmetry & Snapping:** Live X/Y mirroring with native Blender snapping (Vertex/Edge/Face) and `Ctrl` override.
- - **Full Hierarchy:** Creates deform bones, side controls, a master control, and an optional pupil bone.
- - **Auto-Collections:** Automatically groups bones into nested collections (`Quick Eye Rig` > `Eye` / `Eye Control`).
- - **Customizable:** Adjust names, handle sizes, marker colors, and snap sensitivity in preferences.
- **Why it exists:**
To eliminate tedious manual eye rigging. Inspired by the **Auto-Rig Pro (ARP) Smart** marker system, it turns a multi-step setup into a single, fluid click.

---

<!-- New tool template:

## Display Name

- **tool_id:** `xxx`

**What it does:**

**Why it exists:**

-->