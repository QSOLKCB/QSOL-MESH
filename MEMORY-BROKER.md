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

## Still capability-gated

Phase 3 is **not** claiming these physical capabilities yet:

- actual OS-backed pinned host allocation;
- actual persistent VRAM allocation;
- measured transfer completion/events;
- observed reuse across real accelerator submissions.

Those become executable only after an accelerator backend owns the physical resources and can report observed evidence.
