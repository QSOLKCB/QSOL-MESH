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
  - [x] Retained execution receipt from a CUDA-capable host.
- [x] Static CPU/GPU partition only.
  - [x] Caller-fixed contiguous CPU prefix + CUDA suffix with range-native execution.
  - [x] Per-partition range-oracle verification and full scalar-oracle reduction.
  - [x] Retained static heterogeneous execution receipt from a CUDA-capable host.
- [x] Concurrent execution.
  - [x] CPU range task is spawned before canonical CUDA range dispatch and joined only after CUDA returns.
  - [x] Deterministic CPU→CUDA reduction remains independent of completion order.
  - [x] Retained concurrent heterogeneous execution receipt from a CUDA-capable host.
  - [ ] Kernel-level overlap measurement remains outside this bring-up rung.
- [x] Deterministic reduction independent of completion order.
- [x] Canonical parity and receipt.
- [x] No adaptive scheduling.

## Phase 2 — GALAXY adapter
- [x] Adapter contract without copying GALAXY semantics into MESH.
- [x] Logical-ID range partitioning and executor-local regeneration requests.
- [x] Compact partial reductions.
- [x] Exact GALAXY oracle parity.
  - [x] Frozen v0.4.0 authority and archived CPU oracle checksums are pinned exactly.
  - [x] Live partitioned parity through GALAXY's merged CPU range entrypoint, including the archived frozen checksum.
- [ ] CPU-only/GPU-only/heterogeneous baselines.
  - [x] Archived and live CPU-only evidence are bound; static requested baseline geometries are defined.
  - [ ] GPU-only and heterogeneous execution evidence require a GALAXY-owned accelerator path plus retained CUDA-host evidence.

## Phase 3 — memory broker
- [x] Persistent accelerator allocation pool.
  - [x] Persistent accelerator-local pool planning, lifetime, and reuse contract.
  - [x] Bounded CUDA stream worker allocates its device input and partial buffers once per run and reuses them across chunks.
  - [x] Retained CUDA-host evidence of physical pool allocation and reuse.
- [x] Bounded pinned-host staging.
  - [x] Bounded staging plan, peak-live enforcement, and reuse contract.
  - [x] CUDA-owned pinned staging and compact partial buffers are allocated once under explicit physical budgets.
  - [x] Retained CUDA-host evidence of OS/CUDA-backed pinned staging.
- [x] Explicit transfer/event graph.
- [x] Memory-plan receipts.
- [x] Stream/reduce/discard where permitted.
  - [x] Constant-size reusable stream/reduce/discard planning template.
  - [x] Separate smoke CUDA worker implements ordered upload, kernel, compact download, host reduction, and discard per chunk.
  - [x] Retained CUDA-host runtime streaming and scalar-oracle receipt.

## Phase 4 — calibrated planning
- [x] Measure CPU/GPU service and setup/transfer costs.
  - [x] Real host CPU smoke service measurements with explicit cost scope.
  - [x] Versioned setup/service/transfer cost evidence fields.
  - [x] Optional CUDA timing receipt v2 separates helper latency, setup, kernel service, D2H transfer, teardown, and scalar verification with explicit clock scopes.
  - [x] Opt-in CUDA calibrator consumes verified timing v2 samples and compares CPU-only, CUDA-only, and static heterogeneous candidates with full-work confirmation.
  - [x] Retained CUDA-host calibration receipt with measured setup/service/transfer costs and full-work selection evidence.
- [x] Topology-derived bounded candidate plans.
- [x] Deterministic search and full-work confirmation.
- [x] Keep canonical on near ties.

Retained Phase 3/4 evidence: `evidence/phase3-4-cuda-host-2026-09-23/` (two host captures; canonical CPU retained).

## Phase 5 — adaptive heterogeneous runtime
- [x] Versioned bounded phase-boundary replanning over independent smoke instances.
- [x] Fresh measured selection and full-work confirmation before each selected-plan execution.
- [x] Per-phase scalar verification, ordered reduction, and receipts recording actual plan changes.
- [x] Fail closed on execution or CUDA identity mismatch without fallback or partial verified receipts.
- [ ] Retained Phase 5 CUDA-host execution receipt; Phase 3/4 captures do not satisfy this gate.

Deferred: dynamic work stealing, NUMA placement, multi-GPU, peer memory, managed-memory experiments, persistent calibration cache.
