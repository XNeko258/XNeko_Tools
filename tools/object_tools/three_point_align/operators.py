"""Operators for the three-point align tool."""

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from .geometry import build_alignment_matrix, bake_matrix
from .overlay import (
    OverlayHost, ScreenText, StatusPanel,
    WorldLines, WorldDots, WorldTriangle, CrossMarker,
)
from .raycaster import ViewportRaycaster
from .session import Session, Side


# =====================================================================
# Step 1 — pick the two meshes
# =====================================================================

class XNEKO_OT_tpa_pick_objects(Operator):
    bl_idname = 'xneko.tpa_pick_objects'
    bl_label = '三点对齐:选择网格'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self._host = OverlayHost()
        self._status = self._host.adopt(
            StatusPanel(self._host, x=14, y=14, size=16))
        self._hint = self._host.adopt(
            ScreenText(self._host, x=context.area.width, y=25,
                       size=16, center=True))
        self._auto_accept = True

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # ---------- selection analysis ----------

    @staticmethod
    def _evaluate(context):
        sel = list(context.selected_objects)
        act = context.active_object
        meshes = [o for o in sel if o.type == 'MESH']

        if not sel:
            return False, False, "请选中两个多边形网格"
        if len(sel) == 1 and len(meshes) == 1:
            return True, False, "按住 Shift 再选另一个网格作为源"
        if len(sel) == 2 and len(meshes) == 2 and act in sel:
            return True, True, "按 [空格/回车] 开始连线"
        if len(sel) == 2 and len(meshes) == 2:
            return True, False, "请把其中一个网格设为活动对象"
        return False, False, "选择必须恰好是两个网格对象"

    # ---------- modal ----------

    def modal(self, context, event):
        self._host.redraw()

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} \
                or (event.alt or event.ctrl or event.shift) and event.value == 'PRESS':
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._host.release_all()
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE':
            return {'PASS_THROUGH'}

        tgt_ok, src_ok, hint = self._evaluate(context)
        self._hint.body = hint
        self._status.set_rows((
            ("源网格",
             (1, 1, 1, 1),
             "已设置" if src_ok else "未设置",
             (0.2, 1.0, 0.3, 1) if src_ok else (0.5, 0.5, 0.5, 1)),
            ("目标网格",
             (1, 1, 1, 1),
             "已设置" if tgt_ok else "未设置",
             (0.2, 1.0, 0.3, 1) if tgt_ok else (0.5, 0.5, 0.5, 1)),
        ))

        go = tgt_ok and src_ok and (
            self._auto_accept
            or (event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'}
                and event.value == 'PRESS'))

        if go:
            self._host.release_all()
            bpy.ops.xneko.tpa_run('INVOKE_DEFAULT')
            return {'FINISHED'}

        self._auto_accept = False
        return {'RUNNING_MODAL'}


# =====================================================================
# Step 2 — connect 3 pairs of vertices
# =====================================================================

