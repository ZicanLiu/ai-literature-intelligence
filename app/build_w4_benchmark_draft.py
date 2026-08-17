"""Build the versioned W4 Pilot Query Relevance judged-set draft."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w4_benchmark_artifact import build_benchmark_draft


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "benchmarks"
    / "w4_query_relevance"
    / "v0.1.0-draft.1"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成可人工复核的 W4 Pilot Query Relevance judged-set draft。"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--proposals",
        type=Path,
        default=DEFAULT_OUTPUT / "adjudication_proposals.csv",
    )
    parser.add_argument("--force", action="store_true", help="显式覆盖已生成的 draft。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        paths = build_benchmark_draft(
            project_root=PROJECT_ROOT,
            candidate_pool_path=TASK_DIR / "candidate_pool_v0.1.csv",
            assignments_path=TASK_DIR / "assignments_v0.1.csv",
            research_queries_path=PROJECT_ROOT / "configs" / "w4" / "research_queries.json",
            source_sample_path=(
                PROJECT_ROOT
                / "data"
                / "samples"
                / "w2"
                / "domain_query"
                / "live_query_sample.csv"
            ),
            pool_manifest_path=TASK_DIR / "pool_manifest_v0.1.json",
            annotations_dir=TASK_DIR / "annotations",
            proposals_path=args.proposals,
            output_dir=args.output_dir,
            reference_year=2026,
            force=args.force,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"生成 benchmark draft 失败：{error}")
        return 1
    print("已生成 W4 Pilot judged-set draft：")
    for name in ("judgements", "proposals", "manifest"):
        print(f"  {name}: {_display(paths[name])}")
    print("状态：proposed；3 个 AI adjudication proposal 仍待独立人工复核。")
    return 0


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


if __name__ == "__main__":
    raise SystemExit(main())
