# ------------------------------------------------------------
# GPU shader source strings for the three-points-align overlay.
# Kept identical to the original addon; no functional changes.
# ------------------------------------------------------------


def color_3d_vertex_shader():
    return '''
        uniform mat4 viewProjectionMatrix;
        uniform vec4 color;

        in vec3 pos;
        out vec4 finalColor;

        void main()
        {
            gl_Position = viewProjectionMatrix * vec4(pos, 1.0);;
            finalColor = color;
        }
    '''


def simple_fragment_shader():
    return '''
        in vec4 finalColor;
        out vec4 FragColor;

        void main()
        {
            FragColor = finalColor;
        }
    '''


def point_fragment_shader():
    return '''
        in vec4 finalColor;
        out vec4 fragColor;

        void main()
        {
            vec2 st = gl_PointCoord;
            float dist = distance(vec2(0.5), st);
            float alpha = 1 - smoothstep(0.45, 0.5, dist);
            fragColor = finalColor * alpha;
        }
    '''


def cross_fragment_shader():
    return '''
        uniform float u_time;
        #define PI 3.14159265359

        in vec4 finalColor;
        out vec4 fragColor;

        float box(in vec2 _st, in vec2 _size, in vec2 _pos){
            _size = vec2(0.5) - (_size)*0.5;
            vec2 uv = smoothstep(_size, _size+vec2(0.01), _st - _pos);
            uv *= smoothstep(_size, _size+vec2(0.01), vec2(1.0) - _st + _pos);
            return uv.x*uv.y;
        }

        mat2 rotate2d(float _angle){
            return mat2(cos(_angle),-sin(_angle), sin(_angle),cos(_angle));
        }

        void main()
        {
            vec2 st = gl_PointCoord;
            float alpha = 0.0;

            st -= vec2(0.5);
            st = rotate2d( PI/4.0 ) * st;
            st += vec2(0.5);

            float move = sin(u_time*6.0)*0.05 + 0.07;
            float box0 = box(st, vec2(0.03, 0.4), vec2(0.0,0.25+move));
            float box1 = box(st, vec2(0.03, 0.4), vec2(0.0,-0.25-move));
            float box2 = box(st, vec2(0.4, 0.03), vec2(0.25+move,0));
            float box3 = box(st, vec2(0.4, 0.03), vec2(-0.25-move,0));

            alpha =+ box0 + box1 + box2 + box3;

            fragColor = finalColor * alpha;
        }
    '''