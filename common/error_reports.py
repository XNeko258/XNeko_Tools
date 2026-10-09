"""Error reporting for XNeko Tools.

Two separate channels:

  * Tool-module errors -- user-controllable. Written to
    logs/reports/ only when 'Enable Error Reporting' is on in the
    addon preferences. Default: silent.

  * Addon critical errors -- always-on. Written to logs/critical/
    regardless of the user preference. Reserved for failures in
    the addon's own infrastructure (top-level register/unregister,
    dynamic preference class build, discovery pipeline itself) as
    opposed to failures inside a single tool module.

Both directories retain only the newest MAX_FILES entries, so the
log area cannot grow without bound.

This module is deliberately lightweight: no event streams, no
session files, no per-run overhead. It only runs when an error
actually occurs.
"""

import os
import sys
import datetime

import bpy


# ------------------------------------------------------------
# Layout
# ------------------------------------------------------------
REPORTS_SUBDIR = "reports"
CRITICAL_SUBDIR = "critical"
MAX_FILES = 10

REPORT_PREFIX = "report_"
CRITICAL_PREFIX = "critical_"
FILE_SUFFIX = ".log"


# Deduplicates critical reports within a Blender session. Cleared
# by reset_dedup() (called from core.rescan_tools) so that the
# next discovery pass can log again if the same failure recurs.
_critical_dedup = set()


# Tool reports raised during addon registration cannot be written
# immediately: the XNekoPreferences class is not registered yet, so
# addon.preferences is unavailable and the user toggle cannot be
# read. Those reports are queued here and flushed by flush_pending()
# once preferences become available.
_pending_reports = []


# ------------------------------------------------------------
# Directory helpers
# ------------------------------------------------------------
def _log_root():
    """Shared log root, defined in core.get_log_dir()."""
    from .. import core
    return core.get_log_dir()


def _ensure_dir(subdir):
    path = os.path.join(_log_root(), subdir)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def user_reports_dir():
    return _ensure_dir(REPORTS_SUBDIR)


def critical_reports_dir():
    return _ensure_dir(CRITICAL_SUBDIR)


# ------------------------------------------------------------
# File listing / pruning
# ------------------------------------------------------------
def _list_files(folder, prefix):
    try:
        names = [
            n for n in os.listdir(folder)
            if n.startswith(prefix) and n.endswith(FILE_SUFFIX)
        ]
    except OSError:
        return []
    paths = [os.path.join(folder, n) for n in names]
    try:
        paths.sort(key=os.path.getmtime, reverse=True)
    except OSError:
        return paths
    return paths


def _prune(folder, prefix):
    paths = _list_files(folder, prefix)
    if len(paths) <= MAX_FILES:
        return
    for old in paths[MAX_FILES:]:
        try:
            os.remove(old)
        except OSError:
            pass


def list_user_reports():
    return _list_files(user_reports_dir(), REPORT_PREFIX)


def list_critical_reports():
    return _list_files(critical_reports_dir(), CRITICAL_PREFIX)


def clear_user_reports():
    removed = 0
    for path in list_user_reports():
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def clear_critical_reports():
    removed = 0
    for path in list_critical_reports():
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


# ------------------------------------------------------------
# User preference
# ------------------------------------------------------------
# bpy.context.preferences.addons is keyed on the addon's top-level
# package name ("XNeko_Tools"). __package__ inside this submodule is
# "XNeko_Tools.common", which would fail the lookup. Strip the
# subpackage suffix once at import time.
_ADDON_PACKAGE = __package__.rsplit(".", 1)[0]


def is_user_reporting_enabled():
    """Return the user's reporting preference.

    True  -- opt-in is on
    False -- opt-in is off
    None  -- preferences are not available yet (we are inside
             addon registration, before XNekoPreferences has been
             registered). Callers must queue rather than decide.
    """
    try:
        addon = bpy.context.preferences.addons.get(_ADDON_PACKAGE)
        if addon is None:
            return None
        prefs = addon.preferences
        if prefs is None:
            return None
        return bool(getattr(prefs, "enable_error_report", False))
    except Exception:
        return None


# ------------------------------------------------------------
# Report writing
# ------------------------------------------------------------
def _plugin_version():
    try:
        from .. import bl_info
        return ".".join(str(v) for v in bl_info.get("version", (0, 0, 0)))
    except Exception:
        return "unknown"


