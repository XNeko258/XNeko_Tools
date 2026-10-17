import bpy
import math
import mathutils
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.props import FloatVectorProperty, FloatProperty, StringProperty, EnumProperty, BoolProperty

# ==========================================
# XNeko_Tools Framework Metadata
# ==========================================
tool_id = "quick_eye_bone"

_cached_prefs = None
_resolved_get_tool_prefs = None

# ==========================================
# Addon Preferences
# ==========================================
preference_props = {
    "eye_marker_color": FloatVectorProperty(
        name="Base Color", subtype='COLOR_GAMMA', size=4,
        default=(0.2, 1.0, 0.2, 1.0), min=0.0, max=1.0,
        description="Color of the marker cursor"
    ),
    "eye_marker_snap_color": FloatVectorProperty(
        name="Snap Color", subtype='COLOR_GAMMA', size=4,
        default=(1.0, 0.8, 0.1, 1.0), min=0.0, max=1.0,
        description="Color of the cursor when snapping"
    ),
    "eye_marker_size": FloatProperty(
        name="Cursor Size", default=8.0, soft_min=2.0, soft_max=30.0,
        description="Radius of the marker cursor"
    ),
    "snap_sensitivity": FloatProperty(
        name="Snap Sensitivity", default=0.1, min=0.001, max=1.0,
        description="Distance (in meters) at which vertex/edge snapping triggers"
    ),

    # Bone Naming
    "eye_bone_name_l": StringProperty(name="Left Eye Bone", default="Eye.L"),
    "eye_bone_name_r": StringProperty(name="Right Eye Bone", default="Eye.R"),
    "bone_name_ctrl_master": StringProperty(name="Master Control Bone", default="Eye.Control.C"),
    "bone_name_ctrl_l": StringProperty(name="Left Control Bone", default="Eye.Control.L"),
    "bone_name_ctrl_r": StringProperty(name="Right Control Bone", default="Eye.Control.R"),
    "bone_name_ctrl_pupil": StringProperty(name="Pupil Control Bone", default="Eye.Control.Pupil"),

    # Controller Size
    "ctrl_offset_dist": FloatProperty(
        name="Controller Offset Distance", default=0.05, min=0.0, max=1.0,
        description="Distance from the anchor point to the controller (meters)"
    ),
    "ctrl_length": FloatProperty(
        name="Controller Length", default=0.01, min=0.01, max=1.0,
        description="Length of the controller bone"
    )
}

def draw_preferences(layout, context, prefs):
    global _cached_prefs
    _cached_prefs = prefs

    box = layout.box()
    box.label(text="Marker Settings", icon='EYEDROPPER')
    grid = box.grid_flow(row_major=True, columns=2, align=True)
    grid.use_property_split = True
    prefs.prop(grid, "eye_marker_color")
    prefs.prop(grid, "eye_marker_snap_color")
    prefs.prop(grid, "eye_marker_size")
    prefs.prop(grid, "snap_sensitivity")

    box = layout.box()
    box.label(text="Bone Naming Settings", icon='BONE_DATA')
    grid = box.grid_flow(row_major=True, columns=2, align=True)
    grid.use_property_split = True
    prefs.prop(grid, "eye_bone_name_l")
    prefs.prop(grid, "eye_bone_name_r")
    prefs.prop(grid, "bone_name_ctrl_master")
    prefs.prop(grid, "bone_name_ctrl_l")
    prefs.prop(grid, "bone_name_ctrl_r")
    prefs.prop(grid, "bone_name_ctrl_pupil")

    box = layout.box()
    box.label(text="Controller Dimensions", icon='CON_TRACKTO')
    grid = box.grid_flow(row_major=True, columns=2, align=True)
    grid.use_property_split = True
    prefs.prop(grid, "ctrl_offset_dist")
    prefs.prop(grid, "ctrl_length")

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
    global _cached_prefs
    if _cached_prefs is not None:
        return _cached_prefs

    get_tool_prefs = _resolve_get_tool_prefs()
    if get_tool_prefs is None:
        return None

    try:
        return get_tool_prefs(tool_id)
    except Exception:
        return None

# Helper function: align bone Z axis (referenced from ARP)
def align_bone_z_axis(edit_bone, target_z):
    y_axis = edit_bone.y_axis
    x_axis = y_axis.cross(target_z).normalized()
    new_z_axis = x_axis.cross(y_axis).normalized()
    edit_bone.align_roll(new_z_axis)


