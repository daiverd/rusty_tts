/*
 * sv_shim.c - Unicorn-emulated Win32 shim for SoftVoice, Inc.'s TIBASE32.DLL
 * (+ TIENG32.DLL/TISPAN32.DLL language modules), same approach as
 * native/keynote/bst_shim.c: map the real 32-bit PE DLL into emulated x86
 * memory, service its Win32 imports (KERNEL32/USER32/WINMM/MSVCRT40) with
 * hand-written C stubs, capture waveOutWrite's PCM instead of playing it.
 * No Wine dependency.
 *
 * Debug build: gcc -DSV_DEBUG ...
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>
#include <time.h>
#include <stdbool.h>
#include <unicorn/unicorn.h>
#include "sv_shim.h"

#ifdef SV_DEBUG
#define DBG(...) fprintf(stderr, __VA_ARGS__)
#else
#define DBG(...) do {} while (0)
#endif

#pragma pack(push, 1)
typedef struct { uint16_t e_magic; uint8_t pad[58]; uint32_t e_lfanew; } DOS_HEADER;
typedef struct {
    uint32_t Signature; uint16_t Machine, NumberOfSections;
    uint32_t TimeDateStamp, PointerToSymbolTable, NumberOfSymbols;
    uint16_t SizeOfOptionalHeader, Characteristics;
} FILE_HEADER;
typedef struct { uint32_t VirtualAddress, Size; } DATA_DIR;
typedef struct {
    uint16_t Magic; uint8_t MajorLinkerVersion, MinorLinkerVersion;
    uint32_t SizeOfCode, SizeOfInitializedData, SizeOfUninitializedData;
    uint32_t AddressOfEntryPoint, BaseOfCode, BaseOfData, ImageBase;
    uint32_t SectionAlignment, FileAlignment;
    uint16_t MajorOSVer, MinorOSVer, MajorImageVer, MinorImageVer, MajorSubVer, MinorSubVer;
    uint32_t Win32VersionValue, SizeOfImage, SizeOfHeaders, CheckSum;
    uint16_t Subsystem, DllCharacteristics;
    uint32_t SizeOfStackReserve, SizeOfStackCommit, SizeOfHeapReserve, SizeOfHeapCommit, LoaderFlags, NumberOfRvaAndSizes;
    DATA_DIR DataDirectory[16];
} OPT_HEADER;
typedef struct {
    char Name[8];
    uint32_t VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData;
    uint32_t PointerToRelocations, PointerToLinenumbers;
    uint16_t NumberOfRelocations, NumberOfLinenumbers;
    uint32_t Characteristics;
} SECTION_HEADER;
typedef struct { uint32_t OriginalFirstThunk, TimeDateStamp, ForwarderChain, Name, FirstThunk; } IMPORT_DESC;
typedef struct {
    uint32_t Characteristics, TimeDateStamp; uint16_t MajorVersion, MinorVersion;
    uint32_t Name, Base, NumberOfFunctions, NumberOfNames;
    uint32_t AddressOfFunctions, AddressOfNames, AddressOfNameOrdinals;
} EXPORT_DIR;
#pragma pack(pop)

// ---------------------------------------------------------------------------
// Memory map
// ---------------------------------------------------------------------------
#define STACK_BASE    0x00300000u
#define STACK_SIZE    0x00100000u
#define STACK_TOP     (STACK_BASE + STACK_SIZE - 0x100)
#define SCRATCH_BASE  0x00500000u   // nested-call scratch stacks (one per depth)
#define SCRATCH_SIZE  0x00100000u
#define HEAP_BASE     0x40000000u
#define HEAP_SIZE     0x08000000u
#define TIB_BASE      0x00100000u
#define TIB_SIZE      0x00001000u
#define STUB_BASE     0x70000000u
#define STUB_SIZE     0x00010000u
#define RET_MAGIC     0x0000DEADu

#define CALLER_HWND   0x00CAFE00u   // fake HWND passed to SVOpenSpeech (the "caller window")
#define FIRST_HWND    0x00CC0001u   // fake HWNDs allocated for CreateWindowExA (DLL's own window)

#define MAX_SHIMS   256
#define MAX_MODULES 3
#define MAX_HANDLES 16
#define MSGQ_SIZE   64

typedef struct { uint8_t *file; long filelen; OPT_HEADER *opt; SECTION_HEADER *secs; int nsec; uint32_t base; } pe_module;

typedef struct { uint32_t hwnd, message, wparam, lparam; int used; } msg_t;

typedef struct { uint32_t class_wndproc; int used; } wndclass_t;

struct sv_engine {
    uc_engine *uc;
    pe_module mods[MAX_MODULES];
    int nmods;

    uint32_t heap_ptr;
    uint32_t scratch_depth;

    char      *shim_name[MAX_SHIMS];
    uint32_t   shim_stub[MAX_SHIMS];
    int        nshims;

    uint32_t tls[512];
    int tls_next;
    uint32_t last_error;
    uint32_t cmdline;

    // fake FILE* handles (real host FILE* behind an index)
    FILE *host_files[MAX_HANDLES];

    // window/message state
    uint32_t last_registered_wndproc;  // from most recent RegisterClassA
    uint32_t next_hwnd;
    wndclass_t hwnd_wndproc[64];       // indexed by (hwnd - FIRST_HWND)
    msg_t msgq[MSGQ_SIZE];
    int msgq_head, msgq_tail;

    // multimedia timer (timeSetEvent) - only one active at a time, which is
    // all TIBASE32 ever uses
    uint32_t timer_proc, timer_user, timer_flags;
    int timer_active;

    // waveOut state: only one device open at a time
    uint32_t wave_callback_hwnd; // target hwnd for MM_WOM_DONE if CALLBACK_WINDOW
    int wave_open;
    uint32_t wave_sample_rate;  // read from the DLL's own waveOutOpen WAVEFORMATEX
    uint32_t wave_channels;
    uint32_t wave_bits;         // 8 or 16 - TIBASE32 actually opens 8-bit unsigned PCM

    // captured audio + completion signal
    sv_sample_cb cb;
    void *cb_ctx;
    int speech_done;    // set when caller-hwnd PostMessageA(..., SPEECH_DONE, ...) seen
    int pump_budget;     // safety valve against runaway timer pumping
};

// ---------------------------------------------------------------------------
// Basic reg/mem helpers
// ---------------------------------------------------------------------------
static uint32_t rd32(sv_engine *e, uint32_t a){ uint32_t v=0; uc_mem_read(e->uc,a,&v,4); return v; }
static void     wr32(sv_engine *e, uint32_t a, uint32_t v){ uc_mem_write(e->uc,a,&v,4); }
static uint8_t  rd8(sv_engine *e, uint32_t a){ uint8_t v=0; uc_mem_read(e->uc,a,&v,1); return v; }
static uint32_t reg(sv_engine *e, int r){ uint32_t v=0; uc_reg_read(e->uc,r,&v); return v; }
static void     setreg(sv_engine *e, int r, uint32_t v){ uc_reg_write(e->uc,r,&v); }
static uint32_t arg(sv_engine *e, int n){ return rd32(e, reg(e,UC_X86_REG_ESP) + 4 + n*4); }

static uint32_t heap_alloc(sv_engine *e, uint32_t size){
    uint32_t p = (e->heap_ptr + 15) & ~15u;
    e->heap_ptr = p + (size ? size : 16);
    if (e->heap_ptr > HEAP_BASE + HEAP_SIZE) return 0;
    static uint8_t z[4096];
    uint32_t left=size, a=p;
    while(left){ uint32_t c=left>sizeof(z)?sizeof(z):left; uc_mem_write(e->uc,a,z,c); a+=c; left-=c; }
    return p;
}

static void read_cstr(sv_engine *e, uint32_t a, char *out, size_t maxlen){
    size_t i=0;
    for (; i+1<maxlen; i++){ uint8_t b=rd8(e,a+(uint32_t)i); out[i]=(char)b; if(!b) return; }
    out[i]=0;
}

// ---------------------------------------------------------------------------
// Nested call helper: call an emulated function and get its EAX, without
// disturbing the caller's own registers/ESP. Verified safe (nested
// uc_emu_start on the same engine works correctly with this unicorn build).
// ---------------------------------------------------------------------------
static uint32_t call_sub(sv_engine *e, uint32_t va, int argc, const uint32_t *argv){
    if (va == 0) return 0;
    uint32_t save_esp, save_ebp, save_eip;
    save_esp = reg(e, UC_X86_REG_ESP);
    save_ebp = reg(e, UC_X86_REG_EBP);
    save_eip = reg(e, UC_X86_REG_EIP);
    uint32_t save_eax=reg(e,UC_X86_REG_EAX), save_ebx=reg(e,UC_X86_REG_EBX);
    uint32_t save_ecx=reg(e,UC_X86_REG_ECX), save_edx=reg(e,UC_X86_REG_EDX);
    uint32_t save_esi=reg(e,UC_X86_REG_ESI), save_edi=reg(e,UC_X86_REG_EDI);

    uint32_t depth = e->scratch_depth++;
    uint32_t top = SCRATCH_BASE + (depth % 8) * 0x10000 + 0xFF00;
    uint32_t esp = top & ~0xFu;
    for (int i=argc-1;i>=0;i--){ esp-=4; wr32(e, esp, argv[i]); }
    esp-=4; wr32(e, esp, RET_MAGIC);
    setreg(e, UC_X86_REG_ESP, esp); setreg(e, UC_X86_REG_EBP, 0);
    uc_err err = uc_emu_start(e->uc, va, RET_MAGIC, 0, 0);
    uint32_t result = reg(e, UC_X86_REG_EAX);
    e->scratch_depth--;
    if (err) { DBG("[sv_shim] call_sub to 0x%x failed: %s at EIP=0x%x\n", va, uc_strerror(err), reg(e,UC_X86_REG_EIP)); result = 0; }

    setreg(e, UC_X86_REG_ESP, save_esp); setreg(e, UC_X86_REG_EBP, save_ebp); setreg(e, UC_X86_REG_EIP, save_eip);
    setreg(e, UC_X86_REG_EAX, save_eax); setreg(e, UC_X86_REG_EBX, save_ebx);
    setreg(e, UC_X86_REG_ECX, save_ecx); setreg(e, UC_X86_REG_EDX, save_edx);
    setreg(e, UC_X86_REG_ESI, save_esi); setreg(e, UC_X86_REG_EDI, save_edi);
    return result;
}

// ---------------------------------------------------------------------------
// Message queue
// ---------------------------------------------------------------------------
static void msgq_post(sv_engine *e, uint32_t hwnd, uint32_t message, uint32_t wparam, uint32_t lparam){
    int i = e->msgq_tail;
    if (e->msgq[i].used) { DBG("[sv_shim] message queue full, dropping msg\n"); return; }
    e->msgq[i] = (msg_t){hwnd,message,wparam,lparam,1};
    e->msgq_tail = (i+1) % MSGQ_SIZE;
}
// Returns 1 and fills *out if a message matching filters was found (and removes it if remove!=0).
static int msgq_get(sv_engine *e, uint32_t hwnd_filter, int remove, msg_t *out){
    for (int n=0;n<MSGQ_SIZE;n++){
        int i = (e->msgq_head + n) % MSGQ_SIZE;
        if (!e->msgq[i].used) continue;
        if (hwnd_filter != 0 && e->msgq[i].hwnd != hwnd_filter) continue;
        *out = e->msgq[i];
        if (remove){
            // shift-compact isn't necessary; just mark slot free. Head only
            // advances when the head slot itself is consumed, else leave a hole
            // (used=0) that msgq_get skips over.
            e->msgq[i].used = 0;
            while (e->msgq_head != e->msgq_tail && !e->msgq[e->msgq_head].used)
                e->msgq_head = (e->msgq_head+1) % MSGQ_SIZE;
        }
        return 1;
    }
    return 0;
}

static void wndproc_for_hwnd_register(sv_engine *e, uint32_t hwnd, uint32_t wndproc){
    uint32_t idx = hwnd - FIRST_HWND;
    if (idx < 64) e->hwnd_wndproc[idx] = (wndclass_t){wndproc, 1};
}
static uint32_t wndproc_for_hwnd(sv_engine *e, uint32_t hwnd){
    uint32_t idx = hwnd - FIRST_HWND;
    if (idx < 64 && e->hwnd_wndproc[idx].used) return e->hwnd_wndproc[idx].class_wndproc;
    return 0;
}

// ---------------------------------------------------------------------------
// Import shims
// ---------------------------------------------------------------------------
static int shim_index_for_stub(sv_engine *e, uint32_t addr){
    if (addr < STUB_BASE || addr >= STUB_BASE + STUB_SIZE) return -1;
    (void)e;
    return (int)((addr - STUB_BASE) / 8);
}
static int find_or_add_shim(sv_engine *e, const char *name){
    for (int i=0;i<e->nshims;i++) if (!strcmp(e->shim_name[i],name)) return i;
    int i = e->nshims++;
    e->shim_name[i] = strdup(name);
    e->shim_stub[i] = STUB_BASE + (uint32_t)i*8;
    return i;
}

static uint32_t find_module_export(sv_engine *e, uint32_t modbase, const char *want);

static uint32_t run_shim(sv_engine *e, const char *fn, int *arg_dwords){
    // ---- WINMM: capture audio, never play it ----
    if (!strcmp(fn,"waveOutOpen")) {
        uint32_t phwo=arg(e,0);
        uint32_t pFormat=arg(e,2);
        uint32_t dwCallback=arg(e,3), fdwOpen=arg(e,5);
        if (phwo) wr32(e,phwo,0xBEEF);
        e->wave_open = 1;
        e->wave_callback_hwnd = (fdwOpen & 0x00010000u /*CALLBACK_WINDOW*/) ? dwCallback : 0;
        if (pFormat) {
            // WAVEFORMATEX: wFormatTag(2) nChannels(2) nSamplesPerSec(4) ...
            uint32_t tag_channels = rd32(e, pFormat + 0); // low16=wFormatTag, high16=nChannels
            uint32_t samplesPerSec = rd32(e, pFormat + 4);
            uint32_t bitsBlock = rd32(e, pFormat + 12); // low16=nBlockAlign, high16=wBitsPerSample
            uint16_t nChannels = (uint16_t)(tag_channels >> 16);
            uint16_t bitsPerSample = (uint16_t)(bitsBlock >> 16);
            if (samplesPerSec) e->wave_sample_rate = samplesPerSec;
            if (nChannels) e->wave_channels = nChannels;
            if (bitsPerSample) e->wave_bits = bitsPerSample;
            DBG("[sv_shim] waveOutOpen format: tag=0x%x channels=%u samplesPerSec=%u bitsPerSample=%u\n",
                tag_channels & 0xFFFF, nChannels, samplesPerSec, bitsPerSample);
        }
        DBG("[sv_shim] waveOutOpen callback_hwnd=0x%x flags=0x%x\n", dwCallback, fdwOpen);
        *arg_dwords=6; return 0;
    }
    if (!strcmp(fn,"waveOutPrepareHeader"))   { DBG("[sv_shim] waveOutPrepareHeader\n"); *arg_dwords=3; return 0; }
    if (!strcmp(fn,"waveOutUnprepareHeader")) { DBG("[sv_shim] waveOutUnprepareHeader\n"); *arg_dwords=3; return 0; }
    if (!strcmp(fn,"waveOutReset"))           { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"waveOutPause"))           { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"waveOutRestart"))         { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"waveOutClose"))           { e->wave_open=0; *arg_dwords=1; return 0; }
    if (!strcmp(fn,"waveOutGetNumDevs"))      { *arg_dwords=0; return 1; }
    if (!strcmp(fn,"waveOutWrite")) {
        uint32_t pwh = arg(e,1);
        uint32_t lpData = rd32(e, pwh + 0);
        uint32_t dwLen  = rd32(e, pwh + 4);
        DBG("[sv_shim] waveOutWrite lpData=0x%x len=%u\n", lpData, dwLen);
        if (lpData && dwLen && dwLen < 0x02000000 && e->cb) {
            if (e->wave_bits == 16) {
                int16_t *tmp = (int16_t*)malloc(dwLen);
                if (tmp) {
                    uc_mem_read(e->uc, lpData, tmp, dwLen);
                    e->cb(tmp, dwLen/2, e->cb_ctx);
                    free(tmp);
                }
            } else {
                // TIBASE32 actually opens the wave device as 8-bit UNSIGNED
                // PCM (silence = 0x80), not 16-bit signed - confirmed by
                // reading the real WAVEFORMATEX it passes to waveOutOpen.
                // Widen to signed 16-bit for the callback's fixed contract.
                uint8_t *raw = (uint8_t*)malloc(dwLen);
                int16_t *tmp = (int16_t*)malloc(dwLen * 2);
                if (raw && tmp) {
                    uc_mem_read(e->uc, lpData, raw, dwLen);
                    for (uint32_t i=0;i<dwLen;i++) tmp[i] = (int16_t)(((int)raw[i] - 128) * 256);
                    e->cb(tmp, dwLen, e->cb_ctx);
                }
                free(raw); free(tmp);
            }
        }
        uint32_t flags = rd32(e, pwh + 16);
        wr32(e, pwh + 16, (flags | 0x1u) & ~0x2u);  // WHDR_DONE set, WHDR_INQUEUE cleared
        if (e->wave_callback_hwnd)
            msgq_post(e, e->wave_callback_hwnd, 0x3BD /*MM_WOM_DONE*/, 0xBEEF, pwh);
        *arg_dwords=3; return 0;
    }
    if (!strcmp(fn,"timeGetTime")) { *arg_dwords=0; static uint32_t t=0; t+=10; return t; }
    if (!strcmp(fn,"timeBeginPeriod")) { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"timeEndPeriod"))   { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"timeKillEvent")) {
        e->timer_active = 0;
        DBG("[sv_shim] timeKillEvent\n");
        *arg_dwords=1; return 0;
    }
    if (!strcmp(fn,"timeSetEvent")) {
        // (uDelay, uResolution, lpTimeProc, dwUser, fuEvent)
        e->timer_proc = arg(e,2); e->timer_user = arg(e,3); e->timer_flags = arg(e,4);
        e->timer_active = 1;
        DBG("[sv_shim] timeSetEvent proc=0x%x user=0x%x flags=0x%x\n", e->timer_proc, e->timer_user, e->timer_flags);
        *arg_dwords=5; return 1; // fake timer id
    }

    // ---- KERNEL32 ----
    if (!strcmp(fn,"GlobalAlloc")) { *arg_dwords=2; return heap_alloc(e, arg(e,1)); }
    if (!strcmp(fn,"LocalAlloc"))  { *arg_dwords=2; return heap_alloc(e, arg(e,1)); }
    if (!strcmp(fn,"GlobalLock"))  { *arg_dwords=1; return arg(e,0); }
    if (!strcmp(fn,"LocalLock"))   { *arg_dwords=1; return arg(e,0); }
    if (!strcmp(fn,"GlobalUnlock")){ *arg_dwords=1; return 1; }
    if (!strcmp(fn,"LocalUnlock")) { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"GlobalFree"))  { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"LocalFree"))   { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"GetVersion"))  { *arg_dwords=0; return 0x00000004; }
    if (!strcmp(fn,"GetProcAddress")) {
        uint32_t hmod = arg(e,0);
        uint32_t namep = arg(e,1);
        char name[256]; read_cstr(e, namep, name, sizeof(name));
        uint32_t rva = find_module_export(e, hmod, name);
        DBG("[sv_shim] GetProcAddress(0x%x, \"%s\") -> 0x%x\n", hmod, name, rva);
        *arg_dwords=2; return rva;
    }
    if (!strcmp(fn,"LoadLibraryA")) {
        char name[256]; read_cstr(e, arg(e,0), name, sizeof(name));
        for (int i=0;i<256;i++) name[i]=name[i]?(char)tolower((unsigned char)name[i]):0;
        uint32_t base = 0;
        for (int m=0;m<e->nmods;m++){
            // crude match: does the module's own base correspond to this name?
            // caller (sv_create) records which base is which language before
            // this is ever invoked, via g_mod_names below.
            extern const char *sv_shim_mod_name_hack(sv_engine*,int);
            const char *mn = sv_shim_mod_name_hack(e,m);
            if (mn && strstr(name, mn)) { base = e->mods[m].base; break; }
        }
        DBG("[sv_shim] LoadLibraryA(\"%s\") -> 0x%x\n", name, base);
        *arg_dwords=1; return base;
    }
    if (!strcmp(fn,"FreeLibrary")) { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"GetModuleHandleA")) { *arg_dwords=1; return e->mods[0].base; }

    // ---- MSVCRT40 ----
    if (!strcmp(fn,"malloc"))  { *arg_dwords=0; return heap_alloc(e, arg(e,0)); }
    if (!strcmp(fn,"calloc"))  { *arg_dwords=0; return heap_alloc(e, arg(e,0)*arg(e,1)); }
    if (!strcmp(fn,"realloc")) {
        uint32_t old=arg(e,0), sz=arg(e,1);
        uint32_t p = heap_alloc(e, sz);
        if (old && p) { // best-effort copy (bump allocator never frees, so old data is still valid)
            uint8_t buf[4096]; uint32_t left=sz, a=old, b=p;
            while(left){ uint32_t c=left>sizeof(buf)?sizeof(buf):left; uc_mem_read(e->uc,a,buf,c); uc_mem_write(e->uc,b,buf,c); a+=c;b+=c;left-=c; }
        }
        *arg_dwords=0; return p;
    }
    if (!strcmp(fn,"free")) { *arg_dwords=0; return 0; }
    if (!strcmp(fn,"_initterm")) {
        uint32_t pbegin=arg(e,0), pend=arg(e,1);
        DBG("[sv_shim] _initterm [0x%x,0x%x)\n", pbegin, pend);
        for (uint32_t a=pbegin; a+4<=pend; a+=4){
            uint32_t fn_va = rd32(e,a);
            if (fn_va && fn_va != 0xFFFFFFFFu) call_sub(e, fn_va, 0, NULL);
        }
        *arg_dwords=0; return 0;
    }
    if (!strcmp(fn,"_adjust_fdiv")) { *arg_dwords=0; return 0; } // shouldn't be called (data import)
    if (!strcmp(fn,"__p___mb_cur_max")) { static uint32_t slot=0; if(!slot){slot=heap_alloc(e,4); wr32(e,slot,1);} *arg_dwords=0; return slot; }
    if (!strcmp(fn,"__p__pctype")) {
        // __p__pctype() returns &_pctype (a `const unsigned short **`); callers
        // do **two** dereferences: `mov ecx,[eax]` to get the real table
        // pointer, then `[ecx+idx*2]` to read the flags word for idx. Table
        // is indexed from -1 (EOF) through 255, MS's standard _pctype layout.
        static uint32_t ptr_slot=0;
        if (!ptr_slot) {
            uint32_t table = heap_alloc(e, 257*2);
            for (int c=-1; c<256; c++){
                uint16_t f=0;
                if (c>=0){
                    if (isupper(c)) f|=0x0001;
                    if (islower(c)) f|=0x0002;
                    if (isdigit(c)) f|=0x0004;
                    if (isspace(c)) f|=0x0008;
                    if (ispunct(c)) f|=0x0010;
                    if (iscntrl(c)) f|=0x0020;
                    if (c==' '||c=='\t') f|=0x0040;
                    if (isxdigit(c)) f|=0x0080;
                    if (isalpha(c))  f|=0x0100;
                }
                uint32_t addr = table + (uint32_t)((c+1)*2);
                uint8_t b[2] = { (uint8_t)(f&0xFF), (uint8_t)(f>>8) };
                uc_mem_write(e->uc, addr, b, 2);
            }
            uint32_t table_at_zero = table + 2; // so index -1 reads table[0]
            ptr_slot = heap_alloc(e, 4);
            wr32(e, ptr_slot, table_at_zero);
        }
        *arg_dwords=0; return ptr_slot;
    }
    if (!strcmp(fn,"_isctype")) {
        int c=(int)arg(e,0), t=(int)arg(e,1);
        int r=0;
        switch(t){ case 1: r=isupper(c); break; case 2: r=islower(c); break; case 4: r=isdigit(c); break;
                   case 8: r=isspace(c); break; case 0x10: r=ispunct(c); break; case 0x20: r=iscntrl(c); break;
                   default: r=isalpha(c); }
        *arg_dwords=0; return r?1:0;
    }
    if (!strcmp(fn,"toupper")) { *arg_dwords=0; return (uint32_t)toupper((int)arg(e,0)); }
    if (!strcmp(fn,"tolower")) { *arg_dwords=0; return (uint32_t)tolower((int)arg(e,0)); }
    if (!strcmp(fn,"time"))    { *arg_dwords=0; return (uint32_t)time(NULL); }
    if (!strcmp(fn,"localtime")) {
        static uint32_t slot=0; if(!slot) slot=heap_alloc(e,36);
        *arg_dwords=0; return slot;
    }
    if (!strcmp(fn,"_ltoa")) {
        int32_t v=(int32_t)arg(e,0); uint32_t buf=arg(e,1); int radix=(int)arg(e,2);
        char tmp[32]; snprintf(tmp,sizeof(tmp), radix==16?"%x":"%d", v);
        uc_mem_write(e->uc, buf, tmp, strlen(tmp)+1);
        *arg_dwords=0; return buf;
    }
    if (!strcmp(fn,"strncat")) {
        uint32_t d=arg(e,0), s=arg(e,1), n=arg(e,2);
        char dst[512],src[512]; read_cstr(e,d,dst,sizeof(dst)); read_cstr(e,s,src,sizeof(src));
        strncat(dst,src,n); uc_mem_write(e->uc,d,dst,strlen(dst)+1);
        *arg_dwords=0; return d;
    }
    if (!strcmp(fn,"strncpy")) {
        uint32_t d=arg(e,0), s=arg(e,1), n=arg(e,2);
        char src[512]; read_cstr(e,s,src,sizeof(src));
        char dst[512]; memset(dst,0,sizeof(dst)); strncpy(dst,src,n<sizeof(dst)?n:sizeof(dst)-1);
        uc_mem_write(e->uc,d,dst,n<sizeof(dst)?n:sizeof(dst)-1);
        *arg_dwords=0; return d;
    }
    if (!strcmp(fn,"strncmp")) {
        char a[512],b[512]; read_cstr(e,arg(e,0),a,sizeof(a)); read_cstr(e,arg(e,1),b,sizeof(b));
        *arg_dwords=0; return (uint32_t)(int32_t)strncmp(a,b,arg(e,2));
    }
    if (!strcmp(fn,"strchr")) {
        char s[512]; read_cstr(e,arg(e,0),s,sizeof(s));
        char *p = strchr(s,(int)arg(e,1));
        *arg_dwords=0; return p ? arg(e,0)+(uint32_t)(p-s) : 0;
    }
    if (!strcmp(fn,"strrchr")) {
        char s[512]; read_cstr(e,arg(e,0),s,sizeof(s));
        char *p = strrchr(s,(int)arg(e,1));
        *arg_dwords=0; return p ? arg(e,0)+(uint32_t)(p-s) : 0;
    }
    if (!strcmp(fn,"strcspn")) {
        char s[512],r[512]; read_cstr(e,arg(e,0),s,sizeof(s)); read_cstr(e,arg(e,1),r,sizeof(r));
        *arg_dwords=0; return (uint32_t)strcspn(s,r);
    }
    if (!strcmp(fn,"strspn")) {
        char s[512],r[512]; read_cstr(e,arg(e,0),s,sizeof(s)); read_cstr(e,arg(e,1),r,sizeof(r));
        *arg_dwords=0; return (uint32_t)strspn(s,r);
    }
    if (!strcmp(fn,"fopen")) {
        char path[512],mode[16]; read_cstr(e,arg(e,0),path,sizeof(path)); read_cstr(e,arg(e,1),mode,sizeof(mode));
        DBG("[sv_shim] fopen(\"%s\",\"%s\")\n", path, mode);
        int slot=-1;
        for (int i=0;i<MAX_HANDLES;i++) if(!e->host_files[i]){slot=i;break;}
        *arg_dwords=0;
        if (slot<0) return 0;
        FILE *f = fopen(path, mode); // best-effort; expected to be missing (no bundled dicts) -> NULL, matches an optional-file codepath
        if (!f) return 0;
        e->host_files[slot]=f;
        return 0x9F000000u | (uint32_t)slot;
    }
    if (!strcmp(fn,"fread")) {
        uint32_t buf=arg(e,0), sz=arg(e,1), n=arg(e,2), h=arg(e,3);
        *arg_dwords=0;
        if ((h & 0xFF000000u)!=0x9F000000u) return 0;
        int slot=(int)(h & 0xFF); if (slot>=MAX_HANDLES || !e->host_files[slot]) return 0;
        uint32_t total=sz*n; if (total>65536) total=65536;
        uint8_t tmp[65536];
        size_t got = fread(tmp,1,total,e->host_files[slot]);
        if (got) uc_mem_write(e->uc, buf, tmp, got);
        return sz? (uint32_t)(got/sz) : 0;
    }
    if (!strcmp(fn,"fclose")) {
        uint32_t h=arg(e,0); *arg_dwords=0;
        if ((h & 0xFF000000u)==0x9F000000u){ int slot=(int)(h&0xFF); if(slot<MAX_HANDLES && e->host_files[slot]){ fclose(e->host_files[slot]); e->host_files[slot]=NULL; } }
        return 0;
    }

    // ---- USER32: message-window plumbing ----
    if (!strcmp(fn,"RegisterClassA")) {
        uint32_t pwc = arg(e,0);
        uint32_t wndproc = rd32(e, pwc+4); // WNDCLASSA.lpfnWndProc is 2nd field
        e->last_registered_wndproc = wndproc;
        DBG("[sv_shim] RegisterClassA wndproc=0x%x\n", wndproc);
        *arg_dwords=1; return 1; // fake atom
    }
    if (!strcmp(fn,"CreateWindowExA")) {
        uint32_t hwnd = e->next_hwnd++;
        wndproc_for_hwnd_register(e, hwnd, e->last_registered_wndproc);
        DBG("[sv_shim] CreateWindowExA -> hwnd=0x%x wndproc=0x%x\n", hwnd, e->last_registered_wndproc);
        *arg_dwords=12; return hwnd;
    }
    if (!strcmp(fn,"DestroyWindow")) { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"DefWindowProcA")) { *arg_dwords=4; return 0; }
    if (!strcmp(fn,"MessageBeep")) { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"RegisterWindowMessageA")) { *arg_dwords=1; return 0xC211; }
    if (!strcmp(fn,"TranslateMessage")) { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"PostMessageA")) {
        uint32_t hwnd=arg(e,0), msg=arg(e,1), wparam=arg(e,2), lparam=arg(e,3);
        DBG("[sv_shim] PostMessageA hwnd=0x%x msg=0x%x wparam=0x%x lparam=0x%x\n", hwnd,msg,wparam,lparam);
        if (hwnd == CALLER_HWND) {
            if (wparam == 1001 /*sv_EVENT_SPEECH_DONE*/) e->speech_done = 1;
        } else {
            msgq_post(e, hwnd, msg, wparam, lparam);
        }
        *arg_dwords=4; return 1;
    }
    if (!strcmp(fn,"PeekMessageA")) {
        // BOOL PeekMessageA(LPMSG lpMsg, HWND hWnd, UINT wMsgFilterMin, UINT wMsgFilterMax, UINT wRemoveMsg)
        uint32_t pmsg=arg(e,0), hwndFilter=arg(e,1), remove=arg(e,4);
        msg_t m = {0,0,0,0,0};
        int got = msgq_get(e, hwndFilter, remove!=0, &m);
        DBG("[sv_shim] PeekMessageA filter=0x%x remove=%u -> got=%d (hwnd=0x%x msg=0x%x)\n", hwndFilter, remove, got, m.hwnd, m.message);
        if (got) {
            wr32(e,pmsg+0,m.hwnd); wr32(e,pmsg+4,m.message); wr32(e,pmsg+8,m.wparam); wr32(e,pmsg+12,m.lparam);
            wr32(e,pmsg+16,0); wr32(e,pmsg+20,0); // time, pt
        }
        *arg_dwords=5; return got?1:0;
    }
    if (!strcmp(fn,"DispatchMessageA")) {
        uint32_t pmsg=arg(e,0);
        uint32_t hwnd=rd32(e,pmsg+0), message=rd32(e,pmsg+4), wparam=rd32(e,pmsg+8), lparam=rd32(e,pmsg+12);
        uint32_t wndproc = wndproc_for_hwnd(e, hwnd);
        uint32_t result = 0;
        if (wndproc) {
            uint32_t a[4]={hwnd,message,wparam,lparam};
            result = call_sub(e, wndproc, 4, a);
        }
        DBG("[sv_shim] DispatchMessageA hwnd=0x%x msg=0x%x -> wndproc=0x%x result=0x%x\n", hwnd,message,wndproc,result);
        *arg_dwords=1; return result;
    }

    DBG("[sv_shim] UNHANDLED IMPORT: %s\n", fn);
    *arg_dwords=0; return 0;
}

