"""Portable NPZ interchange cases written with NumPy, not solver fixtures."""

import io
from pathlib import Path
import struct
import tempfile
import unittest
import warnings
import zipfile

import numpy as np

from backend.input_data import inspect_npz, load_density


class NpzInputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "topology.npz"

    def tearDown(self):
        self.directory.cleanup()

    def save(self, **arrays):
        np.savez_compressed(self.path, **arrays)
        return self.path

    def test_supported_numeric_types_endianness_and_storage_order(self):
        expected = np.array([0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 0, 1]).reshape(2, 3, 2)
        for kind in ("f4", "f8", "i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8", "b1"):
            for endian in ("<", ">"):
                for order in ("C", "F"):
                    with self.subTest(kind=kind, endian=endian, order=order):
                        source = np.array(expected, dtype=endian + kind, order=order)
                        self.save(density=source)
                        metadata = inspect_npz(self.path)
                        self.assertEqual(metadata["arrays"][0]["shape"], [2, 3, 2])
                        actual = load_density(self.path, "density")
                        self.assertEqual(actual.dtype, np.float64)
                        np.testing.assert_array_equal(actual, expected)

    def test_float64_threshold_precision_is_preserved(self):
        source = np.array([0.5 - 2**-40, 0.5, 0.5 + 2**-40]).reshape(1, 1, 3)
        self.save(density=source)
        actual = load_density(self.path, "density")
        np.testing.assert_array_equal(actual, source)
        np.testing.assert_array_equal(actual >= 0.5, [[[False, True, True]]])

    def test_noncanonical_boolean_true_bytes_follow_numpy_semantics(self):
        source = np.array([0, 1, 2, 255], dtype=np.uint8).view(np.bool_).reshape(1, 2, 2)
        self.save(density=source)
        np.testing.assert_array_equal(load_density(self.path, "density"), [[[0, 1], [1, 1]]])

    def test_unsupported_dtypes_do_not_become_density(self):
        for dtype in (np.float16, np.complex64, np.complex128, object,
                      "U1", [ ("material", "f4") ]):
            with self.subTest(dtype=dtype):
                self.save(density=np.zeros((2, 2, 2), dtype=dtype))
                with self.assertRaises(ValueError):
                    inspect_npz(self.path)
                with self.assertRaises(ValueError):
                    load_density(self.path, "density")

    def test_metadata_and_non_array_zip_members_are_ignored(self):
        source = np.ones((2, 3, 2), dtype=np.float32)
        self.save(density=source, label=np.array("bridge"), iterations=np.array(20),
                  ignored_float16=np.ones((2, 2, 2), dtype=np.float16),
                  object_metadata=np.array({"unused": True}, dtype=object))
        with zipfile.ZipFile(self.path, "a") as archive:
            archive.writestr("README.txt", "Description without planner settings.")
        metadata = inspect_npz(self.path)
        self.assertEqual([item["key"] for item in metadata["arrays"]], ["density"])
        np.testing.assert_array_equal(load_density(self.path, "density"), source)
        with self.assertRaises(ValueError):
            load_density(self.path, "README.txt")

    def test_discovery_does_not_silently_replace_an_invalid_selected_density(self):
        for value in (np.nan, np.inf, -0.01, 1.01):
            with self.subTest(value=value):
                self.save(density=np.full((2, 2, 2), value), design=np.ones((2, 2, 2)))
                self.assertEqual([item["key"] for item in inspect_npz(self.path)["arrays"]], ["density", "design"])
                with self.assertRaisesRegex(ValueError, "finite values"):
                    load_density(self.path, "density")
                self.assertTrue(np.all(load_density(self.path, "design") == 1))

    def test_nonempty_three_dimensional_requirement_and_missing_keys(self):
        for shape in ((2, 2), (2, 2, 2, 1), (2, 0, 2)):
            with self.subTest(shape=shape):
                self.save(density=np.zeros(shape))
                with self.assertRaises(ValueError):
                    inspect_npz(self.path)
                with self.assertRaises(ValueError):
                    load_density(self.path, "density")
        self.save(density=np.ones((1, 1, 1)))
        with self.assertRaisesRegex(ValueError, "not present"):
            load_density(self.path, "missing")

    def test_v2_headers_above_numpy_default_are_supported_up_to_application_limit(self):
        array = np.ones((1, 1, 1), dtype="<f4")
        header = "{'descr': '<f4', 'fortran_order': False, 'shape': (1, 1, 1), }"
        # Prefix plus header is 64-byte aligned, as for ordinary NPY output.
        for header_length in (12020, 65524, 65588):
            with self.subTest(header_length=header_length):
                padded = header.ljust(header_length - 1) + "\n"
                data = b"\x93NUMPY\x02\x00" + struct.pack("<I", header_length) + padded.encode("ascii") + array.tobytes()
                with zipfile.ZipFile(self.path, "w") as archive:
                    archive.writestr("density.npy", data)
                if header_length <= 65536:
                    self.assertEqual(inspect_npz(self.path)["arrays"][0]["shape"], [1, 1, 1])
                    np.testing.assert_array_equal(load_density(self.path, "density"), array)
                else:
                    with self.assertRaises(ValueError):
                        inspect_npz(self.path)
                    with self.assertRaises(ValueError):
                        load_density(self.path, "density")

    def test_archive_entry_limit_includes_ignored_members_and_duplicate_names(self):
        buffer = io.BytesIO()
        np.save(buffer, np.ones((1, 1, 1)))
        for count in (64, 65):
            with self.subTest(count=count):
                with zipfile.ZipFile(self.path, "w") as archive:
                    archive.writestr("density.npy", buffer.getvalue())
                    for index in range(count - 1):
                        archive.writestr(f"note-{index}.txt", "ignored")
                if count == 64:
                    self.assertEqual(len(inspect_npz(self.path)["arrays"]), 1)
                else:
                    with self.assertRaisesRegex(ValueError, "64-entry"):
                        inspect_npz(self.path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.path, "w") as archive:
                archive.writestr("density.npy", buffer.getvalue())
                archive.writestr("density.npy", buffer.getvalue())
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            inspect_npz(self.path)


if __name__ == "__main__":
    unittest.main()
