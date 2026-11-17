#!/usr/bin/env python3
"""Create the Traditional release codebook: an independent character -> code -> glyph ledger.

Written once from the Simplified ledger (same schema, same structural rows), after which it evolves on its own:
new Traditional characters are appended by the build's own allocator (update_zh_release_font_snapshot.py), see
build_dual.py --update-codebook. The Traditional font is rasterized from this ledger's characters by the
unchanged font pipeline.

Initial assignment:
  * structural rows stay as they are: punctuation aliases, source-compatibility rows, every *compatibility*
    relocation, the squad-name ligature, and the characters frozen by the legacy-formation freeze;
  * a hanzi row whose character the Traditional corpus uses keeps its code;
  * a hanzi row whose character only Simplified uses (发) gives its code to the Traditional form that most often
    stands in its place across the parallel corpora (發), if that form has no code yet. So most characters keep
    the same code in both languages (names stored in saves read as the matching character), without the
    Traditional ledger depending on the Simplified one afterwards;
  * Traditional characters still without a code are left to the allocator (standard pool, then the linear area:
    the Traditional font profile has font_capacity 4,800).

Outputs (build_dual.py places them in the Traditional build):
  config/zh-hant/encoding/zh-release-font-assignments.json   the Traditional ledger (replaces config/encoding/...)
  config/zh-hant/font-profile.json                          what differs from config/fonts/zh-release-font.json:
                                                            font_capacity and the assignment-count ratchet
Usage: build_codebook.py [--force]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_corpus import FROZEN_KEYS, KANA, META, strip_meta  # noqa: E402

HAN = re.compile('[㐀-鿿]')
ZH_HANT = ROOT / 'config/zh-hant'
CAPACITY = {'glyph_count': 4992, 'linear_area': True,
            'reason': 'Traditional font: characters past the stock 4,480-glyph store go to the linear area, lead bytes 0x99-0x9A (glyphs 4608-4991).'}


def mapping_sha256(rows) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def strings(doc, key=None):
    if isinstance(doc, str):
        if key not in FROZEN_KEYS and not KANA.search(doc): yield doc
    elif isinstance(doc, list):
        for v in doc: yield from strings(v, key)
    elif isinstance(doc, dict):
        for k, v in doc.items():
            if k not in FROZEN_KEYS and not k.endswith('_sha256') and k not in META and k != 'zh_hant_meta':
                yield from strings(v, k)


def corpus_pairs(sc_root: Path, tc_root: Path):
    """Characters the Traditional corpus uses, and SC->TC character pairs of same-length aligned strings."""
    used, forms = collections.Counter(), collections.defaultdict(collections.Counter)
    for tc_file in tc_root.rglob('*.json'):
        tc = strip_meta(json.loads(tc_file.read_text(encoding='utf-8')))
        for s in strings(tc):
            used.update(HAN.findall(s))
        sc_file = sc_root / tc_file.relative_to(tc_root)
        if not sc_file.exists(): continue
        for a, b in zip(strings(json.loads(sc_file.read_text(encoding='utf-8'))), strings(tc)):
            if len(a) == len(b):
                for x, y in zip(a, b):
                    if HAN.match(x) and HAN.match(y): forms[x][y] += 1
    return used, forms


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--force', action='store_true', help='replace an existing Traditional ledger')
    a = p.parse_args()
    out_ledger = ZH_HANT / 'encoding/zh-release-font-assignments.json'
    out_profile = ZH_HANT / 'font-profile.json'
    if out_ledger.exists() and not a.force:
        raise SystemExit(f'{out_ledger} exists; the Traditional ledger only grows through the allocator (use --force to recreate)')
    ledger = json.loads((ROOT / 'config/encoding/zh-release-font-assignments.json').read_text(encoding='utf-8'))
    font = json.loads((ROOT / 'config/fonts/zh-release-font.json').read_text(encoding='utf-8'))
    freeze = json.loads((ROOT / font['formation_compatibility_freeze']['path']).read_text(encoding='utf-8'))
    frozen = {r.get('character') for r in freeze['relocations'] + freeze['retired_aliases'] if isinstance(r, dict)}
    # Codes the runtime-compatibility audits protect (legacy save formation names, runtime-generated glyphs,
    # sound-select titles) keep their character: the same audits run in the Traditional build.
    sys.path.insert(0, str(ROOT / 'tools'))
    from srwz.text import load_text_table
    from srwz.release_font import (audit_legacy_formation_glyph_compatibility, audit_runtime_generated_glyph_compatibility,
                                   audit_sound_select_title_glyph_compatibility)
    base = json.loads((ROOT / font['base_font_config']['path']).read_text(encoding='utf-8'))
    table = load_text_table(ROOT / base['encoding_baseline']['text_table']['path'])
    protected = set()
    for audit in (audit_legacy_formation_glyph_compatibility, audit_runtime_generated_glyph_compatibility,
                  audit_sound_select_title_glyph_compatibility):
        protected |= {int(c, 16) for c in audit(ledger, table, project_root=ROOT)['protected_original_codes']}
    def relocation_targets(node):                  # every code a compatibility contract relocated a character to
        if isinstance(node, dict):
            if isinstance(node.get('to_code'), str): yield int(node['to_code'], 16)
            for v in node.values(): yield from relocation_targets(v)
        elif isinstance(node, list):
            for v in node: yield from relocation_targets(v)
    protected |= set(relocation_targets([e[k] for e in ledger.get('extensions', []) if isinstance(e, dict)
                                         for k in e if 'compatibility' in k]))
    used, forms = corpus_pairs(ROOT / 'corpus/zh', ROOT / 'corpus/zh-hant')
    assigned = {r['character'] for k in ('primary_assignments', 'surface_alias_assignments', 'source_compatibility_assignments')
                for r in ledger[k]}
    substituted, kept_unused = [], 0
    for row in ledger['primary_assignments']:
        c = row['character']
        structural = ('compatibility' in row['mapping'] or 'ligature' in row['mapping'] or c in frozen
                      or row['mapping'] == 'existing_codebook'          # rows of the locked base codebook (测 试)
                      or int(row['code'], 16) in protected or not HAN.match(c))
        if structural or c in used:
            continue
        target = next((t for t, _ in forms[c].most_common() if t in used and t not in assigned), None)
        if target is None:
            kept_unused += 1; continue
        row['zh_hant_substituted_from'] = c
        row['character'] = target
        assigned.discard(c); assigned.add(target)
        substituted.append(f'{c}->{target}')
    # Surface-safe aliases name the same character as their primary row (a second, default-width code for it):
    # they follow the substitution.
    renamed = {r['zh_hant_substituted_from']: r['character'] for r in ledger['primary_assignments'] if 'zh_hant_substituted_from' in r}
    for row in ledger['surface_alias_assignments']:
        if row['character'] in renamed:
            row['zh_hant_substituted_from'] = row['character']; row['character'] = renamed[row['character']]
    ledger['surface_alias_mapping_sha256'] = mapping_sha256(ledger['surface_alias_assignments'])
    # Migration records (character moved from_code -> to_code) name the character now at to_code; compatibility
    # contracts stay as they are (their rows were not substituted).
    by_code = {r['code'].upper(): r for r in ledger['primary_assignments']}
    def follow(node, in_compat=False):
        if isinstance(node, dict):
            row = by_code.get(str(node.get('to_code', '')).upper())
            if (not in_compat and isinstance(node.get('character'), str) and row is not None
                    and row.get('zh_hant_substituted_from') == node['character']):
                node['zh_hant_substituted_from'] = node['character']; node['character'] = row['character']
            for k, v in node.items():
                follow(v, in_compat or 'compatibility' in k)
        elif isinstance(node, list):
            for v in node: follow(v, in_compat)
    follow(ledger.get('extensions', []))
    for ext in ledger.get('extensions', []):
        record = ext.get('clean_default_width_cjk_primary_migration') if isinstance(ext, dict) else None
        if record and 'migrations_sha256' in record:
            record['migrations_sha256'] = mapping_sha256(record['migrations'])
    ledger['snapshot_id'] = ledger['snapshot_id']                      # identity is checked against the font config
    ledger['primary_mapping_sha256'] = mapping_sha256(ledger['primary_assignments'])
    ledger['zh_hant'] = {'derived_from_simplified_ledger_sha256': hashlib.sha256(
        (ROOT / 'config/encoding/zh-release-font-assignments.json').read_bytes()).hexdigest(),
        'substituted_rows': len(substituted), 'simplified_only_rows_kept_unused': kept_unused}
    missing = sorted(set(used) - assigned)
    text = json.dumps(ledger, ensure_ascii=False, indent=2) + '\n'
    out_ledger.parent.mkdir(parents=True, exist_ok=True); out_ledger.write_text(text, encoding='utf-8')
    out_profile.write_text(json.dumps({
        'schema_version': 1,
        'purpose': 'Traditional font profile: merged by build_dual.py onto config/fonts/zh-release-font.json in the Traditional build.',
        'font_capacity': CAPACITY,
        'expected': font['expected'],
        **{k: v for k, v in (json.loads(out_profile.read_text(encoding='utf-8')) if out_profile.exists() else {}).items()
           if k.startswith('translation_tree_extra_')}}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'protected_codes': len(protected), 'substituted': len(substituted), 'kept_unused_sc_rows': kept_unused,
                      'tc_chars_without_code_left_for_allocator': len(missing), 'examples': substituted[:12],
                      'missing': ''.join(missing)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
