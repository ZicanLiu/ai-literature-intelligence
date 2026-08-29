"""Thin CLI for the W6 Multi-Retriever Candidate Pool Builder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.w6_candidate_pool_builder import run_pool_build


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从冻结 W6 topics、N 个 retrieval artifacts 和 source records 构建"
            "确定性的 pre-canonical Candidate Pool。"
        )
    )
    parser.add_argument("--topics", required=True, help="冻结 w6_topic_set JSON。")
    parser.add_argument(
        "--retrieval",
        required=True,
        action="append",
        help="冻结 w6_retrieval_provenance JSON；可重复传入。",
    )
    parser.add_argument(
        "--source-records", required=True, help="冻结 w6_source_records JSON。"
    )
    parser.add_argument("--policy", required=True, help="冻结 pooling policy JSON。")
    parser.add_argument(
        "--policy-sha256",
        required=True,
        help="policy 文件预注册的 64 位小写 SHA-256。",
    )
    parser.add_argument("--output-dir", required=True, help="空的 artifact 输出目录。")
    parser.add_argument(
        "--status",
        choices=("candidate", "frozen"),
        default="candidate",
        help="输出 pool 状态；frozen 要求生成开始前 Git 工作区 clean。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest_path = run_pool_build(
            topic_set_path=args.topics,
            retrieval_paths=args.retrieval,
            source_records_path=args.source_records,
            policy_path=args.policy,
            expected_policy_sha256=args.policy_sha256,
            output_dir=args.output_dir,
            project_root=PROJECT_ROOT,
            status=args.status,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"W6 candidate-pool build FAILED: {error}", file=sys.stderr)
        return 1

    output = manifest["outputs"]["candidate_pool"]
    print(
        "W6 candidate-pool build PASSED: "
        f"pool_identity={output['pool_identity']}, manifest={manifest_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
