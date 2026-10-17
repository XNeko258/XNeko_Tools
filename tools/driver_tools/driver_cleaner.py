import bpy

# ── Metadata ─────────────────────────────────────────────
tool_id = "driver_cleaner"
tool_name = "Driver Cleaner"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ── Constants ────────────────────────────────────────────
_KIND_ICONS = {
    'OBJECT':     'OBJECT_DATA',
    'MESH':       'MESH_DATA',
    'CURVE':      'CURVE_DATA',
    'FONT':       'FONT_DATA',
    'META':       'META_DATA',
    'LATTICE':    'LATTICE_DATA',
    'CAMERA':     'CAMERA_DATA',
    'LIGHT':      'LIGHT_DATA',
    'SPEAKER':    'SPEAKER',
    'ARMATURE':   'ARMATURE_DATA',
    'BONE':       'BONE_DATA',
    'POSE_BONE':  'BONE_DATA',
    'MATERIAL':   'MATERIAL',
    'SHAPE_KEYS': 'SHAPEKEY_DATA',
    'KEY_BLOCK':  'SHAPEKEY_DATA',
}

_KIND_LABEL = {
    'MESH':     "Mesh",
    'CURVE':    "Curve",
    'FONT':     "Font",
    'META':     "Metaball",
    'LATTICE':  "Lattice",
    'CAMERA':   "Camera",
    'LIGHT':    "Light",
    'SPEAKER':  "Speaker",
    'ARMATURE': "Armature",
}

_OB_DATA_KIND = {
    'MESH':     'MESH',
    'CURVE':    'CURVE',
    'FONT':     'FONT',
    'META':     'META',
    'LATTICE':  'LATTICE',
    'CAMERA':   'CAMERA',
    'LIGHT':    'LIGHT',
    'SPEAKER':  'SPEAKER',
    'ARMATURE': 'ARMATURE',
}


# ── Module state (no RNA writes) ────────────────────────
_STATE = {
    'selected_flags': {},   # key_str -> bool (checkbox state)
}

_scan_cache = {'objs_key': None, 'problems': None}


def _invalidate_scan_cache():
    _scan_cache['objs_key'] = None
    _scan_cache['problems'] = None


def _tag_redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ── Scanning ────────────────────────────────────────────

def _iter_selection_driver_owners(context):
    """Yield (key_str, kind, label, owner_id, anim_data) for every owner
    on selected objects (object itself, its data, shape keys / key blocks,
    bones, pose bones, and materials). Owners are deduplicated by pointer
    identity so shared data (e.g. material reused across objects) is
    visited only once.
    """
    seen = set()

    def try_emit(kind, label, owner):
        ad = getattr(owner, 'animation_data', None)
        if not ad or not ad.drivers:
            return None
        key = f"{kind}:{owner.as_pointer()}"
        if key in seen:
            return None
        seen.add(key)
        return key, kind, label, owner, ad

    for ob in context.selected_objects:
        if getattr(ob, 'library', None) or getattr(ob, 'override_library', None):
            continue

        # Object itself
        r = try_emit('OBJECT', f"Object: {ob.name}", ob)
        if r:
            yield r

        # Object data (mesh, curve, font, metaball, lattice, camera, light,
        # speaker, armature)
        data = getattr(ob, 'data', None)
        data_kind = _OB_DATA_KIND.get(ob.type)
        if data is not None and data_kind is not None:
            r = try_emit(data_kind, f"{_KIND_LABEL[data_kind]}: {data.name}", data)
            if r:
                yield r

            # Shape keys container
            sk = getattr(data, 'shape_keys', None)
            if sk is not None:
                r = try_emit('SHAPE_KEYS', f"Shape Keys: {ob.name}", sk)
                if r:
                    yield r
                for kb in sk.key_blocks:
                    r = try_emit(
                        'KEY_BLOCK',
                        f"Key Block: {kb.name} ({ob.name})",
                        kb,
                    )
                    if r:
                        yield r

            # Bones (armature data)
            if ob.type == 'ARMATURE':
                for bone in data.bones:
                    r = try_emit(
                        'BONE',
                        f"Bone: {bone.name} ({ob.name})",
                        bone,
                    )
                    if r:
                        yield r

        # Pose bones (armature object)
        if ob.type == 'ARMATURE':
            for pb in ob.pose.bones:
                r = try_emit(
                    'POSE_BONE',
                    f"Pose Bone: {pb.name} ({ob.name})",
                    pb,
                )
                if r:
                    yield r

        # Materials
        for slot in getattr(ob, 'material_slots', ()):
            mat = slot.material
            if mat is None:
                continue
            if getattr(mat, 'library', None) or getattr(mat, 'override_library', None):
                continue
            r = try_emit('MATERIAL', f"Material: {mat.name}", mat)
            if r:
                yield r


