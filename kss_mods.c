/* Data-driven sprite-replacement mods for the KSS native runtime.
 *
 * A mod is a directory with mod.txt plus raw indexed art (.bin). Two kinds:
 *   actor  - replaces every native object of one actor (matched by OBJ
 *            palette + tile range) with one animated frame anchored to the
 *            actor's world position; the frame is drawn at the first matched
 *            object in OAM order, so priority and sprite order stay native.
 *   object - replaces each matching native object in place with an art frame
 *            (same position, flip and priority), e.g. projectiles.
 *   tiles  - background tiles: any 8x8 BG tile whose VRAM pixel data hashes
 *            to a tile-pack entry is drawn from the pack instead (2bpp/4bpp).
 *            VRAM itself is never modified.
 * Rules activate only while all their `when` conditions hold (BW-RAM words).
 * See mods/README.md for the format.
 */
#include "kss_mods.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

uint16_t kss_read_bwram16(uint32_t off);
uint16_t* kss_cgram(void);

#define MAX_RULES 32
#define MAX_COND 8
#define MAX_FRAMES 64
#define MAX_ANIMS 16
#define MAX_POSES 64
#define MAX_STEPS 16
#define MAX_CG 32          /* cgram / cgram_lines directives per rule */

typedef struct { uint32_t addr; int op; int n; uint16_t v[4]; } Cond; /* op 0 ==, 1 in, 2 != */
typedef struct { char name[24]; int nsteps; int frame[MAX_STEPS]; int dur[MAX_STEPS]; } Anim;

typedef struct {
    int kind;                 /* 0 actor, 1 object, 2 tiles */
    char name[32];
    int ncond; Cond cond[MAX_COND];
    int match_pal, tile_lo, tile_hi;
    int w, h, nframes; uint8_t* art; char fname[MAX_FRAMES][24];
    int has_palette, pal_index; uint16_t colors[16];
    int draw_pal;             /* palette used for art pixels (-1 = object's own) */
    uint32_t ax, ay, camx, camy, pose_addr;
    int anchor_x, anchor_y, flip_invert;
    int nanims; Anim anims[MAX_ANIMS];
    int npose; uint16_t pose_v[MAX_POSES]; int pose_anim[MAX_POSES];
    int default_anim;
    int obj_anim, off_x, off_y;
    /* Per-shot state (object rules): the owner's type-5 shot under the
     * sprite picks the animation from its own state word. */
    int has_shot_state, shot_owner; uint32_t shot_state_addr, shot_camx, shot_camy; uint16_t shot_mask;
    int nstate; uint16_t state_v[MAX_POSES]; int state_anim[MAX_POSES];
    int active, cur_anim, step, tick, frame, sx, sy, flip, last_flip, drawn_line, seen_now, seen_prev;
    int ncg; uint16_t cg_start[MAX_CG]; uint16_t cg_count[MAX_CG]; uint16_t cg_words[MAX_CG][256]; uint16_t cg_y0[MAX_CG], cg_y1[MAX_CG];
    int ntiles; struct TileEntry* tiles;
    int scope_always, matched;    /* tiles: palette writes only while >=1 own tile is in VRAM */
} Rule;

typedef struct TileEntry { uint64_t hash; uint8_t bpp; uint16_t words[16]; } TileEntry;

const uint16_t* kss_ovr4[2048];
const uint16_t* kss_ovr2[4096];

static Rule g_rules[MAX_RULES];
static int g_nrules;
static uint32_t g_frame_no;

static int parse_num(const char* s) { return (int)strtol(s, NULL, 0); }
static int find_frame(Rule* r, const char* n) {
    for (int i = 0; i < r->nframes; i++) if (!strcmp(r->fname[i], n)) return i;
    return -1;
}
static int find_anim(Rule* r, const char* n) {
    for (int i = 0; i < r->nanims; i++) if (!strcmp(r->anims[i].name, n)) return i;
    return -1;
}

