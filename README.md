# QSOL-MESH

**Heterogeneous compute and memory runtime that calibrates real CPU/GPU silicon, plans workload placement across system RAM and VRAM, and executes deterministic workloads across both.**

MESH separates workload meaning from execution placement. A workload defines what must be computed and how correctness is verified. MESH may decide where, when, and how work executes, but may not redefine the workload.

Initial CLI: `mesh inspect`, `mesh calibrate`, `mesh plan`, `mesh run`, `mesh verify`, `mesh receipt`.

Human-readable explanations live at the repository root. Normative automated-agent authority lives under `machine/`.

## Local build and run

Run these commands from the **QSOL-MESH repository root**.

> **Do not install Ubuntu's suggested `mesh` snap.** It is unrelated to QSOL-MESH. The QSOL-MESH `mesh` command is the Rust binary built from `crates/mesh-cli`.

### Prerequisites

QSOL-MESH pins Rust `1.85.1` in `rust-toolchain.toml`. Confirm the Rust toolchain first:

```sh
rustc --version
cargo --version
```

For NVIDIA CUDA execution, also confirm that the NVIDIA driver and CUDA compiler are available:

```sh
nvidia-smi
nvcc --version
```

The CPU path does not require CUDA. The CUDA paths require a CUDA-capable NVIDIA GPU and `nvcc`.

### Build the Rust CLI

From the repository root:

```sh
cargo build --release -p qsol-mesh-cli
```

The resulting QSOL-MESH executable is:

```text
target/release/mesh
```

Running it without arguments prints the supported command list:

```sh
./target/release/mesh
```

### Build the verified CUDA helper

On a CUDA-capable host:

```sh
bash scripts/build-cuda-helper.sh
```

The helper is deliberately written to:

```text
target/mesh-cuda-smoke
```

Do not rename or relocate this helper for verified CUDA execution. The verified launcher resolves the canonical worker relative to the built application's `target` directory, and caller-selected helper overrides are intentionally not admitted.

You can confirm both binaries exist with:

```sh
test -x target/release/mesh && echo "mesh CLI: OK"
test -x target/mesh-cuda-smoke && echo "CUDA helper: OK"
```

The CUDA helper is an internal worker rather than the user-facing CLI. Running `target/mesh-cuda-smoke` by itself without its required worker arguments will therefore report an argument error; normally invoke it through `mesh`.

### Run the CUDA smoke workload

Use the repo-built release executable:

```sh
./target/release/mesh run smoke-cuda \
  --items 100000 \
  --device 0 \
  --json
```

A successful run emits a CUDA smoke receipt whose verification section contains matching `checksum` and `reference` values and:

```json
"verified": true
```

### Verify the CUDA smoke workload

```sh
./target/release/mesh verify smoke-cuda \
  --items 100000 \
  --device 0 \
  --json
```

This independently checks the CUDA result against the scalar smoke oracle. A successful receipt reports observed NVIDIA CUDA topology and `"verified":true`.

### Optional timing receipt

Timing evidence is opt-in:

```sh
./target/release/mesh verify smoke-cuda \
  --items 100000 \
  --device 0 \
  --timing \
  --json
```

The timing receipt keeps host timing, CUDA event timing, and scalar verification timing as distinct measurements rather than combining them into a synthetic total.

### CPU-only smoke test

CUDA is not required for the baseline CPU workload:

```sh
./target/release/mesh inspect --json

./target/release/mesh run smoke \
  --items 100000 \
  --workers 8 \
  --json

./target/release/mesh verify smoke \
  --items 100000 \
  --workers 8 \
  --json
```

### Run through Cargo during development

For CPU commands, or when developing the Rust CLI, Cargo can invoke the binary directly:

```sh
cargo run --release -p qsol-mesh-cli -- inspect --json

cargo run --release -p qsol-mesh-cli -- \
  run smoke \
  --items 100000 \
  --workers 8 \
  --json
```

For verified CUDA execution, prefer `./target/release/mesh` after building both the CLI and canonical CUDA helper as shown above so executable-relative helper resolution remains explicit.

### Minimal CUDA bring-up sequence

