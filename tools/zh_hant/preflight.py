#!/usr/bin/env python3
"""Check the Taiwan and Hong Kong text against every known build gate before a build, and list all findings at once.

A build stops at its first failing gate and each attempt takes minutes; an edit across the regional corpora (a name
change, a terminology sweep) can trip a dozen different gates. This runs the static part of those gates over both
regions in one pass:

  codebook        characters the Traditional codebook (config/zh-hant/encoding) has no code for
  word-lists      unbreakable-word lists: one-character, multi-line or repeated words
  story-layout    main-game story dialogue: 21x3 cells, map-box width, no break inside a listed word
  prose           stage overviews (main_flow), world-history summaries (main_scroll), SP synopses (sp_flow, 11 rows)
  pictures        text whose pixels are frozen: stage titles (Traditional snapshot), world-map titles (vs --baseline)
  demo-titles     auto-demo work titles must equal the unit-list work names
  length-bound    SP tutorial / Q&A pages: each string keeps the Simplified length
  doubled         a rename applied twice (墮天翅族族: the old name was a prefix of the new one)
  separators      halfwidth ･ (no glyph) or ・ in name lists
  stale (warning) entries whose Simplified entry changed since they were written (sync_corpus.stale_entries)
  slots (warning) fixed-capacity strings (menus, UI tables, unit / pilot / squad names, runtime keywords) that grew
                  past both the Simplified string and the --baseline regional string: may overflow their slot

Errors exit 1; warnings are listed for review (the slot check is a byte-length estimate, the build decides).
Report: build/zh-hant/preflight-report.json.

Usage: preflight.py [--region tw|hk] [--baseline GIT_REF (default HEAD)] [--skip-layout]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
import os
DATA = Path(os.environ.get('SRWZ_PREFLIGHT_ROOT') or ROOT)   # where the text is read from (tests point it at a copy)
sys.path[:0] = [str(HERE), str(ROOT / 'tools'), str(ROOT / 'tools/text_layout')]
import regional_terms as rt  # noqa: E402
import sync_corpus as sc_mod  # noqa: E402

REGIONS = {'tw': '', 'hk': '-hk'}
KANA = re.compile('[ぁ-ヺｦ-ﾟ]')
LAYOUT = ('zh-story-unbroken-words.json', 'zh-flow-scroll-words.json', 'zh-prose-extra-words.json')
SLOT_DIRS = ('menu', 'display-names', 'special-disc')
SLOT_FILES_EXCLUDED = {'menu/stage-overviews.json', 'menu/hsfc-overviews.json', 'menu/nisv-strategy-qa.json',
                       'special-disc/story-dialogue.json', 'special-disc/challenge-dialogue.json',
                       'special-disc/battle-lines.json', 'special-disc/frame-text.json',
                       'special-disc/instructions-overrides.json', 'special-disc/event-gallery-talk.json'}
CACHE = ROOT / 'work/cache/zh-hant-preflight'
LAST_GOOD = ROOT / 'work/cache/zh-hant-preflight/last-good-slots.json'   # sizes a finished build accepted
# string paths a build encodes: translations, the UI tables keyed by offset or Japanese, unit lists, word lists
ENCODED = re.compile(r'/(translation|translations(\[\d+\])?|work|common_words\[\d+\]|proper_names\[\d+\])$'
                     r'|_by_(offset|source_text)/[^/]+$')


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def git_json(ref: str, rel: str):
    out = subprocess.run(['git', 'show', f'{ref}:{rel}'], cwd=ROOT, capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 else None


def strings(doc, path='', frozen=frozenset()):
    """(path, text) for every string value; entries with an id are addressed by id."""
    if isinstance(doc, str):
        yield path, doc
    elif isinstance(doc, dict):
        base = f"{path}#{doc['id']}" if isinstance(doc.get('id'), str) else path
        for k, v in doc.items():
            if k in frozen or k.endswith('_sha256') or k in ('zh_hans_sha256', 'zh_hant_status', 'zh_hant_meta'):
                continue
            yield from strings(v, f'{base}/{k}', frozen)
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            key = v['id'] if isinstance(v, dict) and isinstance(v.get('id'), str) else str(i)
            yield from strings(v, f'{path}[{key}]' if not (isinstance(v, dict) and 'id' in v) else path, frozen)


def encoded_size(text: str) -> int:
    from srwz.text import normalize_original_fullwidth_ascii
    # the release text is stored two bytes per character, Latin letters and digits included (MMI-GAU2 needs 16)
    t = normalize_original_fullwidth_ascii(text)
    return 2 * len(t.replace('\n', '')) + t.count('\n') + 1


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, level, check, region, where, message):
        self.items.append(dict(level=level, check=check, region=region, where=where, message=message))

    def count(self, level):
        return sum(1 for i in self.items if i['level'] == level)


def layout_dir(region: str) -> Path:
    """config/text-layout with the region's Traditional word lists over it (what a regional view builds with)."""
    tmp = Path(tempfile.mkdtemp(prefix='zh-hant-preflight-'))
    for f in (DATA / 'config/text-layout').glob('*'):
        if f.is_file():
            shutil.copy(f, tmp / f.name)
    for f in (DATA / f'config/zh-hant/text-layout{REGIONS[region]}').glob('*.json'):
        doc = load(f)
        seen = set()
        for field in ('common_words', 'proper_names'):       # malformed words are reported by check_word_lists
            if isinstance(doc.get(field), list):
                doc[field] = [w for w in doc[field] if isinstance(w, str) and len(w) > 1 and '\n' not in w
                              and not (w in seen or seen.add(w))]
        (tmp / f.name).write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return tmp


