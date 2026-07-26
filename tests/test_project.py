import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.project import (
    ProjectConfigError,
    load_build_profile,
    validate_profile_encoding,
)
from tools.srwz.text import TextTable


class ProjectProfileTests(unittest.TestCase):
    def _write_fixture(self, root: Path, mutate=None) -> Path:
        source_hash = "a" * 64
        documents = {
            "config/surfaces/menu.json": {
                "schema_version": 1,
                "surface_id": "menu/test",
                "source_member": "SLPS_258.87",
                "record": {
                    "entry_id": "menu/test",
                    "source_text_sha256": source_hash,
                },
                "layout": {
                    "kind": "embedded_fixed_text",
                    "offsets": [16],
                    "encoded_size_with_terminator": 3,
                },
                "codec_profile": "srwz-text-table-v1",
                "render": {"profile": "menu"},
                "writer": {
                    "kind": "fixed_preimage",
                    "require_equal_encoded_size": True,
                },
                "runtime_fixture": "menu-test",
            },
            "corpus/zh/menu.json": {
                "schema_version": 1,
                "entries": [
                    {
                        "id": "menu/test",
                        "source_text_sha256": source_hash,
                        "translation": "测",
                        "editorial_status": "final",
                    }
                ],
            },
            "config/encoding/codebook.json": {
                "schema_version": 1,
                "assignments": [
                    {
                        "id": "ce",
                        "character": "测",
                        "code": "987E",
                        "glyph_index": 4478,
                        "mapping": "standard",
                        "status": "assigned",
                        "raster": {
                            "raw_gray_sha256": "b" * 64,
                            "pixels_4bpp_sha256": "c" * 64,
                            "packed_glyph_sha256": "d" * 64,
                        },
                    }
                ],
            },
            "config/build-profiles/test.json": {
                "schema_version": 1,
                "profile_id": "test",
                "status": "candidate",
                "minimum_editorial_status": "final",
                "surfaces": [
                    {
                        "id": "menu/test",
                        "spec": "config/surfaces/menu.json",
                    }
                ],
                "translation_sources": ["corpus/zh/menu.json"],
                "codebook": "config/encoding/codebook.json",
                "codebook_assignments": ["ce"],
                "required_gates": ["profile_reconciliation"],
            },
        }
        if mutate is not None:
            mutate(documents)
        for relative, document in documents.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(document, ensure_ascii=False),
                encoding="utf-8",
            )
        return root / "config/build-profiles/test.json"

    def test_profile_reconciles_and_encodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root)
            selection = load_build_profile(root, profile_path)
            validation = validate_profile_encoding(
                selection,
                TextTable(characters={}, tags={}),
            )
        self.assertEqual(validation["surface_count"], 1)
        self.assertEqual(validation["codebook_assignment_count"], 1)
        self.assertEqual(
            validation["encoded_records"][0]["encoded_sha256"],
            hashlib.sha256(bytes.fromhex("987E00")).hexdigest(),
        )

    def test_zh_source_rejects_duplicated_japanese_text(self):
        def mutate(documents):
            documents["corpus/zh/menu.json"]["entries"][0][
                "source_text"
            ] = "duplicate"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root, mutate)
            with self.assertRaisesRegex(
                ProjectConfigError,
                "must not duplicate JP text",
            ):
                load_build_profile(root, profile_path)

    def test_profile_rejects_source_hash_drift(self):
        def mutate(documents):
            documents["corpus/zh/menu.json"]["entries"][0][
                "source_text_sha256"
            ] = "e" * 64

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root, mutate)
            with self.assertRaisesRegex(
                ProjectConfigError,
                "source hashes differ",
            ):
                load_build_profile(root, profile_path)

    def test_profile_rejects_editorial_status_below_gate(self):
        def mutate(documents):
            documents["corpus/zh/menu.json"]["entries"][0][
                "editorial_status"
            ] = "draft"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root, mutate)
            with self.assertRaisesRegex(ProjectConfigError, "is below"):
                load_build_profile(root, profile_path)

    def test_profile_rejects_unused_codebook_assignment(self):
        def mutate(documents):
            codebook = documents["config/encoding/codebook.json"]
            codebook["assignments"].append(
                {
                    "id": "shi",
                    "character": "试",
                    "code": "987F",
                    "glyph_index": 4479,
                    "mapping": "standard",
                    "status": "assigned",
                    "raster": {
                        "raw_gray_sha256": "1" * 64,
                        "pixels_4bpp_sha256": "2" * 64,
                        "packed_glyph_sha256": "3" * 64,
                    },
                }
            )
            documents["config/build-profiles/test.json"][
                "codebook_assignments"
            ].append("shi")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root, mutate)
            selection = load_build_profile(root, profile_path)
            with self.assertRaisesRegex(
                ProjectConfigError,
                "unused codebook characters",
            ):
                validate_profile_encoding(
                    selection,
                    TextTable(characters={}, tags={}),
                )

    def test_profile_rejects_unassigned_codebook_record(self):
        def mutate(documents):
            documents["config/encoding/codebook.json"]["assignments"][0][
                "status"
            ] = "candidate"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root, mutate)
            with self.assertRaisesRegex(
                ProjectConfigError,
                "is not selectable",
            ):
                load_build_profile(root, profile_path)

    def test_profile_reference_cannot_escape_project_root(self):
        def mutate(documents):
            documents["config/build-profiles/test.json"]["surfaces"][0][
                "spec"
            ] = "../outside.json"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root, mutate)
            with self.assertRaisesRegex(
                ProjectConfigError,
                "escapes the project root",
            ):
                load_build_profile(root, profile_path)

    def test_codebook_code_must_use_declared_standard_branch(self):
        def mutate(documents):
            assignment = documents[
                "config/encoding/codebook.json"
            ]["assignments"][0]
            assignment["code"] = "8040"
            assignment["glyph_index"] = 0

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self._write_fixture(root, mutate)
            with self.assertRaisesRegex(
                ProjectConfigError,
                "outside the standard glyph branch",
            ):
                load_build_profile(root, profile_path)


if __name__ == "__main__":
    unittest.main()
