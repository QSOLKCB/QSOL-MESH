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
    require(REQUIRED_RECEIPT_SECTIONS <= data.keys(), f"{relative}: missing common evidence sections")
    return data


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
    require("Cuda compilation tools, release 12.4, V12.4.131" in text, f"{relative}: CUDA toolkit drift")
    require("NVIDIA GeForce RTX 5060 Ti" in text, f"{relative}: GPU identity drift")
    require("595.84" in text, f"{relative}: NVIDIA driver drift")


def verify_phase1() -> None:
    cpu = load_json("phase1/cpu-verify-100000.json")
    cuda = load_json("phase1/cuda-verify-100000.json")
    static = load_json("phase1/static-verify-100000-40000.json")
    concurrent = load_json("phase1/concurrent-verify-100000-40000.json")

    require(cpu["schema"] == "qsol.mesh.smoke-receipt.v1", "phase1 CPU schema drift")
    require(cpu["requested_configuration"] == {"command": "verify", "items": 100000, "workers": 8}, "phase1 CPU request drift")
    require(cpu["verification"] == {"kind": "scalar-reference-equality", "checksum": FULL_CHECKSUM, "reference": FULL_CHECKSUM, "verified": True}, "phase1 CPU verification drift")

    require(cuda["schema"] == "qsol.mesh.cuda-smoke-receipt.v1", "phase1 CUDA schema drift")
    require(cuda["requested_configuration"]["command"] == "verify", "phase1 CUDA activation drift")
    require(cuda["requested_configuration"]["items"] == 100000, "phase1 CUDA item count drift")
    require(cuda["requested_configuration"]["device_ordinal"] == 0, "phase1 CUDA device drift")
    topo = cuda["observed_topology"]
    require(topo["accelerator_observed"] is True and topo["compute_major"] == 12 and topo["compute_minor"] == 0, "phase1 CUDA topology drift")
    require(topo["cuda_runtime_version"] == 12040 and topo["cuda_driver_version"] == 13020, "phase1 CUDA version drift")
    require(cuda["verification"]["verified"] is True and cuda["verification"]["checksum"] == FULL_CHECKSUM and cuda["verification"]["reference"] == FULL_CHECKSUM, "phase1 CUDA oracle drift")

    require(static["schema"] == "qsol.mesh.static-split-receipt.v1", "phase1 static schema drift")
    require(static["requested_configuration"] == {"command": "verify", "items": 100000, "cpu_items": 40000, "cpu_workers": 8, "device_ordinal": 0}, "phase1 static request drift")
    effective = static["effective_execution"]
    require(effective["concurrent"] is False and effective["adaptive"] is False, "phase1 static claim boundary drift")
    require(effective["cpu"]["checksum"] == CPU_40K_CHECKSUM and effective["cuda"]["checksum"] == CUDA_60K_CHECKSUM, "phase1 static partition checksum drift")
    require(static["verification"] == {"kind": "partition-range-oracles-plus-full-scalar-reference", "cpu_reference": CPU_40K_CHECKSUM, "cuda_reference": CUDA_60K_CHECKSUM, "checksum": FULL_CHECKSUM, "reference": FULL_CHECKSUM, "verified": True}, "phase1 static oracle drift")

    require(concurrent["schema"] == "qsol.mesh.concurrent-split-receipt.v1", "phase1 concurrent schema drift")
    require(concurrent["requested_configuration"] == {"command": "verify", "items": 100000, "cpu_items": 40000, "cpu_workers": 8, "device_ordinal": 0}, "phase1 concurrent request drift")
    effective = concurrent["effective_execution"]
    require(effective["concurrent_dispatch"] is True and effective["adaptive"] is False, "phase1 concurrent dispatch drift")
    dispatch = effective["dispatch_contract"]
    require(dispatch == {"cpu_task_spawned_before_cuda_call": True, "cpu_joined_after_cuda_call_return": True, "kernel_overlap_measured": False}, "phase1 concurrent overlap claim drift")
    require(effective["cpu"]["checksum"] == CPU_40K_CHECKSUM and effective["cuda"]["checksum"] == CUDA_60K_CHECKSUM, "phase1 concurrent partition checksum drift")
    require(concurrent["verification"]["verified"] is True and concurrent["verification"]["checksum"] == FULL_CHECKSUM and concurrent["verification"]["reference"] == FULL_CHECKSUM, "phase1 concurrent oracle drift")

    verify_environment("phase1/environment.txt")


def verify_phase3() -> None:
    multi = load_json("phase3/multi-chunk.json")
    single = load_json("phase3/one-chunk.json")
    for receipt, chunks, items, checksum in ((multi, 25, 100000, FULL_CHECKSUM), (single, 1, 1000, "d3886842145b489c")):
        require(receipt["schema"] == "qsol.mesh.cuda-stream-receipt.v1", "phase3 stream schema drift")
        require(receipt["requested_configuration"]["command"] == "verify", "phase3 undeclared activation")
        require(receipt["requested_configuration"]["items"] == items, "phase3 item count drift")
        require(receipt["observed_topology"]["accelerator_observed"] is True, "phase3 accelerator observation missing")
        require(receipt["effective_execution"]["chunk_count"] == chunks, "phase3 chunk geometry drift")
        memory = receipt["memory_plan"]
        require(memory["physically_materialized"] is True, "phase3 physical materialization claim missing")
        require(memory["pinned_staging_allocations"] == 1 and memory["device_pool_allocations"] == 1, "phase3 reusable pool/staging drift")
        require(memory["reuse_across_chunks"] is True, "phase3 reuse claim drift")
        require(receipt["verification"] == {"kind": "scalar-reference-equality", "checksum": checksum, "reference": checksum, "verified": True}, "phase3 oracle drift")
    verify_environment("phase3/environment.txt")


