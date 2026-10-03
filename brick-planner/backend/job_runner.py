"""Isolated solver process; cancellation cannot leave work running in the server."""
import json
from pathlib import Path
import sys
import time
import traceback
from .input_data import load_density

def main():
    folder = Path(sys.argv[1])
    request = json.loads((folder / 'request.json').read_text())
    start = time.monotonic()
    try:
        from .solver import solve
        density = load_density(Path(request['topology_path']), request['options']['key'])
        result = solve(density, request['inventory'], request['options'])
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        result['input'] = {'topology_id': request['topology_id'], 'options': request['options'],
                           'inventory': request['inventory']}
        temporary = folder / 'result.tmp.json'
        temporary.write_text(json.dumps(result, allow_nan=False))
        temporary.replace(folder / 'result.json')
    except Exception as error:
        (folder / 'error.json').write_text(json.dumps({'error': str(error)}))
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
