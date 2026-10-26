/*
 * kss-native: a small SDL3 frontend for the KSS SNES runtime (kss_mod.c).
 *
 * The player's own unheadered USA ROM is verified by SHA-256, an optional IPS
 * patch is applied in memory, and the result is handed to kss_open_memory().
 * No ROM data is ever written to disk.
 */
#define _POSIX_C_SOURCE 200809L

#include <SDL3/SDL.h>
#include <mach-o/dyld.h>

#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "kss_api.h"
#include "ips.h"
#include "sha256.h"

#define ROM_BYTES 4194304u
#define ROM_SHA256_HEX "4e095fbbdec4a16b075d7140385ff68b259870ca9e3357f076dfff7f3d1c4a62"
#define RUNTIME_FPS 60.0988
#define AUDIO_RATE 44100
#define AUDIO_SAMPLES_PER_FRAME 735
#define AUDIO_QUEUE_LIMIT_BYTES (4 * AUDIO_SAMPLES_PER_FRAME * 2 * 2)
#define SRAM_SAVE_INTERVAL_NS 30000000000ull

/* SNES pad bits. */
#define PAD_B 0x8000u
#define PAD_Y 0x4000u
#define PAD_SELECT 0x2000u
#define PAD_START 0x1000u
#define PAD_UP 0x0800u
#define PAD_DOWN 0x0400u
#define PAD_LEFT 0x0200u
#define PAD_RIGHT 0x0100u
#define PAD_A 0x0080u
#define PAD_X 0x0040u
#define PAD_L 0x0020u
#define PAD_R 0x0010u

typedef struct {
    const char *rom_path;
    const char *ips_path;
    const char *expansion_path;
    const char *mods_dir;
    const char *saves_dir;
    int scale;
    int widescreen;
    int fullscreen;
    int headless_frames;
    int press_start_every;
    int exit_after_frames;
    const char *dump_path;
    int audio_stats;
    const char *load_state_path;
} Options;

typedef struct {
    char saves_dir[PATH_MAX];
    char sram_path[PATH_MAX];
    char state_path[PATH_MAX];
    char mods_dir[PATH_MAX];
} Paths;

typedef struct {
    SDL_Window *window;
    SDL_Renderer *renderer;
    SDL_Texture *texture;
    int tex_w;
    int tex_h;
    SDL_AudioStream *audio;
    int audio_warned;
    SDL_Gamepad *pads[2];
    int npads;
    bool paused;
    bool widescreen;
} App;

static volatile sig_atomic_t g_interrupted = 0;

static void on_signal(int sig) {
    (void)sig;
    g_interrupted = 1;
}