# ---------------------------------------------------------------------------------------------------- checks

def check_codebook(rep: Report, region: str):
    from srwz.text import normalize_original_fullwidth_ascii
    led = load(DATA / 'config/zh-hant/encoding/zh-release-font-assignments.json')
    known = set()
    for key in ('primary_assignments', 'surface_alias_assignments', 'source_compatibility_assignments'):
        known.update(r['character'] for r in led.get(key, []))
    for ext in led.get('extensions', []):
        known.update(r['character'] for r in ext.get('assignments', []))
    frozen = sc_mod.FROZEN_KEYS | sc_mod.SP_FROZEN | {'review_notes', 'reason', 'baseline_translation', 'source_text'}
    missing: dict[str, str] = {}
    suffix = REGIONS[region]
    roots = [DATA / f'corpus/zh-hant{suffix}', DATA / f'corpus/runtime-zh-hant{suffix}',
             DATA / f'config/zh-hant/text-layout{suffix}']
    for root in roots:
        for f in sorted(root.rglob('*.json')):
            for where, text in strings(load(f), str(f.relative_to(DATA)), frozenset(frozen)):
                if KANA.search(text) or not ENCODED.search(where) or '/ui-atlas/' in where:   # ui-atlas: pictures
                    continue
                text = normalize_original_fullwidth_ascii(sc_mod.TM_SCOPE.sub('', text))     # <tm> keeps Japanese
                for c in text:
                    if ord(c) < 0x80 or c in known or c in '\n　':
                        continue
                    missing.setdefault(c, where)
    for c, where in sorted(missing.items()):
        rep.add('error', 'codebook', region, where,
                f'{c} (U+{ord(c):04X}) has no Traditional code: extend the codebook (README: codebook) or change the text')


def check_word_lists(rep: Report, region: str):
    lay = DATA / f'config/zh-hant/text-layout{REGIONS[region]}'
    for name in LAYOUT:
        doc = load(lay / name)
        seen: dict[str, str] = {}
        for field in ('common_words', 'proper_names'):
            for w in doc.get(field, []):
                where = f'{lay.relative_to(DATA)}/{name}#{field}'
                if not isinstance(w, str) or len(w) < 2 or '\n' in w:
                    rep.add('error', 'word-lists', region, where, f'malformed word {w!r} (one character or multi-line)')
                elif w in seen:
                    rep.add('error', 'word-lists', region, where, f'{w} listed twice ({seen[w]} and {field})')
                else:
                    seen[w] = field


