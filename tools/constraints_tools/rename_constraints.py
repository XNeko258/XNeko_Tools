import bpy
from bpy.props import StringProperty, CollectionProperty, BoolProperty, EnumProperty
from typing import NamedTuple, Optional


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "rename_constraints"
tool_name = "Rename Constraints"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Constants
# ============================================================
DEFAULT_CON_NAMES = {
    'CAMERA_SOLVER': 'CameraSolver', 'OBJECT_SOLVER': 'ObjectSolver',
    'FOLLOW_TRACK': 'FollowTrack', 'COPY_LOCATION': 'CopyLocation',
    'COPY_ROTATION': 'CopyRotation', 'COPY_SCALE': 'CopyScale',
    'COPY_TRANSFORMS': 'CopyTransforms', 'LIMIT_DISTANCE': 'LimitDistance',
    'LIMIT_LOCATION': 'LimitLocation', 'LIMIT_ROTATION': 'LimitRotation',
    'LIMIT_SCALE': 'LimitScale', 'MAINTAIN_VOLUME': 'MaintainVolume',
    'TRANSFORM': 'Transform', 'CLAMP_TO': 'ClampTo',
    'DAMPED_TRACK': 'DampedTrack', 'IK': 'IK',
    'LOCKED_TRACK': 'LockedTrack', 'SPLINE_IK': 'SplineIK',
    'STRETCH_TO': 'StretchTo', 'TRACK_TO': 'TrackTo',
    'ACTION': 'Action', 'ARMATURE': 'Armature',
    'CHILD_OF': 'ChildOf', 'FLOOR': 'Floor',
    'FOLLOW_PATH': 'FollowPath', 'PIVOT': 'Pivot',
    'RIGID_BODY_JOINT': 'RigidBodyJoint', 'SCRIPT': 'Script',
    'SHRINKWRAP': 'Shrinkwrap', 'GEOMETRY_ATTRIBUTE': 'GeometryAttribute',
}

CON_ICONS = {
    'CAMERA_SOLVER': 'CON_CAMERASOLVER', 'OBJECT_SOLVER': 'CON_OBJECTSOLVER',
    'FOLLOW_TRACK': 'CON_FOLLOWTRACK', 'COPY_LOCATION': 'CON_LOCLIKE',
    'COPY_ROTATION': 'CON_ROTLIKE', 'COPY_SCALE': 'CON_SIZELIKE',
    'COPY_TRANSFORMS': 'CON_TRANSLIKE', 'LIMIT_DISTANCE': 'CON_DISTLIMIT',
    'LIMIT_LOCATION': 'CON_LOCLIMIT', 'LIMIT_ROTATION': 'CON_ROTLIMIT',
    'LIMIT_SCALE': 'CON_SIZELIMIT', 'MAINTAIN_VOLUME': 'CON_SAMEVOL',
    'TRANSFORM': 'CON_TRANSFORM', 'CLAMP_TO': 'CON_CLAMPTO',
    'DAMPED_TRACK': 'CON_DAMPEDTRACK', 'IK': 'CON_KINEMATIC',
    'LOCKED_TRACK': 'CON_LOCKTRACK', 'SPLINE_IK': 'CON_SPLINEIK',
    'STRETCH_TO': 'CON_STRETCHTO', 'TRACK_TO': 'CON_TRACKTO',
    'ACTION': 'CON_ACTION', 'ARMATURE': 'CON_ARMATURE',
    'CHILD_OF': 'CON_CHILDOF', 'FLOOR': 'CON_FLOOR',
    'FOLLOW_PATH': 'CON_FOLLOWPATH', 'PIVOT': 'CON_PIVOT',
    'RIGID_BODY_JOINT': 'CON_RIGIDBODYJOINT', 'SCRIPT': 'CON_PYTHON',
    'SHRINKWRAP': 'CON_SHRINKWRAP', 'GEOMETRY_ATTRIBUTE': 'CON_GEOMETRYATTRIBUTE',
}


# ============================================================
# Data classes
# ============================================================
class ConstraintEntry(NamedTuple):
    """A single constraint with its owner info for scanning."""
    constraint: object
    owner: object          # Object or PoseBone
    owner_type: str        # 'OBJECT' or 'BONE'
    obj: object            # The parent object (always Object)
    pose_bone: Optional[object] = None  # Only for BONE owners


class SelectionInfo(NamedTuple):
    entries: tuple
    types_in_use: frozenset
    total_constraints: int
    object_count: int
    bone_count: int
    has_target: bool       # At least one constraint has a target object
    has_subtarget: bool    # At least one constraint has a subtarget bone


