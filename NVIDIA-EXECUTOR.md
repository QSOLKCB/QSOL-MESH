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

An alternate output path may be passed as the first build-script argument.

## Run

```sh
mesh run smoke-cuda --items 100000 --device 0 --json
```

or explicitly:

```sh
mesh verify smoke-cuda \
  --items 100000 \
  --device 0 \
  --helper target/mesh-cuda-smoke \
  --json
```

`QSOL_MESH_CUDA_HELPER` can set the default helper path.

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
