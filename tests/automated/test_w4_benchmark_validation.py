from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.evaluate_w4_benchmark import main as evaluate_cli_main
from app.validate_w4_benchmark import (
    DEFAULT_MANIFEST,
    main as validate_cli_main,
)
from src.annotation_tasks import read_csv_rows, sha256_file, write_csv_rows
from src.w4_benchmark_artifact import build_benchmark_draft
from src.w4_benchmark_validation import (
    APPROVAL_CHECKLIST_FIELDS,
    JUDGEMENT_FIELDS,
    PROPOSAL_FIELDS,
    TRUSTED_W4_V01_REVIEW_DRAFT,
    compute_input_set_identity,
    validate_benchmark_package,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DRAFT_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "benchmarks"
    / "w4_query_relevance"
    / "v0.1.0-draft.1"
    / "manifest.json"
)
APPROVED_VERSION = "w4_query_relevance_pilot_v0.1.0"
APPROVED_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "benchmarks"
    / "w4_query_relevance"
    / "v0.1.0"
    / "manifest.json"
)


class BenchmarkPackageValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(dir=PROJECT_ROOT)
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_repository_draft_is_structurally_valid_but_not_strict(self) -> None:
        result = validate_benchmark_package(
            DRAFT_MANIFEST,
            project_root=PROJECT_ROOT,
            require_approved=False,
        )
        self.assertEqual(result["pair_count"], 60)
        self.assertEqual(result["manifest"]["status"], "proposed")
        self.assertEqual(len(result["labels"]), 57)
        self.assertEqual(
            result["benchmark_hash"], TRUSTED_W4_V01_REVIEW_DRAFT["sha256"]
        )
        with self.assertRaisesRegex(ValueError, "未 approved"):
            validate_benchmark_package(
                DRAFT_MANIFEST,
                project_root=PROJECT_ROOT,
                require_approved=True,
            )

    def test_builder_recreates_a_reviewable_60_pair_draft(self) -> None:
        output = self.root / "rebuilt"
        task_dir = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"
        paths = build_benchmark_draft(
            project_root=PROJECT_ROOT,
            candidate_pool_path=task_dir / "candidate_pool_v0.1.csv",
            assignments_path=task_dir / "assignments_v0.1.csv",
            research_queries_path=PROJECT_ROOT / "configs" / "w4" / "research_queries.json",
            source_sample_path=(
                PROJECT_ROOT
                / "data"
                / "samples"
                / "w2"
                / "domain_query"
                / "live_query_sample.csv"
            ),
            pool_manifest_path=task_dir / "pool_manifest_v0.1.json",
            annotations_dir=task_dir / "annotations",
            proposals_path=(DRAFT_MANIFEST.parent / "adjudication_proposals.csv"),
            output_dir=output,
        )
        result = validate_benchmark_package(
            paths["manifest"],
            project_root=PROJECT_ROOT,
            require_approved=False,
        )
        self.assertEqual(result["pair_count"], 60)
        self.assertEqual(result["manifest"]["counts"]["pending_human_review_pairs"], 3)

    def test_approved_60_pair_package_passes_strict(self) -> None:
        package = self._copy_package(self.root / "approved")
        self._approve(package)
        result = validate_benchmark_package(
            package["manifest"],
            project_root=PROJECT_ROOT,
            require_approved=True,
        )
        self.assertEqual(len(result["labels"]), 60)
        self.assertEqual(result["counts_by_query"], {
            "rq01_stellar_classification": 20,
            "rq02_stellar_parameters": 20,
            "rq03_spectral_preprocessing": 20,
        })

    def test_strict_rejects_non_60_and_duplicate_pair(self) -> None:
        missing = self._copy_package(self.root / "missing")
        self._approve(missing)
        _fields, rows = read_csv_rows(missing["judgements"])
        write_csv_rows(missing["judgements"], JUDGEMENT_FIELDS, rows[:-1])
        self._refresh_artifact_hash(missing, "judgements")
        with self.assertRaisesRegex(ValueError, "60/60"):
            self._strict(missing)

        duplicate = self._copy_package(self.root / "duplicate")
        self._approve(duplicate)
        _fields, rows = read_csv_rows(duplicate["judgements"])
        rows[-1] = dict(rows[0])
        write_csv_rows(duplicate["judgements"], JUDGEMENT_FIELDS, rows)
        self._refresh_artifact_hash(duplicate, "judgements")
        with self.assertRaisesRegex(ValueError, "pair_id"):
            self._strict(duplicate)

    def test_strict_rejects_unknown_missing_or_wrong_rq_pair_identity(self) -> None:
        unknown = self._copy_package(self.root / "unknown")
        self._approve(unknown)
        _fields, rows = read_csv_rows(unknown["judgements"])
        rows[0]["pair_id"] = "w4_unknown_001"
        write_csv_rows(unknown["judgements"], JUDGEMENT_FIELDS, rows)
        self._refresh_artifact_hash(unknown, "judgements")
        with self.assertRaisesRegex(ValueError, "未知 pair"):
            self._strict(unknown)

        wrong_rq = self._copy_package(self.root / "wrong_rq")
        self._approve(wrong_rq)
        _fields, rows = read_csv_rows(wrong_rq["judgements"])
        rows[0]["research_query_id"] = "rq02_stellar_parameters"
        write_csv_rows(wrong_rq["judgements"], JUDGEMENT_FIELDS, rows)
        self._refresh_artifact_hash(wrong_rq, "judgements")
        with self.assertRaisesRegex(ValueError, "research_query_id"):
            self._strict(wrong_rq)

    def test_strict_rejects_empty_question_mark_and_non_graded_labels(self) -> None:
        for index, label in enumerate(("", "?", "3"), start=1):
            with self.subTest(label=label):
                package = self._copy_package(self.root / f"bad_label_{index}")
                self._approve(package)
                _fields, rows = read_csv_rows(package["judgements"])
                rows[0]["final_label"] = label
                write_csv_rows(package["judgements"], JUDGEMENT_FIELDS, rows)
                self._refresh_artifact_hash(package, "judgements")
                with self.assertRaises(ValueError):
                    self._strict(package)

    def test_hash_mismatch_rejected_for_pool_query_and_source(self) -> None:
        for name in ("candidate_pool", "research_queries", "source_sample"):
            with self.subTest(input=name):
                package = self._copy_package(self.root / f"hash_{name}")
                self._approve(package)
                manifest = self._load_manifest(package)
                manifest["inputs"][name]["sha256"] = "0" * 64
                self._write_manifest(package, manifest)
                with self.assertRaisesRegex(ValueError, "hash"):
                    self._strict(package)

    def test_strict_rejects_manual_ready_bypass_while_proposals_are_pending(self) -> None:
        package = self._copy_package(self.root / "manual_ready_bypass")
        self._approve(package)
        _fields, judgements = read_csv_rows(package["judgements"])
        for row in judgements:
            if row["agreement_status"] == "disagreement":
                row["judgement_status"] = "ready"
                row["final_label"] = row["proposed_label"]
                for field in ("review_decision", "reviewer", "reviewed_at", "review_note"):
                    row[field] = ""
        write_csv_rows(package["judgements"], JUDGEMENT_FIELDS, judgements)

        _fields, proposals = read_csv_rows(package["adjudication_proposals"])
        for row in proposals:
            row["proposal_status"] = "pending_human_review"
            for field in (
                "review_decision",
                "reviewed_label",
                "reviewer",
                "reviewed_at",
                "review_note",
            ):
                row[field] = ""
        write_csv_rows(package["adjudication_proposals"], PROPOSAL_FIELDS, proposals)
        self._refresh_artifact_hash(package, "judgements")
        self._refresh_artifact_hash(package, "adjudication_proposals")

        with self.assertRaisesRegex(ValueError, "双标分歧只能"):
            self._strict(package)

    def test_strict_rejects_incomplete_human_adjudication_record(self) -> None:
        package = self._copy_package(self.root / "missing_review_note")
        self._approve(package)
        _fields, judgements = read_csv_rows(package["judgements"])
        for row in judgements:
            if row["agreement_status"] == "disagreement":
                row["review_note"] = ""
        write_csv_rows(package["judgements"], JUDGEMENT_FIELDS, judgements)
        _fields, proposals = read_csv_rows(package["adjudication_proposals"])
        for row in proposals:
            row["review_note"] = ""
        write_csv_rows(package["adjudication_proposals"], PROPOSAL_FIELDS, proposals)
        self._refresh_artifact_hash(package, "judgements")
        self._refresh_artifact_hash(package, "adjudication_proposals")
        with self.assertRaisesRegex(ValueError, "reviewer/time/note"):
            self._strict(package)

    def test_strict_rejects_self_reported_tampered_frozen_input(self) -> None:
        package = self._copy_package(self.root / "self_reported_input")
        self._approve(package)
        tampered = self.root / "candidate_pool_tampered.csv"
        shutil.copy2(package["candidate_pool"], tampered)
        with tampered.open("ab") as handle:
            handle.write(b"\n")
        manifest = self._load_manifest(package)
        manifest["inputs"]["candidate_pool"] = {
            "path": tampered.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(tampered),
            "version": "w4_pilot_v0.1",
        }
        manifest["input_set_identity"] = compute_input_set_identity(
            manifest["inputs"]
        )
        self._write_manifest(package, manifest)

        with self.assertRaisesRegex(ValueError, "可信 W4 v0.1 锚点"):
            self._strict(package)

    def test_strict_rechecks_proposal_against_original_annotations(self) -> None:
        for field, value in (
            ("annotator_a", "forged_annotator"),
            ("label_a", "9"),
            ("reason_a", "forged reason"),
        ):
            with self.subTest(field=field):
                package = self._copy_package(self.root / f"proposal_{field}")
                self._approve(package)
                _fields, proposals = read_csv_rows(
                    package["adjudication_proposals"]
                )
                proposals[0][field] = value
                write_csv_rows(
                    package["adjudication_proposals"],
                    PROPOSAL_FIELDS,
                    proposals,
                )
                self._refresh_artifact_hash(package, "adjudication_proposals")
                with self.assertRaisesRegex(ValueError, "原始 annotation provenance"):
                    self._strict(package)

    def test_approved_package_requires_complete_human_review_checklist(self) -> None:
        package = self._copy_package(self.root / "incomplete_checklist")
        self._approve(package)
        manifest = self._load_manifest(package)
        manifest["approval"]["checklist"][
            "original_annotation_provenance_verified"
        ] = False
        self._write_manifest(package, manifest)
        with self.assertRaisesRegex(ValueError, "全部 protocol"):
            self._strict(package)

    def test_approved_package_must_bind_reviewed_parent_draft(self) -> None:
        package = self._copy_package(self.root / "missing_parent")
        self._approve(package)
        manifest = self._load_manifest(package)
        manifest["parent_package"] = None
        self._write_manifest(package, manifest)
        with self.assertRaisesRegex(ValueError, "parent draft"):
            self._strict(package)

    def test_approved_package_cannot_rewrite_parent_proposal_evidence(self) -> None:
        package = self._copy_package(self.root / "rewritten_proposal")
        self._approve(package)
        _fields, proposals = read_csv_rows(package["adjudication_proposals"])
        proposals[0]["proposal_reason"] += " forged post-review change"
        write_csv_rows(
            package["adjudication_proposals"], PROPOSAL_FIELDS, proposals
        )
        self._refresh_artifact_hash(package, "adjudication_proposals")
        with self.assertRaisesRegex(ValueError, "parent draft"):
            self._strict(package)

    def test_approved_package_accepts_reviewed_blind_audit_overrides(self) -> None:
        package = self._copy_package(self.root / "blind_audit_overrides")
        self._approve(package)
        _fields, judgements = read_csv_rows(package["judgements"])
        by_pair = {row["pair_id"]: row for row in judgements}
        for pair_id, final_label in (
            ("w4_rq02_013", "0"),
            ("w4_rq03_005", "0"),
        ):
            row = by_pair[pair_id]
            row.update(
                {
                    "final_label": final_label,
                    "judgement_status": "adjudicated",
                    "judgement_basis": "blind_ai_audit_human_review",
                    "adjudication_ai_assistance": "label_suggestion",
                    "review_decision": "modify",
                    "reviewer": "independent_reviewer",
                    "reviewed_at": "2026-08-17T12:30:00+08:00",
                    "review_note": "human review after independent blind AI audit",
                }
            )
        write_csv_rows(package["judgements"], JUDGEMENT_FIELDS, judgements)
        self._refresh_artifact_hash(package, "judgements")

        result = self._strict(package)

        self.assertEqual(result["labels"]["w4_rq02_013"], "0")
        self.assertEqual(result["labels"]["w4_rq03_005"], "0")

    def test_approved_package_rejects_original_annotator_as_reviewer(self) -> None:
        package = self._copy_package(self.root / "non_independent_reviewer")
        self._approve(package)
        _fields, judgements = read_csv_rows(package["judgements"])
        target = next(
            row for row in judgements if row["agreement_status"] == "disagreement"
        )
        target["reviewer"] = target["primary_annotator"]
        write_csv_rows(package["judgements"], JUDGEMENT_FIELDS, judgements)
        _fields, proposals = read_csv_rows(package["adjudication_proposals"])
        proposal = next(row for row in proposals if row["pair_id"] == target["pair_id"])
        proposal["reviewer"] = target["primary_annotator"]
        write_csv_rows(package["adjudication_proposals"], PROPOSAL_FIELDS, proposals)
        self._refresh_artifact_hash(package, "judgements")
        self._refresh_artifact_hash(package, "adjudication_proposals")

        with self.assertRaisesRegex(ValueError, "独立 reviewer"):
            self._strict(package)

    def test_approved_package_rejects_blind_audit_provenance_hash_drift(self) -> None:
        package = self._copy_package(self.root / "blind_audit_hash_drift")
        self._approve(package)
        manifest = self._load_manifest(package)
        manifest["blind_ai_audit_provenance"]["files"]["blind_audit"][
            "sha256"
        ] = "0" * 64
        self._write_manifest(package, manifest)

        with self.assertRaisesRegex(ValueError, "hash"):
            self._strict(package)

    def test_approved_status_cannot_reuse_draft_version(self) -> None:
        package = self._copy_package(self.root / "draft_version")
        manifest = self._load_manifest(package)
        manifest["status"] = "approved"
        self._write_manifest(package, manifest)
        with self.assertRaisesRegex(ValueError, "draft"):
            self._strict(package)

    def test_default_manifest_points_to_approved_v010(self) -> None:
        self.assertEqual(DEFAULT_MANIFEST.resolve(), APPROVED_MANIFEST.resolve())

    def test_default_validator_cli_accepts_approved_package(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = validate_cli_main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("mode=strict-approved", output.getvalue())
        self.assertIn("status=approved", output.getvalue())
        self.assertIn("pairs=60", output.getvalue())

    def test_explicit_draft_is_rejected_by_strict_mode(self) -> None:
        strict_output = io.StringIO()
        with redirect_stdout(strict_output):
            strict_code = validate_cli_main(["--manifest", str(DRAFT_MANIFEST)])
        self.assertEqual(strict_code, 1)
        self.assertIn("approved", strict_output.getvalue())

    def test_explicit_draft_is_accepted_by_review_mode(self) -> None:
        review_output = io.StringIO()
        with redirect_stdout(review_output):
            review_code = validate_cli_main(
                ["--manifest", str(DRAFT_MANIFEST), "--allow-draft"]
            )
        self.assertEqual(review_code, 0)
        self.assertIn("draft-review", review_output.getvalue())

    def _strict(self, package: dict[str, Path]) -> dict:
        return validate_benchmark_package(
            package["manifest"],
            project_root=PROJECT_ROOT,
            require_approved=True,
        )

    def _copy_package(self, destination: Path) -> dict[str, Path]:
        destination.mkdir(parents=True)
        source_manifest = json.loads(DRAFT_MANIFEST.read_text(encoding="utf-8"))
        manifest = json.loads(json.dumps(source_manifest))
        package: dict[str, Path] = {"manifest": destination / "manifest.json"}

        for name, reference in manifest["inputs"].items():
            if name != "annotations":
                package[name] = PROJECT_ROOT / reference["path"]

        for name, reference in manifest["artifacts"].items():
            source = PROJECT_ROOT / reference["path"]
            target = destination / "artifacts" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            reference["path"] = target.relative_to(PROJECT_ROOT).as_posix()
            reference["sha256"] = sha256_file(target)
            package[name] = target

        self._write_manifest(package, manifest)
        return package

    def _approve(self, package: dict[str, Path]) -> None:
        _fields, judgements = read_csv_rows(package["judgements"])
        for row in judgements:
            row["benchmark_version"] = APPROVED_VERSION
            if row["agreement_status"] == "disagreement":
                row["final_label"] = row["proposed_label"]
                row["judgement_status"] = "adjudicated"
                row["review_decision"] = "approve"
                row["reviewer"] = "test_reviewer"
                row["reviewed_at"] = "2026-08-17T12:00:00+08:00"
                row["review_note"] = "test approval"
        write_csv_rows(package["judgements"], JUDGEMENT_FIELDS, judgements)

        _fields, proposals = read_csv_rows(package["adjudication_proposals"])
        for row in proposals:
            row["proposal_status"] = "reviewed"
            row["review_decision"] = "approve"
            row["reviewed_label"] = row["proposed_final_label"]
            row["reviewer"] = "test_reviewer"
            row["reviewed_at"] = "2026-08-17T12:00:00+08:00"
            row["review_note"] = "test approval"
        write_csv_rows(package["adjudication_proposals"], PROPOSAL_FIELDS, proposals)

        manifest = self._load_manifest(package)
        manifest["status"] = "approved"
        manifest["benchmark_version"] = APPROVED_VERSION
        manifest["display_name"] = "W4 Pilot Adjudicated Judged Set"
        manifest["counts"]["pending_human_review_pairs"] = 0
        parent_manifest = json.loads(DRAFT_MANIFEST.read_text(encoding="utf-8"))
        manifest["parent_package"] = {
            "path": DRAFT_MANIFEST.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(DRAFT_MANIFEST),
            "benchmark_version": parent_manifest["benchmark_version"],
            "input_set_identity": manifest["input_set_identity"],
        }
        manifest["approval"] = {
            "status": "approved",
            "approved_by": "test_reviewer",
            "approved_at": "2026-08-17T12:00:00+08:00",
            "review_note": "test package approval",
            "checklist": {field: True for field in APPROVAL_CHECKLIST_FIELDS},
        }
        approved_manifest = json.loads(APPROVED_MANIFEST.read_text(encoding="utf-8"))
        manifest["blind_ai_audit_provenance"] = approved_manifest[
            "blind_ai_audit_provenance"
        ]
        jia = manifest["annotation_review_provenance"]["jiafucheng"]
        jia.update(
            {
                "protocol_review_checklist_required": False,
                "protocol_review_confirmed_by": "test_reviewer",
                "protocol_review_confirmed_at": "2026-08-17T12:00:00+08:00",
                "protocol_review_note": "AI assistance provenance checked",
            }
        )
        manifest["artifacts"]["judgements"]["sha256"] = sha256_file(
            package["judgements"]
        )
        manifest["artifacts"]["adjudication_proposals"]["sha256"] = sha256_file(
            package["adjudication_proposals"]
        )
        self._write_manifest(package, manifest)

    def _refresh_artifact_hash(self, package: dict[str, Path], name: str) -> None:
        manifest = self._load_manifest(package)
        manifest["artifacts"][name]["sha256"] = sha256_file(package[name])
        self._write_manifest(package, manifest)

    @staticmethod
    def _load_manifest(package: dict[str, Path]) -> dict:
        return json.loads(package["manifest"].read_text(encoding="utf-8"))

    @staticmethod
    def _write_manifest(package: dict[str, Path], manifest: dict) -> None:
        package["manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


class StrictEvaluatorTests(unittest.TestCase):
    setUp = BenchmarkPackageValidationTests.setUp
    tearDown = BenchmarkPackageValidationTests.tearDown
    _copy_package = BenchmarkPackageValidationTests._copy_package
    _approve = BenchmarkPackageValidationTests._approve
    _load_manifest = staticmethod(BenchmarkPackageValidationTests._load_manifest)
    _write_manifest = staticmethod(BenchmarkPackageValidationTests._write_manifest)

    def test_strict_evaluator_writes_reproducibility_manifest(self) -> None:
        package = self._copy_package(self.root / "strict_eval")
        self._approve(package)
        output_dir = self.root / "experiment"
        output = io.StringIO()
        clean_environment = _environment_snapshot(dirty=False)

        def capture_before_outputs(**_kwargs: object) -> dict:
            self.assertFalse(output_dir.exists())
            return clean_environment

        with patch(
            "app.evaluate_w4_benchmark.capture_experiment_environment",
            side_effect=capture_before_outputs,
        ), redirect_stdout(output):
            exit_code = evaluate_cli_main(
                [
                    "--strict",
                    "--benchmark-manifest",
                    str(package["manifest"]),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(exit_code, 0, output.getvalue())
        experiment_path = output_dir / "experiment_manifest.json"
        self.assertTrue(experiment_path.is_file())
        experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
        self.assertEqual(experiment["git_revision"], _git_revision())
        self.assertEqual(experiment["benchmark"]["version"], APPROVED_VERSION)
        self.assertEqual(
            experiment["benchmark"]["manifest_sha256"],
            sha256_file(package["manifest"]),
        )
        self.assertEqual(experiment["reference_year"], 2026)
        self.assertEqual(experiment["git_dirty"], False)
        self.assertEqual(experiment["environment"]["python"]["version"], "3.test")
        self.assertIn("pandas", experiment["environment"]["dependencies"])
        self.assertEqual(
            experiment["environment"]["requirements"]["sha256"], "a" * 64
        )
        self.assertEqual(set(experiment["methods"]), {"baseline", "two_stage"})
        self.assertEqual(len(experiment["output_files"]), 2)
        for item in experiment["output_files"]:
            output_file = output_dir / Path(item["path"]).name
            self.assertEqual(item["sha256"], sha256_file(output_file))

    def test_strict_evaluator_rejects_repository_draft_without_outputs(self) -> None:
        output_dir = self.root / "draft_rejected"
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = evaluate_cli_main(
                [
                    "--strict",
                    "--benchmark-manifest",
                    str(DRAFT_MANIFEST),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("approved", output.getvalue())
        self.assertFalse(output_dir.exists())

    def test_strict_evaluator_rejects_dirty_tree_before_any_output(self) -> None:
        package = self._copy_package(self.root / "dirty_eval")
        self._approve(package)
        output_dir = self.root / "dirty_output"
        output = io.StringIO()
        with patch(
            "app.evaluate_w4_benchmark.capture_experiment_environment",
            return_value=_environment_snapshot(dirty=True),
        ), redirect_stdout(output):
            exit_code = evaluate_cli_main(
                [
                    "--strict",
                    "--benchmark-manifest",
                    str(package["manifest"]),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("dirty working tree", output.getvalue())
        self.assertFalse(output_dir.exists())

    def test_strict_evaluator_rejects_reference_year_mismatch_without_outputs(self) -> None:
        package = self._copy_package(self.root / "wrong_year_eval")
        self._approve(package)
        output_dir = self.root / "wrong_year_output"
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = evaluate_cli_main(
                [
                    "--strict",
                    "--benchmark-manifest",
                    str(package["manifest"]),
                    "--reference-year",
                    "2025",
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("reference-year", output.getvalue())
        self.assertFalse(output_dir.exists())


def _git_revision() -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


def _environment_snapshot(*, dirty: bool) -> dict:
    return {
        "git_revision": _git_revision(),
        "git_dirty": dirty,
        "python": {
            "version": "3.test",
            "implementation": "CPython",
            "cache_tag": "cpython-test",
        },
        "platform": {"system": "test", "release": "test", "machine": "test"},
        "requirements": {"path": "requirements.txt", "sha256": "a" * 64},
        "dependencies": {
            "requests": "test",
            "pandas": "test",
            "matplotlib": "test",
            "python-dotenv": "test",
        },
    }


if __name__ == "__main__":
    unittest.main()
