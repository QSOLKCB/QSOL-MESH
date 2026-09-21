# QSOL-MESH

**Heterogeneous compute and memory runtime that calibrates real CPU/GPU silicon, plans workload placement across system RAM and VRAM, and executes deterministic workloads across both.**

MESH separates workload meaning from execution placement. A workload defines what must be computed and how correctness is verified. MESH may decide where, when, and how work executes, but may not redefine the workload.

Initial CLI: `mesh inspect`, `mesh calibrate`, `mesh plan`, `mesh run`, `mesh verify`, `mesh receipt`.

PR #1 is architecture-first: contracts, machine-readable agent policy, validation CI, and a minimal Rust CLI skeleton. It intentionally contains no CUDA kernel and no copied GALAXY implementation.

Human-readable explanations live at the repository root. Normative automated-agent authority lives under `machine/`.
