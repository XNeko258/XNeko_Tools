"""Import operators for UE Format.

The bl_idnames are namespaced with xneko.ueformat_* so they do not
collide with the standalone UEFormat addon if both are installed.
"""

from pathlib import Path
from typing import Generic, TypeVar

import bpy
from bpy.props import CollectionProperty, StringProperty
from bpy.types import FileHandler, Operator, OperatorFileListElement
from bpy_extras.io_utils import ImportHelper, poll_file_object_drop

from ._context import ops_safe
from ._importer.logic import UEFormatImport
from ._panel import UEFORMAT_PT_Panel
from ._settings import (
    UEAnimOptions, UEFormatOptions, UEModelOptions, UEPoseOptions,
)

T = TypeVar("T", bound=UEFormatOptions)


def _draw_import_menu(self, context):
    self.layout.operator(
        UFImportUEModel.bl_idname, text="Unreal Model (.uemodel)"
    )
    self.layout.operator(
        UFImportUEAnim.bl_idname, text="Unreal Animation (.ueanim)"
    )
    self.layout.operator(
        UFImportUEPose.bl_idname, text="Unreal Pose Asset (.uepose)"
    )


def register_import_menu() -> None:
    bpy.types.TOPBAR_MT_file_import.append(_draw_import_menu)


def unregister_import_menu() -> None:
    try:
        bpy.types.TOPBAR_MT_file_import.remove(_draw_import_menu)
    except Exception:
        pass


class UFImportBase(Operator, ImportHelper, Generic[T]):
    bl_context = "scene"

    files: CollectionProperty(
        type=OperatorFileListElement,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    directory: StringProperty(subtype="DIR_PATH")

    options_class: type[T]

    def _collect_overrides(self, scene) -> dict:
        """Collect scene-provided overrides for the option dataclass.

        Subclasses declare which scene properties apply to them by
        overriding _override_map(); the base class does not need to
        know about UEAnimOptions / UEPoseOptions by name.
        """
        return {}

    def execute(self, context):
        scene = context.scene
        settings = scene.ueformat_settings

        options = self.options_class.from_settings(settings)
        for key, value in self._collect_overrides(scene).items():
            setattr(options, key, value)

        directory = Path(self.directory)
        for file in self.files:
            file: OperatorFileListElement
            try:
                with ops_safe():
                    UEFormatImport(options).import_file(directory / file.name)
            except Exception as exc:
                self.report({'ERROR'}, f"{file.name}: {exc}")
        return {"FINISHED"}

    def invoke(self, context, event):
        return ImportHelper.invoke_popup(self, context)


class UFImportUEModel(UFImportBase):
    bl_idname = "xneko.ueformat_import_uemodel"
    bl_label = "Import Model"
    bl_description = "Import a .uemodel file"

    filename_ext = ".uemodel"
    filter_glob: StringProperty(
        default="*.uemodel", options={"HIDDEN"}, maxlen=255,
    )

    options_class = UEModelOptions

    def draw(self, context):
        settings = context.scene.ueformat_settings
        UEFORMAT_PT_Panel.draw_general_options(self, settings)
        UEFORMAT_PT_Panel.draw_model_options(
            self, settings, import_menu=True,
        )


class UFImportUEAnim(UFImportBase):
    bl_idname = "xneko.ueformat_import_ueanim"
    bl_label = "Import Animation"
    bl_description = "Import a .ueanim file"

    filename_ext = ".ueanim"
    filter_glob: StringProperty(
        default="*.ueanim", options={"HIDDEN"}, maxlen=255,
    )

    options_class = UEAnimOptions

    def _collect_overrides(self, scene) -> dict:
        return {"override_skeleton": scene.ueformat_anim_skeleton}

    def draw(self, context):
        scene = context.scene
        settings = scene.ueformat_settings
        UEFORMAT_PT_Panel.draw_general_options(self, settings)
        UEFORMAT_PT_Panel.draw_anim_options(
            self, settings, import_menu=True, scene=scene,
        )


class UFImportUEPose(UFImportBase):
    bl_idname = "xneko.ueformat_import_uepose"
    bl_label = "Import Pose"
    bl_description = "Import a .uepose file"

    filename_ext = ".uepose"
    filter_glob: StringProperty(
        default="*.uepose", options={"HIDDEN"}, maxlen=255,
    )

    options_class = UEPoseOptions

    def _collect_overrides(self, scene) -> dict:
        bone = scene.ueformat_pose_root_bone
        return {
            "override_skeleton": scene.ueformat_pose_skeleton,
            "root_bone": bone.name if bone is not None else "",
        }

    def draw(self, context):
        scene = context.scene
        settings = scene.ueformat_settings
        UEFORMAT_PT_Panel.draw_general_options(self, settings)
        UEFORMAT_PT_Panel.draw_pose_options(
            self, settings, import_menu=True, scene=scene,
        )


# ============================================================
# Drag-and-drop handlers
# ============================================================
class IO_FH_ueformatBase(FileHandler):
    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


class IO_FH_uemodel(IO_FH_ueformatBase):
    bl_idname = "XNeko_IO_FH_uemodel"
    bl_label = "UEFormat Model"
    bl_import_operator = UFImportUEModel.bl_idname
    bl_file_extensions = ".uemodel"


class IO_FH_ueanim(IO_FH_ueformatBase):
    bl_idname = "XNeko_IO_FH_ueanim"
    bl_label = "UEFormat Animation"
    bl_import_operator = UFImportUEAnim.bl_idname
    bl_file_extensions = ".ueanim"


class IO_FH_uepose(IO_FH_ueformatBase):
    bl_idname = "XNeko_IO_FH_uepose"
    bl_label = "UEFormat Pose"
    bl_import_operator = UFImportUEPose.bl_idname
    bl_file_extensions = ".uepose"