/*
 * bst_shim.c — Unicorn-emulated BestSpeech engine (see bst_shim.h).
 *
 * Vendored unmodified from cullen-gallagher/BestSpeechForMac
 * (https://github.com/cullen-gallagher/BestSpeechForMac, commit e590b53),
 * a macOS port of BestSpeech/Keynote Gold built around the same b32_tts.dll
 * as providers/keynote.py's Windows-DLL-via-Wine sibling approach - except
 * here the DLL's ~56 Win32 imports are serviced entirely by a hand-written
 * shim under Unicorn CPU emulation, so there's no Windows/Wine dependency
 * at all. Pure C + libunicorn, confirmed to build and run unmodified on
 * Linux (only tested/shipped as macOS before this). No LICENSE file was
 * present in that checkout as of the vendored commit.
 *
 * Refactor of the proof-of-concept pe_emu.c into a per-engine, re-entrant-safe
 * library. All emulator state lives in `struct bst_engine`; Unicorn hooks recover
 * it via user_data. The one subtlety proven out in the PoC: TtsWav will not
 * return until the host calls bstRelBuf once per waveOutWrite, so bst_speak runs
 * TtsWav as a co-routine — when it enters its internal message pump with a buffer
 * pending release, we stop, call bstRelBuf on a separate scratch stack (with
 * TtsWav's register context preserved), then resume.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "bst_shim.h"
#include <unicorn/unicorn.h>

// ---------------------------------------------------------------------------
// Minimal PE structures (no windows.h on Apple platforms)
// ---------------------------------------------------------------------------
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
// Emulated memory map (per engine)
// ---------------------------------------------------------------------------
#define IMAGE_BASE    0x10000000u
#define STACK_BASE    0x00300000u
#define STACK_SIZE    0x00100000u
#define STACK_TOP     (STACK_BASE + STACK_SIZE - 0x100)
#define HEAP_BASE     0x40000000u
#define HEAP_SIZE     0x08000000u
#define TIB_BASE      0x00100000u
#define TIB_SIZE      0x00001000u
#define SCRATCH_BASE  0x00200000u
#define SCRATCH_SIZE  0x00080000u
#define SCRATCH_TOP   (SCRATCH_BASE + SCRATCH_SIZE - 0x100)
#define STUB_BASE     0x70000000u
#define STUB_SIZE     0x00010000u
#define RET_MAGIC     0x0000DEADu
#define PUMP_ADDR     0x1000eea0u   // head of TtsWav's internal message pump

// BST parameter selectors (from @rommix0's BST.h, via b32_wrapper.cpp)
#define BST_RATE_SETTING       257
#define BST_GAIN_SETTING       258
#define BST_BIT_DEPTH_SETTING  4097

#define MAX_SHIMS 256

struct bst_engine {
    uc_engine *uc;
    uint8_t   *file;          // raw DLL bytes (kept for export lookups)
    long       filelen;
    OPT_HEADER *opt;
    SECTION_HEADER *secs;
    int        nsec;

    uint32_t   heap_ptr;
    uint32_t   tts;           // engine handle from bstCreate
    uint32_t   ttswav_va, relbuf_va;

    // import shim table
    char      *shim_name[MAX_SHIMS];
    uint32_t   shim_stub[MAX_SHIMS];
    int        nshims;

    // TLS / misc Win32 state
    uint32_t   tls[512];
    int        tls_next;
    uint32_t   last_error;
    uint32_t   cmdline, envstr; // lazily-allocated empty strings

    // buffer-release handshake
    int        pending_relbuf;
    volatile int yield;
    int        write_n;

    // active synthesis callback
    bst_sample_cb cb;
    void         *ctx;
};

// ---------------------------------------------------------------------------
// Unicorn helpers (per engine)
// ---------------------------------------------------------------------------
static uint32_t rd32(bst_engine *e, uint32_t a){ uint32_t v=0; uc_mem_read(e->uc,a,&v,4); return v; }
static void     wr32(bst_engine *e, uint32_t a, uint32_t v){ uc_mem_write(e->uc,a,&v,4); }
static uint32_t reg(bst_engine *e, int r){ uint32_t v=0; uc_reg_read(e->uc,r,&v); return v; }
static void     setreg(bst_engine *e, int r, uint32_t v){ uc_reg_write(e->uc,r,&v); }
static uint32_t arg(bst_engine *e, int n){ return rd32(e, reg(e,UC_X86_REG_ESP) + 4 + n*4); }

static uint32_t heap_alloc(bst_engine *e, uint32_t size){
    uint32_t p = (e->heap_ptr + 15) & ~15u;
    e->heap_ptr = p + (size ? size : 16);
    if (e->heap_ptr > HEAP_BASE + HEAP_SIZE) return 0;
    static uint8_t z[4096];
    uint32_t left=size, a=p;
    while(left){ uint32_t c=left>sizeof(z)?sizeof(z):left; uc_mem_write(e->uc,a,z,c); a+=c; left-=c; }
    return p;
}

// ---------------------------------------------------------------------------
// Built-in voice table (name, inline prefix, rate prefix) from b32_wrapper.cpp
// ---------------------------------------------------------------------------
static const char *g_voice_data[] = {
    "Fred",    "~v0]~e3]~h0]~u0]~f80]",    "~r0]",
    "Sara",    "~v2]~e3]~h-20]~u0]~f175]", "~r0]",
    "Hary",    "~v3]~e3]~h10]~u0]~f65]",   "~r5]",
    "Wendy",   "~v2]~e1]~h50]~u0]~f150]",  "~r-5]",
    "Dexter",  "~v6]~e6]~h0]~u-25]~f90]",  "~r7]",
    "Alien",   "~v4]~e6]~h-50]~u-20]~f115]","~r-20]",
    "Kit",     "~v5]~e3]~h40]~u0]~f230]",  "~r-10]",
    "Bruno",   "~v3]~e3]~h50]~u0]~f60]",   "~r8]",
    "Ghost",   "~v3]~e2]~h50]~u0]~f60]",   "~r8]",
    "Peeper",  "~v2]~e2]~h0]~u5]~f80]",    "~r0]",
    "Dracula", "~v3]~e3]~h45]~u-5]~f47]",  "~r10]",
    "Granny",  "~v4]~e3]~h-60]~u0]~f350]", "~r20]",
    "Martha",  "~v6]~e4]~h100]~u-5]~f300]","~r-10]",
    "Tim",     "~v3]~e4]~h-10]~u0]~f60]",  "~r-10]",
    NULL, NULL, NULL
};
int bst_voice_count(void){ int n=0; for(int i=0; g_voice_data[i]; i+=3) n++; return n; }
const char *bst_voice_name(int idx){ return (idx>=0 && idx<bst_voice_count()) ? g_voice_data[idx*3] : NULL; }
const char *bst_voice_prefix(int idx){ return (idx>=0 && idx<bst_voice_count()) ? g_voice_data[idx*3+1] : NULL; }

// ---------------------------------------------------------------------------
// Import shims
// ---------------------------------------------------------------------------
static int shim_index_for_stub(bst_engine *e, uint32_t addr){
    if (addr < STUB_BASE || addr >= STUB_BASE + STUB_SIZE) return -1;
    return (int)((addr - STUB_BASE) / 8);
}
static int find_or_add_shim(bst_engine *e, const char *name){
    for (int i=0;i<e->nshims;i++) if (!strcmp(e->shim_name[i],name)) return i;
    int i = e->nshims++;
    e->shim_name[i] = strdup(name);
    e->shim_stub[i] = STUB_BASE + i*8;
    return i;
}

// Behavior of each imported function. Returns EAX; sets *arg_dwords for stdcall
// stack cleanup. Every import here is stdcall (WINAPI).
static uint32_t run_shim(bst_engine *e, const char *fn, int *arg_dwords){
    // WINMM: capture audio, never play it
    if (!strcmp(fn,"waveOutOpen")) {
        uint32_t phwo=arg(e,0); if (phwo) wr32(e,phwo,0xBEEF);
        *arg_dwords=6; return 0;
    }
    if (!strcmp(fn,"waveOutPrepareHeader"))   { *arg_dwords=3; return 0; }
    if (!strcmp(fn,"waveOutUnprepareHeader")) { *arg_dwords=3; return 0; }
    if (!strcmp(fn,"waveOutReset"))           { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"waveOutClose"))           { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"waveOutWrite")) {
        uint32_t pwh = arg(e,1);
        uint32_t lpData = rd32(e, pwh + 0);
        uint32_t dwLen  = rd32(e, pwh + 4);
        if (lpData && dwLen && dwLen < 0x02000000 && e->cb) {
            int16_t *tmp = (int16_t*)malloc(dwLen);
            if (tmp) {
                uc_mem_read(e->uc, lpData, tmp, dwLen);
                e->cb(tmp, dwLen/2, e->ctx);
                free(tmp);
            }
        }
        // Mark buffer done (we consumed it synchronously) and queue its release.
        uint32_t flags = rd32(e, pwh + 16);
        wr32(e, pwh + 16, (flags | 0x1u) & ~0x2u);   // set WHDR_DONE, clear INQUEUE
        e->write_n++;
        e->pending_relbuf++;
        *arg_dwords=3; return 0;
    }
    // memory allocators (bump)
    if (!strcmp(fn,"GlobalAlloc")) { *arg_dwords=2; return heap_alloc(e, arg(e,1)); }
    if (!strcmp(fn,"LocalAlloc"))  { *arg_dwords=2; return heap_alloc(e, arg(e,1)); }
    if (!strcmp(fn,"VirtualAlloc")){ *arg_dwords=4; return heap_alloc(e, arg(e,1)?arg(e,1):4096); }
    if (!strcmp(fn,"GlobalLock"))  { *arg_dwords=1; return arg(e,0); }
    if (!strcmp(fn,"LocalLock"))   { *arg_dwords=1; return arg(e,0); }
    if (!strcmp(fn,"GlobalUnlock")){ *arg_dwords=1; return 1; }
    if (!strcmp(fn,"LocalUnlock")) { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"GlobalFree"))  { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"LocalFree"))   { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"VirtualFree")) { *arg_dwords=3; return 1; }
    // TLS
    if (!strcmp(fn,"TlsAlloc"))    { *arg_dwords=0; return e->tls_next++; }
    if (!strcmp(fn,"TlsFree"))     { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"TlsSetValue")) { uint32_t i=arg(e,0); if(i<512) e->tls[i]=arg(e,1); *arg_dwords=2; return 1; }
    if (!strcmp(fn,"TlsGetValue")) { uint32_t i=arg(e,0); *arg_dwords=1; return i<512?e->tls[i]:0; }
    // critical sections: no-ops
    if (!strcmp(fn,"InitializeCriticalSection")){ *arg_dwords=1; return 0; }
    if (!strcmp(fn,"DeleteCriticalSection"))    { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"EnterCriticalSection"))     { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"LeaveCriticalSection"))     { *arg_dwords=1; return 0; }
    // locale / CRT startup
    if (!strcmp(fn,"GetVersion"))         { *arg_dwords=0; return 0x00000004; }
    if (!strcmp(fn,"GetACP"))             { *arg_dwords=0; return 1252; }
    if (!strcmp(fn,"GetOEMCP"))           { *arg_dwords=0; return 437; }
    if (!strcmp(fn,"GetCPInfo"))          { uint32_t p=arg(e,1); wr32(e,p,1); *arg_dwords=2; return 1; }
    if (!strcmp(fn,"GetLastError"))       { *arg_dwords=0; return e->last_error; }
    if (!strcmp(fn,"GetCurrentThreadId")) { *arg_dwords=0; return 0x1000; }
    if (!strcmp(fn,"GetModuleHandleA"))   { *arg_dwords=1; return IMAGE_BASE; }
    if (!strcmp(fn,"GetModuleFileNameA")) { uint32_t p=arg(e,1),n=arg(e,2); if(p&&n){uint8_t z=0;uc_mem_write(e->uc,p,&z,1);} *arg_dwords=3; return 0; }
    if (!strcmp(fn,"GetProcAddress"))     { *arg_dwords=2; return 0; }
    if (!strcmp(fn,"GetStdHandle"))       { *arg_dwords=1; return 0xFF00 | (arg(e,0)&0xFF); }
    if (!strcmp(fn,"GetFileType"))        { *arg_dwords=1; return 2; }
    if (!strcmp(fn,"SetStdHandle"))       { *arg_dwords=2; return 1; }
    if (!strcmp(fn,"GetStartupInfoA"))    { uint32_t p=arg(e,0); for(int i=0;i<68;i+=4) wr32(e,p+i,0); wr32(e,p,68); *arg_dwords=1; return 0; }
    if (!strcmp(fn,"GetCommandLineA"))    { if(!e->cmdline){e->cmdline=heap_alloc(e,8);uint8_t b[2]={0,0};uc_mem_write(e->uc,e->cmdline,b,2);} *arg_dwords=0; return e->cmdline; }
    if (!strcmp(fn,"GetEnvironmentStrings")){ if(!e->envstr){e->envstr=heap_alloc(e,8);uint8_t b[2]={0,0};uc_mem_write(e->uc,e->envstr,b,2);} *arg_dwords=0; return e->envstr; }
    if (!strcmp(fn,"SetEnvironmentVariableA")){ *arg_dwords=2; return 1; }
    if (!strcmp(fn,"GetTimeZoneInformation")){ *arg_dwords=1; return 0; }
    if (!strcmp(fn,"GetLocalTime"))       { uint32_t p=arg(e,0); for(int i=0;i<16;i+=4) wr32(e,p+i,0); *arg_dwords=1; return 0; }
    if (!strcmp(fn,"WriteFile"))          { uint32_t pw=arg(e,3); if(pw) wr32(e,pw,arg(e,2)); *arg_dwords=5; return 1; }
    if (!strcmp(fn,"FlushFileBuffers"))   { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"SetFilePointer"))     { *arg_dwords=4; return 0; }
    if (!strcmp(fn,"CloseHandle"))        { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"ExitProcess"))        { uc_emu_stop(e->uc); *arg_dwords=1; return 0; }
    // code-page conversions (treat as latin-1/1252, one byte per wide char)
    if (!strcmp(fn,"MultiByteToWideChar")) {
        uint32_t src=arg(e,2); int slen=(int)arg(e,3); uint32_t dst=arg(e,4); int dlen=(int)arg(e,5);
        int n=0; uint32_t s=src;
        for(;;){ uint8_t b=0; uc_mem_read(e->uc,s++,&b,1);
            if(slen<0){ if(!b){ if(dst&&dlen&&n<dlen){uint16_t w=0;uc_mem_write(e->uc,dst+n*2,&w,2);} n++; break; } }
            else { if(n>=slen) break; }
            if(dst&&dlen&&n<dlen){ uint16_t w=b; uc_mem_write(e->uc,dst+n*2,&w,2); }
            n++;
        }
        *arg_dwords=6; return n;
    }
    if (!strcmp(fn,"WideCharToMultiByte")) {
        uint32_t src=arg(e,2); int slen=(int)arg(e,3); uint32_t dst=arg(e,4); int dlen=(int)arg(e,5);
        int n=0; uint32_t s=src;
        for(;;){ uint16_t w=0; uc_mem_read(e->uc,s,&w,2); s+=2;
            if(slen<0){ if(!w){ if(dst&&dlen&&n<dlen){uint8_t z=0;uc_mem_write(e->uc,dst+n,&z,1);} n++; break; } }
            else { if(n>=slen) break; }
            if(dst&&dlen&&n<dlen){ uint8_t b=(uint8_t)w; uc_mem_write(e->uc,dst+n,&b,1); }
            n++;
        }
        *arg_dwords=8; return n;
    }
    // USER32: message-window plumbing (mostly inert; we drive the pump ourselves)
    if (!strcmp(fn,"RegisterClassA"))   { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"CreateWindowExA"))  { *arg_dwords=12; return 0x00CC0000; }
    if (!strcmp(fn,"DefWindowProcA"))   { *arg_dwords=4; return 0; }
    if (!strcmp(fn,"MessageBeep"))      { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"PeekMessageA"))     { *arg_dwords=5; return 0; }
    if (!strcmp(fn,"TranslateMessage")) { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"DispatchMessageA")) { *arg_dwords=1; return 0; }

    // Unknown import: return 0 and hope it's non-essential.
    *arg_dwords=0; return 0;
}

// Code hook: services the pump-loop yield and dispatches import stubs.
static void hook_code(uc_engine *uc, uint64_t address, uint32_t size, void *user){
    bst_engine *e = (bst_engine*)user;
    if ((uint32_t)address == PUMP_ADDR) {
        if (e->pending_relbuf > 0) { e->yield = 1; uc_emu_stop(e->uc); }
        return;
    }
    int idx = shim_index_for_stub(e, (uint32_t)address);
    if (idx < 0) return;
    int argdw = 0;
    uint32_t ret = run_shim(e, e->shim_name[idx], &argdw);
    uint32_t esp = reg(e, UC_X86_REG_ESP);
    uint32_t retaddr = rd32(e, esp);
    esp += 4 + argdw*4;
    setreg(e, UC_X86_REG_ESP, esp);
    setreg(e, UC_X86_REG_EAX, ret);
    setreg(e, UC_X86_REG_EIP, retaddr);
}

// ---------------------------------------------------------------------------
// PE loading
// ---------------------------------------------------------------------------
static uint32_t rva_to_off(bst_engine *e, uint32_t rva){
    for (int i=0;i<e->nsec;i++){
        uint32_t va=e->secs[i].VirtualAddress, sz=e->secs[i].SizeOfRawData;
        if (rva>=va && rva<va+sz) return e->secs[i].PointerToRawData + (rva-va);
    }
    return 0;
}
static void map_image(bst_engine *e){
    uint32_t imgsz = (e->opt->SizeOfImage + 0xFFF) & ~0xFFFu;
    uc_mem_map(e->uc, IMAGE_BASE, imgsz, UC_PROT_ALL);
    uc_mem_write(e->uc, IMAGE_BASE, e->file, e->opt->SizeOfHeaders);
    for (int i=0;i<e->nsec;i++){
        SECTION_HEADER *s=&e->secs[i];
        if (s->SizeOfRawData && s->PointerToRawData)
            uc_mem_write(e->uc, IMAGE_BASE + s->VirtualAddress, e->file + s->PointerToRawData, s->SizeOfRawData);
    }
}
static void patch_imports(bst_engine *e){
    DATA_DIR imp = e->opt->DataDirectory[1];
    if (!imp.VirtualAddress) return;
    IMPORT_DESC *d = (IMPORT_DESC*)(e->file + rva_to_off(e, imp.VirtualAddress));
    for (; d->Name; d++){
        uint32_t thunkRVA = d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk;
        uint32_t *names = (uint32_t*)(e->file + rva_to_off(e, thunkRVA));
        uint32_t iat = IMAGE_BASE + d->FirstThunk;
        for (int k=0; names[k]; k++, iat+=4){
            uint32_t t = names[k];
            char ordbuf[32]; const char *fn;
            if (t & 0x80000000u){ snprintf(ordbuf,sizeof(ordbuf),"ord_%u",t&0xFFFF); fn=ordbuf; }
            else { fn = (char*)(e->file + rva_to_off(e, t) + 2); }
            int si = find_or_add_shim(e, fn);
            wr32(e, iat, e->shim_stub[si]);
        }
    }
}
static uint32_t export_rva(bst_engine *e, const char *want){
    DATA_DIR ed = e->opt->DataDirectory[0];
    EXPORT_DIR *ex = (EXPORT_DIR*)(e->file + rva_to_off(e, ed.VirtualAddress));
    uint32_t *funcs = (uint32_t*)(e->file + rva_to_off(e, ex->AddressOfFunctions));
    uint32_t *names = (uint32_t*)(e->file + rva_to_off(e, ex->AddressOfNames));
    uint16_t *ords  = (uint16_t*)(e->file + rva_to_off(e, ex->AddressOfNameOrdinals));
    for (uint32_t i=0;i<ex->NumberOfNames;i++){
        const char *nm = (char*)(e->file + rva_to_off(e, names[i]));
        if (!strcmp(nm,want)) return funcs[ords[i]];
    }
    return 0;
}

// Call an exported cdecl function; ESP is reset each call (safe for our uses).
static uint32_t call_export_va(bst_engine *e, uint32_t va, int argc, uint32_t *argv){
    uint32_t esp = STACK_TOP & ~0xFu;
    for (int i=argc-1;i>=0;i--){ esp-=4; wr32(e, esp, argv[i]); }
    esp-=4; wr32(e, esp, RET_MAGIC);
    setreg(e, UC_X86_REG_ESP, esp); setreg(e, UC_X86_REG_EBP, 0);
    uc_err err = uc_emu_start(e->uc, va, RET_MAGIC, 0, 0);
    if (err) return 0;
    return reg(e, UC_X86_REG_EAX);
}

// ---------------------------------------------------------------------------
// Co-routine driver: run TtsWav, servicing buffer-release yields
// ---------------------------------------------------------------------------
typedef struct { uint32_t esp,ebp,eip,eax,ebx,ecx,edx,esi,edi,eflags; } regs_t;
static void save_regs(bst_engine *e, regs_t *r){
    r->esp=reg(e,UC_X86_REG_ESP); r->ebp=reg(e,UC_X86_REG_EBP); r->eip=reg(e,UC_X86_REG_EIP);
    r->eax=reg(e,UC_X86_REG_EAX); r->ebx=reg(e,UC_X86_REG_EBX); r->ecx=reg(e,UC_X86_REG_ECX);
    r->edx=reg(e,UC_X86_REG_EDX); r->esi=reg(e,UC_X86_REG_ESI); r->edi=reg(e,UC_X86_REG_EDI);
    r->eflags=reg(e,UC_X86_REG_EFLAGS);
}
static void restore_regs(bst_engine *e, regs_t *r){
    setreg(e,UC_X86_REG_ESP,r->esp); setreg(e,UC_X86_REG_EBP,r->ebp); setreg(e,UC_X86_REG_EIP,r->eip);
    setreg(e,UC_X86_REG_EAX,r->eax); setreg(e,UC_X86_REG_EBX,r->ebx); setreg(e,UC_X86_REG_ECX,r->ecx);
    setreg(e,UC_X86_REG_EDX,r->edx); setreg(e,UC_X86_REG_ESI,r->esi); setreg(e,UC_X86_REG_EDI,r->edi);
    setreg(e,UC_X86_REG_EFLAGS,r->eflags);
}
static void call_relbuf(bst_engine *e){
    uint32_t esp = SCRATCH_TOP & ~0xFu;
    esp-=4; wr32(e, esp, e->tts);
    esp-=4; wr32(e, esp, RET_MAGIC);
    setreg(e, UC_X86_REG_ESP, esp); setreg(e, UC_X86_REG_EBP, 0);
    uc_emu_start(e->uc, e->relbuf_va, RET_MAGIC, 0, 0);
}
static void drive_ttswav(bst_engine *e, uint32_t textaddr){
    uint32_t esp = STACK_TOP & ~0xFu;
    uint32_t a[3]={e->tts, 0, textaddr};
    for (int i=2;i>=0;i--){ esp-=4; wr32(e, esp, a[i]); }
    esp-=4; wr32(e, esp, RET_MAGIC);
    setreg(e, UC_X86_REG_ESP, esp); setreg(e, UC_X86_REG_EBP, 0);
    uint32_t eip = e->ttswav_va;
    for (;;){
        e->yield = 0;
        uc_err err = uc_emu_start(e->uc, eip, RET_MAGIC, 0, 0);
        if (err) return;
        eip = reg(e, UC_X86_REG_EIP);
        if (!e->yield) return;                 // reached RET_MAGIC: done
        regs_t saved; save_regs(e, &saved);
        call_relbuf(e);
        restore_regs(e, &saved);
        e->pending_relbuf--;
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
bst_engine *bst_create(const char *dll_path){
    FILE *f = fopen(dll_path,"rb");
    if (!f) return NULL;
    bst_engine *e = (bst_engine*)calloc(1, sizeof(bst_engine));
    if (!e){ fclose(f); return NULL; }
    e->heap_ptr = HEAP_BASE; e->tls_next = 1;

    fseek(f,0,SEEK_END); e->filelen=ftell(f); fseek(f,0,SEEK_SET);
    e->file = (uint8_t*)malloc(e->filelen);
    if (!e->file || fread(e->file,1,e->filelen,f)!=(size_t)e->filelen){ fclose(f); free(e->file); free(e); return NULL; }
    fclose(f);

    DOS_HEADER *dos=(DOS_HEADER*)e->file;
    FILE_HEADER *fh=(FILE_HEADER*)(e->file+dos->e_lfanew);
    e->opt=(OPT_HEADER*)((uint8_t*)fh+sizeof(FILE_HEADER));
    e->secs=(SECTION_HEADER*)((uint8_t*)e->opt + fh->SizeOfOptionalHeader);
    e->nsec=fh->NumberOfSections;
    if (e->opt->ImageBase != IMAGE_BASE){ free(e->file); free(e); return NULL; }

    if (uc_open(UC_ARCH_X86, UC_MODE_32, &e->uc)){ free(e->file); free(e); return NULL; }

    map_image(e);
    uc_mem_map(e->uc, STACK_BASE, STACK_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, HEAP_BASE, HEAP_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, TIB_BASE, TIB_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, SCRATCH_BASE, SCRATCH_SIZE, UC_PROT_ALL);
    uc_mem_map(e->uc, STUB_BASE, STUB_SIZE, UC_PROT_ALL);
    { uint8_t *fill=(uint8_t*)malloc(STUB_SIZE); memset(fill,0xC3,STUB_SIZE); uc_mem_write(e->uc,STUB_BASE,fill,STUB_SIZE); free(fill); }

    // Minimal TIB so any fs:[..] access is valid.
    wr32(e, TIB_BASE+0x00, 0xFFFFFFFF);
    wr32(e, TIB_BASE+0x18, TIB_BASE);
    setreg(e, UC_X86_REG_FS_BASE, TIB_BASE);

    patch_imports(e);

    uc_hook h1, h2;
    uc_hook_add(e->uc, &h1, UC_HOOK_CODE, (void*)hook_code, e, STUB_BASE, STUB_BASE+STUB_SIZE);
    uc_hook_add(e->uc, &h2, UC_HOOK_CODE, (void*)hook_code, e, PUMP_ADDR, PUMP_ADDR+1);

    // Run the DLL CRT/entry: DllMain(hinst, DLL_PROCESS_ATTACH=1, 0)
    if (e->opt->AddressOfEntryPoint){
        uint32_t a[3]={IMAGE_BASE,1,0};
        call_export_va(e, IMAGE_BASE + e->opt->AddressOfEntryPoint, 3, a);
    }

    e->ttswav_va = IMAGE_BASE + export_rva(e, "TtsWav");
    e->relbuf_va = IMAGE_BASE + export_rva(e, "bstRelBuf");
    uint32_t bstCreate_va = IMAGE_BASE + export_rva(e, "bstCreate");
    uint32_t setparams_va = IMAGE_BASE + export_rva(e, "bstSetParams");
    if (!export_rva(e,"TtsWav") || !export_rva(e,"bstRelBuf") || !export_rva(e,"bstCreate")){
        bst_destroy(e); return NULL;
    }

    // bstCreate(long*& handle_out): give it a heap slot to fill.
    uint32_t handle_slot = heap_alloc(e, 4);
    { uint32_t a[1]={handle_slot}; call_export_va(e, bstCreate_va, 1, a); }
    e->tts = rd32(e, handle_slot);
    if (!e->tts){ bst_destroy(e); return NULL; }

    // 16-bit PCM output.
    if (setparams_va != IMAGE_BASE){ uint32_t a[3]={e->tts, BST_BIT_DEPTH_SETTING, 16}; call_export_va(e, setparams_va, 3, a); }
    return e;
}

void bst_destroy(bst_engine *e){
    if (!e) return;
    if (e->uc) uc_close(e->uc);
    for (int i=0;i<e->nshims;i++) free(e->shim_name[i]);
    free(e->file);
    free(e);
}

int bst_sample_rate(const bst_engine *e){ (void)e; return 11025; }

int bst_speak(bst_engine *e, const char *text, bst_sample_cb cb, void *ctx){
    if (!e || !text) return -1;
    e->cb = cb; e->ctx = ctx;
    e->pending_relbuf = 0; e->write_n = 0; e->yield = 0;
    uint32_t len = (uint32_t)strlen(text) + 1;
    uint32_t addr = heap_alloc(e, len);
    if (!addr) return -1;
    uc_mem_write(e->uc, addr, text, len);
    drive_ttswav(e, addr);
    e->cb = NULL; e->ctx = NULL;
    return 0;
}

// ---- WAV convenience ----
typedef struct { FILE *f; uint32_t nbytes; } wav_ctx;
static void wav_cb(const int16_t *s, size_t n, void *ctx){
    wav_ctx *w=(wav_ctx*)ctx; fwrite(s,2,n,w->f); w->nbytes += (uint32_t)(n*2);
}
int bst_speak_to_wav(bst_engine *e, const char *path, const char *text){
    if (!e || !path || !text) return -1;
    FILE *f=fopen(path,"wb"); if(!f) return -1;
    uint8_t hdr[44]; memset(hdr,0,44); fwrite(hdr,1,44,f);   // placeholder
    wav_ctx w={f,0};
    bst_speak(e, text, wav_cb, &w);
    // patch header
    uint32_t rate=11025, byteRate=rate*2, chunk=36+w.nbytes; uint16_t ch=1,bps=16,ba=2,pcm=1; uint32_t sz16=16;
    fseek(f,0,SEEK_SET);
    fwrite("RIFF",1,4,f); fwrite(&chunk,4,1,f); fwrite("WAVE",1,4,f);
    fwrite("fmt ",1,4,f); fwrite(&sz16,4,1,f); fwrite(&pcm,2,1,f); fwrite(&ch,2,1,f);
    fwrite(&rate,4,1,f); fwrite(&byteRate,4,1,f); fwrite(&ba,2,1,f); fwrite(&bps,2,1,f);
    fwrite("data",1,4,f); fwrite(&w.nbytes,4,1,f);
    fclose(f);
    return 0;
}
