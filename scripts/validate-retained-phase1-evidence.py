#!/usr/bin/env python3
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "phase1-cuda-host-2026-09-23"
MANIFEST = EVIDENCE / "manifest.json"
MANIFEST_REPO_PATH = "evidence/phase1-cuda-host-2026-09-23/manifest.json"
SOURCE_COMMIT = "58301da12f241ae823f70174a3028319abe9a36f"
EXPECTED_CHECKSUM = "9d390352e9b7d24c"
EXPECTED_CUDA_HELPER_PATH = "/home/trent/qsol-mesh-dev/QSOL-MESH/target/mesh-cuda-smoke"
EXPECTED_CUDA_RECEIPT_REDUCTION = "device-strided-local-sums-plus-atomicAdd-u64"
EXPECTED_RETAINED_ENVIRONMENT = {
    "cpu": "AMD Ryzen 9 5950X",
    "gpu": "NVIDIA GeForce RTX 5060 Ti",
    "gpu_memory_mib": 16311,
    "compute_capability": "12.0",
    "nvidia_driver": "595.84",
    "cuda_runtime_api": 13020,
    "cuda_driver_api": 13020,
    "cuda_compiler": "13.2.86",
    "rust": "1.85.1",
}
MASK_U64 = (1 << 64) - 1
SMOKE_SEED = 0x4D4553485F534D4B

EXPECTED_FILES = {
    "gpu-verify-100000.json": {
        "kind": "single-device-cuda-verified-receipt",
        "schema": "qsol.mesh.cuda-smoke-receipt.v1",
    },
    "smoke-static-verify-100000-40000.json": {
        "kind": "static-heterogeneous-verified-receipt",
        "schema": "qsol.mesh.static-split-receipt.v1",
    },
    "smoke-concurrent-verify-100000-40000.json": {
        "kind": "concurrent-heterogeneous-verified-receipt",
        "schema": "qsol.mesh.concurrent-split-receipt.v1",
    },
}


def mix64(value):
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & MASK_U64
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & MASK_U64
    return (value ^ (value >> 31)) & MASK_U64


def smoke_reference_range(start, items):
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        raise SystemExit("retained smoke range start is invalid")
    if not isinstance(items, int) or isinstance(items, bool) or items <= 0:
        raise SystemExit("retained smoke range item count is invalid")
    if start > MASK_U64 or items > MASK_U64 or start + items > MASK_U64:
        raise SystemExit("retained smoke range overflows u64")

    checksum = 0
    for logical_id in range(start, start + items):
        checksum = (checksum + mix64(logical_id ^ SMOKE_SEED)) & MASK_U64
    return f"{checksum:016x}"


def load(name):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def rust_string_constant(path, name):
    source = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(
        rf"pub const {re.escape(name)}: &str =\s*\"([^\"]+)\";",
        source,
    )
    if match is None:
        raise SystemExit(f"cannot resolve runtime claim boundary: {name}")
    return match.group(1)


def require_verified_full_oracle(receipt, label):
    if receipt.get("workload_identity") != {
        "workload_contract_version": "1.0.0",
        "workload_id": "mesh-smoke-v1",
    }:
        raise SystemExit(f"{label}: workload identity drift")

    request = receipt.get("requested_configuration", {})
    items = request.get("items")
    expected = smoke_reference_range(0, items)
    if expected != EXPECTED_CHECKSUM:
        raise SystemExit(f"{label}: retained full-work geometry/checksum drift")

    verification = receipt.get("verification", {})
    if verification.get("verified") is not True:
        raise SystemExit(f"{label}: retained receipt is not verified")
    if verification.get("checksum") != expected or verification.get("reference") != expected:
        raise SystemExit(f"{label}: retained receipt full-work oracle drift")

    topology = receipt.get("observed_topology", {})
    if topology.get("accelerator_observed") is not True:
        raise SystemExit(f"{label}: retained receipt does not record observed accelerator execution")

    return expected