def _write_report(folder, prefix, label, exc, extra, forced):
    """Write one report file. Returns the path, or None on failure."""
    import traceback

    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}{stamp}{FILE_SUFFIX}"
    path = os.path.join(folder, filename)

    tag = "CRITICAL" if forced else "TOOL"
    sep = "=" * 72
    sub = "-" * 9

    lines = []
    lines.append(sep)
    lines.append(f"[{tag}] {label}")
    lines.append(sep)
    lines.append("")

    src = extra or {}
    where = src.get("module") or src.get("file") or "-"

    lines.append(f"Where   : {where}")
    lines.append(f"When    : {now.isoformat(timespec='seconds')}")
    lines.append("")

    src_file = src.get("file")
    if src_file:
        lines.append("Source")
        lines.append(sub)
        lines.append(f"File   : {src_file}")
        src_line = src.get("line")
        if src_line:
            lines.append(f"Line   : {src_line}")
        src_field = src.get("field")
        if src_field:
            lines.append(f"Field  : {src_field}")
        lines.append("")

    if exc is not None:
        lines.append("Exception")
        lines.append(sub)
        lines.append(f"Type    : {type(exc).__name__}")
        lines.append(f"Message : {exc}")
        lines.append("")

        lines.append("Traceback")
        lines.append(sub)
        try:
            tb = "".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__
            ))
            lines.append(tb.rstrip())
        except Exception:
            lines.append("(traceback unavailable)")
        lines.append("")

    elif extra:
        lines.append("Detail")
        lines.append(sub)
        for k in sorted(extra.keys()):
            if k in ("file", "module", "line", "field"):
                continue
            lines.append(f"{k:<8}: {extra[k]}")
        lines.append("")

    lines.append("Environment")
    lines.append(sub)
    lines.append(f"Plugin   : {_plugin_version()}")
    lines.append(
        f"Blender  : {'.'.join(str(v) for v in bpy.app.version)}"
    )
    lines.append(f"Python   : {sys.version.split()[0]}")
    lines.append(f"Platform : {sys.platform}")
    lines.append("")

    lines.append(f"Report   : {os.path.basename(path)}")
    lines.append(sep)

    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    except Exception as write_err:
        print(f"[XNeko] failed to write report: {write_err}")
        return None

    _prune(folder, prefix)
    return path


def report_tool_error(label, exc=None, extra=None):
    """Report an error originating inside a single tool module.

    Behavior depends on when the call happens:

      * Before preferences are registered (during addon discovery):
        the report is queued. flush_pending() writes it later.
      * After preferences exist and the toggle is on: written now.
      * After preferences exist and the toggle is off: discarded.
    """
    state = is_user_reporting_enabled()
    if state is None:
        # Preferences not ready. Queue and let register() flush.
        _pending_reports.append((label, exc, extra))
        return None
    if not state:
        return None
    return _write_report(
        user_reports_dir(), REPORT_PREFIX, label, exc, extra,
        forced=False,
    )


def flush_pending():
    """Write any tool reports queued during addon registration.

    Called from the addon's register() after XNekoPreferences has
    been registered, so the user toggle is finally readable. If the
    toggle is off, the queue is simply dropped.
    """
    if not _pending_reports:
        return
    state = is_user_reporting_enabled()
    if not state:
        _pending_reports.clear()
        return
    for label, exc, extra in _pending_reports:
        try:
            _write_report(
                user_reports_dir(), REPORT_PREFIX,
                label, exc, extra, forced=False,
            )
        except Exception:
            pass
    _pending_reports.clear()


def report_critical_error(label, exc=None, extra=None):
    """Report an error inside the addon's own infrastructure.

    Always writes a report, regardless of user preference. Deduped
    per session on (label, exception_type).
    """
    key = (label, type(exc).__name__ if exc is not None else None)
    if key in _critical_dedup:
        return None
    _critical_dedup.add(key)

    path = _write_report(
        critical_reports_dir(), CRITICAL_PREFIX, label, exc, extra,
        forced=True,
    )
    if path:
        print(f"[XNeko] critical error report: {path}")
    return path


def reset_dedup():
    """Allow the next discovery pass to re-log critical errors."""
    _critical_dedup.clear()