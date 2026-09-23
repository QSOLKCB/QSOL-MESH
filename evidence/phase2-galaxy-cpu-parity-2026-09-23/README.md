# MESH live GALAXY CPU parity, 2026-09-23

The receipts are the exact JSON payloads from the `galaxy-cpu-parity` artifact in [MESH CI run 35910900118](https://github.com/QSOLKCB/QSOL-MESH/actions/runs/35910900118), built from MESH commit `f103b838662e45b89702e86100efd958ff63c1e4` and the merged GALAXY authority commit `623c43a13c0696533164826ec71896488c7aed44`. This run supersedes the older receipts that omitted required evidence sections.

- Artifact ID: `10773395989`
- Artifact ZIP SHA-256: `c8cdc6aeb56aaaa0b193e0767dacc165a70fa6a15609d11afd3a2093fb12104c`
- `bounded.json` SHA-256: `b362a24da907f8249fe055ce3ae586b24c48ed706231d97b1e2f5bfba8b81e3a`
- `frozen.json` SHA-256: `1f26830e677b75e5d9cfda086385b5effb7b7800cd3c0c3952fbb7e8b2535ef3`

The bounded case uses logical 4096, resident 1024, 2 frames, seed 303, and 4 partitions. Its full and reduced checksum is `ffcb0799ff078917`. The frozen case uses logical `u64::MAX`, resident 8,388,608, 8 frames, seed 303, and 2 partitions. Its full and reduced checksum is `8d6f07bd77e2fc16`, equal to GALAXY's archived v0.4.0 CPU oracle.

The CI job builds both repositories with their pinned Rust toolchain and executes the MESH adapter against GALAXY's own CPU range command. These receipts establish CPU-only partition parity for this source pair and host. They do not establish GPU execution, heterogeneous GALAXY parity, physical accelerator memory allocation, or a universal performance result.
MESH records external host topology and GALAXY-owned allocation behavior as not observed, and records that no calibration was performed.
