"""Shape Key Plus — single-file development build.

Patches the built-in Object Data > Shape Keys panel to:

  * Add two columns to each list row: [GRIP] [select]
    - GRIP enters reorder mode (click, wheel to move, click or Enter
      to confirm, right-click or Esc to cancel).
    - select toggles multi-selection (click / Shift+click / Ctrl+click).

  * Replace the remove button with a context-aware variant: with two
    or more selected keys it removes all of them; otherwise it behaves
    exactly like the built-in remove button.

  * Append a reorder-mode hint box below the panel with native key-cap
    icons while reorder mode is active.

Clicking a row's name in the list also updates the selection to that
row, so the remove button never deletes keys the user did not intend
to target.
"""

import time

import bpy
from bpy.props import BoolProperty, IntProperty

tool_id = "shape_key_plus"
tool_name = "Shape Key Plus"
tool_default_enabled = False

# Minimum supported Blender version. All features work on 4.0+
# except the name filter, whose search bar only exists from 4.5
# onward. The filter degrades silently on 4.0 ~ 4.4; every other
# feature remains fully functional.
blender_version_min = (4, 0, 0)


# =====================================================================
# Tool preferences
# =====================================================================

preference_props = {
    "wheel_acceleration": BoolProperty(
        name="Wheel Acceleration",
        description=(
            "Roll the wheel fast to move further per notch; roll it "
            "slowly to fall back to Base Step. Off by default so a "
            "fast scroll never moves more rows than expected"
        ),
        default=False,
    ),
    "scroll_step": IntProperty(
        name="Base Step",
        description="Rows moved per wheel notch at normal speed",
        default=1,
        min=1, max=50,
        soft_min=1, soft_max=5,
    ),
    "max_scroll_step": IntProperty(
        name="Max Step",
        description=(
            "Maximum rows moved per wheel notch when rolling fast "
            "(requires Wheel Acceleration)"
        ),
        default=10,
        min=1, max=1000,
        soft_min=1, soft_max=20,
    ),
    "accel_step": IntProperty(
        name="Acceleration Step",
        description=(
            "How many rows the step size grows by per rapid wheel "
            "notch. Smaller values take longer to reach Max Step"
        ),
        default=1,
        min=1, max=200,
        soft_min=1, soft_max=5,
    ),
    "wheel_fast_ms": IntProperty(
        name="Fast Threshold (ms)",
        description=(
            "Intervals shorter than this are treated as fast scrolling "
            "and start ramping up the step size"
        ),
        default=150,
        min=10, max=2000,
        soft_min=50, soft_max=300,
    ),
    "wheel_slow_ms": IntProperty(
        name="Slow Threshold (ms)",
        description=(
            "Intervals longer than this reset the step size back to "
            "Base Step"
        ),
        default=400,
        min=20, max=5000,
        soft_min=150, soft_max=1000,
    ),
}

_cached_prefs = None


# Shape keys list height, in rows.
#
# _LIST_ROWS_BASE   -> visible rows when the extra tools block is collapsed
# _RENAME_EXTRA_ROWS -> extra rows added while the extra tools block is open
#
# Nudge these two numbers to taste; a plugin reload is enough to see
# the effect. The button column next to the list is roughly 8 rows
# tall when collapsed and 15 when expanded.
_LIST_ROWS_BASE = 8
_RENAME_EXTRA_ROWS = 9


def draw_preferences(layout, context, prefs):
    global _cached_prefs
    _cached_prefs = prefs

    col = layout.column(align=True)
    prefs.prop(col, "wheel_acceleration")

    try:
        accel_on = bool(getattr(prefs, "wheel_acceleration"))
    except Exception:
        accel_on = False

    grid = col.grid_flow(row_major=True, columns=2, align=True)
    grid.use_property_split = True

    # Base Step: occupies the first cell of the first row, always enabled.
    cell = grid.column()
    cell.use_property_split = True
    prefs.prop(cell, "scroll_step")

    # Empty cell so Base Step spans the whole row.
    grid.label(text="")

    # The remaining four settings are gated by the acceleration switch.
    for name in ("max_scroll_step", "accel_step",
                 "wheel_fast_ms", "wheel_slow_ms"):
        cell = grid.column()
        cell.use_property_split = True
        cell.active = accel_on
        prefs.prop(cell, name)


_resolved_get_tool_prefs = None


def _resolve_get_tool_prefs():
    """Locate get_tool_prefs in the surrounding addon.

    The relative depth of `preferences.py` depends on how the tools
    tree sits inside the addon package, so both common depths are
    tried in turn. The first one that imports wins and is cached for
    subsequent calls.
    """
    global _resolved_get_tool_prefs
    if _resolved_get_tool_prefs is not None:
        return _resolved_get_tool_prefs

    get_tool_prefs = None
    try:
        from ...preferences import get_tool_prefs
    except ImportError:
        try:
            from ....preferences import get_tool_prefs
        except ImportError:
            return None
        except Exception:
            return None
    except Exception:
        return None

    _resolved_get_tool_prefs = get_tool_prefs
    return get_tool_prefs


def _get_prefs():
    if _cached_prefs is not None:
        return _cached_prefs

    get_tool_prefs = _resolve_get_tool_prefs()
    if get_tool_prefs is None:
        return None

    try:
        return get_tool_prefs("shape_key_plus")
    except Exception:
        return None


def _read_scroll_step():
    prefs = _get_prefs()
    if prefs is None:
        return 1
    try:
        return max(1, int(prefs.scroll_step))
    except Exception:
        return 1


def _read_max_scroll_step(base):
    prefs = _get_prefs()
    if prefs is None:
        return base
    try:
        return max(base, int(prefs.max_scroll_step))
    except Exception:
        return base


def _read_accel_step():
    prefs = _get_prefs()
    if prefs is None:
        return 1
    try:
        return max(1, int(prefs.accel_step))
    except Exception:
        return 1


def _read_wheel_acceleration():
    prefs = _get_prefs()
    if prefs is None:
        return False
    try:
        return bool(prefs.wheel_acceleration)
    except Exception:
        return False


def _read_wheel_fast_dt():
    """Seconds below which two wheel events count as 'fast'."""
    prefs = _get_prefs()
    if prefs is None:
        return 0.15
    try:
        return max(0.01, int(prefs.wheel_fast_ms) / 1000.0)
    except Exception:
        return 0.15


def _read_wheel_slow_dt():
    """Seconds above which the step size resets to Base Step."""
    prefs = _get_prefs()
    if prefs is None:
        return 0.40
    try:
        return max(0.02, int(prefs.wheel_slow_ms) / 1000.0)
    except Exception:
        return 0.40


# =====================================================================
# Selection state
# =====================================================================

_selection = {}
_anchor = {}
# Tracks the last observed active_shape_key_index per object so we can
# sync the selection when the user clicks a row's name (which only
# changes the active index, not our own selection set).
_last_active = {}

# Shared between the modal operator and the UIList draw code.
_drag_state = {"active": False, "obj_name": "", "target": -1}


# Set during batch removal so draw_item skips its per-frame selection
# sync (which is O(N) per row and would make bulk delete O(M*N)).
_batch_operation = False


# Rename Tools block expand state. Module-level so it never ends up
# in the .blend file; it resets on Blender restart or plugin reload.
_rename_expand = False


def _toggle_rename_expand():
    global _rename_expand
    _rename_expand = not _rename_expand


# The per-object stores below are keyed by object name and are never
# trimmed on deletion, so a long session with many created or renamed
# objects would keep stale entries forever. Pruning walks every object
# in the file, so we hand it to a one-shot app timer instead of
# running it from a panel draw, where it would stutter on large scenes.
_maintenance_scheduled = False


def _prune_state():
    """Drop entries whose key no longer matches a live object."""
    live_names = {o.name for o in bpy.data.objects}
    for store in (_selection, _anchor, _last_active):
        for key in list(store.keys()):
            if key not in live_names:
                del store[key]


def _run_prune_timer():
    global _maintenance_scheduled
    _maintenance_scheduled = False
    _prune_state()
    # Returning None tells the timer system this was a one-shot and
    # should not be rescheduled.
    return None


def _maybe_prune_state():
    """Schedule a prune pass if one is not already pending."""
    global _maintenance_scheduled
    if _maintenance_scheduled:
        return
    _maintenance_scheduled = True
    bpy.app.timers.register(_run_prune_timer, first_interval=0.0)


def _live_names(obj):
    if not obj or not obj.data.shape_keys:
        return set()
    return {kb.name for kb in obj.data.shape_keys.key_blocks}


