import bpy
import re

# ── Metadata ─────────────────────────────────────────────
tool_id = "node_group_clean"
tool_name = "Node Group Clean"
tool_default_enabled = True
blender_version_min = (4, 2, 0)


# ── Constants ────────────────────────────────────────────
_GROUP_NODE_TYPES = frozenset((
    'ShaderNodeGroup',
    'GeometryNodeGroup',
    'CompositorNodeGroup',
    'FunctionNodeGroup',
))

_NODE_PROP_SKIP = frozenset((
    'name', 'label', 'location', 'location_absolute',
    'width', 'height', 'color', 'select', 'hide',
    'show_options', 'show_preview', 'show_texture',
    'use_custom_color', 'parent', 'dimensions',
    'inputs', 'outputs', 'internal_links',
    'rna_type', 'bl_idname', 'bl_label', 'bl_static_type',
))

_PROP_TYPE_WHITELIST = frozenset((
    'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM',
))

_WL_ITERATIONS = 1
_rna_props_cache = {}


# ── Properties ───────────────────────────────────────────
class NGD_IsolatedItem(bpy.types.PropertyGroup):
    mat_name: bpy.props.StringProperty()
    node_name: bpy.props.StringProperty()
    group_name: bpy.props.StringProperty()
    selected: bpy.props.BoolProperty(default=True)


# ── State ────────────────────────────────────────────────
_is_scanned = False
_scan_cache = {
    'duplicates': None,
    'group_count': 0,
}
_sig_cache = {}
_search_results = None


def _invalidate_scan_cache(_scene=None):
    global _is_scanned
    _is_scanned = False
    _scan_cache['duplicates'] = None
    _scan_cache['group_count'] = 0
    _sig_cache.clear()


def _tag_redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'NODE_EDITOR'}:
                area.tag_redraw()


# ── Context Materials ────────────────────────────────────
def _get_target_materials(context):
    target = set()
    if context.area and context.area.type == 'NODE_EDITOR':
        if context.space_data and context.space_data.type == 'MATERIAL':
            if context.space_data.id and context.space_data.id.type == 'MATERIAL':
                target.add(context.space_data.id)
                
    for obj in context.selected_objects:
        if hasattr(obj, 'material_slots'):
            for slot in obj.material_slots:
                if slot.material:
                    target.add(slot.material)
    return target


# ── Signature ────────────────────────────────────────────
def _is_group_node(node):
    return node.bl_idname in _GROUP_NODE_TYPES


def _get_rna_props_for_type(bl_idname, rna_props):
    if bl_idname in _rna_props_cache:
        return _rna_props_cache[bl_idname]
    
    props = []
    for prop in rna_props:
        ident = prop.identifier
        if ident in _NODE_PROP_SKIP:
            continue
        if prop.type not in _PROP_TYPE_WHITELIST:
            continue
        if getattr(prop, 'array_length', 0) > 0:
            continue
        props.append(ident)
    
    _rna_props_cache[bl_idname] = props
    return props


def _node_props(node):
    try:
        rna = node.bl_rna.properties
    except Exception:
        return ""
        
    idents = _get_rna_props_for_type(node.bl_idname, rna)
    props = []
    for ident in idents:
        try:
            value = getattr(node, ident)
            if isinstance(value, float):
                value = round(value, 4)
            elif hasattr(value, 'identifier'): # Enum
                value = value.identifier
            elif not isinstance(value, (str, int, bool)):
                continue
            props.append(f"{ident}={value}")
        except Exception:
            pass
    return "|".join(sorted(props))


