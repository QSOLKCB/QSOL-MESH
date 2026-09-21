#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release/manifest-v0.1.0.json"
BASELINE = "8a3d03e0fbded1849e40b78c734b9217bf634019"
EXPECTED_BASELINE_TREE = "66224f422f029a5f598f1db060084257198a251c"

ALLOWED_RELEASE_PREP_PATHS = frozenset(
    {
        ".github/workflows/contracts.yml",
        "RELEASE_NOTES_v0.1.0.md",
        "ROADMAP.md",
        "release/manifest-v0.1.0.json",
        "scripts/release-preflight.py",
    }
)

FROZEN_SURFACES = {
    "CONSTITUTION.md": {"kind": "human-contract"},
    "ARCHITECTURE.md": {"kind": "human-contract"},
    "WORKLOAD-CONTRACT.md": {"kind": "human-contract"},
    "MEMORY-MODEL.md": {"kind": "human-contract"},
    "EVIDENCE.md": {"kind": "human-contract"},
    "AGENTS.md": {"kind": "agent-entrypoint"},
    "machine/mesh-contract.v1.json": {
        "schema": "qsol.mesh.contract.v1",
        "version_field": "contract_version",
        "version": "1.0.0",
    },
    "machine/agent-review-policy.v1.json": {
        "schema": "qsol.mesh.agent-review-policy.v1",
        "version_field": "policy_version",
        "version": "1.0.0",
    },
    "machine/workload-contract.v1.json": {
        "schema": "qsol.mesh.workload-contract.v1",
        "version_field": "contract_version",
        "version": "1.0.0",
    },
    "machine/memory-model.v1.json": {
        "schema": "qsol.mesh.memory-model.v1",
        "version_field": "contract_version",
        "version": "1.0.0",
    },
    "machine/evidence-contract.v1.json": {
        "schema": "qsol.mesh.evidence-contract.v1",
        "version_field": "contract_version",
        "version": "1.0.0",
    },
    "rust-toolchain.toml": {"kind": "rust-toolchain", "channel": "1.85.1"},
    "Cargo.toml": {"kind": "workspace"},
    "Cargo.lock": {"kind": "dependency-lock"},
    "crates/mesh-core/src/lib.rs": {"kind": "cli-contract-source"},
}

