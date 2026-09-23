#!/usr/bin/env python3
"""Isolated protocol/CLI fixtures only. No CUDA execution or performance evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else ROOT / "target/debug/mesh"

# Stand-in at the canonical location of a copied test executable, never the real helper.
HELPER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
items = int(args[args.index('--items') + 1])
start = int(args[args.index('--start') + 1]) if '--start' in args else 0
mask = (1 << 64) - 1
def mix(x):
    x = ((x ^ (x >> 30)) * 0xbf58476d1ce4e5b9) & mask
    x = ((x ^ (x >> 27)) * 0x94d049bb133111eb) & mask
    return x ^ (x >> 31)
checksum = sum(mix(i ^ 0x4d4553485f534d4b) for i in range(start, start + items)) & mask
mode = os.environ.get('FIXTURE_MODE', '')
log = pathlib.Path(os.environ['FIXTURE_LOG'])
previous = log.read_text().splitlines() if log.exists() else []
with log.open('a') as f: f.write(json.dumps(args) + '\n')
if mode == 'bad-checksum': checksum ^= 1
major = 12
if mode == 'repeat-identity' and previous: major = 11
if mode == 'candidate-identity' and '--start' in args: major = 11
protocol = 'qsol.mesh.cuda-smoke-range-worker.v1' if '--start' in args else 'qsol.mesh.cuda-smoke-worker.v2'
fields = [protocol]
if '--start' in args: fields.append(f'start={start}')
fields += [f'items={items}', f'checksum={checksum:016x}', 'blocks=1', 'threads_per_block=256',
           'device=0', f'compute_major={major}', 'compute_minor=0', 'cuda_runtime=13020', 'cuda_driver=13020']
if '--timing-v2' in args:
    fields += ['setup_host_ns=100', 'kernel_device_ns=40', 'transfer_host_ns=20',
               'teardown_host_ns=10', 'worker_total_ns=200']
print('\t'.join(fields))
'''


class CalibrationProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        target = self.root / 'target'
        (target / 'debug').mkdir(parents=True)
        self.mesh = target / 'debug/mesh'
        shutil.copy2(BINARY, self.mesh)
        self.helper = target / 'mesh-cuda-smoke'
        self.helper.write_text(HELPER)
        self.helper.chmod(0o755)
        self.log = self.root / 'calls'

    def run_calibration(self, mode='', extra=()):
        command = [str(self.mesh), 'calibrate', 'smoke', '--cuda', '--calibration-items', '1000',
                   '--full-items', '2000', '--repeats', '3', '--near-tie-bps', '500', '--json']
        if extra:
            command[command.index(extra[0]) + 1] = extra[1]
        return subprocess.run(
            command,
            env=dict(os.environ, FIXTURE_MODE=mode, FIXTURE_LOG=str(self.log)),
            capture_output=True, text=True,
        )

    def test_complete_receipt_and_all_cuda_paths_measured(self):
        result = self.run_calibration()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        contract = json.loads((ROOT / 'machine/calibrated-plan-contract.v2.json').read_text())
        evidence = json.loads((ROOT / 'machine/evidence-contract.v1.json').read_text())
        self.assertEqual(receipt['schema'], contract['receipt_schema'])
        self.assertTrue(set(evidence['receipt_required_sections']) <= set(receipt))
        self.assertEqual(receipt['workload_identity']['workload_id'], 'mesh-smoke-v1')
        calibration = receipt['calibration']
        candidates = {c['id']: c for c in calibration['candidates']}
        self.assertLessEqual(len(candidates), 4)
        self.assertEqual({c['backend'] for c in candidates.values()}, {'cpu', 'accelerator', 'heterogeneous-static'})
        self.assertEqual({o['candidate_id'] for o in calibration['observations']}, set(candidates))
        for observation in calibration['observations'] + calibration['full_work_confirmation']:
            self.assertTrue(observation['verified'])
            self.assertEqual(observation['total_ns'], sum(observation[k] for k in ('service_ns', 'setup_ns', 'transfer_ns')))
            if candidates[observation['candidate_id']]['backend'] == 'accelerator':
                self.assertEqual((observation['setup_ns'], observation['transfer_ns']), (100, 20))
        effective = receipt['effective_execution']
        selected = next(o for o in calibration['full_work_confirmation'] if o['candidate_id'] == effective['selected_candidate_id'])
        self.assertEqual(selected['work_units'], 2000)
        self.assertEqual(effective['selected_effective_cpu_workers'], selected['effective_cpu_workers'])
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(sum('--timing-v2' in c and c[c.index('--items') + 1] == '1000' for c in calls), 3)
        self.assertEqual(sum('--start' in c and c[c.index('--start') + 1] == '500' for c in calls), 3)

    def test_bad_checksum_and_identity_changes_fail_closed(self):
        for mode, error in [('bad-checksum', 'checksum'), ('repeat-identity', 'identity changed between repeats'),
                            ('candidate-identity', 'identity changed across calibration candidates')]:
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                result = self.run_calibration(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn(error, result.stderr)

    def test_invalid_geometry_rejected_before_helper_and_missing_helper_fails(self):
        for extra in [('--calibration-items', '1'), ('--repeats', '0'), ('--near-tie-bps', '10000')]:
            result = self.run_calibration(extra=extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertFalse(self.log.exists())
        self.helper.unlink()
        result = self.run_calibration()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('CUDA timing helper launch failed', result.stderr)


class CompilerCaptureTest(unittest.TestCase):
    def test_selected_nvcc_builds_and_reports_its_own_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("capture-phase4-cuda-calibration.sh", "build-cuda-helper.sh"):
                shutil.copy(Path(__file__).parent / name, scripts / name)
            shutil.copytree(ROOT / "machine", root / "machine")
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
from pathlib import Path
root = Path(__file__).resolve().parents[2]
evidence = json.loads((root / 'machine/evidence-contract.v1.json').read_text())
receipt = {section: {} for section in evidence['receipt_required_sections']}
receipt.update(schema='qsol.mesh.cuda-smoke-receipt.v2' if sys.argv[1] == 'verify' else 'qsol.mesh.calibrated-plan-receipt.v2', verification={'verified': True})
print(json.dumps(receipt))
''')
            environment = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}",
                               NVCC=str(compiler), TEST_ROOT=str(root))
            result = subprocess.run(
                ["bash", str(scripts / "capture-phase4-cuda-calibration.sh"), str(root / "output")],
                env=environment, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "compiler-calls").read_text().splitlines(), ["build", "version"])
            metadata = (root / "output/environment.txt").read_text()
            self.assertIn(f"nvcc_path={compiler}", metadata)
            self.assertIn("selected-CUDA-12", metadata)


if __name__ == '__main__':
    unittest.main()