def cached(key_parts: list, compute):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps(key_parts, ensure_ascii=False).encode()).hexdigest()
    path = CACHE / f'{key}.json'
    if path.exists():
        return load(path)
    value = compute()
    path.write_text(json.dumps(value, ensure_ascii=False))
    return value


def check_story_layout(rep: Report, region: str):
    from rebalance_story_dialogue import keyword_link_ids
    from srwz.build_layout import dialogue_scene, stored_geometry_issues
    from srwz.chinese_layout import dialogue_layout_issues, load_layout_profiles
    tmp = layout_dir(region)
    words = [(tmp / n).read_text(encoding='utf-8') for n in sorted(p.name for p in tmp.glob('*.json'))]
    profile = load_layout_profiles(tmp / 'zh-layout-profiles.json')['story_dialogue']
    links = keyword_link_ids()
    tools_sig = [(ROOT / p).read_bytes().hex()[:0] + hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                 for p in ('tools/srwz/build_layout.py', 'tools/srwz/chinese_layout.py', 'shared/text-layout/cli.mjs')]
    for path in sorted((DATA / f'corpus/zh-hant{REGIONS[region]}/story-dialogue').glob('stage-*.json')):
        text = path.read_text(encoding='utf-8')

        def compute():
            entries = json.loads(text)['entries']; geo = {}; out = []
            for scene in ('story', 'story_map'):
                geo.update(stored_geometry_issues([(e['id'], e['translation'], e['id'] in links) for e in entries
                                                   if dialogue_scene(e['id']) == scene], scene))
            for e in entries:
                issues = list(dialogue_layout_issues(e['translation'], profile=profile, stage_keyword_links=e['id'] in links,
                                                     check_width=False)) + list(geo.get(e['id'], ()))
                if issues:
                    out.append([e['id'], issues])
            return out
        for entry_id, issues in cached(['story', text, words, tools_sig, sorted(links)], compute):
            rep.add('error', 'story-layout', region, f'{path.relative_to(DATA)}#{entry_id}',
                    '; '.join(issues) + ' (fix: re-break the record, e.g. the shared JS layout with protectedTerms)')
    shutil.rmtree(tmp, ignore_errors=True)


def check_prose(rep: Report, region: str):
    from srwz.build_layout import PROSE_HANGING_PX, prose_widths
    from srwz.text import normalize_original_fullwidth_ascii
    suffix = REGIONS[region]
    flow = load(DATA / 'config/products/special-disc/flow-layout.json')

    def measure(rows, scene):
        bad = []
        for identity, text, max_rows in rows:
            try:
                prose_widths([(identity, text, max_rows)], scene, hanging_px=PROSE_HANGING_PX)
            except ValueError as error:
                bad.append([identity, str(error)])
        return bad
    jobs = []
    ov = DATA / f'corpus/zh-hant{suffix}/menu/stage-overviews.json'
    jobs.append((ov, 'main_flow', [(e['id'], e['translation'].rstrip('\n'), None) for e in load(ov)['entries']
                                   if isinstance(e.get('translation'), str) and e['translation']]))
    summ = DATA / f'corpus/zh-hant{suffix}/summary.json'
    if summ.exists():
        rows = [(i, t, None) for i, t in strings(load(summ)) if '/translation' in i and t]
        jobs.append((summ, 'main_scroll', rows))
    fr = DATA / f'corpus/zh-hant{suffix}/special-disc/frame-text.json'
    jobs.append((fr, 'sp_flow', [(e['id'], normalize_original_fullwidth_ascii(e['translation']).replace(' ', '　'),
                                  flow['maximum_lines']) for e in load(fr)['entries']
                                 if str(e.get('id', '')).startswith('synopsis/') and isinstance(e.get('translation'), str)]))
    tools_sig = hashlib.sha256((ROOT / 'shared/text-layout/cli.mjs').read_bytes()).hexdigest()
    for path, scene, rows in jobs:
        for identity, message in cached(['prose', scene, rows, tools_sig], lambda: measure(rows, scene)):
            rep.add('error', 'prose', region, f'{path.relative_to(DATA)}#{identity}',
                    f'{message} (fix: re-break the paragraph; wording unchanged)')


