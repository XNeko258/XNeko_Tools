import bpy
from bpy.props import StringProperty, CollectionProperty, BoolProperty
from typing import NamedTuple, Optional


tool_name = "Rename Modifiers"
tool_default_enabled = True


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
# PropertyGroup
# ============================================================
class VERIFY_ModPref(bpy.types.PropertyGroup):
    mod_type: StringProperty()
    custom_name: StringProperty(
        name="Custom Name",
        description=(
            "Leave empty to use the default rule: Armature/Hook uses "
            "the target object name, Mask uses the vertex group name, "
            "others use the default English label"
        ),
    )
    enabled: BoolProperty(
        name="Enabled",
        description="If off, this modifier type is skipped during rename",
        default=True,
    )


# ============================================================
# Scan helpers
# ============================================================
def scan_selection(context) -> SelectionInfo:
    pairs = []
    types = set()
    has_arm = False
    has_mask = False
    has_hook = False
    objects = context.selected_objects

    for obj in objects:
        mods = getattr(obj, 'modifiers', None)
        if not mods:
            continue
        for mod in mods:
            pairs.append((obj, mod))
            types.add(mod.type)
            if not has_arm and mod.type == 'ARMATURE' and mod.object:
                has_arm = True
            elif not has_mask and mod.type == 'MASK' and mod.vertex_group:
                has_mask = True
            elif not has_hook and mod.type == 'HOOK' and mod.object:
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
    """Cache the set of icon names supported by the current Blender build."""
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
    # If the enum list is unavailable, trust the mapping as-is
    if valid and icon not in valid:
        return 'MODIFIER'
    return icon


def has_any_modifier(context) -> bool:
    for obj in context.selected_objects:
        if getattr(obj, 'modifiers', None):
            return True
    return False


def get_pref(prefs, mod_type: str) -> Optional['VERIFY_ModPref']:
    for p in prefs:
        if p.mod_type == mod_type:
            return p
    return None


# ============================================================
# Pre-population
# ============================================================
def ensure_prefs_for_scene(scene) -> None:
    prefs = getattr(scene, 'verify_mod_prefs', None)
    if prefs is None:
        return
    existing = {p.mod_type for p in prefs}
    for mtype in DEFAULT_MOD_NAMES:
        if mtype not in existing:
            p = prefs.add()
            p.mod_type = mtype


def _prepopulate_timer():
    try:
        for scene in bpy.data.scenes:
            ensure_prefs_for_scene(scene)
    except Exception as e:
        print(f"[XNeko] prepopulate failed: {e}")
    return None


@bpy.app.handlers.persistent
def _on_load_post(_dummy):
    try:
        for scene in bpy.data.scenes:
            ensure_prefs_for_scene(scene)
    except Exception as e:
        print(f"[XNeko] load_post prepopulate failed: {e}")


# ============================================================
# Core renaming logic
# ============================================================
def rename_mods(pairs, prefs, *, use_armature: bool,
                use_group: bool, use_hook: bool) -> int:
    count = 0
    for _obj, mod in pairs:
        pref = get_pref(prefs, mod.type)
        if pref is not None and not pref.enabled:
            continue

        custom = (pref.custom_name.strip() if pref and pref.custom_name else "")

        if mod.type == 'ARMATURE':
            if use_armature and mod.object:
                mod.name = mod.object.name
            else:
                mod.name = custom or "Armature"

        elif mod.type == 'HOOK':
            if use_hook and mod.object:
                mod.name = mod.object.name
            else:
                mod.name = custom or "Hook"

        elif mod.type == 'MASK':
            if use_group and mod.vertex_group:
                mod.name = mod.vertex_group
            else:
                mod.name = custom or "Mask"

        else:
            mod.name = custom or DEFAULT_MOD_NAMES.get(
                mod.type, mod.type.title()
            )

        count += 1
    return count


# ============================================================
# Panel drawing helpers
# ============================================================
def draw_modifier_row(layout, scene, entry, mtype: str, info: SelectionInfo):
    default = DEFAULT_MOD_NAMES.get(mtype, mtype.title())
    icon_name = safe_icon(mtype)
    row = layout.row(align=True)

    row.prop(entry, "enabled", text="")
    row.label(text=default, icon=icon_name)

    right = row.row(align=True)
    right.enabled = entry.enabled

    if mtype == 'ARMATURE':
        use_obj = scene.verify_armature_use_object
        has_target = info.has_armature_target

        cb = right.row(align=True)
        cb.enabled = has_target
        cb.prop(scene, "verify_armature_use_object", text="Follow Armature")

        inp = right.row(align=True)
        inp.enabled = not (use_obj and has_target)
        inp.prop(entry, "custom_name", text="", icon='SORTALPHA')

    elif mtype == 'HOOK':
        use_hook = scene.verify_hook_use_object
        has_target = info.has_hook_target

        cb = right.row(align=True)
        cb.enabled = has_target
        cb.prop(scene, "verify_hook_use_object", text="Follow Object")

        inp = right.row(align=True)
        inp.enabled = not (use_hook and has_target)
        inp.prop(entry, "custom_name", text="", icon='SORTALPHA')

    elif mtype == 'MASK':
        use_grp = scene.verify_mask_use_group
        has_target = info.has_mask_target

        cb = right.row(align=True)
        cb.enabled = has_target
        cb.prop(scene, "verify_mask_use_group", text="Follow VGroup")

        inp = right.row(align=True)
        inp.enabled = not (use_grp and has_target)
        inp.prop(entry, "custom_name", text="", icon='SORTALPHA')

    else:
        right.prop(entry, "custom_name", text="", icon='SORTALPHA')


