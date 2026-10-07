"""Exercise the production STAGE writer with two-byte Latin squad names."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from tools import build_full_story_components as build
from tools.srwz.stage_formations import FormationCell, FormationGroup
from tools.srwz.squad_name_ligature import CHARACTER, CODE, stored_squad_name, logical_squad_name
from tools.srwz.text import encode_text, load_text_table, original_fullwidth_ascii_overrides, project_runtime_text_table


class StageFormationVisibleSpacesTests(unittest.TestCase):
    def test_english_heat_ligature_agrees_and_fits_all_locked_main_game_slots(self):
        root = build.PROJECT_ROOT
        names = json.loads((root / "corpus/zh/menu/ui-name-tables.json").read_text())
        formations = json.loads((root / "corpus/zh/menu/stage-default-formations.json").read_text())
        name = next(row for row in names["squad_names"] if row["source"] == "ザ・ヒート")
        self.assertEqual(name["translation"], "THE HEAT")
        self.assertEqual(formations["translations_by_source_text"]["ザ・ヒート"], name["translation"])
        assignments = json.loads((root / "config/encoding/zh-release-font-assignments.json").read_text())
        overrides = {row["character"]: int(row["code"], 16) for row in assignments["primary_assignments"]}
        table = load_text_table(root / "vendor/upstream-python/project/tbl_all.json")
        overrides.update(original_fullwidth_ascii_overrides(table))
        stored = stored_squad_name(name["source"], name["translation"])
        payload = encode_text(stored, table, overrides=overrides, terminate=True)
        self.assertEqual(logical_squad_name(stored), "THE\u3000HEAT")
        self.assertEqual(payload, bytes.fromhex("8273826797f0826782648260827300"))
        self.assertEqual(len(payload), 15)
        inventory = json.loads((root / "config/stage-default-formation-inventory.json").read_text())
        index = inventory["sources"].index("ザ・ヒート")
        capacities = [int(group["layout"].rsplit("-", 1)[1])
                      for group in inventory["groups"] for _, source in group["cells"] if source == index]
        self.assertEqual(len(capacities), 11)
        self.assertTrue(all(len(payload) <= capacity for capacity in capacities))

    def test_default_names_keep_two_byte_pairing_and_slot_boundaries(self):
        table = load_text_table(build.PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json")
        translations = {"ザ・ヒート": "THE HEAT", "ザ・ビッグ": "The Big", "別働隊": "別働隊"}
        source = bytearray(b"owner-metadata!!" + bytes(96))
        cells = []
        for index, name in enumerate(translations):
            offset = 16 + index * 32
            payload = encode_text(name, table, terminate=True)
            source[offset:offset + len(payload)] = payload
            cells.append(FormationCell(offset, name, len(payload), ""))
        source = bytes(source)
        groups = (FormationGroup(1, "slot32", 32, 32, tuple(cells)),)
        inventory_sha = build.formation_inventory_sha256(groups)
        document = dict(schema_version=1, language="zh-Hans", editorial_status="reviewed",
                        policy=dict(source_text_authority="original_disc_only",
                                    build_selection_authority="locked_occurrence_inventory",
                                    scan_only_when_explicitly_refreezing=True,
                                    require_locked_source_coverage=True, preserve_record_metadata=True),
                        translations_by_source_text=translations)
        files = {"original": source, "corpus": json.dumps(document).encode(),
                 "inventory": b"{}", "fixed": json.dumps({
                     "stage_fixed_formation_by_offset": {"0x50": "別働隊"}}).encode()}
        reference = dict(original_stage="original", translations="fixed",
                         stage_default_formations="corpus", stage_default_formation_inventory="inventory",
                         expected=dict(stage_default_formation_group_count=1,
                                       stage_default_formation_entry_count=3,
                                       stage_default_formation_unique_source_count=3,
                                       stage_default_formation_stage_count=1,
                                       stage_default_formation_record_metadata_count=0,
                                       stage_default_formation_inventory_sha256=inventory_sha,
                                       stage_fixed_formation_chunk_index=1,
                                       stage_fixed_formation_entry_count=1,
                                       stage_default_formation_compact_ascii_entry_count=0))

        def locked_groups(*args, decoded_cache, **kwargs):
            decoded_cache[1] = SimpleNamespace(output=source, consumed=len(source))
            return groups

        # Compression and inventory discovery have separate coverage. Keep this
        # fixture focused on the actual writer, including its stock raw-space
        # override, preimage checks, capacity checks, and output reread.
        with patch.object(build, "_locked_file", side_effect=lambda key, **kw: (Path(key), files[key])), \
             patch.object(build, "load_locked_stage_default_formations", side_effect=locked_groups), \
             patch.object(build, "read_executable_archive_offsets", return_value=[0, 0, len(source)]), \
             patch.object(build, "_full_story_overrides", return_value=(Path("font"), {CHARACTER: CODE}, {}, {})), \
             patch.object(build, "decode", side_effect=lambda data: SimpleNamespace(output=data, consumed=len(data))), \
             patch.object(build, "reencode_changed_suffix", side_effect=lambda old, new, **kw: new):
            output, report, *_ = build._apply_stage_default_formation_names(
                source, b"", reference, {},
                dict(strategy="rust-fit", min_match_length=3, max_match_chain=64, lazy_matching=True))
        heat = bytes.fromhex("8273826797f0826782648260827300")
        big = bytes.fromhex("827382888285814082618289828700")
        self.assertEqual(output[16:48], heat + bytes(32 - len(heat)))
        self.assertEqual(output[48:80], big + bytes(32 - len(big)))
        self.assertEqual(output[:16], source[:16])
        self.assertEqual(output[80:], source[80:])
        self.assertEqual(len(output), len(source))
        self.assertEqual(report["compact_ascii_entry_count"], 0)

        # The independent final-ISO verifier must reject the previous bytes,
        # even though the generic decoder can read a raw ASCII space.
        import verify_full_story_iso_content as verify
        runtime = project_runtime_text_table(table, {**original_fullwidth_ascii_overrides(table), CHARACTER: CODE})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            locked = dict(reference)
            for key, name in (("original_stage", "original"), ("translations", "fixed"),
                              ("stage_default_formations", "corpus"),
                              ("stage_default_formation_inventory", "inventory")):
                (root / name).write_bytes(files[name])
                locked[key] = dict(path=name, size=len(files[name]), sha256=build.sha256_bytes(files[name]))
            config = root / "config.json"
            config.write_text(json.dumps({"remaining_ui": locked}))
            with patch.object(verify, "PROJECT_ROOT", root), \
                 patch.object(verify, "FULL_COMPONENT_CONFIG", config), \
                 patch.object(verify, "load_locked_stage_default_formations", return_value=groups), \
                 patch.object(verify, "read_executable_archive_offsets", return_value=[0, 0, len(source)]), \
                 patch.object(verify, "decode", side_effect=lambda data: SimpleNamespace(output=data, consumed=len(data))):
                self.assertTrue(verify.verify_stage_default_formation(output, b"", table, runtime)["two_byte_spaces_exact"])
                old = bytearray(output)
                old_heat = bytes.fromhex("82738267826420826782648260827300")
                old[16:48] = old_heat + bytes(32 - len(old_heat))
                with self.assertRaisesRegex(SystemExit, "default formation-name mismatch"):
                    verify.verify_stage_default_formation(bytes(old), b"", table, runtime)


if __name__ == "__main__":
    unittest.main()
