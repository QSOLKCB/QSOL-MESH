# Retained full CUDA-host evidence — 2026-09-27

This directory retains a fresh end-to-end hardware evidence capture for QSOL-MESH from clean source commit `838e725f687888f55000f045b4a6846a46b10413` on 2026-09-27.

The capture was produced on an AMD Ryzen 9 5950X host with an NVIDIA GeForce RTX 5060 Ti (16,311 MiB), NVIDIA driver 595.84, CUDA 12.4 compiler tooling, and the repository-pinned Rust 1.85.1 toolchain. The uploaded transport archive had SHA-256 `27f56e72cb93643354e140ef633206a1ffcc29dd53ea29093c78a65fb419a44d`; the repository retains the extracted evidence bytes rather than the archive container.

## Retained execution chain

### Phase 1 — CPU/CUDA bring-up and fixed heterogeneous execution

`phase1/` retains four verified executions of the same 100,000-item `mesh-smoke-v1` workload:

- `cpu-verify-100000.json` — CPU scalar-parity verification with 8 workers;
- `cuda-verify-100000.json` — physical single-device CUDA execution on device 0;
- `static-verify-100000-40000.json` — sequential fixed split with a 40,000-item CPU prefix and 60,000-item CUDA suffix;
- `concurrent-verify-100000-40000.json` — concurrent executor dispatch of the same fixed split.

All four receipts verify the full checksum/reference `9d390352e9b7d24c`. The static and concurrent receipts bind the CPU partition to `5adf225493d7a5bf` and the CUDA partition to `4259e0fe55e02c8d`. The concurrent receipt records `kernel_overlap_measured:false`; it does not claim measured kernel-level overlap.

### Phase 3 — bounded physical CUDA streaming

`phase3/` retains verified one-chunk and 25-chunk physical streaming receipts. Both observe CUDA execution with bounded pinned-host staging and accelerator-local allocation, exactly one reusable pinned staging allocation, exactly one reusable device pool allocation, and scalar-oracle equality.

### Phase 4 — separated CUDA timing and measured calibrated planning

`phase4/timing.json` is a verified `qsol.mesh.cuda-smoke-receipt.v2` timing receipt. Host monotonic measurements and CUDA-event kernel time remain separate; the receipt records `cross_clock_additive_total:false`.

`phase4/calibration.json` measures four bounded candidates: canonical one-worker CPU, 32-worker CPU, CUDA-only, and a static heterogeneous candidate. Every calibration observation verifies against the same scalar oracle. The canonical one-worker CPU candidate was retained after the configured near-tie rule and was reverified on the full 100,000-item workload. This is host-specific planning evidence, not a universal performance claim.

### Phase 5 — bounded phase-boundary replanning

`phase5/adaptive.json` retains a verified three-phase run for phase sizes 1,000, 100,000, and 10,000 items. CUDA candidates were admitted and measured before every phase. All three phases retained candidate 0 (canonical one-worker CPU), all three executions verified against their phase scalar oracle, and the receipt records zero plan changes and no within-phase replanning.

## Integrity and provenance

Each phase directory contains its original `environment.txt` and `SHA256SUMS`. `scripts/validate-retained-full-run-evidence.py` additionally pins the exact retained file digests and validates the semantic boundaries of every receipt in normal CPU-only CI.

The source commit is the implementation/documentation state that produced the evidence. The later commit that adds this retained evidence necessarily has a different Git identity and does not retroactively change the captured source identity.

## Claim boundary

This bundle establishes retained execution evidence for the captured host and source commit. It does **not** establish universal speedup, cryptographic host attestation, independently attested GPU telemetry, or CUDA-kernel/CPU-compute overlap. Phase 4 planner selections are measurements from this host and capture only. Phase 5 demonstrates bounded phase-boundary recalibration and verified execution, not dynamic work stealing or within-phase adaptive migration.
