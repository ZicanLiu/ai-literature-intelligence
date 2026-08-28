"""Thin CLI: canonicalize W6 source records, build the post-canonical pool and run
the pool bias audit from the public Bootstrap bundle.

Business logic lives in ``src.w6_canonicalization`` and ``src.w6_pool_audit``. This
module only wires the *label-free* task-scoped inputs, stages outputs in a temporary
directory, hashes the actual written files, self-validates, then atomically
publishes. It never opens downstream (annotation / review / benchmark / synthesis)
artifacts and never writes into the frozen input tree.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from src.annotation_tasks import sha256_file
from src.w6_canonicalization import (
    build_canonical_entities,
    build_post_canonical_pool,
)
from src.w6_contracts import (
    load_canonicalization_inputs,
    validate_candidate_pool,
    validate_canonical_entities,
)
from src.w6_pool_audit import audit_pool_bias


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = (
    PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="W6 candidate canonicalization + post-canonical pool + bias audit。"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_BUNDLE,
        help="W6 Bootstrap bundle manifest（默认公共 fixture）。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="输出目录（canonical_entities.json / post_canonical_pool.json / pool_bias_audit.json）。",
    )
    parser.add_argument(
        "--canonical-artifact-id",
        default=None,
        help="canonical entities artifact_id（默认 w6_canonical_entities_v1）。",
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


def _check_output_dir_safe(output_dir: Path, input_root: Path) -> None:
    resolved = output_dir.resolve()
    root = input_root.resolve()
    if resolved == root or resolved.is_relative_to(root) or root.is_relative_to(resolved):
        raise ValueError(f"输出目录与冻结输入树重合，禁止覆盖：{root}")
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError(f"输出目录已存在且非空，拒绝覆盖：{resolved}")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inputs = load_canonicalization_inputs(args.manifest)
    records = inputs["records"]
    retrieval = inputs["retrieval"]
    topics = inputs["topics"]
    pre_pool_payload = inputs["precanonical_candidate_pool"]
    input_root = inputs["bundle_dir"]

    git_revision = _git_revision()
    if not git_revision:
        print("错误：无法确认完整 Git commit SHA。")
        return 1
    created_at = datetime.now().astimezone().isoformat()

    output_dir = args.output_dir.resolve()
    try:
        _check_output_dir_safe(output_dir, input_root)
    except ValueError as error:
        print(f"输出目录校验失败：{error}")
        return 1

    canonical_artifact_id = args.canonical_artifact_id or "w6_canonical_entities_v1"
    canonical_payload = build_canonical_entities(
        records,
        artifact_id=canonical_artifact_id,
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=True,
    )

    with tempfile.TemporaryDirectory(prefix="w6_canonicalize_") as tmp:
        tmp_dir = Path(tmp)
        canonical_path = tmp_dir / "canonical_entities.json"
        _write_json(canonical_path, canonical_payload)
        canonical_sha256 = sha256_file(canonical_path)

        post_pool_payload = build_post_canonical_pool(
            pre_pool_payload,
            canonical_payload,
            artifact_id="w6_post_canonical_pool_v1",
            canonical_artifact_id=canonical_artifact_id,
            canonical_sha256=canonical_sha256,
            created_at=created_at,
            git_revision=git_revision,
            is_fixture=True,
        )
        post_pool_path = tmp_dir / "post_canonical_pool.json"
        _write_json(post_pool_path, post_pool_payload)
        post_pool_sha256 = sha256_file(post_pool_path)

        # 自检：生成物必须通过 W6 contract validator。
        canonical_result = validate_canonical_entities(
            canonical_payload, records=records, retrieval=retrieval
        )
        registry = dict(inputs["registry"])
        registry[canonical_artifact_id] = {
            "artifact_id": canonical_artifact_id,
            "sha256": canonical_sha256,
        }
        pool_members = validate_candidate_pool(
            post_pool_payload,
            topics=topics,
            records=records,
            retrieval=retrieval,
            registry=registry,
            canonical=canonical_result,
        )

        audit = audit_pool_bias(
            retrieval=retrieval,
            post_pool_payload=post_pool_payload,
            canonical=canonical_result,
            artifact_id="w6_pool_bias_audit_v1",
            pool_reference={
                "artifact_id": post_pool_payload["artifact_id"],
                "sha256": post_pool_sha256,
            },
            canonical_reference={
                "artifact_id": canonical_artifact_id,
                "sha256": canonical_sha256,
            },
            created_at=created_at,
            git_revision=git_revision,
            is_fixture=True,
        )
        audit_path = tmp_dir / "pool_bias_audit.json"
        _write_json(audit_path, audit)

        # 自检通过后再原子发布到最终 output directory。
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "canonical_entities.json",
            "post_canonical_pool.json",
            "pool_bias_audit.json",
        ):
            shutil.copy2(tmp_dir / name, output_dir / name)

    print(
        "W6 canonicalization PASSED: "
        f"entities={len(canonical_result['entities'])}, "
        f"records={len(records)}, "
        f"pool_items={len(pool_members)}, "
        f"suspected={len(canonical_result['relationships'])}."
    )
    print(f"输出目录：{output_dir}")
    for name in (
        "canonical_entities.json",
        "post_canonical_pool.json",
        "pool_bias_audit.json",
    ):
        print(f"  {name}  sha256={sha256_file(output_dir / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
