#!/usr/bin/env python3
"""Exercise immutable capture admission and independent receipt semantics."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('retained', Path(__file__).with_name('validate-retained-phase5-evidence.py'))
retained = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retained)


class RetainedPhase5Test(unittest.TestCase):
    def test_original_capture(self):
        retained.validate()

    def test_capture_files_cannot_be_changed_or_resealed(self):
        for name in ('adaptive.json', 'environment.txt', 'SHA256SUMS'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'evidence'
                shutil.copytree(retained.EVIDENCE, root)
                path = root / name
                path.write_bytes(path.read_bytes() + b'\n')
                with self.assertRaisesRegex(ValueError, 'retained evidence changed'):
                    retained.validate(root)
                manifest = json.loads((root / 'manifest.json').read_text())
                manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
                (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
                with self.assertRaisesRegex(ValueError, 'manifest digest mismatch'):
                    retained.validate(root)

    def test_receipt_semantic_mutations(self):
        original = json.loads((retained.EVIDENCE / 'adaptive.json').read_text())
        phase = ('effective_execution', 'phases', 1)
        calibration = phase + ('calibration_receipt',)
        # These checks bypass the immutable file hashes deliberately: malformed
        # fields must fail their own semantic checks, not merely a digest check.
        cases = [
            (('requested_configuration', 'phase_items'), [1000, 100000, 10001], 'request mismatch'),
            (phase + ('phase_index',), 0, 'phase order'),
            (calibration + ('requested_configuration', 'full_work_items'), 10000, 'request binding'),
            (calibration + ('observed_topology', 'device_ordinal'), 1, 'topology continuity'),
            (calibration + ('calibration', 'observations', 2, 'work_units'), 9999, 'work binding'),
            (calibration + ('calibration', 'observations', 2, 'checksum'), '0000000000000000', 'measurement scalar oracle'),
            (calibration + ('calibration', 'observations', 2, 'total_ns'), 1, 'cost arithmetic'),
            (calibration + ('calibration', 'full_work_confirmation'), [], 'confirmation coverage'),
            (calibration + ('calibration', 'full_work_confirmation', 0, 'work_units'), 10000, 'work binding'),
            (calibration + ('effective_execution', 'selected_candidate_id'), 2, 'canonical selection'),
            (phase + ('execution', 'checksum'), '0000000000000000', 'phase execution or scalar oracle'),
            (phase + ('execution', 'cuda_items'), 100000, 'phase execution or scalar oracle'),
            (phase + ('execution', 'effective_cpu_workers'), 32, 'phase execution or scalar oracle'),
            (phase + ('plan_changed',), True, 'phase change flag'),
            (('effective_execution', 'plan_changes'), 1, 'plan change count'),
            (('verification', 'checksum'), retained.oracle(111000), 'aggregate oracle'),
            (('claim_boundary',), 'universal-speedup', 'phase claim boundary'),
        ]
        for path, value, message in cases:
            with self.subTest(path=path):
                receipt = copy.deepcopy(original)
                node = receipt
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                with self.assertRaisesRegex(ValueError, message):
                    retained.validate_receipt(receipt)

    def test_common_sections_required_at_both_levels(self):
        original = json.loads((retained.EVIDENCE / 'adaptive.json').read_text())
        sections = json.loads((retained.ROOT / 'machine/evidence-contract.v1.json').read_text())['receipt_required_sections']
        for nested in (False, True):
            for section in sections:
                with self.subTest(nested=nested, section=section):
                    receipt = copy.deepcopy(original)
                    node = receipt['effective_execution']['phases'][0]['calibration_receipt'] if nested else receipt
                    del node[section]
                    with self.assertRaisesRegex(ValueError, 'missing .*evidence section'):
                        retained.validate_receipt(receipt)

    def test_costs_must_support_captured_selection(self):
        receipt = json.loads((retained.EVIDENCE / 'adaptive.json').read_text())
        observation = receipt['effective_execution']['phases'][0]['calibration_receipt']['calibration']['observations'][1]
        observation.update(service_ns=1, setup_ns=0, transfer_ns=0, total_ns=1)
        with self.assertRaisesRegex(ValueError, 'canonical is not lowest cost'):
            retained.validate_receipt(receipt)


if __name__ == '__main__':
    unittest.main()
