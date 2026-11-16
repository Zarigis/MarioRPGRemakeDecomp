// Code patch sets (recomp/patches.py, gen.py --patches). The generator lifts both the original and the replacement
// instructions of every patched site, and rt_patch_on[set] picks one when the site runs, so a set is switched at start
// without touching code, and also while the game runs (rt_patch_switch: the frame-limit setting of the menu). The sets,
// their environment switches and defaults, and the patch page come from the generated patches.h; without it (C
// generated without --patches) there are no sets and every site runs the original.
//
// The patch page is the first 4 KiB page after main's image, inside the module window memory.c reserved: replacement
// code reaches it with one adrp, as MacNativeGames' data page after main (games/totk/runtime/game_patches.c). Its
// layout belongs to the sets that use it (frame_rate.c: +0 the 30 Hz ratio, +4 the frame step in seconds, +8 the
// step in 60 Hz ticks).
// Probe modes never call rt_patches_init: every set stays off.
#include "cfg.h"
#include "platform/platform.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"

#if __has_include("patches.h")
#include "patches.h"
#endif
#ifndef RT_PATCH_COUNT
#define RT_PATCH_COUNT 0
#endif

uint8_t rt_patch_on[RT_PATCH_COUNT > 0 ? RT_PATCH_COUNT : 1];   // read by the generated C at every patched site

#if RT_PATCH_COUNT
static const struct { const char *name, *env; int on; } sets[] = {
#define X(i, n, e, d) {#n, e, d},
    RT_PATCH_SETS(X)
#undef X
};
static void *page;
#endif

void rt_patches_init(void) {
#if RT_PATCH_COUNT
    if (!plat_mem_commit(RT_PATCH_PAGE, 0x1000))
        rt_fatal("patches: cannot commit the patch page at %#llx", RT_PATCH_PAGE);
    page = (void *)(uintptr_t)RT_PATCH_PAGE;
    char list[512];
    size_t n = 0;
    list[0] = 0;
    for (int i = 0; i < RT_PATCH_COUNT; i++) {
        const char *e = cfg_get(sets[i].env);
        // a set with a row in the settings table takes its default from there; the generated default serves the rest
        rt_patch_on[i] = (uint8_t)(cfg_meta(sets[i].env) ? cfg_bool(sets[i].env) : e && *e ? strcmp(e, "0") != 0 : sets[i].on);
        n += (size_t)snprintf(list + n, sizeof list - n, "%s%s %s", i ? ", " : "", sets[i].name,
                              rt_patch_on[i] ? "on" : "off");
        if (n >= sizeof list) n = sizeof list - 1;
    }
    rt_log("patches: %s (page %#llx)", list, RT_PATCH_PAGE);
#endif
}

int rt_patch_set(const char *name) {
#if RT_PATCH_COUNT
    for (int i = 0; i < RT_PATCH_COUNT; i++)
        if (!strcmp(sets[i].name, name)) return i;
#endif
    (void)name;
    return -1;
}

int rt_patch_enabled(int set) { return set >= 0 && set < RT_PATCH_COUNT && rt_patch_on[set]; }

void rt_patch_disable(int set) {
    if (set >= 0 && set < RT_PATCH_COUNT) rt_patch_on[set] = 0;
}

void rt_patch_switch(int set, int on) {
    if (set >= 0 && set < RT_PATCH_COUNT) __atomic_store_n(&rt_patch_on[set], (uint8_t)(on != 0), __ATOMIC_RELAXED);
}

void *rt_patch_page(void) {
#if RT_PATCH_COUNT
    return page;
#else
    return NULL;
#endif
}

// The cave streaming wait of a scene load (patch set cavewait, recomp/patches-v143.txt). The sequence query
// SeqQueryIsCaveStreamingCompleteOrStable (main 0x99e690) lets a load go on once the cave system's stability counter
// ([cave + 0x9500], 30 a second while nothing is pending) has passed 30. The game zeroes the counter whenever the set
// of loaded cave chunks changes, also when surplus chunks of the previous visit are dropped one by one: coming back
// to a place that is still cached (leaving a shrine) then waits 4 to 5 s where a first visit waits 1.5 s. The site at
// 0x99e778 (ldr w10, [x10], the counter) calls here instead with x10 = the counter's address and w11 = the number of
// loaded chunks, and gets a count of the same quiet ticks that only an added chunk restarts: it adds up the game's
// increments, starts again from the game's value when a chunk was added or after half a second without a call, and
// keeps its sum when the game's count falls back for a dropped chunk. While the game holds its counter at zero
// (streaming pending) nothing is added, so a slow start of the streaming still waits. Never less than the game's.
#if RT_PATCH_COUNT
#define HOST_CAVE_STABLE (RT_PATCH_PAGE + 0xf60)

static void cave_stable(Cpu *c) {
    static uint32_t prev_game, prev_chunks, count, logged;
    static uint64_t last_ns, first_ns;
    uint32_t game = *(const uint32_t *)(uintptr_t)c->x[10], chunks = (uint32_t)c->x[11];
    uint64_t now = plat_now_ns();
    if (now - last_ns > 500000000ull) count = game, first_ns = now, logged = 0;
    else if (chunks > prev_chunks) count = game;
    else if (game > prev_game) count += game - prev_game;
    if (count < game) count = game;
    // one line per wait that this shortened, as it ends (a loading screen is up)
    if (count > 30 && game <= 30 && !logged) {
        logged = 1;
        rt_log("cave wait: stable %.2f s after the wait began; the game's own count was at %u of 31 (%u chunks)",
               (double)(now - first_ns) / 1e9, game, chunks);
    }
    prev_game = game, prev_chunks = chunks, last_ns = now;
    c->x[10] = count;
}

__attribute__((constructor)) static void cave_stable_register(void) { rt_register_host(HOST_CAVE_STABLE, cave_stable); }
#endif
