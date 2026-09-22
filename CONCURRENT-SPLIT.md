# QSOL-MESH Concurrent CPU/CUDA Execution

This stage completes the final unchecked Phase 1 implementation rung: concurrent dispatch of the fixed CPU/CUDA partition introduced in the previous stage.

The partition itself does **not** change:

```text
CPU  : [0, cpu_items)
CUDA : [cpu_items, items)
```

The caller still supplies `--cpu-items`. No calibration result, hardware model name, or adaptive policy changes the geometry.

## Dispatch model

The concurrent coordinator uses this ordering:

```text
1. validate fixed split
2. spawn CPU range task
3. invoke canonical CUDA range executor
4. wait for CUDA call to return
5. join CPU task
6. verify both range partials
7. reduce in CPU -> CUDA partition order
8. verify full scalar oracle
```

The important distinction is that the CPU task is not joined before CUDA dispatch. Therefore the CPU executor call and CUDA executor call are concurrently dispatched.

## Claim boundary

This stage does **not** claim that the CUDA kernel interval itself was measured to overlap the CPU compute interval.

The receipt records:

```json
{
  "concurrent_dispatch": true,
  "adaptive": false,
  "dispatch_contract": {
    "cpu_task_spawned_before_cuda_call": true,
    "cpu_joined_after_cuda_call_return": true,
    "kernel_overlap_measured": false
  }
}
```

That is intentionally narrower than a timing or performance claim.

## Run

After building the canonical CUDA worker:

```sh
bash scripts/build-cuda-helper.sh
```

run:

```sh
mesh run smoke-concurrent \
  --items 100000 \
  --cpu-items 40000 \
  --cpu-workers 8 \
  --device 0 \
  --json
```

or:

```sh
mesh verify smoke-concurrent \
  --items 100000 \
  --cpu-items 40000 \
  --cpu-workers 8 \
  --device 0 \
  --json
```

## Determinism

Concurrency changes dispatch, not workload semantics.

The reduction is always:

```text
wrapping_u64(cpu_partial + cuda_partial)
```

in fixed CPU -> CUDA partition order regardless of which executor finishes first.

Both partition partials must independently pass their range oracles before reduction, and the final checksum must pass the full scalar reference.

## Failure semantics

CUDA failure is not converted into CPU-only success. The CPU task is joined for clean lifecycle handling, but the CUDA error is still propagated and no verified heterogeneous receipt is emitted.

CPU thread panic or CPU range failure also fails the run.

## CI boundary

The generic dispatch primitive is unit-tested without requiring a GPU: the CPU test closure waits for a signal that only the CUDA closure can send. This proves the CUDA closure is invoked while the CPU task is still live.

Default GitHub CI still has no retained CUDA-capable execution evidence. It can validate the scheduler, contracts, deterministic reduction, and missing-worker fail-closed behavior, but it cannot claim measured CUDA kernel overlap or retained concurrent heterogeneous execution evidence.
