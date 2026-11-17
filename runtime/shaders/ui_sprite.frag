#version 450
// Sharper enlarged UI sprites (the plain variant).
// The game's own shader (Unity's UI sprite shader as the translator produced it; SPIR-V FNV-1a 7b7d7c7ab436c4ec, decompiled with
// spirv-cross) with its one texture read replaced by ui_sample: runtime/ui_sharp.c swaps it in. The bindings,
// locations and arithmetic are the game's.
//
// ui_sample: where the sprite is drawn larger than its texture (the battle menu's buttons, the damage digits: 54 and 64
// texel sprites shown 2 to 4 times their size at 4K), bilinear filtering shows the texels as a soft staircase along every
// edge. There it takes a Catmull-Rom bicubic instead (9 bilinear taps; the weights as in "Filtering in fewer taps",
// vec3.ca), clamped to the 2x2 texels around the point so the curve does not ring past them, and then sharpens each
// edge to one screen pixel (below). A sprite drawn at its size or smaller is sampled as the game does.

layout(set = 0, binding = 0, std140) uniform support_buffer
{
    layout(offset = 0) uint _m0;
    layout(offset = 16) uint _m1[8];
    layout(offset = 144) vec4 _m2;
    layout(offset = 160) vec4 _m3;
    layout(offset = 176) int _m4;
    layout(offset = 192) float _m5[73];
    layout(offset = 1360) ivec4 _m6;
    layout(offset = 1376) int _m7;
    layout(offset = 1392) float _m8;
    layout(offset = 1408) vec4 _m9;
    layout(offset = 1424) vec4 _m10;
} support_buffer_1;

layout(set = 0, binding = 2, std140) uniform fp_c1
{
    vec4 _m0[4096];
} fp_c1_1;

layout(set = 0, binding = 3, std140) uniform fp_c3
{
    vec4 _m0[4096];
} fp_c3_1;

layout(set = 0, binding = 1) uniform sampler2D fp_t_cb196610_1056805A;

layout(location = 3) in vec4 _29;
layout(location = 0) in vec4 _31;
layout(location = 0) out vec4 _34;

vec4 ui_sample(sampler2D t, vec2 uv) {
    vec2 size = vec2(textureSize(t, 0));
    vec2 texels = fwidth(uv * size);   // texels per pixel
    if (max(texels.x, texels.y) >= 1.0 || size.x < 4.0 || size.y < 4.0) return texture(t, uv);
    vec2 p = uv * size - 0.5, f = fract(p), c = floor(p) + 0.5;
    vec2 w0 = f * (-0.5 + f * (1.0 - 0.5 * f));
    vec2 w1 = 1.0 + f * f * (-2.5 + 1.5 * f);
    vec2 w2 = f * (0.5 + f * (2.0 - 1.5 * f));
    vec2 w3 = f * f * (-0.5 + 0.5 * f);
    vec2 w12 = w1 + w2;
    vec2 t0 = (c - 1.0) / size, t3 = (c + 2.0) / size, t12 = (c + w2 / w12) / size;
    vec4 r = (textureLod(t, vec2(t0.x, t0.y), 0.0) * w0.x + textureLod(t, vec2(t12.x, t0.y), 0.0) * w12.x +
              textureLod(t, vec2(t3.x, t0.y), 0.0) * w3.x) * w0.y +
             (textureLod(t, vec2(t0.x, t12.y), 0.0) * w0.x + textureLod(t, vec2(t12.x, t12.y), 0.0) * w12.x +
              textureLod(t, vec2(t3.x, t12.y), 0.0) * w3.x) * w12.y +
             (textureLod(t, vec2(t0.x, t3.y), 0.0) * w0.x + textureLod(t, vec2(t12.x, t3.y), 0.0) * w12.x +
              textureLod(t, vec2(t3.x, t3.y), 0.0) * w3.x) * w3.y;
    ivec2 i = ivec2(floor(p)), last = ivec2(size) - 1;
    vec4 a = texelFetch(t, clamp(i, ivec2(0), last), 0), b = texelFetch(t, clamp(i + ivec2(1, 0), ivec2(0), last), 0);
    vec4 d = texelFetch(t, clamp(i + ivec2(0, 1), ivec2(0), last), 0), e = texelFetch(t, clamp(i + ivec2(1, 1), ivec2(0), last), 0);
    vec4 lo = min(min(a, b), min(d, e)), hi = max(max(a, b), max(d, e)), range = hi - lo;
    r = clamp(r, lo, hi);
    // Edge reconstruction: the sprites are flat colours with edges one texel wide, so between the darker and
    // lighter texels around the point the bicubic value is a position across that edge. Pushing it to the
    // nearer side, with a ramp one screen pixel wide (texels per pixel, in texel units), redraws the edge at the
    // screen's resolution along the smooth curve the bicubic traces, instead of one texel wide and soft.
    float k = clamp(0.5 * max(texels.x, texels.y), 0.03, 0.5);
    vec4 s = smoothstep(0.5 - k, 0.5 + k, clamp((r - lo) / max(range, vec4(1e-4)), 0.0, 1.0));
    return mix(r, lo + range * s, step(vec4(0.06), range));
}

void main()
{
    vec2 _54 = vec2(_29.x, _29.y);
    vec4 _41 = ui_sample(fp_t_cb196610_1056805A, mix(_54, vec2(0.0), isnan(_54))).xyzw;
    precise float _69 = _41.w + fp_c3_1._m0[0].w;
    precise float _74 = _31.w * fp_c1_1._m0[0].x;
    precise float _79 = roundEven(_74) * fp_c1_1._m0[0].y;
    precise float _80 = _69 * _79;
    float _44 = _80;
    precise float _87 = _41.x + fp_c3_1._m0[0].x;
    precise float _90 = _87 * _31.x;
    precise float _92 = _90 * _44;
    _34.x = _92;
    precise float _98 = _41.y + fp_c3_1._m0[0].y;
    precise float _101 = _98 * _31.y;
    precise float _103 = _101 * _44;
    _34.y = _103;
    precise float _110 = _41.z + fp_c3_1._m0[0].z;
    precise float _113 = _110 * _31.z;
    precise float _115 = _113 * _44;
    _34.z = _115;
    _34.w = _44;
}

