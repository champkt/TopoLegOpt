"""Inventory-constrained experimental brick packing on a physical 5:6:5 grid.

This is a bounded heuristic, not a structural analysis or a proof of optimality.
The important invariant is that contact growth uses overlapping studs on adjacent
layers. Adjacent brick sides never count as a connection. Reflection orbits make
symmetry a placement constraint rather than a cosmetic change to the preview.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import heapq
import math
import time

import numpy as np
from scipy import ndimage, sparse

try:
    from .validation import validate_assembly, validate_sequence
except ImportError:
    from validation import validate_assembly, validate_sequence


CATALOG = {
    "1x1": (1, 1), "2x1": (2, 1), "4x1": (4, 1), "6x1": (6, 1),
    "2x2": (2, 2), "2x3": (2, 3), "2x4": (2, 4), "2x6": (2, 6),
    "2x8": (2, 8),
}
PART_IDS = tuple(CATALOG)
AXES = ("x", "y", "z")
PITCH = np.array([5.0, 6.0, 5.0])


@dataclass
class Candidates:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    width: np.ndarray
    depth: np.ndarray
    part: np.ndarray
    count: np.ndarray
    quality: np.ndarray
    cells: sparse.csr_matrix
    at_cell: sparse.csr_matrix
    shape: tuple
    symmetry: tuple

    def __len__(self):
        return len(self.x)

    def footprint(self, index):
        return self.cells.indices[self.cells.indptr[index]:self.cells.indptr[index + 1]]

    def bricks(self, index):
        x, y, z = int(self.x[index]), int(self.y[index]), int(self.z[index])
        w, d = int(self.width[index]), int(self.depth[index])
        xs = sorted({x, self.shape[0] - x - w}) if 0 in self.symmetry else [x]
        ys = sorted({y, self.shape[1] - y - 1}) if 1 in self.symmetry else [y]
        zs = sorted({z, self.shape[2] - z - d}) if 2 in self.symmetry else [z]
        return [dict(part_id=PART_IDS[int(self.part[index])], x=xx, y=yy, z=zz,
                     width=w, depth=d, height=1) for xx in xs for yy in ys for zz in zs]


def _inventory_counts(inventory):
    """Accept the compact API map and the UI's exported parts object."""
    if not isinstance(inventory, dict):
        raise ValueError("Inventory must be a part ID to quantity mapping.")
    if isinstance(inventory.get("parts"), list):
        inventory = {p["id"]: p.get("quantity", 0) for p in inventory["parts"]}
    result = {}
    for key, count in inventory.items():
        if key not in CATALOG:
            raise ValueError(f"Unsupported brick: {key}.")
        if isinstance(count, bool) or not isinstance(count, (int, np.integer)) or count < 0:
            raise ValueError(f"Quantity for {key} must be a nonnegative integer.")
        result[key] = int(count)
    return {key: result.get(key, 0) for key in CATALOG}


def _overlap_weights(source_size, target_size, source_step):
    """Exact averaging of unit source voxels, with centered empty padding."""
    edges = (np.arange(target_size + 1) - target_size / 2) * source_step + source_size / 2
    left = np.maximum(edges[:-1, None], np.arange(source_size)[None, :])
    right = np.minimum(edges[1:, None], np.arange(1, source_size + 1)[None, :])
    return sparse.csr_matrix(np.maximum(0, right - left) / source_step)


def resample_occupancy(mask, scale, symmetry=()):
    """scale is horizontal studs per source voxel, preserving cubic voxels."""
    steps = PITCH / (5 * scale)
    shape = np.maximum(1, np.ceil(np.asarray(mask.shape) / steps - 1e-10).astype(int))
    for axis in symmetry:
        if axis == 1 and shape[axis] % 2 == 0:
            shape[axis] += 1  # the central full-height layer straddles a Y plane
        elif axis != 1 and shape[axis] % 2:
            shape[axis] += 1  # even dimensions admit centered even-length seam bricks
    field = mask.astype(np.float32)
    for axis, (n, step) in enumerate(zip(shape, steps)):
        moved = np.moveaxis(field, axis, 0)
        matrix = _overlap_weights(mask.shape[axis], int(n), float(step))
        transformed = matrix @ moved.reshape(moved.shape[0], -1)
        field = np.moveaxis(transformed.reshape((int(n),) + moved.shape[1:]), 0, axis)
    return np.asarray(field, dtype=np.float32)


