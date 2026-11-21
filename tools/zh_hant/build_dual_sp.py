#!/usr/bin/env python3
"""SP's Traditional inputs (docs/ZH_HANT_SP_DUAL_PLAN_20261117.md).

Same scheme as build_dual.py (Original): the unchanged pipeline builds SP once per language from this checkout
(build_editions.py --editions sp --language ...). SP is built on a frozen baseline whose inherited text comes
from the Original build; sp_prepare below rebuilds that baseline in the language, inside the view that
language_view.py makes when the build freezes its inputs, with the same language's Original build as answer key.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_dual as bd  # noqa: E402

ROOT = bd.ROOT
SP_FILES = ['work/analysis/sp-event-fidelity-20261013/' + n for n in      # author_talk.py's id map and name helper
            ('id-map.json', 'names.py', 'original-compdata.bin', 'sp-jp-compdata.bin')]
DISC_INVENTORY = ROOT / 'config/products/special-disc/disc-inventory.json'
SP_ISO = json.loads(DISC_INVENTORY.read_text(encoding='utf-8'))['sp']['path']   # rom/...


SP_FONT_FILES = ['work/build/special-disc/text-candidate/font/' + n for n in ('manifest.json', 'profile.json', 'proposal.json')] + \
                ['work/build/special-disc/text-candidate/sp-font/' + n for n in ('font.bin', 'report.json')]


def sp_font(tc: Path) -> None:
    """SP's font component from the Traditional codebook (the clone's release-font profile), by the SP font steps of
    build_text_candidate.py (not its baseline assembly: SP keeps the Simplified baseline), then the SP input locks."""
    # build_text_candidate.build() minus its last step (migrate_stage_dialogue: the canary stage component, an
    # input of the baseline assembly only)
    bd.run(sys.executable, '-c', "import sys, subprocess; sys.path[:0] = ['tools', 'tools/special_disc/writeback']; "
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
                    'config/products/special-disc/event-gallery.json',             # 名场面集 scene names
                    # styled layouts of the tutorial / Q&A pages: each language's own (records, lines, colour runs
                    # and cells carry that language's text, at that language's lengths)
                    'config/editorial/special-disc/instructions-layout.json',
                    'config/products/special-disc/qa-layout.json']


# Main-game asset configs that SP's own image chain applies to SP's atlas (menu restore, bazaar heading). The
# Traditional overlays of these describe the Original atlas, so the SP clone keeps the Simplified ones until SP's
# own Traditional image chain exists (S5).
SP_KEEP_SC = ['config/assets/ui-menu-native-restore.json', 'config/assets/ui-bazaar-atlas-render-snapshot.json']


def sp_keep_sc(tc: Path) -> None:
    import shutil
    for rel in SP_KEEP_SC:
        shutil.copyfile(ROOT / rel, tc / rel)
    from locks import refresh_locks
    print('SP keeps Simplified', SP_KEEP_SC, 'locks refreshed:', refresh_locks(tc, SP_KEEP_SC), flush=True)


def sp_config_drafts(tc: Path, variant: str = 'tw') -> None:
    """The regional SP configs are kept per language in config/zh-hant/sp-configs/<variant> (sp_configs.py): drafted
    from Simplified once, then edited there. A build copies them; a stale or missing copy stops it."""
    import shutil
    import sp_configs
    problems = [p for p in sp_configs.status() if p.startswith(f'{variant}:')]
    if problems:
        raise SystemExit('regional SP configs need attention:\n' + '\n'.join(problems))
    for rel in sp_configs.stored_paths():
        shutil.copyfile(sp_configs.STORE / variant / rel, tc / rel)
    from locks import refresh_locks
    print('SP regional configs placed:', len(sp_configs.stored_paths()), 'locks refreshed:',
          refresh_locks(tc, SP_CONFIG_DRAFTS), flush=True)
    sp_name_reference(tc, variant)


def sp_name_reference(tc: Path, variant: str) -> None:
    """SP's roster check compares every unit/pilot name on the disc with shared-name-reference.json. The disc takes
    those names from this language's corpus (unit display names, story speakers, residual names), so the reference
    takes them from the same place: each Simplified value becomes the regional value the corpus pairs it with."""
    suffix = '' if variant == 'tw' else '-hk'
    pairs: dict = {}
    def add(sc, rg):
        if isinstance(sc, str) and isinstance(rg, str) and sc and rg: pairs.setdefault(sc, set()).add(rg)
    sc_u = json.loads((ROOT / 'corpus/zh/display-names/units-full.json').read_text(encoding='utf-8'))['segments']
    rg_u = json.loads((ROOT / f'corpus/zh-hant{suffix}/display-names/units-full.json').read_text(encoding='utf-8'))['segments']
    for a, b in zip(sc_u, rg_u):
        for x, y in zip(a['translations'], b['translations']): add(x, y)
    sc_s = {e['id']: e['translation'] for e in json.loads((ROOT / 'corpus/zh/story-speakers.json').read_text(encoding='utf-8'))['entries']}
    for e in json.loads((ROOT / f'corpus/zh-hant{suffix}/story-speakers.json').read_text(encoding='utf-8'))['entries']:
        add(sc_s.get(e['id']), e['translation'])
    sc_r = json.loads((ROOT / 'corpus/zh/menu/remaining-ui.json').read_text(encoding='utf-8')).get('display_names_by_source_text', {})
    rg_r = json.loads((ROOT / f'corpus/zh-hant{suffix}/menu/remaining-ui.json').read_text(encoding='utf-8')).get('display_names_by_source_text', {})
    for k, v in sc_r.items(): add(v, rg_r.get(k))
    rel = 'config/products/special-disc/shared-name-reference.json'
    sc_doc = json.loads((ROOT / rel).read_text(encoding='utf-8'))
    # names without a corpus pair: this language's stored reference (static, config/zh-hant/sp-configs/<variant>)
    doc = json.loads((bd.ZH_HANT / 'sp-configs' / variant / rel).read_text(encoding='utf-8'))
    changed = 0
    for kind in ('units', 'pilots'):
        for key, values in sc_doc[kind].items():
            out = list(doc[kind][key])
            for i, v in enumerate(values):
                forms = pairs.get(v)
                if forms and len(forms) == 1 and out[i] not in forms:
                    out[i] = next(iter(forms)); changed += 1
            doc[kind][key] = out
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP name reference bound to the corpus names:', changed, 'locks refreshed:', refresh_locks(tc, [rel]), flush=True)
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
        if e.get('category') == 'image-label' and any(l.startswith('sd/image/kvmdata/') for l in e['locations']):
            e['translation'] = sc[e['id']]['translation']; n += 1
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP menu-atlas labels kept Simplified:', n, 'locks refreshed:', refresh_locks(tc, [rel]), flush=True)
    sp_image_labels_refreeze(tc)


def sp_image_labels_refreeze(tc: Path) -> None:
    """Refreeze SP's image-label snapshot on the clone's current baseline: the other image labels (the three newer
    world-map titles in MAPMODEL) are authored in Traditional; the settlement-label chunk's source changes again once
    the Traditional baseline carries the Original's Traditional texture delta (its 已通關)."""
    from locks import refresh_locks
    bd.run(sys.executable, 'tools/special_disc/writeback/write_image_labels.py', '--refreeze',
           '--output', tc / 'build/zh-hant-sp/image-labels', cwd=tc)
    snap = 'config/assets/special-disc/full-text-image-labels.json'
    print('SP image labels re-authored; locks refreshed:', refresh_locks(tc, [snap]), flush=True)


