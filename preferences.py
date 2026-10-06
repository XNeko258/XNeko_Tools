import bpy
from bpy.props import StringProperty, BoolProperty, CollectionProperty, IntProperty

from . import core


# ---------------- Link configuration ----------------
# (label, url, icon, author)
LINKS = (
    ("Patreon", "https://www.patreon.com/c/XNeko_258",              "FUND",         "XNeko"),
    ("X",       "https://x.com/XNeko_258",                          "URL",          "XNeko"),
    ("Bluesky", "https://bsky.app/profile/xneko258.bsky.social",    "URL",          "XNeko"),
    ("Iwara",   "https://www.iwara.tv/profile/shaoqin",             "FILE_MOVIE",   "Shao qin"),
)


# ==================================================
# Layout helpers for dynamic tab pagination
# ==================================================
def _get_ui_scale():
    """Current Blender UI scale (1.0 = default)."""
    try:
        return bpy.context.preferences.system.ui_scale
    except Exception:
        return 1.0


def _get_usable_width(context):
    """Estimate the pixel width available inside the preferences panel."""
    width = None
    try:
        screen = context.screen
        if screen is not None:
            for area in screen.areas:
                if area.type == 'PREFERENCES':
                    width = area.width
                    break
            if width is None and screen.areas:
                width = screen.areas[0].width
    except Exception:
        pass

    if not width:
        try:
            width = context.window.width
        except Exception:
            width = 900

    # Reserve room for the two arrow buttons and padding
    return max(150, width - 130)


def _estimate_tab_px(display_text):
    """Approximate the pixel width of a tab button."""
    scale = _get_ui_scale()
    # ~7 px per character + icon (~22 px) + button padding (~16 px)
    return int((len(display_text) * 7 + 22 + 16) * scale)


# ==================================================
# Category selector operator
# ==================================================
class XNEKO_OT_set_active_category(bpy.types.Operator):
    bl_idname = "xneko.set_active_category"
    bl_label = "Set Active Category"
    bl_options = {'INTERNAL'}

    category: StringProperty()

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if not prefs:
            return {'CANCELLED'}
        prefs.preferences.active_category = self.category
        return {'FINISHED'}


# ==================================================
# Tab page shifter operator
# ==================================================
class XNEKO_OT_shift_tab_page(bpy.types.Operator):
    bl_idname = "xneko.shift_tab_page"
    bl_label = "Shift Tab Page"
    bl_options = {'INTERNAL'}

    delta: IntProperty()

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if not prefs:
            return {'CANCELLED'}
        p = prefs.preferences
        new_page = p.tab_page + self.delta
        if new_page < 0:
            new_page = 0
        p.tab_page = new_page
        return {'FINISHED'}


# ==================================================
# Per-tool toggle
# ==================================================
class XNekoToolToggle(bpy.types.PropertyGroup):
    tool_id: StringProperty()
    display_name: StringProperty()
    enabled: BoolProperty(
        default=True,
        update=lambda self, ctx: _on_toggle(self),
    )


