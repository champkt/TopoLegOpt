"""Behavioral regressions for scale, real contacts, symmetry, and build ordering."""

import json
import unittest
from unittest.mock import patch

import numpy as np

from backend.solver import _sequence, resample_occupancy, solve
from backend.validation import validate_assembly


MIXED_STOCK = {"1x1": 40, "2x1": 30, "4x1": 20, "6x1": 12,
               "2x2": 20, "2x3": 16, "2x4": 20, "2x6": 12, "2x8": 12}


class SolverTests(unittest.TestCase):
    def test_resampling_preserves_volume_and_physical_aspect(self):
        mask = np.ones((5, 7, 9), dtype=bool)
        scale = 0.67
        field = resample_occupancy(mask, scale)
        self.assertAlmostEqual(float(field.sum()) * 1.2 / scale ** 3,
                               int(mask.sum()), places=4)
        self.assertEqual(field.shape, (4, 4, 7))
        self.assertLess(float(field[0].mean()), 1)
        self.assertTrue(np.allclose(field, np.flip(field, axis=0)))

    def test_full_symmetry_has_actual_crossing_bricks_on_all_planes(self):
        result = solve(np.ones((12, 8, 16)), MIXED_STOCK)
        self.assertTrue(result["success"], result["diagnostics"])
        self.assertEqual(set(result["symmetry"]["build_axes"]), {"x", "y", "z"})
        self.assertEqual(result["dimensions"][1] % 2, 1)
        validation = result["validation"]
        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(validation["component_count"], 1)
        for axis in ("x", "y", "z"):
            self.assertTrue(validation["crossing_bricks"][axis])
        json.dumps(result, allow_nan=False)

    def test_inventory_and_cap_include_details_with_floor_tolerance(self):
        result = solve(np.ones((12, 8, 16)), MIXED_STOCK,
                       {"piece_cap": 60, "tolerance": 0.05})
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["placements"]), 63)
        for part, used in result["inventory_usage"].items():
            self.assertLessEqual(used, MIXED_STOCK[part])
        self.assertLessEqual(result["metrics"]["detail_count"],
                             int(0.1 * result["metrics"]["structural_count"]))
        self.assertTrue(result["validation"]["structural_connected"])

    def test_one_piece_cap_does_not_round_up_to_two(self):
        result = solve(np.ones((8, 8, 8)), {"2x2": 10},
                       {"piece_cap": 1, "tolerance": 0.05})
        self.assertTrue(result["success"], result["diagnostics"])
        self.assertEqual(len(result["placements"]), 1)
        self.assertEqual(result["metrics"]["maximum_pieces"], 1)

    def test_detail_pieces_never_replace_structural_stock(self):
        result = solve(np.ones((6, 6, 6)), {"1x1": 1000})
        self.assertFalse(result["success"])
        self.assertEqual(result["placements"], [])
        self.assertIn("reserved for details", result["diagnostics"][0])

    def test_empty_and_nonfinite_topology(self):
        result = solve(np.zeros((4, 4, 4)), MIXED_STOCK)
        self.assertFalse(result["success"])
        for array in (np.full((3, 3, 3), np.nan), np.full((3, 3, 3), np.inf),
                      np.ones((3, 3))):
            with self.assertRaises(ValueError):
                solve(array, MIXED_STOCK)

    def test_boolean_masks_match_numeric_masks_and_invalid_density_is_rejected(self):
        mask = np.ones((8, 8, 8), dtype=bool)
        options = {"piece_cap": 1, "scale_factors": [1.0]}
        numeric = solve(mask.astype(np.float32), {"2x2": 1}, options)
        boolean = solve(mask, {"2x2": 1}, options)
        self.assertTrue(boolean["success"], boolean["diagnostics"])
        self.assertEqual(boolean["placements"], numeric["placements"])
        for array in (np.full((3, 3, 3), -0.01), np.full((3, 3, 3), 1.01),
                      np.ones((3, 3, 3), dtype=np.complex128),
                      np.full((3, 3, 3), "1", dtype=object)):
            with self.subTest(dtype=array.dtype, sample=array.flat[0]):
                with self.assertRaises(ValueError):
                    solve(array, MIXED_STOCK)

    def test_invalid_stock_and_cap_are_rejected(self):
        for stock in ({"2x1": -1}, {"2x1": 1.5}, {"2x1": True}, {"unknown": 3}):
            with self.assertRaises(ValueError):
                solve(np.ones((3, 3, 3)), stock)
        for cap in (0, -3, 2.5, True):
            with self.assertRaises(ValueError):
                solve(np.ones((3, 3, 3)), MIXED_STOCK, {"piece_cap": cap})

    def test_source_axis_permutation_is_explicit(self):
        result = solve(np.ones((8, 12, 6)), MIXED_STOCK,
                       {"up": "z", "symmetry": "z", "piece_cap": 40})
        self.assertTrue(result["success"], result["diagnostics"])
        self.assertEqual(result["source_to_build_axes"], ["x", "z", "y"])
        self.assertEqual(result["source_to_build_axis_signs"], [1, 1, -1])
        self.assertEqual(result["symmetry"]["build_axes"], ["y"])
        self.assertTrue(result["validation"]["crossing_bricks"]["y"])

    def test_changing_up_axis_rotates_asymmetric_landmarks_without_reflection(self):
        # Three distinct positive-axis arm lengths make these four landmarks
        # distinguishable; unsigned transposition changes their handedness.
        density = np.zeros((3, 4, 5), dtype=bool)
        for point in ((0, 0, 0), (2, 0, 0), (0, 3, 0), (0, 0, 4)):
            density[point] = True
        cases = {
            "x": (np.rot90(density, 1, axes=(0, 1)), ["y", "x", "z"], [-1, 1, 1]),
            "y": (density, ["x", "y", "z"], [1, 1, 1]),
            "z": (np.rot90(density, -1, axes=(1, 2)), ["x", "z", "y"], [1, 1, -1]),
        }
        for up, (expected, axes, signs) in cases.items():
            captured = []

            def record_mask(mask, scale, symmetry):
                captured.append(mask.copy())
                return resample_occupancy(mask, scale, symmetry)

            with self.subTest(up=up), patch("backend.solver.resample_occupancy", side_effect=record_mask):
                result = solve(density, {"2x2": 4}, {"up": up, "symmetry": "none", "scale_factors": [1.0]})
                self.assertEqual(len(captured), 1)
                np.testing.assert_array_equal(captured[0], expected)
                self.assertEqual(result["source_to_build_axes"], axes)
                self.assertEqual(result["source_to_build_axis_signs"], signs)
                transform = np.diag(signs) @ np.eye(3)[["xyz".index(axis) for axis in axes]]
                self.assertAlmostEqual(np.linalg.det(transform), 1.0)

    def test_mirror_option_matches_explicit_reflected_field(self):
        density = np.ones((6, 5, 8))
        density[:, 3:, 3:] = 0
        options = {"piece_cap": 50, "symmetry": "auto", "scale_factors": [0.9, 1.0]}
        implicit = solve(density, MIXED_STOCK, dict(options, mirror="z"))
        explicit = solve(np.concatenate((density[:, :, ::-1], density), axis=2),
                         MIXED_STOCK, options)
        self.assertTrue(implicit["success"], implicit["diagnostics"])
        self.assertEqual(implicit["placements"], explicit["placements"])
        self.assertIn("z", implicit["symmetry"]["build_axes"])

    def test_disconnected_source_is_reported(self):
        density = np.zeros((12, 8, 12))
        density[:4, :, :] = 1
        density[8:, :, :] = 1
        result = solve(density, MIXED_STOCK,
                       {"symmetry": "none", "piece_cap": 40})
        self.assertTrue(any("disconnected voxel components" in w for w in result["warnings"]))
        if result["success"]:
            self.assertTrue(result["validation"]["connected"])
            self.assertEqual(result["metrics"]["target_component_count"], 2)

    def test_bottom_up_sequence_avoids_sandwich_insertion_trap(self):
        # A contact-first traversal can roof over brick 7 before it is inserted.
        specs = [(1, "2x2", 0, 0, 0, 2, 2), (2, "2x1", 0, 1, 0, 2, 1),
                 (3, "2x1", 0, 1, 1, 2, 1), (4, "2x6", 0, 2, 0, 6, 2),
                 (5, "2x2", 2, 1, 0, 2, 2), (6, "2x4", 2, 0, 0, 4, 2),
                 (7, "2x2", 4, 1, 0, 2, 2)]
        placements = [dict(id=pid, part_id=part, x=x, y=y, z=z,
                           width=w, depth=d, height=1)
                      for pid, part, x, y, z, w, d in specs]
        inventory = {"2x2": 3, "2x1": 2, "2x6": 1, "2x4": 1}
        validation = validate_assembly(placements, inventory)
        self.assertTrue(validation["valid"], validation["errors"])
        sequence = _sequence(placements, validation["connection_edges"])
        order = [step["brick_ids"][0] for step in sequence]
        self.assertLess(order.index(7), order.index(4))
        by_id = {brick["id"]: brick for brick in placements}
        self.assertEqual([by_id[pid]["y"] for pid in order], [0, 0, 1, 1, 1, 1, 2])
        self.assertTrue(sequence[1]["starts_subassembly"])

    def test_raised_unsupported_bricks_are_flagged_in_sequence(self):
        placements = [dict(id=1, part_id="2x2", x=0, y=4, z=0, width=2, depth=2, height=1),
                      dict(id=2, part_id="2x2", x=2, y=5, z=0, width=2, depth=2, height=1),
                      dict(id=3, part_id="2x4", x=0, y=6, z=0, width=4, depth=2, height=1)]
        sequence = _sequence(placements, [[2, 3]])
        self.assertFalse(sequence[0]["requires_support"])
        self.assertTrue(sequence[1]["requires_support"])
        self.assertIn("temporary support", sequence[1]["instruction"])


if __name__ == "__main__":
    unittest.main()
