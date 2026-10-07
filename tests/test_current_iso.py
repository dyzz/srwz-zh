import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz import current_iso
from srwz.battle_square_skip import apply_battle_square_skip, BattleSquareSkipError
from tests.test_battle_square_skip import _synthetic_executable

ROOT = Path(__file__).resolve().parents[1]


class CurrentIsoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for relative in ('config/full-story-components.json',
                         'config/products/special-disc/battle-square-skip.json'):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def fixture(self, edition, enabled=True):
        config = ('config/products/special-disc/battle-square-skip.json' if edition == 'sp'
                  else 'config/full-story-components.json')
        contract = json.loads((self.root / config).read_text())
        if edition != 'sp':
            contract = contract['battle_square_skip']
        executable = _synthetic_executable(contract, edition)
        if enabled:
            executable, _ = apply_battle_square_skip(executable, contract, edition)
        iso = self.root / f'current-{edition}.iso'
        iso.write_bytes(bytes(2048) + executable)
        return iso, contract, SimpleNamespace(extent_lba=1, size=len(executable))

    def test_all_three_current_images_verify_without_creating_copies(self):
        for edition in ('original', 'best', 'sp'):
            with self.subTest(edition=edition):
                iso, contract, member = self.fixture(edition)
                before = sorted(p.relative_to(self.root) for p in self.root.rglob('*') if p.is_file())
                with patch.object(current_iso, 'scan_iso9660'), patch.object(
                        current_iso, 'member_map', return_value={contract['editions'][edition]['member']: member}):
                    self.assertTrue(current_iso.verify_skip(iso, self.root, edition)['enabled'])
                self.assertEqual(before, sorted(p.relative_to(self.root) for p in self.root.rglob('*') if p.is_file()))

    def test_current_without_skip_is_rejected(self):
        iso, contract, member = self.fixture('original', enabled=False)
        with patch.object(current_iso, 'scan_iso9660'), patch.object(
                current_iso, 'member_map', return_value={contract['editions']['original']['member']: member}):
            with self.assertRaises(BattleSquareSkipError):
                current_iso.verify_skip(iso, self.root, 'original')

    def test_policy_has_exactly_three_native_current_slots(self):
        config = json.loads((ROOT / 'config/iso/current-isos.json').read_text())
        self.assertEqual(config['expected_count'], 3)
        self.assertEqual({s['slot'] for s in config['slots']},
                         {'current-original', 'current-best', 'current-sp'})
        for slot in config['slots']:
            self.assertNotIn('daily-test', slot['path'])
            self.assertTrue(slot['skip_required'])
