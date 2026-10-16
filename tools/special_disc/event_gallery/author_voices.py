"""Author the CCC voice clips the SP disc lacks but a gallery effect plays.

SP's effect 256 (阿克艾里昂合体) asks for CCC 30896 at frame 710; SP's CCC
directory ends at 30895, so the line is silent on the retail SP disc. The
Original disc plays its battle-voice clip 20354 there (Best: 20358, same
bytes). This tool copies such clips byte for byte from the locked Japanese
Original disc into ``config/products/special-disc/event-gallery-voice/`` and
records them under ``voice_restorations`` in the gallery config; the build
appends them to SP's ``SOUND/CCC.MSB`` and fills the matching directory rows.
Usage: author_voices.py
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys  # noqa: E402

sys.path[:0] = [str(ROOT / "tools")]
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402

ORIGINAL_ISO = ROOT / "build/iso/sources/original.iso"
CONFIG = ROOT / "config/products/special-disc/event-gallery.json"
ASSETS = ROOT / "config/products/special-disc/event-gallery-voice"

# SP CCC id the SP effect resource already references -> Original CCC id with the audio.
RESTORE = [
    {"sp_ccc": 30896, "original_ccc": 20354,
     "used_by": "effect 256 frame 710 (阿克艾里昂合体): the scream うわっ! うおおお…; Best plays the same bytes as 20358"},
]


def original_clip(index: int) -> bytes:
    members = member_map(scan_iso9660(ORIGINAL_ISO))
    with ORIGINAL_ISO.open("rb") as stream:
        entry = members["SOUND/CCC.MSH"]
        stream.seek(entry.extent_lba * 2048)
        directory = stream.read(entry.size)
        if index >= struct.unpack_from("<I", directory, 8)[0]:
            raise ValueError(f"Original CCC {index} out of range")
        size, offset = struct.unpack_from("<II", directory, 12 + 8 * index)
        stream.seek(members["SOUND/CCC.MSB"].extent_lba * 2048 + offset)
        return stream.read(size)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in RESTORE:
        clip = original_clip(row["original_ccc"])
        if not clip or len(clip) % 16:
            raise ValueError(f"CCC {row['original_ccc']} is not whole ADPCM blocks")
        path = ASSETS / f"ccc-original-{row['original_ccc']}.adpcm"
        path.write_bytes(clip)
        rows.append({**row, "file": str(path.relative_to(ROOT)), "size": len(clip),
                     "sha256": hashlib.sha256(clip).hexdigest()})
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["voice_restorations"] = rows
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
