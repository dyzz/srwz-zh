"""Add transparent Chinese captions while preserving every source quad."""
import sys,struct,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.tim2 import parse_tim2
from srwz.parallel import map_processes
from srwz.tim2_writeback import swizzle_psmt8, unswizzle_psmt8, _csm1_palette_offset
from srwz.psmt4 import swizzle_psmt4, unswizzle_psmt4
from srwz.imagemagick import render_grayscale_text_mask,write_rgba8_png
from srwz.codec import encode,decode_production

def records(data):
 n,base=struct.unpack_from('<II',data)
 return [data[base+o:base+o+s] for o,s in [struct.unpack_from('<II',data,8+i*8) for i in range(n)]]

def decode(a):
 word,*tables=struct.unpack_from('<5I',a); frames=word&0xffffff;flags=word>>24
 stride=48-14*(flags&1!=0)-8*(flags&2!=0)-6*(flags&4!=0)-2*(flags&8!=0)-2*(flags&16!=0)
 offsets=struct.unpack_from('<%dH'%(frames+2),a,20); begin=20+(frames+2)*2
 quads=[]
 for i in range(offsets[frames]):
  p=begin+i*stride
  def take(n):
   nonlocal p
   x=a[p:p+n];p+=n;return x
  def lookup(table,n):
   return a[table+int.from_bytes(take(2),'little')*n:][:n] if table else take(n)
  head=lookup(tables[2],4);xy=take(16)
  if flags&1: rgb=lookup(tables[0],16)
  elif flags&2:rgb=b''.join(lookup(tables[0],4) for _ in range(4))
  else:rgb=take(16)
  uv=lookup(tables[1],8);end=lookup(tables[3],4)
  assert p==begin+(i+1)*stride
  quads.append(head+xy+rgb+uv+end)
 return frames,offsets,quads


FONT_POINT_SIZE = 32  # final 640x448 display-space size
# Texels per display pixel (across, down). The caption spans 512x40 display
# pixels (x64..576, y388..428 of 640x448), i.e. 20 native 640x224 field rows.
# Upscaling renderers (ARMSX2/PCSX2 at 6x) sample at display resolution or
# above: a 1:1 native texture (20 rows, 2026-10-13 V7) puts samples on texel
# edges and alternates rows between fields (jitter, black lines); two texture
# rows per native row stays stable (V6). The runtime filters the atlas
# bilinearly, so at native resolution the two rows average into one and
# upscaled output magnifies smoothly. Doubling across (2, 1) was not visibly
# sharper in ARMSX2 (2026-10-14) and nearly fills GS memory for two effects.
CAPTION_SCALE = (1, 1)


# Narrower fallback for an effect whose GS memory cannot hold the wide atlas.
FALLBACK_SCALE = (1, 1)


# Drawn caption width in display pixels. GS texture coordinates are 10.4 fixed
# point (U < 1024 texels), so a 1024-texel-wide line must stop short of the
# atlas edge: 508 display pixels = 1016 texels at scale 2, 508 at scale 1.
CAPTION_DISPLAY_WIDTH = 508


def caption_geometry(scale=None):
    """(drawn texture width, rows per caption line) for ``scale`` (default CAPTION_SCALE)."""
    sx, sy = CAPTION_SCALE if scale is None else scale
    return CAPTION_DISPLAY_WIDTH * sx, 40 * sy


def atlas_width(scale=None):
    sx, _ = CAPTION_SCALE if scale is None else scale
    return 512 * sx


