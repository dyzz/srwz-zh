#!/usr/bin/env python3
"""One Original disc with Simplified and Traditional, built from parallel sources.

Simplified and Traditional are parallel: each language has its own corpus, glossary, runtime keyword table,
layout word lists and release codebook/font. The unchanged build pipeline runs once per language, each in an
APFS clone of the build inputs under build/zh-hant/ (nothing in the repository changes), and
assemble_dual.py turns the two single-language images into one disc.

Traditional sources (repository):
  corpus/zh-hant/, corpus/glossary-zh-hant/, corpus/runtime-zh-hant/   parallel corpora (tools/zh_hant/sync_corpus.py)
  config/zh-hant/encoding/zh-release-font-assignments.json            Traditional codebook (build_codebook.py)
  config/zh-hant/font-profile.json                                    font_capacity + count ratchet of that codebook
  config/zh-hant/text-layout/*.json                                    Traditional layout word lists
Generated into the Traditional clone only:
  config/zh-hant/readback-literals.json   Simplified readback literals -> Traditional counterparts (parallel corpora)
  stage-title snapshot text               the Traditional stage names (pixels stay Simplified until M4 textures)

Steps: check the parallel corpora are in sync -> Simplified build -> Traditional build -> assemble.
A Traditional character without a code stops the build; --update-codebook lets the pipeline's allocator append it
and writes the grown codebook back to config/zh-hant/.
Usage: build_dual.py [--release-version 0.5.1] [--skip-sc] [--update-codebook] [--out build/iso/test/NAME.iso]
Needs a Python with opencc (sync check); the builds use plain python3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT / 'build/zh-hant'
TREES = ['config', 'corpus', 'manifests', 'tools', 'vendor/upstream-python', 'shared/text-layout',
         'work/font-source', 'work/disc', 'work/toolchain', 'work/writeback']
ZH_HANT = ROOT / 'config/zh-hant'
sys.path.insert(0, str(HERE))
from sync_corpus import strip_meta, FROZEN_KEYS, META  # noqa: E402


def run(*cmd, cwd=ROOT, check=True):
    print('$', ' '.join(map(str, cmd)), flush=True)
    return subprocess.run(list(map(str, cmd)), cwd=cwd, check=check, capture_output=not check, text=True)


def clone(name: str) -> Path:
    dst = BASE / name
    if dst.exists(): shutil.rmtree(dst)
    for tree in TREES:
        (dst / tree).parent.mkdir(parents=True, exist_ok=True)
        run('cp', '-cR', ROOT / tree, dst / tree)
    (dst / 'build/iso/sources').mkdir(parents=True)
    run('cp', '-c', ROOT / 'build/iso/sources/original.iso', dst / 'build/iso/sources/original.iso')
    (dst / 'rom').symlink_to('build/iso/sources')
    return dst


def build(project: Path, version: str) -> Path:
    (project / 'manifests/editions/original/candidate.json').unlink(missing_ok=True)
    run('python3', 'tools/build_editions.py', '--editions', 'original', '--candidate', '--release-version', version, cwd=project)
    return project / 'build/iso/test/integrated-original.iso'


def dump(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


# Parallel files the build does not take (see the note below).
# formation-help-headings feeds the heading cells; every visible one is overwritten by a Traditional clarity or
# help-title cell (author_textures.kvm_chain), so the build keeps the Simplified file and its heading snapshot.
TEXTURE_DEFERRED = {'corpus/zh-hant/ui-atlas/formation-help-headings.json'}


OVERLAID: list = []       # build paths of the parallel files placed by overlay_tree (their locks are refreshed)


def overlay_tree(src: Path, dst: Path) -> int:
    """Replace each file of dst that src has a parallel of (metadata stripped); keep dst's other files."""
    n = 0
    for f in src.rglob('*.json'):
        if any(str(f.relative_to(ROOT)).startswith(d) for d in TEXTURE_DEFERRED): continue
        target = dst / f.relative_to(src)
        dump(target, strip_meta(json.loads(f.read_text(encoding='utf-8')))); n += 1
        OVERLAID.append(str(target.relative_to(dst.parents[1])))              # dst is <clone>/corpus/<tree>
    return n


