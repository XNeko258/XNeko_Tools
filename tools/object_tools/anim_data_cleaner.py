import bpy

# ── Metadata ─────────────────────────────────────────────
tool_id = "anim_data_cleaner"
tool_name = "Anim Data Cleaner"
tool_default_enabled = True
blender_version_min = (4, 2, 0)


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
    'POSE_BONE':  'BONE_DATA',
    'MATERIAL':   'MATERIAL',
    'SHAPE_KEYS': 'SHAPEKEY_DATA',
    'CURVES':       'CURVES_DATA',
    'GREASEPENCIL': 'GREASEPENCIL',
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
    'CURVES':       "Hair Curves",
    'GREASEPENCIL': "Grease Pencil",
}


# ── LTS feature detection (once, at module load) ────────
# The three LTS targets split cleanly at Blender 4.4:
#   4.2 LTS : legacy action.fcurves only
#   4.5 LTS : layered API + slots (action.fcurves is a proxy)
#   5.2 LTS : layered API only (action.fcurves was removed)
#
# hasattr on the RNA type answers "does this build expose the
# layered API" directly, which is more robust than a version
# check: a backport or a custom build still selects the correct
# backend.
_HAS_LAYERED_ACTIONS = hasattr(bpy.types.Action, 'layers')
_HAS_ACTION_SLOT = hasattr(bpy.types.AnimData, 'action_slot')


# ── State ────────────────────────────────────────────────
_scan_cache = {'objs_key': None, 'problems': None, 'totals': None}


def _invalidate_scan_cache(_scene=None):
    """Clear the scan cache. Also serves as the undo_post handler,
    which is why it accepts an unused scene argument."""
    _scan_cache['objs_key'] = None
    _scan_cache['problems'] = None
    _scan_cache['totals'] = None


def _tag_redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ── Action fcurves: backend chosen at import time ───────
def _iter_action_fcurves_legacy(action):
    """Blender 4.2 LTS backend: legacy action.fcurves."""
    try:
        for fc in action.fcurves:
            yield action, fc
    except Exception:
        pass


def _iter_action_fcurves_layered(action):
    """Blender 4.5 / 5.2 LTS backend: layered channelbag.fcurves.

    Covers every slot in 4.5 and is the only valid path in 5.2,
    where action.fcurves no longer exists.
    """
    try:
        for layer in action.layers:
            for strip in layer.strips:
                for cbag in getattr(strip, 'channelbags', ()):
                    for fc in cbag.fcurves:
                        yield cbag, fc
    except Exception:
        pass


if _HAS_LAYERED_ACTIONS:
    _iter_action_fcurves = _iter_action_fcurves_layered
else:
    _iter_action_fcurves = _iter_action_fcurves_legacy


# ── Slot binding check: backend chosen at import time ───
if _HAS_ACTION_SLOT:
    def _action_has_no_bound_slot(anim_data, action):
        """4.5 / 5.2 LTS: an assigned action without a bound slot
        does not actually animate this data-block, even though
        anim_data.action is set."""
        try:
            if not hasattr(action, 'slots'):
                return False
            if len(action.slots) == 0:
                return True
            return getattr(anim_data, 'action_slot', None) is None
        except Exception:
            return False
else:
    def _action_has_no_bound_slot(anim_data, action):
        """4.2 LTS: slots do not exist, so an assigned action is
        always considered bound."""
        return False


