# How TopoLegOpt plans an assembly

TopoLegOpt turns a three-dimensional topology and a finite brick inventory into
a candidate brick assembly, a preview, and a one-brick-at-a-time build order.
It chooses a scale from the available structural material, tests a small set of
scales, and greedily places rectangular bricks. A separate validator rejects
results with overlapping bricks, exceeded inventory, disconnected permanent
structure, or unsatisfied requested symmetry.

This is an **experimental, bounded heuristic**. It does not establish the
largest feasible model, the best possible shape approximation, or mechanical
strength. “Connected” has a precise geometric meaning here: at least one aligned
stud position overlaps between bricks in consecutive layers. The explanation
below describes the implemented method, including its empirical choices and
limitations, so results can be interpreted and reproduced.

For preparing a topology, see the [NPZ input specification](NPZ_SPEC.md). For
installation and operation, see the [project README](../README.md). The primary
implementations are [solver.py](../brick-planner/backend/solver.py) and
[validation.py](../brick-planner/backend/validation.py).

## 1. Problem definition and coordinate systems

The inputs are a density array `density[x, y, z]`, a threshold, an orientation,
optional reflection settings, nine inventory quantities, and an optional
approximate piece cap. Source voxels are equal-sized cubes; the input supplies
shape, not an absolute brick scale. A density value is thresholded into a binary
material decision rather than used as a mechanical property.

The workflow is:

1. Threshold the topology, apply requested mirroring, determine symmetry, and
   rotate the chosen source up axis into build Y.
2. Estimate scale from structural stock and test a small neighborhood of scales.
3. At each scale, integrate target volume into brick cells, grow structural
   brick groups, and add limited details.
4. Independently validate each candidate and rank those that pass.
5. Preview the chosen assembly and generate bottom-up building steps.

The supported part footprints are `1x1`, `2x1`, `4x1`, `6x1`, `2x2`, `2x3`,
`2x4`, `2x6`, and `2x8`, expressed in studs. Every part is one full brick high.
A part can rotate by 90 degrees in the horizontal plane; it cannot tilt or turn
its studs sideways. There are no plates, slopes, hinges, color constraints, or
specialized connection types. The `1x1` part is reserved for details.

The output always uses a **Y-up build lattice**. Its integer coordinates count
stud columns in X and Z and full brick layers in Y. An occupied lattice cell
therefore has relative physical dimensions `(5, 6, 5)`, or volume 150. These are
relative units, not millimeters and not source-voxel dimensions. A `2x4` brick
occupies eight such cells and has body dimensions `10 × 6 × 20` in these units.

| Symbol | Meaning |
| --- | --- |
| `M` | Binary target after thresholding, optional mirroring, and proper build-axis rotation |
| `N` | Number of solid source voxels in `M` |
| `n = (nx, ny, nz)` | Source dimensions after these transformations |
| `c[t]`, `a[t]` | Available count and footprint area in studs of part type `t` |
| `S`, `T` | Structural stock count, and total stock count including details |
| `K`, `epsilon` | Optional nominal cap and its allowed fractional overrun |
| `s` | Horizontal stud pitches per source-voxel edge |
| `L = (Lx, Ly, Lz)` | Dimensions of the discretized build lattice |
| `f[u]` | Fraction of lattice cell `u` occupied by the binary source target |
| `O[u]` | One if a placed brick occupies lattice cell `u`, otherwise zero |

The desired behavior combines shape agreement, structural stock use, and a
large physical representation. In the implementation these are competing
preferences, not an exact optimization problem solved to completion. In
particular, “use more pieces” and “make the largest model” are not equivalent:
one large brick can contain more material than several small ones. Scale is
estimated from material volume; final ranking includes structural **piece
count**, with no separate term for physical dimensions.

## 2. Prepare the target and determine symmetry

The default threshold is `tau = 0.5`, and the material mask is
`M[x,y,z] = (density[x,y,z] >= tau)`. Equality is included. Continuous density
values are discarded after this decision. TopoLegOpt does not rerun topology
optimization, infer loads, or preserve a compliance or stress objective.

