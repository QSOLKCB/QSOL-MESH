# QSOL-MESH Constitution

> **MESH may decide where, when, and how work executes. It may never redefine what the workload computes.**

A workload owns semantic meaning, inputs/outputs, admissible partitioning, exactness/tolerance, reduction semantics, verification oracle, and side-effect commit rules.

MESH owns topology observation, calibration, planning, scheduling, memory placement, transfer orchestration, executor lifecycle, and execution evidence.

Non-negotiable rules:

1. Hardware identity may generate candidates; it is never performance authority.
2. Measured execution selects among admissible candidates.
3. Optimization evidence never becomes workload semantic authority.
4. CPU/GPU/future backends are mechanisms, not independent workload definitions.
5. Verified status requires the workload verification contract to pass.
6. Silent correctness fallback is forbidden.
7. Memory ownership and transfer boundaries must be explicit.
8. Deterministic workloads preserve declared reduction/commit order despite out-of-order completion.
9. Calibration is bounded, versioned, and auditable.
10. Canonical/reference execution remains available until an explicit versioned replacement.
11. No CPU/GPU/model-name lookup table may hard-code a claimed optimum.
12. All future backends remain behind the same workload/evidence boundaries.

Machine-enforceable form: `machine/mesh-contract.v1.json`.
