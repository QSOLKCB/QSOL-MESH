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
    "calibrated-plan-contract.v1.json":"qsol.mesh.calibrated-plan-contract.v1",
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
if galaxy["verification_contract"]["live_partitioned_oracle_status"] != "pending-galaxy-owned-range-entrypoint":
    raise SystemExit("GALAXY live parity must remain capability-gated")
if galaxy["baseline_contract"]["requested_plan_is_execution_evidence"] is not False:
    raise SystemExit("requested GALAXY baseline plans must not imply execution evidence")

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
if calibrated["measurement_contract"]["accelerator_measurement_status"] != "pending-real-accelerator-executor":
    raise SystemExit("accelerator measurement boundary drift")
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

agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
for contract_name in (
    "machine/memory-plan-contract.v1.json",
    "machine/calibrated-plan-contract.v1.json",
):
    if contract_name not in agents:
        raise SystemExit(f"AGENTS.md does not expose normative contract: {contract_name}")

print("QSOL-MESH machine contracts valid")
