import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.zh_hant.assemble_dual import disc_identity
from special_disc.resource_view import ResourceView
from srwz.multilang_release import verify, verify_wide
from widescreen.build import build


class MultilangReleaseTests(unittest.TestCase):
    def test_sparse_sp_input_has_logical_disc_identity(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.iso'
            source.write_bytes(b'abcdef')
            view = ResourceView.create(Path(tmp) / 'sp.spview', source)
            with view.open('r+b') as stream:
                stream.seek(2)
                stream.write(b'XY')
            self.assertEqual(disc_identity(view), {'size': 6, 'sha256': hashlib.sha256(b'abXYef').hexdigest()})
            self.assertNotEqual(disc_identity(view), disc_identity(source))

    def test_freeze_requires_every_region(self):
        config = {'tag': 'v0.5.2', 'validation': 'manifests/releases/v0.5.2/validation.json', 'skip': 'built_in'}
        validation = {'status': 'multilang_widescreen_readback_passed', 'batches': {'sc': {}}, 'editions': {}}
        with self.assertRaisesRegex(ValueError, 'incomplete edition or region'):
            verify(Path('.'), config, validation)

    def test_widescreen_never_replaces_input(self):
        with TemporaryDirectory() as tmp:
            disc = Path(tmp) / 'unchanged.iso'
            disc.write_bytes(b'previous')
            with self.assertRaisesRegex(ValueError, 'aliases'):
                build('original', disc, disc, Path(tmp), Path(tmp), replace=True)
            self.assertEqual(disc.read_bytes(), b'previous')

    def test_wide_receipt_is_checked_against_disc_members_and_words(self):
        from zh_hant.editions import EDITIONS
        title = EDITIONS['sp'].title_site[0]
        effect = b'checked effect'
        words = {title: 0x0c300000, 0x800000: 0}
        wide = {'elf_words': {hex(title): words[title]},
                'wide_enabled': {'address': 0x800000, 'default': 0},
                'members': {'EFF/VEFF2DX.BIN': {'size': len(effect),
                                                'sha256': hashlib.sha256(effect).hexdigest()}}}
        with patch('zh_hant.assemble_dual.Disc') as disc, patch('zh_hant.assemble_dual.Elf') as elf:
            disc.return_value.read.return_value = effect
            elf.return_value.word.side_effect = words.__getitem__
            verify_wide(Path('candidate.iso'), 'sp', wide)
            words[title] += 1
            with self.assertRaisesRegex(ValueError, 'ELF words differ'):
                verify_wide(Path('candidate.iso'), 'sp', wide)
            words[title] -= 1
            disc.return_value.read.return_value = b'other effect'
            with self.assertRaisesRegex(ValueError, 'effect member differs'):
                verify_wide(Path('candidate.iso'), 'sp', wide)
