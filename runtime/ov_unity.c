// SDK functions the Unity player calls that the lifted SDK could only answer through system services this host does
// not run (ro:, nifm:, bsd:, acc:, ...). Each is replaced at the nn::* level, as ov_system.c does for the rest: the
// host is one offline console with one user, no network, no add-on content and no loadable modules.
//
// Every stub logs its first call, so a boot log lists which of them the game really uses.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "host.h"
#include "ov.h"
#include "platform/platform.h"

#define FIRST_CALL(name)                                                                                          \
    do {                                                                                                          \
        static volatile int32_t seen;                                                                             \
        if (!plat_xchg32(&seen, 1)) rt_log("unity: first call of %s", name);                                      \
    } while (0)

// A function that only reports success (nn::Result 0, false, or void: x0 is ignored by a void caller).
#define STUB_ZERO(id, sym)                                                                                        \
    static void id(Cpu *c) {                                                                                      \
        FIRST_CALL(sym);                                                                                          \
        ret_x(c, 0);                                                                                              \
    }                                                                                                             \
    HOST_OVERRIDE(sym, id)
// A function that returns a fixed value: an error nn::Result, -1, a count.
#define STUB_VALUE(id, sym, value)                                                                                \
    static void id(Cpu *c) {                                                                                      \
        FIRST_CALL(sym);                                                                                          \
        ret_x(c, (uint64_t)(value));                                                                              \
    }                                                                                                             \
    HOST_OVERRIDE(sym, id)

#define RESULT(module, description) ((uint32_t)(module) | (uint32_t)(description) << 9)
#define R_RO_NOT_FOUND RESULT(22, 2)       // nn::ro: no such symbol / module
#define R_NIFM_NO_NETWORK RESULT(110, 300)
#define R_ACCOUNT_NO_NSA RESULT(124, 200)  // no network service account linked

// ---- nn::ro: no NRO modules exist on this host; lookups miss
STUB_ZERO(ro_initialize, "_ZN2nn2ro10InitializeEv");
STUB_VALUE(ro_load, "_ZN2nn2ro10LoadModuleEPNS0_6ModuleEPKvPvmi", R_RO_NOT_FOUND);
STUB_VALUE(ro_lookup, "_ZN2nn2ro12LookupSymbolEPmPKc", R_RO_NOT_FOUND);
STUB_VALUE(ro_lookup_module, "_ZN2nn2ro18LookupModuleSymbolEPmPKNS0_6ModuleEPKc", R_RO_NOT_FOUND);
STUB_VALUE(ro_buffer_size, "_ZN2nn2ro13GetBufferSizeEPmPKv", R_RO_NOT_FOUND);
STUB_VALUE(ro_register, "_ZN2nn2ro18RegisterModuleInfoEPNS0_16RegistrationInfoEPKv", R_RO_NOT_FOUND);
STUB_ZERO(ro_unload, "_ZN2nn2ro12UnloadModuleEPNS0_6ModuleE");
STUB_ZERO(ro_unregister, "_ZN2nn2ro20UnregisterModuleInfoEPNS0_16RegistrationInfoE");

// ---- nn::oe
STUB_ZERO(oe_crash_on, "_ZN2nn2oe17EnableCrashReportEv");
STUB_ZERO(oe_crash_off, "_ZN2nn2oe18DisableCrashReportEv");
STUB_ZERO(oe_perf_config, "_ZN2nn2oe27SetPerformanceConfigurationEi");
STUB_ZERO(oe_exit_enter, "_ZN2nn2oe31EnterExitRequestHandlingSectionEv");
STUB_ZERO(oe_exit_leave, "_ZN2nn2oe31LeaveExitRequestHandlingSectionEv");

// void GetPseudoDeviceId(nn::util::Uuid *out): a stable id per profile, derived from the local user's id.
static void oe_pseudo_device(Cpu *c) {
    FIRST_CALL("nn::oe::GetPseudoDeviceId");
    uint64_t uid[2];
    account_uid(uid);
    uid[0] ^= 0x5d1f2a3b4c6e7f80ull;
    uid[1] ^= 0x0f1e2d3c4b5a6978ull;
    if (arg_p(c, 0)) memcpy(arg_p(c, 0), uid, 16);
}
HOST_OVERRIDE("_ZN2nn2oe17GetPseudoDeviceIdEPNS_4util4UuidE", oe_pseudo_device);

