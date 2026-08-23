"""W5 B0/B1 基线 artifact 导出入口。

把现有 B0（preliminary_score）与 B1（TF-IDF two-stage）在不修改任何公式、
权重或阈值的前提下，导出为两个独立的 W5 Method Ranking Contract package，
并立即用公共 validator 复核。reference year 继承冻结 pool manifest（2026）。
生成阶段不读取任何 benchmark label/judgement。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w4_benchmark_evaluation import build_source_index
from src.w4_benchmark_validation import TRUSTED_W4_V01_INPUTS
from src.w5_baseline_export import (
    BASELINE_METHODS,
    capture_generation_environment,
    export_baseline_packages,
    load_frozen_inputs,
)
from src.w5_method_contract import validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="导出 B0/B1 基线为 W5 method ranking package。"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "analysis" / "w5_methods",
        help="两个 method package 的父目录。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        # 必须在任何输出写出前采集；dirty 或无法确认的 Git 状态会被拒绝。
        environment = capture_generation_environment(PROJECT_ROOT)
        frozen = load_frozen_inputs(PROJECT_ROOT)
        source_index = build_source_index(
            PROJECT_ROOT / TRUSTED_W4_V01_INPUTS["source_sample"]["path"]
        )
        manifests = export_baseline_packages(
            pool_rows=frozen["pool_rows"],
            research_queries=frozen["research_queries"],
            source_index=source_index,
            reference_year=frozen["reference_year"],
            output_root=args.output_root,
            environment=environment,
        )
        for method_id in BASELINE_METHODS:
            result = validate_method_output(
                Path(args.output_root) / method_id / "manifest.json",
                project_root=PROJECT_ROOT,
            )
            print(
                f"{method_id} 已导出并通过 W5 validator："
                f"pairs={len(result['ranking_rows'])}，"
                f"SHA-256={manifests[method_id]['ranking']['sha256']}"
            )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"B0/B1 基线导出失败：{error}")
        return 1
    print(f"reference_year={frozen['reference_year']}（继承冻结 pool manifest）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
