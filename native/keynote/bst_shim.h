/*
 * bst_shim — a small, clean C surface over the BestSpeech / Keynote Gold TTS
 * engine, which ships only as a 32-bit Windows DLL (b32_tts.dll).
 *
 * The engine is executed under the Unicorn CPU emulator: the DLL is mapped into
 * emulated x86 memory and its ~56 Windows imports (KERNEL32/USER32/WINMM) are
 * serviced by hand-written shims. waveOut* audio is captured rather than played,
 * so this presents the same shape as any other in-memory synth: text in, signed
 * 16-bit mono PCM out (11025 Hz), delivered incrementally to a callback.
 *
 * All speech parameters (voice, pitch, rate, head size, …) are passed as inline
 * `~cmd]` commands inside the text, so the API surface stays tiny.
 */
#ifndef BST_SHIM_H
#define BST_SHIM_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct bst_engine bst_engine;

/*
 * Receives a block of signed 16-bit mono PCM samples at bst_sample_rate().
 * `samples` is valid only for the duration of the call — copy if retaining.
 */
typedef void (*bst_sample_cb)(const int16_t *samples, size_t count, void *ctx);

/*
 * Create an engine by loading b32_tts.dll from `dll_path`. Runs the DLL's CRT
 * startup and creates the underlying synthesizer. Returns NULL on failure.
 */
bst_engine *bst_create(const char *dll_path);
void        bst_destroy(bst_engine *e);

/* Native output sample rate in Hz (11025). */
int         bst_sample_rate(const bst_engine *e);

/*
 * Synthesize `text` (Windows-1252, may contain inline `~cmd]` commands),
 * delivering PCM to `cb` (with `ctx`) and blocking until synthesis completes.
 * Returns 0 on success. Not reentrant per engine.
 */
int         bst_speak(bst_engine *e, const char *text, bst_sample_cb cb, void *ctx);

/* Convenience: synthesize `text` to a 16-bit mono WAV file at `path`. */
int         bst_speak_to_wav(bst_engine *e, const char *path, const char *text);

/*
 * The engine's built-in voices (names collected from @rommix0's BST.h). Index a
 * voice's inline command prefix with bst_voice_prefix(); higher layers usually
 * build their own prefixes instead.
 */
int         bst_voice_count(void);
const char *bst_voice_name(int index);
const char *bst_voice_prefix(int index);

#ifdef __cplusplus
}
#endif

#endif /* BST_SHIM_H */
