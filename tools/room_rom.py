"""Decode Kirby Super Star rooms from the ROM itself (read-only; no game data stored).

  /usr/bin/python3 tools/room_rom.py ROM INDEX         # print one room's header and layout summary

The room pointer table is at FF:009A (file 0x3F009A, HiROM: (bank-$C0)*0x10000 + addr),
4-byte entries (u16 offset, bank, pad). A room record is a header (+$3A), six
sections each skipped by its first word, one word, width word, height word,
then HAL-compressed data straight away: width*height LOW bytes, then the HIGH
bytes, then sprite records (6 bytes: type/param word, x word, y word; FFFF ends).
Checked against the maps and spawn lists the game loads (tests/room_rom_check.py).
Correction to kss-deuce docs/TERRAIN-QUERY.md H1/H2: the stream starts right
after the height word, not 2 bytes later; starting 2 bytes late still
decompresses, but into a 15-column shift with corrupted high bytes, which is
where the old "base 0x1001E" and "runtime high-byte flips" came from.

hal_unpack follows exhal's decompressor (MIT, devinacker/exhal compress.c):
a command byte (long form 111ccc ll + one length byte), then 0 raw, 1 byte RLE,
2 word RLE, 3 increasing bytes, 4/7 forward reference, 5 bit-reversed
reference, 6 backward reference (offsets big-endian); 0xFF ends the stream.

Writing (tests/room_edit_check.py): write_room keeps the original packed bytes
for an unchanged room (byte-identical ROM); an edited room is re-encoded with
hal_pack (greedy, about the size of HAL's own packer) and must fit its slot.
"""
import json, sys
from pathlib import Path
# The codec lives with the build (kss-deuce/source, or game/source in the release kit).
HERE = Path(__file__).resolve().parent
for src in (HERE / '../../../kss-deuce/source', HERE / '../../game/source'):
    if (src / 'room_codec.py').exists(): sys.path.insert(0, str(src.resolve())); break
from room_codec import *          # noqa: F401,F403  (hal_unpack, decode_room, write_room, relocate_room, ...)


if __name__ == '__main__':
    rom = Path(sys.argv[1]).read_bytes(); r = decode_room(rom, int(sys.argv[2], 0))
    print(json.dumps({k: (hex(v) if k.endswith('_file') else v) for k, v in r.items() if k not in ('layout', 'sprites', 'exits')} | {'sprites': len(r['sprites']), 'exits': r['exits']}))