static int load_mod(const char* dir) {
    char path[1024]; snprintf(path, sizeof path, "%s/mod.txt", dir);
    FILE* f = fopen(path, "r");
    if (!f) { fprintf(stderr, "kss-mods: missing %s\n", path); return -1; }
    Rule* r = NULL; char line[512]; int lineno = 0, loaded = 0;
    while (fgets(line, sizeof line, f)) {
        lineno++;
        char* hash = strchr(line, '#'); if (hash) *hash = 0;
        char* tok[40]; int nt = 0;
        for (char* t = strtok(line, " \t\r\n"); t && nt < 40; t = strtok(NULL, " \t\r\n")) tok[nt++] = t;
        if (!nt) continue;
#define NEED(k) do { if (nt < (k)) { fprintf(stderr, "kss-mods: %s:%d: too few fields\n", path, lineno); goto fail; } } while (0)
        if (!strcmp(tok[0], "rule")) {
            NEED(3);
            if (g_nrules >= MAX_RULES) goto fail;
            r = &g_rules[g_nrules++]; memset(r, 0, sizeof *r);
            r->kind = !strcmp(tok[1], "object") ? 1 : !strcmp(tok[1], "tiles") ? 2 : 0; snprintf(r->name, sizeof r->name, "%s", tok[2]);
            r->draw_pal = -1; r->default_anim = -1; r->obj_anim = -1; r->drawn_line = -1; r->cur_anim = -1;
            loaded++;
            continue;
        }
        if (!r) { fprintf(stderr, "kss-mods: %s:%d: directive before rule\n", path, lineno); goto fail; }
        if (!strcmp(tok[0], "when")) {
            NEED(4); if (r->ncond >= MAX_COND) goto fail;
            Cond* c = &r->cond[r->ncond++]; c->addr = (uint32_t)parse_num(tok[1]);
            c->op = !strcmp(tok[2], "in") ? 1 : !strcmp(tok[2], "!=") ? 2 : 0;
            c->n = 0; for (int i = 3; i < nt && c->n < 4; i++) c->v[c->n++] = (uint16_t)parse_num(tok[i]);
        } else if (!strcmp(tok[0], "match")) {           /* match palette P tiles LO HI */
            NEED(6); r->match_pal = parse_num(tok[2]); r->tile_lo = parse_num(tok[4]); r->tile_hi = parse_num(tok[5]);
        } else if (!strcmp(tok[0], "art")) {             /* art FILE W H name0 name1 ... */
            NEED(5); r->w = parse_num(tok[2]); r->h = parse_num(tok[3]); r->nframes = nt - 4;
            if (r->nframes > MAX_FRAMES || r->w > 128 || r->h > 128) goto fail;
            for (int i = 0; i < r->nframes; i++) snprintf(r->fname[i], 24, "%s", tok[4 + i]);
            char ap[1024]; snprintf(ap, sizeof ap, "%s/%s", dir, tok[1]);
            FILE* a = fopen(ap, "rb"); if (!a) { fprintf(stderr, "kss-mods: missing %s\n", ap); goto fail; }
            size_t need = (size_t)r->w * r->h * r->nframes; r->art = malloc(need);
            size_t got = r->art ? fread(r->art, 1, need, a) : 0; fclose(a);
            if (got != need) { fprintf(stderr, "kss-mods: %s size %zu != %zu\n", ap, got, need); goto fail; }
        } else if (!strcmp(tok[0], "palette")) {         /* palette OBJPAL c1..c15 (BGR555 hex) */
            NEED(17); r->has_palette = 1; r->pal_index = parse_num(tok[1]);
            for (int i = 1; i < 16; i++) r->colors[i] = (uint16_t)strtol(tok[1 + i], NULL, 16);
        } else if (!strcmp(tok[0], "cgram") || !strcmp(tok[0], "cgram_lines")) {
            /* cgram START w1 ...           : written once before each frame
             * cgram_lines Y0 Y1 START w1 ...: written at the start of every scanline
             *                                 Y0..Y1 (survives mid-frame palette loads) */
            int lines = !strcmp(tok[0], "cgram_lines"), at = lines ? 3 : 1;
            NEED(at + 2);
            if (r->ncg >= MAX_CG || nt - at - 1 > 256) { fprintf(stderr, "kss-mods: %s:%d: at most %d cgram directives of <=256 words per rule\n", path, lineno, MAX_CG); goto fail; }
            r->cg_y0[r->ncg] = lines ? (uint16_t)parse_num(tok[1]) : 0xFFFF;
            r->cg_y1[r->ncg] = lines ? (uint16_t)parse_num(tok[2]) : 0;
            r->cg_start[r->ncg] = (uint16_t)parse_num(tok[at]); r->cg_count[r->ncg] = (uint16_t)(nt - at - 1);
            for (int i = at + 1; i < nt; i++) r->cg_words[r->ncg][i - at - 1] = (uint16_t)strtol(tok[i], NULL, 16);
            if (r->cg_start[r->ncg] + r->cg_count[r->ncg] > 256) goto fail;
            r->ncg++;
        } else if (!strcmp(tok[0], "tilepack")) {        /* tilepack FILE (KTP1) */
            NEED(2); char tp[1024]; snprintf(tp, sizeof tp, "%s/%s", dir, tok[1]);
            FILE* t = fopen(tp, "rb"); if (!t) { fprintf(stderr, "kss-mods: missing %s\n", tp); goto fail; }
            char magic[4]; uint32_t count = 0;
            if (fread(magic, 1, 4, t) != 4 || memcmp(magic, "KTP1", 4) || fread(&count, 4, 1, t) != 1 || count > 65536) { fclose(t); goto fail; }
            r->tiles = calloc(count ? count : 1, sizeof(TileEntry)); r->ntiles = 0;
            for (uint32_t k = 0; k < count; k++) {
                uint8_t hdr[12]; if (fread(hdr, 1, 12, t) != 12) { fclose(t); goto fail; }
                TileEntry* e = &r->tiles[r->ntiles++]; e->bpp = hdr[0];
                memcpy(&e->hash, hdr + 4, 8);
                int nw = e->bpp == 4 ? 16 : 8;
                if ((e->bpp != 2 && e->bpp != 4) || fread(e->words, 2, (size_t)nw, t) != (size_t)nw) { fclose(t); goto fail; }
            }
            fclose(t);
        } else if (!strcmp(tok[0], "scope")) {           /* scope always | scope tiles (default) */
            NEED(2); r->scope_always = !strcmp(tok[1], "always");
        } else if (!strcmp(tok[0], "draw_palette")) { NEED(2); r->draw_pal = parse_num(tok[1]);
        } else if (!strcmp(tok[0], "actor")) {           /* actor X Y CAMX CAMY POSE */
            NEED(6); r->ax = parse_num(tok[1]); r->ay = parse_num(tok[2]); r->camx = parse_num(tok[3]); r->camy = parse_num(tok[4]); r->pose_addr = parse_num(tok[5]);
        } else if (!strcmp(tok[0], "anchor")) { NEED(3); r->anchor_x = parse_num(tok[1]); r->anchor_y = parse_num(tok[2]);
        } else if (!strcmp(tok[0], "offset")) { NEED(3); r->off_x = parse_num(tok[1]); r->off_y = parse_num(tok[2]);
        } else if (!strcmp(tok[0], "shot_state")) {     /* shot_state OWNER STATE_ADDR MASK CAMX CAMY */
            NEED(6); r->has_shot_state = 1; r->shot_owner = parse_num(tok[1]); r->shot_state_addr = (uint32_t)parse_num(tok[2]);
            r->shot_mask = (uint16_t)parse_num(tok[3]); r->shot_camx = (uint32_t)parse_num(tok[4]); r->shot_camy = (uint32_t)parse_num(tok[5]);
        } else if (!strcmp(tok[0], "state")) {          /* state VALUE ANIM */
            NEED(3); if (r->nstate >= MAX_POSES) goto fail;
            int an = find_anim(r, tok[2]); if (an < 0) { fprintf(stderr, "kss-mods: %s:%d: unknown anim %s\n", path, lineno, tok[2]); goto fail; }
            r->state_v[r->nstate] = (uint16_t)parse_num(tok[1]); r->state_anim[r->nstate++] = an;
        } else if (!strcmp(tok[0], "flip_invert")) { r->flip_invert = 1;
        } else if (!strcmp(tok[0], "anim")) {             /* anim NAME dur:frame ... (dur 0 = hold) */
            NEED(3); if (r->nanims >= MAX_ANIMS) goto fail;
            Anim* an = &r->anims[r->nanims++]; snprintf(an->name, sizeof an->name, "%s", tok[1]);
            for (int i = 2; i < nt && an->nsteps < MAX_STEPS; i++) {
                char* colon = strchr(tok[i], ':'); if (!colon) goto fail; *colon = 0;
                int fr = find_frame(r, colon + 1);
                if (fr < 0) { fprintf(stderr, "kss-mods: %s:%d: unknown frame %s\n", path, lineno, colon + 1); goto fail; }
                an->dur[an->nsteps] = parse_num(tok[i]); an->frame[an->nsteps] = fr; an->nsteps++;
            }
        } else if (!strcmp(tok[0], "pose")) {             /* pose ANIM v1 v2 ... */
            NEED(3); int ai = find_anim(r, tok[1]);
            if (ai < 0) { fprintf(stderr, "kss-mods: %s:%d: unknown anim %s\n", path, lineno, tok[1]); goto fail; }
            for (int i = 2; i < nt && r->npose < MAX_POSES; i++) { r->pose_v[r->npose] = (uint16_t)parse_num(tok[i]); r->pose_anim[r->npose++] = ai; }
        } else if (!strcmp(tok[0], "default")) { NEED(2); r->default_anim = find_anim(r, tok[1]);
        } else if (!strcmp(tok[0], "play")) { NEED(2); r->obj_anim = find_anim(r, tok[1]);
        } else { fprintf(stderr, "kss-mods: %s:%d: unknown directive %s\n", path, lineno, tok[0]); goto fail; }
#undef NEED
    }
    fclose(f);
    return loaded;
fail:
    fclose(f);
    fprintf(stderr, "kss-mods: failed to load %s (line %d)\n", path, lineno);
    return -1;
}

