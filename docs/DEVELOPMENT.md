# Development and hosting

## Architecture

TopoLegOpt is a single-origin web application. FastAPI accepts NPZ uploads and
starts isolated Python solver subprocesses; the same Uvicorn process serves the
compiled browser app and documentation. The browser uses a Web Worker to parse
and inspect NPZ files and Three.js for the topology and assembly views.

| Location | Responsibility |
| --- | --- |
| `brick-planner/backend/input_data.py` | NPZ, inventory, and request validation |
| `brick-planner/backend/solver.py` | Scale search, fitting, packing, sequencing |
| `brick-planner/backend/validation.py` | Independent geometric and sequence checks |
| `brick-planner/backend/server.py` | Uploads, job lifecycle, static serving |
| `brick-planner/backend/job_runner.py` | One subprocess's input/output boundary |
| `brick-planner/src/` | Authored JavaScript, inventory model, NPZ decoder, UI |
| `brick-planner/web/` | HTML and CSS source |
| `brick-planner/scripts/build.mjs` | esbuild bundles and Marked documentation pages |
| `brick-planner/tests/` | Node and Python tests |

The build derives the hosted method and input-specification pages directly from
`docs/ALGORITHM.md` and `docs/NPZ_SPEC.md`. Relative documentation links are
rewritten for the website. Source-code links point to GitHub. The build completes
in `dist-next/` before replacing `dist/`, so a compilation error preserves the
previous build. Source documents are trusted repository files; this renderer is
not a service for arbitrary user-submitted Markdown.

## Development commands

Follow the [installation instructions](../README.md#run-locally), then run these
commands from `brick-planner/`:

```bash
npm run build
npm test
npm run test:python
.venv/bin/python scripts/experiment.py
```

Rebuild after changing browser source or documentation. Restart the server after
changing Python code. For backend-only iteration, start Uvicorn manually after
a build:

```bash
.venv/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port 5173 --reload
```

Keep the independent validators separate from the placement heuristic. A solver
change should include a counterexample or regression case that distinguishes
correct behavior from an incorrect implementation. Update documented thresholds,
assumptions, metrics, and credits when behavior or dependencies change.

Dependencies are pinned in `requirements.txt` and `package-lock.json`. The Python
file includes the API test client's dependencies so the documented installation
can run the tests directly. There is no dependency on a topology-optimization
project, CUDA, or the protected research directories.

## Public example experiment

`python scripts/experiment.py` uses `examples/bridge.npz`, the labeled synthetic
`experiments/reference-inventory.json`, Y up, no mirroring, threshold 0.5, and
automatic symmetry. It tries caps of 100, 500, and the full inventory. Supply
`--npz`, `--inventory`, `--mirror`, and `--output` to run another case. Full results
and a summary are written to `.local/experiments/` by default. These are illustrative
runs, not a benchmark suite. The script exits unsuccessfully if any run fails
its independent checks.

## Data and persistence

Browser data stays associated with its origin. Existing keys are preserved:

| Storage | Key | Content |
| --- | --- | --- |
| localStorage | `topoleg.inventory.v1` | Brick inventory |
| IndexedDB | `topoleg.topology.v1` | Uploaded NPZ and preview settings |
| localStorage | `topoleg-assembly-settings-v1` | Solver settings |
| localStorage | `topoleg-assembly-job-v1` | Latest job reference |

Server uploads are content-addressed by SHA-256 in `.local/topologies/`. Job
inputs, logs, status, and results live in `.local/jobs/`. Neither directory is
served as static content or committed. Export inventory and assembly JSON through
the UI for portable backups. Keep the source NPZ separately. A restarted server
marks interrupted jobs as failed; it does not resume an interrupted search.

Set `TOPOLEG_DATA_DIR` to an absolute directory to relocate server data. The
operator is responsible for backup and retention; automatic deletion is not
implemented. Do not use user uploads or saved inventories as public test fixtures.

## HTTP interface

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Application status and maximum piece budget |
| `POST /api/topology` | Raw NPZ bytes; optional `X-Filename` display name |
| `POST /api/assembly` | JSON `topology_id`, `inventory`, and `options` |
| `GET /api/jobs/{job_id}` | Status and, after completion, the result |
| `DELETE /api/jobs/{job_id}` | Cancel a pending or active job |

API schema documentation is available at `/docs` and `/openapi.json`; authored
user documentation is under `/docs/algorithm.html` and `/docs/npz-spec.html`.
The default settings and supported values are specified by
`backend/input_data.py`. Completed API results include placements, sequence, metrics, input inventory
and settings, and independent validation reports. The result format is currently
unversioned; the input inventory format separately uses `schema_version: 1`. Treat unsuccessful results and API errors as failures, not
empty build plans.

## Hosting

The default setup is intended for one user on localhost or a trusted private
network. For network access, `npm start` binds all IPv4 interfaces on port 5173.
Clients must be able to reach that host and port. Use the same host and port to
retain existing browser storage.

A public deployment needs a Python service as well as the static assets. A
static-only host can display files but cannot run this solver. Keep uploads and
job data on a persistent private volume, terminate HTTPS at a reverse proxy, and
add authentication and per-user data isolation before offering shared accounts.
The present API has no authentication: anyone with access to the service can
submit jobs and can retrieve a job if they have its identifier. Same-origin
request checks are not authentication.

Run **one Uvicorn worker**. Job concurrency and process handles are maintained
in that worker's memory; multiple workers require an external job queue and
shared lifecycle management. The application permits two concurrent jobs and
stops a subprocess after three minutes. Request and resource limits are
prototype safeguards, not a complete public multi-tenant service design.
