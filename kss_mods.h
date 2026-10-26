/* Data-driven sprite-replacement mods for the KSS native runtime. */
#ifndef KSS_MODS_H
#define KSS_MODS_H
#include <stdint.h>
#include <stddef.h>
/* Load every mod under mods_dir (e.g. mods/blip/mod.txt). Returns count loaded, <0 on error. */
int  kss_mods_init(const char* mods_dir);
/* Called by kss_step() before each emulated frame. */
void kss_mods_pre_frame(void);
#endif