def literal_pairs(sc_root: Path, tc_root: Path) -> dict:
    """Every translated Simplified string -> the Traditional string at the same place in the parallel file."""
    def strings(doc, key=None):
        if isinstance(doc, str):
            if key not in FROZEN_KEYS: yield doc
        elif isinstance(doc, list):
            for v in doc: yield from strings(v, key)
        elif isinstance(doc, dict):
            for k, v in doc.items():
                if k not in FROZEN_KEYS and not k.endswith('_sha256') and k not in META and k != 'zh_hant_meta':
                    yield from strings(v, k)
    pairs = {}
    for f in tc_root.rglob('*.json'):
        sc = sc_root / f.relative_to(tc_root)
        if sc.exists():
            for a, b in zip(strings(json.loads(sc.read_text(encoding='utf-8'))), strings(json.loads(f.read_text(encoding='utf-8')))):
                pairs.setdefault(a, b)
    return pairs


BUILD_TOOL_SOURCES = ('tools/srwz/*.py', 'tools/build_full_story_components.py', 'tools/verify_full_story_iso_content.py',
                      'tools/special_disc/writeback/*.py', 'tools/special_disc/event_gallery/*.py',      # SP (build_dual_sp.py)
                      'tools/special_disc/no_bgm/*.py', 'tools/special_disc/verification/*.py')
LITERAL_SKIP = {'tutorial_title_effects'}        # replaced as a whole by its Traditional section (author_textures.py)


def localize_literals(node, literals: dict, key=None) -> int:
    """Replace, in place, every string value that is exactly a Simplified corpus string with its Traditional one."""
    n = 0
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for k, v in items:
        name = k if isinstance(k, str) else key
        if isinstance(name, str) and (name in FROZEN_KEYS or 'source' in name or name.endswith('sha256') or name in LITERAL_SKIP):
            continue
        if isinstance(v, str):
            if v in literals and literals[v] != v:
                node[k] = literals[v]; n += 1
        else:
            n += localize_literals(v, literals, name)
    return n


def reencode_weapon_categories(comp: dict, tc: Path) -> None:
    """Weapon-category labels are built by LUI/ORI immediates in the executable: re-encode each changed character
    with the Traditional codebook and rewrite the immediates (格斗 -> 格鬥 needs 鬥's own code)."""
    import struct
    sc_sites = {s['id']: s for s in json.loads((ROOT / 'config/full-story-components.json').read_text(encoding='utf-8'))
                ['runtime_weapon_category_labels']['sites']}
    ledger = json.loads((ZH_HANT / 'encoding/zh-release-font-assignments.json').read_text(encoding='utf-8'))
    code_of = {r['character']: int(r['code'], 16) for r in ledger['primary_assignments']}
    pairs = {'melee': ((0, 2), (4, 5), (8, 9), (12, 14)), 'ranged': ((2, 3), (4, 6), (8, 10), (12, 14))}
    for site in comp['runtime_weapon_category_labels']['sites']:
        sc = sc_sites[site['id']]
        tc_text = site['translation']
        out = bytearray(bytes.fromhex(sc['output_materialized_hex']))
        if len(tc_text) != len(sc['translation']):
            raise SystemExit(f"weapon category {site['id']}: Traditional label changes length")
        for i, (a, b) in enumerate(zip(sc['translation'], tc_text)):
            if a != b:
                out[2 * i:2 * i + 2] = code_of[b].to_bytes(2, 'big')
        block = bytearray(bytes.fromhex(sc['replacement_block_hex']))
        words = list(struct.unpack(f'<{len(block) // 4}I', block))
        for n, (lui, ori) in enumerate(pairs[site['id']]):
            value = int.from_bytes(out[4 * n:4 * n + 4], 'little')
            words[lui] = (words[lui] & 0xFFFF0000) | (value >> 16)
            words[ori] = (words[ori] & 0xFFFF0000) | (value & 0xFFFF)
        site['replacement_block_hex'] = struct.pack(f'<{len(words)}I', *words).hex().upper()
        site['output_materialized_hex'] = out.hex().upper()


def stale_stage_titles(tc_iso: Path) -> list:
    """What the Traditional stage-title snapshot was authored against, compared with the current inputs."""
    sys.path.insert(0, str(HERE))
    from author_stage_titles import tc_font
    prov = json.loads((ZH_HANT / 'stage-title-graphics-indexed-snapshot.json').read_text(encoding='utf-8'))['provenance']
    sha = lambda b: hashlib.sha256(b).hexdigest()
    now = {'font_decoded_sha256': sha(tc_font(tc_iso)),
           'codebook_sha256': sha((ZH_HANT / 'encoding/zh-release-font-assignments.json').read_bytes()),
           'stage_names_sha256': sha((ROOT / 'corpus/zh-hant/menu/stage-names.json').read_bytes())}
    return [k for k, v in now.items() if prov.get(k) != v]


