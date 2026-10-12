"""UE Format importer for XNeko Tools.

Fork of https://github.com/h4lfheart/UEFormat, adapted to the
XNeko Tools lifecycle. The importer package (_importer/) is
byte-identical with the standalone plugin's importer/ package.
"""

tool_id = "ueformat"
tool_name = "UE Format"
tool_default_enabled = False

from . import _operators
from . import _panel
from . import _settings
from ._importer import _zstd

# UFSettings (defined in _importer/options.py) must be registered
# before install_scene_props() creates the Scene.ueformat_settings
# pointer.
preference_classes = (_settings.UFSettings,)

preference_props = _settings.preference_props
draw_preferences = _settings.draw_preferences

# Scene properties are managed by install_scene_props() /
# uninstall_scene_props() in _settings, called from on_load /
# on_unload below.
scene_props = {}

classes = (
    _panel.UEFORMAT_PT_Panel,
    _operators.UFImportUEModel,
    _operators.UFImportUEAnim,
    _operators.UFImportUEPose,
    _operators.UFShowImportTime,
    _operators.IO_FH_uemodel,
    _operators.IO_FH_ueanim,
    _operators.IO_FH_uepose,
)


def on_load():
    _zstd.reset_cache()
    _settings.install_scene_props()
    _operators.register_import_menu()


def on_unload():
    _operators.unregister_import_menu()
    _settings.uninstall_scene_props()
    _zstd.reset_cache()