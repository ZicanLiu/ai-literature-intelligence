"""Generate the preregistered W5 Cross-Encoder ranking artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.cross_encoder_ranking import (
    METHOD_ID,
    OUTPUT_DIR,
    SentenceTransformersCrossEncoderScorer,
    generate_cross_encoder_artifact,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "使用预注册的固定模型、revision、输入和 CPU 参数生成 W5 Cross-Encoder "
            "ranking artifact。"
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    try:
        result = generate_cross_encoder_artifact(
            project_root=PROJECT_ROOT,
            output_dir=PROJECT_ROOT / OUTPUT_DIR,
            scorer=SentenceTransformersCrossEncoderScorer(),
        )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(f"Cross-Encoder ranking 生成失败：{error}")
        return 1
    print(
        "Cross-Encoder ranking 生成完成："
        f"method_id={METHOD_ID}，pairs={len(result['ranking_rows'])}，"
        f"title_only={result['title_only_count']}"
    )
    print("ranking artifact SHA-256：" + str(result["ranking_sha256"]))
    print("manifest：" + str(result["manifest_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