def _get_selection(obj):
    if not obj:
        return set()
    return _selection.get(obj.name, set()) & _live_names(obj)


def _select_only(obj, index):
    if not obj or not obj.data.shape_keys:
        return
    blocks = obj.data.shape_keys.key_blocks
    if index < 0 or index >= len(blocks):
        return
    _selection[obj.name] = {blocks[index].name}


def _toggle(obj, index):
    if not obj or not obj.data.shape_keys:
        return
    blocks = obj.data.shape_keys.key_blocks
    if index < 0 or index >= len(blocks):
        return
    name = blocks[index].name
    sel = set(_selection.get(obj.name, set()))
    if name in sel:
        sel.discard(name)
    else:
        sel.add(name)
    _selection[obj.name] = sel


def _select_range(obj, from_index, to_index):
    if not obj or not obj.data.shape_keys:
        return
    blocks = obj.data.shape_keys.key_blocks
    lo = max(0, min(from_index, to_index))
    hi = min(len(blocks) - 1, max(from_index, to_index))
    names = {blocks[i].name for i in range(lo, hi + 1)}
    _selection[obj.name] = set(_selection.get(obj.name, set())) | names


def _is_selected(obj, index):
    # During a batch removal the UI does not need per-row selection
    # state, and rebuilding it via _get_selection() is O(N) per call.
    #
    # This path bypasses _get_selection(): the live-name intersection
    # it performs costs O(N) per call and would make a full redraw
    # O(N^2). Stale names left in _selection are harmless here, since
    # a name that no longer exists can never match blocks[index].name.
    if _batch_operation:
        return False
    if not obj or not obj.data.shape_keys:
        return False
    sel = _selection.get(obj.name)
    if not sel:
        return False
    blocks = obj.data.shape_keys.key_blocks
    if index < 0 or index >= len(blocks):
        return False
    return blocks[index].name in sel


def _clear_selection(obj):
    if obj:
        _selection.pop(obj.name, None)


def _get_anchor(obj):
    return _anchor.get(obj.name) if obj else None


def _set_anchor(obj, index):
    if obj:
        _anchor[obj.name] = index


def _remove_blocked_by_lock(obj):
    """True if the current delete target includes any locked key.

    Blender's built-in shape_key_remove raises a RuntimeError when the
    active key is locked, so a locked row can never be removed anyway.
    We mirror the operator's targeting logic here so the Remove button
    can be greyed out before the user hits that error.
    """
    if not obj or not obj.data.shape_keys:
        return False

    blocks = obj.data.shape_keys.key_blocks
    if not blocks:
        return False

    # Fast path: no raw selection means the active key is the sole
    # target, and that case never needs the O(N) live-name filter
    # _get_selection performs. This is the common path during normal
    # panel redraws. Basis is not special-cased here: if the user
    # locked it, Remove should grey out the same way it would for
    # any other locked row.
    raw_sel = _selection.get(obj.name)
    if not raw_sel:
        idx = obj.active_shape_key_index
        if idx < 0 or idx >= len(blocks):
            return False
        return blocks[idx].lock_shape

    sel = raw_sel & _live_names(obj)
    # Basis is excluded from the batch target set: the batch path
    # deletes by index, and index 0 cannot be removed without
    # invalidating the whole key data block. A single-click on Basis
    # never reaches this branch (raw_sel is empty for it), so the
    # user can still attempt it via the single-delete path, which
    # matches the built-in panel.
    sel.discard(blocks[0].name)
    if len(sel) < 2:
        idx = obj.active_shape_key_index
        if idx < 0 or idx >= len(blocks):
            return False
        return blocks[idx].lock_shape

    targets = [kb for kb in blocks if kb.name in sel]
    # The batch-remove path skips locked keys and still deletes the
    # unlocked ones, so it only fails when every target is locked.
    # Using any() here would grey the button out for a mixed
    # selection that the operator can actually handle.
    return bool(targets) and all(kb.lock_shape for kb in targets)


def _resolve_bulk_targets(obj):
    """Return the key blocks a bulk lock / mute action should touch.

    When two or more keys are selected the action is scoped to that
    selection, matching the way the custom Remove button behaves.
    With one or zero selected, the action falls back to every key so
    the old "All" behaviour stays reachable when nothing is selected.

    Basis (index 0) is always excluded: locking or muting it has no
    useful effect, and the built-in list does not expose those
    toggles on the Basis row either.
    """
    if not obj or not obj.data.shape_keys:
        return []

    key_blocks = obj.data.shape_keys.key_blocks
    if len(key_blocks) <= 1:
        return []

    sel = _get_selection(obj)
    if len(sel) >= 2:
        return [kb for kb in key_blocks[1:] if kb.name in sel]
    return list(key_blocks[1:])


def _in_edit_mode(obj):
    """True when the active object is in Edit Mode.

    The built-in Shape Keys panel gates add / remove / move on Object
    Mode because the underlying operators poll only there. The custom
    operators in this plugin mirror that behaviour: the panel greys
    the buttons out and each operator rejects the call, so a script
    that invokes them directly gets the same result as the UI.
    """
    return bool(obj and obj.mode == 'EDIT')


# =====================================================================
# Rename helpers (R / L suffix, driver swap)
# =====================================================================

def store_driver_data(driver_fcurve):
    """Snapshot a driver's type, expression, and variables."""
    if not driver_fcurve or not driver_fcurve.driver:
        return None

    driver = driver_fcurve.driver
    data = {
        'type': driver.type,
        'expression': driver.expression,
        'variables': [],
    }

    for var in driver.variables:
        var_data = {
            'name': var.name,
            'type': var.type,
            'targets': [],
        }
        for target in var.targets:
            target_data = {
                'id': target.id,
                'data_path': target.data_path,
            }
            if hasattr(target, 'bone_target'):
                target_data['bone_target'] = target.bone_target
            if hasattr(target, 'transform_type'):
                target_data['transform_type'] = target.transform_type
            if hasattr(target, 'transform_space'):
                target_data['transform_space'] = target.transform_space
            var_data['targets'].append(target_data)
        data['variables'].append(var_data)

    return data


def apply_driver_data(driver_fcurve, data):
    """Restore a snapshot produced by store_driver_data()."""
    if not driver_fcurve or not driver_fcurve.driver or not data:
        return

    driver = driver_fcurve.driver
    driver.type = data['type']
    driver.expression = data['expression']

    while driver.variables:
        driver.variables.remove(driver.variables[0])

    for var_data in data['variables']:
        new_var = driver.variables.new()
        new_var.name = var_data['name']
        new_var.type = var_data['type']
        for i, target_data in enumerate(var_data['targets']):
            if i < len(new_var.targets):
                new_target = new_var.targets[i]
                new_target.id = target_data['id']
                new_target.data_path = target_data['data_path']
                if 'bone_target' in target_data:
                    new_target.bone_target = target_data['bone_target']
                if 'transform_type' in target_data:
                    new_target.transform_type = target_data['transform_type']
                if 'transform_space' in target_data:
                    new_target.transform_space = \
                        target_data['transform_space']


def _split_rl_suffix(name, r_suffix, l_suffix):
    """Split a shape key name into (base, side).

    `side` is 'R', 'L', or None. A tail is recognised only when it
    matches the configured suffix for that side exactly, so the
    detection follows whatever the user set in the R/L Naming Pair
    dialog. Everything else, including a trailing single 'R' or 'L',
    is treated as part of the base. This keeps names such as
    "Eyebrow" from being misread as having an L suffix.

    The returned base has trailing separators stripped, so appending
    a new suffix does not produce "Brow._L".
    """
    stripped = name.rstrip()
    if not stripped:
        return stripped, None

    if r_suffix and stripped.endswith(r_suffix):
        return stripped[:-len(r_suffix)].rstrip('._ '), 'R'
    if l_suffix and stripped.endswith(l_suffix):
        return stripped[:-len(l_suffix)].rstrip('._ '), 'L'

    return stripped, None


