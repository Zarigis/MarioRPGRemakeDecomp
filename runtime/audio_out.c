// nn::audio::AudioOut on the host: the raw PCM output a game's own mixer (here CRI's, inside a Unity player) feeds
// with buffers, as opposed to the audio renderer (audren.c). The SDK's functions are replaced at the nn::audio level;
// the system service behind them (audout:u) is not run.
//
// An appended buffer is copied into an SDL audio stream at once. A buffer counts as played, and is handed back by
// GetReleasedAudioOutBuffer, once the stream has consumed every byte up to its end; a host thread watches that and
// signals the game's buffer event. Without an audio device the same bookkeeping runs against the clock, so the
// game's sound thread keeps its pace.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <SDL3/SDL.h>

#include "host.h"
#include "platform/platform.h"

enum { MAX_OUTS = 4, MAX_QUEUED = 128, STATE_STARTED = 0, STATE_STOPPED = 1, FORMAT_PCM_INT16 = 2 };

// nn::audio::AudioOutBuffer as the SDK's accessors read it (SetAudioOutBufferInfo, GetAudioOutBufferDataPointer,
// GetAudioOutBufferDataSize).
typedef struct { uint64_t reserved; uint64_t data, buffer_size, data_size; } OutBuffer;
// nn::audio::AudioOutParameter: InitializeAudioOutParameter writes {0, 0, 0xCAFE}; 0 asks for the default.
typedef struct { int32_t rate; uint16_t channels, magic; } OutParameter;

typedef struct {
    uint64_t guest;                 // the game's AudioOut object, 0 = free
    uint64_t event;                 // nn::os::SystemEvent signalled when a buffer is played, 0 = none
    int rate, channels, state;
    SDL_AudioStream *stream;        // NULL without a device
    uint64_t appended;              // bytes handed over since the last start
    uint64_t clock_start;           // without a device: when the first of them was appended
    struct { uint64_t guest, end; } q[MAX_QUEUED];   // appended and not yet handed back, oldest first; end: the
    int head, count;                                 // value of `appended` after it
    int ready;                      // of those, how many are played
} Out;

static Out outs[MAX_OUTS];
static PlatMutex lock = PLAT_MUTEX_INIT;
static volatile int32_t watcher_started;

static Out *find(uint64_t guest) {
    for (int i = 0; i < MAX_OUTS; i++)
        if (guest && outs[i].guest == guest) return &outs[i];
    return NULL;
}

static Out *need(Cpu *c, const char *fn) {
    Out *o = find(arg_x(c, 0));
    if (!o) rt_fatal("nn::audio::%s: %#llx is not an open AudioOut", fn, (unsigned long long)arg_x(c, 0));
    return o;
}

// Bytes of the appended data the output has taken (under lock).
static uint64_t consumed(const Out *o) {
    if (o->state != STATE_STARTED) return o->appended;   // stopped: everything comes back
    if (o->stream) {
        int queued = SDL_GetAudioStreamQueued(o->stream);
        return queued < 0 || (uint64_t)queued > o->appended ? 0 : o->appended - (uint64_t)queued;
    }
    if (!o->count) return o->appended;
    uint64_t played = (plat_now_ns() - o->clock_start) / 1000 * (uint64_t)o->rate / 1000000 * 2 * (uint64_t)o->channels;
    return played > o->appended ? o->appended : played;
}

// Counts the buffers played since the last look; returns how many became ready (under lock).
static int advance(Out *o) {
    uint64_t done = consumed(o);
    int fresh = 0;
    while (o->ready < o->count && o->q[(o->head + o->ready) % MAX_QUEUED].end <= done) o->ready++, fresh++;
    return fresh;
}

static void watcher(void *arg) {
    (void)arg;
    for (;;) {
        uint64_t signal[MAX_OUTS];
        int n = 0;
        plat_mutex_lock(&lock);
        for (int i = 0; i < MAX_OUTS; i++)
            if (outs[i].guest && advance(&outs[i]) && outs[i].event) signal[n++] = outs[i].event;
        plat_mutex_unlock(&lock);
        for (int i = 0; i < n; i++) kern_signal_system_event(signal[i]);
        plat_wait_ns(1000000);
    }
}

