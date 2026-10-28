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