def _get_valid_graph_elements(group):
    """BFS Pruning: Traverse from Input and Output to filter out dead nodes."""
    input_nodes = set()
    output_nodes = set()
    
    for node in group.nodes:
        if node.bl_idname == 'NodeGroupInput':
            input_nodes.add(node.as_pointer())
        elif node.bl_idname == 'NodeGroupOutput':
            output_nodes.add(node.as_pointer())
            
    if not input_nodes or not output_nodes:
        return set(), []

    adj_out = {}
    adj_in = {}
    for link in group.links:
        f_p = link.from_node.as_pointer()
        t_p = link.to_node.as_pointer()
        adj_out.setdefault(f_p, []).append(t_p)
        adj_in.setdefault(t_p, []).append(f_p)

    reachable_from_in = set(input_nodes)
    queue = list(input_nodes)
    while queue:
        curr = queue.pop(0)
        for nxt in adj_out.get(curr, []):
            if nxt not in reachable_from_in:
                reachable_from_in.add(nxt)
                queue.append(nxt)

    reachable_to_out = set(output_nodes)
    queue = list(output_nodes)
    while queue:
        curr = queue.pop(0)
        for prev in adj_in.get(curr, []):
            if prev not in reachable_to_out:
                reachable_to_out.add(prev)
                queue.append(prev)

    valid_nodes = reachable_from_in & reachable_to_out
    
    valid_links = []
    for link in group.links:
        f_p = link.from_node.as_pointer()
        t_p = link.to_node.as_pointer()
        if f_p in valid_nodes and t_p in valid_nodes:
            valid_links.append((f_p, link.from_socket.identifier,
                                t_p, link.to_socket.identifier))
                                
    return valid_nodes, valid_links


def _group_signature(group, visiting=frozenset()):
    ptr = group.as_pointer()
    if ptr in visiting:
        return "<cycle>"
    if not visiting and ptr in _sig_cache:
        return _sig_cache[ptr]

    visiting = visiting | {ptr}
    
    valid_node_ptrs, edges = _get_valid_graph_elements(group)
    
    node_by_ptr = {}
    sigs = {}
    
    # Calculate initial signatures using integer hashes for performance
    for node in group.nodes:
        p = node.as_pointer()
        if p not in valid_node_ptrs:
            continue
        node_by_ptr[p] = node
        
        nested = ""
        if _is_group_node(node) and node.node_tree is not None:
            nested = _group_signature(node.node_tree, visiting)
            
        sig_str = f"{node.bl_idname}[{_node_props(node)}]<{nested}>"
        sigs[p] = hash(sig_str)

    if len(sigs) < 2:
        result = str(tuple(sorted(sigs.values())))
    else:
        # WL Iterations using integer hashes
        for _ in range(_WL_ITERATIONS):
            incoming = {}
            outgoing = {}
            for frm_p, frm_id, to_p, to_id in edges:
                incoming.setdefault(to_p, []).append((frm_p, frm_id, to_id))
                outgoing.setdefault(frm_p, []).append((to_p, frm_id, to_id))

            new_sigs = {}
            for p in node_by_ptr:
                inc = hash(tuple(sorted(hash((sigs[frm_p], frm_id, to_id)) for frm_p, frm_id, to_id in incoming.get(p, ()))))
                out = hash(tuple(sorted(hash((sigs[to_p], frm_id, to_id)) for to_p, frm_id, to_id in outgoing.get(p, ()))))
                new_sigs[p] = hash((sigs[p], inc, out))
            sigs = new_sigs
            
        result = str(tuple(sorted(sigs.values())))
    
    if len(visiting) == 1:
        _sig_cache[ptr] = result
    return result


def _get_graph_fingerprint(group):
    """L2 Fast Filter: Interface signature + Node count + Link count."""
    items = []
    try:
        for item in group.interface.items_tree:
            if not hasattr(item, 'in_out'):
                continue
            items.append(f"{item.in_out}:{getattr(item, 'socket_type', '')}")
    except Exception:
        pass
    iface_str = "|".join(items)
    
    nodes_count = len(group.nodes)
    links_count = len(group.links)
    
    return f"{nodes_count}:{links_count}:{iface_str}"