// Result OpenDefaultAudioOut(AudioOut *out, nn::os::SystemEvent *event, const AudioOutParameter &param) and the form
// without the event.
static void open_out(Cpu *c, uint64_t event, const OutParameter *p) {
    uint64_t guest = arg_x(c, 0);
    if (!guest || !p) rt_fatal("nn::audio::OpenDefaultAudioOut: null argument");
    int rate = p->rate > 0 ? p->rate : 48000, channels = p->channels ? p->channels : 2;
    if (event) kern_bind_system_event(c, event, 1);
    plat_mutex_lock(&lock);
    Out *o = find(guest);
    for (int i = 0; i < MAX_OUTS && !o; i++)
        if (!outs[i].guest) o = &outs[i];
    if (!o) rt_fatal("nn::audio::OpenDefaultAudioOut: more than %d outputs", MAX_OUTS);
    *o = (Out){.guest = guest, .event = event, .rate = rate, .channels = channels, .state = STATE_STOPPED};
    if (SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        SDL_AudioSpec spec = {SDL_AUDIO_S16LE, channels, rate};
        o->stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, NULL, NULL);
    }
    plat_mutex_unlock(&lock);
    rt_log("audio out: opened, %d Hz, %d channels, 16-bit%s", rate, channels,
           o->stream ? "" : " (no output device: silent, paced by the clock)");
    if (!plat_xchg32(&watcher_started, 1) && !plat_thread_spawn(watcher, NULL, "audio out", 1 << 16))
        rt_fatal("audio out: cannot start the buffer watcher thread");
    ret_x(c, 0);
}
static void ov_open_event(Cpu *c) { open_out(c, arg_x(c, 1), arg_p(c, 2)); }
static void ov_open(Cpu *c) { open_out(c, 0, arg_p(c, 1)); }

// Result StartAudioOut(AudioOut *out)
static void ov_start(Cpu *c) {
    plat_mutex_lock(&lock);
    Out *o = need(c, "StartAudioOut");
    o->state = STATE_STARTED;
    o->clock_start = plat_now_ns();
    if (o->stream) SDL_ResumeAudioStreamDevice(o->stream);
    plat_mutex_unlock(&lock);
    ret_x(c, 0);
}

// void StopAudioOut(AudioOut *out): what is queued is dropped and every buffer comes back
static void ov_stop(Cpu *c) {
    plat_mutex_lock(&lock);
    Out *o = need(c, "StopAudioOut");
    o->state = STATE_STOPPED;
    if (o->stream) {
        SDL_PauseAudioStreamDevice(o->stream);
        SDL_ClearAudioStream(o->stream);
    }
    advance(o);
    plat_mutex_unlock(&lock);
}

// void CloseAudioOut(AudioOut *out)
static void ov_close(Cpu *c) {
    plat_mutex_lock(&lock);
    Out *o = need(c, "CloseAudioOut");
    if (o->stream) SDL_DestroyAudioStream(o->stream);
    *o = (Out){0};
    plat_mutex_unlock(&lock);
}

// bool AppendAudioOutBuffer(AudioOut *out, AudioOutBuffer *buffer)
static void ov_append(Cpu *c) {
    const OutBuffer *b = arg_p(c, 1);
    if (!b) rt_fatal("nn::audio::AppendAudioOutBuffer: null buffer");
    plat_mutex_lock(&lock);
    Out *o = need(c, "AppendAudioOutBuffer");
    int ok = o->count < MAX_QUEUED;
    if (ok) {
        if (!o->count) o->clock_start = plat_now_ns() - o->appended * 1000000000ull / ((uint64_t)o->rate * 2 * (uint64_t)o->channels);
        if (o->stream && b->data && b->data_size)
            SDL_PutAudioStreamData(o->stream, (const void *)(uintptr_t)b->data, (int)b->data_size);
        o->appended += b->data_size;
        o->q[(o->head + o->count++) % MAX_QUEUED] = (typeof(o->q[0])){arg_x(c, 1), o->appended};
    }
    plat_mutex_unlock(&lock);
    ret_x(c, (uint64_t)ok);
}

// AudioOutBuffer *GetReleasedAudioOutBuffer(AudioOut *out): the oldest played buffer, NULL if none
static void ov_released(Cpu *c) {
    plat_mutex_lock(&lock);
    Out *o = need(c, "GetReleasedAudioOutBuffer");
    advance(o);
    uint64_t b = 0;
    if (o->ready) {
        b = o->q[o->head].guest;
        o->head = (o->head + 1) % MAX_QUEUED;
        o->count--, o->ready--;
    }
    plat_mutex_unlock(&lock);
    ret_x(c, b);
}

#define GETTER(id, fn, field)                                                                                     \
    static void id(Cpu *c) {                                                                                      \
        plat_mutex_lock(&lock);                                                                                   \
        uint64_t v = (uint64_t)need(c, fn)->field;                                                                \
        plat_mutex_unlock(&lock);                                                                                 \
        ret_x(c, v);                                                                                              \
    }