// ---- nn::aoc
STUB_ZERO(aoc_count, "_ZN2nn3aoc17CountAddOnContentEv");

// ---- nn::nifm: offline
STUB_ZERO(nifm_initialize, "_ZN2nn4nifm10InitializeEv");
STUB_ZERO(nifm_available, "_ZN2nn4nifm18IsNetworkAvailableEv");
STUB_ZERO(nifm_local_mode, "_ZN2nn4nifm19SetLocalNetworkModeEb");
STUB_ZERO(nifm_cancel, "_ZN2nn4nifm20CancelNetworkRequestEv");
STUB_ZERO(nifm_submit, "_ZN2nn4nifm20SubmitNetworkRequestEv");
STUB_ZERO(nifm_on_hold, "_ZN2nn4nifm22IsNetworkRequestOnHoldEv");
STUB_VALUE(nifm_proxy, "_ZN2nn4nifm22GetCurrentProxySettingEPNS0_12ProxySettingE", R_NIFM_NO_NETWORK);
STUB_VALUE(nifm_address, "_ZN2nn4nifm26GetCurrentPrimaryIpAddressEPNS_6socket6InAddrE", R_NIFM_NO_NETWORK);
STUB_VALUE(nifm_handle_error, "_ZN2nn4nifm31HandleNetworkRequestErrorResultEv", R_NIFM_NO_NETWORK);

// ---- nn::socket: the library initialises, every socket call fails with ENETDOWN
#define NN_ENETDOWN 100
STUB_ZERO(socket_initialize, "_ZN2nn6socket10InitializeEPvmmi");
STUB_ZERO(socket_initialize_config, "_ZN2nn6socket10InitializeERKNS0_6ConfigE");
STUB_ZERO(socket_finalize, "_ZN2nn6socket8FinalizeEv");
STUB_VALUE(socket_last_error, "_ZN2nn6socket12GetLastErrorEv", NN_ENETDOWN);
STUB_VALUE(socket_socket, "_ZN2nn6socket6SocketENS0_6FamilyENS0_4TypeENS0_8ProtocolE", -1);
STUB_VALUE(socket_getsockopt, "_ZN2nn6socket10GetSockOptEiNS0_5LevelENS0_6OptionEPvPj", -1);
STUB_VALUE(socket_setsockopt, "_ZN2nn6socket10SetSockOptEiNS0_5LevelENS0_6OptionEPKvj", -1);
STUB_VALUE(socket_getsockname, "_ZN2nn6socket11GetSockNameEiPNS0_8SockAddrEPj", -1);
STUB_VALUE(socket_eventfd_write, "_ZN2nn6socket12EventFdWriteEim", -1);
STUB_VALUE(socket_bind, "_ZN2nn6socket4BindEiPKNS0_8SockAddrEj", -1);
STUB_VALUE(socket_poll, "_ZN2nn6socket4PollEPNS0_6PollFdEmi", -1);
STUB_VALUE(socket_recv, "_ZN2nn6socket4RecvEiPvmNS0_7MsgFlagE", -1);
STUB_VALUE(socket_send, "_ZN2nn6socket4SendEiPKvmNS0_7MsgFlagE", -1);
STUB_VALUE(socket_close, "_ZN2nn6socket5CloseEi", -1);
STUB_VALUE(socket_fcntl, "_ZN2nn6socket5FcntlEiNS0_12FcntlCommandEz", -1);
STUB_VALUE(socket_accept, "_ZN2nn6socket6AcceptEiPNS0_8SockAddrEPj", -1);
STUB_VALUE(socket_listen, "_ZN2nn6socket6ListenEii", -1);
STUB_VALUE(socket_sendto, "_ZN2nn6socket6SendToEiPKvmNS0_7MsgFlagEPKNS0_8SockAddrEj", -1);
STUB_VALUE(socket_connect, "_ZN2nn6socket7ConnectEiPKNS0_8SockAddrEj", -1);
STUB_VALUE(socket_recvfrom, "_ZN2nn6socket8RecvFromEiPvmNS0_7MsgFlagEPNS0_8SockAddrEPj", -1);
STUB_VALUE(socket_shutdown, "_ZN2nn6socket8ShutdownEiNS0_14ShutdownMethodE", -1);

