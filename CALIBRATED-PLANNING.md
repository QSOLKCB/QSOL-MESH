# QSOL-MESH Calibrated Planning

Phase 4 adds a deterministic planner that may choose among **measured admissible candidates**. It does not infer speed from CPU/GPU model names and it does not promote a plan from calibration alone.

## Candidate generation

The current host probe derives a finite candidate set from observed topology:

- canonical CPU execution with one worker;
- observed maximum CPU-worker execution when more than one worker is available;
- accelerator-only and static heterogeneous candidates only when an accelerator is actually observed.

The candidate budget is fixed at four. Candidate IDs are deterministic contiguous indices, and candidate ID order is the deterministic tie-break.

## Cost evidence

Each observation records:

```text
service_ns
setup_ns
transfer_ns
checksum
verified
```

Total cost is their checked integer sum.

For the current CPU smoke probe, `service_ns` measures the complete `run_smoke` call, including scoped thread lifecycle. `setup_ns = 0` means setup is not separately isolated by this probe; it is not a claim that CPU setup has zero physical cost. `transfer_ns = 0` is valid because the CPU smoke workload performs no cross-domain transfer.

The opt-in v2 probe fills the setup and transfer fields from measured CUDA timing evidence. The default v1 probe remains CPU-only.

## Selection

The planner:

1. measures every bounded calibration candidate;
2. rejects unverified or checksum-divergent evidence;
3. chooses the lowest measured total, using candidate ID only to break exact ties;
4. keeps canonical when the apparent improvement is within the near-tie margin;
5. if a noncanonical candidate survives calibration, measures both canonical and that candidate on the full requested work;
6. promotes the candidate only if the full-work result still beats canonical by more than the margin;
7. otherwise restores canonical.

The default near-tie margin is **500 basis points (5%)**.

## Host probe

```sh
mesh calibrate smoke \
  --calibration-items 10000 \
  --full-items 100000 \
  --repeats 3 \
  --near-tie-bps 500 \
  --json
```

The receipt is `qsol.mesh.calibrated-plan-receipt.v1` and records the observed topology, bounded candidate set, calibration observations, full-work confirmation, provisional selection, final selection, and claim boundary.

## Accelerator boundary

Accelerator and heterogeneous candidates are admitted by the opt-in v2 contract only after the canonical CUDA helper reports an accelerator and supplies verified measurements. The default v1 calibration remains CPU-only. Retained physical CUDA calibration evidence is still pending; protocol fixtures are not hardware evidence.


## Receipt integrity hardening

Calibrated-plan receipts keep three identities/configuration layers distinct:

- `source_identity.plan_identity = mesh-calibration-smoke-v1` identifies the planner/procedure;
- `workload_identity.workload_id = mesh-smoke-v1` identifies the workload actually executed;
- `requested_configuration.repeats` records the requested measurement repetition count.

Every cost observation records `effective_cpu_workers` separately from the candidate's requested worker count. This captures clamping such as an eight-worker candidate measured on only one work item.

For CPU smoke observations, `setup_ns` and `transfer_ns` must remain zero because setup is already inside the service measurement and the workload performs no cross-domain transfer.

The serializer revalidates the complete public `CalibratedPlan` before emitting a receipt with `verification.verified = true`. Extra confirmation observations are rejected, and every retained confirmation must preserve canonical checksum parity.

## Opt-in CUDA calibration (v2)

After building the canonical CUDA helper on a CUDA host, run:

```sh
mesh calibrate smoke --cuda --device 0 \
  --calibration-items 10000 --full-items 100000 --repeats 3 --json
```

The bounded candidate set now includes CPU, accelerator-only, and a 50/50
static CPU/CUDA partition. Each CUDA-only repeat uses the verified timing-v2
helper. The sample with median launcher plus verification time supplies all three additive
cost fields: setup and D2H transfer are nested host intervals; service is the
remaining launcher wall interval plus the separate Rust scalar-verification
interval, including process and teardown overhead. This makes the total cost
include verification on CPU, CUDA, and static heterogeneous candidates.
The CUDA event kernel interval is recorded by the helper but is never added to
that host-clock total. CPU and static heterogeneous candidates use measured
end-to-end wall time; the latter does not separately isolate setup or transfer.

The planner requires scalar checksum parity, stable CUDA worker identity
across all CUDA samples and candidate paths, a deterministic near-tie margin,
and full-work confirmation
before promotion. An absent or failing helper rejects the opt-in run. The v1
CPU-only CLI and receipt remain available without `--cuda`. The v2 receipt is
host-specific selection evidence, not a claim of kernel overlap, independent
hardware attestation, or persistent memory reuse.

On a CUDA-capable Ubuntu host, `bash scripts/capture-phase4-cuda-calibration.sh
phase4-cuda-evidence` builds the canonical helper and release CLI, executes a
timing-v2 verification and the v2 calibrator, and saves both verified JSON
receipts with environment details and SHA-256 hashes. Supply a new output
directory; the script refuses to overwrite existing evidence.
