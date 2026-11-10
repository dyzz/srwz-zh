"""The gallery's map-dialogue snapshot must follow the reviewed corpus."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.event_gallery.author_talk import OUT, snapshot_drift


class TalkSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.scenes = json.loads(OUT.read_text(encoding='utf-8'))['scenes']

    def test_snapshot_matches_corpus(self):
        self.assertEqual(snapshot_drift(self.scenes), [])

    def test_gallery_uses_map_width_before_encoding(self):
        from special_disc.event_gallery.apply import encode_talk
        scenes = copy.deepcopy(self.scenes)
        record = next(r for d in scenes.values() for sec in d['sections']
                      for r in sec['records'] if 'text' in r)
        # Fits the 483px conversation box, but exceeds the 420px map box.
        record['text'] = '中' * 21
        with self.assertRaisesRegex(ValueError, 'story_map geometry'):
            encode_talk(scenes, Path('/unused-codebook'))

    def test_all_expanded_gallery_lines_fit_map_box(self):
        from srwz.build_layout import verify_stored
        rows = [(r['source']['id'], r['text'], False) for d in self.scenes.values()
                for sec in d['sections'] for r in sec['records'] if 'text' in r]
        self.assertEqual(verify_stored(rows, 'story_map'), len(rows))

    def test_text_and_speaker_edits_are_reported(self):
        scenes = copy.deepcopy(self.scenes)
        lines = [(scene, r) for scene, d in scenes.items() for s in d['sections']
                 for r in s['records'] if 'source' in r]
        edited, named = lines[0], next(line for line in lines[1:] if line[1]['speaker'])
        edited[1]['text'] += '！'
        named[1]['speaker'] += '？'
        self.assertEqual(snapshot_drift(scenes),
                         [f"{scene} {r['source']['id']}" for scene, r in (edited, named)])


if __name__ == '__main__':
    unittest.main()