def _rename_locked_to_suffix(obj, target_side, r_suffix, l_suffix):
    """Append the target suffix to every name that has no R/L tail.

    Only names with no recognisable R or L ending are touched. A
    name already ending in R or L is left untouched; use Swap R/L
    to flip those to the other side.

    Target priority:
      1. the multi-selection, if any
      2. the locked keys, if any
      3. the active key
    """
    if not obj or not obj.data.shape_keys:
        return {'CANCELLED'}

    key_blocks = obj.data.shape_keys.key_blocks

    sel = _get_selection(obj)
    if sel:
        targets = [kb for kb in key_blocks[1:] if kb.name in sel]
        if not targets:
            return {'CANCELLED'}
    else:
        locked_keys = [kb for kb in key_blocks[1:] if kb.lock_shape]
        if locked_keys:
            targets = locked_keys
        else:
            idx = obj.active_shape_key_index
            if idx <= 0 or idx >= len(key_blocks):
                return {'CANCELLED'}
            targets = [key_blocks[idx]]

    new_suffix = r_suffix if target_side == 'R' else l_suffix
    renamed = 0
    for kb in targets:
        base, side = _split_rl_suffix(kb.name, r_suffix, l_suffix)
        if side is not None:
            # Already on R or L. Skip; Swap R/L is the tool for
            # changing sides.
            continue
        kb.name = f"{base}{new_suffix}"
        renamed += 1

    if renamed == 0:
        return {'CANCELLED'}
    return {'FINISHED'}


def _swap_locked_r_l_keys(obj, r_suffix, l_suffix):
    """Flip the R/L suffix of every locked shape key.

    A key ending in R becomes L, one ending in L becomes R. When a
    matching pair is locked at once this is equivalent to swapping
    their names; a single locked key simply flips its own suffix.
    Drivers stay bound to the same data and are re-pointed at the
    new name.

    The rename is done in two passes (temporary names first) so that
    two keys in the same batch never collide on their target name.
    """
    if not obj or not obj.data.shape_keys:
        return {'CANCELLED'}

    key_blocks = obj.data.shape_keys.key_blocks

    # Target priority:
    #   1. the multi-selection, if any
    #   2. the locked keys, if any
    #   3. the active key
    sel = _get_selection(obj)
    if sel:
        targets = []
        for kb in key_blocks[1:]:
            if kb.name not in sel:
                continue
            base, side = _split_rl_suffix(kb.name, r_suffix, l_suffix)
            if side in ('R', 'L'):
                targets.append((kb, base, side))
        # A selection made entirely of suffix-less keys has nothing
        # to flip. Bail out rather than silently switching to a
        # different target set the user did not ask for.
        if not targets:
            return {'CANCELLED'}
    else:
        locked_targets = []
        for kb in key_blocks[1:]:
            if not kb.lock_shape:
                continue
            base, side = _split_rl_suffix(kb.name, r_suffix, l_suffix)
            if side in ('R', 'L'):
                locked_targets.append((kb, base, side))

        if locked_targets:
            targets = locked_targets
        else:
            idx = obj.active_shape_key_index
            if idx <= 0 or idx >= len(key_blocks):
                return {'CANCELLED'}
            active = key_blocks[idx]
            base, side = _split_rl_suffix(active.name, r_suffix,
                                          l_suffix)
            if side not in ('R', 'L'):
                return {'CANCELLED'}
            targets = [(active, base, side)]

    shape_keys_obj = obj.data.shape_keys
    has_drivers = bool(
        shape_keys_obj.animation_data
        and shape_keys_obj.animation_data.drivers
    )

    # Snapshot drivers keyed by KeyBlock, so the association survives
    # the renames below.
    saved_drivers = {}
    if has_drivers:
        for kb, _, _ in targets:
            old_path = f'key_blocks["{kb.name}"].value'
            for fcurve in shape_keys_obj.animation_data.drivers:
                if fcurve.data_path == old_path:
                    saved_drivers[kb] = (old_path,
                                         store_driver_data(fcurve))
                    break

    # Pass 1: temporary names to avoid collisions.
    for i, (kb, base, side) in enumerate(targets):
        kb.name = f"__rlswap_{i:02d}_{base}"

    # Pass 2: apply the flipped suffix.
    for kb, base, side in targets:
        new_suffix = l_suffix if side == 'R' else r_suffix
        kb.name = f"{base}{new_suffix}"

    # Re-point every saved driver at its key's new data path.
    if saved_drivers:
        for kb, (old_path, data) in saved_drivers.items():
            new_path = f'key_blocks["{kb.name}"].value'
            try:
                shape_keys_obj.driver_remove(old_path)
            except Exception:
                pass
            new_driver = shape_keys_obj.driver_add(new_path)
            apply_driver_data(new_driver, data)

    return {'FINISHED'}


# =====================================================================
# draw_item patch for MESH_UL_shape_keys
# =====================================================================

_original_draw_item = None


def _draw_item_custom(self, context, layout, data, item, icon,
                      active_data, active_propname, index):
    obj = active_data
    key_block = item

    # Keep our selection set in sync with the active row. When the
    # user clicks a row's name Blender only updates
    # active_shape_key_index; we mirror that into a single-selection
    # so the remove button never targets the wrong keys.
    #
    # Skipped during batch removal: the operator sets
    # active_shape_key_index once per deleted key, and each change
    # would otherwise trigger an O(N) _live_names() rebuild here.
    if not _batch_operation:
        prev_active = _last_active.get(obj.name)
        cur_active = obj.active_shape_key_index
        if prev_active != cur_active:
            _last_active[obj.name] = cur_active
            # Clicking a row's name only changes active_shape_key_index,
            # so mirror it into a single-selection. This is what makes
            # a plain click fall back to the traditional behaviour and
            # drop any explicit multi-selection the user had built up.
            #
            # Our own operators update _last_active themselves before
            # touching active_shape_key_index, so this path only fires
            # for clicks on the name column and for scripts that drive
            # the index directly.
            if cur_active > 0:
                _select_only(obj, cur_active)
                _set_anchor(obj, cur_active)
            else:
                _clear_selection(obj)

    is_drop_target = (
        _drag_state["active"]
        and _drag_state["obj_name"] == obj.name
        and _drag_state["target"] == index
    )

    row = layout.row(align=True)

    # Basis (index 0) is structural: it cannot be removed, reordered
    # or locked, so it does not get a grip handle or a selection
    # toggle. Drawing empty placeholders keeps the name column
    # aligned with every other row.
    if index == 0:
        placeholder = row.row(align=True)
        placeholder.enabled = False
        placeholder.label(text="", icon='BLANK1')
        placeholder.label(text="", icon='BLANK1')
    else:
        selected = _is_selected(obj, index)
        # --- Column 1: reorder handle ---
        # Greyed out in Edit Mode, matching the built-in move
        # buttons.
        drag_row = row.row(align=True)
        drag_row.enabled = obj.mode != 'EDIT'
        drag = drag_row.operator(
            "xneko.shape_key_drag",
            text="", icon='GRIP', emboss=False,
        )
        drag.source_index = index

        # --- Column 2: selection icon ---
        sel_icon = ('RESTRICT_SELECT_OFF' if selected
                    else 'RESTRICT_SELECT_ON')
        sel = row.operator(
            "xneko.shape_key_select",
            text="", icon=sel_icon, emboss=False,
        )
        sel.clicked_index = index

    # --- Original Blender content: name / value / mute / lock ---
    split = row.split(factor=0.66, align=False)

    name_cell = split.row()
    if is_drop_target:
        name_cell.alert = True
    name_cell.prop(key_block, "name", text="",
                   emboss=False, icon_value=icon)

    sub = split.row(align=True)
    sub.emboss = 'NONE_OR_STATUS'

    if key_block.mute or (
        obj.mode == 'EDIT'
        and not (obj.use_shape_key_edit_mode and obj.type == 'MESH')
    ):
        split.active = False

    if not item.id_data.use_relative:
        sub.prop(key_block, "frame", text="")
    elif index > 0:
        sub.prop(key_block, "value", text="")
        # Per-row 0/1 toggle. Independent from the multi-select set:
        # it always acts on this row's key only.
        toggle_icon = ('RADIOBUT_ON' if key_block.value > 0.0
                       else 'RADIOBUT_OFF')
        toggle = sub.operator(
            "xneko.shape_key_value_toggle",
            text="", icon=toggle_icon, emboss=False,
        )
        toggle.index = index
    else:
        sub.label(text="")

    sub.prop(key_block, "mute", text="", emboss=False)
    sub.prop(key_block, "lock_shape", text="", emboss=False)


def _install_draw_item_patch():
    global _original_draw_item
    list_cls = getattr(bpy.types, "MESH_UL_shape_keys", None)
    if list_cls is None:
        print("[XNeko] MESH_UL_shape_keys not found; patch skipped")
        return
    if list_cls.draw_item is _draw_item_custom:
        return
    if _original_draw_item is None:
        _original_draw_item = list_cls.draw_item
    list_cls.draw_item = _draw_item_custom


def _remove_draw_item_patch():
    global _original_draw_item
    list_cls = getattr(bpy.types, "MESH_UL_shape_keys", None)
    if list_cls is None or _original_draw_item is None:
        return
    list_cls.draw_item = _original_draw_item
    _original_draw_item = None


