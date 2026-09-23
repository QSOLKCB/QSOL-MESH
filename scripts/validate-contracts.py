#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MACHINE = ROOT / "machine"
EXPECTED = {
    "mesh-contract.v1.json":"qsol.mesh.contract.v1",
    "agent-review-policy.v1.json":"qsol.mesh.agent-review-policy.v1",
    "workload-contract.v1.json":"qsol.mesh.workload-contract.v1",
    "memory-model.v1.json":"qsol.mesh.memory-model.v1",
    "memory-plan-contract.v1.json":"qsol.mesh.memory-plan-contract.v1",
    "cuda-stream-contract.v1.json":"qsol.mesh.cuda-stream-contract.v1",
    "calibrated-plan-contract.v1.json":"qsol.mesh.calibrated-plan-contract.v1",
    "calibrated-plan-contract.v2.json":"qsol.mesh.calibrated-plan-contract.v2",
    "galaxy-range-contract.v2.json":"qsol.mesh.galaxy-range-adapter.v2",
    "nvidia-executor-contract.v1.json":"qsol.mesh.nvidia-executor-contract.v1",
    "nvidia-executor-timing-contract.v2.json":"qsol.mesh.nvidia-executor-timing-contract.v2",
    "static-split-contract.v1.json":"qsol.mesh.static-split-contract.v1",
    "concurrent-split-contract.v1.json":"qsol.mesh.concurrent-split-contract.v1",
    "evidence-contract.v1.json":"qsol.mesh.evidence-contract.v1",
}
loaded = {}
for name, schema in EXPECTED.items():
    data = json.loads((MACHINE / name).read_text(encoding="utf-8"))
    if data.get("schema") != schema:
        raise SystemExit(f"{name}: schema mismatch")
    loaded[name] = data

mesh = loaded["mesh-contract.v1.json"]
ids = [item.get("id") for item in mesh.get("invariants", [])]
if not ids or len(ids) != len(set(ids)):
    raise SystemExit("mesh invariant IDs must be present and unique")
if not all(item.get("blocking") is True for item in mesh["invariants"]):
    raise SystemExit("constitutional invariants must remain blocking")

review = loaded["agent-review-policy.v1.json"]
req = review["blocking_finding_requirements"]
for key in (
    "must_be_actionable_correctness_defect",
    "must_bind_existing_contract_or_invariant",
    "must_include_minimal_reproduction",
    "must_include_expected_behavior",
    "must_include_actual_behavior",
    "must_include_affected_file_and_lines",
    "must_identify_new_failing_case_if_previously_reported",
    "must_use_input_admitted_by_declared_grammar_or_api",
):
    if req.get(key) is not True:
        raise SystemExit(f"review policy weakened: {key}")

canonical = review["canonical_review_instruction"]
for phrase in ("exact SHA","actionable correctness defects","minimal reproduction","expected versus actual","executed or statically inferred","Don’t repeat fixed findings","architectural suggestions separate and non-blocking"):
    if phrase not in canonical:
        raise SystemExit(f"review instruction missing: {phrase}")

source = (ROOT / "crates/mesh-core/src/lib.rs").read_text(encoding="utf-8")
for command in mesh["cli_commands"]:
    if f'"{command}"' not in source:
        raise SystemExit(f"CLI contract command missing: {command}")

required = set(loaded["workload-contract.v1.json"]["required_fields"])
workloads = {}
for path in sorted((MACHINE / "workloads").glob("*.json")):
    workload = json.loads(path.read_text(encoding="utf-8"))
    missing = required - set(workload)
    if missing:
        raise SystemExit(f"{path.name} missing required fields: {sorted(missing)}")
    workloads[path.name] = workload

smoke = workloads["smoke-v1.json"]
if smoke["workload_id"] != "mesh-smoke-v1":
    raise SystemExit("unexpected smoke workload identity")
if smoke["reduction_contract"]["kind"] != "worker-index-order-wrapping-u64":
    raise SystemExit("smoke reduction contract drift")
if smoke["verification_contract"] != {"kind":"scalar-reference-equality","fail_closed":True}:
    raise SystemExit("smoke verification contract drift")

galaxy = workloads["galaxy-v0.4.0.json"]
if galaxy.get("schema") != "qsol.mesh.galaxy-adapter.v1":
    raise SystemExit("GALAXY adapter schema drift")
if galaxy["workload_id"] != "galaxy-v0.4.0-bam-lut-q30":
    raise SystemExit("GALAXY adapter identity drift")

upstream = galaxy["upstream_authority"]
if upstream != {
    "repository": "QSOLKCB/GALAXY",
    "frozen_release": "v0.4.0",
    "frozen_release_commit": "6f17a734b9241359d36a9bf3d208b8527a456327",
    "cpu_runtime_blob_sha": "b12220565f6059482f706d46db1d9d2c29a9cc82",
    "source_copy_into_mesh": False,
    "mesh_may_implement_galaxy_particle_semantics": False,
}:
    raise SystemExit("GALAXY upstream authority drift")

oracle = galaxy["verification_contract"]["archived_cpu_oracle"]
if oracle != {
    "evidence_commit": "b9e61d20d0fe0fa99f302a2ed13aa1215a60c5f3",
    "logical_population": "18446744073709551615",
    "resident_particles": 8388608,
    "frames": 8,
    "seed": 303,
    "bam_lut_checksum": "8d6f07bd77e2fc16",
    "float_checksum": "adf6d6e30d3ad26d",
}:
    raise SystemExit("GALAXY archived oracle drift")