def _count_problems(anim_data):
    """Return (invalid_count, duplicate_count).

    Invalid drivers are counted separately and excluded from the duplicate
    count so a broken driver is never reported twice.
    """
    invalid = 0
    dup = 0
    seen = set()
    for fc in anim_data.drivers:
        if not fc.driver.is_valid:
            invalid += 1
            continue
        sig = (fc.data_path, fc.array_index, fc.driver.expression)
        if sig in seen:
            dup += 1
        else:
            seen.add(sig)
    return invalid, dup


def _scan_problems(context):
    """Return {key_str: problem_dict} for owner items that currently have
    at least one problem driver.

    Results are cached against the current selection. The cache is
    invalidated whenever this module modifies drivers (i.e. after a clean
    operation) or whenever the selection changes.
    """
    objs_key = tuple(sorted(
        (ob.name, ob.as_pointer()) for ob in context.selected_objects
    ))

    cached = _scan_cache['problems']
    if _scan_cache['objs_key'] == objs_key and cached is not None:
        # Refresh checkbox states (user may have toggled items since the
        # last scan) without recomputing the whole list.
        for key, p in cached.items():
            p['selected'] = _STATE['selected_flags'].get(key, True)
        return cached

    problems = {}
    live_keys = set()

    for key, kind, label, owner, ad in _iter_selection_driver_owners(context):
        live_keys.add(key)
        invalid, dup = _count_problems(ad)
        if invalid == 0 and dup == 0:
            continue
        problems[key] = {
            'kind': kind,
            'label': label,
            'icon': _KIND_ICONS.get(kind, 'DOT'),
            'anim_data': ad,
            'invalid': invalid,
            'dup': dup,
            'selected': _STATE['selected_flags'].get(key, True),
        }

    # Drop stale selection flags for keys that no longer exist
    for k in list(_STATE['selected_flags'].keys()):
        if k not in live_keys:
            del _STATE['selected_flags'][k]

    _scan_cache['objs_key'] = objs_key
    _scan_cache['problems'] = problems
    return problems


# ── Cleaning ────────────────────────────────────────────

def _clean_anim_data(anim_data, mode):
    """Remove invalid and/or duplicate drivers from anim_data.

    mode: 'INVALID' | 'DUP' | 'BOTH'
    Returns (removed_invalid, removed_dup).

    Duplicate handling keeps the first driver of each signature and
    removes every subsequent match, including multiple identical
    duplicates of the same (data_path, array_index).
    """
    removed_inv = 0
    removed_dup = 0

    if mode in ('INVALID', 'BOTH'):
        for fc in list(anim_data.drivers):
            if not fc.driver.is_valid:
                anim_data.drivers.remove(fc)
                removed_inv += 1

    if mode in ('DUP', 'BOTH'):
        drivers = list(anim_data.drivers)
        seen = set()
        to_remove_indices = []
        for i, fc in enumerate(drivers):
            if not fc.driver.is_valid:
                continue
            sig = (fc.data_path, fc.array_index, fc.driver.expression)
            if sig in seen:
                to_remove_indices.append(i)
            else:
                seen.add(sig)

        # Remove in reverse index order so earlier indices stay valid.
        for i in reversed(to_remove_indices):
            anim_data.drivers.remove(drivers[i])
            removed_dup += 1

    return removed_inv, removed_dup


# ── Operators ───────────────────────────────────────────

class XNEKO_OT_toggle_problem(bpy.types.Operator):
    """Toggle selection of a single problem item"""
    bl_idname = "xneko.driver_toggle_problem"
    bl_label = "Toggle Problem"
    bl_options = {'INTERNAL'}

    key_str: bpy.props.StringProperty()

    def execute(self, context):
        cur = _STATE['selected_flags'].get(self.key_str, True)
        _STATE['selected_flags'][self.key_str] = not cur
        _tag_redraw(context)
        return {'FINISHED'}


class XNEKO_OT_select_all_problems(bpy.types.Operator):
    """Select or deselect all problem items"""
    bl_idname = "xneko.driver_select_all_problems"
    bl_label = "Select All Problems"
    bl_options = {'INTERNAL'}

    select: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        for k in _scan_problems(context):
            _STATE['selected_flags'][k] = self.select
        _tag_redraw(context)
        return {'FINISHED'}


