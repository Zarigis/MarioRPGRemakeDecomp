// Adapted from MacNativeGames games/totk/runtime/opus_codec.c @ b75be8cf (MIT, Copyright (c) 2026 MacNativeGames
// contributors).
// The hardware Opus decoder (nn::codec), decoded with libopus on the host. The software keyboard (nn::swkbd) is
// in swkbd_win.c.
#include <stdint.h>
#include <limits.h>
#include <stdlib.h>

#include <opus/opus.h>

#include "host.h"
#include "platform/platform.h"

#define CODEC_R_INVALID 0x1fcd1u   // MacNativeGames' "invalid argument" result for nn::codec
#define OPUS_WORK_SIZE 0x9000u     // what the game is told to reserve: libopus stereo decoder state (about 26 KiB) plus 4 KiB

// One record per initialised decoder object (the guest's HardwareOpusDecoderType). The registry lock only guards the
// list; a decoder's own lock serialises its libopus state, so different streams decode in parallel. Lock order:
// registry, then decoder (a caller takes the decoder lock before it drops the registry lock, so Finalize cannot free a
// decoder another thread is using).
typedef struct Decoder {
    uint64_t guest;
    OpusDecoder *dec;
    int rate, channels;
    PlatMutex use;
    struct Decoder *next;
} Decoder;
static Decoder *decoders;
static PlatMutex lock = PLAT_MUTEX_INIT;

static int valid_format(int rate, int channels) {
    return (rate == 48000 || rate == 24000 || rate == 16000 || rate == 12000 || rate == 8000) &&
           (channels == 1 || channels == 2);
}

// Returns the decoder with its use lock held.
static Decoder *acquire(uint64_t guest, const char *fn) {
    plat_mutex_lock_shared(&lock);
    Decoder *d = decoders;
    while (d && d->guest != guest) d = d->next;
    if (d) plat_mutex_lock(&d->use);
    plat_mutex_unlock_shared(&lock);
    if (!d) rt_fatal("nn::codec::%s: unknown hardware Opus decoder %#llx", fn, (unsigned long long)guest);
    return d;
}

static void release(Decoder *d) { plat_mutex_unlock(&d->use); }

static OpusDecoder *opus_new(int rate, int channels) {
    int err = 0;
    OpusDecoder *o = opus_decoder_create(rate, channels, &err);
    if (!o || err != OPUS_OK) rt_fatal("nn::codec: opus_decoder_create(%d, %d): %s", rate, channels, opus_strerror(err));
    return o;
}

// size_t GetHardwareOpusDecoderWorkBufferSize(int rate, int channels, int option)
static void ov_work_size(Cpu *c) {
    ret_x(c, valid_format((int)arg_x(c, 0), (int)arg_x(c, 1)) ? OPUS_WORK_SIZE : 0);
}

// Result InitializeHardwareOpusDecoder(HardwareOpusDecoderType *d, int rate, int channels, void *work, size_t size,
// int option). The state lives in libopus on the host; the guest's work buffer is reserved but unused. Initialising
// the same object again without Finalize replaces its decoder.
static void ov_initialize(Cpu *c) {
    uint64_t guest = arg_x(c, 0), size = arg_x(c, 4);
    int rate = (int)arg_x(c, 1), channels = (int)arg_x(c, 2);
    if (!guest || !valid_format(rate, channels) || size < OPUS_WORK_SIZE) { ret_x(c, CODEC_R_INVALID); return; }
    OpusDecoder *fresh = opus_new(rate, channels);
    plat_mutex_lock(&lock);
    Decoder *d = decoders;
    while (d && d->guest != guest) d = d->next;
    if (d) {
        plat_mutex_lock(&d->use);   // waits for a decode in flight
        OpusDecoder *old = d->dec;
        d->dec = fresh;
        d->rate = rate;
        d->channels = channels;
        plat_mutex_unlock(&d->use);
        plat_mutex_unlock(&lock);
        opus_decoder_destroy(old);
    } else {
        d = calloc(1, sizeof *d);
        if (!d) rt_fatal("nn::codec: decoder allocation");
        plat_mutex_init(&d->use);
        d->guest = guest;
        d->dec = fresh;
        d->rate = rate;
        d->channels = channels;
        d->next = decoders;
        decoders = d;
        plat_mutex_unlock(&lock);
    }
    ret_x(c, 0);
}

