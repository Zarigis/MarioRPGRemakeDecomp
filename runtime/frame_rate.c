// Frame rate: the frame limit, and the game clock that input scripts and measurements run on.
// The limit's parsing and the pacing model are adapted from MacNativeGames games/totk/runtime/game_patches.c @ ebe621d
// (MIT, Copyright (c) 2026 MacNativeGames contributors).
//
// The game is a Unity player: every frame it reads the clock and steps its world by the time that passed
// (Time.deltaTime), and it waits for the display only inside nvnWindowAcquireTexture and nvnQueuePresentTexture. So
// the frame rate is whatever the present pacer allows (nvn_api_obj.c, present_period), and no game code is patched:
// on the console the pacer's tick is the 60 Hz vblank, here it is the frame limit. The game's present interval still
// counts ticks, so a scene the game runs at interval 2 (half rate) runs at half the limit.
//
// The limit (MRPG_FPS_LIMIT, live): 30 to 240 per second, or "display" for the refresh rate of the window's monitor.
// The vsync event stays at 60 Hz whatever the limit (gfx_vsync_bind): the player does not wait for it each frame.
//
// What a higher rate does not change: animation and movement that the game steps by elapsed time. What it does change
// is anything the game counts in frames, and battles are that: at a limit of 120 a battle ran at twice its speed. The
// game says so itself. Battle.BattleManager.set_frame_rate (main+0x1cd0500, version 1.0.1) is called with 60 or 30,
// keeps the number in the manager's _frame_rate (+0x1c8) and sets Unity's vSyncCount to 1 or 2: so many 60 Hz vblanks
// per frame; reset_frame_rate (main+0x1cd0580) puts 0 back. While that field is not 0 the pacer's tick is the
// console's 1/60 s whatever the limit (frame_step_tick_ns), so frame-counted scenes keep their speed and the limit
// applies to the rest of the game. The field is read from the game's memory at each present (locked_read): the
// manager's class through the pointer at main+0x3a57e48 (as its get_instance does, main+0x1cd11c0), the class's
// static fields at +0xb8, the instance at +0x10 of those.
// Other frame-counted code may exist outside battles; it has to be found by playing.
//
// The game clock (frame_step_ticks) advances by the pacer's nominal period per present, not by
// the measured time: at the default limit of 60 a present is exactly one tick, so recorded input replays on the same
// frames, and at another limit a script's tick numbers still mean sixtieths of a second of game time.
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "gfx.h"
#include "host.h"
#include "layout.h"
#include "platform/platform.h"

#define LIMIT_MIN_HZ 30
#define LIMIT_MAX_HZ 240

static unsigned limit_seen;
static int limit_read;
static int limit_hz = -1;   // 0: display; -1 before the first read

static int limit_parse(void) {
    const char *e = cfg_get("MRPG_FPS_LIMIT");
    if (!e || !*e) return 60;
    if (!strcmp(e, "display")) return 0;
    char *end;
    long n = strtol(e, &end, 10);
    if (!*end && n > LIMIT_MAX_HZ) {
        rt_log("frame rate: MRPG_FPS_LIMIT=%s is above %d; %d", e, LIMIT_MAX_HZ, LIMIT_MAX_HZ);
        return LIMIT_MAX_HZ;
    }
    if (!*end && n >= LIMIT_MIN_HZ) return (int)n;
    rt_log("frame rate: MRPG_FPS_LIMIT=%s is not %d..%d or display; 60", e, LIMIT_MIN_HZ, LIMIT_MAX_HZ);
    return 60;
}

static void frame_limit_live(void) {
    unsigned v = cfg_version();
    if (limit_read && v == limit_seen) return;
    limit_read = 1;
    limit_seen = v;
    int hz = limit_parse();
    if (hz == limit_hz) return;
    limit_hz = hz;
    if (hz) rt_log("frame rate: limit %d fps", hz);
    else if (gfx_window_refresh_hz() > 0) rt_log("frame rate: limit at the monitor's refresh rate (%.3f Hz now)", gfx_window_refresh_hz());
    else rt_log("frame rate: limit at the monitor's refresh rate (60 until the window measures it)");
}

void frame_step_init(void) { frame_limit_live(); }

// No patched frame step in this game (the TotK code base's real-time step): callers that ask take the plain path.
int frame_step_realtime(void) { return 0; }

