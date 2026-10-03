# Documentation and publication review

Recorded October 3, 2026. Two independent assistant reviewers challenged the
algorithm and NPZ documentation against the source and then rechecked revisions.
This is an internal engineering review, not external journal peer review.

## Round 1: challenge assumptions and implementation correspondence

The review checked formulas, coordinate conventions, stock accounting, scale
limits, fit metrics, symmetry, connectivity, sequence claims, input portability,
and whether a reader could reproduce an example without private project files.

| Finding | Resolution |
| --- | --- |
| Changing up axis used an odd axis permutation and could reflect an asymmetric shape. | Changed X/Z-up handling to proper rotations, exported axis signs, and added asymmetric landmark regressions. |
| NumPy and browser readers accepted different density types and header/archive limits. | Aligned supported numeric types, the 65,536-byte header limit, and archive accounting. Added NumPy-generated compatibility and boundary cases. |
| NumPy boolean masks can encode true with nonzero bytes other than one. | Normalize boolean bytes in the browser while retaining strict integer-mask checks. |
| Direct solver input accepted unsuitable numeric data and rejected boolean masks. | Validate real finite densities in `[0,1]` and support boolean occupancy. |
| Greedy growth could be described as guaranteeing connectedness too early. | Explain single-brick versus multi-brick seeds and make final independent validation the acceptance gate. |
| Sparse overlap matrices conceal a dense temporary workspace. | Document memory cost and explain why grid caps are not complete memory bounds. |
| Independent validation could be mistaken for enforcing every detail policy. | Distinguish solver-enforced detail attachment/count policy from validator checks. |
| Earlier experiments depended on an unpublished research topology. | Add an independent bridge generator and default experiment; label external measurements as historical. |

## Round 2: recheck revised claims and usability

Reviewers rechecked the corrected coordinate map, overlap and score equations,
reflection groups, center crossings, cap rounding, soft stopping limits, physical
assumptions, executable NPZ examples, and original method/library attribution.
They also examined the README and setup guidance. Follow-up corrections removed
an unsupported within-layer attachment-priority claim and an incorrect claim
that exported solver results already had a schema version.

The method now separates established mathematical tools from this project's
empirical choices. It explains why successful geometry checks do not establish
mechanical reliability or global optimality. The input specification starts with
a minimal portable export and separates optional format alternatives and limits.

## Verification

The publication checks include the generated website, JavaScript and Python
regressions, the public bridge at three piece budgets, and a browser walkthrough
of documentation links, responsive layout, upload, assembly preview, and saved
state. The build reads the same Markdown shown on GitHub, preventing a separate
hosted explanation from drifting from the repository documentation.

A clean temporary checkout containing only the publication files passed fresh
dependency installation, the site build, 14 JavaScript tests, and 49 Python tests.
The public bridge produced validated plans of 103, 522, and 1,000 pieces for the
three requested budgets. The browser walkthrough also verified the final 3D
preview, export, reload persistence, and documentation navigation. All six
documentation pages passed local-link and anchor checks and layout checks down
to a 320-pixel viewport.

Future solver changes require renewed review of the corresponding claims;
this record describes the current publication work, not a permanent correctness
certificate. Read the [method's limitations](ALGORITHM.md#12-stopping-evidence-and-research-limitations)
and [input specification](NPZ_SPEC.md) alongside any generated plan.
