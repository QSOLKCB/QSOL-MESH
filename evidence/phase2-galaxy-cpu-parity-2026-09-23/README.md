# MESH live GALAXY CPU parity, 2026-09-23

The receipts are the exact JSON payloads from the `galaxy-cpu-parity` artifact in [MESH CI run 35907825394](https://github.com/QSOLKCB/QSOL-MESH/actions/runs/35907825394), built from MESH commit `d2db65897481d76f0117f0de0ad069e8a72186b4` and the merged GALAXY authority commit `623c43a13c0696533164826ec71896488c7aed44`.

- Artifact ID: `10771876789`
- Artifact ZIP SHA-256: `699d9e10d5c65c1571e5272543f581f6a87d35d0cdaf6db821292fa6cf872356`
- `bounded.json` SHA-256: `3e525d2d083613fa2803d0179cbe8b7a1c6d17a8e02d7b098823da4298c332d2`
- `frozen.json` SHA-256: `5305c828579dd2cc8c4e200bc0645429b33d86ad6d11bb3b4da259c4f38b1090`

The bounded case uses logical 4096, resident 1024, 2 frames, seed 303, and 4 partitions. Its full and reduced checksum is `ffcb0799ff078917`. The frozen case uses logical `u64::MAX`, resident 8,388,608, 8 frames, seed 303, and 2 partitions. Its full and reduced checksum is `8d6f07bd77e2fc16`, equal to GALAXY's archived v0.4.0 CPU oracle.

The CI job builds both repositories with their pinned Rust toolchain and executes the MESH adapter against GALAXY's own CPU range command. These receipts establish CPU-only partition parity for this source pair and host. They do not establish GPU execution, heterogeneous GALAXY parity, physical accelerator memory allocation, or a universal performance result.
