"""GLSL sources for the three-point align overlays.

Shaders are compiled lazily and cached in `_CACHE` so repeated draws
do not re-compile them.
"""

import gpu


_CACHE = {}


_VS_3D = """
uniform mat4 viewProjection;
uniform vec4 baseColor;

in vec3 position;
out vec4 vColor;

void main() {
    gl_Position = viewProjection * vec4(position, 1.0);
    vColor = baseColor;
}
"""


_FS_FLAT = """
in vec4 vColor;
out vec4 fragColor;
void main() { fragColor = vColor; }
"""


_FS_ROUND = """
in vec4 vColor;
out vec4 fragColor;

void main() {
    float r = length(gl_PointCoord - vec2(0.5));
    if (r > 0.5) discard;
    float a = smoothstep(0.5, 0.40, r);
    fragColor = vec4(vColor.rgb, vColor.a * a);
}
"""


_FS_CROSS = """
uniform float time;

in vec4 vColor;
out vec4 fragColor;

float band(vec2 uv, vec2 center, vec2 half) {
    vec2 d = abs(uv - center) - half;
    return 1.0 - smoothstep(0.0, 0.02, max(d.x, d.y));
}

void main() {
    vec2 uv = gl_PointCoord - vec2(0.5);
    uv = mat2(0.7071, -0.7071, 0.7071, 0.7071) * uv + vec2(0.5);

    float pulse = 0.05 + 0.05 * sin(time * 5.0);
    float arm = 0.20;
    float thick = 0.015;

    float m = 0.0;
    m = max(m, band(uv, vec2(0.5, 0.5 + arm - pulse), vec2(thick, arm)));
    m = max(m, band(uv, vec2(0.5, 0.5 - arm + pulse), vec2(thick, arm)));
    m = max(m, band(uv, vec2(0.5 + arm - pulse, 0.5), vec2(arm, thick)));
    m = max(m, band(uv, vec2(0.5 - arm + pulse, 0.5), vec2(arm, thick)));

    if (m < 0.01) discard;
    fragColor = vec4(vColor.rgb, vColor.a * m);
}
"""


def solid_3d():
    if 'solid_3d' not in _CACHE:
        _CACHE['solid_3d'] = gpu.types.GPUShader(_VS_3D, _FS_FLAT)
    return _CACHE['solid_3d']


def round_point_3d():
    if 'round_point_3d' not in _CACHE:
        _CACHE['round_point_3d'] = gpu.types.GPUShader(_VS_3D, _FS_ROUND)
    return _CACHE['round_point_3d']


def pulsing_cross_3d():
    if 'pulsing_cross_3d' not in _CACHE:
        _CACHE['pulsing_cross_3d'] = gpu.types.GPUShader(_VS_3D, _FS_CROSS)
    return _CACHE['pulsing_cross_3d']