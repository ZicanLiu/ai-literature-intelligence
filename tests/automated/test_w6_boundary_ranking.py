"""Issue #64 tests for the label-free Boundary-Aware ranking prototype."""

from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.run_w6_boundary_ranking import main as boundary_cli_main

from src.w6_boundary_ranking import (
    BOUNDARY_DIMENSIONS,
    BoundaryAssessment,
    BoundaryRankingConfig,
    DeterministicFakeBoundaryBackend,
    DeterministicLexicalBoundaryBackend,
    build_boundary_aware_rankings,
    build_w6_boundary_method_package,
    load_boundary_ranking_config_artifact,
    load_boundary_ranking_config,
    load_w6_boundary_generation_inputs,
    validate_w6_boundary_method_package,
)
from src.w6_contracts import load_json_object, validate_w6_bootstrap_bundle
from src.w6_method_contract import (
    compute_method_configuration_hash,
    validate_w6_method_package,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_bootstrap"
    / "valid"
    / "bundle_manifest.json"
)
CONFIG = PROJECT_ROOT / "configs" / "w6" / "boundary_aware_structured_lexical_v1.json"
SAFE_INPUTS = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_bootstrap"
    / "valid"
    / "boundary_generation_inputs.json"
)
COMMITTED_METHOD_FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_issue64"
    / "boundary_method"
    / "manifest.json"
)
BASE_REVISION = "90811052194801263708627c1eda39a2765e9037"


def assessment(
    value: float, *, mismatch: float = 0.0, missing_abstract: bool = False
) -> BoundaryAssessment:
    return BoundaryAssessment(
        dimension_scores={dimension: value for dimension in BOUNDARY_DIMENSIONS},
        scope_out_overlap=mismatch,
        boundary_case_overlap=0.0,
        missing_abstract=missing_abstract,
        evidence_summary="Deterministic synthetic compatibility assessment.",
    )