static void warn_msg(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fputs("kss-native: ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
}

static void die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fputs("kss-native: error: ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
    exit(EXIT_FAILURE);
}

static void usage(FILE *out) {
    fputs(
        "Usage: kss-native --rom ORIGINAL.sfc [options]\n"
        "\n"
        "  --rom PATH              unheadered USA Kirby Super Star ROM (required)\n"
        "  --ips PATH              IPS patch applied in memory\n"
        "  --expansion PATH        native-only expansion ROM (.kx) mapped at banks 70-7D\n"
        "  --mods DIR              mods directory (default: mods next to the executable)\n"
        "  --saves DIR             save directory (default: ~/Library/Application Support/KSSNative/)\n"
        "  --scale N               integer window scale (default 3)\n"
        "  --widescreen            start in 16:9 (352x224); the game only draws 256 px, so the\n"
        "                          extra side columns show unloaded tiles (W toggles live)\n"
        "  --no-widescreen         start in 4:3 (256x224) (default)\n"
        "  --fullscreen            start fullscreen\n"
        "  --headless-frames N     run N frames with no window/audio, then print JSON\n"
        "  --press-start-every K   headless: hold Start for 6 frames every K frames\n"
        "  --dump PATH             headless: write final frame as binary PPM\n"
        "  --audio-stats           headless: print audio statistics to stderr\n"
        "  --exit-after-frames N   quit after N emulated frames (windowed smoke test)\n"
        "  -h, --help              show this help\n",
        out);
}

static int parse_int_arg(const char *name, const char *value, int lo, int hi) {
    char *end = NULL;
    long parsed;

    errno = 0;
    parsed = strtol(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0' || parsed < lo || parsed > hi) {
        die("invalid value '%s' for %s (expected %d..%d)", value, name, lo, hi);
    }
    return (int)parsed;
}

static void parse_args(int argc, char **argv, Options *options) {
    int i;

    memset(options, 0, sizeof *options);
    options->scale = 3;
    options->widescreen = 0;   /* 4:3 by default: the game never draws the 16:9 side columns */

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];

        if (strcmp(arg, "--rom") == 0) {
            if (++i >= argc) die("missing value for --rom");
            options->rom_path = argv[i];
        } else if (strcmp(arg, "--ips") == 0) {
            if (++i >= argc) die("missing value for --ips");
            options->ips_path = argv[i];
        } else if (strcmp(arg, "--expansion") == 0) {
            if (++i >= argc) die("missing value for --expansion");
            options->expansion_path = argv[i];
        } else if (strcmp(arg, "--mods") == 0) {
            if (++i >= argc) die("missing value for --mods");
            options->mods_dir = argv[i];
        } else if (strcmp(arg, "--saves") == 0) {
            if (++i >= argc) die("missing value for --saves");
            options->saves_dir = argv[i];
        } else if (strcmp(arg, "--scale") == 0) {
            if (++i >= argc) die("missing value for --scale");
            options->scale = parse_int_arg("--scale", argv[i], 1, 16);
        } else if (strcmp(arg, "--widescreen") == 0) {
            options->widescreen = 1;
        } else if (strcmp(arg, "--no-widescreen") == 0) {
            options->widescreen = 0;
        } else if (strcmp(arg, "--fullscreen") == 0) {
            options->fullscreen = 1;
        } else if (strcmp(arg, "--headless-frames") == 0) {
            if (++i >= argc) die("missing value for --headless-frames");
            options->headless_frames = parse_int_arg("--headless-frames", argv[i], 1, 100000000);
        } else if (strcmp(arg, "--press-start-every") == 0) {
            if (++i >= argc) die("missing value for --press-start-every");
            options->press_start_every = parse_int_arg("--press-start-every", argv[i], 1, 100000000);
        } else if (strcmp(arg, "--exit-after-frames") == 0) {
            if (++i >= argc) die("missing value for --exit-after-frames");
            options->exit_after_frames = parse_int_arg("--exit-after-frames", argv[i], 1, 100000000);
        } else if (strcmp(arg, "--dump") == 0) {
            if (++i >= argc) die("missing value for --dump");
            options->dump_path = argv[i];
        } else if (strcmp(arg, "--load-state") == 0) {
            if (++i >= argc) die("--load-state requires a path");
            options->load_state_path = argv[i];
        } else if (strcmp(arg, "--audio-stats") == 0) {
            options->audio_stats = 1;
        } else if (strcmp(arg, "--help") == 0 || strcmp(arg, "-h") == 0) {
            usage(stdout);
            exit(EXIT_SUCCESS);
        } else {
            die("unknown option '%s' (try --help)", arg);
        }
    }

    if (options->rom_path == NULL || options->rom_path[0] == '\0') {
        die("--rom is required (try --help)");
    }
    if (options->headless_frames == 0) {
        if (options->dump_path != NULL) die("--dump requires --headless-frames");
        if (options->audio_stats) die("--audio-stats requires --headless-frames");
        if (options->press_start_every != 0) die("--press-start-every requires --headless-frames");
    }
}

static uint8_t *read_whole_file(const char *path, size_t *out_size) {
    FILE *file;
    long length;
    uint8_t *data;
    size_t got;

    *out_size = 0;
    file = fopen(path, "rb");
    if (file == NULL) return NULL;
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return NULL;
    }
    length = ftell(file);
    if (length < 0) {
        fclose(file);
        return NULL;
    }
    rewind(file);
    data = (uint8_t *)malloc(length > 0 ? (size_t)length : 1u);
    if (data == NULL) {
        fclose(file);
        return NULL;
    }
    got = fread(data, 1, (size_t)length, file);
    fclose(file);
    if (got != (size_t)length) {
        free(data);
        return NULL;
    }
    *out_size = got;
    return data;
}

