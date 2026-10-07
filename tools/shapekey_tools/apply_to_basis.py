import bpy


# ------------------------------------------------------------
# XNeko Tools metadata
# ------------------------------------------------------------
tool_id = "apply_to_basis"
tool_name = "Swap Shape Key with Basis"
tool_default_enabled = True
blender_version_min = (4, 0, 0)


# ============================================================
# Sync guard
# ------------------------------------------------------------
# Prevents re-entrant updates between the PropertyGroup
# update callback and the depsgraph handler.
# ============================================================
_sync_guard = {"busy": False}


# ============================================================
# PropertyGroups
# ============================================================
class XNEKO_ShapeKeyItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()


def _on_active_index_change(self, context):
    """Push the list selection to obj.active_shape_key_index."""
    if _sync_guard["busy"]:
        return
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return
    sk = obj.data.shape_keys if obj.data else None
    if sk is None:
        return
    if 0 <= self.active_index < len(sk.key_blocks):
        _sync_guard["busy"] = True
        try:
            obj.active_shape_key_index = self.active_index
        finally:
            _sync_guard["busy"] = False


class XNEKO_SwapBasisProps(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=XNEKO_ShapeKeyItem)
    active_index: bpy.props.IntProperty(
        default=0,
        update=_on_active_index_change,
    )
    source_object: bpy.props.StringProperty(default="")


# ============================================================
# Helpers
# ============================================================
def _has_shape_keys(obj):
    """Return True if obj is a mesh with at least one non-basis key."""
    if obj is None or obj.type != 'MESH':
        return False
    if obj.data is None or obj.data.shape_keys is None:
        return False
    return len(obj.data.shape_keys.key_blocks) > 1


def _active_key_index(obj):
    """Return the active non-basis shape key index, or -1 if invalid."""
    if not _has_shape_keys(obj):
        return -1
    idx = obj.active_shape_key_index
    sk = obj.data.shape_keys
    if idx <= 0 or idx >= len(sk.key_blocks):
        return -1
    return idx


def swap_with_basis(obj):
    """Swap the active shape key with the basis.

    Exchanges vertex coordinates and names between key_blocks[0]
    and the active key. Resets every key value to 0.

    Also syncs mesh.vertices to the new basis, because Blender's
    shape_key_add() uses mesh vertices as the starting shape for
    newly created keys, not key_blocks[0].data.

    Returns True on success.
    """
    if not _has_shape_keys(obj):
        return False

    idx = _active_key_index(obj)
    if idx < 0:
        return False

    sk = obj.data.shape_keys
    basis = sk.key_blocks[0]
    active = sk.key_blocks[idx]

    basis_co = [pt.co.copy() for pt in basis.data]
    active_co = [pt.co.copy() for pt in active.data]

    for i, co in enumerate(active_co):
        basis.data[i].co = co
    for i, co in enumerate(basis_co):
        active.data[i].co = co

    basis_name = basis.name
    active_name = active.name
    basis.name = active_name
    active.name = basis_name

    for kb in sk.key_blocks:
        kb.value = 0.0

    # ---- Sync mesh.vertices to the new basis ----
    # Without this, newly created shape keys would start from the
    # old basis shape, since Blender reads mesh vertices as the
    # template for new keys.
    mesh = obj.data
    if len(mesh.vertices) == len(basis.data):
        for i, v in enumerate(mesh.vertices):
            v.co = basis.data[i].co
        mesh.update()

    obj.data.update_tag()

    return True


# ============================================================
# List sync
# ============================================================
def _sync_shape_key_list(scene):
    """Refresh the cached shape key list for the active object."""
    if _sync_guard["busy"]:
        return

    props = getattr(scene, "xneko_swap_basis_props", None)
    if props is None:
        return

    obj = bpy.context.active_object

    # ---- No valid target: clear the list ----
    if (obj is None or obj.type != 'MESH'
            or obj.data is None or obj.data.shape_keys is None):
        if props.items or props.source_object:
            _sync_guard["busy"] = True
            try:
                props.items.clear()
                props.source_object = ""
                props.active_index = 0
            finally:
                _sync_guard["busy"] = False
        return

    sk = obj.data.shape_keys
    current_names = [kb.name for kb in sk.key_blocks]
    stored_names = [it.name for it in props.items]

    needs_rebuild = (
        props.source_object != obj.name
        or current_names != stored_names
    )

    if needs_rebuild:
        _sync_guard["busy"] = True
        try:
            props.items.clear()
            for kb in sk.key_blocks:
                item = props.items.add()
                item.name = kb.name
            props.source_object = obj.name
            props.active_index = obj.active_shape_key_index
            if props.active_index >= len(props.items):
                props.active_index = 0
        finally:
            _sync_guard["busy"] = False
        return

    # ---- Sync active index when changed externally ----
    if props.active_index != obj.active_shape_key_index:
        _sync_guard["busy"] = True
        try:
            props.active_index = obj.active_shape_key_index
        finally:
            _sync_guard["busy"] = False