// ---- nn::account: one local user, always open, without a network service account
static void put_uid(void *out) {
    uint64_t uid[2];
    account_uid(uid);
    if (out) memcpy(out, uid, 16);
}

// Result GetUserCount(int *out)
static void account_count(Cpu *c) {
    FIRST_CALL("nn::account::GetUserCount");
    if (arg_p(c, 0)) *(int32_t *)arg_p(c, 0) = 1;
    ret_x(c, 0);
}
HOST_OVERRIDE("_ZN2nn7account12GetUserCountEPi", account_count);

// Result ListAllUsers / ListOpenUsers / ListQualifiedUsers(int *count, Uid *out, int capacity)
static void account_list(Cpu *c) {
    FIRST_CALL("nn::account::List*Users");
    int n = (int32_t)arg_x(c, 2) > 0;
    if (n) put_uid(arg_p(c, 1));
    if (arg_p(c, 0)) *(int32_t *)arg_p(c, 0) = n;
    ret_x(c, 0);
}
HOST_OVERRIDE("_ZN2nn7account12ListAllUsersEPiPNS0_3UidEi", account_list);
HOST_OVERRIDE("_ZN2nn7account13ListOpenUsersEPiPNS0_3UidEi", account_list);
HOST_OVERRIDE("_ZN2nn7account18ListQualifiedUsersEPiPNS0_3UidEi", account_list);

// Result GetLastOpenedUser(Uid *out); Result ShowUserSelector(Uid *out, const UserSelectionSettings &)
static void account_the_user(Cpu *c) {
    FIRST_CALL("nn::account::GetLastOpenedUser / ShowUserSelector");
    put_uid(arg_p(c, 0));
    ret_x(c, 0);
}
HOST_OVERRIDE("_ZN2nn7account17GetLastOpenedUserEPNS0_3UidE", account_the_user);
HOST_OVERRIDE("_ZN2nn7account16ShowUserSelectorEPNS0_3UidERKNS0_21UserSelectionSettingsE", account_the_user);

// Result IsNetworkServiceAccountAvailable(bool *out, const UserHandle &)
static void account_nsa_available(Cpu *c) {
    FIRST_CALL("nn::account::IsNetworkServiceAccountAvailable");
    if (arg_p(c, 0)) *(uint8_t *)arg_p(c, 0) = 0;
    ret_x(c, 0);
}
HOST_OVERRIDE("_ZN2nn7account32IsNetworkServiceAccountAvailableEPbRKNS0_10UserHandleE", account_nsa_available);
STUB_VALUE(account_nsa_ensure, "_ZN2nn7account36EnsureNetworkServiceAccountAvailableERKNS0_10UserHandleE", R_ACCOUNT_NO_NSA);
STUB_VALUE(account_nsa_id, "_ZN2nn7account26GetNetworkServiceAccountIdEPNS0_23NetworkServiceAccountIdERKNS0_10UserHandleE",
           R_ACCOUNT_NO_NSA);
STUB_VALUE(account_nsa_token, "_ZN2nn7account37LoadNetworkServiceAccountIdTokenCacheEPmPcmRKNS0_10UserHandleE",
           R_ACCOUNT_NO_NSA);
STUB_ZERO(account_thumbnail_store, "_ZN2nn7account27StoreSaveDataThumbnailImageERKNS0_3UidEPKvm");
STUB_ZERO(account_thumbnail_delete, "_ZN2nn7account28DeleteSaveDataThumbnailImageERKNS0_3UidE");

// ---- nn::crypto, nn::os random bytes run lifted (svc GetInfo entropy); nothing to replace

// ---- the C API of nn::ssl and nn::socket, and musl's BSD sockets, which the player's bundled libcurl and Mono
// socket layer call: the libraries initialise, nothing connects
#define R_SSL_UNAVAILABLE RESULT(123, 1)
STUB_ZERO(c_ssl_initialize, "nnsslInitialize");
STUB_ZERO(c_ssl_finalize, "nnsslFinalize");
STUB_VALUE(c_ssl_context_destroy, "nnsslContextDestroy", R_SSL_UNAVAILABLE);
STUB_VALUE(c_ssl_context_id, "nnsslContextGetContextId", R_SSL_UNAVAILABLE);
STUB_VALUE(c_ssl_create, "nnsslConnectionCreate", R_SSL_UNAVAILABLE);
STUB_VALUE(c_ssl_destroy, "nnsslConnectionDestroy", R_SSL_UNAVAILABLE);
STUB_VALUE(ssl_context_create, "_ZN2nn3ssl7Context6CreateENS1_10SslVersionE", R_SSL_UNAVAILABLE);

