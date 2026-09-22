import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz import daily_test
from srwz.battle_square_skip import apply_battle_square_skip, BattleSquareSkipError
from srwz.edition import EditionError
from srwz.release_inputs import sha256_file
from tests.test_battle_square_skip import _synthetic_executable

REPO = Path(__file__).resolve().parents[1]


class DailyTestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for relative in ('config/full-story-components.json', 'config/products/special-disc/battle-square-skip.json'):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, path)

    def fixture(self, edition, enabled=True):
        raw = ('config/products/special-disc/battle-square-skip.json' if edition == 'sp'
               else 'config/full-story-components.json')
        contract = json.loads((self.root / raw).read_text())
        if edition != 'sp':
            contract = contract['battle_square_skip']
        self.assertTrue(contract['enabled'])
        executable = _synthetic_executable(contract, edition)
        if enabled:
            executable, _ = apply_battle_square_skip(executable, contract, edition)
        source = self.root / f'build/iso/current-{edition}.iso'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(bytes(2048) + executable)
        member = SimpleNamespace(extent_lba=1, size=len(executable))
        scanner = patch.object(daily_test, 'scan_iso9660', return_value=[])
        mapper = patch.object(daily_test, 'member_map', return_value={contract['editions'][edition]['member']: member})
        scanner.start(); mapper.start()
        self.addCleanup(scanner.stop); self.addCleanup(mapper.stop)
        return {'edition_id': edition, 'output': {'path': source.relative_to(self.root).as_posix(),
                'size': source.stat().st_size, 'sha256': sha256_file(source)}}

    def test_all_three_defaults_publish_exact_independent_copies_and_verify_skip(self):
        for edition in ('original', 'best', 'sp'):
            with self.subTest(edition=edition):
                result = self.fixture(edition)
                proof = daily_test.publish_daily_test(self.root, self.root, result)
                self.assertTrue(daily_test.verify_daily_test(self.root, self.root, result, proof)['enabled'])
                self.assertEqual(proof['runtime'], 'not_tested')
                self.assertNotEqual((self.root / proof['path']).stat().st_ino,
                                    (self.root / result['output']['path']).stat().st_ino)
                with (self.root / proof['path']).open('r+b') as handle:
                    handle.write(b'bad')
                with self.assertRaisesRegex(EditionError, 'differs'):
                    daily_test.verify_daily_test(self.root, self.root, result, proof)
                self.assertEqual(sha256_file(self.root / result['output']['path']), result['output']['sha256'])

    def test_wrong_hash_or_disabled_skip_preserves_previous_daily_iso(self):
        for disabled in (False, True):
            result = self.fixture('original', enabled=not disabled)
            target = self.root / 'build/iso/daily-test/current-original-skip.iso'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'previous verified ISO')
            if not disabled:
                result['output']['sha256'] = '0' * 64
            with self.assertRaises((EditionError, BattleSquareSkipError)):
                daily_test.publish_daily_test(self.root, self.root, result)
            self.assertEqual(target.read_bytes(), b'previous verified ISO')
            self.assertFalse(target.with_suffix('.iso.tmp').exists())

    def test_daily_target_cannot_alias_source(self):
        result = self.fixture('original')
        target = self.root / 'build/iso/daily-test/current-original-skip.iso'
        target.parent.mkdir(parents=True)
        target.symlink_to(self.root / result['output']['path'])
        with self.assertRaisesRegex(EditionError, 'alias'):
            daily_test.publish_daily_test(self.root, self.root, result)
        self.assertEqual(sha256_file(self.root / result['output']['path']), result['output']['sha256'])