def prepare_tc(tc: Path) -> None:
    for parallel in ('zh-hant', 'glossary-zh-hant', 'runtime-zh-hant'):
        shutil.rmtree(tc / 'corpus' / parallel, ignore_errors=True)     # sources of the overlay, not build inputs
    stats = {'corpus/zh': overlay_tree(ROOT / 'corpus/zh-hant', tc / 'corpus/zh'),
             'corpus/glossary': overlay_tree(ROOT / 'corpus/glossary-zh-hant', tc / 'corpus/glossary'),
             'corpus/runtime': overlay_tree(ROOT / 'corpus/runtime-zh-hant', tc / 'corpus/runtime')}
    for f in (ZH_HANT / 'text-layout').glob('*.json'):
        shutil.copyfile(f, tc / 'config/text-layout' / f.name)
    # Traditional codebook and font profile
    ledger = (ZH_HANT / 'encoding/zh-release-font-assignments.json').read_bytes()
    (tc / 'config/encoding/zh-release-font-assignments.json').write_bytes(ledger)
    font_config = tc / 'config/fonts/zh-release-font.json'
    font = json.loads(font_config.read_text(encoding='utf-8'))
    profile = json.loads((ZH_HANT / 'font-profile.json').read_text(encoding='utf-8'))
    font['font_capacity'] = profile['font_capacity']; font['expected'] = profile['expected']
    selection = font['translation_tree_selection']
    selection['exclude_globs'] = selection['exclude_globs'] + profile.get('translation_tree_extra_exclude_globs', [])
    if profile.get('translation_tree_extra_exclude_reason'):
        selection['exclude_reason'] += ' ' + profile['translation_tree_extra_exclude_reason']
    font['allocation_snapshot']['sha256'] = hashlib.sha256(ledger).hexdigest()
    dump(font_config, font)
    # Stage-title images: the Traditional snapshot (author_stage_titles.py, rendered from the Traditional build's
    # own font) replaces the Simplified one; its lock and precision counts follow.
    snap_path = tc / 'config/assets/stage-title-graphics-indexed-snapshot.json'
    shutil.copyfile(ZH_HANT / 'stage-title-graphics-indexed-snapshot.json', snap_path)
    snap = json.loads(snap_path.read_text(encoding='utf-8'))
    components = tc / 'config/full-story-components.json'
    comp = json.loads(components.read_text(encoding='utf-8'))
    graphics = comp['full_stage_titles']['graphics']
    graphics['frozen_snapshot'].update(size=snap_path.stat().st_size, sha256=hashlib.sha256(snap_path.read_bytes()).hexdigest())
    reduced = [t['ordinal'] for t in snap['titles'] if t['quantization_levels'] < 16]
    graphics['expected'].update(full_precision_count=len(snap['titles']) - len(reduced), reduced_precision_ordinals=reduced)
    dump(components, comp)
    literals = literal_pairs(ROOT / 'corpus/zh', ROOT / 'corpus/zh-hant')
    from sync_corpus import Drafter
    drafter = Drafter(ZH_HANT / 'bootstrap.json')
    # String constants of the build tools that are not whole corpus strings (layout-protected words, label
    # fragments) get the bootstrap conversion, so srwz.build_language can answer for every literal a gate names.
    extra = 0
    for f in BUILD_TOOL_SOURCES:
        for path in sorted(ROOT.glob(f)):
            for m in re.finditer(r'(["\'])([^"\'\n]*[\u4e00-\u9fff][^"\'\n]*)\1', path.read_text(encoding='utf-8')):
                if m.group(2) not in literals:
                    literals[m.group(2)] = drafter.text(m.group(2)); extra += 1
    forms = {}
    for a, b in literals.items():
        if len(a) == len(b):
            for x, y in zip(a, b):
                if '\u3400' <= x <= '\u9fff': forms.setdefault(x, {}).setdefault(y, 0); forms[x][y] += 1
    characters = {x: max(c, key=lambda y: (c[y], y == x)) for x, c in sorted(forms.items())}
    dump(tc / 'config/zh-hant/readback-literals.json', {'schema_version': 1, 'literals': literals, 'characters': characters})
    print('readback literals: corpus', len(literals) - extra, 'tool constants', extra, flush=True)
    # Scenario / mode select labels are composed from release-font glyphs at build time (no pixel lock): they
    # follow the Traditional text. The TTF-rendered, mask-locked tutorial titles wait for M4 like other textures.
    comp = json.loads(components.read_text(encoding='utf-8'))
    for key in ('scenario_select_effect', 'mode_select_effect'):
        effect = comp[key]
        effect['composed_labels'] = [literals.get(t) or drafter.text(t) for t in effect['composed_labels']]
        for seg in effect['raster']['segments']:
            text = literals.get(seg['text']) or drafter.text(seg['text'])
            if len(text) != len(seg['text']):
                raise SystemExit(f'{key}: Traditional label changes length: {seg["text"]} -> {text}')
            seg['text'] = text
    # Expected-inventory literals in the component config (translated label lists, ...) are corpus strings:
    # exact matches follow the parallel corpus. Japanese sources, hashes and pixel-locked texture texts stay.
    converted = localize_literals(comp, literals)
    reencode_weapon_categories(comp, tc)
    dump(components, comp)
    print('component config literals mapped to Traditional:', converted, flush=True)
    print('Traditional sources placed:', stats, 'readback literals:', len(literals), flush=True)
    apply_traditional_assets(tc)


