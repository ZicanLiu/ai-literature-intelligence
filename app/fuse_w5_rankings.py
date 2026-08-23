"""W5 RRF 混合排序融合 CLI。

将两个或更多已经通过 W5 validator 的 method ranking 通过 RRF 融合为 hybrid ranking，
并输出符合 W5 Method Ranking Contract 的 package（ranking.csv + manifest.json）。
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from src.annotation_tasks import sha256_file, write_csv_rows
from src.w5_method_contract import (
    GIT_REVISION_PATTERN,
    METHOD_ID_PATTERN,
    RANKING_FIELDS,
    validate_method_output,
)
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
                "rrf_k": RRF_K,
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


def _validate_method_id(method_id: str) -> None:
    if (
        not isinstance(method_id, str)
        or method_id != method_id.strip()
        or not METHOD_ID_PATTERN.fullmatch(method_id)
    ):
        raise ValueError(
            "method-id 必须是稳定的小写机器标识（a-z、0-9、点、下划线或连字符）。"
        )


def _check_output_dir_safe(output_dir: Path, input_package_dirs: list[Path]) -> None:
    resolved = output_dir.resolve()
    for package_dir in input_package_dirs:
        package_resolved = package_dir.resolve()
        if resolved == package_resolved or resolved.is_relative_to(
            package_resolved
        ) or package_resolved.is_relative_to(resolved):
            raise ValueError(
                f"输出目录与输入 package 重合，禁止覆盖输入 artifact：{package_resolved}"
            )
    if resolved.exists():
        if any(resolved.iterdir()):
            raise ValueError(f"输出目录已存在且非空，拒绝覆盖：{resolved}")


def _publish_package(source_dir: Path, output_dir: Path) -> None:
    """在目标同级准备完整 package，再整体发布到最终目录。"""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.publish_", dir=output_dir.parent
    ) as publish_tmp:
        publish_dir = Path(publish_tmp)
        shutil.copy2(source_dir / "ranking.csv", publish_dir / "ranking.csv")
        shutil.copy2(source_dir / "manifest.json", publish_dir / "manifest.json")

        # 安全预检只允许目标不存在或为空；在完整 staging package 就绪后再移除空目录。
        if output_dir.exists():
            output_dir.rmdir()
        publish_dir.replace(output_dir)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if len(args.manifest) < 2:
        print("错误：至少需要两个 --manifest 输入。")
        return 1

    started = time.perf_counter()

    # 预检 1：method_id 格式（可提前判断）。
    try:
        _validate_method_id(args.method_id)
    except ValueError as error:
        print(f"输出参数校验失败：{error}")
        return 1

    # 输入 method artifact 校验（先于 Git / 输出目录预检，保证错误信息准确）。
    packages = []
    try:
        for manifest_path in args.manifest:
            packages.append(
                validate_method_output(manifest_path, project_root=PROJECT_ROOT)
            )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输入 method artifact 校验失败：{error}")
        return 1

    # 预检 2：Git clean 状态与完整 revision（写文件前提前失败）。
    git_revision = _git_revision()
    git_worktree_clean = _git_worktree_clean()
    if not git_worktree_clean:
        print("错误：正式 method ranking 必须在 clean Git 工作树生成。")
        return 1
    if not GIT_REVISION_PATTERN.fullmatch(git_revision):
        print("错误：无法确认完整 40 位 Git commit SHA。")
        return 1

    # 预检 3：输出目录安全（不与输入 package 重合、不覆盖非空目标）。
    input_package_dirs = [p["manifest_path"].parent for p in packages]
    try:
        _check_output_dir_safe(args.output_dir, input_package_dirs)
    except (OSError, ValueError) as error:
        print(f"输出目录校验失败：{error}")
        return 1

    try:
        fusion = fuse_rankings(packages, output_method_id=args.method_id)
    except ValueError as error:
        print(f"RRF 融合失败：{error}")
        return 1

    output_dir = args.output_dir.resolve()
    display_name = args.display_name or args.method_id.replace("_", " ")

    # 先在临时目录完整生成并通过 validator 自检，成功后再发布到最终目录；
    # 任何失败都不会在最终 output directory 留下半成品。
    with tempfile.TemporaryDirectory(prefix="w5_rrf_") as tmp:
        tmp_dir = Path(tmp)
        ranking_path = tmp_dir / "ranking.csv"
        write_csv_rows(ranking_path, RANKING_FIELDS, fusion["rows"])
        ranking_sha256 = sha256_file(ranking_path)
        duration_seconds = round(time.perf_counter() - started, 6)

        manifest = build_manifest(
            output_method_id=args.method_id,
            display_name=display_name,
            frozen_inputs={
                name: packages[0]["manifest"]["inputs"][name]
                for name in ("candidate_pool", "research_queries")
            },
            ranking_sha256=ranking_sha256,
            input_method_ids=fusion["input_method_ids"],
            input_manifest_sha256=fusion["input_manifest_sha256"],
            input_ranking_sha256=fusion["input_ranking_sha256"],
            input_order_semantic=fusion["input_order_semantic"],
            duration_seconds=duration_seconds,
            git_revision=git_revision,
            git_worktree_clean=git_worktree_clean,
        )
        manifest_path = tmp_dir / "manifest.json"
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

        # 自检通过后在目标同级准备完整 package，再整体 rename 发布。
        try:
            _publish_package(tmp_dir, output_dir)
        except OSError as error:
            print(f"正式 package 发布失败：{error}")
            return 1

    print(f"RRF 融合完成：method_id={result['method_id']}，pairs={len(result['ranking_rows'])}")
    print(f"输出目录：{output_dir}")
    print(f"ranking artifact SHA-256：{ranking_sha256}")
    print(f"输入 method_ids：{', '.join(fusion['input_method_ids'])}")
    print(f"rrf_k：{fusion['rrf_k']}，输入顺序语义：{fusion['input_order_semantic']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
