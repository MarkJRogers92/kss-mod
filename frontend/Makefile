# kss-native: SDL3 frontend for the KSS SNES runtime.
#
# The runtime is compiled as one translation unit (kss_mod.c #includes
# snes_runtime.c); never compile snes_runtime.c separately.

CC ?= clang
ifeq ($(origin CC),default)
CC := clang
endif
PYTHON ?= /usr/bin/python3
CFLAGS ?= -O2 -std=c11 -Wall -Wextra
RUNTIME_CFLAGS ?= -O2 -std=c11 -w
LDFLAGS ?=

RUNTIME_DIR := ..
SDL_CFLAGS := $(shell pkg-config --cflags sdl3 2>/dev/null || echo -I/opt/homebrew/include)
SDL_LIBS := $(shell pkg-config --libs sdl3 2>/dev/null || echo -L/opt/homebrew/lib -lSDL3)

# Default test assets; override on the command line or in the environment.
ROM ?= /Users/markrogers/Documents/Codex/2026-10-14/task-4/originals/Kirby Super Star (USA).sfc
IPS ?= /Users/markrogers/kss-work/kss-helper/build/Seven-Abilities.ips
TEST_DIR := test-out
UNIT_BIN := tests/unit_tests

FRONTEND_SRCS := main_sdl.c sha256.c ips.c
FRONTEND_OBJS := $(FRONTEND_SRCS:.c=.o)
RUNTIME_OBJS := kss_mod.o kss_mods.o no_embedded_rom.o
OBJS := $(FRONTEND_OBJS) $(RUNTIME_OBJS)

.PHONY: all test clean

all: kss-native

kss-native: $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJS) $(SDL_LIBS) -lm

main_sdl.o: main_sdl.c $(RUNTIME_DIR)/kss_api.h $(RUNTIME_DIR)/kss_mods.h ips.h sha256.h
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -I. -I$(RUNTIME_DIR) -c $< -o $@

sha256.o: sha256.c sha256.h
	$(CC) $(CFLAGS) -c $< -o $@

ips.o: ips.c ips.h
	$(CC) $(CFLAGS) -c $< -o $@

kss_mod.o: $(RUNTIME_DIR)/kss_mod.c $(RUNTIME_DIR)/kss_mods.h $(RUNTIME_DIR)/snes_runtime.c $(RUNTIME_DIR)/snes_runtime.h
	$(CC) $(RUNTIME_CFLAGS) -I$(RUNTIME_DIR) -c $(RUNTIME_DIR)/kss_mod.c -o $@

kss_mods.o: $(RUNTIME_DIR)/kss_mods.c $(RUNTIME_DIR)/kss_mods.h
	$(CC) $(RUNTIME_CFLAGS) -I$(RUNTIME_DIR) -c $(RUNTIME_DIR)/kss_mods.c -o $@

no_embedded_rom.o: $(RUNTIME_DIR)/no_embedded_rom.c
	$(CC) $(RUNTIME_CFLAGS) -c $(RUNTIME_DIR)/no_embedded_rom.c -o $@

test: kss-native $(UNIT_BIN) tests/check_headless.py
	@test -f "$(ROM)" || { echo "error: ROM not found: $(ROM)"; exit 1; }
	@test -f "$(IPS)" || { echo "error: IPS not found: $(IPS)"; exit 1; }
	@rm -rf $(TEST_DIR)
	@mkdir -p $(TEST_DIR)/saves
	@echo "== (0) IPS (standard/RLE/errors) and SHA-256 unit tests =="
	@./$(UNIT_BIN)
	@echo "== (a) stock ROM, 1300 frames, default 4:3 =="
	@./kss-native --rom "$(ROM)" --saves $(TEST_DIR)/saves \
		--headless-frames 1300 --press-start-every 118 \
		--dump $(TEST_DIR)/test-stock.ppm --audio-stats \
		> $(TEST_DIR)/test-stock.json
	@$(PYTHON) tests/check_headless.py $(TEST_DIR)/test-stock.json \
		--width 256 --height 224 --min-nonblack 20000 --min-audio-nonzero 1000
	@echo "== (b) patched ROM, 1300 frames, --widescreen =="
	@./kss-native --rom "$(ROM)" --ips "$(IPS)" --saves $(TEST_DIR)/saves --widescreen \
		--headless-frames 1300 --press-start-every 118 \
		--dump $(TEST_DIR)/test-patched.ppm --audio-stats \
		> $(TEST_DIR)/test-patched.json
	@$(PYTHON) tests/check_headless.py $(TEST_DIR)/test-patched.json \
		--width 352 --height 224 --min-nonblack 20000 --min-audio-nonzero 1000
	@echo "== (c) wrong ROM must be rejected =="
	@if ./kss-native --rom "$(IPS)" --saves $(TEST_DIR)/saves --headless-frames 1 \
		> $(TEST_DIR)/test-wrong.log 2>&1; then \
		echo "FAIL: IPS file was accepted as a ROM"; exit 1; \
	else \
		echo "PASS: wrong file rejected: $$(head -n 1 $(TEST_DIR)/test-wrong.log)"; \
	fi
	@echo "== all tests passed =="

$(UNIT_BIN): tests/unit_tests.c ips.c ips.h sha256.c sha256.h
	$(CC) $(CFLAGS) -I. -o $@ tests/unit_tests.c ips.c sha256.c

clean:
	rm -f $(OBJS) kss-native $(UNIT_BIN)
	rm -rf $(TEST_DIR)
