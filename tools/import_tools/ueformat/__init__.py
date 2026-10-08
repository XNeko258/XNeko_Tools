"""UE Format importer for XNeko Tools.

Extracted from the standalone UEFormat addon by Half
(https://github.com/h4lfheart/UEFormat), trimmed to the essentials
and adapted to the XNeko Tools lifecycle.

What changed vs. the original:
  - Operator bl_idnames use xneko.ueformat_* to avoid collisions.
  - Scene properties are installed explicitly by this tool in
    on_load / on_unload, not via the framework's scene_props
    mechanism. This keeps the tool independent of the framework
    version and avoids silent panel disappearance when the
    framework does not support scene_props injection.
  - bpy.ops calls are wrapped in _context.ops_safe so the importer
    works from both the N panel and the Topbar > File > Import menu.
  - zstandard is optional: files compressed with ZSTD will raise a
    clear RuntimeError if the package is missing, everything else
    keeps working.
  - All asserts replaced with real exceptions so -O mode cannot
    silently skip validation.
"""

tool_id = "ueformat"
tool_name = "UE Format"
tool_default_enabled = False

from . import _operators
from . import _panel
from . import _settings
from . import _zstd

# UFSettings must be registered before install_scene_props() creates
# the Scene.ueformat_settings pointer.
preference_classes = (_settings.UFSettings,)

# Scene properties are managed by install_scene_props() /
# uninstall_scene_props() in _settings, called from on_load /
# on_unload below. The framework's scene_props dict is left empty.
scene_props = {}

classes = (
    _panel.UEFORMAT_PT_Panel,
    _operators.UFImportUEModel,
    _operators.UFImportUEAnim,
    _operators.UFImportUEPose,
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