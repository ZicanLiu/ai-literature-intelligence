"""分析 W4 独立双标结果的一致性并输出待人工仲裁队列。"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.annotation_agreement import AgreementAnalyzer
from src.run_context import safe_error_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="分析 W4 双人独立标注的一致性与分歧。"
    )
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=DEFAULT_DATA_DIR / "candidate_pool_v0.1.csv",
        help="W4 candidate pool 文件路径。",
    )
    parser.add_argument(
        "--assignments",
        type=Path,
        default=DEFAULT_DATA_DIR / "assignments_v0.1.csv",
        help="W4 assignment 文件路径。",
    )
    parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=DEFAULT_DATA_DIR / "annotations",
        help="成员标注 CSV 所在目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "analysis" / "w4_annotation_agreement",
        help="分析结果输出目录。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    analyzer = AgreementAnalyzer(
        assignments_path=args.assignments,
        annotations_dir=args.annotations_dir,
        candidate_pool_path=args.candidate_pool,
    )

    print("正在分析 W4 标注一致性...")
    try:
        summary = analyzer.analyze(output_dir=args.output_dir)
    except (OSError, UnicodeError, ValueError) as error:
        print(
            "标注一致性分析失败："
            + safe_error_summary(error, PROJECT_ROOT, args.output_dir)
        )
        return 1

    coverage = summary["coverage"]
    print(
        "分析完成："
        f"status={summary['analysis_status']}，"
        f"expected={coverage['expected_double_pairs']}，"
        f"comparable={coverage['comparable_double_pairs']}，"
        f"missing={coverage['missing_double_pairs']}"
    )
    missing_annotators = summary["annotators"]["missing"]
    if missing_annotators:
        print("尚缺成员文件：" + ", ".join(missing_annotators))
    print("报告目录：" + _display_path(args.output_dir))
    return 0


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


if __name__ == "__main__":
    raise SystemExit(main())
