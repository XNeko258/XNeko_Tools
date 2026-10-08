"""XNeko Tools - Shape Key Linker module."""

import bpy


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "shape_key_linker"
tool_name = "Shape Key Linker"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Helpers
# ============================================================
def _is_mesh_with_keys(obj):
    """Return True if obj is a mesh object with shape keys."""
    return (
        obj is not None
        and obj.type == 'MESH'
        and obj.data is not None
        and obj.data.shape_keys is not None
    )


def _poll_mesh_with_keys(self, obj):
    """Poll callback for PointerProperty."""
    return _is_mesh_with_keys(obj)


def _escape_key_name(name):
    """Escape a shape key name for use inside a data path string."""
    return name.replace('\\', '\\\\').replace('"', '\\"')


def _starts_with_symbol(name):
    """Return True if the name starts with a non-alphanumeric symbol."""
    if not name:
        return False
    return not name[0].isalnum()


def _build_driver_index(tgt):
    """Return {data_path: fcurve} for tgt's shape key drivers."""
    index = {}
    if tgt is None or tgt.data is None:
        return index
    if not tgt.data.shape_keys:
        return index
    anim = tgt.data.shape_keys.animation_data
    if anim is None:
        return index
    for fcurve in anim.drivers:
        index[fcurve.data_path] = fcurve
    return index


def _is_mirror_driver(src, fcurve, key_name):
    """Return True if fcurve is our mirror driver for key_name."""
    if fcurve is None:
        return False

    safe_name = _escape_key_name(key_name)
    expected_path = f'key_blocks["{safe_name}"].value'
    if fcurve.data_path != expected_path:
        return False

    driver = fcurve.driver
    if driver.type != 'SCRIPTED':
        return False
    if driver.expression != "src_val":
        return False
    if len(driver.variables) != 1:
        return False

    var = driver.variables[0]
    if var.name != "src_val" or var.type != 'SINGLE_PROP':
        return False
    if len(var.targets) != 1:
        return False

    target = var.targets[0]
    if target.id_type != 'OBJECT':
        return False
    if target.id is not src:
        return False

    expected_src = (
        f'data.shape_keys.key_blocks["{safe_name}"].value'
    )
    if target.data_path != expected_src:
        return False

    return True


def _count_pending(src, tgt, skip_symbols):
    """Count keys that need any action (link or cleanup)."""
    if tgt is None or tgt is src:
        return 0
    if tgt.data is None or not tgt.data.shape_keys:
        return 0
    if src.data is None or not src.data.shape_keys:
        return 0

    src_names = {k.name for k in src.data.shape_keys.key_blocks}
    driver_index = _build_driver_index(tgt)
    count = 0

    for i, tgt_key in enumerate(tgt.data.shape_keys.key_blocks):
        if i == 0:
            continue

        safe_name = _escape_key_name(tgt_key.name)
        path = f'key_blocks["{safe_name}"].value'
        existing = driver_index.get(path)
        is_mirror = _is_mirror_driver(src, existing, tgt_key.name)

        if skip_symbols and _starts_with_symbol(tgt_key.name):
            if is_mirror:
                count += 1
            continue

        if tgt_key.name not in src_names:
            continue
        if is_mirror:
            continue

        count += 1

    return count


def _link_one(src, tgt, skip_symbols=True):
    """Add or refresh mirror drivers on tgt's shape keys.

    Returns (linked, skipped, symbol_ignored, already_ok, cleaned).
    """
    if tgt is None or tgt is src:
        return 0, 0, 0, 0, 0
    if tgt.data is None or not tgt.data.shape_keys:
        return 0, 0, 0, 0, 0

    src_names = {k.name for k in src.data.shape_keys.key_blocks}
    driver_index = _build_driver_index(tgt)

    linked = 0
    skipped = 0
    symbol_ignored = 0
    already_ok = 0
    cleaned = 0

    for i, tgt_key in enumerate(tgt.data.shape_keys.key_blocks):
        if i == 0:
            continue

        safe_name = _escape_key_name(tgt_key.name)
        path = f'key_blocks["{safe_name}"].value'
        existing = driver_index.get(path)
        is_mirror = _is_mirror_driver(src, existing, tgt_key.name)

        if skip_symbols and _starts_with_symbol(tgt_key.name):
            if is_mirror:
                try:
                    tgt_key.driver_remove("value")
                    cleaned += 1
                except Exception:
                    pass
            symbol_ignored += 1
            continue

        if tgt_key.name not in src_names:
            skipped += 1
            continue

        if is_mirror:
            already_ok += 1
            continue

        try:
            tgt_key.driver_remove("value")
        except Exception:
            pass

        try:
            fcurve = tgt_key.driver_add("value")
        except Exception as e:
            print(
                f"[Shape Key Linker] driver_add failed on "
                f"'{tgt_key.name}': {e}"
            )
            skipped += 1
            continue

        driver = fcurve.driver
        driver.type = 'SCRIPTED'

        var = driver.variables.new()
        var.name = "src_val"
        var.type = 'SINGLE_PROP'

        target = var.targets[0]
        target.id_type = 'OBJECT'
        target.id = src
        target.data_path = (
            f'data.shape_keys.key_blocks["{safe_name}"].value'
        )

        driver.expression = "src_val"
        linked += 1

    return linked, skipped, symbol_ignored, already_ok, cleaned


