#!/usr/bin/env python3
"""One Special Disc with Simplified and Traditional (docs/ZH_HANT_SP_DUAL_PLAN_20261117.md).

Same scheme as build_dual.py (Original): the unchanged pipeline builds SP once per language, each in an APFS clone
of the build inputs, and assemble_dual.py --edition sp turns the two images into one disc. SP is built on its
frozen Simplified baseline (work/build/special-disc/baselines); the Traditional build keeps that baseline: under
the Traditional codebook its Simplified bytes read as their Traditional forms, except for the few codes listed by
--audit-codes.

Usage: build_dual_sp.py [--release-version 0.5.1] [--skip-sc] [--out build/iso/test/NAME.iso]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_dual as bd  # noqa: E402

ROOT = bd.ROOT
SP_TREES = ['work/build/special-disc']
SP_FILES = ['work/analysis/sp-event-fidelity-20261013/' + n for n in      # author_talk.py's id map and name helper
            ('id-map.json', 'names.py', 'original-compdata.bin', 'sp-jp-compdata.bin')]
DISC_INVENTORY = ROOT / 'config/products/special-disc/disc-inventory.json'
SP_ISO = json.loads(DISC_INVENTORY.read_text(encoding='utf-8'))['sp']['path']   # rom/... (the clone's rom/ is build/iso/sources)


def clone(name: str) -> Path:
    dst = bd.clone(name)
    for tree in SP_TREES:
        (dst / tree).parent.mkdir(parents=True, exist_ok=True)
        bd.run('cp', '-cR', ROOT / tree, dst / tree)
    for rel in SP_FILES:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        bd.run('cp', '-c', ROOT / rel, dst / rel)
    src = (ROOT / SP_ISO).resolve()
    bd.run('cp', '-c', src, dst / 'build/iso/sources' / src.name)
    return dst


SP_FONT_FILES = ['work/build/special-disc/text-candidate/font/' + n for n in ('manifest.json', 'profile.json', 'proposal.json')] + \
                ['work/build/special-disc/text-candidate/sp-font/' + n for n in ('font.bin', 'report.json')]


def sp_font(tc: Path) -> None:
    """SP's font component from the Traditional codebook (the clone's release-font profile), by the SP font steps of
    build_text_candidate.py (not its baseline assembly: SP keeps the Simplified baseline), then the SP input locks."""
    # build_text_candidate.build() minus its last step (migrate_stage_dialogue: the canary stage component, an
    # input of the baseline assembly only)
    bd.run('python3', '-c', "import sys, subprocess; sys.path[:0] = ['tools', 'tools/special_disc/writeback']; "
           "import build_text_candidate as b; b.WORK.mkdir(parents=True, exist_ok=True); real = b.subprocess.run; "
           "b.subprocess.run = lambda cmd, **k: None if 'migrate_stage_dialogue' in str(cmd[1]) else real(cmd, **k); "
           "b.build()", cwd=tc)
    from locks import refresh_locks
    print('SP font locks refreshed:', refresh_locks(tc, SP_FONT_FILES), flush=True)


# SP configs that carry translations of their own (corpus-shaped: entries with translation), drafted into the
# Traditional clone with the corpus sync's converter and SP key rules; their locks follow.
SP_CONFIG_DRAFTS = ['config/editorial/special-disc/stage-context-reuse.json',
                    'config/editorial/special-disc/stage-native-overrides.json',
                    'config/products/special-disc/flow-layout.json',           # protected terms of the flow texts
                    'config/editorial/special-disc/chart-episode-labels.json',
                    'config/editorial/special-disc/chart-key-help.json',
                    'config/editorial/special-disc/chart-z-ending-titles.json',
                    'config/products/special-disc/shared-name-reference.json',   # Japanese name -> translations
                    'config/products/special-disc/name-unification-20261017.json',
                    'config/products/special-disc/event-gallery.json']             # 名场面集 scene names


# Main-game asset configs that SP's own image chain applies to SP's atlas (menu restore, bazaar heading). The
# Traditional overlays of these describe the Original atlas, so the SP clone keeps the Simplified ones until SP's
# own Traditional image chain exists (S5).
SP_KEEP_SC = ['config/assets/ui-menu-native-restore.json', 'config/assets/ui-bazaar-atlas-render-snapshot.json',
              'config/world-map-title-render-snapshot.json']            # SP world-map title bindings


def sp_keep_sc(tc: Path) -> None:
    import shutil
    for rel in SP_KEEP_SC:
        shutil.copyfile(ROOT / rel, tc / rel)
    from locks import refresh_locks
    print('SP keeps Simplified', SP_KEEP_SC, 'locks refreshed:', refresh_locks(tc, SP_KEEP_SC), flush=True)


def sp_config_drafts(tc: Path) -> None:
    from sync_corpus import Drafter, FROZEN_KEYS, SP_FROZEN
    drafter = Drafter(bd.ZH_HANT / 'bootstrap.json')
    drafter.frozen = (FROZEN_KEYS - {'review_history'}) | SP_FROZEN | {'source_locks'}
    for rel in SP_CONFIG_DRAFTS:
        doc = json.loads((ROOT / rel).read_text(encoding='utf-8'))
        bd.dump(tc / rel, drafter.value(doc))
    from locks import refresh_locks
    print('SP config drafts:', len(SP_CONFIG_DRAFTS), 'locks refreshed:', refresh_locks(tc, SP_CONFIG_DRAFTS), flush=True)


def sp_images_stay_sc(tc: Path) -> None:
    """S4: SP's label images (frame-text category image-label: world-map titles, KVM labels) stay Simplified in the
    Traditional build. Their snapshot and the KVM image chain after them (command headings, title atlas, menu
    restore, help title, ...) are bound to the Simplified pixels; the Traditional image chain is S5."""
    rel = 'corpus/zh/special-disc/frame-text.json'
    sc = {e['id']: e for e in json.loads((ROOT / rel).read_text(encoding='utf-8'))['entries']}
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    n = 0
    for e in doc['entries']:
        if e.get('category') == 'image-label':
            e['translation'] = sc[e['id']]['translation']; n += 1
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP image labels kept Simplified:', n, 'locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_instruction_layout(tc: Path) -> None:
    """Tutorial / Q&A instruction pages are bound to styled records (config/editorial/special-disc/
    instructions-layout.json): rebind each to its Traditional translation, record texts cut at the same lengths."""
    import hashlib
    rel = 'config/editorial/special-disc/instructions-layout.json'
    doc = json.loads((ROOT / rel).read_text(encoding='utf-8'))
    tc_rows = {e['id']: e for e in json.loads((tc / 'corpus/zh/special-disc/instructions-overrides.json').read_text(encoding='utf-8'))['entries']}
    for page in doc['pages']:
        text = tc_rows[page['id']]['translation']; flat = text.replace('\n', '')
        if len(flat) != sum(len(r['text']) for r in page['records']):
            raise SystemExit(f"{page['id']}: Traditional instruction text has another length")
        pos = 0
        for r in page['records']:
            n = len(r['text']); r['text'] = flat[pos:pos + n]; pos += n
        page['translation_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP instruction layout rebound:', len(doc['pages']), 'pages; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_stage_title_bindings(tc: Path) -> None:
    """The 21 SP stage-title images bind to the episode-title texts, which are also written as text (flow,
    titles), so the texts are Traditional; the image snapshot's bindings follow them while its pixels stay as
    authored until the Traditional images (S5)."""
    rel = 'config/assets/special-disc/stage-title-graphics.json'
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    rows = {e['id']: e for e in json.loads((tc / 'corpus/zh/special-disc/frame-text.json').read_text(encoding='utf-8'))['entries']}
    for t in doc['titles']:
        t['translation'] = rows[t['corpus_id']]['translation']
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP stage-title bindings follow the Traditional texts; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_qa_layout(tc: Path) -> None:
    """SP-reviewed Q&A answers are bound to styled lines (config/products/special-disc/qa-layout.json). Rebind each
    page to its Traditional translation: line texts from the Traditional entry, colour runs and table cells cut
    at the same character counts (the drafter keeps lengths; anything else stops here)."""
    import hashlib
    rel = 'config/products/special-disc/qa-layout.json'
    doc = json.loads((ROOT / rel).read_text(encoding='utf-8'))
    tc_native = {e['id']: e for e in json.loads((tc / 'corpus/zh/special-disc/native-text.json').read_text(encoding='utf-8'))['entries']}
    for page in doc['pages']:
        text = tc_native[page['id']]['translation']; lines = text.split('\n')
        if len(lines) != len(page['lines']): raise SystemExit(f"{page['id']}: Traditional answer has other lines")
        for line, new in zip(page['lines'], lines):
            if len(new) != len(line['text']): raise SystemExit(f"{page['id']}: line length changed: {line['text']} -> {new}")
            line['text'] = new
            for key in ('runs', 'cells'):
                pos = 0
                for part in line.get(key, []):
                    n = len(part['text']); part['text'] = new[pos:pos + n]; pos += n
        page['translation_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP Q&A layout rebound:', len(doc['pages']), 'pages; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_weapon_categories(tc: Path) -> None:
    """SP's weapon-category labels are LUI/ORI immediates like Original's: Traditional label, re-encoded with the
    Traditional codebook (build_dual.reencode_weapon_categories on SP's own contract)."""
    import struct
    from sync_corpus import Drafter
    drafter = Drafter(bd.ZH_HANT / 'bootstrap.json')
    rel = 'config/products/special-disc/weapon-detail-labels.json'
    sc_doc = json.loads((ROOT / rel).read_text(encoding='utf-8'))
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    sc_sites = {x['id']: x for x in sc_doc['runtime_weapon_category_labels']['sites']}
    ledger = json.loads((bd.ZH_HANT / 'encoding/zh-release-font-assignments.json').read_text(encoding='utf-8'))
    code_of = {r['character']: int(r['code'], 16) for r in ledger['primary_assignments']}
    pairs = {'melee': ((0, 2), (4, 5), (8, 9), (12, 14)), 'ranged': ((2, 3), (4, 6), (8, 10), (12, 14))}
    for site in doc['runtime_weapon_category_labels']['sites']:
        sc = sc_sites[site['id']]
        site['translation'] = tc_text = drafter.text(sc['translation'])
        if len(tc_text) != len(sc['translation']): raise SystemExit(f"weapon category {site['id']}: length changes")
        out = bytearray(bytes.fromhex(sc['output_materialized_hex']))
        for i, (x, y) in enumerate(zip(sc['translation'], tc_text)):
            if x != y: out[2 * i:2 * i + 2] = code_of[y].to_bytes(2, 'big')
        block = bytearray(bytes.fromhex(sc['replacement_block_hex']))
        words = list(struct.unpack(f'<{len(block) // 4}I', block))
        for n, (lui, ori) in enumerate(pairs[site['id']]):
            value = int.from_bytes(out[4 * n:4 * n + 4], 'little')
            words[lui] = (words[lui] & 0xFFFF0000) | (value >> 16)
            words[ori] = (words[ori] & 0xFFFF0000) | (value & 0xFFFF)
        site['replacement_block_hex'] = struct.pack(f'<{len(words)}I', *words).hex().upper()
        site['output_materialized_hex'] = out.hex().upper()
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP weapon categories:', [x['translation'] for x in doc['runtime_weapon_category_labels']['sites']],
          'locks refreshed:', refresh_locks(tc, [rel]), flush=True)


