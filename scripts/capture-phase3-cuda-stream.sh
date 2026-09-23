#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 )); then
  echo "Usage: bash scripts/capture-phase3-cuda-stream.sh OUTPUT_DIRECTORY" >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$1"
if [[ -e "$output" ]]; then
  echo "capture-phase3: output path exists: $output" >&2
  exit 2
fi
if [[ -n "$(git -C "$root" status --porcelain)" ]]; then
  echo "capture-phase3: source checkout must be clean" >&2
  exit 2
fi

compiler="$(command -v -- "${NVCC:-nvcc}")" || {
  echo "capture-phase3: selected NVCC executable not found" >&2
  exit 2
}
compiler="$(realpath -- "$compiler")"
if [[ ! -f "$compiler" || ! -x "$compiler" ]]; then
  echo "capture-phase3: selected NVCC is not an executable file" >&2
  exit 2
fi
NVCC="$compiler" bash "$root/scripts/build-cuda-stream-helper.sh"
cargo build --manifest-path "$root/Cargo.toml" --release --locked -p qsol-mesh-cli
mkdir -p "$output"
output="$(cd "$output" && pwd)"
"$root/target/release/mesh" verify smoke-stream --items 100000 --chunk-items 4096 \
  --pinned-limit-bytes 32776 --accelerator-limit-bytes 32776 --device 0 --json \
  > "$output/multi-chunk.json"
"$root/target/release/mesh" verify smoke-stream --items 1000 --chunk-items 1000 \
  --pinned-limit-bytes 8008 --accelerator-limit-bytes 8008 --device 0 --json \
  > "$output/one-chunk.json"

python3 - "$output" <<'PY'
import json
import pathlib
import sys

directory = pathlib.Path(sys.argv[1])
multi = json.loads((directory / "multi-chunk.json").read_text())
single = json.loads((directory / "one-chunk.json").read_text())
for receipt, chunks in ((multi, 25), (single, 1)):
    if receipt["schema"] != "qsol.mesh.cuda-stream-receipt.v1":
        raise SystemExit("unexpected stream receipt schema")
    if receipt["workload_identity"] != {"workload_id": "mesh-smoke-stream-v1", "workload_contract_version": "1.0.0"}:
        raise SystemExit("unexpected staged-stream workload")
    if receipt["requested_configuration"]["command"] != "verify":
        raise SystemExit("undeclared stream activation")
    if not receipt["verification"]["verified"] or not receipt["memory_plan"]["physically_materialized"]:
        raise SystemExit("unverified physical streaming execution")
    if receipt["effective_execution"]["chunk_count"] != chunks:
        raise SystemExit("wrong observed chunk count")
    if receipt["memory_plan"]["device_pool_allocations"] != 1 or receipt["memory_plan"]["pinned_staging_allocations"] != 1:
        raise SystemExit("persistent memory pool or pinned staging was not observed")
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
  sha256sum multi-chunk.json one-chunk.json environment.txt > SHA256SUMS
)
echo "capture-phase3: verified receipts and hashes saved to $output"
