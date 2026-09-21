"""Edition promotion must use the component generation actually verified."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.edition import EditionError
from srwz.sp_edition import validate_sp_readback


class SpEditionReadbackTests(unittest.TestCase):
    def fixture(self, root):
        def save(path, data):
            target = root/path
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            target.write_bytes(raw)
            return hashlib.sha256(raw).hexdigest()

        iso = 'build/iso/special-disc/sp-current.iso'
        iso_hash = save(iso, b'fixture')
        identity = dict(path=iso, size=7, sha256=iso_hash)
        run = 'work/build/special-disc/full-text/runs/build-test'
        component = run+'/stage/report.json'
        component_hash = save(component, {})
        report = run+'/independent-readback.json'
        report_hash = save(report, dict(status='all_bound_text_reread_from_final_iso',
                                       iso=identity, component_hashes_verified=True))
        return dict(status='all_bound_text_reread_from_final_iso_runtime_pending',
                    iso=identity, coverage=dict(pending_targets=[], unassigned_display_characters=[]),
                    independent_readback=dict(path=report, sha256=report_hash),
                    components={component: component_hash}, files={})

    def test_current_and_legacy_verified_status_keep_full_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = self.fixture(root)
            with patch('srwz.sp_edition.scan_iso9660'), patch('srwz.sp_edition.member_map', return_value={}):
                validate_sp_readback(root, proof)
                proof['status'] = 'all_current_draft_text_written_static_verified_runtime_pending'
                validate_sp_readback(root, proof)
                proof['coverage']['pending_targets'] = ['unwritten']
                with self.assertRaisesRegex(EditionError, 'coverage incomplete'):
                    validate_sp_readback(root, proof)

    def test_stale_legacy_report_is_rejected_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = self.fixture(root)
            old = root/proof['independent_readback']['path']
            stale = root/'work/build/special-disc/full-text/independent-readback.json'
            stale.write_bytes(old.read_bytes())
            proof['independent_readback']['path'] = str(stale.relative_to(root))
            with self.assertRaisesRegex(EditionError, 'different build runs'):
                validate_sp_readback(root, proof)

    def test_mixed_component_generations_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = self.fixture(root)
            proof['components']['work/build/special-disc/full-text/runs/other/frame/report.json'] = '0'*64
            with self.assertRaisesRegex(EditionError, 'different build runs'):
                validate_sp_readback(root, proof)
