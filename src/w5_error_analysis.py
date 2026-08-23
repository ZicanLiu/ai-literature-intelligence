"""Validated, pair-level W5 error analysis.

The formal order is deliberate: every method artifact is validated before the
approved benchmark (and therefore its labels) is opened. Taxonomy evidence is
then joined by ``pair_id`` and never by an OpenAlex work identifier.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from src.annotation_tasks import read_csv_rows, sha256_file
from src.w4_benchmark_validation import validate_benchmark_package
from src.w5_method_contract import validate_method_output


TAXONOMY_MAPPING_FIELDS = [
    "example_id",
    "pair_id",
    "research_query_id",
    "example_role",
    "boundary_type",
    "boundary_reason",
    "source",
]
W4_TAXONOMY_REQUIRED_FIELDS = frozenset(
    {
        "example_id",
        "pair_id",
        "research_query_id",
        "example_role",
        "boundary_type",
        "boundary_reason",
    }
)
EXAMPLE_ROLES = ("scope_in", "hard_negative", "boundary")
TOP_K_VALUES = (5, 10)
RELEVANT_BURIED_MIN_RANK = 11
RANK_SHIFT_MIN_DELTA = 10
W4_TAXONOMY_SOURCE_SHA256 = (
    "2d435f4e7f3d16a383f398232f7d1b0d22c47b6583dcd702b90c5f25428dec70"
)

PAIR_ANALYSIS_FIELDS = [
    "method_id",
    "pair_id",
    "research_query_id",
    "final_label",
    "score",
    "rank",
    "example_role",
    "boundary_type",
    "error_type",
    "source",
]
MATRIX_FIELDS = [
    "method_id",
    "example_role",
    "error_type",
    "n_pairs",
    "top5_count",
    "top10_count",
    "irrelevant_top5",
    "irrelevant_top10",
]
ERROR_CASE_FIELDS = [
    "case_type",
    "method_id",
    "pair_id",
    "research_query_id",
    "final_label",
    "rank",
    "in_top5",
    "in_top10",
    "example_role",
    "boundary_type",
    "error_type",
    "source",
]
RANK_SHIFT_FIELDS = [
    "pair_id",
    "research_query_id",
    "final_label",
    "min_method_id",
    "min_rank",
    "max_method_id",
    "max_rank",
    "rank_shift",
    "example_role",
    "boundary_type",
    "error_type",
    "source",
]
COVERAGE_FIELDS = [
    "coverage_scope",
    "category",
    "count",
    "denominator",
    "ratio",
]

_ROLE_ORDER = {
    "scope_in": 0,
    "hard_negative": 1,
    "boundary": 2,
    "unclassified": 3,
}
_CASE_ORDER = {
    "irrelevant_top_k": 0,
    "relevant_buried": 1,
    "hard_negative_top_k": 2,
}
_W4_SOURCE_REFERENCE = "data/analysis/w4_query_boundary_examples.csv"


def build_taxonomy_mapping(
    w4_rows: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Convert frozen W4 examples without inventing or collapsing categories."""

    mapping: list[dict[str, str]] = []
    seen_examples: set[str] = set()
    seen_pairs: set[str] = set()
    for row_number, row in enumerate(w4_rows, start=2):
        missing = W4_TAXONOMY_REQUIRED_FIELDS.difference(row)
        if missing:
            raise ValueError(
                "W4 taxonomy source 缺少字段：" + ", ".join(sorted(missing))
            )
        item = {field: str(row.get(field) or "").strip() for field in row}
        example_id = item["example_id"]
        pair_id = item["pair_id"]
        query_id = item["research_query_id"]
        role = item["example_role"]
        boundary_type = item["boundary_type"]
        boundary_reason = item["boundary_reason"]
        if not example_id or not pair_id or not query_id or not boundary_reason:
            raise ValueError(f"W4 taxonomy source 第 {row_number} 行缺少必要值。")
        if example_id in seen_examples:
            raise ValueError(f"W4 taxonomy source 存在重复 example_id：{example_id}。")
        if pair_id in seen_pairs:
            raise ValueError(f"W4 taxonomy source 存在重复 pair_id：{pair_id}。")
        if role not in EXAMPLE_ROLES:
            raise ValueError(f"W4 taxonomy source 存在未知 example_role：{role}。")
        if role != "scope_in" and not boundary_type:
            raise ValueError(f"W4 error/boundary evidence 缺少 boundary_type：{pair_id}。")
        seen_examples.add(example_id)
        seen_pairs.add(pair_id)
        mapping.append(
            {
                "example_id": example_id,
                "pair_id": pair_id,
                "research_query_id": query_id,
                "example_role": role,
                "boundary_type": boundary_type,
                "boundary_reason": boundary_reason,
                "source": f"{_W4_SOURCE_REFERENCE}#{example_id}",
            }
        )
    return mapping


