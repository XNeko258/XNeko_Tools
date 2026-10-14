"""Vertex Groups Plus — single-file development build.

Patches the built-in Object Data > Vertex Groups panel to:

  * Add two columns to each list row: [GRIP] [select]
    - GRIP enters reorder mode (click, wheel to move, click or Enter
      to confirm, right-click or Esc to cancel).
    - select toggles multi-selection (click / Shift+click / Ctrl+click).

  * Replace the remove button with a context-aware variant: with two
    or more selected groups it removes all of them; otherwise it
    behaves exactly like the built-in remove button.

  * Collapsible "More Tools" block with batch lock / unlock and the
    R/L rename suite (Rename to R, Rename to L, Swap R/L, and the
    suffix settings dialog).

  * Append a reorder-mode hint box below the panel with native key-cap
    icons while reorder mode is active.

Clicking a row's name in the list also updates the selection to that
row, so the remove button never deletes groups the user did not intend
to target.
"""

import time

import bpy
from bpy.props import BoolProperty, IntProperty

tool_id = "vertex_groups_plus"
tool_name = "Vertex Groups Plus"
tool_default_enabled = True

blender_version_min = (4, 0, 0)


# Shape group list height, in rows.
#
# _LIST_ROWS_BASE   -> visible rows when the extra tools block is
#                      collapsed (matches the built-in 3 / 5 behaviour
#                      via the +0 case in the panel below)
# _RENAME_EXTRA_ROWS -> extra rows added while the extra tools block
#                      is open
_LIST_ROWS_BASE = 6
_RENAME_EXTRA_ROWS = 6


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

    cell = grid.column()
    cell.use_property_split = True
    prefs.prop(cell, "scroll_step")

    grid.label(text="")

    for name in ("max_scroll_step", "accel_step",
                 "wheel_fast_ms", "wheel_slow_ms"):
        cell = grid.column()
        cell.use_property_split = True
        cell.active = accel_on
        prefs.prop(cell, name)


_resolved_get_tool_prefs = None


def _resolve_get_tool_prefs():
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
        return get_tool_prefs("vertex_groups_plus")
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
    prefs = _get_prefs()
    if prefs is None:
        return 0.15
    try:
        return max(0.01, int(prefs.wheel_fast_ms) / 1000.0)
    except Exception:
        return 0.15


def _read_wheel_slow_dt():
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
_last_active = {}

_drag_state = {"active": False, "obj_name": "", "target": -1}

_batch_operation = False

# Rename Tools block expand state. Module-level so it never ends up
# in the .blend file; it resets on Blender restart or plugin reload.
_rename_expand = False

_maintenance_scheduled = False


def _toggle_rename_expand():
    global _rename_expand
    _rename_expand = not _rename_expand


def _prune_state():
    live_names = {o.name for o in bpy.data.objects}
    for store in (_selection, _anchor, _last_active):
        for key in list(store.keys()):
            if key not in live_names:
                del store[key]


def _run_prune_timer():
    global _maintenance_scheduled
    _maintenance_scheduled = False
    _prune_state()
    return None


def _maybe_prune_state():
    global _maintenance_scheduled
    if _maintenance_scheduled:
        return
    _maintenance_scheduled = True
    bpy.app.timers.register(_run_prune_timer, first_interval=0.0)


def _live_names(obj):
    if not obj:
        return set()
    return {vg.name for vg in obj.vertex_groups}


def _get_selection(obj):
    if not obj:
        return set()
    return _selection.get(obj.name, set()) & _live_names(obj)


def _select_only(obj, index):
    if not obj:
        return
    groups = obj.vertex_groups
    if index < 0 or index >= len(groups):
        return
    _selection[obj.name] = {groups[index].name}


def _toggle(obj, index):
    if not obj:
        return
    groups = obj.vertex_groups
    if index < 0 or index >= len(groups):
        return
    name = groups[index].name
    sel = set(_selection.get(obj.name, set()))
    if name in sel:
        sel.discard(name)
    else:
        sel.add(name)
    _selection[obj.name] = sel


