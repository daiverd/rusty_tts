/*
 * Resident host for one Apple Eloquence language module (eci.so + a
 * single language .so). One of these processes is spawned per language,
 * lazily, by providers/eloquence.py.
 *
 * Why one process per language, and why the caller must set this
 * process's *starting* working directory (not chdir() into it after the
 * fact): eciNew() reads eci.ini from the process's CWD, and testing
 * showed it only works when that CWD was the process's cwd from the
 * very start (e.g. via posix_spawn's file-actions chdir, or Python's
 * subprocess.Popen(cwd=...), or `docker exec -w`) - calling chdir() at
 * runtime inside an already-running process to reach the *same*
 * directory reliably makes eciNew() return NULL instead. The exact
 * mechanism inside the engine is unclear (not $PWD - that was tested and
 * ruled out too), but the empirical rule is unambiguous, so this program
 * never calls chdir() at all - the caller is responsible for exec'ing it
 * with the right cwd already set.
 *
 * A second, unrelated wrinkle also confirmed by testing: eciVersion()
 * must be called before eciNew() - it's required initialization, not
 * just diagnostic output (matches Apple-Eloquence-ELF's own
 * examples/speak.c, which always calls it first too).
 *
 * Wire protocol (all integers little-endian int32, host's native order):
 *
 * Startup (host -> service, once):
 *   "READY\n" on success, or "INIT_FAIL\n" + exit(1) if eciNew() failed -
 *   the parent should kill and respawn this process (a fresh exec() with
 *   the same cwd has been reliable in testing; if it weren't, spawning
 *   with a *different* fresh temp cwd would be the next thing to try).
 *
 * Request (service -> host, per utterance):
 *   int32 text_len
 *   text_len bytes (Latin-1 text)
 *
 * Response (host -> service, per utterance):
 *   int32 status      (0 = ok, nonzero = failed)
 *   int32 pcm_len     (bytes of 16-bit mono PCM @ 11025 Hz; 0 if status != 0)
 *   pcm_len bytes of PCM data
 */
#include <dlfcn.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define CHUNK_SAMPLES 8192
#define eciWaveformBuffer 0
#define eciDataProcessed 1

typedef int (*ECICallback)(void *hEngine, int msg, long lParam, void *pData);
typedef void*  (*eciNew_fn)(void);
typedef int    (*eciSetOutputBuffer_fn)(void *, int, void *);
typedef int    (*eciAddText_fn)(void *, const char *);
typedef int    (*eciSynthesize_fn)(void *);
typedef int    (*eciSynchronize_fn)(void *);
typedef void   (*eciRegisterCallback_fn)(void *, ECICallback, void *);
typedef void   (*eciVersion_fn)(char *);

static eciAddText_fn         p_eciAddText;
static eciSynthesize_fn      p_eciSynthesize;
static eciSynchronize_fn     p_eciSynchronize;

static int16_t  g_chunk[CHUNK_SAMPLES];
static int16_t *g_pcm      = NULL;
static long     g_pcm_len  = 0;
static long     g_pcm_cap  = 0;

static int my_callback(void *hEngine, int msg, long lParam, void *pData) {
    (void)hEngine; (void)pData;
    if (msg != eciWaveformBuffer || lParam <= 0) return eciDataProcessed;

    long need = g_pcm_len + lParam;
    if (need > g_pcm_cap) {
        long new_cap = g_pcm_cap ? g_pcm_cap * 2 : 65536;
        while (new_cap < need) new_cap *= 2;
        int16_t *p = realloc(g_pcm, (size_t)new_cap * sizeof(int16_t));
        if (!p) return 2; /* eciDataAbort */
        g_pcm = p;
        g_pcm_cap = new_cap;
    }
    memcpy(g_pcm + g_pcm_len, g_chunk, (size_t)lParam * sizeof(int16_t));
    g_pcm_len += lParam;
    return eciDataProcessed;
}

static int read_exact(void *buf, size_t n) {
    size_t got = 0; char *p = (char*)buf;
    while (got < n) {
        size_t r = fread(p + got, 1, n - got, stdin);
        if (r == 0) return 0;
        got += r;
    }
    return 1;
}
static int write_exact(const void *buf, size_t n) {
    size_t wrote = 0; const char *p = (const char*)buf;
    while (wrote < n) {
        size_t w = fwrite(p + wrote, 1, n - wrote, stdout);
        if (w == 0) return 0;
        wrote += w;
    }
    return 1;
}
static int read_i32(int32_t *v) { return read_exact(v, 4); }
static int write_i32(int32_t v) { return write_exact(&v, 4); }

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <eci.so path>  (run with cwd already set to the language's eci.ini directory)\n", argv[0]);
        return 1;
    }
    const char *eci_so = argv[1];

    void *h = dlopen(eci_so, RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen FAIL: %s\n", dlerror()); return 1; }

    eciVersion_fn          p_eciVersion          = (eciVersion_fn)dlsym(h, "eciVersion");
    eciNew_fn               p_eciNew               = (eciNew_fn)dlsym(h, "eciNew");
    eciSetOutputBuffer_fn   p_eciSetOutputBuffer   = (eciSetOutputBuffer_fn)dlsym(h, "eciSetOutputBuffer");
    eciRegisterCallback_fn  p_eciRegisterCallback  = (eciRegisterCallback_fn)dlsym(h, "eciRegisterCallback");
    p_eciAddText     = (eciAddText_fn)dlsym(h, "eciAddText");
    p_eciSynthesize  = (eciSynthesize_fn)dlsym(h, "eciSynthesize");
    p_eciSynchronize = (eciSynchronize_fn)dlsym(h, "eciSynchronize");

    if (!p_eciVersion || !p_eciNew || !p_eciSetOutputBuffer ||
        !p_eciRegisterCallback || !p_eciAddText || !p_eciSynthesize || !p_eciSynchronize) {
        fprintf(stderr, "missing required ECI symbols\n");
        return 1;
    }

    char version[64];
    p_eciVersion(version); /* required, not just diagnostic - see header comment */

    void *engine = p_eciNew();
    if (!engine) {
        fprintf(stderr, "INIT_FAIL: eciNew() failed\n");
        printf("INIT_FAIL\n");
        fflush(stdout);
        return 1;
    }
    p_eciRegisterCallback(engine, my_callback, NULL);
    p_eciSetOutputBuffer(engine, CHUNK_SAMPLES, g_chunk);

    printf("READY\n");
    fflush(stdout);

    for (;;) {
        int32_t text_len;
        if (!read_i32(&text_len)) break;
        if (text_len < 0 || text_len > (16 * 1024 * 1024)) break;

        char *text = malloc(text_len + 1);
        if (text_len > 0 && !read_exact(text, text_len)) { free(text); break; }
        text[text_len] = '\0';

        g_pcm_len = 0;
        p_eciAddText(engine, text);
        p_eciSynthesize(engine);
        p_eciSynchronize(engine);
        free(text);

        if (g_pcm_len <= 0) {
            write_i32(1);
            write_i32(0);
        } else {
            write_i32(0);
            write_i32((int32_t)(g_pcm_len * 2));
            write_exact(g_pcm, (size_t)g_pcm_len * 2);
        }
        fflush(stdout);
    }

    return 0;
}
