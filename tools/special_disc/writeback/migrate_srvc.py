"""Bring the main game's finished battle subtitles into the SP disc's SRVC.BIN.

SP's SRVC archive has the main game's layout; only each chunk header's magic
reads 0x4F01 instead of 0x4F00 (the game does not read that byte). Every line
whose Japanese is already translated for the main game (by sha256 of the text)
is written with that Chinese, through the same compact-pool writer and codebook
as the main build: the SEG offsets, index metadata and unindexed tails stay
byte-exact, and each chunk's rebuilt pool must fit its own capacity.

Lines without a translation (SP-only lines) keep their exact original bytes;
they are passed through the writer as raw-byte notation.

Outputs (work/build/special-disc/components/srvc/):
  BTL/SRVC.BIN   the archive with the reusable lines in Chinese
  report.json    coverage, pool headroom and the readback check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import srwz.srvc as srvc  # noqa: E402
from srwz.image_export import parse_seg_offsets  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.srvc import parse_srvc_archive, rebuild_srvc_archive  # noqa: E402
from migrate_slps_text import encoding_tables  # noqa: E402

from special_disc.source import SOURCE_ISO as ISO  # noqa: E402
from special_disc.source import DISC_INVENTORY as LOCKS  # noqa: E402
CORPUS = ROOT / "corpus/zh/battle/srvc-lines.json"
OUT = ROOT / "work/build/special-disc/components/srvc"
BIN, SEG = "BTL/SRVC.BIN", "BTL/SRVC.SEG"
SD_MAGIC = 0x4F01


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(members, locks, name: str) -> bytes:
    m = members[name]
    with ISO.open("rb") as f:
        f.seek(m.extent_lba * 2048)
        data = f.read(m.size)
    assert sha256(data) == locks[name], f"{name} lock drift"
    return data


def raw_notation(data: bytes) -> str:
    return "".join(f"{{{byte:02X}}}" for byte in data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proposal', type=Path)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--include-sp', action='store_true')
    parser.add_argument('--allow-draft', action='store_true')
    args = parser.parse_args()
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    source_bin = read_member(members, locks, BIN)
    source_seg = read_member(members, locks, SEG)
    table, _menu_overrides, story_overrides, readback = encoding_tables(args.proposal)

    srvc.SRVC_MAGIC = SD_MAGIC  # SP chunks; the layout is otherwise the main game's
    offsets = parse_seg_offsets(source_seg, len(source_bin))
    chunks = parse_srvc_archive(source_bin, offsets, table)
    records = [record for chunk in chunks for record in chunk.records]

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    by_hash = {e["source_text_sha256"]: e["translation"] for e in corpus["entries"]
               if e.get("editorial_status") == "reviewed" and e.get("translation")}
    sp_rows = []
    sp_path = ROOT / 'corpus/zh/special-disc/battle-lines.json'
    if args.include_sp:
        sp_rows = json.loads(sp_path.read_text())['entries']
        seen = set()
        for row in sp_rows:
            digest = sha256(row['source_text'].encode())
            if digest != row['source_text_sha256'] or digest in seen or digest in by_hash:
                raise ValueError(f"SP battle source identity/conflict: {row['id']}")
            seen.add(digest)
            if row.get('editorial_status') != 'reviewed' and not args.allow_draft:
                raise ValueError(f"SP draft requires --allow-draft: {row['id']}")
            translation = row['translation']
            if not srvc.subtitle_line_break_policy_satisfied(row['source_text'], translation, row):
                raise ValueError(f"battle line-break timing changed: {row['id']}")
            if max(len(line.strip('“”　')) for line in translation.split('\\n')) > 20:
                raise ValueError(f"battle subtitle exceeds 20 inner cells: {row['id']}")
            actual = {(r.chunk_index, r.record_index) for r in records if r.text == row['source_text']}
            expected = {(r['chunk'], r['record']) for r in row['triggers']}
            if not actual or actual != expected:
                raise ValueError(f"SP battle trigger binding drift: {row['id']}")
            by_hash[digest] = translation

    translations, kept_raw = {}, {}
    for record in records:
        if record.text in translations:
            continue
        found = by_hash.get(sha256(record.text.encode("utf-8")))
        if found is not None:
            translations[record.text] = found.replace(" ", "　")  # visible spaces as 0x8140
        else:
            # keep the exact source bytes, terminator excluded (the writer terminates)
            raw = source_bin[record.archive_text_start:record.archive_text_end]
            assert raw.endswith(b"\0"), record
            translations[record.text] = raw_notation(raw[:-1])
            kept_raw[record.text] = raw

    output, parsed, pool = rebuild_srvc_archive(source_bin, offsets, table, translations,
                                                encoding_overrides=story_overrides, parsed_chunks=chunks)

    # readback: structure unchanged, Chinese lines decode to the Chinese, the rest keep their bytes
    out_chunks = parse_srvc_archive(output, offsets, readback)
    translated = kept = 0
    for before, after in zip(chunks, out_chunks):
        assert (before.archive_start, before.archive_end, before.text_record_count,
                before.text_index_start, before.text_pool_start) == \
               (after.archive_start, after.archive_end, after.text_record_count,
                after.text_index_start, after.text_pool_start), before.chunk_index
        assert [r.metadata for r in before.records] == [r.metadata for r in after.records]
        if not before.records:
            assert source_bin[before.archive_start:before.archive_end] == output[after.archive_start:after.archive_end]
            continue
        tail = before.archive_start + before.indexed_text_end
        assert source_bin[tail:before.archive_end] == output[tail:before.archive_end], "tail changed"
        for r_before, r_after in zip(before.records, after.records):
            if r_before.text in kept_raw:
                assert output[r_after.archive_text_start:r_after.archive_text_end] == kept_raw[r_before.text]
                kept += 1
            else:
                want = translations[r_before.text].replace("\\n", "\\n")
                assert r_after.text == want, (r_before.chunk_index, r_after.text, want)
                translated += 1
    assert len(output) == len(source_bin)

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "BTL").mkdir(exist_ok=True)
    (args.output / BIN).write_bytes(output)
    unique = {r.text for r in records}
    report = dict(
        proposal_sha256=sha256(args.proposal.read_bytes()) if args.proposal else None,
        corpus=str(CORPUS.relative_to(ROOT)), corpus_sha256=sha256(CORPUS.read_bytes()),
        records=len(records), unique_lines=len(unique),
        translated_unique=len(unique) - len(kept_raw), untranslated_unique=len(kept_raw),
        translated_records=translated, untranslated_records=kept,
        pool=pool, chunks=len(chunks),
        untranslated_samples=[t[:60] for t in list(kept_raw)[:15]],
        files={BIN: sha256(output)}, original_files={BIN: locks[BIN]},
        sp_corpus=({'path': str(sp_path.relative_to(ROOT)), 'sha256': sha256(sp_path.read_bytes()),
                    'entries': len(sp_rows), 'records': sum(len(r['triggers']) for r in sp_rows),
                    'line_breaks_preserved': True, 'maximum_inner_cells': 20} if sp_rows else None),
    )
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "untranslated_samples"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
