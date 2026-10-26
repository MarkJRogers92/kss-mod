/* Public API of kss_mod.c (forked KirbySuperStarRecomp runtime + mod layer). */
#ifndef KSS_API_H
#define KSS_API_H
#include <stdint.h>
#include <stddef.h>
#include "kss_mods.h"
int  kss_open(const char* rom_path);
int  kss_open_memory(const uint8_t* data, size_t size);
void kss_close(void);
void kss_step(uint16_t p1, uint16_t p2);           /* one frame; runs mods first */
size_t kss_audio(int16_t* out, size_t max_samples); /* interleaved stereo int16, 44100 Hz */
const uint32_t* kss_fb(void);                       /* 0x00RRGGBB, width x height */
int  kss_fb_w(void);
int  kss_fb_h(void);
uint32_t kss_frame(void);
void kss_set_widescreen(int on);
int  kss_save_state(const char* path);
int  kss_load_state(const char* path);
int  kss_save_sram(const char* path);
int  kss_load_sram(const char* path);
uint16_t kss_read_bwram16(uint32_t off);
uint16_t kss_read_iram16(uint16_t addr);            /* SA-1 I-RAM $3000-$37FF, read-only */
/* Native-only expansion ROM, mapped read-only at banks 70-7D for both CPUs
 * (max 14 x 64 KiB). NULL/empty clears it. Returns 1 on success. */
int  kss_load_expansion(const char* path);
int  kss_load_expansion_memory(const uint8_t* data, size_t size);
uint32_t kss_expansion_size(void);
/* SNES pad bits: B 8000 Y 4000 Select 2000 Start 1000 Up 0800 Down 0400 Left 0200 Right 0100 A 0080 X 0040 L 0020 R 0010 */
#endif