# =====================================================================
# Shape Keys panel (full replacement, based on the built-in draw)
# =====================================================================

_original_panel_draw = None


def _draw_shape_keys_panel_custom(self, context):
    _maybe_prune_state()

    layout = self.layout
    ob = context.object
    if ob is None or ob.data is None:
        return
    key = ob.data.shape_keys

    if key is None:
        # No shape keys on this object: hand the draw over to the
        # unpatched Blender panel so the empty state stays byte-for-
        # byte identical to stock. This also keeps the layout in
        # sync if a future Blender build changes the placeholder.
        if _original_panel_draw is not None:
            _original_panel_draw(self, context)
        return

    kb = ob.active_shape_key

    enable_edit = ob.mode != 'EDIT'
    enable_edit_value = False
    enable_pin = False

    if enable_edit or (ob.use_shape_key_edit_mode and ob.type == 'MESH'):
        enable_pin = True
        if ob.show_only_shape_key is False:
            enable_edit_value = True

    # List height tracks the button column. Both halves are tunable
    # via the module constants near the top of the file.
    list_rows = _LIST_ROWS_BASE + (
        _RENAME_EXTRA_ROWS if _rename_expand else 0
    )

    row = layout.row()
    row.template_list(
        "SKP_UL_keys", "",
        key, "key_blocks",
        ob, "active_shape_key_index",
        rows=list_rows,
    )

    col = row.column()

    # Structural operations (add / remove / move / reorder) require
    # Object Mode, matching the built-in panel. The buttons are
    # greyed out in Edit Mode, and each operator rejects the call
    # itself so the behaviour is identical from a script.
    structure_enabled = not _in_edit_mode(ob)

    # Add / Remove (grouped together)
    sub = col.column(align=True)
    add_row = sub.row()
    add_row.enabled = structure_enabled
    add_row.operator("xneko.shape_key_add_clean", icon='ADD', text="")

    # Grey out Remove while any locked key is in the target set.
    # Blender's built-in remove raises an error on locked keys, so
    # blocking the click up front avoids a RuntimeError traceback.
    locked = _remove_blocked_by_lock(ob)
    remove_row = sub.row()
    remove_row.enabled = structure_enabled and not locked
    if locked:
        remove_row.operator("xneko.shape_key_remove_locked",
                            icon='REMOVE', text="")
    else:
        remove_row.operator("xneko.shape_key_remove_custom",
                            icon='REMOVE', text="")

    col.separator()

    # New shape key from the current mix, placed below the active key.
    new_row = col.row()
    new_row.enabled = structure_enabled
    new_row.operator("xneko.shape_key_new_from_mix",
                     icon='NLA_PUSHDOWN', text="")

    col.separator()

    # Specials menu
    col.menu("MESH_MT_shape_key_context_menu",
             icon='DOWNARROW_HLT', text="")

    col.separator()

    # Move up / down (restored from the built-in panel layout).
    move_row = col.column(align=True)
    move_row.enabled = structure_enabled
    move_row.operator("object.shape_key_move",
                      icon='TRIA_UP', text="").type = 'UP'
    move_row.operator("object.shape_key_move",
                      icon='TRIA_DOWN', text="").type = 'DOWN'

    # Collapsible rename tools. Collapsed by default so the panel
    # stays compact. The expand state lives in a module-level global
    # and is therefore never written to the .blend file.
    #
    # Rendered as a bare icon button, matching the Specials and Move
    # buttons above it: no label, no wrapper row. A wrapper row plus
    # a text label is what caused the button to stretch across the
    # whole panel in the previous version.
    col.separator()
    col.operator(
        "xneko.shape_key_toggle_rename_tools",
        text="",
        icon=('TRIA_DOWN' if _rename_expand else 'TRIA_RIGHT'),
        emboss=False,
    )

    if _rename_expand:
        # Lock / unlock first: they get used far more often than the
        # rename tools, so they sit at the top of the expanded block.
        lock_col = col.column(align=True)
        lock_col.operator("xneko.shape_key_lock_all",
                          text="", icon='LOCKED')
        lock_col.operator("xneko.shape_key_unlock_all",
                          text="", icon='UNLOCKED')

        visibility_col = col.column(align=True)
        visibility_col.operator("xneko.shape_key_enable_all",
                                text="", icon='CHECKBOX_HLT')
        visibility_col.operator("xneko.shape_key_disable_all",
                                text="", icon='CHECKBOX_DEHLT')
    
        col.separator()

        rename_col = col.column(align=True)
        rename_col.operator("xneko.shape_key_rename_r",
                            text="", icon='EVENT_R')
        rename_col.operator("xneko.shape_key_rename_l",
                            text="", icon='EVENT_L')
        rename_col.operator("xneko.shape_key_swap_rl",
                            text="", icon='FILE_REFRESH')
        rename_col.operator("xneko.shape_key_rename_settings",
                            text="", icon='PREFERENCES')

    # Filter syntax hint, shown while the background poll is still
    # watching the cursor. The poll stops once the cursor leaves the
    # Properties area or the hard time cap expires, which hides this
    # box on the next redraw.
    if _hint_poll_active:
        hint_box = layout.box()
        hint_col = hint_box.column(align=True)
        hint_col.scale_y = 0.85
        hint_col.label(text="Catgirl * Wifu  =  Catgirl and Wifu")
        hint_col.label(text="Catgirl / Wifu  =  Catgirl or Wifu")

    # --- Reorder-mode hint, right below the list ---
    # Only draw the hint in the panel whose object actually owns the
    # active drag. Without the obj_name check, a second Properties
    # area pointed at another object would also show the hint.
    #
    # Placed here rather than at the bottom of the panel so the keys
    # the user is currently dragging stay visible while the hint is
    # on screen: the value / vertex-group fields below can push the
    # list far enough up that the last rows would scroll out of view
    # if the hint lived underneath them.
    if _drag_state["active"] and _drag_state["obj_name"] == ob.name:
        box = layout.box()
        box.label(text="Reorder Mode", icon='TRIA_RIGHT')

        row = box.row(align=True)
        c = row.column(align=True)
        c.ui_units_x = 1.6
        c.label(text="", icon='MOUSE_MMB_SCROLL')
        row.label(text="Move")

        row = box.row(align=True)
        c = row.column(align=True)
        c.ui_units_x = 1.6
        c.label(text="", icon='EVENT_RETURN')
        c = row.column(align=True)
        c.ui_units_x = 1.6
        c.label(text="", icon='MOUSE_LMB')
        row.label(text="Confirm")

        row = box.row(align=True)
        c = row.column(align=True)
        c.ui_units_x = 1.6
        c.label(text="", icon='EVENT_ESC')
        c = row.column(align=True)
        c.ui_units_x = 1.6
        c.label(text="", icon='MOUSE_RMB')
        row.label(text="Cancel")

    split = layout.split(factor=0.4)
    row = split.row()
    row.enabled = enable_edit
    row.prop(key, "use_relative", text="Relative")

    row = split.row()
    row.alignment = 'RIGHT'

    sub = row.row(align=True)
    sub.label()
    subsub = sub.row(align=True)
    subsub.active = enable_pin
    subsub.prop(ob, "show_only_shape_key", text="",
                icon='SOLO_OFF', toggle=True)
    sub.prop(ob, "use_shape_key_edit_mode", text="")

    sub = row.row()
    if key.use_relative:
        sub.operator("object.shape_key_clear", icon='X', text="")
    else:
        sub.operator("object.shape_key_retime",
                     icon='RECOVER_LAST', text="")

    layout.use_property_split = True
    if key.use_relative:
        if kb is not None and ob.active_shape_key_index != 0:
            row = layout.row()
            row.active = enable_edit_value
            row.prop(kb, "value")

            col = layout.column()
            sub = col.column(align=True)
            sub.active = enable_edit_value
            sub.prop(kb, "slider_min", text="Range Min")
            sub.prop(kb, "slider_max", text="Max")

            col.prop_search(kb, "vertex_group",
                            ob, "vertex_groups", text="Vertex Group")
            col.prop_search(kb, "relative_key",
                            key, "key_blocks", text="Relative To")
    else:
        layout.prop(kb, "interpolation")
        row = layout.column()
        row.active = enable_edit_value
        row.prop(key, "eval_time")

    if ob.type == 'MESH':
        layout.prop(ob, "add_rest_position_attribute")


