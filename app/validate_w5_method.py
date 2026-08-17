"""Validate one W5 method-ranking output package."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w5_method_contract import validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="验证 W5 Method Ranking Contract、冻结输入与 artifact hash。"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="method output package 的 manifest.json。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_method_output(
            args.manifest,
            project_root=PROJECT_ROOT,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W5 method output 验证失败：{error}")
        return 1
    print(
        "W5 method output 验证通过："
        f"method_id={result['method_id']}，pairs={len(result['ranking_rows'])}"
    )
    print("每 RQ pair：" + str(result["counts_by_query"]))
    print("ranking artifact SHA-256：" + result["ranking_sha256"])
    print("method manifest SHA-256：" + result["manifest_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
