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

---

<!-- New tool template:

## Display Name

- **tool_id:** `xxx`

**What it does:**

**Why it exists:**

-->