def _install_panel_patch():
    global _original_panel_draw
    panel_cls = getattr(bpy.types, "DATA_PT_shape_keys", None)
    if panel_cls is None:
        print("[XNeko] DATA_PT_shape_keys not found; panel patch skipped")
        return
    if panel_cls.draw is _draw_shape_keys_panel_custom:
        return
    if _original_panel_draw is None:
        _original_panel_draw = panel_cls.draw
    panel_cls.draw = _draw_shape_keys_panel_custom


def _remove_panel_patch():
    global _original_panel_draw
    panel_cls = getattr(bpy.types, "DATA_PT_shape_keys", None)
    if panel_cls is None or _original_panel_draw is None:
        return
    panel_cls.draw = _original_panel_draw
    _original_panel_draw = None


# =====================================================================
# Shape key list (custom UIList with a name filter)
# =====================================================================

# Last filter text the UIList saw during a draw. filter_items runs on
# every redraw, so after the list has been drawn this holds the
# current search text, letting the panel decide whether to show the
# syntax hint underneath the list.
_last_filter_text = ""

# The syntax hint is hidden by a background poll rather than a fixed
# delay. Blender's native UIList search bar does not expose focus /
# blur events to Python, so "hide when the user is done typing" has
# to be approximated. The closest signal is the mouse cursor: once
# it leaves the Properties area, the user has clearly moved on. A
# time cap handles the case where the cursor stays parked inside the
# panel forever.
_hint_poll_active = False
_filter_hint_until = 0.0

# Seconds between mouse-position checks while the hint is on screen.
_HINT_POLL_INTERVAL = 0.2

# Hard cap on how long the hint can stay visible, in seconds.
_HINT_MAX_DURATION = 8.0


def _mouse_in_properties():
    """True if the cursor is currently inside any Properties area."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        # Background mode and some scripted contexts have no window
        # manager. Treat that as "cursor is elsewhere" so the hint
        # hides rather than throwing inside the timer.
        return False
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'PROPERTIES':
                continue
            for region in area.regions:
                # region.mouse_x / mouse_y are relative to that
                # region, so the cursor is inside it when both fall
                # within its width and height.
                if (0 <= region.mouse_x < region.width
                        and 0 <= region.mouse_y < region.height):
                    return True
    return False


def _redraw_properties():
    """Tag every Properties area for redraw."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()


def _hint_poll():
    """Hide the hint once the cursor leaves or the cap expires."""
    global _hint_poll_active
    if not _last_filter_text:
        _hint_poll_active = False
        return None
    if (_mouse_in_properties()
            and time.time() < _filter_hint_until):
        # Returning a float reschedules the timer.
        return _HINT_POLL_INTERVAL

    # Cursor is gone (or the cap expired): redraw so the hint
    # disappears on the next panel draw.
    _hint_poll_active = False
    _redraw_properties()
    return None


def _start_hint_poll():
    """Start the mouse-position poll if it is not already running."""
    global _hint_poll_active, _filter_hint_until
    _filter_hint_until = time.time() + _HINT_MAX_DURATION
    if _hint_poll_active:
        return
    _hint_poll_active = True
    bpy.app.timers.register(
        _hint_poll,
        first_interval=_HINT_POLL_INTERVAL,
    )


def _stop_hint_poll():
    """Cancel the poll and hide the hint immediately."""
    global _hint_poll_active
    if not _hint_poll_active:
        return
    _hint_poll_active = False
    try:
        bpy.app.timers.unregister(_hint_poll)
    except Exception:
        pass


def _get_filter_matcher(text):
    """Return a predicate `name -> bool`, or None for "no filter".

    The filter syntax is intentionally minimal:

      * "A * B"  -> the name must contain both A and B
      * "A / B"  -> the name must contain A or B
      * "A * B / C" -> A, and (B or C): AND binds tighter than OR

    Both operators need a space on each side, so a shape key whose
    name happens to contain a bare "*" or "/" is not accidentally
    split. Every term is a case-insensitive substring match, not a
    regular expression, which keeps the syntax easy to remember.
    """
    if not text or not text.strip():
        return None

    # Split on the AND operator first so it binds tighter than OR,
    # matching the usual boolean precedence: "A * B / C" reads as
    # "(A) AND (B OR C)".
    and_groups = []
    for and_part in text.split(" * "):
        or_group = [
            needle.strip().lower()
            for needle in and_part.split(" / ")
            if needle.strip()
        ]
        if or_group:
            and_groups.append(or_group)

    if not and_groups:
        return None

    def match(name):
        low = name.lower()
        for or_group in and_groups:
            if not any(needle in low for needle in or_group):
                return False
        return True

    return match


class SKP_UL_keys(bpy.types.UIList):
    """Shape key list with the native Blender 4.5 filter bar.

    The class name doubles as the UIList's bl_idname, so it must be
    globally unique across every addon. The "SKP_" prefix keeps it
    out of the way of other tools that might also define a shape
    key list.

    Row layout is delegated to `_draw_item_custom`, the same
    function the panel patch installs on the built-in UIList, so
    the two code paths cannot drift apart.
    """

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        _draw_item_custom(self, context, layout, data, item, icon,
                          active_data, active_propname, index)

    def filter_items(self, context, data, propname):
        global _last_filter_text
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)

        # `filter_name` is populated by Blender's native filter bar.
        # getattr guards against a Blender build without the field.
        text = getattr(self, "filter_name", "")

        # Only react when the text actually changed. filter_items runs
        # on every redraw, so restarting the poll on every call would
        # keep the hint alive forever.
        if text != _last_filter_text:
            _last_filter_text = text
            if text:
                _start_hint_poll()
            else:
                _stop_hint_poll()

        matcher = _get_filter_matcher(text)
        if matcher is None:
            return flags, []

        for i, kb in enumerate(items):
            if not matcher(kb.name):
                flags[i] = 0

        return flags, []


# =====================================================================
# Select operator
# =====================================================================

class XNEKO_OT_shape_key_select(bpy.types.Operator):
    bl_idname = "xneko.shape_key_select"
    bl_label = "Select Shape Key"
    bl_description = "Click to select. Shift for range, Ctrl for multi-select"
    # INTERNAL keeps this UI-only operator out of the F3 search. No
    # UNDO flag: the operator only touches the module-level selection
    # set and active_shape_key_index, so pushing an undo step here
    # would make Ctrl+Z step through selections before it reached the
    # user's last real edit.
    bl_options = {'INTERNAL'}

    clicked_index: IntProperty(default=-1)

    def invoke(self, context, event):
        obj = context.object
        if not obj or not obj.data.shape_keys:
            return {'CANCELLED'}

        blocks = obj.data.shape_keys.key_blocks
        if self.clicked_index < 0 or self.clicked_index >= len(blocks):
            return {'CANCELLED'}

        index = self.clicked_index
        name = blocks[index].name

        if event.shift:
            anchor = _get_anchor(obj)
            if anchor is None:
                anchor = index
            _select_range(obj, anchor, index)
        elif event.ctrl:
            _toggle(obj, index)
            _set_anchor(obj, index)
        else:
            sel = _get_selection(obj)
            if sel == {name}:
                _clear_selection(obj)
            else:
                _select_only(obj, index)
            _set_anchor(obj, index)

        obj.active_shape_key_index = index
        # Keep _last_active in sync so the next draw does not re-sync
        # our own selection back to a single row.
        _last_active[obj.name] = index
        return {'FINISHED'}


# =====================================================================
# Custom remove operator (single / batch depending on selection size)
# =====================================================================

class XNEKO_OT_shape_key_remove_locked(bpy.types.Operator):
    """Placeholder operator shown while the delete target is locked.

    The panel swaps to this operator when _remove_blocked_by_lock()
    returns True. Its only purpose is to carry a different
    bl_description so hovering the greyed-out button explains why it
    is disabled.
    """
    bl_idname = "xneko.shape_key_remove_locked"
    bl_label = "Remove Shape Key"
    bl_description = "Locked shape keys cannot be removed"
    bl_options = {'REGISTER'}

    def execute(self, context):
        self.report(
            {'WARNING'},
            "Locked shape keys cannot be removed",
        )
        return {'CANCELLED'}