def validate_partition_receipt(receipt, label, *, concurrent):
    request = receipt.get("requested_configuration", {})
    if request.get("command") != "verify":
        raise SystemExit(f"{label}: retained heterogeneous receipt is not a verify receipt")

    items = request.get("items")
    cpu_items = request.get("cpu_items")
    cpu_workers = request.get("cpu_workers")
    requested_device = request.get("device_ordinal")
    if (
        not isinstance(items, int)
        or isinstance(items, bool)
        or items < 2
        or not isinstance(cpu_items, int)
        or isinstance(cpu_items, bool)
        or cpu_items <= 0
        or cpu_items >= items
        or not isinstance(cpu_workers, int)
        or isinstance(cpu_workers, bool)
        or cpu_workers <= 0
        or not isinstance(requested_device, int)
        or isinstance(requested_device, bool)
        or requested_device < 0
    ):
        raise SystemExit(f"{label}: retained heterogeneous request geometry is invalid")

    topology = receipt.get("observed_topology", {})
    if topology.get("cuda_device_ordinal") != requested_device:
        raise SystemExit(f"{label}: requested and observed CUDA device mismatch")

    execution = receipt.get("effective_execution", {})
    cpu = execution.get("cpu", {})
    cuda = execution.get("cuda", {})
    if (
        cpu.get("range_start") != 0
        or cpu.get("range_end") != cpu_items
        or cpu.get("requested_workers") != cpu_workers
    ):
        raise SystemExit(f"{label}: CPU effective range/request drift")

    effective_workers = cpu.get("effective_workers")
    if (
        not isinstance(effective_workers, int)
        or isinstance(effective_workers, bool)
        or effective_workers <= 0
        or effective_workers > cpu_workers
        or effective_workers > cpu_items
    ):
        raise SystemExit(f"{label}: CPU effective worker evidence drift")

    if (
        cuda.get("range_start") != cpu_items
        or cuda.get("range_end") != items
        or cuda.get("device_ordinal") != requested_device
    ):
        raise SystemExit(f"{label}: CUDA effective range/device drift")
    if (
        not isinstance(cuda.get("blocks"), int)
        or isinstance(cuda.get("blocks"), bool)
        or cuda.get("blocks") <= 0
        or not isinstance(cuda.get("threads_per_block"), int)
        or isinstance(cuda.get("threads_per_block"), bool)
        or cuda.get("threads_per_block") <= 0
    ):
        raise SystemExit(f"{label}: CUDA launch geometry is invalid")

    cpu_reference = smoke_reference_range(0, cpu_items)
    cuda_reference = smoke_reference_range(cpu_items, items - cpu_items)
    verification = receipt.get("verification", {})
    if verification.get("kind") != "partition-range-oracles-plus-full-scalar-reference":
        raise SystemExit(f"{label}: partition verification kind drift")
    if verification.get("cpu_reference") != cpu_reference or cpu.get("checksum") != cpu_reference:
        raise SystemExit(f"{label}: CPU partition oracle drift")
    if verification.get("cuda_reference") != cuda_reference or cuda.get("checksum") != cuda_reference:
        raise SystemExit(f"{label}: CUDA partition oracle drift")

    reduced = (int(cpu_reference, 16) + int(cuda_reference, 16)) & MASK_U64
    reduced_hex = f"{reduced:016x}"
    full_reference = smoke_reference_range(0, items)
    if reduced_hex != full_reference:
        raise SystemExit(f"{label}: partition reduction does not match full smoke oracle")
    if verification.get("checksum") != reduced_hex or verification.get("reference") != full_reference:
        raise SystemExit(f"{label}: full partition reduction evidence drift")

    if execution.get("reduction") != "partition-order-wrapping-u64":
        raise SystemExit(f"{label}: deterministic reduction contract drift")

    if concurrent:
        dispatch = {
            "cpu_joined_after_cuda_call_return": True,
            "cpu_task_spawned_before_cuda_call": True,
            "kernel_overlap_measured": False,
        }
        expected_execution = {
            "adaptive": False,
            "concurrent_dispatch": True,
            "cpu": {
                "checksum": cpu_reference,
                "effective_workers": effective_workers,
                "range_end": cpu_items,
                "range_start": 0,
                "requested_workers": cpu_workers,
            },
            "cuda": {
                "blocks": cuda["blocks"],
                "checksum": cuda_reference,
                "device_ordinal": requested_device,
                "range_end": items,
                "range_start": cpu_items,
                "threads_per_block": cuda["threads_per_block"],
            },
            "dispatch_contract": dispatch,
            "kind": "concurrent-cpu-cuda-partition-v1",
            "reduction": "partition-order-wrapping-u64",
            "reduction_order": ["cpu", "nvidia-cuda"],
        }
        if execution != expected_execution:
            raise SystemExit(f"{label}: concurrent effective-execution shape drift")
    else:
        expected_execution = {
            "adaptive": False,
            "concurrent": False,
            "cpu": {
                "checksum": cpu_reference,
                "effective_workers": effective_workers,
                "range_end": cpu_items,
                "range_start": 0,
                "requested_workers": cpu_workers,
            },
            "cuda": {
                "blocks": cuda["blocks"],
                "checksum": cuda_reference,
                "device_ordinal": requested_device,
                "range_end": items,
                "range_start": cpu_items,
                "threads_per_block": cuda["threads_per_block"],
            },
            "execution_order": ["cpu", "nvidia-cuda"],
            "kind": "static-cpu-cuda-partition-v1",
            "reduction": "partition-order-wrapping-u64",
        }
        if execution != expected_execution:
            raise SystemExit(f"{label}: static effective-execution shape drift")

    return {
        "items": items,
        "cpu_items": cpu_items,
        "cpu_workers": cpu_workers,
        "device_ordinal": requested_device,
        "cpu_reference": cpu_reference,
        "cuda_reference": cuda_reference,
        "full_reference": full_reference,
    }


manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
if manifest.get("schema") != "qsol.mesh.retained-execution-evidence.v1":
    raise SystemExit("retained evidence manifest schema drift")
if manifest.get("source_commit") != SOURCE_COMMIT:
    raise SystemExit("retained evidence source commit drift")
if manifest.get("workload_identity") != "mesh-smoke-v1":
    raise SystemExit("retained evidence workload identity drift")
if manifest.get("environment") != EXPECTED_RETAINED_ENVIRONMENT:
    raise SystemExit("retained evidence environment identity drift")

entries = manifest.get("files")
if not isinstance(entries, list) or len(entries) != len(EXPECTED_FILES):
    raise SystemExit("retained evidence file inventory drift")

manifest_by_path = {}
for entry in entries:
    if not isinstance(entry, dict):
        raise SystemExit("retained evidence manifest entry is invalid")
    path_name = entry.get("path")
    if not isinstance(path_name, str) or not path_name:
        raise SystemExit("retained evidence manifest path is invalid")
    if path_name in manifest_by_path:
        raise SystemExit(f"duplicate retained evidence manifest path: {path_name}")
    expected_entry = EXPECTED_FILES.get(path_name)
    if expected_entry is None:
        raise SystemExit(f"unexpected retained evidence manifest path: {path_name}")
    if entry.get("kind") != expected_entry["kind"] or entry.get("schema") != expected_entry["schema"]:
        raise SystemExit(f"retained evidence manifest metadata drift: {path_name}")
    path = EVIDENCE / path_name
    if not path.is_file():
        raise SystemExit(f"retained evidence file is missing: {path_name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get("sha256"):
        raise SystemExit(f"retained evidence digest mismatch: {path_name}")
    manifest_by_path[path_name] = entry

if set(manifest_by_path) != set(EXPECTED_FILES):
    raise SystemExit("retained evidence manifest inventory is incomplete")

gpu = load("gpu-verify-100000.json")
static = load("smoke-static-verify-100000-40000.json")
concurrent = load("smoke-concurrent-verify-100000-40000.json")

evidence_contract = json.loads(
    (ROOT / "machine" / "evidence-contract.v1.json").read_text(encoding="utf-8")
)
required_sections = evidence_contract.get("receipt_required_sections")
if not isinstance(required_sections, list) or not required_sections:
    raise SystemExit("evidence contract required-section inventory is invalid")
for label, receipt in (
    ("CUDA", gpu),
    ("static split", static),
    ("concurrent split", concurrent),
):
    missing_sections = [section for section in required_sections if section not in receipt]
    if missing_sections:
        raise SystemExit(
            f"{label}: retained receipt missing required sections: {missing_sections}"
        )

require_verified_full_oracle(gpu, "CUDA")
require_verified_full_oracle(static, "static split")
require_verified_full_oracle(concurrent, "concurrent split")

nvidia_contract = json.loads(
    (ROOT / "machine" / "nvidia-executor-contract.v1.json").read_text(encoding="utf-8")
)
static_contract = json.loads(
    (ROOT / "machine" / "static-split-contract.v1.json").read_text(encoding="utf-8")
)
concurrent_contract = json.loads(
    (ROOT / "machine" / "concurrent-split-contract.v1.json").read_text(encoding="utf-8")
)

if (
    static_contract.get("cuda_executor") != nvidia_contract["executor_id"]
    or concurrent_contract.get("cuda_executor") != nvidia_contract["executor_id"]
):
    raise SystemExit("split CUDA executor identity disagrees with NVIDIA executor")
if (
    static_contract.get("cuda_range_worker_protocol") != nvidia_contract["range_worker_protocol"]
):
    raise SystemExit("static split CUDA worker protocol disagrees with NVIDIA executor")


def retained_cuda_identity():
    environment = manifest["environment"]
    compute_capability = environment.get("compute_capability")
    if not isinstance(compute_capability, str):
        raise SystemExit("retained manifest compute capability is invalid")
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)", compute_capability)
    if match is None:
        raise SystemExit("retained manifest compute capability is invalid")

    compute_major = int(match.group(1))
    compute_minor = int(match.group(2))
    runtime_version = environment.get("cuda_runtime_api")
    driver_version = environment.get("cuda_driver_api")
    if (
        compute_major <= 0
        or compute_minor < 0
        or not isinstance(runtime_version, int)
        or isinstance(runtime_version, bool)
        or runtime_version <= 0
        or not isinstance(driver_version, int)
        or isinstance(driver_version, bool)
        or driver_version <= 0
    ):
        raise SystemExit("retained manifest CUDA identity is invalid")

    gpu_topology = gpu.get("observed_topology", {})
    identity = {
        "device_ordinal": gpu.get("requested_configuration", {}).get("device_ordinal"),
        "compute_major": compute_major,
        "compute_minor": compute_minor,
        "cuda_runtime_version": runtime_version,
        "cuda_driver_version": driver_version,
        "evidence_source": nvidia_contract["observation_contract"]["evidence_source"],
    }
    if gpu_topology != {
        "accelerator_observed": True,
        "backend": "nvidia-cuda",
        **identity,
    }:
        raise SystemExit("retained GPU topology disagrees with manifest environment")
    if (
        manifest.get("claim_boundary", {}).get(
            "helper_reported_topology_is_independently_attested"
        )
        is not nvidia_contract["observation_contract"][
            "helper_reported_topology_is_independently_attested"
        ]
    ):
        raise SystemExit("retained topology attestation boundary drift")
    return identity


