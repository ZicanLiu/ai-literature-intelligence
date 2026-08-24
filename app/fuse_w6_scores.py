"""W6 标准化分数融合 CLI。

将两个或更多已通过 W6 validator 的 frozen method package，在显式、无标签的
normalization 之后按权重融合，输出符合 W6 Method Ranking Contract 的 package
（ranking.csv + manifest.json）。

generation 只读取 frozen method artifacts 与公共 bundle registry，绝不读取
W6 Dev/Hidden relevance labels、annotation、review、adjudication 或 metrics。
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from src.annotation_tasks import sha256_file, write_csv_rows
from src.w5_method_contract import GIT_REVISION_PATTERN, METHOD_ID_PATTERN, RANKING_FIELDS
from src.w6_contracts import (
    W6_SCHEMA_VERSION,
    canonical_json_sha256,
    load_json_object,
    validate_w6_bootstrap_bundle,
)
from src.w6_method_contract import (
    W6_METHOD_ARTIFACT_TYPE,
    W6_METHOD_CONTRACT_NAME,
    W6_METHOD_CONTRACT_VERSION,
    compute_method_configuration_hash,
    validate_w6_method_package,
)
from src.w6_score_fusion import (
    FIT_SCOPES,
    FUSION_RULE,
    INPUT_ORDER_SEMANTIC,
    NORMALIZATION_STRATEGIES,
    fuse_method_rankings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = (
    PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
)

W6_COMPATIBILITY = {
    "base_contract": "w5_method_ranking",
    "base_ranking_schema_version": "1.0",
    "ranking_fields": RANKING_FIELDS,
    "identity_mapping": {"pair_id": "pool_item_id", "research_query_id": "topic_id"},
    "ranking_unit": "source_record",
}
FUSION_LABEL_DECLARATION = (
    "Score fusion generated from frozen W6 method artifacts only; "
    "no dev/hidden relevance labels, annotations, reviews, adjudications "
    "or evaluation metrics were read."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 >=2 个 W6 frozen method package 经 normalization 后加权融合。"
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=DEFAULT_BUNDLE,
        help="W6 bundle manifest（提供公共 artifact registry 与冻结 Candidate Pool）。",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        required=True,
        help="输入 method manifest（可多次传入，至少两个）。",
    )
    parser.add_argument("--method-id", default=None, help="输出 hybrid artifact 的 method_id。")
    parser.add_argument("--display-name", default=None, help="输出显示名，默认由 method-id 生成。")
    parser.add_argument(
        "--normalization",
        choices=sorted(NORMALIZATION_STRATEGIES),
        default=None,
        help="score normalization 策略。",
    )
    parser.add_argument(
        "--fit-scope",
        choices=sorted(FIT_SCOPES),
        default=None,
        help="normalization 拟合范围（per_topic / global_frozen_pool）。",
    )
    parser.add_argument(
        "--weight",
        action="append",
        default=None,
        metavar="METHOD_ID=VALUE",
        help="单个输入 method 的权重（可多次传入；缺省时全部等权 1/n）。",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="冻结的 fusion 配置 JSON（与 --method-id/--normalization/--fit-scope/--weight 互斥）。",
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


def _validate_method_id(method_id: str) -> None:
    if (
        not isinstance(method_id, str)
        or method_id != method_id.strip()
        or not METHOD_ID_PATTERN.fullmatch(method_id)
    ):
        raise ValueError(
            "method-id 必须是稳定的小写机器标识（a-z、0-9、点、下划线或连字符）。"
        )


def _parse_weights(entries: list[str] | None) -> dict[str, float] | None:
    if entries is None:
        return None
    weights: dict[str, float] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"--weight 必须是 METHOD_ID=VALUE 形式：{entry}。")
        method_id, _, raw_value = entry.partition("=")
        method_id = method_id.strip()
        if not METHOD_ID_PATTERN.fullmatch(method_id):
            raise ValueError(f"--weight 的 method_id 非法：{method_id}。")
        try:
            value = float(raw_value)
        except ValueError as error:
            raise ValueError(f"--weight 的数值非法：{entry}。") from error
        if not math.isfinite(value):
            raise ValueError(f"--weight 必须有限：{entry}。")
        if method_id in weights:
            raise ValueError(f"--weight 重复：{method_id}。")
        weights[method_id] = value
    return weights


def load_fusion_config(config_path: Path) -> dict:
    """加载并校验冻结的 fusion 配置（含 configuration hash 复核）。"""
    config = load_json_object(config_path, label="fusion config")
    expected = {
        "config_id",
        "version",
        "status",
        "frozen_at",
        "output",
        "input_methods",
        "normalization",
        "weights",
        "configuration_sha256",
    }
    if set(config) != expected:
        raise ValueError(
            f"fusion config 字段不符合约定：missing={sorted(expected - set(config))}, "
            f"extra={sorted(set(config) - expected)}。"
        )
    if config["status"] != "frozen":
        raise ValueError("fusion config 必须处于 frozen 状态。")
    core = {
        "config_id": config["config_id"],
        "version": config["version"],
        "input_methods": config["input_methods"],
        "normalization": config["normalization"],
        "weights": config["weights"],
    }
    if config["configuration_sha256"] != canonical_json_sha256(core):
        raise ValueError("fusion config configuration_sha256 mismatch。")
    output = config["output"]
    if set(output) != {"method_id", "display_name"}:
        raise ValueError("fusion config output 必须只含 method_id/display_name。")
    _validate_method_id(output["method_id"])
    normalization = config["normalization"]
    if set(normalization) != {"strategy", "fit_scope"}:
        raise ValueError("fusion config normalization 必须只含 strategy/fit_scope。")
    if normalization["strategy"] not in NORMALIZATION_STRATEGIES:
        raise ValueError("fusion config normalization.strategy 非法。")
    if normalization["fit_scope"] not in FIT_SCOPES:
        raise ValueError("fusion config normalization.fit_scope 非法。")
    if not isinstance(config["input_methods"], list) or len(config["input_methods"]) < 2:
        raise ValueError("fusion config input_methods 至少需要两个 method_id。")
    if set(config["weights"]) != set(config["input_methods"]):
        raise ValueError("fusion config weights 必须精确覆盖 input_methods。")
    return config


def build_manifest(
    *,
    output_method_id: str,
    display_name: str,
    frozen_inputs: dict,
    ranking_sha256: str,
    row_count: int,
    fusion: dict,
    method_inputs: list[dict],
    git_revision: str,
) -> dict:
    now = datetime.now().astimezone().isoformat()
    manifest = {
        "schema_version": W6_SCHEMA_VERSION,
        "contract_name": W6_METHOD_CONTRACT_NAME,
        "contract_version": W6_METHOD_CONTRACT_VERSION,
        "artifact_type": W6_METHOD_ARTIFACT_TYPE,
        "artifact_id": f"{output_method_id}_artifact",
        "is_fixture": False,
        "status": "frozen",
        "compatibility": W6_COMPATIBILITY,
        "method": {
            "method_id": output_method_id,
            "display_name": display_name,
            "family": "hybrid",
            "parameters": {
                "weights": fusion["weights"],
                "fusion_rule": FUSION_RULE,
                "score_basis": "raw_score",
                "input_order_semantic": INPUT_ORDER_SEMANTIC,
            },
            "model": None,
        },
        "inputs": frozen_inputs,
        "auxiliary_inputs": {},
        "method_inputs": method_inputs,
        "score_processing": {
            "output_score_semantics": "higher_is_better",
            "normalization": {
                "strategy": fusion["strategy"],
                "parameters": fusion["normalization_parameters"],
                "fit_scope": fusion["fit_scope"],
                "label_access": False,
            },
        },
        "ranking": {
            "path": "ranking.csv",
            "sha256": ranking_sha256,
            "row_count": row_count,
            "score_direction": "higher_is_better",
            "tie_breaking": ["score_desc", "pair_id_asc"],
        },
        "freeze": {
            "frozen_at": now,
            "configuration_sha256": None,
            "evaluation_started_at": None,
        },
        "generation": {
            "generated_at": now,
            "git_revision": git_revision,
            "git_worktree_clean": True,
            "dependencies": {},
            "deterministic_seed": None,
        },
        "label_access": {
            "relevance_labels_read": False,
            "hidden_test_labels_read": False,
            "declaration": FUSION_LABEL_DECLARATION,
        },
    }
    manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(manifest)
    return manifest


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

    # 预检 1：配置来源（--config 与散参互斥）与 method_id 格式。
    try:
        if args.config is not None:
            if (
                args.method_id is not None
                or args.normalization is not None
                or args.fit_scope is not None
                or args.weight is not None
            ):
                raise ValueError(
                    "--config 与 --method-id/--normalization/--fit-scope/--weight 互斥。"
                )
            config = load_fusion_config(args.config)
            method_id = config["output"]["method_id"]
            display_name = config["output"]["display_name"]
            strategy = config["normalization"]["strategy"]
            fit_scope = config["normalization"]["fit_scope"]
            weights = dict(config["weights"])
            expected_input_methods = list(config["input_methods"])
        else:
            method_id = args.method_id
            if method_id is None:
                raise ValueError("缺少 --method-id（或使用 --config）。")
            display_name = args.display_name or args.method_id.replace("_", " ")
            strategy = args.normalization or "z_score"
            fit_scope = args.fit_scope or "per_topic"
            weights = _parse_weights(args.weight)
            expected_input_methods = None
        _validate_method_id(method_id)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输出参数校验失败：{error}")
        return 1

    # 预检 2：加载 bundle（公共 registry + 冻结 pool），再逐个校验输入 package。
    try:
        bundle = validate_w6_bootstrap_bundle(args.bundle)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W6 bundle 校验失败：{error}")
        return 1
    registry = bundle["registry"]
    pool_members = bundle["pool_members"]

    packages = []
    known_method_packages = dict(bundle["method_packages"])
    try:
        for manifest_path in args.manifest:
            package = validate_w6_method_package(
                manifest_path,
                artifact_registry=registry,
                pool_members=pool_members,
                known_method_packages=known_method_packages,
            )
            packages.append(package)
            known_method_packages[package["artifact_id"]] = package
    except (OSError, UnicodeError, ValueError) as error:
        print(f"输入 method artifact 校验失败：{error}")
        return 1

    input_method_ids = [package["method_id"] for package in packages]
    if expected_input_methods is not None and sorted(input_method_ids) != sorted(
        expected_input_methods
    ):
        print(
            "错误：输入 method 与冻结 config 不一致："
            f"config={sorted(expected_input_methods)}, actual={sorted(input_method_ids)}。"
        )
        return 1
    if weights is None:
        equal = 1.0 / len(packages)
        weights = {method_id_item: equal for method_id_item in input_method_ids}

    # 预检 3：Git clean 状态与完整 revision（写文件前提前失败）。
    git_revision = _git_revision()
    if not _git_worktree_clean():
        print("错误：正式 method ranking 必须在 clean Git 工作树生成。")
        return 1
    if not GIT_REVISION_PATTERN.fullmatch(git_revision):
        print("错误：无法确认完整 40 位 Git commit SHA。")
        return 1

    # 预检 4：输出目录安全（不与输入 package 重合、不覆盖非空目标）。
    input_package_dirs = [p["manifest_path"].parent for p in packages]
    try:
        _check_output_dir_safe(args.output_dir, input_package_dirs)
    except (OSError, ValueError) as error:
        print(f"输出目录校验失败：{error}")
        return 1

    try:
        fusion = fuse_method_rankings(
            packages,
            output_method_id=method_id,
            strategy=strategy,
            fit_scope=fit_scope,
            weights=weights,
        )
    except ValueError as error:
        print(f"score fusion 失败：{error}")
        return 1

    output_dir = args.output_dir.resolve()

    # 先在临时目录完整生成并通过 validator 自检，成功后再发布到最终目录；
    # 任何失败都不会在最终 output directory 留下半成品。
    with tempfile.TemporaryDirectory(prefix="w6_fusion_") as tmp:
        tmp_dir = Path(tmp)
        ranking_path = tmp_dir / "ranking.csv"
        write_csv_rows(ranking_path, RANKING_FIELDS, fusion["rows"])
        ranking_sha256 = sha256_file(ranking_path)

        method_inputs = [
            {
                "method_id": package["method_id"],
                "manifest_artifact_id": package["artifact_id"],
                "manifest_sha256": package["manifest_sha256"],
                "ranking_sha256": package["ranking_sha256"],
                "uses_raw_score": True,
                "uses_rank": False,
            }
            for package in packages
        ]
        manifest = build_manifest(
            output_method_id=method_id,
            display_name=display_name,
            frozen_inputs={
                name: packages[0]["input_references"][name]
                for name in ("topic_set", "candidate_pool")
            },
            ranking_sha256=ranking_sha256,
            row_count=len(fusion["rows"]),
            fusion=fusion,
            method_inputs=method_inputs,
            git_revision=git_revision,
        )
        manifest_path = tmp_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # 输出自检：重新用 W6 validator 校验生成的 package。
        try:
            result = validate_w6_method_package(
                manifest_path,
                artifact_registry=registry,
                pool_members=pool_members,
                known_method_packages=known_method_packages,
            )
        except (OSError, UnicodeError, ValueError) as error:
            print(f"输出自检失败：{error}")
            return 1

        # 自检通过后在目标同级准备完整 package，再整体 rename 发布。
        try:
            _publish_package(tmp_dir, output_dir)
        except OSError as error:
            print(f"正式 package 发布失败：{error}")
            return 1

    duration_seconds = round(time.perf_counter() - started, 6)
    print(
        f"score fusion 完成：method_id={result['method_id']}，items={len(result['ranking_rows'])}"
    )
    print(f"输出目录：{output_dir}")
    print(f"ranking artifact SHA-256：{ranking_sha256}")
    print(f"输入 method_ids：{', '.join(fusion['input_method_ids'])}")
    print(
        f"normalization：{fusion['strategy']}（fit_scope={fusion['fit_scope']}），"
        f"weights={fusion['weights']}，耗时 {duration_seconds}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
