"""Validate portable inputs before starting an experimental solver job."""
from pathlib import Path
import math
from decimal import Decimal, ROUND_FLOOR
import zipfile
import numpy as np

CATALOG = {'1x1': (1, 1), '2x1': (2, 1), '4x1': (4, 1), '6x1': (6, 1),
           '2x2': (2, 2), '2x3': (2, 3), '2x4': (2, 4), '2x6': (2, 6), '2x8': (2, 8)}
MAX_UPLOAD = 128 * 1024**2
MAX_VOXELS = 32_000_000
MAX_HEADER_BYTES = 65_536

def supported_density_dtype(dtype):
    return ((dtype.kind == 'b' and dtype.itemsize == 1)
            or (dtype.kind in 'iu' and dtype.itemsize in (1, 2, 4, 8))
            or (dtype.kind == 'f' and dtype.itemsize in (4, 8)))

def inspect_npz(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 64 or sum(entry.file_size for entry in entries) > 512 * 1024**2:
            raise ValueError('NPZ exceeds the 64-entry or 512 MiB unpacked limit.')
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError('Duplicate array names are unsupported.')
    arrays = []
    with np.load(path, allow_pickle=False, max_header_size=MAX_HEADER_BYTES) as archive:
        for key in archive.files:
            try:
                value = archive[key]
            except ValueError:
                continue
            if isinstance(value, np.ndarray) and value.ndim == 3 and supported_density_dtype(value.dtype) and 0 < value.size <= MAX_VOXELS:
                arrays.append({'key': key, 'shape': list(value.shape), 'dtype': str(value.dtype)})
    if not arrays:
        raise ValueError('No supported 3D numeric array was found in the NPZ.')
    return {'arrays': arrays}

def load_density(path: Path, key: str) -> np.ndarray:
    with np.load(path, allow_pickle=False, max_header_size=MAX_HEADER_BYTES) as archive:
        if key not in archive.files:
            raise ValueError('The selected density array is not present in the NPZ.')
        value = archive[key]
        if not isinstance(value, np.ndarray) or value.ndim != 3 or not supported_density_dtype(value.dtype) or not 0 < value.size <= MAX_VOXELS:
            raise ValueError('Density must be a numeric 3D array with at most 32 million voxels.')
        if not np.isfinite(value).all() or value.min() < 0 or value.max() > 1:
            raise ValueError('Density must contain finite values between zero and one.')
        return np.asarray(value, dtype=np.float64)

def validate_inventory(value: dict) -> dict:
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('Expected a version 1 brick inventory.')
    if value.get('geometry') != {'stud_pitch': 5, 'layer_height': 6, 'units': 'relative'}:
        raise ValueError('Inventory geometry must use relative stud pitch 5 and layer height 6.')
    name = value.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError('Invalid inventory name.')
    parts = value.get('parts')
    if not isinstance(parts, list) or len(parts) != 9:
        raise ValueError('Inventory must contain all nine brick types.')
    seen = set()
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError('Invalid brick inventory entry.')
        key = part.get('id')
        if key not in CATALOG or key in seen:
            raise ValueError('Unknown or duplicate part type.')
        seen.add(key)
        quantity = part.get('quantity')
        if type(quantity) is not int or not 0 <= quantity <= 1_000_000:
            raise ValueError('Part quantities must be whole numbers from 0 to 1,000,000.')
        if part.get('studs') != list(CATALOG[key]) or part.get('height_layers') != 1:
            raise ValueError('Part dimensions do not match the supported catalog.')
        if part.get('role') != ('detail' if key == '1x1' else 'structure'):
            raise ValueError('Only 1×1 bricks may be classified as details.')
    return value

def validate_options(value: dict, inventory: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError('Expected assembly settings.')
    result = {key: value.get(key, default) for key, default in {
        'threshold': .5, 'up': 'y', 'mirror': 'none', 'symmetry': 'auto',
        'piece_cap': None, 'tolerance': .05, 'key': 'density',
    }.items()}
    if type(result['threshold']) not in (int, float) or not math.isfinite(result['threshold']) or not 0 <= result['threshold'] <= 1:
        raise ValueError('Threshold must be between zero and one.')
    if result['up'] not in ('x', 'y', 'z') or result['mirror'] not in ('none', 'x', 'y', 'z'):
        raise ValueError('Invalid topology orientation.')
    if result['symmetry'] not in ('auto', 'none', 'x', 'y', 'z'):
        raise ValueError('Invalid symmetry setting.')
    cap = result['piece_cap']
    if cap is not None and (type(cap) is not int or not 1 <= cap <= 9_000_000):
        raise ValueError('The approximate piece cap must be a positive whole number.')
    tolerance = result['tolerance']
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 <= tolerance <= .2:
        raise ValueError('Piece tolerance must be between 0% and 20%.')
    if not isinstance(result['key'], str) or not 1 <= len(result['key']) <= 256:
        raise ValueError('Invalid density array key.')
    total = sum(p['quantity'] for p in inventory['parts'])
    ceiling = int((Decimal(cap) * (1 + Decimal(str(tolerance)))).to_integral_value(rounding=ROUND_FLOOR)) if cap is not None else total
    maximum = min(total, ceiling)
    if maximum > 5000:
        raise ValueError('This experimental solver supports up to 5,000 pieces per run. Set a smaller approximate cap.')
    return result
