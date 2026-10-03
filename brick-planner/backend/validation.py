"""Independent geometry checks for full-height brick placements.

Coordinates are *lattice* coordinates: x/z count studs and y counts full-height
layers. Their physical relative pitches are (5, 6, 5), not cubic voxels. A graph
edge means at least one aligned stud in consecutive layers. It is not a claim
about clutch force, load capacity, or unsupported insertion stability.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from math import isfinite
from numbers import Integral, Real


CATALOG = {
    "1x1": (1, 1),
    "2x1": (2, 1),
    "4x1": (4, 1),
    "6x1": (6, 1),
    "2x2": (2, 2),
    "2x3": (2, 3),
    "2x4": (2, 4),
    "2x6": (2, 6),
    "2x8": (2, 8),
}
GEOMETRY = {"stud_pitch": 5, "layer_height": 6, "units": "relative"}
MAX_QUANTITY = 1_000_000
AXES = ("x", "y", "z")


def _integer(value):
    return isinstance(value, Integral) and not isinstance(value, bool)


def _sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _components(indices, edges):
    """Connected components of an induced graph, including isolated vertices."""
    remaining = set(indices)
    adjacency = defaultdict(set)
    for left, right in edges:
        if left in remaining and right in remaining:
            adjacency[left].add(right)
            adjacency[right].add(left)
    result = []
    while remaining:
        root = min(remaining)
        remaining.remove(root)
        component, todo = [root], [root]
        while todo:
            for neighbor in adjacency[todo.pop()]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.append(neighbor)
                    todo.append(neighbor)
        result.append(sorted(component))
    return result


def validate_assembly(
    placements,
    inventory,
    symmetry_axes=None,
    grid_shape=None,
    piece_cap=None,
    cap_tolerance=0.05,
):
    """Return JSON-safe validation evidence, without trusting solver metadata.

    A placement is ``{id, part_id, x, y, z, width, depth, height: 1}``.
    ``inventory`` accepts the part-id/quantity mapping used by the solver, or the
    browser's version-1 inventory document. Symmetry planes bisect ``grid_shape``
    in build coordinates. Each requested plane requires a structural brick
    whose *own center* lies on that plane; a symmetric pair of adjacent bricks
    does not satisfy this requirement.

    The optional cap permits up to floor(cap * (1 + tolerance)) pieces. It is a
    ceiling, not a minimum utilization requirement. Final and structural-only
    graphs must both be connected so 1x1 details cannot hold the backbone
    together. Assembly sequence feasibility is deliberately not inferred.
    """
    errors, warnings = [], []
    flags = {
        "geometry_valid": True,
        "no_overlaps": True,
        "inventory_valid": True,
        "budget_valid": True,
        "symmetry_valid": True,
        "center_bridges_valid": True,
    }

    def fail(flag, message):
        flags[flag] = False
        errors.append(message)

    # Accept exported inventory documents as a convenience without allowing
    # their dimensions or roles to replace the fixed supported catalog.
    stock = {}
    if isinstance(inventory, Mapping) and "parts" in inventory:
        if inventory.get("schema_version") != 1:
            fail("inventory_valid", "Inventory schema_version must be 1.")
        if inventory.get("geometry") != GEOMETRY:
            fail("inventory_valid", "Inventory must use relative stud pitch 5 and layer height 6.")
        parts = inventory.get("parts")
        if not _sequence(parts):
            fail("inventory_valid", "Inventory parts must be a list.")
            parts = []
        for part in parts:
            if not isinstance(part, Mapping):
                fail("inventory_valid", "Every inventory part must be an object.")
                continue
            part_id = part.get("id")
            if not isinstance(part_id, str) or part_id not in CATALOG:
                fail("inventory_valid", "Inventory contains an unsupported part ID.")
                continue
            if part_id in stock:
                fail("inventory_valid", f"Inventory repeats part {part_id}.")
            if (
                part.get("studs") != list(CATALOG[part_id])
                or part.get("height_layers") != 1
                or part.get("role") != ("detail" if part_id == "1x1" else "structure")
            ):
                fail("inventory_valid", f"Inventory dimensions or role are invalid for {part_id}.")
            stock[part_id] = part.get("quantity")
        if set(stock) != set(CATALOG):
            fail("inventory_valid", "Inventory document must contain all nine supported parts.")
    elif isinstance(inventory, Mapping):
        stock = dict(inventory)
    else:
        fail("inventory_valid", "Inventory must be an object mapping part IDs to quantities.")

    normalized_stock = {part_id: 0 for part_id in CATALOG}
    for part_id, quantity in stock.items():
        if part_id not in CATALOG:
            fail("inventory_valid", f"Unsupported inventory part ID: {part_id!r}.")
        elif not _integer(quantity) or quantity < 0 or quantity > MAX_QUANTITY:
            fail("inventory_valid", f"Quantity for {part_id} must be an integer from 0 to {MAX_QUANTITY}.")
        else:
            normalized_stock[part_id] = int(quantity)

    shape = None
    if grid_shape is not None:
        if (
            not _sequence(grid_shape)
            or len(grid_shape) != 3
            or any(not _integer(n) or n <= 0 for n in grid_shape)
        ):
            fail("geometry_valid", "grid_shape must contain three positive integers in x/y/z order.")
        else:
            shape = tuple(int(n) for n in grid_shape)

    axes = []
    if symmetry_axes is not None:
        if not _sequence(symmetry_axes):
            fail("symmetry_valid", "symmetry_axes must be a list of x/y/z axes.")
        else:
            for axis in symmetry_axes:
                if _integer(axis) and 0 <= axis < 3:
                    axis = AXES[int(axis)]
                if not isinstance(axis, str) or axis not in AXES:
                    fail("symmetry_valid", f"Unsupported symmetry axis: {axis!r}.")
                elif axis not in axes:
                    axes.append(axis)
    if axes and shape is None:
        fail("symmetry_valid", "Requested symmetry requires a valid grid_shape.")
        fail("center_bridges_valid", "Center bridges require a valid symmetry plane.")

    cap_upper = None
    if not isinstance(cap_tolerance, Real) or isinstance(cap_tolerance, bool) or not isfinite(cap_tolerance) or not 0 <= cap_tolerance <= 1:
        fail("budget_valid", "cap_tolerance must be a finite number between 0 and 1.")
    if piece_cap is not None:
        if not _integer(piece_cap) or piece_cap <= 0:
            fail("budget_valid", "piece_cap must be a positive integer or null.")
        elif flags["budget_valid"]:
            # Decimal preserves a user's exact percentage: binary floating
            # point would floor 100 * 1.15 to 114 instead of the intended 115.
            cap_upper = int(Decimal(int(piece_cap)) * (1 + Decimal(str(cap_tolerance))))

    if not _sequence(placements):
        fail("geometry_valid", "placements must be a list.")
        placements = []
    piece_count = len(placements)
    if cap_upper is not None and piece_count > cap_upper:
        fail("budget_valid", f"Assembly uses {piece_count} pieces, exceeding the permitted cap of {cap_upper}.")
    if not placements:
        fail("geometry_valid", "Assembly contains no bricks.")

    usage = Counter()
    bricks = []
    seen_ids = set()
    for index, placement in enumerate(placements):
        if not isinstance(placement, Mapping):
            fail("geometry_valid", f"Placement {index} must be an object.")
            continue
        part_id = placement.get("part_id")
        if not isinstance(part_id, str) or part_id not in CATALOG:
            fail("geometry_valid", f"Placement {index} has an unsupported part ID.")
            continue
        usage[part_id] += 1
        brick_id = placement.get("id")
        if not (isinstance(brick_id, str) and brick_id) and not _integer(brick_id):
            fail("geometry_valid", f"Placement {index} requires a nonempty string or integer ID.")
            continue
        if brick_id in seen_ids:
            fail("geometry_valid", f"Duplicate placement ID: {brick_id!r}.")
        seen_ids.add(brick_id)
        values = [placement.get(field) for field in ("x", "y", "z", "width", "depth", "height")]
        if any(not _integer(value) for value in values):
            fail("geometry_valid", f"Brick {brick_id!r} requires integer lattice coordinates and dimensions.")
            continue
        x, y, z, width, depth, height = map(int, values)
        if min(x, y, z) < 0:
            fail("geometry_valid", f"Brick {brick_id!r} lies outside the nonnegative build lattice.")
        if height != 1 or (width, depth) not in (CATALOG[part_id], CATALOG[part_id][::-1]):
            fail("geometry_valid", f"Brick {brick_id!r} dimensions do not match {part_id} in either allowed rotation.")
            continue
        if shape and (x + width > shape[0] or y + 1 > shape[1] or z + depth > shape[2]):
            fail("geometry_valid", f"Brick {brick_id!r} extends beyond grid_shape.")
        bricks.append({"id": int(brick_id) if _integer(brick_id) else brick_id, "part_id": part_id, "x": x, "y": y, "z": z, "width": width, "depth": depth, "height": 1})

    for part_id, used in usage.items():
        if used > normalized_stock[part_id]:
            fail("inventory_valid", f"Assembly uses {used} of {part_id}, but inventory contains {normalized_stock[part_id]}.")

    occupied = {}
    overlap_pairs = set()
    for index, brick in enumerate(bricks):
        for x in range(brick["x"], brick["x"] + brick["width"]):
            for z in range(brick["z"], brick["z"] + brick["depth"]):
                cell = (x, brick["y"], z)
                if cell in occupied:
                    overlap_pairs.add((occupied[cell], index))
                else:
                    occupied[cell] = index
    for left, right in sorted(overlap_pairs):
        fail("no_overlaps", f"Bricks {bricks[left]['id']!r} and {bricks[right]['id']!r} overlap.")

    contacts = Counter()
    for upper, brick in enumerate(bricks):
        for x in range(brick["x"], brick["x"] + brick["width"]):
            for z in range(brick["z"], brick["z"] + brick["depth"]):
                lower = occupied.get((x, brick["y"] - 1, z))
                if lower is not None:
                    contacts[(lower, upper)] += 1
    edges = list(contacts)
    components = _components(range(len(bricks)), edges)
    structural = {index for index, brick in enumerate(bricks) if brick["part_id"] != "1x1"}
    structural_components = _components(structural, edges)
    connected = len(components) == 1 and len(bricks) == piece_count
    structure_connected = len(structural_components) == 1
    if not connected:
        errors.append(f"Assembly has {len(components)} stud-connected components; exactly one is required.")
    if not structural:
        errors.append("Assembly needs structural bricks; 1x1 bricks are reserved for details.")
    elif not structure_connected:
        errors.append(f"Structural bricks form {len(structural_components)} components without 1x1 details; details cannot connect the backbone.")

    key_fields = ("part_id", "x", "y", "z", "width", "depth", "height")
    keys = Counter(tuple(brick[field] for field in key_fields) for brick in bricks)
    crossing = {axis: [] for axis in axes}
    planes = {}
    if shape:
        for axis in axes:
            size = shape[AXES.index(axis)]
            planes[axis] = size / 2
            dimension = {"x": "width", "y": "height", "z": "depth"}[axis]
            reflected = Counter()
            for brick in bricks:
                mirror = dict(brick)
                mirror[axis] = size - brick[axis] - brick[dimension]
                reflected[tuple(mirror[field] for field in key_fields)] += 1
                if (
                    brick["part_id"] != "1x1"
                    and brick[axis] * 2 < size < (brick[axis] + brick[dimension]) * 2
                    and brick[axis] * 2 + brick[dimension] == size
                ):
                    crossing[axis].append(brick["id"])
            if reflected != keys:
                fail("symmetry_valid", f"Brick placements are not reflection-symmetric across {axis}={size / 2:g}.")
            if not crossing[axis]:
                fail("center_bridges_valid", f"Symmetry plane {axis}={size / 2:g} has no centered structural brick crossing it.")

    single_contacts = sum(studs == 1 for studs in contacts.values())
    if single_contacts:
        warnings.append(f"{single_contacts} brick connections engage only one stud; connection strength is not evaluated.")
    if piece_cap is not None and _integer(piece_cap) and piece_count < piece_cap:
        warnings.append("The requested piece cap is an upper limit; this candidate uses fewer pieces.")
    warnings.append("Stud connectivity and brick geometry do not certify strength, support stability, or an executable assembly sequence.")

    return {
        "valid": not errors,
        "success": not errors,
        **flags,
        "connected": connected,
        "structural_connected": structure_connected,
        "component_count": len(components),
        "structural_component_count": len(structural_components),
        "components": [[bricks[index]["id"] for index in component] for component in components],
        "connection_edges": [[bricks[left]["id"], bricks[right]["id"]] for left, right in edges],
        "connection_contacts": [{"lower_id": bricks[left]["id"], "upper_id": bricks[right]["id"], "studs": int(studs)} for (left, right), studs in contacts.items()],
        "inventory_usage": {part_id: int(usage[part_id]) for part_id in CATALOG},
        "inventory_remaining": {part_id: int(normalized_stock[part_id] - usage[part_id]) for part_id in CATALOG},
        "piece_count": piece_count,
        "structural_piece_count": len(structural),
        "detail_piece_count": int(usage["1x1"]),
        "piece_cap": int(piece_cap) if _integer(piece_cap) else None,
        "piece_cap_upper": cap_upper,
        "symmetry_axes": axes,
        "symmetry_planes": planes,
        "crossing_bricks": crossing,
        "geometry": dict(GEOMETRY),
        "errors": errors,
        "warnings": warnings,
    }


def validate_sequence(placements, sequence, connection_edges=None):
    """Check one-brick steps for vertical insertion and honest support notes.

    Recompute contacts from geometry instead of trusting sequence metadata or
    ``connection_edges`` (accepted for callers that already carry the graph).
    Each brick descends vertically from above. Earlier bricks at any greater
    height with overlapping stud footprints obstruct that insertion. Separate
    grounded components are permitted until a later brick joins them.

    The lowest occupied lattice layer is the work surface. An elevated brick
    without a previously placed lower contact needs explicit temporary support.
    This check does not establish balance, clutch strength, or access for hands.
    """
    errors = []
    normalized = {}
    if not _sequence(placements) or not _sequence(sequence):
        return {"valid": False, "complete": False, "unique_coverage": False,
                "top_down_clearance": False, "insertion_paths": False,
                "support_notes_valid": False, "contact_order": False,
                "gravity_stability": False, "support_required_bricks": [],
                "independent_ground_bricks": [], "ground_layer": None,
                "errors": ["Placements and sequence must be lists."], "warnings": []}
    for index, brick in enumerate(placements):
        if not isinstance(brick, Mapping):
            errors.append(f"Placement {index} must be an object.")
            continue
        brick_id = brick.get("id")
        if not ((isinstance(brick_id, str) and brick_id) or _integer(brick_id)):
            errors.append(f"Placement {index} needs a string or integer ID.")
            continue
        if brick_id in normalized:
            errors.append(f"Duplicate placement ID: {brick_id!r}.")
            continue
        fields = ("x", "y", "z", "width", "depth", "height")
        values = [brick.get(field) for field in fields]
        if any(not _integer(value) for value in values) or min(values[:3]) < 0 or min(values[3:]) <= 0 or values[-1] != 1:
            errors.append(f"Brick {brick_id!r} has invalid one-layer lattice geometry.")
            continue
        # Bound work per brick with the same actual part catalog as the main
        # validator; a bogus billion-stud dimension must not create a huge loop.
        part_id = brick.get("part_id")
        if not isinstance(part_id, str) or part_id not in CATALOG or (values[3], values[4]) not in (CATALOG[part_id], CATALOG[part_id][::-1]):
            errors.append(f"Brick {brick_id!r} dimensions do not match the catalog.")
            continue
        normalized[brick_id] = {field: int(value) for field, value in zip(fields, values)}
    ground = min((brick["y"] for brick in normalized.values()), default=None)
    unique = not errors
    clearance, support_notes, contact_order = True, True, True
    placed, occupied, highest = set(), {}, {}
    support_required, independent_ground, step_evidence = [], [], []
    for step_number, step in enumerate(sequence, start=1):
        if not isinstance(step, Mapping) or not _sequence(step.get("brick_ids")) or len(step["brick_ids"]) != 1:
            errors.append(f"Step {step_number} must identify exactly one brick.")
            unique = False
            continue
        brick_id = step["brick_ids"][0]
        if not ((isinstance(brick_id, str) and brick_id) or _integer(brick_id)) or brick_id not in normalized:
            errors.append(f"Step {step_number} refers to an unknown brick.")
            unique = False
            continue
        if brick_id in placed:
            errors.append(f"Step {step_number} places brick {brick_id!r} twice.")
            unique = False
            continue
        brick = normalized[brick_id]
        footprint = [(x, z) for x in range(brick["x"], brick["x"] + brick["width"])
                     for z in range(brick["z"], brick["z"] + brick["depth"])]
        blockers, lower, contacts = set(), set(), set()
        for x, z in footprint:
            previous = highest.get((x, z))
            if previous is not None and previous[0] >= brick["y"]:
                blockers.add(previous[1])
            below = occupied.get((x, brick["y"] - 1, z))
            above = occupied.get((x, brick["y"] + 1, z))
            if below is not None:
                lower.add(below)
                contacts.add(below)
            if above is not None:
                contacts.add(above)
        if blockers:
            clearance = False
            errors.append(f"Step {step_number}: previously placed bricks obstruct vertical insertion of brick {brick_id!r}.")
        needs_support = brick["y"] > ground and not lower
        if needs_support:
            support_required.append(brick_id)
            if step.get("requires_support") is not True:
                support_notes = False
                errors.append(f"Step {step_number}: brick {brick_id!r} needs an explicit temporary-support instruction.")
        if not contacts:
            if placed:
                contact_order = False
            if brick["y"] == ground:
                independent_ground.append(brick_id)
        if "attached_to" in step:
            claimed = step["attached_to"]
            if not _sequence(claimed) or any(not ((isinstance(item, str) and item) or _integer(item)) for item in claimed) or set(claimed) != contacts:
                errors.append(f"Step {step_number}: attached_to does not match earlier stud contacts.")
        step_evidence.append({"step": step_number, "brick_id": brick_id,
                              "requires_support": needs_support,
                              "lower_contacts": sorted(lower, key=str),
                              "obstructed_by": sorted(blockers, key=str)})
        placed.add(brick_id)
        for x, z in footprint:
            occupied[(x, brick["y"], z)] = brick_id
            previous = highest.get((x, z))
            if previous is None or previous[0] < brick["y"]:
                highest[(x, z)] = (brick["y"], brick_id)
    complete = bool(normalized) and unique and len(normalized) == len(placements) and placed == set(normalized)
    if not complete:
        errors.append("The sequence must place every assembly brick exactly once.")
    warnings = ["Vertical insertion clearance assumes axis-aligned bricks and the stated temporary supports; gravity, clutch force, balance, and hand access are not simulated."]
    if len(independent_ground) > 1:
        warnings.append("Some ground-level pieces start as separate aligned sections before upper bricks connect them.")
    if support_required:
        warnings.append(f"{len(support_required)} elevated bricks require temporary support before later pieces connect them.")
    return {"valid": not errors, "complete": complete, "unique_coverage": unique and complete,
            "top_down_clearance": clearance, "insertion_paths": clearance,
            "support_notes_valid": support_notes, "contact_order": contact_order,
            "gravity_stability": False, "support_required_bricks": support_required,
            "independent_ground_bricks": independent_ground, "ground_layer": ground,
            "step_evidence": step_evidence, "errors": errors, "warnings": warnings}