def _select_range(obj, from_index, to_index):
    if not obj:
        return
    groups = obj.vertex_groups
    lo = max(0, min(from_index, to_index))
    hi = min(len(groups) - 1, max(from_index, to_index))
    names = {groups[i].name for i in range(lo, hi + 1)}
    _selection[obj.name] = set(_selection.get(obj.name, set())) | names


def _is_selected(obj, index):
    if _batch_operation:
        return False
    if not obj:
        return False
    sel = _selection.get(obj.name)
    if not sel:
        return False
    groups = obj.vertex_groups
    if index < 0 or index >= len(groups):
        return False
    return groups[index].name in sel


def _clear_selection(obj):
    if obj:
        _selection.pop(obj.name, None)


def _get_anchor(obj):
    return _anchor.get(obj.name) if obj else None


def _set_anchor(obj, index):
    if obj:
        _anchor[obj.name] = index


def _remove_blocked_by_lock(obj):
    """True if the current delete target includes only locked groups."""
    if not obj:
        return False

    groups = obj.vertex_groups
    if not groups:
        return False

    raw_sel = _selection.get(obj.name)
    if not raw_sel:
        idx = obj.vertex_groups.active_index
        if idx < 0 or idx >= len(groups):
            return False
        return groups[idx].lock_weight

    sel = raw_sel & _live_names(obj)
    if len(sel) < 2:
        idx = obj.vertex_groups.active_index
        if idx < 0 or idx >= len(groups):
            return False
        return groups[idx].lock_weight

    targets = [vg for vg in groups if vg.name in sel]
    return bool(targets) and all(vg.lock_weight for vg in targets)


def _resolve_bulk_targets(obj):
    """Return the vertex groups a bulk lock / rename action should touch.

    When two or more groups are selected the action is scoped to that
    selection, matching the way the custom Remove button behaves.
    With one or zero selected, the action falls back to every group so
    the old "All" behaviour stays reachable when nothing is selected.
    """
    if not obj:
        return []

    groups = obj.vertex_groups
    if not groups:
        return []

    sel = _get_selection(obj)
    if len(sel) >= 2:
        return [vg for vg in groups if vg.name in sel]
    return list(groups)


def _in_edit_mode(obj):
    return bool(obj and obj.mode == 'EDIT')


# =====================================================================
# Rename helpers (R / L suffix)
# =====================================================================

def _split_rl_suffix(name, r_suffix, l_suffix):
    """Split a vertex-group name into (base, side).

    `side` is 'R', 'L', or None. A tail is recognised only when it
    matches the configured suffix for that side exactly, so the
    detection follows whatever the user set in the R/L Naming Pair
    dialog. Everything else, including a trailing single 'R' or 'L',
    is treated as part of the base.
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
      2. the locked groups, if any
      3. the active group
    """
    if not obj:
        return {'CANCELLED'}

    groups = obj.vertex_groups
    if not groups:
        return {'CANCELLED'}

    sel = _get_selection(obj)
    if sel:
        targets = [vg for vg in groups if vg.name in sel]
        if not targets:
            return {'CANCELLED'}
    else:
        locked_groups = [vg for vg in groups if vg.lock_weight]
        if locked_groups:
            targets = locked_groups
        else:
            idx = obj.vertex_groups.active_index
            if idx < 0 or idx >= len(groups):
                return {'CANCELLED'}
            targets = [groups[idx]]

    new_suffix = r_suffix if target_side == 'R' else l_suffix
    renamed = 0
    for vg in targets:
        base, side = _split_rl_suffix(vg.name, r_suffix, l_suffix)
        if side is not None:
            continue
        vg.name = f"{base}{new_suffix}"
        renamed += 1

    if renamed == 0:
        return {'CANCELLED'}
    return {'FINISHED'}