# ── Scanning & Search Core ───────────────────────────────
def _scan_isolated(target_mats, wm):
    wm.ngd_isolated_items.clear()
    for mat in target_mats:
        nt = mat.node_tree
        if not nt: continue
        for node in nt.nodes:
            if _is_group_node(node) and node.node_tree:
                has_in = any(i.is_linked for i in node.inputs)
                has_out = any(o.is_linked for o in node.outputs)
                if not has_in and not has_out:
                    item = wm.ngd_isolated_items.add()
                    item.mat_name = mat.name
                    item.node_name = node.name
                    item.group_name = node.node_tree.name
                    item.selected = True


def _run_scan(context):
    global _is_scanned
    _invalidate_scan_cache()
    
    target_mats = _get_target_materials(context)
    if not target_mats:
        return

    wm = context.window_manager
    _scan_isolated(target_mats, wm)

    mat_nodes = []
    used_groups = set()
    for mat in target_mats:
        if not mat.node_tree: continue
        for node in mat.node_tree.nodes:
            if _is_group_node(node) and node.node_tree:
                mat_nodes.append((mat, node))
                used_groups.add(node.node_tree)

    all_shaders = [ng for ng in bpy.data.node_groups if ng.bl_idname == 'ShaderNodeTree']

    # L2 Coarse Filter using combined fingerprint
    interface_pool = {}
    for ng in all_shaders:
        fp = _get_graph_fingerprint(ng)
        interface_pool.setdefault(fp, []).append(ng)

    result = []
    _sig_cache.clear()

    for mat, node in mat_nodes:
        target_group = node.node_tree
        target_fp = _get_graph_fingerprint(target_group)
        
        candidates = interface_pool.get(target_fp, [])
        if len(candidates) < 2:
            continue 

        # L3 Precise Filter (Graph Isomorphism)
        target_sig = _group_signature(target_group)
        alternatives = []
        
        for cand in candidates:
            if cand == target_group:
                continue
            
            cand_sig = _group_signature(cand)
            if cand_sig == target_sig:
                alternatives.append(cand)
                
        if alternatives:
            base_name = re.sub(r'\.\d+$', '', target_group.name).lower()
            
            def sort_key(group_obj):
                cand_base = re.sub(r'\.\d+$', '', group_obj.name).lower()
                name_match = 0 if cand_base == base_name else 1
                return (name_match, -group_obj.users, group_obj.name)
                
            alternatives.sort(key=sort_key)
            
            existing = next((r for r in result if r['target'] == target_group), None)
            if existing:
                if (mat, node) not in existing['nodes']:
                    existing['nodes'].append((mat, node))
            else:
                result.append({
                    'target': target_group,
                    'nodes': [(mat, node)],
                    'alternatives': alternatives
                })

    _scan_cache['duplicates'] = result
    _scan_cache['group_count'] = len(used_groups)
    _is_scanned = True


def _is_group_used_in_tree(tree, query, visited=None):
    if visited is None:
        visited = set()
    ptr = tree.as_pointer()
    if ptr in visited:
        return False
    visited.add(ptr)
    
    for node in tree.nodes:
        if _is_group_node(node) and node.node_tree:
            if query in node.node_tree.name.lower():
                return True
            if _is_group_used_in_tree(node.node_tree, query, visited):
                return True
    return False


# ── Reference redirection ────────────────────────────────
def _backup_inputs(node):
    backup = {}
    for inp in node.inputs:
        if inp.is_linked or not hasattr(inp, 'default_value'):
            continue
        try:
            v = inp.default_value
        except Exception:
            continue
        if hasattr(v, '__iter__') and not isinstance(v, str):
            try: v = tuple(v)
            except Exception: pass
        backup[inp.identifier] = v
    return backup


def _restore_inputs(node, backup):
    for inp in node.inputs:
        if inp.is_linked or not hasattr(inp, 'default_value'):
            continue
        if inp.identifier not in backup:
            continue
        try:
            inp.default_value = backup[inp.identifier]
        except Exception:
            pass


