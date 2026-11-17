// The colour around a field room (MRPG_SKY_GROUND, read at start). Behind a room's edges the field camera sees Unity's
// procedural skybox, and looking down it sees the skybox's ground colour: a flat light grey where the original game
// showed dark blue. The skybox's fragment shader is recognised by the FNV-1a hash of its translated SPIR-V (the hash
// vk_dump.c names shaders by) and replaced with runtime/shaders/sky_ground.frag, the same shader with the ground colour
// taken from the setting. The setting is a colour as RRGGBB hex (sRGB, the colour as shown in SDR), or "game" for the
// game's grey. The default is the blue of the Super Nintendo version's backgrounds, 1839e0. Another translator or game
// version gives another hash, and the game's shader stays.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "cfg.h"
#include "host.h"
#include "sky_ground_spv.h"
#include "platform/platform.h"

#define SKY_FS_HASH 0x11c2f08abe8aecb7ull

static uint64_t fnv(const uint32_t *w, uint64_t words) {
    const uint8_t *b = (const uint8_t *)w;
    uint64_t h = 0xcbf29ce484222325ull;
    for (uint64_t i = 0; i < words * 4; i++) h = (h ^ b[i]) * 0x100000001b3ull;
    return h;
}

static float srgb_decode(float c) { return c <= 0.04045f ? c / 12.92f : powf((c + 0.055f) / 1.055f, 2.4f); }

// The setting's colour, linear, into rgb; 0 for "game" or a value that is not six hex digits.
static int wanted(float rgb[3]) {
    const char *v = cfg_value("MRPG_SKY_GROUND");
    unsigned x;
    char tail;
    if (!v || strlen(v) != 6 || sscanf(v, "%6x%c", &x, &tail) != 1) return 0;
    for (int i = 0; i < 3; i++) rgb[i] = srgb_decode((float)((x >> (16 - 8 * i)) & 0xff) / 255.0f);
    return 1;
}

void sky_ground_shader_swap(uint32_t **spirv, uint64_t *words) {
    static int on = -1;
    static float rgb[3];
    if (on < 0) on = wanted(rgb);
    if (!on || !*spirv || *words < 5 || fnv(*spirv, *words) != SKY_FS_HASH) return;
    uint32_t *out = malloc(sizeof sky_ground_spv);
    if (!out) return;
    memcpy(out, sky_ground_spv, sizeof sky_ground_spv);
    // the three placeholder constants of GROUND (shaders/sky_ground.frag): their float bits, each once in the module
    static const float ph[3] = {0.123456789f, 0.234567891f, 0.345678912f};
    int found = 0;
    for (size_t i = 0; i < sizeof sky_ground_spv / 4; i++)
        for (int k = 0; k < 3; k++) {
            uint32_t b;
            memcpy(&b, &ph[k], 4);
            if (out[i] == b) memcpy(&out[i], &rgb[k], 4), found |= 1 << k;
        }
    if (found != 7) {
        rt_log("sky_ground: the shader's colour constants were not found; the game's background stays");
        free(out);
        on = 0;
        return;
    }
    free(*spirv);
    *spirv = out;
    *words = sizeof sky_ground_spv / 4;
    static volatile int32_t n;
    if (plat_inc32(&n) <= 1) rt_log("sky_ground: the field background is %s", cfg_value("MRPG_SKY_GROUND"));
}
