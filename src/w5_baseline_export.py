"""W5 基线导出与 method ranking package 写出逻辑。

本模块做两件事：

1. 为所有 W5 方法提供统一的 package 写出（ranking.csv + manifest.json），
   冻结输入的 path/hash 直接取自 ``src.w4_benchmark_validation.TRUSTED_W4_V01_INPUTS``
   这一唯一事实来源；
2. 把现有 B0（preliminary_score）与 B1（TF-IDF two-stage）**原样**导出为 W5
   Method Ranking Contract artifact。排序完全复用
   ``src.w4_benchmark_evaluation.rank_query_papers`` 调用的
   ``src.processor.add_preliminary_scores`` 与 ``src.ranking.apply_two_stage_ranking``，
   不重写任何公式、权重或阈值。

注意：artifact 的 ``score`` 列原样记录算法输出；``rank`` 列按 Contract 固定规则
``score desc → pair_id asc`` 生成（与旧 ``old_rank``/``new_rank`` 的引用量/年份
tie-break 不同），这是"不改算法"与 Contract 确定性排序的唯一交集。

生成阶段不读取 benchmark label/judgement/annotation/audit；本模块甚至没有接受
label 的函数参数。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.annotation_tasks import (
    load_research_queries,
    read_csv_rows,
    sha256_file,
    write_csv_rows,
)
from src.bm25_ranking import rank_scored_pairs
from src.processor import PRELIMINARY_SCORE_WEIGHTS
from src.ranking import (
    STAGE1_HIGH_THRESHOLD,
    STAGE1_LEVEL_GATE,
    STAGE1_MEDIUM_THRESHOLD,
    STAGE2_SCORE_WEIGHTS,
)
from src.text_relevance import ABSTRACT_WEIGHT, TITLE_WEIGHT
from src.w4_benchmark_evaluation import (
    capture_experiment_environment,
    rank_query_papers,
)
from src.w4_benchmark_validation import TRUSTED_W4_V01_INPUTS
from src.w5_method_contract import (
    ARTIFACT_TYPE,
    CONTRACT_NAME,
    CONTRACT_VERSION,
    CONTRACT_VERSION_V11,
    RANKING_FIELDS,
    SCHEMA_VERSION,
    SCHEMA_VERSION_V11,
    SCORE_DIRECTION,
    TIE_BREAKING,
)


# 两个基线的稳定 method 标识；family=baseline 表示它们是项目既有基线而非新算法。
BASELINE_METHODS = {
    "preliminary_score_v1": {
        "display_name": "B0 preliminary_score v1",
        "family": "baseline",
    },
    "tfidf_two_stage_v1": {
        "display_name": "B1 TF-IDF two-stage v1",
        "family": "baseline",
    },
}

LABEL_ACCESS_DECLARATION = (
    "Ranking generation did not read benchmark labels, judgements, annotations, "
    "AI audit results or any W5 evaluation metrics."
)
INPUT_VERSIONS = {
    "candidate_pool": "w4_pilot_v0.1",
    "research_queries": "w4_pilot_v0.1",
    "source_sample": "w2_live_query_sample_v1",
}


def capture_generation_environment(project_root: str | Path) -> dict[str, Any]:
    """在写任何输出前采集正式生成环境；dirty 或无法确认时拒绝生成。

    W5 Contract 要求正式 method ranking 在 clean Git 工作树生成并记录完整
    commit SHA。该快照必须在 package 写出之前采集，避免被自身输出污染。
    """
    snapshot = capture_experiment_environment(project_root=project_root)
    revision = snapshot["git_revision"]
    dirty = snapshot["git_dirty"]
    if not revision or dirty is not False:
        raise ValueError(
            "正式 method ranking 必须在 clean Git 工作树生成；"
            f"当前 git_revision={revision!r}，git_dirty={dirty!r}。"
        )
    return {
        "git_revision": revision,
        "git_worktree_clean": True,
        "python": {
            "version": snapshot["python"]["version"],
            "implementation": snapshot["python"]["implementation"],
        },
        "platform": {
            "system": snapshot["platform"]["system"],
            "release": snapshot["platform"]["release"],
            "machine": snapshot["platform"]["machine"],
        },
        # BM25 与 B0/B1 导出只使用 Python 标准库与项目内模块，
        # 没有额外的直接第三方依赖。
        "dependencies": {},
    }


def load_frozen_reference_year(project_root: str | Path) -> int:
    """从冻结 pool manifest 读取项目固定 reference year（当前为 2026）。"""
    anchor = TRUSTED_W4_V01_INPUTS["pool_manifest"]
    manifest_path = Path(project_root) / anchor["path"]
    if not manifest_path.is_file():
        raise ValueError(f"冻结 pool manifest 不存在：{manifest_path}")
    if sha256_file(manifest_path) != anchor["sha256"]:
        raise ValueError("冻结 pool manifest 已发生 hash 漂移。")
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    reference_year = payload.get("reference_year")
    if (
        isinstance(reference_year, bool)
        or not isinstance(reference_year, int)
        or not 1000 <= reference_year <= 9999
    ):
        raise ValueError(
            f"冻结 pool manifest 的 reference_year 非法：{reference_year!r}。"
        )
    return reference_year


def collect_baseline_rankings(
    pool_rows: list[dict[str, str]],
    research_queries: dict[str, Any],
    source_index: dict[str, dict[str, str]],
    reference_year: int,
) -> dict[str, list[dict[str, Any]]]:
    """逐 RQ 复用现有算法计算 B0/B1 排序，并按 Contract 规则生成 rank。

    返回 method_id 到 60 行 ``pair_id/research_query_id/score/rank`` 的映射。
    score 原样取 ``preliminary_score``（B0）与 ``stage2_ranking_score``（B1），
    不做任何舍入或改动。
    """
    pool_by_query: dict[str, list[dict[str, Any]]] = {}
    for row in pool_rows:
        pool_by_query.setdefault(str(row.get("research_query_id") or ""), []).append(
            row
        )

    baseline_rows: list[dict[str, Any]] = []
    two_stage_rows: list[dict[str, Any]] = []
    for query in research_queries["queries"]:
        query_id = str(query["research_query_id"])
        ranking = rank_query_papers(
            pool_by_query.get(query_id, []),
            source_index,
            str(query["ranking_keyword"]),
            reference_year,
        )
        baseline_scored = [
            (str(paper["pair_id"]), float(paper["preliminary_score"]))
            for paper in ranking["ranked_papers"]
        ]
        two_stage_scored = [
            (str(paper["pair_id"]), float(paper["stage2_ranking_score"]))
            for paper in ranking["ranked_papers"]
        ]
        for row in rank_scored_pairs(baseline_scored):
            baseline_rows.append({**row, "research_query_id": query_id})
        for row in rank_scored_pairs(two_stage_scored):
            two_stage_rows.append({**row, "research_query_id": query_id})

    return {
        "preliminary_score_v1": baseline_rows,
        "tfidf_two_stage_v1": two_stage_rows,
    }


def baseline_parameters(method_id: str, reference_year: int) -> dict[str, Any]:
    """如实记录两个基线的全部实际固定参数，不写"默认参数"。"""
    if method_id == "preliminary_score_v1":
        return {
            "scoring_module": "src.processor.add_preliminary_scores",
            "preliminary_score_weights": dict(PRELIMINARY_SCORE_WEIGHTS),
            "reference_year": reference_year,
        }
    if method_id == "tfidf_two_stage_v1":
        return {
            "scoring_module": "src.ranking.apply_two_stage_ranking",
            "tfidf_title_weight": TITLE_WEIGHT,
            "tfidf_abstract_weight": ABSTRACT_WEIGHT,
            "stage1_high_threshold": STAGE1_HIGH_THRESHOLD,
            "stage1_medium_threshold": STAGE1_MEDIUM_THRESHOLD,
            "stage1_level_gate": dict(STAGE1_LEVEL_GATE),
            "stage2_score_weights": dict(STAGE2_SCORE_WEIGHTS),
            "reference_year": reference_year,
        }
    raise ValueError(f"未知 baseline method_id：{method_id!r}。")


def format_score(score: float) -> str:
    """用 repr 全精度写出分数，避免四舍五入制造虚假并列。"""
    value = float(score)
    return repr(value)


def write_w5_package(
    output_dir: str | Path,
    *,
    method_id: str,
    display_name: str,
    family: str,
    parameters: dict[str, Any],
    model: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    environment: dict[str, Any],
    started_at: datetime,
    schema_version: str = SCHEMA_VERSION,
    contract_version: str = CONTRACT_VERSION,
    input_names: tuple[str, ...] = ("candidate_pool", "research_queries"),
) -> dict[str, Any]:
    """写出一个完整的 W5 method ranking package（ranking.csv + manifest.json）。

    参数：
        rows：60 行含 pair_id/research_query_id/score/rank 的字典。
        environment：``capture_generation_environment`` 的返回结果（必须在
            任何输出写出前采集）。
        started_at：本次生成开始的带时区时间；manifest 的 generated_at 取自它，
            duration_seconds 为写出完成时的实际耗时。
    返回：写出的 manifest 字典。
    """
    package_dir = Path(output_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    ranking_path = package_dir / "ranking.csv"
    csv_rows = [
        {
            "pair_id": row["pair_id"],
            "research_query_id": row["research_query_id"],
            "method_id": method_id,
            "score": format_score(row["score"]),
            "rank": str(row["rank"]),
        }
        for row in rows
    ]
    write_csv_rows(ranking_path, list(RANKING_FIELDS), csv_rows)

    finished_at = datetime.now(timezone.utc).astimezone()
    manifest = {
        "schema_version": schema_version,
        "contract_name": CONTRACT_NAME,
        "contract_version": contract_version,
        "artifact_type": ARTIFACT_TYPE,
        "method": {
            "method_id": method_id,
            "display_name": display_name,
            "family": family,
            "parameters": parameters,
            "model": model,
        },
        "inputs": {
            name: {
                "path": TRUSTED_W4_V01_INPUTS[name]["path"],
                "sha256": TRUSTED_W4_V01_INPUTS[name]["sha256"],
                "version": INPUT_VERSIONS[name],
            }
            for name in input_names
        },
        "ranking": {
            "path": "ranking.csv",
            "sha256": sha256_file(ranking_path),
            "row_count": len(csv_rows),
            "score_direction": SCORE_DIRECTION,
            "tie_breaking": list(TIE_BREAKING),
        },
        "generation": {
            "generated_at": started_at.isoformat(timespec="seconds"),
            "duration_seconds": round(
                (finished_at - started_at).total_seconds(), 6
            ),
            **environment,
        },
        "label_access": {
            "benchmark_labels_read": False,
            "declaration": LABEL_ACCESS_DECLARATION,
        },
    }
    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def export_baseline_packages(
    *,
    pool_rows: list[dict[str, str]],
    research_queries: dict[str, Any],
    source_index: dict[str, dict[str, str]],
    reference_year: int,
    output_root: str | Path,
    environment: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """导出 B0/B1 两个 W5 package，返回 method_id 到 manifest 的映射。

    ``environment`` 必须在调用前（即任何输出写出前）采集。计时起点在排序
    计算之前，manifest 的 generation timing 覆盖排序计算与写出全程。
    """
    started = datetime.now(timezone.utc).astimezone()
    rankings = collect_baseline_rankings(
        pool_rows, research_queries, source_index, reference_year
    )
    manifests: dict[str, dict[str, Any]] = {}
    for method_id, rows in rankings.items():
        manifest = write_w5_package(
            Path(output_root) / method_id,
            method_id=method_id,
            display_name=BASELINE_METHODS[method_id]["display_name"],
            family=BASELINE_METHODS[method_id]["family"],
            parameters=baseline_parameters(method_id, reference_year),
            model=None,
            rows=rows,
            environment=environment,
            started_at=started,
            schema_version=SCHEMA_VERSION_V11,
            contract_version=CONTRACT_VERSION_V11,
            input_names=("candidate_pool", "research_queries", "source_sample"),
        )
        manifests[method_id] = manifest
    return manifests


def load_frozen_inputs(project_root: str | Path) -> dict[str, Any]:
    """读取冻结 Candidate Pool 与 Research Query 配置（不含任何 label）。"""
    root = Path(project_root)
    pool_path = root / TRUSTED_W4_V01_INPUTS["candidate_pool"]["path"]
    queries_path = root / TRUSTED_W4_V01_INPUTS["research_queries"]["path"]
    _fields, pool_rows = read_csv_rows(pool_path)
    research_queries = load_research_queries(queries_path)
    return {
        "pool_rows": pool_rows,
        "research_queries": research_queries,
        "reference_year": load_frozen_reference_year(root),
    }