# ============================================================
# PropertyGroup
# ============================================================
class XNEKO_PG_sk_target(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(
        name="Object",
        description="Target object to mirror the source shape keys",
        type=bpy.types.Object,
        poll=_poll_mesh_with_keys,
    )


# ============================================================
# UIList
# ============================================================
class XNEKO_UL_sk_targets(bpy.types.UIList):
    bl_idname = "XNEKO_UL_sk_targets"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        if item.object is None:
            layout.label(text=f"{index + 1}. (empty)", icon='ERROR')
        else:
            layout.label(
                text=f"{index + 1}. {item.object.name}",
                icon='OBJECT_DATA',
            )


# ============================================================
# Operators
# ============================================================
class XNEKO_OT_sk_add_target(bpy.types.Operator):
    bl_idname = "xneko.sk_add_target"
    bl_label = "Add Target"
    bl_description = (
        "Add every selected mesh object with shape keys to the list. "
        "Objects already in the list, the source object, and meshes "
        "without shape keys are skipped"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        src = scene.xneko_sk_source
        existing = {item.object for item in scene.xneko_sk_targets}

        for obj in context.selected_objects:
            if obj is None or obj is src:
                continue
            if not _is_mesh_with_keys(obj):
                continue
            if obj in existing:
                continue
            return True
        return False

    def execute(self, context):
        scene = context.scene
        src = scene.xneko_sk_source
        existing = {item.object for item in scene.xneko_sk_targets}

        added = 0
        for obj in context.selected_objects:
            if obj is None or obj is src:
                continue
            if not _is_mesh_with_keys(obj):
                continue
            if obj in existing:
                continue
            item = scene.xneko_sk_targets.add()
            item.object = obj
            existing.add(obj)
            added += 1

        scene.xneko_sk_target_index = len(scene.xneko_sk_targets) - 1
        self.report({'INFO'}, f"Added {added} target(s)")
        return {'FINISHED'}


class XNEKO_OT_sk_remove_target(bpy.types.Operator):
    bl_idname = "xneko.sk_remove_target"
    bl_label = "Remove Target"
    bl_description = "Remove the currently selected target from the list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        idx = scene.xneko_sk_target_index
        return 0 <= idx < len(scene.xneko_sk_targets)

    def execute(self, context):
        scene = context.scene
        idx = scene.xneko_sk_target_index

        scene.xneko_sk_targets.remove(idx)

        if len(scene.xneko_sk_targets) == 0:
            scene.xneko_sk_target_index = 0
        else:
            scene.xneko_sk_target_index = min(
                idx, len(scene.xneko_sk_targets) - 1
            )
        return {'FINISHED'}


class XNEKO_OT_sk_clear_targets(bpy.types.Operator):
    bl_idname = "xneko.sk_clear_targets"
    bl_label = "Clear Targets"
    bl_description = "Remove all targets from the list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.xneko_sk_targets) > 0

    def execute(self, context):
        context.scene.xneko_sk_targets.clear()
        context.scene.xneko_sk_target_index = 0
        context.scene.xneko_sk_status = "Target list cleared"
        return {'FINISHED'}


class XNEKO_OT_sk_link(bpy.types.Operator):
    bl_idname = "xneko.sk_link"
    bl_label = "Link All Targets"
    bl_description = (
        "Add drivers to every target so their same-name shape keys "
        "mirror the source in real time. Keys that are already linked "
        "are left untouched, and stale mirror drivers on symbol-prefixed "
        "keys are removed"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        scene = context.scene

        if not _is_mesh_with_keys(scene.xneko_sk_source):
            return False

        if len(scene.xneko_sk_targets) == 0:
            return False

        for item in scene.xneko_sk_targets:
            tgt = item.object
            if (tgt is not None
                    and tgt is not scene.xneko_sk_source
                    and _is_mesh_with_keys(tgt)):
                return True

        return False

    def execute(self, context):
        scene = context.scene
        src = scene.xneko_sk_source
        skip_symbols = scene.xneko_sk_skip_symbols

        planned_total = 0
        for item in scene.xneko_sk_targets:
            planned_total += _count_pending(
                src, item.object, skip_symbols
            )

        if planned_total == 0:
            scene.xneko_sk_status = "Already up to date, no changes made"
            self.report({'INFO'}, scene.xneko_sk_status)
            return {'FINISHED'}

        try:
            bpy.ops.ed.undo_push(message="Shape Key Link")
        except Exception as e:
            print(f"[Shape Key Linker] undo_push failed: {e}")

        total_linked = 0
        total_skipped = 0
        total_symbol_ignored = 0
        total_already_ok = 0
        total_cleaned = 0
        targets_processed = 0

        for item in scene.xneko_sk_targets:
            tgt = item.object
            if tgt is None or tgt is src:
                continue
            if not _is_mesh_with_keys(tgt):
                continue

            linked, skipped, symbol_ignored, already_ok, cleaned = \
                _link_one(src, tgt, skip_symbols=skip_symbols)

            if linked > 0 or cleaned > 0:
                if tgt.data is not None:
                    tgt.data.update_tag()

            if linked > 0 or skipped > 0 or symbol_ignored > 0:
                targets_processed += 1

            total_linked += linked
            total_skipped += skipped
            total_symbol_ignored += symbol_ignored
            total_already_ok += already_ok
            total_cleaned += cleaned

        msg = (
            f"Linked {total_linked} key(s) "
            f"across {targets_processed} target(s)"
        )
        if total_already_ok:
            msg += f", {total_already_ok} already linked"
        if total_cleaned:
            msg += f", cleaned {total_cleaned} stale"
        if total_skipped:
            msg += f", skipped {total_skipped}"
        if total_symbol_ignored:
            msg += f", ignored {total_symbol_ignored} symbolic"

        if scene.xneko_sk_clear_after_link and total_linked > 0:
            scene.xneko_sk_targets.clear()
            scene.xneko_sk_target_index = 0
            msg += " | list cleared"

        scene.xneko_sk_status = msg
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_xneko_sk_linker(bpy.types.Panel):
    bl_label = "Shape Key Linker"
    bl_idname = "VIEW3D_PT_xneko_sk_linker"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Use split layout to separate label and property
        # factor=0.2 means the left label takes 20% of the width
        split = layout.split(factor=0.2)
        
        # Left side: label
        split.label(text="Source:")
        
        # Right side: object picker (stretches to fill remaining space)
        split.prop(scene, "xneko_sk_source", text="")

        layout.separator()

        layout.label(text="Targets:")

        row = layout.row()
        row.template_list(
            "XNEKO_UL_sk_targets", "",
            scene, "xneko_sk_targets",
            scene, "xneko_sk_target_index",
            rows=5,
        )

        col = row.column(align=True)
        col.operator("xneko.sk_add_target", text="", icon='ADD')
        col.operator("xneko.sk_remove_target", text="", icon='REMOVE')
        col.separator()
        col.operator("xneko.sk_clear_targets", text="", icon='TRASH')

        layout.separator()

        col = layout.column(align=True)
        col.prop(scene, "xneko_sk_skip_symbols")
        col.prop(scene, "xneko_sk_clear_after_link")

        layout.operator("xneko.sk_link", icon='LINKED')

        if scene.xneko_sk_status:
            layout.separator()
            layout.label(text=scene.xneko_sk_status, icon='INFO')


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_PG_sk_target,
    XNEKO_UL_sk_targets,
    XNEKO_OT_sk_add_target,
    XNEKO_OT_sk_remove_target,
    XNEKO_OT_sk_clear_targets,
    XNEKO_OT_sk_link,
    VIEW3D_PT_xneko_sk_linker,
)


scene_props = {
    "xneko_sk_source": bpy.props.PointerProperty(
        name="Source",
        description="Object whose shape key values drive all targets",
        type=bpy.types.Object,
        poll=_poll_mesh_with_keys,
    ),
    "xneko_sk_targets": bpy.props.CollectionProperty(type=XNEKO_PG_sk_target),
    "xneko_sk_target_index": bpy.props.IntProperty(
        name="Target Index", default=0, min=0,
    ),
    "xneko_sk_skip_symbols": bpy.props.BoolProperty(
        name="Skip Symbol-Prefixed Keys",
        description=(
            "Ignore target shape keys whose names start with a symbol "
            "such as '.' or '_' — typical for helper keys that should "
            "not deform along with the source. Any stale mirror driver "
            "on such keys is removed"
        ),
        default=True,
    ),
    "xneko_sk_clear_after_link": bpy.props.BoolProperty(
        name="Clear List After Linking",
        description="Empty the target list automatically after applying drivers",
        default=True,
    ),
    "xneko_sk_status": bpy.props.StringProperty(
        name="Status", default="",
    ),
}