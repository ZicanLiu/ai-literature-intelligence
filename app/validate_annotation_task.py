"""验证一个 W4 个人标注文件的格式与公共数据契约。"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.annotation_validation import annotation_summary, validate_annotation_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查 W4 标注任务完整性；不判断人工 label 是否正确。"
    )
    parser.add_argument("--file", type=Path, required=True)
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = validate_annotation_file(
        annotation_path=args.file,
        candidate_pool_path=args.candidate_pool,
        assignments_path=args.assignments,
    )
    if errors:
        print(f"标注文件验证失败：{len(errors)} 个问题")
        for error in errors:
            print(f"- {error}")
        return 1
    summary = annotation_summary(args.file)
    print("标注文件验证通过。")
    print(f"行数：{summary['row_count']}")
    print(f"label 分布：{summary['label_counts']}")
    print(f"evidence level：{summary['evidence_level_counts']}")
    print(f"AI assistance：{summary['ai_assistance_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
