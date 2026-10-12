"""N panel for the UE Format toolbox module.

The framework attaches this panel under the object_tools group panel
(or whatever group the module is placed in) and applies the configured
N panel category through refresh_panel_category(). The bl_category
here is only a fallback.
"""

import bpy

from ._importer.options import UFSettings


class UEFORMAT_PT_Panel(bpy.types.Panel):
    bl_label = "UE Format"
    bl_idname = "UEFORMAT_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "XNeko Tools"

    @classmethod
    def poll(cls, context):
        if context.area is None or context.area.type != "VIEW_3D":
            return False
        scene = context.scene
        if scene is None:
            return False
        return hasattr(scene, "ueformat_settings")

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        settings = getattr(scene, "ueformat_settings", None)
        if settings is None:
            layout.label(text="UE Format not initialized", icon='ERROR')
            return

        self.draw_general_options(self, settings)
        self.draw_model_options(self, settings)
        self.draw_anim_options(self, settings, scene=scene)
        self.draw_pose_options(self, settings, scene=scene)

    @staticmethod
    def draw_general_options(obj, settings: UFSettings) -> None:
        box = obj.layout.box()
        box.label(text="General", icon="SETTINGS")
        box.row().prop(settings, "scale_factor")

    @staticmethod
    def draw_model_options(
        obj, settings: UFSettings, *, import_menu: bool = False,
    ) -> None:
        box = obj.layout.box()
        box.label(text="Model", icon="OUTLINER_OB_MESH")
        box.row().prop(settings, "target_lod")
        box.row().prop(settings, "import_collision")
        box.row().prop(settings, "import_morph_targets")
        box.row().prop(settings, "import_sockets")
        box.row().prop(settings, "import_virtual_bones")
        box.row().prop(settings, "reorient_bones")
        box.row().prop(settings, "bone_length")

        if not import_menu:
            box.row().operator(
                "xneko.ueformat_import_uemodel", icon="MESH_DATA",
            )

    @staticmethod
    def draw_anim_options(
        obj, settings: UFSettings, *, import_menu: bool = False, scene=None,
    ) -> None:
        box = obj.layout.box()
        box.label(text="Animation", icon="ACTION")
        box.row().prop(settings, "rotation_only")
        box.row().prop(settings, "import_curves")
        if scene is not None and hasattr(scene, "ueformat_anim_skeleton"):
            box.row().prop(scene, "ueformat_anim_skeleton")

        if not import_menu:
            box.row().operator(
                "xneko.ueformat_import_ueanim", icon="ANIM",
            )

    @staticmethod
    def draw_pose_options(
        obj, settings: UFSettings, *, import_menu: bool = False, scene=None,
    ) -> None:
        box = obj.layout.box()
        box.label(text="Pose", icon="OUTLINER_OB_ARMATURE")
        if scene is not None:
            if hasattr(scene, "ueformat_pose_skeleton"):
                box.row().prop(scene, "ueformat_pose_skeleton")
            if hasattr(scene, "ueformat_pose_root_bone"):
                armature = getattr(scene, "ueformat_pose_skeleton", None)
                if armature is not None and armature.type == "ARMATURE":
                    box.row().prop_search(
                        scene, "ueformat_pose_root_bone",
                        armature.data, "bones",
                        text="Root Bone",
                    )
                else:
                    row = box.row()
                    row.enabled = False
                    row.prop(scene, "ueformat_pose_root_bone", text="Root Bone")

        if not import_menu:
            box.row().operator(
                "xneko.ueformat_import_uepose", icon="ARMATURE_DATA",
            )