class XNEKO_OT_clean_selected_problems(bpy.types.Operator):
    """Clean all problem drivers on checked items"""
    bl_idname = "xneko.driver_clean_selected"
    bl_label = "Clean Selected Problems"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        problems = _scan_problems(context)
        if not problems:
            self.report({'INFO'}, "No problems found.")
            return {'CANCELLED'}

        total_inv = 0
        total_dup = 0
        items = 0
        for key, p in problems.items():
            if not _STATE['selected_flags'].get(key, True):
                continue
            inv, dup = _clean_anim_data(p['anim_data'], 'BOTH')
            if inv or dup:
                items += 1
            total_inv += inv
            total_dup += dup

        _invalidate_scan_cache()

        if total_inv or total_dup:
            self.report(
                {'INFO'},
                f"Cleaned {items} item(s): "
                f"{total_inv} invalid, {total_dup} duplicate."
            )
        else:
            self.report({'INFO'}, "Nothing to clean in selection.")
        _tag_redraw(context)
        return {'FINISHED'}


class XNEKO_OT_clean_all_invalid(bpy.types.Operator):
    """Clean all invalid drivers on selected objects (ignores checkboxes)"""
    bl_idname = "xneko.driver_clean_all_invalid"
    bl_label = "Clean All Invalid"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        n = 0
        for p in _scan_problems(context).values():
            inv, _ = _clean_anim_data(p['anim_data'], 'INVALID')
            n += inv

        _invalidate_scan_cache()

        if n:
            self.report({'INFO'}, f"Cleaned {n} invalid driver(s).")
        else:
            self.report({'INFO'}, "No invalid drivers found.")
        _tag_redraw(context)
        return {'FINISHED'}


class XNEKO_OT_clean_all_dup(bpy.types.Operator):
    """Clean all duplicate drivers on selected objects (ignores checkboxes)"""
    bl_idname = "xneko.driver_clean_all_dup"
    bl_label = "Clean All Duplicates"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        n = 0
        for p in _scan_problems(context).values():
            _, dup = _clean_anim_data(p['anim_data'], 'DUP')
            n += dup

        _invalidate_scan_cache()

        if n:
            self.report({'INFO'}, f"Cleaned {n} duplicate driver(s).")
        else:
            self.report({'INFO'}, "No duplicate drivers found.")
        _tag_redraw(context)
        return {'FINISHED'}


# ── UI Panel ────────────────────────────────────────────

class VIEW3D_PT_xneko_driver_cleaner(bpy.types.Panel):
    bl_label = "Driver Cleaner"
    bl_idname = "VIEW3D_PT_xneko_driver_cleaner"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        selected_objs = context.selected_objects

        # No selection
        if not selected_objs:
            box = layout.box()
            box.label(text="No object selected.", icon='INFO')
            box.label(text="Select object(s) to scan their drivers.")
            return

        problems = _scan_problems(context)

        # Header
        layout.label(
            text=f"Selected: {len(selected_objs)} object(s)",
            icon='RESTRICT_SELECT_OFF',
        )

        if not problems:
            box = layout.box()
            box.label(text="No problem drivers found.", icon='CHECKMARK')
            return

        # Problem list
        box = layout.box()
        box.label(
            text=f"Found {len(problems)} item(s) with problems:",
            icon='ERROR',
        )

        col = box.column(align=True)
        for key, p in problems.items():
            row = col.row(align=True)
            op = row.operator(
                "xneko.driver_toggle_problem",
                text="",
                icon='CHECKBOX_HLT' if p['selected'] else 'CHECKBOX_DEHLT',
                emboss=False,
            )
            op.key_str = key
            row.label(text=p['label'], icon=p['icon'])

            sub = row.row(align=True)
            sub.alignment = 'RIGHT'
            if p['invalid']:
                sub.label(text=f"inv:{p['invalid']}")
            if p['dup']:
                sub.label(text=f"dup:{p['dup']}")

        # Select all / none
        row = box.row(align=True)
        op = row.operator("xneko.driver_select_all_problems", text="Select All")
        op.select = True
        op = row.operator("xneko.driver_select_all_problems", text="Select None")
        op.select = False

        # Clean actions
        box = layout.box()
        box.label(text="Clean:", icon='DRIVER')
        col = box.column(align=True)
        col.scale_y = 1.2
        col.operator(
            "xneko.driver_clean_selected",
            text="Clean Selected Problems",
            icon='BRUSH_DATA',
        )
        row = col.row(align=True)
        row.operator("xneko.driver_clean_all_invalid", text="Clean All Invalid")
        row.operator("xneko.driver_clean_all_dup", text="Clean All Dup")


# ── Registration ────────────────────────────────────────

classes = (
    XNEKO_OT_toggle_problem,
    XNEKO_OT_select_all_problems,
    XNEKO_OT_clean_selected_problems,
    XNEKO_OT_clean_all_invalid,
    XNEKO_OT_clean_all_dup,
    VIEW3D_PT_xneko_driver_cleaner,
)