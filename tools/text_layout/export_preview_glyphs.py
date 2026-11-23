"""Export the complete Original game font cells and character indices for all locales.

Reads the manifest-verified SLPS, VT1 and proposal in prepared edition projects.
--hans-project, --tw-project and --hk-project select newer component builds.
Without overrides, reproduce the workspaces recorded in the published indices.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image
from export_story_ink import ROOT, latin_bank, load_font_component
from srwz.font import GLYPH_SIZE, decode_glyph
from srwz.text import normalize_original_fullwidth_ascii

ASSETS = ROOT / 'shared/text-layout/assets'
LOCALES = (
    ('zh', 'native-glyphs.json', 'hans_project', 'candidate.json'),
    ('zh-hant', 'native-glyphs.zh-hant.json', 'tw_project', 'candidate-zh-hant-tw.json'),
    ('zh-hant-hk', 'native-glyphs.zh-hant-hk.json', 'hk_project', 'candidate-zh-hant-hk.json'),
)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def native_atlas(project, locale, output):
    traditional = locale != 'zh'
    font, glyphs, banks, manifest = load_font_component(project, traditional)
    # A region's prepared view installs its ledger at the same path as Simplified.
    ledger = project/'config/encoding/zh-release-font-assignments.json'
    if bool(read(ledger).get('zh_hant')) != traditional:
        raise ValueError(f'{locale}: incorrect component language')
    count, partial = divmod(len(font), GLYPH_SIZE)
    if partial:
        raise ValueError('Decoded VT1 contains a partial font cell')
    # Fold stock fullwidth Latin/digits just as the production writer does. A
    # CP932 identity displaced by a localized assignment must not get its old cell.
    for ch in '０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ':
        glyphs[ch] = glyphs[normalize_original_fullwidth_ascii(ch)]

    # Place tiles in native index order, including unassigned slots. Coordinates
    # are reversible even for glyphs without an authorable Unicode identity.
    columns = 64
    def cell(index):
        return [24 * (index % columns), 24 * (index // columns)]

    image = Image.new('RGBA', (24*columns, 24*((count+columns-1)//columns)), 'white')
    alpha = Image.new('L', image.size)
    for index in range(count):
        pixels = decode_glyph(font, index)
        tile = Image.frombytes('L', (24,24), bytes(p*17 for p in pixels))
        alpha.paste(tile, cell(index))
    image.putalpha(alpha)
    from io import BytesIO
    stream = BytesIO()
    image.save(stream, 'PNG', optimize=True)
    binary = stream.getvalue()
    image_sha = sha256(binary)
    filename = f'native-glyphs.{image_sha[:12]}.png'
    (output/filename).write_bytes(binary)
    bank_base = latin_bank.base_glyph_index()
    # Only expose truly readable cells, apart from genuine whitespace.
    visible = {ch:cell(i) for ch,i in sorted(glyphs.items())
               if ch.isspace() or any(font[i*GLYPH_SIZE:(i+1)*GLYPH_SIZE])}
    for ch,index in banks.items():
        if not any(font[index*GLYPH_SIZE:(index+1)*GLYPH_SIZE]):
            raise ValueError(f'{locale}: empty Latin cell for {ch}')
    badge = read(project/'config/assets/title-menu-zh.json')['version_badge']['text']
    return dict(
        schemaVersion=2, locale=locale, cellSize=24, width=image.width, height=image.height,
        image=filename, imageSha256=image_sha, fontDecodedSha256=sha256(font),
        manifestSha256=sha256((project/'manifests/zh-release-font-validation.json').read_bytes()),
        proposalSha256=manifest['proposal']['sha256'], ledgerSha256=sha256(ledger.read_bytes()),
        componentSha256={k:manifest['font_component'][k]['sha256'] for k in ('slps','vt1')},
        sourceProject=project.relative_to(ROOT).as_posix() if project.is_relative_to(ROOT) else str(project),
        edition='Original', buildVersion=badge, glyphCount=count, linearAddressing=traditional,
        glyphs=visible, latinBank=dict(baseGlyphIndex=bank_base,
            cells=[cell(i) for i in latin_bank.glyph_indices()],
            glyphs={ch:cell(i) for ch,i in sorted(banks.items())}),
        source='Decoded Original VT1 font component; native glyph index order; 24x24 pixels; alpha=nibble*17.',
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ASSETS)
    for flag in ('--hans-project', '--tw-project', '--hk-project'):
        parser.add_argument(flag, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for locale, name, option, receipt in LOCALES:
        project = getattr(args, option)
        if project is None:
            index = read(ASSETS/name) if (ASSETS/name).exists() else {}
            project = ROOT/(index.get('sourceProject') or read(ROOT/'manifests/editions/original'/receipt)['workspace'])
        atlas = native_atlas(project.resolve(), locale, args.output)
        (args.output/name).write_text(json.dumps(atlas,ensure_ascii=False,separators=(',',':'))+'\n')
        print(locale, atlas['glyphCount'], 'native cells,', len(atlas['glyphs']), 'mapped characters,', atlas['image'])


if __name__ == '__main__':
    main()
