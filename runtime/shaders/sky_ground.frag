#version 450
// The field's background (runtime/sky_ground.c, MRPG_SKY_GROUND): Unity's procedural skybox shader of Super Mario RPG
// (fragment shader FNV 0x11c2f08abe8aecb7, decompiled from its translated SPIR-V) with the ground colour replaced. The
// skybox mixes its sky colour and its ground colour by the view direction's height, clamp(50 y), and adds the sun on the
// sky side; the field camera looks down, so all it shows around a room is the ground colour, a flat grey. Here GROUND
// takes the place of the ground colour the vertex shader passes in (_26, still declared so the interface matches): the
// horizon blend and the sky stay. GROUND's three values are placeholders that sky_ground.c finds in the SPIR-V and
// replaces with the setting's colour (linear).

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

layout(binding = 1, std140) uniform fp_c3
{
    vec4 _m0[4096];
} fp_c3_1;

layout(binding = 2, std140) uniform fp_c1
{
    vec4 _m0[4096];
} fp_c1_1;

layout(location = 0) in vec4 _24;
layout(location = 1) in vec4 _26;
layout(location = 2) in vec4 _28;
layout(location = 3) in vec4 _30;
layout(location = 0) out vec4 _33;

const vec3 GROUND = vec3(0.123456789, 0.234567891, 0.345678912);

void main()
{
    float _40 = _24.x;
    float _42 = _24.y;
    float _44 = _24.z;
    precise float _94 = _40 * _40;
    float _46 = inversesqrt(fma(_44, _44, fma(_42, _42, _94)));
    precise float _101 = _42 * _46;
    float _48 = _101;
    bool _52 = _48 < 0.0;
    precise float _107 = _48 * 50.0;
    float _54 = clamp(_107, 0.0, 1.0);
    float _56 = _28.x;
    precise float _114 = _44 * _46;
    precise float _125 = _40 * _46;
    precise float _129 = _125 * (-fp_c3_1._m0[0].x);
    precise float _136 = log2(clamp(fma(_114, -fp_c3_1._m0[0].z, fma(_48, -fp_c3_1._m0[0].y, _129)), 0.0, 1.0)) * fp_c3_1._m0[1].y;
    float _58 = exp2(_136);
    float _60 = _28.z;
    float _62 = _28.y;
    precise float _147 = GROUND.x + (-_56);
    float _64 = fma(_54, _147, _56);
    precise float _155 = GROUND.z + (-_60);
    float _66 = fma(_54, _155, _60);
    precise float _163 = GROUND.y + (-_62);
    float _68 = fma(_54, _163, _62);
    precise float _173 = fma(_58, _58, fp_c1_1._m0[0].z) * fp_c1_1._m0[1].x;
    precise float _180 = log2(fp_c3_1._m0[1].x) * fp_c1_1._m0[0].w;
    precise float _183 = exp2(_180) * 10.0;
    precise float _190 = (-0.0) + fp_c1_1._m0[0].y;
    precise float _193 = _183 * log2(fma(_58, fp_c1_1._m0[0].x, _190));
    precise float _197 = 1.0 / max(exp2(_193), 0.00010001659393310546875);
    precise float _198 = _173 * _197;
    float _70 = _198;
    int _73 = floatBitsToInt(_64);
    int _75 = floatBitsToInt(_68);
    int _77 = floatBitsToInt(_66);
    if (_52)
    {
        _73 = floatBitsToInt(fma(_30.x, _70, _64));
    }
    if (_52)
    {
        _75 = floatBitsToInt(fma(_30.y, _70, _68));
    }
    if (_52)
    {
        _77 = floatBitsToInt(fma(_30.z, _70, _66));
    }
    _33.x = intBitsToFloat(_73);
    _33.y = intBitsToFloat(_75);
    _33.z = intBitsToFloat(_77);
    _33.w = 1.0;
}