int kss_mods_init(const char* mods_dir) {
    for (int i = 0; i < g_nrules; i++) { free(g_rules[i].art); free(g_rules[i].tiles); }
    g_nrules = 0;
    g_frame_no = 0;   /* (re)loading mods restarts the animation clock: same state, same picture */
    char list[1024]; snprintf(list, sizeof list, "%s/mods.list", mods_dir);
    FILE* f = fopen(list, "r");
    if (!f) return 0;
    int total = 0; char name[256];
    while (fgets(name, sizeof name, f)) {
        name[strcspn(name, " \t\r\n#")] = 0;
        if (!name[0]) continue;
        char dir[1024]; snprintf(dir, sizeof dir, "%s/%s", mods_dir, name);
        int n = load_mod(dir);
        if (n < 0) { fclose(f); return -1; }
        total += n;
    }
    fclose(f);
    fprintf(stderr, "kss-mods: %d rule(s) loaded from %s\n", total, mods_dir);
    return total;
}

static int palette_live(const Rule* r) {
    return r->kind != 2 || r->scope_always || !r->ntiles || r->matched > 0;
}

static int conditions_hold(const Rule* r) {
    for (int i = 0; i < r->ncond; i++) {
        const Cond* c = &r->cond[i]; uint16_t v = kss_read_bwram16(c->addr);
        if (c->op == 0 && v != c->v[0]) return 0;
        if (c->op == 2 && v == c->v[0]) return 0;
        if (c->op == 1) { int ok = 0; for (int k = 0; k < c->n; k++) ok |= v == c->v[k]; if (!ok) return 0; }
    }
    return 1;
}

