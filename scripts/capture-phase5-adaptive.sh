#!/usr/bin/env bash
set -euo pipefail
if (( $# != 1 )); then
  echo 'Usage: bash scripts/capture-phase5-adaptive.sh OUTPUT_DIRECTORY' >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$1"
[[ ! -e "$output" ]] || { echo 'output path already exists' >&2; exit 2; }
[[ -z "$(git -C "$root" status --porcelain)" ]] || { echo 'source checkout must be clean' >&2; exit 2; }
compiler="$(command -v -- "${NVCC:-nvcc}")"
compiler="$(realpath -- "$compiler")"
[[ -f "$compiler" && -x "$compiler" ]] || { echo 'CUDA compiler is not executable' >&2; exit 2; }
NVCC="$compiler" bash "$root/scripts/build-cuda-helper.sh"
cargo build --manifest-path "$root/Cargo.toml" --release --locked -p qsol-mesh-cli
mkdir -p "$output"
output="$(cd "$output" && pwd)"
"$root/target/release/mesh" verify smoke-phases --phase-items 1000,100000,10000 \
  --calibration-items 10000 --repeats 3 --cuda --device 0 --json > "$output/adaptive.json"
python3 - "$output/adaptive.json" "$root" <<'PY'
import json, pathlib, sys
r = json.loads(pathlib.Path(sys.argv[1]).read_text())
required = json.loads((pathlib.Path(sys.argv[2]) / 'machine/evidence-contract.v1.json').read_text())['receipt_required_sections']
assert set(required) <= r.keys()
assert r['schema'] == 'qsol.mesh.phase-runtime-receipt.v1'
assert r['verification']['verified'] is True
assert r['observed_topology']['accelerator_observed'] is True
assert r['effective_execution']['completed_phases'] == 3
for p in r['effective_execution']['phases']:
    assert p['execution']['verified'] is True
    assert p['calibration_receipt']['schema'] == 'qsol.mesh.calibrated-plan-receipt.v2'
    assert p['calibration_receipt']['verification']['verified'] is True
PY
{
  printf 'source_commit=%s\n' "$(git -C "$root" rev-parse HEAD)"
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  uname -a
  rustc --version
  printf 'nvcc_path=%s\n' "$compiler"
  "$compiler" --version
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader
} > "$output/environment.txt"
(
  cd "$output"
  sha256sum adaptive.json environment.txt > SHA256SUMS
)
echo "capture-phase5: verified phase execution receipt saved to $output"
