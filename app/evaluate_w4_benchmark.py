"""W4 Pilot Benchmark 的 Baseline vs Two-stage 统一评价入口。

partial/smoke 模式继续接受 labels CSV；正式模式只接受通过 strict validator 的
approved versioned benchmark package。两种模式都复用现有 Baseline / Two-stage
ranking，并输出按 RQ 分开的结果与 error case 底稿。

用法示例：

    python -m app.evaluate_w4_benchmark \\
        --strict --benchmark-manifest data/benchmarks/.../manifest.json
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
    write_experiment_manifest,
)
from src.w4_benchmark_validation import validate_benchmark_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis"
DEFAULT_SOURCE = (
    PROJECT_ROOT / "data" / "samples" / "w2" / "domain_query" / "live_query_sample.csv"
)
DEFAULT_RESEARCH_QUERIES = PROJECT_ROOT / "configs" / "w4" / "research_queries.json"

METRIC_CSV_FIELDS = [
    "research_query_id",
    "method",
    "reference_year",
    "pair_count",
    "labeled_count",
] + METRIC_KEYS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="W4 Pilot Benchmark：Baseline vs Two-stage 统一评价与 error case 输出。"
    )
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        help="W4 candidate pool CSV；partial 模式默认使用冻结 v0.1。",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        help="partial/smoke labels（pair_id,label）；strict 模式禁止使用此参数。",
    )
    parser.add_argument(
        "--research-queries",
        type=Path,
        help="W4 research query 配置 JSON；partial 模式默认使用冻结 v0.1。",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="既有 W2 live 样例 CSV；partial 模式默认使用冻结来源。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="正式 benchmark 模式：只接受 approved 60/60 versioned package。",
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        help="strict 模式必需的 approved benchmark manifest.json。",
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
    parser.add_argument(
        "--experiment-manifest",
        type=Path,
        help="strict 模式实验 manifest 路径；默认 output-dir/experiment_manifest.json。",
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
        benchmark_package = None
        if args.strict:
            if args.benchmark_manifest is None:
                raise ValueError("strict 模式必须提供 --benchmark-manifest。")
            if args.labels is not None:
                raise ValueError("strict 模式从 approved package 读取标签，禁止 --labels。")
            benchmark_package = validate_benchmark_package(
                args.benchmark_manifest,
                project_root=PROJECT_ROOT,
                require_approved=True,
            )
            package_paths = benchmark_package["paths"]
            _reject_input_mismatch(
                args.candidate_pool, package_paths["candidate_pool"], "candidate pool"
            )
            _reject_input_mismatch(
                args.research_queries,
                package_paths["research_queries"],
                "research query config",
            )
            _reject_input_mismatch(args.source, package_paths["source_sample"], "source")
            candidate_pool_path = package_paths["candidate_pool"]
            research_queries_path = package_paths["research_queries"]
            source_path = package_paths["source_sample"]
            labels = benchmark_package["labels"]
        else:
            if args.benchmark_manifest is not None:
                raise ValueError("--benchmark-manifest 只能与 --strict 一起使用。")
            if args.labels is None:
                raise ValueError("partial/smoke 模式必须提供 --labels。")
            candidate_pool_path = args.candidate_pool or (
                DEFAULT_DATA_DIR / "candidate_pool_v0.1.csv"
            )
            research_queries_path = args.research_queries or DEFAULT_RESEARCH_QUERIES
            source_path = args.source or DEFAULT_SOURCE
            labels = load_benchmark_labels(args.labels)

        _pool_fields, pool_rows = read_csv_rows(candidate_pool_path)
        research_queries = load_research_queries(research_queries_path)
        source_index = build_source_index(source_path)
        result = evaluate_benchmark(
            pool_rows=pool_rows,
            labels=labels,
            research_queries=research_queries,
            source_index=source_index,
            reference_year=args.reference_year,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输入读取失败：{error}")
        return 1

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

    if args.strict:
        experiment_manifest = args.experiment_manifest or (
            output_dir / "experiment_manifest.json"
        )
        experiment_manifest = _resolve(experiment_manifest)
        write_experiment_manifest(
            output_path=experiment_manifest,
            project_root=PROJECT_ROOT,
            benchmark_package=benchmark_package,
            candidate_pool_path=candidate_pool_path,
            research_queries_path=research_queries_path,
            source_path=source_path,
            reference_year=args.reference_year,
            metrics_path=metrics_csv,
            error_cases_path=error_cases_csv,
        )
        print(f"已保存正式实验 manifest：{_display(experiment_manifest)}")

    print(f"\nreference_year：{result['reference_year']}（baseline recency_score 固定参考年）")
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
    macro_incomplete = any(
        result["macro"][method].get(key) is None
        for method in ("baseline", "two_stage")
        for key in METRIC_KEYS
    )
    if macro_incomplete:
        print(
            "\n注意：benchmark judgement 尚不完整——至少一个正式 Research Query "
            "缺少有效标签，macro 中对应指标为 None，不能当作三组 Query 的平均值。"
        )
    print("\n说明：指标为 judged（condensed）口径；None 表示该截断下无确定等级，"
          "不代表 0 分。error case 只给类型代码，不做原因结论。")
    return 0


def _reject_input_mismatch(
    supplied: Path | None, expected: Path, label: str
) -> None:
    if supplied is not None and supplied.resolve() != expected.resolve():
        raise ValueError(
            f"strict 模式的 {label} 必须与 benchmark manifest 锁定路径一致。"
        )


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
