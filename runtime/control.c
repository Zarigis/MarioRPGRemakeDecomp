// The control port: a program outside the game pauses it, plays it in turns and looks at its picture. Off unless
// MRPG_CONTROL=<port> is set; then a thread listens on 127.0.0.1:<port>. tools/mcp/ is the client.
//
// A connection carries one command line and gets one line of JSON back:
//   status                        the state (running, turn, paused), the present count and the turn's progress
//   pause [timeout ms]            freezes the guest at the next present; without a present in time, at once
//   resume                        lets the guest run on; drops a turn in progress
//   turn <timeout ms> <n> {<frames> <buttons hex> <lx> <ly> <rx> <ry>} x n
//                                 from any state: runs n steps, each holding its buttons (bits of input_map.h B_*) and
//                                 sticks (-32767..32767, up is +y) for <frames> presents, then freezes the guest again.
//                                 Answers when the turn ended or after the timeout; the turn goes on either way
//   wait <timeout ms>             answers when the guest is paused, or after the timeout
//   shot <w> <h> <path>           writes the frame kept at the last pause as a PNG of w x h; while the guest runs, the
//                                 next present's frame instead
//   record <every> <w> <h> <dir>  from now on every <every>-th present is written to <dir>/f<present>.png at w x h
//                                 (every 1: each frame between two pauses); `record 0` ends it. It slows the game
//                                 down by a read-back and a PNG per recorded frame, but game time is counted in
//                                 frames by `turn`, so a recorded turn covers the same frames as an unrecorded one
//   quit                          saves and ends the process
//
// A pause is kern_freeze (kernel.c): every guest thread stops at its next checkpoint and the guest clock stands still,
// so the game sees no time pass. It starts in control_frame, on the presenting thread, right after a present, so a turn
// is a whole number of frames; the frame just presented is read back there and kept for `shot`.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
typedef SOCKET sock_t;
#define sock_close closesocket
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
typedef int sock_t;
#define sock_close close
#define INVALID_SOCKET (-1)
#endif

#include "cfg.h"
#include "fs.h"
#include "gfx.h"
#include "host.h"
#include "nvn_api.h"
#include "platform/platform.h"
#include "vk.h"

enum { RUNNING, TURN, PAUSED };
enum { MAX_STEPS = 256 };
typedef struct { uint32_t frames; uint64_t buttons; int32_t l[2], r[2]; } Step;

static int g_on;
static PlatMutex M = PLAT_MUTEX_INIT;
static PlatCond CV;
static int state = RUNNING, pause_req, shot_req, forced;
static Step steps[MAX_STEPS];
static int nsteps, cur;
static uint32_t left;
static uint64_t frame, turns;
static uint8_t *shot_px;              // RGBA of the frame kept at the last pause or shot request
static uint32_t shot_w, shot_h;
static uint64_t shot_frame;
static uint32_t rec_every, rec_w, rec_h;   // record: every rec_every-th present goes to rec_dir
static uint64_t rec_count, rec_first, rec_last;
static char rec_dir[PLAT_PATH_MAX];
static int write_shot(const char *path, uint32_t ow, uint32_t oh);
// The input of the step being played, read by control_input on the thread that polls the pad.
static uint64_t in_buttons;
static int32_t in_axes[4];

static void set_input(const Step *s) {
    __atomic_store_n(&in_buttons, s ? s->buttons : 0, __ATOMIC_RELAXED);
    for (int i = 0; i < 4; i++)
        __atomic_store_n(&in_axes[i], s ? (i < 2 ? s->l[i] : s->r[i - 2]) : 0, __ATOMIC_RELAXED);
}

void control_input(uint64_t *buttons, int32_t sl[2], int32_t sr[2]) {
    if (!g_on) return;
    *buttons |= __atomic_load_n(&in_buttons, __ATOMIC_RELAXED);
    int32_t a[4];
    for (int i = 0; i < 4; i++) a[i] = __atomic_load_n(&in_axes[i], __ATOMIC_RELAXED);
    if (a[0] | a[1]) sl[0] = a[0], sl[1] = a[1];
    if (a[2] | a[3]) sr[0] = a[2], sr[1] = a[3];
}