// The frame limit's period in ns.
static uint64_t frame_step_cap_ns(void) {
    frame_limit_live();
    double hz = limit_hz ? limit_hz : gfx_window_refresh_hz();
    if (hz < LIMIT_MIN_HZ) hz = 60;   // display rate unknown (no window yet)
    if (hz > LIMIT_MAX_HZ) hz = LIMIT_MAX_HZ;
    return (uint64_t)(1e9 / hz + 0.5);
}

// The frame rate the limit gives, for the performance overlay; 0 before the first frame read the setting.
double frame_step_limit_hz(void) {
    int hz = limit_hz;
    if (hz < 0) return 0;
    double r = hz ? hz : gfx_window_refresh_hz();
    if (r < LIMIT_MIN_HZ) r = 60;
    return r > LIMIT_MAX_HZ ? LIMIT_MAX_HZ : r;
}

// ---- scenes the game runs at a fixed rate (the comment at the top)
#define VBLANK_NS 16666667ull
static _Atomic int locked;

static void locked_read(void) {
    uint64_t slot = 0, klass = 0, statics = 0, inst = 0;
    int32_t rate = 0;
    int on = plat_mem_read(MOD_MAIN_BASE + 0x3a57e48, &slot, 8) && slot && !(slot & 7) && plat_mem_read(slot, &klass, 8) &&
             klass > 0x10000 && !(klass & 7) && plat_mem_read(klass + 0xb8, &statics, 8) && statics > 0x10000 &&
             !(statics & 7) && plat_mem_read(statics + 0x10, &inst, 8) && inst > 0x10000 && !(inst & 7) &&
             plat_mem_read(inst + 0x1c8, &rate, 4) && (rate == 30 || rate == 60);
    if (on != atomic_load_explicit(&locked, memory_order_relaxed)) {
        atomic_store_explicit(&locked, on, memory_order_relaxed);
        if (frame_step_cap_ns() != VBLANK_NS)
            rt_log("frame rate: %s", on ? "the game asks for a fixed rate (a battle): 60 Hz ticks until it ends"
                                        : "the fixed-rate scene ended: back to the frame limit");
    }
}

// One pacer tick in ns: a frame with present interval 1 lasts this long.
uint64_t frame_step_tick_ns(void) {
    return atomic_load_explicit(&locked, memory_order_relaxed) ? VBLANK_NS : frame_step_cap_ns();
}

// ---- MRPG_TRACE=perf: a line per 120 presents
static uint64_t win_t0, win_frames, win_hist[4];   // win_hist: frames by present interval 1, 2, 3+ ([0] unused)

static void speed_report(uint64_t now, int interval) {
    if (!win_t0) {
        win_t0 = now;
        return;
    }
    win_frames++;
    win_hist[interval < 1 ? 1 : interval > 3 ? 3 : interval]++;
    if (win_frames < 120) return;
    double wall = (double)(now - win_t0) * 1e-9;
    rt_log("fps: %llu frames in %.3f s (%.1f fps); interval 1/2/3+ %llu/%llu/%llu", (unsigned long long)win_frames, wall,
           (double)win_frames / wall, (unsigned long long)win_hist[1], (unsigned long long)win_hist[2],
           (unsigned long long)win_hist[3]);
    win_t0 = now;
    win_frames = 0;
    memset(win_hist, 0, sizeof win_hist);
}

static _Atomic uint64_t game_ns;   // game time since the first present: the nominal periods summed

// The world clock of the TotK code base started at the end of the first save load, found through that game's player
// actor. This game has no such point the host knows, so the clock never starts: input scripts and recordings stay on
// ticks, and measurements that ask for world-clock seconds fall back to presents.
int64_t frame_step_world_us(void) { return -1; }
uint64_t frame_step_ticks(void) { return atomic_load_explicit(&game_ns, memory_order_relaxed) * 60 / 1000000000ull; }

void frame_step_present(uint64_t display_ns, int interval) {
    locked_read();
    uint64_t step = frame_step_tick_ns() * (uint64_t)(interval > 0 ? interval : 1);
    atomic_store_explicit(&game_ns, atomic_load_explicit(&game_ns, memory_order_relaxed) + step, memory_order_relaxed);
    if (rt_trace & RT_TRACE_PERF) speed_report(display_ns, interval);
}