if galaxy["verification_contract"]["live_partitioned_oracle_status"] != "admitted-galaxy-owned-cpu-range-v1":
    raise SystemExit("GALAXY live CPU parity admission drift")
if galaxy["verification_contract"].get("live_cpu_range_contract") != "machine/galaxy-range-contract.v2.json":
    raise SystemExit("GALAXY live CPU range contract binding drift")
if galaxy["baseline_contract"].get("cpu_only_live_evidence_available") is not True:
    raise SystemExit("GALAXY CPU baseline evidence drift")
if galaxy["baseline_contract"]["requested_plan_is_execution_evidence"] is not False:
    raise SystemExit("requested GALAXY baseline plans must not imply execution evidence")

galaxy_range = loaded["galaxy-range-contract.v2.json"]
if galaxy_range["workload_id"] != galaxy["workload_id"] or galaxy_range["contract_version"] != "2.0.0":
    raise SystemExit("GALAXY live range identity drift")
if galaxy_range["upstream_authority"] != {
    "repository": upstream["repository"],
    "frozen_release_commit": upstream["frozen_release_commit"],
    "cpu_runtime_blob_sha": upstream["cpu_runtime_blob_sha"],
    "live_cpu_range_merge_commit": "623c43a13c0696533164826ec71896488c7aed44",
    "range_protocol": "galaxy.cpu-range.v1",
    "source_copy_into_mesh": False,
}:
    raise SystemExit("GALAXY live range upstream authority drift")
if galaxy_range["domain"] != {
    "logical_population": "u64-nonzero",
    "resident_particles": "1..=16777216-and-no-greater-than-logical-population",
    "partition_axis": "resident-sample-index",
    "interval": "nonempty-half-open-start-end-within-resident-population",
    "global_id_mapping_owner": "GALAXY",
    "global_id_mapping": "floor(resident_index-times-logical_population-divided-by-full_resident_particles)",
}:
    raise SystemExit("GALAXY live range domain drift")
if galaxy_range["execution"] != {
    "backend": "GALAXY-owned-CPU-only",
    "requested_partitions": "2..=256",
    "complete_gap_free_cover_required": True,
    "partial_checksum": "wrapping-u64",
    "full_range_execution_required": True,
    "partitioned_checksum_must_equal_full_range": True,
    "archived_oracle_required_for_frozen_geometry": True,
    "archived_bam_lut_checksum": oracle["bam_lut_checksum"],
}:
    raise SystemExit("GALAXY live range execution or oracle drift")
if galaxy_range["evidence_boundary"] != {
    "binary_provenance_attested": False,
    "cuda_executed": False,
    "requested_gpu_plan_is_evidence": False,
    "standalone_partition_parity_is_independent_oracle": False,
    "receipt_schema": "qsol.mesh.galaxy-cpu-parity-receipt.v1",
    "common_evidence_sections_required": True,
    "topology_and_memory_observation_status": "not-observed",
    "calibration_performed": False,
}:
    raise SystemExit("GALAXY live range evidence boundary drift")

galaxy_source = (ROOT / "crates/mesh-core/src/galaxy.rs").read_text(encoding="utf-8")
for token in (
    "6f17a734b9241359d36a9bf3d208b8527a456327",
    "b12220565f6059482f706d46db1d9d2c29a9cc82",
    "b9e61d20d0fe0fa99f302a2ed13aa1215a60c5f3",
    "0x8d6f_07bd_77e2_fc16",
):
    if token not in galaxy_source:
        raise SystemExit(f"GALAXY adapter source lost pinned identity: {token}")

for forbidden in ("fn address_word(", "fn build_particles(", "physics::", "sin_cos_q30("):
    if forbidden in galaxy_source:
        raise SystemExit(f"GALAXY semantics copied into MESH adapter: {forbidden}")

memory_plan = loaded["memory-plan-contract.v1.json"]
if memory_plan["plan_identity"] != "mesh-memory-broker-v1":
    raise SystemExit("memory plan identity drift")
if memory_plan["strategy_contract"] != {
    "kind": "stream-reduce-discard-template-v1",
    "template_repeated_per_chunk": True,
    "per_chunk_graph_materialization": False,
    "reduce_event_required": True,
    "discard_event_required": True,
    "bounded_staging_reuse": True,
    "accelerator_pool_reuse_planned": True,
}:
    raise SystemExit("memory plan strategy contract drift")
if memory_plan["materialization_boundary"] != {
    "planning_layer_may_claim_physical_materialization": False,
    "host_pinned_materialization_status": "pending-backend-owned-pinned-allocation",
    "accelerator_pool_materialization_status": "pending-real-accelerator-executor",
    "requested_or_planned_memory_is_execution_evidence": False,
}:
    raise SystemExit("memory materialization boundary drift")
if memory_plan["receipt_contract"]["schema"] != "qsol.mesh.memory-plan-receipt.v1":
    raise SystemExit("memory plan receipt schema drift")

stream = loaded["cuda-stream-contract.v1.json"]
staged_workload = workloads["smoke-stream-v1.json"]
if staged_workload["workload_id"] != "mesh-smoke-stream-v1" or staged_workload["workload_contract_version"] != "1.0.0":
    raise SystemExit("staged stream workload identity drift")
if staged_workload["computation_contract"] != {
    "kind": "mesh-smoke-v1-contribution-and-wrapping-u64-sum",
    "scalar_oracle": "mesh-smoke-v1",
    "memory_semantics_inherited": False,
}:
    raise SystemExit("staged stream scalar oracle binding drift")
