#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "full-cuda-host-2026-09-27"
SOURCE_COMMIT = "838e725f687888f55000f045b4a6846a46b10413"
FULL_CHECKSUM = "9d390352e9b7d24c"
CPU_40K_CHECKSUM = "5adf225493d7a5bf"
CUDA_60K_CHECKSUM = "4259e0fe55e02c8d"
U128_MAX = (1 << 128) - 1
U64_MAX = (1 << 64) - 1
U32_MAX = (1 << 32) - 1
CUDA_RETAINED_BLOCKS = 144
CUDA_THREADS_PER_BLOCK = 256
SMOKE_SEED = 0x4D45_5348_5F53_4D4B

EXPECTED_SHA256 = {
    "phase1/SHA256SUMS": "304151512dcf00ca78c62dd8d773ef7fff35bc8406f6812e2a4f95bc2ebe62c7",
    "phase3/SHA256SUMS": "feac1a924147eba9a8a10a9b46d90a154a7e29e3dc0761bbab9ac0bb991fca42",
    "phase4/SHA256SUMS": "47db5ffd2e6445a0d8ff8583bff9912ec7d8fa291853e90e126daec7ebb3c7b4",
    "phase5/SHA256SUMS": "2cd8d5da62afa30f9b1f6432e2b4b58220c98513f974cac4236ef595b35ed39f",
    "phase1/cpu-verify-100000.json": "5149e7b084a93d5ba60f80d38f9c45fffd1225d7e0520dad2cf8b48770fb334b",
    "phase1/cuda-verify-100000.json": "05c3191184ebbc4829e359d4e0b29ded05ece2b219ad15b947cdb09904c568f7",
    "phase1/static-verify-100000-40000.json": "a7c83788a8574eea66d0fb129a8990a9c5ed3c0768783f705d1f54e663e4bd01",
    "phase1/concurrent-verify-100000-40000.json": "87f229e6b5a55ebdc9d2fac0ffef7406c9caa8f68e0c2f584868558a34955a99",
    "phase1/environment.txt": "ed1ea60769938b4a6b26f34172362b8f941015ede3ff2a75e3df460d8db0f7b6",
    "phase3/multi-chunk.json": "27140f226eca7ad90d744ac8a52d9facf2dffae8b1914e9e3bf817c960eaaa8a",
    "phase3/one-chunk.json": "030e7f92535762d5ce91c689bda907b7360b2f30d5b2aac5c5f5e567cb0b4b53",
    "phase3/environment.txt": "da53a037ed53774395165fd7c22acc0a8be25bc2f66ecb2fad553e8098e3f3ac",
    "phase4/calibration.json": "dd0bbfbd697577cdd263322a2d3ea2cb3fe2f369af1fe86034b01895c16c8585",
    "phase4/timing.json": "a39643e0dd965b894b794cebee5bb0338b5b4b4ba957a518f37328588ff0f943",
    "phase4/environment.txt": "5bb074cfa3a96e3af21201de577a81671892c237c86f86c7b021794dd0719fe2",
    "phase5/adaptive.json": "07222f3861e5ecb98347a98e1fe16fc7371b967bcf628759bdab2bf0a54db5ab",
    "phase5/environment.txt": "e9b9b6222bb3442772a5a04204b654be13b8dbebc13e0b29d9624432b296b420",
}