#ifdef SV_DEBUG
static bool hook_mem_invalid(uc_engine *uc, uc_mem_type type, uint64_t address, int size, int64_t value, void *user){
    (void)user;
    uint32_t eip=0; uc_reg_read(uc, UC_X86_REG_EIP, &eip);
    DBG("[sv_shim] MEM_INVALID type=%d addr=0x%llx size=%d value=0x%llx at EIP=0x%x\n",
        (int)type, (unsigned long long)address, size, (unsigned long long)value, eip);
    return false;
}
#endif

static void hook_code(uc_engine *uc, uint64_t address, uint32_t size, void *user){
    sv_engine *e = (sv_engine*)user;
    (void)uc; (void)size;
    int idx = shim_index_for_stub(e, (uint32_t)address);
    if (idx < 0) return;
    int argdw = 0;
    uint32_t ret = run_shim(e, e->shim_name[idx], &argdw);
    uint32_t esp = reg(e, UC_X86_REG_ESP);
    uint32_t retaddr = rd32(e, esp);
    esp += 4 + (uint32_t)argdw*4;
    setreg(e, UC_X86_REG_ESP, esp);
    setreg(e, UC_X86_REG_EAX, ret);
    setreg(e, UC_X86_REG_EIP, retaddr);
}

// ---------------------------------------------------------------------------
// PE loading
// ---------------------------------------------------------------------------
static uint32_t rva_to_off(pe_module *m, uint32_t rva){
    for (int i=0;i<m->nsec;i++){
        uint32_t va=m->secs[i].VirtualAddress, sz=m->secs[i].SizeOfRawData;
        if (rva>=va && rva<va+sz) return m->secs[i].PointerToRawData + (rva-va);
    }
    return 0;
}
static void map_image(sv_engine *e, pe_module *m){
    uint32_t imgsz = (m->opt->SizeOfImage + 0xFFF) & ~0xFFFu;
    uc_mem_map(e->uc, m->base, imgsz, UC_PROT_ALL);
    uc_mem_write(e->uc, m->base, m->file, m->opt->SizeOfHeaders);
    for (int i=0;i<m->nsec;i++){
        SECTION_HEADER *s=&m->secs[i];
        if (s->SizeOfRawData && s->PointerToRawData)
            uc_mem_write(e->uc, m->base + s->VirtualAddress, m->file + s->PointerToRawData, s->SizeOfRawData);
    }
}
static void patch_imports(sv_engine *e, pe_module *m){
    DATA_DIR imp = m->opt->DataDirectory[1];
    if (!imp.VirtualAddress) return;
    IMPORT_DESC *d = (IMPORT_DESC*)(m->file + rva_to_off(m, imp.VirtualAddress));
    for (; d->Name; d++){
        uint32_t thunkRVA = d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk;
        uint32_t *names = (uint32_t*)(m->file + rva_to_off(m, thunkRVA));
        uint32_t iat = m->base + d->FirstThunk;
        for (int k=0; names[k]; k++, iat+=4){
            uint32_t t = names[k];
            char ordbuf[32]; const char *fn;
            if (t & 0x80000000u){ snprintf(ordbuf,sizeof(ordbuf),"ord_%u",t&0xFFFF); fn=ordbuf; }
            else { fn = (char*)(m->file + rva_to_off(m, t) + 2); }
            if (!strcmp(fn,"_adjust_fdiv")) {
                // Data import, not a function: point the IAT slot at a
                // writable dword instead of a code stub.
                static uint32_t slot = 0;
                if (!slot) { slot = heap_alloc(e, 4); wr32(e, slot, 0); }
                wr32(e, iat, slot);
                continue;
            }
            int si = find_or_add_shim(e, fn);
            wr32(e, iat, e->shim_stub[si]);
        }
    }
}
static uint32_t export_rva(pe_module *m, const char *want){
    DATA_DIR ed = m->opt->DataDirectory[0];
    if (!ed.VirtualAddress) return 0;
    EXPORT_DIR *ex = (EXPORT_DIR*)(m->file + rva_to_off(m, ed.VirtualAddress));
    uint32_t *funcs = (uint32_t*)(m->file + rva_to_off(m, ex->AddressOfFunctions));
    uint32_t *names = (uint32_t*)(m->file + rva_to_off(m, ex->AddressOfNames));
    uint16_t *ords  = (uint16_t*)(m->file + rva_to_off(m, ex->AddressOfNameOrdinals));
    for (uint32_t i=0;i<ex->NumberOfNames;i++){
        const char *nm = (char*)(m->file + rva_to_off(m, names[i]));
        if (!strcmp(nm,want)) return funcs[ords[i]];
    }
    return 0;
}
static uint32_t find_module_export(sv_engine *e, uint32_t modbase, const char *want){
    for (int i=0;i<e->nmods;i++){
        if (e->mods[i].base == modbase){
            uint32_t rva = export_rva(&e->mods[i], want);
            return rva ? modbase+rva : 0;
        }
    }
    return 0;
}

