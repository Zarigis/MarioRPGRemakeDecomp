#version 450
// Text outlines that follow the text's colour (runtime/text_outline.c): TextMeshPro's Distance Field fragment shader as
// Super Mario RPG builds it (FNV 0x913112079c440ca2, decompiled from its translated SPIR-V), with one change: when the
// material's outline colour is magenta (1, 0, 1), the marker tools/font_mod.py --outline-color auto writes, the outline
// takes a colour chosen from the text's own colour (the vertex colour times the face colour): LIGHT around dark text,
// DARK around light text, blended over a short range of luminance. Any other outline colour, the game's own materials
// among them, draws as before. LIGHT and DARK are placeholders that text_outline.c replaces with the settings' colours
// (linear).
//
// The inputs, as the decompiled shader uses them: _33.xy the atlas coordinates; _35 x the alpha clip, y the distance
// scale, z the bias; _37 the face (xy) and outline (zw) texture coordinates; _39 the vertex colour. fp_c3 is the
// material: [2] _FaceColor, [4] _OutlineColor, [5] x _OutlineWidth, y _ScaleRatioA, [3] x _OutlineSoftness.

layout(binding = 0, std140) uniform support_buffer
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

layout(binding = 4, std140) uniform fp_c3
{
    vec4 _m0[4096];
} fp_c3_1;

layout(binding = 5, std140) uniform fp_c1
{
    vec4 _m0[4096];
} fp_c1_1;

layout(binding = 1) uniform sampler2D fp_t_cb196610_1057805A;
layout(binding = 2) uniform sampler2D fp_t_cb196610_1056805C;
layout(binding = 3) uniform sampler2D fp_t_cb196610_1057005E;

layout(location = 6) in vec4 _33;
layout(location = 1) in vec4 _35;
layout(location = 5) in vec4 _37;
layout(location = 0) in vec4 _39;
layout(location = 0) out vec4 _42;

const vec3 LIGHT = vec3(0.123456789, 0.234567891, 0.345678912);
const vec3 DARK = vec3(0.456789123, 0.567891234, 0.678912345);

void main()
{
    vec2 _100 = vec2(_33.x, _33.y);
    float _49 = texture(fp_t_cb196610_1057805A, mix(_100, vec2(0.0), isnan(_100))).w;
    if (_49 < _35.x)
    {
        discard;
    }
    vec2 _132 = vec2(fma(fp_c3_1._m0[0].y, fp_c3_1._m0[1].x, _37.x), fma(fp_c3_1._m0[0].y, fp_c3_1._m0[1].y, _37.y));
    vec4 _52 = texture(fp_t_cb196610_1056805C, mix(_132, vec2(0.0), isnan(_132))).xyzw;
    float _54 = _52.w;
    vec2 _156 = vec2(fma(fp_c3_1._m0[0].y, fp_c3_1._m0[3].y, _37.z), fma(fp_c3_1._m0[0].y, fp_c3_1._m0[3].z, _37.w));
    vec4 _56 = texture(fp_t_cb196610_1057005E, mix(_156, vec2(0.0), isnan(_156))).xyzw;
    float _58 = _56.w;
    vec3 face = _39.xyz * fp_c3_1._m0[2].xyz;
    vec3 oc = fp_c3_1._m0[4].xyz;
    if (oc == vec3(1.0, 0.0, 1.0))
    {
        float lum = dot(face, vec3(0.2126, 0.7152, 0.0722));   // linear: dark brown text is near 0.03, white 1
        oc = mix(LIGHT, DARK, smoothstep(0.12, 0.3, lum));
    }
    precise float _169 = _39.x * fp_c3_1._m0[2].x;
    precise float _170 = _52.x * _169;
    float _60 = _170;
    precise float _174 = _54 * fp_c3_1._m0[2].w;
    float _62 = _174;
    precise float _181 = _39.y * fp_c3_1._m0[2].y;
    precise float _182 = _52.y * _181;
    float _64 = _182;
    precise float _189 = _39.z * fp_c3_1._m0[2].z;
    precise float _190 = _52.z * _189;
    float _66 = _190;
    precise float _195 = _58 * fp_c3_1._m0[4].w;
    float _68 = _195;
    float _70 = _35.y;
    precise float _202 = (-_49) + _35.z;
    float _72 = _202;
    precise float _208 = fp_c3_1._m0[5].y * fp_c3_1._m0[3].x;
    float _74 = _208;
    precise float _213 = fp_c3_1._m0[5].y * fp_c3_1._m0[5].x;
    precise float _215 = _213 * _70;
    precise float _217 = _215 * 0.5;
    float _76 = _217;
    precise float _228 = fp_c3_1._m0[5].y * fp_c3_1._m0[5].x;
    precise float _230 = _228 * _70;
    precise float _233 = clamp(fma(_72, _70, _76), 0.0, 1.0) * sqrt(min(_230, 1.0));
    float _78 = _233;
    precise float _241 = _56.x * oc.x;
    precise float _245 = _60 * _62;
    precise float _248 = _78 * fma(_241, _68, -_245);
    float _80 = fma(_60, _62, _248);
    float _82 = _39.w;
    precise float _259 = _56.y * oc.y;
    precise float _263 = _64 * _62;
    precise float _266 = _78 * fma(_259, _68, -_263);
    float _84 = fma(_64, _62, _266);
    precise float _275 = _56.z * oc.z;
    precise float _279 = _66 * _62;
    precise float _282 = _78 * fma(_275, _68, -_279);
    float _86 = fma(_66, _62, _282);
    precise float _294 = _78 * fma(_58, fp_c3_1._m0[4].w, -_62);
    float _88 = fma(_54, fp_c3_1._m0[2].w, _294);
    precise float _298 = _70 * _74;
    precise float _310 = 1.0 / fma(_70, _74, fp_c1_1._m0[0].x);
    precise float _311 = fma(_298, 0.5, fma(_72, _70, -_76)) * _310;
    float _90 = clamp(_311, 0.0, 1.0);
    precise float _321 = fma(_90, -_80, _80) * _82;
    _42.x = _321;
    precise float _329 = fma(_90, -_84, _84) * _82;
    _42.y = _329;
    precise float _337 = fma(_90, -_86, _86) * _82;
    _42.z = _337;
    precise float _345 = fma(_90, -_88, _88) * _82;
    _42.w = _345;
}