static int is_directory(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static int mkdir_p(const char *path) {
    char tmp[PATH_MAX];
    size_t length;
    size_t i;
    struct stat st;

    length = strlen(path);
    if (length == 0 || length >= sizeof tmp) return -1;
    memcpy(tmp, path, length + 1);

    for (i = 1; i < length; i++) {
        if (tmp[i] == '/') {
            tmp[i] = '\0';
            if (mkdir(tmp, 0755) != 0 && errno != EEXIST) return -1;
            tmp[i] = '/';
        }
    }
    if (mkdir(tmp, 0755) != 0 && errno != EEXIST) return -1;
    if (stat(tmp, &st) != 0 || !S_ISDIR(st.st_mode)) return -1;
    return 0;
}

static char *expand_home(const char *path) {
    const char *home;
    size_t length;
    char *expanded;

    if (path[0] != '~' || (path[1] != '/' && path[1] != '\0')) {
        return strdup(path);
    }
    home = getenv("HOME");
    if (home == NULL) return NULL;
    length = strlen(home) + strlen(path + 1) + 1;
    expanded = (char *)malloc(length);
    if (expanded == NULL) return NULL;
    snprintf(expanded, length, "%s%s", home, path + 1);
    return expanded;
}

static int executable_directory(char *out, size_t out_cap) {
    char executable[PATH_MAX];
    char resolved[PATH_MAX];
    uint32_t size = (uint32_t)sizeof executable;
    char *slash;
    const char *real;

    if (_NSGetExecutablePath(executable, &size) != 0) return 0;
    real = realpath(executable, resolved);
    if (real == NULL) {
        snprintf(resolved, sizeof resolved, "%s", executable);
    }
    slash = strrchr(resolved, '/');
    if (slash == NULL) return 0;
    *slash = '\0';
    if (snprintf(out, out_cap, "%s", resolved) >= (int)out_cap) return 0;
    return 1;
}

static void init_paths(const Options *options, Paths *paths) {
    const char *home;
    char *expanded;

    memset(paths, 0, sizeof *paths);

    if (options->saves_dir != NULL) {
        expanded = expand_home(options->saves_dir);
        if (expanded == NULL) die("could not expand --saves path");
        if (snprintf(paths->saves_dir, sizeof paths->saves_dir, "%s", expanded) >=
            (int)sizeof paths->saves_dir) {
            free(expanded);
            die("--saves path is too long");
        }
        free(expanded);
    } else {
        home = getenv("HOME");
        if (home == NULL) die("HOME is not set; pass --saves DIR");
        if (snprintf(paths->saves_dir, sizeof paths->saves_dir,
                     "%s/Library/Application Support/KSSNative", home) >=
            (int)sizeof paths->saves_dir) {
            die("default save path is too long");
        }
    }

    if (mkdir_p(paths->saves_dir) != 0) {
        die("cannot create save directory '%s': %s", paths->saves_dir, strerror(errno));
    }

    if (options->mods_dir != NULL) {
        expanded = expand_home(options->mods_dir);
        if (expanded == NULL) die("could not expand --mods path");
        if (snprintf(paths->mods_dir, sizeof paths->mods_dir, "%s", expanded) >=
            (int)sizeof paths->mods_dir) {
            free(expanded);
            die("--mods path is too long");
        }
        free(expanded);
    } else {
        char exe_dir[PATH_MAX];
        if (executable_directory(exe_dir, sizeof exe_dir)) {
            char candidate[PATH_MAX];
            if (snprintf(candidate, sizeof candidate, "%s/mods", exe_dir) <
                (int)sizeof candidate && is_directory(candidate)) {
                snprintf(paths->mods_dir, sizeof paths->mods_dir, "%s", candidate);
            }
        }
    }

    {
        char base[256];
        const char *ips_base;
        const char *slash;
        char *dot;

        if (options->ips_path == NULL) {
            snprintf(base, sizeof base, "kss");
        } else {
            char patch_base[200];
            slash = strrchr(options->ips_path, '/');
            ips_base = (slash != NULL) ? slash + 1 : options->ips_path;
            snprintf(patch_base, sizeof patch_base, "%s", ips_base);
            dot = strrchr(patch_base, '.');
            if (dot != NULL && strcasecmp(dot, ".ips") == 0) *dot = '\0';
            if (patch_base[0] == '\0') snprintf(patch_base, sizeof patch_base, "patch");
            snprintf(base, sizeof base, "kss-%s", patch_base);
        }

        if (snprintf(paths->sram_path, sizeof paths->sram_path, "%s/%s.srm",
                     paths->saves_dir, base) >= (int)sizeof paths->sram_path ||
            snprintf(paths->state_path, sizeof paths->state_path, "%s/%s.state",
                     paths->saves_dir, base) >= (int)sizeof paths->state_path) {
            die("save path is too long");
        }
    }
}

static int files_identical(const char *a, const char *b) {
    struct stat sa;
    struct stat sb;
    FILE *fa;
    FILE *fb;
    uint8_t buf_a[4096];
    uint8_t buf_b[4096];
    int same = 1;

    if (stat(a, &sa) != 0 || stat(b, &sb) != 0) return 0;
    if (sa.st_size != sb.st_size) return 0;
    fa = fopen(a, "rb");
    if (fa == NULL) return 0;
    fb = fopen(b, "rb");
    if (fb == NULL) {
        fclose(fa);
        return 0;
    }
    for (;;) {
        size_t got_a = fread(buf_a, 1, sizeof buf_a, fa);
        size_t got_b = fread(buf_b, 1, sizeof buf_b, fb);
        if (got_a != got_b || memcmp(buf_a, buf_b, got_a) != 0) {
            same = 0;
            break;
        }
        if (got_a == 0) break;
    }
    fclose(fa);
    fclose(fb);
    return same;
}

/* Saves SRAM to path.tmp and atomically renames it when the contents changed.
 * Returns 1 if the file changed, 0 if unchanged, -1 on error. */
static int save_sram_atomic(const char *path, int *changed) {
    char tmp[PATH_MAX];

    if (changed != NULL) *changed = 0;
    if (snprintf(tmp, sizeof tmp, "%s.tmp", path) >= (int)sizeof tmp) return -1;
    if (!kss_save_sram(tmp)) {
        unlink(tmp);
        return -1;
    }
    if (files_identical(tmp, path)) {
        unlink(tmp);
        return 0;
    }
    if (rename(tmp, path) != 0) {
        unlink(tmp);
        return -1;
    }
    if (changed != NULL) *changed = 1;
    return 1;
}

static int write_ppm(const char *path, const uint32_t *fb, int width, int height) {
    FILE *file;
    uint8_t row[352 * 3];
    int x;
    int y;
    int ok = 1;

    if (width <= 0 || width > 352 || height <= 0) return 0;
    file = fopen(path, "wb");
    if (file == NULL) return 0;
    if (fprintf(file, "P6\n%d %d\n255\n", width, height) < 0) ok = 0;
    for (y = 0; ok && y < height; y++) {
        const uint32_t *line = fb + (size_t)y * (size_t)width;
        for (x = 0; x < width; x++) {
            uint32_t pixel = line[x];
            row[x * 3 + 0] = (uint8_t)((pixel >> 16) & 0xffu);
            row[x * 3 + 1] = (uint8_t)((pixel >> 8) & 0xffu);
            row[x * 3 + 2] = (uint8_t)(pixel & 0xffu);
        }
        if (fwrite(row, 3, (size_t)width, file) != (size_t)width) ok = 0;
    }
    if (fclose(file) != 0) ok = 0;
    return ok;
}

static int redirect_stdout_to_stderr(void) {
    int saved;

    fflush(stdout);
    saved = dup(STDOUT_FILENO);
    if (saved < 0) return -1;
    if (dup2(STDERR_FILENO, STDOUT_FILENO) < 0) {
        close(saved);
        return -1;
    }
    return saved;
}

static void restore_stdout(int saved) {
    if (saved < 0) return;
    fflush(stdout);
    dup2(saved, STDOUT_FILENO);
    close(saved);
}

static int run_headless(const Options *options, const Paths *paths, int saved_stdout) {
    int16_t audio[4096];
    unsigned long long total_samples = 0;
    unsigned long long nonzero_samples = 0;
    unsigned long long nonblack_pixels = 0;
    unsigned long long sram_bytes = 0;
    int executed = 0;
    int i;
    int width;
    int height;
    const uint32_t *fb;

    for (i = 0; i < options->headless_frames; i++) {
        uint16_t p1 = 0;

        if (options->press_start_every > 0 && (i % options->press_start_every) < 6) {
            p1 |= PAD_START;
        }
        kss_step(p1, 0);
        executed++;

        for (;;) {
            size_t got = kss_audio(audio, 4096);
            size_t j;
            if (got == 0) break;
            total_samples += (unsigned long long)got;
            for (j = 0; j < got; j++) {
                if (audio[j] != 0) nonzero_samples++;
            }
        }

        if (g_interrupted) {
            warn_msg("interrupted after %d frames", executed);
            break;
        }
    }

    width = kss_fb_w();
    height = kss_fb_h();
    fb = kss_fb();
    if (fb == NULL || width <= 0 || height <= 0) {
        warn_msg("runtime returned no framebuffer");
        restore_stdout(saved_stdout);
        return 1;
    }
    for (i = 0; i < height; i++) {
        int x;
        for (x = 0; x < width; x++) {
            if ((fb[(size_t)i * (size_t)width + (size_t)x] & 0x00ffffffu) != 0) {
                nonblack_pixels++;
            }
        }
    }

    if (options->dump_path != NULL) {
        if (!write_ppm(options->dump_path, fb, width, height)) {
            die("cannot write PPM dump '%s'", options->dump_path);
        }
        warn_msg("wrote %s (%dx%d)", options->dump_path, width, height);
    }

    {
        int changed = 0;
        int saved = save_sram_atomic(paths->sram_path, &changed);
        struct stat st;
        if (saved < 0) {
            warn_msg("could not save SRAM to %s", paths->sram_path);
        } else {
            if (changed) warn_msg("saved SRAM to %s", paths->sram_path);
            if (stat(paths->sram_path, &st) == 0) {
                sram_bytes = (unsigned long long)st.st_size;
            }
        }
    }

    if (options->audio_stats) {
        fprintf(stderr,
                "kss-native: audio: %llu samples, %llu nonzero (%.2f%%)\n",
                total_samples, nonzero_samples,
                total_samples > 0 ? 100.0 * (double)nonzero_samples / (double)total_samples : 0.0);
        fprintf(stderr, "kss-native: video: %dx%d, %llu nonblack pixels\n",
                width, height, nonblack_pixels);
    }

    if (g_interrupted) {
        warn_msg("headless run interrupted");
    }

    /* Runtime diagnostics go to stderr; restore real stdout for the JSON line. */
    restore_stdout(saved_stdout);
    printf("{\"frames\":%d,\"fb\":[%d,%d],\"nonblack_pixels\":%llu,"
           "\"audio_samples\":%llu,\"audio_nonzero\":%llu,\"sram_bytes\":%llu}\n",
           executed, width, height, nonblack_pixels,
           total_samples, nonzero_samples, sram_bytes);
    fflush(stdout);
    return 0;
}

static uint16_t keyboard_bits(const bool *keys, int player) {
    uint16_t bits = 0;

    if (player == 1) {
        if (keys[SDL_SCANCODE_UP]) bits |= PAD_UP;
        if (keys[SDL_SCANCODE_DOWN]) bits |= PAD_DOWN;
        if (keys[SDL_SCANCODE_LEFT]) bits |= PAD_LEFT;
        if (keys[SDL_SCANCODE_RIGHT]) bits |= PAD_RIGHT;
        if (keys[SDL_SCANCODE_Z]) bits |= PAD_B;
        if (keys[SDL_SCANCODE_X]) bits |= PAD_A;
        if (keys[SDL_SCANCODE_A]) bits |= PAD_Y;
        if (keys[SDL_SCANCODE_S]) bits |= PAD_X;
        if (keys[SDL_SCANCODE_Q]) bits |= PAD_L;
        if (keys[SDL_SCANCODE_E]) bits |= PAD_R;
        if (keys[SDL_SCANCODE_RETURN]) bits |= PAD_START;
        if (keys[SDL_SCANCODE_RSHIFT]) bits |= PAD_SELECT;
    } else {
        if (keys[SDL_SCANCODE_I]) bits |= PAD_UP;
        if (keys[SDL_SCANCODE_K]) bits |= PAD_DOWN;
        if (keys[SDL_SCANCODE_J]) bits |= PAD_LEFT;
        if (keys[SDL_SCANCODE_L]) bits |= PAD_RIGHT;
        if (keys[SDL_SCANCODE_N]) bits |= PAD_B;
        if (keys[SDL_SCANCODE_M]) bits |= PAD_A;
        if (keys[SDL_SCANCODE_H]) bits |= PAD_Y;
        if (keys[SDL_SCANCODE_U]) bits |= PAD_X;
        if (keys[SDL_SCANCODE_7]) bits |= PAD_L;
        if (keys[SDL_SCANCODE_9]) bits |= PAD_R;
        if (keys[SDL_SCANCODE_0]) bits |= PAD_START;
        if (keys[SDL_SCANCODE_8]) bits |= PAD_SELECT;
    }
    return bits;
}

static uint16_t gamepad_bits(SDL_Gamepad *pad) {
    uint16_t bits = 0;
    Sint16 axis_x;
    Sint16 axis_y;

    if (pad == NULL) return 0;

    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_SOUTH)) bits |= PAD_B;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_EAST)) bits |= PAD_A;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_WEST)) bits |= PAD_Y;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_NORTH)) bits |= PAD_X;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER)) bits |= PAD_L;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER)) bits |= PAD_R;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_BACK)) bits |= PAD_SELECT;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_START)) bits |= PAD_START;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_DPAD_UP)) bits |= PAD_UP;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_DPAD_DOWN)) bits |= PAD_DOWN;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_DPAD_LEFT)) bits |= PAD_LEFT;
    if (SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_DPAD_RIGHT)) bits |= PAD_RIGHT;

    axis_x = SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTX);
    axis_y = SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTY);
    if (axis_x > 16384) bits |= PAD_RIGHT;
    else if (axis_x < -16384) bits |= PAD_LEFT;
    if (axis_y > 16384) bits |= PAD_DOWN;
    else if (axis_y < -16384) bits |= PAD_UP;

    return bits;
}

