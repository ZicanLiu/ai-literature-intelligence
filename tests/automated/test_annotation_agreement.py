from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from app.analyze_annotation_agreement import main as agreement_cli_main
from src.annotation_agreement import (
    DISAGREEMENT_FIELDS,
    DOUBLE_ANNOTATION_FIELDS,
    AgreementAnalyzer,
    calculate_metrics,
)
from src.annotation_tasks import (
    ANNOTATORS,
    ANNOTATION_TASK_FIELDS,
    ASSIGNMENT_FIELDS,
    CANDIDATE_POOL_FIELDS,
    POOL_VERSION,
    build_balanced_assignments,
    create_annotation_task,
    read_csv_rows,
    write_csv_rows,
)


RESEARCH_QUERY_IDS = (
    "rq01_stellar_classification",
    "rq02_stellar_parameters",
    "rq03_spectral_preprocessing",
)


class AgreementAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.pool_path = self.root / "candidate_pool_v0.1.csv"
        self.assignments_path = self.root / "assignments_v0.1.csv"
        self.annotations_dir = self.root / "annotations"
        self.annotations_dir.mkdir()
        self.output_dir = self.root / "output"

        self.candidate_rows = self._build_candidate_rows()
        self.assignments = build_balanced_assignments(self.candidate_rows)
        write_csv_rows(
            self.pool_path,
            CANDIDATE_POOL_FIELDS,
            self.candidate_rows,
        )
        write_csv_rows(
            self.assignments_path,
            ASSIGNMENT_FIELDS,
            self.assignments,
        )
        self.double_pairs = self._double_pair_contract()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_metrics_handle_exact_question_mark_and_kappas(self) -> None:
        metrics = calculate_metrics(
            [
                {"label_a": "0", "label_b": "0"},
                {"label_a": "1", "label_b": "2"},
                {"label_a": "2", "label_b": "2"},
                {"label_a": "?", "label_b": "?"},
            ]
        )

        self.assertEqual(metrics["total_comparable_pairs"], 4)
        self.assertEqual(metrics["exact_agreement_count"], 3)
        self.assertEqual(metrics["exact_agreement_rate"], 0.75)
        self.assertEqual(metrics["pairs_with_question_mark"], 1)
        self.assertEqual(metrics["kappa_eligible_pairs"], 3)
        self.assertEqual(metrics["cohens_kappa"], 0.5)
        self.assertEqual(metrics["weighted_cohens_kappa_quadratic"], 0.8)
        self.assertEqual(metrics["cohens_kappa_status"], "computed")
        self.assertEqual(metrics["weighted_cohens_kappa_status"], "computed")

    def test_metrics_report_empty_insufficient_and_single_category(self) -> None:
        empty = calculate_metrics([])
        self.assertIsNone(empty["exact_agreement_rate"])
        self.assertEqual(empty["cohens_kappa_reason"], "no_kappa_eligible_pairs")

        insufficient = calculate_metrics([{"label_a": "0", "label_b": "1"}])
        self.assertEqual(insufficient["cohens_kappa_reason"], "insufficient_pairs")

        single_category = calculate_metrics(
            [
                {"label_a": "1", "label_b": "1"},
                {"label_a": "1", "label_b": "1"},
            ]
        )
        self.assertIsNone(single_category["cohens_kappa"])
        self.assertEqual(single_category["cohens_kappa_reason"], "single_category")
        self.assertIsNone(single_category["weighted_cohens_kappa_quadratic"])
        json.dumps(single_category, allow_nan=False)

    def test_metrics_reject_invalid_labels(self) -> None:
        with self.assertRaisesRegex(ValueError, "label_b 必须是"):
            calculate_metrics([{"label_a": "0", "label_b": "bad"}])

    def test_partial_data_writes_stable_outputs_and_missing_details(self) -> None:
        self._create_annotation_file("huangbin")

        summary = self._analyzer().analyze(self.output_dir)

        self.assertEqual(summary["analysis_status"], "partial")
        self.assertEqual(summary["annotators"]["found"], ["huangbin"])
        self.assertEqual(len(summary["annotators"]["missing"]), 5)
        self.assertEqual(summary["coverage"]["expected_double_pairs"], 30)
        self.assertEqual(summary["coverage"]["comparable_double_pairs"], 0)
        self.assertEqual(summary["coverage"]["missing_double_pairs"], 30)
        self.assertEqual(len(summary["coverage"]["missing_pair_details"]), 30)

        self._assert_output_headers("double_annotations.csv", DOUBLE_ANNOTATION_FIELDS)
        self._assert_output_headers("disagreements.csv", DISAGREEMENT_FIELDS)
        parsed = self._load_strict_summary()
        self.assertEqual(parsed["analysis_status"], "partial")
        for research_query_id in RESEARCH_QUERY_IDS:
            rq = parsed["rq_breakdown"][research_query_id]
            self.assertEqual(rq["coverage"]["expected_double_pairs"], 10)
            self.assertEqual(rq["coverage"]["comparable_double_pairs"], 0)
            self.assertIsNone(rq["metrics"]["exact_agreement_rate"])

    def test_partial_subset_metrics_cannot_be_misread_as_complete(self) -> None:
        partnership = {
            self.double_pairs[0]["annotator_a"],
            self.double_pairs[0]["annotator_b"],
        }
        for slug in partnership:
            self._create_annotation_file(slug)
        partnership_pair_count = sum(
            {row["annotator_a"], row["annotator_b"]} == partnership
            for row in self.double_pairs
        )

        summary = self._analyzer().analyze(self.output_dir)

        self.assertEqual(summary["analysis_status"], "partial")
        self.assertEqual(
            summary["coverage"]["comparable_double_pairs"],
            partnership_pair_count,
        )
        self.assertEqual(
            summary["coverage"]["missing_double_pairs"],
            30 - partnership_pair_count,
        )
        self.assertEqual(summary["overall"]["exact_agreement_rate"], 1.0)
        self.assertLess(summary["coverage"]["completion_rate"], 1.0)

    def test_complete_data_reports_overall_rq_metrics_and_disagreements(self) -> None:
        question_pair = self.double_pairs[0]
        conflict_pair = self.double_pairs[1]
        secondary_by_pair = {
            row["pair_id"]: row["annotator_b"] for row in self.double_pairs
        }

        def labeler(slug: str, pair_id: str) -> str:
            base = self._default_label(pair_id)
            if pair_id == question_pair["pair_id"] and slug == secondary_by_pair[pair_id]:
                return "?"
            if pair_id == conflict_pair["pair_id"] and slug == secondary_by_pair[pair_id]:
                return str((int(base) + 1) % 3)
            return base

        for slug in ANNOTATORS:
            self._create_annotation_file(slug, labeler)

        summary = self._analyzer().analyze(self.output_dir)

        self.assertEqual(summary["analysis_status"], "complete")
        self.assertEqual(summary["coverage"]["comparable_double_pairs"], 30)
        self.assertEqual(summary["coverage"]["missing_double_pairs"], 0)
        self.assertEqual(summary["overall"]["exact_agreement_count"], 28)
        self.assertEqual(summary["overall"]["pairs_with_question_mark"], 1)
        self.assertEqual(summary["overall"]["kappa_eligible_pairs"], 29)
        self.assertEqual(summary["overall"]["cohens_kappa_status"], "computed")
        self.assertEqual(
            summary["overall"]["weighted_cohens_kappa_status"], "computed"
        )
        for research_query_id in RESEARCH_QUERY_IDS:
            coverage = summary["rq_breakdown"][research_query_id]["coverage"]
            self.assertEqual(coverage["expected_double_pairs"], 10)
            self.assertEqual(coverage["comparable_double_pairs"], 10)

        _fields, disagreements = read_csv_rows(
            self.output_dir / "disagreements.csv"
        )
        self.assertEqual(len(disagreements), 2)
        by_pair = {row["pair_id"]: row for row in disagreements}
        self.assertEqual(
            by_pair[question_pair["pair_id"]]["disagreement_type"],
            "Needs_Discussion_Unknown",
        )
        self.assertEqual(
            by_pair[conflict_pair["pair_id"]]["disagreement_type"],
            "Label_Conflict",
        )
        self.assertNotIn("final_label", _fields)
        self._load_strict_summary()

    def test_missing_pair_in_present_member_file_is_rejected(self) -> None:
        path = self._create_annotation_file("huangbin")
        fields, rows = read_csv_rows(path)
        write_csv_rows(path, fields, rows[1:])

        with self.assertRaisesRegex(ValueError, "缺少已分配 pair"):
            self._analyzer().analyze(self.output_dir)
        self.assertFalse(self.output_dir.exists())

    def test_duplicate_annotation_pair_is_rejected(self) -> None:
        path = self._create_annotation_file("huangbin")
        fields, rows = read_csv_rows(path)
        write_csv_rows(path, fields, rows + [dict(rows[0])])

        with self.assertRaisesRegex(ValueError, "pair_id 不得重复"):
            self._analyzer().analyze(self.output_dir)

    def test_invalid_annotation_label_is_rejected(self) -> None:
        path = self._create_annotation_file("huangbin")
        fields, rows = read_csv_rows(path)
        rows[0]["label"] = "3"
        write_csv_rows(path, fields, rows)

        with self.assertRaisesRegex(ValueError, r"label 必须是 2/1/0/\?"):
            self._analyzer().analyze(self.output_dir)

    def test_duplicate_and_third_assignment_are_rejected(self) -> None:
        original = [dict(row) for row in self.assignments]
        invalid_cases = {
            "same annotator repeated": original + [dict(original[0])],
            "third annotator": self._assignment_with_third_annotator(original),
        }
        for name, invalid in invalid_cases.items():
            with self.subTest(name=name):
                write_csv_rows(self.assignments_path, ASSIGNMENT_FIELDS, invalid)
                with self.assertRaisesRegex(ValueError, "公共 assignment 无效"):
                    self._analyzer().analyze(self.output_dir)
        write_csv_rows(self.assignments_path, ASSIGNMENT_FIELDS, original)

    def test_invalid_assignment_header_is_rejected(self) -> None:
        write_csv_rows(
            self.assignments_path,
            ["pair_id", "annotator_slug"],
            [{"pair_id": "x", "annotator_slug": "huangbin"}],
        )
        with self.assertRaisesRegex(ValueError, "assignment 表头"):
            self._analyzer().analyze(self.output_dir)

    def test_invalid_candidate_pool_is_rejected(self) -> None:
        write_csv_rows(
            self.pool_path,
            CANDIDATE_POOL_FIELDS,
            self.candidate_rows + [dict(self.candidate_rows[0])],
        )
        with self.assertRaisesRegex(ValueError, "公共 assignment 无效"):
            self._analyzer().analyze(self.output_dir)

    def test_cli_is_gbk_safe_and_reports_partial_status(self) -> None:
        self._create_annotation_file("huangbin")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = agreement_cli_main(
                [
                    "--candidate-pool",
                    str(self.pool_path),
                    "--assignments",
                    str(self.assignments_path),
                    "--annotations-dir",
                    str(self.annotations_dir),
                    "--output-dir",
                    str(self.output_dir),
                ]
            )
        output = stdout.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("status=partial", output)
        output.encode("gbk")

    def test_cli_catches_invalid_input_without_traceback(self) -> None:
        write_csv_rows(
            self.assignments_path,
            ASSIGNMENT_FIELDS,
            self.assignments + [dict(self.assignments[0])],
        )
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = agreement_cli_main(
                [
                    "--candidate-pool",
                    str(self.pool_path),
                    "--assignments",
                    str(self.assignments_path),
                    "--annotations-dir",
                    str(self.annotations_dir),
                    "--output-dir",
                    str(self.output_dir),
                ]
            )
        output = stdout.getvalue()

        self.assertEqual(exit_code, 1)
        self.assertIn("标注一致性分析失败", output)
        self.assertNotIn("Traceback", output)
        output.encode("gbk")

    def _analyzer(self) -> AgreementAnalyzer:
        return AgreementAnalyzer(
            assignments_path=self.assignments_path,
            annotations_dir=self.annotations_dir,
            candidate_pool_path=self.pool_path,
        )

    def _create_annotation_file(self, slug: str, labeler=None) -> Path:
        path = self.annotations_dir / f"{slug}.csv"
        create_annotation_task(
            annotator_slug=slug,
            candidate_pool_path=self.pool_path,
            assignments_path=self.assignments_path,
            output_path=path,
        )
        fields, rows = read_csv_rows(path)
        for row in rows:
            row.update(
                {
                    "label": (
                        labeler(slug, row["pair_id"])
                        if labeler is not None
                        else self._default_label(row["pair_id"])
                    ),
                    "confidence": "high",
                    "evidence_level": "A",
                    "reason": "测试 fixture 的明确判断",
                    "source_checked": "title_abstract",
                    "evidence_url": "",
                    "ai_assistance": "none",
                }
            )
        write_csv_rows(path, ANNOTATION_TASK_FIELDS, rows)
        self.assertEqual(fields, ANNOTATION_TASK_FIELDS)
        return path

    def _double_pair_contract(self) -> list[dict[str, str]]:
        pool_by_pair = {row["pair_id"]: row for row in self.candidate_rows}
        by_pair: dict[str, list[dict[str, str]]] = {}
        for row in self.assignments:
            by_pair.setdefault(row["pair_id"], []).append(row)
        result = []
        for pair_id in sorted(by_pair):
            rows = by_pair[pair_id]
            secondaries = [row for row in rows if row["assignment_role"] == "secondary"]
            if not secondaries:
                continue
            primary = [row for row in rows if row["assignment_role"] == "primary"][0]
            result.append(
                {
                    "pair_id": pair_id,
                    "research_query_id": pool_by_pair[pair_id]["research_query_id"],
                    "annotator_a": primary["annotator_slug"],
                    "annotator_b": secondaries[0]["annotator_slug"],
                }
            )
        return result

    def _assignment_with_third_annotator(
        self, assignments: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        pair = self.double_pairs[0]
        used = {pair["annotator_a"], pair["annotator_b"]}
        third = next(slug for slug in ANNOTATORS if slug not in used)
        return assignments + [
            {
                "pair_id": pair["pair_id"],
                "annotator_slug": third,
                "annotator_name": ANNOTATORS[third],
                "assignment_role": "secondary",
            }
        ]

    def _assert_output_headers(self, filename: str, expected: list[str]) -> None:
        with (self.output_dir / filename).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            reader = csv.reader(handle)
            self.assertEqual(next(reader), expected)

    def _load_strict_summary(self) -> dict[str, object]:
        text = (self.output_dir / "agreement_summary.json").read_text(
            encoding="utf-8"
        )

        def reject_constant(value: str) -> None:
            raise ValueError(f"非标准 JSON 常量：{value}")

        return json.loads(text, parse_constant=reject_constant)

    @staticmethod
    def _default_label(pair_id: str) -> str:
        pair_number = int(pair_id.rsplit("_", maxsplit=1)[1])
        return str((pair_number - 1) % 3)

    @staticmethod
    def _build_candidate_rows() -> list[dict[str, str]]:
        rows = []
        for rq_index, research_query_id in enumerate(RESEARCH_QUERY_IDS, start=1):
            for pair_index in range(1, 21):
                rows.append(
                    {
                        "pair_id": f"w4_rq{rq_index:02d}_{pair_index:03d}",
                        "research_query_id": research_query_id,
                        "research_question_zh": f"研究问题 {rq_index}",
                        "research_question_en": f"Research question {rq_index}",
                        "acquisition_query_id": f"q{rq_index:02d}",
                        "openalex_id": f"https://openalex.org/W{rq_index}{pair_index:03d}",
                        "title": f"Paper {rq_index}-{pair_index}",
                        "abstract": "Fixture abstract",
                        "landing_page_url": "https://example.org/paper",
                        "publication_year": "2026",
                        "doi": f"10.0000/{rq_index}.{pair_index}",
                        "source_query_ids": f'["q{rq_index:02d}"]',
                        "source_run_ids": f'["run-{rq_index:02d}"]',
                        "pool_version": POOL_VERSION,
                        "selection_bucket": "top",
                    }
                )
        return rows


if __name__ == "__main__":
    unittest.main()
