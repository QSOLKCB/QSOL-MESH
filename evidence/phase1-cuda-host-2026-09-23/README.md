# Retained Phase 1 CUDA-host evidence — 2026-09-23

This directory retains the minimum verified execution evidence needed to close the three CUDA-host evidence gates left open after Phase 1 implementation.

The evidence was produced from a clean checkout at source commit `58301da12f241ae823f70174a3028319abe9a36f` on an AMD Ryzen 9 5950X host with an NVIDIA GeForce RTX 5060 Ti using NVIDIA driver 595.84 and CUDA 13.2 tooling. The operator-supplied run report recorded 70 commands with no unexpected outcomes, 53 passing Rust unit tests, contract validation, formatting, clippy, and a clean source tree.

Retained receipts:

- `gpu-verify-100000.json` — verified single-device CUDA execution;
- `smoke-static-verify-100000-40000.json` — verified sequential fixed CPU/CUDA split;
- `smoke-concurrent-verify-100000-40000.json` — verified concurrent executor-call dispatch of the same fixed split.

All three receipts bind `mesh-smoke-v1` to the same full checksum/reference `9d390352e9b7d24c`. The heterogeneous receipts use 100,000 items with a 40,000-item CPU prefix and 60,000-item CUDA suffix.

## Claim boundary

This evidence establishes retained CUDA-host execution for the existing Phase 1 runtime. It does **not** establish a performance gain, cryptographic host attestation, independently attested GPU telemetry, or CUDA-kernel/CPU-compute overlap. The concurrent receipt explicitly records `kernel_overlap_measured:false`.

`scripts/validate-retained-phase1-evidence.py` verifies file digests, receipt semantics, consistent topology/geometry, the non-overlap claim boundary, contract bindings, and roadmap state in normal CPU-only CI.