def _swap_locked_r_l_keys(obj, r_suffix, l_suffix):
    """Flip the R/L suffix of every target vertex group.

    A group ending in R becomes L, one ending in L becomes R. When a
    matching pair is targeted at once this is equivalent to swapping
    their names; a single group simply flips its own suffix.

    The rename is done in two passes (temporary names first) so that
    two groups in the same batch never collide on their target name.
    """
    if not obj:
        return {'CANCELLED'}

    groups = obj.vertex_groups
    if not groups:
        return {'CANCELLED'}

    sel = _get_selection(obj)
    if sel:
        targets = []
        for vg in groups:
            if vg.name not in sel:
                continue
            base, side = _split_rl_suffix(vg.name, r_suffix, l_suffix)
            if side in ('R', 'L'):
                targets.append((vg, base, side))
        if not targets:
            return {'CANCELLED'}
    else:
        locked_targets = []
        for vg in groups:
            if not vg.lock_weight:
                continue
            base, side = _split_rl_suffix(vg.name, r_suffix, l_suffix)
            if side in ('R', 'L'):
                locked_targets.append((vg, base, side))

        if locked_targets:
            targets = locked_targets
        else:
            idx = obj.vertex_groups.active_index
            if idx < 0 or idx >= len(groups):
                return {'CANCELLED'}
            active = groups[idx]
            base, side = _split_rl_suffix(active.name, r_suffix,
                                          l_suffix)
            if side not in ('R', 'L'):
                return {'CANCELLED'}
            targets = [(active, base, side)]

    # Pass 1: temporary names to avoid collisions.
    for i, (vg, base, side) in enumerate(targets):
        vg.name = f"__rlswap_{i:02d}_{base}"

    # Pass 2: apply the flipped suffix.
    for vg, base, side in targets:
        new_suffix = l_suffix if side == 'R' else r_suffix
        vg.name = f"{base}{new_suffix}"

    return {'FINISHED'}


# =====================================================================
# draw_item patch for MESH_UL_vgroups
# =====================================================================

_original_draw_item = None


def _draw_item_custom(self, context, layout, data, item, icon,
                      active_data, active_propname, index):
    obj = data
    vgroup = item

    # Keep our selection set in sync with the active row. When the
    # user clicks a row's name Blender only updates active_index; we
    # mirror that into a single-selection so the remove button never
    # targets the wrong groups.
    if not _batch_operation:
        prev_active = _last_active.get(obj.name)
        cur_active = obj.vertex_groups.active_index
        if prev_active != cur_active:
            _last_active[obj.name] = cur_active
            if cur_active >= 0:
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

    selected = _is_selected(obj, index)

    # --- Column 1: reorder handle ---
    # Greyed out in Edit Mode, matching the built-in move buttons.
    drag_row = row.row(align=True)
    drag_row.enabled = obj.mode != 'EDIT'
    drag = drag_row.operator(
        "xneko.vertex_group_drag",
        text="", icon='GRIP', emboss=False,
    )
    drag.source_index = index

    # --- Column 2: selection icon ---
    sel_icon = ('RESTRICT_SELECT_OFF' if selected
                else 'RESTRICT_SELECT_ON')
    sel = row.operator(
        "xneko.vertex_group_select",
        text="", icon=sel_icon, emboss=False,
    )
    sel.clicked_index = index

    # --- Column 3: name (this row stretches to fill) ---
    name_cell = row.row()
    if is_drop_target:
        name_cell.alert = True
    name_cell.prop(vgroup, "name", text="",
                   emboss=False, icon_value=icon)

    # --- Column 4: lock, with the native LOCKED / UNLOCKED icon so
    #     the toggle stays visible exactly like the built-in list. ---
    lock_icon = 'LOCKED' if vgroup.lock_weight else 'UNLOCKED'
    row.prop(vgroup, "lock_weight", text="",
             icon=lock_icon, emboss=False)


def _install_draw_item_patch():
    global _original_draw_item
    list_cls = getattr(bpy.types, "MESH_UL_vgroups", None)
    if list_cls is None:
        print("[XNeko] MESH_UL_vgroups not found; patch skipped")
        return
    if list_cls.draw_item is _draw_item_custom:
        return
    if _original_draw_item is None:
        _original_draw_item = list_cls.draw_item
    list_cls.draw_item = _draw_item_custom


