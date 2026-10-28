#!/usr/bin/env python3
"""Preview/apply shared-JS full-width flow and scrolling prose, preserving author scopes.

Only soft physical wraps change. Paragraph starts, native blank rows, wording,
controls and compact author notation are retained. Source row budgets are checked
before any file is written; the production builders verify encoded capacities.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from srwz.chinese_layout import load_layout_profiles
from srwz.chinese_prose import logical_prose_text, reflow_chinese_prose
from srwz.codec import decode_production
from srwz.compact_scopes import FLOW_SYNOPSIS, expand, collapse
from srwz.iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from srwz.stage_overview import parse_stage_overviews
from srwz.summary import parse_summary
from srwz.text import CONTROL_NOTATION, load_text_table
from write_frame_text import FLOW_PROTECTED_TERMS, validate_flow_layout


def plan():
    profiles = load_layout_profiles(ROOT / 'config/text-layout/zh-layout-profiles.json')
    narrow_ids=set(json.loads((ROOT/'config/text-layout/native-scene-contracts.json').read_text())['variants']['main_scroll_strip']['resource_ids'])
    table = load_text_table(ROOT / 'vendor/upstream-python/project/tbl_all.json')
    stage = decode_production((ROOT / 'work/disc/DATA/STAGE.BIN').read_bytes()[:55392]).output
    overviews = {r.entry_id: r.source_text for r in parse_stage_overviews(stage, table)}
    archive = (ROOT / 'work/disc/DATA/MTV_PROS.BIN').read_bytes()
    exe = (ROOT / 'work/disc/SLPS_258.87').read_bytes()
    offsets = read_executable_archive_offsets(exe, CORE_ARCHIVE_SPECS['MTV_PROS.BIN'], len(archive))
    summaries = {r.entry_id: r.text for i, (start, end) in enumerate(zip(offsets, offsets[1:]))
                 for r in parse_summary(decode_production(archive[start:end]).output, table, chunk_index=i).entries}
    paths = ('corpus/zh/menu/stage-overviews.json', 'corpus/zh/summary.json',
             'corpus/zh/special-disc/frame-text.json')
    documents, inputs, rows = {}, {}, []
    for path in paths:
        raw = (ROOT / path).read_bytes()
        inputs[path] = hashlib.sha256(raw).hexdigest()
        document = documents[path] = json.loads(raw)
        for entry in document['entries']:
            kind = entry.get('kind')
            if path == paths[0]:
                surface, profile_id, advance = 'main_flow', 'stage_scroll_overview', 16
                source = overviews[entry['id']]
                limit = len(source.rstrip('\n').splitlines()) + entry['translation'].endswith('\n')
            elif path == paths[1]:
                surface, profile_id, advance = 'main_scroll', 'world_history_scroll', 24
                source = summaries[entry['id']]
                limit = len(source.split('\n'))
            elif kind in ('synopsis', 'narration'):
                source = entry['source_text']
                surface = 'sp_flow' if kind == 'synopsis' else 'sp_scroll'
                profile_id = 'stage_scroll_overview' if kind == 'synopsis' else 'sp_narration_scroll'
                advance = 16 if kind == 'synopsis' else 25
                limit = 11 if kind == 'synopsis' else len(source.split('\n'))
            else:
                continue
            if hashlib.sha256(source.encode()).hexdigest() != entry['source_text_sha256']:
                raise ValueError(f"Source drift: {entry['id']}")
            profile = replace(profiles[profile_id], default_advance_px=advance)
            if surface=='main_scroll' and entry['id'] in narrow_ids:profile=replace(profile,maximum_width=21)
            if profile.line_packing != 'max_width':
                raise ValueError(f'{profile_id} must use shared maximum-width packing')
            before = entry['translation']
            native = expand(before, FLOW_SYNOPSIS) if surface == 'sp_flow' else before
            terms = (FLOW_PROTECTED_TERMS if surface == 'sp_flow' else
                     ('下达',) if surface == 'sp_scroll' else ())
            fitted = reflow_chinese_prose(native, profile=profile, maximum_lines=limit,
                                         protected_terms=terms,resource_id=entry['id'])
            after = collapse(fitted.text, FLOW_SYNOPSIS) if surface == 'sp_flow' else fitted.text
            if surface == 'sp_flow':
                validate_flow_layout(fitted.text)
                if expand(after, FLOW_SYNOPSIS) != fitted.text:
                    raise ValueError('Compact scope round trip failed')
            if logical_prose_text(before) != logical_prose_text(after):
                raise ValueError('Author text changed')
            if CONTROL_NOTATION.findall(before) != CONTROL_NOTATION.findall(after):
                raise ValueError('Author controls changed')
            rows.append(dict(path=path, id=entry['id'], surface=surface, before=before, after=after,
                             changed=after != before, widths_px=fitted.line_widths_px,
                             maximum_width_px=profile.maximum_width * advance, maximum_lines=limit,
                             selected_width_px=fitted.selected_width_px,width_selection=fitted.width_selection))
            entry['translation'] = after
    documents[paths[0]]['policy']['maximum_line_width'] = profiles['stage_scroll_overview'].maximum_width
    return documents, dict(inputs=inputs, scanned=len(rows), changed=sum(r['changed'] for r in rows),
                           counts=dict(Counter(r['surface'] for r in rows)), records=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    documents, report = plan()
    if args.apply:
        # Finish all validation, then reject concurrent changes before writeback.
        for path, expected in report['inputs'].items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
                raise ValueError(f'Input drift: {path}')
        for path, document in documents.items():
            (ROOT / path).write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
    report['applied'] = args.apply
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('inputs', 'records')}))


if __name__ == '__main__':
    main()
