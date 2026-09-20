"""Read-only inventory of the SP handoff; writes only this directory's snapshot.

Run from any directory: python3 /path/to/this/audit.py
Does not rebuild components, change corpora, or run an emulator.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/special_disc/writeback"))
from srwz.iso9660 import member_map, scan_iso9660
from srwz.text import encode_text, SrwzTextEncodeError
import migrate_slps_text as mst
from special_disc.source import CURRENT_ISO, SOURCE_ISO


def digest(path):
    with path.open("rb") as source:
        h = hashlib.sha256()
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            h.update(block)
        return h.hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text())


manifest_path = CURRENT_ISO.with_suffix('.json')
manifest = json.loads(manifest_path.read_text())
iso = CURRENT_ISO
members = member_map(scan_iso9660(iso))
original_members = member_map(scan_iso9660(SOURCE_ISO))
result = {
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "scope": "current corpus inventory, encoding availability and declared-member ISO hash readback; no rebuild or runtime acceptance",
    "manifest_sha256": digest(manifest_path),
    "iso": {"path": str(iso.relative_to(ROOT)), "size": iso.stat().st_size,
            "sha256": digest(iso)},
    "component_count": len(manifest["components"]),
    "stage_titles": manifest.get('stage_titles'),
    "same_member_paths": set(members) == set(original_members),
    "layout_mismatches": [name for name in members if name not in original_members or
                          (members[name].extent_lba, members[name].size) !=
                          (original_members[name].extent_lba, original_members[name].size)],
    "member_readback": {}, "corpora": {},
}
with iso.open("rb") as source:
    for name, record in manifest["files"].items():
        member = members[name]
        source.seek(member.extent_lba * 2048)
        remaining = member.size
        h = hashlib.sha256()
        while remaining:
            block = source.read(min(remaining, 4 * 1024 * 1024))
            if not block:
                raise RuntimeError(f"truncated ISO member: {name}")
            remaining -= len(block)
            h.update(block)
        result["member_readback"][name] = {
            "sha256": h.hexdigest(), "matches_manifest": h.hexdigest() == (record if isinstance(record, str) else record["sha256"])}

table, _, overrides, _ = mst.encoding_tables()
characters = set()
for path in sorted((ROOT / "corpus/zh/special-disc").glob("*.json")):
    doc = json.loads(path.read_text())
    entries = doc["entries"]
    result["corpora"][path.name] = {
        "entries": len(entries), "sha256": digest(path),
        "editorial_status": dict(Counter(e.get("editorial_status") for e in entries)),
        "duplicate_ids": len(entries) - len({e.get("id", e.get("source")) for e in entries}),
        "source_hashes_not_recorded": sum('source_text_sha256' not in e for e in entries),
        "bad_source_hashes": [e["id"] for e in entries if 'source_text_sha256' in e and
                              hashlib.sha256(e["source_text"].encode()).hexdigest() != e["source_text_sha256"]],
        "flagged_entries": [{"id": e["id"], "flags": e["flags"]} for e in entries if e.get("flags")],
    }
    for e in entries:
        characters.update(c for c in e["translation"] if not c.isascii())
missing = []
for c in sorted(characters):
    try:
        encode_text(c, table, overrides=overrides)
    except SrwzTextEncodeError:
        missing.append(c)
result["current_missing_characters"] = "".join(missing)
system = read("work/build/special-disc/components/system-text/report.json")
result["system_component"] = {k: system[k] for k in ("corpus", "frame_corpus", "written", "left", "compdata_codec")}
result["system_corpus_hashes_match"] = (
    system["corpus"]["sha256"] == result["corpora"]["system-text.json"]["sha256"] and
    system["frame_corpus"]["sha256"] == result["corpora"]["frame-text.json"]["sha256"])
stage = read("work/build/special-disc/components/stage-dialogue/report.json")
result["stage_survey"] = stage
result["stage_component_binary_exists"] = (ROOT / "work/build/special-disc/components/stage-dialogue/DATA/STAGE.BIN").exists()
result["stage_component_in_current"] = any('stage/report.json' in c for c in manifest['components'])
validation = read("work/authoring/special-disc/translation/results/full/validation.json")
result["historical_mt_validation"] = {
    "stats": validation["stats"],
    "flags": {k: v["flagged"] for k, v in validation["batches"].items() if v.get("flagged")},
}
out = ROOT / "work/review/special-disc/status/verification.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"output": str(out), "iso": result["iso"],
                 "member_hashes_match": all(v["matches_manifest"] for v in result["member_readback"].values()),
                 "members_checked": len(result["member_readback"]),
                 "layout_mismatches": result["layout_mismatches"],
                 "missing_characters": result["current_missing_characters"],
                 "system_corpus_hashes_match": result["system_corpus_hashes_match"]}, ensure_ascii=False, indent=2))