static void open_initial_gamepads(App *app) {
    int count = 0;
    SDL_JoystickID *ids = SDL_GetGamepads(&count);
    int i;

    for (i = 0; i < count && app->npads < 2; i++) {
        SDL_Gamepad *pad = SDL_OpenGamepad(ids[i]);
        if (pad != NULL) {
            const char *name = SDL_GetGamepadName(pad);
            app->pads[app->npads++] = pad;
            warn_msg("gamepad %d: %s", app->npads, name != NULL ? name : "unknown");
        }
    }
    SDL_free(ids);
}

static void close_gamepads(App *app) {
    int i;
    for (i = 0; i < app->npads; i++) {
        SDL_CloseGamepad(app->pads[i]);
        app->pads[i] = NULL;
    }
    app->npads = 0;
}

static void handle_gamepad_event(App *app, const SDL_Event *event) {
    int i;

    if (event->type == SDL_EVENT_GAMEPAD_ADDED) {
        if (app->npads < 2) {
            SDL_Gamepad *pad = SDL_OpenGamepad(event->gdevice.which);
            if (pad != NULL) {
                const char *name = SDL_GetGamepadName(pad);
                app->pads[app->npads++] = pad;
                warn_msg("gamepad %d connected: %s", app->npads,
                         name != NULL ? name : "unknown");
            }
        }
        return;
    }

    if (event->type == SDL_EVENT_GAMEPAD_REMOVED) {
        for (i = 0; i < app->npads; i++) {
            if (SDL_GetGamepadID(app->pads[i]) == event->gdevice.which) {
                SDL_CloseGamepad(app->pads[i]);
                if (i + 1 < app->npads) {
                    app->pads[i] = app->pads[i + 1];
                }
                app->pads[app->npads - 1] = NULL;
                app->npads--;
                break;
            }
        }
    }
}

