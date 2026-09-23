#!/usr/bin/env python3
"""Validate the retained cross-repository GALAXY CPU parity payloads."""
import hashlib
import json
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
root = repository / "evidence" / "phase2-galaxy-cpu-parity-2026-09-23"
evidence_contract = json.loads((repository / "machine" / "evidence-contract.v1.json").read_text())
range_contract = json.loads((repository / "machine" / "galaxy-range-contract.v2.json").read_text())
cases = {
    "bounded.json": ("b362a24da907f8249fe055ce3ae586b24c48ed706231d97b1e2f5bfba8b81e3a", "ffcb0799ff078917", 4, False),
    "frozen.json": ("1f26830e677b75e5d9cfda086385b5effb7b7800cd3c0c3952fbb7e8b2535ef3", "8d6f07bd77e2fc16", 2, True),
}
for name, (digest, checksum, partitions, archived) in cases.items():
    raw = (root / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest, name
    receipt = json.loads(raw)
    assert receipt["schema"] == range_contract["evidence_boundary"]["receipt_schema"]
    assert set(evidence_contract["receipt_required_sections"]) <= set(receipt)
    assert receipt["observed_topology"] == {
        "status": "not-observed", "source": "external-galaxy-cpu-range-process"
    }
    assert receipt["memory_plan"] == {
        "status": "not-observed", "owner": "galaxy-cpu-runtime",
        "mesh_materializes_logical_population": False,
    }
    assert receipt["calibration"] == {"performed": False, "placement_decision_influenced": False}
    assert receipt["requested_configuration"]["partitions"] == partitions
    assert receipt["effective_execution"]["partial_count"] == partitions
    verification = receipt["verification"]
    assert verification["full_checksum"] == checksum
    assert verification["partitioned_checksum"] == checksum
    assert verification["partitioned_parity"] is True
    assert verification["archived_oracle_verified"] is archived
assert json.loads((root / "frozen.json").read_text())["requested_configuration"] == {
    "logical_population": 18446744073709551615,
    "resident_particles": 8388608,
    "frames": 8,
    "seed": 303,
    "partitions": 2,
}
print("retained GALAXY CPU parity evidence verified")
