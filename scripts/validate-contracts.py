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

workload = json.loads((MACHINE / "workloads/smoke-v1.json").read_text(encoding="utf-8"))
required = set(loaded["workload-contract.v1.json"]["required_fields"])
missing = required - set(workload)
if missing:
    raise SystemExit(f"smoke workload missing required fields: {sorted(missing)}")
if workload["workload_id"] != "mesh-smoke-v1":
    raise SystemExit("unexpected smoke workload identity")
if workload["reduction_contract"]["kind"] != "worker-index-order-wrapping-u64":
    raise SystemExit("smoke reduction contract drift")
if workload["verification_contract"] != {"kind":"scalar-reference-equality","fail_closed":True}:
    raise SystemExit("smoke verification contract drift")

print("QSOL-MESH machine contracts valid")
