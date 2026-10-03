#!/usr/bin/env python3
"""Create a portable, synthetic TopoLegOpt input using only NumPy.

Run from any directory:
    python /path/to/TopoLegOpt/examples/create_topology.py --output bridge.npz

The density is a full arched bridge in source (X, Y, Z) coordinates, with Y up.
Use threshold 0.5 and no mirroring. No external topology data is read.
"""

import argparse
from pathlib import Path

import numpy as np


def create_bridge() -> np.ndarray:
    """Return a C-order little-endian float32 density with shape (48, 24, 12)."""
    nx, ny, nz = 48, 24, 12
    # Evaluate at cell centers so reflection about the X/Z midplanes is exact.
    x = np.arange(nx, dtype=np.float64)[:, None, None] + 0.5 - nx / 2
    y = np.arange(ny, dtype=np.float64)[None, :, None] + 0.5
    arch_opening = (x / 16.0) ** 2 + (y / 17.0) ** 2 < 1.0
    solid = np.broadcast_to(~arch_opening, (nx, ny, nz))
    return np.ascontiguousarray(solid, dtype=np.dtype("<f4"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Destination .npz file")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file")
    args = parser.parse_args()
    path = args.output.expanduser()
    if path.suffix != ".npz":
        parser.error("--output must have a .npz extension")
    if path.exists() and not args.overwrite:
        parser.error(f"{path} already exists; choose another path or add --overwrite")

    density = create_bridge()
    path.parent.mkdir(parents=True, exist_ok=True)
    # A file object prevents NumPy from changing the requested output filename.
    with path.open("wb" if args.overwrite else "xb") as output:
        np.savez_compressed(output, density=density)
    with np.load(path, allow_pickle=False) as saved:
        if saved.files != ["density"]:
            raise RuntimeError("Unexpected array names in the generated archive")
        reloaded = saved["density"]
        if reloaded.dtype != np.dtype("<f4") or not reloaded.flags.c_contiguous:
            raise RuntimeError("Generated density has an unexpected data representation")
        np.testing.assert_array_equal(reloaded, density)

    print(f"Wrote {path.resolve()}")
    print(f"density: shape={density.shape}, dtype={density.dtype}, C-contiguous")
    print(f"Occupied cells at threshold 0.5: {np.count_nonzero(density >= 0.5):,}")
    print("Topology settings: Y up, threshold 0.5, no mirroring.")


if __name__ == "__main__":
    main()
