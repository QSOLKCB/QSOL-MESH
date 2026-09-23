# Bounded phase-boundary runtime

Phase 5 begins with `mesh run smoke-phases` and `mesh verify smoke-phases`.
Both execute and verify the complete sequence. Their workload authority is
`machine/workloads/smoke-phases-v1.json`, and their runtime authority is
`machine/phase-runtime-contract.v1.json`.

```sh
mesh verify smoke-phases --phase-items 1000,100000,10000 \
  --calibration-items 10000 --repeats 3 --json

# On a CUDA host after building the canonical helper:
mesh verify smoke-phases --phase-items 1000,100000,10000 \
  --calibration-items 10000 --repeats 3 --cuda --device 0 --json
```

Each phase is a separate instance of the MESH smoke calculation. Logical item
IDs restart at zero in every phase; phase sizes do not describe contiguous
pieces of one larger smoke range. The sequence result is the wrapping-u64 sum
of verified phase checksums in phase-index order. Calibration and confirmation
executions are measurements, not extra contributions to workload output.

Before each phase, the runtime takes fresh measurements using the existing v1
CPU or opt-in v2 CUDA calibrator. Calibration work is clamped to the phase size.
There are at most four candidates; noncanonical promotion still requires a
full-work win beyond the near-tie margin. After confirmation, the runtime
executes the selected plan again as the actual phase execution, verifies its
scalar checksum, and reduces that result before calibrating the next phase.

No work moves during a phase. CUDA-only execution uses the existing canonical
smoke helper; static heterogeneous execution uses a CPU prefix of
`floor(items/2)` and a CUDA suffix. Helper-reported CUDA identity must agree
across calibration, selected CUDA execution, and subsequent phases. A helper
failure, identity change, or checksum mismatch aborts the run without fallback
or a partial verified receipt. Each completed phase remains side-effect-free.

Requests admit 1–64 phases, 1–31 repeats, and a checked-u64 sum of phase items.
CPU phase and calibration sizes must be positive; CUDA needs at least two items
for its fixed split. The phase sequence is bounded in memory, but very large
caller-supplied work sizes can still take substantial execution time.

The v1 phase receipt embeds the full calibration receipt for every phase and
records the selected backend, requested/effective workers, CPU/CUDA geometry,
actual execution checksum, and observed plan-change count. Zero plan changes
is a valid measured result. Calibration wall time is separate from the selected
executor call plus phase verification wall time; neither implies a speedup.

This first slice does not retain a persistent CUDA context or remove helper
startup costs. Dynamic work stealing, NUMA, multi-GPU, managed memory, and a
persistent calibration cache remain deferred.

## Evidence

The uploaded Phase 3/4 captures are retained under
`evidence/phase3-4-cuda-host-2026-09-23/`. They close those earlier physical
streaming/calibration evidence gates. They do not establish Phase 5 execution.
CPU tests exercise phase ordering and forced plan transitions; isolated CUDA
fixtures check protocol and identity failure paths without claiming hardware.

For a fresh Phase 5 hardware receipt, from a clean checkout on a CUDA host:

```sh
NVCC=/usr/bin/nvcc bash scripts/capture-phase5-adaptive.sh /tmp/mesh-phase5-evidence
```

Use a new output directory. The script builds the canonical helper and release
CLI, runs three phases with CUDA candidate measurements, records the source SHA
and selected compiler, and writes receipt/environment hashes. CPU may remain
selected throughout; a GPU win is not a condition for successful validation.
