from __future__ import annotations

import gzip
from pathlib import Path
from typing import cast

import bpy
from bpy.types import (
    Action,
    ArmatureModifier,
    ByteColorAttribute,
    EditBone,
    Object,
    PoseBone,
)
from bpy_extras import anim_utils
from mathutils import Matrix, Quaternion, Vector

from .._context import ops_safe
from .._logging import Log
from .._settings import (
    UEAnimOptions,
    UEFormatOptions,
    UEModelOptions,
    UEPoseOptions,
)
from .._zstd import get_zstd_decompressor
from .classes import (
    ANIM_IDENTIFIER,
    MAGIC,
    MODEL_IDENTIFIER,
    POSE_IDENTIFIER,
    EUEFormatVersion,
    UEAnim,
    UEModel,
    UEModelLOD,
    UEModelSkeleton,
    UEPose,
)
from .reader import FArchiveReader
from .utils import (
    best,
    bone_has_parent,
    bone_hierarchy_has_vertex_groups,
    bone_swap_orig_parents,
    disable_constraints,
    first,
    get_active_armature,
    get_armature_mesh,
    get_case_insensitive,
    has_vertex_weights,
    make_axis_vector,
    make_quat,
    make_vector,
)


class UEFormatImport:
    def __init__(self, options: UEFormatOptions) -> None:
        self.options = options

    def import_file(self, path: str | Path) -> Object | Action | None:
        path = path if isinstance(path, Path) else Path(path)
        Log.time_start(f"Import {path}")
        try:
            with path.open("rb") as file:
                return self.import_data(file.read())
        finally:
            Log.time_end(f"Import {path}")

    def import_data(self, data: bytes) -> Object | Action | None:
        with FArchiveReader(data) as ar:
            return self.import_data_by_reader(ar)

    def import_data_by_reader(
        self, ar: FArchiveReader,
    ) -> Object | Action | None:
        magic = ar.read_string(len(MAGIC))
        if magic != MAGIC:
            raise ValueError(
                f"Invalid file magic: expected {MAGIC!r}, got {magic!r}"
            )

        identifier = ar.read_fstring()
        file_version = EUEFormatVersion(
            int.from_bytes(ar.read_byte(), byteorder="big")
        )
        if file_version > EUEFormatVersion.LatestVersion:
            raise ValueError(
                f"File version {file_version} is not supported "
                f"by this importer (latest: {EUEFormatVersion.LatestVersion})"
            )

        object_name = ar.read_fstring()
        Log.info(f"Importing {object_name}")

        read_archive = ar
        is_compressed = ar.read_bool()
        if is_compressed:
            compression_type = ar.read_fstring()
            uncompressed_size = ar.read_int()
            _compressed_size = ar.read_int()

            if compression_type == "GZIP":
                read_archive = FArchiveReader(gzip.decompress(ar.read_to_end()))
            elif compression_type == "ZSTD":
                decompressor = get_zstd_decompressor()
                if decompressor is None:
                    raise RuntimeError(
                        "This file uses ZSTD compression. "
                        "Install the 'zstandard' package to import it."
                    )
                read_archive = FArchiveReader(
                    decompressor.decompress(
                        ar.read_to_end(), uncompressed_size,
                    ),
                )
            else:
                raise ValueError(
                    f"Unknown compression type: {compression_type}"
                )

        read_archive.file_version = file_version
        read_archive.metadata["scale"] = self.options.scale_factor

        if identifier == MODEL_IDENTIFIER:
            result = self.import_uemodel_data(read_archive, object_name)
            return result[0] if result else None
        if identifier == ANIM_IDENTIFIER:
            result = self.import_ueanim_data(read_archive, object_name)
            return result[0] if result else None
        if identifier == POSE_IDENTIFIER:
            self.import_uepose_data(read_archive, object_name)
            return None

        raise ValueError(f"Unknown identifier: {identifier}")

    # =========================================================
    # UEMODEL
    # =========================================================
    def import_uemodel_data(
        self, ar: FArchiveReader, name: str,
    ) -> tuple[Object | None, UEModel]:
        if not isinstance(self.options, UEModelOptions):
            raise TypeError("options must be UEModelOptions for model import")

        if ar.file_version >= EUEFormatVersion.LevelOfDetailFormatRestructure:
            data = UEModel.from_archive(ar)
        else:
            data = UEModel.from_archive_legacy(ar)

        return_object = None
        target_lod = min(self.options.target_lod, len(data.lods) - 1)
        created_lods: list[Object] = []

        for index, lod in enumerate(data.lods):
            if index != target_lod:
                continue

            lod_name = f"{name}_{lod.name}"
            mesh_data = bpy.data.meshes.new(lod_name)
            mesh_data.from_pydata(lod.vertices, [], lod.indices)

            mesh_object = bpy.data.objects.new(lod_name, mesh_data)
            return_object = mesh_object
            if self.options.link:
                bpy.context.collection.objects.link(mesh_object)

            self._apply_normals(mesh_data, lod)
            self._apply_weights(mesh_object, lod, data.skeleton)
            self._apply_morphs(mesh_object, lod)
            self._apply_colors(mesh_data, lod)
            self._apply_uvs(mesh_data, lod)
            self._apply_materials(mesh_data, lod)

            created_lods.append(mesh_object)

        skeleton_armature = self._build_skeleton(name, data, created_lods)
        if created_lods and skeleton_armature is not None:
            return_object = skeleton_armature

        self._build_collisions(name, data)

        return return_object, data

    def _apply_normals(self, mesh_data: bpy.types.Mesh, lod: UEModelLOD) -> None:
        if len(lod.normals) == 0:
            return
        mesh_data.polygons.foreach_set(
            "use_smooth", [True] * len(mesh_data.polygons),
        )
        mesh_data.normals_split_custom_set_from_vertices(lod.normals)
        if bpy.app.version < (4, 1, 0):
            mesh_data.use_auto_smooth = True

    def _apply_weights(
        self, mesh_object: Object, lod: UEModelLOD,
        skeleton: UEModelSkeleton | None,
    ) -> None:
        if not lod.weights or not skeleton or not skeleton.bones:
            return
        for weight in lod.weights:
            bone_name = skeleton.bones[weight.bone_index].name
            vg = mesh_object.vertex_groups.get(bone_name)
            if not vg:
                vg = mesh_object.vertex_groups.new(name=bone_name)
            vg.add([weight.vertex_index], weight.weight, "ADD")

    def _apply_morphs(self, mesh_object: Object, lod: UEModelLOD) -> None:
        if not self.options.import_morph_targets or not lod.morphs:
            return
        if not mesh_object.data.shape_keys:
            mesh_object.shape_key_add(name="Basis", from_mix=False)
        for morph in lod.morphs:
            key = mesh_object.shape_key_add(from_mix=False)
            key.name = morph.name
            key.interpolation = "KEY_LINEAR"
            for delta in morph.deltas:
                key.data[delta.vertex_index].co += Vector(delta.position)
            key.value = 0

    def _apply_colors(self, mesh_data: bpy.types.Mesh, lod: UEModelLOD) -> None:
        if not lod.colors:
            return
        vertices = [v for poly in mesh_data.polygons for v in poly.vertices]
        for color_info in lod.colors:
            remapped = color_info.data[vertices]
            vc = cast(
                ByteColorAttribute,
                mesh_data.color_attributes.new(
                    domain="CORNER", type="BYTE_COLOR", name=color_info.name,
                ),
            )
            vc.data.foreach_set("color", remapped.reshape(remapped.size))

    def _apply_uvs(self, mesh_data: bpy.types.Mesh, lod: UEModelLOD) -> None:
        if not lod.uvs:
            return
        vertices = [v for poly in mesh_data.polygons for v in poly.vertices]
        for i, uvs in enumerate(lod.uvs):
            remapped = uvs[vertices]
            uv_layer = mesh_data.uv_layers.new(name=f"UV{i}")
            uv_layer.data.foreach_set("uv", remapped.reshape(remapped.size))

    def _apply_materials(
        self, mesh_data: bpy.types.Mesh, lod: UEModelLOD,
    ) -> None:
        if not lod.materials:
            return
        for i, material in enumerate(lod.materials):
            mat = bpy.data.materials.get(material.material_name)
            if mat is None:
                mat = bpy.data.materials.new(name=material.material_name)
            mesh_data.materials.append(mat)
            start = material.first_index // 3
            end = start + material.num_faces
            for face_index in range(start, end):
                mesh_data.polygons[face_index].material_index = i

    def _build_skeleton(
        self,
        name: str,
        data: UEModel,
        created_lods: list[Object],
    ) -> Object | None:
        skeleton = data.skeleton
        if not skeleton:
            return None
        has_bones = bool(skeleton.bones)
        has_sockets = self.options.import_sockets and bool(skeleton.sockets)
        if not (has_bones or has_sockets):
            return None

        armature_data = bpy.data.armatures.new(name=name)
        armature_data.display_type = "STICK"

        template_arm = bpy.data.objects.new(
            f"{name}_Template_Skeleton", armature_data,
        )
        template_arm.show_in_front = True
        bpy.context.collection.objects.link(template_arm)
        bpy.context.view_layer.objects.active = template_arm
        template_arm.select_set(state=True)

        if has_bones:
            self._create_bones(armature_data, skeleton)

        if has_sockets and skeleton.sockets:
            self._create_sockets(armature_data, skeleton)

        if has_bones and self.options.reorient_bones:
            self._reorient_bones(armature_data)

        if created_lods:
            bpy.data.objects.remove(template_arm)
            armature_obj = None
            for lod in created_lods:
                armature_obj = self._attach_skeleton(
                    lod, armature_data, skeleton,
                )
            return armature_obj

        template_arm.name = name
        if self.options.import_virtual_bones and skeleton.virtual_bones:
            self._build_virtual_bones(template_arm, armature_data, skeleton)
        self._apply_default_bone_colors(template_arm, skeleton)
        return template_arm

    def _create_bones(
        self, armature_data: bpy.types.Armature,
        skeleton: UEModelSkeleton,
    ) -> None:
        with ops_safe(mode="EDIT"):
            edit_bones = armature_data.edit_bones
            for bone_ in skeleton.bones:
                bone_pos = Vector(bone_.position)
                bone_rot = Quaternion((
                    bone_.rotation[3], bone_.rotation[0],
                    bone_.rotation[1], bone_.rotation[2],
                ))
                edit_bone = edit_bones.new(bone_.name)
                edit_bone["orig_loc"] = bone_pos
                edit_bone["orig_quat"] = bone_rot.conjugated()
                edit_bone.length = (
                    self.options.bone_length * self.options.scale_factor
                )

                bone_matrix = (
                    Matrix.Translation(bone_pos)
                    @ bone_rot.to_matrix().to_4x4()
                )
                if bone_.parent_index >= 0:
                    parent_bone = cast(
                        EditBone | None,
                        edit_bones.get(
                            skeleton.bones[bone_.parent_index].name,
                        ),
                    )
                    if parent_bone is None:
                        raise RuntimeError(
                            f"Parent bone not found: "
                            f"{skeleton.bones[bone_.parent_index].name}"
                        )
                    edit_bone.parent = parent_bone
                    bone_matrix = (
                        cast(Matrix, parent_bone.matrix) @ bone_matrix
                    )
                edit_bone.matrix = bone_matrix

                if not self.options.reorient_bones:
                    edit_bone["post_quat"] = bone_rot

    def _create_sockets(
        self, armature_data: bpy.types.Armature,
        skeleton: UEModelSkeleton,
    ) -> None:
        with ops_safe(mode="EDIT"):
            edit_bones = armature_data.edit_bones
            socket_collection = armature_data.collections.new("Sockets")
            for socket in skeleton.sockets:
                socket_bone = edit_bones.new(socket.name)
                socket_collection.assign(socket_bone)
                socket_bone["is_socket"] = True
                parent_bone = cast(
                    EditBone | None,
                    get_case_insensitive(edit_bones, socket.parent_name),
                )
                if parent_bone is None:
                    continue
                socket_bone.parent = parent_bone
                socket_bone.length = (
                    self.options.bone_length * self.options.scale_factor
                )
                socket_bone.matrix = (
                    cast(Matrix, parent_bone.matrix)
                    @ Matrix.Translation(socket.position)
                    @ Quaternion((
                        socket.rotation[3], socket.rotation[0],
                        socket.rotation[1], socket.rotation[2],
                    )).to_matrix().to_4x4()
                )

    def _reorient_bones(self, armature_data: bpy.types.Armature) -> None:
        with ops_safe(mode="EDIT"):
            for bone in armature_data.edit_bones:
                if bone.get("is_socket"):
                    continue
                children = [
                    c for c in bone.children if not c.get("is_socket")
                ]
                if len(children) == 0 and bone.parent is None:
                    continue
                target_length = bone.length

                if len(children) == 0:
                    new_rot = Vector(bone.parent["reorient_direction"])
                    new_rot.rotate(
                        Quaternion(bone["orig_quat"]).conjugated(),
                    )
                    target_rotation = make_axis_vector(new_rot)
                else:
                    avg_child_pos = Vector()
                    avg_child_length = 0.0
                    allowed_children = None
                    if self.options.allowed_reorient_children is not None:
                        allowed_children = (
                            self.options.allowed_reorient_children.get(
                                bone.name,
                            )
                        )

                    used = 0
                    for child in children:
                        if (
                            allowed_children is not None
                            and child.name not in allowed_children
                        ):
                            continue
                        pos = Vector(child["orig_loc"])
                        avg_child_pos += pos
                        avg_child_length += pos.length
                        used += 1

                    if used == 0:
                        continue
                    avg_child_pos /= used
                    avg_child_length /= used
                    target_rotation = make_axis_vector(avg_child_pos)
                    bone["reorient_direction"] = target_rotation
                    target_length = avg_child_length

                post_quat = Vector((0, 1, 0)).rotation_difference(
                    target_rotation,
                )
                bone.matrix @= post_quat.to_matrix().to_4x4()
                bone.length = max(0.01, target_length)

                post_quat.rotate(Quaternion(bone["orig_quat"]).conjugated())
                bone["post_quat"] = post_quat

    def _build_virtual_bones(
        self, armature_obj: Object, armature_data: bpy.types.Armature,
        skeleton: UEModelSkeleton,
    ) -> None:
        with ops_safe(mode="EDIT"):
            vc = armature_data.collections.new("Virtual Bones")
            edit_bones = armature_data.edit_bones
            for virtual in skeleton.virtual_bones:
                source = edit_bones.get(virtual.source_name)
                if source is None:
                    continue
                vb = edit_bones.new(virtual.virtual_name)
                vc.assign(vb)
                vb.head = source.tail
                vb.tail = source.head

        with ops_safe(mode="POSE"):
            for virtual in skeleton.virtual_bones:
                pose_bone = armature_obj.pose.bones.get(virtual.virtual_name)
                if pose_bone is None:
                    continue
                constraint = pose_bone.constraints.new("IK")
                constraint.target = armature_obj
                constraint.subtarget = virtual.target_name
                constraint.chain_count = 1
                pose_bone.ik_stretch = 1

    def _apply_default_bone_colors(
        self, armature_obj: Object, skeleton: UEModelSkeleton,
    ) -> None:
        for bone in armature_obj.pose.bones:
            if not bone.children:
                bone.color.palette = "THEME03"
        for socket in skeleton.sockets:
            sb = armature_obj.pose.bones.get(socket.name)
            if sb is not None:
                sb.color.palette = "THEME05"
        for virtual in skeleton.virtual_bones:
            vb = armature_obj.pose.bones.get(virtual.virtual_name)
            if vb is not None:
                vb.color.palette = "THEME11"

    def _attach_skeleton(
        self, lod: Object, armature_data: bpy.types.Armature,
        skeleton: UEModelSkeleton,
    ) -> Object:
        armature_obj = bpy.data.objects.new(
            f"{lod.name}_Skeleton", armature_data,
        )
        armature_obj.show_in_front = True
        if self.options.link:
            bpy.context.collection.objects.link(armature_obj)
        bpy.context.view_layer.objects.active = armature_obj
        armature_obj.select_set(state=True)

        lod.parent = armature_obj

        armature_modifier = cast(
            ArmatureModifier,
            lod.modifiers.new(armature_obj.name, type="ARMATURE"),
        )
        armature_modifier.show_expanded = False
        armature_modifier.use_vertex_groups = True
        armature_modifier.object = armature_obj

        with ops_safe(mode="POSE"):
            for bone in armature_obj.pose.bones:
                vg = lod.vertex_groups.get(bone.name)
                if not vg or not has_vertex_weights(lod, vg):
                    bone.color.palette = "THEME14"
                    continue
                if not bone.children:
                    bone.color.palette = "THEME03"
            for socket in skeleton.sockets:
                sb = armature_obj.pose.bones.get(socket.name)
                if sb is not None:
                    sb.color.palette = "THEME05"
            for virtual in skeleton.virtual_bones:
                vb = armature_obj.pose.bones.get(virtual.virtual_name)
                if vb is not None:
                    vb.color.palette = "THEME11"

        return armature_obj

    def _build_collisions(self, name: str, data: UEModel) -> None:
        if not self.options.import_collision or not data.collisions:
            return
        for index, collision in enumerate(data.collisions):
            collision_name = (
                index if collision.name == "None" else collision.name
            )
            obj_name = f"UCX_{name}_{collision_name}"
            mesh_data = bpy.data.meshes.new(obj_name)
            mesh_data.from_pydata(
                collision.vertices, [], collision.indices,
            )
            obj = bpy.data.objects.new(obj_name, mesh_data)
            obj.display_type = "WIRE"
            if self.options.link:
                bpy.context.collection.objects.link(obj)

    # =========================================================
    # UEANIM
    # =========================================================
    def import_ueanim_data(
        self, ar: FArchiveReader, name: str,
    ) -> tuple[Action, UEAnim]:
        if not isinstance(self.options, UEAnimOptions):
            raise TypeError(
                "options must be UEAnimOptions for animation import"
            )

        data = UEAnim.from_archive(ar)
        action = bpy.data.actions.new(name=name)

        armature = self.options.override_skeleton or get_active_armature()
        if not isinstance(armature, bpy.types.Object):
            raise RuntimeError("No active armature for animation import")

        if armature.animation_data:
            armature.animation_data.action = None

        if self.options.link:
            armature.animation_data_create()
            armature.animation_data.action = action

        if self.options.link and bpy.app.version >= (4, 4, 0):
            slot = action.slots.new(
                id_type='OBJECT', name=f"Slot_{armature.name}",
            )
            armature.animation_data.action_slot = slot

        self._apply_bone_animation(action, armature, data)

        if self.options.import_curves:
            self._apply_curve_animation(name, armature, data)

        return action, data

    def _apply_bone_animation(
        self, action: Action, armature: Object, data: UEAnim,
    ) -> None:
        pose_bones = armature.pose.bones
        for track in data.tracks:
            bone = get_case_insensitive(pose_bones, track.name)
            if bone is None:
                continue

            def create_fcurves(path_name, count, key_count, bone):
                path = bone.path_from_id(path_name)
                curves = []
                for i in range(count):
                    if bpy.app.version < (5, 0, 0):
                        curve = action.fcurves.new(path, index=i)
                    else:
                        slot = (
                            action.slots[0]
                            if len(action.slots) > 0
                            else action.slots.new(
                                id_type='OBJECT',
                                name=f"Slot_{armature.name}",
                            )
                        )
                        channelbag = (
                            anim_utils.action_ensure_channelbag_for_slot(
                                action, slot,
                            )
                        )
                        curve = channelbag.fcurves.new(path, index=i)
                    curve.keyframe_points.add(key_count)
                    curves.append(curve)
                return curves

            def add_key(curves, vector, key_index, frame):
                for i in range(len(vector)):
                    kp = curves[i].keyframe_points[key_index]
                    kp.co = frame, vector[i]
                    kp.interpolation = "LINEAR"

            orig_loc = (
                Vector(orig_loc)
                if (orig_loc := bone.bone.get("orig_loc"))
                else Vector()
            )
            orig_quat = (
                Quaternion(orig_quat)
                if (orig_quat := bone.bone.get("orig_quat"))
                else Quaternion()
            )
            post_quat = (
                Quaternion(post_quat)
                if (post_quat := bone.bone.get("post_quat"))
                else Quaternion()
            )

            if not self.options.rotation_only:
                loc_curves = create_fcurves(
                    "location", 3, len(track.position_keys), bone,
                )
                scale_curves = create_fcurves(
                    "scale", 3, len(track.scale_keys), bone,
                )
                for index, key in enumerate(track.position_keys):
                    pos = key.get_vector()
                    pos -= orig_loc
                    pos.rotate(post_quat.conjugated())
                    add_key(loc_curves, pos, index, key.frame)
                for index, key in enumerate(track.scale_keys):
                    add_key(scale_curves, key.value, index, key.frame)

            rot_curves = create_fcurves(
                "rotation_quaternion", 4, len(track.rotation_keys), bone,
            )
            for index, key in enumerate(track.rotation_keys):
                p_quat = key.get_quat().conjugated()

                q = post_quat.copy()
                q.rotate(orig_quat)
                quat = q

                q = post_quat.copy()
                q.rotate(p_quat)
                quat.rotate(q.conjugated())

                add_key(rot_curves, quat, index, key.frame)

            bone.matrix_basis.identity()

    def _apply_curve_animation(
        self, name: str, armature: Object, data: UEAnim,
    ) -> None:
        mesh = get_armature_mesh(armature)
        if not mesh or not mesh.data.shape_keys:
            return
        shape_keys = mesh.data.shape_keys
        shape_keys.name = "Pose Asset"
        if shape_keys.animation_data:
            shape_keys.animation_data.action = None

        shape_keys_action = bpy.data.actions.new(name=f"{name}_Curves")
        if self.options.link:
            shape_keys.animation_data_create()
            shape_keys.animation_data.action = shape_keys_action

        key_blocks = shape_keys.key_blocks
        for key_block in key_blocks:
            key_block.value = 0
        for curve in data.curves:
            shape_key = best(
                key_blocks,
                lambda b: b.name.lower(),
                curve.name.lower(),
            )
            if not shape_key:
                continue
            for key in curve.keys:
                shape_key.value = key.value
                shape_key.keyframe_insert(
                    data_path="value", frame=key.frame,
                )

    # =========================================================
    # UEPOSE
    # =========================================================
    def import_uepose_data(self, ar: FArchiveReader, name: str) -> None:
        if not isinstance(self.options, UEPoseOptions):
            raise TypeError("options must be UEPoseOptions for pose import")

        data = UEPose.from_archive(ar)
        selected_armature = (
            self.options.override_skeleton or get_active_armature()
        )
        if not isinstance(selected_armature, bpy.types.Object):
            raise RuntimeError("No active armature for pose import")

        selected_mesh = get_armature_mesh(selected_armature)
        if selected_mesh is None:
            raise RuntimeError("No mesh attached to the armature")

        original_shape_key_lock = selected_mesh.show_only_shape_key
        original_mode = (
            bpy.context.active_object.mode
            if bpy.context.active_object
            else 'OBJECT'
        )

        armature_modifier = first(
            selected_mesh.modifiers, lambda m: m.type == "ARMATURE",
        )
        if armature_modifier is None:
            raise RuntimeError("Mesh has no armature modifier")

        selected_mesh.show_only_shape_key = False
        bone_swap_orig_parents(selected_armature)
        muted_constraints = disable_constraints(selected_armature)

        if not selected_mesh.data.shape_keys:
            selected_mesh.shape_key_add(name="Basis", from_mix=False)

        original_values = {}
        for sk in selected_mesh.data.shape_keys.key_blocks:
            if sk.value != 0:
                original_values[sk.name] = sk.value
                sk.value = 0

        root_bone = (
            selected_armature.pose.bones.get(self.options.root_bone)
            or selected_armature.pose.bones[0]
        )

        for pose in data.poses:
            self._apply_single_pose(
                selected_armature, selected_mesh, armature_modifier,
                root_bone, pose,
            )

        self._apply_pose_curves(selected_mesh, data, original_values)

        bpy.context.view_layer.objects.active = selected_armature
        with ops_safe(mode="POSE"):
            bpy.ops.pose.select_all(action="SELECT")
            bpy.ops.pose.transforms_clear()
            bpy.ops.pose.select_all(action="DESELECT")

        bone_swap_orig_parents(selected_armature)
        for c in muted_constraints:
            c.mute = False

        selected_mesh.show_only_shape_key = original_shape_key_lock
        bpy.context.view_layer.objects.active = selected_mesh

    def _apply_single_pose(
        self, armature: Object, mesh: Object,
        armature_modifier: bpy.types.Modifier, root_bone: PoseBone, pose,
    ) -> None:
        bpy.context.view_layer.objects.active = armature
        with ops_safe(mode="POSE"):
            bpy.ops.pose.select_all(action="SELECT")
            bpy.ops.pose.transforms_clear()
            bpy.ops.pose.select_all(action="DESELECT")

        contributed = False
        for pose_key in pose.keys:
            pose_bone: PoseBone | None = get_case_insensitive(
                armature.pose.bones, pose_key.bone_name,
            )
            if not pose_bone:
                continue
            if root_bone and not bone_has_parent(pose_bone, root_bone):
                continue
            if not bone_hierarchy_has_vertex_groups(
                pose_bone, mesh.vertex_groups,
            ):
                continue

            pose_bone.matrix_basis.identity()
            edit_bone = pose_bone.bone
            post_quat = (
                Quaternion(post_quat)
                if (post_quat := edit_bone.get("post_quat"))
                else Quaternion()
            )
            q = post_quat.copy()
            q.rotate(make_quat(pose_key.rotation))
            quat = post_quat.copy()
            quat.rotate(q.conjugated())
            pose_bone.rotation_quaternion = (
                quat.conjugated() @ pose_bone.rotation_quaternion
            )
            loc = make_vector(pose_key.position)
            loc.rotate(post_quat.conjugated())
            pose_bone.location = pose_bone.location + loc
            pose_bone.scale = Vector((1, 1, 1)) + make_vector(pose_key.scale)
            pose_bone.rotation_quaternion.normalize()
            contributed = True

        if not contributed:
            return

        with ops_safe(mode="OBJECT"):
            bpy.context.view_layer.objects.active = mesh
            mesh.select_set(True)
            bpy.ops.object.modifier_apply_as_shapekey(
                keep_modifier=True, modifier=armature_modifier.name,
            )
        new_key = mesh.data.shape_keys.key_blocks[-1]
        new_key.name = pose.name
        new_key.value = 0

    def _apply_pose_curves(
        self, mesh: Object, data: UEPose, original_values: dict,
    ) -> None:
        key_blocks = mesh.data.shape_keys.key_blocks
        for pose in data.poses:
            if not pose.curves:
                continue
            pose_name = pose.name
            if pose_name in key_blocks:
                pose_name = f"curve_{pose_name}"
            contributed = False
            for curve in pose.curves:
                target_name = data.curve_names[curve.curve_index]
                sk = key_blocks.get(target_name)
                if not sk:
                    continue
                value = curve.influence
                if value < sk.slider_min:
                    sk.slider_min = value - 1.0
                if value > sk.slider_max:
                    sk.slider_max = value + 1.0
                sk.value = value
                contributed = True
            if contributed:
                mesh.shape_key_add(name=pose_name, from_mix=True)
            for k in key_blocks:
                k.value = 0

        if original_values:
            for k in key_blocks:
                if v := original_values.get(k.name):
                    k.value = v