# ============================================================
# Operators
# ============================================================
class VERIFY_OT_rename_modifiers(bpy.types.Operator):
    bl_idname = "xneko.verify_rename_modifiers"
    bl_label = "Rename Modifiers"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return has_any_modifier(context)

    def invoke(self, context, event):
        if context.scene.verify_show_warning:
            return context.window_manager.invoke_props_dialog(self, width=400)
        return self.execute(context)

    def draw(self, context):
        info = scan_selection(context)
        col = self.layout.column()
        col.label(text="Rename modifiers on all selected objects?",
                  icon='QUESTION')
        col.separator()
        col.label(
            text=f"Will process {info.total_mods} modifier(s) "
                 f"on {info.object_count} object(s)"
        )
        col.separator()
        col.label(text="· Existing modifier names will be overwritten")
        col.label(text="· Cannot be undone after saving the file")
        col.label(text="· Ctrl+Z works within this session")

    def execute(self, context):
        scene = context.scene
        ensure_prefs_for_scene(scene)
        info = scan_selection(context)
        n = rename_mods(
            info.pairs,
            scene.verify_mod_prefs,
            use_armature=scene.verify_armature_use_object,
            use_group=scene.verify_mask_use_group,
            use_hook=scene.verify_hook_use_object,
        )
        if n == 0:
            self.report({'WARNING'}, "No entries are enabled")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Done. Processed {n} modifier(s)")
        return {'FINISHED'}


class VERIFY_OT_toggle_all_enabled(bpy.types.Operator):
    bl_idname = "xneko.verify_toggle_all_enabled"
    bl_label = "Toggle All Enabled"
    bl_description = "Toggle the enabled state of all visible entries"

    def execute(self, context):
        scene = context.scene
        ensure_prefs_for_scene(scene)
        info = scan_selection(context)
        prefs = scene.verify_mod_prefs

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
class VIEW3D_PT_xneko_verify_rename(bpy.types.Panel):
    bl_label = "Rename Modifiers"
    bl_idname = "VIEW3D_PT_xneko_verify_rename"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    @classmethod
    def poll(cls, context):
        return has_any_modifier(context)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        mod_prefs = scene.verify_mod_prefs
        info = scan_selection(context)

        layout.label(
            text=f"Selected {info.object_count} object(s) / "
                 f"{info.total_mods} modifier(s)"
        )
        layout.separator()

        for mtype in sorted(info.types_in_use):
            entry = get_pref(mod_prefs, mtype)
            if entry is None:
                continue
            draw_modifier_row(layout, scene, entry, mtype, info)

        layout.separator()

        row = layout.row(align=True)
        row.operator("xneko.verify_rename_modifiers", icon='MODIFIER')
        row.prop(scene, "verify_show_warning", text="Confirm")

        visible = [p for p in mod_prefs if p.mod_type in info.types_in_use]
        all_on = all(p.enabled for p in visible) if visible else True
        layout.operator(
            "xneko.verify_toggle_all_enabled",
            text="Disable All" if all_on else "Enable All",
            icon='CHECKBOX_HLT' if all_on else 'CHECKBOX_DEHLT',
        )


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    VERIFY_ModPref,
    VERIFY_OT_rename_modifiers,
    VERIFY_OT_toggle_all_enabled,
    VIEW3D_PT_xneko_verify_rename,
)

scene_props = {
    "verify_mod_prefs": CollectionProperty(type=VERIFY_ModPref),
    "verify_armature_use_object": BoolProperty(
        name="Follow Armature",
        description=(
            "When on, modifier name matches the armature object name; "
            "falls back to 'Armature' if nothing is assigned"
        ),
        default=True,
    ),
    "verify_hook_use_object": BoolProperty(
        name="Follow Object",
        description=(
            "When on, modifier name matches the Hook target object name; "
            "falls back to 'Hook' if nothing is assigned"
        ),
        default=True,
    ),
    "verify_mask_use_group": BoolProperty(
        name="Follow VGroup",
        description=(
            "When on, modifier name matches the vertex group name; "
            "falls back to 'Mask' if nothing is assigned"
        ),
        default=True,
    ),
    "verify_show_warning": BoolProperty(
        name="Confirm",
        description="Show a confirmation dialog when renaming",
        default=True,
    ),
}


def on_load():
    """Register the timer and load handler when the tool is enabled."""
    if not bpy.app.timers.is_registered(_prepopulate_timer):
        bpy.app.timers.register(_prepopulate_timer, first_interval=0.1)

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def on_unload():
    """Remove the timer and load handler when the tool is disabled."""
    if bpy.app.timers.is_registered(_prepopulate_timer):
        bpy.app.timers.unregister(_prepopulate_timer)

    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)