# ==========================================
# Main Modal Operator
# ==========================================
class XNEKO_OT_eye_rig_modal(bpy.types.Operator):
    """Click to enter placement mode and draw glowing markers"""
    bl_idname = "xneko.eye_rig_modal"
    bl_label = "Quick Eye Rig Modal"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        obj = context.active_object
        if (not obj or obj.type != 'MESH' 
                or not obj.select_get() 
                or not obj.visible_get() 
                or context.mode != 'OBJECT'):
            self.report({'WARNING'}, "Please select a visible mesh in the viewport in Object Mode!")
            return {'CANCELLED'}

        self.obj = obj
        self.region = context.region
        self.rv3d = context.region_data
        self.anchors = []
        
        self.is_rmb_down = False
        self.rmb_start_pos = (0, 0)
        
        self.preview_left_loc = None
        self.preview_right_loc = None
        self.is_snapped = False
        
        self.build_search_trees(context)
        
        self.draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback, (context,), 'WINDOW', 'POST_PIXEL'
        )
        
        context.view_layer.objects.active = self.obj
        context.window.cursor_modal_set('CROSSHAIR')
        context.window_manager.modal_handler_add(self)
        
        context.area.header_text_set("Left Click: Confirm | Right Click / ESC: Cancel | Hold Ctrl: Snap | Right Drag: Rotate View")
        return {'RUNNING_MODAL'}

    def build_search_trees(self, context):
        depsgraph = context.evaluated_depsgraph_get()
        self.bvh = BVHTree.FromObject(self.obj, depsgraph)
        
        self.kd = mathutils.kdtree.KDTree(len(self.obj.data.vertices))
        for i, v in enumerate(self.obj.data.vertices):
            self.kd.insert(v.co, i)
        self.kd.balance()
        
        self.edges = self.obj.data.edges
        self.edge_kd = mathutils.kdtree.KDTree(len(self.edges))
        for i, e in enumerate(self.edges):
            v0 = self.obj.data.vertices[e.vertices[0]].co
            v1 = self.obj.data.vertices[e.vertices[1]].co
            mid = (v0 + v1) / 2.0
            self.edge_kd.insert(mid, i)
        self.edge_kd.balance()

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        if event.type == 'RIGHTMOUSE':
            if event.value == 'PRESS':
                self.is_rmb_down = True
                self.rmb_start_pos = (event.mouse_x, event.mouse_y)
                return {'PASS_THROUGH'} 
            elif event.value == 'RELEASE':
                if getattr(self, 'is_rmb_down', False):
                    self.is_rmb_down = False
                    dist = abs(event.mouse_x - self.rmb_start_pos[0]) + abs(event.mouse_y - self.rmb_start_pos[1])
                    if dist < 5: 
                        if hasattr(self, 'cleanup'):
                            self.cleanup(context)
                        else:
                            context.window.cursor_modal_restore()
                            context.area.header_text_set(None)
                        return {'CANCELLED'}
                return {'PASS_THROUGH'}

        if event.type == 'ESC':
            if hasattr(self, 'cleanup'):
                self.cleanup(context)
            else:
                context.window.cursor_modal_restore()
                context.area.header_text_set(None)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            if getattr(self, 'is_rmb_down', False):
                return {'PASS_THROUGH'} 
            else:
                self.update_symmetric_preview(context, event)

        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if len(self.anchors) == 0:
                if self.preview_left_loc != self.preview_right_loc and self.preview_left_loc is not None:
                    self.anchors = [self.preview_left_loc.copy(), self.preview_right_loc.copy()]
                    
                    if hasattr(self, 'cleanup'):
                        self.cleanup(context)
                    else:
                        context.window.cursor_modal_restore()
                        context.area.header_text_set(None)
                    
                    try:
                        self.generate_bones(context)
                    except Exception as e:
                        self.report({'ERROR'}, f"Generation failed: {e}")
                    
                    return {'FINISHED'}
            else:
                if hasattr(self, 'cleanup'):
                    self.cleanup(context)
                return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def update_symmetric_preview(self, context, event):
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, coord)
        
        obj_origin = self.obj.matrix_world.inverted() @ origin
        obj_dir = self.obj.matrix_world.inverted().to_3x3() @ direction
        
        hit_loc, hit_normal, face_index, dist = self.bvh.ray_cast(obj_origin, obj_dir)

        if hit_loc:
            world_loc = self.obj.matrix_world @ hit_loc
            
            ts = context.scene.tool_settings
            do_snap = event.ctrl or ts.use_snap
            is_snapped = False
            
            if do_snap:
                snap_elems = ts.snap_elements
                prefs = _get_prefs()
                snap_threshold = getattr(prefs, "snap_sensitivity", 0.1) if prefs else 0.1
                
                # Vertex Snap
                if 'VERTEX' in snap_elems:
                    closest_co, index, dist_kd = self.kd.find(hit_loc)
                    if dist_kd < snap_threshold: 
                        world_loc = self.obj.matrix_world @ closest_co
                        is_snapped = True
                
                # Edge / Edge Midpoint Snap
                elif not is_snapped and ('EDGE' in snap_elems or 'EDGE_MIDPOINT' in snap_elems):
                    if face_index >= 0 and face_index < len(self.obj.data.polygons):
                        poly = self.obj.data.polygons[face_index]
                        min_dist = float('inf')
                        best_snap_co = None
                        
                        for i in range(len(poly.vertices)):
                            v0_idx = poly.vertices[i]
                            v1_idx = poly.vertices[(i + 1) % len(poly.vertices)]
                            
                            v0 = self.obj.data.vertices[v0_idx].co
                            v1 = self.obj.data.vertices[v1_idx].co
                            
                            if 'EDGE_MIDPOINT' in snap_elems:
                                mid = (v0 + v1) / 2.0
                                d = (mid - hit_loc).length
                                if d < min_dist:
                                    min_dist = d
                                    best_snap_co = mid
                            elif 'EDGE' in snap_elems:
                                pt_proj, factor = mathutils.geometry.intersect_point_line(hit_loc, v0, v1)
                                factor = max(0.0, min(1.0, factor))
                                pt_on_edge = v0 + (v1 - v0) * factor
                                d = (hit_loc - pt_on_edge).length
                                
                                if d < min_dist:
                                    min_dist = d
                                    best_snap_co = pt_on_edge
                                    
                        if best_snap_co and min_dist < snap_threshold:
                            world_loc = self.obj.matrix_world @ best_snap_co
                            is_snapped = True

                # Face Snap
                if not is_snapped and 'FACE' in snap_elems:
                    is_snapped = True
            
            self.preview_left_loc = world_loc
            self.is_snapped = is_snapped
            
        else:
            # If mouse leaves the mesh, project onto a virtual plane at the object's origin
            depth_loc = self.obj.location
            world_loc = view3d_utils.region_2d_to_location_3d(self.region, self.rv3d, coord, depth_loc)
            self.preview_left_loc = world_loc
            self.is_snapped = False

        # Symmetry Calculation
        symmetry_axis = getattr(context.scene, "quick_eye_symmetry_axis", 'X')
        
        x, y, z = self.preview_left_loc.x, self.preview_left_loc.y, self.preview_left_loc.z
        
        if symmetry_axis == 'X':
            if abs(x) < 0.005: x = 0.005
            self.preview_right_loc = Vector((-x, y, z))
        elif symmetry_axis == 'Y':
            if abs(y) < 0.005: y = 0.005
            self.preview_right_loc = Vector((x, -y, z))
        else:
            if abs(x) < 0.005: x = 0.005
            self.preview_right_loc = Vector((-x, y, z))

    def draw_callback(self, context):
        if not self.preview_left_loc or not self.preview_right_loc:
            return
            
        region = context.region
        rv3d = context.space_data.region_3d
        
        loc_left_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self.preview_left_loc)
        loc_right_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self.preview_right_loc)
        
        if not loc_left_2d or not loc_right_2d:
            return
            
        prefs = _get_prefs()
        if prefs:
            base_color = prefs.eye_marker_color
            snap_color = prefs.eye_marker_snap_color
            marker_size = prefs.eye_marker_size
        else:
            base_color = (0.2, 1.0, 0.2, 1.0)
            snap_color = (1.0, 0.8, 0.1, 1.0)
            marker_size = 8.0
            
        color = snap_color if self.is_snapped else base_color
            
        gpu.state.blend_set('ALPHA')
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        
        self.draw_marker_graphics(shader, loc_left_2d, color, marker_size)
        self.draw_marker_graphics(shader, loc_right_2d, color, marker_size)
        
        gpu.state.blend_set('NONE')

    def draw_marker_graphics(self, shader, pos, color, size):
        segments = 32
        
        halo_radius = size * 1.6
        ring_inner = size
        ring_outer = size + 2.0
        center_radius = size * 0.5
        
        # Halo
        halo_color = (color[0], color[1], color[2], 0.2)
        coords_halo = [pos]
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            coords_halo.append((pos[0] + halo_radius * math.cos(angle), pos[1] + halo_radius * math.sin(angle)))
        coords_halo.append(coords_halo[1])
        
        # Ring
        coords_ring = []
        for i in range(segments):
            a1 = 2 * math.pi * i / segments
            a2 = 2 * math.pi * (i+1) / segments
            
            p1_in = (pos[0] + ring_inner * math.cos(a1), pos[1] + ring_inner * math.sin(a1))
            p2_in = (pos[0] + ring_inner * math.cos(a2), pos[1] + ring_inner * math.sin(a2))
            p1_out = (pos[0] + ring_outer * math.cos(a1), pos[1] + ring_outer * math.sin(a1))
            p2_out = (pos[0] + ring_outer * math.cos(a2), pos[1] + ring_outer * math.sin(a2))
            
            coords_ring.extend([p1_in, p1_out, p2_out, p1_in, p2_out, p2_in])
            
        # Center Dot
        coords_center = [pos]
        for i in range(16):
            angle = 2 * math.pi * i / 16
            coords_center.append((pos[0] + center_radius * math.cos(angle), pos[1] + center_radius * math.sin(angle)))
        coords_center.append(coords_center[1])

        batch_halo = batch_for_shader(shader, 'TRI_FAN', {"pos": coords_halo})
        shader.bind()
        shader.uniform_float("color", halo_color)
        batch_halo.draw(shader)
        
        batch_ring = batch_for_shader(shader, 'TRIS', {"pos": coords_ring})
        shader.bind()
        shader.uniform_float("color", color)
        batch_ring.draw(shader)
        
        batch_center = batch_for_shader(shader, 'TRI_FAN', {"pos": coords_center})
        shader.bind()
        shader.uniform_float("color", color)
        batch_center.draw(shader)

    def generate_bones(self, context):
        col_name = "Eye_Rig_Collection"
        eye_col = bpy.data.collections.get(col_name)
        if not eye_col:
            eye_col = bpy.data.collections.new(col_name)
            context.scene.collection.children.link(eye_col)

        arm_data = bpy.data.armatures.new("Eye_Rig_Data")
        arm_obj = bpy.data.objects.new("Eye_Rig", arm_data)
        eye_col.objects.link(arm_obj)
        
        show_front = getattr(context.scene, "quick_eye_show_in_front", True)
        arm_obj.show_in_front = show_front

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')

        try:
            ebones = arm_obj.data.edit_bones
            left_pos = self.anchors[0]
            right_pos = self.anchors[1]
            
            prefs = _get_prefs()
            
            gen_deform = getattr(context.scene, "quick_eye_gen_deform", True)
            gen_ctrl_pupil = getattr(context.scene, "quick_eye_gen_pupil", True)
            
            # Fallbacks for empty names
            actual_bone_l = getattr(prefs, "eye_bone_name_l", "").strip() or "Eye.L"
            actual_bone_r = getattr(prefs, "eye_bone_name_r", "").strip() or "Eye.R"
            actual_master_ctrl = getattr(prefs, "bone_name_ctrl_master", "").strip() or "Eye.Control.C"
            actual_ctrl_l = getattr(prefs, "bone_name_ctrl_l", "").strip() or "Eye.Control.L"
            actual_ctrl_r = getattr(prefs, "bone_name_ctrl_r", "").strip() or "Eye.Control.R"
            actual_pupil_ctrl = getattr(prefs, "bone_name_ctrl_pupil", "").strip() or "Eye.Control.Pupil"
            
            ctrl_dist = getattr(prefs, "ctrl_offset_dist", 0.05) if prefs else 0.05
            ctrl_len = getattr(prefs, "ctrl_length", 0.01) if prefs else 0.01

            # Calculate Directions
            symmetry_axis = getattr(context.scene, "quick_eye_symmetry_axis", 'X')
            
            if symmetry_axis == 'X':
                left_dir = Vector((0, -1, 0)) if left_pos.y < 0 else Vector((0, 1, 0))
                right_dir = Vector((0, -1, 0)) if right_pos.y < 0 else Vector((0, 1, 0))
                center_dir = left_dir
            elif symmetry_axis == 'Y':
                left_dir = Vector((1, 0, 0)) if left_pos.x >= 0 else Vector((-1, 0, 0))
                right_dir = Vector((1, 0, 0)) if right_pos.x >= 0 else Vector((-1, 0, 0))
                center_dir = left_dir
            else:
                left_dir = Vector((0, -1, 0))
                right_dir = Vector((0, -1, 0))
                center_dir = left_dir

            # Deform Bone internal offset (always inwards)
            offset = -center_dir * 0.05

            # 1. Deform Bones
            if gen_deform:
                bone_left = ebones.new(actual_bone_l)
                bone_left.head = left_pos + offset
                bone_left.tail = left_pos
                align_bone_z_axis(bone_left, Vector((0, 0, 1)))
                bone_left.parent = None

                bone_right = ebones.new(actual_bone_r)
                bone_right.head = right_pos + offset
                bone_right.tail = right_pos
                align_bone_z_axis(bone_right, Vector((0, 0, 1)))
                bone_right.parent = None

            # 2. Master Control Bone
            master_ctrl = ebones.new(actual_master_ctrl)
            center_pos = (left_pos + right_pos) / 2.0
            master_head = center_pos + center_dir * ctrl_dist
            master_ctrl.head = master_head
            master_ctrl.tail = master_head + center_dir * 0.02
            align_bone_z_axis(master_ctrl, Vector((0, 0, 1)))
            master_ctrl.parent = None

            # 3. Pupil Control Bone
            if gen_ctrl_pupil:
                pupil_ctrl = ebones.new(actual_pupil_ctrl)
                pupil_head = master_head + Vector((0, 0, 0.01))
                pupil_ctrl.head = pupil_head
                pupil_ctrl.tail = pupil_head + center_dir * 0.01
                align_bone_z_axis(pupil_ctrl, Vector((0, 0, 1)))
                pupil_ctrl.parent = master_ctrl
                pupil_ctrl.use_connect = False

            # 4. Left & Right Control Bones
            ctrl_left = ebones.new(actual_ctrl_l)
            ctrl_left.head = left_pos + left_dir * ctrl_dist
            ctrl_left.tail = ctrl_left.head + left_dir * ctrl_len
            align_bone_z_axis(ctrl_left, Vector((0, 0, 1)))
            ctrl_left.parent = master_ctrl
            ctrl_left.use_connect = False
            
            ctrl_right = ebones.new(actual_ctrl_r)
            ctrl_right.head = right_pos + right_dir * ctrl_dist
            ctrl_right.tail = ctrl_right.head + right_dir * ctrl_len
            align_bone_z_axis(ctrl_right, Vector((0, 0, 1)))
            ctrl_right.parent = master_ctrl
            ctrl_right.use_connect = False
            
        finally:
            # Always ensure we return to object mode even if something above fails
            bpy.ops.object.mode_set(mode='OBJECT')

        # 5. Add Constraints
        if gen_deform:
            enable_constraint = getattr(context.scene, "quick_eye_deform_constraint", False)
            
            for bname, cname in [(actual_bone_l, actual_ctrl_l), (actual_bone_r, actual_ctrl_r)]:
                pbone = arm_obj.pose.bones.get(bname)
                if pbone:
                    con = pbone.constraints.new('DAMPED_TRACK')
                    con.target = arm_obj
                    con.subtarget = cname
                    con.track_axis = 'TRACK_Y'
                    con.mute = not enable_constraint

        # 6. Organize Bone Collections
        if hasattr(arm_obj.data, "collections"):
            default_coll = arm_obj.data.collections.get("Collection")
            
            master_coll = arm_obj.data.collections.new("Quick Eye Rig")
            
            eye_coll = arm_obj.data.collections.new("Eye")
            eye_coll.parent = master_coll
            
            ctrl_coll = arm_obj.data.collections.new("Eye Control")
            ctrl_coll.parent = master_coll
            
            for b_name in [actual_bone_l, actual_bone_r]:
                bone = arm_obj.data.bones.get(b_name)
                if bone:
                    eye_coll.assign(bone)
                    if default_coll:
                        default_coll.unassign(bone)
                        
            for b_name in [actual_ctrl_l, actual_ctrl_r, actual_master_ctrl, actual_pupil_ctrl]:
                bone = arm_obj.data.bones.get(b_name)
                if bone:
                    ctrl_coll.assign(bone)
                    if default_coll:
                        default_coll.unassign(bone)

        self.report({'INFO'}, f"Generated new armature: {arm_obj.name}")

    def cleanup(self, context):
        context.window.cursor_modal_restore()
        if context.area:
            context.area.header_text_set(None)
        
        self.preview_left_loc = None
        self.preview_right_loc = None

        if hasattr(self, 'draw_handle') and self.draw_handle:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, 'WINDOW')
            except Exception:
                pass
            self.draw_handle = None
            
        # Safely restore active object
        if getattr(self, 'obj', None) and self.obj.name in bpy.data.objects: 
            context.view_layer.objects.active = self.obj


