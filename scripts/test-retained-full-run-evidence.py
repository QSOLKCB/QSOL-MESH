#!/usr/bin/env python3
"""Deterministic adversarial regression tests for the full retained-evidence validator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

VALIDATOR = Path(__file__).with_name("validate-retained-full-run-evidence.py")
spec = importlib.util.spec_from_file_location("retained_full_run", VALIDATOR)
retained = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(retained)


class RetainedFullRunEvidenceRegressionTest(unittest.TestCase):
    def _mutate_json_and_reject(
        self,
        relative: str,
        mutate,
        verifier,
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "evidence"
            shutil.copytree(retained.EVIDENCE, root)
            path = root / relative
            data = json.loads(path.read_text(encoding="utf-8"))
            mutate(data)
            path.write_text(
                json.dumps(data, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            original = retained.EVIDENCE
            retained.EVIDENCE = root
            try:
                with self.assertRaisesRegex(SystemExit, message):
                    verifier()
            finally:
                retained.EVIDENCE = original

    def test_original_bundle(self) -> None:
        retained.main()

    def test_every_pinned_file_rejects_byte_drift(self) -> None:
        for relative in sorted(retained.EXPECTED_SHA256):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "evidence"
                shutil.copytree(retained.EVIDENCE, root)
                path = root / relative
                path.write_bytes(path.read_bytes() + b"\n")

                original = retained.EVIDENCE
                retained.EVIDENCE = root
                try:
                    with self.assertRaisesRegex(SystemExit, "SHA-256 drift"):
                        retained.verify_hashes()
                finally:
                    retained.EVIDENCE = original

    def test_phase1_cpu_topology_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase1/cpu-verify-100000.json",
            lambda receipt: receipt["observed_topology"].update(available_parallelism=0),
            retained.verify_phase1,
            "phase1 CPU observed topology drift",
        )

    def test_phase1_cuda_oracle_kind_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase1/cuda-verify-100000.json",
            lambda receipt: receipt["verification"].update(kind="peer-checksum-equality"),
            retained.verify_phase1,
            "phase1 CUDA oracle drift",
        )

    def test_phase1_static_execution_kind_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase1/static-verify-100000-40000.json",
            lambda receipt: receipt["effective_execution"].update(kind="dynamic-work-stealing"),
            retained.verify_phase1,
            "phase1 static effective execution kind drift",
        )

    def test_phase1_concurrent_execution_kind_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase1/concurrent-verify-100000-40000.json",
            lambda receipt: receipt["effective_execution"].update(kind="dynamic-work-stealing"),
            retained.verify_phase1,
            "phase1 concurrent effective execution kind drift",
        )

    def test_phase3_multi_chunk_provenance_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase3/multi-chunk.json",
            lambda receipt: receipt["source_identity"].update(
                worker_protocol="qsol.mesh.cuda-stream-worker.v999"
            ),
            retained.verify_phase3,
            "phase3 stream source identity drift",
        )

    def test_phase3_one_chunk_event_geometry_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase3/one-chunk.json",
            lambda receipt: receipt["effective_execution"].update(event_records=0),
            retained.verify_phase3,
            "phase3 CUDA event count drift",
        )

    def test_phase4_timing_clock_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase4/timing.json",
            lambda receipt: receipt["timing"]["clock_sources"].update(
                kernel_device_ns="rust-std-instant-monotonic"
            ),
            retained.verify_phase4,
            "phase4 timing clock source drift",
        )

    def test_phase4_calibration_candidate_geometry_mutation(self) -> None:
        def mutate(receipt: dict) -> None:
            receipt["calibration"]["candidates"][2].update(
                cpu_workers=99,
                accelerator_share_bps=0,
            )

        self._mutate_json_and_reject(
            "phase4/calibration.json",
            mutate,
            retained.verify_phase4,
            "phase4: calibration candidate geometry drift",
        )

    def test_phase5_cached_calibration_mutation(self) -> None:
        self._mutate_json_and_reject(
            "phase5/adaptive.json",
            lambda receipt: receipt["calibration"].update(
                performed_before_every_phase=False,
                cached=True,
            ),
            retained.verify_phase5,
            "phase5 calibration boundary drift",
        )

    def test_phase5_trailing_phase_mutation(self) -> None:
        def mutate(receipt: dict) -> None:
            receipt["effective_execution"]["phases"].append(
                receipt["effective_execution"]["phases"][-1].copy()
            )

        self._mutate_json_and_reject(
            "phase5/adaptive.json",
            mutate,
            retained.verify_phase5,
            "phase5 requested/completed/retained phase count mismatch",
        )


if __name__ == "__main__":
    unittest.main()
