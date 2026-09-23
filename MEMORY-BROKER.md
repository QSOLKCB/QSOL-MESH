# QSOL-MESH Memory Broker

Phase 3 begins at the **auditable planning boundary**. The broker can describe exactly what memory would exist, where it belongs, how long it lives, and which transfers/events connect it, without pretending that a backend has physically materialized those resources.

## What the broker owns now

The first memory-plan implementation provides:

- explicit `host-pageable`, `host-pinned`, and `accelerator-local` domains;
- allocation roles with byte extents and event-bounded lifetimes;
- a topologically ordered transfer/event graph;
- bounded host-pinned and accelerator-local plan budgets;
- reusable staging and accelerator-pool **plan** allocations;
- a constant-size `stream-reduce-discard-template-v1`;
- peak-live byte accounting per domain;
- machine-readable memory-plan receipts;
- fail-closed structural validation.

For a logical byte extent of any size, including `u64::MAX`, MESH records one reusable template and a `chunk_count`. It does not allocate one graph node, transfer record, or buffer description per chunk.

## Plan versus physical memory

This distinction is mandatory:

```text
planned host-pinned allocation != physically pinned host pages
planned accelerator-local pool != allocated VRAM
requested transfer             != observed transfer
```

The Phase 3 planning layer therefore hard-codes:

```text
physically_materialized = false
```

and rejects a plan that attempts to claim otherwise.

Physical host pinning remains backend-owned. Physical accelerator allocation remains gated on the real Phase 1 accelerator executor.

## Streaming template

The current reusable template is:

```text
source-ready
    |
    v
stage-host-pinned
    |
    v
upload-accelerator
    |
    v
execute
    |
    v
download-partial
    |
    v
reduce
    |
    v
discard
```

The host-pinned staging buffer and accelerator-local pool are planned for reuse across chunks. Only the compact partial result is returned for reduction.

The effective chunk size is bounded by all of:

- total remaining logical byte extent;
- requested chunk bytes;
- declared host-pinned limit;
- declared accelerator-local limit.

## CLI

A planning receipt can be produced without allocating the described memory:

```sh
mesh plan memory \
  --total-bytes 1073741824 \
  --chunk-bytes 67108864 \
  --pinned-limit-bytes 67108864 \
  --accelerator-limit-bytes 268435456 \
  --partial-bytes 24 \
  --json
```

The result is a `qsol.mesh.memory-plan-receipt.v1` receipt with the existing evidence sections plus the explicit memory graph and peak-live accounting.

## Planning receipt boundary

The v1 planning receipt does **not** claim these physical capabilities:

- actual OS-backed pinned host allocation;
- actual persistent VRAM allocation;
- measured transfer completion/events;
- observed reuse across real accelerator submissions.

The separate CUDA executor below owns the resources. Its retained host
execution receipts now close the roadmap's Phase 3 physical gates.

## Experimental physical CUDA stream rung

The planning-only `mesh plan memory` receipt above remains unchanged. A separate
`mesh verify smoke-stream` command uses a CUDA-owned worker for the versioned
`mesh-smoke-stream-v1` workload. It retains the procedural smoke checksum
arithmetic and scalar oracle, but explicitly permits bounded per-item staging
under `machine/workloads/smoke-stream-v1.json`. Only `verify` is admitted.
It allocates one pinned input buffer, one pinned 8-byte partial,
one device input buffer, and one device 8-byte partial. All four buffers and
three CUDA events are reused for every chunk and released before a receipt is
reported. The worker stages logical IDs, uploads them on a single CUDA stream,
executes the device checksum kernel, downloads one compact partial, waits for
completion, reduces in chunk order, and discards the staged IDs.

The effective chunk count is bounded by the requested chunk, both declared
memory budgets (including the 8-byte partial per domain), and platform pointer
capacity. Rust rejects any worker report that differs from the requested
geometry or exceeds either budget, then compares the final checksum to the
independent scalar smoke oracle. CUDA topology and physical allocation counts
are helper-reported rather than independently attested.

On a CUDA host:

```sh
bash scripts/build-cuda-stream-helper.sh
cargo build --release --locked -p qsol-mesh-cli
target/release/mesh verify smoke-stream --items 100000 --chunk-items 4096 \
  --pinned-limit-bytes 32776 --accelerator-limit-bytes 32776 --device 0 --json
```

Use `bash scripts/capture-phase3-cuda-stream.sh phase3-cuda-evidence` on a clean
checkout to retain one-chunk and multi-chunk receipts, environment, and hashes.
The capture resolves `NVCC` (or `nvcc` on PATH) once and records the same compiler
executable and version used to build the helper.
The roadmap's physical execution evidence boxes remain open until those
receipts are captured and independently checked on a CUDA-capable host. The
versioned physical contract is `machine/cuda-stream-contract.v1.json`.

Retained single-chunk and 25-chunk physical CUDA captures are now available in
`evidence/phase3-4-cuda-host-2026-09-23/` and checked by
`scripts/validate-retained-phase3-4-evidence.py`. These cover allocation and
reuse within one stream-worker run, not a cross-process persistent CUDA pool.