def check_pictures(rep: Report, region: str, baseline: str):
    suffix = REGIONS[region]
    snap = load(DATA / 'config/zh-hant/stage-title-graphics-indexed-snapshot.json')['titles']
    names = {}
    for f in (DATA / f'corpus/zh-hant{suffix}/menu').glob('*.json'):
        for where, text in strings(load(f), f.name):
            m = re.search(r'#(menu/Compdata/03/\d{4})/translation$', where)
            if m:
                names[m.group(1)] = text
    for t in snap:
        text = names.get(t['entry_id'])
        if text is not None and text != t['text'] and region == 'tw':
            rep.add('error', 'pictures', region, t['entry_id'],
                    f'stage title {text!r} differs from its frozen picture {t["text"]!r}: keep the text or re-author the picture')
    # world-map titles are drawn from the Taiwan text in both variants (shared MAPMODEL): compare the Taiwan file
    # with the frozen render (config/zh-hant/overlay, author_textures.py world_map)
    if region != 'tw':
        return
    rel = 'corpus/zh-hant/ui-atlas/world-map-titles-v1.json'
    drawn = {e['id']: e['translation'] for e in load(DATA / 'config/zh-hant/overlay/config/world-map-title-render-snapshot.json')['entries']}
    for e in load(DATA / rel)['entries']:
        if e['id'] in drawn and drawn[e['id']] != e['translation']:
            rep.add('error', 'pictures', region, e['id'],
                    f'world-map title {e["translation"]!r} differs from its frozen render {drawn[e["id"]]!r}: '
                    'keep the text or re-author it (build_dual.py --author-textures)')


def check_demo_titles(rep: Report, region: str):
    suffix = REGIONS[region]
    units = load(DATA / f'corpus/zh-hant{suffix}/display-names/units-full.json')['segments']
    for e in load(DATA / f'corpus/zh-hant{suffix}/auto-demo-work-titles.json').get('entries', []):
        src = e.get('translation_source') or ''
        if src.startswith('units-full:segment/'):
            want = units[int(src.rsplit('/', 1)[1])]['work']
            if e.get('translation') != want:
                rep.add('error', 'demo-titles', region, e.get('id'),
                        f'{e.get("translation")!r} must equal the unit-list work name {want!r}')


def check_length_bound(rep: Report, region: str):
    suffix = REGIONS[region]
    for rel_tc in json.loads((DATA / 'config/zh-hant/regional-terms.json').read_text(encoding='utf-8')).get('length_bound_files', {}):
        name = rel_tc.split('/', 2)[2]
        tc_doc = load(DATA / f'corpus/zh-hant{suffix}/{name}'); sc_doc = load(DATA / f'corpus/zh/{name}')
        sc = dict(strings(sc_doc, name, frozenset(sc_mod.FROZEN_KEYS | sc_mod.SP_FROZEN)))
        for where, text in strings(tc_doc, name, frozenset(sc_mod.FROZEN_KEYS | sc_mod.SP_FROZEN)):
            if 'instructions' not in name and '/qa/' not in where:
                continue
            base = sc.get(where)
            if base is not None and not KANA.search(text) and len(base) != len(text):
                rep.add('error', 'length-bound', region, where,
                        f'{len(text)} characters, Simplified {len(base)}: this page is cut at the Simplified lengths')