def verify_phase4() -> None:
    timing = load_json("phase4/timing.json")
    calibration = load_json("phase4/calibration.json")

    require(timing["schema"] == "qsol.mesh.cuda-smoke-receipt.v2", "phase4 timing schema drift")
    require(timing["requested_configuration"]["timing"] is True, "phase4 timing activation missing")
    require(timing["verification"]["verified"] is True and timing["verification"]["checksum"] == FULL_CHECKSUM, "phase4 timing oracle drift")
    require(timing["timing"]["cross_clock_additive_total"] is False, "phase4 cross-clock timing boundary drift")
    for key in ("launcher_total_ns", "worker_total_ns", "setup_host_ns", "kernel_device_ns", "transfer_host_ns", "teardown_host_ns", "verification_ns"):
        require(isinstance(timing["timing"][key], int) and timing["timing"][key] >= 0, f"phase4 invalid timing field: {key}")

    require(calibration["schema"] == "qsol.mesh.calibrated-plan-receipt.v2", "phase4 calibration schema drift")
    require(calibration["verification"] == {"kind": "scalar-oracle-plus-full-work-confirmation", "verified": True}, "phase4 calibration verification drift")
    cal = calibration["calibration"]
    require(cal["candidate_budget"] == 4 and len(cal["candidates"]) == 4, "phase4 candidate budget drift")
    require([c["backend"] for c in cal["candidates"]] == ["cpu", "cpu", "accelerator", "heterogeneous-static"], "phase4 candidate set drift")
    require(all(o["verified"] is True for o in cal["observations"]), "phase4 unverified calibration observation")
    require(len({o["checksum"] for o in cal["observations"]}) == 1, "phase4 calibration checksum divergence")
    require(cal["cross_clock_kernel_timing_added"] is False, "phase4 CUDA event timing became additive")
    require(cal["full_work_confirmation"] and all(o["verified"] is True for o in cal["full_work_confirmation"]), "phase4 full-work confirmation missing")
    require(cal["full_work_confirmation"][0]["checksum"] == FULL_CHECKSUM, "phase4 full-work checksum drift")
    effective = calibration["effective_execution"]
    require(effective["selected_candidate_id"] == 0 and effective["canonical_candidate_id"] == 0, "phase4 selected candidate drift")
    require(effective["canonical_retained"] is True, "phase4 canonical retention drift")
    require(effective["selection_reason"] == "canonical-kept-after-calibration-near-tie", "phase4 selection reason drift")
    verify_environment("phase4/environment.txt")


def verify_phase5() -> None:
    receipt = load_json("phase5/adaptive.json")
    require(receipt["schema"] == "qsol.mesh.phase-runtime-receipt.v1", "phase5 schema drift")
    require(receipt["requested_configuration"]["phase_items"] == [1000, 100000, 10000], "phase5 phase geometry drift")
    require(receipt["requested_configuration"]["cuda"] is True and receipt["requested_configuration"]["device_ordinal"] == 0, "phase5 CUDA activation drift")
    effective = receipt["effective_execution"]
    require(effective["completed_phases"] == 3 and effective["plan_changes"] == 0 and effective["within_phase_replanning"] is False, "phase5 adaptive boundary drift")
    expected = [(0, 1000, "d3886842145b489c"), (1, 100000, FULL_CHECKSUM), (2, 10000, "7cf0a1247592acff")]
    for phase, (index, items, checksum) in zip(effective["phases"], expected):
        require(phase["phase_index"] == index and phase["items"] == items and phase["plan_changed"] is False, "phase5 phase identity drift")
        calibration = phase["calibration_receipt"]
        require(calibration["schema"] == "qsol.mesh.calibrated-plan-receipt.v2", "phase5 calibration schema drift")
        require(calibration["verification"]["verified"] is True, "phase5 unverified calibration")
        selected = calibration["effective_execution"]
        require(selected["selected_candidate_id"] == 0 and selected["canonical_candidate_id"] == 0 and selected["canonical_retained"] is True, "phase5 plan selection drift")
        require(selected["selection_reason"] == "canonical-kept-after-calibration-near-tie", "phase5 selection reason drift")
        execution = phase["execution"]
        require(execution["backend"] == "cpu" and execution["cpu_items"] == items and execution["cuda_items"] == 0, "phase5 execution backend drift")
        require(execution["verified"] is True and execution["checksum"] == checksum and execution["reference"] == checksum, "phase5 phase oracle drift")
    require(receipt["verification"] == {"kind": "per-phase-scalar-oracle-and-phase-order-wrapping-u64", "checksum": "edb20cb973a5c7e7", "reference": "edb20cb973a5c7e7", "verified": True}, "phase5 aggregate verification drift")
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
