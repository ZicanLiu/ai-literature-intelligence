"""Thin CLI for the W6 Bootstrap contract bundle validator."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w6_contracts import validate_w6_bootstrap_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = (
    PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate W6 Bootstrap contracts and fixtures.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_BUNDLE,
        help="W6 Bootstrap bundle manifest (defaults to the deterministic public fixture).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_w6_bootstrap_bundle(args.manifest)
    except (OSError, ValueError) as error:
        print(f"W6 Bootstrap validation FAILED: {error}")
        return 1
    print(
        "W6 Bootstrap validation PASSED: "
        f"topics={len(result['topics'])}, "
        f"records={len(result['records'])}, "
        f"pool_items={len(result['pool_members'])}, "
        f"methods={len(result['method_packages'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
