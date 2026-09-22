import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from special_disc.writeback import slot_codec


class SlotCodecTests(unittest.TestCase):
    def test_fast_success_does_not_run_exhaustive_compressor(self):
        with patch.object(slot_codec, 'reencode_changed_suffix', return_value=b'ok') as encoder:
            self.assertEqual(slot_codec.encode_slot(b'a', b'b', max_output_size=2, original_result=None), b'ok')
        self.assertEqual(encoder.call_count, 1)
        self.assertEqual(encoder.call_args.kwargs['strategy'], 'rust-fit')

    def test_tight_slot_falls_back_without_relaxing_budget(self):
        with patch.object(slot_codec, 'reencode_changed_suffix', side_effect=[slot_codec.SrwzEncodeError('limit'), b'ok']) as encoder:
            slot_codec.encode_slot(b'a', b'b', max_output_size=2, original_result=None)
        self.assertEqual([c.kwargs['strategy'] for c in encoder.call_args_list], ['rust-fit', 'rust-maximum'])
        self.assertTrue(all(c.kwargs['max_output_size'] == 2 for c in encoder.call_args_list))

    def test_preimage_errors_are_not_hidden_by_fallback(self):
        with patch.object(slot_codec, 'reencode_changed_suffix', side_effect=ValueError('preimage')) as encoder:
            with self.assertRaisesRegex(ValueError, 'preimage'):
                slot_codec.encode_slot(b'a', b'b', max_output_size=2, original_result=None)
        self.assertEqual(encoder.call_count, 1)