# ============================================================
# PropertyGroup (per-type overrides stored on Scene)
# ============================================================
class XNEKO_ConPref(bpy.types.PropertyGroup):
    con_type: StringProperty()
    custom_name: StringProperty(
        name="Custom Name",
        description=(
            "Optional. When filled, overrides everything else "
            "(including the follow toggle)"
        ),
    )
    enabled: BoolProperty(
        name="Enabled",
        description="If off, this constraint type is skipped during rename",
        default=True,
    )
    follow_target: BoolProperty(
        name="Follow Target",
        description=(
            "When on, use the target object name. "
            "When off, fall back to the default label"
        ),
        default=True,
    )
    follow_subtarget: BoolProperty(
        name="Follow Subtarget",
        description=(
            "When on, use the subtarget bone/vertex-group name. "
            "Requires both target and subtarget to be set"
        ),
        default=True,
    )


# ============================================================
# Scan helpers
# ============================================================
def _iter_constraints(obj, include_bone=True, selected_pose_bones=None):
    """Yield ConstraintEntry for object constraints and (optionally) bone constraints.

    selected_pose_bones: if not None, only pose bones in this set are yielded.
    """
    # Object-level constraints
    for con in getattr(obj, 'constraints', []):
        yield ConstraintEntry(
            constraint=con,
            owner=obj,
            owner_type='OBJECT',
            obj=obj,
        )

    if not include_bone:
        return

    # Bone-level constraints (only for armatures)
    if obj.type != 'ARMATURE':
        return
    pose = getattr(obj, 'pose', None)
    if pose is None:
        return

    for pbone in pose.bones:
        if selected_pose_bones is not None and pbone not in selected_pose_bones:
            continue
        for con in pbone.constraints:
            yield ConstraintEntry(
                constraint=con,
                owner=pbone,
                owner_type='BONE',
                obj=obj,
                pose_bone=pbone,
            )


def _get_selected_pose_bones(context, mode='ALL'):
    """Return None (all bones) or a set of pose bones depending on mode."""
    if mode != 'SELECTED':
        return None
    if context.mode != 'POSE':
        return None
    try:
        selected_objs = set(context.selected_objects)
        return {
            pb for pb in (context.selected_pose_bones or [])
            if pb.id_data in selected_objs
        }
    except Exception:
        return None




def scan_selection(context) -> SelectionInfo:
    objects = list(context.selected_objects)

    include_bone = getattr(context.scene, 'xneko_con_include_bone', True)
    bone_mode = getattr(context.scene, 'xneko_con_bone_mode', 'ALL')
    selected_pose_bones = _get_selected_pose_bones(context, bone_mode) if include_bone else None

    entries = []
    types = set()
    has_target = False
    has_subtarget = False
    bone_count = 0

    for obj in objects:
        for entry in _iter_constraints(
            obj,
            include_bone=include_bone,
            selected_pose_bones=selected_pose_bones,
        ):
            con = entry.constraint
            entries.append(entry)
            types.add(con.type)

            if entry.owner_type == 'BONE':
                bone_count += 1

            # Check target / subtarget availability
            if not has_target:
                tgt = getattr(con, 'target', None)
                if tgt is not None:
                    has_target = True
            if not has_subtarget:
                sub = getattr(con, 'subtarget', '')
                if sub:
                    has_subtarget = True

    return SelectionInfo(
        entries=tuple(entries),
        types_in_use=frozenset(types),
        total_constraints=len(entries),
        object_count=len(objects),
        bone_count=bone_count,
        has_target=has_target,
        has_subtarget=has_subtarget,
    )


_VALID_ICONS_CACHE = None


def _get_valid_icons():
    global _VALID_ICONS_CACHE
    if _VALID_ICONS_CACHE is None:
        try:
            props = bpy.types.UILayout.bl_rna.functions['label'].parameters['icon']
            _VALID_ICONS_CACHE = set(props.enum_items.keys())
        except Exception:
            _VALID_ICONS_CACHE = set()
    return _VALID_ICONS_CACHE


def safe_icon(con_type: str) -> str:
    icon = CON_ICONS.get(con_type, 'CONSTRAINT')
    valid = _get_valid_icons()
    if valid and icon not in valid:
        return 'CONSTRAINT'
    return icon


def has_any_constraint(context) -> bool:
    include_bone = getattr(context.scene, 'xneko_con_include_bone', True)
    bone_mode = getattr(context.scene, 'xneko_con_bone_mode', 'ALL')
    selected_pose_bones = _get_selected_pose_bones(context, bone_mode) if include_bone else None

    for obj in context.selected_objects:
        for _ in _iter_constraints(
            obj,
            include_bone=include_bone,
            selected_pose_bones=selected_pose_bones,
        ):
            return True
    return False