// Reads the presented texture back as RGBA, on the presenting thread (as series_shot in boot.c).
static void capture(const tex_t *t, uint64_t n) {
    int fmt = t->d.format;
    int bgra = fmt == NVN_FORMAT_BGRA8 || fmt == NVN_FORMAT_BGRA8_SRGB;
    if (!bgra && fmt != NVN_FORMAT_RGBA8 && fmt != NVN_FORMAT_RGBA8_SRGB) return;
    uint32_t w = t->d.width, h = t->d.height;
    if (w != shot_w || h != shot_h || !shot_px) {
        free(shot_px);
        shot_px = malloc(4ull * w * h);
        if (!shot_px) rt_fatal("control: out of memory for a frame");
        shot_w = w, shot_h = h;
    }
    view_t view;
    memset(&view, 0, sizeof view);
    NVNcopyRegion r = {.width = (int)w, .height = (int)h, .depth = 1};
    if (gfx_replay_async()) gfx_backend()->finish();   // the presented frame may still be queued for the replay
    gfx_backend()->read_texels(t, &view, &r, shot_px, 4ull * w, 4ull * w * h);
    for (uint64_t i = 0; i < 4ull * w * h; i += 4) {
        if (bgra) {
            uint8_t x = shot_px[i];
            shot_px[i] = shot_px[i + 2], shot_px[i + 2] = x;
        }
        shot_px[i + 3] = 255;
    }
    shot_frame = n;
}

void control_frame(const void *tex, uint64_t n) {
    if (!g_on) return;
    plat_mutex_lock(&M);
    frame = n;
    int stop = 0;
    if (state == TURN && left && !--left) {
        if (++cur < nsteps) left = steps[cur].frames, set_input(&steps[cur]);
        else stop = 1;
    }
    if (pause_req && state != PAUSED) stop = 1;
    int rec = rec_every && n % rec_every == 0;
    if (stop || shot_req || rec) capture(tex, n);
    shot_req = 0;
    if (rec && shot_frame == n) {
        char path[PLAT_PATH_MAX + 32];
        snprintf(path, sizeof path, "%s/f%07llu.png", rec_dir, (unsigned long long)n);
        if (write_shot(path, rec_w, rec_h)) {
            if (!rec_count++) rec_first = n;
            rec_last = n;
        }
    }
    if (stop) {
        set_input(NULL);
        pause_req = 0, forced = 0;
        state = PAUSED;
        kern_freeze(1);   // this thread stops at its next checkpoint, the others at theirs
    }
    plat_cond_broadcast(&CV);
    plat_mutex_unlock(&M);
}

// ---- commands, on the server thread

static uint64_t now_ms(void) { return plat_now_ns() / 1000000; }

// Holding M: waits until the guest is paused, at most ms. 1 when it is.
static int wait_paused(uint64_t ms) {
    uint64_t end = now_ms() + ms;
    while (state != PAUSED) {
        uint64_t now = now_ms();
        if (now >= end) return 0;
        plat_cond_wait_ns(&CV, &M, (end - now) * 1000000);
    }
    return 1;
}

static void status(char *out, size_t cap, const char *extra) {
    snprintf(out, cap, "{\"ok\":1,\"state\":\"%s\",\"frame\":%llu,\"tick\":%llu,\"turns\":%llu,\"step\":%d,\"steps\":%d,"
             "\"frames_left\":%u,\"forced\":%d,\"shot_frame\":%llu,\"shot_size\":[%u,%u],\"record_every\":%u,"
             "\"recorded\":%llu,\"recorded_first\":%llu,\"recorded_last\":%llu%s}\n",
             state == PAUSED ? "paused" : state == TURN ? "turn" : "running", (unsigned long long)frame,
             (unsigned long long)frame_step_ticks(), (unsigned long long)turns, state == TURN ? cur : 0,
             state == TURN ? nsteps : 0, state == TURN ? left : 0, forced, (unsigned long long)shot_frame, shot_w, shot_h,
             rec_every, (unsigned long long)rec_count, (unsigned long long)rec_first, (unsigned long long)rec_last,
             extra ? extra : "");
}

