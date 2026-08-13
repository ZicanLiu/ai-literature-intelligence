"""W4 Pilot Benchmark 的 Baseline vs Two-stage 统一评价与 Error Case 适配器。

本模块为第四周 Pilot Benchmark 准备评价入口：未来输入是「最终 adjudicated
benchmark labels + Candidate Pool + 现有 Baseline / Two-stage ranking」，输出统一
实验结果和 error case 底稿。

设计原则：

1. 不实现任何新排序算法。baseline（B0 = preliminary_score）与 two-stage（B1 =
   TF-IDF 两阶段）完全复用 ``src.processor`` 与 ``src.ranking``；
2. 指标复用 ``src.evaluation`` 的 judged（condensed）口径函数，只保留 Issue 要求
   的核心指标，不额外堆指标；
3. 严格按 Research Question 分开评价（每个 RQ 的 20 个 query-paper pair 在候选
   集合内部重新计算排名），最后给出 macro average；
4. error case 只给类型代码，不自动写「为什么错」的最终结论，原因分析保留给人工。

标签口径：W4 Query Relevance 使用 ``2/1/0/?``，其中 ``?``（待讨论）与空标签都
没有确定等级，评价时按未标注处理，不能当作不相关。这与 ``src.evaluation`` 对
「待讨论」的处理保持一致。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.annotation_tasks import read_csv_rows
from src.evaluation import (
    count_irrelevant_in_top_k,
    filter_grades_to_ranked,
    judged_count_at_k,
    judged_ndcg_at_k,
    judged_precision_at_k,
)
from src.processor import add_preliminary_scores, clean_papers
from src.ranking import apply_two_stage_ranking


# W4 数字标签到数值等级的映射：高度相关 = 2，部分相关 = 1，不相关 = 0。
W4_LABEL_TO_GRADE = {
    "2": 2,
    "1": 1,
    "0": 0,
}

# 待讨论与空标签都没有确定等级，评价时按未标注处理。
W4_UNGRADED_LABELS = {"?", ""}

# 评价截断位置。只保留 Issue 要求的 K，不额外增加指标数量。
METRIC_KS = (5, 10)

# 指标固定输出顺序（用于 CSV 表头与 macro average）。
METRIC_KEYS = [
    "ndcg_at_5",
    "ndcg_at_10",
    "precision_at_5",
    "precision_at_10",
    "coverage_at_5",
    "coverage_at_10",
    "irrelevant_top_5",
    "irrelevant_top_10",
]

# baseline 与 two-stage 的稳定方法标识与说明。
METHOD_NAMES = {
    "baseline": "B0 preliminary_score",
    "two_stage": "B1 TF-IDF two-stage",
}

# error case 输出列顺序（Issue 第八节约定）。
ERROR_CASE_FIELDS = [
    "pair_id",
    "research_query_id",
    "human_label",
    "baseline_rank",
    "two_stage_rank",
    "rank_delta",
    "title",
    "error_type",
]

# candidate pool 参与评价所需的必要字段。
REQUIRED_POOL_FIELDS = {"pair_id", "research_query_id", "openalex_id"}

# error case 候选类型的判定阈值：Top-K 与「明显排名变化」的位次差。
# 这些是透明的启发式阈值，只用于标记候选案例，不构成任何结论。
ERROR_TOP_K = 5
ERROR_RANK_DELTA_THRESHOLD = 5


def parse_w4_label(label: object) -> int | None:
    """把 W4 Query Relevance 标签解析成数值等级。

    参数：
        label：标签原文，通常是 "2"、"1"、"0"、"?" 或 None/空字符串。
    返回：2、1、0 或 None；None 表示该 pair 没有可用等级（未标注或待讨论）。
    异常或特殊情况：标签不在 W4 允许取值内时抛出 ValueError，非法标签必须报错，
        不能悄悄当作不相关或未标注。
    """
    if label is None:
        return None
    text = str(label).strip()
    if text in W4_UNGRADED_LABELS:
        return None
    if text in W4_LABEL_TO_GRADE:
        return W4_LABEL_TO_GRADE[text]
    raise ValueError(
        f"非法 W4 相关等级标签：{text!r}。允许的取值：2/1/0/? 或空。"
    )


def load_benchmark_labels(label_file: Path) -> dict[str, str]:
    """读取 adjudicated benchmark labels，返回 pair_id 到标签原文的字典。

    参数：
        label_file：包含 pair_id 和 label 两列的 CSV 路径。个人标注 CSV 同样满足
            该契约，因此也能直接作为输入（覆盖率由 coverage 指标真实反映）。
    返回：pair_id 到标签原文的字典；label 为空的行按未标注跳过。
    异常或特殊情况：文件不存在或缺少必需列时抛出 ValueError。
    """
    label_path = Path(label_file)
    if not label_path.is_file():
        raise ValueError(f"标签文件不存在：{label_path}")
    _fields, rows = read_csv_rows(label_path)
    if not {"pair_id", "label"} <= set(_fields):
        raise ValueError("benchmark labels CSV 必须包含 pair_id 和 label 两列。")
    labels: dict[str, str] = {}
    for row in rows:
        pair_id = (row.get("pair_id") or "").strip()
        label = (row.get("label") or "").strip()
        if pair_id and label:
            labels[pair_id] = label
    return labels


def build_source_index(source_file: Path) -> dict[str, dict[str, str]]:
    """把 W2 live 样例按 openalex_id 建索引，用于补全 candidate pool 的排序字段。

    candidate pool 只保留展示字段，preliminary_score 与 two-stage 所需的
    cited_by_count / authors / source_name 等必须从既有来源样例补回，避免重算
    baseline 时缺失输入字段。
    """
    source_path = Path(source_file)
    if not source_path.is_file():
        raise ValueError(f"来源样例 CSV 不存在：{source_path}")
    fields, rows = read_csv_rows(source_path)
    required = {
        "openalex_id",
        "title",
        "authors",
        "publication_year",
        "doi",
        "abstract",
        "cited_by_count",
        "source_name",
        "landing_page_url",
    }
    missing = required.difference(fields)
    if missing:
        raise ValueError("来源样例缺少字段：" + ", ".join(sorted(missing)))
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        openalex_id = (row.get("openalex_id") or "").strip()
        if openalex_id:
            index[openalex_id] = row
    return index


def rank_query_papers(
    pairs: list[dict[str, Any]],
    source_index: dict[str, dict[str, str]],
    keyword: str,
    reference_year: int,
) -> dict[str, Any]:
    """在一个 research query 的候选 pair 上复用现有算法计算两种排序。

    排序完全复用 ``src.processor.add_preliminary_scores`` 与
    ``src.ranking.apply_two_stage_ranking``，不做任何算法改动。排名是候选集合
    （该 RQ 的 20 个 pair）内部的 1..N 名次，用于 NDCG / Precision / error case。
    """
    openalex_to_pair: dict[str, str] = {}
    raw_papers: list[dict[str, Any]] = []
    for pair in pairs:
        openalex_id = str(pair.get("openalex_id") or "").strip()
        if openalex_id not in source_index:
            raise ValueError(f"来源样例缺少 candidate pool 的 openalex_id：{openalex_id}")
        openalex_to_pair[openalex_id] = str(pair.get("pair_id") or "")
        raw_papers.append(dict(source_index[openalex_id]))

    cleaned = clean_papers(raw_papers, keyword)
    for paper in cleaned:
        paper["pair_id"] = openalex_to_pair[paper["openalex_id"]]

    baseline = add_preliminary_scores(
        cleaned, keyword, reference_year=reference_year
    )
    ranked = apply_two_stage_ranking(baseline, keyword)

    baseline_ids = [
        paper["openalex_id"]
        for paper in sorted(ranked, key=lambda item: item["old_rank"])
    ]
    two_stage_ids = [
        paper["openalex_id"]
        for paper in sorted(ranked, key=lambda item: item["new_rank"])
    ]
    return {
        "ranked_papers": ranked,
        "baseline_ids": baseline_ids,
        "two_stage_ids": two_stage_ids,
    }


def build_query_grade_map(
    pairs: list[dict[str, Any]], labels: dict[str, str]
) -> dict[str, int]:
    """把某 RQ 的 pair 标签转成 openalex_id 到数值等级的映射。"""
    grade_map: dict[str, int] = {}
    for pair in pairs:
        grade = parse_w4_label(labels.get(str(pair.get("pair_id") or "")))
        if grade is not None:
            grade_map[str(pair.get("openalex_id") or "")] = grade
    return grade_map


def compute_method_metrics(
    ranked_ids: list[str], grade_map: dict[str, int]
) -> dict[str, float | int | None]:
    """对一个排序方法计算 K=5/10 的核心指标，复用 ``src.evaluation`` judged 口径。

    coverage_at_k 沿用 ``src.evaluation`` 的定义：原始 Top K 中有确定等级论文的
    比例；未标注 / 待讨论论文不进入分母也不拉低 judged 指标。
    """
    filtered = filter_grades_to_ranked(ranked_ids, grade_map)
    metrics: dict[str, float | int | None] = {}
    for k in METRIC_KS:
        top_k_size = len(ranked_ids[:k])
        judged_count = judged_count_at_k(ranked_ids, filtered, k)
        metrics[f"ndcg_at_{k}"] = judged_ndcg_at_k(ranked_ids, filtered, k)
        metrics[f"precision_at_{k}"] = judged_precision_at_k(ranked_ids, filtered, k)
        metrics[f"coverage_at_{k}"] = (
            (judged_count / top_k_size) if top_k_size else None
        )
        metrics[f"irrelevant_top_{k}"] = count_irrelevant_in_top_k(
            ranked_ids, filtered, k
        )
    return metrics


def average_metrics(
    metrics_list: list[dict[str, float | int | None]],
) -> dict[str, float | int | None]:
    """对多个 RQ 的指标做 macro average；None 值跳过，全部为 None 时保持 None。"""
    averaged: dict[str, float | int | None] = {}
    for key in METRIC_KEYS:
        values = [
            float(metrics[key])
            for metrics in metrics_list
            if metrics.get(key) is not None
        ]
        if not values:
            averaged[key] = None
        else:
            averaged[key] = round(sum(values) / len(values), 6)
    return averaged


def classify_error_case(
    human_label: object, baseline_rank: int, two_stage_rank: int
) -> list[str]:
    """按 Issue 第八节识别候选错误类型，只给类型代码，不给最终结论。

    A：人工高度相关，但 two-stage 排名靠后；
    B：人工不相关，但进入任一方法的 Top-K；
    C：baseline 排名高、two-stage 明显降低；
    D：two-stage 排名高、baseline 较低；
    E：人工标注为待讨论（两种方法都难以给出可靠判断）。

    返回命中类型列表（可能为空，表示未命中任何候选类型）。
    """
    label_text = str(human_label or "").strip()
    grade = parse_w4_label(label_text)
    rank_delta = baseline_rank - two_stage_rank
    types: list[str] = []
    if grade == 2 and two_stage_rank > ERROR_TOP_K:
        types.append("A")
    if grade == 0 and (
        baseline_rank <= ERROR_TOP_K or two_stage_rank <= ERROR_TOP_K
    ):
        types.append("B")
    if baseline_rank <= ERROR_TOP_K and rank_delta <= -ERROR_RANK_DELTA_THRESHOLD:
        types.append("C")
    if two_stage_rank <= ERROR_TOP_K and rank_delta >= ERROR_RANK_DELTA_THRESHOLD:
        types.append("D")
    if label_text == "?":
        types.append("E")
    return types


def build_error_cases(
    per_query: dict[str, dict[str, Any]], labels: dict[str, str]
) -> list[dict[str, Any]]:
    """生成统一 error-case 底稿；每行一个 pair，error_type 记录命中的候选类型。"""
    rows: list[dict[str, Any]] = []
    for query_id, result in per_query.items():
        for paper in result["ranked_papers"]:
            pair_id = str(paper.get("pair_id") or "")
            human_label = labels.get(pair_id, "")
            baseline_rank = int(paper["old_rank"])
            two_stage_rank = int(paper["new_rank"])
            rows.append(
                {
                    "pair_id": pair_id,
                    "research_query_id": query_id,
                    "human_label": human_label,
                    "baseline_rank": baseline_rank,
                    "two_stage_rank": two_stage_rank,
                    "rank_delta": baseline_rank - two_stage_rank,
                    "title": paper.get("title") or "",
                    "error_type": ";".join(
                        classify_error_case(
                            human_label, baseline_rank, two_stage_rank
                        )
                    ),
                }
            )
    return rows


def evaluate_benchmark(
    *,
    pool_rows: list[dict[str, Any]],
    labels: dict[str, str],
    research_queries: dict[str, Any],
    source_index: dict[str, dict[str, str]],
    reference_year: int = 2026,
) -> dict[str, Any]:
    """按 Research Question 分别评价 baseline 与 two-stage，并给出 macro summary。

    返回结构：
        {
            "per_query": {
                rq_id: {
                    "baseline": {指标...},
                    "two_stage": {指标...},
                    "pair_count": int,
                    "labeled_count": int,
                    "ranked_papers": [...],
                },
            },
            "macro": {"baseline": {指标...}, "two_stage": {指标...}},
        }
    """
    if pool_rows:
        missing = REQUIRED_POOL_FIELDS.difference(set(pool_rows[0]))
        if missing:
            raise ValueError(
                "candidate pool 缺少字段：" + ", ".join(sorted(missing))
            )

    pool_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pool_rows:
        pool_by_query[str(row.get("research_query_id") or "")].append(row)

    query_list = research_queries["queries"]
    per_query: dict[str, dict[str, Any]] = {}
    for query in query_list:
        query_id = str(query["research_query_id"])
        pairs = pool_by_query.get(query_id, [])
        ranking = rank_query_papers(
            pairs,
            source_index,
            str(query["ranking_keyword"]),
            reference_year,
        )
        grade_map = build_query_grade_map(pairs, labels)
        per_query[query_id] = {
            "baseline": compute_method_metrics(ranking["baseline_ids"], grade_map),
            "two_stage": compute_method_metrics(ranking["two_stage_ids"], grade_map),
            "pair_count": len(pairs),
            "labeled_count": len(grade_map),
            "ranked_papers": ranking["ranked_papers"],
        }

    query_ids = [str(query["research_query_id"]) for query in query_list]
    macro = {
        "baseline": average_metrics([per_query[qid]["baseline"] for qid in query_ids]),
        "two_stage": average_metrics([per_query[qid]["two_stage"] for qid in query_ids]),
    }
    return {"per_query": per_query, "macro": macro}


def build_metric_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """把评价结果展平成 CSV 行：每个 RQ × 方法一行，最后是 macro 汇总。"""
    rows: list[dict[str, Any]] = []
    for query_id, query_result in result["per_query"].items():
        for method in ("baseline", "two_stage"):
            row: dict[str, Any] = {"research_query_id": query_id, "method": method}
            row.update(query_result[method])
            rows.append(row)
    for method in ("baseline", "two_stage"):
        row = {"research_query_id": "macro", "method": method}
        row.update(result["macro"][method])
        rows.append(row)
    return rows


if __name__ == "__main__":
    # 仅演示：构造一份最小输入验证指标路径，不读取真实数据。
    demo_ranked = ["A", "B", "C", "D", "E"]
    demo_grades = {"A": 2, "B": 0, "C": 1}
    print("demo metrics:", compute_method_metrics(demo_ranked, demo_grades))