if staged_workload["memory_contract"] != {
    "per_item_materialization": True,
    "materialization_scope": "current-chunk-only",
    "temporary_state": "O(effective_chunk_items)",
    "item_bytes_per_domain": 8,
    "partial_bytes_per_domain": 8,
    "domains": ["host-pinned", "accelerator-local"],
    "declared_domain_budgets_required": True,
    "budget_includes_partial_buffers": True,
    "allocation_reuse_across_chunks": True,
}:
    raise SystemExit("staged stream memory semantics drift")
if smoke["memory_contract"] != {"per_item_materialization": False, "temporary_state": "O(workers)"}:
    raise SystemExit("procedural smoke workload memory semantics drift")
if staged_workload["reduction_contract"] != {"kind": "chunk-index-order-wrapping-u64"} or staged_workload["verification_contract"] != {"kind": "scalar-reference-equality", "fail_closed": True}:
    raise SystemExit("staged stream reduction or oracle drift")
if stream["activation"] != "mesh-verify-smoke-stream":
    raise SystemExit("CUDA stream activation drift")
if stream["workload_identity"] != staged_workload["workload_id"] or stream["worker_protocol"] != "qsol.mesh.cuda-stream-worker.v1":
    raise SystemExit("CUDA stream workload or worker protocol drift")
if stream["receipt_schema"] != "qsol.mesh.cuda-stream-receipt.v1":
    raise SystemExit("CUDA stream receipt identity drift")
if stream["verified_worker_location"] != "application-target-directory/mesh-cuda-stream":
    raise SystemExit("CUDA stream canonical worker boundary drift")
if stream["physical_memory"] != {
    "host_pinned_staging_allocation": "cudaHostAlloc-once-per-run",
    "host_pinned_partial_allocation": "cudaHostAlloc-once-per-run",
    "device_input_pool_allocation": "cudaMalloc-once-per-run",
    "device_partial_allocation": "cudaMalloc-once-per-run",
    "partial_bytes": 8,
    "peak_pinned_bytes": "effective_chunk_items-times-8-plus-8",
    "peak_accelerator_bytes": "effective_chunk_items-times-8-plus-8",
    "effective_chunk_items": "min(items,requested_chunk_items,floor((pinned_limit-8)/8),floor((accelerator_limit-8)/8),floor(size_t_max/8))",
    "allocation_reuse_required": True,
    "chunk_count": "ceil(items/effective_chunk_items)",
}:
    raise SystemExit("CUDA stream physical memory contract drift")
if stream["event_graph"] != ["stage-host-pinned", "upload-accelerator", "execute", "download-partial", "reduce", "discard"] or stream["cuda_events_per_chunk"] != 3:
    raise SystemExit("CUDA stream event graph drift")
if stream["verification"] != {
    "independent_scalar_oracle_required": True,
    "strict_single_line_worker_protocol": True,
    "required_common_evidence_sections": True,
    "helper_topology_independently_attested": False,
}:
    raise SystemExit("CUDA stream verification boundary drift")
if stream["ci_boundary"] != {
    "default_runner_has_cuda_execution_evidence": False,
    "retained_cuda_host_evidence_required_for_roadmap_completion": True,
}:
    raise SystemExit("CUDA stream hardware evidence boundary drift")
worker_source = (ROOT / "accelerators/cuda/mesh_stream_cuda.cu").read_text(encoding="utf-8")
runtime_source = (ROOT / "crates/mesh-core/src/memory_runtime.rs").read_text(encoding="utf-8")
for token in ("cudaHostAlloc", "cudaMalloc", "cudaMemcpyAsync", "cudaEventRecord", "cudaEventSynchronize", "cudaFreeHost", "cudaFree"):
    if token not in worker_source:
        raise SystemExit(f"CUDA stream worker lost physical primitive: {token}")
for token in ("canonical_cuda_worker_path", "smoke_reference", "host_pinned_peak_bytes", "accelerator_peak_bytes", "stream_receipt_json", 'STREAM_WORKLOAD_ID: &str = "mesh-smoke-stream-v1"'):
    if token not in runtime_source:
        raise SystemExit(f"CUDA stream Rust launcher lost verification: {token}")

memory_source = (ROOT / "crates/mesh-core/src/memory.rs").read_text(encoding="utf-8")
for token in (
    "stream-reduce-discard-template-v1",
    "planning-only-not-physical-allocation-evidence",
    "physically_materialized",
    "host pinned peak exceeds declared limit",
    "accelerator peak exceeds declared limit",
):
    if token not in memory_source:
        raise SystemExit(f"memory broker source lost required boundary: {token}")
for forbidden in ("cudaMalloc", "cuMemAlloc", "mlock(", "VirtualLock("):
    if forbidden in memory_source:
        raise SystemExit(f"planning-only memory broker acquired physical allocation primitive: {forbidden}")

calibrated = loaded["calibrated-plan-contract.v1.json"]
if calibrated["plan_identity"] != "mesh-calibration-smoke-v1":
    raise SystemExit("calibrated plan identity drift")
if calibrated["executed_workload_identity"] != "mesh-smoke-v1":
    raise SystemExit("calibrated executed workload identity drift")
if calibrated["candidate_contract"]["maximum_candidates"] != 4:
    raise SystemExit("calibrated candidate budget drift")
if calibrated["candidate_contract"]["hardware_model_name_may_select_candidate"] is not False:
    raise SystemExit("hardware model name became performance authority")
if calibrated["measurement_contract"]["measured_evidence_required"] is not True:
    raise SystemExit("calibrated planner no longer requires measured evidence")
