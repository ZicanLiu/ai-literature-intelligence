"""W2 TF-IDF 两阶段排序的可复用业务逻辑。

该模块从原评价 CLI 中提取纯排序函数和输出契约。算法、阈值、权重、排序键和解释文本
保持不变；``app.evaluate_ranking`` 继续导入并向后兼容地暴露这些名称。
"""

from __future__ import annotations

from src.text_relevance import add_text_relevance_scores


STAGE1_HIGH_THRESHOLD = 0.20
STAGE1_MEDIUM_THRESHOLD = 0.05

STAGE1_LEVEL_GATE = {
    "high": 1.0,
    "medium": 0.8,
    "low": 0.5,
}

STAGE2_SCORE_WEIGHTS = {
    "relevance_score": 0.50,
    "impact_score": 0.25,
    "recency_score": 0.15,
    "completeness_score": 0.10,
}

COMPARISON_FIELDS = [
    "openalex_id",
    "title",
    "cited_by_count",
    "publication_year",
    "baseline_preliminary_score",
    "title_relevance_score",
    "abstract_relevance_score",
    "combined_relevance_score",
    "stage1_relevance_score",
    "stage1_relevance_level",
    "stage2_ranking_score",
    "old_rank",
    "new_rank",
    "rank_change",
]

ERROR_CASE_FIELDS = [
    "openalex_id",
    "title",
    "cited_by_count",
    "old_rank",
    "new_rank",
    "rank_change",
    "baseline_preliminary_score",
    "combined_relevance_score",
    "stage1_relevance_level",
    "explanation",
]


def assign_stage1_level(combined_relevance_score: float) -> str:
    """按原固定阈值返回 high、medium 或 low，不删除论文。"""
    if combined_relevance_score is None:
        return "low"
    if combined_relevance_score >= STAGE1_HIGH_THRESHOLD:
        return "high"
    if combined_relevance_score >= STAGE1_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def apply_two_stage_ranking(papers: list[dict], keyword: str) -> list[dict]:
    """在已有 preliminary_score baseline 上追加原 W2 两阶段排序。"""
    if not papers:
        return []
    for paper in papers:
        if paper.get("preliminary_score") is None:
            raise ValueError(
                "两阶段排序要求输入论文已带 preliminary_score；"
                "请先经过 processor.add_preliminary_scores。"
            )

    baseline_order = sorted(
        range(len(papers)),
        key=lambda index: (
            papers[index].get("preliminary_score", 0),
            papers[index].get("cited_by_count") or 0,
            papers[index].get("publication_year") or 0,
        ),
        reverse=True,
    )
    old_rank_by_index = {}
    for rank_index, paper_index in enumerate(baseline_order):
        old_rank_by_index[paper_index] = rank_index + 1

    scored_papers = add_text_relevance_scores(papers, keyword)
    for paper_index, paper in enumerate(scored_papers):
        paper["baseline_preliminary_score"] = paper["preliminary_score"]
        paper["old_rank"] = old_rank_by_index[paper_index]
        paper["stage1_relevance_score"] = paper["combined_relevance_score"]
        paper["stage1_relevance_level"] = assign_stage1_level(
            paper["combined_relevance_score"]
        )

        stage2_base = (
            STAGE2_SCORE_WEIGHTS["relevance_score"]
            * paper["combined_relevance_score"]
            + STAGE2_SCORE_WEIGHTS["impact_score"] * (paper.get("impact_score") or 0)
            + STAGE2_SCORE_WEIGHTS["recency_score"] * (paper.get("recency_score") or 0)
            + STAGE2_SCORE_WEIGHTS["completeness_score"]
            * (paper.get("completeness_score") or 0)
        )
        gate = STAGE1_LEVEL_GATE[paper["stage1_relevance_level"]]
        paper["stage2_ranking_score"] = round(stage2_base * gate, 4)

    ranked_papers = sorted(
        scored_papers,
        key=lambda paper: (
            paper["stage2_ranking_score"],
            paper["combined_relevance_score"],
            paper.get("cited_by_count") or 0,
            paper.get("publication_year") or 0,
        ),
        reverse=True,
    )
    for rank_index, paper in enumerate(ranked_papers):
        paper["new_rank"] = rank_index + 1
        paper["rank_change"] = paper["old_rank"] - paper["new_rank"]
    return ranked_papers


def build_comparison_rows(ranked_papers: list[dict]) -> list[dict]:
    """生成 baseline 与两阶段排序的逐论文对比行。"""
    return [
        {field: paper.get(field) for field in COMPARISON_FIELDS}
        for paper in ranked_papers
    ]


def explain_rank_change(paper: dict) -> str:
    """按原规则生成不依赖人工标签的排名变化解释。"""
    rank_change = paper.get("rank_change", 0)
    combined = paper.get("combined_relevance_score", 0.0)
    level = paper.get("stage1_relevance_level", "low")
    cited = paper.get("cited_by_count") or 0
    if rank_change < 0:
        return (
            f"排名下降 {-rank_change} 位：引用量 {cited} 支撑了旧版高分，"
            f"但词法相关性 combined={combined:.4f}（{level} 层），"
            f"第一阶段降权系数 {STAGE1_LEVEL_GATE[level]} 生效"
        )
    if rank_change > 0:
        return (
            f"排名上升 {rank_change} 位：词法相关性 combined={combined:.4f}"
            f"（{level} 层）在新权重 0.50 下贡献超过引用影响"
        )
    return "排名不变：两阶段相对位置未改变"


def select_ranking_error_cases(
    ranked_papers: list[dict], min_cases: int = 5
) -> list[dict]:
    """选出排名变化绝对值最大的案例，保持原排序和解释规则。"""
    sorted_by_change = sorted(
        ranked_papers,
        key=lambda paper: (abs(paper.get("rank_change", 0)), paper.get("old_rank", 0)),
        reverse=True,
    )
    cases = sorted_by_change[: max(min_cases, 1)]
    rows = []
    for paper in cases:
        row = {field: paper.get(field) for field in ERROR_CASE_FIELDS}
        row["explanation"] = explain_rank_change(paper)
        rows.append(row)
    return rows