class W6BoundaryRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BOOTSTRAP)
        cls.inputs = load_w6_boundary_generation_inputs(SAFE_INPUTS)
        cls.config_artifact = load_boundary_ranking_config_artifact(CONFIG)

    def _builder_kwargs(self, output_dir: Path) -> dict:
        payloads = self.inputs.payloads
        return {
            "topics": self.inputs.topics,
            "pool_members": self.inputs.pool_members,
            "records": self.inputs.records,
            "artifact_registry": self.inputs.registry,
            "topic_reference": self.inputs.registry[
                payloads["topic_set"]["artifact_id"]
            ],
            "candidate_pool_reference": self.inputs.registry[
                payloads["candidate_pool"]["artifact_id"]
            ],
            "source_records_reference": self.inputs.registry[
                payloads["source_records"]["artifact_id"]
            ],
            "retrieval_reference": self.inputs.registry[
                payloads["retrieval_provenance"]["artifact_id"]
            ],
            "canonical_reference": self.inputs.registry[
                payloads["canonical_entities"]["artifact_id"]
            ],
            "frozen_input_paths": [
                self.inputs.manifest_path,
                *self.inputs.paths.values(),
            ],
            "config_artifact": self.config_artifact,
            "output_dir": output_dir,
            "is_fixture": True,
            "generated_at": "2026-08-24T14:51:21+08:00",
            "frozen_at": "2026-08-24T14:51:22+08:00",
            "git_revision": BASE_REVISION,
            "git_worktree_clean": True,
            "backend": DeterministicLexicalBoundaryBackend(),
        }

    def test_preregistered_config_matches_frozen_defaults_and_rejects_label_access(
        self,
    ) -> None:
        self.assertEqual(load_boundary_ranking_config(CONFIG), BoundaryRankingConfig())
        payload = load_json_object(CONFIG)
        payload["input_policy"]["hidden_test_labels_read"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no-label policy"):
                load_boundary_ranking_config(config_path)

    def test_committed_boundary_method_fixture_validates(self) -> None:
        result = validate_w6_boundary_method_package(
            COMMITTED_METHOD_FIXTURE,
            artifact_registry=self.inputs.registry,
            pool_members=self.inputs.pool_members,
            source_config_path=CONFIG,
        )
        self.assertEqual(result["method_id"], "boundary_aware_structured_lexical_v1")
        self.assertEqual(len(result["ranking_rows"]), len(self.bundle["pool_members"]))

    def test_fake_backend_generation_is_deterministic_and_dynamic(self) -> None:
        assessments = {
            item_id: assessment(0.8 if index % 2 == 0 else 0.2)
            for index, item_id in enumerate(sorted(self.bundle["pool_members"]))
        }
        backend = DeterministicFakeBoundaryBackend(assessments)
        first = build_boundary_aware_rankings(
            topics=self.bundle["topics"],
            pool_members=self.bundle["pool_members"],
            records=self.bundle["records"],
            backend=backend,
        )
        reversed_pool = dict(reversed(list(self.bundle["pool_members"].items())))
        second = build_boundary_aware_rankings(
            topics=self.bundle["topics"],
            pool_members=reversed_pool,
            records=self.bundle["records"],
            backend=backend,
        )
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual(len(first["rows"]), len(self.bundle["pool_members"]))

    def test_boundary_mismatch_penalizes_otherwise_equal_candidate(self) -> None:
        topic_id = "topic_test"
        topics = {
            topic_id: {
                "research_question": "classify stellar spectra",
                "scientific_object": "stars",
                "data_modality": "optical spectra",
                "target_task": "classification",
                "method_role": "primary classifier",
                "scope_in": ["stellar spectra classification"],
                "scope_out": ["galaxy regression"],
                "boundary_cases": ["parameter regression instead of classification"],
            }
        }
        records = {
            "record_a": {"title": "same text", "abstract": "same text"},
            "record_b": {"title": "same text", "abstract": "same text"},
        }
        pool = {
            "item_a": {"topic_id": topic_id, "record_id": "record_a"},
            "item_b": {"topic_id": topic_id, "record_id": "record_b"},
        }
        backend = DeterministicFakeBoundaryBackend(
            {"item_a": assessment(1.0), "item_b": assessment(1.0, mismatch=1.0)}
        )
        result = build_boundary_aware_rankings(
            topics=topics, pool_members=pool, records=records, backend=backend
        )
        rows = {row["pair_id"]: row for row in result["rows"]}
        self.assertGreater(rows["item_a"]["score"], rows["item_b"]["score"])
        self.assertEqual(rows["item_a"]["rank"], 1)

    def test_missing_abstract_is_retained_with_title_only(self) -> None:
        result = build_boundary_aware_rankings(
            topics=self.bundle["topics"],
            pool_members=self.bundle["pool_members"],
            records=self.bundle["records"],
            backend=DeterministicLexicalBoundaryBackend(),
        )
        missing_items = {
            item_id
            for item_id, member in self.bundle["pool_members"].items()
            if self.bundle["records"][member["record_id"]]["abstract"] is None
        }
        ranked_items = {row["pair_id"] for row in result["rows"]}
        self.assertTrue(missing_items)
        self.assertTrue(missing_items <= ranked_items)
        self.assertTrue(
            all(
                result["diagnostics"][item_id]["missing_abstract"]
                for item_id in missing_items
            )
        )

    def test_invalid_fake_assessment_fails_closed(self) -> None:
        item_ids = sorted(self.bundle["pool_members"])
        invalid = BoundaryAssessment(
            dimension_scores={"scientific_object": 0.5},
            scope_out_overlap=0.0,
            boundary_case_overlap=0.0,
            missing_abstract=False,
            evidence_summary="Deliberately incomplete deterministic assessment.",
        )
        backend = DeterministicFakeBoundaryBackend(
            {
                item_id: (invalid if item_id == item_ids[0] else assessment(0.5))
                for item_id in item_ids
            }
        )
        with self.assertRaisesRegex(ValueError, "dimensions 不完整"):
            build_boundary_aware_rankings(
                topics=self.bundle["topics"],
                pool_members=self.bundle["pool_members"],
                records=self.bundle["records"],
                backend=backend,
            )

    def test_generation_api_has_no_label_input(self) -> None:
        parameters = inspect.signature(build_boundary_aware_rankings).parameters
        self.assertFalse(
            {"labels", "judgements", "annotations", "metrics", "hidden_labels"}
            & set(parameters)
        )

    def test_generated_method_package_declares_auxiliary_text_and_validates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = build_w6_boundary_method_package(
                **self._builder_kwargs(Path(temp_dir) / "method")
            )
            result = validate_w6_boundary_method_package(
                manifest_path,
                artifact_registry=self.inputs.registry,
                pool_members=self.inputs.pool_members,
                source_config_path=CONFIG,
            )
            manifest = load_json_object(manifest_path)
        self.assertIn("source_records", manifest["auxiliary_inputs"])
        self.assertIn("retrieval_provenance", manifest["auxiliary_inputs"])
        self.assertIn("canonical_entities", manifest["auxiliary_inputs"])
        self.assertEqual(
            manifest["method"]["parameters"]["source_config"],
            self.config_artifact.reference,
        )
        self.assertFalse(manifest["label_access"]["relevance_labels_read"])
        self.assertFalse(manifest["label_access"]["hidden_test_labels_read"])
        self.assertEqual(len(result["ranking_rows"]), len(self.bundle["pool_members"]))

    def test_auxiliary_input_hash_drift_fails_before_generation(self) -> None:
        payloads = self.inputs.payloads
        bad_source_ref = dict(
            self.inputs.registry[payloads["source_records"]["artifact_id"]]
        )
        bad_source_ref["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                ValueError, "source_records input identity/hash drift"
            ):
                build_w6_boundary_method_package(
                    **{
                        **self._builder_kwargs(Path(temp_dir) / "method"),
                        "source_records_reference": bad_source_ref,
                    }
                )

    def test_task_scoped_loader_uses_minimal_label_free_closure(self) -> None:
        self.assertEqual(
            set(self.inputs.paths),
            {
                "topic_set",
                "retrieval_provenance",
                "source_records",
                "canonical_entities",
                "candidate_pool",
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            closure = Path(temp_dir) / "closure"
            closure.mkdir()
            shutil.copy2(SAFE_INPUTS, closure / SAFE_INPUTS.name)
            for path in self.inputs.paths.values():
                shutil.copy2(path, closure / path.name)
            copied_manifest = closure / SAFE_INPUTS.name
            loaded = load_w6_boundary_generation_inputs(copied_manifest)
            self.assertEqual(len(loaded.pool_members), len(self.inputs.pool_members))
            with patch(
                "app.run_w6_boundary_ranking.capture_generation_environment",
                return_value={
                    "git_revision": BASE_REVISION,
                    "git_worktree_clean": True,
                },
            ):
                self.assertEqual(
                    boundary_cli_main(
                        [
                            "--inputs",
                            str(copied_manifest),
                            "--config",
                            str(CONFIG),
                            "--output-dir",
                            str(Path(temp_dir) / "method"),
                        ]
                    ),
                    0,
                )
            (closure / "source_records.json").unlink()
            with self.assertRaisesRegex(ValueError, "required input 不存在"):
                load_w6_boundary_generation_inputs(copied_manifest)
            with patch(
                "app.run_w6_boundary_ranking.capture_generation_environment",
                return_value={
                    "git_revision": BASE_REVISION,
                    "git_worktree_clean": True,
                },
            ):
                self.assertEqual(
                    boundary_cli_main(
                        [
                            "--inputs",
                            str(copied_manifest),
                            "--config",
                            str(CONFIG),
                            "--output-dir",
                            str(Path(temp_dir) / "missing-input-method"),
                        ]
                    ),
                    1,
                )

    def test_boundary_cli_file_open_audit_reads_zero_label_artifacts(self) -> None:
        opened: list[str] = []

        def audit(event: str, args: tuple) -> None:
            if event == "open" and args and isinstance(args[0], str):
                opened.append(str(Path(args[0]).resolve()))

        sys.addaudithook(audit)
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.run_w6_boundary_ranking.capture_generation_environment",
            return_value={
                "git_revision": BASE_REVISION,
                "git_worktree_clean": True,
            },
        ):
            exit_code = boundary_cli_main(
                [
                    "--inputs",
                    str(SAFE_INPUTS),
                    "--config",
                    str(CONFIG),
                    "--output-dir",
                    str(Path(temp_dir) / "method"),
                ]
            )
        self.assertEqual(exit_code, 0)
        opened_names = {Path(path).name for path in opened}
        forbidden = {
            "annotation_results.json",
            "annotation_reviews.json",
            "annotation_tasks.json",
            "benchmark_manifest.json",
            "hidden_label_anchor.json",
            "evidence_units.json",
            "synthesis_input.json",
            "structured_synthesis.json",
            "bundle_manifest.json",
        }
        self.assertFalse(forbidden & opened_names)
        self.assertFalse(
            [
                path
                for path in opened
                if "method_rankings" in Path(path).parts
                or "metrics" in Path(path).name.lower()
                or "synthesis" in Path(path).name.lower()
            ]
        )
        allowed_repo_artifacts = {
            str(path.resolve())
            for path in [SAFE_INPUTS, CONFIG, *self.inputs.paths.values()]
        }
        opened_repo_artifacts = {
            path
            for path in opened
            if Path(path).suffix.lower() in {".json", ".csv"}
            and Path(path).is_relative_to(PROJECT_ROOT)
        }
        self.assertEqual(opened_repo_artifacts, allowed_repo_artifacts)
        self.assertTrue(
            {
                "boundary_generation_inputs.json",
                "topics.json",
                "retrieval_runs.json",
                "source_records.json",
                "canonical_entities.json",
                "candidate_pool.json",
                CONFIG.name,
            }
            <= opened_names
        )

    def test_source_config_identity_is_bound_even_when_scoring_is_unchanged(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as config_dir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(config_dir)
            config_payload = load_json_object(CONFIG)
            config_payload["selection_reason"] += " Provenance-only test amendment."
            alternate_config = root / "config.json"
            alternate_config.write_text(json.dumps(config_payload), encoding="utf-8")
            alternate = load_boundary_ranking_config_artifact(alternate_config)
            kwargs = self._builder_kwargs(Path(output_dir) / "method")
            kwargs["config_artifact"] = alternate
            manifest_path = build_w6_boundary_method_package(**kwargs)
            with self.assertRaisesRegex(
                ValueError, "source config identity/hash drift"
            ):
                validate_w6_boundary_method_package(
                    manifest_path,
                    artifact_registry=self.inputs.registry,
                    pool_members=self.inputs.pool_members,
                    source_config_path=CONFIG,
                )

    def test_source_config_after_generation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as config_dir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(config_dir)
            payload = load_json_object(CONFIG)
            late_config = root / "late_config.json"
            late_config.write_text(json.dumps(payload), encoding="utf-8")
            kwargs = self._builder_kwargs(Path(output_dir) / "method")
            kwargs["config_artifact"] = load_boundary_ranking_config_artifact(
                late_config
            )
            manifest_path = build_w6_boundary_method_package(**kwargs)

            payload["frozen_at"] = "2026-08-24T14:51:22+08:00"
            late_config.write_text(json.dumps(payload), encoding="utf-8")
            late_artifact = load_boundary_ranking_config_artifact(late_config)
            manifest = load_json_object(manifest_path)
            manifest["method"]["parameters"]["source_config"] = late_artifact.reference
            manifest["freeze"]["configuration_sha256"] = (
                compute_method_configuration_hash(manifest)
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            validate_w6_method_package(
                manifest_path,
                artifact_registry=self.inputs.registry,
                pool_members=self.inputs.pool_members,
                known_method_packages={},
            )
            with self.assertRaisesRegex(ValueError, "先 freeze 再 generation"):
                validate_w6_boundary_method_package(
                    manifest_path,
                    artifact_registry=self.inputs.registry,
                    pool_members=self.inputs.pool_members,
                    source_config_path=late_config,
                )

    def test_self_consistent_method_freeze_before_generation_fails_strict_layer(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = build_w6_boundary_method_package(
                **self._builder_kwargs(Path(temp_dir) / "method")
            )
            manifest = load_json_object(manifest_path)
            manifest["freeze"]["frozen_at"] = "2026-08-24T14:51:20+08:00"
            manifest["freeze"]["configuration_sha256"] = (
                compute_method_configuration_hash(manifest)
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            validate_w6_method_package(
                manifest_path,
                artifact_registry=self.inputs.registry,
                pool_members=self.inputs.pool_members,
                known_method_packages={},
            )
            with self.assertRaisesRegex(ValueError, "freeze 不得早于 generation"):
                validate_w6_boundary_method_package(
                    manifest_path,
                    artifact_registry=self.inputs.registry,
                    pool_members=self.inputs.pool_members,
                    source_config_path=CONFIG,
                )

    def test_boundary_output_overlap_equal_child_ancestor_and_resolved_fails(
        self,
    ) -> None:
        input_root = self.inputs.manifest_path.parent
        cases = {
            "equal": input_root,
            "child": input_root / "generated",
            "ancestor": input_root.parent,
            "resolved": input_root / "nested" / "..",
        }
        for label, output in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError, "frozen input tree"
            ):
                build_w6_boundary_method_package(**self._builder_kwargs(output))

    def test_boundary_output_symlink_overlap_fails_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            alias = Path(temp_dir) / "input_alias"
            try:
                os.symlink(
                    self.inputs.manifest_path.parent, alias, target_is_directory=True
                )
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "frozen input tree"):
                build_w6_boundary_method_package(
                    **self._builder_kwargs(alias / "generated")
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