if calibrated["measurement_contract"]["requested_repeat_count_must_be_recorded"] is not True:
    raise SystemExit("calibrated repeat evidence requirement drift")
if calibrated["measurement_contract"]["effective_cpu_workers_must_be_recorded"] is not True:
    raise SystemExit("calibrated effective-worker evidence requirement drift")
if calibrated["measurement_contract"]["cpu_smoke_nonzero_setup_or_transfer_is_admissible"] is not False:
    raise SystemExit("CPU smoke cost-field boundary drift")
if (
    calibrated["measurement_contract"]["accelerator_measurement_status"]
    != "admitted-only-by-calibrated-plan-contract.v2"
):
    raise SystemExit("accelerator measurement availability boundary drift")
if (
    calibrated["measurement_contract"].get("accelerator_timing_receipt_schema")
    != "qsol.mesh.cuda-smoke-receipt.v2"
):
    raise SystemExit("accelerator timing receipt binding drift")
if calibrated["measurement_contract"].get("accelerator_measurements_admitted_by_planner") is not False:
    raise SystemExit("accelerator timing evidence became planner authority before admission")
if calibrated["oracle_contract"] != {
    "kind": "mesh-smoke-v1-scalar-reference-equality",
    "calibration_canonical_must_match_smoke_reference": True,
    "confirmation_canonical_must_match_smoke_reference": True,
    "peer_checksum_equality_cannot_replace_workload_oracle": True,
}:
    raise SystemExit("calibrated workload oracle contract drift")
if calibrated["confirmation_contract"]["full_work_confirmation_required_before_noncanonical_promotion"] is not True:
    raise SystemExit("full-work confirmation requirement drift")
if calibrated["confirmation_contract"]["unexpected_confirmation_observations_allowed"] is not False:
    raise SystemExit("unexpected confirmation evidence became admissible")
if calibrated["near_tie_contract"] != {
    "default_basis_points": 500,
    "comparison": "strict-improvement-greater-than-margin",
    "canonical_retained_on_equal_or-near-tie": True,
    "canonical_restored_if_full-work-confirmation-falls-within-margin": True,
}:
    raise SystemExit("near-tie contract drift")
if calibrated["receipt_contract"]["schema"] != "qsol.mesh.calibrated-plan-receipt.v1":
    raise SystemExit("calibrated plan receipt schema drift")
for key in (
    "must_record_executed_workload_identity",
    "must_keep_plan_identity_separate_from_workload_identity",
    "must_record_requested_repeat_count",
    "must_record_effective_cpu_workers_per_observation",
    "must_record_selected_requested_and_effective_cpu_workers",
    "serializer_must_revalidate_plan_before_verified_status",
):
    if calibrated["receipt_contract"].get(key) is not True:
        raise SystemExit(f"calibrated receipt contract weakened: {key}")

cuda_calibrated = loaded["calibrated-plan-contract.v2.json"]
if calibrated.get("activation") != "mesh-calibrate-smoke-without---cuda" or calibrated["measurement_contract"].get("opt_in_cuda_contract") != "machine/calibrated-plan-contract.v2.json":
    raise SystemExit("CPU-only default and opt-in CUDA calibration authority drift")
expected_cuda_calibrated = {'schema': 'qsol.mesh.calibrated-plan-contract.v2',
 'contract_version': '2.0.0',
 'plan_identity': 'mesh-calibration-smoke-v1',
 'activation': 'mesh-calibrate-smoke---cuda',
 'cuda_helper': 'canonical-mesh-cuda-smoke',
 'workload_identity': 'mesh-smoke-v1',
 'candidate_set': ['canonical-cpu', 'topology-derived-cpu', 'cuda-only', 'static-cpu-cuda'],
 'measurement': {'repeats': 'positive',
                 'cuda_protocol': 'qsol.mesh.cuda-smoke-worker.v2',
                 'cuda_sample_policy': 'median-launcher-plus-scalar-verification-host-time-sample-with-components-from-same-repeat',
                 'cuda_service_ns': 'launcher_total_ns-plus-verification_ns-minus-nested-setup_host_ns-minus-nested-transfer_host_ns',
                 'cuda_setup_ns': 'setup_host_ns',
                 'cuda_transfer_ns': 'transfer_host_ns',
                 'cuda_total_ns': 'launcher_total_ns-plus-verification_ns',
                 'cuda_kernel_event_ns_added_to_total': False,
                 'cpu_service_ns': 'run_smoke-end-to-end',
                 'heterogeneous_service_ns': 'run_static_smoke_partition-end-to-end',
                 'heterogeneous_setup_transfer_separately_isolated': False,
                 'worker_topology_is_independently_attested': False,
                 'cuda_identity_stable_across_all_samples_and_candidates': True,
                 'cuda_timing_contract': 'machine/nvidia-executor-timing-contract.v2.json'},
 'selection': {'canonical_checksum_is_independent_scalar_oracle': True,
               'all_candidates_measured': True,
               'near_tie_and_full_work_confirmation': True,
               'adaptive_work_stealing': False},
 'receipt_schema': 'qsol.mesh.calibrated-plan-receipt.v2',
 'base_planning_contract': 'machine/calibrated-plan-contract.v1.json',
 'request_domain': {'calibration_items': '2..=u64::MAX',
                    'full_work_items': 'calibration_items..=u64::MAX',
                    'repeats': 'positive-usize',
                    'near_tie_bps': '0..=9999',
                    'device': 'u32'},
 'receipt_requires_common_evidence_sections': True,
 'cuda_host_evidence_status': 'pending-retained-physical-calibration-receipt'}
