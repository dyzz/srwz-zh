import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.zh_hant import assemble_dual


class MultilangPublishTests(unittest.TestCase):
    def test_failed_readback_leaves_previous_product_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / 'build/iso/test'
            directory.mkdir(parents=True)
            output = directory / 'disc.iso'
            receipt = output.with_suffix('.receipt.json')
            output.write_bytes(b'previous image')
            receipt.write_bytes(b'previous receipt')

            def fail_readback(args, staged, staged_receipt):
                staged.write_bytes(b'unverified image')
                raise SystemExit('readback hk ZHTP patch')

            args = ['assemble_dual.py', '--sc', 'sc.iso', '--tc', 'tc.iso', '--hk', 'hk.iso',
                    '--tc-codebook', 'tc.json', '--out', str(output)]
            with patch.object(assemble_dual, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.object(assemble_dual, 'assemble', side_effect=fail_readback):
                with self.assertRaisesRegex(SystemExit, 'readback hk'):
                    assemble_dual.main()
            self.assertEqual(output.read_bytes(), b'previous image')
            self.assertEqual(receipt.read_bytes(), b'previous receipt')
            self.assertEqual(set(directory.iterdir()), {output, receipt})

    def test_receipt_failure_restores_previous_product(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output = directory / 'disc.iso'
            receipt = directory / 'disc.receipt.json'
            staged = directory / 'verified.iso'
            staged_receipt = directory / 'verified.json'
            output.write_bytes(b'old verified image')
            receipt.write_bytes(b'old receipt')
            staged.write_bytes(b'new verified image')
            staged_receipt.write_bytes(b'new receipt')
            replace = Path.replace

            def fail_receipt(path, target):
                if path == staged_receipt:
                    raise OSError('injected receipt publication failure')
                return replace(path, target)

            with patch.object(Path, 'replace', fail_receipt):
                with self.assertRaisesRegex(OSError, 'injected'):
                    assemble_dual.publish(staged, output, staged_receipt, receipt)
            self.assertEqual(output.read_bytes(), b'old verified image')
            self.assertEqual(receipt.read_bytes(), b'old receipt')
