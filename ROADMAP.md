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
- [x] Experimental NVIDIA accelerator executor.
  - [x] Real single-device CUDA smoke kernel/helper and Rust launcher.
  - [x] Requested/observed/effective CUDA receipt with exact scalar-oracle verification.
  - [ ] Retained execution receipt from a CUDA-capable host.
- [x] Static CPU/GPU partition only.
  - [x] Caller-fixed contiguous CPU prefix + CUDA suffix with range-native execution.
  - [x] Per-partition range-oracle verification and full scalar-oracle reduction.
  - [ ] Retained static heterogeneous execution receipt from a CUDA-capable host.
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
  - [ ] GPU-only and heterogeneous execution evidence require a GALAXY-owned accelerator path plus retained CUDA-host evidence.

## Phase 3 — memory broker
- [ ] Persistent accelerator allocation pool.
  - [x] Persistent accelerator-local pool planning, lifetime, and reuse contract.
  - [ ] Physical persistent pool is not provided by the single-checksum CUDA worker.
- [ ] Bounded pinned-host staging.
  - [x] Bounded staging plan, peak-live enforcement, and reuse contract.
  - [ ] Physical OS/CUDA-backed pinned staging remains backend-owned.
- [x] Explicit transfer/event graph.
- [x] Memory-plan receipts.
- [ ] Stream/reduce/discard where permitted.
  - [x] Constant-size reusable stream/reduce/discard planning template.
  - [ ] Runtime streaming execution remains a later executor rung.

## Phase 4 — calibrated planning
- [ ] Measure CPU/GPU service and setup/transfer costs.
  - [x] Real host CPU smoke service measurements with explicit cost scope.
  - [x] Versioned setup/service/transfer cost evidence fields.
  - [ ] CUDA executor timing/setup/transfer measurement has not yet been integrated into the calibrator.
- [x] Topology-derived bounded candidate plans.
- [x] Deterministic search and full-work confirmation.
- [x] Keep canonical on near ties.

## Phase 5 — adaptive heterogeneous runtime
Deferred: dynamic work stealing, NUMA placement, multi-GPU, peer memory, managed-memory experiments, phase-sensitive replanning, persistent calibration cache.
