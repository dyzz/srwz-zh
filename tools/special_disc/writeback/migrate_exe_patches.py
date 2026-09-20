"""Port the main game's position-independent executable patches to SP.

ui/patch_sites.json locates each main-game patch site in SP (exact bytes,
masked search or function alignment). For every site ported here the main
game's built executable is the answer key: the runs of bytes its build changed
around the site are copied to the SP site, each only where SP holds exactly the
main game's Japanese bytes for that run.

Ported (the analysis marks them "direct port"):
  text_measurement_range            the width-measurement bound 0x889F -> 0x829F
  runtime_movement_type_labels      movement-type label layout
  dialogue_speaker_colors           the quote constant
  bazaar_top_help_alignment         bazaar help positions
  remaining_squad_count_alignment   remaining-squad count position
  search_tab_alignment              search-page tab positions (table at SP 0x39F2E0)
  intermission_library_alignment    intermission library x table (SP 0x3A0550)

Not ported here: the post-game mode unlock (SP may not use it), name order,
library unlocks and
protagonist names (SP's code differs), the □ skip (a policy decision).
Weapon labels and effect-2 builders use SP-native contracts in
weapon_detail_labels.py, applied by build_full_text.py during final assembly.

Outputs (work/build/special-disc/components/exe-patches/): SLPS_259.20 and report.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_textures import runs  # noqa: E402

SITES = ROOT / "config/products/special-disc/ui/patch_sites.json"
OG_JAPANESE = ROOT / "work/disc/SLPS_258.87"
OG_CHINESE = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                     "/project/work/build/zh-release-full-story/components/SLPS_258.87")
BASE = ROOT / "work/build/special-disc/components/library"  # the latest executable in the component chain
OUT = ROOT / "work/build/special-disc/components/exe-patches"
EXE = "SLPS_259.20"
GROUPS = {
    "text_measurement_range": None,
    "runtime_movement_type_labels": None,
    "dialogue_speaker_colors": None,
    "bazaar_top_help_alignment": None,
    "remaining_squad_count_alignment": None,
    # data tables SP moved (their pointers were relocated, so no byte search finds them):
    # main-game table start -> SP table start; a site keeps its offset inside the table
    "search_tab_alignment": (0x331730, 0x39F2E0),
    "intermission_library_alignment": (0x332410, 0x3A0550),
}
WINDOW = 4  # bytes around a site in which the main build's changes belong to that patch


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    sites = json.loads(SITES.read_text(encoding="utf-8"))
    japanese, chinese = OG_JAPANESE.read_bytes(), OG_CHINESE.read_bytes()
    base_report = json.loads((BASE / "report.json").read_text())
    exe = bytearray((BASE / EXE).read_bytes())
    assert sha256(bytes(exe)) == base_report["files"][EXE], "base executable drift"
    rows, applied_total = [], 0
    for site in sites:
        group = site["group"]
        if group not in GROUPS:
            continue
        og, length = site["off"], site["len"]
        table = GROUPS[group]
        hits = [int(h, 16) for h in site.get("sd", [])]
        if table is not None:
            hits = [table[1] + og - table[0]]
        if len(hits) != 1:
            rows.append(dict(group=group, id=site["id"], result="not located uniquely", hits=len(hits)))
            continue
        sd = hits[0]
        # the main build's changes near the site, as offsets relative to it
        lo, hi = og - WINDOW, og + length + WINDOW
        changed = [(a + lo - og, b + lo - og) for a, b in runs(japanese[lo:hi], chinese[lo:hi])]
        if not changed:
            rows.append(dict(group=group, id=site["id"], result="the main build left it unchanged"))
            continue
        applied, refused = 0, 0
        for a, b in changed:
            before, after = japanese[og + a:og + b], chinese[og + a:og + b]
            if bytes(exe[sd + a:sd + b]) == before:
                exe[sd + a:sd + b] = after
                applied += 1
            elif bytes(exe[sd + a:sd + b]) == after:
                applied += 1  # already done (a neighbouring site shares the run)
            else:
                refused += 1
        applied_total += applied
        rows.append(dict(group=group, id=site["id"], og=hex(og), sd=hex(sd), runs=len(changed),
                         applied=applied, preimage_differs=refused))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / EXE).write_bytes(bytes(exe))
    report = dict(sites=rows, runs_applied=applied_total,
                  files={EXE: sha256(bytes(exe))}, base_files={EXE: base_report["files"][EXE]},
                  original_files={EXE: base_report["original_files"][EXE]})
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
