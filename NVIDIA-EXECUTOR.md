# QSOL-MESH NVIDIA CUDA Executor

This stage returns to the unfinished Phase 1 dependency that blocks accelerator evidence in Phases 2–4.

The executor is deliberately split into two pieces:

```text
qsol-mesh-cli
    |
    v
Rust CUDA launcher / protocol validator
    |
    v
mesh-cuda-smoke
    |
    v
CUDA Runtime -> NVIDIA device -> smoke kernel
```

## Real accelerator work

`accelerators/cuda/mesh_smoke_cuda.cu` is a real CUDA program. It:

- selects the requested CUDA device with `cudaSetDevice`;
- obtains observed device properties and CUDA runtime/driver versions;
- allocates an 8-byte accelerator-local checksum buffer with `cudaMalloc`;
- launches a CUDA kernel over the `mesh-smoke-v1` logical ID domain;
- performs wrapping `u64` local sums on device;
- commits those local sums with `atomicAdd`;
- synchronizes the device;
- copies the checksum back to host;
- emits one strict machine protocol line.

The kernel does **not** allocate one value per logical item.

## Build

A CUDA-capable host with `nvcc` can build the worker with:

```sh
bash scripts/build-cuda-helper.sh
```

The default output is:

```text
target/mesh-cuda-smoke
```

The verified worker is intentionally built only at `target/mesh-cuda-smoke`. Alternate output paths are rejected by the build script because caller-selected executables are not allowed to mint verified physical-execution claims.

## Run

```sh
mesh run smoke-cuda --items 100000 --device 0 --json
```

and:

```sh
mesh verify smoke-cuda \
  --items 100000 \
  --device 0 \
  --json
```

There is no verified `--helper` override and `QSOL_MESH_CUDA_HELPER` is not consulted by the verified execution path.

## Admission boundary

The Rust launcher treats worker output as untrusted until all of these pass:

1. the helper process launches successfully;
2. the helper exits successfully;
3. stdout contains exactly one valid `qsol.mesh.cuda-smoke-worker.v1` line;
4. reported item count equals the request;
5. reported device ordinal equals the request;
6. launch geometry is nonzero;
7. CUDA compute capability, runtime version, and driver version are present;
8. the reported checksum equals the independently computed `smoke_reference(items)`.

Only then can a `qsol.mesh.cuda-smoke-receipt.v1` receipt say `verified:true`.

## Evidence boundary

The worker reports CUDA topology through CUDA Runtime APIs, but that telemetry is still **helper-process-reported evidence**, not cryptographically independent hardware attestation.

Default GitHub CI has no retained CUDA execution evidence. CI validates:

- Rust protocol parsing;
- fail-closed missing-helper behavior;
- exact scalar-oracle verification;
- receipt shape and claim boundary;
- CUDA source/build-contract structure.

A real GPU execution receipt must come from a CUDA-capable host that actually runs the worker.

## Not implemented in this slice

This executor deliberately does not yet claim:

- static CPU/GPU partition execution;
- concurrent CPU/GPU execution;
- persistent accelerator pools;
- pinned-host staging;
- GALAXY GPU execution;
- accelerator calibration timings;
- multi-GPU execution.

Those are subsequent rungs after the single-device executor boundary is stable.


## Framing, provenance, and maximum-range hardening

The worker protocol permits either no line terminator, one LF, or one CRLF after the protocol record. Additional blank lines or any embedded CR/LF are rejected. This preserves the contract's single-exact-protocol-line requirement.

A verified `CudaSmokeRun` is an opaque launcher-issued value. Its provenance fields are private, and raw observation validation is internal to the accelerator module. External callers can inspect a launched run through read-only accessors, but cannot construct a receipt-capable run from a hand-built observation.

The CUDA logical-ID loop is also safe at the full admitted `u64` workload domain. After processing an ID, the kernel compares the remaining distance with the stride before incrementing. It never performs an `id += stride` that can wrap through `ULLONG_MAX` and revisit earlier IDs.


## Canonical worker provenance

A protocol line is evidence about what a process *said*, not proof that the process executed CUDA. Therefore arbitrary executables cannot enter the verified execution path even if they print a byte-for-byte valid worker record and the correct checksum.

The public verified launcher is `run_cuda_smoke(items, device)`. It invokes only the repository canonical build output at `target/mesh-cuda-smoke`. The lower-level path-taking launcher remains private to the accelerator module, and the CLI rejects `--helper` overrides before any process is launched. The environment variable `QSOL_MESH_CUDA_HELPER` is likewise ignored.

This is a repository/application trust boundary, not cryptographic binary attestation: the local filesystem and build environment are explicitly outside this contract. The guarantee here is narrower and important—**a caller-selected executable cannot mint a verified CUDA physical-execution receipt merely by forging stdout.**