REQUIRED_RECEIPT_SECTIONS = {
    "schema",
    "source_identity",
    "workload_identity",
    "requested_configuration",
    "observed_topology",
    "effective_execution",
    "memory_plan",
    "calibration",
    "verification",
    "claim_boundary",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def load_json(relative: str) -> dict:
    path = EVIDENCE / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    require(
        REQUIRED_RECEIPT_SECTIONS <= data.keys(),
        f"{relative}: missing common evidence sections",
    )
    return data


def mix64(value: int) -> int:
    value &= U64_MAX
    value ^= value >> 30
    value = (value * 0xBF58_476D_1CE4_E5B9) & U64_MAX
    value ^= value >> 27
    value = (value * 0x94D0_49BB_1331_11EB) & U64_MAX
    return (value ^ (value >> 31)) & U64_MAX


def smoke_reference(items: int) -> str:
    require(type(items) is int and 0 < items <= U64_MAX, "invalid smoke oracle item count")
    total = 0
    for logical_id in range(items):
        total = (total + mix64(logical_id ^ SMOKE_SEED)) & U64_MAX
    return f"{total:016x}"


def verify_hashes() -> None:
    for relative, expected in EXPECTED_SHA256.items():
        path = EVIDENCE / relative
        require(path.is_file(), f"missing retained evidence: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual == expected, f"{relative}: SHA-256 drift: {actual}")


def verify_environment(relative: str) -> None:
    text = (EVIDENCE / relative).read_text(encoding="utf-8")
    fields: dict[str, list[str]] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key or not all(character.isalnum() or character == "_" for character in key):
            continue
        fields.setdefault(key, []).append(value)

    source_commits = fields.get("source_commit", [])
    require(
        source_commits == [SOURCE_COMMIT],
        f"{relative}: source commit drift",
    )
    require("rustc 1.85.1" in text, f"{relative}: pinned Rust compiler missing")
    nvcc_paths = fields.get("nvcc_path", [])
    require(
        nvcc_paths == ["/usr/bin/nvcc"],
        f"{relative}: CUDA compiler path drift",
    )
    require(
        "Cuda compilation tools, release 12.4, V12.4.131" in text,
        f"{relative}: CUDA toolkit drift",
    )
    require("NVIDIA GeForce RTX 5060 Ti" in text, f"{relative}: GPU identity drift")
    require("595.84" in text, f"{relative}: NVIDIA driver drift")


def verify_split_geometry(receipt: dict, *, concurrent: bool) -> None:
    request = receipt["requested_configuration"]
    effective = receipt["effective_execution"]
    items = request["items"]
    cpu_items = request["cpu_items"]
    cpu = effective["cpu"]
    cuda = effective["cuda"]
    topology = receipt["observed_topology"]

    require(
        type(request["items"]) is int
        and 0 < request["items"] <= U64_MAX
        and type(request["cpu_items"]) is int
        and 0 < request["cpu_items"] <= U64_MAX
        and type(request["cpu_workers"]) is int
        and request["cpu_workers"] > 0
        and type(request["device_ordinal"]) is int
        and 0 <= request["device_ordinal"] <= U32_MAX,
        "phase1 split request numeric field drift",
    )

    require(
        topology
        == {
            "available_cpu_workers": 32,
            "accelerator_observed": True,
            "cuda_device_ordinal": request["device_ordinal"],
            "cuda_compute_major": 12,
            "cuda_compute_minor": 0,
            "cuda_runtime_version": 12040,
            "cuda_driver_version": 13020,
            "cuda_helper_path": "/home/trent/qsolmesh-dev/QSOL-MESH/target/mesh-cuda-smoke",
            "cuda_evidence_source": "cuda-helper-process",
        },
        "phase1 split observed CUDA topology drift",
    )
    require(
        topology["cuda_device_ordinal"] == cuda["device_ordinal"],
        "phase1 split observed/effective CUDA device drift",
    )

    require(
        0 < cpu_items < items,
        "phase1 split must contain two nonempty partitions",
    )
    require(
        type(cpu["range_start"]) is int
        and type(cpu["range_end"]) is int
        and (cpu["range_start"], cpu["range_end"]) == (0, cpu_items),
        "phase1 CPU split range drift",
    )
    require(
        type(cuda["range_start"]) is int
        and type(cuda["range_end"]) is int
        and (cuda["range_start"], cuda["range_end"]) == (cpu_items, items),
        "phase1 CUDA split range drift",
    )
    require(
        type(cpu["requested_workers"]) is int
        and cpu["requested_workers"] == request["cpu_workers"],
        "phase1 split requested CPU workers drift",
    )
    expected_cpu_workers = min(request["cpu_workers"], cpu_items)
    require(
        type(cpu["effective_workers"]) is int
        and cpu["effective_workers"] == expected_cpu_workers,
        "phase1 split effective CPU workers drift",
    )
    require(
        cuda["device_ordinal"] == request["device_ordinal"],
        "phase1 split CUDA device drift",
    )
    require(
        type(cuda["blocks"]) is int
        and cuda["blocks"] == CUDA_RETAINED_BLOCKS
        and type(cuda["threads_per_block"]) is int
        and cuda["threads_per_block"] == CUDA_THREADS_PER_BLOCK,
        "phase1 split CUDA launch geometry drift",
    )
    require(
        effective["reduction"] == "partition-order-wrapping-u64",
        "phase1 split reduction drift",
    )

    if concurrent:
        require(
            effective["reduction_order"] == ["cpu", "nvidia-cuda"],
            "phase1 concurrent reduction order drift",
        )
    else:
        require(
            effective["execution_order"] == ["cpu", "nvidia-cuda"],
            "phase1 static execution order drift",
        )


def verify_phase1() -> None:
    cpu = load_json("phase1/cpu-verify-100000.json")
    cuda = load_json("phase1/cuda-verify-100000.json")
    static = load_json("phase1/static-verify-100000-40000.json")
    concurrent = load_json("phase1/concurrent-verify-100000-40000.json")

    require(cpu["schema"] == "qsol.mesh.smoke-receipt.v1", "phase1 CPU schema drift")
    require(
        cpu["source_identity"]
        == {
            "runtime": "qsol-mesh-cli",
            "mesh_contract_schema": "qsol.mesh.contract.v1",
            "mesh_contract_version": "1.0.0",
        },
        "phase1 CPU source identity drift",
    )
    require(
        cpu["workload_identity"]
        == {"workload_id": "mesh-smoke-v1", "workload_contract_version": "1.0.0"},
        "phase1 CPU workload identity drift",
    )
    require(
        cpu["requested_configuration"]
        == {"command": "verify", "items": 100000, "workers": 8},
        "phase1 CPU request drift",
    )
    require(
        cpu["observed_topology"]
        == {
            "arch": "x86_64",
            "os": "linux",
            "available_parallelism": 32,
        },
        "phase1 CPU observed topology drift",
    )
    require(
        cpu["effective_execution"]
        == {
            "backend": "cpu",
            "workers": 8,
            "reduction": "worker-index-order-wrapping-u64",
        },
        "phase1 CPU effective execution drift",
    )
    require(
        cpu["memory_plan"]
        == {
            "domains": ["host-pageable"],
            "per_item_materialization": False,
            "temporary_state": "O(workers)",
        },
        "phase1 CPU memory plan drift",
    )
    require(
        cpu["calibration"] == {"performed": False},
        "phase1 CPU calibration boundary drift",
    )
    require(
        cpu["claim_boundary"] == "runtime-bring-up-only-not-performance-evidence",
        "phase1 CPU claim boundary drift",
    )
    require(
        cpu["verification"]
        == {
            "kind": "scalar-reference-equality",
            "checksum": FULL_CHECKSUM,
            "reference": FULL_CHECKSUM,
            "verified": True,
        },
        "phase1 CPU verification drift",
    )

    require(
        cuda["schema"] == "qsol.mesh.cuda-smoke-receipt.v1",
        "phase1 CUDA schema drift",
    )
    require(
        cuda["source_identity"]
        == {
            "runtime": "qsol-mesh-cli",
            "executor_id": "qsol-mesh-cuda-smoke-v1",
            "worker_protocol": "qsol.mesh.cuda-smoke-worker.v1",
        },
        "phase1 CUDA source identity drift",
    )
    require(
        cuda["workload_identity"]
        == {"workload_id": "mesh-smoke-v1", "workload_contract_version": "1.0.0"},
        "phase1 CUDA workload identity drift",
    )
    require(
        cuda["requested_configuration"]
        == {
            "command": "verify",
            "items": 100000,
            "device_ordinal": 0,
            "helper_path": "/home/trent/qsolmesh-dev/QSOL-MESH/target/mesh-cuda-smoke",
        },
        "phase1 CUDA request drift",
    )
    topo = cuda["observed_topology"]
    require(
        topo
        == {
            "accelerator_observed": True,
            "backend": "nvidia-cuda",
            "device_ordinal": 0,
            "compute_major": 12,
            "compute_minor": 0,
            "cuda_runtime_version": 12040,
            "cuda_driver_version": 13020,
            "evidence_source": "cuda-helper-process",
        },
        "phase1 CUDA topology drift",
    )
    effective = cuda["effective_execution"]
    require(
        effective["backend"] == "nvidia-cuda"
        and effective["device_ordinal"] == cuda["requested_configuration"]["device_ordinal"]
        and type(effective["blocks"]) is int
        and effective["blocks"] == CUDA_RETAINED_BLOCKS
        and type(effective["threads_per_block"]) is int
        and effective["threads_per_block"] == CUDA_THREADS_PER_BLOCK
        and effective["reduction"] == "device-strided-local-sums-plus-atomicAdd-u64",
        "phase1 CUDA effective execution drift",
    )
    require(
        cuda["memory_plan"]
        == {
            "domains": ["accelerator-local", "host-pageable"],
            "accelerator_checksum_buffer_bytes": 8,
            "per_item_materialization": False,
        },
        "phase1 CUDA memory plan drift",
    )
    require(cuda["calibration"] == {"performed": False}, "phase1 CUDA calibration drift")
    require(
        cuda["claim_boundary"]
        == "experimental-nvidia-cuda-smoke-single-device-helper-reported-topology-not-performance-evidence",
        "phase1 CUDA claim boundary drift",
    )
    require(
        cuda["verification"]
        == {
            "kind": "scalar-reference-equality",
            "checksum": FULL_CHECKSUM,
            "reference": FULL_CHECKSUM,
            "verified": True,
        },
        "phase1 CUDA oracle drift",
    )

    require(
        static["schema"] == "qsol.mesh.static-split-receipt.v1",
        "phase1 static schema drift",
    )
    require(
        static["source_identity"]
        == {
            "runtime": "qsol-mesh-cli",
            "split_id": "mesh-smoke-static-cpu-cuda-v1",
            "split_schema": "qsol.mesh.static-split.v1",
            "cuda_executor_id": "qsol-mesh-cuda-smoke-v1",
            "cuda_worker_protocol": "qsol.mesh.cuda-smoke-range-worker.v1",
        },
        "phase1 static source identity drift",
    )
    require(
        static["workload_identity"]
        == {"workload_id": "mesh-smoke-v1", "workload_contract_version": "1.0.0"},
        "phase1 static workload identity drift",
    )
    require(
        static["requested_configuration"]
        == {
            "command": "verify",
            "items": 100000,
            "cpu_items": 40000,
            "cpu_workers": 8,
            "device_ordinal": 0,
        },
        "phase1 static request drift",
    )
    require(
        static["memory_plan"]
        == {
            "domains": ["host-pageable", "accelerator-local"],
            "per_item_materialization": False,
            "cpu_temporary_state": "O(cpu-workers)",
            "accelerator_checksum_buffer_bytes": 8,
            "device_to_host_result_bytes": 8,
        },
        "phase1 static memory plan drift",
    )
    require(static["calibration"] == {"performed": False}, "phase1 static calibration drift")
    require(
        static["claim_boundary"]
        == "runtime-bring-up-static-cpu-cuda-sequential-not-concurrent-not-performance-evidence",
        "phase1 static claim boundary drift",
    )
    effective = static["effective_execution"]
    require(
        effective["kind"] == "static-cpu-cuda-partition-v1"
        and effective["concurrent"] is False
        and effective["adaptive"] is False,
        "phase1 static effective execution kind drift",
    )
    verify_split_geometry(static, concurrent=False)
    require(
        effective["cpu"]["checksum"] == CPU_40K_CHECKSUM
        and effective["cuda"]["checksum"] == CUDA_60K_CHECKSUM,
        "phase1 static partition checksum drift",
    )
    require(
        static["verification"]
        == {
            "kind": "partition-range-oracles-plus-full-scalar-reference",
            "cpu_reference": CPU_40K_CHECKSUM,
            "cuda_reference": CUDA_60K_CHECKSUM,
            "checksum": FULL_CHECKSUM,
            "reference": FULL_CHECKSUM,
            "verified": True,
        },
        "phase1 static oracle drift",
    )

    require(
        concurrent["schema"] == "qsol.mesh.concurrent-split-receipt.v1",
        "phase1 concurrent schema drift",
    )
    require(
        concurrent["source_identity"]
        == {
            "runtime": "qsol-mesh-cli",
            "split_id": "mesh-smoke-concurrent-cpu-cuda-v1",
            "split_schema": "qsol.mesh.concurrent-split.v1",
            "cuda_executor_id": "qsol-mesh-cuda-smoke-v1",
            "cuda_worker_protocol": "qsol.mesh.cuda-smoke-range-worker.v1",
        },
        "phase1 concurrent source identity drift",
    )
    require(
        concurrent["workload_identity"]
        == {"workload_id": "mesh-smoke-v1", "workload_contract_version": "1.0.0"},
        "phase1 concurrent workload identity drift",
    )
    require(
        concurrent["requested_configuration"]
        == {
            "command": "verify",
            "items": 100000,
            "cpu_items": 40000,
            "cpu_workers": 8,
            "device_ordinal": 0,
        },
        "phase1 concurrent request drift",
    )
    require(
        concurrent["memory_plan"]
        == {
            "domains": ["host-pageable", "accelerator-local"],
            "per_item_materialization": False,
            "cpu_temporary_state": "O(cpu-workers)",
            "accelerator_checksum_buffer_bytes": 8,
            "device_to_host_result_bytes": 8,
        },
        "phase1 concurrent memory plan drift",
    )
    require(
        concurrent["calibration"] == {"performed": False},
        "phase1 concurrent calibration drift",
    )
    require(
        concurrent["claim_boundary"]
        == "runtime-bring-up-concurrent-dispatch-fixed-split-not-kernel-overlap-measurement-not-performance-evidence",
        "phase1 concurrent claim boundary drift",
    )
    effective = concurrent["effective_execution"]
    require(
        effective["kind"] == "concurrent-cpu-cuda-partition-v1"
        and effective["concurrent_dispatch"] is True
        and effective["adaptive"] is False,
        "phase1 concurrent effective execution kind drift",
    )
    dispatch = effective["dispatch_contract"]
    require(
        dispatch
        == {
            "cpu_task_spawned_before_cuda_call": True,
            "cpu_joined_after_cuda_call_return": True,
            "kernel_overlap_measured": False,
        },
        "phase1 concurrent overlap claim drift",
    )
    verify_split_geometry(concurrent, concurrent=True)
    require(
        effective["cpu"]["checksum"] == CPU_40K_CHECKSUM
        and effective["cuda"]["checksum"] == CUDA_60K_CHECKSUM,
        "phase1 concurrent partition checksum drift",
    )
    require(
        concurrent["verification"]
        == {
            "kind": "partition-range-oracles-plus-full-scalar-reference",
            "cpu_reference": CPU_40K_CHECKSUM,
            "cuda_reference": CUDA_60K_CHECKSUM,
            "checksum": FULL_CHECKSUM,
            "reference": FULL_CHECKSUM,
            "verified": True,
        },
        "phase1 concurrent oracle drift",
    )

    verify_environment("phase1/environment.txt")



def verify_stream_receipt(
    receipt: dict,
    *,
    expected_request: dict,
    expected_checksum: str,
) -> None:
    require(
        REQUIRED_RECEIPT_SECTIONS <= receipt.keys(),
        "phase3 stream receipt missing common evidence sections",
    )
    require(
        receipt["schema"] == "qsol.mesh.cuda-stream-receipt.v1",
        "phase3 stream schema drift",
    )
    require(
        receipt["source_identity"]
        == {
            "runtime": "qsol-mesh-cli",
            "worker_protocol": "qsol.mesh.cuda-stream-worker.v1",
            "helper_resolution": "application-target-directory/mesh-cuda-stream",
        },
        "phase3 stream source identity drift",
    )
    require(
        receipt["workload_identity"]
        == {
            "workload_id": "mesh-smoke-stream-v1",
            "workload_contract_version": "1.0.0",
        },
        "phase3 stream workload identity drift",
    )
    request = receipt["requested_configuration"]
    require(request == expected_request, "phase3 stream request drift")
    require(
        receipt["observed_topology"]
        == {
            "accelerator_observed": True,
            "device_ordinal": request["device_ordinal"],
            "compute_major": 12,
            "compute_minor": 0,
            "cuda_runtime_version": 12040,
            "cuda_driver_version": 13020,
            "evidence_source": "cuda-helper-process",
        },
        "phase3 observed CUDA topology drift",
    )
    require(receipt["calibration"] == {"performed": False}, "phase3 calibration drift")
    require(
        receipt["claim_boundary"]
        == "helper-reported-physical-cuda-streaming-and-scalar-parity-not-independent-hardware-attestation",
        "phase3 claim boundary drift",
    )

    items = request["items"]
    requested_chunk = request["requested_chunk_items"]
    pinned_limit = request["host_pinned_limit_bytes"]
    accelerator_limit = request["accelerator_limit_bytes"]
    require(
        type(items) is int
        and 0 < items <= U64_MAX
        and type(requested_chunk) is int
        and 0 < requested_chunk <= U64_MAX
        and type(pinned_limit) is int
        and 8 < pinned_limit <= U64_MAX
        and type(accelerator_limit) is int
        and 8 < accelerator_limit <= U64_MAX
        and type(request["device_ordinal"]) is int
        and 0 <= request["device_ordinal"] <= U32_MAX,
        "phase3 invalid retained stream bounds",
    )
    effective_chunk = min(
        items,
        requested_chunk,
        (pinned_limit - 8) // 8,
        (accelerator_limit - 8) // 8,
        U64_MAX // 8,
    )
    require(effective_chunk > 0, "phase3 effective chunk is empty")
    chunk_count = (items + effective_chunk - 1) // effective_chunk
    peak_bytes = effective_chunk * 8 + 8

    effective = receipt["effective_execution"]
    require(effective["backend"] == "nvidia-cuda", "phase3 backend drift")
    require(
        type(effective["effective_chunk_items"]) is int
        and effective["effective_chunk_items"] == effective_chunk,
        "phase3 effective chunk geometry drift",
    )
    require(
        type(effective["chunk_count"]) is int
        and effective["chunk_count"] == chunk_count,
        "phase3 chunk count drift",
    )
    require(
        type(effective["event_records"]) is int
        and effective["event_records"] == chunk_count * 3,
        "phase3 CUDA event count drift",
    )
    require(
        effective["reduction"] == "host-ordered-wrapping-u64-partials",
        "phase3 reduction drift",
    )

    memory = receipt["memory_plan"]
    require(
        memory["physically_materialized"] is True,
        "phase3 physical materialization claim missing",
    )
    require(
        type(memory["host_pinned_peak_bytes"]) is int
        and memory["host_pinned_peak_bytes"] == peak_bytes
        and type(memory["accelerator_peak_bytes"]) is int
        and memory["accelerator_peak_bytes"] == peak_bytes,
        "phase3 peak memory geometry drift",
    )
    require(
        type(memory["partial_bytes"]) is int and memory["partial_bytes"] == 8,
        "phase3 partial byte width drift",
    )
    require(
        type(memory["pinned_staging_allocations"]) is int
        and memory["pinned_staging_allocations"] == 1
        and type(memory["pinned_partial_allocations"]) is int
        and memory["pinned_partial_allocations"] == 1
        and type(memory["device_pool_allocations"]) is int
        and memory["device_pool_allocations"] == 1
        and type(memory["device_partial_allocations"]) is int
        and memory["device_partial_allocations"] == 1,
        "phase3 reusable allocation geometry drift",
    )
    require(memory["reuse_across_chunks"] is True, "phase3 reuse claim drift")
    require(
        receipt["verification"]
        == {
            "kind": "scalar-reference-equality",
            "checksum": expected_checksum,
            "reference": expected_checksum,
            "verified": True,
        },
        "phase3 oracle drift",
    )



def verify_phase3() -> None:
    multi = load_json("phase3/multi-chunk.json")
    single = load_json("phase3/one-chunk.json")
    verify_stream_receipt(
        multi,
        expected_request={
            "command": "verify",
            "items": 100000,
            "requested_chunk_items": 4096,
            "host_pinned_limit_bytes": 32776,
            "accelerator_limit_bytes": 32776,
            "device_ordinal": 0,
        },
        expected_checksum=FULL_CHECKSUM,
    )
    verify_stream_receipt(
        single,
        expected_request={
            "command": "verify",
            "items": 1000,
            "requested_chunk_items": 1000,
            "host_pinned_limit_bytes": 8008,
            "accelerator_limit_bytes": 8008,
            "device_ordinal": 0,
        },
        expected_checksum="d3886842145b489c",
    )
    verify_environment("phase3/environment.txt")


def materially_faster(candidate_ns: int, canonical_ns: int, near_tie_bps: int) -> bool:
    require(
        type(candidate_ns) is int and type(canonical_ns) is int,
        "calibration cost comparison requires integers",
    )
    require(
        0 <= candidate_ns <= U128_MAX and 0 <= canonical_ns <= U128_MAX,
        "calibration cost comparison exceeds u128",
    )
    require(
        type(near_tie_bps) is int and 0 <= near_tie_bps < 10_000,
        "calibration near-tie basis points out of range",
    )
    if candidate_ns >= canonical_ns:
        return False
    improvement = canonical_ns - candidate_ns
    lhs = improvement * 10_000
    rhs = canonical_ns * near_tie_bps
    require(lhs <= U128_MAX and rhs <= U128_MAX, "near-tie arithmetic overflow")
    return lhs > rhs


def validate_cost_observation(
    observation: dict,
    *,
    candidate: dict,
    work_units: int,
    context: str,
) -> None:
    require(
        observation["candidate_id"] == candidate["id"],
        f"{context}: observation candidate drift",
    )
    require(
        type(work_units) is int and 0 < work_units <= U64_MAX,
        f"{context}: invalid expected work size",
    )
    require(
        type(observation["work_units"]) is int
        and 0 < observation["work_units"] <= U64_MAX,
        f"{context}: invalid observation work size",
    )
    require(
        observation["work_units"] == work_units,
        f"{context}: observation work size drift",
    )
    for field in ("service_ns", "setup_ns", "transfer_ns", "total_ns"):
        require(
            type(observation[field]) is int and 0 <= observation[field] <= U128_MAX,
            f"{context}: invalid {field}",
        )
    total = (
        observation["service_ns"]
        + observation["setup_ns"]
        + observation["transfer_ns"]
    )
    require(total <= U128_MAX, f"{context}: calibration cost arithmetic overflow")
    require(
        observation["total_ns"] == total,
        f"{context}: calibration total cost drift",
    )
    require(observation["verified"] is True, f"{context}: unverified observation")
    require(
        observation["checksum"] == smoke_reference(work_units),
        f"{context}: observation disagrees with scalar oracle",
    )

    backend = candidate["backend"]
    effective_workers = observation["effective_cpu_workers"]
    require(
        type(effective_workers) is int and effective_workers >= 0,
        f"{context}: invalid effective CPU worker count",
    )
    if backend == "cpu":
        require(
            observation["setup_ns"] == 0 and observation["transfer_ns"] == 0,
            f"{context}: CPU observation has separate setup/transfer cost",
        )
        expected_effective_workers = min(candidate["cpu_workers"], work_units)
        require(
            effective_workers == expected_effective_workers,
            f"{context}: CPU effective workers drift",
        )
    elif backend == "accelerator":
        require(
            effective_workers == 0,
            f"{context}: accelerator observation reports CPU workers",
        )
        require(
            observation["total_ns"] > 0,
            f"{context}: accelerator total cost must be positive",
        )
        require(
            observation["setup_ns"] <= U64_MAX
            and observation["transfer_ns"] <= U64_MAX,
            f"{context}: accelerator timing component width drift",
        )
        accelerator_total_max = 2 * U64_MAX
        require(
            observation["service_ns"] <= accelerator_total_max
            and observation["total_ns"] <= accelerator_total_max,
            f"{context}: accelerator service/total provenance width drift",
        )
    elif backend == "heterogeneous-static":
        require(
            observation["setup_ns"] == 0 and observation["transfer_ns"] == 0,
            f"{context}: heterogeneous observation has separately isolated setup/transfer cost",
        )
        expected_effective_workers = min(candidate["cpu_workers"], work_units // 2)
        require(
            effective_workers == expected_effective_workers,
            f"{context}: heterogeneous effective workers drift",
        )
    else:
        raise SystemExit(f"{context}: unknown candidate backend")


def verify_calibration_receipt(
    receipt: dict,
    *,
    expected_request: dict,
    context: str,
) -> None:
    require(
        REQUIRED_RECEIPT_SECTIONS <= receipt.keys(),
        f"{context}: calibration receipt missing common evidence sections",
    )
    require(
        receipt["schema"] == "qsol.mesh.calibrated-plan-receipt.v2",
        f"{context}: calibration schema drift",
    )
    require(
        receipt["source_identity"]
        == {
            "runtime": "qsol-mesh-cli",
            "plan_identity": "mesh-calibration-smoke-v1",
            "plan_version": "2.0.0",
        },
        f"{context}: calibration source identity drift",
    )
    require(
        receipt["workload_identity"] == {"workload_id": "mesh-smoke-v1"},
        f"{context}: calibration workload identity drift",
    )
    require(
        receipt["memory_plan"] == {"physical_memory_claim": False},
        f"{context}: calibration memory claim drift",
    )
    require(
        receipt["claim_boundary"]
        == "host-specific-helper-reported-CUDA-calibration-not-universal-performance-or-kernel-overlap-evidence",
        f"{context}: calibration claim boundary drift",
    )

    request = receipt["requested_configuration"]
    require(request == expected_request, f"{context}: calibration request drift")
    require(
        type(request["calibration_items"]) is int
        and type(request["full_work_items"]) is int
        and 2 <= request["calibration_items"] <= request["full_work_items"] <= U64_MAX,
        f"{context}: calibration work bounds drift",
    )
    require(
        type(request["repeats"]) is int and request["repeats"] > 0,
        f"{context}: calibration repeat bound drift",
    )
    require(
        type(request["near_tie_bps"]) is int and 0 <= request["near_tie_bps"] <= 9999,
        f"{context}: calibration near-tie bound drift",
    )
    require(
        type(request["device_ordinal"]) is int
        and 0 <= request["device_ordinal"] <= U32_MAX,
        f"{context}: calibration device bound drift",
    )
    require(
        receipt["verification"]
        == {"kind": "scalar-oracle-plus-full-work-confirmation", "verified": True},
        f"{context}: calibration verification drift",
    )

    topology = receipt["observed_topology"]
    require(
        topology
        == {
            "available_cpu_workers": 32,
            "device_ordinal": request["device_ordinal"],
            "accelerator_observed": True,
            "cuda_compute_major": 12,
            "cuda_compute_minor": 0,
            "cuda_runtime_version": 12040,
            "cuda_driver_version": 13020,
            "cuda_topology_source": "canonical-helper-reported",
        },
        f"{context}: CUDA calibration topology/identity drift",
    )

    calibration = receipt["calibration"]
    candidates = calibration["candidates"]
    observations = calibration["observations"]
    expected_candidates = [
        {
            "id": 0,
            "backend": "cpu",
            "cpu_workers": 1,
            "accelerator_share_bps": 0,
            "canonical": True,
        },
        {
            "id": 1,
            "backend": "cpu",
            "cpu_workers": topology["available_cpu_workers"],
            "accelerator_share_bps": 0,
            "canonical": False,
        },
        {
            "id": 2,
            "backend": "accelerator",
            "cpu_workers": 0,
            "accelerator_share_bps": 10_000,
            "canonical": False,
        },
        {
            "id": 3,
            "backend": "heterogeneous-static",
            "cpu_workers": topology["available_cpu_workers"],
            "accelerator_share_bps": 5_000,
            "canonical": False,
        },
    ]
    require(
        type(calibration["candidate_budget"]) is int
        and calibration["candidate_budget"] == 4,
        f"{context}: calibration candidate budget drift",
    )
    require(
        all(
            type(candidate.get("id")) is int
            and 0 <= candidate["id"] <= U32_MAX
            and type(candidate.get("cpu_workers")) is int
            and candidate["cpu_workers"] >= 0
            and type(candidate.get("accelerator_share_bps")) is int
            and 0 <= candidate["accelerator_share_bps"] <= 10_000
            and type(candidate.get("canonical")) is bool
            for candidate in candidates
        ),
        f"{context}: calibration candidate field types drift",
    )
    require(
        candidates == expected_candidates,
        f"{context}: calibration candidate geometry drift",
    )
    require(
        calibration["cost_scopes"]
        == {
            "cpu": "run_smoke-end-to-end",
            "accelerator": "median-sample-launcher-plus-verification-host-wall-partitioned-by-nested-setup-and-D2H",
            "heterogeneous-static": "full-static-call-end-to-end",
        },
        f"{context}: calibration cost scope drift",
    )
    require(
        calibration["cross_clock_kernel_timing_added"] is False,
        f"{context}: CUDA event timing became additive",
    )

    candidate_by_id = {candidate["id"]: candidate for candidate in candidates}
    require(
        all(
            type(observation.get("candidate_id")) is int
            and 0 <= observation["candidate_id"] <= U32_MAX
            for observation in observations
        ),
        f"{context}: calibration observation candidate ID type drift",
    )
    observation_ids = [observation["candidate_id"] for observation in observations]
    require(
        len(observations) == len(candidates)
        and len(set(observation_ids)) == len(observation_ids)
        and set(observation_ids) == set(candidate_by_id),
        f"{context}: observations do not cover every candidate exactly once",
    )
    for observation in observations:
        validate_cost_observation(
            observation,
            candidate=candidate_by_id[observation["candidate_id"]],
            work_units=request["calibration_items"],
            context=f"{context} calibration candidate {observation['candidate_id']}",
        )

    calibration_by_id = {
        observation["candidate_id"]: observation for observation in observations
    }
    canonical_id = 0
    calibration_winner = min(
        candidate_by_id,
        key=lambda candidate_id: (
            calibration_by_id[candidate_id]["total_ns"],
            candidate_id,
        ),
    )
    canonical_calibration = calibration_by_id[canonical_id]
    winner_calibration = calibration_by_id[calibration_winner]
    if calibration_winner == canonical_id or not materially_faster(
        winner_calibration["total_ns"],
        canonical_calibration["total_ns"],
        request["near_tie_bps"],
    ):
        provisional = canonical_id
    else:
        provisional = calibration_winner

    required_confirmation_ids = (
        [canonical_id] if provisional == canonical_id else [canonical_id, provisional]
    )
    confirmation = calibration["full_work_confirmation"]
    require(
        all(
            type(observation.get("candidate_id")) is int
            and 0 <= observation["candidate_id"] <= U32_MAX
            for observation in confirmation
        ),
        f"{context}: confirmation candidate ID type drift",
    )
    confirmation_ids = [observation["candidate_id"] for observation in confirmation]
    require(
        len(confirmation) == len(required_confirmation_ids)
        and len(set(confirmation_ids)) == len(confirmation_ids)
        and set(confirmation_ids) == set(required_confirmation_ids),
        f"{context}: full-work confirmation candidate coverage drift",
    )
    for observation in confirmation:
        validate_cost_observation(
            observation,
            candidate=candidate_by_id[observation["candidate_id"]],
            work_units=request["full_work_items"],
            context=f"{context} confirmation candidate {observation['candidate_id']}",
        )
    confirmation_by_id = {
        observation["candidate_id"]: observation for observation in confirmation
    }

    if provisional == canonical_id:
        selected = canonical_id
        selection_reason = "canonical-kept-after-calibration-near-tie"
    else:
        canonical_full = confirmation_by_id[canonical_id]
        provisional_full = confirmation_by_id[provisional]
        if materially_faster(
            provisional_full["total_ns"],
            canonical_full["total_ns"],
            request["near_tie_bps"],
        ):
            selected = provisional
            selection_reason = "promoted-after-full-work-confirmation"
        else:
            selected = canonical_id
            selection_reason = "canonical-restored-after-full-work-near-tie"

    effective = receipt["effective_execution"]
    require(
        effective["kind"] == "calibration-and-planning",
        f"{context}: calibration effective kind drift",
    )
    require(
        all(
            type(effective.get(field)) is int
            and 0 <= effective[field] <= U32_MAX
            for field in (
                "provisional_candidate_id",
                "selected_candidate_id",
                "canonical_candidate_id",
            )
        ),
        f"{context}: effective candidate ID type drift",
    )
    require(
        effective["provisional_candidate_id"] == provisional
        and effective["selected_candidate_id"] == selected
        and effective["canonical_candidate_id"] == canonical_id
        and effective["canonical_retained"] is (selected == canonical_id)
        and effective["selection_reason"] == selection_reason,
        f"{context}: measured selection history drift",
    )
    selected_candidate = candidate_by_id[selected]
    selected_confirmation = confirmation_by_id[selected]
    require(
        type(effective.get("selected_requested_cpu_workers")) is int
        and 0 <= effective["selected_requested_cpu_workers"] <= topology["available_cpu_workers"]
        and type(effective.get("selected_effective_cpu_workers")) is int
        and 0 <= effective["selected_effective_cpu_workers"] <= topology["available_cpu_workers"],
        f"{context}: selected worker field types/bounds drift",
    )
    require(
        effective["selected_requested_cpu_workers"] == selected_candidate["cpu_workers"]
        and effective["selected_effective_cpu_workers"]
        == selected_confirmation["effective_cpu_workers"],
        f"{context}: selected worker evidence drift",
    )



def verify_phase4() -> None:
    timing = load_json("phase4/timing.json")
    calibration = load_json("phase4/calibration.json")

    require(
        timing["schema"] == "qsol.mesh.cuda-smoke-receipt.v2",
        "phase4 timing schema drift",
    )
    require(
        timing["requested_configuration"]
        == {
            "command": "verify",
            "items": 100000,
            "device_ordinal": 0,
            "helper_path": "/home/trent/qsolmesh-dev/QSOL-MESH/target/mesh-cuda-smoke",
            "timing": True,
        },
        "phase4 timing request drift",
    )
    require(
        timing["source_identity"]
        == {
            "runtime": "qsol-mesh-cli",
            "executor_id": "qsol-mesh-cuda-smoke-v1",
            "worker_protocol": "qsol.mesh.cuda-smoke-worker.v2",
            "base_executor_contract": "qsol.mesh.nvidia-executor-contract.v1",
        },
        "phase4 timing source identity drift",
    )
    require(
        timing["workload_identity"]
        == {"workload_id": "mesh-smoke-v1", "workload_contract_version": "1.0.0"},
        "phase4 timing workload identity drift",
    )
    timing_topology = timing["observed_topology"]
    require(
        timing_topology
        == {
            "accelerator_observed": True,
            "backend": "nvidia-cuda",
            "device_ordinal": timing["requested_configuration"]["device_ordinal"],
            "compute_major": 12,
            "compute_minor": 0,
            "cuda_runtime_version": 12040,
            "cuda_driver_version": 13020,
            "evidence_source": "cuda-helper-process",
        },
        "phase4 timing CUDA topology drift",
    )
    timing_effective = timing["effective_execution"]
    require(
        timing_effective["backend"] == "nvidia-cuda"
        and timing_effective["device_ordinal"]
        == timing["requested_configuration"]["device_ordinal"]
        and type(timing_effective["blocks"]) is int
        and timing_effective["blocks"] == CUDA_RETAINED_BLOCKS
        and type(timing_effective["threads_per_block"]) is int
        and timing_effective["threads_per_block"] == CUDA_THREADS_PER_BLOCK
        and timing_effective["reduction"]
        == "device-strided-local-sums-plus-atomicAdd-u64",
        "phase4 timing effective CUDA execution drift",
    )
    require(
        timing["memory_plan"]
        == {
            "domains": ["accelerator-local", "host-pageable"],
            "accelerator_checksum_buffer_bytes": 8,
            "device_to_host_result_bytes": 8,
            "per_item_materialization": False,
        },
        "phase4 timing memory plan drift",
    )
    require(
        timing["calibration"]
        == {"performed": False, "placement_decision_influenced": False},
        "phase4 timing calibration boundary drift",
    )
    require(
        timing["claim_boundary"]
        == "experimental-nvidia-cuda-smoke-separated-timing-evidence-not-placement-not-performance-evidence",
        "phase4 timing claim boundary drift",
    )
    require(
        timing["verification"]
        == {
            "kind": "scalar-reference-equality",
            "checksum": FULL_CHECKSUM,
            "reference": FULL_CHECKSUM,
            "verified": True,
        },
        "phase4 timing oracle drift",
    )
    values = timing["timing"]
    require(
        values["clock_sources"]
        == {
            "launcher_total_ns": "rust-std-instant-monotonic",
            "worker_total_ns": "cxx-std-steady-clock-monotonic",
            "setup_host_ns": "cxx-std-steady-clock-monotonic",
            "kernel_device_ns": "cuda-event-default-stream",
            "transfer_host_ns": "cxx-std-steady-clock-monotonic",
            "teardown_host_ns": "cxx-std-steady-clock-monotonic",
            "verification_ns": "rust-std-instant-monotonic",
        },
        "phase4 timing clock source drift",
    )
    require(
        values["synchronization"]
        == {
            "kernel": "cuda-event-start-kernel-event-stop-device-synchronize",
            "transfer": "synchronous-cudaMemcpy-device-to-host-after-device-synchronize",
            "host_destination": "pageable-stack-u64",
        },
        "phase4 timing synchronization drift",
    )
    require(
        values["cross_clock_additive_total"] is False,
        "phase4 cross-clock timing boundary drift",
    )
    timing_fields = (
        "launcher_total_ns",
        "worker_total_ns",
        "setup_host_ns",
        "kernel_device_ns",
        "transfer_host_ns",
        "teardown_host_ns",
        "verification_ns",
    )
    for key in timing_fields:
        require(
            type(values[key]) is int and 0 <= values[key] <= U64_MAX,
            f"phase4 invalid timing field: {key}",
        )
    require(values["worker_total_ns"] > 0, "phase4 worker total must be nonzero")
    host_component_sum = (
        values["setup_host_ns"]
        + values["transfer_host_ns"]
        + values["teardown_host_ns"]
    )
    require(
        host_component_sum <= U64_MAX,
        "phase4 host timing component sum overflow",
    )
    require(
        host_component_sum <= values["worker_total_ns"],
        "phase4 host timing components exceed worker total",
    )
    require(
        values["worker_total_ns"] <= values["launcher_total_ns"],
        "phase4 worker total exceeds launcher total",
    )

    verify_calibration_receipt(
        calibration,
        expected_request={
            "calibration_items": 10000,
            "full_work_items": 100000,
            "repeats": 3,
            "near_tie_bps": 500,
            "device_ordinal": 0,
        },
        context="phase4",
    )
    verify_environment("phase4/environment.txt")


def verify_phase5() -> None:
    receipt = load_json("phase5/adaptive.json")
    require(
        receipt["schema"] == "qsol.mesh.phase-runtime-receipt.v1",
        "phase5 schema drift",
    )
    require(
        receipt["source_identity"]
        == {"runtime": "qsol-mesh-cli", "contract": "qsol.mesh.phase-runtime-contract.v1"},
        "phase5 source identity drift",
    )
    require(
        receipt["workload_identity"]
        == {"workload_id": "mesh-smoke-phases-v1", "workload_contract_version": "1.0.0"},
        "phase5 workload identity drift",
    )
    require(
        receipt["observed_topology"]
        == {
            "available_cpu_workers": 32,
            "accelerator_observed": True,
            "details": "per-phase-calibration-receipts",
        },
        "phase5 observed topology drift",
    )
    require(
        receipt["memory_plan"]
        == {
            "per_item_materialization": False,
            "phase_state_bound": 64,
            "persistent_cuda_context": False,
        },
        "phase5 memory/lifecycle claim drift",
    )
    require(
        receipt["calibration"]
        == {
            "performed_before_every_phase": True,
            "candidate_budget_per_phase": 4,
            "cached": False,
            "calibration_host_scope": "calibrator-call-plus-plan-validation",
            "execution_host_scope": "selected-executor-call-plus-phase-oracle-validation",
        },
        "phase5 calibration boundary drift",
    )
    require(
        receipt["claim_boundary"]
        == "bounded-phase-boundary-replanning-only-not-work-stealing-kernel-overlap-or-universal-speedup",
        "phase5 claim boundary drift",
    )

    request = receipt["requested_configuration"]
    expected_request = {
        "command": "verify",
        "phase_items": [1000, 100000, 10000],
        "calibration_items": 10000,
        "repeats": 3,
        "near_tie_bps": 500,
        "cuda": True,
        "device_ordinal": 0,
    }
    require(request == expected_request, "phase5 request drift")
    require(
        1 <= len(request["phase_items"]) <= 64,
        "phase5 phase count bound drift",
    )
    minimum_items = 2 if request["cuda"] else 1
    require(
        type(request["calibration_items"]) is int
        and request["calibration_items"] >= minimum_items
        and all(
            type(items) is int and items >= minimum_items
            for items in request["phase_items"]
        ),
        "phase5 phase/calibration item bound drift",
    )
    require(
        type(request["repeats"]) is int and 1 <= request["repeats"] <= 31,
        "phase5 repeats bound drift",
    )
    require(
        type(request["near_tie_bps"]) is int
        and 0 <= request["near_tie_bps"] <= 9999,
        "phase5 near-tie bound drift",
    )
    require(
        type(request["device_ordinal"]) is int
        and 0 <= request["device_ordinal"] <= U32_MAX,
        "phase5 device bound drift",
    )
    total_phase_items = sum(request["phase_items"])
    require(total_phase_items <= U64_MAX, "phase5 total phase items overflow u64")

    effective = receipt["effective_execution"]
    require(
        effective["kind"] == "phase-boundary-replanning-and-execution",
        "phase5 effective execution kind drift",
    )
    expected = [
        (0, 1000, "d3886842145b489c"),
        (1, 100000, FULL_CHECKSUM),
        (2, 10000, "7cf0a1247592acff"),
    ]
    require(
        type(effective["completed_phases"]) is int
        and effective["completed_phases"] == len(expected)
        and effective["completed_phases"] == len(request["phase_items"])
        and len(effective["phases"]) == len(expected),
        "phase5 requested/completed/retained phase count mismatch",
    )
    require(
        type(effective["plan_changes"]) is int
        and 0 <= effective["plan_changes"] <= max(0, len(effective["phases"]) - 1)
        and effective["plan_changes"] == 0
        and effective["within_phase_replanning"] is False,
        "phase5 adaptive boundary drift",
    )

    observed_plan_changes = 0
    previous_selected = None
    phase_checksums = []
    for phase, (index, items, checksum) in zip(effective["phases"], expected):
        require(
            type(phase["phase_index"]) is int
            and phase["phase_index"] == index
            and type(phase["items"]) is int
            and phase["items"] == items,
            "phase5 phase identity drift",
        )
        require(
            type(phase["calibration_host_ns"]) is int
            and 0 <= phase["calibration_host_ns"] <= U128_MAX,
            f"phase5 phase {index}: invalid calibration_host_ns",
        )
        require(
            type(phase["execution_host_ns"]) is int
            and 0 < phase["execution_host_ns"] <= U128_MAX,
            f"phase5 phase {index}: invalid execution_host_ns",
        )

        expected_calibration_items = min(request["calibration_items"], items)
        calibration_receipt = phase["calibration_receipt"]
        verify_calibration_receipt(
            calibration_receipt,
            expected_request={
                "calibration_items": expected_calibration_items,
                "full_work_items": items,
                "repeats": request["repeats"],
                "near_tie_bps": request["near_tie_bps"],
                "device_ordinal": request["device_ordinal"],
            },
            context=f"phase5 phase {index}",
        )
        nested_totals = [
            observation["total_ns"]
            for observation in (
                calibration_receipt["calibration"]["observations"]
                + calibration_receipt["calibration"]["full_work_confirmation"]
            )
        ]
        nested_sum = sum(nested_totals)
        repeat_lower_bound_factor = request["repeats"] - request["repeats"] // 2
        require(
            nested_totals
            and nested_sum <= U128_MAX
            and repeat_lower_bound_factor > 0
            and nested_sum <= U128_MAX // repeat_lower_bound_factor
            and phase["calibration_host_ns"]
            >= nested_sum * repeat_lower_bound_factor,
            f"phase5 phase {index}: calibration host duration shorter than repeat-aware sequential nested measurements",
        )
        selected_id = calibration_receipt["effective_execution"]["selected_candidate_id"]
        selected_candidate = next(
            candidate
            for candidate in calibration_receipt["calibration"]["candidates"]
            if candidate["id"] == selected_id
        )
        expected_plan_changed = (
            previous_selected is not None and selected_candidate != previous_selected
        )
        require(
            phase["plan_changed"] is expected_plan_changed,
            "phase5 per-phase plan change flag drift",
        )
        observed_plan_changes += int(expected_plan_changed)
        previous_selected = selected_candidate

        backend = selected_candidate["backend"]
        require(
            backend == "cpu",
            "phase5 selected CUDA/heterogeneous execution lacks retained private execution provenance",
        )
        expected_cpu_items = {
            "cpu": items,
            "accelerator": 0,
            "heterogeneous-static": items // 2,
        }[backend]
        expected_cuda_items = items - expected_cpu_items
        expected_requested_workers = selected_candidate["cpu_workers"]
        expected_effective_workers = min(
            expected_requested_workers,
            expected_cpu_items,
        )

        execution = phase["execution"]
        require(
            type(execution.get("requested_cpu_workers")) is int
            and 0 <= execution["requested_cpu_workers"] <= receipt["observed_topology"]["available_cpu_workers"]
            and type(execution.get("effective_cpu_workers")) is int
            and 0 <= execution["effective_cpu_workers"] <= receipt["observed_topology"]["available_cpu_workers"]
            and type(execution.get("cpu_items")) is int
            and 0 <= execution["cpu_items"] <= items
            and type(execution.get("cuda_items")) is int
            and 0 <= execution["cuda_items"] <= items,
            "phase5 execution geometry field types/bounds drift",
        )
        require(
            execution["backend"] == backend
            and execution["requested_cpu_workers"] == expected_requested_workers
            and execution["effective_cpu_workers"] == expected_effective_workers
            and execution["cpu_items"] == expected_cpu_items
            and execution["cuda_items"] == expected_cuda_items,
            "phase5 execution does not match selected plan",
        )
        require(
            execution["verified"] is True
            and execution["checksum"] == checksum
            and execution["reference"] == checksum
            and execution["checksum"] == smoke_reference(items),
            "phase5 phase oracle drift",
        )
        phase_checksums.append(int(execution["checksum"], 16))

    require(
        observed_plan_changes == effective["plan_changes"],
        "phase5 plan change count drift",
    )
    aggregate = sum(phase_checksums) & U64_MAX
    aggregate_hex = f"{aggregate:016x}"
    require(
        receipt["verification"]
        == {
            "kind": "per-phase-scalar-oracle-and-phase-order-wrapping-u64",
            "checksum": aggregate_hex,
            "reference": aggregate_hex,
            "verified": True,
        },
        "phase5 aggregate verification drift",
    )
    verify_environment("phase5/environment.txt")



def main() -> None:
    require(EVIDENCE.is_dir(), f"retained evidence directory missing: {EVIDENCE}")
    verify_hashes()
    verify_phase1()
    verify_phase3()
    verify_phase4()
    verify_phase5()
    print("retained full CUDA-host evidence 2026-09-27: valid")


if __name__ == "__main__":
    main()