static int anim_frame_at(const Anim* an, uint32_t t) {
    int total = 0;
    for (int k = 0; k < an->nsteps; k++) total += an->dur[k] > 0 ? an->dur[k] : 1;
    t %= (uint32_t)total;
    for (int k = 0; k < an->nsteps; k++) {
        int d = an->dur[k] > 0 ? an->dur[k] : 1;
        if (t < (uint32_t)d) return an->frame[k];
        t -= (uint32_t)d;
    }
    return an->frame[0];
}

void kss_mods_pre_frame(void) {
    g_frame_no++;
    for (int i = 0; i < g_nrules; i++) {
        Rule* r = &g_rules[i];
        r->active = (r->art || r->ntiles || r->ncg) && conditions_hold(r);
        r->drawn_line = -1; r->seen_prev = r->seen_now; r->seen_now = 0;
        if (!r->active) { r->cur_anim = -1; continue; }
        if (r->has_palette) {
            uint16_t* cg = kss_cgram();
            for (int k = 1; k < 16; k++) cg[0x80 + r->pal_index * 16 + k] = r->colors[k];
        }
        if (r->ncg && palette_live(r)) {
            uint16_t* cg = kss_cgram();
            for (int g = 0; g < r->ncg; g++) if (r->cg_y0[g] == 0xFFFF) for (int k = 0; k < r->cg_count[g]; k++) cg[r->cg_start[g] + k] = r->cg_words[g][k];
        }
        if (r->kind == 2) continue;
        if (r->kind == 0) {
            uint16_t pose = kss_read_bwram16(r->pose_addr); int a = r->default_anim;
            for (int k = 0; k < r->npose; k++) if (r->pose_v[k] == pose) { a = r->pose_anim[k]; break; }
            if (a < 0) a = 0;
            if (a != r->cur_anim) { r->cur_anim = a; r->step = 0; r->tick = 0; }
            Anim* an = &r->anims[a];
            if (an->nsteps) {
                if (an->dur[r->step] > 0 && ++r->tick >= an->dur[r->step]) {
                    r->tick = 0;
                    if (r->step + 1 < an->nsteps) r->step++;
                    else if (an->dur[an->nsteps - 1] > 0) r->step = 0;   /* loop unless last step holds */
                }
                r->frame = an->frame[r->step];
            } else r->frame = 0;
            int x = (int)(uint16_t)(kss_read_bwram16(r->ax) - kss_read_bwram16(r->camx));
            int y = (int)(uint16_t)(kss_read_bwram16(r->ay) - kss_read_bwram16(r->camy));
            if (x >= 0x8000) x -= 0x10000;
            if (y >= 0x8000) y -= 0x10000;
            r->sx = x; r->sy = y; r->flip = r->last_flip;
        } else {
            r->frame = (r->obj_anim >= 0 && r->anims[r->obj_anim].nsteps) ? anim_frame_at(&r->anims[r->obj_anim], g_frame_no) : 0;
        }
    }
}