def validate_split_topology(receipt, label):
    topology = receipt.get("observed_topology", {})
    request = receipt.get("requested_configuration", {})
    available_workers = topology.get("available_cpu_workers")
    if (
        not isinstance(available_workers, int)
        or isinstance(available_workers, bool)
        or available_workers <= 0
    ):
        raise SystemExit(f"{label}: retained CPU topology evidence drift")

    identity = retained_cuda_identity()
    expected = {
        "available_cpu_workers": available_workers,
        "accelerator_observed": True,
        "cuda_device_ordinal": identity["device_ordinal"],
        "cuda_compute_major": identity["compute_major"],
        "cuda_compute_minor": identity["compute_minor"],
        "cuda_runtime_version": identity["cuda_runtime_version"],
        "cuda_driver_version": identity["cuda_driver_version"],
        "cuda_helper_path": EXPECTED_CUDA_HELPER_PATH,
        "cuda_evidence_source": identity["evidence_source"],
    }
    if request.get("device_ordinal") != identity["device_ordinal"]:
        raise SystemExit(f"{label}: requested CUDA device disagrees with retained host")
    if topology != expected:
        raise SystemExit(f"{label}: retained CUDA topology evidence drift")


def expected_split_memory_plan():
    nvidia_memory = nvidia_contract["memory_contract"]
    split_memory = static_contract["memory_contract"]
    if (
        nvidia_memory["persistent_accelerator_pool"] is not False
        or nvidia_memory["pinned_host_staging"] is not False
    ):
        raise SystemExit("NVIDIA executor physical-memory claim boundary drift")
    if (
        split_memory["accelerator_checksum_buffer_bytes"]
        != nvidia_memory["accelerator_checksum_buffer_bytes"]
        or split_memory["per_item_materialization"]
        != nvidia_memory["per_item_device_materialization"]
    ):
        raise SystemExit("split memory contract disagrees with NVIDIA executor")
    return {
        "domains": [
            split_memory["cpu_domain"],
            split_memory["cuda_domain"],
        ],
        "per_item_materialization": nvidia_memory[
            "per_item_device_materialization"
        ],
        "cpu_temporary_state": "O(cpu-workers)",
        "accelerator_checksum_buffer_bytes": nvidia_memory[
            "accelerator_checksum_buffer_bytes"
        ],
        "device_to_host_result_bytes": split_memory[
            "device_to_host_result_bytes"
        ],
    }

