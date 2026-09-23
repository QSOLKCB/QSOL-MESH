#!/usr/bin/env python3
"""Validate the retained cross-repository GALAXY CPU parity payloads."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "evidence" / "phase2-galaxy-cpu-parity-2026-09-23"
cases = {
    "bounded.json": ("3e525d2d083613fa2803d0179cbe8b7a1c6d17a8e02d7b098823da4298c332d2", "ffcb0799ff078917", 4, False),
    "frozen.json": ("5305c828579dd2cc8c4e200bc0645429b33d86ad6d11bb3b4da259c4f38b1090", "8d6f07bd77e2fc16", 2, True),
}
for name, (digest, checksum, partitions, archived) in cases.items():
    raw = (root / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest, name
    receipt = json.loads(raw)
    assert receipt["schema"] == "qsol.mesh.galaxy-cpu-parity-receipt.v1"
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