static uint32_t call_export_va(sv_engine *e, uint32_t va, int argc, uint32_t *argv){
    uint32_t esp = STACK_TOP & ~0xFu;
    for (int i=argc-1;i>=0;i--){ esp-=4; wr32(e, esp, argv[i]); }
    esp-=4; wr32(e, esp, RET_MAGIC);
    setreg(e, UC_X86_REG_ESP, esp); setreg(e, UC_X86_REG_EBP, 0);
    uc_err err = uc_emu_start(e->uc, va, RET_MAGIC, 0, 0);
    if (err) { DBG("[sv_shim] call_export_va(0x%x) failed: %s at EIP=0x%x ESP=0x%x\n", va, uc_strerror(err), reg(e,UC_X86_REG_EIP), reg(e,UC_X86_REG_ESP)); return 0; }
    return reg(e, UC_X86_REG_EAX);
}

static const char *g_mod_names[MAX_MODULES];
const char *sv_shim_mod_name_hack(sv_engine *e, int i){ (void)e; return (i>=0&&i<MAX_MODULES)?g_mod_names[i]:NULL; }

static int load_module(sv_engine *e, const char *path, const char *shortname){
    FILE *f = fopen(path,"rb");
    if (!f) { DBG("[sv_shim] cannot open %s\n", path); return -1; }
    pe_module *m = &e->mods[e->nmods];
    fseek(f,0,SEEK_END); m->filelen=ftell(f); fseek(f,0,SEEK_SET);
    m->file = (uint8_t*)malloc((size_t)m->filelen);
    if (!m->file || fread(m->file,1,(size_t)m->filelen,f)!=(size_t)m->filelen){ fclose(f); free(m->file); return -1; }
    fclose(f);
    DOS_HEADER *dos=(DOS_HEADER*)m->file;
    FILE_HEADER *fh=(FILE_HEADER*)(m->file+dos->e_lfanew);
    m->opt=(OPT_HEADER*)((uint8_t*)fh+sizeof(FILE_HEADER));
    m->secs=(SECTION_HEADER*)((uint8_t*)m->opt + fh->SizeOfOptionalHeader);
    m->nsec=fh->NumberOfSections;
    m->base=m->opt->ImageBase;
    map_image(e, m);
    patch_imports(e, m);
    g_mod_names[e->nmods] = shortname;
    e->nmods++;
    // DllMain(hinst, DLL_PROCESS_ATTACH=1, 0)
    if (m->opt->AddressOfEntryPoint){
        uint32_t a[3]={m->base,1,0};
        call_export_va(e, m->base + m->opt->AddressOfEntryPoint, 3, a);
    }
    return 0;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
sv_engine *sv_create(const char *base_dll, const char *lang_dll, const char *lang_shortname){
    sv_engine *e = (sv_engine*)calloc(1, sizeof(sv_engine));
    if (!e) return NULL;
    e->heap_ptr = HEAP_BASE; e->tls_next = 1; e->next_hwnd = FIRST_HWND;

    if (uc_open(UC_ARCH_X86, UC_MODE_32, &e->uc)) { free(e); return NULL; }

    uc_mem_map(e->uc, STACK_BASE, STACK_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, SCRATCH_BASE, SCRATCH_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, HEAP_BASE, HEAP_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, TIB_BASE, TIB_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, STUB_BASE, STUB_SIZE, UC_PROT_ALL);
    { uint8_t *fill=(uint8_t*)malloc(STUB_SIZE); memset(fill,0xC3,STUB_SIZE); uc_mem_write(e->uc,STUB_BASE,fill,STUB_SIZE); free(fill); }
    wr32(e, TIB_BASE+0x00, 0xFFFFFFFF);
    wr32(e, TIB_BASE+0x18, TIB_BASE);
    setreg(e, UC_X86_REG_FS_BASE, TIB_BASE);

    uc_hook h1;
    uc_hook_add(e->uc, &h1, UC_HOOK_CODE, (void*)hook_code, e, STUB_BASE, STUB_BASE+STUB_SIZE);
#ifdef SV_DEBUG
    uc_hook h2;
    uc_hook_add(e->uc, &h2, UC_HOOK_MEM_INVALID, (void*)hook_mem_invalid, e, 1, 0);
#endif
    if (load_module(e, lang_dll, lang_shortname) != 0) { sv_destroy(e); return NULL; }
    if (load_module(e, base_dll, "tibase") != 0) { sv_destroy(e); return NULL; }

    return e;
}

void sv_destroy(sv_engine *e){
    if (!e) return;
    if (e->uc) uc_close(e->uc);
    for (int i=0;i<e->nshims;i++) free(e->shim_name[i]);
    for (int i=0;i<e->nmods;i++) free(e->mods[i].file);
    for (int i=0;i<MAX_HANDLES;i++) if (e->host_files[i]) fclose(e->host_files[i]);
    free(e);
}

int sv_sample_rate(const sv_engine *e){ return e->wave_sample_rate ? (int)e->wave_sample_rate : 11025; }

// Pump the multimedia timer callback synchronously until speech is done or
// no more progress is being made (safety valve).
// Drain our fake message queue ourselves, dispatching to each window's
// registered wndproc - this is normally the *host application's* job (its
// own Win32 message loop pumping every window in the process, including
// ones a loaded DLL creates for its own bookkeeping); since we have no such
// host loop, we play that role directly instead of hoping the DLL's own
// code calls PeekMessageA/DispatchMessageA for us (it mostly doesn't - only
// the caller-supplied SVOpenSpeech hwnd notifications are pulled from here
// by real embedding apps).
static void drain_messages(sv_engine *e){
    msg_t m;
    int guard = 256;
    while (guard-- > 0 && msgq_get(e, 0, 1, &m)) {
        uint32_t wndproc = wndproc_for_hwnd(e, m.hwnd);
        if (wndproc) {
            uint32_t a[4] = { m.hwnd, m.message, m.wparam, m.lparam };
            call_sub(e, wndproc, 4, a);
        }
    }
}

static void pump_timer(sv_engine *e){
    int stale = 0;
    int iters = 0;
    DBG("[sv_shim] pump_timer: active=%d proc=0x%x user=0x%x\n", e->timer_active, e->timer_proc, e->timer_user);
    drain_messages(e);
    while (e->timer_active && !e->speech_done && e->pump_budget > 0 && stale < 8) {
        int before_done = e->speech_done;
        int before_active = e->timer_active;
        // LPTIMECALLBACK: void CALLBACK proc(UINT uID,UINT uMsg,DWORD_PTR dwUser,DWORD_PTR dw1,DWORD_PTR dw2)
        uint32_t argv[5] = {1, 0, e->timer_user, 0, 0};
        call_sub(e, e->timer_proc, 5, argv);
        drain_messages(e);
        e->pump_budget--;
        iters++;
        if (e->speech_done == before_done && e->timer_active == before_active) stale++;
        else stale = 0;
    }
    DBG("[sv_shim] pump_timer: done after %d iters, speech_done=%d timer_active=%d budget_left=%d\n",
        iters, e->speech_done, e->timer_active, e->pump_budget);
}

int sv_open(sv_engine *e, int language){
    uint32_t open_va = find_module_export(e, e->mods[e->nmods-1].base, "_SVOpenSpeech@20");
    if (!open_va) { DBG("[sv_shim] no SVOpenSpeech export\n"); return -1; }
    uint32_t handle_slot = heap_alloc(e, 4);
    uint32_t a[5] = { handle_slot, CALLER_HWND, 0, (uint32_t)language, 0 };
    call_export_va(e, open_va, 5, a);
    uint32_t handle = rd32(e, handle_slot);
    DBG("[sv_shim] SVOpenSpeech(language=%d) -> handle=0x%x\n", language, handle);
    e->tls[0] = handle; // stash: tls slot 0 reused as "the" handle for this simple single-session shim
    return handle ? 0 : -1;
}

int sv_set_personality(sv_engine *e, int variant){
    uint32_t va = find_module_export(e, e->mods[e->nmods-1].base, "_SVSetPersonality@8");
    if (!va) { DBG("[sv_shim] no SVSetPersonality export\n"); return -1; }
    uint32_t a[2] = { e->tls[0], (uint32_t)variant };
    call_export_va(e, va, 2, a);
    return 0;
}

int sv_speak(sv_engine *e, const char *text, sv_sample_cb cb, void *ctx){
    if (!e || !text) return -1;
    e->cb = cb; e->cb_ctx = ctx; e->speech_done = 0; e->pump_budget = 20000;

    uint32_t handle = e->tls[0];
    uint32_t len = (uint32_t)strlen(text)+1;
    uint32_t addr = heap_alloc(e, len);
    uc_mem_write(e->uc, addr, text, len);

    uint32_t tts_va = find_module_export(e, e->mods[e->nmods-1].base, "_SVTTS@32");
    if (!tts_va) { DBG("[sv_shim] no SVTTS export\n"); return -1; }
    // _SVTTS@32: (handle, text, ?, ?, hwnd, ?, ?, ?) — 8 args, best-effort
    // guess for the trailing unknowns based on sv.py's call convention.
    uint32_t a[8] = { handle, addr, 0, 0, CALLER_HWND, 0, 0, 0 };
    uint32_t rc = call_export_va(e, tts_va, 8, a);
    DBG("[sv_shim] SVTTS returned 0x%x, pumping timer...\n", rc);

    pump_timer(e);

    e->cb = NULL; e->cb_ctx = NULL;
    return 0;
}

typedef struct { FILE *f; uint32_t nbytes; } wav_ctx;
static void wav_cb(const int16_t *s, size_t n, void *ctx){
    wav_ctx *w=(wav_ctx*)ctx; fwrite(s,2,n,w->f); w->nbytes += (uint32_t)(n*2);
}
int sv_speak_to_wav(sv_engine *e, const char *path, const char *text){
    FILE *f=fopen(path,"wb"); if(!f) return -1;
    uint8_t hdr[44]; memset(hdr,0,44); fwrite(hdr,1,44,f);
    wav_ctx w = { f, 0 };
    sv_speak(e, text, wav_cb, &w);
    uint32_t nbytes = w.nbytes;
    uint32_t rate=11025, byteRate=rate*2, chunk=36+nbytes; uint16_t ch=1,bps=16,ba=2,pcm=1; uint32_t sz16=16;
    fseek(f,0,SEEK_SET);
    fwrite("RIFF",1,4,f); fwrite(&chunk,4,1,f); fwrite("WAVE",1,4,f);
    fwrite("fmt ",1,4,f); fwrite(&sz16,4,1,f); fwrite(&pcm,2,1,f); fwrite(&ch,2,1,f);
    fwrite(&rate,4,1,f); fwrite(&byteRate,4,1,f); fwrite(&ba,2,1,f); fwrite(&bps,2,1,f);
    fwrite("data",1,4,f); fwrite(&nbytes,4,1,f);
    fclose(f);
    return 0;
}