def sp_instruction_layout(tc: Path) -> None:
    """Tutorial / Q&A instruction pages are bound to styled records (config/editorial/special-disc/
    instructions-layout.json). Each language keeps its own layout (config/zh-hant/sp-configs/<variant>, placed in
    the clone by sp_config_drafts): its records must spell exactly that language's instruction text."""
    import hashlib
    rel = 'config/editorial/special-disc/instructions-layout.json'
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    rows = {e['id']: e for e in json.loads((tc / 'corpus/zh/special-disc/instructions-overrides.json').read_text(encoding='utf-8'))['entries']}
    for page in doc['pages']:
        text = rows[page['id']]['translation']
        if ''.join(r['text'] for r in page['records']) != text.replace('\n', ''):
            raise SystemExit(f"{page['id']}: the regional instruction layout does not spell the regional text; update "
                             f"config/zh-hant/sp-configs/<variant>/{rel}")
        page['translation_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP instruction layout checked:', len(doc['pages']), 'pages; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_world_map_titles(tc: Path) -> None:
    """SP's ten world-map titles reuse the Original world-map title renders (config/world-map-title-render-snapshot.json,
    Traditional in the clone): the SP bindings take the Traditional rows."""
    import hashlib
    rel = 'config/assets/special-disc/world-map-title-bindings.json'
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    snap_path = tc / doc['snapshot']['path']
    rows = {e['id']: e for e in json.loads(snap_path.read_text(encoding='utf-8'))['entries']}
    for b in doc['bindings']:
        row = rows[b['snapshot_id']]
        if row['source_raw_sha256'] != b['source_raw_sha256']: raise SystemExit(f"{b['snapshot_id']}: source drift")
        b['translation'] = row['translation']; b['output_raw_sha256'] = row['output_raw_sha256']
    doc['snapshot']['sha256'] = hashlib.sha256(snap_path.read_bytes()).hexdigest()
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP world-map titles bound to the Traditional renders; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_qa_layout(tc: Path) -> None:
    """SP-reviewed Q&A answers are bound to styled lines (config/products/special-disc/qa-layout.json). Each language
    keeps its own layout (config/zh-hant/sp-configs/<variant>): its lines, colour runs and table cells must spell
    exactly that language's answer text."""
    import hashlib
    rel = 'config/products/special-disc/qa-layout.json'
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    native = {e['id']: e for e in json.loads((tc / 'corpus/zh/special-disc/native-text.json').read_text(encoding='utf-8'))['entries']}
    for page in doc['pages']:
        text = native[page['id']]['translation']; lines = text.split('\n')
        bad = len(lines) != len(page['lines']) or any(
            line['text'] != new or any(''.join(x['text'] for x in line[key]) != new for key in ('runs', 'cells') if line.get(key))
            for line, new in zip(page['lines'], lines))
        if bad:
            raise SystemExit(f"{page['id']}: the regional Q&A layout does not spell the regional answer; update "
                             f"config/zh-hant/sp-configs/<variant>/{rel}")
        page['translation_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    bd.dump(tc / rel, doc)
    from locks import refresh_locks
    print('SP Q&A layout checked:', len(doc['pages']), 'pages; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_weapon_categories(tc: Path, variant: str = 'tw') -> None:
    """SP's weapon-category labels are LUI/ORI immediates like Original's: Traditional label, re-encoded with the
    Traditional codebook (build_dual.reencode_weapon_categories on SP's own contract)."""
    import struct
    # the label text is this language's own (the readback literals of the clone, i.e. its parallel corpus), never a draft
    literals = json.loads((tc / 'config/zh-hant/readback-literals.json').read_text(encoding='utf-8'))['literals']
    rel = 'config/products/special-disc/weapon-detail-labels.json'
    sc_doc = json.loads((ROOT / rel).read_text(encoding='utf-8'))
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    sc_sites = {x['id']: x for x in sc_doc['runtime_weapon_category_labels']['sites']}
    ledger = json.loads((bd.ZH_HANT / 'encoding/zh-release-font-assignments.json').read_text(encoding='utf-8'))
    code_of = {r['character']: int(r['code'], 16) for r in ledger['primary_assignments']}
    pairs = {'melee': ((0, 2), (4, 5), (8, 9), (12, 14)), 'ranged': ((2, 3), (4, 6), (8, 10), (12, 14))}
    for site in doc['runtime_weapon_category_labels']['sites']:
        sc = sc_sites[site['id']]
        if sc['translation'] not in literals:
            raise SystemExit(f"SP weapon category {site['id']}: {sc['translation']!r} has no {variant} text in the corpus")
        site['translation'] = tc_text = literals[sc['translation']]
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
    sys.path.insert(0, str(ROOT / 'tools'))
    from srwz.build_language import AskedLiterals
    literals = AskedLiterals(tc)       # asked string by string: the dictionary changes with every edited line
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
    bd.run(sys.executable, '-c', script, cwd=tc)
    from locks import refresh_locks
    rel = 'config/products/special-disc/keyword-list-names.json'
    print('SP keyword targets re-encoded; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_gallery_talk(tc: Path) -> None:
    """The 名场面集 dialogue is a corpus snapshot (event-gallery-talk.json): author it from the Traditional corpus."""
    bd.run(sys.executable, 'tools/special_disc/event_gallery/author_talk.py', cwd=tc)
    from locks import refresh_locks
    rel = 'config/products/special-disc/event-gallery-talk.json'
    print('SP gallery dialogue re-authored; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_stage_titles(tc: Path) -> None:
    """The 21 SP stage-title images, authored from the Traditional texts with the Traditional SP font (the text
    canary baseline carries it) by SP's own authoring tool; the snapshot's locks follow."""
    script = ("import sys; sys.path[:0] = ['tools', 'tools/special_disc/writeback', 'tools/special_disc/images']\n"
              "from special_disc.baselines import baseline_iso\n"
              "iso = baseline_iso('text-canary')\n"
              "sys.argv = ['freeze_stage_titles', '--font-iso', str(iso), '--proposal',\n"
              "            'work/build/special-disc/text-candidate/font/proposal.json', '--output', 'build/zh-hant-sp/stage-titles']\n"
              "import freeze_stage_titles\nfreeze_stage_titles.main()\n")
    bd.run(sys.executable, '-c', script, cwd=tc)
    from locks import refresh_locks
    rel = 'config/assets/special-disc/stage-title-graphics.json'
    print('SP stage titles authored in Traditional; locks refreshed:', refresh_locks(tc, [rel]), flush=True)


def sp_prepare(tc: Path, variant: str, answer_key: Path, tw_key: Path, sc_key: Path, *, answer_keys=None) -> None:
    """SP's own Traditional inputs, in a project that already holds the language's corpus, codebook and menu
    codebook (build_dual.prepare_tc / menu_codebook) and SP's support trees (work/build/special-disc, discs).
    Two stages; language_view.py runs each as a process of its own so that srwz.step_memo can reuse them."""
    sp_stage_font_configs(tc, variant)
    if answer_keys is not None:
        answer_key, tw_key, sc_key = answer_keys()
    sp_stage_baseline_atlas(tc, variant, answer_key, tw_key, sc_key)


def sp_stage_font_configs(tc: Path, variant: str) -> None:
    """Everything that does not read an Original build: SP's font in the Traditional codebook, and the SP
    configs and image labels rebound to the Traditional texts."""
    started = time.perf_counter()
    sp_keep_sc(tc)
    sp_font(tc)
    print(f'[sp-view] font: {time.perf_counter()-started:.2f}s', flush=True)
    started = time.perf_counter()
    sp_config_drafts(tc, variant)
    sp_world_map_titles(tc)
    sp_images_stay_sc(tc)
    sp_qa_layout(tc)
    sp_instruction_layout(tc)
    sp_weapon_categories(tc, variant)
    sp_localize(tc)
    print(f'[sp-view] configs-and-labels: {time.perf_counter()-started:.2f}s', flush=True)


def sp_stage_baseline_atlas(tc: Path, variant: str, answer_key: Path, tw_key: Path, sc_key: Path) -> None:
    """Everything that reads the Original builds: the inherited baseline, the assets bound to it and the atlas."""
    # SP's frozen baseline in Traditional: the September converters with the Traditional Original build as the
    # answer key (sp_tc_baseline.py), so inherited text comes from the same parallel corpus as Original.
    started = time.perf_counter()
    bd.run(sys.executable, HERE / 'sp_tc_baseline.py', tc, '--answer-key', answer_key, '--simplified-answer-key', sc_key,
           '--variant', variant)
    print(f'[sp-view] baseline-total: {time.perf_counter()-started:.2f}s', flush=True)
    started = time.perf_counter()
    sp_image_labels_refreeze(tc)
    sp_encoded_contracts(tc)
    sp_gallery_talk(tc)
    sp_stage_titles(tc)
    print(f'[sp-view] post-baseline-assets: {time.perf_counter()-started:.2f}s', flush=True)
    # SP's own image chain stays Simplified (its seals); its text cells become Traditional in one final delta
    started = time.perf_counter()
    bd.run(sys.executable, HERE / 'sp_menu_atlas.py', tc, '--simplified', sc_key, '--traditional', tw_key,
           '--review', bd.BASE / f'sp-menu-atlas-review-{variant}')
    print(f'[sp-view] menu-atlas: {time.perf_counter()-started:.2f}s', flush=True)


def sp_shared_from_taiwan(tc: Path) -> None:
    """Hong Kong SP: rows whose output is shared with the Taiwan build take the Taiwan text, so the disc keeps one
    copy of each big member (the Original's texture sources and terrain names do the same):
      * frame-corpus image labels (world-map titles, KVM labels) and stage names (the 21 stage-title images);
      * frame-corpus rows stored in VT1 (sd/vt1/...): SP's VT1 can only be redirected whole (196 MB);
      * the Data Link page (data_link_bonus.py, VT1 group 40);
      * terrain names: stored in every map chunk of MAPMODEL (37.7 MB)."""
    rel = 'corpus/zh/special-disc/frame-text.json'
    tw = {e['id']: e for e in json.loads((ROOT / 'corpus/zh-hant/special-disc/frame-text.json').read_text(encoding='utf-8'))['entries']}
    doc = json.loads((tc / rel).read_text(encoding='utf-8'))
    n = 0
    for e in doc['entries']:
        if e.get('category') == 'image-label' or any(l.startswith(('sd/stage-name/', 'sd/vt1/')) for l in e.get('locations', [])):
            if e['translation'] != tw[e['id']]['translation']: n += 1
            e['translation'] = tw[e['id']]['translation']
    bd.dump(tc / rel, doc)
    terrain = 'corpus/zh/special-disc/terrain-names.json'
    bd.dump(tc / terrain, bd.strip_meta(json.loads((ROOT / 'corpus/zh-hant/special-disc/terrain-names.json').read_text(encoding='utf-8'))))
    # the Data Link page (data_link_bonus.PAGE_LINES, VT1 group 40) is a tool constant: its readback literals too
    lit_path = tc / 'config/zh-hant/readback-literals.json'
    lit = json.loads(lit_path.read_text(encoding='utf-8'))
    lit['literals'].update(taiwan_data_link_literals())
    bd.dump(lit_path, lit)
    from locks import refresh_locks
    print('SP rows kept Taiwan:', n, '+ terrain names + Data Link page; locks refreshed:', refresh_locks(tc, [rel, terrain]), flush=True)


def taiwan_data_link_literals():
    """The Taiwan literal mapping actually consumed by Hong Kong's shared Data Link page."""
    import ast, re
    src = (ROOT / 'tools/special_disc/writeback/data_link_bonus.py').read_text(encoding='utf-8')
    lines = ast.literal_eval(re.search(r'^PAGE_LINES = (\(.*?^\))', src, re.S | re.M).group(1))
    import tool_literals
    tw_lit = bd.literal_pairs(ROOT / 'corpus/zh', ROOT / 'corpus/zh-hant')
    tw_tool = tool_literals.load('tw')
    out = {}
    for s in lines:
        if not s: continue
        t = tw_lit.get(s) or tw_tool.get(s)
        if t is None:
            raise SystemExit(f'Data Link line {s!r} has no Taiwan text (config/zh-hant/tool-literals/tw.json)')
        out[s] = t
    return out