static void fail(char *out, size_t cap, const char *why) { snprintf(out, cap, "{\"ok\":0,\"error\":\"%s\"}\n", why); }

// The kept frame box-filtered to ow x oh, as a PNG.
static int write_shot(const char *path, uint32_t ow, uint32_t oh) {
    if (!shot_px) return 0;
    uint32_t w = shot_w, h = shot_h;
    if (!ow || !oh || ow > w || oh > h) ow = w, oh = h;
    uint8_t *o = malloc(4ull * ow * oh);
    if (!o) return 0;
    for (uint32_t y = 0; y < oh; y++)
        for (uint32_t x = 0; x < ow; x++) {
            uint32_t x0 = x * w / ow, x1 = (x + 1) * w / ow, y0 = y * h / oh, y1 = (y + 1) * h / oh;
            if (x1 <= x0) x1 = x0 + 1;
            if (y1 <= y0) y1 = y0 + 1;
            uint32_t sum[4] = {0}, k = 0;
            for (uint32_t sy = y0; sy < y1; sy++)
                for (uint32_t sx = x0; sx < x1; sx++, k++)
                    for (int c = 0; c < 4; c++) sum[c] += shot_px[4ull * (sy * (uint64_t)w + sx) + (uint32_t)c];
            for (int c = 0; c < 4; c++) o[4ull * (y * ow + x) + (uint32_t)c] = (uint8_t)(sum[c] / k);
        }
    rt_write_png(path, o, ow, oh);
    free(o);
    return 1;
}

