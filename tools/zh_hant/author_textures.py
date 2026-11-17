#!/usr/bin/env python3
"""Author the Traditional versions of text drawn into pixels (textures, title cards, atlases).

Each step renders the Traditional text with the same renderer and font the Simplified build uses and freezes the
result the way the Simplified pipeline freezes its own (snapshots, mask hashes, output locks). The Traditional
results live in the repository:
  config/zh-hant/sections.json   Traditional values of whole config sections (e.g. tutorial_title_effects of
                                 config/full-story-components.json), each with the Simplified section's hash it
                                 was drafted from and a status like the parallel corpus
  config/zh-hant/overlay/<path>  Traditional replacements of whole repository files (render snapshots, ...)
build_dual.py applies both to the Traditional build and refreshes every file lock that names an overlaid file.

Steps run in a prepared Traditional clone (build/zh-hant/project-tc after build_dual.prepare_tc), so the
Traditional corpus is in place. Usage: author_textures.py [STEP ...] [--clone DIR]   (no STEP: all steps)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ZH_HANT = ROOT / 'config/zh-hant'
SECTIONS = ZH_HANT / 'sections.json'
OVERLAY = ZH_HANT / 'overlay'
HAND_DRAWN = ZH_HANT / 'hand-drawn/original.json'
HELP_TITLES = {'按键说明': (142, 205, 75, 20), '项目说明': (108, 227, 75, 19)}
SELECT_HEADING_BANDS = {'plain': (3, 1, 74, 21), 'bold': (2, 24, 77, 23)}
sys.path.insert(0, str(HERE))
from sync_corpus import FROZEN_KEYS, Drafter  # noqa: E402


def sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def dump(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Author:
    def __init__(self, clone: Path):
        self.clone = clone
        self.drafter = Drafter(ZH_HANT / 'bootstrap.json')
        literals = clone / 'config/zh-hant/readback-literals.json'
        self.literals = load_json(literals)['literals'] if literals.exists() else {}
        self.sections = load_json(SECTIONS) if SECTIONS.exists() else {}
        self.report = {}
        self.used = {}

    def text(self, s: str) -> str:
        """A Simplified string's Traditional counterpart: the parallel corpus's when it has one, else a draft."""
        t = self.literals.get(s) or self.drafter.text(s)
        self.used[s] = t
        return t

    def artwork(self, group: str, key: str, text: str, width: int, height: int) -> bytes:
        """Load approved row-major 4-bpp index values from the Traditional source manifest."""
        import base64
        import zlib

        if not hasattr(self, '_artwork'):
            doc = load_json(HAND_DRAWN)
            if doc['schema_version'] != 1:
                raise ValueError(f'Unsupported texture manifest version: {HAND_DRAWN}')
            self._artwork = doc['entries']
        name = f'{group}/{key}'
        entry = self._artwork[name]
        pixels = zlib.decompress(base64.b64decode(entry['indices_zlib_base64'], validate=True))
        if (entry['text'] != text or entry['size'] != [width, height] or len(pixels) != width * height
                or max(pixels) > 15 or hashlib.sha256(pixels).hexdigest() != entry['sha256']):
            raise ValueError(f'Traditional artwork contract changed: {name} ({text}, {width}x{height})')
        return pixels

    def draft(self, value, key=None):
        if isinstance(value, str):
            return value if key in FROZEN_KEYS else self.text(value)
        if isinstance(value, list):
            return [self.draft(v, key) for v in value]
        if isinstance(value, dict):
            return {k: (v if k in FROZEN_KEYS or k.endswith('sha256') else self.draft(v, k)) for k, v in value.items()}
        return value

    def section(self, config_rel: str, key: str) -> dict:
        """The Traditional value of one config section: kept when the Simplified section is unchanged or the
        Traditional one was edited by hand, otherwise drafted from the Simplified section."""
        sc = load_json(ROOT / config_rel)[key]
        name = f'{config_rel}#{key}'
        entry = self.sections.get(name)
        if entry and (entry['zh_hans_sha256'] == sha(sc) or entry.get('zh_hant_status', 'draft') != 'draft'):
            return entry['value']
        entry = {'zh_hans_sha256': sha(sc), 'zh_hant_status': 'draft', 'value': self.draft(sc)}
        self.sections[name] = entry
        return entry['value']

    def save_section(self, config_rel: str, key: str, value: dict) -> None:
        self.sections[f'{config_rel}#{key}']['value'] = value
        dump(SECTIONS, dict(sorted(self.sections.items())))

    # ---- steps ---------------------------------------------------------------------------------------------
    def tutorial(self):
        """Tutorial title cards (VEFF2DX effects 284-287): TTF masks and per-chunk output locks."""
        sys.path.insert(0, str(ROOT / 'tools'))           # repository code, clone data
        from srwz.render_locks import relocking
        from srwz.veff_tutorial_titles import build_veff_tutorial_titles
        rel = 'config/full-story-components.json'
        value = self.section(rel, 'tutorial_title_effects')
        components = load_json(self.clone / rel)
        source = (self.clone / value['original_archive']['path']).read_bytes()
        slps = (self.clone / components['world_map_titles']['original_slps']['path']).read_bytes()
        with relocking() as changed:
            build_veff_tutorial_titles(source, slps, self.clone / value['font']['path'], value)
        build_veff_tutorial_titles(source, slps, self.clone / value['font']['path'], value)   # as a build runs it
        self.save_section(rel, 'tutorial_title_effects', value)
        self.report['tutorial'] = {'relocked': len(changed),
                                   'texts': [p.get('translation') for p in value['pictures']]}


    def tc_corpus(self, rel: str, lock: dict | None = None) -> bytes:
        """Place a Traditional parallel corpus file at its build path in the clone (metadata stripped), update
        the in-memory lock that names it, and return its bytes."""
        from sync_corpus import strip_meta
        doc = strip_meta(load_json(ROOT / rel.replace('corpus/zh/', 'corpus/zh-hant/', 1)))
        dump(self.clone / rel, doc)
        data = (self.clone / rel).read_bytes()
        if lock is not None:
            lock.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        return data

    def world_map(self):
        """World-map place names (MAPMODEL members 81-195): live render, frozen into the render snapshot."""
        sys.path.insert(0, str(ROOT / 'tools'))
        from srwz.world_map_titles import build_world_map_titles
        rel_config = 'config/full-story-components.json'
        ref = self.section(rel_config, 'world_map_titles')
        self.tc_corpus(ref['corpus']['path'], ref['corpus'])
        # Titles whose Traditional text equals the Japanese keep the original art: the counts follow the text.
        entries = load_json(self.clone / ref['corpus']['path'])['entries']
        changed = [e for e in entries if e['source'] != e['translation']]
        ref['expected'].update(translated_unique_title_count=len(changed),
                               translated_member_count=sum(len(e['members']) for e in changed))
        sink: dict = {}
        build_world_map_titles(self.clone, self.clone / 'work', ref, preview_root=self.clone / 'build/zh-hant-author/world-map',
                               live_render=True, render_snapshot_sink=sink)
        rel = ref['render_snapshot']['path']
        dump(OVERLAY / rel, sink)
        self.save_section(rel_config, 'world_map_titles', ref)
        self.report['world_map'] = {'snapshot': rel, 'entries': len(sink.get('entries', []))}

    def library(self):
        """Library menu (NISVDATA chunk 0), sound select title (chunk 1), scenario chart title (HSFC chunk 1):
        live render of the Traditional labels, frozen into their render snapshots."""
        sys.path.insert(0, str(ROOT / 'tools'))
        from srwz.nisv_library_menu import build_hsfc_scenario_chart, build_nisv_library_menu, build_nisv_sound_select
        rel = 'config/library/v0.2.0.json'
        font = self.clone / load_json(self.clone / 'config/full-story-components.json')['runtime_library_menu']['font']['path']
        nisv = (self.clone / 'work/disc/DATA/NISVDATA.BIN').read_bytes()
        hsfc = (self.clone / 'work/disc/DATA/HSFC.BIN').read_bytes()
        done = {}
        for key, builder, archive in (('library_menu_runtime_tim2', build_nisv_library_menu, nisv),
                                      ('sound_select_runtime_tim2', build_nisv_sound_select, nisv),
                                      ('scenario_chart_runtime_tim2', build_hsfc_scenario_chart, hsfc)):
            contract = self.section(rel, key)
            sink: dict = {}
            builder(archive, contract, font_path=font, project_root=self.clone, live_render=True, render_snapshot_sink=sink)
            snap = contract['writeback']['render_snapshot']['path']
            dump(OVERLAY / snap, sink); dump(self.clone / snap, sink)
            data = (self.clone / snap).read_bytes()
            contract['writeback']['render_snapshot'].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            builder(archive, contract, font_path=font, project_root=self.clone)           # as a build runs it
            self.save_section(rel, key, contract)
            done[key] = contract.get('labels')
        self.report['library'] = done

    def _cli_refreeze(self, tool: str, config_rel: str, label: str):
        """Assets whose tool has its own authoring path (--live-render / --refreeze-snapshot): run it in the
        clone on the Traditional corpus, take the rendered expected values, refreeze, then check the frozen build.
        The changed config and snapshot become overlays."""
        import subprocess
        sys.path.insert(0, str(HERE))
        from locks import refresh_locks
        config_path = self.clone / config_rel
        config = load_json(config_path)
        self.tc_corpus(config['corpus']['path'])
        run = lambda *args: subprocess.run(['python3', tool, *args], cwd=self.clone, check=True,
                                           capture_output=True, text=True)
        # Traditional labels can be wider than the Simplified ones in a fixed rectangle: a label that touches
        # the rectangle edge gets its character spacing reduced a step at a time. The result is recorded in
        # config/zh-hant/render-adjustments.json and reapplied on every authoring run.
        adjustments_path = ZH_HANT / 'render-adjustments.json'
        adjustments = load_json(adjustments_path) if adjustments_path.exists() else {}
        mine = adjustments.setdefault(config_rel, {})
        by_id = {l['entry_id']: l for l in config.get('labels', [])}
        for entry_id, render in mine.items():
            by_id[entry_id].setdefault('render', {}).update(render)
        dump(config_path, config)
        for _ in range(40):
            result = subprocess.run(['python3', tool, '--live-render', '--no-enforce-expected', '--force'],
                                    cwd=self.clone, capture_output=True, text=True)
            if result.returncode == 0:
                break
            import re
            m = re.search(r'(\S+) \(.*\): rendered text touches the right rectangle edge', result.stdout + result.stderr)
            if not m:
                raise SystemExit(result.stdout + result.stderr)
            tweak = by_id[m.group(1)].setdefault('render', {})
            tweak['character_spacing'] = float(tweak.get('character_spacing', 0)) - 1.0
            mine[m.group(1)] = {'character_spacing': tweak['character_spacing']}
            dump(config_path, config)
        else:
            raise SystemExit(f'{label}: labels do not fit')
        dump(adjustments_path, adjustments)
        config['expected'] = load_json(self.clone / config['outputs']['report'])['expected']
        dump(config_path, config)
        run('--live-render', '--refreeze-snapshot', '--force')
        snapshot_rel = config['frozen_snapshot']['path']
        refresh_locks(self.clone, [snapshot_rel, config['corpus']['path']])
        run('--force', '--refresh-manifest')                                        # the frozen build
        manifest_rel = config['outputs']['manifest']                                 # checked by the edition build
        for rel in (config_rel, snapshot_rel, manifest_rel):
            dump(OVERLAY / rel, load_json(self.clone / rel))
        self.report[label] = {'overlays': [config_rel, snapshot_rel, manifest_rel]}

    def aid(self):
        """Aid battle prompts (AIDDATA): 10 labels."""
        self._cli_refreeze('tools/build_aid_battle_prompts.py', 'config/assets/aid-battle-prompts-zh.json', 'aid')

    def tricmn(self):
        """TRI/command battle overlays (TRICMN): 51 labels."""
        self._cli_refreeze('tools/build_tricmn_battle_overlays.py', 'config/assets/tricmn-battle-overlays-zh.json', 'tricmn')

    # ---- KVMDATA / KVPDATA (UI atlases and the heading chain) ----------------------------------------------
    def _run(self, *args):
        import subprocess
        result = subprocess.run(['python3', *args], cwd=self.clone, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(f'{args}: {result.stdout[-2000:]}{result.stderr[-2000:]}')
        return result.stdout

    def _keep(self, *rels):
        for rel in rels:
            target = OVERLAY / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((self.clone / rel).read_bytes())

    def atlases(self):
        """The six localized KVMDATA atlases and their suite: live render of the Traditional atlas corpora, frozen
        into Traditional render snapshots; atlas and suite output locks follow (the pipeline's own ratchet)."""
        sys.path.insert(0, str(ROOT / 'tools'))
        sys.path.insert(0, str(HERE))
        from locks import refresh_locks
        from srwz.ui_atlas_localization import build_ui_atlas_localization
        chain = load_json(self.clone / 'config/fonts/zh-font-build-chain.json')
        refs = chain['localized_atlases']
        kept = []
        for ref in refs:
            config = load_json(self.clone / ref)
            sources = set()
            def walk(node):
                if isinstance(node, dict):
                    src = node.get('translation_source')
                    if isinstance(src, dict) and isinstance(src.get('path'), str):
                        sources.add(src['path'])
                    for v in node.values(): walk(v)
                elif isinstance(node, list):
                    for v in node: walk(v)
            walk(config)
            for rel in sorted(sources):
                self.tc_corpus(rel)
            refresh_locks(self.clone, sorted(sources))
            sink: dict = {}
            build_ui_atlas_localization(self.clone, self.clone / 'work', self.clone / ref, enforce_expected=False,
                                        live_render=True, render_snapshot_sink=sink)
            snapshot = load_json(self.clone / ref)['render_snapshot']['path']
            dump(self.clone / snapshot, sink)
            refresh_locks(self.clone, [snapshot])
            config = load_json(self.clone / ref)
            config['expected'] = json.loads(self._run('tools/ui_atlas.py', 'build', '--config', ref, '--print-output-locks'))
            dump(self.clone / ref, config)
            self._run('tools/ui_atlas.py', 'build', '--config', ref, '--force', '--verify-output', '--refresh-manifest')
            kept += [ref, snapshot] + ([config['outputs']['manifest']] if 'manifest' in config.get('outputs', {}) else [])
        suite = chain['atlas_suite']
        self._run('-c', 'import sys; sys.path.insert(0, "tools"); import rebuild_zh_font as r; '
                        f'r._refresh_suite_ratchets({suite!r}, {refs!r})')
        self._run('tools/ui_atlas.py', 'build-suite', '--config', suite, '--force', '--verify-output', '--refresh-manifest')
        suite_config = load_json(self.clone / suite)
        kept.append(suite)
        kept.append(suite_config['outputs']['manifest'])
        self._keep(*kept)
        self.report['atlases'] = {'overlays': kept}

    def kvm_chain(self):
        """The heading chain on top of the Traditional atlas suite (srwz/ui_headings.py order): menu restore
        identities, clarity cells, help titles, battle SELECT glyphs re-drawn in Traditional; heading cells stay
        (every visible one is overwritten by a clarity or help-title cell). Writes the Traditional configs and
        the KVMDATA/KVPDATA output locks."""
        import base64, zlib
        sys.path.insert(0, str(ROOT / 'tools'))
        sys.path.insert(0, str(HERE))
        from locks import refresh_locks
        from srwz.iso9660 import member_map, scan_iso9660
        from srwz.render_locks import relocking
        from srwz import ui_headings as uh, ui_menu_restore as mr, ui_text_clarity as tcl, ui_battle_select as bs
        from srwz.ui_frame_uv import apply_frame_uv_patches
        from srwz.ui_frame_joins import apply_frame_joins, load_join_contract
        c = self.clone
        sha = lambda b: hashlib.sha256(b).hexdigest()
        z = lambda b: base64.b64encode(zlib.compress(b, 9)).decode('ascii')
        unz = lambda t: zlib.decompress(base64.b64decode(t))
        page_pixels = lambda atlas, n: bytes(v for b in atlas[n * 33344 + 64:n * 33344 + 64 + 32768] for v in (b & 15, b >> 4))
        cell_pixels = lambda atlas, n, rect: (lambda px: bytes(px[(rect[1] + r) * 256 + rect[0] + k]
                                                               for r in range(rect[3]) for k in range(rect[2])))(page_pixels(atlas, n))
        hcfg_rel = 'config/assets/ui-headings-zh.json'
        hcfg = load_json(c / hcfg_rel)
        refresh_locks(c, [hcfg['base_atlas']['path']])                     # the Traditional atlas suite output
        hcfg = load_json(c / hcfg_rel)
        suite = (c / hcfg['base_atlas']['path']).read_bytes()
        for chunk in hcfg['texture_chunks']:                               # base pages carry Traditional atlas text
            chunk['sha256'] = sha(suite[chunk['start']:chunk['end']])
        snapshot = json.loads((c / hcfg['snapshot']['path']).read_bytes())
        atlas = uh.apply_index_cells(suite, hcfg, snapshot)
        iso = c / hcfg['source_iso']
        rec = member_map(scan_iso9660(iso))[hcfg['source_drawings']['member']]
        with iso.open('rb') as f:
            f.seek(rec.extent_lba * 2048); drawings = f.read(rec.size)
        drawings = uh.apply_shared_letter_patches(atlas, uh.apply_draw_patches(drawings, hcfg['draw_patches']), hcfg)
        # menu restore: input/output identities of the Traditional atlas
        mr_doc = load_json(c / mr.CONFIG)
        prof = mr_doc['profiles']['original']
        prof['before']['atlas'] = sha(atlas)
        for cell in prof['cells']:                                         # native restores now cover Traditional text
            if cell['kind'] == 'native_restore':
                cell['before_sha256'] = sha(cell_pixels(atlas, cell['page'], cell['rect']))
        for page in prof['pages']:
            n = page['index']; a = n * 33344
            page['container_sha256'] = sha(atlas[a:a + 64] + atlas[a + 64 + 32768:a + 33344])
        with relocking():
            atlas, drawings, _ = mr.apply_menu_restore(atlas, drawings, c, config=prof)
        dump(c / mr.CONFIG, mr_doc)
        # clarity cells: Traditional text, stock clarity style (gray stroke #505050 0.65 px under a white fill)
        texts = {'formation': '阵型', 'select': '选择', 'key': '按键', 'help': '说明', 'item': '项目', 'sort': '排序'}
        cl_doc = load_json(c / tcl.CONFIG)
        for cell in cl_doc['profiles']['original']['cells']:
            x, y, w, h = cell['rect']
            before = cell_pixels(atlas, cell['page'], cell['rect'])
            after = self.artwork('clarity', cell['id'], self.text(texts[cell['id']]), w, h)
            cell.update(before_sha256=sha(before), after_sha256=sha(after), before_zlib_base64=z(before), after_zlib_base64=z(after))
        dump(c / tcl.CONFIG, cl_doc)
        atlas, _ = tcl.apply_atlas(atlas, c)
        drawings, _ = tcl.apply_native_select(drawings, c)
        sel_rel = 'config/assets/ui-select-native.json'
        sel_doc = load_json(c / sel_rel)
        cell = sel_doc['profiles']['original']['atlas_cell']               # native SORT restore covers Traditional pixels
        before = cell_pixels(atlas, cell['page'], cell['rect'])
        cell.update(before_sha256=sha(before), before_zlib_base64=z(before))
        dump(c / sel_rel, sel_doc)
        atlas = tcl.apply_native_title_atlas(atlas, c)
        # help titles: the after-state of the Simplified region with both full titles drawn in Traditional
        ht = load_json(c / mr.HELP_TITLES_CONFIG)
        block = ht['atlas']
        off, size = block['offset'], block['size']
        sc_final = (ROOT / 'work/build/ui-headings-zh/components/KURODATA/KVMDATA.BIN').read_bytes()
        region = bytearray(sc_final[off:off + size])
        page, base = 3, 3 * 33344 + 64
        def put(buf, x, y, value):                                         # one 4-bpp pixel inside the region
            i = (y * 256 + x); o = base + i // 2 - off
            if 0 <= o < size:
                buf[o] = (buf[o] & (0xF0 if i % 2 == 0 else 0x0F)) | (value << (4 * (i % 2)))
        for title in (load_json(SUPPORT_TITLE := c / mr.SUPPORT_TITLE_CONFIG), load_json(c / mr.COMMAND_TITLE_CONFIG)):
            for cell in title['cells']:
                if title.get('page', 3) != page: continue
                x, y, w, h = cell['rect']
                for yy in range(y, y + h):
                    for xx in range(x, x + w): put(region, xx, yy, 0)     # cells written after the help titles
        for text, (x, y, w, h) in HELP_TITLES.items():
            pixels = self.artwork('help', text, self.text(text), w, h)
            for r in range(h):
                for k in range(w): put(region, x + k, y + r, pixels[r * w + k])
        before = atlas[off:off + size]
        block.update(before_sha256=sha(before), after_sha256=sha(bytes(region)),
                     xor_zlib_base64=z(bytes(a ^ b for a, b in zip(before, region))))
        dump(c / mr.HELP_TITLES_CONFIG, ht)
        atlas, drawings, _ = mr.apply_help_titles(atlas, drawings, c)
        atlas, drawings, _ = mr.apply_support_title(atlas, drawings, c)
        atlas, drawings, _ = mr.apply_command_title(atlas, drawings, c)
        # battle SELECT glyphs (page 9): Traditional characters where they differ
        bs_doc = load_json(c / bs.CONFIG)
        for ch, cell in zip('排选择阵型队员机体列师', bs_doc['cells']):
            tc = self.text(ch)
            if tc == ch: continue
            x, y, w, h = cell['rect']
            tile = self.artwork('battle-select', ch, tc, w, h)
            cell.update(sha256=sha(tile), indices_zlib_base64=z(tile), zh_hant_character=tc)
        dump(c / bs.CONFIG, bs_doc)
        atlas = bs.apply_atlas(atlas, bs_doc)
        drawings, _ = apply_frame_uv_patches(drawings, hcfg['shared_frame_uv'])
        drawings, _ = apply_frame_joins(drawings, load_join_contract(c, 'original'))
        outputs = {'KURODATA/KVMDATA.BIN': atlas, hcfg['source_drawings']['member']: drawings}
        hcfg['expected_outputs'] = {name: {'size': len(b), 'sha256': sha(b)} for name, b in outputs.items()}
        dump(c / hcfg_rel, hcfg)
        refresh_locks(c, [hcfg_rel, mr.CONFIG, tcl.CONFIG, mr.HELP_TITLES_CONFIG, bs.CONFIG, sel_rel])
        self._run('tools/build_ui_headings.py', '--refresh-manifest')
        built = {name: (c / hcfg['output_root'] / name).read_bytes() for name in outputs}
        if built != outputs:
            raise SystemExit('heading build differs from the authored chain')
        refresh_locks(c, [f"{hcfg['output_root']}/{name}" for name in outputs])
        components = load_json(c / 'config/full-story-components.json')
        for key in ('kvmdata', 'kvpdata'):
            self.section('config/full-story-components.json', key)
            self.save_section('config/full-story-components.json', key, components[key])
        self._keep(hcfg_rel, mr.CONFIG, tcl.CONFIG, mr.HELP_TITLES_CONFIG, bs.CONFIG, sel_rel, hcfg['manifest'])
        self.report['kvm_chain'] = {'kvmdata_sha256': sha(atlas), 'kvpdata_sha256': sha(drawings)}

    def title_menu(self):
        """Title-menu buttons (VT1 chunk 6): four frozen 128x32 Traditional masks and their output locks."""
        import base64, zlib
        sys.path.insert(0, str(ROOT / 'tools'))
        sys.path.insert(0, str(HERE))
        from srwz.codec import decode
        from srwz.title_menu import build_title_menu
        from srwz.render_locks import relocking
        rel = 'config/assets/title-menu-zh.json'
        doc = load_json(ROOT / rel)                                         # Simplified labels and contract
        for label, mask in zip(doc['labels'], doc['masks']):
            label['translation'] = self.text(label['translation'])
            indices = self.artwork('title-menu', label['source'], label['translation'], 128, 32)
            pixels = bytes(v * 17 for v in indices)
            mask.update(size=len(pixels), sha256=hashlib.sha256(pixels).hexdigest(),
                        zlib_base64=base64.b64encode(zlib.compress(pixels, 9)).decode('ascii'))
        # the localized index plane: run the writer once on the original chunk to read its output identity
        import struct
        sys.path.insert(0, str(HERE))
        from assemble_dual import Disc
        from srwz.iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
        disc = Disc(self.clone / 'rom/original.iso')
        exe, vt1 = disc.read('SLPS_258.87'), disc.read('DATA/VT1.BIN')
        offsets = read_executable_archive_offsets(exe, CORE_ARCHIVE_SPECS['VT1.BIN'], len(vt1))
        chunk = decode(vt1[offsets[6]:offsets[7]]).output
        from srwz.title_menu import apply_title_menu_masks, extract_vt1_title_indexes, _thaw_mask
        from srwz.tim2 import scan_tim2
        record = scan_tim2(chunk)[doc['target']['record_index']]
        source = extract_vt1_title_indexes(chunk[record.offset:record.end])
        edited, _ = apply_title_menu_masks(source, tuple(_thaw_mask(m) for m in doc['masks']))
        doc['target']['output_indexes_sha256'] = hashlib.sha256(edited).hexdigest()
        doc['target']['expected_changed_pixel_count'] = sum(a != b for a, b in zip(source, edited))
        dump(self.clone / rel, doc)
        build_title_menu(chunk, doc)                                        # as the build runs it
        self._keep(rel)
        self.report['title_menu'] = [l['translation'] for l in doc['labels']]

    def select_headings(self):
        import base64, zlib
        sys.path.insert(0, str(HERE))
        rel = 'config/full-story-components.json'
        for key in ('scenario_select_effect', 'mode_select_effect'):
            value = self.section(rel, key)
            heading = value['select_heading']
            sc = load_json(ROOT / rel)[key]['select_heading']
            pixels = bytearray(zlib.decompress(base64.b64decode(sc['indices_zlib_base64'])))
            for band, (x, y, w, h) in SELECT_HEADING_BANDS.items():
                cell = self.artwork('opening', f'{key}/{band}', heading['text'], w, h)
                for r in range(h):
                    pixels[(y + r) * 256 + x:(y + r) * 256 + x + w] = cell[r * w:(r + 1) * w]
            heading.update(after_sha256=hashlib.sha256(bytes(pixels)).hexdigest(),
                           indices_zlib_base64=base64.b64encode(zlib.compress(bytes(pixels), 9)).decode('ascii'))
            self.save_section(rel, key, value)
        self.report['select_headings'] = [self.sections[f'{rel}#{k}']['value']['select_heading']['text']
                                          for k in ('scenario_select_effect', 'mode_select_effect')]

    def event_subtitles(self):
        """Event-movie captions (rendered from text and the caption TTF at build time): Traditional chinese_draft;
        every other caption field stays as in the Simplified file."""
        out = []
        for rel in ('config/products/special-disc/event-subtitles.json', 'config/event-subtitles/main-only-captions.json'):
            sc = load_json(ROOT / rel)['captions']
            value = self.section(rel, 'captions')
            for tc_caption, sc_caption in zip(value, sc):
                for k in sc_caption:
                    if k != 'chinese_draft':
                        tc_caption[k] = sc_caption[k]
            self.save_section(rel, 'captions', value)
            out += [c['chinese_draft'] for c in value]
        self.report['event_subtitles'] = {'captions': len(out), 'examples': out[:3]}


# Inputs the authored files derive from (besides the texts looked up, recorded with their Traditional values).
FINGERPRINT_FILES = ['tools/zh_hant/author_textures.py', 'config/zh-hant/bootstrap.json',
                     'config/zh-hant/render-adjustments.json', 'config/library/v0.2.0.json',
                     'config/assets/aid-battle-prompts-zh.json', 'config/assets/tricmn-battle-overlays-zh.json',
                     'config/assets/ui-atlas-suite-zh.json', 'config/assets/ui-headings-zh.json',
                     'config/assets/ui-menu-native-restore.json', 'config/assets/ui-text-clarity.json',
                     'config/assets/ui-help-titles-zh.json', 'config/assets/ui-battle-select-titles-zh.json',
                     'config/assets/ui-select-native.json', 'config/assets/title-menu-zh.json',
                     'config/world-map-title-render-snapshot.json', 'config/products/special-disc/event-subtitles.json',
                     'config/event-subtitles/main-only-captions.json']
FINGERPRINT_GLOBS = ['config/zh-hant/hand-drawn/*.json', 'config/assets/ui-*-atlas-zh.json', 'corpus/zh-hant/ui-atlas/*.json', 'corpus/zh-hant/menu/stage-names.json']
FINGERPRINT = ZH_HANT / 'author-fingerprint.json'


def current_fingerprint(clone: Path, recorded_texts: dict | None = None) -> dict:
    files = sorted(set(FINGERPRINT_FILES) | {str(p.relative_to(ROOT)) for g in FINGERPRINT_GLOBS for p in ROOT.glob(g)})
    author = Author(clone)
    texts = {s: author.text(s) for s in (recorded_texts or {})}
    return {'files': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files if (ROOT / f).is_file()},
            'texts': texts}


def stale(clone: Path) -> bool:
    """True when the authored Traditional textures no longer match their inputs (author_textures.py reruns)."""
    if not FINGERPRINT.exists():
        return True
    recorded = load_json(FINGERPRINT)
    return current_fingerprint(clone, recorded.get('texts')) != recorded


STEPS = ['tutorial', 'world_map', 'library', 'aid', 'tricmn', 'atlases', 'kvm_chain', 'title_menu', 'select_headings',
         'event_subtitles']


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('steps', nargs='*', choices=STEPS + [[]], default=[])
    p.add_argument('--clone', type=Path, default=ROOT / 'build/zh-hant/project-tc')
    a = p.parse_args()
    author = Author(a.clone)
    for step in a.steps or STEPS:
        getattr(author, step)()
    if not a.steps:                                       # a complete run: record what it was authored from
        dump(FINGERPRINT, {**current_fingerprint(a.clone, author.used), 'texts': dict(sorted(author.used.items()))})
    print(json.dumps(author.report, ensure_ascii=False))


if __name__ == '__main__':
    main()
