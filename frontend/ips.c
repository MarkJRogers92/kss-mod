/* In-memory IPS patch application, including RLE records. */
#include "ips.h"

#include <stdio.h>
#include <string.h>

static void set_error(char *err, size_t err_cap, const char *message) {
    if (err != NULL && err_cap > 0) {
        snprintf(err, err_cap, "%s", message);
    }
}

int ips_apply(const uint8_t *ips, size_t ips_size,
              uint8_t *rom, size_t rom_size,
              char *err, size_t err_cap) {
    size_t pos;

    if (err != NULL && err_cap > 0) {
        err[0] = '\0';
    }
    if (ips == NULL || rom == NULL) {
        set_error(err, err_cap, "null buffer");
        return 0;
    }
    if (ips_size < 5 || memcmp(ips, "PATCH", 5) != 0) {
        set_error(err, err_cap, "not an IPS file (missing PATCH header)");
        return 0;
    }

    pos = 5;
    for (;;) {
        uint32_t offset;
        uint16_t length;

        if (pos + 3 <= ips_size && memcmp(ips + pos, "EOF", 3) == 0) {
            return 1; /* trailing bytes after EOF are ignored */
        }
        if (pos + 5 > ips_size) {
            set_error(err, err_cap, "truncated IPS record header (missing EOF?)");
            return 0;
        }

        offset = ((uint32_t)ips[pos] << 16) |
                 ((uint32_t)ips[pos + 1] << 8) |
                 (uint32_t)ips[pos + 2];
        length = (uint16_t)(((uint16_t)ips[pos + 3] << 8) | ips[pos + 4]);
        pos += 5;

        if (length == 0) {
            uint32_t count;
            uint8_t value;

            if (pos + 4 > ips_size) {
                set_error(err, err_cap, "truncated IPS RLE record");
                return 0;
            }
            count = ((uint32_t)ips[pos] << 16) |
                    ((uint32_t)ips[pos + 1] << 8) |
                    (uint32_t)ips[pos + 2];
            value = ips[pos + 3];
            pos += 4;

            if ((uint64_t)offset + count > (uint64_t)rom_size) {
                set_error(err, err_cap, "IPS RLE record writes past end of ROM");
                return 0;
            }
            memset(rom + offset, value, count);
        } else {
            if (pos + length > ips_size) {
                set_error(err, err_cap, "truncated IPS data record");
                return 0;
            }
            if ((uint64_t)offset + length > (uint64_t)rom_size) {
                set_error(err, err_cap, "IPS record writes past end of ROM");
                return 0;
            }
            memcpy(rom + offset, ips + pos, length);
            pos += length;
        }
    }
}