def get_pref(prefs, con_type: str) -> Optional['XNEKO_ConPref']:
    for p in prefs:
        if p.con_type == con_type:
            return p
    return None


# ============================================================
# Pre-population
# ============================================================
def ensure_prefs_for_scene(scene) -> None:
    prefs = getattr(scene, 'xneko_con_prefs', None)
    if prefs is None:
        return
    existing = {p.con_type for p in prefs}
    for ctype in DEFAULT_CON_NAMES:
        if ctype not in existing:
            p = prefs.add()
            p.con_type = ctype


@bpy.app.handlers.persistent
def _on_load_post(_dummy):
    try:
        for scene in bpy.data.scenes:
            ensure_prefs_for_scene(scene)
    except Exception as e:
        print(f"[XNeko] load_post prepopulate failed: {e}")


# ============================================================
# Core renaming logic
# ------------------------------------------------------------
# Name resolution order:
#   1. custom_name          -- overrides everything when filled
#   2. follow_subtarget on  -- use the subtarget bone/vertex-group name
#   3. follow_target on     -- use the target object name
#   4. default label        -- fallback
# ============================================================
def _compute_name(con, pref):
    custom = (pref.custom_name.strip() if pref and pref.custom_name else "")
    if custom:
        return custom

    # Subtarget takes priority (more specific than target)
    follow_sub = bool(pref.follow_subtarget) if pref else True
    if follow_sub:
        sub = getattr(con, 'subtarget', '')
        if sub:
            return sub

    follow_tgt = bool(pref.follow_target) if pref else True
    if follow_tgt:
        tgt = getattr(con, 'target', None)
        if tgt is not None:
            return tgt.name

    return DEFAULT_CON_NAMES.get(con.type, con.type.title())


def rename_constraints(entries, prefs):
    """Rename every constraint in `entries`.

    Returns (processed, collisions). Collisions are cases where
    Blender had to append a numeric suffix because the target name
    was already taken on the same owner.
    """
    processed = 0
    collisions = 0

    for entry in entries:
        con = entry.constraint
        pref = get_pref(prefs, con.type)
        if pref is not None and not pref.enabled:
            continue

        target = _compute_name(con, pref)
        con.name = target
        processed += 1

        if con.name != target:
            collisions += 1

    return processed, collisions


# ============================================================
# Panel drawing helper
# ============================================================
def draw_constraint_row(layout, entry, ctype, info):
    default = DEFAULT_CON_NAMES.get(ctype, ctype.title())
    icon_name = safe_icon(ctype)
    row = layout.row(align=True)

    row.prop(entry, "enabled", text="")
    row.label(text=default, icon=icon_name)

    right = row.row(align=True)
    right.enabled = entry.enabled

    # Target/subtarget follow checkboxes are only meaningful
    # when the constraint type actually uses them.
    has_subtarget_field = ctype not in {
        'CAMERA_SOLVER', 'OBJECT_SOLVER', 'FOLLOW_TRACK',
        'SCRIPT', 'PIVOT', 'RIGID_BODY_JOINT',
    }

    if has_subtarget_field:
        cb = right.row(align=True)
        cb.enabled = info.has_target
        cb.prop(entry, "follow_target", text="Follow Obj")

        cb2 = right.row(align=True)
        cb2.enabled = info.has_subtarget
        cb2.prop(entry, "follow_subtarget", text="Follow Sub")

        inp = right.row(align=True)
        # Disable custom input when following is active and data exists
        follow_active = (
            (entry.follow_target and info.has_target)
            or (entry.follow_subtarget and info.has_subtarget)
        )
        inp.enabled = not follow_active
        inp.prop(entry, "custom_name", text="", icon='SORTALPHA')
    else:
        right.prop(entry, "custom_name", text="", icon='SORTALPHA')


# ============================================================
# Operators
# ============================================================
class XNEKO_OT_rename_constraints(bpy.types.Operator):
    bl_idname = "xneko.rename_constraints"
    bl_label = "Rename Constraints"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return has_any_constraint(context)

    def invoke(self, context, event):
        scene = context.scene
        if getattr(scene, "xneko_con_show_warning", True):
            return context.window_manager.invoke_props_dialog(self, width=400)
        return self.execute(context)

    def draw(self, context):
        info = scan_selection(context)
        col = self.layout.column()
        col.label(text="Rename constraints?", icon='QUESTION')
        col.separator()
        col.label(
            text=f"Will process {info.total_constraints} constraint(s) "
                 f"on {info.object_count} object(s) "
                 f"({info.bone_count} bone constraint(s))"
        )
        col.separator()
        col.label(text="· Existing constraint names will be overwritten")
        col.label(text="· Duplicate targets get '.001' suffixes")
        col.label(text="· Ctrl+Z works within this session")

    def execute(self, context):
        scene = context.scene
        ensure_prefs_for_scene(scene)
        info = scan_selection(context)

        n, collisions = rename_constraints(info.entries, scene.xneko_con_prefs)

        if n == 0:
            self.report({'WARNING'}, "No entries are enabled")
            return {'CANCELLED'}

        if collisions:
            self.report(
                {'INFO'},
                f"Renamed {n} constraint(s); "
                f"{collisions} name collision(s) got .001 suffixes",
            )
        else:
            self.report({'INFO'}, f"Renamed {n} constraint(s)")
        return {'FINISHED'}