EXPECTED_CLI_SURFACE = ["inspect", "calibrate", "plan", "run", "verify", "receipt"]
EXPECTED_EXCLUDED_CAPABILITIES = {
    "cuda-execution",
    "galaxy-adapter",
    "heterogeneous-runtime-execution",
    "dynamic-scheduling",
    "managed-memory-policy",
    "runtime-calibration-implementation",
    "automatic-performance-promotion",
}
EXPECTED_TAG_TARGET_POLICY = {
    "must_descend_from_constitutional_baseline": True,
    "must_contain_exact_frozen_blobs": True,
    "must_contain_release_notes": "RELEASE_NOTES_v0.1.0.md",
    "must_contain_manifest": "release/manifest-v0.1.0.json",
    "must_pass_preflight": "scripts/release-preflight.py",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def fail(message):
    raise SystemExit(message)


manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

if manifest.get("schema") != "qsol.mesh.release-manifest.v1":
    fail("release manifest schema mismatch")
if manifest.get("release_version") != "0.1.0":
    fail("release version mismatch")
if manifest.get("expected_tag") != "v0.1.0":
    fail("expected tag mismatch")
if manifest.get("release_title") != "QSOL-MESH v0.1.0 — Constitutional Architecture Freeze":
    fail("release title mismatch")
if manifest.get("release_class") != "immutable-constitutional-baseline":
    fail("release class mismatch")

baseline = manifest.get("constitutional_baseline", {})
if baseline.get("pull_request") != 1:
    fail("constitutional baseline PR mismatch")
if baseline.get("commit_sha") != BASELINE:
    fail("constitutional baseline commit mismatch")
if baseline.get("tree_sha") != EXPECTED_BASELINE_TREE:
    fail("constitutional baseline tree mismatch")
if git("rev-parse", f"{BASELINE}^{{tree}}") != EXPECTED_BASELINE_TREE:
    fail("recorded baseline tree does not match Git history")

try:
    subprocess.check_call(
        ["git", "merge-base", "--is-ancestor", BASELINE, "HEAD"],
        cwd=ROOT,
    )
except subprocess.CalledProcessError as exc:
    raise SystemExit(
        "release candidate HEAD does not descend from constitutional baseline"
    ) from exc

manifest_allowed = manifest.get("release_prep_allowed_paths", [])
if len(manifest_allowed) != len(set(manifest_allowed)):
    fail("release manifest contains duplicate release-prep paths")
if set(manifest_allowed) != ALLOWED_RELEASE_PREP_PATHS:
    fail("release manifest release-prep allowlist differs from independent policy")

changed = set(filter(None, git("diff", "--name-only", f"{BASELINE}..HEAD").splitlines()))
unexpected = changed - ALLOWED_RELEASE_PREP_PATHS
if unexpected:
    fail(f"release prep changed forbidden paths: {sorted(unexpected)}")

manifest_surfaces = manifest.get("frozen_surfaces", [])
manifest_paths = [surface.get("path") for surface in manifest_surfaces]
if len(manifest_paths) != len(set(manifest_paths)):
    fail("release manifest contains duplicate frozen-surface paths")
if set(manifest_paths) != set(FROZEN_SURFACES):
    fail("release manifest frozen-surface set differs from independent policy")
manifest_by_path = {surface["path"]: surface for surface in manifest_surfaces}

for relative_path, policy in FROZEN_SURFACES.items():
    path = ROOT / relative_path
    if not path.is_file():
        fail(f"missing frozen surface: {relative_path}")

    expected_blob = git("rev-parse", f"{BASELINE}:{relative_path}")
    actual_blob = git("hash-object", "--", relative_path)
    if actual_blob != expected_blob:
        fail(
            f"frozen surface changed: {relative_path}: "
            f"{actual_blob} != baseline {expected_blob}"
        )

    recorded = manifest_by_path[relative_path]
    if recorded.get("git_blob_sha") != expected_blob:
        fail(f"manifest blob identity mismatch: {relative_path}")

    if "kind" in policy and recorded.get("kind") != policy["kind"]:
        fail(f"manifest kind mismatch: {relative_path}")

    if "schema" in policy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != policy["schema"]:
            fail(f"schema drift: {relative_path}")
        if payload.get(policy["version_field"]) != policy["version"]:
            fail(f"version drift: {relative_path}")
        if recorded.get("schema") != policy["schema"]:
            fail(f"manifest schema mismatch: {relative_path}")
        if recorded.get("version") != policy["version"]:
            fail(f"manifest version mismatch: {relative_path}")

    if "channel" in policy:
        if recorded.get("channel") != policy["channel"]:
            fail(f"manifest toolchain channel mismatch: {relative_path}")

mesh = json.loads((ROOT / "machine/mesh-contract.v1.json").read_text(encoding="utf-8"))
if mesh.get("cli_commands") != EXPECTED_CLI_SURFACE:
    fail("machine CLI surface drift")
if manifest.get("cli_surface") != EXPECTED_CLI_SURFACE:
    fail("release manifest CLI surface differs from independent policy")

review = json.loads(
    (ROOT / "machine/agent-review-policy.v1.json").read_text(encoding="utf-8")
)
if review.get("schema") != "qsol.mesh.agent-review-policy.v1":
    fail("review policy schema drift")
if review.get("policy_version") != "1.0.0":
    fail("review policy version drift")
if manifest.get("review_policy_schema") != "qsol.mesh.agent-review-policy.v1":
    fail("manifest review policy schema mismatch")
if manifest.get("review_policy_version") != "1.0.0":
    fail("manifest review policy version mismatch")

if set(manifest.get("excluded_capabilities", [])) != EXPECTED_EXCLUDED_CAPABILITIES:
    fail("release excluded-capability set differs from independent policy")
if manifest.get("tag_target_policy") != EXPECTED_TAG_TARGET_POLICY:
    fail("release tag-target policy differs from independent policy")

toolchain = (ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
if 'channel = "1.85.1"' not in toolchain:
    fail("Rust toolchain channel drift")

notes = (ROOT / "RELEASE_NOTES_v0.1.0.md").read_text(encoding="utf-8")
for phrase in ("QSOL-MESH v0.1.0", "Constitutional Architecture Freeze", "v0.1.0"):
    if phrase not in notes:
        fail(f"release notes missing required phrase: {phrase}")

roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
if "- [x] Merge PR #1 only with green contract/Rust CI." not in roadmap:
    fail("roadmap does not record PR #1 completion")
if (
    "- [x] Prepare the v0.1.0 constitutional release manifest, notes, and machine preflight."
    not in roadmap
):
    fail("roadmap does not record release-prep completion")

print("QSOL-MESH v0.1.0 release preflight passed")
print(f"constitutional_baseline={BASELINE}")
print("expected_tag=v0.1.0")
