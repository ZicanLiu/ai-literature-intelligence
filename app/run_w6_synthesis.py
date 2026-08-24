"""W6 evidence-grounded synthesis CLI（原型）。

从一个已验证、冻结的 W6 method ranking 出发：

    top-N rank-ordered selection → evidence 抽取 → deterministic fake backend
    → structured claims → contract 校验 → mini review + unsupported claim audit

全程离线；不读取 `.env`，不调用真实 LLM，不读取任何 relevance label。
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
from src.w5_method_contract import GIT_REVISION_PATTERN
from src.w6_contracts import load_json_object, validate_w6_bootstrap_bundle
from src.w6_method_contract import validate_w6_method_package
from src.w6_synthesis_contract import (
    load_and_validate_evidence_units,
    validate_structured_synthesis,
    validate_synthesis_input,
)
from src.w6_synthesis_pipeline import (
    DeterministicFakeBackend,
    build_evidence_units,
    build_synthesis_input,
    generate_structured_synthesis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = (
    PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
)
DEFAULT_TOPIC_ID = "w6_fixture_topic_denoising"
BACKENDS = {"fake": DeterministicFakeBackend}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从冻结 W6 ranking 生成 evidence-grounded structured synthesis 与 mini review。"
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=DEFAULT_BUNDLE,
        help="W6 bundle manifest（提供公共 artifact registry 与冻结 Candidate Pool）。",
    )
    parser.add_argument(
        "--method-manifest",
        type=Path,
        default=None,
        help="已冻结 method package 的 manifest（默认使用 bundle 的 fusion fixture）。",
    )
    parser.add_argument("--topic-id", default=DEFAULT_TOPIC_ID, help="目标 topic_id。")
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="按冻结 ranking 顺序选取的论文数（默认 3）。",
    )
    parser.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        default="fake",
        help="synthesis backend（当前只有离线 deterministic fake）。",
    )
    parser.add_argument(
        "--artifact-prefix",
        default="w6_synthesis_demo",
        help="输出 artifact_id 前缀（小写机器标识）。",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help=(
            "输出目录（evidence_units.json / synthesis_input.json / "
            "structured_synthesis.json / mini_review.md / unsupported_claim_audit.json）。"
        ),
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


def _write_json(path: Path, payload: dict) -> str:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return sha256_file(path)


def _publish_outputs(source_dir: Path, output_dir: Path, filenames: list[str]) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.publish_", dir=output_dir.parent
    ) as publish_tmp:
        publish_dir = Path(publish_tmp)
        for name in filenames:
            shutil.copy2(source_dir / name, publish_dir / name)
        if output_dir.exists():
            output_dir.rmdir()
        publish_dir.replace(output_dir)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 预检 1：Git revision（provenance 需要完整 40 位 SHA；离线测试可 patch）。
    git_revision = _git_revision()
    if not GIT_REVISION_PATTERN.fullmatch(git_revision):
        print("错误：无法确认完整 40 位 Git commit SHA。")
        return 1

    # 预检 2：输出目录安全（不与 method package 重合、不覆盖非空目标）。
    output_dir = args.output_dir.resolve()
    if args.method_manifest is not None:
        package_dir = args.method_manifest.resolve().parent
        if output_dir == package_dir or package_dir.is_relative_to(output_dir):
            print(f"错误：输出目录与输入 method package 重合：{package_dir}")
            return 1
    if output_dir.exists() and any(output_dir.iterdir()):
        print(f"错误：输出目录已存在且非空，拒绝覆盖：{output_dir}")
        return 1

    # 加载并验证 bundle（公共 registry、冻结 pool、records、canonical、method packages）。
    try:
        bundle = validate_w6_bootstrap_bundle(args.bundle)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W6 bundle 校验失败：{error}")
        return 1
    registry = dict(bundle["registry"])
    topics = bundle["topics"]
    pool_members = bundle["pool_members"]
    records = bundle["records"]
    canonical = bundle["canonical"]
    payloads = bundle["payloads"]
    method_packages = dict(bundle["method_packages"])

    if args.topic_id not in topics:
        print(f"错误：未知 topic_id：{args.topic_id}。")
        return 1

    # 校验输入 method package（必须 frozen 且 identity 与 registry 一致）。
    manifest_path = args.method_manifest or bundle["paths"]["method_fusion_manifest"]
    try:
        package = validate_w6_method_package(
            manifest_path,
            artifact_registry=registry,
            pool_members=pool_members,
            known_method_packages=method_packages,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输入 method artifact 校验失败：{error}")
        return 1
    method_packages[package["artifact_id"]] = package

    created_at = datetime.now().astimezone().isoformat()
    prefix = args.artifact_prefix

    # 在临时目录完整生成并逐层通过 contract 校验，成功后再发布到最终目录。
    with tempfile.TemporaryDirectory(prefix="w6_synthesis_") as tmp:
        tmp_dir = Path(tmp)

        # 1) rank-ordered selection（与 build_synthesis_input 内部选择保持同一确定性逻辑）。
        topic_rows = [
            row
            for row in package["ranking_rows"]
            if row["research_query_id"] == args.topic_id
        ]
        topic_rows.sort(key=lambda row: row["rank"])
        selected = [row["pair_id"] for row in topic_rows[: args.top_n]]
        if not selected:
            print(f"错误：topic {args.topic_id} 在 ranked list 中没有候选。")
            return 1
        selected_record_ids = [pool_members[item]["record_id"] for item in selected]

        # 2) evidence 抽取（只取 abstract 短 snippet / structured metadata）。
        evidence_payload = build_evidence_units(
            records,
            canonical,
            selected_record_ids,
            artifact_id=f"{prefix}_evidence",
            created_at=created_at,
            git_revision=git_revision,
        )
        evidence_path = tmp_dir / "evidence_units.json"
        evidence_sha = _write_json(evidence_path, evidence_payload)
        registry[f"{prefix}_evidence"] = {
            "artifact_id": f"{prefix}_evidence",
            "sha256": evidence_sha,
        }
        try:
            evidence = load_and_validate_evidence_units(
                evidence_path, records=records, canonical=canonical
            )
        except (OSError, UnicodeError, ValueError) as error:
            print(f"evidence units 校验失败：{error}")
            return 1

        # 3) synthesis input（绑定 frozen topic/pool/ranking/evidence identity）。
        references = {
            "topic_artifact": {
                "artifact_id": payloads["topic_set"]["artifact_id"],
                "sha256": registry[payloads["topic_set"]["artifact_id"]]["sha256"],
            },
            "paper_metadata": {
                "artifact_id": payloads["source_records"]["artifact_id"],
                "sha256": registry[payloads["source_records"]["artifact_id"]]["sha256"],
            },
            "source_provenance": {
                "artifact_id": payloads["retrieval_provenance"]["artifact_id"],
                "sha256": registry[payloads["retrieval_provenance"]["artifact_id"]]["sha256"],
            },
            "evidence_units": {
                "artifact_id": f"{prefix}_evidence",
                "sha256": evidence_sha,
            },
        }
        try:
            input_payload = build_synthesis_input(
                topic_id=args.topic_id,
                topics=topics,
                package=package,
                top_n=args.top_n,
                references=references,
                artifact_id=f"{prefix}_input",
                synthesis_input_id=f"{prefix}_input_v1",
                created_at=created_at,
                git_revision=git_revision,
            )
        except ValueError as error:
            print(f"synthesis input 构造失败：{error}")
            return 1
        input_path = tmp_dir / "synthesis_input.json"
        input_sha = _write_json(input_path, input_payload)
        registry[f"{prefix}_input"] = {
            "artifact_id": f"{prefix}_input",
            "sha256": input_sha,
        }
        try:
            synthesis_input = validate_synthesis_input(
                input_payload,
                registry=registry,
                topics=topics,
                pool_members=pool_members,
                method_packages=method_packages,
                records=records,
                canonical=canonical,
                evidence=evidence,
                expected_artifact_ids={
                    "topic_set": payloads["topic_set"]["artifact_id"],
                    "source_records": payloads["source_records"]["artifact_id"],
                    "retrieval_provenance": payloads["retrieval_provenance"]["artifact_id"],
                    "evidence_units": f"{prefix}_evidence",
                },
            )
        except ValueError as error:
            print(f"synthesis input 校验失败：{error}")
            return 1

        # 4) backend 生成 structured claims 并渲染 mini review（先过 contract validator）。
        backend = BACKENDS[args.backend]()
        try:
            result = generate_structured_synthesis(
                backend,
                synthesis_input=synthesis_input,
                evidence=evidence,
                canonical=canonical,
                artifact_id=f"{prefix}_structured",
                synthesis_id=f"{prefix}_synthesis_v1",
                created_at=created_at,
                git_revision=git_revision,
            )
        except ValueError as error:
            print(f"structured synthesis 生成失败：{error}")
            return 1

        structured_path = tmp_dir / "structured_synthesis.json"
        _write_json(structured_path, result["payload"])
        review_path = tmp_dir / "mini_review.md"
        review_path.write_text(result["rendered_review"] + "\n", encoding="utf-8")
        audit_path = tmp_dir / "unsupported_claim_audit.json"
        _write_json(audit_path, result["audit"])

        # 5) 输出自检：从磁盘回读并重新通过 contract validator。
        try:
            reloaded = load_json_object(structured_path, label="structured synthesis")
            validate_structured_synthesis(
                reloaded,
                synthesis_input=synthesis_input,
                evidence=evidence,
                canonical=canonical,
            )
        except (OSError, UnicodeError, ValueError) as error:
            print(f"输出自检失败：{error}")
            return 1

        try:
            _publish_outputs(
                tmp_dir,
                output_dir,
                [
                    "evidence_units.json",
                    "synthesis_input.json",
                    "structured_synthesis.json",
                    "mini_review.md",
                    "unsupported_claim_audit.json",
                ],
            )
        except OSError as error:
            print(f"输出发布失败：{error}")
            return 1

    audit = result["audit"]
    print(
        f"synthesis 完成：topic={args.topic_id}，selected={len(selected)} 篇，"
        f"claims={audit['claim_count']}（supported={len(audit['supported_claim_ids'])}，"
        f"partially_supported={len(audit['partially_supported_claim_ids'])}，"
        f"unsupported={len(audit['unsupported_claim_ids'])}）"
    )
    print(f"输出目录：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