# ==========================================
# UI Panel
# ==========================================
class XNEKO_PT_eye_rig_panel(bpy.types.Panel):
    bl_label = "Quick Eye Bone"
    bl_idname = "XNEKO_PT_eye_rig_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XNeko Tools"
    
    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        obj = context.active_object
        is_valid = (obj and obj.type == 'MESH' 
                    and obj.select_get() 
                    and obj.visible_get() 
                    and context.mode == 'OBJECT')

        if is_valid:
            # Symmetry Axis
            row = layout.row(align=True)
            row.label(text="", icon='MOD_MIRROR')
            if hasattr(scene, "quick_eye_symmetry_axis"):
                row.prop(scene, "quick_eye_symmetry_axis", expand=True)
            
            layout.separator()

            # Generation Options Box
            box = layout.box()
            row = box.row()
            row.prop(scene, "quick_eye_ui_show_options", 
                     icon="TRIA_DOWN" if scene.quick_eye_ui_show_options else "TRIA_RIGHT", 
                     icon_only=True, emboss=False)
            row.label(text="Generation & Display Options")
            
            if scene.quick_eye_ui_show_options:
                col = box.column(align=True)
                col.prop(scene, "quick_eye_gen_deform", text="Generate Eye Deform Bones")
                col.prop(scene, "quick_eye_gen_pupil", text="Generate Pupil Control Bone")
                
                sub = col.column(align=True)
                sub.active = scene.quick_eye_gen_deform
                sub.prop(scene, "quick_eye_deform_constraint", text="Deform Bone Constraint")
                
                col.separator()
                col.prop(scene, "quick_eye_show_in_front", text="Show In Front")
            
            layout.separator()
            
            # Generate Button
            col = layout.column()
            col.scale_y = 1.5
            col.operator("xneko.eye_rig_modal", text="Quick Locate & Generate", icon='TRACKER')
            
        else:
            col = layout.column(align=True)
            col.scale_y = 0.9
            row = col.row()
            row.alignment = 'CENTER'
            row.label(text="Please select a mesh model", icon='INFO')
            row = col.row()
            row.alignment = 'CENTER'
            row.label(text="(Object Mode required)")