static int draw_row(const Rule* r, int frame, int row, int x0, int flip, uint16_t* buf, int extra, uint16_t z) {
    if (row < 0 || row >= r->h) return 0;
    const uint8_t* src = r->art + ((size_t)frame * r->h + row) * r->w;
    int drew = 0;
    for (int px = 0; px < r->w; px++) {
        int sx = x0 + px;
        if (sx < -extra || sx >= 256 + extra) continue;
        uint8_t c = src[flip ? r->w - 1 - px : px];
        if (!c) continue;
        uint16_t* d = buf + sx;
        if ((d[0] & 0xff) == 0) { d[0] = (uint16_t)(z + c); drew = 1; }
    }
    return drew;
}

/* The owner's live type-5 shot whose screen position is this sprite's centre
 * (within half a sprite + 4 px): its masked state word picks the animation.
 * -1 = no shot or no matching state (keep the rule's own animation). */
static int shot_state_anim(const Rule* r, int cx, int cy, int size) {
    int camx = kss_read_bwram16(r->shot_camx), camy = kss_read_bwram16(r->shot_camy), tol = size / 2 + 4;
    for (int s = 0; s < 0x80; s += 2) {
        if (kss_read_bwram16(0x23C + s) != 5 || kss_read_bwram16(0xE4A + s) != r->shot_owner) continue;
        int sx = (int16_t)(uint16_t)(kss_read_bwram16(0x986 + s) - camx), sy = (int16_t)(uint16_t)(kss_read_bwram16(0xA00 + s) - camy);
        if (abs(sx - cx) > tol || abs(sy - cy) > tol) continue;
        uint16_t v = kss_read_bwram16(r->shot_state_addr + s) & r->shot_mask;
        for (int k = 0; k < r->nstate; k++) if (r->state_v[k] == v) return r->state_anim[k];
        return -1;
    }
    return -1;
}

int kss_mod_obj_hook(int line, int oam1, int x, int row, int size, uint16_t* buf, int extra, uint16_t zprio) {
    int tile = oam1 & 0x1ff, pal = (oam1 & 0xe00) >> 9, hflip = (oam1 & 0x4000) != 0;
    for (int i = 0; i < g_nrules; i++) {
        Rule* r = &g_rules[i];
        if (!r->active || r->kind == 2 || !r->art || pal != r->match_pal || tile < r->tile_lo || tile > r->tile_hi) continue;
        int use_pal = r->draw_pal >= 0 ? r->draw_pal : pal;
        uint16_t z = (uint16_t)(zprio + 0x80 + 16 * use_pal);
        if (r->kind == 0) {
            r->last_flip = hflip ^ r->flip_invert; r->seen_now = 1;
            if (r->drawn_line != line) {
                r->drawn_line = line;
                draw_row(r, r->frame, line - (r->sy - r->anchor_y), r->sx - r->anchor_x, r->flip, buf, extra, z);
            }
        } else {
            int frame = r->frame;
            if (r->has_shot_state) {
                int a = shot_state_anim(r, x + size / 2, line - row + size / 2, size);
                if (a >= 0 && r->anims[a].nsteps) frame = anim_frame_at(&r->anims[a], g_frame_no);
            }
            int ox = x + r->off_x + (size - r->w) / 2;
            draw_row(r, frame, row - r->off_y - (size - r->h) / 2, ox, hflip, buf, extra, z);
        }
        return 1;
    }
    return 0;
}

