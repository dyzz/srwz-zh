"""Write config/fonts/zh-latin-bank.json: font sources, natural advances and raster locks.

Advances come from the locked TTFs (needs Pillow); everything the build needs afterwards
is in the JSON, so builds themselves do not import Pillow.

    python3 tools/text_layout/export_latin_bank.py [--check]
"""
from pathlib import Path
import argparse, hashlib, json, sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from PIL import ImageFont
from srwz import latin_bank

p = argparse.ArgumentParser(); p.add_argument('--check', action='store_true'); a = p.parse_args()
LOCKS = {'letters': 'config/fonts/harmonyos-sans-condensed.lock.json', 'digits': 'config/fonts/harmonyos-sans-sc.lock.json'}
rasterizer = json.loads((ROOT / 'config/fonts/zh-font-base.json').read_text())['rasterizer']
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
fonts = {}
sources = {}
for key, lock_path in LOCKS.items():
    lock = json.loads((ROOT / lock_path).read_text())
    sources[key] = dict(font_lock=lock_path, font_lock_sha256=sha(ROOT / lock_path), family=lock['family'], style=lock['style'])
    # 64x the raster size: unhinted advances in 1/64 px of the 22 px em.
    fonts[key] = ImageFont.truetype(str(ROOT / lock['font']['path']), rasterizer['point_size'] * 64)
DIGITS = dict(supersample=8, scale_1000=990, y_offset_supersampled=13,
              reason='Regular-width digits drawn on the Condensed capitals\' rows 5..20 (same height and baseline); the families\' own vertical metrics differ.')
advance = lambda character: round(fonts['digits'].getlength(character) * DIGITS['scale_1000'] / 1000) if character.isdigit() else round(fonts['letters'].getlength(character))
config = dict(
    schema_version=1, bank_id='srwz-zh-latin-bank-v1', base_code=f'{latin_bank.BASE_CODE:04X}',
    purpose='HarmonyOS Latin letters, digits and identifier punctuation for the proportional text scenes only. Stored in the unused Cyrillic glyph slots; text codes are unchanged and fixed-pitch UI keeps the stock glyphs.',
    sources=sources,
    baseline_shift_rows=-1,
    digits=DIGITS,
    zero_dot=dict(radius_64=83, reason='Round centre dot so 0 and O cannot be confused (user reference 2026-11-12).'),
    word_space=dict(advance_64=advance(' '), minimum_px=5),
    glyphs={character: dict(slot=slot, advance_64=advance(character)) for slot, character in sorted(latin_bank.slot_characters().items())},
)
path = ROOT / latin_bank.CONFIG
path.write_text(json.dumps(config, ensure_ascii=False, indent=1) + '\n') if not path.exists() else None
draft = latin_bank.load(ROOT) if path.exists() else None
loaded = dict(config); loaded['sources'] = {k: dict(v, path=draft['sources'][k]['path']) for k, v in sources.items()}
for slot, (character, gray, _) in latin_bank.rasters(ROOT, rasterizer, {**loaded, 'glyphs': {c: dict(g) for c, g in config['glyphs'].items()}}).items():
    config['glyphs'][character]['raw_gray_sha256'] = hashlib.sha256(gray).hexdigest()
content = json.dumps(config, ensure_ascii=False, indent=1) + '\n'
if a.check:
    assert path.read_text() == content, 'Latin bank config stale'
else:
    path.write_text(content)
print(hashlib.sha256(content.encode()).hexdigest())
