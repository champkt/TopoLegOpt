"""Run a portable example without using or changing browser inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.input_data import load_density, validate_inventory
from backend.solver import solve

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--npz', type=Path, default=ROOT.parent / 'examples/bridge.npz')
    parser.add_argument('--inventory', type=Path, default=ROOT / 'experiments/reference-inventory.json')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/experiments')
    parser.add_argument('--mirror', choices=['none', 'x', 'y', 'z'], default='none')
    args = parser.parse_args()
    inventory = validate_inventory(json.loads(args.inventory.read_text()))
    density = load_density(args.npz, 'density')
    args.output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for cap in [100, 500, None]:
        mirror = args.mirror
        options = dict(threshold=.5, up='y', mirror=mirror, piece_cap=cap, tolerance=.05, symmetry='auto')
        result = solve(density, inventory, options)
        result['experiment_inputs'] = {'npz': args.npz.name, 'source_sha256': hashlib.sha256(args.npz.read_bytes()).hexdigest(), 'inventory': inventory, 'options': options}
        name = f'mirror-{mirror}_cap-{cap if cap is not None else "inventory"}'
        (args.output / f'{name}.json').write_text(json.dumps(result, indent=2, allow_nan=False))
        row = {'case': name, 'success': result['success'], **result.get('metrics', {}),
               'symmetry': result.get('symmetry'), 'validation': result.get('validation'),
               'sequence_validation': result.get('sequence_validation')}
        summaries.append(row)
        print(json.dumps({key: row.get(key) for key in ['case','success','piece_count','shape_iou','target_coverage','elapsed_seconds']}), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(summaries, indent=2, allow_nan=False))
    if not all(row['success'] and row.get('validation', {}).get('valid') and row.get('sequence_validation', {}).get('valid') for row in summaries):
        raise SystemExit('At least one example run failed independent validation. Inspect summary.json.')

if __name__ == '__main__':
    main()
