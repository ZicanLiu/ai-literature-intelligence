"""Validate the real W6 Topic viability/freeze/split artifacts for Issue #64."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w6_benchmark import validate_topic_freeze_files


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate W6 frozen Topic roster and split.")
    parser.add_argument("--topics", type=Path, default=DEFAULT_ROOT / "topics.json")
    parser.add_argument("--split", type=Path, default=DEFAULT_ROOT / "split_manifest.json")
    parser.add_argument("--research", type=Path, default=DEFAULT_ROOT / "topic_research.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_topic_freeze_files(
            args.topics, args.split, research_path=args.research
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W6 Topic freeze validation FAILED: {error}")
        return 1
    print(
        "W6 Topic freeze validation PASSED: "
        f"topics={len(result['topics'])}, "
        f"dev={len(result['split_sets']['dev'])}, "
        f"hidden={len(result['split_sets']['hidden'])}, "
        f"split_identity={result['split_payload']['split_identity']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