// void FinalizeHardwareOpusDecoder(HardwareOpusDecoderType *d)
static void ov_finalize(Cpu *c) {
    uint64_t guest = arg_x(c, 0);
    plat_mutex_lock(&lock);
    Decoder **p = &decoders;
    while (*p && (*p)->guest != guest) p = &(*p)->next;
    if (!*p) rt_fatal("nn::codec::FinalizeHardwareOpusDecoder: unknown decoder %#llx", (unsigned long long)guest);
    Decoder *d = *p;
    plat_mutex_lock(&d->use);   // a decode in flight finishes first; the registry lock keeps new ones out
    *p = d->next;
    plat_mutex_unlock(&lock);
    opus_decoder_destroy(d->dec);
    free(d);
}

// int GetHardwareOpusDecoderSampleRate / GetHardwareOpusDecoderChannelCount(const HardwareOpusDecoderType *d)
static void ov_sample_rate(Cpu *c) {
    Decoder *d = acquire(arg_x(c, 0), "GetHardwareOpusDecoderSampleRate");
    int v = d->rate;
    release(d);
    ret_x(c, (uint64_t)v);
}

static void ov_channel_count(Cpu *c) {
    Decoder *d = acquire(arg_x(c, 0), "GetHardwareOpusDecoderChannelCount");
    int v = d->channels;
    release(d);
    ret_x(c, (uint64_t)v);
}

// Result ResetHardwareOpusDecoder(HardwareOpusDecoderType *d)
static void ov_reset(Cpu *c) {
    Decoder *d = acquire(arg_x(c, 0), "ResetHardwareOpusDecoder");
    int ok = opus_decoder_ctl(d->dec, OPUS_RESET_STATE);
    release(d);
    ret_x(c, ok == OPUS_OK ? 0 : CODEC_R_INVALID);
}

static uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

// Result DecodeOpusInterleavedWithHardware(HardwareOpusDecoderType *d, size_t *consumed, int *samples, int16_t *out,
// size_t out_size, const void *in, size_t in_size). The input is Nintendo's frame: an 8-byte big-endian header
// {payload size, final range} and the Opus packet. A header range of 0 is not a recorded value (some encoders write 0
// into every packet), so it is not checked. A range mismatch is logged once and the samples are kept.
static void ov_decode(Cpu *c) {
    static int32_t warned;
    uint64_t guest = arg_x(c, 0), out_size = arg_x(c, 4), in_size = arg_x(c, 6);
    size_t *consumed = arg_p(c, 1);
    int *samples = arg_p(c, 2);
    int16_t *out = arg_p(c, 3);
    const uint8_t *in = arg_p(c, 5);
    if (!consumed || !samples || !out || !in || in_size < 8) { ret_x(c, CODEC_R_INVALID); return; }
    uint32_t n = be32(in), range = be32(in + 4);
    if (n > in_size - 8 || n > INT_MAX) { ret_x(c, CODEC_R_INVALID); return; }
    Decoder *d = acquire(guest, "DecodeOpusInterleavedWithHardware");
    size_t capacity = out_size / (sizeof(int16_t) * (size_t)d->channels);
    if (capacity > INT_MAX) { release(d); ret_x(c, CODEC_R_INVALID); return; }
    int got = opus_decode(d->dec, in + 8, (opus_int32)n, out, (int)capacity, 0);
    opus_uint32 final = 0;
    if (got >= 0) opus_decoder_ctl(d->dec, OPUS_GET_FINAL_RANGE(&final));
    release(d);
    if (got < 0) {
        rt_log("nn::codec: opus_decode: %s", opus_strerror(got));
        ret_x(c, CODEC_R_INVALID);
        return;
    }
    if (n && range && final != range && !plat_xchg32(&warned, 1))
        rt_log("nn::codec: Opus final range %#x != stream %#x (logged once)", (unsigned)final, (unsigned)range);
    *consumed = 8 + n;
    *samples = got;
    ret_x(c, 0);
}

HOST_OVERRIDE("_ZN2nn5codec36GetHardwareOpusDecoderWorkBufferSizeEiii", ov_work_size);
HOST_OVERRIDE("_ZN2nn5codec29InitializeHardwareOpusDecoderEPNS0_23HardwareOpusDecoderTypeEiiPvmi", ov_initialize);
HOST_OVERRIDE("_ZN2nn5codec27FinalizeHardwareOpusDecoderEPNS0_23HardwareOpusDecoderTypeE", ov_finalize);
HOST_OVERRIDE("_ZN2nn5codec32GetHardwareOpusDecoderSampleRateEPKNS0_23HardwareOpusDecoderTypeE", ov_sample_rate);
HOST_OVERRIDE("_ZN2nn5codec34GetHardwareOpusDecoderChannelCountEPKNS0_23HardwareOpusDecoderTypeE", ov_channel_count);
HOST_OVERRIDE("_ZN2nn5codec24ResetHardwareOpusDecoderEPNS0_23HardwareOpusDecoderTypeE", ov_reset);
HOST_OVERRIDE("_ZN2nn5codec33DecodeOpusInterleavedWithHardwareEPNS0_23HardwareOpusDecoderTypeEPmPiPsmPKvm", ov_decode);