if {key: value for key, value in cuda_calibrated.items() if key != "claim_boundary"} != expected_cuda_calibrated:
    raise SystemExit("CUDA calibrated planning admission, measurement, or evidence boundary drift")

planner_source = (ROOT / "crates/mesh-core/src/planner.rs").read_text(encoding="utf-8")
for token in (
    "CANDIDATE_BUDGET",
    "DEFAULT_NEAR_TIE_BPS",
    "promoted-after-full-work-confirmation",
    "canonical-restored-after-full-work-near-tie",
    "accelerator candidate lacks observed topology",
    "candidate checksum does not match canonical result",
    "canonical checksum does not match smoke oracle",
    "smoke_reference",
    "full-work confirmation contains unexpected candidates",
    "CPU smoke observations require zero separate setup and transfer cost",
    "selected_effective_cpu_workers",
    "SMOKE_WORKLOAD_ID",
    "validate_calibrated_plan",
):
    if token not in planner_source:
        raise SystemExit(f"calibrated planner lost required boundary: {token}")
for forbidden in ("RTX", "GeForce", "A100", "H100", "product_name", "model_name"):
    if forbidden in planner_source:
        raise SystemExit(f"calibrated planner contains hardware-name performance policy: {forbidden}")

nvidia = loaded["nvidia-executor-contract.v1.json"]
if nvidia["executor_id"] != "qsol-mesh-cuda-smoke-v1":
    raise SystemExit("NVIDIA executor identity drift")
if nvidia["backend"] != "nvidia-cuda":
    raise SystemExit("NVIDIA executor backend drift")
if nvidia["worker_protocol"] != "qsol.mesh.cuda-smoke-worker.v1":
    raise SystemExit("CUDA worker protocol drift")
if nvidia["range_worker_protocol"] != "qsol.mesh.cuda-smoke-range-worker.v1":
    raise SystemExit("CUDA range worker protocol drift")
if nvidia["execution_contract"]["range_execution_supported"] is not True:
    raise SystemExit("CUDA range execution support drift")
if nvidia["execution_contract"]["range_start_plus_items_must_fit_u64"] is not True:
    raise SystemExit("CUDA range arithmetic boundary drift")
if nvidia["workload_identity"] != "mesh-smoke-v1":
    raise SystemExit("CUDA executor workload identity drift")
if nvidia["execution_contract"]["real_cuda_kernel_required"] is not True:
    raise SystemExit("CUDA executor no longer requires real kernel execution")
if nvidia["execution_contract"]["host_scalar_fallback_inside_cuda_worker_allowed"] is not False:
    raise SystemExit("CUDA worker scalar fallback became admissible")
for key in (
    "worker_exit_success_required",
    "single_exact_protocol_line_required",
    "protocol_may_have_at_most_one_line_terminator",
    "verified_run_provenance_must_be_launcher_issued",
    "logical_id_iteration_must_not_wrap_u64",
):
    if nvidia["execution_contract"].get(key) is not True:
        raise SystemExit(f"CUDA execution contract weakened: {key}")
if nvidia["execution_contract"]["verified_worker_location"] != "application-target-directory/mesh-cuda-smoke":
    raise SystemExit("verified CUDA worker location drift")
if nvidia["execution_contract"]["verified_worker_resolution"] != "canonicalized-current-executable-nearest-target-ancestor":
    raise SystemExit("verified CUDA worker resolution drift")
if nvidia["execution_contract"]["caller_working_directory_may_influence_verified_worker_resolution"] is not False:
    raise SystemExit("caller CWD became CUDA worker resolution authority")
for key in (
    "verified_worker_override_allowed",
    "verified_worker_environment_override_allowed",
    "arbitrary_helper_stdout_may_issue_verified_receipt",
):
    if nvidia["execution_contract"].get(key) is not False:
        raise SystemExit(f"CUDA verified-worker override boundary weakened: {key}")
if nvidia["build_contract"]["verified_output"] != "target/mesh-cuda-smoke":
    raise SystemExit("CUDA verified build output drift")
if nvidia["build_contract"]["alternate_verified_output_allowed"] is not False:
    raise SystemExit("alternate CUDA verified build output became admissible")
if nvidia["trust_boundary"] != {
    "caller_selected_executables_are_execution_evidence": False,
    "caller_working_directory_is_execution_authority": False,
    "application_anchored_canonical_worker_is_required": True,
    "local_filesystem_and_build_environment_are_outside_this_contract": True,
    "canonical_path_is_not_cryptographic_binary_attestation": True,
}:
    raise SystemExit("CUDA worker trust boundary drift")
if nvidia["verification_contract"] != {
    "kind": "mesh-smoke-v1-scalar-reference-equality",
    "rust_launcher_recomputes_scalar_reference": True,
    "worker_checksum_must_equal_scalar_reference": True,
    "verified_receipt_requires_oracle_pass": True,
    "receipt_revalidates_resolved_worker_path": True,
    "range_worker_checksum_must_equal_scalar_range_reference": True,
}:
    raise SystemExit("CUDA executor verification contract drift")
if nvidia["observation_contract"]["helper_reported_topology_is_independently_attested"] is not False:
    raise SystemExit("helper-reported CUDA topology was overstated as attested")
if nvidia["ci_boundary"]["default_github_runner_has_cuda_execution_evidence"] is not False:
    raise SystemExit("default CI falsely claims CUDA execution evidence")
if nvidia["ci_boundary"]["ci_may_claim_gpu_execution_without_cuda_capable_runner"] is not False:
    raise SystemExit("CI CUDA evidence boundary weakened")

