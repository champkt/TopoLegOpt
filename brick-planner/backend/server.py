"""Same-origin local API plus the static TopoLegOpt application."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from .input_data import MAX_UPLOAD, inspect_npz, validate_inventory, validate_options

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('TOPOLEG_DATA_DIR', ROOT / '.local'))
TOPOLOGIES = DATA / 'topologies'
JOBS = DATA / 'jobs'
PROCESSES = {}
TASKS = set()

async def stop_process(process):
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()

def save_json(path, value):
    temporary = path.with_suffix('.tmp.json')
    temporary.write_text(json.dumps(value, allow_nan=False))
    temporary.replace(path)

def job_folder(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise HTTPException(404, 'Unknown assembly job.')
    folder = JOBS / job_id
    if not (folder / 'status.json').exists():
        raise HTTPException(404, 'Unknown assembly job.')
    return folder

@asynccontextmanager
async def lifespan(app):
    TOPOLOGIES.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    for path in JOBS.glob('*/status.json'):
        value = json.loads(path.read_text())
        if value.get('status') in ('queued', 'running'):
            value.update(status='failed', error='Server restarted before this run completed. Run the assembly again.')
            save_json(path, value)
    yield
    for process in list(PROCESSES.values()):
        await stop_process(process)
    if TASKS:
        await asyncio.gather(*TASKS, return_exceptions=True)

app = FastAPI(title='TopoLegOpt local assembly API', lifespan=lifespan)

@app.middleware('http')
async def same_origin(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method in ('POST', 'DELETE') and origin and origin != str(request.base_url).rstrip('/'):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': 'Use the TopoLegOpt page on the same host.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.get('/api/health')
def health():
    return {'status': 'ok', 'application': 'TopoLegOpt', 'max_pieces': 5000}

@app.post('/api/topology')
async def upload_topology(request: Request):
    temporary = TOPOLOGIES / f'{uuid4().hex}.tmp.npz'
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open('wb') as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, 'NPZ uploads are limited to 128 MiB.')
                stream.write(chunk)
                digest.update(chunk)
        try:
            metadata = await asyncio.to_thread(inspect_npz, temporary)
        except Exception as error:
            raise HTTPException(422, f'Cannot read this topology: {error}') from error
        topology_id = digest.hexdigest()
        destination = TOPOLOGIES / f'{topology_id}.npz'
        temporary.replace(destination)
        metadata.update(id=topology_id, name=Path(unquote(request.headers.get('x-filename', 'topology.npz'))).name[:255], size_bytes=size)
        save_json(TOPOLOGIES / f'{topology_id}.json', metadata)
        return metadata
    finally:
        temporary.unlink(missing_ok=True)

async def run_job(job_id):
    folder = JOBS / job_id
    status_path = folder / 'status.json'
    process = None
    try:
        status = json.loads(status_path.read_text())
        if status['status'] == 'cancelled':
            return
        status['status'] = 'running'
        save_json(status_path, status)
        with (folder / 'worker.log').open('wb') as log:
            environment = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
            process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'backend.job_runner', str(folder), cwd=ROOT, stdout=log, stderr=log, env=environment)
            PROCESSES[job_id] = process
            if json.loads(status_path.read_text())['status'] == 'cancelled':
                await stop_process(process)
                return
            try:
                await asyncio.wait_for(process.wait(), timeout=180)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                status.update(status='failed', error='This experimental run exceeded three minutes. Try a lower piece cap.')
        current = json.loads(status_path.read_text())
        if current['status'] == 'cancelled':
            return
        if status['status'] != 'failed':
            if process.returncode == 0 and (folder / 'result.json').exists():
                status['status'] = 'completed'
            else:
                error_path = folder / 'error.json'
                error = json.loads(error_path.read_text())['error'] if error_path.exists() else 'The solver process stopped unexpectedly.'
                status.update(status='failed', error=error)
        save_json(status_path, status)
    except Exception as error:
        current = json.loads(status_path.read_text())
        if current.get('status') != 'cancelled':
            save_json(status_path, {'job_id': job_id, 'status': 'failed', 'error': str(error)})
    finally:
        if process is not None:
            await stop_process(process)
        PROCESSES.pop(job_id, None)

@app.post('/api/assembly', status_code=202)
async def create_assembly(request: Request):
    # Small JSON requests only; topology bytes use the separate upload endpoint.
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, 'Assembly settings are too large.')
    try:
        value = json.loads(raw)
        inventory = validate_inventory(value.get('inventory'))
        options = validate_options(value.get('options', {}), inventory)
        topology_id = value.get('topology_id', '')
        if not isinstance(topology_id, str) or not re.fullmatch(r'[a-f0-9]{64}', topology_id):
            raise ValueError('Load a topology before running the assembly.')
    except (ValueError, TypeError, AttributeError) as error:
        raise HTTPException(422, str(error)) from error
    topology_path = TOPOLOGIES / f'{topology_id}.npz'
    if not topology_path.exists():
        raise HTTPException(404, 'Topology is no longer on this server. Reload the topology tab to sync it again.')
    active = sum(json.loads(path.read_text()).get('status') in ('queued', 'running') for path in JOBS.glob('*/status.json'))
    if active >= 2:
        raise HTTPException(409, 'Two assembly experiments are already running. Wait or cancel a run first.')
    job_id = uuid4().hex
    folder = JOBS / job_id
    folder.mkdir()
    save_json(folder / 'request.json', {'topology_id': topology_id, 'topology_path': str(topology_path), 'inventory': inventory, 'options': options})
    save_json(folder / 'status.json', {'job_id': job_id, 'status': 'queued', 'created_at': time.time()})
    task = asyncio.create_task(run_job(job_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {'job_id': job_id}

@app.get('/api/jobs/{job_id}')
def read_job(job_id: str):
    folder = job_folder(job_id)
    status = json.loads((folder / 'status.json').read_text())
    if status['status'] == 'completed':
        status['result'] = json.loads((folder / 'result.json').read_text())
    return status

@app.delete('/api/jobs/{job_id}')
async def cancel_job(job_id: str):
    folder = job_folder(job_id)
    status = json.loads((folder / 'status.json').read_text())
    if status['status'] in ('queued', 'running'):
        status['status'] = 'cancelled'
        save_json(folder / 'status.json', status)
        process = PROCESSES.get(job_id)
        if process:
            await stop_process(process)
    return status

app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='application')