def apply_traditional_assets(tc: Path) -> None:
    """Traditional config sections and file overlays (author_textures.py), then every file lock that names a
    changed file. Locks are {"path", "size", "sha256"} objects in config/ and manifests/ JSON; a refreshed lock
    changes its own file, so this repeats until nothing changes."""
    changed = set(OVERLAID)
    sections = ZH_HANT / 'sections.json'
    if sections.exists():
        by_file = {}
        for name, entry in json.loads(sections.read_text(encoding='utf-8')).items():
            rel, key = name.split('#', 1)
            by_file.setdefault(rel, {})[key] = entry['value']
        for rel, values in by_file.items():
            doc = json.loads((tc / rel).read_text(encoding='utf-8'))
            doc.update(values); dump(tc / rel, doc); changed.add(rel)
    overlay = ZH_HANT / 'overlay'
    for f in sorted(overlay.rglob('*')) if overlay.exists() else []:
        if f.is_file():
            rel = str(f.relative_to(overlay)); (tc / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, tc / rel); changed.add(rel)
    from locks import refresh_locks
    refreshed = refresh_locks(tc, changed)
    print('Traditional assets applied:', sorted(changed), 'locks refreshed:', refreshed, flush=True)


def codebook_step(tc: Path, update: bool) -> None:
    cmd = ('python3', 'tools/update_zh_release_font_snapshot.py', '--config', 'config/fonts/zh-release-font.json')
    probe = run(*cmd, cwd=tc, check=False)
    print(probe.stdout.strip(), flush=True)
    if not probe.returncode:
        return
    if 'changes found' not in probe.stdout + probe.stderr:
        raise SystemExit(probe.stdout + probe.stderr)
    if not update:
        raise SystemExit('the Traditional corpus needs characters the Traditional codebook lacks; '
                         'rerun with --update-codebook to append them (config/zh-hant/ changes)')
    run(*cmd, '--apply', cwd=tc)
    shutil.copyfile(tc / 'config/encoding/zh-release-font-assignments.json', ZH_HANT / 'encoding/zh-release-font-assignments.json')
    profile = json.loads((ZH_HANT / 'font-profile.json').read_text(encoding='utf-8'))
    profile['expected'] = json.loads((tc / 'config/fonts/zh-release-font.json').read_text(encoding='utf-8'))['expected']
    dump(ZH_HANT / 'font-profile.json', profile)
    print('Traditional codebook grown and written back to config/zh-hant/', flush=True)