timing = loaded["nvidia-executor-timing-contract.v2.json"]
if timing["contract_version"] != "2.0.0":
    raise SystemExit("CUDA timing contract version drift")
if timing["base_executor_contract"] != {
    "path": "machine/nvidia-executor-contract.v1.json",
    "schema": "qsol.mesh.nvidia-executor-contract.v1",
    "executor_id": "qsol-mesh-cuda-smoke-v1",
}:
    raise SystemExit("CUDA timing base-executor binding drift")
if timing["workload_identity"] != "mesh-smoke-v1":
    raise SystemExit("CUDA timing workload identity drift")
if timing["worker_protocol"] != "qsol.mesh.cuda-smoke-worker.v2":
    raise SystemExit("CUDA timing worker protocol drift")
if timing["receipt_schema"] != "qsol.mesh.cuda-smoke-receipt.v2":
    raise SystemExit("CUDA timing receipt schema drift")
if timing["activation"] != {
    "cli_flag": "--timing",
    "worker_flag": "--timing-v2",
    "default_smoke_cuda_protocol_remains_v1": True,
    "default_smoke_cuda_receipt_remains_v1": True,
    "range_timing_supported": False,
    "placement_behavior_may_change": False,
    "calibrator_may_consume_v2_timings": True,
    "calibrator_admission_contract": "machine/calibrated-plan-contract.v2.json",
}:
    raise SystemExit("CUDA timing activation/compatibility boundary drift")

expected_timing_fields = {
    "launcher_total_ns": {
        "producer": "rust-launcher",
        "clock": "rust-std-instant-monotonic",
        "scope": "canonical-helper-command-output-from-pre-spawn-through-captured-exit",
    },
    "worker_total_ns": {
        "producer": "cuda-worker",
        "clock": "cxx-std-steady-clock-monotonic",
        "scope": "pre-cudaSetDevice-through-cudaFree-and-timing-event-destruction",
    },
    "setup_host_ns": {
        "producer": "cuda-worker",
        "clock": "cxx-std-steady-clock-monotonic",
        "scope": "cudaSetDevice-through-topology-version-query-launch-geometry-allocation-zeroing-and-timing-event-creation",
    },
    "kernel_device_ns": {
        "producer": "cuda-worker",
        "clock": "cuda-event-default-stream",
        "scope": "cuda-event-before-kernel-through-event-after-kernel-with-device-synchronization-before-readout",
    },
    "transfer_host_ns": {
        "producer": "cuda-worker",
        "clock": "cxx-std-steady-clock-monotonic",
        "scope": "synchronous-eight-byte-cudaMemcpy-device-to-pageable-host-after-device-synchronization",
    },
    "teardown_host_ns": {
        "producer": "cuda-worker",
        "clock": "cxx-std-steady-clock-monotonic",
        "scope": "cudaFree-through-timing-event-destruction",
    },
    "verification_ns": {
        "producer": "rust-launcher",
        "clock": "rust-std-instant-monotonic",
        "scope": "independent-smoke_reference-computation-only",
    },
}
if timing["timing_fields"] != expected_timing_fields:
    raise SystemExit("CUDA timing field scope/clock contract drift")
if timing["consistency_contract"] != {
    "worker_protocol_timing_values_are_unsigned_decimal_u64": True,
    "missing_or_duplicate_or_misordered_fields_must_fail_closed": True,
    "negative_or_overflowed_timing_values_must_fail_closed": True,
    "worker_total_ns_must_be_nonzero": True,
    "host_component_sum_is_checked_u64": True,
    "setup_plus_transfer_plus_teardown_must_not_exceed_worker_total": True,
    "launcher_total_must_not_be_less_than_worker_total": True,
    "kernel_device_ns_is_not_added_to_host_component_sum": True,
    "cross_clock_additive_total_may_be_claimed": False,
}:
    raise SystemExit("CUDA timing consistency contract drift")
if timing["verification_contract"] != {
    "kind": "mesh-smoke-v1-scalar-reference-equality",
    "worker_checksum_must_equal_independent_rust_scalar_reference": True,
    "timing_validation_precedes_verified_receipt": True,
    "receipt_serialization_revalidates_timing_and_oracle": True,
    "canonical_worker_path_must_be_revalidated": True,
}:
    raise SystemExit("CUDA timing verification contract drift")
if timing["evidence_boundary"] != {
    "single_sample_is_performance_evidence": False,
    "timing_receipt_is_calibration_selection_evidence": False,
    "helper_reported_topology_is_independently_attested": False,
    "kernel_level_cpu_gpu_overlap_is_measured": False,
    "retained_cuda_host_v1_evidence_is_reinterpreted_as_v2": False,
}:
    raise SystemExit("CUDA timing evidence boundary drift")
if timing["ci_boundary"] != {
    "default_github_runner_has_cuda_timing_evidence": False,
    "ci_may_validate_v2_protocol_parser_and_contract": True,
    "ci_may_claim_cuda_timing_execution_without_cuda_capable_runner": False,
}:
    raise SystemExit("CUDA timing CI boundary drift")

