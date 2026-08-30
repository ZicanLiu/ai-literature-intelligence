"""Validate a hash-pinned W6 Benchmark v0.2-alpha workflow package."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w6_benchmark import validate_w6_benchmark_package


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a W6 Benchmark workflow package.")
    parser.add_argument("--package", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_w6_benchmark_package(args.package)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W6 Benchmark package validation FAILED: {error}")
        return 1
    print(
        "W6 Benchmark package validation PASSED: "
        f"status={result['package']['status']}, "
        f"topics={len(result['graph']['topics'])}, "
        f"pool_items={len(result['graph']['pool_members'])}, "
        f"annotations={len(result['graph']['annotations'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
