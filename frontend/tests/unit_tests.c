/* Small dependency-free unit tests for the IPS and SHA-256 helpers. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "ips.h"
#include "sha256.h"

static int failures = 0;

#define CHECK(cond, message)                                            \
    do {                                                               \
        if (!(cond)) {                                                 \
            fprintf(stderr, "FAIL: %s (%s:%d)\n", message, __FILE__,   \
                    __LINE__);                                         \
            failures++;                                                \
        }                                                              \
    } while (0)

static void test_ips_standard(void) {
    uint8_t rom[16];
    /* PATCH, offset 0x000002, length 2, data 11 22, EOF */
    static const uint8_t patch[] = {
        'P', 'A', 'T', 'C', 'H',
        0x00, 0x00, 0x02, 0x00, 0x02, 0x11, 0x22,
        'E', 'O', 'F'
    };

    memset(rom, 0xAA, sizeof rom);
    CHECK(ips_apply(patch, sizeof patch, rom, sizeof rom, NULL, 0) == 1,
          "standard IPS record accepted");
    CHECK(rom[2] == 0x11 && rom[3] == 0x22, "standard IPS record written");
    CHECK(rom[1] == 0xAA && rom[4] == 0xAA, "standard IPS leaves other bytes alone");
    CHECK(ips_apply(patch, sizeof patch - 3, rom, sizeof rom, NULL, 0) == 0,
          "IPS without EOF is rejected");
}

static void test_ips_rle(void) {
    uint8_t rom[16];
    /* PATCH, offset 0x000004, length 0, count 0x000003, value 0x77, EOF */
    static const uint8_t patch[] = {
        'P', 'A', 'T', 'C', 'H',
        0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x03, 0x77,
        'E', 'O', 'F'
    };

    memset(rom, 0xAA, sizeof rom);
    CHECK(ips_apply(patch, sizeof patch, rom, sizeof rom, NULL, 0) == 1,
          "RLE IPS record accepted");
    CHECK(rom[4] == 0x77 && rom[5] == 0x77 && rom[6] == 0x77,
          "RLE IPS record writes count bytes");
    CHECK(rom[3] == 0xAA && rom[7] == 0xAA, "RLE IPS record is bounded");
}

static void test_ips_rejections(void) {
    uint8_t rom[16];
    char error[128];
    static const uint8_t bad_magic[] = {'P', 'A', 'T', 'C', 'X'};
    static const uint8_t out_of_bounds[] = {
        'P', 'A', 'T', 'C', 'H',
        0x00, 0x00, 0x0F, 0x00, 0x02, 0x11, 0x22,
        'E', 'O', 'F'
    };
    static const uint8_t truncated[] = {
        'P', 'A', 'T', 'C', 'H',
        0x00, 0x00, 0x02, 0x00, 0x02, 0x11
    };

    memset(rom, 0xAA, sizeof rom);
    CHECK(ips_apply(bad_magic, sizeof bad_magic, rom, sizeof rom, error, sizeof error) == 0,
          "bad IPS magic rejected");
    CHECK(strstr(error, "PATCH") != NULL, "bad magic error is descriptive");
    CHECK(ips_apply(out_of_bounds, sizeof out_of_bounds, rom, sizeof rom, error, sizeof error) == 0,
          "out-of-bounds IPS record rejected");
    CHECK(strstr(error, "past end") != NULL, "out-of-bounds error is descriptive");
    CHECK(ips_apply(truncated, sizeof truncated, rom, sizeof rom, error, sizeof error) == 0,
          "truncated IPS record rejected");
}

static void test_sha256_vectors(void) {
    static const char *abc_hex =
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    static const char *empty_hex =
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
    char hex[65];

    sha256_hex("abc", 3, hex);
    CHECK(strcmp(hex, abc_hex) == 0, "SHA-256(\"abc\") vector");
    sha256_hex("", 0, hex);
    CHECK(strcmp(hex, empty_hex) == 0, "SHA-256(\"\") vector");
}

int main(void) {
    test_ips_standard();
    test_ips_rle();
    test_ips_rejections();
    test_sha256_vectors();
    if (failures != 0) {
        fprintf(stderr, "%d unit test(s) failed\n", failures);
        return 1;
    }
    printf("PASS: IPS (standard/RLE/errors) and SHA-256 vectors\n");
    return 0;
}