accelerator_source = (ROOT / "crates/mesh-core/src/accelerator.rs").read_text(encoding="utf-8")
for token in (
    "qsol.mesh.cuda-smoke-worker.v1",
    "qsol.mesh.cuda-smoke-worker.v2",
    "qsol.mesh.cuda-smoke-range-worker.v1",
    "run_cuda_smoke_timed",
    "cuda_smoke_timing_receipt_json",
    "CUDA timing host components exceed worker total",
    "cross_clock_additive_total",
    "run_cuda_smoke_range",
    "CUDA range checksum does not match scalar smoke oracle",
    "CANONICAL_CUDA_HELPER_FILENAME",
    "canonical_cuda_helper_path",
    "std::env::current_exe",
    "std::fs::canonicalize",
    "running mesh executable is outside the supported application target tree",
    "CUDA smoke run was not produced by the canonical worker path",
    "pub fn run_cuda_smoke(",
    "CUDA checksum does not match scalar smoke oracle",
    "smoke_reference",
    "cuda_runtime_version",
    "cuda_driver_version",
    "helper-reported-topology-not-performance-evidence",
    "strip_suffix",
    "CUDA worker output must contain exactly one protocol line",
    "fn validate_cuda_worker_observation",
):
    if token not in accelerator_source:
        raise SystemExit(f"CUDA Rust launcher lost required boundary: {token}")

cuda_source = (ROOT / "accelerators/cuda/mesh_smoke_cuda.cu").read_text(encoding="utf-8")
for token in (
    "__global__ void smoke_kernel",
    "const unsigned long long remaining = items - offset",
    "if (remaining <= stride)",
    "cudaSetDevice",
    "cudaGetDeviceProperties",
    "cudaRuntimeGetVersion",
    "cudaDriverGetVersion",
    "cudaMalloc",
    "atomicAdd",
    "cudaDeviceSynchronize",
    "cudaMemcpy",
    "qsol.mesh.cuda-smoke-worker.v1",
    "qsol.mesh.cuda-smoke-worker.v2",
    "qsol.mesh.cuda-smoke-range-worker.v1",
    'std::strcmp(argv[index], "--start")',
    'std::strcmp(argv[index], "--timing-v2")',
    "std::chrono::steady_clock",
    "cudaEventRecord",
    "cudaEventElapsedTime",
    "const unsigned long long id = start + offset",
):
    if token not in cuda_source:
        raise SystemExit(f"CUDA worker lost required execution primitive: {token}")
if "for (unsigned long long id = tid; id < items; id += stride)" in cuda_source:
    raise SystemExit("CUDA worker reintroduced wrapping logical-ID for-loop")
if "pub fn validate_cuda_worker_observation" in accelerator_source:
    raise SystemExit("raw CUDA observation validation became a public run constructor")
if "pub fn run_cuda_smoke_with_helper" in accelerator_source:
    raise SystemExit("caller-selected helper execution became a public verified-run constructor")
if 'Path::new("target/mesh-cuda-smoke")' in accelerator_source:
    raise SystemExit("verified CUDA worker resolution regressed to caller-CWD-relative path")
if "pub observation: CudaWorkerObservation" in accelerator_source or "pub reference: u64" in accelerator_source:
    raise SystemExit("CUDA run provenance fields became publicly constructible")

cli_source = (ROOT / "crates/mesh-cli/src/main.rs").read_text(encoding="utf-8")
if "QSOL_MESH_CUDA_HELPER" in cli_source:
    raise SystemExit("environment helper override re-entered verified CUDA CLI")
if "--helper PATH" in cli_source:
    raise SystemExit("verified CUDA usage re-exposed caller-selected helper path")
if "--helper overrides are not admitted for verified CUDA execution" not in cli_source:
    raise SystemExit("verified CUDA CLI lost explicit helper-override rejection")
if "--timing" not in cli_source or "run_cuda_smoke_timed" not in cli_source:
    raise SystemExit("CUDA timing CLI surface missing")

build_script = (ROOT / "scripts/build-cuda-helper.sh").read_text(encoding="utf-8")
for token in (
    "nvcc",
    "accelerators/cuda/mesh_smoke_cuda.cu",
    'OUT="$ROOT/target/mesh-cuda-smoke"',
    "alternate output paths are not admitted for the verified worker",
):
    if token not in build_script:
        raise SystemExit(f"CUDA build script lost required binding: {token}")


static_split = loaded["static-split-contract.v1.json"]
if static_split["split_id"] != "mesh-smoke-static-cpu-cuda-v1":
    raise SystemExit("static split identity drift")
if static_split["workload_identity"] != "mesh-smoke-v1":
    raise SystemExit("static split workload identity drift")
if static_split["cuda_range_worker_protocol"] != "qsol.mesh.cuda-smoke-range-worker.v1":
    raise SystemExit("static split CUDA range protocol drift")
if static_split["partition_contract"] != {
    "kind": "caller-fixed-contiguous-prefix-suffix-v1",
    "caller_supplies_cpu_items": True,
    "cpu_range": "[0,cpu_items)",
    "cuda_range": "[cpu_items,items)",
    "two_nonempty_partitions_required": True,
    "complete_cover_required": True,
    "overlap_allowed": False,
    "adaptive_repartitioning": False,
    "hardware_name_may_choose_split": False,
}:
    raise SystemExit("static split partition contract drift")
if static_split["execution_contract"] != {
    "execution_order": ["cpu", "nvidia-cuda"],
    "concurrent": False,
    "dynamic_work_stealing": False,
    "cpu_fallback_on_cuda_failure": False,
    "cuda_range_must_use_canonical_worker": True,
    "each_partition_requires_its_own_range_oracle": True,
    "full_reduction_requires_scalar_oracle": True,
}:
    raise SystemExit("static split execution contract drift")
if static_split["reduction_contract"] != {
    "kind": "partition-order-wrapping-u64",
    "order": ["cpu", "nvidia-cuda"],
    "completion_order_may_change_reduction_order": False,
}:
    raise SystemExit("static split reduction contract drift")
