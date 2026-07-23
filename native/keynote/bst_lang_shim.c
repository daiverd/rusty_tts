/*
 * bst_lang_shim.c — Unicorn-emulated shim for the 2006 "Lingvosoft"
 * BestSpeech language DLLs (see bst_lang_shim.h and roms/keynote/lang/
 * PROVENANCE.md). Same PE-loading/import-shim technique as bst_shim.c
 * (vendored from cullen-gallagher/BestSpeechForMac), rewritten for this
 * DLL family's own export/import surface: Init_TTS/Say_TTS/DeInit_TTS
 * (all cdecl, Say_TTS takes one UTF-16 wchar_t* argument), and a plain
 * MSVC-CRT-startup import set (KERNEL32 heap/TLS/critical-section/locale
 * calls + WINMM waveOut*) with no USER32 - so unlike bst_shim.c, no
 * message-pump/coroutine driver is needed: each exported call just runs
 * to completion in a single uc_emu_start.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "bst_lang_shim.h"
#include <unicorn/unicorn.h>

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

#define IMAGE_BASE    0x10000000u
#define STACK_BASE    0x00300000u
#define STACK_SIZE    0x00100000u
#define STACK_TOP     (STACK_BASE + STACK_SIZE - 0x100)
#define HEAP_BASE     0x40000000u
#define HEAP_SIZE     0x08000000u
#define TIB_BASE      0x00100000u
#define TIB_SIZE      0x00001000u
#define STUB_BASE     0x70000000u
#define STUB_SIZE     0x00010000u
#define RET_MAGIC     0x0000DEADu
#define MAX_SHIMS 256

struct bstl_engine {
    uc_engine *uc;
    uint8_t   *file;
    long       filelen;
    OPT_HEADER *opt;
    SECTION_HEADER *secs;
    int        nsec;

    uint32_t   heap_ptr;
    uint32_t   say_va, deinit_va;

    char      *shim_name[MAX_SHIMS];
    uint32_t   shim_stub[MAX_SHIMS];
    int        nshims;

    uint32_t   tls[512];
    int        tls_next;
    uint32_t   last_error;
    uint32_t   cmdline, envstr, envstrw;

    bstl_sample_cb cb;
    void          *ctx;
};

static uint32_t rd32(bstl_engine *e, uint32_t a){ uint32_t v=0; uc_mem_read(e->uc,a,&v,4); return v; }
static void     wr32(bstl_engine *e, uint32_t a, uint32_t v){ uc_mem_write(e->uc,a,&v,4); }
static uint32_t reg(bstl_engine *e, int r){ uint32_t v=0; uc_reg_read(e->uc,r,&v); return v; }
static void     setreg(bstl_engine *e, int r, uint32_t v){ uc_reg_write(e->uc,r,&v); }
static uint32_t arg(bstl_engine *e, int n){ return rd32(e, reg(e,UC_X86_REG_ESP) + 4 + n*4); }

static uint32_t heap_alloc(bstl_engine *e, uint32_t size){
    uint32_t p = (e->heap_ptr + 15) & ~15u;
    e->heap_ptr = p + (size ? size : 16);
    if (e->heap_ptr > HEAP_BASE + HEAP_SIZE) return 0;
    static uint8_t z[4096];
    uint32_t left=size, a=p;
    while(left){ uint32_t c=left>sizeof(z)?sizeof(z):left; uc_mem_write(e->uc,a,z,c); a+=c; left-=c; }
    return p;
}

static int shim_index_for_stub(bstl_engine *e, uint32_t addr){
    (void)e;
    if (addr < STUB_BASE || addr >= STUB_BASE + STUB_SIZE) return -1;
    return (int)((addr - STUB_BASE) / 8);
}
static int find_or_add_shim(bstl_engine *e, const char *name){
    for (int i=0;i<e->nshims;i++) if (!strcmp(e->shim_name[i],name)) return i;
    int i = e->nshims++;
    e->shim_name[i] = strdup(name);
    e->shim_stub[i] = STUB_BASE + i*8;
    return i;
}

// Every import here is __stdcall (WINAPI); *arg_dwords must match the real
// signature's stack-arg count exactly, or the callee-cleanup we simulate
// after each stub call corrupts the stack.
static uint32_t run_shim(bstl_engine *e, const char *fn, int *arg_dwords){
    // WINMM: capture audio, never play it (same behavior as bst_shim.c)
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
        uint32_t flags = rd32(e, pwh + 16);
        wr32(e, pwh + 16, (flags | 0x1u) & ~0x2u);
        *arg_dwords=3; return 0;
    }
    // Heap*
    if (!strcmp(fn,"HeapCreate"))  { *arg_dwords=3; return 1; }   // fake nonzero handle
    if (!strcmp(fn,"HeapDestroy")) { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"HeapAlloc"))   { *arg_dwords=3; return heap_alloc(e, arg(e,2)); }
    if (!strcmp(fn,"HeapFree"))    { *arg_dwords=3; return 1; }   // bump allocator: leak, don't free
    if (!strcmp(fn,"HeapReAlloc")) {
        // No per-block size tracking in this bump allocator, so this can't
        // preserve old contents beyond a best-effort copy of the new size.
        // Short single-utterance requests are not expected to stress this.
        uint32_t newsize = arg(e,3);
        *arg_dwords=4; return heap_alloc(e, newsize);
    }
    // Other memory allocators (kept for parity with bst_shim.c's family)
    if (!strcmp(fn,"VirtualAlloc")){ *arg_dwords=4; return heap_alloc(e, arg(e,1)?arg(e,1):4096); }
    if (!strcmp(fn,"VirtualFree")) { *arg_dwords=3; return 1; }
    // TLS
    if (!strcmp(fn,"TlsAlloc"))    { *arg_dwords=0; return e->tls_next++; }
    if (!strcmp(fn,"TlsFree"))     { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"TlsSetValue")) { uint32_t i=arg(e,0); if(i<512) e->tls[i]=arg(e,1); *arg_dwords=2; return 1; }
    if (!strcmp(fn,"TlsGetValue")) { uint32_t i=arg(e,0); *arg_dwords=1; return i<512?e->tls[i]:0; }
    // Critical sections: no-ops (single-threaded emulation)
    if (!strcmp(fn,"InitializeCriticalSection")){ *arg_dwords=1; return 0; }
    if (!strcmp(fn,"DeleteCriticalSection"))    { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"EnterCriticalSection"))     { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"LeaveCriticalSection"))     { *arg_dwords=1; return 0; }
    // Process/thread/handle bookkeeping
    if (!strcmp(fn,"Sleep"))              { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"CloseHandle"))        { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"ExitProcess"))        { uc_emu_stop(e->uc); *arg_dwords=1; return 0; }
    if (!strcmp(fn,"TerminateProcess"))   { uc_emu_stop(e->uc); *arg_dwords=2; return 1; }
    if (!strcmp(fn,"GetCurrentProcess"))  { *arg_dwords=0; return 0xFFFFFFFF; }
    if (!strcmp(fn,"GetCurrentThreadId")) { *arg_dwords=0; return 0x1000; }
    if (!strcmp(fn,"SetHandleCount"))     { *arg_dwords=1; return arg(e,0); }
    if (!strcmp(fn,"GetLastError"))       { *arg_dwords=0; return e->last_error; }
    if (!strcmp(fn,"SetLastError"))       { e->last_error=arg(e,0); *arg_dwords=1; return 0; }
    // Locale / CRT startup
    if (!strcmp(fn,"GetVersion"))         { *arg_dwords=0; return 0x00000004; }
    if (!strcmp(fn,"GetACP"))             { *arg_dwords=0; return 1252; }
    if (!strcmp(fn,"GetOEMCP"))           { *arg_dwords=0; return 437; }
    if (!strcmp(fn,"GetCPInfo"))          { uint32_t p=arg(e,1); wr32(e,p,1); *arg_dwords=2; return 1; }
    if (!strcmp(fn,"GetModuleHandleA"))   { *arg_dwords=1; return IMAGE_BASE; }
    if (!strcmp(fn,"GetModuleFileNameA")) { uint32_t p=arg(e,1),n=arg(e,2); if(p&&n){uint8_t z=0;uc_mem_write(e->uc,p,&z,1);} *arg_dwords=3; return 0; }
    if (!strcmp(fn,"GetProcAddress"))     { *arg_dwords=2; return 0; }
    if (!strcmp(fn,"LoadLibraryA"))       { *arg_dwords=1; return 0; }
    if (!strcmp(fn,"GetStdHandle"))       { *arg_dwords=1; return 0xFF00 | (arg(e,0)&0xFF); }
    if (!strcmp(fn,"SetStdHandle"))       { *arg_dwords=2; return 1; }
    if (!strcmp(fn,"GetFileType"))        { *arg_dwords=1; return 2; }
    if (!strcmp(fn,"GetStartupInfoA"))    { uint32_t p=arg(e,0); for(int i=0;i<68;i+=4) wr32(e,p+i,0); wr32(e,p,68); *arg_dwords=1; return 0; }
    if (!strcmp(fn,"GetCommandLineA"))    { if(!e->cmdline){e->cmdline=heap_alloc(e,8);uint8_t b[2]={0,0};uc_mem_write(e->uc,e->cmdline,b,2);} *arg_dwords=0; return e->cmdline; }
    if (!strcmp(fn,"GetEnvironmentStrings")) { if(!e->envstr){e->envstr=heap_alloc(e,8);uint8_t b[2]={0,0};uc_mem_write(e->uc,e->envstr,b,2);} *arg_dwords=0; return e->envstr; }
    if (!strcmp(fn,"GetEnvironmentStringsW")){ if(!e->envstrw){e->envstrw=heap_alloc(e,8);uint8_t b[4]={0,0,0,0};uc_mem_write(e->uc,e->envstrw,b,4);} *arg_dwords=0; return e->envstrw; }
    if (!strcmp(fn,"FreeEnvironmentStringsA")){ *arg_dwords=1; return 1; }
    if (!strcmp(fn,"FreeEnvironmentStringsW")){ *arg_dwords=1; return 1; }
    if (!strcmp(fn,"WriteFile"))          { uint32_t pw=arg(e,3); if(pw) wr32(e,pw,arg(e,2)); *arg_dwords=5; return 1; }
    if (!strcmp(fn,"FlushFileBuffers"))   { *arg_dwords=1; return 1; }
    if (!strcmp(fn,"SetFilePointer"))     { *arg_dwords=4; return 0; }
    if (!strcmp(fn,"RtlUnwind"))          { *arg_dwords=4; return 0; }
    // GetStringTypeA/W, LCMapStringA/W: best-effort - CRT startup/locale
    // table setup only calls these to build ctype tables, not per-utterance,
    // so a minimal always-succeeds stub (zero-filled output) is sufficient.
    if (!strcmp(fn,"GetStringTypeA")) {
        uint32_t cch=arg(e,3), out=arg(e,4);
        for(uint32_t i=0;i<cch && out;i++){ uint16_t z=0; uc_mem_write(e->uc,out+i*2,&z,2); }
        *arg_dwords=5; return 1;
    }
    if (!strcmp(fn,"GetStringTypeW")) {
        uint32_t cch=arg(e,2), out=arg(e,3);
        for(uint32_t i=0;i<cch && out;i++){ uint16_t z=0; uc_mem_write(e->uc,out+i*2,&z,2); }
        *arg_dwords=4; return 1;
    }
    if (!strcmp(fn,"LCMapStringA")) { *arg_dwords=6; return 0; }
    if (!strcmp(fn,"LCMapStringW")) { *arg_dwords=6; return 0; }
    // Code-page conversions (treat as latin-1/1252, one byte/word per char -
    // same approach as bst_shim.c)
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
    *arg_dwords=0; return 0;
}

static void hook_code(uc_engine *uc, uint64_t address, uint32_t size, void *user){
    (void)uc; (void)size;
    bstl_engine *e = (bstl_engine*)user;
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

static uint32_t rva_to_off(bstl_engine *e, uint32_t rva){
    for (int i=0;i<e->nsec;i++){
        uint32_t va=e->secs[i].VirtualAddress, sz=e->secs[i].SizeOfRawData;
        if (rva>=va && rva<va+sz) return e->secs[i].PointerToRawData + (rva-va);
    }
    return 0;
}
static void map_image(bstl_engine *e){
    uint32_t imgsz = (e->opt->SizeOfImage + 0xFFF) & ~0xFFFu;
    uc_mem_map(e->uc, IMAGE_BASE, imgsz, UC_PROT_ALL);
    uc_mem_write(e->uc, IMAGE_BASE, e->file, e->opt->SizeOfHeaders);
    for (int i=0;i<e->nsec;i++){
        SECTION_HEADER *s=&e->secs[i];
        if (s->SizeOfRawData && s->PointerToRawData)
            uc_mem_write(e->uc, IMAGE_BASE + s->VirtualAddress, e->file + s->PointerToRawData, s->SizeOfRawData);
    }
}
static void patch_imports(bstl_engine *e){
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
static uint32_t export_rva(bstl_engine *e, const char *want){
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

static uint32_t call_export_va(bstl_engine *e, uint32_t va, int argc, uint32_t *argv){
    uint32_t esp = STACK_TOP & ~0xFu;
    for (int i=argc-1;i>=0;i--){ esp-=4; wr32(e, esp, argv[i]); }
    esp-=4; wr32(e, esp, RET_MAGIC);
    setreg(e, UC_X86_REG_ESP, esp); setreg(e, UC_X86_REG_EBP, 0);
    uc_err err = uc_emu_start(e->uc, va, RET_MAGIC, 0, 0);
    if (err) return 0;
    return reg(e, UC_X86_REG_EAX);
}

bstl_engine *bstl_create(const char *dll_path){
    FILE *f = fopen(dll_path,"rb");
    if (!f) return NULL;
    bstl_engine *e = (bstl_engine*)calloc(1, sizeof(bstl_engine));
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
    uc_mem_map(e->uc, STUB_BASE, STUB_SIZE, UC_PROT_ALL);
    { uint8_t *fill=(uint8_t*)malloc(STUB_SIZE); memset(fill,0xC3,STUB_SIZE); uc_mem_write(e->uc,STUB_BASE,fill,STUB_SIZE); free(fill); }

    wr32(e, TIB_BASE+0x00, 0xFFFFFFFF);
    wr32(e, TIB_BASE+0x18, TIB_BASE);
    setreg(e, UC_X86_REG_FS_BASE, TIB_BASE);
    // UC_X86_REG_FS_BASE is documented as an x86_64 convenience and does not
    // reliably affect fs:-prefixed effective addresses in UC_MODE_32 (this
    // DLL family's CRT startup installs an SEH frame via fs:[0]/fs:[0x18],
    // unlike b32_tts.dll's simpler DllMain - see bst_shim.c). Getting a real
    // GDT+selector setup right without also clobbering Unicorn's implicit
    // flat CS/DS/SS/ES descriptors turned out to be its own rabbit hole, and
    // is unnecessary here: this emulation never dispatches a real exception,
    // so fs:[0]/fs:[0x18] just need to land somewhere valid, not be correct.
    // Mapping a zero page at linear address 0 (where fs:-relative accesses
    // empirically land in this Unicorn build) is the simplest fix that is.
    uc_mem_map(e->uc, 0, 0x1000, UC_PROT_ALL);

    patch_imports(e);

    uc_hook h1;
    uc_hook_add(e->uc, &h1, UC_HOOK_CODE, (void*)hook_code, e, STUB_BASE, STUB_BASE+STUB_SIZE);

    if (e->opt->AddressOfEntryPoint){
        uint32_t a[3]={IMAGE_BASE,1,0};
        call_export_va(e, IMAGE_BASE + e->opt->AddressOfEntryPoint, 3, a);
    }

    e->say_va = IMAGE_BASE + export_rva(e, "Say_TTS");
    e->deinit_va = IMAGE_BASE + export_rva(e, "DeInit_TTS");
    uint32_t init_va = IMAGE_BASE + export_rva(e, "Init_TTS");
    if (!export_rva(e,"Say_TTS") || !export_rva(e,"DeInit_TTS") || !export_rva(e,"Init_TTS")){
        bstl_destroy(e); return NULL;
    }

    uint32_t rc = call_export_va(e, init_va, 0, NULL);
    if (!rc){ bstl_destroy(e); return NULL; }
    return e;
}

void bstl_destroy(bstl_engine *e){
    if (!e) return;
    if (e->uc && e->deinit_va) call_export_va(e, e->deinit_va, 0, NULL);
    if (e->uc) uc_close(e->uc);
    for (int i=0;i<e->nshims;i++) free(e->shim_name[i]);
    free(e->file);
    free(e);
}

int bstl_sample_rate(const bstl_engine *e){ (void)e; return 11025; }

int bstl_speak(bstl_engine *e, const uint16_t *text_utf16, bstl_sample_cb cb, void *ctx){
    if (!e || !text_utf16) return -1;
    e->cb = cb; e->ctx = ctx;
    size_t n = 0; while (text_utf16[n]) n++;
    uint32_t addr = heap_alloc(e, (uint32_t)((n+1)*2));
    if (!addr) return -1;
    uc_mem_write(e->uc, addr, text_utf16, (n+1)*2);
    uint32_t a[1] = { addr };
    call_export_va(e, e->say_va, 1, a);
    e->cb = NULL; e->ctx = NULL;
    return 0;
}
