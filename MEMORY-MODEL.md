# QSOL-MESH Memory Model

Initial explicit memory domains:

```text
host-pageable
host-pinned
accelerator-local
```

Rules:

- every managed allocation has explicit ownership and lifetime;
- every transfer names source, destination, bytes, and lifetime;
- pinned host memory is bounded transport memory, not replacement RAM;
- accelerator-local memory is not interchangeable with host RAM;
- future unified/managed addressing does not erase physical placement/transfer cost;
- the same physical storage may not be double-counted as capacity;
- prefer local deterministic regeneration over bulk transfer when the workload proves equivalence;
- prefer stream/reduce/discard when permitted;
- memory optimization may not weaken verification;
- peak-live memory and cumulative allocation traffic are different metrics.