# ── Operators ────────────────────────────────────────────
class NGD_OT_refresh(bpy.types.Operator):
    """Perform a full manual scan"""
    bl_idname = "ngd.refresh"
    bl_label = "Scan Now"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _run_scan(context)
        _tag_redraw(context)
        return {'FINISHED'}


class NGD_OT_copy_text(bpy.types.Operator):
    """Copy text to clipboard"""
    bl_idname = "ngd.copy_text"
    bl_label = "Copy Text"
    bl_options = {'INTERNAL'}

    text: bpy.props.StringProperty()

    def execute(self, context):
        context.window_manager.clipboard = self.text
        self.report({'INFO'}, f"Copied: {self.text}")
        return {'FINISHED'}


class NGD_OT_search_group(bpy.types.Operator):
    """Search for materials using a node group"""
    bl_idname = "ngd.search_group"
    bl_label = "Search"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global _search_results
        query = context.scene.ngd_search_query
        
        if not query:
            _search_results = None
            _tag_redraw(context)
            return {'CANCELLED'}
            
        _search_results = []
        q = query.lower().strip()
        
        for mat in bpy.data.materials:
            if not mat.node_tree: 
                continue
            if _is_group_used_in_tree(mat.node_tree, q):
                try:
                    _search_results.append(mat.name)
                except ReferenceError:
                    pass
                    
        _search_results.sort()
        _tag_redraw(context)
        return {'FINISHED'}


class NGD_OT_replace_single(bpy.types.Operator):
    """Replace current node group usage with the selected alternative"""
    bl_idname = "ngd.replace_single"
    bl_label = "Replace Node Group"
    bl_options = {'REGISTER', 'UNDO'}

    target_name: bpy.props.StringProperty()
    replacement_name: bpy.props.StringProperty()

    def execute(self, context):
        if not _is_scanned: return {'CANCELLED'}
        
        target = bpy.data.node_groups.get(self.target_name)
        replacement = bpy.data.node_groups.get(self.replacement_name)
        
        if not target or not replacement:
            return {'CANCELLED'}
            
        count = 0
        for entry in _scan_cache['duplicates']:
            if entry['target'] == target:
                for mat, node in entry['nodes']:
                    try:
                        _ = mat.name
                        _ = node.name
                        backup = _backup_inputs(node)
                        node.node_tree = replacement
                        _restore_inputs(node, backup)
                        count += 1
                    except ReferenceError:
                        pass
                break
        
        self.report({'INFO'}, f"Replaced {count} instance(s).")
        _run_scan(context)
        _tag_redraw(context)
        return {'FINISHED'}


class NGD_OT_replace_all_auto(bpy.types.Operator):
    """Automatically replace all targets with the best matched alternative"""
    bl_idname = "ngd.replace_all_auto"
    bl_label = "Auto Replace All"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not _is_scanned or not _scan_cache['duplicates']:
            self.report({'INFO'}, "No replacements needed.")
            return {'CANCELLED'}

        count = 0
        for entry in _scan_cache['duplicates']:
            target = entry['target']
            best_alt = entry['alternatives'][0]
            
            for mat, node in entry['nodes']:
                try:
                    _ = mat.name
                    _ = node.name
                    backup = _backup_inputs(node)
                    node.node_tree = best_alt
                    _restore_inputs(node, backup)
                    count += 1
                except ReferenceError:
                    pass
                
        self.report({'INFO'}, f"Auto-replaced {count} instance(s).")
        _run_scan(context)
        _tag_redraw(context)
        return {'FINISHED'}


class NGD_OT_clear_isolated(bpy.types.Operator):
    """Clear selected isolated node instances"""
    bl_idname = "ngd.clear_isolated"
    bl_label = "Clear Selected Refs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not _is_scanned:
            self.report({'INFO'}, "Please scan first.")
            return {'CANCELLED'}
            
        wm = context.window_manager
        count = 0
        
        for item in wm.ngd_isolated_items:
            if not item.selected:
                continue
            mat = bpy.data.materials.get(item.mat_name)
            if not mat or not mat.node_tree:
                continue
            node = mat.node_tree.nodes.get(item.node_name)
            if not node:
                continue
            mat.node_tree.nodes.remove(node)
            count += 1
                
        self.report({'INFO'}, f"Cleared {count} selected instance(s).")
        _run_scan(context)
        _tag_redraw(context)
        return {'FINISHED'}


