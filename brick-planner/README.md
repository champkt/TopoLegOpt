# TopoLegOpt application

Start with the [project README](../README.md) for installation, the user workflow,
input examples, and an overview of the algorithm.

- [Detailed method](../docs/ALGORITHM.md)
- [NPZ input specification](../docs/NPZ_SPEC.md)
- [Architecture, development, and hosting](../docs/DEVELOPMENT.md)
- [Experiments and limitations](EXPERIMENTS.md)

This directory contains the Python API/solver and authored browser code.
`npm run build` produces the complete `dist/` website from `src/`, `web/`, and the
shared repository documentation. Do not edit generated `dist/` files.

From this directory, `npm run start:local` serves localhost and `npm start`
serves all IPv4 interfaces on port 5173. Both require the Python `.venv` and npm
dependencies described in the project README.
