// Sharper enlarged UI sprites (MRPG_UI_SHARP, default on, read at start). The game draws its battle menu's buttons and
// the damage digits from small sprites (54 and 64 texels high) through Unity's UI sprite shader; at 4K they are shown
// 2 to 4 times their size, and bilinear filtering turns their edges into a soft staircase. The two variants of that
// shader are recognised by the FNV-1a hash of their translated SPIR-V (the hash vk_dump.c names shaders by) and
// replaced with runtime/shaders/ui_sprite.frag and ui_sprite_cutout.frag: the same code, decompiled, with a bicubic
// read where a sprite is enlarged. Another translator or game version gives other hashes, and the game's shaders stay.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "host.h"
#include "ui_sprite_cutout_spv.h"
#include "ui_sprite_spv.h"
#include "platform/platform.h"

static uint64_t fnv(const uint32_t *w, uint64_t words) {
    const uint8_t *b = (const uint8_t *)w;
    uint64_t h = 0xcbf29ce484222325ull;
    for (uint64_t i = 0; i < words * 4; i++) h = (h ^ b[i]) * 0x100000001b3ull;
    return h;
}

void ui_sharp_shader_swap(uint32_t **spirv, uint64_t *words) {
    static int on = -1;
    if (on < 0) on = cfg_bool("MRPG_UI_SHARP");
    if (!on || !*spirv || *words < 5) return;
    static const struct { uint64_t hash; const uint32_t *code; size_t size; } swaps[] = {
        {0x7b7d7c7ab436c4ecull, ui_sprite_spv, sizeof ui_sprite_spv},
        {0x4477bffb445d09f0ull, ui_sprite_cutout_spv, sizeof ui_sprite_cutout_spv},
    };
    uint64_t h = fnv(*spirv, *words);
    for (size_t i = 0; i < sizeof swaps / sizeof *swaps; i++) {
        if (swaps[i].hash != h) continue;
        uint32_t *out = malloc(swaps[i].size);
        if (!out) return;
        memcpy(out, swaps[i].code, swaps[i].size);
        free(*spirv);
        *spirv = out;
        *words = swaps[i].size / 4;
        static volatile int32_t n;
        if (plat_inc32(&n) <= 2) rt_log("ui_sharp: the UI sprite shader %016llx samples enlarged sprites bicubically", (unsigned long long)h);
        return;
    }
}