# ==================================================
# Addon preferences
# ==================================================
class XNekoPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    panel_category: StringProperty(
        name="N Panel Category",
        description="Category name shown in the N panel sidebar. "
                    "Use the same name as another add-on to merge them.",
        default="XNeko Tools",
        update=lambda self, ctx: refresh_panel_category(),
    )

    active_category: StringProperty(default="")

    tab_page: IntProperty(default=0)

    tool_toggles: CollectionProperty(type=XNekoToolToggle)

    def draw(self, context):
        layout = self.layout

        # ---------- N panel category input ----------
        layout.prop(self, "panel_category")

        # ---------- Tools: top tabs / bottom toggles ----------
        layout.separator()
        layout.label(text="Tools:")

        # Group all tool toggles by category id
        groups = {}
        for item in self.tool_toggles:
            gid = item.tool_id.rsplit(".", 1)[0] if "." in item.tool_id else ""
            if gid.startswith("tools."):
                gid = gid[len("tools."):]
            groups.setdefault(gid or "(root)", []).append(item)

        if not groups:
            layout.label(text="No tools found", icon='INFO')
        else:
            # Fall back to first category if the stored one no longer exists
            if self.active_category not in groups:
                self.active_category = list(groups.keys())[0]

            # ----- Top: horizontal tab bar with paging arrows -----
            all_gids = list(groups.keys())
            total = len(all_gids)

            # Dynamic tabs-per-page based on available width
            usable_px = _get_usable_width(context)

            widest_tab_px = 1
            for gid in all_gids:
                display_text = gid.replace(".", " / ").replace("_", " ").title()
                w = _estimate_tab_px(display_text)
                if w > widest_tab_px:
                    widest_tab_px = w

            # Use the widest tab as the reference so no tab ever overflows
            TABS_PER_PAGE = max(1, usable_px // widest_tab_px)
            if TABS_PER_PAGE > total:
                TABS_PER_PAGE = total

            page_count = max(1, (total + TABS_PER_PAGE - 1) // TABS_PER_PAGE)

            # Clamp stored page to valid range
            if self.tab_page >= page_count:
                self.tab_page = page_count - 1
            if self.tab_page < 0:
                self.tab_page = 0

            start = self.tab_page * TABS_PER_PAGE
            end = min(start + TABS_PER_PAGE, total)
            visible_gids = all_gids[start:end]

            # One single row: [<] tab tab tab [>]
            tab_row = layout.row(align=True)

            left = tab_row.row(align=True)
            left.enabled = self.tab_page > 0
            left.operator(
                "xneko.shift_tab_page",
                text="",
                icon='TRIA_LEFT',
            ).delta = -1

            for gid in visible_gids:
                display = gid.replace(".", " / ").replace("_", " ").title()
                is_active = (self.active_category == gid)
                tab_row.operator(
                    "xneko.set_active_category",
                    text=display,
                    icon=core._get_group_icon(gid),
                    depress=is_active,
                ).category = gid

            right = tab_row.row(align=True)
            right.enabled = self.tab_page < page_count - 1
            right.operator(
                "xneko.shift_tab_page",
                text="",
                icon='TRIA_RIGHT',
            ).delta = 1

            # ----- Bottom: toggles of the active category -----
            box = layout.box()
            for item in groups[self.active_category]:
                box.prop(item, "enabled", text=item.display_name)

        # ---------- Links ----------
        layout.separator()
        layout.label(text="Links:", icon='BOOKMARKS')

        by_author = {}
        for label, url, icon, author in LINKS:
            by_author.setdefault(author, []).append((label, url, icon))

        for author, items in by_author.items():
            box = layout.box()
            box.label(text=author, icon='USER')
            grid = box.grid_flow(row_major=True, columns=2, even_columns=True)
            for label, url, icon in items:
                grid.operator("wm.url_open", text=label, icon=icon).url = url


# ==================================================
# Callbacks
# ==================================================
def _on_toggle(item):
    if item.enabled:
        core.load_tool(item.tool_id)
    else:
        core.unload_tool(item.tool_id)

    screen = bpy.context.screen
    if screen is not None:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def init_tool_toggles():
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return
    p = prefs.preferences
    p.tool_toggles.clear()
    for tool_id, tool in core._TOOL_REGISTRY.items():
        item = p.tool_toggles.add()
        item.tool_id = tool_id
        item.display_name = tool["display_name"]
        item.enabled = tool["enabled_by_default"]


def clear_tool_toggles():
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return
    prefs.preferences.tool_toggles.clear()


def refresh_panel_category():
    """Re-register all panels with the category name from preferences."""
    prefs = bpy.context.preferences.addons.get(__package__)
    if not prefs:
        return

    category = (prefs.preferences.panel_category or "XNeko Tools").strip() or "XNeko Tools"

    all_panels = list(core._GROUP_PANEL_CLASSES)

    for tool in core._TOOL_REGISTRY.values():
        if tool["loaded"]:
            for cls in tool["classes"]:
                if isinstance(cls, type) and issubclass(cls, bpy.types.Panel):
                    all_panels.append(cls)

    for cls in all_panels:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    for cls in all_panels:
        cls.bl_category = category

    for cls in core._GROUP_PANEL_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass

    for tool in core._TOOL_REGISTRY.values():
        if tool["loaded"]:
            for cls in tool["classes"]:
                if isinstance(cls, type) and issubclass(cls, bpy.types.Panel):
                    try:
                        bpy.utils.register_class(cls)
                    except Exception:
                        pass