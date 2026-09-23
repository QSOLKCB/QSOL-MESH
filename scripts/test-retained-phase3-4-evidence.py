#!/usr/bin/env python3
"""Reject edited or substituted retained evidence even with refreshed local hashes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('retained', Path(__file__).with_name('validate-retained-phase3-4-evidence.py'))
retained = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retained)


class RetainedEvidenceTest(unittest.TestCase):
    def test_original_captures(self):
        retained.validate()

    def test_modified_environment_or_receipt_cannot_be_resealed(self):
        for name in ('capture-2/environment.txt', 'capture-2/calibration.json'):
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


if __name__ == '__main__':
    unittest.main()