if gpu.get("schema") != EXPECTED_FILES["gpu-verify-100000.json"]["schema"]:
    raise SystemExit("retained CUDA receipt schema drift")
gpu_request = gpu.get("requested_configuration", {})
gpu_topology = gpu.get("observed_topology", {})
gpu_execution = gpu.get("effective_execution", {})
if gpu_request.get("command") != "verify":
    raise SystemExit("retained CUDA receipt is not a verify receipt")
if gpu_request.get("items") != 100000:
    raise SystemExit("retained CUDA workload size drift")
if gpu_request.get("helper_path") != EXPECTED_CUDA_HELPER_PATH:
    raise SystemExit("retained CUDA helper path is not the retained canonical worker path")

requested_device = gpu_request.get("device_ordinal")
if (
    not isinstance(requested_device, int)
    or isinstance(requested_device, bool)
    or requested_device < 0
    or gpu_topology.get("device_ordinal") != requested_device
    or gpu_execution.get("device_ordinal") != requested_device
):
    raise SystemExit("retained CUDA requested/observed/effective device mismatch")
if gpu_topology.get("backend") != "nvidia-cuda":
    raise SystemExit("retained CUDA backend drift")

blocks = gpu_execution.get("blocks")
threads_per_block = gpu_execution.get("threads_per_block")
if (
    not isinstance(blocks, int)
    or isinstance(blocks, bool)
    or blocks <= 0
    or not isinstance(threads_per_block, int)
    or isinstance(threads_per_block, bool)
    or threads_per_block <= 0
):
    raise SystemExit("retained CUDA launch geometry is invalid")