class XNEKO_OT_shape_key_remove_custom(bpy.types.Operator):
    bl_idname = "xneko.shape_key_remove_custom"
    bl_label = "Remove Shape Key"
    bl_description = (
        "Remove the active shape key. If two or more keys are selected, "
        "remove all selected keys at once"
    )
    bl_options = {'REGISTER', 'UNDO'}

    all: BoolProperty(default=False)

    def execute(self, context):
        obj = context.object
        if not obj or not obj.data.shape_keys:
            return {'CANCELLED'}

        # Structural edits require Object Mode. The button is greyed
        # out in Edit Mode, but a script can still invoke the operator
        # directly, so it is rejected here too.
        if _in_edit_mode(obj):
            self.report({'INFO'},
                        "Removing shape keys requires Object Mode")
            return {'CANCELLED'}

        if self.all:
            # "Remove all" from the context menu keeps the original
            # behaviour.
            return bpy.ops.object.shape_key_remove(all=True)

        blocks = obj.data.shape_keys.key_blocks
        if not blocks:
            return {'CANCELLED'}

        sel = _get_selection(obj)
        sel.discard(blocks[0].name)   # Never touch Basis

        if len(sel) >= 2:
            # Batch delete: walk indices from highest to lowest so
            # the indices of the rows we still need to remove do
            # not shift. Locked keys are skipped, so a selection
            # that mixes locked and unlocked keys still deletes
            # the unlocked ones without tripping Blender's
            # RuntimeError.
            indices = [
                i for i, kb in enumerate(blocks)
                if kb.name in sel and not kb.lock_shape
            ]
            indices.sort(reverse=True)
            if not indices:
                self.report({'WARNING'},
                            "Locked shape keys cannot be removed")
                return {'CANCELLED'}

            global _batch_operation
            _batch_operation = True
            wm = context.window_manager
            total = len(indices)
            wm.progress_begin(0, total)
            try:
                for n, i in enumerate(indices):
                    obj.active_shape_key_index = i
                    bpy.ops.object.shape_key_remove()
                    # Throttle progress updates to reduce redraws.
                    if (n & 3) == 0 or n == total - 1:
                        wm.progress_update(n + 1)
            finally:
                try:
                    wm.progress_end()
                finally:
                    _batch_operation = False

            _clear_selection(obj)
            # Record the (Blender-corrected) active index so the next
            # draw_item sees prev_active == cur_active and does not
            # re-select a single row from the cleared selection.
            _last_active[obj.name] = obj.active_shape_key_index
            return {'FINISHED'}

        # Single selection or none: original behaviour, with a guard.
        # Only locked keys are intercepted up front, because that is
        # the one case the operator can recognise on its own and give
        # a clean message for. Everything else, including Basis, is
        # handed to the native operator so the behaviour matches the
        # built-in panel exactly. A RuntimeError is caught rather than
        # allowed to bubble: it would otherwise abort the whole click
        # and print a traceback, even though the user only needs to
        # see the reason spelled out.
        idx = obj.active_shape_key_index
        if idx < 0 or idx >= len(blocks):
            return {'CANCELLED'}
        if blocks[idx].lock_shape:
            self.report({'WARNING'},
                        "Locked shape keys cannot be removed")
            return {'CANCELLED'}
        try:
            return bpy.ops.object.shape_key_remove(all=False)
        except RuntimeError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


# =====================================================================
# Clean add (zero existing values so the new key starts from Basis)
# =====================================================================

