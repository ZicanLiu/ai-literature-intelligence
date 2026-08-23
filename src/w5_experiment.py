"""Algorithm-neutral W5 multi-method experiment orchestration.

All method artifacts are validated and identity-checked before the approved W4
benchmark package is opened.  This preserves the formal boundary between
label-free method generation and label-joining evaluation.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from src.annotation_tasks import (
    load_research_queries,
    read_csv_rows,
    sha256_file,
    write_csv_rows,
)
from src.w4_benchmark_evaluation import (
    METRIC_KEYS,
    capture_experiment_environment,
    evaluate_contract_ranking,
)
from src.w4_benchmark_validation import validate_benchmark_package
from src.w5_method_contract import validate_method_output


EXPERIMENT_SCHEMA_VERSION = "1.0"
EXPERIMENT_TYPE = "w5_multi_method_query_relevance"
METRIC_FIELDS = [
    "method_id",
    "research_query_id",
    "pair_count",
    "labeled_count",
] + METRIC_KEYS


def run_w5_experiment(
    *,
    method_manifest_paths: Sequence[str | Path],
    benchmark_manifest_path: str | Path,
    output_dir: str | Path,
    project_root: str | Path,
    require_clean_git: bool = True,
) -> dict[str, Any]:
    """Validate arbitrary W5 methods, then evaluate them on one approved package."""
    root = Path(project_root).resolve()
    manifest_paths = [Path(path).resolve() for path in method_manifest_paths]
    if not manifest_paths:
        raise ValueError("至少需要一个 W5 method manifest。")

    # Phase 1: method validation.  No benchmark package or labels are read here.
    method_packages: list[dict[str, Any]] = []
    for path in manifest_paths:
        try:
            package = validate_method_output(path, project_root=root)
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError(f"invalid method manifest {path}: {error}") from error
        method_packages.append(package)
    _validate_method_set(method_packages)

    # Phase 2: only frozen, validated method artifacts may reach label joining.
    benchmark_package = validate_benchmark_package(
        benchmark_manifest_path,
        project_root=root,
        require_approved=True,
    )
    package_paths = benchmark_package["paths"]
    _validate_benchmark_identity(method_packages, benchmark_package)
    _pool_fields, pool_rows = read_csv_rows(package_paths["candidate_pool"])
    research_queries = load_research_queries(package_paths["research_queries"])
    labels = benchmark_package["labels"]

    results: list[dict[str, Any]] = []
    for package in method_packages:
        results.append(
            evaluate_contract_ranking(
                pool_rows=pool_rows,
                labels=labels,
                research_queries=research_queries,
                method_package=package,
            )
        )

    environment = capture_experiment_environment(project_root=root)
    if require_clean_git:
        if environment["git_dirty"] is not False:
            raise ValueError("正式 W5 experiment 必须在 clean Git working tree 运行。")
        if not environment["git_revision"]:
            raise ValueError("无法记录正式 W5 experiment 的 Git revision。")

    target_dir = Path(output_dir).resolve()
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError(f"拒绝覆盖已有 W5 experiment output：{target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = target_dir / "metrics.csv"
    experiment_manifest_path = target_dir / "experiment_manifest.json"
    metric_rows = _build_metric_rows(results, research_queries)
    write_csv_rows(metrics_path, METRIC_FIELDS, metric_rows)

    manifest = _build_experiment_manifest(
        project_root=root,
        method_packages=method_packages,
        benchmark_package=benchmark_package,
        metrics_path=metrics_path,
        environment=environment,
    )
    experiment_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "results": results,
        "metric_rows": metric_rows,
        "metrics_path": metrics_path,
        "experiment_manifest_path": experiment_manifest_path,
        "experiment_manifest": manifest,
        "method_ids": [package["method_id"] for package in method_packages],
    }


def _validate_method_set(method_packages: list[dict[str, Any]]) -> None:
    method_ids = [str(package["method_id"]) for package in method_packages]
    duplicates = sorted(
        method_id for method_id in set(method_ids) if method_ids.count(method_id) > 1
    )
    if duplicates:
        raise ValueError("duplicate method_id：" + ", ".join(duplicates) + "。")
    core_input_names = ("candidate_pool", "research_queries")
    expected_inputs = {
        name: method_packages[0]["manifest"]["inputs"][name]
        for name in core_input_names
    }
    for package in method_packages[1:]:
        package_inputs = {
            name: package["manifest"]["inputs"][name]
            for name in core_input_names
        }
        if package_inputs != expected_inputs:
            raise ValueError("所有 W5 methods 必须使用同一 Candidate Pool / Research Query。")


def _validate_benchmark_identity(
    method_packages: list[dict[str, Any]], benchmark_package: dict[str, Any]
) -> None:
    benchmark_paths = benchmark_package["paths"]
    for package in method_packages:
        if Path(package["candidate_pool_path"]).resolve() != Path(
            benchmark_paths["candidate_pool"]
        ).resolve():
            raise ValueError("method Candidate Pool 与 approved benchmark 不一致。")
        if Path(package["research_queries_path"]).resolve() != Path(
            benchmark_paths["research_queries"]
        ).resolve():
            raise ValueError("method Research Query 与 approved benchmark 不一致。")


def _build_metric_rows(
    results: list[dict[str, Any]], research_queries: dict[str, Any]
) -> list[dict[str, Any]]:
    query_ids = [
        str(query["research_query_id"]) for query in research_queries["queries"]
    ]
    rows: list[dict[str, Any]] = []
    for result in results:
        method_id = result["method_id"]
        total_pairs = 0
        total_labels = 0
        for query_id in query_ids:
            query_result = result["per_query"][query_id]
            total_pairs += int(query_result["pair_count"])
            total_labels += int(query_result["labeled_count"])
            rows.append(
                {
                    "method_id": method_id,
                    "research_query_id": query_id,
                    "pair_count": query_result["pair_count"],
                    "labeled_count": query_result["labeled_count"],
                    **_csv_metrics(query_result["metrics"]),
                }
            )
        rows.append(
            {
                "method_id": method_id,
                "research_query_id": "macro",
                "pair_count": total_pairs,
                "labeled_count": total_labels,
                **_csv_metrics(result["macro"]),
            }
        )
    return rows


def _csv_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: "" if metrics.get(key) is None else metrics[key] for key in METRIC_KEYS}


def _build_experiment_manifest(
    *,
    project_root: Path,
    method_packages: list[dict[str, Any]],
    benchmark_package: dict[str, Any],
    metrics_path: Path,
    environment: dict[str, Any],
) -> dict[str, Any]:
    benchmark_manifest = benchmark_package["manifest"]
    return {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "experiment_type": EXPERIMENT_TYPE,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_revision": environment["git_revision"],
        "git_dirty": environment["git_dirty"],
        "environment": {
            "python": environment["python"],
            "platform": environment["platform"],
            "requirements": environment["requirements"],
            "dependencies": environment["dependencies"],
        },
        "benchmark": {
            "version": benchmark_manifest["benchmark_version"],
            "status": benchmark_manifest["status"],
            "manifest_path": _safe_path(
                Path(benchmark_package["manifest_path"]), project_root
            ),
            "manifest_sha256": benchmark_package["benchmark_hash"],
            "input_set_identity": benchmark_package["input_set_identity"],
            "parent_draft_manifest_sha256": benchmark_manifest["parent_package"][
                "sha256"
            ],
        },
        "methods": [
            {
                "method_id": package["method_id"],
                "family": package["manifest"]["method"]["family"],
                "manifest_path": _safe_path(Path(package["manifest_path"]), project_root),
                "manifest_sha256": package["manifest_sha256"],
                "ranking_path": _safe_path(Path(package["ranking_path"]), project_root),
                "ranking_sha256": package["ranking_sha256"],
            }
            for package in method_packages
        ],
        "evaluation": {
            "target": "query_relevance",
            "candidate_scope": "fixed_60_pair_candidate_pool_reranking",
            "label_scheme": [0, 1, 2],
            "metric_policy": "judged_condensed",
            "metric_keys": list(METRIC_KEYS),
            "method_selection_or_best_claim": False,
        },
        "outputs": [
            {
                "path": _safe_path(metrics_path, project_root),
                "sha256": sha256_file(metrics_path),
                "row_count": len(method_packages) * 4,
            }
        ],
    }


def _safe_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root).as_posix()
    except ValueError:
        return resolved.name