expected_gpu_execution = {
    "backend": "nvidia-cuda",
    "blocks": blocks,
    "device_ordinal": requested_device,
    "reduction": EXPECTED_CUDA_RECEIPT_REDUCTION,
    "threads_per_block": threads_per_block,
}
if gpu_execution != expected_gpu_execution:
    raise SystemExit("retained CUDA effective-execution shape drift")

compute_major = gpu_topology.get("compute_major")
compute_minor = gpu_topology.get("compute_minor")
runtime_version = gpu_topology.get("cuda_runtime_version")
driver_version = gpu_topology.get("cuda_driver_version")
if (
    not isinstance(compute_major, int)
    or isinstance(compute_major, bool)
    or compute_major <= 0
    or not isinstance(compute_minor, int)
    or isinstance(compute_minor, bool)
    or compute_minor < 0
    or not isinstance(runtime_version, int)
    or isinstance(runtime_version, bool)
    or runtime_version <= 0
    or not isinstance(driver_version, int)
    or isinstance(driver_version, bool)
    or driver_version <= 0
    or gpu_topology.get("evidence_source")
    != nvidia_contract["observation_contract"]["evidence_source"]
):
    raise SystemExit("retained CUDA required topology evidence drift")

if (
    nvidia_contract["execution_contract"]["device_side_checksum_accumulation"]
    != "wrapping-u64-local-sums-plus-atomicAdd"
    or nvidia_contract["execution_contract"]["host_scalar_fallback_inside_cuda_worker_allowed"]
    is not False
):
    raise SystemExit("NVIDIA executor checksum-accumulation contract drift")

gpu_memory = gpu.get("memory_plan", {})
if gpu_memory != {
    "accelerator_checksum_buffer_bytes": nvidia_contract["memory_contract"][
        "accelerator_checksum_buffer_bytes"
    ],
    "domains": ["accelerator-local", "host-pageable"],
    "per_item_materialization": nvidia_contract["memory_contract"][
        "per_item_device_materialization"
    ],
}:
    raise SystemExit("retained CUDA memory evidence drift")

if gpu.get("verification", {}).get("kind") != "scalar-reference-equality":
    raise SystemExit("retained CUDA verification kind drift")
if gpu.get("source_identity") != {
    "executor_id": nvidia_contract["executor_id"],
    "runtime": "qsol-mesh-cli",
    "worker_protocol": nvidia_contract["worker_protocol"],
}:
    raise SystemExit("retained CUDA source identity drift")

cuda_boundary = rust_string_constant(
    "crates/mesh-core/src/accelerator.rs",
    "CUDA_SMOKE_CLAIM_BOUNDARY",
)
if gpu.get("claim_boundary") != cuda_boundary:
    raise SystemExit("retained CUDA receipt claim-boundary drift")

if static.get("schema") != static_contract["receipt_contract"]["schema"]:
    raise SystemExit("retained static receipt schema drift")
static_geometry = validate_partition_receipt(static, "static split", concurrent=False)
if static.get("source_identity") != {
    "cuda_executor_id": nvidia_contract["executor_id"],
    "cuda_worker_protocol": static_contract["cuda_range_worker_protocol"],
    "runtime": "qsol-mesh-cli",
    "split_id": static_contract["split_id"],
    "split_schema": "qsol.mesh.static-split.v1",
}:
    raise SystemExit("retained static source identity drift")
validate_split_topology(static, "static split")
static_memory = static.get("memory_plan", {})
if static_memory != expected_split_memory_plan():
    raise SystemExit("retained static memory evidence drift")
static_boundary = rust_string_constant(
    "crates/mesh-core/src/static_split.rs",
    "STATIC_SPLIT_CLAIM_BOUNDARY",
)
if static.get("claim_boundary") != static_boundary:
    raise SystemExit("retained static receipt claim-boundary drift")

if concurrent.get("schema") != concurrent_contract["receipt_contract"]["schema"]:
    raise SystemExit("retained concurrent receipt schema drift")
