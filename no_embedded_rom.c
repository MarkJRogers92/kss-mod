/* The runtime falls back to an embedded ROM when none is loaded. This build
 * never embeds game data: the player's own ROM is always loaded from disk. */
#include <stdint.h>
const uint32_t g_snes_rom_size = 0u;
const uint8_t g_snes_rom_data[1] = {0};
