#!/usr/bin/env python3
"""Read-only Original/BEST miscellaneous-text export, excluding BGM titles."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

from export_explanatory_text import Export, ROOT, sha, write_json
from srwz.auto_demo import discover_auto_demo_name_slots
from srwz.codec import decode_production
from srwz.display_names import parse_display_names, load_full_unit_name_corpus
from srwz.iso9660 import member_map, scan_iso9660
from srwz.menu import parse_menu_file
from srwz.nisv_tutorial import parse_nisv_tutorial_pages
from srwz.text import load_text_table
from srwz.ui_name_tables import name_slots
from srwz.weapon_special_effects import _read_builder_chunk

EDITIONS = ('original', 'best')
CATEGORIES = dict(zip(
    ['01-system', '02-opening', '03-management', '04-formation-search',
     '05-tactical', '06-parameters', '07-spirit', '08-abilities', '09-bonuses',
     '10-parts', '11-bazaar', '12-results', '13-common-help', '14-library-navigation',
     'A1-pilot-names', 'A2-unit-names', 'A3-weapon-names', 'A4-squad-suggestions',
     'A5-default-squads', 'A6-demo-names', 'A7-work-titles', 'B1-map-names',
     'B2-terrain-names', 'C1-tutorial', 'D1-ui-images', 'D2-battle-images', 'D3-map-images'],
    ['系统、设置与存读档', '开局选择与命名', '整备与养成操作', '小队编成与搜索',
     '地图与战术指令', '能力、属性与状态字段', '精神指令', '特殊技能、能力与武器效果',
     '队长效果与小队奖励', '强化零件', '交易所与商品介绍', '结算、奖励与成长通知',
     '按键帮助与共通提示', '资料库与音乐选择操作', '人物显示名', '机体与母舰名',
     '武器名称', '小队名称建议', '默认小队名称', '待机演示名称', '参战作品标题',
     '地图名称', '地形名称', '教程页面', '界面图片文字', '战斗界面图片文字', '世界地图图片标题']))

SECTION_CATEGORY = {
    'Name Screen': '02-opening', 'Birth / Blood': '02-opening',
    'Map Data': '06-parameters', 'Unit-Mech-Pilot-Weapons': '06-parameters',
    'Spirit Accronym': '07-spirit', 'Spirit Cmds/Choose and Others': '07-spirit',
    'Skills': '08-abilities', 'Special Abilities': '08-abilities',
    'Leadership Effect': '09-bonuses', 'leadership_effect_by_offset': '09-bonuses',
    'Parts': '10-parts', 'Level Up & Results': '12-results', 'Buttons': '13-common-help',
    'Search': '04-formation-search', 'Search Menu': '04-formation-search',
    'Tactical Screen': '05-tactical', 'Battle Conditions': '05-tactical',
}


def classify(row):
    """Navigation grouping only; retain rules and flag heuristic assignments."""
    section = row['category'].removeprefix('menu/')
    if section in SECTION_CATEGORY:
        return SECTION_CATEGORY[section], 'source_section', False
    text = row['translation_zh'] + '\n' + row['editions']['original']['source_ja']
    loc = row['editions']['original']['location']
    off = loc.get('text_offsets', [0])[0]
    if loc['member'] == 'SLPS_258.87':
        for lo, hi, cat in [(0x31B610, 0x31B710, 'A2-unit-names'),
                            (0x33A9F0, 0x33B440, '01-system'),
                            (0x33B440, 0x33B470, 'A1-pilot-names'),
                            (0x33BAE0, 0x33BDE0, '02-opening'),
                            (0x33C280, 0x33C400, '10-parts'),
                            (0x33C400, 0x33D770, '11-bazaar'),
                            (0x33D770, 0x33DAB4, '11-bazaar'),
                            (0x3407C8, 0x340998, '02-opening')]:
            if lo <= off < hi:
                return cat, 'inspected_source_region', False
    rules = [
        ('01-system', r'存储卡|メモリーカード|保存|存档|读取|读档|格式化|容量不足|音量|游戏设置|系统设置|快捷指令|セーブ|ロード|オプション'),
        ('02-opening', r'主人公|生日|血型|昵称|姓氏|姓名|命名|男女|男主人公|女主人公|誕生日|血液型'),
        ('11-bazaar', r'交易所|集市|买入|卖出|购买|出售|商品|价格|买卖|バザー|売却|購入'),
        ('14-library-navigation', r'图鉴|事典|资料库|音乐选择|收录率|ＢＧＭ|BGM|曲目|曲名'),
        ('12-results', r'升级|等级提升|习得|获得资金|获得零件|获得强化|击坠数|獲得|レベルアップ'),
        ('10-parts', r'强化零件|强化部件|強化パーツ'),
        ('03-management', r'改造|培养|养成|换乘|换装|乗り換え|養成|整备|中场休息'),
        ('04-formation-search', r'编成|編成|搜索|検索|排序|並び|小队|小隊|队员|后备|阵型|フォーメーション'),
        ('09-bonuses', r'队长效果|隊長効果|小队奖励|小隊ボーナス'),
        ('07-spirit', r'精神指令|精神コマンド|精神点|ＳＰ|SP'),
        ('08-abilities', r'特殊技能|特殊能力|特殊スキル|屏障|バリア|发动概率|发动条件|特殊效果|特殊効果'),
        ('06-parameters', r'能力|命中|回避率|防御率|射程|移动力|运动性|装甲|气力|属性|地形|移动类型|ＨＰ|ＥＮ|HP|EN|攻击力|格斗|射击|弹数|弹药|等级|Lv|体型|武器性能|机体性能'),
        ('05-tactical', r'攻击|攻撃|反击|反撃|防御|回避|移动|移動|待机|待機|出击|出撃|援护|援護|回合|阶段|修理|补给|搭载|作战|作戦'),
    ]
    for cat, pattern in rules:
        if re.search(pattern, text):
            return cat, 'keyword_rule', True
    return '13-common-help', 'common_or_context_review_pending', True


class MiscExport(Export):
    def __init__(self):
        self.inputs, self.rows, self.sources, self.native, self.profiles = {}, {}, {}, {}, {}
        self.layout = self.load('config/editions/best/source-layout.json')
        self.build = self.load('config/full-story-components.json')
        self.table = load_text_table(ROOT / 'vendor/upstream-python/project/tbl_all.json')
        self.track('vendor/upstream-python/project/tbl_all.json')
        self.menu_translations = {}
        for p in sorted((ROOT / 'corpus/zh/menu').glob('*.json')):
            if p.name in {'battle-lines.json', 'stage-names.json', 'stage-overviews.json',
                          'hsfc-overviews.json', 'release-v0.3.json', 'nisv-strategy-qa.json',
                          'nisv-tutorial-pages.json'}:
                continue
            ref = str(p.relative_to(ROOT))
            for entry in self.load(ref).get('entries', []):
                if entry.get('id', '').startswith('menu/'):
                    self.menu_translations[entry['id']] = entry, ref
        ref = 'corpus/zh/menu/release-v0.3.json'
        for entry in self.load(ref)['entries']:
            self.menu_translations[entry['id']] = entry, ref
        self.remaining = self.load('corpus/zh/menu/remaining-ui.json')
        self.cache, self.offset_cache = {}, {}
        self.coverage, self.omitted = {}, []

    def track(self, ref):
        self.inputs[ref] = sha((ROOT / ref).read_bytes())

    def load_disc(self, edition):
        p = self.load(f'config/editions/{edition}/edition.json')
        self.profiles[edition] = p
        path = ROOT / p['source_iso']['path']
        with path.open('rb') as stream:
            hasher = hashlib.sha256()
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                hasher.update(block)
            digest = hasher.hexdigest()
        assert digest == p['source_iso']['sha256'], f'{edition}: source ISO hash drift'
        assert path.stat().st_size == p['source_iso']['size']
        members = member_map(scan_iso9660(path))
        names = [p['executable']['member'], 'DATA/COMPDATA.BN', 'DATA/NISVDATA.BIN',
                 'DATA/STAGE.BIN', 'HEDBDY/HB.BIN', 'MAP/MAPMODEL.BIN', 'MAP/MAPNAME.BIN',
                 'DATA/VT1.BIN', 'DATA/HSFC.BIN', 'KURODATA/KVMDATA.BIN', 'KURODATA/KVPDATA.BIN',
                 'AID_DATA/AIDDATA.BIN', 'BTL/TRICMN.BIN', 'EFF/VEFF2DX.BIN',
                 *[f'BTL/OP{i}.{ext}' for i in range(3) for ext in ('BIN', 'SEG')]]
        source, locks = {}, {}
        with path.open('rb') as stream:
            for name in names:
                m = members[name]
                stream.seek(m.extent_lba * 2048)
                source[name] = stream.read(m.size)
                assert len(source[name]) == m.size
                locks[name] = {'sha256': sha(source[name]), 'size': m.size, 'extent_lba': m.extent_lba}
        assert locks[p['executable']['member']]['sha256'] == p['executable']['sha256']
        self.sources[edition] = {'iso': p['source_iso'], 'members': locks}
        source['elf'] = source[p['executable']['member']]
        source['compdata'] = decode_production(source['DATA/COMPDATA.BN']).output
        self.native[edition] = source

    def offsets(self, edition, member):
        key = edition, member
        if key in self.offset_cache:
            return self.offset_cache[key]
        if member == 'DATA/STAGE.BIN':
            offsets = list(struct.unpack_from('<206I', self.native[edition]['HEDBDY/HB.BIN'], 30320))
        else:
            spec = next(r for r in self.layout['archive_tables'] if r['member'] == member)
            count = 197 if member == 'MAP/MAPMODEL.BIN' else spec['count']
            offsets = list(struct.unpack_from('<' + 'I' * count, self.native[edition]['elf'], spec[f'{edition}_start']))
        size = len(self.native[edition][member])
        if offsets[-1] != size:
            offsets.append(size)
        assert offsets[0] == 0 and offsets[-1] == size
        assert all(a <= b for a, b in zip(offsets, offsets[1:])), (edition, member)
        self.offset_cache[key] = offsets
        return offsets

    def chunk(self, edition, member, index):
        key = edition, member, index
        if key not in self.cache:
            offsets = self.offsets(edition, member)
            lo, hi = offsets[index:index + 2]
            stored = self.native[edition][member][lo:hi]
            result = decode_production(stored)
            assert not any(stored[result.consumed:]), key
            self.cache[key] = result.output, {'member': member, 'chunk_index': index,
                'stored_range': [lo, hi], 'offset_space': 'decoded', 'decoded_sha256': sha(result.output)}
        return self.cache[key]

    def add(self, entry_id, category, role, translation, refs, texts, locations, **context):
        super().add(entry_id, category, role, translation, refs, texts, locations, **context)
        self.rows[entry_id]['source_evidence'] = 'decoded_from_each_verified_source_iso'

    def fixed(self, entry_id, cat, translation, ref, kind, offset, **context):
        texts, locations = {}, {}
        for e in EDITIONS:
            target = self.mapped(offset) if e == 'best' and kind == 'elf' else offset
            texts[e] = self.text_at(self.native[e][kind], target)
            locations[e] = {'member': self.profiles[e]['executable']['member'] if kind == 'elf' else 'DATA/COMPDATA.BN',
                            'offset_space': 'file' if kind == 'elf' else 'decoded', 'text_offsets': [target]}
        self.add(entry_id, cat, 'ui_text', translation, [ref], texts, locations, **context)

    def menu_rows(self):
        self.menus()
        # The executable has additional squad-name templates outside NISVDATA.
        removed = []
        for entry_id, row in list(self.rows.items()):
            loc = row['editions']['original']['location']
            offsets = loc.get('text_offsets', [])
            if loc['member'] == 'SLPS_258.87' and any(
                    0x340A08 <= o < 0x340BB8 or o in {0x3409A0, 0x3409C0, 0x3409D0, 0x3409D8, 0x3409E0}
                    for o in offsets):
                removed.append({'id': entry_id, 'source_offsets': offsets, 'reason': 'excluded_executable_squad_name_template'})
                del self.rows[entry_id]
        self.coverage['excluded_executable_squad_name_templates'] = removed
        for row in self.rows.values():
            cat, basis, review = classify(row)
            row['technical_group'] = row['category']
            row['category'] = cat
            row['classification'] = {'basis': basis, 'needs_context_review': review}
        # Weapon names were intentionally excluded by the explanation-only exporter.
        ref = 'corpus/zh/menu/weapons.json'
        translations = {r['id']: r for r in self.load(ref)['entries']}
        descriptors = self.load('vendor/upstream-python/project/menu_files.json')
        for desc in descriptors:
            kind = 'elf' if desc['friendly_name'] == 'SLPS' else 'compdata'
            parsed = parse_menu_file(self.native['original'][kind], desc, self.table)
            for entry in parsed.entries:
                if entry.entry_id in self.rows:
                    self.rows[entry.entry_id]['context']['original_descriptor_references'] = {
                        'pointer_offsets': list(entry.pointer_offsets), 'embedded_hi': list(entry.embedded_hi),
                        'embedded_lo': list(entry.embedded_lo)}
            if desc['friendly_name'] != 'Compdata':
                continue
            for entry in parsed.entries:
                if entry.section != 'Weapon' or not entry.text.strip():
                    continue
                corpus = translations[entry.entry_id]
                texts = {e: self.text_at(self.native[e]['compdata'], entry.target_offsets[0]) for e in EDITIONS}
                locs = {e: {'member': 'DATA/COMPDATA.BN', 'offset_space': 'decoded',
                            'text_offsets': list(entry.target_offsets), 'pointer_offsets': list(entry.pointer_offsets)} for e in EDITIONS}
                for e in EDITIONS:
                    assert all(self.text_at(self.native[e]['compdata'], o) == texts[e] for o in entry.target_offsets)
                assert sha(texts['original'].encode()) == corpus['source_text_sha256']
                self.add(entry.entry_id, 'A3-weapon-names', 'name', corpus['translation'],
                         [{'path': ref, 'id': entry.entry_id}], texts, locs)
        # Match the reviewed profiles by original source identity, not guessed slots.
        ref = 'corpus/zh/menu/opening-protagonist-profile.json'
        for profile in self.load(ref)['entries']:
            matched = []
            for row in self.rows.values():
                if row['editions']['original']['source_text_sha256'] == profile['source_text_sha256']:
                    row['category'] = '02-opening'
                    row['translation_zh'] = profile['translation']
                    row['corpus_references'].append({'path': ref, 'id': profile['id']})
                    row['classification'] = {'basis': 'opening_profile_source_hash', 'needs_context_review': False}
                    matched.append(row['id'])
            assert matched, profile['id']

    def names(self):
        ref = 'config/display-names/compdata.json'
        config = self.load(ref)
        parsed = {}
        for e in EDITIONS:
            cfg = json.loads(json.dumps(config))
            cfg['unit_table']['pointer_base_address'] = self.profiles[e]['layout']['compdata_base']
            parsed[e] = parse_display_names(self.native[e]['compdata'], self.table, cfg,
                                           verify_text_preimages=e == 'original')
        unit_ref = 'corpus/zh/display-names/units-full.json'
        self.track(unit_ref)
        units, _ = load_full_unit_name_corpus(ROOT, ROOT / unit_ref, parsed['original'].unit_entries)
        speaker_ref = 'corpus/zh/story-speakers.json'
        speakers = {}
        for r in self.load(speaker_ref)['entries']:
            if r.get('translation'):
                h = r['source_text_sha256']
                assert h not in speakers or speakers[h]['translation'] == r['translation']
                speakers[h] = r
        self.name_by_hash = {h: (r['translation'], {'path': speaker_ref, 'id': r['id']}) for h, r in speakers.items()}
        residual_ref = 'corpus/zh/menu/remaining-ui.json'
        for s, t in self.remaining['display_names_by_source_text'].items():
            self.name_by_hash[sha(s.encode())] = t, {'path': residual_ref, 'json_pointer': '/display_names_by_source_text/' + s}
        overrides = {r['id']: r for r in self.remaining.get('pilot_name_overrides', [])}
        others = {e: {r.entry_id: r for r in parsed[e].entries} for e in EDITIONS}
        for row in parsed['original'].entries:
            if not row.text:
                continue
            texts, locs = {}, {}
            for e in EDITIONS:
                r = others[e][row.entry_id]
                texts[e] = r.text
                locs[e] = {'member': 'DATA/COMPDATA.BN', 'offset_space': 'decoded',
                           'text_offsets': [r.target_offset], 'pointer_offsets': list(r.pointer_offsets),
                           'record_indices': list(r.pointer_record_indices), 'field': r.field, 'capacity': r.capacity}
            if row.table == 'unit':
                t = units[row.entry_id]['translation']
                tr = {'path': unit_ref, 'record_index': row.record_index}
            else:
                t, tr = self.name_by_hash[row.source_text_sha256]
                if row.entry_id in overrides:
                    t, tr = overrides[row.entry_id]['translation'], {'path': residual_ref, 'id': row.entry_id}
            self.add(row.entry_id, 'A1-pilot-names' if row.table == 'pilot' else 'A2-unit-names',
                     'name', t, [tr], texts, locs)
        self.coverage['empty_pilot_name_fields_omitted'] = 347
        ref = 'corpus/zh/menu/ui-name-tables.json'
        doc = self.load(ref)
        for kind, key, cat in [('map', 'map_names', 'B1-map-names')]:
            sources, base_locs = {}, {}
            for e in EDITIONS:
                if kind == 'squad':
                    sources[e], base_locs[e] = self.chunk(e, 'DATA/NISVDATA.BIN', 4)
                else:
                    sources[e], base_locs[e] = self.native[e]['MAP/MAPNAME.BIN'], {'member': 'MAP/MAPNAME.BIN', 'offset_space': 'file'}
            for offset, capacity, row in name_slots(sources['original'], doc[key], kind=kind, table=self.table):
                texts = {e: self.text_at(sources[e], offset) for e in EDITIONS}
                locs = {e: {**base_locs[e], 'text_offsets': [offset], 'capacity': capacity, 'record_index': row['index']} for e in EDITIONS}
                self.add(row['id'], cat, 'name', row['translation'], [{'path': ref, 'id': row['id']}], texts, locs)
        ref = 'corpus/zh/auto-demo-work-titles.json'
        titles = self.load(ref)['entries']
        title_by_id = {r['id']: r for r in titles}
        for row in titles:
            self.fixed(row['id'], 'A7-work-titles', row['translation'], {'path': ref, 'id': row['id']}, 'elf', int(row['offset'], 0))
        for off, spec in self.remaining['compdata_library_work_titles_by_offset'].items():
            row = title_by_id[spec['title_id']]
            self.fixed('work-title/compdata/' + off, 'A7-work-titles', row['translation'],
                       {'path': residual_ref, 'json_pointer': '/compdata_library_work_titles_by_offset/' + off}, 'compdata', int(off, 0))
        for i in range(3):
            member, seg = f'BTL/OP{i}.BIN', f'BTL/OP{i}.SEG'
            slots = {e: discover_auto_demo_name_slots(self.native[e][member], self.native[e][seg]) for e in EDITIONS}
            assert len(slots['original']) == len(slots['best'])
            for j, source in enumerate(slots['original']):
                t, tr = self.name_by_hash[sha(source.source_text.encode())]
                texts = {e: slots[e][j].source_text for e in EDITIONS}
                locs = {e: {'member': member, 'offset_space': 'file', 'text_offsets': [slots[e][j].offset],
                            'capacity': slots[e][j].capacity, 'segment_member': seg} for e in EDITIONS}
                self.add(f'demo/op{i}/{j:03d}', 'A6-demo-names', 'name', t, [tr], texts, locs)

    def chart_prompts(self):
        for off, t in self.remaining['stage_scenario_chart_prompts_by_offset'].items():
            texts, locs = {}, {}
            for e in EDITIONS:
                data, loc = self.chunk(e, 'DATA/STAGE.BIN', 0)
                texts[e] = self.text_at(data, int(off, 0))
                locs[e] = {**loc, 'text_offsets': [int(off, 0)]}
            self.add('chart-control/' + off, '13-common-help', 'ui_text', t,
                     [{'path': 'corpus/zh/menu/remaining-ui.json', 'json_pointer': '/stage_scenario_chart_prompts_by_offset/' + off}], texts, locs)

    def tutorials(self):
        ref = 'corpus/zh/menu/nisv-tutorial-pages.json'
        doc = self.load(ref)
        pages, bases = {}, {}
        for e in EDITIONS:
            data, bases[e] = self.chunk(e, 'DATA/NISVDATA.BIN', 5)
            pages[e] = parse_nisv_tutorial_pages(data)
        for pi, page in enumerate(doc['pages']):
            for ri, row in enumerate(page['records']):
                texts, locs = {}, {}
                for e in EDITIONS:
                    r = pages[e][pi]['records'][ri]
                    prefix = bytes.fromhex(row.get('source_prefix_hex', ''))
                    assert r['raw'].startswith(prefix)
                    assert r['raw'] == prefix + row['source'].encode('cp932'), (e, pi, ri, r['raw'], row['source'])
                    texts[e] = self.text_at(r['raw'][len(prefix):] + b'\0', 0)
                    locs[e] = {**bases[e], 'page': pi + 1, 'record': ri, 'text_offsets': [r['offset'] + 8],
                               'source_prefix_hex': prefix.hex(), 'position': [r['x'], r['y'], r['z']],
                               'style': [r['style0'], r['style1']]}
                self.add(f'tutorial/{pi+1:02d}/{ri:03d}', 'C1-tutorial', 'explanation', row['translation'],
                         [{'path': ref, 'json_pointer': f'/pages/{pi}/records/{ri}'}], texts, locs)
        # Page-title annotations can be stale; the live fixed-string corpus owns headings.
        headings = sorted((int(o, 0), t) for group in ('slps_by_offset', 'slps_context_ui_by_offset')
                          for o, t in self.remaining[group].items() if 0x347B40 <= int(o, 0) <= 0x347CA0)
        assert len(headings) == 10
        mismatches = []
        for pi, (offset, translation) in enumerate(headings):
            entry_id = f'tutorial/{pi+1:02d}/title'
            self.fixed(entry_id, 'C1-tutorial', translation,
                       {'path': 'corpus/zh/menu/remaining-ui.json', 'source_offset': hex(offset)}, 'elf', offset)
            self.rows[entry_id]['role'] = 'heading'
            annotation = doc['pages'][pi]['title']
            if annotation['source'] != self.rows[entry_id]['editions']['original']['source_ja']:
                mismatch = {'id': entry_id, 'annotation_path': ref, 'annotation': annotation,
                            'actual_source': self.rows[entry_id]['editions']['original']['source_ja'],
                            'selected_translation': translation}
                mismatches.append(mismatch)
                self.rows[entry_id]['context']['stale_title_annotation'] = mismatch
        self.coverage['tutorial_title_annotation_mismatches'] = mismatches

    def image_row(self, entry_id, category, source, translation, ref, targets):
        locs = {}
        for e in EDITIONS:
            occurrences = []
            for target in targets:
                member = target['member']
                loc = dict(target)
                if 'chunk_index' in target:
                    offsets = self.offsets(e, member)
                    lo, hi = offsets[target['chunk_index']:target['chunk_index'] + 2]
                    raw = self.native[e][member][lo:hi]
                    loc.update(stored_range=[lo, hi], source_chunk_sha256=sha(raw))
                else:
                    loc['source_member_sha256'] = sha(self.native[e][member])
                occurrences.append(loc)
            locs[e] = {'occurrences': occurrences, 'offset_space': 'image_annotation'}
        equal = all(a.get('source_chunk_sha256', a.get('source_member_sha256')) == b.get('source_chunk_sha256', b.get('source_member_sha256'))
                    for a, b in zip(locs['original']['occurrences'], locs['best']['occurrences']))
        # Changed container bytes do not prove a changed caption, or its equality.
        if entry_id in self.rows:
            row = self.rows[entry_id]
            assert row['editions']['original']['source_ja'] == source and row['translation_zh'] == translation
            for e in EDITIONS:
                row['editions'][e]['location']['occurrences'].extend(locs[e]['occurrences'])
            if ref not in row['corpus_references']:
                row['corpus_references'].append(ref)
            equal = equal and row['image_container_equal_between_editions']
        else:
            self.add(entry_id, category, 'image_label', translation, [ref],
                     {'original': source, 'best': source}, locs)
        row = self.rows[entry_id]
        row['source_evidence'] = 'existing_image_annotation; no_OCR'
        row['source_changed_in_best'] = False if equal else None
        row['image_container_equal_between_editions'] = equal
        if not equal:
            row['editions']['best']['source_ja'] = None
            row['editions']['best']['source_text_sha256'] = None
            row['context']['best_transcription_status'] = 'container_changed_caption_not_independently_verified'

    def images(self):
        # All currently registered corpus labels, with their actual configuration bindings.
        image_refs = {}
        for p in sorted((ROOT / 'corpus/zh/ui-atlas').glob('*.json')):
            ref = str(p.relative_to(ROOT))
            for row in self.load(ref)['entries']:
                image_refs[row['id']] = row, ref
        bound = set()
        for name in ['ui-battle-command-atlas-zh', 'ui-formation-atlas-zh', 'ui-intermission-atlas-zh',
                     'ui-bazaar-atlas-zh', 'ui-info-atlas-zh', 'ui-stage-clear-atlas-zh']:
            ref = f'config/assets/{name}.json'
            config = self.load(ref)
            mapping = self.load(config['base_mapping']['config'])
            labels = [config['localized_label'], *config.get('additional_localized_labels', [])]
            for j, label in enumerate(labels):
                tr = label.get('translation_source', label)
                row, corpus_ref = image_refs[tr['entry_id']]
                target = {k: v for k, v in config['target'].items() if k in ('member', 'chunk_index', 'record_index', 'picture_index')}
                target['config_reference'] = ref
                target['label_index'] = j
                target['geometry'] = label.get('mask', label.get('rect', mapping['target'].get('mask') if j == 0 else None))
                self.image_row('image/' + row['id'], 'D1-ui-images', row.get('source_text', row.get('source')),
                               row['translation'], {'path': corpus_ref, 'id': row['id']}, [target])
                bound.add(row['id'])
        for config_name, member, cat in [('aid-battle-prompts-zh', 'AID_DATA/AIDDATA.BIN', 'D2-battle-images'),
                                        ('tricmn-battle-overlays-zh', 'BTL/TRICMN.BIN', 'D2-battle-images')]:
            ref = f'config/assets/{config_name}.json'
            cfg = self.load(ref)
            for label in cfg['labels']:
                row, corpus_ref = image_refs[label['entry_id']]
                target = {'member': member, 'config_reference': ref, **label}
                if cat == 'D2-battle-images' and member.startswith('AID'):
                    target.update(chunk_index=0, tim2_offset=cfg['tim2']['offset'])
                else:
                    target['record_offset'] = cfg['tim2']['record_offset']
                self.image_row('image/' + row['id'], cat, row['source_text'], row['translation'],
                               {'path': corpus_ref, 'id': row['id']}, [target])
                bound.add(row['id'])
        ref = 'config/assets/title-menu-zh.json'
        cfg = self.load(ref)
        for i, row in enumerate(cfg['labels']):
            self.image_row(f'image/title/{i}', 'D1-ui-images', row['source'], row['translation'],
                           {'path': ref, 'json_pointer': f'/labels/{i}'},
                           [{**cfg['target'], 'label_index': i}])
        ref = 'config/assets/ui-headings-zh.json'
        cfg = self.load(ref)
        for entry_id, (row, corpus_ref) in image_refs.items():
            if entry_id in bound:
                continue
            if entry_id.startswith('world-map/'):
                targets = [{'member': 'MAP/MAPMODEL.BIN', 'chunk_index': i, 'decoded_image_range': [0x1DE0, 0x3DE0],
                            'width': 512, 'height': 32} for i in row['members']]
                self.image_row('image/' + entry_id, 'D3-map-images', row['source'], row['translation'],
                               {'path': corpus_ref, 'id': entry_id}, targets)
            elif corpus_ref.endswith('formation-help-headings.json'):
                patches = [p for p in cfg['draw_patches'] if p['token'] == entry_id]
                self.image_row('image/heading/' + entry_id, 'D1-ui-images', row['source'], row['translation'],
                               {'path': corpus_ref, 'id': entry_id},
                               [{'member': 'KURODATA/KVPDATA.BIN', 'config_reference': ref, 'draw_patches': patches}])
            else:
                raise ValueError(f'Unbound image corpus entry: {entry_id}')
        ref = 'config/library/v0.2.0.json'
        cfg = self.load(ref)
        self.export_library_images(cfg, ref)

    def export_library_images(self, cfg, ref):
        for key in ('library_menu_runtime_tim2', 'sound_select_runtime_tim2', 'scenario_chart_runtime_tim2'):
            spec = cfg[key]
            for mask in spec['writeback']['masks']:
                source = mask['source_text']
                if 'Ｑ＆Ａ' in source:
                    continue
                target = {k: v for k, v in spec['target'].items() if k in ('chunk_index', 'record_index', 'record_offset', 'picture_index')}
                target.update(member=spec['member'], rect=[mask[x] for x in ('x', 'y', 'width', 'height')], config_reference=ref)
                self.image_row('image/library/' + key + '/' + mask['id'], 'D1-ui-images', source, spec['labels'][source],
                               {'path': ref, 'json_pointer': '/' + key + '/labels/' + source}, [target])

    def dynamic_labels(self):
        ref = 'corpus/zh/menu/weapon-special-effect-2.json'
        corpus = {r['id']: r for r in self.load(ref)['entries']}
        for field in self.build['weapon_special_effect_2']['fields']:
            row = corpus[field['id']]
            texts, locs = {}, {}
            for e in EDITIONS:
                builders = json.loads(json.dumps(field['word_builders']))
                sites = []
                for b in builders:
                    for k in ('ori_file_offset', 'lui_file_offset'):
                        if k in b:
                            offset = int(b[k], 0)
                            b[k] = self.mapped(offset) if e == 'best' else offset
                            sites.append(b[k])
                raw = b''.join(_read_builder_chunk(self.native[e]['elf'], b) for b in builders)
                texts[e] = self.text_at(raw, 0)
                assert texts[e] == row['source']
                locs[e] = {'member': self.profiles[e]['executable']['member'], 'offset_space': 'mips_instruction',
                           'instruction_offsets': sites, 'materialized_hex': raw.hex()}
            self.add('dynamic/effect/' + row['id'], '08-abilities', 'ui_text', row['translation'],
                     [{'path': ref, 'id': row['id']}], texts, locs)
        for key in ('runtime_weapon_category_labels', 'runtime_movement_type_labels'):
            for row in self.build[key]['sites']:
                texts, locs = {}, {}
                for e in EDITIONS:
                    off = int(row['file_offset'], 0)
                    block = bytes.fromhex(row['original_block_hex'])
                    if e == 'best':
                        try:
                            off = self.mapped(off)
                        except ValueError:
                            matches = [m.start() for m in re.finditer(re.escape(block), self.native[e]['elf'])]
                            assert len(matches) == 1, (key, row['id'], matches)
                            off = matches[0]
                    # Branch destinations can move in BEST; the materialization immediates must remain.
                    actual = self.native[e]['elf'][off:off+len(block)]
                    if e == 'original':
                        assert actual == block
                    else:
                        for i in range(0, len(block), 4):
                            op = struct.unpack_from('<I', block, i)[0] >> 26
                            if op in (0x0F, 0x0D, 0x09):
                                assert actual[i:i+4] == block[i:i+4], (key, row['id'], i)
                    texts[e] = row['source_text']
                    locs[e] = {'member': self.profiles[e]['executable']['member'], 'offset_space': 'mips_instruction',
                               'instruction_range': [off, off+len(block)], 'source_block_sha256': sha(actual),
                               'materialized_hex': row['source_materialized_hex']}
                self.add('dynamic/' + key + '/' + row['id'], '06-parameters', 'ui_text', row['translation'],
                         [{'path': 'config/full-story-components.json', 'json_pointer': '/' + key + '/sites', 'id': row['id']}], texts, locs)
                self.rows['dynamic/' + key + '/' + row['id']]['source_evidence'] = 'source_contract_and_native_instruction_preimage'

    def effect_images(self):
        ref = 'config/full-story-components.json'
        # Transcribed from the hash-locked native 256x256 selection atlas.
        # The scenario labels combine separate 本編 / ガイダンス / シナリオ glyph runs.
        source_labels = {'scenario_select_effect': ['本編シナリオ', 'ガイダンスシナリオ'],
                         'mode_select_effect': ['ノーマルモード', 'EXハードモード', 'スペシャルモード']}
        for key, sources in source_labels.items():
            cfg = self.build[key]
            for i, (source, translation) in enumerate(zip(sources, cfg['composed_labels'])):
                target = {k: v for k, v in cfg['target'].items() if k in ('chunk_index', 'record_index', 'record_offset', 'record_size', 'picture_index')}
                target.update(member='EFF/VEFF2DX.BIN', source_logical_image_sha256=cfg['target']['logical_image_sha256'],
                              composition=cfg['geometry']['groups'][i])
                for e in EDITIONS:
                    data, _ = self.chunk(e, 'EFF/VEFF2DX.BIN', target['chunk_index'])
                    lo = target['record_offset']
                    assert sha(data[lo:lo+target['record_size']]) == cfg['target']['record_sha256']
                entry_id = f'image/{key}/{i}'
                self.image_row(entry_id, 'D1-ui-images', source, translation,
                               {'path': ref, 'json_pointer': f'/{key}/composed_labels/{i}'}, [target])
                self.rows[entry_id]['source_evidence'] = 'native_atlas_visual_transcription_and_equal_TIM2_record_hashes; no_OCR'
        spec = self.build['tutorial_title_effects']
        for picture in spec['pictures']:
            if picture['translation'] == picture['source_text']:
                continue
            targets = [{'member': 'EFF/VEFF2DX.BIN', 'chunk_index': target['chunk_index'],
                        'record_index': spec['record_index'], 'picture_index': picture['picture_index'],
                        'rect': picture.get('clear_rect'), 'segments': picture.get('segments', [])}
                       for target in spec['targets'] if picture['picture_index'] in target['localized_picture_indices']]
            if targets:
                self.image_row('image/tutorial-effect/' + str(picture['picture_index']), 'D1-ui-images',
                               picture['source_text'], picture['translation'],
                               {'path': ref, 'json_pointer': '/tutorial_title_effects/pictures/' + str(picture['picture_index'])}, targets)

    def write_outputs(self, output):
        rows = sorted(self.rows.values(), key=lambda r: (r['category'], r['id']))
        shared = defaultdict(list)
        for r in rows:
            assert r['category'] not in {'A4-squad-suggestions', 'A5-default-squads', 'B2-terrain-names'}
            for e in EDITIONS:
                loc = r['editions'][e]['location']
                if 'text_offsets' in loc:
                    loc['source_reference_count'] = len(loc['text_offsets'])
                    loc['text_offsets'] = list(dict.fromkeys(loc['text_offsets']))
                if loc.get('member') == 'DATA/COMPDATA.BN':
                    assert not any(0x6EBF0 <= o < 0x6F630 for o in loc.get('text_offsets', [])), 'BGM title entered export'
                if e == 'original':
                    for off in loc.get('text_offsets', []):
                        shared[(loc['member'], loc.get('chunk_index'), loc['offset_space'], off)].append(r)
            if r['category'].startswith('A') or r['category'] == 'B1-map-names':
                r['role'] = 'name'
            r['category_label'] = CATEGORIES[r['category']]
            r.setdefault('classification', {'basis': 'explicit_source_table', 'needs_context_review': False})
        shared_rows = []
        for (member, chunk, space, off), group in shared.items():
            if len(group) > 1:
                ids = [r['id'] for r in group]
                shared_rows.append({'original_location': {'member': member, 'chunk_index': chunk, 'offset_space': space, 'offset': off},
                                    'entries': [{'id': r['id'], 'translation': r['translation_zh'], 'category': r['category']} for r in group],
                                    'note': 'Distinct semantic owners share original bytes; preserve separate IDs and current corpus translations.'})
                for r in group:
                    r['context']['shared_source_owner_ids'] = ids
        self.coverage['bgm_title_range_excluded'] = {'member': 'DATA/COMPDATA.BN', 'offset_space': 'decoded', 'start': '0x6EBF0', 'end': '0x6F630', 'exported_references': 0}
        assert len(rows) == len({r['id'] for r in rows})
        assert all(r['translation_zh'] for r in rows)
        assert not any(r['category'].startswith('library/') for r in rows)
        for ref, digest in self.inputs.items():
            assert sha((ROOT / ref).read_bytes()) == digest, f'Input drift during export: {ref}'
        for ref in ['tools/export_misc_text.py', 'tools/export_explanatory_text.py']:
            self.track(ref)
        output.mkdir(parents=True, exist_ok=False)
        grouped = defaultdict(list)
        for r in rows:
            grouped[r['category']].append(r)
        (output / 'categories').mkdir()
        for cat, group in grouped.items():
            write_json(output / 'categories' / (cat + '.json'), {'category': cat, 'label': CATEGORIES[cat], 'entries': group})
        write_json(output / 'combined.json', {'schema_version': 2, 'entries': rows})
        for e in EDITIONS:
            write_json(output / (e + '.json'), {'schema_version': 2, 'edition': e, 'source': self.sources[e],
                'entries': [{k: v for k, v in r.items() if k != 'editions'} | r['editions'][e] for r in rows]})
        diffs = [r for r in rows if r['source_changed_in_best'] is True]
        write_json(output / 'edition-differences.json', {'entries': diffs})
        write_json(output / 'shared-source-owners.json', {'entries': shared_rows})
        review = [r for r in rows if r['classification']['needs_context_review']]
        write_json(output / 'classification-review.json', {'scope': 'Category review only; source extraction is separately verified.', 'entries': review})
        manifest = {'schema_version': 2, 'entry_count_per_edition': len(rows),
                    'categories': {k: {'label': CATEGORIES[k], 'count': len(v)} for k, v in grouped.items()},
                    'roles': dict(Counter(r['role'] for r in rows)), 'edition_source_differences': len(diffs),
                    'image_caption_comparison_unknown': sum(r['source_changed_in_best'] is None for r in rows),
                    'classification_review_count': len(review), 'coverage': self.coverage,
                    'excluded': ['BGM track titles (explicit user request)', 'squad names: suggestions and defaults', 'terrain names', 'story dialogue', 'battle dialogue',
                                 'encyclopedia bodies and metadata', 'strategy Q&A', 'story summaries/history/Z reports',
                                 'stage titles and stage-specific objectives', 'Special Disc'],
                    'sources': self.sources, 'input_sha256': self.inputs,
                    'translation_evidence': 'Current corpus selection, not decoded Chinese ISO or runtime verification.',
                    'image_evidence': 'Existing annotations, version-native container hashes; no OCR or new visual acceptance.'}
        write_json(output / 'manifest.json', manifest)
        self.html_export(output, rows, manifest)
        lines = ['# 本篇 / BEST 零散文本结构化导出', '',
                 f'每版 {len(rows):,} 条记录，原文差异 {len(diffs)} 条。BGM 曲名已排除。', '',
                 '中文来自当前工作区语料；日文字符串分别从 SHA-256 验证通过的两版原盘读取。图片文字来自现有标注，保留配置和资源位置，不是 OCR。', '',
                 '## 文件', '', '- `index.html`：离线检索、类别筛选及两版日文／中文对照。',
                 '- `combined.json`：两版按稳定 ID 对齐的完整结构。', '- `original.json` / `best.json`：单版结构。',
                 '- `categories/`：按类别拆分，名称、教程、图片单列。', '- `edition-differences.json`：确认存在差异的原文。',
                 '- `classification-review.json`：启发式分组的上下文复核队列；不影响原文定位证据。',
                 '- `shared-source-owners.json`：共用原始字节但用途不同的条目，保留各自 ID 与译文。',
                 '- `manifest.json`：版本身份、原盘／成员／输入哈希、统计及范围。', '',
                 '## 计数与边界', '',
                 '人物字段按记录保留，机体和武器名沿用原表的共享指针分组。不同字段角色不因同文而合并。BGM 曲名、小队名称建议、默认小队名和地形名均已排除；地图地点名和世界地图图片标题保留。',
                 '不把覆盖层和基础表重复累计；同一条目的重复目标偏移已合并，原始引用保留在指针或上下文字段。新增来源可能与菜单有同文，保留用途和定位。空人物字段、空武器项不进入校对记录。',
                 '教程第8页的旧元数据标题是“技能等级”，两版 ELF 原文及固定槽译文均为“选择帮助”；本导出采用实际标题，并在 manifest 和对应条目中记录旧备注差异。教程第10页介绍攻略 Q&A 的入口，不是 Q&A 正文。',
                 '类别属于导航分组，启发式分组明确标记需要上下文复核。图片容器不同而未经独立确认的 BEST 标注为空，并以 null 表示差异未知。',
                 '这是已知来源的结构化导出，不声称扫描出游戏所有未知图片／职员表／版权文字。没有修改译文、ISO 或构建锁。', '',
                 '| 类别 | 记录数 |', '| --- | --- |']
        lines += [f'| {CATEGORIES[k]} | {len(v)} |' for k, v in grouped.items()]
        lines += ['', '重跑：`python3 tools/export_misc_text.py --output work/exports/misc-text-新目录`。输出目录必须不存在。']
        (output / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        checksums = {str(p.relative_to(output)): sha(p.read_bytes()) for p in sorted(output.rglob('*')) if p.is_file()}
        write_json(output / 'checksums.json', checksums)
        archive = output.with_suffix('.zip')
        assert not archive.exists()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(output.rglob('*')):
                if p.is_file():
                    z.write(p, str(Path(output.name) / p.relative_to(output)))
        print(json.dumps({k: manifest[k] for k in ('entry_count_per_edition', 'roles', 'edition_source_differences', 'classification_review_count', 'image_caption_comparison_unknown')}, ensure_ascii=False), flush=True)

    def html_export(self, output, rows, manifest):
        payload = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
        html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>本篇 / BEST 零散文本</title>
<style>body{font:15px/1.6 system-ui;background:#f5f7fa;color:#203345;margin:28px}input,select,button{font:inherit;padding:7px;margin:4px}table{width:100%;border-collapse:collapse;background:white}td,th{border:1px solid #d5dfe8;padding:10px;vertical-align:top;text-align:left}td{white-space:pre-wrap;overflow-wrap:anywhere}td:first-child{width:22%}td:not(:first-child){width:26%}th{background:#e7edf4}details{font-size:12px}small{color:#66778a}</style>
<h1>本篇 / BEST 零散文本</h1><p>BGM 曲名、小队名、地形名、剧情／战斗台词、图鉴正文及攻略 Q&A 已排除。日文字符串来自两版原盘；中文来自当前语料；图片文字为已有标注。地图地点名和世界地图图片标题保留。</p>
<input id="q" placeholder="搜索 ID、日文、中文" size="34"><select id="cat"><option value="">全部类别</option></select><label><input id="diff" type="checkbox">只看版本差异</label><label><input id="review" type="checkbox">分类待复核</label><p id="count"></p><button id="prev">上一页</button><button id="next">下一页</button><table><thead><tr><th>类别 / ID / 来源</th><th>本篇日文</th><th>BEST 日文</th><th>当前中文</th></tr></thead><tbody id="body"></tbody></table>
<script>const rows=PAYLOAD;const $=s=>document.getElementById(s);let page=0;for(const c of [...new Set(rows.map(r=>r.category))]){const o=document.createElement('option');o.value=c;o.textContent=rows.find(r=>r.category===c).category_label;$('cat').append(o)}
function render(){const q=$('q').value.toLowerCase();const a=rows.filter(r=>(!$('cat').value||r.category===$('cat').value)&&(!$('diff').checked||r.source_changed_in_best===true)&&(!$('review').checked||r.classification.needs_context_review)&&(!q||[r.id,r.translation_zh,...Object.values(r.editions).map(x=>x.source_ja||'')].join(' ').toLowerCase().includes(q)));const n=Math.max(1,Math.ceil(a.length/60));page=Math.min(Math.max(page,0),n-1);$('count').textContent=`${a.length} 条 · 第 ${page+1}/${n} 页`;$('body').replaceChildren();for(const r of a.slice(page*60,page*60+60)){const tr=document.createElement('tr');for(const t of [r.category_label+'\\n'+r.id+(r.classification.needs_context_review?'\\n分类待复核':''),r.editions.original.source_ja??'标注待核实',r.editions.best.source_ja??'标注待核实',r.translation_zh]){const td=document.createElement('td');td.textContent=t;tr.append(td)}const d=document.createElement('details'),s=document.createElement('summary'),p=document.createElement('pre');s.textContent='定位与证据';p.textContent=JSON.stringify({source_evidence:r.source_evidence,corpus:r.corpus_references,locations:Object.fromEntries(Object.entries(r.editions).map(([k,v])=>[k,v.location]))},null,2);d.append(s,p);tr.firstChild.append(d);$('body').append(tr)}$('prev').disabled=page===0;$('next').disabled=page===n-1}
for(const id of ['q','cat','diff','review'])$(id).oninput=()=>{page=0;render()};$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};render();</script></html>'''
        (output / 'index.html').write_text(html.replace('PAYLOAD', payload), encoding='utf-8')

    def run(self, output):
        for e in EDITIONS:
            print('Verifying source ISO: ' + e, flush=True)
            self.load_disc(e)
        for method in (self.menu_rows, self.names, self.chart_prompts, self.tutorials,
                       self.dynamic_labels, self.images, self.effect_images):
            print('Exporting ' + method.__name__, flush=True)
            method()
            print(f'{len(self.rows)} records so far', flush=True)
        self.write_outputs(output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'work').resolve()) or output.exists() or output.with_suffix('.zip').exists():
        p.error('Use a new output directory under work, with no existing adjacent ZIP')
    MiscExport().run(output)


if __name__ == '__main__':
    main()
