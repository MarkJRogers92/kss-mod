/* In-memory IPS patch application. */
#ifndef KSS_FRONTEND_IPS_H
#define KSS_FRONTEND_IPS_H

#include <stddef.h>
#include <stdint.h>

/*
 * Apply a standard IPS patch to rom in place.
 *
 * Supports ordinary records (3-byte offset, 2-byte length, data) and RLE
 * records (length 0, 3-byte count, 1-byte value), terminated by "EOF".
 * Returns 1 on success. On failure returns 0 and writes a human-readable
 * reason to err (if err is non-NULL and err_cap > 0); rom may be partially
 * modified in that case, so callers should patch a private copy.
 */
int ips_apply(const uint8_t *ips, size_t ips_size,
              uint8_t *rom, size_t rom_size,
              char *err, size_t err_cap);

#endif