# ── Scanning ─────────────────────────────────────────────
def _iter_selection_owners(context):
    """Yield (key, kind, label, owner, anim_data) for every owner on
    selected objects that has animation_data.

    Bones and key blocks are deliberately not yielded: bpy Bone and
    ShapeKey are not IDs and carry no animation_data. Pose-bone
    animation lives on the PoseBone, and key-block animation lives
    on the Key datablock (emitted as SHAPE_KEYS).
    """
    seen = set()

    def try_emit(kind, label, owner):
        ad = getattr(owner, 'animation_data', None)
        if ad is None:
            return None
        key = f"{kind}:{owner.as_pointer()}"
        if key in seen:
            return None
        seen.add(key)
        return key, kind, label, owner, ad

    for ob in context.selected_objects:
        if getattr(ob, 'library', None) or getattr(ob, 'override_library', None):
            continue

        r = try_emit('OBJECT', f"Object: {ob.name}", ob)
        if r:
            yield r

        data = getattr(ob, 'data', None)
        if data is not None and ob.type in _KIND_LABEL:
            kind = ob.type
            r = try_emit(kind, f"{_KIND_LABEL[kind]}: {data.name}", data)
            if r:
                yield r

            sk = getattr(data, 'shape_keys', None)
            if sk is not None:
                r = try_emit('SHAPE_KEYS', f"Shape Keys: {ob.name}", sk)
                if r:
                    yield r

        if ob.type == 'ARMATURE':
            for pb in ob.pose.bones:
                r = try_emit(
                    'POSE_BONE',
                    f"Pose Bone: {pb.name} ({ob.name})",
                    pb,
                )
                if r:
                    yield r

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
    """Return a dict of problem counts for anim_data."""
    out = {
        'invalid_drivers': 0,
        'dup_drivers': 0,
        'empty_action': False,
        'bad_fcurves': 0,
        'dup_fcurves': 0,
        'empty_tracks': 0,
        'empty_strips': 0,
    }

    seen = set()
    for fc in anim_data.drivers:
        drv = fc.driver
        if not drv.is_valid:
            out['invalid_drivers'] += 1
            continue
        sig = (fc.data_path, fc.array_index, drv.expression)
        if sig in seen:
            out['dup_drivers'] += 1
        else:
            seen.add(sig)

    action = getattr(anim_data, 'action', None)
    if action is not None:
        if _action_has_no_bound_slot(anim_data, action):
            out['empty_action'] = True
        else:
            fcurves = [fc for _c, fc in _iter_action_fcurves(action)]
            if not any(len(fc.keyframe_points) > 0 for fc in fcurves):
                out['empty_action'] = True
            else:
                seen_fc = set()
                for fc in fcurves:
                    if not fc.is_valid:
                        out['bad_fcurves'] += 1
                        continue
                    sig = (fc.data_path, fc.array_index)
                    if sig in seen_fc:
                        out['dup_fcurves'] += 1
                    else:
                        seen_fc.add(sig)

    for track in anim_data.nla_tracks:
        if len(track.strips) == 0:
            out['empty_tracks'] += 1
            continue
        # Not copied to a list: this loop only reads, so iterating
        # the RNA collection directly is safe and avoids a list
        # allocation per non-empty track.
        for strip in track.strips:
            if getattr(strip, 'type', 'ANIMATION') != 'ANIMATION':
                continue
            if getattr(strip, 'action', None) is None:
                out['empty_strips'] += 1

    return out


def _scan_problems(context):
    """Return {key: problem_dict} for owners with problems. Cached
    against the current selection; invalidated by selection change,
    clean operations, and undo_post. Per-type totals are computed
    once per scan and cached alongside problems so Panel.draw does
    not re-aggregate them on every redraw."""
    objs_key = frozenset(ob.as_pointer() for ob in context.selected_objects)

    if _scan_cache['objs_key'] == objs_key and _scan_cache['problems'] is not None:
        return _scan_cache['problems']

    problems = {}
    totals = {
        'invalid_drivers': 0,
        'dup_drivers': 0,
        'empty_action': 0,
        'bad_fcurves': 0,
        'dup_fcurves': 0,
        'empty_tracks': 0,
        'empty_strips': 0,
    }

    for key, kind, label, owner, ad in _iter_selection_owners(context):
        counts = _count_problems(ad)
        if not any(counts.values()):
            continue
        p = {
            'kind': kind,
            'label': label,
            'icon': _KIND_ICONS.get(kind, 'DOT'),
            'anim_data': ad,
        }
        p.update(counts)
        problems[key] = p

        totals['invalid_drivers'] += counts['invalid_drivers']
        totals['dup_drivers'] += counts['dup_drivers']
        totals['empty_action'] += 1 if counts['empty_action'] else 0
        totals['bad_fcurves'] += counts['bad_fcurves']
        totals['dup_fcurves'] += counts['dup_fcurves']
        totals['empty_tracks'] += counts['empty_tracks']
        totals['empty_strips'] += counts['empty_strips']

    _scan_cache['objs_key'] = objs_key
    _scan_cache['problems'] = problems
    _scan_cache['totals'] = totals
    return problems