For a fresh checkout on an already configured CUDA host, the complete sequence is:

```sh
cargo build --release -p qsol-mesh-cli
bash scripts/build-cuda-helper.sh

./target/release/mesh run smoke-cuda \
  --items 100000 \
  --device 0 \
  --json

./target/release/mesh verify smoke-cuda \
  --items 100000 \
  --device 0 \
  --json
```

If both CUDA commands finish with receipts containing `"verified":true`, the local CUDA smoke execution and scalar-reference verification gates passed for that run.

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

This stage is deliberately **sequential**: CPU runs first, CUDA second, and receipts state `"concurrent":false` and `"adaptive":false`. The concurrent-dispatch path is documented in the following section.

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

This is **planning evidence only**. The plan hard-fails if it attempts to claim physical materialization. The separate experimental CUDA worker below owns physical allocations; its execution evidence remains gated on a CUDA-host run.

See `MEMORY-BROKER.md` and `machine/memory-plan-contract.v1.json`.

A separate experimental `mesh verify smoke-stream` path now implements bounded
CUDA-owned pinned staging, reusable device allocation, and ordered compact
reductions for the synthetic smoke workload. Its physical execution claim
requires a CUDA-host run; see `MEMORY-BROKER.md` and
`machine/cuda-stream-contract.v1.json` for the executable contract and capture
command. The existing `mesh plan memory` receipt remains planning-only.


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

Default calibrated planning remains CPU-only. On a CUDA host, opt in to measured CPU, CUDA-only, and static CPU/CUDA candidate selection:

```sh
mesh calibrate smoke --cuda --device 0 --calibration-items 10000 --full-items 100000 --repeats 3 --json
```

The v2 calibrator consumes verified timing measurements, uses setup and transfer costs from the same median host-time sample, and confirms a noncanonical winner on full work. CUDA event time is not added to host costs. Two physical CUDA calibration captures are retained under `evidence/phase3-4-cuda-host-2026-09-23/`, along with physical streaming receipts; both calibrations selected the canonical CPU plan. Run `bash scripts/capture-phase4-cuda-calibration.sh phase4-cuda-evidence` on a CUDA host to capture timing and calibration receipts with compiler metadata and hashes.

See `CALIBRATED-PLANNING.md` and `machine/calibrated-plan-contract.v2.json` (opt-in CUDA) or `machine/calibrated-plan-contract.v1.json` (default CPU).


## Phase 5 bounded phase-boundary runtime

`mesh verify smoke-phases --phase-items 1000,100000,10000 --repeats 3 --json`
remeasures, selects, executes, and scalar-verifies a plan at each declared phase
boundary. Add `--cuda --device 0` to admit measured CUDA and static heterogeneous
candidates. Every phase restarts smoke IDs at zero; results reduce in phase order.

The runtime admits at most 64 phases and 31 repeats, keeps canonical on near
ties, and fails on execution or CUDA identity mismatch. Receipts embed per-phase
calibration evidence and actual execution results. Existing Phase 3/4 captures
do not claim Phase 5 hardware execution. A separate Phase 5 capture is now
retained under `evidence/phase5-cuda-host-2026-09-23/`: every phase measured CUDA
candidates and selected CPU execution, with zero plan changes. Its local capture
script is `scripts/capture-phase5-adaptive.sh`. See `PHASE-RUNTIME.md`.

### Retained full-chain CUDA-host evidence

A fresh full-chain hardware capture from source commit `838e725f687888f55000f045b4a6846a46b10413` is retained under `evidence/full-cuda-host-2026-09-27/`. It covers CPU and single-device CUDA parity, fixed sequential and concurrent CPU/CUDA execution, bounded physical CUDA streaming, separated timing and CUDA-aware calibration, and the three-phase bounded runtime. Every retained execution receipt is verified; the Phase 4 and Phase 5 planners retained the canonical one-worker CPU candidate on this host.

The bundle is integrity-pinned and semantically validated by `scripts/validate-retained-full-run-evidence.py` in normal CI. It remains host-specific evidence and does not claim universal speedup, independently attested GPU telemetry, cryptographic host attestation, or measured CUDA-kernel/CPU-compute overlap.