class XNEKO_OT_toggle_all_con_enabled(bpy.types.Operator):
    bl_idname = "xneko.rename_constraints_toggle_all"
    bl_label = "Toggle All Enabled"
    bl_description = "Toggle the enabled state of all visible entries"

    def execute(self, context):
        scene = context.scene
        ensure_prefs_for_scene(scene)
        info = scan_selection(context)
        prefs = scene.xneko_con_prefs

        visible = [p for p in prefs if p.con_type in info.types_in_use]
        if not visible:
            self.report({'INFO'}, "No visible entries")
            return {'CANCELLED'}

        new_state = not all(p.enabled for p in visible)
        for p in visible:
            p.enabled = new_state
        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_xneko_rename_constraints(bpy.types.Panel):
    bl_label = "Rename Constraints"
    bl_idname = "VIEW3D_PT_xneko_rename_constraints"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    # No poll -> the panel header is always visible.

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        selected = context.selected_objects
        active_obj = context.object

        # Case 1: nothing selected at all
        if not selected and active_obj is None:
            box = layout.box()
            box.label(text="No object selected", icon='INFO')
            return

        # Case 2: selection has no constraints
        if not has_any_constraint(context):
            box = layout.box()
            box.label(text="No constraints in target", icon='INFO')
            return

        # Case 3: normal
        ensure_prefs_for_scene(scene)

        con_prefs = scene.xneko_con_prefs
        info = scan_selection(context)

        layout.label(
            text=f"Selected {info.object_count} object(s) / "
                 f"{info.total_constraints} constraint(s)"
        )

        hint = layout.row()
        hint.enabled = False
        hint.label(text="Settings below are stored in this .blend", icon='INFO')

        row = layout.row()
        row.prop(scene, "xneko_con_include_bone", toggle=True)

        if scene.xneko_con_include_bone:
            row = layout.row(align=True)
            row.prop(scene, "xneko_con_bone_mode", expand=True)

        layout.separator()

        for ctype in sorted(info.types_in_use):
            entry = get_pref(con_prefs, ctype)
            if entry is None:
                continue
            draw_constraint_row(layout, entry, ctype, info)

        layout.separator()

        row = layout.row(align=True)
        row.operator("xneko.rename_constraints", icon='CONSTRAINT')
        row.prop(scene, "xneko_con_show_warning", text="Confirm")

        visible = [p for p in con_prefs if p.con_type in info.types_in_use]
        all_on = all(p.enabled for p in visible) if visible else True
        layout.operator(
            "xneko.rename_constraints_toggle_all",
            text="Disable All" if all_on else "Enable All",
            icon='CHECKBOX_HLT' if all_on else 'CHECKBOX_DEHLT',
        )


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_ConPref,
    XNEKO_OT_rename_constraints,
    XNEKO_OT_toggle_all_con_enabled,
    VIEW3D_PT_xneko_rename_constraints,
)

scene_props = {
    "xneko_con_prefs": CollectionProperty(type=XNEKO_ConPref),
    "xneko_con_show_warning": BoolProperty(
        name="Show Confirmation",
        description=(
            "Show a confirmation dialog before renaming. "
            "Turn off to rename immediately"
        ),
        default=True,
    ),
    "xneko_con_include_bone": BoolProperty(
        name="Include Bone Constraints",
        description=(
            "When ON, constraints on pose bones are renamed as well. "
            "When OFF, only object-level constraints are processed"
        ),
        default=True,
    ),
    "xneko_con_bone_mode": EnumProperty(
        name="Bone Mode",
        description=(
            "ALL: rename constraints on every bone in the armature. "
            "SELECTED: only rename constraints on pose bones currently selected"
        ),
        items=[
            ('ALL', "All Bones", "Process every bone of the armature"),
            ('SELECTED', "Selected Bones",
             "Only process pose bones that are selected in Pose Mode"),
        ],
        default='ALL',
    ),
}


# ============================================================
# Lifecycle
# ============================================================
def on_load():
    global _VALID_ICONS_CACHE
    _VALID_ICONS_CACHE = None

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def on_unload():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)