// ---- the multi-stream decoder (5.1 music in a Unity player's sound middleware), on libopus' multistream decoder.
// HardwareOpusMultiStreamDecoderType as the SDK's accessors read it: +0 the decoder service object, +8 and +0x10 the
// work buffer and its size, +0x18 sample rate, +0x1c channels, +0x20 streams, +0x24 stereo streams, +0x28 the last
// decode's time, +0x30 a pending reset. The C++ class HardwareOpusMultiStreamDecoder keeps the type at this+8 and
// reads those fields itself, so Initialize fills them as the SDK does. Its Finalize releases the service object
// through the object's vtable instead of calling the C function: the object here is a stand-in at the start of the
// game's work buffer, whose vtable slots all lead to ms_object_call, and the work buffer's address names the decoder.
#include <string.h>

#include <opus/opus_multistream.h>

#define MS_WORK_SIZE 0x10000u
typedef struct MsDecoder {
    uint64_t object;   // the stand-in service object = the work buffer
    OpusMSDecoder *dec;
    int channels;
    PlatMutex use;
    struct MsDecoder *next;
} MsDecoder;
static MsDecoder *ms_decoders;
static uint64_t ms_object_fn;   // synthetic address of ms_object_call

static void ms_drop(uint64_t object, const char *who) {
    plat_mutex_lock(&lock);
    MsDecoder **p = &ms_decoders;
    while (*p && (*p)->object != object) p = &(*p)->next;
    MsDecoder *d = *p;
    if (d) {
        plat_mutex_lock(&d->use);
        *p = d->next;
    }
    plat_mutex_unlock(&lock);
    if (!d) rt_fatal("nn::codec::%s: unknown multi-stream decoder %#llx", who, (unsigned long long)object);
    opus_multistream_decoder_destroy(d->dec);
    free(d);
}

// Any virtual call on the stand-in object. The SDK only makes one: Release, from the class's Finalize.
static void ms_object_call(Cpu *c) {
    ms_drop(arg_x(c, 0), "HardwareOpusMultiStreamDecoder::Finalize");
    ret_x(c, 0);
}

__attribute__((constructor)) static void ms_register(void) {
    ms_object_fn = hostfn_register("nn::codec::detail::IHardwareOpusDecoder (host stand-in)", ms_object_call);
}

// size_t GetHardwareOpusMultiStreamDecoderWorkBufferSize(int rate, int channels, int streams, int stereo[, int option])
static void ov_ms_work_size(Cpu *c) { ret_x(c, MS_WORK_SIZE); }

// Result InitializeHardwareOpusMultiStreamDecoder(HardwareOpusMultiStreamDecoderType *d, int rate, int channels,
// int streams, int stereo_streams, const uint8_t *mapping, void *work, size_t work_size, int option)
static void ov_ms_initialize(Cpu *c) {
    uint64_t type = arg_x(c, 0), work = arg_x(c, 6), size = arg_x(c, 7);
    int rate = (int)arg_x(c, 1), channels = (int)arg_x(c, 2), streams = (int)arg_x(c, 3), stereo = (int)arg_x(c, 4);
    const uint8_t *mapping = arg_p(c, 5);
    if (!type || !work || !mapping || size < 0x80 || channels < 1 || channels > 255) { ret_x(c, CODEC_R_INVALID); return; }
    int err = 0;
    OpusMSDecoder *dec = opus_multistream_decoder_create(rate, channels, streams, stereo, mapping, &err);
    if (!dec || err != OPUS_OK) {
        rt_log("nn::codec: opus_multistream_decoder_create(%d Hz, %d channels, %d streams, %d stereo): %s", rate, channels,
               streams, stereo, opus_strerror(err));
        ret_x(c, CODEC_R_INVALID);
        return;
    }
    MsDecoder *d = calloc(1, sizeof *d);
    if (!d) rt_fatal("nn::codec: decoder allocation");
    plat_mutex_init(&d->use);
    d->object = work;
    d->dec = dec;
    d->channels = channels;
    // The stand-in object: its vtable pointer, then eight slots of the same host function.
    uint64_t *obj = (uint64_t *)(uintptr_t)work;
    obj[0] = work + 16;
    for (int i = 0; i < 8; i++) obj[2 + i] = ms_object_fn;
    uint8_t *t = (uint8_t *)(uintptr_t)type;
    memset(t, 0, 0x38);
    memcpy(t, &work, 8);
    memcpy(t + 8, &work, 8);
    memcpy(t + 0x10, &size, 8);
    memcpy(t + 0x18, &rate, 4);
    memcpy(t + 0x1c, &channels, 4);
    memcpy(t + 0x20, &streams, 4);
    memcpy(t + 0x24, &stereo, 4);
    plat_mutex_lock(&lock);
    d->next = ms_decoders;
    ms_decoders = d;
    plat_mutex_unlock(&lock);
    rt_log("nn::codec: multi-stream Opus decoder, %d Hz, %d channels, %d streams (%d stereo)", rate, channels, streams, stereo);
    ret_x(c, 0);
}