class NGD_OT_clean_all(bpy.types.Operator):
    """Auto replace duplicates and clear selected isolated nodes in one go"""
    bl_idname = "ngd.clean_all"
    bl_label = "Clean Everything"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not _is_scanned:
            self.report({'INFO'}, "Please scan first.")
            return {'CANCELLED'}

        redirects = 0
        removals = 0

        if _scan_cache['duplicates']:
            for entry in _scan_cache['duplicates']:
                target = entry['target']
                best_alt = entry['alternatives'][0]
                for mat, node in entry['nodes']:
                    try:
                        _ = mat.name
                        _ = node.name
                        backup = _backup_inputs(node)
                        node.node_tree = best_alt
                        _restore_inputs(node, backup)
                        redirects += 1
                    except ReferenceError:
                        pass

        wm = context.window_manager
        for item in wm.ngd_isolated_items:
            if not item.selected:
                continue
            mat = bpy.data.materials.get(item.mat_name)
            if not mat or not mat.node_tree:
                continue
            node = mat.node_tree.nodes.get(item.node_name)
            if not node:
                continue
            mat.node_tree.nodes.remove(node)
            removals += 1

        self.report({'INFO'}, f"Cleaned: {redirects} replaced, {removals} removed.")
        _run_scan(context)
        _tag_redraw(context)
        return {'FINISHED'}


