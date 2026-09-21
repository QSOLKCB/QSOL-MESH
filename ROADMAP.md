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
- [ ] Adapter contract without copying GALAXY semantics into MESH.
- [ ] Logical-ID range partitioning and local regeneration.
- [ ] Compact partial reductions.
- [ ] Exact GALAXY oracle parity.
- [ ] CPU-only/GPU-only/heterogeneous baselines.

## Phase 3 — memory broker
- [ ] Persistent accelerator allocation pool.
- [ ] Bounded pinned-host staging.
- [ ] Explicit transfer/event graph.
- [ ] Memory-plan receipts.
- [ ] Stream/reduce/discard where permitted.

## Phase 4 — calibrated planning
- [ ] Measure CPU/GPU service and setup/transfer costs.
- [ ] Topology-derived bounded candidate plans.
- [ ] Deterministic search and full-work confirmation.
- [ ] Keep canonical on near ties.

## Phase 5 — adaptive heterogeneous runtime
Deferred: dynamic work stealing, NUMA placement, multi-GPU, peer memory, managed-memory experiments, phase-sensitive replanning, persistent calibration cache.
