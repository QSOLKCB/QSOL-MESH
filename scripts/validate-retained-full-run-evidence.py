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
U64_MAX = (1 << 64) - 1
U32_MAX = (1 << 32) - 1
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
    require(f"source_commit={SOURCE_COMMIT}" in text, f"{relative}: source commit drift")
    require("rustc 1.85.1" in text, f"{relative}: pinned Rust compiler missing")
    require("nvcc_path=/usr/bin/nvcc" in text, f"{relative}: CUDA compiler path drift")
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

    require(
        0 < cpu_items < items,
        "phase1 split must contain two nonempty partitions",
    )
    require(
        (cpu["range_start"], cpu["range_end"]) == (0, cpu_items),
        "phase1 CPU split range drift",
    )
    require(
        (cuda["range_start"], cuda["range_end"]) == (cpu_items, items),
        "phase1 CUDA split range drift",
    )
    require(
        cpu["requested_workers"] == request["cpu_workers"],
        "phase1 split requested CPU workers drift",
    )
    require(
        type(cpu["effective_workers"]) is int
        and 1 <= cpu["effective_workers"] <= min(request["cpu_workers"], cpu_items),
        "phase1 split effective CPU workers drift",
    )
    require(
        cuda["device_ordinal"] == request["device_ordinal"],
        "phase1 split CUDA device drift",
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
        cpu["requested_configuration"]
        == {"command": "verify", "items": 100000, "workers": 8},
        "phase1 CPU request drift",
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
    require(cuda["requested_configuration"]["command"] == "verify", "phase1 CUDA activation drift")
    require(cuda["requested_configuration"]["items"] == 100000, "phase1 CUDA item count drift")
    require(cuda["requested_configuration"]["device_ordinal"] == 0, "phase1 CUDA device drift")
    topo = cuda["observed_topology"]
    require(
        topo["accelerator_observed"] is True
        and topo["compute_major"] == 12
        and topo["compute_minor"] == 0,
        "phase1 CUDA topology drift",
    )
    require(
        topo["cuda_runtime_version"] == 12040
        and topo["cuda_driver_version"] == 13020,
        "phase1 CUDA version drift",
    )
    require(
        cuda["verification"]["verified"] is True
        and cuda["verification"]["checksum"] == FULL_CHECKSUM
        and cuda["verification"]["reference"] == FULL_CHECKSUM,
        "phase1 CUDA oracle drift",
    )

    require(
        static["schema"] == "qsol.mesh.static-split-receipt.v1",
        "phase1 static schema drift",
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
    effective = static["effective_execution"]
    require(
        effective["concurrent"] is False and effective["adaptive"] is False,
        "phase1 static claim boundary drift",
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
    effective = concurrent["effective_execution"]
    require(
        effective["concurrent_dispatch"] is True and effective["adaptive"] is False,
        "phase1 concurrent dispatch drift",
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
        concurrent["verification"]["verified"] is True
        and concurrent["verification"]["checksum"] == FULL_CHECKSUM
        and concurrent["verification"]["reference"] == FULL_CHECKSUM,
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
        receipt["schema"] == "qsol.mesh.cuda-stream-receipt.v1",
        "phase3 stream schema drift",
    )
    request = receipt["requested_configuration"]
    require(request == expected_request, "phase3 stream request drift")
    require(
        receipt["observed_topology"]["accelerator_observed"] is True,
        "phase3 accelerator observation missing",
    )
    require(
        receipt["observed_topology"]["device_ordinal"] == request["device_ordinal"],
        "phase3 observed CUDA device drift",
    )

    items = request["items"]
    requested_chunk = request["requested_chunk_items"]
    pinned_limit = request["host_pinned_limit_bytes"]
    accelerator_limit = request["accelerator_limit_bytes"]
    require(
        items > 0
        and requested_chunk > 0
        and pinned_limit > 8
        and accelerator_limit > 8,
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
        effective["effective_chunk_items"] == effective_chunk,
        "phase3 effective chunk geometry drift",
    )
    require(effective["chunk_count"] == chunk_count, "phase3 chunk count drift")
    require(
        effective["event_records"] == chunk_count * 3,
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
        memory["host_pinned_peak_bytes"] == peak_bytes
        and memory["accelerator_peak_bytes"] == peak_bytes,
        "phase3 peak memory geometry drift",
    )
    require(memory["partial_bytes"] == 8, "phase3 partial byte width drift")
    require(
        memory["pinned_staging_allocations"] == 1
        and memory["pinned_partial_allocations"] == 1
        and memory["device_pool_allocations"] == 1
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


def verify_calibration_receipt(
    receipt: dict,
    *,
    expected_request: dict,
    context: str,
) -> None:
    require(
        receipt["schema"] == "qsol.mesh.calibrated-plan-receipt.v2",
        f"{context}: calibration schema drift",
    )
    request = receipt["requested_configuration"]
    require(request == expected_request, f"{context}: calibration request drift")
    require(
        2 <= request["calibration_items"] <= request["full_work_items"] <= U64_MAX,
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

    calibration = receipt["calibration"]
    candidates = calibration["candidates"]
    observations = calibration["observations"]
    require(
        calibration["candidate_budget"] == 4 and len(candidates) == 4,
        f"{context}: candidate budget drift",
    )
    require(
        [candidate["id"] for candidate in candidates] == [0, 1, 2, 3],
        f"{context}: candidate ID set drift",
    )
    require(
        [candidate["backend"] for candidate in candidates]
        == ["cpu", "cpu", "accelerator", "heterogeneous-static"],
        f"{context}: candidate backend set drift",
    )
    require(
        [candidate["canonical"] for candidate in candidates] == [True, False, False, False],
        f"{context}: canonical candidate drift",
    )

    candidate_ids = {candidate["id"] for candidate in candidates}
    observation_ids = [observation["candidate_id"] for observation in observations]
    require(
        len(observations) == len(candidates)
        and len(set(observation_ids)) == len(observation_ids)
        and set(observation_ids) == candidate_ids,
        f"{context}: observations do not cover every candidate exactly once",
    )
    for observation in observations:
        work_units = observation["work_units"]
        require(
            work_units == request["calibration_items"],
            f"{context}: calibration observation work size drift",
        )
        require(
            observation["verified"] is True,
            f"{context}: unverified calibration observation",
        )
        require(
            observation["checksum"] == smoke_reference(work_units),
            f"{context}: calibration observation disagrees with scalar oracle",
        )

    require(
        calibration["cross_clock_kernel_timing_added"] is False,
        f"{context}: CUDA event timing became additive",
    )

    effective = receipt["effective_execution"]
    require(
        effective["selected_candidate_id"] in candidate_ids
        and effective["canonical_candidate_id"] in candidate_ids,
        f"{context}: selected/canonical candidate is outside candidate set",
    )
    require(
        effective["selected_candidate_id"] == 0
        and effective["canonical_candidate_id"] == 0
        and effective["canonical_retained"] is True,
        f"{context}: selected candidate drift",
    )
    require(
        effective["selection_reason"] == "canonical-kept-after-calibration-near-tie",
        f"{context}: selection reason drift",
    )

    confirmation = calibration["full_work_confirmation"]
    require(
        len(confirmation) == 1,
        f"{context}: full-work confirmation cardinality drift",
    )
    confirmed = confirmation[0]
    require(
        confirmed["candidate_id"] == effective["selected_candidate_id"],
        f"{context}: full-work confirmation candidate drift",
    )
    require(
        confirmed["work_units"] == request["full_work_items"],
        f"{context}: full-work confirmation size drift",
    )
    require(
        confirmed["verified"] is True
        and confirmed["checksum"] == smoke_reference(confirmed["work_units"]),
        f"{context}: full-work confirmation disagrees with scalar oracle",
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
        timing["verification"]["verified"] is True
        and timing["verification"]["checksum"] == FULL_CHECKSUM
        and timing["verification"]["reference"] == FULL_CHECKSUM,
        "phase4 timing oracle drift",
    )
    values = timing["timing"]
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
        and all(type(items) is int and items >= minimum_items for items in request["phase_items"]),
        "phase5 phase/calibration item bound drift",
    )
    require(
        type(request["repeats"]) is int and 1 <= request["repeats"] <= 31,
        "phase5 repeats bound drift",
    )
    require(
        type(request["near_tie_bps"]) is int and 0 <= request["near_tie_bps"] <= 9999,
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
    expected = [
        (0, 1000, "d3886842145b489c"),
        (1, 100000, FULL_CHECKSUM),
        (2, 10000, "7cf0a1247592acff"),
    ]
    require(
        effective["completed_phases"] == len(expected)
        and effective["completed_phases"] == len(request["phase_items"])
        and len(effective["phases"]) == len(expected),
        "phase5 requested/completed/retained phase count mismatch",
    )
    require(
        effective["plan_changes"] == 0
        and effective["within_phase_replanning"] is False,
        "phase5 adaptive boundary drift",
    )

    observed_plan_changes = 0
    for phase, (index, items, checksum) in zip(effective["phases"], expected):
        require(
            phase["phase_index"] == index
            and phase["items"] == items
            and phase["plan_changed"] is False,
            "phase5 phase identity drift",
        )
        observed_plan_changes += int(phase["plan_changed"])
        expected_calibration_items = min(request["calibration_items"], items)
        verify_calibration_receipt(
            phase["calibration_receipt"],
            expected_request={
                "calibration_items": expected_calibration_items,
                "full_work_items": items,
                "repeats": request["repeats"],
                "near_tie_bps": request["near_tie_bps"],
                "device_ordinal": request["device_ordinal"],
            },
            context=f"phase5 phase {index}",
        )
        execution = phase["execution"]
        require(
            execution["backend"] == "cpu"
            and execution["requested_cpu_workers"] == 1
            and execution["effective_cpu_workers"] == 1
            and execution["cpu_items"] == items
            and execution["cuda_items"] == 0,
            "phase5 execution backend drift",
        )
        require(
            execution["verified"] is True
            and execution["checksum"] == checksum
            and execution["reference"] == checksum
            and execution["checksum"] == smoke_reference(items),
            "phase5 phase oracle drift",
        )
    require(
        observed_plan_changes == effective["plan_changes"],
        "phase5 plan change count drift",
    )
    require(
        receipt["verification"]
        == {
            "kind": "per-phase-scalar-oracle-and-phase-order-wrapping-u64",
            "checksum": "edb20cb973a5c7e7",
            "reference": "edb20cb973a5c7e7",
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
