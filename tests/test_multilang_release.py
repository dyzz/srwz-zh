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

    def test_wide_disc_retains_original_cheat_menu_and_dispatch(self):
        from build_builtin_cheats import BASE, SITES
        from zh_hant.editions import ORIGINAL
        payload = b'menu code'
        hooks = {addr: bytes.fromhex('01020304') * (len(spec) - 1) for addr, spec in SITES.items()}
        menu = {'address': BASE, 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                'hooks': {hex(addr): code.hex() for addr, code in hooks.items()}}
        title = ORIGINAL.title_site[0]
        wide = {'elf_words': {hex(title): 0x0c300000}, 'wide_enabled': {'address': 0x800000, 'default': 0},
                'members': {'EFF/VEFF2DX.BIN': {'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}}}
        data = {BASE: payload, **hooks}
        with patch('zh_hant.assemble_dual.Disc') as disc, patch('zh_hant.assemble_dual.Elf') as elf:
            disc.return_value.read.return_value = b''
            elf.return_value.word.side_effect = {title: 0x0c300000, 0x800000: 0}.__getitem__
            elf.return_value.get.side_effect = lambda addr, size: data[addr][:size]
            verify_wide(Path('candidate.iso'), 'original', wide, menu)
            for address in (BASE, next(iter(hooks))):
                with self.subTest(address=address), patch.dict(data, {address: bytes(len(data[address]))}):
                    with self.assertRaisesRegex(ValueError, 'built-in cheat menu differs'):
                        verify_wide(Path('candidate.iso'), 'original', wide, menu)

    def test_sp_menu_readback_restores_only_the_three_widescreen_imports_for_hashing(self):
        import struct
        from build_builtin_cheats import MENU_BASE, menu_sites
        from zh_hant.editions import SP

        base = MENU_BASE['sp']
        old_imports = [0x81D4F0, 0x81CE3C, 0x81CF04]
        wide_imports = [0x81D790, 0x81CF78, 0x81D010]
        code = b'menu dispatch'
        payload = struct.pack('<3I', *old_imports) + code
        hooks = {addr: bytes(4 * (len(spec) - 1)) for addr, spec in menu_sites('sp').items()}
        menu = {'address': base, 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                'hooks': {hex(addr): data.hex() for addr, data in hooks.items()}, 'language_imports': old_imports}
        words = {base + 4*i: addr for i, addr in enumerate(wide_imports)}
        words[SP.title_site[0]] = 0x0C300000
        wide = {'elf_words': {hex(k): v for k, v in words.items()}, 'wide_enabled': {'address': 0x800000},
                'members': {'EFF/VEFF2DX.BIN': {'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}}}
        wide['wide_enabled']['default'] = 0
        data = {base: struct.pack('<3I', *wide_imports) + code, **hooks}
        with patch('zh_hant.assemble_dual.Disc') as disc, patch('zh_hant.assemble_dual.Elf') as elf:
            disc.return_value.read.return_value = b''
            elf.return_value.word.side_effect = {**words, 0x800000: 0}.__getitem__
            elf.return_value.get.side_effect = lambda addr, size: data[addr][:size]
            verify_wide(Path('sp.iso'), 'sp', wide, menu)
            data[base] = payload
            with self.assertRaisesRegex(ValueError, 'SP menu language imports differ'):
                verify_wide(Path('sp.iso'), 'sp', wide, menu)
            data[base] = struct.pack('<3I', *wide_imports) + b'bad execution'
            with self.assertRaisesRegex(ValueError, 'built-in cheat menu differs'):
                verify_wide(Path('sp.iso'), 'sp', wide, menu)
