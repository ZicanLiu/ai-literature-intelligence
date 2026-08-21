"""Evaluate arbitrary validated W5 method artifacts with the approved benchmark."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w5_experiment import run_w5_experiment


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_MANIFEST = (
    PROJECT_ROOT / "data" / "benchmarks" / "w4_query_relevance" / "v0.1.0" / "manifest.json"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "验证一个或多个 W5 Method Ranking Contract artifact，并使用 approved "
            "W4 benchmark 统一输出 per-RQ 与 macro 指标。"
        )
    )
    parser.add_argument(
        "--method-manifest",
        type=Path,
        action="append",
        required=True,
        help="可重复提供；每项必须先通过 W5 method validator。",
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=DEFAULT_BENCHMARK_MANIFEST,
        help="approved W4 benchmark manifest。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="新的 experiment output 目录；拒绝覆盖非空目录。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else PROJECT_ROOT / args.output_dir
    )
    try:
        result = run_w5_experiment(
            method_manifest_paths=args.method_manifest,
            benchmark_manifest_path=args.benchmark_manifest,
            output_dir=output_dir,
            project_root=PROJECT_ROOT,
            require_clean_git=True,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W5 multi-method experiment 失败：{error}")
        return 1

    print(
        "W5 multi-method experiment 完成："
        f"methods={len(result['method_ids'])}，method_ids={result['method_ids']}"
    )
    print("metrics：" + str(result["metrics_path"]))
    print("experiment manifest：" + str(result["experiment_manifest_path"]))
    for method_result in result["results"]:
        macro = method_result["macro"]
        print(
            f"  {method_result['method_id']}: "
            f"NDCG@5={_fmt(macro['ndcg_at_5'])} "
            f"NDCG@10={_fmt(macro['ndcg_at_10'])} "
            f"P@5={_fmt(macro['precision_at_5'])} "
            f"P@10={_fmt(macro['precision_at_10'])}"
        )
    print("说明：只报告统一指标，不自动宣称最佳方法。")
    return 0


def _fmt(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