// void FinalizeHardwareOpusMultiStreamDecoder(HardwareOpusMultiStreamDecoderType *d)
static void ov_ms_finalize(Cpu *c) {
    uint8_t *t = arg_p(c, 0);
    ms_drop(LD64(arg_x(c, 0)), "FinalizeHardwareOpusMultiStreamDecoder");
    memset(t, 0, 0x28);
}

// Result DecodeOpusMultiStreamInterleavedWithHardware(HardwareOpusMultiStreamDecoderType *d, size_t *consumed,
// int *samples, int16_t *out, size_t out_size, const void *in, size_t in_size): framing as ov_decode
static void ov_ms_decode(Cpu *c) {
    uint64_t type = arg_x(c, 0), out_size = arg_x(c, 4), in_size = arg_x(c, 6);
    size_t *consumed = arg_p(c, 1);
    int *samples = arg_p(c, 2);
    int16_t *out = arg_p(c, 3);
    const uint8_t *in = arg_p(c, 5);
    if (!type || !consumed || !samples || !out || !in || in_size < 8) { ret_x(c, CODEC_R_INVALID); return; }
    uint32_t n = be32(in);
    if (n > in_size - 8 || n > INT_MAX) { ret_x(c, CODEC_R_INVALID); return; }
    uint64_t object = LD64(type);
    uint8_t *reset = (uint8_t *)(uintptr_t)type + 0x30;
    plat_mutex_lock_shared(&lock);
    MsDecoder *d = ms_decoders;
    while (d && d->object != object) d = d->next;
    if (d) plat_mutex_lock(&d->use);
    plat_mutex_unlock_shared(&lock);
    if (!d) rt_fatal("nn::codec::DecodeOpusMultiStreamInterleavedWithHardware: unknown decoder %#llx", (unsigned long long)object);
    if (*reset) {
        opus_multistream_decoder_ctl(d->dec, OPUS_RESET_STATE);
        *reset = 0;
    }
    size_t capacity = out_size / (sizeof(int16_t) * (size_t)d->channels);
    int got = capacity > INT_MAX ? OPUS_BAD_ARG : opus_multistream_decode(d->dec, in + 8, (opus_int32)n, out, (int)capacity, 0);
    plat_mutex_unlock(&d->use);
    if (got < 0) {
        rt_log("nn::codec: opus_multistream_decode: %s", opus_strerror(got));
        ret_x(c, CODEC_R_INVALID);
        return;
    }
    *consumed = 8 + n;
    *samples = got;
    ret_x(c, 0);
}

HOST_OVERRIDE("_ZN2nn5codec47GetHardwareOpusMultiStreamDecoderWorkBufferSizeEiiii", ov_ms_work_size);
HOST_OVERRIDE("_ZN2nn5codec47GetHardwareOpusMultiStreamDecoderWorkBufferSizeEiiiii", ov_ms_work_size);
HOST_OVERRIDE("_ZN2nn5codec40InitializeHardwareOpusMultiStreamDecoderEPNS0_34HardwareOpusMultiStreamDecoderTypeEiiiiPKhPvmi",
              ov_ms_initialize);
HOST_OVERRIDE("_ZN2nn5codec38FinalizeHardwareOpusMultiStreamDecoderEPNS0_34HardwareOpusMultiStreamDecoderTypeE", ov_ms_finalize);
HOST_OVERRIDE("_ZN2nn5codec44DecodeOpusMultiStreamInterleavedWithHardwareEPNS0_34HardwareOpusMultiStreamDecoderTypeEPmPiPsmPKvm",
              ov_ms_decode);
// size_t HardwareOpusMultiStreamDecoder::GetWorkBufferSize(int rate, int channels, int streams, int stereo) const: the
// class asks the service itself instead of calling the C function
HOST_OVERRIDE("_ZNK2nn5codec30HardwareOpusMultiStreamDecoder17GetWorkBufferSizeEiiii", ov_ms_work_size);
