# QSOL-MESH v0.1.0 — Constitutional Architecture Freeze

QSOL-MESH v0.1.0 is the first immutable constitutional baseline for the project.

It freezes the authority boundary established before heterogeneous CPU/GPU implementation begins:

> MESH may decide where, when, and how work executes. It may never redefine what the workload computes.

## Frozen surfaces

- workload-versus-execution authority separation;
- 12 blocking MESH constitutional invariants;
- machine-readable AI review policy;
- workload adapter contract;
- explicit memory-domain contract;
- execution evidence and claim boundary;
- dependency-free Rust workspace;
- initial CLI command surface:
  - `mesh inspect`
  - `mesh calibrate`
  - `mesh plan`
  - `mesh run`
  - `mesh verify`
  - `mesh receipt`
- pinned Rust 1.85.1 bootstrap toolchain.

The release manifest binds these surfaces to their exact Git blob identities from the merged PR #1 constitutional baseline.

## AI review boundary

Blocking automated-review findings must remain actionable correctness defects tied to the exact reviewed SHA and an existing contract/invariant. They require a minimal reproduction, expected versus actual behavior, affected lines, and an explicit executed/statically-inferred status.

The release freezes the rule that architectural suggestions are separate and non-blocking, and that hypothetical invalid-input parser archaeology is not a blocking correctness finding.

## Explicitly not implemented in v0.1.0

This release does **not** claim or contain:

- CUDA execution;
- a GALAXY runtime adapter;
- CPU/GPU concurrent scheduling;
- adaptive scheduling;
- managed/unified-memory policy;
- runtime calibration implementation;
- automatic performance promotion;
- production heterogeneous execution.

Those capabilities begin only in later phases under the frozen constitutional contracts.

## Release procedure

This file is prepared before tagging. After the release-prep PR is merged with green CI, tag the exact merge commit as:

```text
v0.1.0
```

The tag must point to a commit that contains this release manifest and passes `scripts/release-preflight.py`.

Once tagged, v0.1.0 is treated as immutable.
