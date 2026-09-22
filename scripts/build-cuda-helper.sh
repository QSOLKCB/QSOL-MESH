#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NVCC_BIN="${NVCC:-nvcc}"
OUT="${1:-$ROOT/target/mesh-cuda-smoke}"

if ! command -v "$NVCC_BIN" >/dev/null 2>&1; then
  echo "build-cuda-helper: nvcc not found: $NVCC_BIN" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUT")"
exec "$NVCC_BIN"   -std=c++17   -O3   --expt-relaxed-constexpr   "$ROOT/accelerators/cuda/mesh_smoke_cuda.cu"   -o "$OUT"
