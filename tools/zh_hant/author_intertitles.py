#!/usr/bin/env python3
"""Lock the Traditional chapter intertitles (MTV_PROP chunks 21/22) to their Traditional renders.

The intertitles are rendered at build time from corpus text and the HarmonyOS TTF, and the corpus file carries
the output hashes. This renders the Traditional text with the builder's own function and writes the resulting
output hashes into corpus/zh-hant/chapter-intertitles.json (source hashes and the render contract stay).
Usage: author_intertitles.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parent)]
from srwz.mtv_prop_intertitles import build_mtv_prop_intertitles  # noqa: E402
from sync_corpus import strip_meta  # noqa: E402

TC = ROOT / 'corpus/zh-hant/chapter-intertitles.json'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify the stored render locks without writing")
    options = parser.parse_args()
    config = json.loads((ROOT / 'config/full-story-components.json').read_text(encoding='utf-8'))['chapter_intertitles']
    doc = json.loads(TC.read_text(encoding='utf-8'))
    args = ((ROOT / config['original_mtv_prop']['path']).read_bytes(), (ROOT / config['original_slps']['path']).read_bytes(),
            ROOT / config['font']['path'])
    if options.check:
        build_mtv_prop_intertitles(*args, strip_meta(doc))
        print("Traditional chapter intertitle render locks verified")
        return
    relock: dict = {}
    build_mtv_prop_intertitles(*args, strip_meta(doc), relock=relock)
    by_chunk = {e['chunk_index']: e for e in doc['entries']}
    for owner, values in relock.items():
        (doc if owner == 'archive' else by_chunk[owner]).update(values)
    encoded = json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
    if TC.read_text(encoding='utf-8') != encoded:
        TC.write_text(encoded, encoding='utf-8')
    build_mtv_prop_intertitles(*args, strip_meta(doc))                 # must now pass as a build would run it
    print(json.dumps({'relocked': {str(k): sorted(v) for k, v in relock.items()},
                      'texts': [e['translation'] for e in doc['entries']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