# ── Cleaning ─────────────────────────────────────────────
def _clean_anim_data(anim_data, mode):
    """Clean animation data according to mode.

    mode:
        'DRIVERS'      invalid + duplicate drivers (one pass)
        'EMPTY_ACTION' unlink empty action
        'BAD_FCURVES'  remove invalid fcurves
        'DUP_FCURVES'  remove duplicate fcurves
        'NLA'          remove empty NLA strips and tracks
        'ALL'          all of the above

    Returns a dict of removal counts.
    """
    result = {
        'invalid_drivers': 0,
        'dup_drivers': 0,
        'empty_actions': 0,
        'bad_fcurves': 0,
        'dup_fcurves': 0,
        'empty_tracks': 0,
        'empty_strips': 0,
    }

    do_all = mode == 'ALL'

    # Drivers — invalid and duplicate cleaned together.
    if do_all or mode == 'DRIVERS':
        to_remove = []
        seen = set()
        for fc in list(anim_data.drivers):
            drv = fc.driver
            if not drv.is_valid:
                to_remove.append(fc)
                result['invalid_drivers'] += 1
                continue
            sig = (fc.data_path, fc.array_index, drv.expression)
            if sig in seen:
                to_remove.append(fc)
                result['dup_drivers'] += 1
            else:
                seen.add(sig)
        for fc in to_remove:
            try:
                anim_data.drivers.remove(fc)
            except Exception:
                pass

    # Action
    action = getattr(anim_data, 'action', None)

    # Empty action: unlink. Safe regardless of user count because
    # it only drops this anim_data's reference.
    if action is not None and (do_all or mode == 'EMPTY_ACTION'):
        empty = False
        if _action_has_no_bound_slot(anim_data, action):
            empty = True
        else:
            fcurves = [fc for _c, fc in _iter_action_fcurves(action)]
            if not any(len(fc.keyframe_points) > 0 for fc in fcurves):
                empty = True
        if empty:
            try:
                anim_data.action = None
                # 4.5+ also clears the slot reference so the empty
                # action can be reclaimed cleanly.
                if _HAS_ACTION_SLOT:
                    anim_data.action_slot = None
                result['empty_actions'] += 1
                action = None
            except Exception:
                pass

    # Bad / duplicate fcurves. Skipped on shared actions to avoid
    # editing another object's animation.
    if action is not None and (
        do_all or mode in ('BAD_FCURVES', 'DUP_FCURVES')
    ):
        do_bad = do_all or mode == 'BAD_FCURVES'
        do_dup = do_all or mode == 'DUP_FCURVES'
        if getattr(action, 'users', 0) <= 1:
            entries = list(_iter_action_fcurves(action))
            seen_fc = set()
            to_remove = []
            for container, fc in entries:
                # Invalid fcurves never participate in duplicate detection,
                # regardless of whether bad-fcurve cleaning is enabled. This
                # mirrors _count_problems, where invalid fcurves are counted
                # and skipped before the dup signature is computed.
                if not fc.is_valid:
                    if do_bad:
                        to_remove.append((container, fc))
                        result['bad_fcurves'] += 1
                    continue
                if do_dup:
                    sig = (fc.data_path, fc.array_index)
                    if sig in seen_fc:
                        to_remove.append((container, fc))
                        result['dup_fcurves'] += 1
                    else:
                        seen_fc.add(sig)
            for container, fc in to_remove:
                try:
                    container.fcurves.remove(fc)
                except Exception:
                    pass

    # NLA
    if do_all or mode == 'NLA':
        tracks_to_remove = []
        for track in list(anim_data.nla_tracks):
            # Empty check via len() avoids a list allocation per
            # track. This matters when the file carries thousands of
            # empty NLA tracks, which is the common case for files
            # that accumulated stale tracks over time.
            if len(track.strips) == 0:
                tracks_to_remove.append(track)
                result['empty_tracks'] += 1
                continue
            # The strip list must be a copy: strips are removed
            # inside the loop, so iterating the RNA collection
            # directly would invalidate the iterator.
            for strip in list(track.strips):
                if getattr(strip, 'type', 'ANIMATION') != 'ANIMATION':
                    continue
                if getattr(strip, 'action', None) is None:
                    try:
                        track.strips.remove(strip)
                        result['empty_strips'] += 1
                    except Exception:
                        pass
            if len(track.strips) == 0:
                tracks_to_remove.append(track)
                result['empty_tracks'] += 1
        for track in tracks_to_remove:
            try:
                anim_data.nla_tracks.remove(track)
            except Exception:
                pass

    return result