static void ensure_texture(App *app) {
    int width = kss_fb_w();
    int height = kss_fb_h();

    if (app->texture != NULL && app->tex_w == width && app->tex_h == height) return;
    if (app->texture != NULL) {
        SDL_DestroyTexture(app->texture);
        app->texture = NULL;
    }
    app->texture = SDL_CreateTexture(app->renderer, SDL_PIXELFORMAT_XRGB8888,
                                     SDL_TEXTUREACCESS_STREAMING, width, height);
    if (app->texture == NULL) {
        die("cannot create %dx%d texture: %s", width, height, SDL_GetError());
    }
    SDL_SetTextureScaleMode(app->texture, SDL_SCALEMODE_NEAREST);
    app->tex_w = width;
    app->tex_h = height;
}

static void present_frame(App *app) {
    const uint32_t *fb;
    int fb_width;
    int fb_height;
    int out_width = 0;
    int out_height = 0;
    int scale;
    float dst_w;
    float dst_h;
    SDL_FRect dst;

    ensure_texture(app);
    fb = kss_fb();
    fb_width = app->tex_w;
    fb_height = app->tex_h;
    if (fb == NULL) return;

    if (!SDL_UpdateTexture(app->texture, NULL, fb, fb_width * (int)sizeof(uint32_t))) {
        warn_msg("texture upload failed: %s", SDL_GetError());
    }

    if (!SDL_GetRenderOutputSize(app->renderer, &out_width, &out_height) ||
        out_width <= 0 || out_height <= 0) {
        out_width = fb_width * 3;
        out_height = fb_height * 3;
    }

    scale = out_width / fb_width;
    if (out_height / fb_height < scale) scale = out_height / fb_height;
    if (scale >= 1) {
        dst_w = (float)fb_width * (float)scale;
        dst_h = (float)fb_height * (float)scale;
    } else {
        float sx = (float)out_width / (float)fb_width;
        float sy = (float)out_height / (float)fb_height;
        float fit = sx < sy ? sx : sy;
        dst_w = (float)fb_width * fit;
        dst_h = (float)fb_height * fit;
    }
    dst.x = ((float)out_width - dst_w) * 0.5f;
    dst.y = ((float)out_height - dst_h) * 0.5f;
    dst.w = dst_w;
    dst.h = dst_h;

    SDL_SetRenderDrawColor(app->renderer, 0, 0, 0, 255);
    SDL_RenderClear(app->renderer);
    SDL_RenderTexture(app->renderer, app->texture, NULL, &dst);
    SDL_RenderPresent(app->renderer);
}

