/* KSS native runtime API: a single translation unit with the forked
 * KirbySuperStarRecomp runtime (snes_runtime.c, LakeSnes-based). Exposes the
 * C/ctypes API in kss_api.h. Sprite replacement lives in kss_mods.c, called
 * from the forked PPU's per-object hook; mod art lives in host memory, so no
 * ROM, VRAM or BW-RAM budget is involved.
 */
#include "snes_runtime.c"
#include "kss_mods.h"

/* ---- API ---- */
static snes_context_t* g_ctx;
static Snes* hw(void) { return (Snes*)g_ctx->hw_snes; }

int kss_open(const char* rom) {
    g_ctx = snes_runtime_init();
    if (!g_ctx || !snes_runtime_load_rom(g_ctx, rom)) return 0;
    return 1;
}
/* One emulated frame: mod rules (kss_mods.c) run first, then the frame. */
void kss_step(uint16_t p1, uint16_t p2) {
    kss_mods_pre_frame();
    g_ctx->joy1_word = p1; g_ctx->joy2_word = p2;
    snes_runtime_run_frame(g_ctx);
}
void kss_run(uint16_t p1, uint16_t p2, int n) { for (int i = 0; i < n; i++) kss_step(p1, p2); }
int kss_open_memory(const uint8_t* data, size_t size) {
    g_ctx = snes_runtime_init();
    if (!g_ctx || !snes_runtime_load_rom_memory(g_ctx, data, size)) return 0;
    return 1;
}
size_t kss_audio(int16_t* out, size_t max_samples) { return snes_runtime_get_audio_samples(g_ctx, out, max_samples); }
int kss_save_sram(const char* p) { return snes_runtime_save_sram(g_ctx, p); }
int kss_load_sram(const char* p) { return snes_runtime_load_sram(g_ctx, p); }
void kss_close(void) { if (g_ctx) { snes_runtime_free(g_ctx); g_ctx = NULL; } }
uint8_t kss_read_bwram8(uint32_t off) { return off < hw()->cart->ramSize ? hw()->cart->ram[off] : 0; }
uint16_t kss_read_bwram16(uint32_t off) { return (uint16_t)(kss_read_bwram8(off) | kss_read_bwram8(off + 1) << 8); }
uint8_t* kss_bwram(void) { return hw()->cart->ram; }
/* Read-only SA-1 I-RAM word ($3000-$37FF on both CPUs), e.g. the room
 * selectors at $32EA/$32EE/$32F2 (subgame/level/room). Test observation only. */
uint16_t kss_read_iram16(uint16_t addr) {
    Sa1* s = hw()->cart->sa1;
    if (!s || addr < 0x3000 || addr >= 0x37FF) return 0;
    return (uint16_t)(s->iram[addr & (SA1_IRAM_SIZE - 1)] | s->iram[(addr + 1) & (SA1_IRAM_SIZE - 1)] << 8);
}
uint32_t kss_bwram_size(void) { return hw()->cart->ramSize; }
uint8_t* kss_wram(void) { return hw()->ram; }
uint16_t* kss_oam(void) { return hw()->ppu->oam; }
uint8_t* kss_high_oam(void) { return hw()->ppu->highOam; }
uint16_t* kss_cgram(void) { return hw()->ppu->cgram; }
uint16_t* kss_vram(void) { return hw()->ppu->vram; }
const uint32_t* kss_fb(void) { return snes_runtime_get_framebuffer(g_ctx); }
int kss_fb_w(void) { return snes_runtime_get_frame_width(g_ctx); }
int kss_fb_h(void) { return snes_runtime_get_frame_height(g_ctx); }
uint32_t kss_frame(void) { return g_ctx->frame_count; }
int kss_save_state(const char* p) { return snes_runtime_save_state(g_ctx, p); }
int kss_load_state(const char* p) { return snes_runtime_load_state(g_ctx, p); }
void kss_set_widescreen(int on) { snes_runtime_set_widescreen(g_ctx, on != 0); }

/* Native-only expansion ROM at banks 70-7D (see snes_runtime.c). Independent
 * of kss_open/kss_close: it stays loaded until replaced or cleared. A NULL or
 * zero-size image clears it, so those banks read as open bus again. */
int kss_load_expansion_memory(const uint8_t* data, size_t size) {
    free(g_kss_xrom); g_kss_xrom = NULL; g_kss_xrom_size = 0;
    if (!data || !size) return 1;
    if (size > (size_t)KSS_XROM_BANKS << 16) return 0;
    g_kss_xrom = (uint8_t*)malloc(size);
    if (!g_kss_xrom) return 0;
    memcpy(g_kss_xrom, data, size); g_kss_xrom_size = (uint32_t)size;
    return 1;
}
int kss_load_expansion(const char* path) {
    if (!path) return kss_load_expansion_memory(NULL, 0);
    FILE* f = fopen(path, "rb"); if (!f) return 0;
    uint8_t* buf = (uint8_t*)malloc((size_t)KSS_XROM_BANKS << 16);
    size_t n = buf ? fread(buf, 1, (size_t)KSS_XROM_BANKS << 16, f) : 0;
    int too_big = buf && fgetc(f) != EOF;
    fclose(f);
    int ok = buf && n && !too_big && kss_load_expansion_memory(buf, n);
    free(buf);
    return ok;
}
uint32_t kss_expansion_size(void) { return g_kss_xrom_size; }


/* Tile-dumper support: per-scanline BG registers of the last frame. */
void kss_capture_enable(int on) { kss_capture_lines = on; }
const void* kss_capture_regs(void) { return kss_line_regs; }
int kss_capture_stride(void) { return (int)sizeof(KssLineRegs); }
const uint16_t* kss_capture_cgram(void) { return &kss_line_cgram[0][0]; }
