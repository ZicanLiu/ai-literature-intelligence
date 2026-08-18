"""W5 BM25 sparse ranking 生成入口。

在冻结 W4 Candidate Pool 上运行预注册 BM25（k1=1.5, b=0.75），输出符合
W5 Method Ranking Contract 的 package（ranking.csv + manifest.json），并立即
用公共 validator 复核。生成阶段不读取任何 benchmark label/judgement。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.bm25_ranking import BM25_B, BM25_K1, build_pool_rankings
from src.w5_baseline_export import (
    capture_generation_environment,
    load_frozen_inputs,
    write_w5_package,
)
from src.w5_method_contract import validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BM25_METHOD_ID = "bm25_v1"
BM25_DISPLAY_NAME = "BM25 sparse lexical v1"
BM25_PARAMETERS = {
    "k1": BM25_K1,
    "b": BM25_B,
    "tokenizer": "src.text_relevance.tokenize_text",
    "document": "title+abstract",
    "corpus": "w4_candidate_pool_v0.1 60 record-level texts (alias kept)",
    "scoring_module": "src.bm25_ranking",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在冻结 W4 Candidate Pool 上生成 BM25 W5 method ranking package。"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "analysis" / "w5_methods" / BM25_METHOD_ID,
        help="method output package 目录。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        # 必须在任何输出写出前采集；dirty 或无法确认的 Git 状态会被拒绝。
        environment = capture_generation_environment(PROJECT_ROOT)
        frozen = load_frozen_inputs(PROJECT_ROOT)
        started = datetime.now(timezone.utc).astimezone()
        rows = build_pool_rankings(frozen["pool_rows"], frozen["research_queries"])
        manifest = write_w5_package(
            args.output_dir,
            method_id=BM25_METHOD_ID,
            display_name=BM25_DISPLAY_NAME,
            family="sparse",
            parameters=BM25_PARAMETERS,
            model=None,
            rows=rows,
            environment=environment,
            started_at=started,
        )
        result = validate_method_output(
            Path(args.output_dir) / "manifest.json", project_root=PROJECT_ROOT
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"BM25 ranking 生成失败：{error}")
        return 1
    print(
        f"BM25 ranking 已生成并通过 W5 validator：method_id={result['method_id']}，"
        f"pairs={len(result['ranking_rows'])}"
    )
    print(f"输出目录：{Path(args.output_dir)}")
    print(f"ranking artifact SHA-256：{manifest['ranking']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