STUB_VALUE(c_socket_socket, "nnsocketSocket", -1);
STUB_VALUE(c_socket_bind, "nnsocketBind", -1);
STUB_VALUE(c_socket_close, "nnsocketClose", -1);
STUB_VALUE(c_socket_connect, "nnsocketConnect", -1);
STUB_VALUE(c_socket_fcntl, "nnsocketFcntl", -1);
STUB_ZERO(c_socket_host_by_name, "nnsocketGetHostByNameWithOptions");   // NULL: no such host
STUB_VALUE(c_socket_errno, "nnsocketGetLastErrno", NN_ENETDOWN);
STUB_VALUE(c_socket_peer_name, "nnsocketGetPeerName", -1);
STUB_VALUE(c_socket_sock_name, "nnsocketGetSockName", -1);
STUB_VALUE(c_socket_get_opt, "nnsocketGetSockOpt", -1);
STUB_VALUE(c_socket_poll, "nnsocketPoll", -1);
STUB_VALUE(c_socket_recv, "nnsocketRecv", -1);
STUB_VALUE(c_socket_send, "nnsocketSend", -1);
STUB_VALUE(c_socket_set_opt, "nnsocketSetSockOpt", -1);
STUB_VALUE(c_socket_resolver_get, "nnsocketResolverGetOption", -1);
STUB_VALUE(c_socket_resolver_set, "nnsocketResolverSetOption", -1);
STUB_ZERO(c_socket_set_errno, "nnsocketSetLastErrno");

#define NN_EAI_FAIL (-4)
STUB_VALUE(posix_socket, "socket", -1);
STUB_VALUE(posix_bind, "bind", -1);
STUB_VALUE(posix_connect, "connect", -1);
STUB_VALUE(posix_getsockname, "getsockname", -1);
STUB_VALUE(posix_setsockopt, "setsockopt", -1);
STUB_VALUE(posix_recv, "recv", -1);
STUB_VALUE(posix_recvfrom, "recvfrom", -1);
STUB_VALUE(posix_send, "send", -1);
STUB_VALUE(posix_sendto, "sendto", -1);
STUB_VALUE(posix_select, "select", -1);
STUB_VALUE(posix_getaddrinfo, "getaddrinfo", NN_EAI_FAIL);
STUB_VALUE(posix_getnameinfo, "getnameinfo", NN_EAI_FAIL);
STUB_ZERO(posix_freeaddrinfo, "freeaddrinfo");

// ---- bool nn::ro::detail::GetExceptionInfo(ExceptionInfo *out, uintptr_t pc): the C++ unwinder's lookup of the module
// around a pc. The SDK finds the module's extent with QueryMemory and reads .eh_frame_hdr's place from its MOD0 header;
// the loader knows the modules, so the answer comes from there.
// ExceptionInfo {module base, module size, .eh_frame_hdr offset from the base, .eh_frame_hdr size}.
static void ro_exception_info(Cpu *c) {
    uint64_t *out = arg_p(c, 0), pc = arg_x(c, 1);
    for (int i = 0; i < ldr_count(); i++) {
        const RtLoaded *m = ldr_module(i);
        if (pc < m->base || pc >= m->base + m->size) continue;
        uint32_t mod0 = LD32(m->base + 4);
        if (LD32(m->base + mod0) != 0x30444f4du) break;   // "MOD0"
        uint32_t start = LD32(m->base + mod0 + 0x10), end = LD32(m->base + mod0 + 0x14);
        out[0] = m->base;
        out[1] = m->size;
        out[2] = (uint64_t)mod0 + start;
        out[3] = end - start;
        if (rt_trace_unwind) {
            char at[160];
            rt_log("unwind: table lookup for %s", ldr_describe(pc, at, sizeof at));
        }
        ret_x(c, 1);
        return;
    }
    char at[160];
    rt_log("unity: GetExceptionInfo: no module holds %s", ldr_describe(pc, at, sizeof at));
    ret_x(c, 0);
}
HOST_OVERRIDE("_ZN2nn2ro6detail16GetExceptionInfoEPNS1_13ExceptionInfoEm", ro_exception_info);
