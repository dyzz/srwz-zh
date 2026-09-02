from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.tricmn_battle_overlay import (
    _add_indexed_glow,
    _boundary_depths,
    _connected_mask_fringe,
    _coverage_floor,
    _directional_bevel_scores,
    _directional_mask_gradient,
    _outer_edge_mask,
    _pixel_edge_filter_coverage,
    _scaled_source_index_counts,
    _source_continuous_score_assignments,
    _source_soft_fringe_assignments,
    _source_quantile_assignments,
    _upper_left_exposed_at_depth,
    build_tricmn_battle_overlay,
)
from tools.srwz.gs_indexed_texture import (
    abrupt_luminance_pair_count,
    inverse_quantize_tex1_bilinear,
    simulate_tex1_bilinear_continuous_rgba,
    simulate_tex1_bilinear_rgba,
)
from tools.build_tricmn_battle_overlays import (
    FROZEN_STATUS,
    _frozen_component,
    _load_object,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/assets/tricmn-battle-overlays-zh.json"


class TricmnBattleOverlaysTest(unittest.TestCase):
    def test_release_component_consumes_the_reviewed_frozen_snapshot(self) -> None:
        payload, report = _frozen_component(PROJECT_ROOT, CONFIG)

        self.assertEqual(
            report["status"],
            FROZEN_STATUS,
        )
        self.assertEqual(report["build_mode"], "locked_indexed_snapshot")
        self.assertEqual(report["atlas"]["label_count"], 51)
        self.assertTrue(report["atlas"]["frozen_snapshot_consumed"])
        self.assertEqual(report["runtime"]["status"], "accepted")
        self.assertTrue(all(report["acceptance"].values()))
        self.assertEqual(
            report["outputs"]["BTL/TRICMN.BIN"]["sha256"],
            "e5375ac8595a9550efb0cc7680e2131d66dfbfada9ae4534a5188e7dc8e07615",
        )
        self.assertEqual(len(payload), 677424)

    def test_frozen_snapshot_covers_exactly_the_three_localized_pictures(self) -> None:
        config = _load_object(CONFIG)
        snapshot = _load_object(
            PROJECT_ROOT / config["frozen_snapshot"]["path"]
        )

        self.assertEqual(snapshot["status"], "reviewed_locked")
        self.assertEqual(snapshot["update_policy"], "explicit_refreeze_only")
        self.assertEqual(
            [item["picture_index"] for item in snapshot["frozen_image_ranges"]],
            [0, 1, 2],
        )
        self.assertEqual(snapshot["runtime"]["lrps2_ability_sweep"]["passed"], 19)
        self.assertEqual(snapshot["runtime"]["lrps2_ability_sweep"]["total"], 19)

    def test_tex1_palette_sampling_resolves_colours_before_bilinear_mix(self) -> None:
        palette = tuple(
            (index * 16,) * 3 + ((0 if index == 0 else 255),)
            for index in range(16)
        )
        indexes = bytes((1, 5, 9, 13))
        discrete = simulate_tex1_bilinear_rgba(
            indexes,
            width=2,
            height=2,
            palette=palette,
            scale=4,
        )
        native = tuple(
            channel
            for index in indexes
            for channel in palette[index]
        )
        continuous = simulate_tex1_bilinear_continuous_rgba(
            native,
            width=2,
            height=2,
            scale=4,
        )

        self.assertEqual(discrete, continuous)

    def test_tex1_inverse_quantizer_reduces_target_error_and_abrupt_pairs(self) -> None:
        palette = tuple((index * 17,) * 3 + (255,) for index in range(16))
        initial = bytes((1, 15, 1, 15))
        native_target = tuple((136.0, 136.0, 136.0, 255.0) * 4)
        target = simulate_tex1_bilinear_continuous_rgba(
            native_target,
            width=2,
            height=2,
            scale=4,
        )
        optimized, report = inverse_quantize_tex1_bilinear(
            target,
            initial,
            width=2,
            height=2,
            palette=palette,
            allowed_indexes={local: (1, 8, 15) for local in range(4)},
            scale=4,
            passes=3,
            adjacency_threshold=64,
            adjacency_weight=2.0,
        )

        self.assertLess(report.final_weighted_mse, report.initial_weighted_mse)
        self.assertLess(
            abrupt_luminance_pair_count(
                optimized,
                width=2,
                height=2,
                palette=palette,
            ),
            abrupt_luminance_pair_count(
                initial,
                width=2,
                height=2,
                palette=palette,
            ),
        )

    def test_tex1_inverse_protected_edges_cannot_gain_abrupt_pairs(self) -> None:
        palette = tuple((index * 17,) * 3 + (255,) for index in range(16))
        initial = bytes((8, 8, 8, 8))
        abrupt_native = tuple(
            channel
            for index in (1, 15, 1, 15)
            for channel in palette[index]
        )
        target = simulate_tex1_bilinear_continuous_rgba(
            abrupt_native,
            width=2,
            height=2,
            scale=4,
        )
        _optimized, report = inverse_quantize_tex1_bilinear(
            target,
            initial,
            width=2,
            height=2,
            palette=palette,
            allowed_indexes={local: (1, 8, 15) for local in range(4)},
            scale=4,
            passes=3,
            adjacency_threshold=64,
            adjacency_weight=0.0,
            protected_edges=((0, 1), (0, 2), (1, 3), (2, 3)),
        )

        self.assertEqual(report.protected_abrupt_pairs_before, 0)
        self.assertEqual(report.protected_abrupt_pairs_after, 0)

    def test_source_histogram_scaling_preserves_complete_tone_balance(self) -> None:
        counts = _scaled_source_index_counts(
            bytes([1, 1, 2, 15]),
            output_ink_pixel_count=8,
            palette_indexes=tuple(range(1, 16)),
        )

        self.assertEqual(sum(counts.values()), 8)
        self.assertEqual(counts[1], 4)
        self.assertEqual(counts[2], 2)
        self.assertEqual(counts[15], 2)
        self.assertTrue(all(counts[index] == 0 for index in range(3, 15)))

    def test_directional_bevel_extends_and_shades_towards_lower_right(self) -> None:
        mask = bytearray(7 * 7)
        for y in range(2, 5):
            for x in range(2, 5):
                mask[y * 7 + x] = 255
        silhouette, scores = _directional_bevel_scores(
            bytes(mask),
            bytes(mask),
            width=7,
            height=7,
            shadow_offset_x=2,
            shadow_offset_y=2,
        )

        self.assertEqual(silhouette[1 * 7 + 1], 0)
        self.assertEqual(silhouette[6 * 7 + 6], 255)
        self.assertGreater(scores[2 * 7 + 2], scores[4 * 7 + 4])

    def test_indexed_glow_uses_radial_low_coverage_falloff(self) -> None:
        mask = bytearray(7 * 7)
        mask[3 * 7 + 3] = 255
        feathered = _add_indexed_glow(bytes(mask), width=7, height=7, radius=2)

        self.assertEqual(feathered[3 * 7 + 3], 255)
        self.assertGreater(feathered[3 * 7 + 4], feathered[2 * 7 + 2])
        self.assertGreater(feathered[2 * 7 + 2], feathered[3 * 7 + 5])
        self.assertGreater(feathered[3 * 7 + 5], 0)
        self.assertEqual(feathered[2 * 7 + 5], 0)
        self.assertEqual(feathered[1 * 7 + 1], 0)

    def test_wordart_coverage_floor_removes_only_faint_fragments(self) -> None:
        self.assertEqual(
            _coverage_floor(bytes([0, 7, 8, 31, 255]), minimum=8),
            bytes([0, 0, 8, 31, 255]),
        )

    def test_directional_gradient_distinguishes_wordart_sides(self) -> None:
        mask = bytearray(5 * 5)
        for y in range(1, 4):
            for x in range(1, 4):
                mask[y * 5 + x] = 255

        self.assertGreater(
            _directional_mask_gradient(
                bytes(mask), width=5, height=5, x=0, y=0
            ),
            0,
        )
        self.assertLess(
            _directional_mask_gradient(
                bytes(mask), width=5, height=5, x=4, y=4
            ),
            0,
        )

    def test_antialias_fringe_keeps_connected_faint_pixels_only(self) -> None:
        core = bytes(
            [
                0, 0, 0, 0, 0,
                0, 0, 255, 0, 0,
                0, 255, 255, 255, 0,
                0, 0, 255, 0, 0,
                0, 0, 0, 0, 0,
            ]
        )
        full = bytearray(core)
        full[0] = 7
        full[1 * 5 + 1] = 12

        self.assertEqual(
            _connected_mask_fringe(bytes(full), core, width=5, height=5),
            (1 * 5 + 1,),
        )

    def test_pixel_edge_filter_extends_only_the_outer_coverage_fringe(self) -> None:
        core = bytearray(7 * 7)
        for y in range(2, 5):
            for x in range(2, 5):
                core[y * 7 + x] = 255

        filtered = _pixel_edge_filter_coverage(
            bytes(core),
            bytes(core),
            width=7,
            height=7,
            radius=1,
            coverage_ceiling=19,
        )

        self.assertEqual(filtered[3 * 7 + 3], 255)
        self.assertGreater(filtered[3 * 7 + 1], 0)
        self.assertGreater(filtered[1 * 7 + 1], 0)
        self.assertEqual(filtered[3 * 7 + 5], 0)
        self.assertEqual(filtered[5 * 7 + 3], 0)
        self.assertEqual(filtered[0], 0)
        self.assertEqual(
            _pixel_edge_filter_coverage(
                bytes(core),
                bytes(core),
                width=7,
                height=7,
                radius=0,
                coverage_ceiling=19,
            ),
            bytes(core),
        )

    def test_soft_fringe_reserves_brightest_index_for_solid_inner_rim(self) -> None:
        assignments = _source_soft_fringe_assignments(
            (0, 1, 2, 3),
            bytes((1, 7, 13, 19)),
            {9: 27, 11: 34, 12: 221, 14: 325},
            coverage_ceiling=19,
            reserved_inner_rim_index=14,
        )

        self.assertEqual(assignments, {0: 9, 1: 11, 2: 12, 3: 12})
        self.assertNotIn(14, assignments.values())

    def test_continuous_side_scores_keep_face_adjacent_wall_bright(self) -> None:
        assignments = _source_continuous_score_assignments(
            (0, 1, 2, 3),
            (0, 21845, 43690, 65535),
            {1: 10, 2: 10, 3: 10, 4: 10, 5: 10, 6: 10, 7: 10},
        )

        self.assertEqual(assignments, {0: 1, 1: 3, 2: 5, 3: 7})

    def test_boundary_depths_distinguish_first_and_second_rings(self) -> None:
        mask = bytearray(5 * 5)
        for y in range(1, 4):
            for x in range(1, 4):
                mask[y * 5 + x] = 1

        depths = _boundary_depths(bytes(mask), width=5, height=5, maximum=2)

        self.assertEqual(depths[1 * 5 + 1], 1)
        self.assertEqual(depths[2 * 5 + 2], 2)

    def test_upper_left_exposure_does_not_mark_lower_right_edge(self) -> None:
        mask = bytearray(5 * 5)
        for y in range(1, 4):
            for x in range(1, 4):
                mask[y * 5 + x] = 1

        self.assertTrue(
            _upper_left_exposed_at_depth(
                bytes(mask), width=5, height=5, x=1, y=1, depth=1
            )
        )
        self.assertFalse(
            _upper_left_exposed_at_depth(
                bytes(mask), width=5, height=5, x=3, y=3, depth=1
            )
        )

    def test_outer_edge_is_a_distinct_wordart_reflection_layer(self) -> None:
        mask = bytearray(5 * 5)
        for y in range(1, 4):
            for x in range(1, 4):
                mask[y * 5 + x] = 1
        edge = _outer_edge_mask(bytes(mask), width=5, height=5)

        self.assertEqual(sum(edge), 8)
        self.assertEqual(edge[2 * 5 + 2], 0)
        self.assertEqual(edge[1 * 5 + 1], 1)

    def test_source_quantiles_do_not_split_equal_spatial_plateaus(self) -> None:
        assignments = _source_quantile_assignments(
            [0, 1, 2, 3, 4, 5],
            [10, 10, 20, 20, 30, 30],
            {1: 1, 7: 1, 14: 1},
        )

        self.assertEqual(assignments[0], assignments[1])
        self.assertEqual(assignments[2], assignments[3])
        self.assertEqual(assignments[4], assignments[5])
        self.assertEqual(
            [assignments[0], assignments[2], assignments[4]],
            [1, 7, 14],
        )

    def test_locked_component_preserves_alpha_and_neighbours(self) -> None:
        payload, reference, localized, report = build_tricmn_battle_overlay(
            PROJECT_ROOT,
            CONFIG,
        )
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(len(payload), config["source"]["size"])
        self.assertEqual(len(reference), 2048 * 5376 * 4)
        self.assertEqual(len(localized), 2048 * 5376 * 4)
        self.assertTrue(all(report["acceptance"].values()))
        self.assertTrue(report["seg"]["preserved_byte_exact"])
        self.assertTrue(report["atlas"]["clut_preserved_byte_exact"])
        self.assertTrue(
            report["atlas"]["background_transparent_in_all_palette_banks"]
        )
        self.assertTrue(
            report["atlas"]["non_target_logical_indexes_preserved_byte_exact"]
        )
        self.assertEqual(len(report["atlas"]["complete_six_picture_inventory"]), 6)
        labels = {
            item["entry_id"]: item for item in report["atlas"]["labels"]
        }
        self.assertEqual(labels["tricmn/tri-formation"]["translation"], "TRI队形")
        self.assertEqual(labels["tricmn/no-target"]["translation"], "无目标")
        self.assertEqual(
            labels["tricmn/missing-member-reason"]["translation"],
            "（缺人）",
        )
        self.assertEqual(labels["tricmn/no-target"]["source_ink_pixel_count"], 6313)
        self.assertEqual(labels["tricmn/no-target"]["rect"], [153, 0, 214, 40])
        self.assertEqual(
            labels["tricmn/attack-unavailable"]["translation"], "无法攻击"
        )
        self.assertEqual(labels["tricmn/psycho-field"]["translation"], "精神感应力场")
        self.assertEqual(labels["tricmn/vps-armor"]["translation"], "VPS装甲")
        self.assertEqual(labels["tricmn/support"]["translation"], "防御")
        self.assertEqual(
            labels["tricmn/positron-reflector"]["frame_template"][
                "source_text_spill_outside_text_rect_pixel_count"
            ],
            115,
        )
        self.assertEqual(
            labels["tricmn/barrier-field"]["frame_template"][
                "source_text_spill_outside_text_rect_pixel_count"
            ],
            120,
        )
        self.assertTrue(
            labels["tricmn/barrier-field"]["frame_template"][
                "output_frame_matches_empty_template_byte_exact"
            ]
        )
        self.assertNotIn("tricmn/en-reason", labels)
        single_attack = labels["tricmn/single-attack"]
        self.assertEqual(
            single_attack["render_style"],
            "source_wordart_3d_index_layers",
        )
        self.assertFalse(
            single_attack[
                "heightfield_palette_quantization_uses_source_zones"
            ]
        )
        self.assertEqual(
            single_attack["heightfield_surface"][
                "bevel_width_supersampled_pixels"
            ],
            8,
        )
        self.assertEqual(
            single_attack["heightfield_surface"][
                "extrusion_depth_supersampled_pixels"
            ],
            16,
        )
        self.assertEqual(
            single_attack["heightfield_surface"][
                "halo_width_supersampled_pixels"
            ],
            8,
        )
        self.assertTrue(single_attack["heightfield_flat_top_rim"])
        self.assertTrue(single_attack["heightfield_flat_face"])
        self.assertEqual(single_attack["heightfield_flat_top_palette_index"], 14)
        self.assertEqual(single_attack["heightfield_face_rim_palette_index"], 13)
        self.assertEqual(single_attack["heightfield_flat_face_palette_index"], 15)
        self.assertGreater(
            single_attack["heightfield_flat_face_output_pixel_count"],
            0,
        )
        self.assertLess(
            single_attack["heightfield_flat_face_output_pixel_count"],
            sum(single_attack["output_zone_index_counts"]["face"].values()),
        )
        self.assertEqual(
            single_attack["heightfield_face_rim_output_pixel_count"]
            + single_attack["heightfield_flat_face_output_pixel_count"],
            sum(single_attack["output_zone_index_counts"]["face"].values()),
        )
        self.assertEqual(
            single_attack["output_zone_index_counts"]["face"],
            {
                "13": single_attack["heightfield_face_rim_output_pixel_count"],
                "15": single_attack["heightfield_flat_face_output_pixel_count"],
            },
        )
        self.assertFalse(single_attack["inverse_tex1_enabled"])
        self.assertIsNone(single_attack["inverse_tex1"])
        self.assertGreater(
            single_attack["heightfield_flat_top_output_pixel_count"],
            0,
        )
        self.assertEqual(
            len(single_attack["heightfield_surface"]["light_vector"]),
            3,
        )
        self.assertEqual(
            set(single_attack["source_index_boundary_depth_counts"]),
            {str(index) for index in range(1, 16)},
        )
        self.assertIn(
            "1",
            single_attack["source_index_boundary_depth_counts"]["14"],
        )
        self.assertIn(
            "4",
            single_attack["source_index_boundary_depth_counts"]["1"],
        )
        self.assertEqual(
            set(single_attack["source_zone_index_counts"]["halo"]),
            {"9", "11", "12", "14"},
        )
        self.assertEqual(
            single_attack["output_zone_index_counts"]["halo"],
            {"14": single_attack["output_zone_pixel_counts"]["halo"]},
        )
        self.assertFalse(single_attack["anti_alias_uses_source_soft_coverage_ramp"])
        self.assertTrue(single_attack["indexed_edge_filter_enabled"])
        self.assertEqual(single_attack["indexed_edge_filter_radius"], 1)
        self.assertGreater(
            single_attack["indexed_edge_filter_added_pixel_count"], 0
        )
        self.assertGreater(
            single_attack["indexed_edge_filter_changed_coverage_pixel_count"],
            0,
        )
        self.assertTrue(
            single_attack["heightfield_side_uses_continuous_source_ramp"]
        )
        side_counts = {
            int(index): count
            for index, count in single_attack["output_zone_index_counts"][
                "side"
            ].items()
            if 1 <= int(index) <= 7
        }
        self.assertGreaterEqual(len(side_counts), 5)
        self.assertLess(
            max(side_counts.values()),
            sum(side_counts.values()) * 3 // 4,
        )
        self.assertEqual(
            single_attack["index_layer_sequence"],
            [
                "transparent:0",
                "extrusion:1..7",
                "soft-fringe:12",
                "hard-rim:14",
                "face-rim:13",
                "flat-face:15",
            ],
        )
        self.assertTrue(
            single_attack["index_layers_constructed_before_writeback"]
        )
        self.assertFalse(single_attack["result_level_pixel_repair_enabled"])
        self.assertTrue(single_attack["outer_boundary_uses_light_indexes_only"])
        self.assertTrue(
            set(single_attack["outer_boundary_output_index_counts"])
            <= {"12", "14"}
        )
        self.assertGreaterEqual(
            single_attack["dark_index_minimum_boundary_depth"], 2
        )
        self.assertEqual(
            sum(single_attack["output_zone_index_counts"]["face"].values()),
            single_attack["output_zone_pixel_counts"]["face"],
        )
        self.assertGreater(
            single_attack["output_zone_pixel_counts"]["side"], 0
        )
        self.assertGreater(
            single_attack["output_zone_pixel_counts"]["face"], 0
        )
        large = labels["tricmn/tri-formation"]["render"]
        self.assertEqual(
            large["render_style"],
            "source_wordart_3d_index_layers",
        )
        self.assertEqual(large["glow_radius"], 1)
        self.assertEqual(large["point_size"], 31)
        self.assertEqual(large["outline_stroke_width"], 3.0)
        self.assertEqual(large["fill_stroke_width"], 0.8)
        self.assertEqual(large["coverage_floor"], 20)
        self.assertEqual(large["side_direction_weight"], 3)
        self.assertEqual(large["halo_direction_weight"], 0)
        self.assertEqual(large["supersample_factor"], 8)
        self.assertEqual(large["italic_shear_degrees"], 8)
        self.assertTrue(large["vector_effects_before_downsample"])
        self.assertEqual(large["character_spacing"], 5.0)
        self.assertTrue(large["heightfield_flat_top_rim"])
        self.assertTrue(large["heightfield_flat_face"])
        self.assertEqual(large["indexed_edge_filter_radius"], 1)
        self.assertEqual(large["heightfield_bevel_width"], 1.0)
        self.assertNotIn("outline_palette_indexes", large)
        self.assertNotIn("fill_palette_indexes", large)
        self.assertEqual(
            labels["tricmn/single-attack"]["render"]["character_spacing"],
            7.0,
        )
        self.assertEqual(
            labels["tricmn/single-attack"]["render"]["point_size"],
            30,
        )
        self.assertEqual(
            labels["tricmn/single-attack"]["render"]["italic_shear_degrees"],
            8,
        )
        self.assertEqual(
            labels["tricmn/single-attack"]["render"]["heightfield_bevel_width"],
            1.0,
        )
        for entry_id in (
            "tricmn/tri-formation",
            "tricmn/single-attack",
            "tricmn/wide-formation",
            "tricmn/squad-attack",
            "tricmn/center-formation",
            "tricmn/all-attack",
            "tricmn/counter",
            "tricmn/support-attack",
            "tricmn/tri-attack",
            "tricmn/attack-again",
            "tricmn/support-defense",
            "tricmn/combined-attack",
        ):
            self.assertEqual(
                labels[entry_id]["render_style"],
                "source_wordart_3d_index_layers",
            )
            self.assertTrue(labels[entry_id]["heightfield_flat_top_rim"])
            self.assertTrue(labels[entry_id]["heightfield_flat_face"])
            self.assertEqual(
                labels[entry_id]["heightfield_flat_top_palette_index"],
                14,
            )
            self.assertEqual(
                labels[entry_id]["heightfield_flat_face_palette_index"],
                15,
            )
            self.assertEqual(
                labels[entry_id]["heightfield_face_rim_palette_index"],
                13,
            )
            self.assertTrue(
                labels[entry_id]["index_layers_constructed_before_writeback"]
            )
            self.assertFalse(
                labels[entry_id]["result_level_pixel_repair_enabled"]
            )
            self.assertFalse(labels[entry_id]["inverse_tex1_enabled"])
            self.assertTrue(
                set(labels[entry_id]["outer_boundary_output_index_counts"])
                <= {"12", "13", "14"}
            )
            self.assertTrue(
                set(labels[entry_id]["output_zone_index_counts"]["side"])
                <= {str(index) for index in range(1, 8)}
            )
            self.assertEqual(
                set(labels[entry_id]["output_zone_index_counts"]["face"]),
                {"13", "15"},
            )
            self.assertEqual(
                labels[entry_id]["heightfield_flat_face_output_pixel_count"],
                labels[entry_id]["output_zone_index_counts"]["face"]["15"],
            )
            self.assertEqual(
                labels[entry_id]["heightfield_face_rim_output_pixel_count"],
                labels[entry_id]["output_zone_index_counts"]["face"]["13"],
            )
        self.assertTrue(
            labels["tricmn/single-attack"]["vector_effects_before_downsample"]
        )
        self.assertEqual(
            labels["tricmn/single-attack"]["vector_effect_scale"],
            8,
        )
        self.assertEqual(
            labels["tricmn/attack-again"]["render"]["character_spacing"],
            6.0,
        )
        self.assertEqual(
            labels["tricmn/support-attack"]["render"]["character_spacing"],
            6.0,
        )
        self.assertEqual(
            labels["tricmn/support-defense"]["render"]["character_spacing"],
            6.0,
        )
        self.assertEqual(
            labels["tricmn/tri-attack"]["index_layer_sequence"],
            [
                "transparent:0",
                "extrusion:1..7",
                "soft-fringe:12",
                "hard-rim:14",
                "face-rim:13",
                "flat-face:15",
            ],
        )
        self.assertNotIn(
            "13",
            labels["tricmn/tri-attack"]["outer_boundary_output_index_counts"],
        )
        bank_four = report["atlas"]["palette_audit"][4]
        self.assertEqual(len(bank_four["indexes"]), 16)
        self.assertEqual(bank_four["indexes"][0]["role"], "transparent")
        self.assertEqual(bank_four["indexes"][0]["runtime_alpha"], 0)
        self.assertEqual(bank_four["indexes"][1]["role"], "side")
        self.assertEqual(bank_four["indexes"][8]["role"], "light")
        self.assertTrue(
            all(
                item["runtime_alpha"] == min(255, item["tim2_raw_alpha"] * 2)
                for item in bank_four["indexes"]
            )
        )
        for entry_id in (
            "tricmn/wait",
            "tricmn/no-target",
            "tricmn/disabled",
            "tricmn/attack-unavailable",
        ):
            prompt = labels[entry_id]["render"]
            self.assertEqual(prompt["italic_shear_degrees"], 0)
            self.assertEqual(prompt["glow_radius"], 1)
            self.assertNotIn("outline_palette_indexes", prompt)
            self.assertNotIn("fill_palette_indexes", prompt)
        for entry_id in (
            "tricmn/ammo-reason",
            "tricmn/missing-member-reason",
            "tricmn/terrain-reason",
            "tricmn/morale-reason",
            "tricmn/range-reason",
            "tricmn/ability-reason",
        ):
            reason = labels[entry_id]["render"]
            self.assertEqual(reason["point_size"], 28)
            self.assertEqual(reason["italic_shear_degrees"], 0)
            self.assertEqual(reason["glow_radius"], 1)
            self.assertEqual(reason["fill_stroke_width"], 0.0)
        blue_gradient_ids = (
            "tricmn/wait",
            "tricmn/no-target",
            "tricmn/disabled",
            "tricmn/attack-unavailable",
            "tricmn/ammo-reason",
            "tricmn/missing-member-reason",
            "tricmn/terrain-reason",
            "tricmn/morale-reason",
            "tricmn/range-reason",
            "tricmn/ability-reason",
        )
        self.assertEqual(
            [
                item["runtime_rgba"]
                for item in report["atlas"]["palette_audit"][0]["indexes"][8:]
            ],
            [
                "323541ca",
                "363b51f6",
                "04237aff",
                "132d7bff",
                "4c5575ff",
                "34406cff",
                "293a76ff",
                "1f3479ff",
            ],
        )
        for entry_id in blue_gradient_ids:
            item = labels[entry_id]
            self.assertEqual(item["render_style"], "source_wordart_3d")
            self.assertEqual(
                set(item["source_zone_index_counts"]["face"]),
                {str(index) for index in range(8, 16)},
            )
            self.assertEqual(
                set(item["output_zone_index_counts"]["face"]),
                {str(index) for index in range(8, 16)},
            )
            self.assertEqual(
                set(item["output_zone_index_counts"]["anti_alias"]),
                {"1"},
            )
            self.assertTrue(item["source_histogram_used_as_zone_quantile_reference"])
            self.assertTrue(item["equal_spatial_score_groups_share_one_index"])
            self.assertTrue(item["vector_effects_before_downsample"])
            self.assertTrue(item["indexed_edge_filter_enabled"])
            self.assertGreater(item["indexed_edge_filter_added_pixel_count"], 0)
            self.assertFalse(item["heightfield_flat_face"])
            self.assertFalse(item["inverse_tex1_enabled"])
            self.assertEqual(item["dark_component_minimum_pixels"], 1)
            self.assertEqual(item["dark_speckle_pixels_converted_to_light"], 0)
        status_ids = (
            "tricmn/mobility-down",
            "tricmn/armor-down",
            "tricmn/accuracy-down",
            "tricmn/en-down",
            "tricmn/ability-down",
            "tricmn/status-disabled",
            "tricmn/morale-down",
            "tricmn/sp-down",
            "tricmn/mental-defense",
            "tricmn/canceller",
        )
        for row, entry_id in enumerate(status_ids):
            item = labels[entry_id]
            self.assertEqual(item["rect"], [399, row * 24, 113, 24])
            self.assertEqual(
                item["render_style"],
                "source_wordart_3d_dark_core",
            )
            self.assertTrue(item["dark_core_material_layout"])
            self.assertEqual(item["render"]["point_size"], 19)
            self.assertEqual(item["render"]["outline_stroke_width"], 1.2)
            self.assertEqual(item["render"]["fill_stroke_width"], 0.0)
            self.assertEqual(item["render"]["character_spacing"], 0.6)
            self.assertEqual(item["render"]["italic_shear_degrees"], 0)
            self.assertEqual(item["render"]["glow_radius"], 2)
            self.assertEqual(item["render"]["ink_left"], 0)
            self.assertEqual(item["render_ink_bounds"][0], 0)
            self.assertTrue(item["vector_effects_before_downsample"])
            self.assertTrue(item["indexed_edge_filter_enabled"])
            self.assertGreater(item["indexed_edge_filter_added_pixel_count"], 0)
            self.assertTrue(item["source_histogram_used_as_zone_quantile_reference"])
            self.assertEqual(item["dark_speckle_pixels_converted_to_light"], 0)
            expected_anti_alias_indexes = (
                {"11", "14"}
                if entry_id == "tricmn/status-disabled"
                else {"12", "14"}
            )
            self.assertEqual(
                set(item["output_zone_index_counts"]["anti_alias"]),
                expected_anti_alias_indexes,
            )
            marker = item["marker"]
            self.assertEqual(marker["slot_rect"], [384, row * 24, 128, 24])
            self.assertEqual(marker["marker_rect"], [384, row * 24, 15, 24])
            self.assertTrue(marker["source_slot_cleared_before_redraw"])
            self.assertTrue(marker["noncontent_pixels_transparent"])
            self.assertTrue(marker["source_marker_template_copied_byte_exact"])
            self.assertEqual(marker["output_ink_pixel_count"], 243)
            self.assertEqual(marker["source_template_ambiguous_pixel_count"], 19)
            self.assertEqual(
                marker["source_template_ambiguous_foreground_pixel_count"], 12
            )
            self.assertEqual(
                marker["source_template_resolution"],
                "per_pixel_majority_with_higher_index_tiebreak",
            )
        self.assertEqual(
            labels["tricmn/en-down"]["bright_edge_character_indexes"], [1]
        )
        self.assertEqual(
            labels["tricmn/en-down"]["bright_edge_selected_spans"], [[13, 27]]
        )
        self.assertGreater(
            labels["tricmn/en-down"]["bright_edge_promoted_pixel_count"], 0
        )
        self.assertEqual(
            labels["tricmn/sp-down"]["bright_edge_character_indexes"], [0]
        )
        self.assertEqual(
            labels["tricmn/sp-down"]["bright_edge_selected_spans"], [[0, 14]]
        )
        self.assertGreater(
            labels["tricmn/sp-down"]["bright_edge_promoted_pixel_count"], 0
        )
        for entry_id in set(status_ids) - {
            "tricmn/en-down",
            "tricmn/sp-down",
        }:
            self.assertEqual(
                labels[entry_id]["bright_edge_character_indexes"], []
            )
            self.assertEqual(
                labels[entry_id]["bright_edge_promoted_pixel_count"], 0
            )
        ability_labels = [
            item for item in labels.values() if item["frame_template"] is not None
        ]
        self.assertEqual(len(ability_labels), 19)
        for item in ability_labels:
            render = item["render"]
            self.assertEqual(
                item["font_flavor"]["font_flavor_id"],
                "srwz-zh-harmonyos-sans-sc-regular-v1",
            )
            self.assertEqual(
                item["font_file_sha256"],
                "297b088424be212207df2ce8b98e335468b782aa6b96832af0b8b773d711e2b1",
            )
            self.assertEqual(render["point_size"], 19)
            self.assertEqual(render["outline_stroke_width"], 1.2)
            self.assertEqual(render["fill_stroke_width"], 0.8)
            self.assertEqual(render["character_spacing"], 0.6)
            self.assertEqual(render["italic_shear_degrees"], 0)
            self.assertEqual(render["glow_radius"], 2)
            self.assertEqual(render["shadow_offset"], [0, 1])
            self.assertEqual(
                item["render_style"],
                "source_wordart_tight_down_dark_core_layers",
            )
            self.assertTrue(item["dark_core_material_layout"])
            self.assertEqual(render["horizontal_alignment"], "center")
            self.assertTrue(render["match_source_ink_width"])
            self.assertEqual(render["supersample_factor"], 8)
            self.assertTrue(item["vector_effects_before_downsample"])
            self.assertTrue(item["indexed_edge_filter_enabled"])
            self.assertEqual(item["indexed_edge_filter_radius"], 1)
            source_width = (
                item["source_ink_bounds"][2] - item["source_ink_bounds"][0]
            )
            expected_width = min(source_width, item["rect"][2] - 2)
            output_width = (
                item["render_ink_bounds"][2] - item["render_ink_bounds"][0]
            )
            self.assertEqual(item["source_target_ink_width"], expected_width)
            self.assertLessEqual(abs(output_width - expected_width), 1)
            self.assertIsInstance(item["effective_character_spacing"], float)
            self.assertGreater(item["indexed_edge_filter_added_pixel_count"], 0)
            self.assertGreater(item["output_zone_pixel_counts"]["anti_alias"], 0)
            self.assertGreater(item["fill_mask_partial_coverage_pixel_count"], 0)
            self.assertTrue(item["semantic_index_roles_locked"])
            self.assertTrue(
                item["semantic_halo_uses_source_boundary_depth_profile"]
            )
            self.assertEqual(
                set(item["semantic_halo_source_boundary_index_counts"]),
                {"1", "2", "3", "4"},
            )
            self.assertEqual(
                set(item["semantic_halo_outer_fringe_index_counts"]),
                {"1", "2", "3"},
            )
            self.assertEqual(item["semantic_halo_reserved_inner_index"], 4)
            self.assertGreater(
                item["semantic_outer_boundary_reassigned_count"], 0
            )
            self.assertEqual(
                item["semantic_index_roles"],
                {
                    "transparent": [0],
                    "attached_halo": [1, 2, 3, 4],
                    "dark_stroke": [1, 2, 3, 4, 5, 6, 7],
                    "raised_face": [8, 9, 10, 11, 12, 13, 14, 15],
                },
            )
            self.assertEqual(
                item["index_layer_sequence"],
                [
                    "transparent:0",
                    "attached-halo:1..4",
                    "dark-stroke:1..7",
                    "raised-face:8..15",
                ],
            )
            self.assertEqual(
                set(item["output_zone_index_counts"]["halo"]),
                {"1", "2", "3", "4"},
            )
            self.assertLessEqual(
                set(item["output_zone_index_counts"]["anti_alias"]),
                {"1", "2", "3"},
            )
            self.assertEqual(
                set(item["output_zone_index_counts"]["side"]),
                {str(index) for index in range(1, 8)},
            )
            self.assertEqual(
                set(item["output_zone_index_counts"]["face"]),
                {str(index) for index in range(8, 16)},
            )
            self.assertTrue(item["outer_boundary_uses_semantic_halo_only"])
            self.assertLessEqual(
                set(item["outer_boundary_output_index_counts"]),
                {"1", "2", "3"},
            )
            self.assertTrue(item["source_histogram_used_as_zone_quantile_reference"])
            self.assertEqual(item["dark_speckle_pixels_converted_to_light"], 0)
            left, _top, right, _bottom = item["render_ink_bounds"]
            self.assertEqual(left, (128 - (right - left)) // 2)
        self.assertTrue(
            report["acceptance"][
                "status_markers_copied_from_source_after_full_slot_clear"
            ]
        )
        self.assertEqual(report["atlas"]["changed_logical_pixel_counts"][3], 0)


if __name__ == "__main__":
    unittest.main()
