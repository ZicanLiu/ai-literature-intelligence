"""Generate the frozen W5 SPECTER2 dense-ranking artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.specter2_ranking import (
    FROZEN_BATCH_SIZE,
    FROZEN_DEVICE,
    METHOD_ID,
    Specter2EmbeddingBackend,
    generate_specter2_artifact,
    validate_generation_inputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_POOL = (
    PROJECT_ROOT / "data" / "annotation_tasks" / "w4" / "candidate_pool_v0.1.csv"
)
DEFAULT_RESEARCH_QUERIES = PROJECT_ROOT / "configs" / "w4" / "research_queries.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "w5_methods" / METHOD_ID


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "使用已冻结的 AllenAI SPECTER2 base/query/paper adapter 配置生成 "
            "W5 Method Ranking Contract artifact。"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"method output package；默认 {DEFAULT_OUTPUT_DIR.relative_to(PROJECT_ROOT)}。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else PROJECT_ROOT / args.output_dir
    )
    try:
        # Validate both permitted generation inputs before any model download/load.
        validate_generation_inputs(
            project_root=PROJECT_ROOT,
            candidate_pool_path=DEFAULT_CANDIDATE_POOL,
            research_queries_path=DEFAULT_RESEARCH_QUERIES,
        )
        backend = Specter2EmbeddingBackend(
            device=FROZEN_DEVICE,
            batch_size=FROZEN_BATCH_SIZE,
        )
        result = generate_specter2_artifact(
            project_root=PROJECT_ROOT,
            candidate_pool_path=DEFAULT_CANDIDATE_POOL,
            research_queries_path=DEFAULT_RESEARCH_QUERIES,
            output_dir=output_dir,
            backend=backend,
        )
    except (ImportError, OSError, RuntimeError, UnicodeError, ValueError) as error:
        print(f"SPECTER2 ranking 生成失败：{error}")
        return 1

    stats = result["stats"]
    print(
        "SPECTER2 ranking 生成并验证通过："
        f"method_id={result['method_id']}，pairs={len(result['ranking_rows'])}"
    )
    print("每 RQ pair：" + str(result["counts_by_query"]))
    print(
        "缺失摘要："
        f"{stats['missing_abstract_count']}（fallback=title_only，不删除 pair）"
    )
    print("ranking artifact SHA-256：" + result["ranking_sha256"])
    print("manifest：" + str(result["manifest_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