class XNEKO_OT_shape_key_add_clean(bpy.types.Operator):
    bl_idname = "xneko.shape_key_add_clean"
    bl_label = "Add Shape Key"
    bl_description = (
        "Add a new shape key directly below the active key. Existing "
        "shape key values are temporarily zeroed so the new key "
        "starts from Basis instead of the current mix"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or not obj.data.shape_keys:
            # No shape keys yet: the native operator creates Basis plus
            # the first key, and there is nothing to reposition.
            return bpy.ops.object.shape_key_add()

        if _in_edit_mode(obj):
            return bpy.ops.object.shape_key_add()

        blocks = obj.data.shape_keys.key_blocks

        # Remember where the new key should land before the add call
        # runs: shape_key_add appends at the bottom and moves the
        # active index there, so the original row would be lost.
        insert_after = obj.active_shape_key_index
        if insert_after < 0 or insert_after >= len(blocks):
            insert_after = len(blocks) - 1
        target_index = insert_after + 1

        saved = [(kb, kb.value) for kb in blocks[1:]]

        # Fast path: when every key is already at zero the clean pass
        # is a no-op, so call the native operator directly. Skipping
        # the zero/restore dance avoids momentarily tripping driver
        # or NLA evaluation, which can flash the mesh for a frame
        # under some expressions.
        if not any(value for _, value in saved):
            result = bpy.ops.object.shape_key_add()
        else:
            for kb, _ in saved:
                kb.value = 0.0
            try:
                result = bpy.ops.object.shape_key_add()
            finally:
                for kb, value in saved:
                    kb.value = value

        if 'FINISHED' not in result:
            return result

        # shape_key_add always appends at the bottom and makes the new
        # key active. Walk it up until it sits directly below the row
        # that was active before the add, so the new key lands next to
        # the one the user was working on instead of at the end of a
        # long list.
        #
        # Each shape_key_move call carries UNDO, so the repositioning
        # leaves N steps on the undo stack. A named step after the
        # moves gives the user a single landmark in the Undo History
        # popup to jump back to without clicking Ctrl+Z N times.
        moved = False
        while obj.active_shape_key_index > target_index:
            bpy.ops.object.shape_key_move(type='UP')
            moved = True
        if moved:
            bpy.ops.ed.undo_push(message="Add Shape Key")

        new_active = obj.active_shape_key_index
        _last_active[obj.name] = new_active
        _select_only(obj, new_active)
        _set_anchor(obj, new_active)

        return result


# =====================================================================
# New shape from mix
# =====================================================================

class XNEKO_OT_shape_key_new_from_mix(bpy.types.Operator):
    bl_idname = "xneko.shape_key_new_from_mix"
    bl_label = "New Shape From Mix"
    bl_description = (
        "Create a new shape key from the mix of the currently "
        "selected shape keys and place it right below the active "
        "key. With no selection, only the active key is mixed"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or not obj.data.shape_keys:
            return {'CANCELLED'}

        if _in_edit_mode(obj):
            self.report({'INFO'},
                        "Creating shape keys requires Object Mode")
            return {'CANCELLED'}

        blocks = obj.data.shape_keys.key_blocks
        if not blocks:
            return {'CANCELLED'}

        active_index = obj.active_shape_key_index
        if active_index < 0 or active_index >= len(blocks):
            return {'CANCELLED'}

        # The new key goes into the slot right after the active key.
        target_index = active_index + 1

        # Which keys take part in the mix. With nothing selected we
        # fall back to the active key only, so the button always has a
        # well-defined target instead of silently mixing everything.
        sel = _get_selection(obj)
        if not sel:
            sel = {blocks[active_index].name}

        # Blender's shape_key_add(from_mix=True) reads the live value
        # of every key block, so temporarily zero out the ones that are
        # not part of the selection and restore them afterwards. Basis
        # is skipped: its value is read-only.
        saved_values = []
        for kb in blocks[1:]:
            if kb.name in sel:
                continue
            saved_values.append((kb, kb.value))
            kb.value = 0.0

        try:
            bpy.ops.object.shape_key_add(from_mix=True)
            # shape_key_add always appends at the end and makes the new
            # key active. Walk it up until it lands at target_index.
            # See XNEKO_OT_shape_key_add_clean for why the named push
            # is needed after the loop.
            moved = False
            while obj.active_shape_key_index > target_index:
                bpy.ops.object.shape_key_move(type='UP')
                moved = True
            if moved:
                bpy.ops.ed.undo_push(message="New Shape From Mix")
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        finally:
            for kb, value in saved_values:
                kb.value = value

        # Mirror the new active key into our own selection state so the
        # next draw_item does not restore the pre-operation selection
        # and leave the delete button pointing at the wrong rows.
        new_active = obj.active_shape_key_index
        _last_active[obj.name] = new_active
        _select_only(obj, new_active)
        _set_anchor(obj, new_active)

        return {'FINISHED'}


# =====================================================================
# Per-row value toggle
# =====================================================================

class XNEKO_OT_shape_key_value_toggle(bpy.types.Operator):
    bl_idname = "xneko.shape_key_value_toggle"
    bl_label = "Toggle Shape Key Value"
    bl_description = (
        "Toggle this shape key's value between 0.0 and 1.0. If the "
        "value is already animated, a keyframe is inserted on the "
        "current frame so the change sticks"
    )
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        obj = context.object
        if not obj or not obj.data.shape_keys:
            return {'CANCELLED'}

        blocks = obj.data.shape_keys.key_blocks
        if self.index <= 0 or self.index >= len(blocks):
            return {'CANCELLED'}

        key_block = blocks[self.index]

        key_block.value = 0.0 if key_block.value > 0.0 else 1.0

        # Only insert a keyframe when the path is already animated, so
        # a static key does not suddenly pick up an fcurve.
        shape_keys = obj.data.shape_keys
        data_path = f'key_blocks["{key_block.name}"].value'
        if _is_value_animated(shape_keys, data_path):
            shape_keys.keyframe_insert(
                data_path=data_path,
                frame=context.scene.frame_current,
            )

        return {'FINISHED'}


# =====================================================================
# Animation helpers
# =====================================================================

def _is_value_animated(shape_keys, data_path):
    """True if the given shape key value path is already animated.

    Handles both animation layouts:

      * legacy actions, where fcurves hang directly off
        animation_data.action;
      * slotted actions (Blender 4.4+), where the fcurves live inside
        a channelbag on a layer strip beneath action.layers.

    When animation_data.action is None there is nothing driving the
    value, so both layouts can be skipped.
    """
    anim_data = shape_keys.animation_data
    if anim_data is None:
        return False

    action = anim_data.action
    if action is not None:
        # Legacy layout: action.fcurves.
        for fc in getattr(action, "fcurves", []):
            if fc.data_path == data_path:
                return True

        # Slotted layout: layers -> strips -> channelbags -> fcurves.
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for bag in getattr(strip, "channelbags", []):
                    for fc in getattr(bag, "fcurves", []):
                        if fc.data_path == data_path:
                            return True

    # If the action is None, slotted keyframes cannot exist: the fcurve
    # always lives on a layer strip inside an action, so there is
    # nothing else to scan here.
    return False


# =====================================================================
# Rename tools
# =====================================================================

class XNEKO_OT_shape_key_lock_all(bpy.types.Operator):
    bl_idname = "xneko.shape_key_lock_all"
    bl_label = "Lock Shape Keys"
    bl_description = (
        "Lock the selected shape keys, or every shape key when "
        "fewer than two are selected. Basis is never locked"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _resolve_bulk_targets(context.object)
        if not targets:
            return {'CANCELLED'}

        for kb in targets:
            kb.lock_shape = True
        return {'FINISHED'}


class XNEKO_OT_shape_key_unlock_all(bpy.types.Operator):
    bl_idname = "xneko.shape_key_unlock_all"
    bl_label = "Unlock Shape Keys"
    bl_description = (
        "Unlock the selected shape keys, or every shape key when "
        "fewer than two are selected"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _resolve_bulk_targets(context.object)
        if not targets:
            return {'CANCELLED'}

        for kb in targets:
            kb.lock_shape = False
        return {'FINISHED'}


class XNEKO_OT_shape_key_enable_all(bpy.types.Operator):
    bl_idname = "xneko.shape_key_enable_all"
    bl_label = "Enable Shape Keys"
    bl_description = (
        "Unmute the selected shape keys, or every shape key when "
        "fewer than two are selected. Basis is never affected"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _resolve_bulk_targets(context.object)
        if not targets:
            return {'CANCELLED'}

        for kb in targets:
            kb.mute = False
        return {'FINISHED'}


class XNEKO_OT_shape_key_disable_all(bpy.types.Operator):
    bl_idname = "xneko.shape_key_disable_all"
    bl_label = "Disable Shape Keys"
    bl_description = (
        "Mute the selected shape keys, or every shape key when "
        "fewer than two are selected. Basis is never affected"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _resolve_bulk_targets(context.object)
        if not targets:
            return {'CANCELLED'}

        for kb in targets:
            kb.mute = True
        return {'FINISHED'}


class XNEKO_OT_shape_key_rename_r(bpy.types.Operator):
    bl_idname = "xneko.shape_key_rename_r"
    bl_label = "Rename to R"
    bl_description = (
        "Append the configured R suffix to every target name that "
        "has no R or L suffix yet. Targets are the selection if any, "
        "otherwise the locked keys, otherwise the active key. Use "
        "Swap R/L to change the side of keys that already have one"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        return _rename_locked_to_suffix(
            context.object, 'R',
            scene.xneko_shape_key_suffix_r,
            scene.xneko_shape_key_suffix_l,
        )


class XNEKO_OT_shape_key_rename_l(bpy.types.Operator):
    bl_idname = "xneko.shape_key_rename_l"
    bl_label = "Rename to L"
    bl_description = (
        "Append the configured L suffix to every target name that "
        "has no R or L suffix yet. Targets are the selection if any, "
        "otherwise the locked keys, otherwise the active key. Use "
        "Swap R/L to change the side of keys that already have one"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        return _rename_locked_to_suffix(
            context.object, 'L',
            scene.xneko_shape_key_suffix_r,
            scene.xneko_shape_key_suffix_l,
        )


class XNEKO_OT_shape_key_swap_rl(bpy.types.Operator):
    bl_idname = "xneko.shape_key_swap_rl"
    bl_label = "Swap R/L"
    bl_description = (
        "Flip the configured R suffix to L, and L to R, on every "
        "target key that carries one of them. Targets are the "
        "selection if any, otherwise the locked keys, otherwise the "
        "active key. Drivers follow their keys across the rename"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        return _swap_locked_r_l_keys(
            context.object,
            scene.xneko_shape_key_suffix_r,
            scene.xneko_shape_key_suffix_l,
        )


class XNEKO_OT_shape_key_toggle_rename_tools(bpy.types.Operator):
    bl_idname = "xneko.shape_key_toggle_rename_tools"
    bl_label = "More Tools"
    bl_description = (
        "Expand or collapse the additional tools section "
        "(rename, lock, unlock)"
    )
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _toggle_rename_expand()
        return {'FINISHED'}


class XNEKO_OT_shape_key_rename_settings(bpy.types.Operator):
    bl_idname = "xneko.shape_key_rename_settings"
    bl_label = "R/L Naming Pair"
    bl_description = (
        "Configure the suffixes used by Rename to R and Rename to L"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # Buffers for the dialog. Editing Scene properties directly from
    # a props dialog can silently drop the last edit when the user
    # clicks OK without letting the field lose focus first, so the
    # values are held here and committed in execute().
    suffix_r: bpy.props.StringProperty(name="Rename to R")
    suffix_l: bpy.props.StringProperty(name="Rename to L")

    def invoke(self, context, event):
        scene = context.scene
        self.suffix_r = scene.xneko_shape_key_suffix_r
        self.suffix_l = scene.xneko_shape_key_suffix_l
        return context.window_manager.invoke_props_dialog(self, width=240)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "suffix_r", text="R Suffix")
        col.prop(self, "suffix_l", text="L Suffix")

        layout.separator()
        note = layout.column(align=True)
        note.scale_y = 0.8
        note.label(text="Suffixes used by Rename R/L and Swap.",
                   icon='INFO')
        note.label(text="Changing them does not rename saved keys.")

    def execute(self, context):
        # Reject configurations that would make the rename tools
        # behave unpredictably:
        #   * an empty suffix would append nothing, so the button
        #     would silently do nothing on a suffix-less key;
        #   * identical R and L suffixes make "which side is this?"
        #     undecidable, and _split_rl_suffix would always answer
        #     'R' because that check runs first.
        if not self.suffix_r or not self.suffix_l:
            self.report({'ERROR'}, "Suffixes cannot be empty")
            return {'CANCELLED'}
        if self.suffix_r == self.suffix_l:
            self.report({'ERROR'}, "R and L suffixes must differ")
            return {'CANCELLED'}

        scene = context.scene
        scene.xneko_shape_key_suffix_r = self.suffix_r
        scene.xneko_shape_key_suffix_l = self.suffix_l
        return {'FINISHED'}


# =====================================================================
# Reorder operator
# =====================================================================

class XNEKO_OT_shape_key_drag(bpy.types.Operator):
    bl_idname = "xneko.shape_key_drag"
    bl_label = "Reorder Shape Key"
    bl_description = (
        "Click to enter reorder mode, then use the mouse wheel to move "
        "the current selection up or down. Left-click or Enter confirms, "
        "right-click or Esc cancels"
    )
    # UNDO so the finished drag is tagged as one user action. Note that
    # the individual object.shape_key_move() calls inside
    # _move_by_delta() also carry UNDO, and Blender exposes no way to
    # suppress an operator's undo push from Python, so stepping back
    # one row at a time via Ctrl+Z is still possible. The named step
    # this flag adds lets the user jump straight to the pre-drag state
    # from the Undo History popup instead.
    bl_options = {'REGISTER', 'UNDO'}

    source_index: IntProperty(default=-1)

    def invoke(self, context, event):
        obj = context.object
        if not obj or not obj.data.shape_keys:
            return {'CANCELLED'}

        if _in_edit_mode(obj):
            self.report({'INFO'},
                        "Reordering shape keys requires Object Mode")
            return {'CANCELLED'}

        blocks = obj.data.shape_keys.key_blocks
        if self.source_index < 0 or self.source_index >= len(blocks):
            return {'CANCELLED'}

        clicked_name = blocks[self.source_index].name
        sel = _get_selection(obj)
        if clicked_name not in sel:
            _select_only(obj, self.source_index)
            _set_anchor(obj, self.source_index)

        self._obj_name = obj.name
        self._initial_index = self.source_index
        self._target_index = self.source_index

        self._last_wheel_time = 0.0
        self._current_step = _read_scroll_step()

        if context.screen:
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()

        context.window_manager.modal_handler_add(self)

        _drag_state["active"] = True
        _drag_state["obj_name"] = obj.name
        _drag_state["target"] = self.source_index

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        obj = bpy.data.objects.get(self._obj_name)
        if not obj or not obj.data.shape_keys:
            self._end_drag(context)
            return {'CANCELLED'}

        max_index = len(obj.data.shape_keys.key_blocks) - 1

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            base = _read_scroll_step()
            max_step = _read_max_scroll_step(base)

            if _read_wheel_acceleration():
                now = time.time()
                dt = now - self._last_wheel_time
                self._last_wheel_time = now

                accel = _read_accel_step()
                fast_dt = _read_wheel_fast_dt()
                slow_dt = _read_wheel_slow_dt()
                if dt < fast_dt:
                    self._current_step = min(
                        self._current_step + accel, max_step)
                elif dt >= slow_dt:
                    self._current_step = base
            else:
                self._current_step = base

            step = self._current_step
            direction = -1 if event.type == 'WHEELUPMOUSE' else 1
            new_target = max(
                0, min(max_index,
                       self._target_index + direction * step))

            if new_target != self._target_index:
                self._target_index = new_target
                _drag_state["active"] = True
                _drag_state["obj_name"] = obj.name
                _drag_state["target"] = new_target
                obj.active_shape_key_index = new_target
                # Keep _last_active in sync so the draw_item sync does
                # not clobber the reorder target.
                _last_active[obj.name] = new_target
                if context.area:
                    context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            try:
                self._commit_drag(context, obj)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
            finally:
                self._end_drag(context)
            return {'FINISHED'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            try:
                self._commit_drag(context, obj)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
            finally:
                self._end_drag(context)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._end_drag(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _end_drag(self, context):
        _drag_state["active"] = False
        _drag_state["obj_name"] = ""
        _drag_state["target"] = -1
        if context.screen:
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()

    def _commit_drag(self, context, obj):
        blocks = obj.data.shape_keys.key_blocks
        max_index = len(blocks) - 1

        sel = _get_selection(obj)
        sel.discard(blocks[0].name)   # Basis cannot be moved
        if not sel:
            return

        selected_indices = [
            i for i, kb in enumerate(blocks) if kb.name in sel
        ]

        delta = self._target_index - self._initial_index
        delta = self._clamp_delta(selected_indices, delta, max_index)
        if delta == 0:
            return

        # Tag the drag as one named step so it shows up in the Undo
        # History popup. The move calls below still push their own
        # steps, but this gives the user a single named landmark to
        # jump back to without stepping through every row.
        bpy.ops.ed.undo_push(message="Reorder Shape Keys")

        self._move_by_delta(obj, selected_indices, delta, max_index)

        new_active = max(0, min(max_index, self._initial_index + delta))
        obj.active_shape_key_index = new_active
        _last_active[obj.name] = new_active

        _clear_selection(obj)

    @staticmethod
    def _clamp_delta(indices, delta, max_index):
        if delta > 0:
            headroom = max_index - max(indices)
            return min(delta, headroom)
        if delta < 0:
            headroom = min(indices) - 1
            return max(delta, -headroom)
        return 0

    @staticmethod
    def _move_by_delta(obj, indices, delta, max_index):
        """Move the selected keys as one contiguous block.

        A per-key move scatters the selection: shifting 1, 3, 5 down
        four rows with independent moves produces
        2, 4, 6, 7, 1, 8, 3, 9, 5 because each key slides past a
        different set of neighbours. The intended behaviour is to
        treat the selection as a unit and shift the whole block, so
        1, 3, 5 lands at the bottom as 2, 4, 6, 7, 8, 9, 1, 3, 5.

        The block is walked in the direction of travel (bottom-up for
        a downward move, top-down for an upward move). The first key
        moves `delta` slots; each subsequent key moves one slot
        further so it stays directly above the previously moved key.
        The already-moved neighbour acts as a ceiling / floor, which
        is what prevents the block from spreading apart.
        """
        if not indices:
            return

        if delta > 0:
            ceiling = max_index
            for rank, idx in enumerate(sorted(indices, reverse=True)):
                obj.active_shape_key_index = idx
                remaining = delta + rank
                while (remaining > 0
                       and obj.active_shape_key_index < ceiling):
                    bpy.ops.object.shape_key_move(type='DOWN')
                    remaining -= 1
                ceiling = obj.active_shape_key_index - 1
        else:
            # Basis lives at index 0 and cannot be crossed, so the
            # block can never reach that slot.
            floor = 1
            for rank, idx in enumerate(sorted(indices)):
                obj.active_shape_key_index = idx
                remaining = -delta + rank
                while (remaining > 0
                       and obj.active_shape_key_index > floor):
                    bpy.ops.object.shape_key_move(type='UP')
                    remaining -= 1
                floor = obj.active_shape_key_index + 1


# =====================================================================
# Scene properties
# =====================================================================

def _install_scene_properties():
    """Register the Scene properties the rename tools rely on.

    Only the two suffix strings are stored on the Scene. The expand
    state of the Rename Tools block lives in a module-level global
    (`_rename_expand`) instead, so it is never serialized into the
    .blend file.
    """
    if not hasattr(bpy.types.Scene, "xneko_shape_key_suffix_r"):
        bpy.types.Scene.xneko_shape_key_suffix_r = \
            bpy.props.StringProperty(
                name="Rename to R",
                description=(
                    "Suffix appended when renaming shape keys to the "
                    "right side"
                ),
                default="_R",
            )
    if not hasattr(bpy.types.Scene, "xneko_shape_key_suffix_l"):
        bpy.types.Scene.xneko_shape_key_suffix_l = \
            bpy.props.StringProperty(
                name="Rename to L",
                description=(
                    "Suffix appended when renaming shape keys to the "
                    "left side"
                ),
                default="_L",
            )


def _remove_scene_properties():
    for name in ("xneko_shape_key_suffix_r",
                 "xneko_shape_key_suffix_l"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


# =====================================================================
# Registration
# =====================================================================

classes = (
    SKP_UL_keys,
    XNEKO_OT_shape_key_select,
    XNEKO_OT_shape_key_remove_custom,
    XNEKO_OT_shape_key_remove_locked,
    XNEKO_OT_shape_key_add_clean,
    XNEKO_OT_shape_key_new_from_mix,
    XNEKO_OT_shape_key_value_toggle,
    XNEKO_OT_shape_key_toggle_rename_tools,
    XNEKO_OT_shape_key_lock_all,
    XNEKO_OT_shape_key_unlock_all,
    XNEKO_OT_shape_key_enable_all,  
    XNEKO_OT_shape_key_disable_all, 
    XNEKO_OT_shape_key_rename_r,
    XNEKO_OT_shape_key_rename_l,
    XNEKO_OT_shape_key_swap_rl,
    XNEKO_OT_shape_key_rename_settings,
    XNEKO_OT_shape_key_drag,
)


def on_load():
    _install_scene_properties()
    _install_draw_item_patch()
    _install_panel_patch()


def on_unload():
    global _batch_operation, _maintenance_scheduled
    global _last_filter_text, _filter_hint_until
    _remove_draw_item_patch()
    _remove_panel_patch()
    _remove_scene_properties()

    # Cancel the hint poll so it cannot fire against a torn-down
    # module after the plugin is disabled.
    _stop_hint_poll()
    _last_filter_text = ""
    _filter_hint_until = 0.0

    # Cancel a pending prune timer so it cannot fire after the module
    # has been torn down.
    if _maintenance_scheduled:
        try:
            bpy.app.timers.unregister(_run_prune_timer)
        except Exception:
            pass
        _maintenance_scheduled = False
    # Reset shared state so a reload never inherits a stale drag.
    _batch_operation = False
    _drag_state["active"] = False
    _drag_state["obj_name"] = ""
    _drag_state["target"] = -1
    _selection.clear()
    _anchor.clear()
    _last_active.clear()