static void pump_audio(App *app, bool queue) {
    int16_t buffer[4096];

    for (;;) {
        size_t got = kss_audio(buffer, 4096);
        int bytes;
        int queued;

        if (got == 0) break;
        if (!queue || app->audio == NULL) continue;

        bytes = (int)(got * sizeof(int16_t));
        queued = SDL_GetAudioStreamQueued(app->audio);
        if (queued < 0) queued = 0;
        if (queued + bytes <= AUDIO_QUEUE_LIMIT_BYTES) {
            if (!SDL_PutAudioStreamData(app->audio, buffer, bytes) && !app->audio_warned) {
                warn_msg("audio queueing failed: %s", SDL_GetError());
                app->audio_warned = 1;
            }
        }
    }
}

static void set_paused(App *app, bool paused) {
    if (app->paused == paused) return;
    app->paused = paused;
    if (app->audio != NULL) {
        if (paused) {
            SDL_PauseAudioStreamDevice(app->audio);
            SDL_ClearAudioStream(app->audio);
        } else {
            SDL_ResumeAudioStreamDevice(app->audio);
        }
    }
    warn_msg("%s", paused ? "paused" : "resumed");
}

static void handle_key(App *app, const Options *options, const Paths *paths,
                       SDL_Scancode scancode, int *quit) {
    (void)options;
    switch (scancode) {
    case SDL_SCANCODE_ESCAPE:
        *quit = 1;
        break;
    case SDL_SCANCODE_F11: {
        SDL_WindowFlags flags = SDL_GetWindowFlags(app->window);
        bool fullscreen = (flags & SDL_WINDOW_FULLSCREEN) != 0;
        SDL_SetWindowFullscreen(app->window, !fullscreen);
        break;
    }
    case SDL_SCANCODE_W:
        app->widescreen = !app->widescreen;
        kss_set_widescreen(app->widescreen ? 1 : 0);
        warn_msg("widescreen %s (%dx%d)", app->widescreen ? "on" : "off",
                 kss_fb_w(), kss_fb_h());
        break;
    case SDL_SCANCODE_P:
        set_paused(app, !app->paused);
        break;
    case SDL_SCANCODE_F1:
        if (kss_save_state(paths->state_path)) {
            warn_msg("saved state to %s", paths->state_path);
        } else {
            warn_msg("could not save state to %s", paths->state_path);
        }
        break;
    case SDL_SCANCODE_F2:
        if (kss_load_state(paths->state_path)) {
            warn_msg("loaded state from %s", paths->state_path);
        } else {
            warn_msg("could not load state from %s", paths->state_path);
        }
        break;
    default:
        break;
    }
}

