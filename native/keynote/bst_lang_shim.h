/*
 * bst_lang_shim — Unicorn-emulated shim for the "Lingvosoft" 2006-era
 * BestSpeech language DLLs (dll_eng.dll, dll_jpn.dll, dll_ara.dll, ...).
 *
 * Same underlying BestSpeech engine family as bst_shim.h's b32_tts.dll, but
 * a cleaner build: three plain cdecl exports (Init_TTS/Say_TTS/DeInit_TTS),
 * UTF-16 text in, no USER32/message-pump dependency at all (see
 * roms/keynote/lang/PROVENANCE.md), so no coroutine driver is needed - a
 * single emulated call runs each function to completion.
 */
#ifndef BST_LANG_SHIM_H
#define BST_LANG_SHIM_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct bstl_engine bstl_engine;

typedef void (*bstl_sample_cb)(const int16_t *samples, size_t count, void *ctx);

/* Loads `dll_path` and runs its CRT startup + Init_TTS(). NULL on failure. */
bstl_engine *bstl_create(const char *dll_path);
void         bstl_destroy(bstl_engine *e);

int          bstl_sample_rate(const bstl_engine *e);

/*
 * Synthesize `text_utf16` (UTF-16LE, NUL-terminated), delivering PCM to
 * `cb`. Returns 0 on success.
 */
int          bstl_speak(bstl_engine *e, const uint16_t *text_utf16,
                         bstl_sample_cb cb, void *ctx);

#ifdef __cplusplus
}
#endif

#endif /* BST_LANG_SHIM_H */
