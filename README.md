# QSOL-MESH

**Heterogeneous compute and memory runtime that calibrates real CPU/GPU silicon, plans workload placement across system RAM and VRAM, and executes deterministic workloads across both.**

MESH separates workload meaning from execution placement. A workload defines what must be computed and how correctness is verified. MESH may decide where, when, and how work executes, but may not redefine the workload.

Initial CLI: `mesh inspect`, `mesh calibrate`, `mesh plan`, `mesh run`, `mesh verify`, `mesh receipt`.

Human-readable explanations live at the repository root. Normative automated-agent authority lives under `machine/`.

## Phase 1 CPU and CUDA bring-up

The first executable workload is deliberately tiny and dependency-free on the CPU path:

```sh
mesh inspect --json
mesh run smoke --items 100000 --workers 8 --json
mesh verify smoke --items 100000 --workers 8 --json
```

`mesh-smoke-v1` procedurally maps logical IDs to integer values, partitions only contiguous ranges, reduces worker partials in worker-index order, and verifies every run against the scalar reference. It is correctness scaffolding, not a performance benchmark.

An experimental single-device NVIDIA CUDA executor is now also available. Build its real CUDA worker on a CUDA-capable host with:

```sh
bash scripts/build-cuda-helper.sh
```

Then run or verify the same smoke workload on device 0:

```sh
mesh run smoke-cuda --items 100000 --device 0 --json
mesh verify smoke-cuda --items 100000 --device 0 --json
```

The Rust launcher does not accept a requested GPU as evidence by itself. It requires a successful CUDA helper process, observed CUDA runtime/device metadata, exact request matching, and checksum equality with the independently computed scalar smoke oracle before emitting `verified:true`. Default GitHub CI does not claim CUDA execution because it has no retained CUDA-capable runner evidence.

See `NVIDIA-EXECUTOR.md` and `machine/nvidia-executor-contract.v1.json`.

### Static CPU/CUDA partition

The next Phase 1 rung uses one caller-fixed split of the same logical smoke domain:

```sh
mesh run smoke-static \
  --items 100000 \
  --cpu-items 40000 \
  --cpu-workers 8 \
  --device 0 \
  --json
```

The geometry is explicit and immutable for the run: CPU executes `[0,cpu_items)`, CUDA executes `[cpu_items,items)`. Both ranges are verified independently against scalar range oracles, then reduced in partition order and checked against the full scalar oracle.

This stage is deliberately **sequential**: CPU runs first, CUDA second, and receipts state `"concurrent":false` and `"adaptive":false`. Concurrent CPU/GPU execution remains the next roadmap rung.

See `STATIC-SPLIT.md` and `machine/static-split-contract.v1.json`.

### Concurrent CPU/CUDA dispatch

The final Phase 1 implementation rung keeps the same fixed split but dispatches the CPU range task before invoking the canonical CUDA range executor:

```sh
mesh run smoke-concurrent \
  --items 100000 \
  --cpu-items 40000 \
  --cpu-workers 8 \
  --device 0 \
  --json
```

The CPU task is joined only after the CUDA executor call returns. Reduction remains deterministic in CPU→CUDA partition order, so completion order cannot alter the checksum.

The receipt deliberately says `"kernel_overlap_measured":false`. This stage establishes concurrent executor dispatch; it does not claim measured CUDA-kernel/CPU-compute overlap or performance gain.

See `CONCURRENT-SPLIT.md` and `machine/concurrent-split-contract.v1.json`.

### Retained CUDA-host Phase 1 evidence

The three CUDA-host evidence gates left open by the implementation PRs are now backed by retained verify receipts produced from clean source commit `58301da12f241ae823f70174a3028319abe9a36f` on 2026-09-23. The retained bundle covers single-device CUDA execution, the fixed sequential CPU/CUDA split, and concurrent executor-call dispatch of the same fixed split.

The retained concurrent receipt still records `kernel_overlap_measured:false`. This evidence closes the execution-receipt gates only; it does not claim kernel-level overlap, a performance gain, independently attested GPU telemetry, or cryptographic host attestation.

See `evidence/phase1-cuda-host-2026-09-23/README.md` and `scripts/validate-retained-phase1-evidence.py`.

## Phase 2 GALAXY adapter boundary

The first external adapter now has a machine-readable contract plus reusable range/reduction primitives. MESH can split a GALAXY logical population into complete half-open ranges, emit executor-local regeneration requests, accept compact range-bound `u64` partials in any completion order, validate exact coverage, reduce deterministically, and fail closed on oracle disagreement.

GALAXY remains the semantic authority. QSOL-MESH contains no copied GALAXY address mixer, particle generation, physics, projection math, or GPU kernels.

The adapter pins the frozen GALAXY v0.4.0 source identity and archived CPU oracle checksums. Static CPU-only, accelerator-only, and heterogeneous requested geometries are available as planning primitives, but requested accelerator placement is **not** execution evidence. Live partitioned GALAXY parity remains gated on a GALAXY-owned range entrypoint. GALAXY GPU/heterogeneous baselines additionally require a GALAXY-owned accelerator execution path and retained CUDA-host execution evidence.

See `GALAXY-ADAPTER.md` and `machine/workloads/galaxy-v0.4.0.json`.


## Phase 3 memory broker planning

The memory broker now has an auditable planning core with explicit memory domains, allocation ownership/lifetimes, a topologically ordered transfer/event graph, bounded host-pinned and accelerator-local budgets, peak-live accounting, and a reusable stream/reduce/discard template.

A plan can be emitted as a machine-readable evidence receipt:

```sh
mesh plan memory \
  --total-bytes 1073741824 \
  --chunk-bytes 67108864 \
  --pinned-limit-bytes 67108864 \
  --accelerator-limit-bytes 268435456 \
  --partial-bytes 24 \
  --json
```

This is **planning evidence only**. The plan hard-fails if it attempts to claim physical materialization. Real pinned host pages and persistent accelerator-local allocations remain backend-owned and are still gated on the real accelerator executor.

See `MEMORY-BROKER.md` and `machine/memory-plan-contract.v1.json`.


## Phase 4 calibrated planning

QSOL-MESH now has a deterministic measured planner for the executable CPU bring-up workload. Candidate plans are derived from observed topology, bounded to a fixed budget, measured against the same verified workload, and never selected from hardware model names.

```sh
mesh calibrate smoke \
  --calibration-items 10000 \
  --full-items 100000 \
  --repeats 3 \
  --near-tie-bps 500 \
  --json
```

The planner keeps the canonical one-worker plan unless another measured candidate beats it by more than the configured margin. Any noncanonical calibration winner must then repeat that win against canonical on the full requested work before promotion. Otherwise canonical is retained or restored.

Current calibrated planning remains CPU-only even though the smoke CUDA executor now exists. Accelerator `service_ns`, `setup_ns`, and `transfer_ns` measurements have not yet been integrated into the calibrator, so accelerator cost evidence remains unavailable rather than synthesized.

See `CALIBRATED-PLANNING.md` and `machine/calibrated-plan-contract.v1.json`.
