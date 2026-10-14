"""Keep original pictures live when native 0x19 records reference them."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.event_gallery import subtitles


def texture(count, bits, colors):
    result = bytearray(struct.pack('<4sBBH8x', b'TIM2', 4, 0, count))
    for index in range(count):
        pixels = bytes([index + 1]) * (16 * 16 * bits // 8)
        palette = bytes((n % 251 for n in range(colors * 4))) if index == 0 else b''
        header = struct.pack('<IIIHHBBBBHHQQII', 48 + len(pixels) + len(palette),
                             len(palette), len(pixels), 48, colors if index == 0 else 0,
                             0, 1, 3, 5 if bits == 8 else 4, 16, 16, 0, 0, 0, 0)
        result += header + pixels + palette
    return bytes(result)


def quad(picture, bank, group):
    result = bytearray(48)
    result[0] = 0x19  # Live native draw form omitted by the old bit-1 filter.
    result[46] = bank if group == 0 else bank << 3
    result[47] = picture << 2 | group
    return bytes(result)


class CaptionTexturePreservationTests(unittest.TestCase):
    def test_live_draw_form_never_loses_picture_or_palette_to_captions(self):
        for picture_count in (2, 8):
            with self.subTest(pictures=picture_count), tempfile.TemporaryDirectory() as tmp:
                records = [b'', b'', texture(1, 4, 32), texture(picture_count, 8, 2048)]
                before = list(records)
                quads = [quad(i, i if picture_count == 8 else 0, 0)
                         for i in range(picture_count)] + [quad(0, 0, 1)]
                atlas = (512, 128, 40, bytearray(512 * 128), [(0, 0, 0, 0)] * 256)
                with patch.object(subtitles, '_atlas', return_value=atlas), \
                     patch.object(subtitles, 'write_rgba8_png'):
                    *_, receipt = subtitles._caption_texture(records, quads, [], Path('font'), Path(tmp))
                group = receipt['texture_group']
                self.assertEqual(receipt['picture'], picture_count if group == 0 else 1)
                self.assertEqual(receipt['palette_bank'], 1)
                for record_index in (2, 3):
                    old = subtitles.parse_tim2(before[record_index]).pictures
                    new = subtitles.parse_tim2(records[record_index]).pictures
                    for original, updated in zip(old, new):
                        self.assertEqual(
                            before[record_index][original.offset + original.header_size:
                                                 original.offset + original.header_size + original.image_size],
                            records[record_index][updated.offset + updated.header_size:
                                                  updated.offset + updated.header_size + updated.image_size])
                    owner, updated = old[0], new[0]
                    a = owner.offset + owner.header_size + owner.image_size
                    b = updated.offset + updated.header_size + updated.image_size
                    if record_index == 2:
                        for color in range(16):
                            at = subtitles._csm1_palette_offset(color) * 4
                            self.assertEqual(before[record_index][a + at:a + at + 4],
                                             records[record_index][b + at:b + at + 4])
                    else:
                        used = 8192 if picture_count == 8 else 1024
                        self.assertEqual(before[record_index][a:a + used],
                                         records[record_index][b:b + used])


class CaptionSamplingTests(unittest.TestCase):
    """2026-10-14: 1:1 native rows (V7) jitter in upscaled renderers; captions keep
    two texture rows per native row and the runtime filters them bilinearly."""

    def test_default_geometry_keeps_two_rows_per_native_row(self):
        self.assertEqual(subtitles.CAPTION_SCALE, (1, 1))
        self.assertEqual(subtitles.caption_geometry(), (508, 40))
        self.assertEqual(subtitles.atlas_width(), 512)
        rendered = bytes(508 * 40)
        with patch.object(subtitles, 'render_grayscale_text_mask', return_value=rendered) as render:
            mask = subtitles._native_text_mask('一', Path('font'))
        self.assertEqual(len(mask), 508 * 40)
        self.assertEqual(render.call_args.kwargs['width'], 508)
        self.assertEqual(render.call_args.kwargs['height'], 40)

    def test_wide_scale_box_filters_rows_to_the_texture(self):
        # (2, 1): drawn at 2x, then each texel averages two authoring rows.
        width, height = 1016, 80
        high = bytearray(width * height)
        for y in (20, 22):  # alternate thin strokes: both must contribute
            high[y * width + 200] = 255
        with patch.object(subtitles, 'render_grayscale_text_mask', return_value=bytes(high)):
            mask = subtitles._native_text_mask('一', Path('font'), scale=(2, 1))
        self.assertEqual(len(mask), 1016 * 40)
        self.assertEqual(mask[10 * 1016 + 200], 128)
        self.assertEqual(mask[11 * 1016 + 200], 128)
        self.assertEqual(sum(mask), 256)

    def test_runtime_filters_bilinearly_with_one_field_offset(self):
        for path in ('tools/special_disc/event_gallery/runtime.S', 'tools/event_subtitles/runtime.S'):
            source = (ROOT / path).read_text()
            self.assertIn('ori     $t1,$t1,0x60    /* MMAG = MMIN = LINEAR */', source, path)
            self.assertIn('ori     $t1,$zero,0x7900', source, path)
            self.assertNotIn('0x7904', source, path)


if __name__ == '__main__':
    unittest.main()
