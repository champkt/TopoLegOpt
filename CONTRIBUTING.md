# Contributing

Use the [development guide](docs/DEVELOPMENT.md) for setup and verification.
Keep changes scoped to the planner, documentation, and public examples. The
separate research directories are not application dependencies or test fixtures.

For solver changes, explain the failure case and the resulting behavior. Add a
regression test when changing geometry, scale conversion, inventory accounting,
symmetry, connectivity, or sequence guarantees. Report fit and utilization
separately; a larger piece count alone does not establish a better assembly.
Keep empirical policies distinct from mathematically enforced constraints.

Documentation changes should name assumptions, define quantities before using
them, cite primary sources for established methods, and credit libraries in the
software section. Update Markdown sources rather than generated web pages.

Before submitting a change, run the build, JavaScript tests, Python tests, and
portable example experiment from the main README. Exclude local environments,
generated bundles, uploads, and job output. A project license has not yet been
selected; discuss reuse or licensing with the maintainer before relying on a
particular grant of rights.
