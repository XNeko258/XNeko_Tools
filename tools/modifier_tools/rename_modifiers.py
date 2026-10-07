import bpy
from bpy.props import StringProperty, CollectionProperty, BoolProperty
from typing import NamedTuple, Optional


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "rename_modifiers"
tool_name = "Rename Modifiers"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Constants
# ============================================================
DEFAULT_MOD_NAMES = {
    'ARMATURE': 'Armature', 'SUBSURF': 'Subdivision', 'SOLIDIFY': 'Solidify',
    'MASK': 'Mask', 'BEVEL': 'Bevel', 'BOOLEAN': 'Boolean',
    'MIRROR': 'Mirror', 'ARRAY': 'Array', 'WAVE': 'Wave',
    'DISPLACE': 'Displace', 'SMOOTH': 'Smooth', 'LATTICE': 'Lattice',
    'CLOTH': 'Cloth', 'PARTICLE_SYSTEM': 'ParticleSystem',
    'DECIMATE': 'Decimate', 'SCREW': 'Screw', 'EDGE_SPLIT': 'EdgeSplit',
    'WEIGHTED_NORMAL': 'WeightedNormal', 'TRIANGULATE': 'Triangulate',
    'SKIN': 'Skin', 'CURVE': 'Curve', 'HOOK': 'Hook', 'CAST': 'Cast',
    'WIREFRAME': 'Wireframe', 'REMESH': 'Remesh', 'SHRINKWRAP': 'Shrinkwrap',
    'NODES': 'GeometryNodes', 'BUILD': 'Build', 'EXPLODE': 'Explode',
    'OCEAN': 'Ocean', 'CORRECTIVE_SMOOTH': 'CorrectiveSmooth',
    'LAPLACIANSMOOTH': 'LaplacianSmooth', 'SIMPLE_DEFORM': 'SimpleDeform',
    'DATA_TRANSFER': 'DataTransfer', 'NORMAL_EDIT': 'NormalEdit',
    'UV_PROJECT': 'UVProject', 'UV_WARP': 'UVWarp',
    'VERTEX_WEIGHT_EDIT': 'VertexWeightEdit',
    'VERTEX_WEIGHT_MIX': 'VertexWeightMix',
    'VERTEX_WEIGHT_PROXIMITY': 'VertexWeightProximity',
    'MESH_DEFORM': 'MeshDeform', 'MESH_CACHE': 'MeshCache',
    'MULTIRES': 'Multires', 'SOFT_BODY': 'SoftBody',
    'SURFACE': 'Surface', 'COLLISION': 'Collision',
    'DYNAMIC_PAINT': 'DynamicPaint', 'FLUID_SIMULATION': 'FluidSimulation',
    'PARTICLE_INSTANCE': 'ParticleInstance', 'SMOKE': 'Smoke',
    'LAPLACIANDEFORM': 'LaplacianDeform', 'WARP': 'Warp',
}