class XNEKO_OT_tpa_run(Operator):
    bl_idname = 'xneko.tpa_run'
    bl_label = '三点对齐'
    bl_options = {'REGISTER', 'UNDO'}

    # --- redo-menu mirrors of the scene settings ---
    keep_scale: BoolProperty(name='匹配距离', default=False)
    place_origin_between: BoolProperty(name='原点居中', default=False)
    reveal_origin: BoolProperty(name='显示变换轴', default=False)

    # -----------------------------------------------------------------
    # invoke
    # -----------------------------------------------------------------
    def invoke(self, context, event):
        s = context.scene.xneko_tpa
        self._load_props(s)

        self._host = OverlayHost()

        # Identify source (active) and target (the other selected object)
        src = context.active_object
        others = [o for o in context.selected_objects if o is not src]
        if src is None or not others:
            self._host.release_all()
            return {'CANCELLED'}
        tgt = others[0]

        # Build session
        self._session = Session(src, tgt, s)
        self._raycaster = ViewportRaycaster(
            context.region, context.region_data,
            snap_radius=s.snap_radius_px)
        self._obj_names = {src.name, tgt.name}

        # --- overlays ---
        self._cursor = self._host.adopt(
            CrossMarker(self._host, color=s.cursor_color,
                        size=s.cursor_radius_px))

        self._line_ov = []
        self._dot_ov = []
        for pair in self._session.pairs:
            line = self._host.adopt(
                WorldLines(self._host, color=pair.color, width=2.0))
            dots = self._host.adopt(
                WorldDots(self._host, color=pair.color,
                          size=s.dot_radius_px))
            self._line_ov.append(line)
            self._dot_ov.append(dots)

        self._preview = self._host.adopt(
            WorldDots(self._host, color=s.cursor_color,
                      size=s.dot_radius_px))

        self._src_tri = self._host.adopt(
            WorldTriangle(self._host, color=s.plane_color))
        self._tgt_tri = self._host.adopt(
            WorldTriangle(self._host, color=s.plane_color))

        self._status = self._host.adopt(
            StatusPanel(self._host, x=14, y=14, size=16))
        self._hint = self._host.adopt(
            ScreenText(self._host, x=context.area.width, y=25,
                       size=16, center=True))

        # --- pending click data ---
        self._pending_obj = None
        self._pending_vert = None
        self._pending_world = None

        # --- timer ---
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / 30.0, window=context.window)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # -----------------------------------------------------------------
    # settings round-trip
    # -----------------------------------------------------------------
    def _load_props(self, s):
        self.keep_scale = s.keep_scale
        self.place_origin_between = s.place_origin_between
        self.reveal_origin = s.reveal_origin

    def _save_props(self, s):
        s.keep_scale = self.keep_scale
        s.place_origin_between = self.place_origin_between
        s.reveal_origin = self.reveal_origin

    def draw(self, context):
        layout = self.layout
        grid = layout.grid_flow(columns=2, align=True, row_major=True)
        grid.label(text="匹配距离")
        grid.prop(self, 'keep_scale', text='')
        grid.label(text="原点居中")
        grid.prop(self, 'place_origin_between', text='')
        grid.label(text="显示变换轴")
        grid.prop(self, 'reveal_origin', text='')
        self._save_props(context.scene.xneko_tpa)

    # -----------------------------------------------------------------
    # modal
    # -----------------------------------------------------------------
    def modal(self, context, event):
        self._host.redraw()

        if event.type == 'TIMER':
            self._refresh_status()
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} \
                or event.alt:
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            if self._rewind_one_step():
                self._refresh_status()
                return {'RUNNING_MODAL'}
            self._cleanup(context)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            self._on_move(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self._on_click(context, event)
            self._refresh_status()
            return {'RUNNING_MODAL'}

        if event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'} \
                and event.value == 'PRESS':
            if self._session.finished:
                return self._apply(context)

        return {'RUNNING_MODAL'}

    # -----------------------------------------------------------------
    # mouse
    # -----------------------------------------------------------------
    def _on_move(self, context, event):
        obj, face, hit = self._raycaster.hit(
            context, (event.mouse_region_x, event.mouse_region_y),
            self._obj_names)

        if hit is None:
            self._clear_pending()
            return

        vert, vert_world = self._raycaster.snap_vertex(obj, face, hit)

        if vert is not None:
            self._pending_obj = obj
            self._pending_vert = vert
            self._pending_world = vert_world
            self._preview.set_points([vert_world])
            self._cursor.show_at(vert_world)
        else:
            self._clear_pending()
            self._cursor.show_at(hit)

    def _clear_pending(self):
        self._pending_obj = None
        self._pending_vert = None
        self._pending_world = None
        self._preview.clear()
        self._cursor.hide()

    def _on_click(self, context, event):
        if self._pending_vert is None:
            return

        session = self._session
        obj = self._pending_obj
        vert = self._pending_vert
        world = self._pending_world

        side = session.side_of(obj)
        if side is None:
            return

        # Re-open a claimed vertex
        owner_id = session.owner_of(obj, vert)
        if owner_id is not None:
            owner = session.pair_by_id(owner_id)
            session.drop(obj, vert)
            owner.clear(side)
            session.cursor_pair_id = owner.id
            self._sync_overlays()
            return

        # Find which pair should take this click
        target_pair = None
        for p in session.pairs:
            if p.get(side)[2] is None:
                target_pair = p
                break
        if target_pair is None:
            return

        target_pair.put(side, obj, vert, world)
        session.claim(obj, vert, target_pair.id)
        session.cursor_pair_id = target_pair.id
        self._sync_overlays()

    def _rewind_one_step(self):
        """Undo the last click (used by ESC).  Returns True if something was undone."""
        session = self._session
        for pair in reversed(session.pairs):
            if pair.ready:
                continue
            if pair.src_world is not None:
                session.drop(pair.src_obj, pair.src_vert)
                pair.clear(Side.SOURCE)
                session.cursor_pair_id = pair.id
                self._sync_overlays()
                return True
            if pair.tgt_world is not None:
                session.drop(pair.tgt_obj, pair.tgt_vert)
                pair.clear(Side.TARGET)
                session.cursor_pair_id = pair.id
                self._sync_overlays()
                return True
        return False

    # -----------------------------------------------------------------
    # sync overlays with session state
    # -----------------------------------------------------------------
    def _sync_overlays(self):
        for i, pair in enumerate(self._session.pairs):
            segs = []
            dots = []
            if pair.src_world is not None and pair.tgt_world is not None:
                segs.append((pair.src_world, pair.tgt_world))
            if pair.src_world is not None:
                dots.append(pair.src_world)
            if pair.tgt_world is not None:
                dots.append(pair.tgt_world)
            self._line_ov[i].set_segments(segs)
            self._dot_ov[i].set_points(dots)

        if self._session.finished:
            self._src_tri.set_vertices(
                *[p.src_world for p in self._session.pairs])
            self._tgt_tri.set_vertices(
                *[p.tgt_world for p in self._session.pairs])
        else:
            self._src_tri.clear()
            self._tgt_tri.clear()

    # -----------------------------------------------------------------
    # status + hint
    # -----------------------------------------------------------------
    def _refresh_status(self):
        rows = []
        for p in self._session.pairs:
            if p.ready:
                rows.append((p.label, p.color, "已连线", (0.2, 1.0, 0.3, 1)))
            elif p.partial:
                rows.append((p.label, p.color, "半连接", (1.0, 0.8, 0.2, 1)))
            else:
                rows.append((p.label, p.color, "未设置", (0.5, 0.5, 0.5, 1)))
        self._status.set_rows(rows)

        if self._session.finished:
            self._hint.body = "三对点已就位 — 按 [空格/回车] 应用对齐"
        elif any(p.partial for p in self._session.pairs):
            self._hint.body = "点击另一个网格上的对应顶点"
        else:
            self._hint.body = "在两个网格之间连接三对顶点"

    # -----------------------------------------------------------------
    # apply
    # -----------------------------------------------------------------
    def _apply(self, context):
        session = self._session
        target = session.target_obj

        try:
            M_new = build_alignment_matrix(session)
        except ValueError as exc:
            self._hint.body = f"无法对齐：{exc}"
            return {'RUNNING_MODAL'}

        # Base alignment
        target.matrix_world = M_new

        # Optional: move the origin to the midpoint of pair 1
        if self.place_origin_between:
            mid = (session.pairs[0].src_world
                   + session.pairs[1].src_world) * 0.5
            M_mid = M_new.copy()
            M_mid.translation = mid
            bake_matrix(target, M_mid)
            M_new = M_mid

        if self.reveal_origin:
            context.scene.tool_settings.use_transform_data_origin = True

        # Reselect the target only
        for o in context.selected_objects:
            o.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target

        self._cleanup(context)
        return {'FINISHED'}

    # -----------------------------------------------------------------
    # cleanup
    # -----------------------------------------------------------------
    def _cleanup(self, context):
        self._host.release_all()
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None