# ── Panel ────────────────────────────────────────────────
class VIEW3D_PT_node_group_clean(bpy.types.Panel):
    bl_label = "Node Group Clean"
    bl_idname = "VIEW3D_PT_node_group_clean"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        target_mats = _get_target_materials(context)
        wm = context.window_manager
        valid_entries = 0  # Declared early to avoid UnboundLocalError

        # ═══════════════════════════════════════════════
        # Block 1-3: Scan & Clean (Requires selection)
        # ═══════════════════════════════════════════════
        if not target_mats:
            box = layout.box()
            box.label(text="No material selected.", icon='ERROR')
            box.label(text="Select an object with materials to scan.")
        else:
            row = layout.row(align=True)
            row.label(text=f"Selected: {len(target_mats)} mat(s)", icon='MATERIAL')
            row.operator("ngd.refresh", text="Scan Now", icon='FILE_REFRESH')

            if not _is_scanned:
                box = layout.box()
                box.label(text="Click 'Scan Now' to scan.", icon='INFO')
                
            else:
                group_count = _scan_cache['group_count']
                layout.label(text=f"Scanned {group_count} group(s) in use.", icon='CHECKMARK')

                # Block 1: Duplicates
                box_dup = layout.box()
                box_dup.label(text="Duplicate Groups:", icon='DUPLICATE')
                
                entries = _scan_cache['duplicates']
                if not entries:
                    box_dup.label(text="None found.", icon='CHECKMARK')
                else:
                    col = box_dup.column(align=True)
                    
                    for entry in entries:
                        target = entry['target']
                        try:
                            target_name = target.name
                            target_users = target.users
                        except ReferenceError:
                            continue

                        node_count = len(entry['nodes'])
                        valid_entries += 1
                        
                        sub = col.column(align=True)
                        sub.label(text=f"{target_name} (in {node_count} instance(s))", icon='NODETREE')
                        
                        for alt in entry['alternatives']:
                            try:
                                alt_name = alt.name
                                alt_users = alt.users
                            except ReferenceError:
                                continue
                                
                            row = sub.row(align=True)
                            row.label(text="", icon='BLANK1')
                            op = row.operator("ngd.replace_single", text=f"Use {alt_name} ({alt_users}u)", icon='LOOP_BACK')
                            op.target_name = target_name
                            op.replacement_name = alt_name

                    if valid_entries == 0:
                        box_dup.label(text="None found (data removed).", icon='CHECKMARK')
                    else:
                        box_dup.label(text=f"{valid_entries} group(s) have alternatives", icon='ERROR')
                        col = box_dup.column(align=True)
                        col.scale_y = 1.2
                        col.operator("ngd.replace_all_auto", text="Auto Replace (Best Match)", icon='FILE_REFRESH')

                # Block 2: Isolated
                box_iso = layout.box()
                box_iso.label(text="Isolated Nodes:", icon='NODE')
                
                if not len(wm.ngd_isolated_items):
                    box_iso.label(text="None found.", icon='CHECKMARK')
                else:
                    col = box_iso.column(align=True)
                    for item in wm.ngd_isolated_items:
                        row = col.row(align=True)
                        row.prop(item, "selected", text="")
                        row.label(text=f"{item.group_name} (in {item.mat_name})", icon='NODE')
                    
                    box_iso.label(text=f"{len(wm.ngd_isolated_items)} unconnected node(s)", icon='INFO')
                    col = box_iso.column(align=True)
                    col.scale_y = 1.2
                    col.operator("ngd.clear_isolated", text="Clear Selected Refs", icon='TRASH')

                # Block 3: Master Clean
                if valid_entries or len(wm.ngd_isolated_items):
                    layout.separator()
                    info_box = layout.box()
                    info_box.label(text="Note: Only references are cleaned.", icon='INFO')
                    info_box.label(text="Old data becomes Orphans, safe to purge manually.")
                    
                    row = layout.row()
                    row.scale_y = 1.5
                    row.operator("ngd.clean_all", text="Clean Everything (Safe)", icon='BRUSH_DATA')

        # ═══════════════════════════════════════════════
        # Block 4: Search Usage (Always Available)
        # ═══════════════════════════════════════════════
        layout.separator()
        box_search = layout.box()
        box_search.label(text="Search Node Group Usage:", icon='VIEWZOOM')
        
        row = box_search.row(align=True)
        row.prop(context.scene, "ngd_search_query", text="")
        row.operator("ngd.search_group", text="Search", icon='VIEWZOOM')
        
        if _search_results is not None:
            if not _search_results:
                box_search.label(text="No materials found.", icon='INFO')
            else:
                box_search.label(text=f"Found in {len(_search_results)} material(s):", icon='MATERIAL')
                col = box_search.column(align=True)
                for mat_name in _search_results:
                    op = col.operator("ngd.copy_text", text=mat_name, icon='COPYDOWN')
                    op.text = mat_name


# ── Registration ─────────────────────────────────────────
classes = (
    NGD_IsolatedItem,
    NGD_OT_refresh,
    NGD_OT_copy_text,
    NGD_OT_search_group,
    NGD_OT_replace_single,
    NGD_OT_replace_all_auto,
    NGD_OT_clear_isolated,
    NGD_OT_clean_all,
    VIEW3D_PT_node_group_clean,
)


# ── Framework hooks ──────────────────────────────────────
def on_load():
    if _invalidate_scan_cache not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(_invalidate_scan_cache)
        
    bpy.types.Scene.ngd_search_query = bpy.props.StringProperty(
        name="Group Name",
        description="Enter part of the node group name to search",
        default=""
    )
    
    bpy.types.WindowManager.ngd_isolated_items = bpy.props.CollectionProperty(
        type=NGD_IsolatedItem
    )


def on_unload():
    try:
        bpy.app.handlers.undo_post.remove(_invalidate_scan_cache)
    except ValueError:
        pass
        
    if hasattr(bpy.types.Scene, "ngd_search_query"):
        del bpy.types.Scene.ngd_search_query
    if hasattr(bpy.types.WindowManager, "ngd_isolated_items"):
        del bpy.types.WindowManager.ngd_isolated_items