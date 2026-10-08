"""Optional zstandard dependency wrapper.

The UEFormat format supports ZSTD-compressed payloads. If the
'zstandard' package is not installed, we simply cannot decompress
those files - but the rest of the importer keeps working for
uncompressed and GZIP-compressed files.

get_zstd_decompressor() returns None when zstandard is unavailable.

reset_cache() clears the cached check result. Called on tool load
and unload so that installing or removing the zstandard package
while Blender is running is picked up on the next tool reload.
"""

_zstd_decompressor = None
_zstd_checked = False


def get_zstd_decompressor():
    """Return a configured ZstdDecompressor, or None if unavailable."""
    global _zstd_decompressor, _zstd_checked
    if not _zstd_checked:
        _zstd_checked = True
        try:
            import zstandard as zstd
            _zstd_decompressor = zstd.ZstdDecompressor()
        except ImportError:
            _zstd_decompressor = None
    return _zstd_decompressor


def has_zstd() -> bool:
    return get_zstd_decompressor() is not None


def reset_cache() -> None:
    """Forget the cached zstandard availability check."""
    global _zstd_decompressor, _zstd_checked
    _zstd_decompressor = None
    _zstd_checked = False