"""Build an explicit SP STAGE scope using the shared owned-region repacker.

Default scope is chunks 001 (story) and 039 (challenge). The component preserves
HB boundaries, decoded sizes and every unowned byte. Unknown aliases fail closed.
This is a development component, not a complete Special Disc release builder.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/special_disc/export"), str(Path(__file__).resolve().parent)]
import export_sd_text as sd
import migrate_slps_text as mst
from stage_bindings import StageBindings, BindingError
from stage_auxiliary import formation_groups, scalar_sites, write_formations
from srwz.chinese_layout import fit_chinese_dialogue_layout, load_layout_profiles, rendered_line_width
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.iso9660 import member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.text import decode_text, normalize_original_fullwidth_ascii, encode_text
from srwz.writers import repack_stage_texts_in_place
from srwz.writeback import WritebackError

STAGE = "DATA/STAGE.BIN"
HB = "HEDBDY/HB.BIN"
BASE = ROOT / "work/build/special-disc/components/system-text"
OUT = ROOT / "work/build/special-disc/text-candidate/stage"
HB_TABLE_SPAN = 0x114
PROFILES = ROOT / "config/text-layout/zh-layout-profiles.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_disc_member(name: str) -> bytes:
    member = member_map(scan_iso9660(sd.ISO))[name]
    with sd.ISO.open("rb") as disc:
        disc.seek(member.extent_lba * 2048)
        data = disc.read(member.size)
    locks = json.loads((ROOT / "config/products/special-disc/disc-inventory.json").read_text())
    expected = next(r["sha256"] for r in locks["sp"]["members"] if r["path"] == name)
    if sha256(data) != expected:
        raise ValueError(f"original disc member drift: {name}")
    return data


def native_id(index, entry_id):
    domain = "challenge" if 39 <= index <= 56 else "story"
    return f"sd/{domain}/{index:03d}/" + entry_id.split("/", 2)[2]


def reject_interior_references(data, parsed, *, nonpointer_sites=(), text_spans=()):
    """An unowned pointer into a payload is unsafe even when not at its start."""
    spans = []
    for entry in parsed.entries:
        if entry.kind in {"dialogue", "condition"} and entry.text_offset is not None:
            end = data.find(b"\0", entry.text_offset)
            if end < 0:
                raise WritebackError(f"unterminated source: {entry.entry_id}")
            spans.append((entry.text_offset, end + 1))
    known = {e.pointer_offset for e in parsed.entries if e.pointer_offset is not None}
    starts = {a for a, b in spans}
    for site in range(0, len(data) - 3, 4):
        if site in known or site in nonpointer_sites or any(a <= site < b for a, b in (*spans, *text_spans)):
            continue
        target = struct.unpack_from("<I", data, site)[0] - sd.SD_STAGE_BASE
        if target not in starts and any(a < target < b for a, b in spans):
            raise WritebackError(f"untyped interior reference 0x{site:X}->0x{target:X}")


def check_unowned_bytes(before, after, regions, pointer_sites):
    allowed = bytearray(len(before))
    for start, end in regions:
        allowed[start:end] = b"\1" * (end - start)
    for site in pointer_sites:
        allowed[site:site + 4] = b"\1" * 4
    if len(after) != len(before):
        raise WritebackError("decoded size changed")
    for offset, (a, b) in enumerate(zip(before, after)):
        if a != b and not allowed[offset]:
            raise WritebackError(f"unowned byte changed: 0x{offset:X}")
    protected = bytes(a for i, a in enumerate(before) if not allowed[i])
    return dict(bytes=len(protected), sha256=sha256(protected))


def build_chunk(index, stored, function_address, bindings, table, overrides, readback, profile, *, exe=None, include_formations=False):
    decoded = decode_production(stored)
    data = decoded.output
    module = sd.sd_stage_module()
    parsed = module.parse_stage(data, table, stage_index=index, function_address=function_address,
                                base_address=sd.SD_STAGE_BASE)
    if parsed.unknown_code_count:
        raise WritebackError(f"chunk {index}: unknown source codes")
    groups = formation_groups(data, table, index, sd.SD_STAGE_BASE)
    scalars = scalar_sites(data, index, ROOT, exe) if exe is not None else []
    reject_interior_references(data, parsed, nonpointer_sites=scalars,
        text_spans=[(c.offset, c.offset+c.source_consumed) for g in groups for c in g.cells])
    rows, replacements, speakers = [], {}, {}
    for entry in parsed.entries:
        target = native_id(index, entry.entry_id)
        row = bindings.resolve(target, entry.kind, entry.text)
        text = normalize_original_fullwidth_ascii(row["translation"])
        op = struct.unpack_from("<I", data, entry.pointer_offset - 16)[0] if entry.kind == "dialogue" and entry.pointer_offset is not None else None
        if (
            entry.kind == "dialogue"
            and op not in (0x10, 0x11, 0x12)
            and row.get("kind") not in {"scene_label", "location_caption"}
        ):
            text = fit_chinese_dialogue_layout(text, profile=profile).text
            row["layout"] = "story_dialogue"
        else:
            # Labels/conditions retain their explicit line structure, without dialogue indentation.
            if entry.kind != "speaker" and max(map(rendered_line_width, text.split('\n')), default=0) > max(21, max(map(rendered_line_width, entry.text.split('\n')), default=0)):
                raise WritebackError(f"{target}: explicit-layout width exceeds source envelope")
            row["layout"] = (
                "speaker" if entry.kind == "speaker"
                else "location_caption" if row.get("kind") == "location_caption"
                else "explicit_lines"
            )
        row.update(native_id=entry.entry_id, pointer_offset=entry.pointer_offset, text_offset=entry.text_offset, output_text=text)
        rows.append(row)
        if entry.kind == "speaker":
            speakers[entry.speaker_id] = text
        else:
            replacements[entry.entry_id] = text
    result = repack_stage_texts_in_place(data, table, stage_index=index,
        function_address=function_address, replacements=replacements, parsed_source=parsed,
        speaker_replacements=speakers, overrides=overrides, base_address=sd.SD_STAGE_BASE)
    rebuilt = result.data
    name_regions = []
    if include_formations:
        named, name_regions, name_rows = write_formations(data, groups, index, bindings, table, overrides, readback, sd.SD_STAGE_BASE)
        mutable = bytearray(rebuilt)
        for a, b in name_regions:
            if any(a < end and start < b for start, end in result.owned_regions):
                raise WritebackError('formation and dialogue ownership overlap')
            mutable[a:b] = named[a:b]
        rebuilt = bytes(mutable); rows.extend(name_rows)
    protected = check_unowned_bytes(data, rebuilt, (*result.owned_regions, *name_regions),
                                    [a.pointer_offset for a in result.allocations])
    reread = module.parse_stage(rebuilt, readback, stage_index=index, function_address=function_address,
                               base_address=sd.SD_STAGE_BASE)
    actual = {e.entry_id: e for e in reread.entries if e.kind != "speaker"}
    if set(actual) != set(replacements):
        raise WritebackError("native record set changed on full reparse")
    for entry_id, expected in replacements.items():
        if actual[entry_id].text != expected:
            raise WritebackError(f"full reparse mismatch: {entry_id}")
    packed = reencode_changed_suffix(stored, rebuilt, strategy="rust-fit", max_output_size=len(stored), original_result=decoded)
    if len(packed) > len(stored) or decode_production(packed).output != rebuilt:
        raise WritebackError("compressed slot/readback failed")
    compressed_size = len(packed)
    packed += bytes(len(stored) - len(packed))
    return packed, dict(chunk=index, name=data[0x30:0x50].split(b'\0', 1)[0].decode('ascii'),
        input_sha256=sha256(stored), output_sha256=sha256(packed), decoded_sha256=sha256(rebuilt),
        decoded_size=len(data), allocated=len(stored), compressed=compressed_size,
        protected=protected, owned_regions=result.owned_regions, formation_regions=name_regions, preserved_scalar_sites=scalars,
        allocations=[a.to_metadata() for a in result.allocations], bindings=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chunks', nargs='+', type=int, default=[1, 39])
    parser.add_argument('--allow-draft', action='store_true')
    parser.add_argument('--include-formations', action='store_true')
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--proposal', type=Path, required=True)
    args = parser.parse_args()
    table, _, overrides, readback = mst.encoding_tables(args.proposal)
    bindings = StageBindings(ROOT, allow_draft=args.allow_draft)
    for contract in ('config/products/special-disc/stage-scalar-contracts.json',):
        bindings.inputs[contract] = sha256((ROOT/contract).read_bytes())
    profile = load_layout_profiles(PROFILES)['story_dialogue']
    source = (args.base / STAGE).read_bytes()
    base_report = json.loads((args.base / 'report.json').read_text())
    if sha256(source) != base_report['files'][STAGE]:
        raise ValueError('base STAGE drift')
    hb = read_disc_member(HB)
    exe = read_disc_member('SLPS_259.20')
    offsets = read_executable_archive_offsets(hb, ExecutableOffsetSpec(name='SP STAGE', member=HB,
        table_start=sd.HB_STAGE_TABLE, table_end=sd.HB_STAGE_TABLE + HB_TABLE_SPAN), len(source))
    functions = sd.sd_stage_module().read_stage_function_addresses(exe, start=sd.SD_FUNCTION_TABLE[0], end=sd.SD_FUNCTION_TABLE[1])
    selected = sorted(set(args.chunks))
    if len(selected) != len(args.chunks) or any(i <= 0 or i >= len(offsets)-1 for i in selected):
        raise ValueError('invalid or duplicate chunk scope')
    output = bytearray(source)
    reports, failures = [], []
    for index in selected:
        start, end = offsets[index:index+2]
        try:
            packed, report = build_chunk(index, source[start:end], functions[index], bindings, table, overrides, readback, profile, exe=exe, include_formations=args.include_formations)
            output[start:end] = packed
            reports.append(report)
            print(f"chunk {index:03d}: {len(report['bindings'])} bindings; {report['compressed']}/{report['allocated']} bytes", flush=True)
        except (ValueError, RuntimeError) as error:
            failures.append(dict(chunk=index, reason=str(error)))
    report = dict(schema_version=1, status='failed' if failures else 'static_component_verified_runtime_pending',
        allow_draft=args.allow_draft, chunks=selected, baseline=dict(path=str(args.base), sha256=sha256(source)),
        proposal=dict(path=str(args.proposal), sha256=sha256(args.proposal.read_bytes())),
        inputs=bindings.inputs, hb_sha256=sha256(hb), chunk_reports=reports, failures=failures,
        files={} if failures else {STAGE: sha256(output)})
    consumed = {row['target'] for chunk in reports for row in chunk['bindings']}
    prefixes = tuple(native_id(i, f'story/{i:03d}/') for i in selected)
    report['pending_native_targets'] = sorted(
        target for target in bindings.direct
        if target.startswith(prefixes) and target not in consumed
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    if failures:
        # An old successful output must not survive next to a failed report.
        (args.output/STAGE).unlink(missing_ok=True)
        raise SystemExit(json.dumps(failures, ensure_ascii=False))
    (args.output/'DATA').mkdir(exist_ok=True)
    (args.output/STAGE).write_bytes(output)
    print(f"STAGE component: {args.output / STAGE}")


if __name__ == '__main__':
    main()