static void command(char *line, char *out, size_t cap) {
    char cmd[16] = "";
    int off = 0;
    sscanf(line, "%15s%n", cmd, &off);
    char *args = line + off;
    plat_mutex_lock(&M);
    if (!strcmp(cmd, "status")) {
        status(out, cap, NULL);
    } else if (!strcmp(cmd, "pause")) {
        unsigned long ms = 2000;
        sscanf(args, "%lu", &ms);
        if (state != PAUSED) {
            pause_req = 1;
            if (!wait_paused(ms)) {   // nothing is presented (a load, a hang): freeze where the guest is
                pause_req = 0, forced = 1;
                set_input(NULL);
                state = PAUSED;
                kern_freeze(1);
            }
        }
        status(out, cap, NULL);
    } else if (!strcmp(cmd, "resume")) {
        set_input(NULL);
        state = RUNNING, pause_req = 0, forced = 0;
        kern_freeze(0);
        status(out, cap, NULL);
    } else if (!strcmp(cmd, "turn")) {
        unsigned long ms = 0;
        int n = 0, k = 0;
        if (sscanf(args, "%lu %d%n", &ms, &n, &k) < 2 || n < 1 || n > MAX_STEPS) {
            fail(out, cap, "turn <timeout ms> <n> then n steps of <frames> <buttons hex> <lx> <ly> <rx> <ry>");
        } else {
            Step tmp[MAX_STEPS];
            int ok = 1;
            args += k;
            for (int i = 0; i < n && ok; i++) {
                unsigned long fr;
                unsigned long long b;
                long a[4];
                ok = sscanf(args, "%lu %llx %ld %ld %ld %ld%n", &fr, &b, &a[0], &a[1], &a[2], &a[3], &k) >= 6 && fr > 0;
                args += k;
                tmp[i] = (Step){(uint32_t)fr, b, {(int32_t)a[0], (int32_t)a[1]}, {(int32_t)a[2], (int32_t)a[3]}};
            }
            if (!ok) {
                fail(out, cap, "a step is <frames above 0> <buttons hex> <lx> <ly> <rx> <ry>");
            } else {
                memcpy(steps, tmp, (size_t)n * sizeof *tmp);
                nsteps = n, cur = 0, left = steps[0].frames;
                set_input(&steps[0]);
                pause_req = 0, forced = 0;
                state = TURN;
                turns++;
                kern_freeze(0);
                int done = wait_paused(ms);
                status(out, cap, done ? ",\"done\":1" : ",\"done\":0");
            }
        }
    } else if (!strcmp(cmd, "wait")) {
        unsigned long ms = 1000;
        sscanf(args, "%lu", &ms);
        int done = wait_paused(ms);
        status(out, cap, done ? ",\"done\":1" : ",\"done\":0");
    } else if (!strcmp(cmd, "shot")) {
        unsigned w = 0, h = 0;
        int k = 0;
        if (sscanf(args, "%u %u %n", &w, &h, &k) < 2 || !args[k]) {
            fail(out, cap, "shot <w> <h> <path>");
        } else {
            if (state != PAUSED) {   // the next present's frame
                uint64_t before = shot_frame, end = now_ms() + 2000;
                shot_req = 1;
                while (shot_frame == before && shot_req && now_ms() < end) plat_cond_wait_ns(&CV, &M, 100000000);
                shot_req = 0;
            }
            if (write_shot(args + k, w, h)) status(out, cap, NULL);
            else fail(out, cap, "no frame was kept yet");
        }
    } else if (!strcmp(cmd, "record")) {
        unsigned every = 0, w = 0, h = 0;
        int k = 0, got = sscanf(args, "%u %u %u %n", &every, &w, &h, &k);
        if (got < 1 || (every && (got < 3 || !args[k] || strlen(args + k) >= sizeof rec_dir))) {
            fail(out, cap, "record <every> <w> <h> <dir>, or record 0");
        } else {
            rec_every = every, rec_count = rec_first = rec_last = 0;
            if (every) {
                rec_w = w, rec_h = h;
                snprintf(rec_dir, sizeof rec_dir, "%s", args + k);
                plat_file_mkdir_p(rec_dir);
            }
            status(out, cap, NULL);
        }
    } else if (!strcmp(cmd, "quit")) {
        rt_log("control: quit");
        fs_save_flush();
        plat_exit(0);
    } else {
        fail(out, cap, "unknown command; see runtime/control.c");
    }
    plat_mutex_unlock(&M);
}

static void server(void *arg) {
    sock_t ls = (sock_t)(uintptr_t)arg;
    for (;;) {
        sock_t s = accept(ls, NULL, NULL);
        if (s == INVALID_SOCKET) continue;
        char line[16384], out[1536];
        size_t n = 0;
        while (n < sizeof line - 1) {
            int k = recv(s, line + n, (int)(sizeof line - 1 - n), 0);
            if (k <= 0) break;
            n += (size_t)k;
            if (memchr(line, '\n', n)) break;
        }
        line[n] = 0;
        char *e = strpbrk(line, "\r\n");
        if (e) *e = 0;
        if (*line) {
            command(line, out, sizeof out);
            send(s, out, (int)strlen(out), 0);
        }
        sock_close(s);
    }
}

void control_init(void) {
    const char *e = cfg_get("MRPG_CONTROL");
    int port = e ? atoi(e) : 0;
    if (port <= 0 || port > 65535) return;
#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa)) { rt_log("control: no sockets"); return; }
#endif
    sock_t ls = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);   // this machine only
    if (ls == INVALID_SOCKET || bind(ls, (struct sockaddr *)&a, sizeof a) || listen(ls, 4)) {
        rt_log("control: cannot listen on 127.0.0.1:%d (in use by another instance?)", port);
        return;
    }
    plat_cond_init(&CV);
    g_on = 1;
    if (!plat_thread_new(server, (void *)(uintptr_t)ls, "control")) rt_fatal("control: no server thread");
    rt_log("control: listening on 127.0.0.1:%d", port);
}
