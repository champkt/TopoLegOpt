# Portable example topology

`create_topology.py` generates a complete arched bridge using NumPy and Python's
standard library. It does not read the research projects or any saved user data.
The bridge has two piers joined above an elliptical opening and is symmetric
across its X and Z midplanes.

The generated [bridge.npz](bridge.npz) is included for direct upload. Its bytes
may differ after regeneration because ZIP timestamps can change; the generator
checks the array content rather than a particular compressed-file checksum.

From the repository root, after the installation steps in the main README:

```bash
brick-planner/.venv/bin/python examples/create_topology.py --output /tmp/bridge.npz
```

The explicit `--output` argument controls where the file is saved. Existing files
are preserved unless you add `--overwrite`. The script reads the saved file back
and checks exact equality, array name, data type, and storage order.

Open TopoLegOpt, choose **Topology**, and upload the generated file. Use **Y up**,
threshold **0.5**, and **no mirroring**. This is already the complete model.

| Property | Expected value |
| --- | --- |
| Array key | `density` |
| Shape `(X, Y, Z)` | `(48, 24, 12)` |
| Data type | Little-endian float32, C-contiguous |
| Values | 0 and 1 |
| Source cells | 13,824 |
| Occupied cells at threshold 0.5 | 8,664 |
| Geometry | Cubic source voxels, no physical scale |

The opening runs through the full depth. Its piers remain separate near the base;
the arch joins them above. This makes it a useful example of why a final connected
assembly can still need aligned base pieces or temporary supports during the
build sequence. A successful candidate also depends on the available inventory.

To export a topology from your own program, follow the
[NPZ specification](../docs/NPZ_SPEC.md), especially the `(X, Y, Z)` axis order
and cubic-cell requirement. Do not encode the brick height ratio into the source
voxel dimensions; the planner handles that conversion.
