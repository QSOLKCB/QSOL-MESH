#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "phase1-cuda-host-2026-09-23"
MANIFEST = EVIDENCE / "manifest.json"
SOURCE_COMMIT = "58301da12f241ae823f70174a3028319abe9a36f"
EXPECTED_CHECKSUM = "9d390352e9b7d24c"

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
if manifest.get("schema") != "qsol.mesh.retained-execution-evidence.v1":
    raise SystemExit("retained evidence manifest schema drift")
if manifest.get("source_commit") != SOURCE_COMMIT:
    raise SystemExit("retained evidence source commit drift")
if manifest.get("workload_identity") != "mesh-smoke-v1":
    raise SystemExit("retained evidence workload identity drift")

entries = manifest.get("files")
if not isinstance(entries, list) or len(entries) != 3:
    raise SystemExit("retained evidence file inventory drift")
for entry in entries:
    path = EVIDENCE / entry["path"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise SystemExit(f"retained evidence digest mismatch: {entry['path']}")

def load(name):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))

gpu = load("gpu-verify-100000.json")
static = load("smoke-static-verify-100000-40000.json")
concurrent = load("smoke-concurrent-verify-100000-40000.json")

for receipt in (gpu, static, concurrent):
    if receipt.get("workload_identity", {}).get("workload_id") != "mesh-smoke-v1":
        raise SystemExit("retained receipt workload identity drift")
    verification = receipt.get("verification", {})
    if verification.get("verified") is not True:
        raise SystemExit("retained receipt is not verified")
    if verification.get("checksum") != EXPECTED_CHECKSUM or verification.get("reference") != EXPECTED_CHECKSUM:
        raise SystemExit("retained receipt full-work checksum drift")
    topology = receipt.get("observed_topology", {})
    if topology.get("accelerator_observed") is not True:
        raise SystemExit("retained receipt does not record observed accelerator execution")

if gpu.get("schema") != "qsol.mesh.cuda-smoke-receipt.v1":
    raise SystemExit("retained CUDA receipt schema drift")
if gpu.get("requested_configuration", {}).get("command") != "verify":
    raise SystemExit("retained CUDA receipt is not a verify receipt")
if gpu.get("effective_execution", {}).get("backend") != "nvidia-cuda":
    raise SystemExit("retained CUDA receipt backend drift")

if static.get("schema") != "qsol.mesh.static-split-receipt.v1":
    raise SystemExit("retained static receipt schema drift")
static_exec = static.get("effective_execution", {})
if static_exec.get("concurrent") is not False or static_exec.get("adaptive") is not False:
    raise SystemExit("retained static receipt execution-boundary drift")

if concurrent.get("schema") != "qsol.mesh.concurrent-split-receipt.v1":
    raise SystemExit("retained concurrent receipt schema drift")
concurrent_exec = concurrent.get("effective_execution", {})
if concurrent_exec.get("concurrent_dispatch") is not True or concurrent_exec.get("adaptive") is not False:
    raise SystemExit("retained concurrent receipt dispatch-boundary drift")
dispatch = concurrent_exec.get("dispatch_contract", {})
if dispatch.get("kernel_overlap_measured") is not False:
    raise SystemExit("retained concurrent evidence overclaims kernel overlap")

static_req = static.get("requested_configuration", {})
concurrent_req = concurrent.get("requested_configuration", {})
for request in (static_req, concurrent_req):
    if request.get("command") != "verify" or request.get("items") != 100000 or request.get("cpu_items") != 40000:
        raise SystemExit("retained heterogeneous geometry drift")

static_topology = static["observed_topology"]
concurrent_topology = concurrent["observed_topology"]
for key in ("cuda_device_ordinal", "cuda_compute_major", "cuda_compute_minor", "cuda_runtime_version", "cuda_driver_version"):
    if static_topology.get(key) != concurrent_topology.get(key):
        raise SystemExit(f"retained heterogeneous topology mismatch: {key}")

claim = manifest.get("claim_boundary", {})
if claim != {
    "retains_cuda_host_execution_evidence": True,
    "retains_static_heterogeneous_execution_evidence": True,
    "retains_concurrent_executor_dispatch_evidence": True,
    "claims_kernel_level_overlap": False,
    "claims_performance_gain": False,
    "helper_reported_topology_is_independently_attested": False,
    "cryptographic_host_attestation": False,
}:
    raise SystemExit("retained evidence claim boundary drift")

roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
for line in (
    "- [x] Retained execution receipt from a CUDA-capable host.",
    "- [x] Retained static heterogeneous execution receipt from a CUDA-capable host.",
    "- [x] Retained concurrent heterogeneous execution receipt from a CUDA-capable host.",
    "- [ ] Kernel-level overlap measurement remains outside this bring-up rung.",
):
    if line not in roadmap:
        raise SystemExit(f"roadmap retained-evidence state drift: {line}")

contract_expectations = {
    "nvidia-executor-contract.v1.json": "retained-cuda-host-receipt-bound-to-58301da12f241ae823f70174a3028319abe9a36f",
    "static-split-contract.v1.json": "retained-cuda-host-static-split-receipt-bound-to-58301da12f241ae823f70174a3028319abe9a36f",
    "concurrent-split-contract.v1.json": "retained-cuda-host-concurrent-receipt-bound-to-58301da12f241ae823f70174a3028319abe9a36f",
}
for name, status in contract_expectations.items():
    contract = json.loads((ROOT / "machine" / name).read_text(encoding="utf-8"))
    if contract.get("evidence_status") != status:
        raise SystemExit(f"{name}: retained evidence status drift")
    retained = contract.get("retained_evidence", {})
    if retained.get("source_commit") != SOURCE_COMMIT or retained.get("manifest") != "evidence/phase1-cuda-host-2026-09-23/manifest.json":
        raise SystemExit(f"{name}: retained evidence binding drift")

print("retained Phase 1 CUDA-host evidence: valid")
