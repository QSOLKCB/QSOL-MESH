#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compiler="${NVCC:-nvcc}"
if (( $# != 0 )); then
  echo "build-cuda-stream-helper: output overrides are not admitted" >&2
  exit 2
fi
if ! command -v "$compiler" >/dev/null 2>&1; then
  echo "build-cuda-stream-helper: nvcc not found: $compiler" >&2
  exit 2
fi
mkdir -p "$root/target"
exec "$compiler" -std=c++17 -O3 "$root/accelerators/cuda/mesh_stream_cuda.cu" \
  -o "$root/target/mesh-cuda-stream"