static void handle_event(App *app, const Options *options, const Paths *paths,
                         const SDL_Event *event, int *quit) {
    switch (event->type) {
    case SDL_EVENT_QUIT:
    case SDL_EVENT_WINDOW_CLOSE_REQUESTED:
        *quit = 1;
        break;
    case SDL_EVENT_KEY_DOWN:
        if (!event->key.repeat) {
            handle_key(app, options, paths, event->key.scancode, quit);
        }
        break;
    case SDL_EVENT_GAMEPAD_ADDED:
    case SDL_EVENT_GAMEPAD_REMOVED:
        handle_gamepad_event(app, event);
        break;
    default:
        break;
    }
}

static SDL_AudioStream *open_audio(void) {
    SDL_AudioSpec spec;
    SDL_AudioStream *stream;

    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        warn_msg("audio subsystem unavailable (%s); continuing without sound", SDL_GetError());
        return NULL;
    }
    memset(&spec, 0, sizeof spec);
    spec.format = SDL_AUDIO_S16;
    spec.channels = 2;
    spec.freq = AUDIO_RATE;
    stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, NULL, NULL);
    if (stream == NULL) {
        warn_msg("audio device unavailable (%s); continuing without sound", SDL_GetError());
        return NULL;
    }
    if (!SDL_ResumeAudioStreamDevice(stream)) {
        warn_msg("cannot start audio (%s); continuing without sound", SDL_GetError());
        SDL_DestroyAudioStream(stream);
        return NULL;
    }
    return stream;
}

static void cleanup_app(App *app) {
    close_gamepads(app);
    if (app->audio != NULL) SDL_DestroyAudioStream(app->audio);
    if (app->texture != NULL) SDL_DestroyTexture(app->texture);
    if (app->renderer != NULL) SDL_DestroyRenderer(app->renderer);
    if (app->window != NULL) SDL_DestroyWindow(app->window);
    SDL_Quit();
}

static int run_windowed(const Options *options, const Paths *paths) {
    App app;
    uint64_t period = (uint64_t)(1000000000.0 / RUNTIME_FPS + 0.5);
    uint64_t next;
    uint64_t last_sram;
    int frame_count = 0;
    int quit = 0;

    memset(&app, 0, sizeof app);
    app.widescreen = options->widescreen != 0;

    if (!SDL_Init(SDL_INIT_VIDEO)) {
        die("SDL video initialization failed: %s", SDL_GetError());
    }
    if (!SDL_InitSubSystem(SDL_INIT_GAMEPAD)) {
        warn_msg("gamepad subsystem unavailable: %s", SDL_GetError());
    }

    app.window = SDL_CreateWindow("Kirby Super Star (native)",
                                  kss_fb_w() * options->scale,
                                  kss_fb_h() * options->scale,
                                  SDL_WINDOW_RESIZABLE);
    if (app.window == NULL) {
        die("cannot create window: %s", SDL_GetError());
    }
    SDL_SetWindowPosition(app.window, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED);
    app.renderer = SDL_CreateRenderer(app.window, NULL);
    if (app.renderer == NULL) {
        die("cannot create renderer: %s", SDL_GetError());
    }
    SDL_SetRenderVSync(app.renderer, 0);

    if (options->fullscreen) {
        SDL_SetWindowFullscreen(app.window, true);
    }

    ensure_texture(&app);
    app.audio = open_audio();
    open_initial_gamepads(&app);

    warn_msg("window %dx%d, framebuffer %dx%d, scale %d%s",
             kss_fb_w() * options->scale, kss_fb_h() * options->scale,
             kss_fb_w(), kss_fb_h(), options->scale,
             options->fullscreen ? ", fullscreen" : "");
    warn_msg("audio %s", app.audio != NULL ? "44100 Hz stereo" : "disabled");
    warn_msg("ready: Esc quit, F11 fullscreen, W widescreen, P pause, F1/F2 state, Tab fast-forward");

    next = SDL_GetTicksNS();
    last_sram = next;

    while (!quit && !g_interrupted) {
        SDL_Event event;
        const bool *keys;
        bool fast_forward;
        int steps;
        int i;

        while (SDL_PollEvent(&event)) {
            handle_event(&app, options, paths, &event, &quit);
            if (quit) break;
        }
        if (quit) break;

        keys = SDL_GetKeyboardState(NULL);
        fast_forward = keys[SDL_SCANCODE_TAB] && !app.paused;
        steps = app.paused ? 0 : (fast_forward ? 4 : 1);

        if (options->exit_after_frames > 0) {
            int remaining = options->exit_after_frames - frame_count;
            if (remaining < steps) steps = remaining;
            if (steps < 0) steps = 0;
        }

        for (i = 0; i < steps; i++) {
            uint16_t p1 = (uint16_t)(keyboard_bits(keys, 1) | gamepad_bits(app.pads[0]));
            uint16_t p2 = (uint16_t)(keyboard_bits(keys, 2) | gamepad_bits(app.pads[1]));
            kss_step(p1, p2);
            frame_count++;
            pump_audio(&app, !fast_forward && !app.paused);
        }

        present_frame(&app);

        next += period * (uint64_t)(steps > 0 ? steps : 1);
        {
            uint64_t now = SDL_GetTicksNS();
            if (now < next) {
                SDL_DelayNS(next - now);
            } else if (now - next > period * 8u) {
                next = now;
            }
            if (now - last_sram >= SRAM_SAVE_INTERVAL_NS) {
                int changed = 0;
                if (save_sram_atomic(paths->sram_path, &changed) < 0) {
                    warn_msg("periodic SRAM save failed");
                } else if (changed) {
                    warn_msg("saved SRAM to %s", paths->sram_path);
                }
                last_sram = now;
            }
        }

        if (options->exit_after_frames > 0 && frame_count >= options->exit_after_frames) {
            quit = 1;
        }
    }

    {
        int changed = 0;
        if (save_sram_atomic(paths->sram_path, &changed) < 0) {
            warn_msg("could not save SRAM to %s", paths->sram_path);
        } else if (changed) {
            warn_msg("saved SRAM to %s", paths->sram_path);
        }
    }

    warn_msg("exiting after %d frames", frame_count);
    cleanup_app(&app);
    return g_interrupted ? 130 : 0;
}