If the user requests mirroring along a source axis, the algorithm concatenates
the reflected mask followed by the original mask along that axis. This doubles
that dimension and the solid-voxel count. The joining plane is between the two
halves: no center voxel is removed. Mirroring reconstructs a larger target;
it is distinct from requiring a symmetric brick layout within an existing
target. A full model should normally use mirroring `none`.

For each of the three source axes, the algorithm compares the binary mask with
its reflection about the array midpoint:

```text
reflection_IoU = count(M AND reflected(M)) / count(M OR reflected(M))
```

Automatic symmetry enforces **every** axis whose reflected intersection over
union is at least `0.995`. This use of intersection over union is the Jaccard
coefficient; its original attribution is Paul Jaccard (1901), listed in the
[references](#13-references-and-software-credits). Only array-centered,
axis-aligned reflection planes are tested. A symmetric object displaced within
an asymmetric empty margin may fail this test; oblique planes are not searched.
Manual symmetry can impose a reflection on an asymmetric target, in which case
the solver emits a warning when the reflected IoU is below `0.995`.

The selected up axis then becomes build Y using a proper rotation, so the
object's handedness is preserved. In centered coordinates the mapping is:

| Selected source up | Build `(X, Y, Z)` comes from source |
| --- | --- |
| X | `(-Y, X, Z)` |
| Y | `(X, Y, Z)` |
| Z | `(X, Z, -Y)` |

Each negative sign means reversal of that coordinate about the array center;
integer output indices remain nonnegative. These are fixed rotations, not a
search for the best orientation. The result records the source axis names in
`source_to_build_axes` and their signs in `source_to_build_axis_signs`;
source-axis symmetry choices are mapped into build coordinates accordingly.

SciPy's `ndimage.label` also counts the binary target's face-connected voxel
components using its default connectivity (six neighbors in three dimensions).
Multiple source components produce a warning, not automatic rejection. A
connected brick result may omit an island or span a small source gap; fit
metrics account for the omitted and added material. See the
[SciPy labeling documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.label.html).

## 3. Interpret the inventory and approximate piece cap

The maximum permanent piece count is

```text
B = T                                      if K is blank
B = min(T, floor(K × (1 + epsilon)))         otherwise
```

The default tolerance is `epsilon = 0.05`; the UI permits `0` through `0.20`.
Thus a requested cap of 500 allows at most 525 permanent bricks at 5%, and
never more of any type than its stock. The count includes `1x1` details.
**There is no lower-count guarantee**: 400 pieces can be accepted for that cap.
The current server rejects runs whose permitted maximum exceeds 5,000 pieces;
a large inventory is usable by setting a smaller cap.

Define the nominal structural count target

```text
D = S                    if K is blank
D = min(S, K)            otherwise.
```

For the initial scale estimate, take up to `D` available structural bricks in
descending footprint area, without using any `1x1` stock. Let `V` be the sum of
their footprint areas. This is the maximum material volume in lattice-cell
units obtainable from that many structural parts, without considering whether
they can actually fit the topology. The estimate uses the nominal cap, not
the overrun allowance. It does not reserve specific pieces for the final plan.

## 4. Estimate scale and evaluate a bounded neighborhood

At scale `s`, a source-voxel edge has relative length `5s`, so its volume is
`125s³`. A stud-by-stud, one-layer brick cell has volume `150`. Equating the
available structural material with the scaled solid target gives

```text
150 V = 125 N s³
s0 = (1.2 V / N)^(1/3).
```

For example, `V = 1000` stud-layer cells and `N = 1200` solid source voxels
give `s0 = 1`: a source voxel is five relative units wide, while a brick layer
is six units high. The conversion preserves the source's cubic proportions.

The default scale multipliers, in evaluation order, are

```text
0.90, 1.00, 1.08, 0.96, 1.04, 1.14, 1.18, 0.82
```

Each scale is `s = multiplier × s0`. These empirical factors are a small search
neighborhood, not a bound on all feasible scales. The implementation does not
deduplicate equal-sized grids: distinct scales can yield the same integer grid
dimensions while placing its cell boundaries differently in source coordinates.
Neither scale nor the target's centering translation is continuously optimized.
Up to two seeds can be tried per scale, subject to the stopping rules below.

The source-coordinate width of one build cell is

```text
d = (1/s, 1.2/s, 1/s)
L[i] = max(1, ceil(n[i] / d[i])).
```

The resampling implementation subtracts `1e-10` before the ceiling to avoid
floating-point near-integer rounding. For a required X or Z reflection, an odd
grid dimension is increased by one to make it even. For a required Y
reflection, an even layer count is increased by one to make it odd. These
parities admit centered structural bricks across the required planes. The
source stays centered, with empty padding outside its array bounds.

Before resampling, a scale is skipped if its **anticipated unpadded** grid
exceeds 1,500,000 cells or 512 along an axis. Symmetry padding can subsequently
add one cell along a constrained axis; these are therefore pre-padding limits,
not strict limits on the final padded grid.

## 5. Fit cubic source voxels to the brick lattice

The algorithm integrates the overlap of every binary source voxel with the
brick lattice. It does not stretch a source voxel into a `5 × 6 × 5` block or
simply sample one point in each brick cell.

Along one axis, source voxel `k` occupies `[k, k+1)`. Build cell `j` covers the
source interval

```text
I[j] = [(j - L/2)d + n/2, (j + 1 - L/2)d + n/2).
W[j,k] = length(I[j] intersect [k,k+1)) / d.
```

Applying these overlap-weight matrices separately along X, Y, and Z produces
`f[u]`, the material fraction of build cell `u`. The operation is the exact
box-volume average of the piecewise-constant binary source, apart from
floating-point arithmetic; values outside the source are zero. “Exact” here
does not mean the discretized brick model reproduces the original surface
exactly. SciPy sparse matrices implement the overlap transformations; NumPy
holds the fields, with stored field values reduced to `float32`.

The overlap-weight implementation first constructs dense arrays of size
`L[i] × n[i]` along each axis before converting them to sparse form. Long,
thin source grids can therefore require substantial temporary memory even
when their final build grid is small. The file and build-grid limits are
workload guards, not a guarantee that every accepted input fits available RAM.

When symmetry is required, a copy of `f` is averaged with its reflection along
each enforced axis, successively. Call that copy `g`. Candidate brick quality
and placement decisions use `g`, which is symmetric even for a nearly
symmetric or manually constrained asymmetric source. **Final fit metrics use
the original unaveraged `f`**, so enforcing symmetry does not hide error against
the submitted target.

## 6. Enumerate legal brick placements and symmetric groups

For each in-stock structural type and its distinct horizontal rotations, the
algorithm enumerates integer placements wholly inside the lattice. A candidate
is retained if its footprint's mean value in `g` is at least `0.52`:

```text
q = sum(g[u] over the brick's one-layer footprint) / (width × depth).
```

Rectangular sums are computed using a two-dimensional summed-area table in
each layer. This is the method described by Franklin C. Crow (1984), applied
here to footprint occupancy rather than texture filtering; see the
[references](#13-references-and-software-credits).

With symmetry, a candidate represents its entire **reflection group**, also
called an orbit: the original brick plus all distinct reflected copies. An
orbit contains between one and eight physical bricks for up to three axes.
Members have the same part ID and orientation. A brick centered on a symmetry
plane maps to itself and is counted once. Only nonoverlapping orbits are
enumerated; an off-center brick overlapping its reflected counterpart is
excluded. The complete orbit must fit the inventory count for that type.
Every later inventory and cap charge counts all physical members.

The occupancy threshold is per brick footprint, not per cell. Consequently a
structural brick may cross an empty target cell or extend outside the target
surface if its mean occupancy remains at least `0.52`. This permits small gaps
to be bridged and surface errors to be traded against connectivity. It is not
an exact inside-only packing constraint.

For efficient collision and neighbor queries, the implementation stores a
sparse candidate-to-cell incidence matrix and its cell-to-candidate transpose.
This representation also makes candidate enumeration a possible memory
bottleneck; the grid limits do not imply a fixed candidate-count limit.

## 7. Grow the structural backbone greedily

### Choose one or two seeds

Candidates whose reflection orbit contains one brick are preferred as the
seed set whenever any exist. Under multiple enforced symmetries, such a brick
is centered across all of those planes. Otherwise the seed set contains all
candidates.

For each eligible candidate, define `R` as the sum of candidate-incidence
counts in cells immediately above and below all of its occupied cells. This
measures opportunities for later placements, with duplicates allowed; it is
not a count of distinct reachable bricks. The seed score is

```text
q + 0.008 sqrt(width × depth) + 0.018 log(1 + R)
  - 0.5 [R = 0] - 0.002 y / max(1, Ly).
```

Square brackets mean one when the stated condition is true and zero otherwise.
If there are no single-brick orbits, subtract another `0.08 × orbit_size`.
The highest-scoring seed is tried first. A second seed is the first remaining
candidate in score order whose representative Y coordinate is separated by at
least `max(2, floor(Ly/3))` layers. It can escape a poor initial region but does
not provide exhaustive restart coverage.

### Expand through adjacent layers

The first seed is accepted if its orbit fits the total budget. Its occupied
cells block every overlapping candidate. A priority queue then holds unblocked
candidates with at least one occupied cell immediately above or below current
occupancy. Candidate priority is fixed at enumeration time:

```text
priority = (q - 0.30) sqrt(width × depth)
         + 0.012 [(width > depth) equals (y is even)].
```

The main term prefers larger, well-filled footprints. The small parity term
encourages alternating orientations by layer; it does not enforce staggered
joints or measure joint strength. Python's `heapq` supplies the heap priority
queue, using negative priorities to pop the highest first and candidate index
to break ties. This is a greedy packing procedure, not Dijkstra's shortest-path
algorithm or a global combinatorial optimizer. See the
[Python heapq documentation](https://docs.python.org/3/library/heapq.html).
The underlying binary-heap operations originate in J. W. J. Williams's
1964 paper, credited in the references; the planner uses a heap as a dynamic
priority queue rather than running a heapsort over all placements.

At each iteration, the algorithm pops a candidate, skips it if blocked or if
its complete orbit exceeds remaining stock or budget, and otherwise accepts
the entire orbit. Accepted cells block conflicts and expose new above/below
neighbors. There is no backtracking, brick replacement, local rearrangement,
or later repair of an invalid backbone. Growth stops at an empty frontier,
the piece ceiling, or a checked time deadline.

**A subtle symmetry limitation:** an orbit enters the frontier when any member
touches current occupancy. Because current occupancy contains complete
reflection groups, its reflected neighbors provide corresponding contacts for
every member. Starting from a single-brick seed therefore preserves one
connected component. A multi-brick seed can instead start separate components;
greedy growth may eventually join them, but need not do so. The independent
final check is necessary for this general case. A failed check rejects the
trial.

Side-to-side brick contact never enters the frontier as a connection. Two
neighboring bricks in one layer need a connected route through bricks above
or below to belong to the final stud-contact component.

## 8. Add limited 1x1 details

After the backbone is complete, the detail allowance is

```text
min(available_1x1, floor(0.10 × structural_bricks_placed),
    B - structural_bricks_placed).
```

Detail candidates require mean occupancy at least `0.68`, inherit the same
reflection constraints, and are visited in descending occupancy quality. Every
accepted detail must contact the already fixed structural occupancy directly
above or below. A chain of details is not used to reach new locations; details
cannot provide the backbone's only bridge. Complete orbits must fit the
remaining allowance, so some detail stock can remain unused.

Both the 10% policy and the 0.68 threshold are provisional design choices.
They do not represent a derived optimum or a published rule about brick
structures. The solver enforces the 10% allowance and direct structural
attachment while adding details; the separate assembly validator checks the
structural-only connection graph but does not independently retest those two
detail policies.

## 9. Independently check permanent assembly constraints

The validator reconstructs geometry from placements and inventory instead of
trusting solver-supplied collision or connection claims. It checks catalog
dimensions, integer nonnegative coordinates, allowed rotations, unique IDs,
lattice bounds, overlaps, per-type stock limits, and the piece ceiling.

It then creates an undirected graph with one vertex per brick. Two bricks have
an edge only if they occupy consecutive layers and share at least one X/Z stud
position. Each edge records the number of shared stud positions. A stack-based
graph traversal finds connected components, including isolated bricks.

Both the full graph and the graph induced by structural bricks after removing
all `1x1` vertices must contain exactly one component. “Structural” in this
document means that inventory role and graph condition; it is not a stress or
stiffness calculation. A lone structural brick is a connected one-vertex
graph. Single-stud connections are allowed and explicitly reported.

For every requested reflection plane, the validator compares the complete
multiset of brick placements against its reflection, including type and
orientation. It additionally requires at least one **structural brick centered
across that plane**. For the X plane this means

```text
x < Lx/2 < x + width, and 2x + width = Lx.
```

The same condition applies in Z using depth and in Y using height one. The
condition guarantees equal portions of that brick on both sides. Two mirrored
bricks meeting at the plane do not pass it. Each plane may have a different
centered brick; all such bricks still belong to the one validated structural
component. The test does not require a minimum number of crossings, contacts
on both halves of each crossing brick, or a quantified load path across the
plane. Y reflection refers to rectangular brick bodies; real stud-and-tube
geometry is not invariant under turning vertical coordinates upside down.

## 10. Rank valid candidates by shape and structural use

Let the total fractional target material be `A = sum(f)`, the number of occupied
brick lattice cells be `F = sum(O)`, and the matched material be
`I = sum(f[u] × O[u])`. Reported metrics are

```text
shape_IoU       = I / (A + F - I)
target_coverage = I / A
material_precision = I / F.
```

These are **volume overlap** measurements, not surface-distance measurements
or voxel-center classification scores. Because `f` is a volume average and
the assembly fills each occupied cell, the terms correspond to binary-target
and brick-body intersection/union volumes at that scale, up to numerical
roundoff. Multiplying all terms by the physical cell volume 150 cancels in the
ratios. `target_stud_volume` and `used_stud_volume` in exported results refer to
these stud-by-stud, full-layer cell units.

Coverage asks how much target material was retained; precision asks how much
brick material lies inside the target. For example, with `A=100`, `F=90`, and
`I=80`, coverage is 80%, precision is 88.9%, and IoU is 72.7%. A high coverage
alone can hide excess material.

For `Ns` placed structural bricks and nominal target `D` from Section 3,
the selection score is

```text
U = min(1, Ns / max(1, D))
score = 0.48 shape_IoU + 0.20 target_coverage + 0.32 U.
```

Only independently valid candidates can win. The largest score wins; a tie
keeps the earlier trial. Details influence overlap but do not increase `U`.
Structural pieces above the nominal cap, permitted by the tolerance, likewise
do not increase `U` beyond one. Exported `structural_utilization` instead divides
by the full structural inventory `S`; it can be much lower than the score's
utilization term when a cap is active.

The weights and thresholds are empirical, uncalibrated policy parameters.
They are not a theorem, a multiobjective Pareto search, or a guarantee of
maximum inventory use. Metrics are evaluated on each scale's own discretized
target and remain subject to discretization effects. No term directly rewards
surface smoothness, thin-feature preservation, redundant connections, reduced
support burden, or load capacity.

## 11. Produce and inspect the build sequence

After choosing the best validated assembly, bricks are sorted by `(y, x, z, id)`
and emitted as one-brick steps. Each instruction gives the location, part type,
already placed stud neighbors, and any temporary-support requirement.

The lowest occupied Y layer is treated as the work surface. Bricks there may
start as separate aligned sections that upper layers later join. An elevated
brick with no earlier lower contact is labeled as requiring temporary support
or a held, aligned subassembly. Such supports are not modeled or charged to
the permanent inventory. The requirement is a disclosure, not a computed
support design.

A separate sequence validator reconstructs contacts and verifies that every
brick appears exactly once, attachment statements match earlier contacts,
and required support notes are present. It checks a top-down insertion model:
no previously placed brick at the same or a higher layer may overlap the new
brick's horizontal footprint. Bottom-up ordering provides clear insertion
paths for the axis-aligned body boxes under this model. It does not prove hand
access, insertion-force feasibility, support removal, or that the model is
stable while being assembled. The sequence may be valid even when its
`contact_order` diagnostic is false, because separately aligned sections are
allowed. `gravity_stability` remains false because it is not evaluated.

The Three.js preview displays each brick body and stylized studs, with colors
identifying part types rather than inventory colors. Playback exposes the
sequence and temporary-support notes. The body gaps and rendered studs are
visual aids; the geometric validator uses ideal full lattice cells and does
not check real tube/stud meshes or manufacturing tolerances.

## 12. Stopping, evidence, and research limitations

The default solver time allowance is 30 seconds. It is checked before a new
scale, before a second seed, and during growth when the number of selected
orbits is a multiple of 64. Candidate enumeration, details, and validation are
not continuously interruptible, so this is a **soft search budget**, not a
30-second response guarantee. The server separately terminates a job at its
three-minute process timeout. It admits up to two jobs concurrently.

The second seed for a scale is skipped if the first trial is valid and target
coverage is greater than `0.78`. There are at most eight scales and two seeds
per scale, often fewer. The experiment log includes skipped or empty scale
records as well as actual placement trials; its length need not be the number
of completed packing attempts. Search order and wall-clock stopping can affect
the selected result. There is no random generator in the current solver, but
cross-machine bit-for-bit reproducibility is not promised.

An unsuccessful search means **no valid candidate was found within this
enumeration and search policy**. It does not prove that the requested stock,
symmetry, or topology has no feasible assembly. Tight symmetry groups, limited
mixed-size stock, long thin features, strict caps, and unfortunate greedy seed
choices can all cause failure or low coverage.

The following distinction is essential when reporting results:

| Result property | What is established |
| --- | --- |
| Inventory and cap compliance | Independently checked on all permanent bricks |
| No brick overlap | Independently checked in the ideal lattice-body model |
| Final connection | One stud-contact component, also without details |
| Requested symmetry | Exact reflected brick-body multiset and centered crossing brick per plane |
| Fit | Reported volume overlap at the selected scale, not exact surface matching |
| Build order | Complete, unobstructed top-down box insertion with support disclosures |
| Largest scale or best packing | Not established by the bounded greedy search |
| Strength, balance, rigidity, clutch force, and support design | Not simulated or certified |

The [recorded experiments](../brick-planner/EXPERIMENTS.md) document one reference
topology and a labeled test inventory. They are demonstrations, not a benchmark
across shape families or evidence of general optimality. Automated regression
tests exercise coordinate conversion, inventory/cap rules, symmetry,
connectivity, and insertion counterexamples; passing them does not substitute
for physical experiments or comparative evaluation.

A journal evaluation would need a defined collection of independent shapes
and inventories, orientation and symmetry cases, thin/disconnected-feature
cases, timing and memory measurements, comparisons with alternative packing
strategies, sensitivity to thresholds and weights, and ablations of symmetry
and seeding. Claims about mechanical reliability would additionally require
mechanical modeling or physical assembly/load testing. Those studies are
outside the evidence currently provided by this repository.

## 13. References and software credits

The combined inventory-based scale estimate, reflected-group enumeration,
greedy priority formulas, cap policy, and detail policy are this project's
heuristic implementation. The references below credit the actual established
building blocks; they do not imply that those authors proposed or validated
this brick planning method. Machine-readable entries are in
[references.bib](references.bib).

### Established methods

1. **Franklin C. Crow (1984).** “Summed-area tables for texture mapping.”
   *Proceedings of SIGGRAPH '84*, pp. 207–212.
   [doi:10.1145/800031.808600](https://doi.org/10.1145/800031.808600).
   Used for constant-time rectangular footprint sums after a per-layer prefix
   sum is built. [Original paper scan](https://citeseerx.ist.psu.edu/document?doi=c769616122353ff8f9444ac708cea22fc4032685&repid=rep1&type=pdf).
2. **Paul Jaccard (1901).** “Étude comparative de la distribution florale dans
   une portion des Alpes et du Jura.” *Bulletin de la Société Vaudoise des
   Sciences Naturelles*, 37(142), pp. 547–579.
   [doi:10.5169/seals-266450](https://doi.org/10.5169/seals-266450).
   Attribution for the intersection-over-union coefficient used for reflected
   masks and, by volume, shape agreement.
3. **J. W. J. Williams (1964).** “Algorithm 232: Heapsort.”
   *Communications of the ACM*, 7(6), pp. 347–348.
   [doi:10.1145/512274.3734138](https://doi.org/10.1145/512274.3734138).
   Original heap insertion and minimum-extraction operations underlying a
   binary-heap priority queue; the actual implementation here is Python's
   standard-library `heapq`.
4. **Python Software Foundation and Python contributors.**
   [heapq documentation](https://docs.python.org/3/library/heapq.html).
   The standard library implements the heap queue used for candidate priority.
   Component checking uses an elementary stack traversal implemented in this
   repository; it does not call a specialized strongly-connected-component or
   graph-optimization library.

### Libraries and their roles

| Library | Original authors / credited contributors | Used here for |
| --- | --- | --- |
| NumPy | Charles R. Harris, K. Jarrod Millman, Stéfan J. van der Walt, and coauthors; NumPy contributors | NPZ loading, dense arrays, thresholding, prefix sums, and numeric metrics |
| SciPy | Pauli Virtanen, Ralf Gommers, Travis E. Oliphant, and coauthors; SciPy contributors | Sparse overlap/incidence matrices and `ndimage.label` |
| [Three.js](https://github.com/mrdoob/three.js) | Ricardo Cabello (mrdoob) and Three.js contributors | Interactive topology and brick previews, instancing, OrbitControls |
| [fflate](https://github.com/101arrowz/fflate/blob/master/LICENSE) | Arjun Barrett and contributors | Browser-side NPZ ZIP decompression |
| [FastAPI](https://fastapi.tiangolo.com/help-fastapi/) | Sebastián Ramírez and contributors | Local upload, job, and result HTTP API |
| [Uvicorn](https://github.com/Kludex/uvicorn/blob/main/pyproject.toml) | Tom Christie and contributors | ASGI server running the local application |
| [esbuild](https://github.com/evanw/esbuild/blob/main/LICENSE.md) | Evan Wallace and contributors | Bundling browser modules for serving |
| [Marked](https://github.com/markedjs/marked/blob/v15.0.12/LICENSE.md) | Christopher Jeffrey and MarkedJS contributors | Building hosted documentation from the repository's Markdown |

The standard scientific-library citations are **Charles R. Harris et al.
(2020)**, “Array programming with NumPy,” *Nature* 585, 357–362,
[doi:10.1038/s41586-020-2649-2](https://doi.org/10.1038/s41586-020-2649-2), and
**Pauli Virtanen et al. (2020)**, “SciPy 1.0: fundamental algorithms for
scientific computing in Python,” *Nature Methods* 17, 261–272,
[doi:10.1038/s41592-019-0686-2](https://doi.org/10.1038/s41592-019-0686-2).
These publications credit their author teams; neither first author alone
represents the full history of the library. Exact project dependency versions,
including transitive web-server and validation dependencies, are recorded in
[requirements.txt](../brick-planner/requirements.txt) and
[package-lock.json](../brick-planner/package-lock.json). Node's built-in test
runner and Python's `unittest` are used for regression testing; HTTPX supports
API tests through FastAPI's test client.
