# Topology input specification

TopoLegOpt accepts a NumPy `.npz` archive containing a three-dimensional density
array. The file describes a shape on a regular grid of **cubic source voxels**.
It does not describe bricks, physical dimensions, loads, or a finished
assembly. The planner chooses brick scale from the inventory and piece budget.

For the simplest portable file, save one array named `density`, in `(X, Y, Z)`
order, as C-contiguous little-endian `float32`, with values between 0 and 1.
Upload it in **Topology**, confirm the vertical axis and threshold, then generate
an assembly with your inventory. No data from the original topology-optimization
projects is required.

## Recommended interchange profile

The following requirements define the recommended profile for other software
exporting to TopoLegOpt. The wider set of accepted inputs is described below.

| Property | Requirement |
| --- | --- |
| File | A `.npz` ZIP archive, written by `numpy.savez_compressed` or `numpy.savez` |
| Array name | `density`, stored as the root archive member `density.npy` |
| Array shape | Exactly three nonzero dimensions: `(nx, ny, nz)` |
| Coordinates | `density[x, y, z]`, where each index selects one cubic cell |
| Data type | Plain little-endian `float32` (`<f4`), C-contiguous |
| Values | Finite real numbers in the closed interval `[0, 1]` |
| Meaning | `0` is void, `1` is solid; intermediate values are density values to threshold |
| Array size | At most `32,000,000` cells in the source array |
| Archive size | At most `128 MiB` on disk and `512 MiB` unpacked, including headers |
| Additional data | Omit it from the portable file; inventory and planner settings are separate |

This is a TopoLegOpt application profile, not an extension to NumPy's file format.
NPZ is a ZIP container of NPY arrays; NumPy stores each array's shape, data type,
and memory order in its NPY header. See the
[NumPy format specification](https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html).

## Export your own topology

After converting your source to the coordinate convention described below, this
complete export function validates the data before writing it. It intentionally
rejects values outside `[0, 1]` instead of silently clipping them.

```python
from pathlib import Path
import numpy as np


def save_topology(path, density_xyz):
    path = Path(path)
    if path.suffix != ".npz":
        raise ValueError("Use a .npz filename")
    source = np.asarray(density_xyz)
    if source.ndim != 3 or not 0 < source.size <= 32_000_000:
        raise ValueError("Expected a nonempty (X, Y, Z) array <= 32 million cells")
    if source.dtype.kind not in "buif":
        raise ValueError("Expected a real numeric array or boolean mask")
    if not np.isfinite(source).all() or source.min() < 0 or source.max() > 1:
        raise ValueError("Density must be finite and within [0, 1]")

    density = np.ascontiguousarray(source, dtype=np.dtype("<f4"))
    np.savez_compressed(path, density=density)
    with np.load(path, allow_pickle=False) as saved:
        assert saved.files == ["density"]
        assert saved["density"].shape == density.shape
        assert saved["density"].dtype == np.dtype("<f4")
        np.testing.assert_array_equal(saved["density"], density)
    return path
```