# SP configs whose expected inventories list translated labels (exact corpus strings): mapped to the Traditional
# counterparts like the Original component config (build_dual.localize_literals).
SP_LOCALIZE = ['config/products/special-disc/weapon-detail-labels.json']


def sp_localize(tc: Path) -> None:
    literals = json.loads((tc / 'config/zh-hant/readback-literals.json').read_text(encoding='utf-8'))['literals']
    n = 0
    for rel in SP_LOCALIZE:
        doc = json.loads((tc / rel).read_text(encoding='utf-8'))
        n += bd.localize_literals(doc, literals); bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP config literals mapped:', n, 'locks refreshed:', refresh_locks(tc, SP_LOCALIZE), flush=True)


def sp_encoded_contracts(tc: Path) -> None:
    """SP contracts that store the expected encoded bytes of a translation (keyword list labels): recompute them
    from the Traditional translation with the Traditional SP encoding tables, inside the clone."""
    script = (
        "import json, sys; from pathlib import Path; sys.path[:0] = ['tools', 'tools/special_disc/writeback']\n"
        "from migrate_slps_text import encoding_tables\n"
        "import special_disc.writeback.keyword_list_names as k\n"
        "table, _, overrides, _ = encoding_tables(Path('work/build/special-disc/text-candidate/font/proposal.json'))\n"
        "c, rows, _ = k.inputs(); doc = json.loads(k.CONTRACT.read_text())\n"
        "for w in doc['writes']: w['target_hex'] = k.payload(rows[w['index']]['translation'], table, overrides).hex().upper()\n"
        "k.CONTRACT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\\n')\n")
    bd.run('python3', '-c', script, cwd=tc)
    from locks import refresh_locks
    rel = 'config/products/special-disc/keyword-list-names.json'
    print('SP keyword targets re-encoded; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_gallery_talk(tc: Path) -> None:
    """The 名场面集 dialogue is a corpus snapshot (event-gallery-talk.json): author it from the Traditional corpus."""
    bd.run('python3', 'tools/special_disc/event_gallery/author_talk.py', cwd=tc)
    from locks import refresh_locks
    rel = 'config/products/special-disc/event-gallery-talk.json'
    print('SP gallery dialogue re-authored; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def build(project: Path, version: str) -> Path:
    (project / 'manifests/editions/sp/candidate.json').unlink(missing_ok=True)
    bd.run('python3', 'tools/build_editions.py', '--editions', 'sp', '--candidate', '--release-version', version, cwd=project)
    return project / 'build/iso/test/integrated-sp.iso'


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--release-version', default='0.5.1')
    p.add_argument('--skip-sc', action='store_true', help='reuse build/zh-hant/project-sp from an earlier run')
    p.add_argument('--tc-only', action='store_true', help='stop after the Traditional build')
    p.add_argument('--out', type=Path, default=ROOT / 'build/iso/test/zh-hant-dual-sp.iso')
    a = p.parse_args()
    check = bd.run(sys.executable, HERE / 'sync_corpus.py', '--check', check=False)
    if check.returncode:
        raise SystemExit('parallel Traditional corpora are out of sync; run tools/zh_hant/sync_corpus.py\n' + check.stdout)
    sc_iso = bd.BASE / 'project-sp/build/iso/test/integrated-sp.iso'
    if not (a.skip_sc and sc_iso.exists()):
        sc_iso = build(clone('project-sp'), a.release_version)
    tc = clone('project-sp-tc')
    bd.prepare_tc(tc)
    bd.codebook_step(tc, False)
    bd.menu_codebook(tc)
    sp_keep_sc(tc)
    sp_font(tc)
    sp_config_drafts(tc)
    sp_images_stay_sc(tc)
    sp_stage_title_bindings(tc)
    sp_qa_layout(tc)
    sp_instruction_layout(tc)
    sp_weapon_categories(tc)
    sp_localize(tc)
    # SP's frozen baseline in Traditional: the September converters with the Traditional Original build as the
    # answer key (sp_tc_baseline.py), so inherited text comes from the same parallel corpus as Original.
    answer_key = sorted((bd.BASE / 'project-tc/build/editions/zh-release-original').glob('*/project/work/build/zh-release-full-story/components'))
    if len(answer_key) != 1: raise SystemExit('need exactly one Traditional Original build in build/zh-hant/project-tc (run build_dual.py)')
    bd.run(sys.executable, HERE / 'sp_tc_baseline.py', tc, '--answer-key', answer_key[0])
    sp_encoded_contracts(tc)
    sp_gallery_talk(tc)
    tc_iso = build(tc, a.release_version)
    if a.tc_only:
        print(tc_iso); return
    bd.run(sys.executable, HERE / 'assemble_dual.py', '--edition', 'sp', '--sc', sc_iso, '--tc', tc_iso,
           '--tc-codebook', bd.ZH_HANT / 'encoding/zh-release-font-assignments.json', '--out', a.out,
           '--work', bd.BASE / 'assemble-sp')


if __name__ == '__main__':
    main()
