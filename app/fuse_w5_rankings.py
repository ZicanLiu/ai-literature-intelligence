"""W5 RRF 混合排序融合 CLI。

将两个或更多已经通过 W5 validator 的 method ranking 通过 RRF 融合为 hybrid ranking，
并输出符合 W5 Method Ranking Contract 的 package（ranking.csv + manifest.json）。
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from src.annotation_tasks import sha256_file, write_csv_rows
from src.w5_method_contract import RANKING_FIELDS, validate_method_output
from src.w5_rank_fusion import HYBRID_FAMILY, RRF_K, fuse_rankings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将两个或更多 W5 method ranking 通过 RRF 融合为 hybrid ranking。"
    )
    parser.add_argument(
        "--manifest",
        action="append",
        required=True,
        help="输入 method manifest（可多次传入，至少两个）。",
    )
    parser.add_argument(
        "--method-id",
        required=True,
        help="输出 hybrid artifact 的 method_id。",
    )
    parser.add_argument(
        "--display-name",
        default=None,
        help="输出显示名，默认由 method-id 生成。",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="输出 package 目录（写入 ranking.csv 与 manifest.json）。",
    )
    return parser.parse_args(argv)


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_worktree_clean() -> bool:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return output.strip() == ""
    except (OSError, subprocess.SubprocessError):
        return False


def build_manifest(
    *,
    output_method_id: str,
    display_name: str,
    frozen_inputs: dict,
    ranking_sha256: str,
    rrf_k: int,
    input_method_ids: list[str],
    input_manifest_sha256: dict[str, str],
    input_ranking_sha256: dict[str, str],
    input_order_semantic: str,
    duration_seconds: float,
    git_revision: str,
    git_worktree_clean: bool,
) -> dict:
    return {
        "schema_version": "1.0",
        "contract_name": "w5_method_ranking",
        "contract_version": "1.0",
        "artifact_type": "method_ranking",
        "method": {
            "method_id": output_method_id,
            "display_name": display_name,
            "family": HYBRID_FAMILY,
            "parameters": {
                "rrf_k": rrf_k,
                "input_method_ids": input_method_ids,
                "input_manifest_sha256": input_manifest_sha256,
                "input_ranking_sha256": input_ranking_sha256,
                "input_order_semantic": input_order_semantic,
            },
            "model": None,
        },
        "inputs": frozen_inputs,
        "ranking": {
            "path": "ranking.csv",
            "sha256": ranking_sha256,
            "row_count": 60,
            "score_direction": "higher_is_better",
            "tie_breaking": ["score_desc", "pair_id_asc"],
        },
        "generation": {
            "generated_at": datetime.now().astimezone().isoformat(),
            "duration_seconds": duration_seconds,
            "git_revision": git_revision,
            "git_worktree_clean": git_worktree_clean,
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "dependencies": {},
        },
        "label_access": {
            "benchmark_labels_read": False,
            "declaration": (
                "RRF fusion generated from ranking artifacts only; "
                "no benchmark labels or judgements were read."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if len(args.manifest) < 2:
        print("错误：至少需要两个 --manifest 输入。")
        return 1

    git_revision = _git_revision()
    git_worktree_clean = _git_worktree_clean()

    packages = []
    try:
        for manifest_path in args.manifest:
            packages.append(
                validate_method_output(manifest_path, project_root=PROJECT_ROOT)
            )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输入 method artifact 校验失败：{error}")
        return 1

    started = time.perf_counter()
    try:
        fusion = fuse_rankings(
            packages,
            output_method_id=args.method_id,
            k=RRF_K,
        )
    except ValueError as error:
        print(f"RRF 融合失败：{error}")
        return 1
    duration_seconds = time.perf_counter() - started

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ranking_path = output_dir / "ranking.csv"
    write_csv_rows(ranking_path, RANKING_FIELDS, fusion["rows"])
    ranking_sha256 = sha256_file(ranking_path)

    display_name = args.display_name or args.method_id.replace("_", " ")
    manifest = build_manifest(
        output_method_id=args.method_id,
        display_name=display_name,
        frozen_inputs=packages[0]["manifest"]["inputs"],
        ranking_sha256=ranking_sha256,
        rrf_k=fusion["rrf_k"],
        input_method_ids=fusion["input_method_ids"],
        input_manifest_sha256=fusion["input_manifest_sha256"],
        input_ranking_sha256=fusion["input_ranking_sha256"],
        input_order_semantic=fusion["input_order_semantic"],
        duration_seconds=round(duration_seconds, 6),
        git_revision=git_revision,
        git_worktree_clean=git_worktree_clean,
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 输出自检：重新用 W5 validator 校验生成的 package。
    try:
        result = validate_method_output(manifest_path, project_root=PROJECT_ROOT)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输出自检失败：{error}")
        return 1

    print(f"RRF 融合完成：method_id={result['method_id']}，pairs={len(result['ranking_rows'])}")
    print(f"输出目录：{output_dir}")
    print(f"ranking artifact SHA-256：{ranking_sha256}")
    print(f"输入 method_ids：{', '.join(fusion['input_method_ids'])}")
    print(f"rrf_k：{fusion['rrf_k']}，输入顺序语义：{fusion['input_order_semantic']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