def load_taxonomy_mapping(
    mapping_path: str | Path,
    *,
    source_path: str | Path,
    benchmark_by_pair: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Load a mapping and verify that it is the exact deterministic W4 conversion."""

    resolved_source = Path(source_path).resolve()
    if sha256_file(resolved_source) != W4_TAXONOMY_SOURCE_SHA256:
        raise ValueError("W4 taxonomy source hash 与 frozen evidence 不一致。")
    source_fields, source_rows = read_csv_rows(resolved_source)
    missing_source_fields = W4_TAXONOMY_REQUIRED_FIELDS.difference(source_fields)
    if missing_source_fields:
        raise ValueError(
            "W4 taxonomy source 表头缺少字段："
            + ", ".join(sorted(missing_source_fields))
        )
    expected = build_taxonomy_mapping(source_rows)
    mapping_fields, mapping_rows = read_csv_rows(Path(mapping_path).resolve())
    if mapping_fields != TAXONOMY_MAPPING_FIELDS:
        raise ValueError(
            "taxonomy mapping 表头必须严格为："
            + ", ".join(TAXONOMY_MAPPING_FIELDS)
            + "。"
        )
    if mapping_rows != expected:
        raise ValueError("taxonomy mapping 必须是 frozen W4 evidence 的确定性转换。")
    for row in mapping_rows:
        pair_id = row["pair_id"]
        benchmark_row = benchmark_by_pair.get(pair_id)
        if benchmark_row is None:
            raise ValueError(f"taxonomy mapping 包含 benchmark 外 pair：{pair_id}。")
        if row["research_query_id"] != benchmark_row["research_query_id"]:
            raise ValueError(f"taxonomy mapping 的 RQ/pair identity 不一致：{pair_id}。")
    return mapping_rows


def analyze_w5_errors(
    method_manifest_paths: Sequence[str | Path],
    *,
    benchmark_manifest_path: str | Path,
    taxonomy_mapping_path: str | Path,
    taxonomy_source_path: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    """Validate formal inputs, join by pair_id, and build deterministic analysis."""

    if not method_manifest_paths:
        raise ValueError("至少需要一个 W5 method manifest。")
    root = Path(project_root).resolve()

    # Contract invariant: no benchmark label is opened until every method passes.
    method_packages = [
        validate_method_output(path, project_root=root)
        for path in method_manifest_paths
    ]
    method_packages.sort(key=lambda package: str(package["method_id"]))
    method_ids = [str(package["method_id"]) for package in method_packages]
    if len(method_ids) != len(set(method_ids)):
        raise ValueError("method manifests 的 method_id 必须唯一。")

    benchmark = validate_benchmark_package(
        benchmark_manifest_path,
        project_root=root,
        require_approved=True,
    )
    _judgement_fields, judgement_rows = read_csv_rows(benchmark["paths"]["judgements"])
    benchmark_by_pair = {
        row["pair_id"]: {
            "pair_id": row["pair_id"],
            "research_query_id": row["research_query_id"],
            "final_label": row["final_label"],
        }
        for row in judgement_rows
    }
    if len(benchmark_by_pair) != benchmark["pair_count"]:
        raise ValueError("approved benchmark judgement pair_id 必须唯一。")

    taxonomy_rows = load_taxonomy_mapping(
        taxonomy_mapping_path,
        source_path=taxonomy_source_path,
        benchmark_by_pair=benchmark_by_pair,
    )
    taxonomy_by_pair = {row["pair_id"]: row for row in taxonomy_rows}

    pair_rows = _build_pair_analysis_rows(
        method_packages,
        benchmark_by_pair=benchmark_by_pair,
        taxonomy_by_pair=taxonomy_by_pair,
    )
    matrix_rows = _build_method_matrix(pair_rows)
    error_case_rows = _build_error_cases(pair_rows)
    rank_shift_rows = _build_rank_shifts(pair_rows, method_count=len(method_packages))
    coverage_rows = _build_coverage_rows(
        benchmark_pair_count=len(benchmark_by_pair),
        taxonomy_rows=taxonomy_rows,
    )

    method_metadata = [
        {
            "method_id": str(package["method_id"]),
            "manifest_sha256": str(package["manifest_sha256"]),
            "ranking_sha256": str(package["ranking_sha256"]),
        }
        for package in method_packages
    ]
    return {
        "schema_version": "1.0",
        "analysis_type": "w5_error_analysis",
        "benchmark": {
            "benchmark_version": benchmark["manifest"]["benchmark_version"],
            "manifest_sha256": benchmark["benchmark_hash"],
            "pair_count": benchmark["pair_count"],
            "counts_by_query": benchmark["counts_by_query"],
        },
        "taxonomy": {
            "source_sha256": sha256_file(Path(taxonomy_source_path).resolve()),
            "mapping_sha256": sha256_file(Path(taxonomy_mapping_path).resolve()),
            "evidence_pair_count": len(taxonomy_rows),
            "unclassified_pair_count": len(benchmark_by_pair) - len(taxonomy_rows),
        },
        "methods": method_metadata,
        "thresholds": {
            "top_k": list(TOP_K_VALUES),
            "relevant_buried_min_rank": RELEVANT_BURIED_MIN_RANK,
            "rank_shift_min_delta": RANK_SHIFT_MIN_DELTA,
        },
        "pair_rows": pair_rows,
        "matrix_rows": matrix_rows,
        "error_case_rows": error_case_rows,
        "rank_shift_rows": rank_shift_rows,
        "coverage_rows": coverage_rows,
    }


def render_analysis_outputs(result: dict[str, Any]) -> dict[str, str]:
    """Render all formal outputs in memory before the CLI writes any file."""

    summary = {
        "schema_version": result["schema_version"],
        "analysis_type": result["analysis_type"],
        "benchmark": result["benchmark"],
        "taxonomy": result["taxonomy"],
        "methods": result["methods"],
        "thresholds": result["thresholds"],
        "output_row_counts": {
            "pair_analysis": len(result["pair_rows"]),
            "method_error_type_matrix": len(result["matrix_rows"]),
            "error_cases": len(result["error_case_rows"]),
            "rank_shifts": len(result["rank_shift_rows"]),
            "coverage": len(result["coverage_rows"]),
        },
    }
    return {
        "analysis_summary.json": json.dumps(
            summary, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        "pair_analysis.csv": _render_csv(PAIR_ANALYSIS_FIELDS, result["pair_rows"]),
        "method_error_type_matrix.csv": _render_csv(
            MATRIX_FIELDS, result["matrix_rows"]
        ),
        "error_cases.csv": _render_csv(ERROR_CASE_FIELDS, result["error_case_rows"]),
        "rank_shifts.csv": _render_csv(RANK_SHIFT_FIELDS, result["rank_shift_rows"]),
        "coverage.csv": _render_csv(COVERAGE_FIELDS, result["coverage_rows"]),
    }


def _build_pair_analysis_rows(
    method_packages: Sequence[dict[str, Any]],
    *,
    benchmark_by_pair: dict[str, dict[str, str]],
    taxonomy_by_pair: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    expected_pairs = set(benchmark_by_pair)
    rows: list[dict[str, Any]] = []
    for package in method_packages:
        ranking_rows = package["ranking_rows"]
        ranking_pairs = {row["pair_id"] for row in ranking_rows}
        if ranking_pairs != expected_pairs or len(ranking_rows) != len(expected_pairs):
            raise ValueError("validated method ranking 与 approved benchmark pair identity 不一致。")
        for ranking in ranking_rows:
            pair_id = ranking["pair_id"]
            judgement = benchmark_by_pair[pair_id]
            query_id = ranking["research_query_id"]
            if query_id != judgement["research_query_id"]:
                raise ValueError(f"method/benchmark 的 RQ identity 不一致：{pair_id}。")
            taxonomy = taxonomy_by_pair.get(pair_id)
            role, boundary_type, error_type, source = _taxonomy_values(taxonomy)
            rows.append(
                {
                    "method_id": package["method_id"],
                    "pair_id": pair_id,
                    "research_query_id": query_id,
                    "final_label": judgement["final_label"],
                    "score": ranking["score"],
                    "rank": ranking["rank"],
                    "example_role": role,
                    "boundary_type": boundary_type,
                    "error_type": error_type,
                    "source": source,
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["method_id"],
            row["research_query_id"],
            row["rank"],
            row["pair_id"],
        ),
    )


def _build_method_matrix(pair_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        grouped[(row["method_id"], row["example_role"], row["error_type"])].append(
            row
        )
    output: list[dict[str, Any]] = []
    for (method_id, role, error_type), rows in grouped.items():
        output.append(
            {
                "method_id": method_id,
                "example_role": role,
                "error_type": error_type,
                "n_pairs": len(rows),
                "top5_count": sum(row["rank"] <= 5 for row in rows),
                "top10_count": sum(row["rank"] <= 10 for row in rows),
                "irrelevant_top5": sum(
                    row["final_label"] == "0" and row["rank"] <= 5 for row in rows
                ),
                "irrelevant_top10": sum(
                    row["final_label"] == "0" and row["rank"] <= 10
                    for row in rows
                ),
            }
        )
    return sorted(
        output,
        key=lambda row: (
            row["method_id"],
            _ROLE_ORDER[row["example_role"]],
            row["error_type"],
        ),
    )


def _build_error_cases(pair_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for row in pair_rows:
        case_types: list[str] = []
        if row["final_label"] == "0" and row["rank"] <= 10:
            case_types.append("irrelevant_top_k")
        if row["final_label"] == "2" and row["rank"] >= RELEVANT_BURIED_MIN_RANK:
            case_types.append("relevant_buried")
        if row["example_role"] == "hard_negative" and row["rank"] <= 10:
            case_types.append("hard_negative_top_k")
        for case_type in case_types:
            cases.append(
                {
                    "case_type": case_type,
                    "method_id": row["method_id"],
                    "pair_id": row["pair_id"],
                    "research_query_id": row["research_query_id"],
                    "final_label": row["final_label"],
                    "rank": row["rank"],
                    "in_top5": int(row["rank"] <= 5),
                    "in_top10": int(row["rank"] <= 10),
                    "example_role": row["example_role"],
                    "boundary_type": row["boundary_type"],
                    "error_type": row["error_type"],
                    "source": row["source"],
                }
            )
    return sorted(
        cases,
        key=lambda row: (
            _CASE_ORDER[row["case_type"]],
            row["method_id"],
            row["research_query_id"],
            row["rank"],
            row["pair_id"],
        ),
    )


def _build_rank_shifts(
    pair_rows: Sequence[dict[str, Any]], *, method_count: int
) -> list[dict[str, Any]]:
    if method_count < 2:
        return []
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        by_pair[row["pair_id"]].append(row)
    shifts: list[dict[str, Any]] = []
    for pair_id, rows in by_pair.items():
        if len(rows) != method_count:
            raise ValueError(f"跨方法 rank shift 缺少 pair：{pair_id}。")
        minimum = min(rows, key=lambda row: (row["rank"], row["method_id"]))
        maximum = max(rows, key=lambda row: (row["rank"], row["method_id"]))
        delta = maximum["rank"] - minimum["rank"]
        if delta < RANK_SHIFT_MIN_DELTA:
            continue
        shifts.append(
            {
                "pair_id": pair_id,
                "research_query_id": minimum["research_query_id"],
                "final_label": minimum["final_label"],
                "min_method_id": minimum["method_id"],
                "min_rank": minimum["rank"],
                "max_method_id": maximum["method_id"],
                "max_rank": maximum["rank"],
                "rank_shift": delta,
                "example_role": minimum["example_role"],
                "boundary_type": minimum["boundary_type"],
                "error_type": minimum["error_type"],
                "source": minimum["source"],
            }
        )
    return sorted(shifts, key=lambda row: (-row["rank_shift"], row["pair_id"]))


def _build_coverage_rows(
    *, benchmark_pair_count: int, taxonomy_rows: Sequence[dict[str, str]]
) -> list[dict[str, Any]]:
    role_counts = Counter(row["example_role"] for row in taxonomy_rows)
    evidence_count = len(taxonomy_rows)
    unclassified_count = benchmark_pair_count - evidence_count
    if unclassified_count < 0:
        raise ValueError("taxonomy evidence 数量超过 approved benchmark pair 数量。")
    rows: list[dict[str, Any]] = []
    for role in EXAMPLE_ROLES:
        rows.append(
            _coverage_row(
                "benchmark_coverage", role, role_counts[role], benchmark_pair_count
            )
        )
    rows.append(
        _coverage_row(
            "benchmark_coverage",
            "unclassified",
            unclassified_count,
            benchmark_pair_count,
        )
    )
    for role in EXAMPLE_ROLES:
        rows.append(
            _coverage_row(
                "taxonomy_evidence_distribution",
                role,
                role_counts[role],
                evidence_count,
            )
        )
    return rows


def _coverage_row(scope: str, category: str, count: int, denominator: int) -> dict:
    ratio = round(count / denominator, 6) if denominator else 0.0
    return {
        "coverage_scope": scope,
        "category": category,
        "count": count,
        "denominator": denominator,
        "ratio": ratio,
    }


def _taxonomy_values(
    taxonomy: dict[str, str] | None,
) -> tuple[str, str, str, str]:
    if taxonomy is None:
        return "unclassified", "", "unclassified", ""
    role = taxonomy["example_role"]
    boundary_type = taxonomy["boundary_type"]
    error_type = "scope_in" if role == "scope_in" else boundary_type
    return role, boundary_type, error_type, taxonomy["source"]


def _render_csv(fields: list[str], rows: Sequence[dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fields,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()
