# Tool Reference

Why each tool exists, and what it does. One short section per tool.
Authoring rules live in [DEVELOPMENT.md](DEVELOPMENT.md).

---

## Quick Bone Rotate

- **tool_id:** `quick_rotate`

**What it does:** Rotate selected bones around a chosen axis and
pivot, in Pose mode or Edit Armature mode. Batch-edits every
selected bone in one undoable step.

**Why it exists:** Models extracted from games often have bone tails
positioned in ways that do not match the rigging workflow. Fixing
hundreds of bones one at a time in Edit Mode is impractical, so
this tool batch-edits them by a fixed angle around a common pivot.

---

<!-- New tool template:

## Display Name

- **tool_id:** `xxx`

**What it does:**

**Why it exists:**

-->