def check_doubled(rep: Report, region: str):
    rows = load(DATA / 'config/zh-hant/regional-names.json')['names']
    pats = set()
    for r in rows:
        to = r[region]['to']
        for f in r[region]['from']:
            if r[region]['apply'] and f and to.startswith(f) and to != f:
                pats.add(to + to[len(f):])
    if not pats:
        return
    rx = re.compile('|'.join(map(re.escape, sorted(pats, key=len, reverse=True))))
    for root in (DATA / f'corpus/zh-hant{REGIONS[region]}', DATA / f'corpus/glossary-zh-hant{REGIONS[region]}'):
        for f in sorted(root.rglob('*.json')):
            for m in rx.finditer(f.read_text(encoding='utf-8')):
                rep.add('error', 'doubled', region, str(f.relative_to(DATA)), f'{m.group(0)}: a rename applied twice')


def check_separators(rep: Report, region: str):
    suffix = REGIONS[region]
    for root in (DATA / f'corpus/zh-hant{suffix}', DATA / f'corpus/glossary-zh-hant{suffix}',
                 DATA / f'config/zh-hant/text-layout{suffix}'):
        for f in sorted(root.rglob('*.json')):
            text = f.read_text(encoding='utf-8')
            if '･' in text:
                rep.add('error', 'separators', region, str(f.relative_to(DATA)), f'halfwidth ･ ×{text.count("･")}: write ·')
    names = DATA / f'corpus/zh-hant{suffix}/display-names/units-full.json'
    for where, text in strings(load(names), str(names.relative_to(DATA))):
        if '・' in text:
            rep.add('error', 'separators', region, where, f'{text}: unit names use ·')


def japanese_for(where: str):
    """The Japanese source of a string path: a table keyed by the Japanese, or an entry's source hash / id."""
    m = re.search(r'_by_source_text/([^/]+)$', where)
    if m:
        return m.group(1)
    m = re.search(r'#([^/]+(?:/[^/]+)*?)/translation$', where)
    if m:
        by_sha, by_id = rt.japanese()
        return by_id.get(m.group(1)) or _SHA.get(m.group(1))
    return None


_SHA: dict = {}
SIZES: dict = {}
GOOD: dict = json.loads(LAST_GOOD.read_text()) if LAST_GOOD.exists() else {}


def check_stale(rep: Report, region: str):
    for e in sc_mod.stale_entries(region):
        rep.add('warning', 'stale', region, f"{e['file']}#{e['id']}",
                'the Simplified entry changed since this one was written: carry the change over '
                '(tools/zh_hant/port_sc_changes.py)')


def check_tool_literals(rep: Report, region: str):
    """Build-tool constants need each language's own text (config/zh-hant/tool-literals, tool_literals.py)."""
    sys.path.insert(0, str(ROOT / 'tools/zh_hant'))
    import build_dual as bd
    import tool_literals
    if DATA != ROOT:                        # a test copy: the regional constant files are checked against it
        tool_literals.STORE = DATA / 'config/zh-hant/tool-literals'
    literals, ambiguous = tool_literals.corpus_counterparts(region, DATA)
    for c in tool_literals.missing(region, literals, ambiguous):
        rep.add('error', 'tool-literals', region, c, 'build-tool constant has no regional text (tools/zh_hant/tool_literals.py draft)')


def check_sp_configs(rep: Report, region: str):
    store = DATA / 'config/zh-hant/sp-configs'
    known = load(store / 'sources.json') if (store / 'sources.json').exists() else {}
    for key, digest in known.items():
        variant, rel = key.split('/', 1)
        if variant != region:
            continue
        if not (store / key).exists():
            rep.add('error', 'sp-configs', region, rel, 'regional SP config copy missing (tools/zh_hant/sp_configs.py draft)')
        elif hashlib.sha256((DATA / rel).read_bytes()).hexdigest() != digest:
            rep.add('error', 'sp-configs', region, rel,
                    f'Simplified changed since the regional copy: update config/zh-hant/sp-configs/{key} and run '
                    f'sp_configs.py accept {rel} (or sp_configs.py draft {rel})')