def menu_codebook(tc: Path) -> None:
    """Traditional release-menu codebook: the Simplified non-hanzi rows plus every Traditional hanzi primary row.

    A character with a clean-migration record is listed at its pre-migration code and cell (the writeback maps it
    through the record), every other one at its current code. The composition locks in
    config/full-story-components.json and the menu corpus follow.
    """
    ledger = json.loads((tc / 'config/encoding/zh-release-font-assignments.json').read_text(encoding='utf-8'))
    path = tc / 'config/encoding/release-menu-codebook.json'
    menu = json.loads(path.read_text(encoding='utf-8'))
    # Characters with a clean-migration record are listed at their pre-migration code (the menu writeback and
    # the component checks map them through the record), every other primary row at its current code.
    migrated = {m['character']: m for e in ledger.get('extensions', []) if 'clean_default_width_cjk_primary_migration' in e
                for m in e['clean_default_width_cjk_primary_migration'].get('migrations', [])}
    han = lambda c: '\u3400' <= c <= '\u9fff'
    rows = [dict(item) for item in menu['assignments'] if not han(item['character'])]     # punctuation, ASCII, space
    listed = {r['character'] for r in rows}
    for r in ledger['primary_assignments']:
        if r['character'] in listed or not han(r['character']): continue    # non-hanzi rows: the Simplified list's
        m = migrated.get(r['character'])
        if m and m.get('to_code', '').upper() == r['code'].upper():
            rows.append({'character': r['character'], 'code': m['from_code'], 'glyph_index': m['from_glyph_index']})
        else:
            rows.append({'character': r['character'], 'code': r['code'], 'glyph_index': r['glyph_index']})
    pairs = sorted((r['character'], r['code'], r['glyph_index']) for r in rows)
    digest = hashlib.sha256(json.dumps(pairs, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    menu.update(assignments=rows, assignment_count=len(rows), mapping_sha256=digest)
    dump(path, menu)
    components = tc / 'config/full-story-components.json'
    comp = json.loads(components.read_text(encoding='utf-8'))
    comp['menu_text_release']['codebook'].update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    comp['composition']['release_codebook'].update(menu_assignment_count=len(rows), menu_assignment_mapping_sha256=digest)
    dump(components, comp)
    corpus = tc / 'corpus/zh/menu/release-v0.3.json'                 # the menu corpus quotes the same lock
    doc = json.loads(corpus.read_text(encoding='utf-8'))
    doc['codebook'] = {**comp['menu_text_release']['codebook'], 'required_codebook_id': 'srwz-release-menu-v0.3'}
    dump(corpus, doc)
    print('Traditional menu codebook:', len(rows), 'rows', flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--release-version', default='0.5.1')
    p.add_argument('--skip-sc', action='store_true', help='reuse build/zh-hant/project from an earlier run')
    p.add_argument('--update-codebook', action='store_true')
    p.add_argument('--out', type=Path, default=ROOT / 'build/iso/test/zh-hant-dual-original.iso')
    a = p.parse_args()
    check = run(sys.executable, HERE / 'sync_corpus.py', '--check', check=False)
    if check.returncode:
        raise SystemExit('parallel Traditional corpora are out of sync with the Simplified ones; run '
                         'tools/zh_hant/sync_corpus.py and review build/zh-hant/sync-report.json\n' + check.stdout)
    # Traditional render locks that live in the parallel corpus follow its text (deterministic, a few seconds).
    run(sys.executable, HERE / 'author_intertitles.py')
    sc_iso = BASE / 'project/build/iso/test/integrated-original.iso'
    if not (a.skip_sc and sc_iso.exists()):
        sc_iso = build(clone('project'), a.release_version)
    tc = clone('project-tc')
    prepare_tc(tc)
    from author_textures import stale
    if stale(tc):
        # Traditional textures (atlases, title buttons, headings, ...) are authored in a prepared clone and kept in
        # config/zh-hant; their inputs changed, so author them again and start from a fresh clone.
        run(sys.executable, HERE / 'author_textures.py', '--clone', tc)
        tc = clone('project-tc'); prepare_tc(tc)
    codebook_step(tc, a.update_codebook)
    menu_codebook(tc)
    tc_iso = build(tc, a.release_version)
    if stale_stage_titles(tc_iso):
        # Titles are drawn with the Traditional build's own glyphs: re-author them from the font just built
        # (new characters, changed names or a grown codebook), then build again.
        run(sys.executable, HERE / 'author_stage_titles.py', '--iso', tc_iso)
        tc = clone('project-tc'); prepare_tc(tc); codebook_step(tc, False); menu_codebook(tc)
        tc_iso = build(tc, a.release_version)
        if stale_stage_titles(tc_iso):
            raise SystemExit('stage-title snapshot still stale after re-authoring')
    run(sys.executable, HERE / 'assemble_dual.py', '--sc', sc_iso, '--tc', tc_iso,
        '--tc-codebook', ZH_HANT / 'encoding/zh-release-font-assignments.json', '--out', a.out)
    # The builds' intermediate images are not needed once the disc is assembled; the two integrated
    # single-language images stay for checks.
    for iso in BASE.glob('project*/build/editions/*/project/build/iso/zh-release-full-story/*.iso'):
        iso.unlink()


if __name__ == '__main__':
    main()
