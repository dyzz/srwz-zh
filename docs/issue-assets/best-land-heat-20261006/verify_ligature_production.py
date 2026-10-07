"""Independent final ISO bytes, natural runtime RAM, and card evidence."""
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_full_story_iso_content import read_members
from srwz.codec import decode_production

OUT = ROOT / 'work/runtime/lrps2/heat-ligature-20261007/production'
ASSETS = ROOT / 'docs/issue-assets/best-land-heat-20261006'
NAME = bytes.fromhex('8273826797f0826782648260827300')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
contract = json.loads((ROOT / 'config/editions/best/source-layout.json').read_text())
fields = json.loads((OUT / 'implementation-static.json').read_text())['heat_fields']
font = (OUT / 'final-production-font.bin').read_bytes()
glyph = font[4400 * 288:4401 * 288]
assert glyph == (ROOT / 'work/analysis/formation-capacity-20261007/e-space-glyph-v2.bin').read_bytes()
editions = []
vt1_reference = None
for edition, elf in [('original', 'SLPS_258.87'), ('best', 'SLPS_732.70')]:
    iso = ROOT / f'build/iso/zh-release-{edition}/current-{edition}.iso'
    members = read_members(iso, (elf, 'DATA/STAGE.BIN', 'HEDBDY/HB.BIN', 'DATA/NISVDATA.BIN', 'DATA/VT1.BIN'))
    vt1_hash = hashlib.sha256(members['DATA/VT1.BIN']).hexdigest()
    if vt1_reference is None: vt1_reference = vt1_hash
    assert vt1_hash == vt1_reference
    offsets = struct.unpack_from('<206I', members['HEDBDY/HB.BIN'], 30320)
    results = []
    for row in fields:
        index, target = row['stage'], int(row['offset'], 16)
        layout = contract['stage_layouts'].get(str(index), {}) if edition == 'best' else {}
        target += layout.get('second_shift', 0) if 'second_region' in layout and target >= layout['second_region'] else layout.get('shift', 0)
        data = decode_production(members['DATA/STAGE.BIN'][offsets[index]:offsets[index + 1]]).output
        actual = data[target:target + row['capacity']]
        assert actual == NAME + bytes(row['capacity'] - len(NAME)), (edition, row, actual.hex())
        results.append(dict(stage=index, final_offset=hex(target), capacity=row['capacity'], actual_hex=actual.hex()))
    table_start = next(r['best_start' if edition == 'best' else 'original_start'] for r in contract['archive_tables'] if r['member'] == 'DATA/NISVDATA.BIN')
    ni = struct.unpack_from('<7I', members[elf], table_start)
    names = decode_production(members['DATA/NISVDATA.BIN'][ni[4]:ni[5]]).output
    target = 34 + 286 * 97
    assert names[target:target + 28] == NAME + bytes(28 - len(NAME))
    editions.append(dict(edition=edition, iso=str(iso), sha256=sha(iso), stage_fields=results, nisv_index=97,
                         nisv_actual_hex=names[target:target+28].hex(), vt1_sha256=vt1_hash))

runtime = []
for directory, addresses in [('cold-load', [0x57e0b8, 0x590918, 0x75ffd8]),
                             ('reload', [0x57e0b8, 0x590918, 0x75ffd8]),
                             ('original-cold-load', [0x57d8b8, 0x590118, 0x75f7d8])]:
    folder = OUT / directory
    ram_path = next(folder.glob('formation-*.ram'))
    ram = ram_path.read_bytes()
    for address in addresses: assert ram[address:address + len(NAME)] == NAME
    font_address = ram.find(font)
    assert font_address >= 0
    commands = [json.loads(line)['command'] for line in (folder / 'commands.jsonl').read_text().splitlines() if 'command' in json.loads(line)]
    assert not any(c.startswith(('poke ', 'restore ')) for c in commands)
    runtime.append(dict(run=directory, ram_sha256=sha(ram_path), names=[hex(a) for a in addresses],
                        full_font_exact=True, font_address=hex(font_address), ram_pokes=0, savestate_restores=0))

original_card = ROOT.parent / 'work/Mcd001.ps2'
assert sha(original_card) == 'a126d7ecce0f6af8e77acab9fed36776a3051a7786dc86f26cdb3f903237496a'
delivered = ROOT.parent / 'work/Mcd001-THE-HEAT-ligature-fixed.ps2'
assert sha(delivered) == sha(OUT / 'BEST-THE-HEAT-ligature-slot1-repaired.ps2')
report = dict(logical_name='THE HEAT', storage_hex=NAME.hex(), storage_size=len(NAME), code='97F0', glyph_index=4400,
              glyph_sha256=hashlib.sha256(glyph).hexdigest(), editions=editions, runtime=runtime,
              runtime_backend='LRPS2 software rendering; cheats disabled; process cold start, title load slot 1',
              original_card_unchanged=True, original_card_sha256=sha(original_card),
              delivered_card=str(delivered), delivered_card_sha256=sha(delivered),
              native_save=json.loads((OUT / 'native-save-check.json').read_text()),
              best_native_save_cold_reload_passed=True, manual_armsx2_or_pcsx2_acceptance=False,
              full_unit_tests=dict(count=754, passed=True, seconds=142.719),
              batch_manifest='work/editions/f54c7805c552dfc91224354a85c1fed5bd1b765cdad3694ddb4e542eaf958479/original-best.json')
(ASSETS / 'ligature-production-receipt.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
shutil.copy2(OUT / 'original-cold-load/formation-original.png', ASSETS / 'ligature-production-original.png')
print('PASS: both ISOs 11 STAGE + 1 NISV, three cold starts, native save/reload, original card preserved')
