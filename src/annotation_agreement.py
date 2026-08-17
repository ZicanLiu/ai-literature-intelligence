"""W4 独立双标结果合并、一致性计算和分歧队列输出。"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

from src.annotation_tasks import (
    ANNOTATORS,
    ASSIGNMENT_FIELDS,
    CANDIDATE_POOL_FIELDS,
    read_csv_rows,
    validate_assignment_invariants,
    write_csv_rows,
)
from src.annotation_validation import VALID_LABELS, validate_annotation_file


KAPPA_LABELS = ("0", "1", "2")

DOUBLE_ANNOTATION_FIELDS = [
    "pair_id",
    "research_query_id",
    "annotator_a",
    "label_a",
    "confidence_a",
    "reason_a",
    "annotator_b",
    "label_b",
    "confidence_b",
    "reason_b",
]

DISAGREEMENT_FIELDS = DOUBLE_ANNOTATION_FIELDS + ["disagreement_type"]


class AgreementAnalyzer:
    """依据 W4 v0.1 公共契约分析已经提交的独立双标结果。"""

    def __init__(
        self,
        assignments_path: str | Path,
        annotations_dir: str | Path,
        candidate_pool_path: str | Path | None = None,
    ) -> None:
        self.assignments_path = Path(assignments_path)
        self.annotations_dir = Path(annotations_dir)
        self.candidate_pool_path = (
            Path(candidate_pool_path)
            if candidate_pool_path is not None
            else self.assignments_path.with_name("candidate_pool_v0.1.csv")
        )

    def analyze(self, output_dir: str | Path) -> dict[str, Any]:
        """验证输入、输出稳定产物，并返回结构化 summary。"""
        contract = self._load_public_contract()
        annotations = self._load_valid_annotations()
        comparable, missing_pairs = self._build_comparable_records(
            contract["expected_double_pairs"], annotations
        )
        disagreements = generate_disagreements(comparable)
        summary = self._build_summary(
            research_query_ids=contract["research_query_ids"],
            expected_double_pairs=contract["expected_double_pairs"],
            comparable=comparable,
            missing_pairs=missing_pairs,
            found_annotators=list(annotations),
        )

        destination = Path(output_dir)
        write_csv_rows(
            destination / "double_annotations.csv",
            DOUBLE_ANNOTATION_FIELDS,
            comparable,
        )
        write_csv_rows(
            destination / "disagreements.csv",
            DISAGREEMENT_FIELDS,
            disagreements,
        )
        summary_path = destination / "agreement_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return summary

    def _load_public_contract(self) -> dict[str, Any]:
        pool_fields, candidate_rows = read_csv_rows(self.candidate_pool_path)
        assignment_fields, assignments = read_csv_rows(self.assignments_path)
        if pool_fields != CANDIDATE_POOL_FIELDS:
            raise ValueError("公共 candidate pool 表头与 W4 v0.1 契约不一致。")
        if assignment_fields != ASSIGNMENT_FIELDS:
            raise ValueError("公共 assignment 表头与 W4 v0.1 契约不一致。")

        errors = validate_assignment_invariants(candidate_rows, assignments)
        if errors:
            raise ValueError("公共 assignment 无效：" + "; ".join(errors))

        pool_by_pair = {row["pair_id"]: row for row in candidate_rows}
        assignments_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in assignments:
            assignments_by_pair[row["pair_id"]].append(row)

        expected_double_pairs = []
        for pair_id in sorted(pool_by_pair):
            rows = assignments_by_pair[pair_id]
            secondary = [row for row in rows if row["assignment_role"] == "secondary"]
            if not secondary:
                continue
            primary = [row for row in rows if row["assignment_role"] == "primary"]
            expected_double_pairs.append(
                {
                    "pair_id": pair_id,
                    "research_query_id": pool_by_pair[pair_id]["research_query_id"],
                    "annotator_a": primary[0]["annotator_slug"],
                    "annotator_b": secondary[0]["annotator_slug"],
                }
            )

        research_query_ids = list(
            dict.fromkeys(row["research_query_id"] for row in candidate_rows)
        )
        return {
            "research_query_ids": research_query_ids,
            "expected_double_pairs": expected_double_pairs,
        }

    def _load_valid_annotations(self) -> dict[str, dict[str, dict[str, str]]]:
        if self.annotations_dir.exists() and not self.annotations_dir.is_dir():
            raise ValueError("annotations 路径必须是目录。")

        annotations: dict[str, dict[str, dict[str, str]]] = {}
        for path in sorted(self.annotations_dir.glob("*.csv"), key=lambda item: item.name):
            errors = validate_annotation_file(
                annotation_path=path,
                candidate_pool_path=self.candidate_pool_path,
                assignments_path=self.assignments_path,
            )
            if errors:
                raise ValueError(f"成员标注 {path.name} 无效：" + "; ".join(errors))
            _fields, rows = read_csv_rows(path)
            annotations[path.stem] = {row["pair_id"]: row for row in rows}
        return annotations

    @staticmethod
    def _build_comparable_records(
        expected_double_pairs: Sequence[dict[str, str]],
        annotations: dict[str, dict[str, dict[str, str]]],
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        comparable: list[dict[str, str]] = []
        missing_pairs: list[dict[str, Any]] = []
        for expected in expected_double_pairs:
            annotator_a = expected["annotator_a"]
            annotator_b = expected["annotator_b"]
            missing_annotators = [
                slug
                for slug in (annotator_a, annotator_b)
                if slug not in annotations
            ]
            if missing_annotators:
                missing_pairs.append(
                    {
                        **expected,
                        "missing_annotators": missing_annotators,
                    }
                )
                continue

            row_a = annotations[annotator_a][expected["pair_id"]]
            row_b = annotations[annotator_b][expected["pair_id"]]
            comparable.append(
                {
                    "pair_id": expected["pair_id"],
                    "research_query_id": expected["research_query_id"],
                    "annotator_a": annotator_a,
                    "label_a": row_a["label"].strip(),
                    "confidence_a": row_a["confidence"].strip(),
                    "reason_a": row_a["reason"].strip(),
                    "annotator_b": annotator_b,
                    "label_b": row_b["label"].strip(),
                    "confidence_b": row_b["confidence"].strip(),
                    "reason_b": row_b["reason"].strip(),
                }
            )
        return comparable, missing_pairs

    @staticmethod
    def _build_summary(
        *,
        research_query_ids: Sequence[str],
        expected_double_pairs: Sequence[dict[str, str]],
        comparable: Sequence[dict[str, str]],
        missing_pairs: Sequence[dict[str, Any]],
        found_annotators: Sequence[str],
    ) -> dict[str, Any]:
        expected_count = len(expected_double_pairs)
        comparable_count = len(comparable)
        expected_by_rq = Counter(
            row["research_query_id"] for row in expected_double_pairs
        )
        comparable_by_rq: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in comparable:
            comparable_by_rq[row["research_query_id"]].append(row)

        rq_breakdown = {}
        for research_query_id in research_query_ids:
            rq_expected = expected_by_rq[research_query_id]
            rq_comparable = comparable_by_rq[research_query_id]
            rq_breakdown[research_query_id] = {
                "coverage": _coverage_summary(rq_expected, len(rq_comparable)),
                "metrics": calculate_metrics(rq_comparable),
            }

        found_set = set(found_annotators)
        expected_annotators = [
            slug
            for slug in ANNOTATORS
            if any(
                slug in (row["annotator_a"], row["annotator_b"])
                for row in expected_double_pairs
            )
        ]
        ordered_found = [slug for slug in expected_annotators if slug in found_set]
        missing_annotators = [
            slug for slug in expected_annotators if slug not in found_set
        ]

        return {
            "schema_version": "1.0",
            "analysis_status": (
                "complete" if comparable_count == expected_count else "partial"
            ),
            "metric_policy": {
                "exact_agreement_scope": (
                    "all comparable pairs, including pairs containing '?'"
                ),
                "kappa_labels": list(KAPPA_LABELS),
                "question_mark_policy": (
                    "pairs containing '?' are counted separately and excluded from Kappa"
                ),
                "weighted_kappa": "quadratic",
            },
            "annotators": {
                "expected": expected_annotators,
                "found": ordered_found,
                "missing": missing_annotators,
                "found_file_count": len(ordered_found),
            },
            "coverage": {
                **_coverage_summary(expected_count, comparable_count),
                "missing_pair_details": list(missing_pairs),
            },
            "overall": calculate_metrics(comparable),
            "rq_breakdown": rq_breakdown,
        }


def calculate_metrics(records: Sequence[dict[str, str]]) -> dict[str, Any]:
    """计算 exact agreement 及排除 ``?`` 后的两种 Kappa。"""
    _validate_metric_labels(records)
    normalized = [
        {
            **row,
            "label_a": str(row["label_a"]).strip(),
            "label_b": str(row["label_b"]).strip(),
        }
        for row in records
    ]
    total_pairs = len(normalized)
    exact_count = sum(row["label_a"] == row["label_b"] for row in normalized)
    question_count = sum(
        row["label_a"] == "?" or row["label_b"] == "?" for row in normalized
    )
    kappa_records = [
        row
        for row in normalized
        if row["label_a"] != "?" and row["label_b"] != "?"
    ]

    if total_pairs:
        exact_rate: float | None = round(exact_count / total_pairs, 4)
        exact_status = "computed"
    else:
        exact_rate = None
        exact_status = "not_computable"

    kappa_result = _calculate_kappas(kappa_records)
    return {
        "total_comparable_pairs": total_pairs,
        "exact_agreement_count": exact_count,
        "exact_agreement_rate": exact_rate,
        "exact_agreement_status": exact_status,
        "exact_agreement_reason": None if total_pairs else "no_comparable_pairs",
        "pairs_with_question_mark": question_count,
        "kappa_eligible_pairs": len(kappa_records),
        **kappa_result,
    }


def generate_disagreements(
    records: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """只生成待人工仲裁队列，不选择或写入最终标签。"""
    disagreements = []
    for row in records:
        if row["label_a"] == row["label_b"]:
            continue
        disagreement_type = (
            "Needs_Discussion_Unknown"
            if "?" in {row["label_a"], row["label_b"]}
            else "Label_Conflict"
        )
        disagreements.append({**row, "disagreement_type": disagreement_type})
    return disagreements


def _validate_metric_labels(records: Sequence[dict[str, str]]) -> None:
    for index, row in enumerate(records, start=1):
        for field in ("label_a", "label_b"):
            label = str(row.get(field, "")).strip()
            if label not in VALID_LABELS:
                raise ValueError(
                    f"第 {index} 个 comparable pair 的 {field} 必须是 2/1/0/?。"
                )


def _calculate_kappas(records: Sequence[dict[str, str]]) -> dict[str, Any]:
    if len(records) < 2:
        reason = "no_kappa_eligible_pairs" if not records else "insufficient_pairs"
        return _unavailable_kappas(reason)

    labels_a = [row["label_a"] for row in records]
    labels_b = [row["label_b"] for row in records]
    if len(set(labels_a + labels_b)) == 1:
        return _unavailable_kappas("single_category")

    unweighted = _cohens_kappa(labels_a, labels_b)
    weighted = _quadratic_weighted_kappa(labels_a, labels_b)
    if unweighted is None or weighted is None:
        return _unavailable_kappas("zero_expected_disagreement")
    if not math.isfinite(unweighted) or not math.isfinite(weighted):
        raise ValueError("Kappa 计算产生非有限数值。")

    return {
        "cohens_kappa": _rounded_metric(unweighted),
        "cohens_kappa_status": "computed",
        "cohens_kappa_reason": None,
        "weighted_cohens_kappa_quadratic": _rounded_metric(weighted),
        "weighted_cohens_kappa_status": "computed",
        "weighted_cohens_kappa_reason": None,
    }


def _cohens_kappa(labels_a: Sequence[str], labels_b: Sequence[str]) -> float | None:
    count = len(labels_a)
    observed_agreement = Fraction(
        sum(
            label_a == label_b
            for label_a, label_b in zip(labels_a, labels_b)
        ),
        count,
    )
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected_agreement = Fraction(
        sum(counts_a[label] * counts_b[label] for label in KAPPA_LABELS),
        count * count,
    )
    denominator = 1 - expected_agreement
    if denominator == 0:
        return None
    return float((observed_agreement - expected_agreement) / denominator)


def _quadratic_weighted_kappa(
    labels_a: Sequence[str], labels_b: Sequence[str]
) -> float | None:
    count = len(labels_a)
    scale = (len(KAPPA_LABELS) - 1) ** 2
    observed_disagreement = Fraction(
        sum(
            (int(label_a) - int(label_b)) ** 2
            for label_a, label_b in zip(labels_a, labels_b)
        ),
        count * scale,
    )
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected_disagreement = Fraction(
        sum(
            counts_a[label_a]
            * counts_b[label_b]
            * (int(label_a) - int(label_b)) ** 2
            for label_a in KAPPA_LABELS
            for label_b in KAPPA_LABELS
        ),
        count * count * scale,
    )
    if expected_disagreement == 0:
        return None
    return float(1 - observed_disagreement / expected_disagreement)


def _unavailable_kappas(reason: str) -> dict[str, Any]:
    return {
        "cohens_kappa": None,
        "cohens_kappa_status": "not_computable",
        "cohens_kappa_reason": reason,
        "weighted_cohens_kappa_quadratic": None,
        "weighted_cohens_kappa_status": "not_computable",
        "weighted_cohens_kappa_reason": reason,
    }


def _coverage_summary(expected: int, comparable: int) -> dict[str, Any]:
    return {
        "expected_double_pairs": expected,
        "comparable_double_pairs": comparable,
        "missing_double_pairs": expected - comparable,
        "completion_rate": round(comparable / expected, 4) if expected else None,
    }


def _rounded_metric(value: float) -> float:
    rounded = round(float(value), 4)
    return 0.0 if rounded == -0.0 else rounded