def _sum_result(total, result):
    for k, v in result.items():
        total[k] = total.get(k, 0) + v


def _report_clean(op, total):
    """Report a clean summary from accumulated counts."""
    parts = []
    if total.get('invalid_drivers'):
        parts.append(f"{total['invalid_drivers']} inv-drv")
    if total.get('dup_drivers'):
        parts.append(f"{total['dup_drivers']} dup-drv")
    if total.get('empty_actions'):
        parts.append(f"{total['empty_actions']} empty-act")
    if total.get('bad_fcurves'):
        parts.append(f"{total['bad_fcurves']} bad-fc")
    if total.get('dup_fcurves'):
        parts.append(f"{total['dup_fcurves']} dup-fc")
    if total.get('empty_tracks'):
        parts.append(f"{total['empty_tracks']} nla-trk")
    if total.get('empty_strips'):
        parts.append(f"{total['empty_strips']} nla-strip")

    if not parts:
        op.report({'INFO'}, "Nothing to clean.")
    else:
        op.report({'INFO'}, "Cleaned: " + ", ".join(parts))


# ── Operator ─────────────────────────────────────────────

class ADC_OT_refresh_scan(bpy.types.Operator):
    """Force a rescan of the selected objects"""
    bl_idname = "adc.refresh_scan"
    bl_label = "Refresh Scan"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _invalidate_scan_cache()
        _tag_redraw(context)
        return {'FINISHED'}


class ADC_OT_clean_all(bpy.types.Operator):
    """Clean problems on all selected objects.

    The `mode` property selects which problem category to clean.
    Defaults to ALL, but the panel binds specific modes to buttons
    that appear only when the corresponding problem is present.
    """
    bl_idname = "adc.clean_all"
    bl_label = "Clean Anim Data"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        items=[
            ('ALL',          "All",                ""),
            ('DRIVERS',      "Drivers",            ""),
            ('EMPTY_ACTION', "Empty Action",       ""),
            ('BAD_FCURVES',  "Bad F-Curves",       ""),
            ('DUP_FCURVES',  "Duplicate F-Curves", ""),
            ('NLA',          "Empty NLA",          ""),
        ],
        default='ALL',
    )

    def execute(self, context):
        problems = _scan_problems(context)
        if not problems:
            self.report({'INFO'}, "No problems found.")
            return {'CANCELLED'}

        total = {}
        for p in problems.values():
            r = _clean_anim_data(p['anim_data'], self.mode)
            _sum_result(total, r)

        _invalidate_scan_cache()
        _report_clean(self, total)
        _tag_redraw(context)
        return {'FINISHED'}


