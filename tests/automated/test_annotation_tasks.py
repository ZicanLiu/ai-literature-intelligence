"""W4 candidate pool、双标分配、个人任务生成与 validator 测试。"""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from pathlib import Path

from app.create_annotation_task import main as create_task_main
from app.validate_annotation_task import main as validate_task_main
from src.annotation_tasks import (
    ANNOTATION_TASK_FIELDS,
    ANNOTATORS,
    CANDIDATE_POOL_FIELDS,
    build_candidate_pool,
    create_annotation_task,
    read_csv_rows,
    validate_assignment_invariants,
    write_csv_rows,
)
from src.annotation_validation import validate_annotation_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
W4_DATA_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"
POOL_FILE = W4_DATA_DIR / "candidate_pool_v0.1.csv"
ASSIGNMENT_FILE = W4_DATA_DIR / "assignments_v0.1.csv"
RESEARCH_QUERIES_FILE = PROJECT_ROOT / "configs" / "w4" / "research_queries.json"
SOURCE_FILE = (
    PROJECT_ROOT
    / "data"
    / "samples"
    / "w2"
    / "domain_query"
    / "live_query_sample.csv"
)


class W4AnnotationTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _pool_fields, cls.pool_rows = read_csv_rows(POOL_FILE)
        _assignment_fields, cls.assignments = read_csv_rows(ASSIGNMENT_FILE)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_committed_pool_and_assignment_invariants(self) -> None:
        errors = validate_assignment_invariants(self.pool_rows, self.assignments)
        self.assertEqual([], errors)
        self.assertEqual(60, len(self.pool_rows))
        self.assertEqual(60, len({row["pair_id"] for row in self.pool_rows}))
        self.assertEqual(90, len(self.assignments))
        self.assertEqual(
            {"primary": 60, "secondary": 30},
            dict(Counter(row["assignment_role"] for row in self.assignments)),
        )
        self.assertEqual(
            {slug: 15 for slug in ANNOTATORS},
            dict(Counter(row["annotator_slug"] for row in self.assignments)),
        )

        pool_by_pair = {row["pair_id"]: row for row in self.pool_rows}
        secondary_by_query = Counter(
            pool_by_pair[row["pair_id"]]["research_query_id"]
            for row in self.assignments
            if row["assignment_role"] == "secondary"
        )
        self.assertEqual([10, 10, 10], sorted(secondary_by_query.values()))

        by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.assignments:
            by_pair[row["pair_id"]].append(row)
        self.assertEqual(30, sum(len(rows) == 2 for rows in by_pair.values()))
        self.assertTrue(all(len(rows) <= 2 for rows in by_pair.values()))
        for rows in by_pair.values():
            if len(rows) == 2:
                self.assertNotEqual(rows[0]["annotator_slug"], rows[1]["annotator_slug"])

    def test_candidate_pool_is_reproducible_without_label_fields(self) -> None:
        generated, details = build_candidate_pool(
            RESEARCH_QUERIES_FILE,
            SOURCE_FILE,
            reference_year=2026,
        )
        self.assertEqual(self.pool_rows, [{field: str(row.get(field, "")) for field in CANDIDATE_POOL_FIELDS} for row in generated])
        self.assertEqual(3, len(details))
        self.assertTrue(all(item["eligible_count"] == 30 for item in details.values()))
        self.assertTrue(all(item["selected_count"] == 20 for item in details.values()))
        self.assertFalse(
            {"label", "review_status", "annotation_id"}.intersection(
                CANDIDATE_POOL_FIELDS
            )
        )

    def test_all_six_annotators_generate_exactly_fifteen_blind_rows(self) -> None:
        forbidden_fields = {
            "preliminary_score",
            "stage2_ranking_score",
            "old_rank",
            "new_rank",
            "cited_by_count",
            "selection_bucket",
            "assignment_role",
        }
        for slug in ANNOTATORS:
            with self.subTest(annotator=slug):
                output = self.temp_dir / f"{slug}.csv"
                create_annotation_task(
                    annotator_slug=slug,
                    candidate_pool_path=POOL_FILE,
                    assignments_path=ASSIGNMENT_FILE,
                    output_path=output,
                )
                fields, rows = read_csv_rows(output)
                self.assertEqual(ANNOTATION_TASK_FIELDS, fields)
                self.assertEqual(15, len(rows))
                self.assertFalse(forbidden_fields.intersection(fields))
                self.assertTrue(all(row["annotator"] == slug for row in rows))
                self.assertTrue(all(not row["label"] for row in rows))

    def test_generator_refuses_to_overwrite_existing_file(self) -> None:
        output = self.temp_dir / "liuzican.csv"
        kwargs = {
            "annotator_slug": "liuzican",
            "candidate_pool_path": POOL_FILE,
            "assignments_path": ASSIGNMENT_FILE,
            "output_path": output,
        }
        create_annotation_task(**kwargs)
        with self.assertRaises(FileExistsError):
            create_annotation_task(**kwargs)

    def test_generator_and_validator_cli_entrypoints(self) -> None:
        output = self.temp_dir / "liuzican.csv"
        with redirect_stdout(io.StringIO()):
            return_code = create_task_main(
                ["--annotator", "liuzican", "--output", str(output)]
            )
        self.assertEqual(0, return_code)
        fields, rows = read_csv_rows(output)
        for row in rows:
            row.update(
                {
                    "label": "2",
                    "confidence": "high",
                    "evidence_level": "A",
                    "reason": "标题和摘要能够支持判断。",
                    "source_checked": "title_abstract",
                    "evidence_url": "",
                    "ai_assistance": "none",
                }
            )
        write_csv_rows(output, fields, rows)
        with redirect_stdout(io.StringIO()):
            return_code = validate_task_main(["--file", str(output)])
        self.assertEqual(0, return_code)

    def test_validator_accepts_complete_valid_annotation(self) -> None:
        output = self._complete_annotation("wuziheng")
        self.assertEqual([], self._validate(output))

    def test_validator_rejects_unassigned_pair(self) -> None:
        output = self._complete_annotation("jiafucheng")
        fields, rows = read_csv_rows(output)
        expected = {row["pair_id"] for row in rows}
        replacement = next(row for row in self.pool_rows if row["pair_id"] not in expected)
        rows[0].update(
            {
                field: replacement.get(field, "")
                for field in (
                    "pair_id",
                    "research_query_id",
                    "research_question_zh",
                    "research_question_en",
                    "openalex_id",
                    "title",
                    "abstract",
                    "landing_page_url",
                    "publication_year",
                    "doi",
                )
            }
        )
        write_csv_rows(output, fields, rows)
        self.assertTrue(any("未分配 pair" in error for error in self._validate(output)))

    def test_validator_rejects_modified_title_and_abstract(self) -> None:
        output = self._complete_annotation("chenxingyu")
        fields, rows = read_csv_rows(output)
        rows[0]["title"] += " changed"
        rows[1]["abstract"] += " changed"
        write_csv_rows(output, fields, rows)
        errors = self._validate(output)
        self.assertTrue(any("只读字段被修改：title" in error for error in errors))
        self.assertTrue(any("只读字段被修改：abstract" in error for error in errors))

    def test_validator_rejects_illegal_controlled_values(self) -> None:
        invalid_values = {
            "label": "3",
            "confidence": "certain",
            "evidence_level": "D",
            "ai_assistance": "auto",
        }
        expected_messages = {
            "label": "label 必须是",
            "confidence": "confidence 非法",
            "evidence_level": "evidence_level 非法",
            "ai_assistance": "ai_assistance 非法",
        }
        output = self._complete_annotation("huangbin")
        fields, valid_rows = read_csv_rows(output)
        for field, invalid in invalid_values.items():
            with self.subTest(field=field):
                rows = [dict(row) for row in valid_rows]
                rows[0][field] = invalid
                write_csv_rows(output, fields, rows)
                errors = self._validate(output)
                self.assertTrue(
                    any(expected_messages[field] in error for error in errors),
                    errors,
                )

    def test_validator_rejects_incomplete_evidence_and_reason(self) -> None:
        output = self._complete_annotation("puzhengjie")
        fields, rows = read_csv_rows(output)
        rows[0]["reason"] = ""
        rows[1]["evidence_level"] = "B"
        rows[1]["source_checked"] = "title_abstract"
        rows[1]["evidence_url"] = ""
        rows[2]["evidence_level"] = "C"
        rows[2]["source_checked"] = "publisher"
        rows[2]["evidence_url"] = "not-a-url"
        write_csv_rows(output, fields, rows)
        errors = self._validate(output)
        self.assertTrue(any("reason 不能为空" in error for error in errors))
        self.assertTrue(any("B/C 级证据必须记录外部来源" in error for error in errors))
        self.assertTrue(any("B/C 级证据必须填写 evidence_url" in error for error in errors))
        self.assertTrue(any("evidence_url 格式非法" in error for error in errors))
        self.assertTrue(any("C 级证据必须记录 pdf_fulltext" in error for error in errors))

    def _complete_annotation(self, slug: str) -> Path:
        output = self.temp_dir / slug / f"{slug}.csv"
        create_annotation_task(
            annotator_slug=slug,
            candidate_pool_path=POOL_FILE,
            assignments_path=ASSIGNMENT_FILE,
            output_path=output,
        )
        fields, rows = read_csv_rows(output)
        for index, row in enumerate(rows):
            row.update(
                {
                    "label": ("2", "1", "0", "?")[index % 4],
                    "confidence": ("high", "medium", "low")[index % 3],
                    "evidence_level": "A",
                    "reason": "标题和摘要能够支持本条 Query Relevance 判断。",
                    "source_checked": "title_abstract",
                    "evidence_url": "",
                    "ai_assistance": "none",
                }
            )
        write_csv_rows(output, fields, rows)
        return output

    @staticmethod
    def _validate(path: Path) -> list[str]:
        return validate_annotation_file(
            annotation_path=path,
            candidate_pool_path=POOL_FILE,
            assignments_path=ASSIGNMENT_FILE,
        )


if __name__ == "__main__":
    unittest.main()
