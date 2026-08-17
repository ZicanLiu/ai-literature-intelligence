"""Validate a W4 Pilot Query Relevance judged-set package."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w4_benchmark_validation import validate_benchmark_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "benchmarks"
    / "w4_query_relevance"
    / "v0.1.0-draft.1"
    / "manifest.json"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "验证 W4 Pilot judged-set。默认 strict：只接受 approved 60/60 benchmark。"
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="只用于复核 proposed/draft 的结构和 hash；不得用于正式实验。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_benchmark_package(
            args.manifest,
            project_root=PROJECT_ROOT,
            require_approved=not args.allow_draft,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"benchmark 验证失败：{error}")
        return 1
    manifest = result["manifest"]
    mode = "draft-review" if args.allow_draft else "strict-approved"
    print(
        "benchmark 验证通过："
        f"mode={mode}，status={manifest['status']}，"
        f"version={manifest['benchmark_version']}，pairs={result['pair_count']}"
    )
    print("每 RQ pair：" + str(result["counts_by_query"]))
    print("benchmark manifest SHA-256：" + result["benchmark_hash"])
    if args.allow_draft:
        print("注意：draft-review 通过不等于 approved，不得用于正式 strict evaluator。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