def _remove_draw_item_patch():
    global _original_draw_item
    list_cls = getattr(bpy.types, "MESH_UL_vgroups", None)
    if list_cls is None or _original_draw_item is None:
        return
    list_cls.draw_item = _original_draw_item
    _original_draw_item = None


# =====================================================================
# Vertex Groups panel (full replacement, based on the built-in draw)
# =====================================================================

_original_panel_draw = None


def _draw_vertex_groups_panel_custom(self, context):
    ob = context.object
    if ob is None:
        return

    # Empty state: forward to the unpatched panel so the layout and
    # buttons stay byte-for-byte identical to stock Blender when the
    # object has no vertex groups yet. The moment a group exists the
    # patched path takes over with the grip / select columns and the
    # "More Tools" block.
    if not ob.vertex_groups:
        if _original_panel_draw is not None:
            _original_panel_draw(self, context)
        return

    _maybe_prune_state()

    layout = self.layout
    group = ob.vertex_groups.active

    rows = 3
    if group:
        rows = _LIST_ROWS_BASE
    if _rename_expand:
        rows += _RENAME_EXTRA_ROWS

    row = layout.row()
    row.template_list(
        "VGP_UL_groups", "",
        ob, "vertex_groups",
        ob.vertex_groups, "active_index",
        rows=rows,
    )

    col = row.column(align=True)

    structure_enabled = not _in_edit_mode(ob)

    # Add
    add_row = col.row()
    add_row.enabled = structure_enabled
    add_row.operator("object.vertex_group_add", icon='ADD', text="")

    # Remove: grey out while every delete target is locked.
    locked = _remove_blocked_by_lock(ob)
    remove_row = col.row()
    remove_row.enabled = structure_enabled and not locked
    if locked:
        remove_row.operator("xneko.vertex_group_remove_locked",
                            icon='REMOVE', text="")
    else:
        remove_row.operator("xneko.vertex_group_remove_custom",
                            icon='REMOVE', text="")

    col.separator()

    # Specials menu
    col.menu("MESH_MT_vertex_group_context_menu",
             icon='DOWNARROW_HLT', text="")

    # Move up / down
    if group:
        col.separator()
        col.operator("object.vertex_group_move",
                     icon='TRIA_UP', text="").direction = 'UP'
        col.operator("object.vertex_group_move",
                     icon='TRIA_DOWN', text="").direction = 'DOWN'

    # Collapsible rename / batch tools. Collapsed by default. The
    # expand state lives in a module-level global and is therefore
    # never written to the .blend file.
    col.separator()
    col.operator(
        "xneko.vertex_group_toggle_rename_tools",
        text="",
        icon=('TRIA_DOWN' if _rename_expand else 'TRIA_RIGHT'),
        emboss=False,
    )

    if _rename_expand:
        # Lock / unlock first: they get used far more often than
        # the rename tools.
        lock_col = col.column(align=True)
        lock_col.operator("xneko.vertex_group_lock_all",
                          text="", icon='LOCKED')
        lock_col.operator("xneko.vertex_group_unlock_all",
                          text="", icon='UNLOCKED')

        col.separator()

        rename_col = col.column(align=True)
        rename_col.operator("xneko.vertex_group_rename_r",
                            text="", icon='EVENT_R')
        rename_col.operator("xneko.vertex_group_rename_l",
                            text="", icon='EVENT_L')
        rename_col.operator("xneko.vertex_group_swap_rl",
                            text="", icon='FILE_REFRESH')
        rename_col.operator("xneko.vertex_group_rename_settings",
                            text="", icon='PREFERENCES')

    # Filter syntax hint, shown while the background poll is still
    # watching the cursor.
    if _hint_poll_active:
        hint_box = layout.box()
        hint_col = hint_box.column(align=True)
        hint_col.scale_y = 0.85
        hint_col.label(text="Catgirl * Wifu  =  Catgirl and Wifu")
        hint_col.label(text="Catgirl / Wifu  =  Catgirl or Wifu")

    # --- Reorder-mode hint, right below the list ---
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

    # Assign / Remove / Select / Deselect (Edit / Weight Paint only)
    if (ob.vertex_groups and (
        ob.mode == 'EDIT'
        or (ob.mode == 'WEIGHT_PAINT'
            and ob.type == 'MESH'
            and ob.data.use_paint_mask_vertex)
    )):
        r = layout.row()
        sub = r.row(align=True)
        sub.operator("object.vertex_group_assign", text="Assign")
        sub.operator("object.vertex_group_remove_from", text="Remove")

        sub = r.row(align=True)
        sub.operator("object.vertex_group_select", text="Select")
        sub.operator("object.vertex_group_deselect", text="Deselect")

        layout.prop(context.tool_settings, "vertex_group_weight",
                    text="Weight")