def _positions(size, span, symmetric):
    if span > size:
        return []
    if not symmetric:
        return [(np.arange(size - span + 1), 1)]
    result = []
    # A reflected pair may touch, but its interiors cannot overlap.
    left = np.arange(max(0, (size - 2 * span) // 2 + 1))
    if len(left):
        result.append((left, 2))
    if (size - span) % 2 == 0:
        result.append((np.array([(size - span) // 2]), 1))
    return result


def _make_candidates(field, counts, symmetry, minimum_fill=0.52, detail=False):
    nx, ny, nz = field.shape
    integral = np.pad(field, ((1, 0), (0, 0), (1, 0))).cumsum(0).cumsum(2)
    chunks, cell_chunks, lengths = [], [], []
    for part_index, part_id in enumerate(PART_IDS):
        if not counts[part_id] or (part_id == "1x1") != detail:
            continue
        a, b = CATALOG[part_id]
        for w, d in sorted({(a, b), (b, a)}):
            if w > nx or d > nz:
                continue
            quality = (integral[w:, :, d:] - integral[:-w, :, d:]
                       - integral[w:, :, :-d] + integral[:-w, :, :-d]) / (w * d)
            for xs, x_count in _positions(nx, w, 0 in symmetry):
                for ys, y_count in _positions(ny, 1, 1 in symmetry):
                    for zs, z_count in _positions(nz, d, 2 in symmetry):
                        orbit_count = x_count * y_count * z_count
                        if orbit_count > counts[part_id]:
                            continue
                        selected = np.argwhere(quality[np.ix_(xs, ys, zs)] >= minimum_fill)
                        if not len(selected):
                            continue
                        x, y, z = xs[selected[:, 0]], ys[selected[:, 1]], zs[selected[:, 2]]
                        q = quality[x, y, z]
                        chunk = np.column_stack((x, y, z, np.full(len(x), w),
                                                 np.full(len(x), d), np.full(len(x), part_index),
                                                 np.full(len(x), orbit_count), q))
                        chunks.append(chunk)
                        origins = []
                        for xx in [x, nx - x - w] if x_count == 2 else [x]:
                            for yy in [y, ny - y - 1] if y_count == 2 else [y]:
                                for zz in [z, nz - z - d] if z_count == 2 else [z]:
                                    origins.append(xx * ny * nz + yy * nz + zz)
                        offsets = (np.arange(w)[:, None] * ny * nz + np.arange(d)[None, :]).ravel()
                        cells = np.concatenate([o[:, None] + offsets[None, :] for o in origins], axis=1)
                        cell_chunks.append(cells.ravel())
                        lengths.append(np.full(len(x), w * d * orbit_count, dtype=np.int64))
    if not chunks:
        return None
    data = np.concatenate(chunks)
    indices = np.concatenate(cell_chunks).astype(np.int32)
    indptr = np.r_[0, np.cumsum(np.concatenate(lengths))]
    incidence = sparse.csr_matrix((np.ones(len(indices), dtype=np.uint8), indices, indptr),
                                  shape=(len(data), nx * ny * nz))
    incidence.sort_indices()
    return Candidates(*(data[:, i].astype(np.int32) for i in range(7)),
                      data[:, 7].astype(np.float32), incidence,
                      incidence.transpose().tocsr(), tuple(field.shape), tuple(symmetry))


def _incident(candidates, cells):
    if not len(cells):
        return np.empty(0, dtype=np.int32)
    return np.unique(candidates.at_cell[cells].indices)


def _neighbors(cells, shape):
    _, ny, nz = shape
    ys = (cells // nz) % ny
    return np.r_[cells[ys > 0] - nz, cells[ys < ny - 1] + nz]


def _seed_indices(candidates):
    singleton = np.flatnonzero(candidates.count == 1)
    choices = singleton if len(singleton) else np.arange(len(candidates))
    # Favor sound material and an actual seam bridge, then a low starting layer.
    score = candidates.quality[choices] + 0.008 * np.sqrt(
        candidates.width[choices] * candidates.depth[choices])
    potential = np.diff(candidates.at_cell.indptr).reshape(candidates.shape)
    adjacent_potential = np.zeros_like(potential)
    adjacent_potential[:, 1:, :] += potential[:, :-1, :]
    adjacent_potential[:, :-1, :] += potential[:, 1:, :]
    reach = candidates.cells @ adjacent_potential.ravel()
    score += 0.018 * np.log1p(reach[choices])
    score -= (reach[choices] == 0) * 0.5
    score -= 0.002 * candidates.y[choices] / max(1, candidates.shape[1])
    if not len(singleton):
        score -= 0.08 * candidates.count[choices]
    order = choices[np.argsort(-score, kind="stable")]
    if not len(order):
        return []
    selected = [int(order[0])]
    # A second seed in a different layer can escape a local growth dead end.
    for index in order[1:]:
        if abs(int(candidates.y[index]) - int(candidates.y[selected[0]])) >= max(2, candidates.shape[1] // 3):
            selected.append(int(index))
            break
    return selected


def _grow(candidates, counts, budget, seed, deadline):
    remaining = np.array([counts[k] for k in PART_IDS], dtype=np.int64)
    occupied = np.zeros(np.prod(candidates.shape), dtype=bool)
    blocked = np.zeros(len(candidates), dtype=bool)
    queued = np.zeros(len(candidates), dtype=bool)
    frontier = []
    selected = []
    piece_count = 0
    # Large bricks establish the backbone. Smaller stock subsequently fills gaps.
    area = candidates.width * candidates.depth
    priority = (candidates.quality - 0.30) * np.sqrt(area)
    # A small alternating preference reduces repeatedly aligned layer seams.
    priority += 0.012 * (((candidates.width > candidates.depth) == (candidates.y % 2 == 0)))

    def add(index):
        nonlocal piece_count
        selected.append(int(index))
        count = int(candidates.count[index])
        remaining[candidates.part[index]] -= count
        piece_count += count
        cells = candidates.footprint(index)
        occupied[cells] = True
        blocked[_incident(candidates, cells)] = True
        touching = _incident(candidates, _neighbors(cells, candidates.shape))
        touching = touching[~blocked[touching] & ~queued[touching]]
        for ci in touching:
            heapq.heappush(frontier, (-float(priority[ci]), int(ci)))
        queued[touching] = True

    if candidates.count[seed] > budget:
        return [], occupied
    add(seed)
    while frontier and piece_count < budget:
        if len(selected) % 64 == 0 and time.monotonic() > deadline:
            break
        _, index = heapq.heappop(frontier)
        if blocked[index]:
            continue
        count, part = int(candidates.count[index]), int(candidates.part[index])
        if remaining[part] < count or piece_count + count > budget:
            continue
        add(index)
    placements = [brick for index in selected for brick in candidates.bricks(index)]
    return placements, occupied


def _details(field, placements, occupied, counts, symmetry, budget):
    limit = min(counts["1x1"], max(0, int(len(placements) * 0.10)), budget - len(placements))
    if not limit:
        return placements, occupied
    candidates = _make_candidates(field, counts, symmetry, minimum_fill=0.68, detail=True)
    if candidates is None:
        return placements, occupied
    structural_occupancy = occupied.copy()
    # Details attach directly to structural stock, never to a chain of details.
    contact_cells = _neighbors(np.flatnonzero(structural_occupancy), field.shape)
    touching = _incident(candidates, contact_cells)
    touching = touching[np.argsort(-candidates.quality[touching], kind="stable")]
    used = 0
    for index in touching:
        n = int(candidates.count[index])
        cells = candidates.footprint(index)
        if n + used > limit or np.any(occupied[cells]):
            continue
        # Symmetric occupancy implies that every member of this orbit touches.
        occupied[cells] = True
        placements.extend(candidates.bricks(index))
        used += n
    return placements, occupied


def _quality(field, occupied):
    target = float(field.sum())
    filled = int(occupied.sum())
    match = float(field.ravel()[occupied].sum())
    return {
        "shape_iou": match / max(1e-12, target + filled - match),
        "target_coverage": match / max(1e-12, target),
        "material_precision": match / max(1, filled),
        "target_stud_volume": target,
        "used_stud_volume": filled,
    }


def _sequence(placements, edges):
    """Bottom-up order leaves an unobstructed vertical insertion path for every box.

    Raised bricks without prior lower contacts require an aligned temporary
    support. Intermediate assemblies may be separate until a later layer ties
    them together; the validated completed assembly is a single component.
    """
    if not placements:
        return []
    by_id = {p["id"]: p for p in placements}
    adjacent = {p["id"]: [] for p in placements}
    for left, right in edges:
        adjacent[left].append(right)
        adjacent[right].append(left)
    done = set()
    steps = []
    bottom = min(p["y"] for p in placements)
    for brick in sorted(placements, key=lambda p: (p["y"], p["x"], p["z"], p["id"])):
        pid = brick["id"]
        attached = sorted(set(adjacent[pid]) & done)
        support = brick["y"] > bottom and not attached
        coordinate = f"({brick['x']}, {brick['y']}, {brick['z']})"
        if attached:
            instruction = f"Lower brick {pid} ({brick['part_id']}) onto its completed neighbors at {coordinate}."
        elif brick["y"] == bottom:
            instruction = f"Position brick {pid} ({brick['part_id']}) on the work surface at {coordinate}; keep its grid position until later layers connect it."
        else:
            instruction = f"Use a temporary support or hold brick {pid} ({brick['part_id']}) aligned at {coordinate}; a later layer connects it."
        steps.append(dict(step=len(steps) + 1, brick_ids=[pid], attached_to=attached,
                          requires_support=support, starts_subassembly=not bool(attached),
                          instruction=instruction))
        done.add(pid)
    return steps


def solve(density, inventory, options=None):
    """Return a JSON-ready candidate and independent constraint validation.

    Source axes and mirror/symmetry options use the NPZ X/Y/Z convention. The
    returned placement axes always use Y-up build coordinates, studs in X/Z and
    full-height layers in Y. Unknown dimensions are resolved from stock volume.
    """
    started = time.monotonic()
    options = dict(options or {})
    counts = _inventory_counts(inventory)
    density = np.asarray(density)
    if density.ndim != 3 or any(n == 0 for n in density.shape) or density.size > 64_000_000:
        raise ValueError("Topology must be a nonempty three-dimensional array of at most 64 million voxels.")
    if density.dtype.kind not in "buif" or not np.isfinite(density).all():
        raise ValueError("Topology contains nonnumeric or nonfinite values.")
    if np.any(density < 0) or np.any(density > 1):
        raise ValueError("Topology density values must lie between zero and one.")
    threshold = float(options.get("threshold", 0.5))
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Threshold must be between zero and one.")
    up = options.get("up", "y")
    mirror = options.get("mirror", "none")
    requested_symmetry = options.get("symmetry", "auto")
    if up not in AXES or mirror not in (*AXES, "none"):
        raise ValueError("Invalid topology up or mirror axis.")
    tolerance = float(options.get("tolerance", 0.05))
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 0.20:
        raise ValueError("Piece cap tolerance must be between zero and 0.20.")
    cap = options.get("piece_cap")
    if cap is not None:
        if isinstance(cap, bool) or not isinstance(cap, (int, np.integer)) or cap < 1:
            raise ValueError("Piece cap must be a positive integer or null.")
        cap = int(cap)
    time_limit = float(options.get("time_limit", 30))
    if not math.isfinite(time_limit) or not 1 <= time_limit <= 120:
        raise ValueError("Time limit must be between 1 and 120 seconds.")
    deadline = started + time_limit
    source_shape = tuple(int(x) for x in density.shape)
    mask = density >= threshold
    if mirror != "none":
        axis = AXES.index(mirror)
        mask = np.concatenate((np.flip(mask, axis=axis), mask), axis=axis)
    solid = int(mask.sum())
    structural_stock = sum(v for k, v in counts.items() if k != "1x1")
    total_stock = sum(counts.values())
    budget = min(total_stock, math.floor(cap * (1 + tolerance) + 1e-9) if cap else total_stock)
    nominal_budget = min(structural_stock, cap if cap else structural_stock)
    assumptions = [
        "All catalog parts are ordinary rectangular bricks, one full brick high; rotation is allowed only in the horizontal plane.",
        "Source voxels are cubic. One stud pitch is 5 relative units and one brick layer is 6; these ratios are independent of source voxel units.",
        "Scale is selected from an inventory-derived bounded search; neither the largest possible assembly nor globally optimal shape fit is proven.",
        "A connection means at least one overlapping stud between adjacent layers. Side contact alone is never counted.",
        "1×1 pieces are details added after the structural backbone, touch that backbone directly, and are limited to 10% of the structural piece count.",
        "The sequence builds bottom-up with clear vertical insertion paths for the rectangular brick bodies. Separate aligned base pieces and temporary supports for raised subassemblies may be needed; these supports are not included in inventory. Gravity, clutch force, and load-bearing strength are not simulated.",
    ]
    warnings = []
    base = dict(success=False, status="no_valid_assembly", placements=[], sequence=[],
                geometry=dict(stud_pitch=5, layer_height=6), assumptions=assumptions,
                warnings=warnings, diagnostics=[], source_shape=list(source_shape),
                options=dict(threshold=threshold, up=up, mirror=mirror,
                             symmetry=requested_symmetry, piece_cap=cap, tolerance=tolerance))
    if not solid or not structural_stock:
        base["diagnostics"].append("The thresholded topology is empty." if not solid else
                                   "Add structural bricks: 1×1 stock is reserved for details and cannot form the backbone.")
        return base
    if budget > 5000:
        raise ValueError("This experimental solver supports at most 5,000 pieces per run; set a smaller piece cap.")

    source_scores = {}
    for axis, name in enumerate(AXES):
        reflected = np.flip(mask, axis=axis)
        source_scores[name] = float(np.count_nonzero(mask & reflected) / np.count_nonzero(mask | reflected))
    horizontal_source_axes = [axis for axis in AXES if axis != up]
    if requested_symmetry == "auto":
        source_symmetry = [axis for axis in AXES if source_scores[axis] >= 0.995]
        assumptions.append("Automatic symmetry requires at least 99.5% reflected voxel IoU; every detected reflection axis is enforced in the brick bodies.")
    elif requested_symmetry == "none":
        source_symmetry = []
    elif isinstance(requested_symmetry, (list, tuple)):
        source_symmetry = list(dict.fromkeys(requested_symmetry))
    elif requested_symmetry in AXES:
        source_symmetry = [requested_symmetry]
    else:
        raise ValueError("Symmetry must be auto, none, x, y, z, or a list of source axes.")
    if any(axis not in AXES for axis in source_symmetry):
        raise ValueError("Unknown symmetry axis.")
    # Match the topology viewer's proper rotation from the selected positive
    # source up axis to positive build Y. A plain X/Y or Y/Z permutation has
    # determinant -1 and would silently mirror a chiral source shape.
    permutation = [AXES.index(horizontal_source_axes[0]), AXES.index(up), AXES.index(horizontal_source_axes[1])]
    axis_signs = {"x": [-1, 1, 1], "y": [1, 1, 1], "z": [1, 1, -1]}[up]
    mask = np.transpose(mask, permutation)
    for axis, sign in enumerate(axis_signs):
        if sign < 0:
            mask = np.flip(mask, axis=axis)
    build_symmetry = tuple(permutation.index(AXES.index(axis)) for axis in source_symmetry)
    for axis in source_symmetry:
        if source_scores[axis] < 0.995:
            warnings.append(f"Requested {axis.upper()} reflection approximates an asymmetric source (reflected voxel IoU {source_scores[axis]:.3f}).")
    if source_symmetry:
        assumptions.append("Horizontal symmetry planes lie between stud columns; vertical symmetry uses an odd number of layers. Centered structural bricks cross every required plane and reflected bricks use matching part IDs and orientations.")
    labeled, target_components = ndimage.label(mask)
    if target_components > 1:
        warnings.append(f"The thresholded source has {target_components} disconnected voxel components. A single locked assembly may omit components or bridge small gaps.")
    del labeled
    base["source_to_build_axes"] = [AXES[i] for i in permutation]
    base["source_to_build_axis_signs"] = axis_signs
    base["symmetry"] = dict(requested=requested_symmetry, source_axes=source_symmetry,
                            build_axes=[AXES[i] for i in build_symmetry],
                            detected_scores=source_scores, planes={})

    # Estimate the largest material volume available under the nominal count cap.
    volume = 0
    left = nominal_budget
    for key in sorted((k for k in CATALOG if k != "1x1"),
                      key=lambda key: np.prod(CATALOG[key]), reverse=True):
        take = min(left, counts[key])
        volume += take * math.prod(CATALOG[key])
        left -= take
    initial_scale = (volume * 1.2 / solid) ** (1 / 3)
    scale_factors = options.get("scale_factors", [0.90, 1.00, 1.08, 0.96, 1.04, 1.14, 1.18, 0.82])
    if not isinstance(scale_factors, (list, tuple)) or not 1 <= len(scale_factors) <= 8:
        raise ValueError("Scale factors must be a list of one to eight values.")
    scale_factors = [float(factor) for factor in scale_factors]
    if any(not math.isfinite(factor) or not 0.2 <= factor <= 3 for factor in scale_factors):
        raise ValueError("Scale factors must lie between 0.2 and 3.")
    experiments = []
    best = None
    for factor in scale_factors:
        if time.monotonic() > deadline:
            break
        scale = initial_scale * factor
        anticipated_shape = np.maximum(1, np.ceil(np.asarray(mask.shape) * scale * 5 / PITCH))
        if np.prod(anticipated_shape) > 1_500_000 or max(anticipated_shape) > 512:
            experiments.append(dict(scale=float(scale), skipped="Grid exceeds experimental preview/solver limit."))
            continue
        field = resample_occupancy(mask, scale, build_symmetry)
        symmetric_field = field.copy()
        for axis in build_symmetry:
            symmetric_field = (symmetric_field + np.flip(symmetric_field, axis=axis)) / 2
        candidates = _make_candidates(symmetric_field, counts, build_symmetry)
        if candidates is None:
            experiments.append(dict(scale=float(scale), dimensions=list(field.shape), candidates=0))
            continue
        seeds = _seed_indices(candidates)
        for trial, seed in enumerate(seeds):
            if trial and time.monotonic() > deadline:
                break
            placements, occupied = _grow(candidates, counts, budget, seed, deadline)
            placements, occupied = _details(symmetric_field, placements, occupied, counts, build_symmetry, budget)
            for pid, placement in enumerate(placements, start=1):
                placement["id"] = pid
            validation = validate_assembly(placements, counts,
                                           symmetry_axes=[AXES[i] for i in build_symmetry],
                                           grid_shape=list(field.shape), piece_cap=cap,
                                           cap_tolerance=tolerance)
            quality = _quality(field, occupied)
            structural_count = sum(p["part_id"] != "1x1" for p in placements)
            desired_count = min(structural_stock, cap if cap else structural_stock)
            use = min(1, structural_count / max(1, desired_count))
            score = 0.48 * quality["shape_iou"] + 0.20 * quality["target_coverage"] + 0.32 * use
            record = dict(scale=float(scale), dimensions=list(field.shape),
                          candidates=len(candidates), pieces=len(placements),
                          structural_pieces=structural_count, score=float(score),
                          valid=bool(validation["valid"]), **quality)
            experiments.append(record)
            if validation["valid"] and (best is None or score > best[0]):
                best = (score, placements, occupied, field, scale, validation, quality)
            # A good first seed does not need a redundant full packing run.
            if trial == 0 and validation["valid"] and quality["target_coverage"] > 0.78:
                break
    base["experiments"] = experiments
    if best is None:
        base["diagnostics"].append("The bounded search found no assembly satisfying all connection, symmetry, and inventory checks. This is not a proof that no feasible assembly exists. More mixed-size structural stock, a larger cap, or a different up axis may help.")
        base["metrics"] = dict(elapsed_seconds=round(time.monotonic() - started, 3),
                               inventory_total=total_stock, structural_inventory_total=structural_stock,
                               source_solid_voxels=solid, target_component_count=int(target_components))
        return base
    _, placements, occupied, field, scale, validation, quality = best
    structural_count = sum(p["part_id"] != "1x1" for p in placements)
    sequence = _sequence(placements, validation["connection_edges"])
    if len(sequence) != len(placements):
        raise RuntimeError("Validated contact graph did not produce a complete assembly order.")
    sequence_validation = validate_sequence(placements, sequence, validation["connection_edges"])
    if not sequence_validation["valid"]:
        raise RuntimeError("Assembly sequence failed independent insertion/support validation.")
    sequence_validation["bottom_up"] = True
    sequence_validation["top_down_box_insertion"] = True
    sequence_validation["temporary_support_steps"] = len(sequence_validation["support_required_bricks"])
    if sequence_validation["support_required_bricks"]:
        warnings.append(f"{len(sequence_validation['support_required_bricks'])} placement steps need temporary support or an aligned held subassembly; these support materials are not counted as inventory bricks.")
    if quality["target_coverage"] < 0.70:
        warnings.append("The current candidate covers less than 70% of the target material at its selected scale; inspect the preview before building.")
    if structural_count < 0.65 * min(structural_stock, cap if cap else structural_stock):
        warnings.append("This candidate leaves substantial structural stock unused. The heuristic may need better packing or a different inventory mix.")
    if time.monotonic() > deadline:
        warnings.append("The search reached its time budget and returned the best validated candidate found so far.")
    base.update(success=True, status="candidate", placements=placements, sequence=sequence,
                dimensions=list(field.shape), validation=validation,
                sequence_validation=sequence_validation,
                inventory_usage=dict(Counter(p["part_id"] for p in placements)),
                metrics=dict(piece_count=len(placements), structural_count=structural_count,
                             detail_count=len(placements) - structural_count,
                             inventory_total=total_stock, structural_inventory_total=structural_stock,
                             inventory_utilization=len(placements) / max(1, total_stock),
                             structural_utilization=structural_count / max(1, structural_stock),
                             cap=cap, maximum_pieces=budget, scale=float(scale),
                             source_voxel_size_in_relative_units=float(5 * scale),
                             elapsed_seconds=round(time.monotonic() - started, 3),
                             source_solid_voxels=solid, target_component_count=int(target_components),
                             **quality))
    base["symmetry"]["planes"] = {AXES[i]: field.shape[i] / 2 for i in build_symmetry}
    base["diagnostics"].append(f"Selected the best validated candidate from {len(experiments)} scale/seed trials; all {len(placements)} bricks belong to one stud-contact component.")
    return base