MOD_ICONS = {
    'ARMATURE': 'MOD_ARMATURE', 'SUBSURF': 'MOD_SUBSURF',
    'SOLIDIFY': 'MOD_SOLIDIFY', 'MASK': 'MOD_MASK',
    'BEVEL': 'MOD_BEVEL', 'BOOLEAN': 'MOD_BOOLEAN',
    'MIRROR': 'MOD_MIRROR', 'ARRAY': 'MOD_ARRAY', 'WAVE': 'MOD_WAVE',
    'DISPLACE': 'MOD_DISPLACE', 'SMOOTH': 'MOD_SMOOTH',
    'LATTICE': 'MOD_LATTICE', 'CLOTH': 'MOD_CLOTH',
    'PARTICLE_SYSTEM': 'MOD_PARTICLES', 'DECIMATE': 'MOD_DECIM',
    'SCREW': 'MOD_SCREW', 'EDGE_SPLIT': 'MOD_EDGESPLIT',
    'WEIGHTED_NORMAL': 'MODIFIER', 'TRIANGULATE': 'MOD_TRIANGULATE',
    'SKIN': 'MOD_SKIN', 'CURVE': 'MOD_CURVE', 'HOOK': 'HOOK',
    'CAST': 'MOD_CAST', 'WIREFRAME': 'MOD_WIREFRAME',
    'REMESH': 'MOD_REMESH', 'SHRINKWRAP': 'MOD_SHRINKWRAP',
    'NODES': 'GEOMETRY_NODES', 'BUILD': 'MOD_BUILD',
    'EXPLODE': 'MOD_EXPLODE', 'OCEAN': 'MOD_OCEAN',
    'CORRECTIVE_SMOOTH': 'MOD_SMOOTH', 'LAPLACIANSMOOTH': 'MOD_SMOOTH',
    'SIMPLE_DEFORM': 'MOD_SIMPLEDEFORM',
    'DATA_TRANSFER': 'MOD_DATA_TRANSFER',
    'NORMAL_EDIT': 'MOD_NORMALEDIT', 'UV_PROJECT': 'MOD_UVPROJECT',
    'UV_WARP': 'MODIFIER',
    'VERTEX_WEIGHT_EDIT': 'MOD_VERTEX_WEIGHT',
    'VERTEX_WEIGHT_MIX': 'MOD_VERTEX_WEIGHT',
    'VERTEX_WEIGHT_PROXIMITY': 'MOD_VERTEX_WEIGHT',
    'MESH_DEFORM': 'MOD_MESHDEFORM', 'MESH_CACHE': 'MODIFIER',
    'MULTIRES': 'MOD_MULTIRES', 'SOFT_BODY': 'MOD_SOFT',
    'SURFACE': 'MODIFIER', 'COLLISION': 'MOD_PHYSICS',
    'DYNAMIC_PAINT': 'MOD_DYNAMICPAINT',
    'FLUID_SIMULATION': 'MOD_FLUIDSIM',
    'PARTICLE_INSTANCE': 'MOD_PARTICLES',
    'SMOKE': 'MOD_FLUIDSIM', 'LAPLACIANDEFORM': 'MOD_MESHDEFORM',
    'WARP': 'MOD_WARP',
}


# ============================================================
# Data classes
# ============================================================
class SelectionInfo(NamedTuple):
    pairs: tuple
    types_in_use: frozenset
    total_mods: int
    object_count: int
    has_armature_target: bool
    has_mask_target: bool
    has_hook_target: bool


# ============================================================
# PropertyGroup (per-type overrides stored on Scene)
# ------------------------------------------------------------
# Every setting here is per-file. Two types support following the
# attached data (object / vertex group) by default; the checkbox
# lets the user fall back to a static name for the current project.
# ============================================================
class XNEKO_ModPref(bpy.types.PropertyGroup):
    mod_type: StringProperty()
    custom_name: StringProperty(
        name="Custom Name",
        description=(
            "Optional. When filled, overrides everything else "
            "(including the follow toggle)"
        ),
    )
    enabled: BoolProperty(
        name="Enabled",
        description="If off, this modifier type is skipped during rename",
        default=True,
    )
    follow_target: BoolProperty(
        name="Follow Target",
        description=(
            "When on, use the attached data name "
            "(Armature/Hook object, or Mask vertex group). "
            "When off, fall back to the default label"
        ),
        default=True,
    )


