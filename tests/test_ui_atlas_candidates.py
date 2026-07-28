import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from tools.srwz.iso_layout import (
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from tools.srwz.tim2 import extract_tim2_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/assets/ui-atlas-candidates.json"


class UiAtlasCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    @classmethod
    def _source_bytes(cls):
        source = cls.config["source"]
        iso_path = PROJECT_ROOT / source["iso"]["path"]
        image = scan_iso9660(iso_path)
        member = member_map(image)[source["member"]["path"]]
        with iso_path.open("rb") as handle:
            handle.seek(member.extent_lba * SECTOR_SIZE)
            payload = handle.read(member.size)
        return payload

    def test_sources_and_candidate_chunks_are_hash_locked(self):
        source = self.config["source"]
        slps = (PROJECT_ROOT / source["slps"]["path"]).read_bytes()
        member = self._source_bytes()
        self.assertEqual(len(slps), source["slps"]["size"])
        self.assertEqual(
            hashlib.sha256(slps).hexdigest(),
            source["slps"]["sha256"],
        )
        self.assertEqual(len(member), source["member"]["size"])
        self.assertEqual(
            hashlib.sha256(member).hexdigest(),
            source["member"]["sha256"],
        )
        asset_config = json.loads(
            (PROJECT_ROOT / source["asset_config"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        raw = next(
            archive
            for archive in asset_config["archives"]
            if archive["member"] == "KURODATA/KVMDATA.BIN"
        )
        spec = ExecutableOffsetSpec(
            name=raw["name"],
            member=raw["member"],
            table_start=int(raw["table_start"], 0),
            table_end=int(raw["table_end"], 0),
        )
        offsets = read_executable_archive_offsets(slps, spec, len(member))
        for candidate in self.config["candidates"]:
            index = candidate["chunk_index"]
            payload = member[offsets[index] : offsets[index + 1]]
            self.assertEqual(len(payload), candidate["payload_size"])
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(),
                candidate["payload_sha256"],
            )

    def test_all_candidates_are_one_supported_tim2_picture(self):
        source = self.config["source"]
        slps = (PROJECT_ROOT / source["slps"]["path"]).read_bytes()
        member = self._source_bytes()
        asset_config = json.loads(
            (PROJECT_ROOT / source["asset_config"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        raw = next(
            archive
            for archive in asset_config["archives"]
            if archive["member"] == "KURODATA/KVMDATA.BIN"
        )
        spec = ExecutableOffsetSpec(
            name=raw["name"],
            member=raw["member"],
            table_start=int(raw["table_start"], 0),
            table_end=int(raw["table_end"], 0),
        )
        offsets = read_executable_archive_offsets(slps, spec, len(member))
        for candidate in self.config["candidates"]:
            index = candidate["chunk_index"]
            payload = member[offsets[index] : offsets[index + 1]]
            record, stored = extract_tim2_record(payload, 0)
            self.assertEqual(len(stored), len(payload))
            self.assertEqual(len(record.pictures), 1)
            picture = record.pictures[0]
            expected = candidate["picture"]
            self.assertEqual(picture.width, expected["width"])
            self.assertEqual(picture.height, expected["height"])
            self.assertEqual(
                picture.bits_per_pixel,
                expected["bits_per_pixel"],
            )

    def test_no_offline_candidate_is_overclaimed_as_runtime_mapping(self):
        for candidate in self.config["candidates"]:
            self.assertIn("not_runtime_mapped", candidate["evidence_status"])
            self.assertTrue(candidate["candidate_scene_ids"])
            self.assertTrue(candidate["observed_tokens"])
        self.assertEqual(
            self.config["runtime_acceptance"]["status"],
            "not_tested",
        )
        self.assertGreaterEqual(
            len(self.config["runtime_acceptance"]["required_route"]),
            6,
        )


if __name__ == "__main__":
    unittest.main()