# ==========================================
# Registration
# ==========================================
classes = (
    XNEKO_OT_eye_rig_modal,
    XNEKO_PT_eye_rig_panel,
)

if not hasattr(bpy.types.Scene, "quick_eye_symmetry_axis"):
    bpy.types.Scene.quick_eye_symmetry_axis = EnumProperty(
        name="Symmetry Axis",
        items=(
            ('X', "X", "Mirror along X axis"),
            ('Y', "Y", "Mirror along Y axis"),
        ),
        default='X'
    )

if not hasattr(bpy.types.Scene, "quick_eye_ui_show_options"):
    bpy.types.Scene.quick_eye_ui_show_options = BoolProperty(
        name="Show Options",
        default=True,
        description="Show or hide the generation options panel"
    )

if not hasattr(bpy.types.Scene, "quick_eye_show_in_front"):
    bpy.types.Scene.quick_eye_show_in_front = BoolProperty(
        name="Show In Front",
        default=True,
        description="Make the generated armature draw in front of the mesh"
    )

if not hasattr(bpy.types.Scene, "quick_eye_gen_deform"):
    bpy.types.Scene.quick_eye_gen_deform = BoolProperty(
        name="Generate Deform Bones",
        default=True,
        description="Generate deform bones for skinning"
    )

if not hasattr(bpy.types.Scene, "quick_eye_gen_pupil"):
    bpy.types.Scene.quick_eye_gen_pupil = BoolProperty(
        name="Generate Pupil Bone",
        default=True,
        description="Generate the pupil control bone above the master bone"
    )

if not hasattr(bpy.types.Scene, "quick_eye_deform_constraint"):
    bpy.types.Scene.quick_eye_deform_constraint = BoolProperty(
        name="Deform Bone Constraint",
        default=False,
        description="Automatically make deform bones track the control bones"
    )