int main(int argc, char **argv) {
    Options options;
    Paths paths;
    uint8_t *rom_data = NULL;
    size_t rom_size = 0;
    char actual_hash[65];
    int stdout_saved = -1;
    int result;

    parse_args(argc, argv, &options);
    init_paths(&options, &paths);

    if (options.headless_frames > 0) {
        stdout_saved = redirect_stdout_to_stderr();
    }

    rom_data = read_whole_file(options.rom_path, &rom_size);
    if (rom_data == NULL) {
        die("cannot read ROM '%s'", options.rom_path);
    }
    if (rom_size != ROM_BYTES) {
        die("'%s' is %zu bytes; expected the unheadered USA ROM (%u bytes)",
            options.rom_path, rom_size, ROM_BYTES);
    }
    sha256_hex(rom_data, rom_size, actual_hash);
    if (strcmp(actual_hash, ROM_SHA256_HEX) != 0) {
        die("'%s' has SHA-256 %s; expected the supported USA ROM %s. Refusing to run.",
            options.rom_path, actual_hash, ROM_SHA256_HEX);
    }
    warn_msg("ROM verified (%s)", ROM_SHA256_HEX);

    if (options.ips_path != NULL) {
        uint8_t *ips_data;
        size_t ips_size = 0;
        uint8_t *patched;
        char error[256];

        ips_data = read_whole_file(options.ips_path, &ips_size);
        if (ips_data == NULL) {
            die("cannot read IPS patch '%s'", options.ips_path);
        }
        patched = (uint8_t *)malloc(rom_size);
        if (patched == NULL) {
            free(ips_data);
            die("out of memory applying IPS patch");
        }
        memcpy(patched, rom_data, rom_size);
        if (!ips_apply(ips_data, ips_size, patched, rom_size, error, sizeof error)) {
            free(ips_data);
            free(patched);
            die("IPS patch '%s' failed: %s", options.ips_path, error);
        }
        free(ips_data);
        free(rom_data);
        rom_data = patched;
        sha256_hex(rom_data, rom_size, actual_hash);
        warn_msg("applied IPS %s (patched SHA-256 %s)", options.ips_path, actual_hash);
    }

    if (!kss_open_memory(rom_data, rom_size)) {
        die("runtime failed to open the ROM in memory");
    }
    if (options.expansion_path != NULL) {
        if (!kss_load_expansion(options.expansion_path)) {
            die("cannot load expansion ROM '%s' (missing, empty or over 896 KiB)", options.expansion_path);
        }
        warn_msg("loaded expansion %s (%u bytes at 70:0000)", options.expansion_path, (unsigned)kss_expansion_size());
    }

    if (!options.widescreen) {
        kss_set_widescreen(0);
    }

    {
        struct stat st;
        if (stat(paths.sram_path, &st) == 0) {
            if (!kss_load_sram(paths.sram_path)) {
                warn_msg("could not load SRAM from %s", paths.sram_path);
            }
        }
    }

    if (paths.mods_dir[0] != '\0') {
        int loaded = kss_mods_init(paths.mods_dir);
        if (loaded > 0) {
            warn_msg("loaded %d mod(s) from %s", loaded, paths.mods_dir);
        } else if (loaded < 0) {
            warn_msg("could not initialize mods from %s", paths.mods_dir);
        }
    }

    if (options.load_state_path != NULL) {
        /* Start from a save state (e.g. a test fixture) instead of power-on. */
        if (!kss_load_state(options.load_state_path)) die("could not load state %s", options.load_state_path);
        warn_msg("loaded state %s", options.load_state_path);
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    if (options.headless_frames > 0) {
        result = run_headless(&options, &paths, stdout_saved);
        stdout_saved = -1;
    } else {
        result = run_windowed(&options, &paths);
    }

    kss_close();
    free(rom_data);
    return result;
}