@bpy.app.handlers.persistent
def _depsgraph_handler(scene, *args):
    try:
        _sync_shape_key_list(scene)
    except Exception as e:
        print(f"[XNeko] swap basis sync error: {e}")


# ============================================================
# UIList
# ============================================================
class XNEKO_UL_shape_keys(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.name, icon='SHAPEKEY_DATA')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='SHAPEKEY_DATA')


# ============================================================
# Operator
# ============================================================
class XNEKO_OT_apply_to_basis(bpy.types.Operator):
    bl_idname = "xneko.apply_to_basis"
    bl_label = "Swap Shape Key with Basis"
    bl_description = (
        "Exchange the active shape key with the basis. "
        "Coordinates and names are swapped, and all key values reset to 0"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return _active_key_index(obj) > 0

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}

        idx = _active_key_index(obj)
        if idx < 0:
            self.report({'ERROR'}, "Select a non-basis shape key")
            return {'CANCELLED'}

        sk = obj.data.shape_keys
        active_name = sk.key_blocks[idx].name
        basis_name = sk.key_blocks[0].name

        try:
            ok = swap_with_basis(obj)
        except Exception as e:
            self.report({'ERROR'}, f"Swap failed: {e}")
            return {'CANCELLED'}

        if not ok:
            self.report({'ERROR'}, "Swap failed")
            return {'CANCELLED'}

        # Force list rebuild on next depsgraph tick
        props = getattr(context.scene, "xneko_swap_basis_props", None)
        if props is not None:
            _sync_guard["busy"] = True
            try:
                props.source_object = ""
            finally:
                _sync_guard["busy"] = False

        self.report(
            {'INFO'},
            f"Swapped '{active_name}' with '{basis_name}'",
        )
        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================
class VIEW3D_PT_xneko_apply_to_basis(bpy.types.Panel):
    bl_label = "Swap Shape Key with Basis"
    bl_idname = "VIEW3D_PT_xneko_apply_to_basis"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # Case 1: no mesh
        if obj is None or obj.type != 'MESH':
            box = layout.box()
            box.label(text="Select a mesh object", icon='INFO')
            return

        # Case 2: no shape keys
        if not _has_shape_keys(obj):
            box = layout.box()
            box.label(text="No shape keys on this mesh", icon='INFO')
            return

        props = context.scene.xneko_swap_basis_props
        sk = obj.data.shape_keys

        # ---- Shape key list ----
        box = layout.box()
        box.label(text="Shape Keys", icon='SHAPEKEY_DATA')

        box.template_list(
            "XNEKO_UL_shape_keys", "xneko_swap_basis_keys",
            props, "items",
            props, "active_index",
            rows=6,
        )

        # ---- Swap preview ----
        idx = _active_key_index(obj)
        if idx < 0:
            info = layout.box()
            info.label(
                text="Select a non-basis key to swap",
                icon='INFO',
            )
        else:
            active = sk.key_blocks[idx]
            basis = sk.key_blocks[0]
            info = layout.box()
            info.label(
                text=f"Swap: '{active.name}' <-> '{basis.name}'",
                icon='FILE_REFRESH',
            )
            info.label(
                text="All key values will be reset to 0",
                icon='INFO',
            )

        row = layout.row()
        row.scale_y = 1.3
        row.enabled = (idx > 0)
        row.operator(
            "xneko.apply_to_basis",
            text="Swap with Basis",
            icon='SHAPEKEY_DATA',
        )


# ============================================================
# Registration declarations (consumed by core.py)
# ============================================================
classes = (
    XNEKO_ShapeKeyItem,
    XNEKO_SwapBasisProps,
    XNEKO_UL_shape_keys,
    XNEKO_OT_apply_to_basis,
    VIEW3D_PT_xneko_apply_to_basis,
)

scene_props = {
    "xneko_swap_basis_props": bpy.props.PointerProperty(
        type=XNEKO_SwapBasisProps,
    ),
}


# ============================================================
# Lifecycle
# ============================================================
def on_load():
    if _depsgraph_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_handler)


def on_unload():
    try:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_handler)
    except Exception:
        pass