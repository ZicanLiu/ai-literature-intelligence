from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from app.evaluate_w4_benchmark import main as evaluate_cli_main
from app.validate_w4_benchmark import main as validate_cli_main
from src.annotation_tasks import read_csv_rows, sha256_file, write_csv_rows
from src.w4_benchmark_artifact import build_benchmark_draft
from src.w4_benchmark_validation import (
    JUDGEMENT_FIELDS,
    PROPOSAL_FIELDS,
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
                with package[name].open("ab") as handle:
                    handle.write(b"\n")
                with self.assertRaisesRegex(ValueError, "hash"):
                    self._strict(package)

    def test_approved_status_cannot_reuse_draft_version(self) -> None:
        package = self._copy_package(self.root / "draft_version")
        manifest = self._load_manifest(package)
        manifest["status"] = "approved"
        self._write_manifest(package, manifest)
        with self.assertRaisesRegex(ValueError, "draft"):
            self._strict(package)

    def test_default_validator_cli_rejects_draft_and_review_mode_accepts_it(self) -> None:
        strict_output = io.StringIO()
        with redirect_stdout(strict_output):
            strict_code = validate_cli_main(["--manifest", str(DRAFT_MANIFEST)])
        self.assertEqual(strict_code, 1)
        self.assertIn("approved", strict_output.getvalue())

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
            if name == "annotations":
                continue
            source = PROJECT_ROOT / reference["path"]
            target = destination / "inputs" / name / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            reference["path"] = target.relative_to(PROJECT_ROOT).as_posix()
            reference["sha256"] = sha256_file(target)
            package[name] = target

        for slug, reference in manifest["inputs"]["annotations"].items():
            source = PROJECT_ROOT / reference["path"]
            target = destination / "inputs" / "annotations" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            reference["path"] = target.relative_to(PROJECT_ROOT).as_posix()
            reference["sha256"] = sha256_file(target)

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
        with redirect_stdout(output):
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


if __name__ == "__main__":
    unittest.main()
