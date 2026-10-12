"""Optional zstandard dependency wrapper.

If 'zstandard' is not installed, ZSTD-compressed files cannot be
imported; GZIP and uncompressed files still work.

reset_cache() forgets the cached check. Called on plugin load/unload
so that installing or removing zstandard while Blender is running is
picked up on the next reload.
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
    global _zstd_decompressor, _zstd_checked
    _zstd_decompressor = None
    _zstd_checked = False