GETTER(ov_state, "GetAudioOutState", state)
GETTER(ov_rate, "GetAudioOutSampleRate", rate)
GETTER(ov_channels, "GetAudioOutChannelCount", channels)
static void ov_format(Cpu *c) { ret_x(c, FORMAT_PCM_INT16); }

// int ListAudioOuts(AudioOutInfo *out, int count): the one default output. AudioOutInfo is its name, char[256].
static void ov_list(Cpu *c) {
    if (!arg_p(c, 0) || (int32_t)arg_x(c, 1) <= 0) { ret_x(c, 0); return; }
    memset(arg_p(c, 0), 0, 256);
    strcpy(arg_p(c, 0), "DeviceOut");
    ret_x(c, 1);
}

// ---- the audio device calls beside it (nn::audio::AudioDeviceName is char[256]): one stereo device
static void device_name(void *out) {
    if (!out) return;
    memset(out, 0, 256);
    strcpy(out, "AudioTvOutput");
}
// int ListAudioDeviceName(AudioDeviceName *out, int count)
static void ov_device_list(Cpu *c) {
    if ((int32_t)arg_x(c, 1) <= 0) { ret_x(c, 0); return; }
    device_name(arg_p(c, 0));
    ret_x(c, 1);
}
// void GetActiveAudioDeviceName(AudioDeviceName *out)
static void ov_device_active(Cpu *c) { device_name(arg_p(c, 0)); }
// void SetAudioDeviceOutputVolume(const AudioDeviceName *, float)
static void ov_device_volume(Cpu *c) { (void)c; }
// Result AcquireAudioDeviceNotificationForOutput(nn::os::SystemEvent *event): the device never changes
static void ov_device_event(Cpu *c) {
    kern_bind_system_event(c, arg_x(c, 0), 1);
    ret_x(c, 0);
}
// int GetActiveAudioDeviceChannelCountForOutput()
static void ov_device_channels(Cpu *c) { ret_x(c, 2); }

HOST_OVERRIDE("_ZN2nn5audio19OpenDefaultAudioOutEPNS0_8AudioOutEPNS_2os11SystemEventERKNS0_17AudioOutParameterE", ov_open_event);
HOST_OVERRIDE("_ZN2nn5audio19OpenDefaultAudioOutEPNS0_8AudioOutERKNS0_17AudioOutParameterE", ov_open);
HOST_OVERRIDE("_ZN2nn5audio13StartAudioOutEPNS0_8AudioOutE", ov_start);
HOST_OVERRIDE("_ZN2nn5audio12StopAudioOutEPNS0_8AudioOutE", ov_stop);
HOST_OVERRIDE("_ZN2nn5audio13CloseAudioOutEPNS0_8AudioOutE", ov_close);
HOST_OVERRIDE("_ZN2nn5audio20AppendAudioOutBufferEPNS0_8AudioOutEPNS0_14AudioOutBufferE", ov_append);
HOST_OVERRIDE("_ZN2nn5audio25GetReleasedAudioOutBufferEPNS0_8AudioOutE", ov_released);
HOST_OVERRIDE("_ZN2nn5audio16GetAudioOutStateEPKNS0_8AudioOutE", ov_state);
HOST_OVERRIDE("_ZN2nn5audio21GetAudioOutSampleRateEPKNS0_8AudioOutE", ov_rate);
HOST_OVERRIDE("_ZN2nn5audio23GetAudioOutChannelCountEPKNS0_8AudioOutE", ov_channels);
HOST_OVERRIDE("_ZN2nn5audio23GetAudioOutSampleFormatEPKNS0_8AudioOutE", ov_format);
HOST_OVERRIDE("_ZN2nn5audio13ListAudioOutsEPNS0_12AudioOutInfoEi", ov_list);
HOST_OVERRIDE("_ZN2nn5audio19ListAudioDeviceNameEPNS0_15AudioDeviceNameEi", ov_device_list);
HOST_OVERRIDE("_ZN2nn5audio24GetActiveAudioDeviceNameEPNS0_15AudioDeviceNameE", ov_device_active);
HOST_OVERRIDE("_ZN2nn5audio26SetAudioDeviceOutputVolumeEPKNS0_15AudioDeviceNameEf", ov_device_volume);
HOST_OVERRIDE("_ZN2nn5audio39AcquireAudioDeviceNotificationForOutputEPNS_2os11SystemEventE", ov_device_event);
HOST_OVERRIDE("_ZN2nn5audio41GetActiveAudioDeviceChannelCountForOutputEv", ov_device_channels);
