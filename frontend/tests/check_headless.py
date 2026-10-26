#!/usr/bin/env python3
"""Validate the JSON produced by `kss-native --headless-frames ...`."""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--min-nonblack", type=int, default=0)
    parser.add_argument("--min-audio-nonzero", type=int, default=0)
    parser.add_argument("--frames", type=int, default=None)
    args = parser.parse_args()

    try:
        with open(args.json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        print("FAIL: cannot read JSON from %s: %s" % (args.json_path, exc))
        return 1

    errors = []
    fb = data.get("fb")
    if fb != [args.width, args.height]:
        errors.append("fb is %r, expected [%d, %d]" % (fb, args.width, args.height))
    if args.frames is not None and data.get("frames") != args.frames:
        errors.append("frames is %r, expected %d" % (data.get("frames"), args.frames))
    if data.get("nonblack_pixels", 0) < args.min_nonblack:
        errors.append("nonblack_pixels %r < %d"
                      % (data.get("nonblack_pixels"), args.min_nonblack))
    if data.get("audio_samples", 0) <= 0:
        errors.append("audio_samples is not positive")
    if data.get("audio_nonzero", 0) < args.min_audio_nonzero:
        errors.append("audio_nonzero %r < %d"
                      % (data.get("audio_nonzero"), args.min_audio_nonzero))
    if not isinstance(data.get("sram_bytes"), int) or data["sram_bytes"] < 0:
        errors.append("sram_bytes is missing or invalid")

    if errors:
        print("FAIL: %s" % args.json_path)
        for message in errors:
            print("  - %s" % message)
        return 1

    print("PASS: %s: frames=%s fb=%s nonblack=%s audio=%s/%s sram_bytes=%s"
          % (args.json_path, data.get("frames"), fb,
             data.get("nonblack_pixels"), data.get("audio_nonzero"),
             data.get("audio_samples"), data.get("sram_bytes")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
