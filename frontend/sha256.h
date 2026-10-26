/* Minimal self-contained SHA-256 (FIPS 180-4), used to verify the ROM. */
#ifndef KSS_FRONTEND_SHA256_H
#define KSS_FRONTEND_SHA256_H

#include <stddef.h>
#include <stdint.h>

/* Writes the 32-byte digest of data[0..len) to out. */
void sha256(const void *data, size_t len, uint8_t out[32]);

/* Writes a 64-character lowercase hex digest plus a NUL to out[65]. */
void sha256_hex(const void *data, size_t len, char out[65]);

#endif
