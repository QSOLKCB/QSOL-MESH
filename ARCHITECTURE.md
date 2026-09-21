# QSOL-MESH Architecture

```text
Inspector -> Topology Model -> Calibrator -> Planner -> Scheduler
                                              |          |
                                              v          v
                                         Memory Broker  Executors
                                              \          /
                                               v        v
                                        Deterministic Reducer
                                                -> Verifier -> Receipt
```

- **Inspector:** observes CPU, accelerator, memory, NUMA/cache, runtime/driver, and process constraints.
- **Calibrator:** measures bounded admissible candidates; never infers speed from product names.
- **Planner:** creates a versioned execution plan from workload requirements, observations, evidence, and memory constraints.
- **Scheduler:** dispatches plan-owned work without changing workload identity/reduction semantics.
- **Memory Broker:** owns explicit host-pageable, host-pinned, accelerator-local, and future memory-domain policy.
- **Executors:** execute workload-defined operations; they do not define correctness.
- **Reducer/Committer:** combines results under the workload's declared contract.
- **Verifier:** checks selected execution against the workload oracle.
- **Receipt:** records requested, observed, selected, executed, verified, and claimed state.

PR #1 contains no CUDA kernel, dynamic scheduler, managed-memory policy, GALAXY adapter, or performance promotion.
