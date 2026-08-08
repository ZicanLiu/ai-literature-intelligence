"""从领域词典生成稳定的 OpenAlex 查询集合。"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.domain_query import build_query_set, load_domain_terms, write_query_set


DEFAULT_TERMS = Path("data/domain/stellar_spectra_terms_w2.csv")
DEFAULT_OUTPUT = Path("configs/w2/domain_query_set.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="读取天文光谱领域词典并生成 6 组可解释的 OpenAlex search 关键词。"
    )
    parser.add_argument(
        "--terms",
        type=Path,
        default=DEFAULT_TERMS,
        help="领域词典 CSV；默认 data/domain/stellar_spectra_terms_w2.csv。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="查询集合 JSON 输出路径；默认 configs/w2/domain_query_set.json。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        terms = load_domain_terms(args.terms)
        query_set = build_query_set(terms, source_path=args.terms.as_posix())
        write_query_set(query_set, args.output)
    except (OSError, ValueError) as error:
        print(f"生成失败：{error}")
        return 1
    print(
        f"已从 {len(terms)} 个领域词项生成 {query_set['query_count']} 组查询："
        f"{args.output.as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