if static_split["receipt_contract"]["schema"] != "qsol.mesh.static-split-receipt.v1":
    raise SystemExit("static split receipt schema drift")
if static_split["ci_boundary"]["default_github_runner_has_cuda_execution_evidence"] is not False:
    raise SystemExit("static split CI falsely claims CUDA execution evidence")
if static_split["ci_boundary"]["ci_may_claim_static_heterogeneous_execution_without_cuda_capable_runner"] is not False:
    raise SystemExit("static split CI execution-evidence boundary weakened")

split_source = (ROOT / "crates/mesh-core/src/static_split.rs").read_text(encoding="utf-8")
for token in (
    "run_static_smoke_partition",
    "static-cpu-cuda-partition-v1",
    '\\"concurrent\\":false',
    '\\"adaptive\\":false',
    "partition-order-wrapping-u64",
    "CPU static-split checksum does not match assigned range oracle",
    "CUDA static-split checksum does not match assigned range oracle",
    "static CPU/CUDA reduction does not match full smoke oracle",
    "run_cuda_smoke_range",
):
    if token not in split_source:
        raise SystemExit(f"static split source lost required boundary: {token}")

core_source = (ROOT / "crates/mesh-core/src/lib.rs").read_text(encoding="utf-8")
for token in ("smoke_reference_range", "run_smoke_range", "smoke logical range overflows u64"):
    if token not in core_source:
        raise SystemExit(f"CPU smoke range support lost required boundary: {token}")

if "smoke-static" not in cli_source or "--cpu-items is required for a fixed static split" not in cli_source:
    raise SystemExit("static split CLI lost explicit fixed geometry")


concurrent = loaded["concurrent-split-contract.v1.json"]
if concurrent["split_id"] != "mesh-smoke-concurrent-cpu-cuda-v1":
    raise SystemExit("concurrent split identity drift")
if concurrent["partition_source_contract"] != "qsol.mesh.static-split-contract.v1":
    raise SystemExit("concurrent split static-geometry authority drift")
if concurrent["partition_contract"] != {
    "reuse_static_fixed_geometry": True,
    "caller_supplies_cpu_items": True,
    "adaptive_repartitioning": False,
    "dynamic_work_stealing": False,
    "hardware_name_may_choose_split": False,
}:
    raise SystemExit("concurrent split partition contract drift")
if concurrent["dispatch_contract"] != {
    "kind": "cpu-task-spawned-before-cuda-call-v1",
    "cpu_task_spawned_before_cuda_call": True,
    "cpu_joined_after_cuda_call_return": True,
    "cpu_cuda_executor_calls_concurrently_dispatched": True,
    "cuda_kernel_level_overlap_measured": False,
    "cuda_kernel_level_overlap_may_be_claimed": False,
    "cpu_fallback_on_cuda_failure": False,
}:
    raise SystemExit("concurrent split dispatch contract drift")
if concurrent["verification_contract"] != {
    "each_partition_requires_range_oracle": True,
    "full_reduction_requires_scalar_oracle": True,
    "verified_status_requires_both_executor_results": True,
}:
    raise SystemExit("concurrent split verification contract drift")
if concurrent["reduction_contract"] != {
    "kind": "partition-order-wrapping-u64",
    "order": ["cpu", "nvidia-cuda"],
    "completion_order_may_change_reduction_order": False,
}:
    raise SystemExit("concurrent split reduction contract drift")
if concurrent["receipt_contract"]["schema"] != "qsol.mesh.concurrent-split-receipt.v1":
    raise SystemExit("concurrent split receipt schema drift")
if concurrent["ci_boundary"]["default_github_runner_has_cuda_execution_evidence"] is not False:
    raise SystemExit("concurrent split CI falsely claims CUDA execution evidence")
if concurrent["ci_boundary"]["ci_may_claim_cuda_kernel_overlap_without_cuda_capable_measurement"] is not False:
    raise SystemExit("concurrent split CI kernel-overlap boundary weakened")
if concurrent["ci_boundary"]["ci_may_claim_concurrent_heterogeneous_execution_without_cuda_capable_runner"] is not False:
    raise SystemExit("concurrent split CI execution-evidence boundary weakened")

concurrent_source = (ROOT / "crates/mesh-core/src/concurrent_split.rs").read_text(encoding="utf-8")
for token in (
    "run_concurrent_smoke_partition",
    "scope.spawn(cpu_fn)",
    "let cuda_result = cuda_fn()",
    "cpu_handle",
    '\\"concurrent_dispatch\\":true',
    '\\"kernel_overlap_measured\\":false',
    "partition-order-wrapping-u64",
    "cpu_fallback",
    "run_cuda_smoke_range",
):
    if token not in concurrent_source:
        raise SystemExit(f"concurrent split source lost required boundary: {token}")
if "join()" not in concurrent_source:
    raise SystemExit("concurrent split lost CPU join lifecycle")
if "smoke-concurrent" not in cli_source:
    raise SystemExit("concurrent split CLI surface missing")

agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
for contract_name in (
    "machine/memory-plan-contract.v1.json",
    "machine/calibrated-plan-contract.v1.json",
    "machine/calibrated-plan-contract.v2.json",
    "machine/nvidia-executor-contract.v1.json",
    "machine/nvidia-executor-timing-contract.v2.json",
    "machine/static-split-contract.v1.json",
    "machine/concurrent-split-contract.v1.json",
):
    if contract_name not in agents:
        raise SystemExit(f"AGENTS.md does not expose normative contract: {contract_name}")

print("QSOL-MESH machine contracts valid")
