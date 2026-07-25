import tempfile
import json
import unittest
from pathlib import Path

from tools.srwz.iso9660 import (
    Iso9660Error,
    extent_order,
    member_manifest_sha256,
    member_map,
    pcsx2_v263_image_type,
    scan_iso9660,
    sort_file_lines,
)


SECTOR = 2048


def dual_u32(value):
    return value.to_bytes(4, "little") + value.to_bytes(4, "big")


def directory_record(identifier, extent, size, flags=0):
    identifier = bytes(identifier)
    length = 33 + len(identifier)
    if length % 2:
        length += 1
    record = bytearray(length)
    record[0] = length
    record[2:10] = dual_u32(extent)
    record[10:18] = dual_u32(size)
    record[25] = flags
    record[28:32] = b"\x01\x00\x00\x01"
    record[32] = len(identifier)
    record[33 : 33 + len(identifier)] = identifier
    return bytes(record)


def synthetic_iso(path):
    image = bytearray(40 * SECTOR)
    pvd = memoryview(image)[16 * SECTOR : 17 * SECTOR]
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[8:19] = b"PLAYSTATION"
    pvd[40:44] = b"TEST"
    pvd[80:88] = dual_u32(40)
    root = directory_record(b"\x00", 20, SECTOR, flags=2)
    pvd[156 : 156 + len(root)] = root

    directory = memoryview(image)[20 * SECTOR : 21 * SECTOR]
    records = [
        directory_record(b"\x00", 20, SECTOR, flags=2),
        directory_record(b"\x01", 20, SECTOR, flags=2),
        directory_record(b"B.BIN;1", 31, 3),
        directory_record(b"A.BIN;1", 30, 2),
    ]
    offset = 0
    for record in records:
        directory[offset : offset + len(record)] = record
        offset += len(record)
    image[30 * SECTOR : 30 * SECTOR + 2] = b"AA"
    image[31 * SECTOR : 31 * SECTOR + 3] = b"BBB"
    path.write_bytes(image)


class Iso9660Tests(unittest.TestCase):
    def test_scans_members_and_orders_by_extent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.iso"
            synthetic_iso(path)
            image = scan_iso9660(path)
            self.assertEqual(set(member_map(image)), {"A.BIN", "B.BIN"})
            self.assertEqual(extent_order(image), ("A.BIN", "B.BIN"))
            self.assertEqual(image.system_id, "PLAYSTATION")
            self.assertIsNone(image.udf_volume_recognition_sequence)

    def test_rejects_disagreeing_endian_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.iso"
            synthetic_iso(path)
            data = bytearray(path.read_bytes())
            data[16 * SECTOR + 84 : 16 * SECTOR + 88] = (41).to_bytes(
                4,
                "big",
            )
            path.write_bytes(data)
            with self.assertRaisesRegex(Iso9660Error, "endian copies"):
                scan_iso9660(path)

    def test_reports_pcsx2_v263_media_type_from_root_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.iso"
            synthetic_iso(path)
            image = scan_iso9660(path)
            self.assertEqual(image.root_directory_extent_lba, 20)
            self.assertEqual(image.root_directory_size, SECTOR)
            self.assertEqual(
                pcsx2_v263_image_type(image.root_directory_size),
                "CD",
            )
            self.assertEqual(
                pcsx2_v263_image_type(960),
                "DVD",
            )

    def test_sort_file_uses_descending_unique_weights(self):
        root = Path("/tmp/tree")
        self.assertEqual(
            sort_file_lines(root, ("B.BIN", "DATA/A.BIN")),
            (
                "/tmp/tree/B.BIN\t2",
                "/tmp/tree/DATA/A.BIN\t1",
            ),
        )

    def test_member_manifest_digest_is_order_sensitive(self):
        first = member_manifest_sha256(
            (
                ("A.BIN", 1, "a" * 64),
                ("B.BIN", 2, "b" * 64),
            )
        )
        second = member_manifest_sha256(
            (
                ("B.BIN", 2, "b" * 64),
                ("A.BIN", 1, "a" * 64),
            )
        )
        self.assertEqual(
            first,
            "96b21963fcf41a1b02266e2aea7590f60ca77676d400fde6b137ebc1b89fb91c",
        )
        self.assertNotEqual(first, second)

    def test_repository_iso_manifest_matches_build_config(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        manifest = json.loads(
            (
                root / "manifests" / "canary-iso-validation.json"
            ).read_text()
        )
        self.assertEqual(
            manifest["source_iso"]["sha256"],
            config["source_iso"]["sha256"],
        )
        self.assertEqual(
            manifest["observed_output_iso"]["size"],
            config["output"]["expected_size"],
        )
        self.assertEqual(
            manifest["layout"]["member_manifest_sha256"],
            config["output"]["expected_member_manifest_sha256"],
        )
        self.assertEqual(
            manifest["observed_output_iso"]["sha256"],
            config["output"]["expected_sha256"],
        )
        self.assertEqual(
            manifest["observed_output_iso"]["path"],
            config["output"]["path"],
        )
        self.assertEqual(
            manifest["layout"]["lba_prefix_preserved_through"],
            "DATA/VT1.BIN",
        )
        self.assertEqual(
            manifest["runtime_acceptance"],
            "passed_full_game_decoder_output_hash_and_opening_visual_canary",
        )
        self.assertTrue(manifest["emulator_executed"])
        self.assertEqual(
            manifest["visual_menu_acceptance"],
            "passed_select_scenario_screenshot",
        )


if __name__ == "__main__":
    unittest.main()
