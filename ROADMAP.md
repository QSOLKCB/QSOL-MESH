# QSOL-MESH Roadmap

## Phase 0 — constitutional architecture
- [x] Authority boundary.
- [x] Machine-readable invariants and AI review policy.
- [x] Workload/memory/evidence contracts.
- [x] Minimal Rust CLI skeleton.
- [x] Merge PR #1 only with green contract/Rust CI.
- [x] Prepare the v0.1.0 constitutional release manifest, notes, and machine preflight.

## Phase 1 — deterministic dual-executor proof
- [x] MESH-owned synthetic deterministic bring-up workload.
- [x] CPU executor.
- [ ] Experimental NVIDIA accelerator executor.
- [ ] Static CPU/GPU partition only.
- [ ] Concurrent execution.
- [x] Deterministic reduction independent of completion order.
- [x] Canonical parity and receipt.
- [x] No adaptive scheduling.

## Phase 2 — GALAXY adapter
- [x] Adapter contract without copying GALAXY semantics into MESH.
- [x] Logical-ID range partitioning and executor-local regeneration requests.
- [x] Compact partial reductions.
- [ ] Exact GALAXY oracle parity.
  - [x] Frozen v0.4.0 authority and archived CPU oracle checksums are pinned exactly.
  - [ ] Live partitioned parity requires a GALAXY-owned range entrypoint.
- [ ] CPU-only/GPU-only/heterogeneous baselines.
  - [x] Archived CPU-only evidence is bound and static requested baseline geometries are defined.
  - [ ] GPU-only and heterogeneous execution evidence require the real Phase 1 accelerator executor.

## Phase 3 — memory broker
- [ ] Persistent accelerator allocation pool.
  - [x] Persistent accelerator-local pool planning, lifetime, and reuse contract.
  - [ ] Physical accelerator allocation requires the real accelerator executor.
- [ ] Bounded pinned-host staging.
  - [x] Bounded staging plan, peak-live enforcement, and reuse contract.
  - [ ] Physical OS-backed pinned allocation remains backend-owned.
- [x] Explicit transfer/event graph.
- [x] Memory-plan receipts.
- [ ] Stream/reduce/discard where permitted.
  - [x] Constant-size reusable stream/reduce/discard planning template.
  - [ ] Runtime execution remains gated on a physical backend.

## Phase 4 — calibrated planning
- [ ] Measure CPU/GPU service and setup/transfer costs.
- [ ] Topology-derived bounded candidate plans.
- [ ] Deterministic search and full-work confirmation.
- [ ] Keep canonical on near ties.

## Phase 5 — adaptive heterogeneous runtime
Deferred: dynamic work stealing, NUMA placement, multi-GPU, peer memory, managed-memory experiments, phase-sensitive replanning, persistent calibration cache.
