"""Extract a display isosurface from an NPZ in centered source X/Y/Z coordinates.

This demo-only mesh interpolates the density at voxel centers. The assembly
solver instead fits a thresholded cubic-cell target; this surface is not its
optimization input. No axis permutation, mirroring, or brick scaling is applied.

Uses scikit-image's Lewiner marching cubes implementation:
https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.marching_cubes
Lewiner, Lopes, Vieira, and Tavares (2003), doi:10.1080/10867651.2003.10487582.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import skimage
from skimage.measure import marching_cubes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.input_data import load_density


def extract_mesh(npz: Path, key: str, threshold: float) -> dict:
    """Return a finite indexed triangle mesh with provenance and unit spacing."""
    if not np.isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError("A display isosurface threshold must lie strictly between 0 and 1.")
    density = load_density(npz, key)
    # The library uses float32 internally. Make that conversion explicit and
    # pad by one zero-valued sample to close material touching the domain edge.
    padded = np.pad(np.asarray(density, dtype=np.float32), 1, constant_values=0)
    if float(padded.max()) <= threshold:
        raise ValueError("The selected density has no values above the isosurface threshold.")
    positions, faces, normals, _ = marching_cubes(
        padded,
        level=threshold,
        spacing=(1.0, 1.0, 1.0),
        gradient_direction="descent",
        step_size=1,
        allow_degenerate=False,
        method="lewiner",
    )
    # Padded sample 1 is original cell-center 0.5. The source domain center is
    # shape/2; keeping this frame matches the planner's centered resampling grid.
    shape = np.asarray(density.shape, dtype=np.float64)
    positions = positions.astype(np.float64) - 0.5 - shape / 2
    # scikit-image's descent faces use a left-hand convention. Reverse them for
    # outward counter-clockwise WebGL faces in the unchanged X/Y/Z axis order.
    faces = np.ascontiguousarray(faces[:, ::-1], dtype=np.int32)
    if not len(positions) or not len(faces):
        raise ValueError("Marching cubes produced an empty surface.")
    if not np.isfinite(positions).all() or not np.isfinite(normals).all():
        raise ValueError("Marching cubes produced nonfinite positions or normals.")
    if faces.min() < 0 or faces.max() >= len(positions):
        raise ValueError("A triangle references a vertex outside the mesh.")
    triangles = positions[faces]
    double_areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    if not np.isfinite(double_areas).all() or np.any(double_areas <= 0):
        raise ValueError("The mesh contains nonfinite or degenerate triangles.")

    return {
        "schema_version": 1,
        "positions": positions.ravel().tolist(),
        "faces": faces.ravel().tolist(),
        "normals": normals.ravel().tolist(),
        "shape": list(density.shape),
        "bounds": {"min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
        "source_bounds": {"min": (-shape / 2).tolist(), "max": (shape / 2).tolist()},
        "provenance": {
            "source_filename": npz.name,
            "source_sha256": hashlib.sha256(npz.read_bytes()).hexdigest(),
            "array_key": key,
            "threshold": threshold,
            "source_axes": ["x", "y", "z"],
            "up": "y",
            "mirror": "none",
            "units": "cubic source voxel edge lengths; no physical or brick scale applied",
            "origin": "center of the source array bounding box",
            "sample_location": "voxel centers",
            "padding": "one zero-valued sample per boundary",
            "algorithm": "skimage.measure.marching_cubes(method='lewiner', step_size=1)",
            "working_dtype": "float32",
            "scikit_image_version": skimage.__version__,
            "numpy_version": np.__version__,
            "method_reference": "https://doi.org/10.1080/10867651.2003.10487582",
            "interpretation": "Interpolated density isosurface for visualization; solver fit uses thresholded cubic cells.",
        },
        "validation": {
            "finite_positions_and_normals": True,
            "triangle_indices_valid": True,
            "nondegenerate_triangles": True,
            "vertex_count": len(positions),
            "triangle_count": len(faces),
            "minimum_triangle_area": float(double_areas.min() / 2),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npz", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Destination JSON mesh")
    parser.add_argument("--key", default="density", help="NPZ array key; default density")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    if args.output.resolve() == args.npz.resolve():
        parser.error("--output must not overwrite the source NPZ")
    mesh = extract_mesh(args.npz, args.key, args.threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mesh, separators=(",", ":"), allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "shape": mesh["shape"],
                      "bounds": mesh["bounds"], "validation": mesh["validation"],
                      "provenance": mesh["provenance"]}, indent=2))


if __name__ == "__main__":
    main()