def _native_text_mask(text, font, point_size=None, scale=None):
    """Render one caption line at texture resolution.

    The text is drawn isotropically at max(scale) (4x supersampled), then box
    filtered by whole factors down to the texture's per-axis resolution.
    """
    sx, sy = CAPTION_SCALE if scale is None else scale
    scale = max(sx, sy)
    if scale % sx or scale % sy:
        raise ValueError(f'caption scale {(sx, sy)} needs integer filter factors')
    point_size = FONT_POINT_SIZE if point_size is None else point_size
    full_w, full_h = CAPTION_DISPLAY_WIDTH * scale, 40 * scale
    full = render_grayscale_text_mask('/opt/homebrew/bin/magick', font, text,
        width=full_w, height=full_h, point_size=point_size * scale,
        stroke_gray='black', stroke_width=0, fill_stroke_width=.35 * scale,
        supersample_factor=4)
    width, height = caption_geometry((sx, sy))
    fx, fy = scale // sx, scale // sy
    if (fx, fy) == (1, 1):
        mask = full
    else:
        mask, area = bytearray(width * height), fx * fy
        for y in range(height):
            rows = [full[(y * fy + yy) * full_w:(y * fy + yy + 1) * full_w] for yy in range(fy)]
            column = [sum(values) for values in zip(*rows)] if fy > 1 else rows[0]
            for x in range(width):
                mask[y * width + x] = (sum(column[x * fx:(x + 1) * fx]) + area // 2) // area
        mask = bytes(mask)
    # The longest caption must fit with room for its outline and shadow.
    edge = 3 * sx
    if any(mask[y * width + x] for y in range(height)
           for x in (*range(edge), *range(width - edge, width))):
        raise ValueError(f'Caption exceeds its text area: {text!r}')
    return mask


def _dilate(buf, width, height, rx, ry):
    """Square max filter (separable): rx texels across, ry texels down."""
    rows = [buf[y * width:(y + 1) * width] for y in range(height)]
    wide = []
    for row in rows:
        shifted = [row] + [bytes(d) + row[:-d] for d in range(1, rx + 1)] \
                        + [row[d:] + bytes(d) for d in range(1, rx + 1)]
        wide.append(bytes(map(max, *shifted)))
    blank = bytes(width)
    out = bytearray()
    for y in range(height):
        band = [wide[yy] if 0 <= yy < height else blank for yy in range(y - ry, y + ry + 1)]
        out += bytes(map(max, *band))
    return bytes(out)


def _atlas(captions, font, outdir, point_size=None, scale=None):
    scale = CAPTION_SCALE if scale is None else scale
    line_width, row_height = caption_geometry(scale)
    width = atlas_width(scale)
    height = max(128, 1 << (len(captions) * row_height - 1).bit_length())
    assert height <= 1024
    atlas = bytearray(width * height)
    # Outline 2 display pixels each way; shadow 1 pixel right, 2 lines down.
    scale_x, scale_y = scale
    rx, ry, sx, sy = 2 * scale_x, 2 * scale_y, scale_x, 2 * scale_y
    for i, caption in enumerate(captions):
        mask = _native_text_mask(caption['chinese_draft'], font, point_size, scale)
        outline = _dilate(mask, line_width, row_height, rx, ry)
        shadow = bytes(sy * line_width) + b''.join(
            bytes(sx) + outline[y * line_width:(y + 1) * line_width - sx] for y in range(row_height - sy))
        for j, (white, edge, shade) in enumerate(zip(mask, outline, shadow)):
            black = max(edge, round(shade * .35))
            alpha = white + black * (255 - white) / 255
            coverage = round(alpha * 15 / 255)
            gray = round((white / alpha if alpha else 0) * 15)
            y, x = divmod(j, line_width)
            atlas[(i * row_height + y) * width + x] = coverage * 16 + gray if coverage else 0
    palette = [(i % 16 * 17,) * 3 + (round((i // 16) * 128 / 15),) for i in range(256)]
    return width, height, row_height, atlas, palette


class CaptionMemoryError(ValueError):
    """The caption atlas does not fit the effect's native GS memory budget."""


def _caption_texture(rec, quads, captions, font, outdir, scale=None, vram_limit=0x4000):
    """Append a separate caption picture using a conservatively unused palette bank.

    Original used pixels and palette entries remain byte-identical. The native
    effect texture cache has eight picture/CBP slots per texture group.
    """
    scale = CAPTION_SCALE if scale is None else scale
    width, height, row_height, atlas, palette = _atlas(captions, font, outdir, scale=scale)
    eight = parse_tim2(rec[3])
    # Both native draw forms can sample textures. In particular 0x19 records
    # use the image slot even though bit 1 is clear (effect 256 uses image 1).
    # Treat every declared texture slot as live, including non-textured records,
    # and never replace an existing picture based on a flag heuristic.
    used_banks = {q[46] & 7 for q in quads if q[47] & 3 == 0}
    used_pictures = {q[47] >> 2 for q in quads if q[47] & 3 == 0}
    spare_banks = [b for b in range(8) if b not in used_banks]
    use_eight = bool(spare_banks and len(eight.pictures) < 8)
    if use_eight:
        record_index, group = 3, 0
        bank = spare_banks[0]
        picture_index = len(eight.pictures)
        texture = rec[record_index]
        parsed = eight
        pixels = swizzle_psmt8(bytes(atlas), width, height)
        assert unswizzle_psmt8(pixels, width, height) == bytes(atlas)
        owner = parsed.pictures[0]
        old_colors = owner.clut_color_count
        colors = max(old_colors, (bank + 1) * 256)
        raw_clut = bytearray(texture[owner.offset + owner.header_size + owner.image_size:owner.offset + owner.total_size])
        raw_clut.extend(bytes(colors * 4 - len(raw_clut)))
        for n, color in enumerate(palette):
            at = bank * 1024 + _csm1_palette_offset(n) * 4
            raw_clut[at:at + 4] = bytes(color)
        palette_byte = bank
    else:
        record_index, group = 2, 1
        texture = rec[record_index]
        parsed = parse_tim2(texture)
        owner = parsed.pictures[0]
        picture_index = len(parsed.pictures)
        assert picture_index < 8
        assert owner.clut_color_count % 16 == 0
        used_four_banks = {q[46] >> 3 for q in quads if q[47] & 3 == 1}
        bank = next(b for b in range(min(16, owner.clut_color_count // 16)) if b not in used_four_banks)
        colors = owner.clut_color_count
        old_colors = owner.clut_color_count
        compact = [(0, 0, 0, 0), (0, 0, 0, 16), (0, 0, 0, 32), (0, 0, 0, 64),
                   (0, 0, 0, 96), (0, 0, 0, 128), (48, 48, 48, 128), (96, 96, 96, 128),
                   (160, 160, 160, 128), (224, 224, 224, 128), (255, 255, 255, 128),
                   (255, 255, 255, 32), (255, 255, 255, 64), (255, 255, 255, 96),
                   (255, 255, 255, 112), (192, 192, 192, 96)]
        def premul(c):
            return (c[0] * c[3] / 128, c[1] * c[3] / 128, c[2] * c[3] / 128, c[3] * 2)
        target = [premul(c) for c in compact]
        remap = [min(range(16), key=lambda n: sum((a - b) ** 2 for a, b in zip(premul(c), target[n]))) for c in palette]
        atlas = bytearray(remap[i] for i in atlas)
        palette = compact
        pixels = swizzle_psmt4(bytes(atlas), width, height, row_major_pages=True)
        assert unswizzle_psmt4(pixels, width, height, row_major_pages=True) == bytes(atlas)
        raw_clut = bytearray(texture[owner.offset + owner.header_size + owner.image_size:owner.offset + owner.total_size])
        raw_clut.extend(bytes(colors * 4 - len(raw_clut)))
        for n, color in enumerate(palette):
            logical = bank * 16 + n
            at = ((logical & ~255) + _csm1_palette_offset(logical & 255)) * 4
            raw_clut[at:at + 4] = bytes(color)
        palette_byte = bank << 3
    original_clut = texture[owner.offset + owner.header_size + owner.image_size:owner.offset + owner.total_size]
    if group == 1:
        for b in used_four_banks:
            for n in range(16):
                at = _csm1_palette_offset(b * 16 + n) * 4
                assert raw_clut[at:at + 4] == original_clut[at:at + 4]
    else:
        for b in used_banks:
            assert raw_clut[b * 1024:(b + 1) * 1024] == original_clut[b * 1024:(b + 1) * 1024]
    chunks = [bytearray(texture[p.offset:p.offset + p.total_size]) for p in parsed.pictures]
    chunks[0] = chunks[0][:owner.header_size + owner.image_size] + raw_clut
    struct.pack_into('<II', chunks[0], 0, len(chunks[0]), len(raw_clut))
    struct.pack_into('<H', chunks[0], 14, colors)
    header = bytearray(texture[owner.offset:owner.offset + owner.header_size])
    struct.pack_into('<III', header, 0, len(header) + len(pixels), 0, len(pixels))
    struct.pack_into('<H', header, 14, 0)
    struct.pack_into('<HH', header, 20, width, height)
    assert picture_index == len(chunks)
    chunks.append(header + pixels)
    file_header = bytearray(texture[:parsed.pictures[0].offset])
    struct.pack_into('<H', file_header, 6, len(chunks))
    rec[record_index] = bytes(file_header + b''.join(chunks))
    final = parse_tim2(rec[record_index])
    for index, old in enumerate(parsed.pictures):
        new = final.pictures[index]
        assert texture[old.offset + old.header_size:old.offset + old.header_size + old.image_size] == rec[record_index][new.offset + new.header_size:new.offset + new.header_size + new.image_size]
    preview = bytearray()
    for index in atlas:
        r, g, b, a = palette[index]
        preview += bytes((r, g, b, min(255, a * 2)))
    write_rgba8_png('/opt/homebrew/bin/magick', bytes(preview), outdir / 'subtitle-atlas-preview.png', width=width, height=height)
    # SLPS_259.20 1a9d50/1a99d0/1a9840 allocate these groups consecutively.
    native_vram_end = 0x2fc0
    for record_index in (2, 3):
        pictures = parse_tim2(rec[record_index]).pictures
        native_vram_end += min(8, (pictures[0].clut_color_count + 255) // 256) * 4
        native_vram_end += sum(p.width * p.height // (512 if record_index == 2 else 256)
                               for p in pictures if p.image_size)
    if native_vram_end > vram_limit:
        raise CaptionMemoryError(f'caption atlas {width}x{height} ends at block {native_vram_end:#x} > {vram_limit:#x}')
    return (caption_geometry(scale)[0], row_height), picture_index, group, palette_byte, {'texture_group': group, 'picture': picture_index,
        'palette_bank': bank, 'bits_per_pixel': 8 if use_eight else 4, 'atlas_size': [width, height],
        'native_vram_end_block': native_vram_end,
        'original_used_images_and_clut_bytes_preserved': True,
        'all_original_picture_pixels_byte_identical': True,
        'picture_allocation': 'append only; all declared quad references treated as live',
        'text_supersample_factor': 4,
        'authoring_to_native_filter': f'4x supersampled, box filtered to {CAPTION_SCALE} texels per display pixel; two or more rows per native row; GS point sampling',
        'caption_texture_scale': list(scale),
        'caption_line_texels': list(caption_geometry()),
        'swizzle_roundtrip': True}


def _pack_records(rec):
    # Native 1ca690 derives a record length from the next offset, including
    # the last record. Keep the extra end-offset pair before the payload.
    # Omitting it can turn the final CCC table into a huge native memcpy.
    base = (8 + 8 * (len(rec) + 1) + 15) & ~15
    wrapper = bytearray(base)
    struct.pack_into('<II', wrapper, 0, len(rec), base)
    for index, record in enumerate(rec):
        wrapper += bytes((-len(wrapper)) % 16)
        struct.pack_into('<II', wrapper, 8 + index * 8, len(wrapper) - base, len(record))
        wrapper += record
    wrapper += bytes((-len(wrapper)) % 16)
    struct.pack_into('<II', wrapper, 8 + len(rec) * 8, len(wrapper) - base, 0)
    for index, record in enumerate(rec):
        start = struct.unpack_from('<I', wrapper, 8 + index * 8)[0]
        end = struct.unpack_from('<I', wrapper, 8 + (index + 1) * 8)[0]
        assert end - start == (len(record) + 15) & ~15
    return bytes(wrapper)


def build(src, captions, font, outdir, compression=None, vram_limit=0x4000):
    """Preserve voice/model records and add the larger, lower caption overlay.

    The atlas uses CAPTION_SCALE unless that exceeds ``vram_limit`` (the native
    GS block budget; lower for effects that keep a feedback backup), in which
    case it falls back to FALLBACK_SCALE. The width travels in ``runtime_draw``.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    before = records(src)
    frames, offsets, quads = decode(before[1])
    for scale in dict.fromkeys((CAPTION_SCALE, FALLBACK_SCALE)):
        rec = list(before)
        try:
            (width, row_height), picture, group, bank, texture_receipt = _caption_texture(
                rec, quads, captions, font, outdir, scale=scale, vram_limit=vram_limit)
            break
        except CaptionMemoryError:
            if scale == FALLBACK_SCALE:
                raise
    edited_record = 3 if texture_receipt['bits_per_pixel'] == 8 else 2
    assert all(bytes(r) == before[i] for i, r in enumerate(rec) if i != edited_record)
    wrapper = _pack_records(rec)
    packed = encode(wrapper, strategy='rust-fit', **(compression or {}))
    assert decode_production(packed).output == wrapper
    (outdir / 'subtitled.bin').write_bytes(wrapper)
    (outdir / 'subtitled.lz').write_bytes(packed)
    return bytes(wrapper), packed, {'source': len(src), 'new': len(wrapper), 'packed': len(packed),
        'original_primitives': len(quads), 'new_primitives': len(quads), 'caption_count': len(captions),
        'voice_and_model_records_byte_identical': True, 'original_animation_byte_identical': True,
        'texture': texture_receipt, 'runtime_draw': {'row_height': row_height, 'width': width, 'picture': picture, 'group': group, 'palette_byte': bank},
        'style': 'white face, black outline and shadow; transparent outside glyphs',
        'font_point_size': FONT_POINT_SIZE, 'screen_rect': [320 - CAPTION_DISPLAY_WIDTH // 2, 388, 320 + CAPTION_DISPLAY_WIDTH // 2, 428], 'position': 'screen bottom center',
        'compression': {'strategy': 'rust-fit', **(compression or {})}}


def _build_job(job):
    src, captions, font, outdir, compression, vram_limit = job
    return build(src, captions, Path(font), Path(outdir), compression, vram_limit)


def build_many(jobs):
    """``build`` for several effect chunks; each job is
    ``(src, captions, font, outdir, compression, vram_limit)``.

    Rendering and swizzling are pure Python per chunk, so the chunks are
    distributed over worker processes; results come back in job order.
    """
    return map_processes(_build_job, [(bytes(src), list(captions), str(font), str(outdir), compression, vram_limit)
                                      for src, captions, font, outdir, compression, vram_limit in jobs])


# Effect 257 keeps a full-screen feedback backup from GS block 0x3D00.
FEEDBACK_BACKUP_BLOCK = 0x3D00


def vram_limit_for(effect):
    return FEEDBACK_BACKUP_BLOCK if effect == 257 else 0x4000
