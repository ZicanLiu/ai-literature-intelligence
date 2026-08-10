"""生成并冻结 W4 Pilot v0.1 公共候选池与双标分配。"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.annotation_tasks import bootstrap_w4_files
from src.run_context import safe_error_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从既有 W2 live 样例离线生成 W4 Pilot candidate pool。"
    )
    parser.add_argument(
        "--research-queries",
        type=Path,
        default=PROJECT_ROOT / "configs" / "w4" / "research_queries.json",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=(
            PROJECT_ROOT
            / "data"
            / "samples"
            / "w2"
            / "domain_query"
            / "live_query_sample.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "annotation_tasks" / "w4",
    )
    parser.add_argument("--reference-year", type=int, default=2026)
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已冻结 v0.1；仅限公共维护任务，普通成员不应使用。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        outputs = bootstrap_w4_files(
            project_root=PROJECT_ROOT,
            research_queries_path=args.research_queries,
            source_csv_path=args.source,
            output_dir=args.output_dir,
            reference_year=args.reference_year,
            force=args.force,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(
            "W4 bootstrap 失败："
            + safe_error_summary(error, PROJECT_ROOT, args.output_dir)
        )
        return 1
    print("W4 Pilot v0.1 公共文件已生成：")
    for name, path in outputs.items():
        try:
            display = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            display = path.name
        print(f"- {name}: {display}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
