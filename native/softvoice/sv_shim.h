#ifndef SV_SHIM_H
#define SV_SHIM_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct sv_engine sv_engine;
typedef void (*sv_sample_cb)(const int16_t *samples, size_t count, void *ctx);

/* base_dll = path to TIBASE32.DLL; lang_dll = path to TIENG32.DLL or
 * TISPAN32.DLL; lang_shortname = "tieng" or "tispan" (used to match the
 * DLL's own LoadLibraryA("...") calls against the pre-mapped image). */
sv_engine *sv_create(const char *base_dll, const char *lang_dll, const char *lang_shortname);
void       sv_destroy(sv_engine *e);
int        sv_sample_rate(const sv_engine *e);

/* language: 1=English (only language wired up so far; matches sv.py's
 * default curvoice="1" for SVOpenSpeech's own "voice" parameter, which is
 * actually a language selector, not the character voice - see sv_set_personality). */
int sv_open(sv_engine *e, int language);

/* variant: 0=Male,1=Female,2=Large Male,3=Child,4=Giant Male,5=Mellow Female,
 * 6=Mellow Male,7=Crisp Male,8=The Fly,9=Robotoid,10=Martian,11=Colossus,
 * 12=Fast Fred,13=Old Woman,14=Munchkin,15=Troll,16=Nerd,17=Milktoast,
 * 18=Tipsy,19=Choirboy (SVSetPersonality - the actual "character voice"). */
int sv_set_personality(sv_engine *e, int variant);

int sv_speak(sv_engine *e, const char *text, sv_sample_cb cb, void *ctx);
int sv_speak_to_wav(sv_engine *e, const char *path, const char *text);

#ifdef __cplusplus
}
#endif
#endif