def _install_panel_patch():
    global _original_panel_draw
    panel_cls = getattr(bpy.types, "DATA_PT_vertex_groups", None)
    if panel_cls is None:
        print("[XNeko] DATA_PT_vertex_groups not found; "
              "panel patch skipped")
        return
    if panel_cls.draw is _draw_vertex_groups_panel_custom:
        return
    if _original_panel_draw is None:
        _original_panel_draw = panel_cls.draw
    panel_cls.draw = _draw_vertex_groups_panel_custom


def _remove_panel_patch():
    global _original_panel_draw
    panel_cls = getattr(bpy.types, "DATA_PT_vertex_groups", None)
    if panel_cls is None or _original_panel_draw is None:
        return
    panel_cls.draw = _original_panel_draw
    _original_panel_draw = None


# =====================================================================
# Custom UIList with a name filter (Blender 4.5+)
# =====================================================================

_last_filter_text = ""

_hint_poll_active = False
_filter_hint_until = 0.0

_HINT_POLL_INTERVAL = 0.2
_HINT_MAX_DURATION = 8.0


def _mouse_in_properties():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return False
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'PROPERTIES':
                continue
            for region in area.regions:
                if (0 <= region.mouse_x < region.width
                        and 0 <= region.mouse_y < region.height):
                    return True
    return False


def _redraw_properties():
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
    global _hint_poll_active
    if not _last_filter_text:
        _hint_poll_active = False
        return None
    if (_mouse_in_properties()
            and time.time() < _filter_hint_until):
        return _HINT_POLL_INTERVAL

    _hint_poll_active = False
    _redraw_properties()
    return None


def _start_hint_poll():
    global _hint_poll_active, _filter_hint_until
    _filter_hint_until = time.time() + _HINT_MAX_DURATION
    if _hint_poll_active:
        return
    _hint_poll_active = True
    bpy.app.timers.register(
        _hint_poll, first_interval=_HINT_POLL_INTERVAL)


