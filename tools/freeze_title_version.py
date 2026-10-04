#!/usr/bin/env python3
"""Freeze a title version badge; production consumes the indexed mask only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from datetime import datetime
import re
import subprocess
import zlib
from zoneinfo import ZoneInfo

try:
    from srwz.codec import decode
    from srwz.tim2 import scan_tim2
    from srwz.tim2_writeback import _csm1_palette_offset
    from srwz.iso9660 import scan_iso9660
except ModuleNotFoundError:
    from tools.srwz.codec import decode
    from tools.srwz.tim2 import scan_tim2
    from tools.srwz.tim2_writeback import _csm1_palette_offset
    from tools.srwz.iso9660 import scan_iso9660

ROOT = Path(__file__).resolve().parents[1]


def version_text(root: Path, *, date: str | None = None, release_tag: str | None = None) -> str:
    tags = subprocess.check_output(['git', 'tag', '--points-at', 'HEAD'], cwd=root, text=True).splitlines()
    tags = [tag for tag in tags if re.fullmatch(r'v\d+\.\d+\.\d+', tag)]
    if tags:
        return max(tags, key=lambda tag: tuple(map(int, tag[1:].split('.'))))
    if release_tag is None:
        try:
            release_tag = subprocess.check_output(
                ['gh', 'release', 'view', '--repo', 'dyzz/srwz-zh', '--json', 'tagName', '--jq', '.tagName'],
                cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=15).strip()
        except (OSError, subprocess.SubprocessError):
            # The checked release identity is retained for offline builds.
            badge = json.loads((root / 'config/assets/title-menu-zh.json').read_text())['version_badge']
            release_tag = badge['latest_release_tag']
    if not re.fullmatch(r'v\d+\.\d+\.\d+', release_tag):
        raise ValueError('latest release does not have a version tag')
    day = date or datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d')
    if not re.fullmatch(r'\d{8}', day):
        raise ValueError('build date must be YYYYMMDD')
    return f'{release_tag}+{day}'


def freeze(text: str, font_path: Path | None = None, *, root: Path = ROOT) -> dict:
    contract = json.loads((root / 'config/assets/title-menu-zh.json').read_text())
    member_path = root / 'work/disc/DATA/VT1.BIN'
    if member_path.is_file():
        source_path, source_offset = member_path, 0
    else:
        # Fresh checkouts have not extracted work/disc yet when inputs freeze.
        edition = json.loads((root / 'config/editions/original/edition.json').read_text())
        source_path = root / edition['source_iso']['path']
        member = next(m for m in scan_iso9660(source_path).members if m.path == 'DATA/VT1.BIN')
        source_offset = member.extent_lba * 2048
    with source_path.open('rb') as source:
        source.seek(source_offset + 0xA751B0)
        decoded = decode(source.read(0x72560)).output
    if hashlib.sha256(decoded).hexdigest() != contract['target']['decoded_sha256']:
        raise ValueError('title source chunk identity drift')
    record = scan_tim2(decoded)[2]
    picture = record.pictures[0]
    start = picture.offset + picture.header_size
    original = decoded[start:start + picture.image_size]
    palette = decoded[start + picture.image_size:record.end]
    colors = [palette[_csm1_palette_offset(i)*4:_csm1_palette_offset(i)*4+4] for i in range(256)]
    opaque = [i for i in set(original) if colors[i][3] == 128]
    luma = lambda i: sum(colors[i][:3])
    indexes = [min(opaque, key=luma), max(opaque, key=luma)]
    width, height = 160, 20
    if font_path is not None:
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(str(font_path), 10)
        glyphs = {}
        for char in 'v0123456789.+-':
            im = Image.new('L', (16, 16))
            ImageDraw.Draw(im).text((2, -1), char, font=font, fill=2, stroke_width=1, stroke_fill=1)
            raw = im.tobytes()
            glyphs[char] = {'advance': round(font.getlength(char)), 'sha256': hashlib.sha256(raw).hexdigest(),
                            'zlib_base64': base64.b64encode(zlib.compress(raw, 9)).decode()}
        authoring = {'font_filename': font_path.name,
                     'font_sha256': hashlib.sha256(font_path.read_bytes()).hexdigest(),
                     'size_px': 10, 'stroke_px': 1}
    else:
        previous = contract['version_badge']
        glyphs, authoring = previous['glyphs'], previous['authoring']
    try:
        text_width = sum(glyphs[char]['advance'] for char in text)
    except KeyError as error:
        raise ValueError('version contains an unsupported character') from error
    if text_width > width - 6:
        raise ValueError('version text exceeds badge width')
    mask = bytearray(width * height)
    cursor = width - text_width - 4
    for char in text:
        glyph = glyphs[char]
        raw = zlib.decompress(base64.b64decode(glyph['zlib_base64'], validate=True))
        if len(raw) != 256 or hashlib.sha256(raw).hexdigest() != glyph['sha256'] or set(raw) - {0, 1, 2}:
            raise ValueError('frozen version glyph drift')
        for i, value in enumerate(raw):
            px, py = cursor + i % 16, 2 + i // 16
            if value:
                if not 0 <= px < width or not 0 <= py < height:
                    raise ValueError('version glyph exceeds badge rectangle')
                offset = py * width + px
                mask[offset] = max(mask[offset], value)
        cursor += glyph['advance']
    mask = bytes(mask)
    x, y = 464, 416
    output = bytearray(original)
    for offset, value in enumerate(mask):
        if value:
            output[(y + offset // width)*640 + x + offset % width] = indexes[value - 1]
    return {'text': text, 'record_index': 2, 'rectangle': [x, y, width, height],
            'source_record_sha256': hashlib.sha256(decoded[record.offset:record.end]).hexdigest(),
            'palette_indexes': indexes, 'mask_sha256': hashlib.sha256(mask).hexdigest(),
            'mask_zlib_base64': base64.b64encode(zlib.compress(mask, 9)).decode(),
            'output_image_sha256': hashlib.sha256(output).hexdigest(),
            'latest_release_tag': (text.split('+')[0] if '+' in text else
                                   contract.get('version_badge', {}).get('latest_release_tag', text)),
            'glyphs': glyphs, 'authoring': authoring}


def refresh_current_badge(root: Path = ROOT, *, text: str | None = None, font_path: Path | None = None) -> str:
    text = text or version_text(root)
    badge = freeze(text, font_path, root=root)
    path = root / 'config/assets/title-menu-zh.json'
    contract = json.loads(path.read_text())
    contract['version_badge'] = badge
    data = (json.dumps(contract, ensure_ascii=False, indent=2) + '\n').encode()
    if path.read_bytes() != data:
        path.write_bytes(data)
    component_path = root / 'config/full-story-components.json'
    component = json.loads(component_path.read_text())
    component['title_menu'].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    component_data = (json.dumps(component, ensure_ascii=False, indent=2) + '\n').encode()
    if component_path.read_bytes() != component_data:
        component_path.write_bytes(component_data)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', help='override, e.g. v0.5.0; default: tag or latest release + date')
    parser.add_argument('--font', type=Path, help='regenerate the frozen 10px glyphs; Pillow is needed only for authoring')
    args = parser.parse_args()
    print('frozen:', refresh_current_badge(text=args.text, font_path=args.font))


if __name__ == '__main__':
    main()
