"""Thin CLI: canonicalize W6 source records, build the post-canonical pool and run
the pool bias audit from the public Bootstrap bundle.

Business logic lives in ``src.w6_canonicalization`` and ``src.w6_pool_audit``; this
module only wires inputs, writes outputs and self-validates the generated package.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from src.annotation_tasks import sha256_file
from src.w6_canonicalization import (
    build_canonical_entities,
    build_post_canonical_pool,
)
from src.w6_contracts import (
    canonical_json_sha256,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_w6_bootstrap_bundle,
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
        help="canonical entities artifact_id（默认由 inputs 派生）。",
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bundle = validate_w6_bootstrap_bundle(args.manifest)
    records = bundle["records"]
    retrieval = bundle["retrieval"]
    topics = bundle["topics"]
    pre_pool_payload = bundle["payloads"]["precanonical_candidate_pool"]

    git_revision = _git_revision()
    if not git_revision:
        print("错误：无法确认完整 Git commit SHA。")
        return 1
    created_at = datetime.now().astimezone().isoformat()

    canonical_artifact_id = args.canonical_artifact_id or "w6_canonical_entities_v1"
    canonical_payload = build_canonical_entities(
        records,
        artifact_id=canonical_artifact_id,
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=True,
    )
    canonical_sha256 = canonical_json_sha256(canonical_payload)

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

    # 自检：生成物必须通过 W6 contract validator。
    canonical_result = validate_canonical_entities(
        canonical_payload, records=records, retrieval=retrieval
    )
    registry = dict(bundle["registry"])
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
        pool_members=pool_members,
        canonical=canonical_result,
        included_run_ids=post_pool_payload["policy"]["included_retrieval_run_ids"],
        artifact_id="w6_pool_bias_audit_v1",
        pool_reference={
            "artifact_id": post_pool_payload["artifact_id"],
            "sha256": canonical_json_sha256(post_pool_payload),
        },
        canonical_reference={
            "artifact_id": canonical_artifact_id,
            "sha256": canonical_sha256,
        },
        created_at=created_at,
        git_revision=git_revision,
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "canonical_entities.json": canonical_payload,
        "post_canonical_pool.json": post_pool_payload,
        "pool_bias_audit.json": audit,
    }
    for name, payload in files.items():
        path = output_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(
        "W6 canonicalization PASSED: "
        f"entities={len(canonical_result['entities'])}, "
        f"records={len(records)}, "
        f"pool_items={len(pool_members)}, "
        f"suspected={len(canonical_result['relationships'])}."
    )
    print(f"输出目录：{output_dir}")
    for name in files:
        print(f"  {name}  sha256={sha256_file(output_dir / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
