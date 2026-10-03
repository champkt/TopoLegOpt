"""Geometric regression cases independent of the placement heuristic."""

import json
import unittest

from backend.validation import CATALOG, GEOMETRY, validate_assembly, validate_sequence


def brick(brick_id, part_id, x=0, y=0, z=0, rotate=False):
    width, depth = CATALOG[part_id]
    if rotate:
        width, depth = depth, width
    return {"id": brick_id, "part_id": part_id, "x": x, "y": y, "z": z, "width": width, "depth": depth, "height": 1}


class AssemblyValidationTests(unittest.TestCase):
    def test_adjacent_bricks_need_a_real_stud_bridge(self):
        pieces = [brick("left", "2x1"), brick("right", "2x1", x=2)]
        result = validate_assembly(pieces, {"2x1": 3})
        self.assertFalse(result["valid"])
        self.assertEqual(result["component_count"], 2)
        self.assertEqual(result["connection_edges"], [])
        pieces.append(brick("bridge", "2x1", x=1, y=1))
        result = validate_assembly(pieces, {"2x1": 3}, ["x"], [4, 2, 1])
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["crossing_bricks"], {"x": ["bridge"]})
        self.assertEqual(result["connection_edges"], [["left", "bridge"], ["right", "bridge"]])
        self.assertEqual([item["studs"] for item in result["connection_contacts"]], [1, 1])

    def test_top_view_overlap_is_not_contact_across_layer_gap(self):
        result = validate_assembly([brick(0, "2x2"), brick(1, "2x2", y=2)], {"2x2": 2})
        self.assertFalse(result["connected"])
        self.assertTrue(result["no_overlaps"])

    def test_same_layer_overlap_and_rotation_share_stock(self):
        result = validate_assembly([brick(0, "2x3"), brick(1, "2x3", x=1, rotate=True)], {"2x3": 1})
        self.assertFalse(result["no_overlaps"])
        self.assertFalse(result["inventory_valid"])
        self.assertEqual(result["inventory_usage"]["2x3"], 2)

    def test_diagonal_or_edge_contact_does_not_engage_a_stud(self):
        for x, z in [(2, 0), (0, 2), (2, 2)]:
            with self.subTest(x=x, z=z):
                result = validate_assembly([brick(0, "2x2"), brick(1, "2x2", x=x, z=z, y=1)], {"2x2": 2})
                self.assertFalse(result["connected"])
                self.assertEqual(result["connection_edges"], [])

    def test_detail_cannot_be_the_only_connection_between_structural_bricks(self):
        pieces = [brick(0, "2x1"), brick(1, "1x1", y=1), brick(2, "2x1", y=2)]
        result = validate_assembly(pieces, {"2x1": 2, "1x1": 1})
        self.assertTrue(result["connected"])
        self.assertFalse(result["structural_connected"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["structural_component_count"], 2)

    def test_detail_attached_to_connected_structure_is_allowed(self):
        result = validate_assembly([brick(0, "2x1"), brick(1, "1x1", y=1)], {"2x1": 1, "1x1": 1})
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["detail_piece_count"], 1)
        self.assertFalse(validate_assembly([brick(0, "1x1")], {"1x1": 1})["valid"])

    def test_symmetric_voxel_volume_does_not_imply_symmetric_brick_placements(self):
        # The complete rectangular prism is symmetric, but the layer seam is not.
        pieces = [brick(0, "2x1"), brick(1, "4x1", x=2), brick(2, "6x1", y=1)]
        result = validate_assembly(pieces, {"2x1": 1, "4x1": 1, "6x1": 1}, ["x"], [6, 2, 1])
        self.assertTrue(result["connected"])
        self.assertFalse(result["symmetry_valid"])
        self.assertTrue(result["center_bridges_valid"])

    def test_symmetric_halves_without_a_center_piece_are_invalid(self):
        result = validate_assembly([brick(0, "2x2"), brick(1, "2x2", x=2)], {"2x2": 2}, ["x"], [4, 1, 2])
        self.assertTrue(result["symmetry_valid"])
        self.assertFalse(result["center_bridges_valid"])
        self.assertEqual(result["crossing_bricks"]["x"], [])

    def test_two_symmetry_planes_can_share_one_centered_brick(self):
        result = validate_assembly([brick("center", "2x2", x=1, z=1)], {"2x2": 1}, [0, 2], [4, 1, 4])
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["crossing_bricks"], {"x": ["center"], "z": ["center"]})

    def test_odd_width_center_can_use_odd_structural_dimension(self):
        result = validate_assembly([brick(0, "2x3", rotate=True)], {"2x3": 1}, ["x"], [3, 1, 2])
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["symmetry_planes"]["x"], 1.5)

    def test_vertical_symmetry_requires_odd_layers_and_centered_layer(self):
        pieces = [brick(y, "2x2", y=y) for y in range(3)]
        result = validate_assembly(pieces, {"2x2": 3}, ["y"], [2, 3, 2])
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["crossing_bricks"]["y"], [1])
        result = validate_assembly(pieces[:2], {"2x2": 2}, ["y"], [2, 2, 2])
        self.assertTrue(result["symmetry_valid"])
        self.assertFalse(result["center_bridges_valid"])

    def test_cap_is_ceiling_with_five_percent_rounded_down(self):
        pieces = [brick(i, "2x2", y=i) for i in range(21)]
        result = validate_assembly(pieces, {"2x2": 22}, piece_cap=20)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["piece_cap_upper"], 21)
        result = validate_assembly(pieces + [brick(21, "2x2", y=21)], {"2x2": 22}, piece_cap=20)
        self.assertFalse(result["budget_valid"])
        self.assertTrue(validate_assembly(pieces[:2], {"2x2": 22}, piece_cap=20)["valid"])
        self.assertFalse(validate_assembly(pieces[:2], {"2x2": 22}, piece_cap=1)["budget_valid"])
        result = validate_assembly(pieces, {"2x2": 22}, piece_cap=100, cap_tolerance=0.15)
        self.assertEqual(result["piece_cap_upper"], 115)

    def test_bad_dimensions_and_metadata_are_not_trusted(self):
        bad = brick(0, "2x1")
        for field, value in [("width", 2000000000), ("height", 2), ("x", 0.5), ("y", True), ("part_id", [])]:
            with self.subTest(field=field):
                result = validate_assembly([{**bad, field: value}], {"2x1": 1})
                self.assertFalse(result["valid"])
                self.assertFalse(result["geometry_valid"])

    def test_boundaries_and_duplicate_ids_are_checked(self):
        for pieces in [[brick(0, "2x1", x=-1)], [brick(0, "2x1", x=1)], [brick(0, "2x1"), brick(0, "2x1", y=1)]]:
            result = validate_assembly(pieces, {"2x1": 2}, grid_shape=[2, 2, 1])
            self.assertFalse(result["geometry_valid"])
            self.assertFalse(result["valid"])

    def test_empty_and_malformed_inputs_are_invalid_without_exceptions(self):
        for placements, inventory, kwargs in [
            ([], {}, {}), (None, None, {}), ([None], {"2x1": 1}, {}),
            ([brick(0, "2x1")], {"2x1": -1}, {}),
            ([brick(0, "2x1")], {"2x1": True}, {}),
            ([brick(0, "2x1")], {"2x1": 1}, {"piece_cap": float("nan")}),
            ([brick(0, "2x1")], {"2x1": 1}, {"cap_tolerance": float("nan")}),
            ([brick(0, "2x1")], {"2x1": 1}, {"symmetry_axes": ["x"]}),
            ([brick(0, "2x1")], {"2x1": 1}, {"grid_shape": [2, 0, 1]}),
            ([brick(0, "2x1")], {"2x1": 1}, {"symmetry_axes": [[]]}),
        ]:
            with self.subTest(placements=placements, inventory=inventory, kwargs=kwargs):
                result = validate_assembly(placements, inventory, **kwargs)
                self.assertFalse(result["valid"])
                json.dumps(result, allow_nan=False)

    def test_browser_inventory_document_cannot_redefine_physical_geometry(self):
        inventory = {"schema_version": 1, "geometry": dict(GEOMETRY), "parts": [
            {"id": part_id, "studs": list(dimensions), "height_layers": 1, "role": "detail" if part_id == "1x1" else "structure", "quantity": 1}
            for part_id, dimensions in CATALOG.items()
        ]}
        result = validate_assembly([brick(0, "2x1")], inventory)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["geometry"], {"stud_pitch": 5, "layer_height": 6, "units": "relative"})
        inventory["geometry"]["layer_height"] = 5
        self.assertFalse(validate_assembly([brick(0, "2x1")], inventory)["inventory_valid"])


