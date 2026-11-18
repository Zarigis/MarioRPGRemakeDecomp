// No gauge moves (MRPG_HIDE_GAUGE; recomp/patches-v101.txt, set nogauge): the patches make the game treat its gauge and
// its timed-hit chain as in the prologue, where neither fills. Both values live in the save data and carry over from
// battle to battle, and the code that would empty them is the code the patches skip: a gauge or a chain the save already
// had would stay, and a chain keeps its attack and speed bonus (GlobalWork.get_combo_ratio_atk, main+0x188ad70). So while
// the set is on, both are held at 0, at every present. Where they are, in version 1.0.1 (as the MCP cheats read them,
// tools/mcp/mrpg_tools.py): GlobalWork's class through the pointer at main+0x3a58048, its static fields at class+0xb8,
// the instance in the first of them; the save data at instance+0x130; in it the chain count at +0x98
// (GlobalWork.get_just_combo_count, main+0x18877b0) and the gauge at +0x9c (get_just_gauge, main+0x1887820).
//
// One battle needs its gauge move: in battle 2011 (Bowyer) a scripted event at its end, Battle.BattleEvent.calc_2011_7,
// sets a flag (byte +0x30 of the object at BattleManager +0x60) and fills the gauge (set_just_gauge(600) at
// main+0x1d19650), and Battle.BattleManager.can_use_renkei_waza (main+0x1cd34e0) lets the gauge move through in that
// battle only once the flag is set; with the set on, the fight cannot be won. So in battle 2011 the gauge is not held at
// 0 (nothing else fills it while the set is on: the script's fill must not be lost to the present thread's timing), and
// once the flag is set the set is switched off (rt_patch_switch) until the battle ends. The running battle:
// BattleManager's class through the pointer at main+0x3a57e48, its static fields at +0xb8, the instance at +0x10 of
// them (as frame_rate.c reads it); in it the battle's number at +0x168 (as can_use_renkei_waza reads it) and _frame_rate
// at +0x1c8, 30 or 60 while a battle runs.
#include <stdint.h>
#include <string.h>

#include "host.h"
#include "layout.h"
#include "platform/platform.h"

#define GLOBAL_WORK_CLASS_REF 0x3a58048ull
#define BATTLE_MANAGER_CLASS_REF 0x3a57e48ull
#define GAUGE_BATTLE 2011   // the battle that needs its gauge move

static int ptr_ok(uint64_t p) { return p > 0x10000 && !(p & 7); }

// The number of the battle running now (-1 outside battles), and into *event whether battle 2011's gauge move event
// has set its flag.
static int32_t battle_now(int *event) {
    uint64_t slot = 0, klass = 0, statics = 0, inst = 0, ev = 0;
    int32_t id = -1, rate = 0;
    uint8_t flag = 0;
    *event = 0;
    if (!plat_mem_read(MOD_MAIN_BASE + BATTLE_MANAGER_CLASS_REF, &slot, 8) || !ptr_ok(slot) ||
        !plat_mem_read(slot, &klass, 8) || !ptr_ok(klass) || !plat_mem_read(klass + 0xb8, &statics, 8) ||
        !ptr_ok(statics) || !plat_mem_read(statics + 0x10, &inst, 8) || !ptr_ok(inst) ||
        !plat_mem_read(inst + 0x1c8, &rate, 4) || (rate != 30 && rate != 60) || !plat_mem_read(inst + 0x168, &id, 4))
        return -1;
    if (id == GAUGE_BATTLE && plat_mem_read(inst + 0x60, &ev, 8) && ptr_ok(ev) && plat_mem_read(ev + 0x30, &flag, 1))
        *event = flag != 0;
    return id;
}

void nogauge_tick(void) {
    static int set = -2, wanted, lifted;
    if (set == -2) set = rt_patch_set("nogauge"), wanted = rt_patch_enabled(set);
    if (!wanted) return;
    int event, in_battle = battle_now(&event) == GAUGE_BATTLE, need = in_battle && event;
    if (need != lifted) {
        lifted = need;
        rt_patch_switch(set, !need);
        rt_log("nogauge: %s", need ? "battle 2011's scripted gauge move: the gauge is on until the battle ends"
                                   : "the gauge is off again");
    }
    if (in_battle) {   // the chain still held at 0; the gauge left for the script to fill
        uint64_t slot = 0, klass = 0, statics = 0, inst = 0, save = 0;
        if (!lifted && plat_mem_read(MOD_MAIN_BASE + GLOBAL_WORK_CLASS_REF, &slot, 8) && ptr_ok(slot) &&
            plat_mem_read(slot, &klass, 8) && ptr_ok(klass) && plat_mem_read(klass + 0xb8, &statics, 8) &&
            ptr_ok(statics) && plat_mem_read(statics, &inst, 8) && ptr_ok(inst) && plat_mem_read(inst + 0x130, &save, 8) &&
            ptr_ok(save) && plat_mem_readable(save + 0x98, 4))
            __atomic_store_n((int32_t *)(uintptr_t)(save + 0x98), 0, __ATOMIC_RELAXED);
        return;
    }
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
