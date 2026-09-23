#!/usr/bin/env python3
"""Exercise compiler selection with isolated command stubs; no CUDA evidence."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class CompilerCaptureTest(unittest.TestCase):
    def test_selected_nvcc_builds_and_reports_its_own_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("capture-phase3-cuda-stream.sh", "build-cuda-stream-helper.sh"):
                shutil.copy(Path(__file__).parent / name, scripts / name)
            commands = root / "bin"
            commands.mkdir()

            def executable(path, body):
                path.write_text(body)
                path.chmod(0o755)

            compiler = root / "selected nvcc"
            executable(compiler, '''#!/usr/bin/env bash
if [[ "$1" == --version ]]; then
  echo version >> "$TEST_ROOT/compiler-calls"
  echo selected-CUDA-12
else
  echo build >> "$TEST_ROOT/compiler-calls"
fi
''')
            executable(commands / "nvcc", "#!/bin/sh\necho wrong-compiler-used >&2\nexit 90\n")
            executable(commands / "git", '''#!/usr/bin/env bash
if [[ "$3" == rev-parse ]]; then echo test-source; fi
''')
            executable(commands / "rustc", "#!/bin/sh\necho test-rustc\n")
            executable(commands / "nvidia-smi", "#!/bin/sh\necho test-device\n")
            executable(commands / "cargo", '''#!/usr/bin/env bash
mkdir -p "$TEST_ROOT/target/release"
cp "$TEST_ROOT/fake-mesh" "$TEST_ROOT/target/release/mesh"
''')
            executable(root / "fake-mesh", '''#!/usr/bin/env python3
import json
import sys
items = int(sys.argv[sys.argv.index("--items") + 1])
print(json.dumps({
    "schema": "qsol.mesh.cuda-stream-receipt.v1",
    "workload_identity": {"workload_id": "mesh-smoke-stream-v1", "workload_contract_version": "1.0.0"},
    "requested_configuration": {"command": "verify"},
    "verification": {"verified": True},
    "memory_plan": {"physically_materialized": True, "device_pool_allocations": 1, "pinned_staging_allocations": 1},
    "effective_execution": {"chunk_count": 25 if items == 100000 else 1},
}))
''')
            environment = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}",
                               NVCC=str(compiler), TEST_ROOT=str(root))
            result = subprocess.run(
                ["bash", str(scripts / "capture-phase3-cuda-stream.sh"), str(root / "output")],
                env=environment, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "compiler-calls").read_text().splitlines(), ["build", "version"])
            metadata = (root / "output/environment.txt").read_text()
            self.assertIn(f"nvcc_path={compiler}", metadata)
            self.assertIn("selected-CUDA-12", metadata)


if __name__ == "__main__":
    unittest.main()