int kss_mod_line_end(int line, uint16_t* buf, int extra) {
    int drew = 0;
    for (int i = 0; i < g_nrules; i++) {
        Rule* r = &g_rules[i];
        if (!r->active || r->kind != 0 || r->drawn_line == line || !(r->seen_prev || r->seen_now)) continue;
        /* Replacement rows with no native body object on this line (art taller
         * than the native body): draw them behind other sprites at OBJ prio 2. */
        uint16_t z = (uint16_t)((((2 * 4 + 2) * 16 + 4 + 2) << 8) + 0x80 + 16 * (r->draw_pal >= 0 ? r->draw_pal : r->match_pal));
        drew |= draw_row(r, r->frame, line - (r->sy - r->anchor_y), r->sx - r->anchor_x, r->flip, buf, extra, z);
    }
    return drew;
}

/* ---- background tiles ---- */
uint64_t kss_tile_hash(const uint16_t* w, int nwords) {
    uint64_t h = 1469598103934665603ULL;
    for (int i = 0; i < nwords; i++) { h ^= w[i] & 0xff; h *= 1099511628211ULL; h ^= w[i] >> 8; h *= 1099511628211ULL; }
    return h;
}

static const TileEntry* find_tile(uint64_t h, int bpp) {
    for (int i = 0; i < g_nrules; i++) {
        Rule* r = &g_rules[i];
        if (!r->active || r->kind != 2) continue;
        for (int k = 0; k < r->ntiles; k++) if (r->tiles[k].hash == h && r->tiles[k].bpp == bpp) { r->matched++; return &r->tiles[k]; }
    }
    return NULL;
}

static int g_ovr_dirty;
void kss_mods_bg_frame(const uint16_t* vram) {
    int any4 = 0, any2 = 0;
    for (int i = 0; i < g_nrules; i++) {
        Rule* r = &g_rules[i];
        if (!r->active || r->kind != 2) continue;
        r->matched = 0;
        for (int k = 0; k < r->ntiles; k++) { if (r->tiles[k].bpp == 4) any4 = 1; else any2 = 1; }
    }
    if (g_ovr_dirty) { memset(kss_ovr4, 0, sizeof kss_ovr4); memset(kss_ovr2, 0, sizeof kss_ovr2); g_ovr_dirty = 0; }
    static const uint16_t zero[16];
    if (any4) for (int t = 0; t < 2048; t++) {
        const uint16_t* w = vram + t * 16;
        if (!memcmp(w, zero, 32)) continue;
        const TileEntry* e = find_tile(kss_tile_hash(w, 16), 4);
        if (e) { kss_ovr4[t] = e->words; g_ovr_dirty = 1; }
    }
    if (any2) for (int t = 0; t < 4096; t++) {
        const uint16_t* w = vram + t * 8;
        if (!memcmp(w, zero, 16)) continue;
        const TileEntry* e = find_tile(kss_tile_hash(w, 8), 2);
        if (e) { kss_ovr2[t] = e->words; g_ovr_dirty = 1; }
    }
}

void kss_mods_line(uint16_t* cgram, int line) {
    for (int i = 0; i < g_nrules; i++) {
        const Rule* r = &g_rules[i];
        if (!r->active || !palette_live(r)) continue;
        for (int g = 0; g < r->ncg; g++)
            if (r->cg_y0[g] != 0xFFFF && line >= r->cg_y0[g] && line <= r->cg_y1[g])
                for (int k = 0; k < r->cg_count[g]; k++) cgram[r->cg_start[g] + k] = r->cg_words[g][k];
    }
}
