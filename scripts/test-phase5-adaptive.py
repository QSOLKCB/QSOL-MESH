#!/usr/bin/env python3
"""CPU execution and isolated CUDA protocol fixtures, never hardware evidence."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else ROOT / 'target/debug/mesh'
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('phase4', ROOT / 'scripts/test-phase4-calibration.py')
phase4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase4)
HELPER = phase4.HELPER.replace("else 'qsol.mesh.cuda-smoke-worker.v2'", "else ('qsol.mesh.cuda-smoke-worker.v2' if '--timing-v2' in args else 'qsol.mesh.cuda-smoke-worker.v1')")


class AdaptiveTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        target = self.root / 'target'
        (target / 'debug').mkdir(parents=True)
        self.mesh = target / 'debug/mesh'
        shutil.copy2(BINARY, self.mesh)
        self.helper = target / 'mesh-cuda-smoke'
        self.log = self.root / 'calls'

    def invoke(self, *flags, mode=''):
        return subprocess.run([str(self.mesh), 'verify', 'smoke-phases', *flags, '--json'],
            env=dict(os.environ, FIXTURE_LOG=str(self.log), FIXTURE_MODE=mode),
            capture_output=True, text=True)

    def check_receipt(self, result, cuda):
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        sections = json.loads((ROOT / 'machine/evidence-contract.v1.json').read_text())['receipt_required_sections']
        self.assertTrue(set(sections) <= receipt.keys())
        self.assertEqual(receipt['schema'], 'qsol.mesh.phase-runtime-receipt.v1')
        self.assertEqual(receipt['workload_identity']['workload_id'], 'mesh-smoke-phases-v1')
        self.assertEqual(receipt['observed_topology']['accelerator_observed'], cuda)
        phases = receipt['effective_execution']['phases']
        self.assertEqual(len(phases), receipt['effective_execution']['completed_phases'])
        total = 0
        last = None
        changes = 0
        for index, phase in enumerate(phases):
            self.assertEqual(phase['phase_index'], index)
            self.assertEqual(phase['items'], receipt['requested_configuration']['phase_items'][index])
            calibration = phase['calibration_receipt']
            self.assertTrue(set(sections) <= calibration.keys())
            self.assertTrue(calibration['verification']['verified'])
            self.assertEqual(calibration['requested_configuration']['calibration_items'], min(phase['items'], 100))
            selected = calibration['effective_execution']['selected_candidate_id']
            candidate = next(c for c in calibration['calibration']['candidates'] if c['id'] == selected)
            execution = phase['execution']
            self.assertEqual(execution['backend'], candidate['backend'])
            self.assertEqual(execution['requested_cpu_workers'], candidate['cpu_workers'])
            self.assertEqual(execution['cpu_items'] + execution['cuda_items'], phase['items'])
            oracle = subprocess.run([str(self.mesh), 'verify', 'smoke', '--items', str(phase['items']), '--workers', '1', '--json'], capture_output=True, text=True, check=True)
            self.assertEqual(execution['checksum'], json.loads(oracle.stdout)['verification']['checksum'])
            self.assertTrue(execution['verified'])
            changed = last is not None and last != candidate
            self.assertEqual(phase['plan_changed'], changed)
            changes += changed
            last = candidate
            total = (total + int(execution['checksum'], 16)) & ((1 << 64) - 1)
        self.assertEqual(receipt['effective_execution']['plan_changes'], changes)
        self.assertEqual(receipt['verification']['checksum'], f'{total:016x}')
        return receipt

    def test_real_cpu_phases_and_clamped_calibration(self):
        self.check_receipt(self.invoke('--phase-items', '1,1000,25', '--calibration-items', '100', '--repeats', '1'), False)
        self.assertFalse(self.log.exists())

    def test_cuda_remeasured_each_phase_and_identity_changes_fail(self):
        # This helper exists only alongside a copied test binary in a temporary directory.
        self.helper.write_text(HELPER)
        self.helper.chmod(0o755)
        args = ('--phase-items', '1000,2000', '--calibration-items', '100', '--repeats', '1', '--cuda')
        self.check_receipt(self.invoke(*args), True)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(sum('--timing-v2' in c and c[c.index('--items') + 1] == '100' for c in calls), 2)
        # Change identity starting at the second phase calibration, preserving
        # phase-local consistency: cross-phase validation must still fail.
        altered = HELPER.replace("major = 12", "starts = sum('--timing-v2' in json.loads(c) and json.loads(c)[json.loads(c).index('--items') + 1] == '100' for c in previous) + int('--timing-v2' in args and items == 100)\nmajor = 12 if starts < 2 else 11")
        self.helper.write_text(altered)
        self.log.unlink()
        result = self.invoke(*args)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('identity changed across phase boundaries', result.stderr)

    def test_missing_cuda_and_invalid_requests_emit_no_receipt(self):
        for flags in [('--phase-items','2,3','--cuda'), ('--phase-items','1,2','--cuda'),
                      ('--phase-items','0'), ('--phase-items',','.join(['2'] * 65)),
                      ('--phase-items','2','--repeats','32'), ('--phase-items','2','--device','0'),
                      ('--phase-items','18446744073709551615,1')]:
            with self.subTest(flags=flags):
                result = self.invoke(*flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
