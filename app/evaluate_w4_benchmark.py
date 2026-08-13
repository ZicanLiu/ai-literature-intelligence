"""W4 Pilot Benchmark 的 Baseline vs Two-stage 统一评价入口。

未来输入：最终 adjudicated benchmark labels + Candidate Pool + 现有
Baseline / Two-stage ranking；输出统一实验结果（按 RQ 分开 + macro）与
error case 底稿。

用法示例：

    python -m app.evaluate_w4_benchmark \\
        --labels data/annotation_tasks/w4/adjudicated_labels.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.annotation_tasks import load_research_queries, read_csv_rows
from src.w4_benchmark_evaluation import (
    ERROR_CASE_FIELDS,
    METRIC_KEYS,
    METHOD_NAMES,
    build_error_cases,
    build_metric_rows,
    build_source_index,
    evaluate_benchmark,
    load_benchmark_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis"
DEFAULT_SOURCE = (
    PROJECT_ROOT / "data" / "samples" / "w2" / "domain_query" / "live_query_sample.csv"
)
DEFAULT_RESEARCH_QUERIES = PROJECT_ROOT / "configs" / "w4" / "research_queries.json"

METRIC_CSV_FIELDS = ["research_query_id", "method"] + METRIC_KEYS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="W4 Pilot Benchmark：Baseline vs Two-stage 统一评价与 error case 输出。"
    )
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=DEFAULT_DATA_DIR / "candidate_pool_v0.1.csv",
        help="W4 candidate pool CSV。",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        required=True,
        help="adjudicated benchmark labels（pair_id,label）；个人标注 CSV 也可直接使用。",
    )
    parser.add_argument(
        "--research-queries",
        type=Path,
        default=DEFAULT_RESEARCH_QUERIES,
        help="W4 research query 配置 JSON。",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="既有 W2 live 样例 CSV，用于补全排序字段。",
    )
    parser.add_argument(
        "--reference-year",
        type=int,
        default=2026,
        help="baseline recency_score 的固定参考年，与 candidate pool 生成一致。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="分析输出目录，默认 data/analysis。",
    )
    parser.add_argument(
        "--metrics-csv",
        type=Path,
        help="指标结果 CSV 路径；默认 output-dir/w4_benchmark_metrics.csv。",
    )
    parser.add_argument(
        "--error-cases",
        type=Path,
        help="error case CSV 路径；默认 output-dir/w4_ranking_error_cases.csv。",
    )
    return parser.parse_args(argv)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        _pool_fields, pool_rows = read_csv_rows(args.candidate_pool)
        labels = load_benchmark_labels(args.labels)
        research_queries = load_research_queries(args.research_queries)
        source_index = build_source_index(args.source)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输入读取失败：{error}")
        return 1

    result = evaluate_benchmark(
        pool_rows=pool_rows,
        labels=labels,
        research_queries=research_queries,
        source_index=source_index,
        reference_year=args.reference_year,
    )

    output_dir = args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir
    metrics_csv = args.metrics_csv or (output_dir / "w4_benchmark_metrics.csv")
    error_cases_csv = args.error_cases or (output_dir / "w4_ranking_error_cases.csv")
    metrics_csv = _resolve(metrics_csv)
    error_cases_csv = _resolve(error_cases_csv)

    metric_rows = build_metric_rows(result)
    _write_csv(metrics_csv, METRIC_CSV_FIELDS, metric_rows)
    print(f"已保存指标结果：{_display(metrics_csv)}")

    error_rows = build_error_cases(result["per_query"], labels)
    _write_csv(error_cases_csv, ERROR_CASE_FIELDS, error_rows)
    print(f"已保存 error case 底稿：{_display(error_cases_csv)}")

    print("\n按 Research Question 分开评价：")
    for query_id, query_result in result["per_query"].items():
        print(f"  {query_id}（pair {query_result['pair_count']}，labeled {query_result['labeled_count']}）")
        for method in ("baseline", "two_stage"):
            metrics = query_result[method]
            print(
                f"    {METHOD_NAMES[method]}: NDCG@5={_fmt(metrics['ndcg_at_5'])} "
                f"NDCG@10={_fmt(metrics['ndcg_at_10'])} "
                f"P@5={_fmt(metrics['precision_at_5'])} "
                f"P@10={_fmt(metrics['precision_at_10'])} "
                f"Cov@5={_fmt(metrics['coverage_at_5'])} "
                f"Cov@10={_fmt(metrics['coverage_at_10'])} "
                f"irr@5={metrics['irrelevant_top_5']} "
                f"irr@10={metrics['irrelevant_top_10']}"
            )
    print("\nmacro average：")
    for method in ("baseline", "two_stage"):
        metrics = result["macro"][method]
        print(
            f"  {METHOD_NAMES[method]}: NDCG@5={_fmt(metrics['ndcg_at_5'])} "
            f"NDCG@10={_fmt(metrics['ndcg_at_10'])} "
            f"P@5={_fmt(metrics['precision_at_5'])} "
            f"P@10={_fmt(metrics['precision_at_10'])} "
            f"Cov@5={_fmt(metrics['coverage_at_5'])} "
            f"Cov@10={_fmt(metrics['coverage_at_10'])} "
            f"irr@5={metrics['irrelevant_top_5']} "
            f"irr@10={metrics['irrelevant_top_10']}"
        )
    print("\n说明：指标为 judged（condensed）口径；None 表示该截断下无确定等级，"
          "不代表 0 分。error case 只给类型代码，不做原因结论。")
    return 0


def _fmt(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
