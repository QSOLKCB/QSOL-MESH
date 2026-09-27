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

    def test_environment_source_commit_field_cannot_be_shadowed(self) -> None:
        for relative in (
            "phase1/environment.txt",
            "phase3/environment.txt",
            "phase4/environment.txt",
            "phase5/environment.txt",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "evidence"
                shutil.copytree(retained.EVIDENCE, root)
                path = root / relative
                lines = path.read_text(encoding="utf-8").splitlines()
                source_indexes = [
                    index
                    for index, line in enumerate(lines)
                    if line.startswith("source_commit=")
                ]
                self.assertEqual(source_indexes, [0])
                lines[0] = "source_commit=" + "0" * 40
                lines.append(f"capture_note=source_commit={retained.SOURCE_COMMIT}")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")

                original = retained.EVIDENCE
                retained.EVIDENCE = root
                try:
                    with self.assertRaisesRegex(SystemExit, "source commit drift"):
                        retained.verify_environment(relative)
                finally:
                    retained.EVIDENCE = original

    def test_environment_duplicate_source_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "evidence"
            shutil.copytree(retained.EVIDENCE, root)
            relative = "phase1/environment.txt"
            path = root / relative
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text + f"source_commit={retained.SOURCE_COMMIT}\n",
                encoding="utf-8",
            )

            original = retained.EVIDENCE
            retained.EVIDENCE = root
            try:
                with self.assertRaisesRegex(SystemExit, "source commit drift"):
                    retained.verify_environment(relative)
            finally:
                retained.EVIDENCE = original

    def test_environment_nvcc_path_cannot_be_shadowed_or_duplicated(self) -> None:
        for relative in (
            "phase1/environment.txt",
            "phase3/environment.txt",
            "phase4/environment.txt",
            "phase5/environment.txt",
        ):
            for duplicate in (False, True):
                with (
                    self.subTest(relative=relative, duplicate=duplicate),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    root = Path(temporary) / "evidence"
                    shutil.copytree(retained.EVIDENCE, root)
                    path = root / relative
                    lines = path.read_text(encoding="utf-8").splitlines()
                    indexes = [
                        index
                        for index, line in enumerate(lines)
                        if line.startswith("nvcc_path=")
                    ]
                    self.assertEqual(len(indexes), 1)

                    if duplicate:
                        lines.append("nvcc_path=/usr/bin/nvcc")
                    else:
                        lines[indexes[0]] = "nvcc_path=/usr/bin/gcc"
                        lines.append("capture_note=nvcc_path=/usr/bin/nvcc")

                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    original = retained.EVIDENCE
                    retained.EVIDENCE = root
                    try:
                        with self.assertRaisesRegex(SystemExit, "CUDA compiler path drift"):
                            retained.verify_environment(relative)
                    finally:
                        retained.EVIDENCE = original

    def test_cuda_request_items_require_exact_u64(self) -> None:
        cases = (
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                "phase1 CUDA requested items drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                "phase4 timing requested items drift",
            ),
        )
        for relative, verifier, message in cases:
            for value in (100000.0, True):
                with self.subTest(relative=relative, value=value):
                    self._mutate_json_and_reject(
                        relative,
                        lambda receipt, value=value: receipt["requested_configuration"].update(
                            items=value
                        ),
                        verifier,
                        message,
                    )

    def test_cuda_device_ordinals_require_exact_u32_identity(self) -> None:
        cases = (
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("requested_configuration", "device_ordinal"),
                "phase1 CUDA requested device ordinal drift",
            ),
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("observed_topology", "device_ordinal"),
                "phase1 CUDA observed device ordinal drift",
            ),
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("effective_execution", "device_ordinal"),
                "phase1 CUDA effective device ordinal drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("requested_configuration", "device_ordinal"),
                "phase4 timing requested device ordinal drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("observed_topology", "device_ordinal"),
                "phase4 timing observed device ordinal drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("effective_execution", "device_ordinal"),
                "phase4 timing effective device ordinal drift",
            ),
        )
        for relative, verifier, path, message in cases:
            for value in (False, 0.0, 1):
                with self.subTest(relative=relative, path=path, value=value):
                    def mutate(receipt: dict, *, path=path, value=value) -> None:
                        node = receipt
                        for key in path[:-1]:
                            node = node[key]
                        node[path[-1]] = value

                    self._mutate_json_and_reject(
                        relative,
                        mutate,
                        verifier,
                        message
                        + "|request drift|topology drift|effective execution drift"
                        + "|effective CUDA execution drift",
                    )

    def test_cuda_launch_geometry_rejects_overflow_and_booleans(self) -> None:
        cases = (
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("effective_execution",),
                "phase1 CUDA effective execution drift",
            ),
            (
                "phase1/static-verify-100000-40000.json",
                retained.verify_phase1,
                ("effective_execution", "cuda"),
                "phase1 split CUDA launch geometry drift",
            ),
            (
                "phase1/concurrent-verify-100000-40000.json",
                retained.verify_phase1,
                ("effective_execution", "cuda"),
                "phase1 split CUDA launch geometry drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("effective_execution",),
                "phase4 timing effective CUDA execution drift",
            ),
        )
        for relative, verifier, path, message in cases:
            for field in ("blocks", "threads_per_block"):
                for value in (retained.U32_MAX + 1, True):
                    with self.subTest(
                        relative=relative,
                        field=field,
                        value=value,
                    ):
                        def mutate(receipt: dict, *, field=field, value=value, path=path) -> None:
                            node = receipt
                            for key in path:
                                node = node[key]
                            node[field] = value

                        self._mutate_json_and_reject(
                            relative,
                            mutate,
                            verifier,
                            message,
                        )

    def test_cuda_block_count_matches_retained_canonical_launch(self) -> None:
        cases = (
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("effective_execution",),
                "phase1 CUDA effective execution drift",
            ),
            (
                "phase1/static-verify-100000-40000.json",
                retained.verify_phase1,
                ("effective_execution", "cuda"),
                "phase1 split CUDA launch geometry drift",
            ),
            (
                "phase1/concurrent-verify-100000-40000.json",
                retained.verify_phase1,
                ("effective_execution", "cuda"),
                "phase1 split CUDA launch geometry drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("effective_execution",),
                "phase4 timing effective CUDA execution drift",
            ),
        )
        for relative, verifier, path, message in cases:
            with self.subTest(relative=relative):
                def mutate(receipt: dict, *, path=path) -> None:
                    node = receipt
                    for key in path:
                        node = node[key]
                    node["blocks"] = 1

                self._mutate_json_and_reject(
                    relative,
                    mutate,
                    verifier,
                    message,
                )

    def test_cuda_thread_width_matches_canonical_worker(self) -> None:
        cases = (
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("effective_execution",),
                "phase1 CUDA effective execution drift",
            ),
            (
                "phase1/static-verify-100000-40000.json",
                retained.verify_phase1,
                ("effective_execution", "cuda"),
                "phase1 split CUDA launch geometry drift",
            ),
            (
                "phase1/concurrent-verify-100000-40000.json",
                retained.verify_phase1,
                ("effective_execution", "cuda"),
                "phase1 split CUDA launch geometry drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("effective_execution",),
                "phase4 timing effective CUDA execution drift",
            ),
        )
        for relative, verifier, path, message in cases:
            with self.subTest(relative=relative):
                def mutate(receipt: dict, *, path=path) -> None:
                    node = receipt
                    for key in path:
                        node = node[key]
                    node["threads_per_block"] = 1

                self._mutate_json_and_reject(
                    relative,
                    mutate,
                    verifier,
                    message,
                )

    def test_phase3_topology_device_ordinal_requires_exact_u32(self) -> None:
        for relative in ("phase3/one-chunk.json", "phase3/multi-chunk.json"):
            for value in (False, 0.0, 1):
                with self.subTest(relative=relative, value=value):
                    self._mutate_json_and_reject(
                        relative,
                        lambda receipt, value=value: receipt["observed_topology"].update(
                            device_ordinal=value
                        ),
                        retained.verify_phase3,
                        "phase3 observed CUDA device ordinal drift|phase3 observed CUDA topology drift",
                    )

    def test_phase4_timing_activation_requires_boolean_true(self) -> None:
        for value in (1, 1.0, "true"):
            with self.subTest(value=value):
                self._mutate_json_and_reject(
                    "phase4/timing.json",
                    lambda receipt, value=value: receipt["requested_configuration"].update(
                        timing=value
                    ),
                    retained.verify_phase4,
                    "phase4 timing activation flag drift",
                )

    def test_stream_numeric_fields_reject_boolean_coercion(self) -> None:
        cases = (
            (("effective_execution", "effective_chunk_items"), "phase3 effective chunk geometry drift"),
            (("effective_execution", "chunk_count"), "phase3 chunk count drift"),
            (("effective_execution", "event_records"), "phase3 CUDA event count drift"),
            (("memory_plan", "host_pinned_peak_bytes"), "phase3 peak memory geometry drift"),
            (("memory_plan", "accelerator_peak_bytes"), "phase3 peak memory geometry drift"),
            (("memory_plan", "partial_bytes"), "phase3 partial byte width drift"),
            (("memory_plan", "pinned_staging_allocations"), "phase3 reusable allocation geometry drift"),
            (("memory_plan", "pinned_partial_allocations"), "phase3 reusable allocation geometry drift"),
            (("memory_plan", "device_pool_allocations"), "phase3 reusable allocation geometry drift"),
            (("memory_plan", "device_partial_allocations"), "phase3 reusable allocation geometry drift"),
        )
        for relative in ("phase3/one-chunk.json", "phase3/multi-chunk.json"):
            for path, message in cases:
                with self.subTest(relative=relative, path=path):
                    def mutate(receipt: dict, *, path=path) -> None:
                        node = receipt
                        for key in path[:-1]:
                            node = node[key]
                        node[path[-1]] = True

                    self._mutate_json_and_reject(
                        relative,
                        mutate,
                        retained.verify_phase3,
                        message,
                    )

    def test_stream_request_numeric_fields_reject_booleans(self) -> None:
        for field in (
            "items",
            "requested_chunk_items",
            "host_pinned_limit_bytes",
            "accelerator_limit_bytes",
            "device_ordinal",
        ):
            with self.subTest(field=field):
                self._mutate_json_and_reject(
                    "phase3/one-chunk.json",
                    lambda receipt, field=field: receipt["requested_configuration"].update(
                        {field: True}
                    ),
                    retained.verify_phase3,
                    "phase3 stream request drift|phase3 invalid retained stream bounds",
                )

    def test_split_cuda_ordinals_require_exact_u32_identity(self) -> None:
        cases = (
            (
                ("observed_topology", "cuda_device_ordinal"),
                "phase1 split observed CUDA device ordinal drift",
            ),
            (
                ("effective_execution", "cuda", "device_ordinal"),
                "phase1 split effective CUDA device ordinal drift",
            ),
        )
        for relative in (
            "phase1/static-verify-100000-40000.json",
            "phase1/concurrent-verify-100000-40000.json",
        ):
            for path, message in cases:
                for value in (False, 0.0, 1):
                    with self.subTest(relative=relative, path=path, value=value):
                        def mutate(receipt: dict, *, path=path, value=value) -> None:
                            node = receipt
                            for key in path[:-1]:
                                node = node[key]
                            node[path[-1]] = value

                        self._mutate_json_and_reject(
                            relative,
                            mutate,
                            retained.verify_phase1,
                            message
                            + "|phase1 split observed CUDA topology drift"
                            + "|phase1 split observed/effective CUDA device drift"
                            + "|phase1 split CUDA device drift",
                        )

    def test_phase1_cpu_request_geometry_requires_exact_integers(self) -> None:
        for field, value in (
            ("items", 100000.0),
            ("items", True),
            ("workers", 8.0),
            ("workers", True),
        ):
            with self.subTest(field=field, value=value):
                self._mutate_json_and_reject(
                    "phase1/cpu-verify-100000.json",
                    lambda receipt, field=field, value=value: receipt["requested_configuration"].update(
                        {field: value}
                    ),
                    retained.verify_phase1,
                    "phase1 CPU request numeric field drift",
                )

    def test_phase3_verified_status_requires_boolean_true(self) -> None:
        for relative in ("phase3/one-chunk.json", "phase3/multi-chunk.json"):
            for value in (1, 1.0, "true"):
                with self.subTest(relative=relative, value=value):
                    self._mutate_json_and_reject(
                        relative,
                        lambda receipt, value=value: receipt["verification"].update(
                            verified=value
                        ),
                        retained.verify_phase3,
                        "phase3 verified status drift",
                    )

    def test_verified_status_requires_boolean_true_across_receipts(self) -> None:
        cases = (
            (
                "phase1/cpu-verify-100000.json",
                retained.verify_phase1,
                ("verification",),
                "phase1 CPU verified status drift",
            ),
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("verification",),
                "phase1 CUDA verified status drift",
            ),
            (
                "phase1/static-verify-100000-40000.json",
                retained.verify_phase1,
                ("verification",),
                "phase1 static verified status drift",
            ),
            (
                "phase1/concurrent-verify-100000-40000.json",
                retained.verify_phase1,
                ("verification",),
                "phase1 concurrent verified status drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("verification",),
                "phase4 timing verified status drift",
            ),
            (
                "phase4/calibration.json",
                retained.verify_phase4,
                ("verification",),
                "phase4: calibration verified status drift",
            ),
            (
                "phase5/adaptive.json",
                retained.verify_phase5,
                ("verification",),
                "phase5 aggregate verified status drift",
            ),
        )
        for relative, verifier, path, message in cases:
            for value in (1, 1.0, "true"):
                with self.subTest(relative=relative, value=value):
                    def mutate(receipt: dict, *, path=path, value=value) -> None:
                        node = receipt
                        for key in path:
                            node = node[key]
                        node["verified"] = value

                    self._mutate_json_and_reject(
                        relative,
                        mutate,
                        verifier,
                        message,
                    )

    def test_calibration_topology_device_ordinal_requires_exact_u32(self) -> None:
        for relative, verifier, path, message in (
            (
                "phase4/calibration.json",
                retained.verify_phase4,
                ("observed_topology", "device_ordinal"),
                "phase4: calibration topology device ordinal drift",
            ),
            (
                "phase5/adaptive.json",
                retained.verify_phase5,
                (
                    "effective_execution",
                    "phases",
                    0,
                    "calibration_receipt",
                    "observed_topology",
                    "device_ordinal",
                ),
                "phase5 phase 0: calibration topology device ordinal drift",
            ),
        ):
            for value in (False, 0.0, 1):
                with self.subTest(relative=relative, value=value):
                    def mutate(receipt: dict, *, path=path, value=value) -> None:
                        node = receipt
                        for key in path[:-1]:
                            node = node[key]
                        node[path[-1]] = value

                    self._mutate_json_and_reject(
                        relative,
                        mutate,
                        verifier,
                        message + "|CUDA calibration topology/identity drift",
                    )

    def test_phase5_cuda_activation_requires_boolean_true(self) -> None:
        for value in (1, 1.0, "true"):
            with self.subTest(value=value):
                self._mutate_json_and_reject(
                    "phase5/adaptive.json",
                    lambda receipt, value=value: receipt["requested_configuration"].update(
                        cuda=value
                    ),
                    retained.verify_phase5,
                    "phase5 CUDA activation flag drift",
                )

    def test_accelerator_observed_claims_require_boolean_true(self) -> None:
        cases = (
            (
                "phase1/cuda-verify-100000.json",
                retained.verify_phase1,
                ("observed_topology", "accelerator_observed"),
                "phase1 CUDA accelerator-observed claim drift",
            ),
            (
                "phase1/static-verify-100000-40000.json",
                retained.verify_phase1,
                ("observed_topology", "accelerator_observed"),
                "phase1 split accelerator-observed claim drift",
            ),
            (
                "phase1/concurrent-verify-100000-40000.json",
                retained.verify_phase1,
                ("observed_topology", "accelerator_observed"),
                "phase1 split accelerator-observed claim drift",
            ),
            (
                "phase3/one-chunk.json",
                retained.verify_phase3,
                ("observed_topology", "accelerator_observed"),
                "phase3 accelerator-observed claim drift",
            ),
            (
                "phase3/multi-chunk.json",
                retained.verify_phase3,
                ("observed_topology", "accelerator_observed"),
                "phase3 accelerator-observed claim drift",
            ),
            (
                "phase4/timing.json",
                retained.verify_phase4,
                ("observed_topology", "accelerator_observed"),
                "phase4 timing accelerator-observed claim drift",
            ),
            (
                "phase4/calibration.json",
                retained.verify_phase4,
                ("observed_topology", "accelerator_observed"),
                "phase4: calibration accelerator-observed claim drift",
            ),
            (
                "phase5/adaptive.json",
                retained.verify_phase5,
                ("observed_topology", "accelerator_observed"),
                "phase5 accelerator-observed claim drift",
            ),
            (
                "phase5/adaptive.json",
                retained.verify_phase5,
                (
                    "effective_execution",
                    "phases",
                    0,
                    "calibration_receipt",
                    "observed_topology",
                    "accelerator_observed",
                ),
                "phase5 phase 0: calibration accelerator-observed claim drift",
            ),
        )
        for relative, verifier, path, message in cases:
            for value in (1, 1.0, "true"):
                with self.subTest(relative=relative, path=path, value=value):
                    def mutate(receipt: dict, *, path=path, value=value) -> None:
                        node = receipt
                        for key in path[:-1]:
                            node = node[key]
                        node[path[-1]] = value

                    self._mutate_json_and_reject(
                        relative,
                        mutate,
                        verifier,
                        message,
                    )

    def test_concurrent_dispatch_contract_requires_boolean_fields(self) -> None:
        cases = (
            ("cpu_task_spawned_before_cuda_call", (1, 1.0, "true")),
            ("cpu_joined_after_cuda_call_return", (1, 1.0, "true")),
            ("kernel_overlap_measured", (0, 0.0, "false")),
        )
        for field, values in cases:
            for value in values:
                with self.subTest(field=field, value=value):
                    def mutate(receipt: dict, *, field=field, value=value) -> None:
                        receipt["effective_execution"]["dispatch_contract"][field] = value

                    self._mutate_json_and_reject(
                        "phase1/concurrent-verify-100000-40000.json",
                        mutate,
                        retained.verify_phase1,
                        "phase1 concurrent dispatch Boolean evidence drift",
                    )

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

    def test_calibration_work_units_require_exact_u64(self) -> None:
        cases = (
            ("observations", 0, 10000.0, "phase4 calibration candidate 0: invalid observation work size"),
            ("observations", 0, True, "phase4 calibration candidate 0: invalid observation work size"),
            ("full_work_confirmation", 0, 100000.0, "phase4 confirmation candidate 0: invalid observation work size"),
            ("full_work_confirmation", 0, True, "phase4 confirmation candidate 0: invalid observation work size"),
        )
        for collection, index, value, message in cases:
            with self.subTest(collection=collection, value=value):
                def mutate(
                    receipt: dict,
                    *,
                    collection=collection,
                    index=index,
                    value=value,
                ) -> None:
                    receipt["calibration"][collection][index]["work_units"] = value

                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    mutate,
                    retained.verify_phase4,
                    message,
                )

    def test_calibration_request_work_fields_require_exact_integers(self) -> None:
        for field, value in (
            ("calibration_items", 10000.0),
            ("full_work_items", 100000.0),
        ):
            with self.subTest(field=field):
                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    lambda receipt, field=field, value=value: receipt["requested_configuration"].update(
                        {field: value}
                    ),
                    retained.verify_phase4,
                    "phase4: calibration work bounds drift",
                )

    def test_calibration_candidate_ids_reject_boolean_coercion(self) -> None:
        cases = (
            (
                ("calibration", "candidates", 0, "id"),
                "phase4: calibration candidate field types drift",
            ),
            (
                ("calibration", "observations", 0, "candidate_id"),
                "phase4: calibration observation candidate ID type drift",
            ),
            (
                ("calibration", "full_work_confirmation", 0, "candidate_id"),
                "phase4: confirmation candidate ID type drift",
            ),
            (
                ("effective_execution", "provisional_candidate_id"),
                "phase4: effective candidate ID type drift",
            ),
            (
                ("effective_execution", "selected_candidate_id"),
                "phase4: effective candidate ID type drift",
            ),
            (
                ("effective_execution", "canonical_candidate_id"),
                "phase4: effective candidate ID type drift",
            ),
        )
        for path, message in cases:
            with self.subTest(path=path):
                def mutate(receipt: dict, *, path=path) -> None:
                    node = receipt
                    for key in path[:-1]:
                        node = node[key]
                    node[path[-1]] = False

                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    mutate,
                    retained.verify_phase4,
                    message,
                )

    def test_calibration_candidate_numeric_fields_reject_boolean_coercion(self) -> None:
        cases = (
            (("calibration", "candidate_budget"), "phase4: calibration candidate budget drift"),
            (
                ("calibration", "candidates", 1, "cpu_workers"),
                "phase4: calibration candidate field types drift",
            ),
            (
                ("calibration", "candidates", 2, "accelerator_share_bps"),
                "phase4: calibration candidate field types drift",
            ),
        )
        for path, message in cases:
            with self.subTest(path=path):
                def mutate(receipt: dict, *, path=path) -> None:
                    node = receipt
                    for key in path[:-1]:
                        node = node[key]
                    node[path[-1]] = True

                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    mutate,
                    retained.verify_phase4,
                    message,
                )

    def test_split_requested_workers_require_exact_integer(self) -> None:
        for relative in (
            "phase1/static-verify-100000-40000.json",
            "phase1/concurrent-verify-100000-40000.json",
        ):
            for value in (8.0, True):
                with self.subTest(relative=relative, value=value):
                    self._mutate_json_and_reject(
                        relative,
                        lambda receipt, value=value: receipt["effective_execution"]["cpu"].update(
                            requested_workers=value
                        ),
                        retained.verify_phase1,
                        "phase1 split requested CPU workers drift",
                    )

    def test_split_request_numeric_fields_require_exact_integers(self) -> None:
        cases = (
            ("items", 100000.0),
            ("cpu_items", 40000.0),
            ("cpu_workers", 8.0),
            ("device_ordinal", False),
        )
        for relative in (
            "phase1/static-verify-100000-40000.json",
            "phase1/concurrent-verify-100000-40000.json",
        ):
            for field, value in cases:
                with self.subTest(relative=relative, field=field):
                    self._mutate_json_and_reject(
                        relative,
                        lambda receipt, field=field, value=value: receipt["requested_configuration"].update(
                            {field: value}
                        ),
                        retained.verify_phase1,
                        "phase1 split request numeric field drift",
                    )

    def test_split_range_boundaries_reject_boolean_coercion(self) -> None:
        cases = (
            ("cpu", "range_start", False, "phase1 CPU split range drift"),
            ("cpu", "range_end", True, "phase1 CPU split range drift"),
            ("cuda", "range_start", True, "phase1 CUDA split range drift"),
            ("cuda", "range_end", True, "phase1 CUDA split range drift"),
        )
        for relative in (
            "phase1/static-verify-100000-40000.json",
            "phase1/concurrent-verify-100000-40000.json",
        ):
            for partition, field, value, message in cases:
                with self.subTest(
                    relative=relative,
                    partition=partition,
                    field=field,
                ):
                    def mutate(
                        receipt: dict,
                        *,
                        partition=partition,
                        field=field,
                        value=value,
                    ) -> None:
                        receipt["effective_execution"][partition][field] = value

                    self._mutate_json_and_reject(
                        relative,
                        mutate,
                        retained.verify_phase1,
                        message,
                    )

    def test_split_effective_workers_match_deterministic_execution(self) -> None:
        for relative in (
            "phase1/static-verify-100000-40000.json",
            "phase1/concurrent-verify-100000-40000.json",
        ):
            with self.subTest(relative=relative):
                self._mutate_json_and_reject(
                    relative,
                    lambda receipt: receipt["effective_execution"]["cpu"].update(
                        effective_workers=1
                    ),
                    retained.verify_phase1,
                    "phase1 split effective CPU workers drift",
                )

    def test_calibration_effective_workers_match_deterministic_execution(self) -> None:
        cases = (
            (
                1,
                1,
                "phase4 calibration candidate 1: CPU effective workers drift",
            ),
            (
                3,
                1,
                "phase4 calibration candidate 3: heterogeneous effective workers drift",
            ),
        )
        for candidate_id, value, message in cases:
            with self.subTest(candidate_id=candidate_id):
                def mutate(receipt: dict, *, candidate_id=candidate_id, value=value) -> None:
                    observation = next(
                        observation
                        for observation in receipt["calibration"]["observations"]
                        if observation["candidate_id"] == candidate_id
                    )
                    observation["effective_cpu_workers"] = value

                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    mutate,
                    retained.verify_phase4,
                    message,
                )

    def test_accelerator_total_cost_must_be_positive(self) -> None:
        def mutate(receipt: dict) -> None:
            observation = next(
                observation
                for observation in receipt["calibration"]["observations"]
                if observation["candidate_id"] == 2
            )
            observation["service_ns"] = 0
            observation["setup_ns"] = 0
            observation["transfer_ns"] = 0
            observation["total_ns"] = 0

        self._mutate_json_and_reject(
            "phase4/calibration.json",
            mutate,
            retained.verify_phase4,
            "phase4 calibration candidate 2: accelerator total cost must be positive",
        )

    def test_accelerator_confirmation_zero_total_is_rejected_by_shared_validator(self) -> None:
        candidate = {
            "id": 2,
            "backend": "accelerator",
            "cpu_workers": 0,
            "accelerator_share_bps": 10_000,
            "canonical": False,
        }
        observation = {
            "candidate_id": 2,
            "work_units": 1000,
            "effective_cpu_workers": 0,
            "service_ns": 0,
            "setup_ns": 0,
            "transfer_ns": 0,
            "total_ns": 0,
            "checksum": retained.smoke_reference(1000),
            "verified": True,
        }
        with self.assertRaisesRegex(
            SystemExit,
            "confirmation candidate 2: accelerator total cost must be positive",
        ):
            retained.validate_cost_observation(
                observation,
                candidate=candidate,
                work_units=1000,
                context="confirmation candidate 2",
            )

    def test_accelerator_service_and_total_stay_within_formula_width(self) -> None:
        for mode in ("service", "total"):
            with self.subTest(mode=mode):
                def mutate(receipt: dict, *, mode=mode) -> None:
                    observation = next(
                        observation
                        for observation in receipt["calibration"]["observations"]
                        if observation["candidate_id"] == 2
                    )
                    limit = 2 * retained.U64_MAX
                    if mode == "service":
                        observation["service_ns"] = limit + 1
                        observation["total_ns"] = (
                            observation["service_ns"]
                            + observation["setup_ns"]
                            + observation["transfer_ns"]
                        )
                    else:
                        observation["total_ns"] = limit + 1
                        observation["service_ns"] = (
                            observation["total_ns"]
                            - observation["setup_ns"]
                            - observation["transfer_ns"]
                        )

                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    mutate,
                    retained.verify_phase4,
                    "phase4 calibration candidate 2: accelerator service/total provenance width drift",
                )

    def test_accelerator_timing_components_stay_within_u64(self) -> None:
        for field in ("setup_ns", "transfer_ns"):
            with self.subTest(field=field):
                def mutate(receipt: dict, *, field=field) -> None:
                    observation = next(
                        observation
                        for observation in receipt["calibration"]["observations"]
                        if observation["candidate_id"] == 2
                    )
                    observation[field] = retained.U64_MAX + 1
                    observation["total_ns"] = (
                        observation["service_ns"]
                        + observation["setup_ns"]
                        + observation["transfer_ns"]
                    )

                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    mutate,
                    retained.verify_phase4,
                    "phase4 calibration candidate 2: accelerator timing component width drift",
                )

    def test_selected_worker_counts_reject_boolean_coercion(self) -> None:
        for field in (
            "selected_requested_cpu_workers",
            "selected_effective_cpu_workers",
        ):
            with self.subTest(field=field):
                self._mutate_json_and_reject(
                    "phase4/calibration.json",
                    lambda receipt, field=field: receipt["effective_execution"].update(
                        {field: True}
                    ),
                    retained.verify_phase4,
                    "phase4: selected worker field types/bounds drift",
                )

    def test_phase5_identity_fields_reject_boolean_coercion(self) -> None:
        cases = (
            ("phase_index", False),
            ("items", True),
        )
        for field, value in cases:
            with self.subTest(field=field):
                def mutate(receipt: dict, *, field=field, value=value) -> None:
                    receipt["effective_execution"]["phases"][0][field] = value

                self._mutate_json_and_reject(
                    "phase5/adaptive.json",
                    mutate,
                    retained.verify_phase5,
                    "phase5 phase identity drift",
                )

    def test_phase5_execution_geometry_rejects_boolean_coercion(self) -> None:
        for field in (
            "requested_cpu_workers",
            "effective_cpu_workers",
            "cpu_items",
            "cuda_items",
        ):
            with self.subTest(field=field):
                def mutate(receipt: dict, *, field=field) -> None:
                    receipt["effective_execution"]["phases"][0]["execution"][field] = True

                self._mutate_json_and_reject(
                    "phase5/adaptive.json",
                    mutate,
                    retained.verify_phase5,
                    "phase5 execution geometry field types/bounds drift",
                )

    def test_phase5_execution_duration_must_be_positive_integer(self) -> None:
        for value in (0, True):
            with self.subTest(value=value):
                def mutate(receipt: dict, *, value=value) -> None:
                    receipt["effective_execution"]["phases"][0]["execution_host_ns"] = value

                self._mutate_json_and_reject(
                    "phase5/adaptive.json",
                    mutate,
                    retained.verify_phase5,
                    "phase5 phase 0: invalid execution_host_ns",
                )

    def test_phase5_outer_calibration_duration_covers_repeat_aware_sequential_measurements(self) -> None:
        for mode in ("one-ns", "max-only", "median-sum-only"):
            with self.subTest(mode=mode):
                def mutate(receipt: dict, *, mode=mode) -> None:
                    phase = receipt["effective_execution"]["phases"][0]
                    nested = (
                        phase["calibration_receipt"]["calibration"]["observations"]
                        + phase["calibration_receipt"]["calibration"]["full_work_confirmation"]
                    )
                    totals = [observation["total_ns"] for observation in nested]
                    if mode == "one-ns":
                        phase["calibration_host_ns"] = 1
                    elif mode == "max-only":
                        phase["calibration_host_ns"] = max(totals)
                    else:
                        phase["calibration_host_ns"] = sum(totals)

                self._mutate_json_and_reject(
                    "phase5/adaptive.json",
                    mutate,
                    retained.verify_phase5,
                    "phase5 phase 0: calibration host duration shorter than repeat-aware sequential nested measurements",
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

    def test_phase5_completed_phase_count_requires_integer(self) -> None:
        for value in (3.0, True):
            with self.subTest(value=value):
                self._mutate_json_and_reject(
                    "phase5/adaptive.json",
                    lambda receipt, value=value: receipt["effective_execution"].update(
                        completed_phases=value
                    ),
                    retained.verify_phase5,
                    "phase5 requested/completed/retained phase count mismatch",
                )

    def test_phase5_plan_change_count_rejects_boolean_coercion(self) -> None:
        self._mutate_json_and_reject(
            "phase5/adaptive.json",
            lambda receipt: receipt["effective_execution"].update(plan_changes=False),
            retained.verify_phase5,
            "phase5 adaptive boundary drift",
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
