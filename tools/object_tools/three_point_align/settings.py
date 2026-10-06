"""Per-scene settings + a small sidebar panel."""

from bpy.types import PropertyGroup, Panel
from bpy.props import BoolProperty, IntProperty, FloatVectorProperty


class ThreePointAlignSettings(PropertyGroup):

    # ----- redo-menu defaults -----
    keep_scale: BoolProperty(
        name="匹配距离",
        description="按两网格的距离比例缩放目标网格",
        default=False,
    )
    place_origin_between: BoolProperty(
        name="原点居中",
        description="把目标网格原点移到第 1、2 对点的中点",
        default=False,
    )
    reveal_origin: BoolProperty(
        name="显示变换轴",
        description="对齐后显示变换轴",
        default=False,
    )

    # ----- colors -----
    line1_color: FloatVectorProperty(
        name="连线 1", subtype='COLOR', size=4, min=0, max=1,
        default=(1.0, 0.90, 0.20, 1.0))
    line2_color: FloatVectorProperty(
        name="连线 2", subtype='COLOR', size=4, min=0, max=1,
        default=(1.0, 0.55, 0.15, 1.0))
    line3_color: FloatVectorProperty(
        name="连线 3", subtype='COLOR', size=4, min=0, max=1,
        default=(0.95, 0.15, 0.15, 1.0))
    cursor_color: FloatVectorProperty(
        name="光标", subtype='COLOR', size=4, min=0, max=1,
        default=(1.0, 1.0, 1.0, 1.0))
    plane_color: FloatVectorProperty(
        name="三角面", subtype='COLOR', size=4, min=0, max=1,
        default=(0.10, 0.70, 1.00, 0.18))

    # ----- sizes -----
    snap_radius_px: IntProperty(
        name="顶点吸附距离 (px)", min=1, max=200, default=20)
    dot_radius_px: IntProperty(
        name="点大小 (px)", min=1, max=64, default=10)
    cursor_radius_px: IntProperty(
        name="光标大小 (px)", min=4, max=256, default=48)


class XNEKO_PT_three_point_align_settings(Panel):
    bl_label = "三点对齐"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'XNeko Tools'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, 'xneko_tpa')

    def draw(self, context):
        layout = self.layout
        s = context.scene.xneko_tpa

        layout.label(text="颜色", icon='COLOR')
        col = layout.column(align=True)
        col.prop(s, 'line1_color', text='连线 1')
        col.prop(s, 'line2_color', text='连线 2')
        col.prop(s, 'line3_color', text='连线 3')
        col.prop(s, 'cursor_color', text='光标')
        col.prop(s, 'plane_color', text='三角面')

        layout.separator()
        layout.label(text="尺寸", icon='FULLSCREEN_ENTER')
        col = layout.column(align=True)
        col.prop(s, 'snap_radius_px')
        col.prop(s, 'dot_radius_px')
        col.prop(s, 'cursor_radius_px')

        layout.separator()
        layout.label(text="默认行为", icon='PREFERENCES')
        col = layout.column(align=True)
        col.prop(s, 'reveal_origin')
        col.prop(s, 'keep_scale')
        col.prop(s, 'place_origin_between')