class SequenceValidationTests(unittest.TestCase):
    def setUp(self):
        # A roof joins two lower sections; contact-first traversal can fill the
        # floor before inserting the last middle brick, trapping that brick.
        self.pieces = [brick(1, "2x2"), brick(2, "2x1", y=1),
                       brick(3, "2x1", y=1, z=1), brick(4, "2x6", y=2, rotate=True),
                       brick(5, "2x2", x=2, y=1), brick(6, "2x4", x=2, rotate=True),
                       brick(7, "2x2", x=4, y=1)]

    def test_contact_traversal_can_trap_a_brick_between_floor_and_roof(self):
        sequence = [{"brick_ids": [pid], "requires_support": True} for pid in [1, 2, 3, 4, 5, 6, 7]]
        result = validate_sequence(self.pieces, sequence)
        self.assertTrue(result["complete"])
        self.assertFalse(result["top_down_clearance"])
        self.assertFalse(result["valid"])
        self.assertIn(4, result["step_evidence"][-1]["obstructed_by"])

    def test_layer_order_is_clear_even_with_separate_ground_sections(self):
        sequence = [{"brick_ids": [pid], "requires_support": False} for pid in [1, 6, 2, 3, 5, 7, 4]]
        result = validate_sequence(self.pieces, sequence)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["top_down_clearance"])
        self.assertEqual(result["independent_ground_bricks"], [1, 6])
        self.assertFalse(result["contact_order"])
        self.assertEqual(result["support_required_bricks"], [])

    def test_elevated_brick_without_lower_contact_needs_explicit_support(self):
        pieces = [brick(1, "2x1"), brick(2, "2x1", y=1),
                  brick(3, "2x1", x=2, y=1), brick(4, "4x1", y=2)]
        sequence = [{"brick_ids": [pid], "requires_support": False} for pid in [1, 2, 3, 4]]
        result = validate_sequence(pieces, sequence)
        self.assertTrue(result["top_down_clearance"])
        self.assertFalse(result["support_notes_valid"])
        self.assertEqual(result["support_required_bricks"], [3])
        sequence[2]["requires_support"] = True
        self.assertTrue(validate_sequence(pieces, sequence)["valid"])

    def test_ground_surface_uses_lowest_occupied_layer(self):
        pieces = [brick(1, "2x2", y=5), brick(2, "2x2", y=6)]
        result = validate_sequence(pieces, [{"brick_ids": [1]}, {"brick_ids": [2]}])
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["ground_layer"], 5)
        self.assertEqual(result["support_required_bricks"], [])

    def test_missing_duplicate_unknown_and_incorrect_contact_ids_fail(self):
        pieces = [brick(1, "2x2"), brick(2, "2x2", y=1)]
        for sequence in [
            [{"brick_ids": [1]}],
            [{"brick_ids": [1]}, {"brick_ids": [1]}, {"brick_ids": [2]}],
            [{"brick_ids": [1]}, {"brick_ids": [99]}],
            [{"brick_ids": [1]}, {"brick_ids": [2], "attached_to": []}],
            [{"brick_ids": [1]}, {"brick_ids": [2], "attached_to": [[]]}],
        ]:
            with self.subTest(sequence=sequence):
                self.assertFalse(validate_sequence(pieces, sequence)["valid"])

    def test_roof_blocks_insertion_even_when_several_layers_above(self):
        pieces = [brick(1, "2x2", y=4), brick(2, "2x2")]
        result = validate_sequence(pieces, [{"brick_ids": [1], "requires_support": True}, {"brick_ids": [2]}])
        self.assertFalse(result["top_down_clearance"])


if __name__ == "__main__":
    unittest.main()
