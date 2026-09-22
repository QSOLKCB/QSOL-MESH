# QSOL-MESH Static CPU/CUDA Partition

This stage implements the next Phase 1 rung after the single-device CUDA executor: one **fixed**, contiguous CPU/CUDA split for `mesh-smoke-v1`.

It deliberately does not implement concurrent execution or adaptive scheduling.

## Fixed geometry

The caller supplies:

```text
items
cpu_items
cpu_workers
device_ordinal
```

The partition is then immutable for the run:

```text
CPU  : [0, cpu_items)
CUDA : [cpu_items, items)
```

Both partitions must be nonempty. The ranges are contiguous, non-overlapping, and cover the complete workload exactly.

There is no percentage heuristic, hardware-name policy, calibration decision, dynamic work stealing, or phase-sensitive rebalancing.

## Execution order

The current runtime executes:

```text
1. CPU prefix
2. CUDA suffix
3. deterministic partition-order reduction
4. full scalar-oracle verification
```

The receipt explicitly records:

```json
"concurrent": false,
"adaptive": false
```

Concurrent CPU/GPU execution is the next roadmap rung and is not claimed by this stage.

## Range-native executors

The CPU executor now supports `run_smoke_range(start, items, workers)`, with each range independently checked against `smoke_reference_range(start, items)`.

The canonical CUDA worker now accepts an optional `--start` and emits a distinct strict protocol for range execution:

```text
qsol.mesh.cuda-smoke-range-worker.v1
```

A CUDA range is admitted only if:

- start and length match the request;
- `start + items` is representable in `u64`;
- canonical worker provenance passes;
- launch geometry and CUDA runtime/device observations are present;
- the CUDA partial exactly equals the scalar range oracle.

The full CUDA worker protocol remains available for the existing `smoke-cuda` command.

## Run

After building the canonical CUDA worker:

```sh
bash scripts/build-cuda-helper.sh
```

run a fixed split:

```sh
mesh run smoke-static \
  --items 100000 \
  --cpu-items 40000 \
  --cpu-workers 8 \
  --device 0 \
  --json
```

Verification uses the same physical execution path:

```sh
mesh verify smoke-static \
  --items 100000 \
  --cpu-items 40000 \
  --cpu-workers 8 \
  --device 0 \
  --json
```

`--cpu-items` is required so the static placement decision is explicit rather than inferred.

## Verification

The run fails closed unless all three checks pass:

1. CPU partial equals the scalar oracle for `[0, cpu_items)`;
2. CUDA partial equals the scalar oracle for `[cpu_items, items)`;
3. their wrapping-`u64` partition-order reduction equals the full scalar oracle.

A CUDA error does not fall back to CPU execution.

## Evidence boundary

Default GitHub CI has no retained CUDA-capable execution evidence, so CI does not claim that a heterogeneous run occurred.

CI can still validate:

- CPU range execution and stable range vectors;
- fixed partition geometry;
- deterministic reduction;
- CUDA range protocol parsing and range-oracle admission;
- source/contract requirements;
- CLI fail-closed behavior when the canonical CUDA worker is absent.

A retained static heterogeneous execution receipt remains a CUDA-host evidence task, separate from implementation correctness.