concurrent_geometry = validate_partition_receipt(
    concurrent,
    "concurrent split",
    concurrent=True,
)
if concurrent.get("source_identity") != {
    "cuda_executor_id": nvidia_contract["executor_id"],
    "cuda_worker_protocol": nvidia_contract["range_worker_protocol"],
    "runtime": "qsol-mesh-cli",
    "split_id": concurrent_contract["split_id"],
    "split_schema": "qsol.mesh.concurrent-split.v1",
}:
    raise SystemExit("retained concurrent source identity drift")
validate_split_topology(concurrent, "concurrent split")
concurrent_memory = concurrent.get("memory_plan", {})
if concurrent_memory != expected_split_memory_plan():
    raise SystemExit("retained concurrent memory evidence drift")
concurrent_boundary = rust_string_constant(
    "crates/mesh-core/src/concurrent_split.rs",
    "CONCURRENT_SPLIT_CLAIM_BOUNDARY",
)
if concurrent.get("claim_boundary") != concurrent_boundary:
    raise SystemExit("retained concurrent receipt claim-boundary drift")

if static_geometry != concurrent_geometry:
    raise SystemExit("retained static/concurrent partition geometry or oracle mismatch")

static_topology = static["observed_topology"]
concurrent_topology = concurrent["observed_topology"]
for key in (
    "cuda_device_ordinal",
    "cuda_compute_major",
    "cuda_compute_minor",
    "cuda_runtime_version",
    "cuda_driver_version",
):
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
    "nvidia-executor-contract.v1.json": {
        "status": "retained-cuda-host-receipt-bound-to-58301da12f241ae823f70174a3028319abe9a36f",
        "receipt": "evidence/phase1-cuda-host-2026-09-23/gpu-verify-100000.json",
        "manifest_name": "gpu-verify-100000.json",
        "schema": "qsol.mesh.cuda-smoke-receipt.v1",
    },
    "static-split-contract.v1.json": {
        "status": "retained-cuda-host-static-split-receipt-bound-to-58301da12f241ae823f70174a3028319abe9a36f",
        "receipt": "evidence/phase1-cuda-host-2026-09-23/smoke-static-verify-100000-40000.json",
        "manifest_name": "smoke-static-verify-100000-40000.json",
        "schema": "qsol.mesh.static-split-receipt.v1",
    },
    "concurrent-split-contract.v1.json": {
        "status": "retained-cuda-host-concurrent-receipt-bound-to-58301da12f241ae823f70174a3028319abe9a36f",
        "receipt": "evidence/phase1-cuda-host-2026-09-23/smoke-concurrent-verify-100000-40000.json",
        "manifest_name": "smoke-concurrent-verify-100000-40000.json",
        "schema": "qsol.mesh.concurrent-split-receipt.v1",
    },
}
for name, expected in contract_expectations.items():
    contract = json.loads((ROOT / "machine" / name).read_text(encoding="utf-8"))
    if contract.get("evidence_status") != expected["status"]:
        raise SystemExit(f"{name}: retained evidence status drift")
    retained = contract.get("retained_evidence", {})
    if retained.get("source_commit") != SOURCE_COMMIT:
        raise SystemExit(f"{name}: retained evidence source-commit drift")
    if retained.get("manifest") != MANIFEST_REPO_PATH:
        raise SystemExit(f"{name}: retained evidence manifest binding drift")
    if retained.get("receipt") != expected["receipt"]:
        raise SystemExit(f"{name}: retained receipt binding drift")

    receipt_path = ROOT / expected["receipt"]
    if not receipt_path.is_file():
        raise SystemExit(f"{name}: retained receipt path does not exist")
    manifest_entry = manifest_by_path.get(expected["manifest_name"])
    if manifest_entry is None:
        raise SystemExit(f"{name}: retained receipt is absent from manifest inventory")
    if manifest_entry.get("schema") != expected["schema"]:
        raise SystemExit(f"{name}: retained receipt manifest schema drift")

print("retained Phase 1 CUDA-host evidence: valid")