def check_slots(rep: Report, region: str, baseline: str):
    suffix = REGIONS[region]
    frozen = frozenset(sc_mod.FROZEN_KEYS | sc_mod.SP_FROZEN | {'review_notes', 'baseline_translation'})
    files = []
    for d in SLOT_DIRS:
        for f in sorted((DATA / f'corpus/zh-hant{suffix}/{d}').glob('*.json')):
            rel = f'{d}/{f.name}'
            if rel not in SLOT_FILES_EXCLUDED:
                files.append((f'corpus/zh-hant{suffix}/{rel}', f'corpus/zh/{rel}'))
    files.append((f'corpus/runtime-zh-hant{suffix}/stage-keywords-v1.json', 'corpus/runtime/stage-keywords-v1.json'))
    files.append((f'corpus/zh-hant{suffix}/auto-demo-work-titles.json', 'corpus/zh/auto-demo-work-titles.json'))
    by_sha, _ = rt.japanese()
    for rel, sc_rel in files:
        if not (DATA / sc_rel).exists():
            continue
        def index(o):
            if isinstance(o, dict):
                if isinstance(o.get('id'), str):
                    inline = next((o[k] for k in ('source', 'source_text') if isinstance(o.get(k), str) and KANA.search(o[k])), None)
                    if inline or o.get('source_text_sha256') in by_sha:
                        _SHA[o['id']] = inline or by_sha[o['source_text_sha256']]
                for v in o.values(): index(v)
            elif isinstance(o, list):
                for v in o: index(v)
        index(load(DATA / sc_rel))
        cur = dict(strings(load(DATA / rel), '', frozen))
        sc = dict(strings(load(DATA / sc_rel), '', frozen))
        old_doc = git_json(baseline, rel)
        old = dict(strings(old_doc, '', frozen)) if old_doc is not None else {}
        for where, text in cur.items():
            if KANA.search(text) or where not in sc or not ENCODED.search(where):
                continue
            size = encoded_size(text)
            jp = japanese_for(where)
            key = f'{rel}{where}'
            SIZES[key] = size
            limit = max(encoded_size(sc[where]), encoded_size(old[where]) if where in old else 0,
                        len(jp.encode('cp932', 'replace')) + 1 if jp else 0, GOOD.get(key, 0))
            if size > limit:
                rep.add('warning', 'slots', region, f'{rel}{where}',
                        f'{text!r}: {size} bytes, Simplified {encoded_size(sc[where])}'
                        + (f', previous {encoded_size(old[where])}' if where in old else '')
                        + ' - may not fit a fixed slot')


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--region', choices=sorted(REGIONS), action='append')
    p.add_argument('--baseline', default='HEAD')
    p.add_argument('--record', action='store_true', help='after a successful build: accept the current slot sizes')
    p.add_argument('--skip-layout', action='store_true', help='skip the measured layout checks (story, prose)')
    a = p.parse_args()
    rep = Report()
    for region in a.region or sorted(REGIONS, reverse=True):
        checks = [check_stale, check_sp_configs, check_tool_literals, check_codebook, check_word_lists, check_demo_titles, check_length_bound, check_doubled, check_separators]
        for check in checks:
            check(rep, region)
        check_pictures(rep, region, a.baseline)
        check_slots(rep, region, a.baseline)
        if not a.skip_layout:
            check_story_layout(rep, region)
            check_prose(rep, region)
    if a.record:
        LAST_GOOD.parent.mkdir(parents=True, exist_ok=True)
        LAST_GOOD.write_text(json.dumps({**GOOD, **SIZES}, ensure_ascii=False) + '\n')
        print('preflight: slot sizes recorded as built:', len(SIZES))
        return 0
    out = ROOT / 'build/zh-hant/preflight-report.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.items, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    by = {}
    for i in rep.items:
        by.setdefault((i['level'], i['check'], i['region']), []).append(i)
    for (level, check, region), items in sorted(by.items()):
        print(f'{level} {check} [{region}] {len(items)}')
        for i in items[:12]:
            print(f'    {i["where"]}: {i["message"]}')
        if len(items) > 12:
            print(f'    ... {len(items) - 12} more in {out.relative_to(ROOT)}')
    print(f'preflight: {rep.count("error")} errors, {rep.count("warning")} warnings ({out.relative_to(ROOT)})')
    return 1 if rep.count('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