def _stop_hint_poll():
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

    Both operators need a space on each side, so a group whose name
    happens to contain a bare "*" or "/" is not accidentally split.
    Every term is a case-insensitive substring match.
    """
    if not text or not text.strip():
        return None

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


class VGP_UL_groups(bpy.types.UIList):
    """Vertex-group list with the native Blender 4.5 filter bar.

    The class name doubles as the UIList's bl_idname, so it must be
    globally unique across every addon. The "VGP_" prefix keeps it
    out of the way of other tools that might also define a vertex
    group list.
    """

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        _draw_item_custom(self, context, layout, data, item, icon,
                          active_data, active_propname, index)

    def filter_items(self, context, data, propname):
        global _last_filter_text
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)

        text = getattr(self, "filter_name", "")

        if text != _last_filter_text:
            _last_filter_text = text
            if text:
                _start_hint_poll()
            else:
                _stop_hint_poll()

        matcher = _get_filter_matcher(text)
        if matcher is None:
            return flags, []

        for i, vg in enumerate(items):
            if not matcher(vg.name):
                flags[i] = 0

        return flags, []


# =====================================================================
# Select operator
# =====================================================================

class XNEKO_OT_vertex_group_select(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_select"
    bl_label = "Select Vertex Group"
    bl_description = (
        "Click to select. Shift for range, Ctrl for multi-select"
    )
    bl_options = {'INTERNAL'}

    clicked_index: IntProperty(default=-1)

    def invoke(self, context, event):
        obj = context.object
        if not obj:
            return {'CANCELLED'}

        groups = obj.vertex_groups
        if self.clicked_index < 0 or self.clicked_index >= len(groups):
            return {'CANCELLED'}

        index = self.clicked_index
        name = groups[index].name

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

        obj.vertex_groups.active_index = index
        _last_active[obj.name] = index
        return {'FINISHED'}


# =====================================================================
# Custom remove operator (single / batch depending on selection size)
# =====================================================================

class XNEKO_OT_vertex_group_remove_locked(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_remove_locked"
    bl_label = "Remove Vertex Group"
    bl_description = "Locked vertex groups cannot be removed"
    bl_options = {'REGISTER'}

    def execute(self, context):
        self.report({'WARNING'},
                    "Locked vertex groups cannot be removed")
        return {'CANCELLED'}


class XNEKO_OT_vertex_group_remove_custom(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_remove_custom"
    bl_label = "Remove Vertex Group"
    bl_description = (
        "Remove the active vertex group. If two or more groups are "
        "selected, remove all selected groups at once"
    )
    bl_options = {'REGISTER', 'UNDO'}

    all: BoolProperty(default=False)

    def execute(self, context):
        obj = context.object
        if not obj:
            return {'CANCELLED'}

        if _in_edit_mode(obj):
            self.report({'INFO'},
                        "Removing vertex groups requires Object Mode")
            return {'CANCELLED'}

        if self.all:
            return bpy.ops.object.vertex_group_remove(all=True)

        groups = obj.vertex_groups
        if not groups:
            return {'CANCELLED'}

        sel = _get_selection(obj)

        if len(sel) >= 2:
            indices = [
                i for i, vg in enumerate(groups)
                if vg.name in sel and not vg.lock_weight
            ]
            if not indices:
                self.report({'WARNING'},
                            "Locked vertex groups cannot be removed")
                return {'CANCELLED'}

            global _batch_operation
            _batch_operation = True
            wm = context.window_manager
            total = len(indices)
            wm.progress_begin(0, total)
            try:
                for n, i in enumerate(sorted(indices, reverse=True)):
                    vg = groups[i]
                    groups.remove(vg)
                    if (n & 3) == 0 or n == total - 1:
                        wm.progress_update(n + 1)
            finally:
                try:
                    wm.progress_end()
                finally:
                    _batch_operation = False

            _clear_selection(obj)
            _last_active[obj.name] = obj.vertex_groups.active_index
            return {'FINISHED'}

        idx = obj.vertex_groups.active_index
        if idx < 0 or idx >= len(groups):
            return {'CANCELLED'}
        if groups[idx].lock_weight:
            self.report({'WARNING'},
                        "Locked vertex groups cannot be removed")
            return {'CANCELLED'}
        try:
            return bpy.ops.object.vertex_group_remove(all=False)
        except RuntimeError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


# =====================================================================
# Batch lock / unlock
# =====================================================================

class XNEKO_OT_vertex_group_lock_all(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_lock_all"
    bl_label = "Lock Vertex Groups"
    bl_description = (
        "Lock the selected vertex groups, or every group when fewer "
        "than two are selected"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _resolve_bulk_targets(context.object)
        if not targets:
            return {'CANCELLED'}

        for vg in targets:
            vg.lock_weight = True
        return {'FINISHED'}


class XNEKO_OT_vertex_group_unlock_all(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_unlock_all"
    bl_label = "Unlock Vertex Groups"
    bl_description = (
        "Unlock the selected vertex groups, or every group when "
        "fewer than two are selected"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _resolve_bulk_targets(context.object)
        if not targets:
            return {'CANCELLED'}

        for vg in targets:
            vg.lock_weight = False
        return {'FINISHED'}


# =====================================================================
# Rename tools
# =====================================================================

class XNEKO_OT_vertex_group_rename_r(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_rename_r"
    bl_label = "Rename to R"
    bl_description = (
        "Append the configured R suffix to every target name that "
        "has no R or L suffix yet. Targets are the selection if any, "
        "otherwise the locked groups, otherwise the active group. "
        "Use Swap R/L to change the side of names that already have "
        "one"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        return _rename_locked_to_suffix(
            context.object, 'R',
            scene.xneko_vertex_group_suffix_r,
            scene.xneko_vertex_group_suffix_l,
        )


class XNEKO_OT_vertex_group_rename_l(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_rename_l"
    bl_label = "Rename to L"
    bl_description = (
        "Append the configured L suffix to every target name that "
        "has no R or L suffix yet. Targets are the selection if any, "
        "otherwise the locked groups, otherwise the active group. "
        "Use Swap R/L to change the side of names that already have "
        "one"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        return _rename_locked_to_suffix(
            context.object, 'L',
            scene.xneko_vertex_group_suffix_r,
            scene.xneko_vertex_group_suffix_l,
        )


class XNEKO_OT_vertex_group_swap_rl(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_swap_rl"
    bl_label = "Swap R/L"
    bl_description = (
        "Flip the configured R suffix to L, and L to R, on every "
        "target group that carries one of them. Targets are the "
        "selection if any, otherwise the locked groups, otherwise "
        "the active group"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        return _swap_locked_r_l_keys(
            context.object,
            scene.xneko_vertex_group_suffix_r,
            scene.xneko_vertex_group_suffix_l,
        )


class XNEKO_OT_vertex_group_toggle_rename_tools(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_toggle_rename_tools"
    bl_label = "More Tools"
    bl_description = (
        "Expand or collapse the additional tools section "
        "(batch lock, rename)"
    )
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _toggle_rename_expand()
        return {'FINISHED'}


class XNEKO_OT_vertex_group_rename_settings(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_rename_settings"
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
        self.suffix_r = scene.xneko_vertex_group_suffix_r
        self.suffix_l = scene.xneko_vertex_group_suffix_l
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
        note.label(text="Changing them does not rename saved groups.")

    def execute(self, context):
        # Reject configurations that would make the rename tools
        # behave unpredictably:
        #   * an empty suffix would append nothing, so the button
        #     would silently do nothing on a suffix-less name;
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
        scene.xneko_vertex_group_suffix_r = self.suffix_r
        scene.xneko_vertex_group_suffix_l = self.suffix_l
        return {'FINISHED'}


# =====================================================================
# Reorder operator
# =====================================================================

class XNEKO_OT_vertex_group_drag(bpy.types.Operator):
    bl_idname = "xneko.vertex_group_drag"
    bl_label = "Reorder Vertex Group"
    bl_description = (
        "Click to enter reorder mode, then use the mouse wheel to move "
        "the current selection up or down. Left-click or Enter confirms, "
        "right-click or Esc cancels"
    )
    bl_options = {'REGISTER', 'UNDO'}

    source_index: IntProperty(default=-1)

    def invoke(self, context, event):
        obj = context.object
        if not obj:
            return {'CANCELLED'}

        if _in_edit_mode(obj):
            self.report({'INFO'},
                        "Reordering vertex groups requires Object Mode")
            return {'CANCELLED'}

        groups = obj.vertex_groups
        if self.source_index < 0 or self.source_index >= len(groups):
            return {'CANCELLED'}

        clicked_name = groups[self.source_index].name
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
        if not obj:
            self._end_drag(context)
            return {'CANCELLED'}

        max_index = len(obj.vertex_groups) - 1

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
                obj.vertex_groups.active_index = new_target
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
        groups = obj.vertex_groups
        max_index = len(groups) - 1

        sel = _get_selection(obj)
        if not sel:
            return

        selected_indices = [
            i for i, vg in enumerate(groups) if vg.name in sel
        ]

        delta = self._target_index - self._initial_index
        delta = self._clamp_delta(selected_indices, delta, max_index)
        if delta == 0:
            return

        bpy.ops.ed.undo_push(message="Reorder Vertex Groups")

        self._move_by_delta(obj, selected_indices, delta, max_index)

        new_active = max(0, min(max_index,
                                self._initial_index + delta))
        obj.vertex_groups.active_index = new_active
        _last_active[obj.name] = new_active

        _clear_selection(obj)

    @staticmethod
    def _clamp_delta(indices, delta, max_index):
        if delta > 0:
            headroom = max_index - max(indices)
            return min(delta, headroom)
        if delta < 0:
            headroom = min(indices)
            return max(delta, -headroom)
        return 0

    @staticmethod
    def _move_by_delta(obj, indices, delta, max_index):
        """Move the selected groups as one contiguous block.

        Unlike shape keys there is no Basis row to protect: index 0 is
        a regular vertex group and may be reordered freely, so the
        upward floor is 0 rather than 1.
        """
        if not indices:
            return

        if delta > 0:
            ceiling = max_index
            for rank, idx in enumerate(sorted(indices, reverse=True)):
                obj.vertex_groups.active_index = idx
                remaining = delta + rank
                while (remaining > 0
                       and obj.vertex_groups.active_index < ceiling):
                    bpy.ops.object.vertex_group_move(direction='DOWN')
                    remaining -= 1
                ceiling = obj.vertex_groups.active_index - 1
        else:
            floor = 0
            for rank, idx in enumerate(sorted(indices)):
                obj.vertex_groups.active_index = idx
                remaining = -delta + rank
                while (remaining > 0
                       and obj.vertex_groups.active_index > floor):
                    bpy.ops.object.vertex_group_move(direction='UP')
                    remaining -= 1
                floor = obj.vertex_groups.active_index + 1


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
    if not hasattr(bpy.types.Scene, "xneko_vertex_group_suffix_r"):
        bpy.types.Scene.xneko_vertex_group_suffix_r = \
            bpy.props.StringProperty(
                name="Rename to R",
                description=(
                    "Suffix appended when renaming vertex groups to "
                    "the right side"
                ),
                default="_R",
            )
    if not hasattr(bpy.types.Scene, "xneko_vertex_group_suffix_l"):
        bpy.types.Scene.xneko_vertex_group_suffix_l = \
            bpy.props.StringProperty(
                name="Rename to L",
                description=(
                    "Suffix appended when renaming vertex groups to "
                    "the left side"
                ),
                default="_L",
            )


def _remove_scene_properties():
    for name in ("xneko_vertex_group_suffix_r",
                 "xneko_vertex_group_suffix_l"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


# =====================================================================
# Registration
# =====================================================================

classes = (
    VGP_UL_groups,
    XNEKO_OT_vertex_group_select,
    XNEKO_OT_vertex_group_remove_custom,
    XNEKO_OT_vertex_group_remove_locked,
    XNEKO_OT_vertex_group_lock_all,
    XNEKO_OT_vertex_group_unlock_all,
    XNEKO_OT_vertex_group_rename_r,
    XNEKO_OT_vertex_group_rename_l,
    XNEKO_OT_vertex_group_swap_rl,
    XNEKO_OT_vertex_group_toggle_rename_tools,
    XNEKO_OT_vertex_group_rename_settings,
    XNEKO_OT_vertex_group_drag,
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

    _stop_hint_poll()
    _last_filter_text = ""
    _filter_hint_until = 0.0

    if _maintenance_scheduled:
        try:
            bpy.app.timers.unregister(_run_prune_timer)
        except Exception:
            pass
        _maintenance_scheduled = False

    _batch_operation = False
    _drag_state["active"] = False
    _drag_state["obj_name"] = ""
    _drag_state["target"] = -1
    _selection.clear()
    _anchor.clear()
    _last_active.clear()