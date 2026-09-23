# Retained CUDA streaming and calibration captures

These are unmodified user-uploaded receipts and logs from source commit
`69280c4c5d7553cf0fa17f8ddaae34f07dcceddb` on an RTX 5060 Ti host.
The first capture ran at 22:09 UTC on 2026-09-23; the second Phase 4 capture
ran at 22:11 UTC. Both used `/usr/bin/nvcc` 12.4.131, CUDA runtime 12040,
driver API 13020, NVIDIA driver 595.84, and Rust 1.85.1.

`capture-1` preserves all files from the uploaded archive. `capture-2`
preserves the separately uploaded timing, calibration, environment, and hash
files. The manifest binds every uploaded file and the original archive hash;
the retained validator pins the manifest itself and recomputes scalar oracles.
Hashes bind the supplied bytes, not an independently attested physical host.

The stream receipts cover 1,000 items in one chunk and 100,000 items in 25
chunks. The latter reports 32,776 bytes peak in each domain, one input and one
partial allocation per domain, and 75 CUDA event records.

Both calibration captures measured all four candidates and retained the
one-worker CPU plan, then confirmed 100,000 items. CUDA setup and process
costs dominate this small smoke workload. These captures establish no universal
speedup, kernel overlap, Phase 5 adaptive execution, or GALAXY GPU result.

Validate with `python3 scripts/validate-retained-phase3-4-evidence.py`.
