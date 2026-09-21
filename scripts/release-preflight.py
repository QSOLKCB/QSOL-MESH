#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release/manifest-v0.1.0.json"
BASELINE = "8a3d03e0fbded1849e40b78c734b9217bf634019"

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

if manifest.get("schema") != "qsol.mesh.release-manifest.v1":
    raise SystemExit("release manifest schema mismatch")
if manifest.get("release_version") != "0.1.0":
    raise SystemExit("release version mismatch")
if manifest.get("expected_tag") != "v0.1.0":
    raise SystemExit("expected tag mismatch")
if manifest.get("release_class") != "immutable-constitutional-baseline":
    raise SystemExit("release class mismatch")

baseline = manifest.get("constitutional_baseline", {})
if baseline.get("commit_sha") != BASELINE:
    raise SystemExit("constitutional baseline commit mismatch")

try:
    subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE, "HEAD"], cwd=ROOT)
except subprocess.CalledProcessError as exc:
    raise SystemExit("release candidate HEAD does not descend from constitutional baseline") from exc

allowed = set(manifest["release_prep_allowed_paths"])
changed = set(filter(None, git("diff", "--name-only", f"{BASELINE}..HEAD").splitlines()))
unexpected = changed - allowed
if unexpected:
    raise SystemExit(f"release prep changed forbidden paths: {sorted(unexpected)}")

for surface in manifest["frozen_surfaces"]:
    path = ROOT / surface["path"]
    if not path.is_file():
        raise SystemExit(f"missing frozen surface: {surface['path']}")
    actual = git("hash-object", "--", surface["path"])
    expected = surface["git_blob_sha"]
    if actual != expected:
        raise SystemExit(
            f"frozen surface changed: {surface['path']}: {actual} != {expected}"
        )
    if "schema" in surface:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != surface["schema"]:
            raise SystemExit(f"schema drift: {surface['path']}")

mesh = json.loads((ROOT / "machine/mesh-contract.v1.json").read_text(encoding="utf-8"))
if mesh.get("cli_commands") != manifest.get("cli_surface"):
    raise SystemExit("release CLI surface differs from machine contract")

review = json.loads((ROOT / "machine/agent-review-policy.v1.json").read_text(encoding="utf-8"))
if review.get("schema") != manifest.get("review_policy_schema"):
    raise SystemExit("review policy schema mismatch")
if review.get("policy_version") != manifest.get("review_policy_version"):
    raise SystemExit("review policy version mismatch")

toolchain = (ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
if 'channel = "1.85.1"' not in toolchain:
    raise SystemExit("Rust toolchain channel drift")

notes = (ROOT / "RELEASE_NOTES_v0.1.0.md").read_text(encoding="utf-8")
for phrase in ("QSOL-MESH v0.1.0", "Constitutional Architecture Freeze", "v0.1.0"):
    if phrase not in notes:
        raise SystemExit(f"release notes missing required phrase: {phrase}")

roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
if "- [x] Merge PR #1 only with green contract/Rust CI." not in roadmap:
    raise SystemExit("roadmap does not record PR #1 completion")
if "- [x] Prepare the v0.1.0 constitutional release manifest, notes, and machine preflight." not in roadmap:
    raise SystemExit("roadmap does not record release-prep completion")

print("QSOL-MESH v0.1.0 release preflight passed")
print(f"constitutional_baseline={BASELINE}")
print("expected_tag=v0.1.0")
