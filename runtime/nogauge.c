// No gauge moves (MRPG_HIDE_GAUGE; recomp/patches-v101.txt, set nogauge): the patches make the game treat its gauge and
// its timed-hit chain as in the prologue, where neither fills. Both values live in the save data and carry over from
// battle to battle, and the code that would empty them is the code the patches skip: a gauge or a chain the save already
// had would stay, and a chain keeps its attack and speed bonus (GlobalWork.get_combo_ratio_atk, main+0x188ad70). So while
// the set is on, both are held at 0, at every present. Where they are, in version 1.0.1 (as the MCP cheats read them,
// tools/mcp/mrpg_tools.py): GlobalWork's class through the pointer at main+0x3a58048, its static fields at class+0xb8,
// the instance in the first of them; the save data at instance+0x130; in it the chain count at +0x98
// (GlobalWork.get_just_combo_count, main+0x18877b0) and the gauge at +0x9c (get_just_gauge, main+0x1887820).
#include <stdint.h>
#include <string.h>

#include "host.h"
#include "layout.h"
#include "platform/platform.h"

#define GLOBAL_WORK_CLASS_REF 0x3a58048ull

static int ptr_ok(uint64_t p) { return p > 0x10000 && !(p & 7); }

void nogauge_tick(void) {
    static int set = -2;
    if (set == -2) set = rt_patch_set("nogauge");
    if (!rt_patch_enabled(set)) return;
    uint64_t slot = 0, klass = 0, statics = 0, inst = 0, save = 0;
    if (!plat_mem_read(MOD_MAIN_BASE + GLOBAL_WORK_CLASS_REF, &slot, 8) || !ptr_ok(slot) ||
        !plat_mem_read(slot, &klass, 8) || !ptr_ok(klass) || !plat_mem_read(klass + 0xb8, &statics, 8) ||
        !ptr_ok(statics) || !plat_mem_read(statics, &inst, 8) || !ptr_ok(inst) ||
        !plat_mem_read(inst + 0x130, &save, 8) || !ptr_ok(save) || !plat_mem_readable(save + 0x98, 8))
        return;   // no game state yet
    int32_t v[2];
    memcpy(v, (const void *)(uintptr_t)(save + 0x98), 8);
    if (v[0] || v[1]) memset((void *)(uintptr_t)(save + 0x98), 0, 8);
}