# ============================================================
# Scan helpers
# ============================================================
def scan_selection(context) -> SelectionInfo:
    objects = list(context.selected_objects)

    pairs = []
    types = set()
    has_arm = False
    has_mask = False
    has_hook = False

    for obj in objects:
        mods = getattr(obj, 'modifiers', None)
        if not mods:
            continue
        for mod in mods:
            pairs.append((obj, mod))
            types.add(mod.type)
            if not has_arm and mod.type == 'ARMATURE' and mod.object:
                has_arm = True
            if not has_mask and mod.type == 'MASK' and mod.vertex_group:
                has_mask = True
            if not has_hook and mod.type == 'HOOK' and mod.object:
                has_hook = True

    return SelectionInfo(
        pairs=tuple(pairs),
        types_in_use=frozenset(types),
        total_mods=len(pairs),
        object_count=len(objects),
        has_armature_target=has_arm,
        has_mask_target=has_mask,
        has_hook_target=has_hook,
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


def safe_icon(mtype: str) -> str:
    icon = MOD_ICONS.get(mtype, 'MODIFIER')
    valid = _get_valid_icons()
    if valid and icon not in valid:
        return 'MODIFIER'
    return icon


def has_any_modifier(context) -> bool:
    for obj in context.selected_objects:
        if getattr(obj, 'modifiers', None):
            return True
    return False


def get_pref(prefs, mod_type: str) -> Optional['XNEKO_ModPref']:
    for p in prefs:
        if p.mod_type == mod_type:
            return p
    return None


# ============================================================
# Pre-population
# ============================================================
def ensure_prefs_for_scene(scene) -> None:
    prefs = getattr(scene, 'xneko_mod_prefs', None)
    if prefs is None:
        return
    existing = {p.mod_type for p in prefs}
    for mtype in DEFAULT_MOD_NAMES:
        if mtype not in existing:
            p = prefs.add()
            p.mod_type = mtype


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
#   2. follow_target on     -- use the attached data name
#   3. default label        -- fallback
# ============================================================
def _compute_name(mod, pref):
    custom = (pref.custom_name.strip() if pref and pref.custom_name else "")
    if custom:
        return custom

    follow = bool(pref.follow_target) if pref else True

    if follow:
        if mod.type == 'ARMATURE' and mod.object:
            return mod.object.name
        if mod.type == 'HOOK' and mod.object:
            return mod.object.name
        if mod.type == 'MASK' and mod.vertex_group:
            return mod.vertex_group

    return DEFAULT_MOD_NAMES.get(mod.type, mod.type.title())


def rename_mods(pairs, prefs):
    """Rename every modifier in `pairs`.

    Returns (processed, collisions). Collisions are cases where
    Blender had to append a numeric suffix because the target name
    was already taken on the same object.
    """
    processed = 0
    collisions = 0

    for _obj, mod in pairs:
        pref = get_pref(prefs, mod.type)
        if pref is not None and not pref.enabled:
            continue

        target = _compute_name(mod, pref)
        mod.name = target
        processed += 1

        if mod.name != target:
            collisions += 1

    return processed, collisions


# ============================================================
# Panel drawing helper
# ============================================================
def draw_modifier_row(layout, entry, mtype, info):
    default = DEFAULT_MOD_NAMES.get(mtype, mtype.title())
    icon_name = safe_icon(mtype)
    row = layout.row(align=True)

    row.prop(entry, "enabled", text="")
    row.label(text=default, icon=icon_name)

    right = row.row(align=True)
    right.enabled = entry.enabled

    # Follow checkbox is meaningful only for the three target-based types
    if mtype == 'ARMATURE':
        cb = right.row(align=True)
        cb.enabled = info.has_armature_target
        cb.prop(entry, "follow_target", text="Follow Armature")

        inp = right.row(align=True)
        inp.enabled = not (entry.follow_target and info.has_armature_target)
        inp.prop(entry, "custom_name", text="", icon='SORTALPHA')

    elif mtype == 'HOOK':
        cb = right.row(align=True)
        cb.enabled = info.has_hook_target
        cb.prop(entry, "follow_target", text="Follow Object")

        inp = right.row(align=True)
        inp.enabled = not (entry.follow_target and info.has_hook_target)
        inp.prop(entry, "custom_name", text="", icon='SORTALPHA')

    elif mtype == 'MASK':
        cb = right.row(align=True)
        cb.enabled = info.has_mask_target
        cb.prop(entry, "follow_target", text="Follow VGroup")

        inp = right.row(align=True)
        inp.enabled = not (entry.follow_target and info.has_mask_target)
        inp.prop(entry, "custom_name", text="", icon='SORTALPHA')

    else:
        right.prop(entry, "custom_name", text="", icon='SORTALPHA')


# ============================================================
# Operators
# ============================================================
class XNEKO_OT_rename_modifiers(bpy.types.Operator):
    bl_idname = "xneko.rename_modifiers"
    bl_label = "Rename Modifiers"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return has_any_modifier(context)

    def invoke(self, context, event):
        scene = context.scene
        if getattr(scene, "xneko_mod_show_warning", True):
            return context.window_manager.invoke_props_dialog(self, width=400)
        return self.execute(context)

    def draw(self, context):
        info = scan_selection(context)
        col = self.layout.column()
        col.label(text="Rename modifiers?", icon='QUESTION')
        col.separator()
        col.label(
            text=f"Will process {info.total_mods} modifier(s) "
                 f"on {info.object_count} object(s)"
        )
        col.separator()
        col.label(text="· Existing modifier names will be overwritten")
        col.label(text="· Duplicate targets get '.001' suffixes")
        col.label(text="· Ctrl+Z works within this session")

    def execute(self, context):
        scene = context.scene
        ensure_prefs_for_scene(scene)
        info = scan_selection(context)

        n, collisions = rename_mods(info.pairs, scene.xneko_mod_prefs)

        if n == 0:
            self.report({'WARNING'}, "No entries are enabled")
            return {'CANCELLED'}

        if collisions:
            self.report(
                {'INFO'},
                f"Renamed {n} modifier(s); "
                f"{collisions} name collision(s) got .001 suffixes",
            )
        else:
            self.report({'INFO'}, f"Renamed {n} modifier(s)")
        return {'FINISHED'}


class XNEKO_OT_toggle_all_enabled(bpy.types.Operator):
    bl_idname = "xneko.rename_modifiers_toggle_all"
    bl_label = "Toggle All Enabled"
    bl_description = "Toggle the enabled state of all visible entries"

    def execute(self, context):
        scene = context.scene
        ensure_prefs_for_scene(scene)
        info = scan_selection(context)
        prefs = scene.xneko_mod_prefs

        visible = [p for p in prefs if p.mod_type in info.types_in_use]
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
class VIEW3D_PT_xneko_rename_modifiers(bpy.types.Panel):
    bl_label = "Rename Modifiers"
    bl_idname = "VIEW3D_PT_xneko_rename_modifiers"
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

        # Case 2: selection has no modifiers
        if not has_any_modifier(context):
            box = layout.box()
            box.label(text="No modifiers in target", icon='INFO')
            return

        # Case 3: normal
        ensure_prefs_for_scene(scene)

        mod_prefs = scene.xneko_mod_prefs
        info = scan_selection(context)

        layout.label(
            text=f"Selected {info.object_count} object(s) / "
                 f"{info.total_mods} modifier(s)"
        )

        hint = layout.row()
        hint.enabled = False
        hint.label(text="Settings below are stored in this .blend", icon='INFO')

        layout.separator()

        for mtype in sorted(info.types_in_use):
            entry = get_pref(mod_prefs, mtype)
            if entry is None:
                continue
            draw_modifier_row(layout, entry, mtype, info)

        layout.separator()

        row = layout.row(align=True)
        row.operator("xneko.rename_modifiers", icon='MODIFIER')
        row.prop(scene, "xneko_mod_show_warning", text="Confirm")

        visible = [p for p in mod_prefs if p.mod_type in info.types_in_use]
        all_on = all(p.enabled for p in visible) if visible else True
        layout.operator(
            "xneko.rename_modifiers_toggle_all",
            text="Disable All" if all_on else "Enable All",
            icon='CHECKBOX_HLT' if all_on else 'CHECKBOX_DEHLT',
        )


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_ModPref,
    XNEKO_OT_rename_modifiers,
    XNEKO_OT_toggle_all_enabled,
    VIEW3D_PT_xneko_rename_modifiers,
)

scene_props = {
    "xneko_mod_prefs": CollectionProperty(type=XNEKO_ModPref),
    "xneko_mod_show_warning": BoolProperty(
        name="Show Confirmation",
        description=(
            "Show a confirmation dialog before renaming. "
            "Turn off to rename immediately"
        ),
        default=True,
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