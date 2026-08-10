"""W2 统一 Pipeline 命令行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.pipeline import PipelineConfig, run_unified_pipeline
from src.run_context import safe_error_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="多 acquisition query 获取、保留 provenance、统一两阶段排序。"
    )
    parser.add_argument(
        "--query-ids",
        nargs="+",
        required=True,
        help="从领域查询集中选择一个或多个 acquisition query ID。",
    )
    parser.add_argument(
        "--ranking-keyword",
        required=True,
        help="统一候选集使用的显式排序关键词；不会从 acquisition query 推断。",
    )
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument(
        "--max-results-per-query",
        type=int,
        default=20,
        help="每个 acquisition query 最多获取的记录数。",
    )
    parser.add_argument(
        "--terms",
        type=Path,
        default=PROJECT_ROOT / "data" / "domain" / "stellar_spectra_terms_w2.csv",
        help="领域词表 CSV。",
    )
    parser.add_argument(
        "--offline-fixture",
        type=Path,
        help="offline 模式的 query_id -> papers JSON fixture；offline 时必需。",
    )
    parser.add_argument("--from-year", type=int)
    parser.add_argument("--to-year", type=int)
    parser.add_argument("--labels", type=Path, help="可选评价标签 CSV。")
    parser.add_argument("--evaluation-k", type=int, default=10)
    parser.add_argument(
        "--include-unverified-labels",
        action="store_true",
        help="显式允许评价使用 AI-assisted-draft/待复核行；默认排除。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "experiments",
        help="parent run 根目录。",
    )
    parser.add_argument("--run-name", help="可选的安全运行名称片段。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "live":
        # 与现有 live CLI 一致：只把本地变量加载到进程，不读取或回显其值。
        load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

    config = PipelineConfig(
        project_root=PROJECT_ROOT,
        terms_path=args.terms,
        acquisition_query_ids=tuple(args.query_ids),
        ranking_keyword=args.ranking_keyword,
        mode=args.mode,
        max_results_per_query=args.max_results_per_query,
        output_root=args.output_root,
        run_name=args.run_name,
        from_year=args.from_year,
        to_year=args.to_year,
        labels_path=args.labels,
        evaluation_k=args.evaluation_k,
        include_unverified_labels=args.include_unverified_labels,
        offline_fixture_path=args.offline_fixture,
    )
    try:
        result = run_unified_pipeline(config)
    except (OSError, ValueError, RuntimeError) as error:
        print("Pipeline 运行失败：" + safe_error_summary(error, PROJECT_ROOT, args.output_root))
        return 1

    try:
        display_dir = result.run_dir.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        display_dir = result.run_dir.name
    counts = result.run_config["counts"]
    print(f"Pipeline 完成：{result.run_id}")
    print(f"输出目录：{display_dir}")
    print(
        "计数："
        f"combined={counts['combined_count']}，"
        f"exact={counts['exact_duplicate_count']}，"
        f"kept={counts['kept_count']}，"
        f"suspected={counts['suspected_pair_count']}，"
        f"ranked={counts['ranked_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
