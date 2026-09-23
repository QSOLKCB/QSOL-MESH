# Retained Phase 5 CUDA-host capture

Captured at `2026-09-23T22:37:27Z` from implementation commit
`4ea2225658e8e2eba0a7ea91cba59b230637b200` (PR #15 before merge), using
`scripts/capture-phase5-adaptive.sh`. The subsequent merge does not change this
capture's source identity.

The uploaded `adaptive.json`, `environment.txt`, and `SHA256SUMS` bytes are
unchanged. Upload filename suffixes `(1)` were removed from the environment and
hash-list filenames to restore the names used inside `SHA256SUMS`. The added
`manifest.json` binds all three files; the retained validator pins its digest.

Environment: NVIDIA GeForce RTX 5060 Ti, 32 available CPU workers, Rust 1.85.1,
NVCC `/usr/bin/nvcc` 12.4.131, driver 595.84. Nested receipts report compute
capability 12.0, CUDA runtime 12040 and driver API 13020 consistently.

| Phase | Items | Selected execution | Execution and verification (ms) |
| --- | ---: | --- | ---: |
| 0 | 1,000 | CPU, one worker | 0.06447 |
| 1 | 100,000 | CPU, one worker | 0.32414 |
| 2 | 10,000 | CPU, one worker | 0.08315 |

Each phase measured all four candidates (CPU with one worker, CPU with 32
workers, CUDA-only, and static heterogeneous), confirmed the canonical CPU plan
on full work, then executed that plan separately. All calibration and execution
checksums match the independent scalar oracle. The phase-order wrapping-u64
aggregate is `edb20cb973a5c7e7`. Logical IDs restart at zero for each phase.

Total calibration wall time: 4.130932972 seconds. Total selected execution plus
phase verification: 0.47176 milliseconds. CPU was the lowest-cost candidate in
every phase; the historical receipt's generic
`canonical-kept-after-calibration-near-tie` label does not establish an actual
near tie in these measurements.

This capture closes the Phase 5 CUDA-host receipt gate. It records zero plan
changes and zero CUDA items in selected phase execution. CUDA was exercised in
calibration; this is not evidence of selected CUDA phase execution, hardware
plan transitions, kernel overlap, a persistent CUDA context, or speedup.
Hash integrity and scalar parity do not independently attest physical hardware
or binary provenance. CI validates the retained record without running CUDA.

Validation:

```sh
python3 scripts/validate-retained-phase5-evidence.py
python3 scripts/test-retained-phase5-evidence.py
```
