# GALAXY adapter boundary

Phase 2 begins with a deliberately narrow semantic firewall.

MESH owns:

- contiguous half-open logical-ID range geometry;
- requested placement of those ranges;
- executor-local regeneration requests;
- compact range-bound partial checksums;
- deterministic reduction after reordering by logical range;
- exact comparison against a workload-owned oracle;
- execution evidence.

GALAXY owns everything that turns a logical ID into a particle contribution: addressing, random lanes, physical parameters, projection math, and accelerator kernels. None of those implementations are copied into QSOL-MESH.

## Frozen authority

The initial adapter contract is bound to GALAXY v0.4.0 commit:

`6f17a734b9241359d36a9bf3d208b8527a456327`

and CPU-runtime blob:

`b12220565f6059482f706d46db1d9d2c29a9cc82`.

The archived qBraid evidence at GALAXY commit
`b9e61d20d0fe0fa99f302a2ed13aa1215a60c5f3` records the 8,388,608-resident,
8-frame, seed-303 oracle checksums:

- Float: `adf6d6e30d3ad26d`
- BAM-LUT: `8d6f07bd77e2fc16`

MESH pins those as upstream evidence. It does not derive them independently.

## Range protocol

A MESH regeneration request carries only:

`logical_population, range_start, range_end, frames, seed`

The range is a non-empty half-open interval `[start, end)`. Ranges must form a
complete, gap-free, non-overlapping cover of the requested logical population.

A GALAXY-owned executor is responsible for regenerating the semantic state for
that range locally and returning one compact partial:

`range_start, range_end, checksum`

MESH may receive partials in any completion order. It sorts them by
`range_start`, revalidates exact coverage, and then performs the workload-declared
wrapping-u64 reduction. Gaps, overlaps, empty ranges, out-of-domain ranges, and
oracle mismatches fail closed.

## Baseline status

MESH can now construct static requested geometries for CPU-only,
accelerator-only, and 50/50 heterogeneous execution. Those are plans, not
execution evidence.

The archived GALAXY CPU result is bound as evidence. Live partitioned GALAXY
parity and real accelerator/heterogeneous baselines remain gated on two concrete
prerequisites:

1. a GALAXY-owned range entrypoint that accepts the adapter request without
   moving GALAXY semantics into MESH;
2. the real accelerator executor from Phase 1.

Until those exist, QSOL-MESH must not label a requested accelerator plan as an
executed GPU baseline.
