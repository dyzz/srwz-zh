"""Characters in the drafts that the shared Chinese codebook cannot encode (they need glyphs in the font).

  python3 charset.py [--tag full] -> results/<tag>/missing-glyphs.json
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import sys

from common import HERE, ROOT

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/special_disc/writeback"))
import migrate_slps_text as mst  # noqa: E402
from srwz.text import encode_text  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="full")
    args = parser.parse_args()
    table, _menu, story, _readback = mst.encoding_tables()
    ok: dict[str, bool] = {}
    missing = collections.defaultdict(list)
    for path in sorted(glob.glob(str(HERE / "results" / args.tag / "*" / "*.json"))):
        doc = json.loads(open(path, encoding="utf-8").read())
        for t in doc.get("translations", []):
            for ch in set(t["text"]):
                if ch in "\n\\$" or ch.isascii():
                    continue
                if ch not in ok:
                    try:
                        encode_text(ch, table, overrides=story)
                        ok[ch] = True
                    except Exception:  # noqa: BLE001
                        ok[ch] = False
                if not ok[ch] and len(missing[ch]) < 5:
                    missing[ch].append(dict(id=t["id"], text=t["text"]))
    out = HERE / "results" / args.tag / "missing-glyphs.json"
    out.write_text(json.dumps(dict(count=len(missing), chars="".join(sorted(missing)), examples=missing),
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(len(missing), "characters outside the codebook:", "".join(sorted(missing)))


if __name__ == "__main__":
    main()
