# Assembly experiments

These are illustrative runs of a bounded heuristic, not evidence of optimality
or mechanical strength. Geometry and sequence checks concern the simplified
brick model defined in the [method](../docs/ALGORITHM.md).

## Reproducible public example

The publication includes a complete synthetic arched bridge and its NumPy-only
[generator](../examples/create_topology.py). It has `(48, 24, 12)` cubic cells and
8,664 solid cells. The labeled test inventory contains 920 structural and 80
1×1 detail bricks. It is not a user's saved inventory.

From `brick-planner/` after installation:

```bash
.venv/bin/python scripts/experiment.py
```

The script defaults to `examples/bridge.npz`, threshold 0.5, Y up, **no mirroring**,
automatic symmetry, and 5% cap allowance. It runs caps of 100, 500, and the full
inventory, writes full plans and `summary.json` to `.local/experiments/`, and exits
unsuccessfully if any case fails the independent checks. It never reads or
changes browser data. To change inputs:

```bash
.venv/bin/python scripts/experiment.py --npz /path/to/topology.npz --inventory /path/to/inventory.json --mirror none --output /tmp/topolegopt-results
```

The script selects the `density` array. Use the application for other array keys,
orientations, thresholds, and individual budgets. Mirroring is intended for a
saved half-model; the included bridge is already complete.

Recorded on October 3, 2026 with the publication's pinned Python dependencies:

| Approximate cap | Pieces used | Shape IoU | Target material covered |
| --- | ---: | ---: | ---: |
| 100 | 103 | 93.4% | 97.8% |
| 500 | 522 | 86.3% | 93.8% |
| Full inventory | 1,000 | 86.8% | 88.3% |

All three cases passed independent assembly and sequence validation, including
X/Z placement symmetry and centered structural pieces crossing both planes.
The 100-piece case uses a smaller scale: the metric table is **not a comparison
at a common physical size**. Scale factors, inventory utilization, overlap-based
metrics, support requirements, and raw validation evidence are included in the
JSON output. Repeated results can vary if time limits interrupt candidate search;
this small example normally finishes well within them.

The high overlap of this simple bridge does not establish general performance
on thin, disconnected, asymmetric, or more complex topologies. The permanent
assembly may need temporary supports while being built. Supports are not part of
the reported inventory usage.

## Historical external-topology measurements

The separate [reference-results.json](experiments/reference-results.json) records
an earlier experiment on an externally supplied MBB half-beam. Its NPZ is **not
redistributed in this repository**, and these rows are not the default example
experiment or a fresh-checkout benchmark. The source checksum and dependency
versions are retained in that report for provenance.

| Target | Cap | Pieces | Shape IoU | Coverage | Temporary-support steps |
| --- | ---: | ---: | ---: | ---: | ---: |
| Saved half | 500 | 524 | 75.8% | 87.0% | 37 |
| Reflected full | 100 | 104 | 53.1% | 68.8% | 14 |
| Reflected full | 500 | 522 | 77.9% | 88.7% | 43 |
| Reflected full | Inventory | 1,000 | 74.4% | 76.9% | 92 |

These measurements used the same labeled
[reference inventory](experiments/reference-inventory.json), threshold 0.5,
Y up, automatic symmetry, and 5% allowance. The full beam was reconstructed with
Z reflection. They were originally reported as passing geometry and simplified
sequence checks, with approximately 0.2–1.1 seconds of execution on that machine.
They have not been rerun for this repository refactor. No browser inventory or
protected research directory was changed for publication.

## Evidence and limitations

The regression suite checks catalog and stock accounting, coordinate rotations,
NPZ interoperability, connectivity, symmetry bridges, and insertion cases.
For example, a contact-first order can trap a brick between a floor and an
already installed roof; the layer-ordered sequence avoids that obstruction in
the idealized body model.

The algorithm document gives all search policies, thresholds, scoring weights,
and limits. It also describes the additional datasets, comparisons, ablations,
and physical testing that a journal evaluation would require. Review of code
and prose does not substitute for those experiments.