# ── Panel ────────────────────────────────────────────────
class VIEW3D_PT_anim_data_cleaner(bpy.types.Panel):
    bl_label = "Anim Data Cleaner"
    bl_idname = "VIEW3D_PT_anim_data_cleaner"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        selected_objs = context.selected_objects

        if not selected_objs:
            box = layout.box()
            box.label(text="No object selected.", icon='INFO')
            box.label(text="Select object(s) to scan their animation data.")
            return

        problems = _scan_problems(context)

        row = layout.row(align=True)
        row.label(
            text=f"Selected: {len(selected_objs)} object(s)",
            icon='RESTRICT_SELECT_OFF',
        )
        row.operator("adc.refresh_scan", text="", icon='FILE_REFRESH')

        if not problems:
            box = layout.box()
            box.label(text="No problems found.", icon='CHECKMARK')
            return

        totals = _scan_cache['totals']

        # Problem list
        box = layout.box()
        box.label(
            text=f"Found {len(problems)} item(s) with problems:",
            icon='ERROR',
        )
        col = box.column(align=True)
        for key, p in problems.items():
            row = col.row(align=True)
            row.label(text=p['label'], icon=p['icon'])

            if p['invalid_drivers'] or p['dup_drivers']:
                parts = []
                if p['invalid_drivers']:
                    parts.append(f"{p['invalid_drivers']} invalid")
                if p['dup_drivers']:
                    parts.append(f"{p['dup_drivers']} dup")
                sub = col.row(align=True)
                sub.label(text="", icon='BLANK1')
                sub.label(text="Drivers: " + ", ".join(parts), icon='DRIVER')

            if p['empty_action'] or p['bad_fcurves'] or p['dup_fcurves']:
                parts = []
                if p['empty_action']:
                    parts.append("empty")
                if p['bad_fcurves']:
                    parts.append(f"{p['bad_fcurves']} bad")
                if p['dup_fcurves']:
                    parts.append(f"{p['dup_fcurves']} dup")
                sub = col.row(align=True)
                sub.label(text="", icon='BLANK1')
                sub.label(text="Action: " + ", ".join(parts), icon='ANIM')

            if p['empty_tracks'] or p['empty_strips']:
                parts = []
                if p['empty_tracks']:
                    parts.append(f"{p['empty_tracks']} tracks")
                if p['empty_strips']:
                    parts.append(f"{p['empty_strips']} strips")
                sub = col.row(align=True)
                sub.label(text="", icon='BLANK1')
                sub.label(text="NLA: " + ", ".join(parts), icon='NLA')

        # Clean actions
        box = layout.box()
        box.label(text="Clean:", icon='BRUSH_DATA')
        col = box.column(align=True)
        col.scale_y = 1.2
        col.operator(
            "adc.clean_all",
            text="Clean All Problems",
            icon='BRUSH_DATA',
        ).mode = 'ALL'

        # Per-type buttons. A category's buttons are drawn only when
        # that category has at least one problem, so the panel stays
        # focused on what is actually present in the selection.
        drv_n = totals['invalid_drivers'] + totals['dup_drivers']
        has_act = (
            totals['empty_action']
            or totals['bad_fcurves']
            or totals['dup_fcurves']
        )
        nla_n = totals['empty_tracks'] + totals['empty_strips']

        if drv_n or has_act or nla_n:
            box.separator()
            sub = box.column(align=True)
            sub.label(text="Clean by type:")

            if drv_n:
                s = sub.column(align=True)
                s.label(text="Drivers:", icon='DRIVER')
                r = s.row(align=True)
                r.operator(
                    "adc.clean_all",
                    text=f"Clean Invalid & Dup ({drv_n})",
                ).mode = 'DRIVERS'

            if has_act:
                s = sub.column(align=True)
                s.label(text="Action:", icon='ANIM')
                if totals['empty_action']:
                    s.operator(
                        "adc.clean_all",
                        text=f"Empty ({totals['empty_action']})",
                    ).mode = 'EMPTY_ACTION'
                if totals['bad_fcurves']:
                    s.operator(
                        "adc.clean_all",
                        text=f"Bad F-Curves ({totals['bad_fcurves']})",
                    ).mode = 'BAD_FCURVES'
                if totals['dup_fcurves']:
                    s.operator(
                        "adc.clean_all",
                        text=f"Dup F-Curves ({totals['dup_fcurves']})",
                    ).mode = 'DUP_FCURVES'

            if nla_n:
                s = sub.column(align=True)
                s.label(text="NLA:", icon='NLA')
                r = s.row(align=True)
                r.operator(
                    "adc.clean_all",
                    text=f"Empty ({nla_n})",
                ).mode = 'NLA'


# ── Registration ─────────────────────────────────────────
classes = (
    ADC_OT_refresh_scan,
    ADC_OT_clean_all,
    VIEW3D_PT_anim_data_cleaner,
)


# ── Framework hooks ──────────────────────────────────────
def on_load():
    if _invalidate_scan_cache not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(_invalidate_scan_cache)


def on_unload():
    try:
        bpy.app.handlers.undo_post.remove(_invalidate_scan_cache)
    except ValueError:
        pass