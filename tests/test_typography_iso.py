"""Exercise renderer sealing against real edition ELFs in bounded test images."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.typography_iso import seal_iso, verify_iso, EXECUTABLES
from srwz.typography_policy import load_policy


class TypographyIsoTests(unittest.TestCase):
    def test_real_elf_sealing_and_independent_tamper_detection(self):
        for edition in EXECUTABLES:
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as directory:
                elf_path = ROOT / f'work/candidates/tag-free-all-scenes-20261108/{edition}-source.elf'
                if not elf_path.exists():
                    self.skipTest('Local audited edition ELF fixture unavailable')
                elf = elf_path.read_bytes()
                root = Path(directory)
                metrics = root / 'shared/text-layout'
                metrics.mkdir(parents=True)
                (metrics / 'proportional-metrics.mjs').write_bytes((ROOT / 'shared/text-layout/proportional-metrics.mjs').read_bytes())
                iso = root / 'build/iso'
                iso.mkdir(parents=True)
                source, output = iso / 'source.iso', iso / 'candidate.iso'
                source.write_bytes(bytes(4096) + elf + b'outside executable sentinel')
                members = {EXECUTABLES[edition]: SimpleNamespace(extent_lba=2, size=len(elf))}
                # Container metadata is synthetic; real ELF preimages and patch
                # generation, readback and non-executable comparisons are exercised.
                with patch('srwz.typography_iso.scan_iso9660', return_value=None), patch('srwz.typography_iso.member_map', return_value=members):
                    proof = seal_iso(root, edition, source, output)
                    self.assertEqual(proof['payload']['sceneDispatch'], True)
                    exhaustion = proof['payload']['text_atlas_exhaustion']
                    self.assertEqual(exhaustion['after'], '5e000010')
                    at = 4096 + exhaustion['file_offset']
                    self.assertEqual(output.read_bytes()[at:at + 4], bytes.fromhex('5e000010'))
                    self.assertEqual(proof['outside_executable_bytes_compared'], 4096 + 27)
                    self.assertEqual(verify_iso(root, edition, source, output, proof), proof)
                    with output.open('r+b') as stream:
                        stream.seek(at)
                        stream.write(bytes.fromhex(exhaustion['before']))
                    with self.assertRaisesRegex(ValueError, 'regenerated patch'):
                        verify_iso(root, edition, source, output, proof)
                    with output.open('r+b') as stream:
                        stream.seek(at)
                        stream.write(bytes.fromhex(exhaustion['after']))
                    with output.open('r+b') as stream:
                        stream.seek(0)
                        stream.write(b'!')
                    with self.assertRaisesRegex(ValueError, 'outside executable'):
                        verify_iso(root, edition, source, output, proof)
                    with output.open('r+b') as stream:
                        stream.seek(0)
                        stream.write(b'\0')
                        stream.seek(4096)
                        stream.write(b'!')
                    with self.assertRaisesRegex(ValueError, 'regenerated patch'):
                        verify_iso(root, edition, source, output, proof)
                    with self.assertRaisesRegex(ValueError, 'already exists'):
                        seal_iso(root, edition, source, output)

    def test_policy_does_not_depend_on_directory_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(load_policy(root)['mode'], 'native')
            path = root / 'config/text-layout/rendering-mode.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'mode':'proportional','chinese_punctuation':'compact'}))
            self.assertEqual(load_policy(root)['mode'], 'proportional')
            path.write_text('{"mode":"unknown"}')
            with self.assertRaises(ValueError):
                load_policy(root)