Call `save_topology("my_topology.npz", your_density_xyz)` with your array. This
conversion rounds values to float32, so values extremely close to the chosen
threshold may change classification. Retain float64 if that precision matters.
The function checks array content and verifies a round trip; the importer also
enforces archive limits. The two NumPy functions are documented in
[`savez_compressed`](https://numpy.org/doc/stable/reference/generated/numpy.savez_compressed.html)
and [`load`](https://numpy.org/doc/stable/reference/generated/numpy.load.html).

For a runnable example needing only NumPy, use the synthetic arched bridge in
[`examples/create_topology.py`](../examples/create_topology.py):

```bash
# From the repository root, after installing the planner's Python dependencies:
brick-planner/.venv/bin/python examples/create_topology.py --output /tmp/bridge.npz
```

Upload `/tmp/bridge.npz` with **Y up**, threshold **0.5**, and **no mirroring**.
The example contains the complete bridge, with an opening beneath the arch. See
the [example instructions](../examples/README.md) for the expected statistics.

## Coordinates, geometry, and units

Array axes are spatial coordinates in this order:

| Array axis | Source coordinate | Default role |
| --- | --- | --- |
| 0 | X | Horizontal length |
| 1 | Y | Vertical height |
| 2 | Z | Horizontal depth |

An element `density[x, y, z]` occupies the cell
`[x, x+1] × [y, y+1] × [z, z+1]`; its center is
`(x+0.5, y+0.5, z+0.5)`. These are cell values, not values sampled at grid nodes.
All cell edge lengths are equal. The target bounding box has dimensions
`nx : ny : nz`. The entire array is used, including empty padding; the importer
does not crop the shape or read a stored origin.

**Storage order is different from axis order.** C versus Fortran ordering changes
which value is serialized first, not the meanings of X, Y, and Z. For a C-order
array, Z varies fastest. An image stack stored as `(Z, Y, X)` must be explicitly
transposed before export, for example `density_xyz = volume_zyx.transpose(2, 1, 0)`.
If image row indices increase downward, also reverse the corresponding axis
when an upward spatial direction is intended. Use a known asymmetric feature to
check the preview; an unlabeled array cannot communicate anatomical or world
orientation automatically.

The **Up axis** control selects which positive source axis becomes vertical in
the assembly. It does not reinterpret the file's axis labels. Returned assembly
coordinates always have build Y as vertical. Relative to the center of the
source bounding box, the conversion is a rotation:

| Selected source up axis | Build `(X, Y, Z)` comes from source |
| --- | --- |
| X | `(-Y, X, Z)` |
| Y, the default | `(X, Y, Z)` |
| Z | `(X, Z, -Y)` |

A minus sign means reversing that source index direction; it prevents an axis
swap from introducing an unintended reflection. Array indices are shifted back
to nonnegative coordinates after the rotation. Assembly JSON records the axis
names in `source_to_build_axes` and their signs in `source_to_build_axis_signs`.

The brick cell has relative build pitches `(5, 6, 5)`: a stud spacing of 5 in the
two horizontal directions and a full brick height of 6. The topology voxels stay
cubic. **Do not stretch your exported data to a 5:6:5 ratio**; accounting for this
difference is part of the planner's resampling step. Neither the input nor these
ratios specify millimeters or an absolute physical scale.

If your data has unequal physical voxel spacings, resample it onto a grid with
equal spacing in all three directions before export. Preserve the original
physical bounding box and axis order when choosing the new dimensions; simply
changing array shape or discarding a spacing vector will distort the shape.
For scalar density fields, choose an appropriate interpolation or volume-average
method for the source data. For categorical labels, select the intended material
and produce an occupancy mask; interpolating arbitrary label numbers does not
produce meaningful density. Record the resampling method and threshold with
your experiment, because both can change thin features and connectivity.

## Thresholds and incomplete targets

At threshold `t`, a source cell is occupied exactly when `density[x, y, z] >= t`.
The allowed threshold range is `[0, 1]`, inclusive; the default is `0.5`.
Thus a value of `0.5` is solid at the default threshold. A threshold of `0` makes
even zero-valued cells solid; use a positive threshold for a binary mask.

The solver thresholds the field before searching for brick scale. Intermediate
densities are not stiffness, probability, or material fractions carried into the
assembly optimization; after this first step the source target is binary.
The subsequent resampled cell fractions measure overlap with that binary target.

An all-zero array is a valid upload. At threshold `0.5` it gives an empty target,
so the planner reports that there is no shape to assemble. Disconnected targets
can also be uploaded. The solver warns about multiple face-connected components
and still seeks one connected brick assembly; it may omit components or bridge
gaps. A valid file therefore does not guarantee a feasible assembly with a given
inventory, cap, orientation, or symmetry setting. See the
[algorithm and its limitations](ALGORITHM.md).

## Half models and mirroring

Upload a complete model with **Mirror: none** unless your array intentionally
contains only one half. The mirror control reflects the array across the **low
boundary** of the selected source axis, then appends the original array:

```python
# Equivalent reconstruction for a saved half-model along source Z:
full = np.concatenate((np.flip(density, axis=2), density), axis=2)
```

The selected dimension doubles. Each source voxel appears exactly twice, on
opposite sides of a plane between cells; there is no shared center voxel or
omitted seam layer. For the one-dimensional example `[a, b, c]`, reconstruction
is `[c, b, a, a, b, c]`. The first saved slice is the one adjacent to the symmetry
plane. If the symmetry plane is at your last saved slice, reverse that axis before
export. A model sampled at nodes with a sample on the symmetry plane must first
be converted to cell values; the importer does not detect or remove such a sample.

Mirroring is applied before choosing the build orientation. You can mirror one
source axis in the UI; reconstruct additional half axes upstream if necessary.
Do not mirror a file that already contains both halves.

**Mirroring and assembly symmetry are separate controls.** Mirroring reconstructs
the target shape. The Assembly tab's symmetry setting constrains brick bodies
and requires structural bricks crossing the selected central planes. Keeping
Mirror at `none` still allows a complete symmetric model to receive a symmetric
assembly.

## Other accepted inputs and limits

The application also reads the following common NPZ variants. Exporters should
prefer the minimal profile above to avoid ambiguity.

| Feature | Supported behavior |
| --- | --- |
| ZIP compression | Standard stored or DEFLATE members, as written by NumPy |
| NPY format versions | 1.0, 2.0, and 3.0 |
| Numeric types | float32, float64; signed/unsigned 8-, 16-, 32-, 64-bit integers; boolean |
| Numeric range | Every selected value must still be finite and in `[0, 1]`; integer masks therefore contain only 0 and 1 |
| Byte order | Little- and big-endian numeric arrays |
| Array storage | C-contiguous and Fortran-contiguous arrays |
| Array naming | `density` is selected first, then `design`, then the first supported 3D array in the archive |
| Multiple 3D arrays | Select the intended array explicitly in the Topology tab |
| Unsupported types | float16, extended-precision floats, complex, object/pickle, strings, structured/record arrays |
| Archive entries | At most 64 entries; duplicate member names are unsupported |
| NPY headers | At most 65,536 bytes; ordinary density arrays are much smaller |
| Array payload | Exactly `nx × ny × nz × itemsize` data bytes after the NPY header; truncated or trailing payload data is rejected |

Array discovery checks dimensionality and numeric format; automatic selection
does not mean that the selected array has already passed range validation. For
example, an out-of-range array named `density` will fail instead of silently
switching to a valid `design` array. Use the `density` key for the final physical
density you intend to threshold, not for stresses, material IDs, or an unrelated
optimization variable. A `design` array is treated as ordinary density values;
TopoLegOpt does not apply an upstream optimizer's density filter or projection.

The limits on file size, archive entries, and unpacked size apply to the entire
archive, even when only one array will be selected. The 32-million-cell limit is
for the selected source array before mirroring. One reflection can double its
logical size. Memory use can exceed the NPZ file size substantially because the
browser holds decoded float64 density and display buffers. Large source grids
may use a reduced display mesh; this preview reduction does not replace the
original array used by the solver. The browser worker has a 60-second operation
timeout. A solver run has separate limits described in the algorithm document.

**Metadata does not configure the planner.** Scalar, string, and non-3D metadata
arrays may be ignored, but they are not part of the recommended profile. Fields
such as `spacing`, `origin`, `axes`, `units`, `threshold`, `loads`, `supports`,
`fixed_nodes`, and `symmetry` have no special meaning to TopoLegOpt. A supported
3D numeric metadata array can even appear in the array selector. Export only the
intended density, and set threshold, orientation, and mirroring in the UI.
Physical boundary conditions are not imported or used for strength analysis.
Object data is never unpickled.

## Troubleshooting an export

| Symptom | Likely cause and correction |
| --- | --- |
| No supported 3D array | Convert a 2D mask, flattened vector, mesh, or time series to one 3D density grid; select one time frame before export |
| Invalid density range | Convert binary 0/255 masks to 0/1; do not normalize signed distance fields or categorical labels without defining the intended solid region |
| Model looks stretched | Source voxel spacings were unequal, or axes were transposed incorrectly; resample upstream using the correct physical extents |
| Model is upside down | Select the intended up axis; reverse its index direction upstream if needed |
| Model is twice as wide | Disable mirroring for a complete model |
| Mirror joins the wrong ends | Put the half-model's symmetry plane at the low-index boundary before export |
| Thin members vanish or appear joined | Check the threshold and the preview's reduction indicator; inspect the original field at full resolution |
| Upload works but no assembly is found | Check structural stock, cap, symmetry, and orientation; format acceptance does not imply assembly feasibility |

## Format authors and library references

The interchange format is NumPy's NPY/NPZ format, not a new TopoLegOpt format.
Robert Kern authored the original NPY format proposal,
[NEP 1](https://numpy.org/neps/nep-0001-npy-format.html); the maintained
[NumPy format reference](https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html)
describes the current versions. Browser decoding uses
[fflate](https://github.com/101arrowz/fflate) for ZIP decompression and a local
parser for supported NPY numeric arrays. The server uses
[NumPy](https://numpy.org/) with `allow_pickle=False`. Algorithm references and
the full library acknowledgments are separate in [ALGORITHM.md](ALGORITHM.md).
