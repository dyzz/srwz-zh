"""Portable proof rejects changed evidence and independently verifies final bytes."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.release_typography import verified_typography_input

class PortableTypographyTests(unittest.TestCase):
    def test_reconstructs_only_elf_and_cleans_up_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'final.iso';target.write_bytes(b'A'*2048+b'NEW!'+b'B'*64)
            def lock(name,raw):
                p=root/name;p.write_bytes(raw)
                return dict(path=name,size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            old=b'A'*2048+b'OLD!'+b'B'*64
            proof={'source_sha256':hashlib.sha256(old).hexdigest(),'size':len(old),'member':'ELF'}
            receipt={'input':{'sha256':proof['source_sha256'],'size':len(old)},'verification':proof,
                     'original_elf':lock('before.elf',b'OLD!'),'metrics':lock('metrics.mjs',b'metrics')}
            def verify(inputs,edition,source,output,expected):
                self.assertEqual(source.read_bytes(),old)
                self.assertEqual(output.read_bytes(),target.read_bytes())
                self.assertEqual((inputs/'shared/text-layout/proportional-metrics.mjs').read_bytes(),b'metrics')
                raise ValueError('deliberate proof failure')
            with patch('srwz.release_typography.scan_iso9660'), \
                 patch('srwz.release_typography.member_map',return_value={'ELF':SimpleNamespace(extent_lba=1,size=4)}), \
                 patch('srwz.release_typography.verify_iso',side_effect=verify) as check:
                with self.assertRaisesRegex(ValueError,'deliberate'):
                    with verified_typography_input(root,target,'best',receipt):self.fail('yielded invalid image')
                check.assert_called_once()
            self.assertEqual(list((root/'build/iso/.tmp').iterdir()),[])
            (root/'before.elf').write_bytes(b'BAD!')
            with self.assertRaisesRegex(ValueError,'evidence drift'):
                with verified_typography_input(root,target,'best',receipt):pass
            self.assertEqual(target.read_bytes(),b'A'*2048+b'NEW!'+b'B'*64)
