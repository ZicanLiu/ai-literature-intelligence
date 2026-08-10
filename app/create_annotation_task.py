"""为一个 W4 annotator 生成其个人标注 CSV。"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.annotation_tasks import ANNOTATORS, create_annotation_task
from src.run_context import safe_error_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据公共 candidate pool 和 assignment 生成一个人的 15 条标注任务。"
    )
    parser.add_argument("--annotator", required=True, choices=list(ANNOTATORS))
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=DEFAULT_DATA_DIR / "candidate_pool_v0.1.csv",
    )
    parser.add_argument(
        "--assignments",
        type=Path,
        default=DEFAULT_DATA_DIR / "assignments_v0.1.csv",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖现有个人标注文件；普通成员不应使用。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output or DEFAULT_DATA_DIR / "annotations" / f"{args.annotator}.csv"
    try:
        created = create_annotation_task(
            annotator_slug=args.annotator,
            candidate_pool_path=args.candidate_pool,
            assignments_path=args.assignments,
            output_path=output,
            force=args.force,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(
            "创建标注任务失败："
            + safe_error_summary(error, PROJECT_ROOT, output.parent)
        )
        return 1
    try:
        display = created.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        display = created.name
    print(f"已生成 {args.annotator} 的 15 条标注任务：{display}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
