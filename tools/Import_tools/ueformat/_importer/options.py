"""UFSettings PropertyGroup + option dataclasses.

UFSettings is the per-scene import configuration. The outer layer
(op/settings.py) registers and installs it on bpy.types.Scene.

The dataclasses mirror UFSettings but are plain data holders used by
the importer so it does not have to know about bpy property lookups.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import PropertyGroup


class UFSettings(PropertyGroup):
    scale_factor: FloatProperty(name="Scale", default=0.01, min=0.01)

    bone_length: FloatProperty(name="Bone Length", default=4.0, min=0.1)
    reorient_bones: BoolProperty(name="Reorient Bones", default=False)
    target_lod: IntProperty(name="Level of Detail", default=0, min=0)
    import_collision: BoolProperty(name="Import Collision", default=False)
    import_morph_targets: BoolProperty(name="Import Morph Targets", default=True)
    import_sockets: BoolProperty(name="Import Sockets", default=True)
    import_virtual_bones: BoolProperty(name="Import Virtual Bones", default=False)

    rotation_only: BoolProperty(name="Rotation Only", default=False)
    import_curves: BoolProperty(name="Import Curves", default=True)

    def get_props(self) -> dict:
        return {
            key: getattr(self, key)
            for key in type(self).__annotations__.keys()
        }


@dataclass(slots=True)
class UEFormatOptions:
    link: bool = True
    scale_factor: float = 0.01
    profile_import: bool = False

    @classmethod
    def from_settings(cls, settings: UFSettings):
        return cls(**{
            k: v for k, v in settings.get_props().items()
            if k in inspect.signature(cls).parameters
        })


@dataclass(slots=True)
class UEModelOptions(UEFormatOptions):
    bone_length: float = 4.0
    reorient_bones: bool = False
    import_collision: bool = False
    import_sockets: bool = True
    import_morph_targets: bool = True
    import_virtual_bones: bool = False
    target_lod: int = 0
    allowed_reorient_children: dict | None = None


@dataclass(slots=True)
class UEAnimOptions(UEFormatOptions):
    rotation_only: bool = False
    import_curves: bool = True
    override_skeleton: bpy.types.Object | None = None


@dataclass(slots=True)
class UEPoseOptions(UEFormatOptions):
    root_bone: str = ""
    override_skeleton: bpy.types.Object | None = None