# QSOL-MESH

**Heterogeneous compute and memory runtime that calibrates real CPU/GPU silicon, plans workload placement across system RAM and VRAM, and executes deterministic workloads across both.**

MESH separates workload meaning from execution placement. A workload defines what must be computed and how correctness is verified. MESH may decide where, when, and how work executes, but may not redefine the workload.

Initial CLI: `mesh inspect`, `mesh calibrate`, `mesh plan`, `mesh run`, `mesh verify`, `mesh receipt`.

Human-readable explanations live at the repository root. Normative automated-agent authority lives under `machine/`.

## Phase 1 CPU bring-up

The first executable workload is deliberately tiny and dependency-free:

```sh
mesh inspect --json
mesh run smoke --items 100000 --workers 8 --json
mesh verify smoke --items 100000 --workers 8 --json
```

`mesh-smoke-v1` procedurally maps logical IDs to integer values, partitions only contiguous ranges, reduces worker partials in worker-index order, and verifies every run against the scalar reference. It is correctness scaffolding, not a performance benchmark.

## Phase 2 GALAXY adapter boundary

The first external adapter now has a machine-readable contract plus reusable range/reduction primitives. MESH can split a GALAXY logical population into complete half-open ranges, emit executor-local regeneration requests, accept compact range-bound `u64` partials in any completion order, validate exact coverage, reduce deterministically, and fail closed on oracle disagreement.

GALAXY remains the semantic authority. QSOL-MESH contains no copied GALAXY address mixer, particle generation, physics, projection math, or GPU kernels.

The adapter pins the frozen GALAXY v0.4.0 source identity and archived CPU oracle checksums. Static CPU-only, accelerator-only, and heterogeneous requested geometries are available as planning primitives, but requested accelerator placement is **not** execution evidence. Live partitioned GALAXY parity and GPU/heterogeneous baselines remain gated on a GALAXY-owned range entrypoint and the real Phase 1 accelerator executor.

See `GALAXY-ADAPTER.md` and `machine/workloads/galaxy-v0.4.0.json`.
