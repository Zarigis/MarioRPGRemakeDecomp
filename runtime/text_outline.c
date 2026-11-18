// Text outlines that follow the text's colour. The game draws its text with TextMeshPro's Distance Field shader, whose
// outline has one colour per material: a font mod that turns the outline on (tools/font_mod.py --outline) gives dark
// dialogue text and white menu text the same outline, and no one colour suits both. When the mod asks for it by setting
// the outline colour to magenta (--outline-color auto), the shader here picks the outline from the text's own colour
// instead: MRPG_TEXT_OUTLINE_LIGHT around dark text, MRPG_TEXT_OUTLINE_DARK around light text (RRGGBB hex, sRGB; read
// at start). The game's fragment shader is recognised by the FNV-1a hash of its translated SPIR-V (the hash vk_dump.c
// names shaders by) and replaced with runtime/shaders/text_outline.frag, the same shader with that one change; materials
// with any other outline colour, the game's own among them, draw as before. Another translator or game version gives
// another hash, and the game's shader stays.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "cfg.h"
#include "host.h"
#include "text_outline_spv.h"
#include "platform/platform.h"

#define TEXT_FS_HASH 0x913112079c440ca2ull

static uint64_t fnv(const uint32_t *w, uint64_t words) {
    const uint8_t *b = (const uint8_t *)w;
    uint64_t h = 0xcbf29ce484222325ull;
    for (uint64_t i = 0; i < words * 4; i++) h = (h ^ b[i]) * 0x100000001b3ull;
    return h;
}

static float srgb_decode(float c) { return c <= 0.04045f ? c / 12.92f : powf((c + 0.055f) / 1.055f, 2.4f); }

// Setting key as a linear colour into rgb; 0 when it is not six hex digits.
static int colour(const char *key, float rgb[3]) {
    const char *v = cfg_value(key);
    unsigned x;
    char tail;
    if (!v || strlen(v) != 6 || sscanf(v, "%6x%c", &x, &tail) != 1) return 0;
    for (int i = 0; i < 3; i++) rgb[i] = srgb_decode((float)((x >> (16 - 8 * i)) & 0xff) / 255.0f);
    return 1;
}

void text_outline_shader_swap(uint32_t **spirv, uint64_t *words) {
    static int on = -1;
    static float rgb[6];
    if (on < 0) {
        on = colour("MRPG_TEXT_OUTLINE_LIGHT", rgb) && colour("MRPG_TEXT_OUTLINE_DARK", rgb + 3);
        if (!on) rt_log("text_outline: MRPG_TEXT_OUTLINE_LIGHT or _DARK is not RRGGBB; outlines keep their material's colour");
    }
    if (!on || !*spirv || *words < 5 || fnv(*spirv, *words) != TEXT_FS_HASH) return;
    uint32_t *out = malloc(sizeof text_outline_spv);
    if (!out) return;
    memcpy(out, text_outline_spv, sizeof text_outline_spv);
    // the six placeholder constants of LIGHT and DARK (shaders/text_outline.frag): their float bits, each once in the module
    static const float ph[6] = {0.123456789f, 0.234567891f, 0.345678912f, 0.456789123f, 0.567891234f, 0.678912345f};
    int found = 0;
    for (size_t i = 0; i < sizeof text_outline_spv / 4; i++)
        for (int k = 0; k < 6; k++) {
            uint32_t b;
            memcpy(&b, &ph[k], 4);
            if (out[i] == b) memcpy(&out[i], &rgb[k], 4), found |= 1 << k;
        }
    if (found != 0x3f) {
        rt_log("text_outline: the shader's colour constants were not found; outlines keep their material's colour");
        free(out);
        on = 0;
        return;
    }
    free(*spirv);
    *spirv = out;
    *words = sizeof text_outline_spv / 4;
    static volatile int32_t n;
    if (plat_inc32(&n) <= 1)
        rt_log("text_outline: outlines marked auto are %s around dark text, %s around light text",
               cfg_value("MRPG_TEXT_OUTLINE_LIGHT"), cfg_value("MRPG_TEXT_OUTLINE_DARK"));
}
