#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 )); then
  echo "Usage: bash scripts/capture-phase4-cuda-calibration.sh OUTPUT_DIRECTORY" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$1"
if [[ -e "$output" ]]; then
  echo "capture-phase4: output path already exists: $output" >&2
  exit 2
fi
if [[ -n "$(git -C "$root" status --porcelain)" ]]; then
  echo "capture-phase4: source checkout must be clean" >&2
  exit 2
fi

bash "$root/scripts/build-cuda-helper.sh"
cargo build --manifest-path "$root/Cargo.toml" --release --locked -p qsol-mesh-cli
mkdir -p "$output"
output="$(cd "$output" && pwd)"

"$root/target/release/mesh" verify smoke-cuda --items 100000 --device 0 --timing --json \
  > "$output/timing.json"
"$root/target/release/mesh" calibrate smoke --cuda --device 0 \
  --calibration-items 10000 --full-items 100000 --repeats 3 --json \
  > "$output/calibration.json"

python3 - "$output" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
expected = {
    "timing.json": "qsol.mesh.cuda-smoke-receipt.v2",
    "calibration.json": "qsol.mesh.calibrated-plan-receipt.v2",
}
for name, schema in expected.items():
    receipt = json.loads((root / name).read_text(encoding="utf-8"))
    if receipt.get("schema") != schema or receipt.get("verification", {}).get("verified") is not True:
        raise SystemExit(f"{name}: unverified or unexpected receipt")
PY

{
  printf 'source_commit=%s\n' "$(git -C "$root" rev-parse HEAD)"
  printf 'source_branch=%s\n' "$(git -C "$root" branch --show-current)"
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  uname -a
  rustc --version
  nvcc --version
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader
} > "$output/environment.txt"

(
  cd "$output"
  sha256sum calibration.json timing.json environment.txt > SHA256SUMS
)
echo "capture-phase4: verified receipts and hashes saved to $output"
