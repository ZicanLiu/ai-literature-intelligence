"""
两阶段排序评价入口。

该入口在 v0.2.0 初步排序（baseline）之上叠加两阶段排序：
第一阶段用 TF-IDF 词法相关性对论文分层并对低相关论文降权（不删除），
第二阶段在固定权重下综合词法相关性、引用影响、时效性和完整度。
旧版 preliminary_score 完整保留为 baseline，人工标签只用于离线评价。

用法示例：

    python -m app.evaluate_ranking --mode offline ^
        --input data/samples/openalex_stellar_spectra_100.csv ^
        --keyword "machine learning stellar spectra"

    python -m app.evaluate_ranking --mode live ^
        --keyword "machine learning stellar parameter estimation spectra" ^
        --max-results 60 ^
        --sample-csv data/samples/w2/ranking/live_ranking_sample.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.evaluation import evaluate_ranking, load_label_csv
from src.openalex_client import fetch_openalex_papers
from src.processor import (
    add_preliminary_scores,
    clean_papers,
    remove_duplicates,
)
from src.run_context import build_run_id
from src.text_relevance import add_text_relevance_scores
from src.utils import ensure_directories


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "w2_ranking"

# 第一阶段分层阈值：在 100 条统一样例（openalex_stellar_spectra_100.csv）上，
# 两个候选关键词下都能把论文分成数量合理的三层（见设计文档第 4 节）。
# 阈值固定，不随单次数据自动调整，也不使用人工标签。
STAGE1_HIGH_THRESHOLD = 0.20
STAGE1_MEDIUM_THRESHOLD = 0.05

# 第一阶段分层对第二阶段总分的降权系数：低相关论文降权但保留，
# 本周不硬删除任何论文。
STAGE1_LEVEL_GATE = {
    "high": 1.0,
    "medium": 0.8,
    "low": 0.5,
}

# 第二阶段固定权重：词法相关性提升到主导地位（0.50），直接针对第一周
# "高引用但主题偏离的论文排名较高"的问题；引用影响下调到 0.25。
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

LIVE_SAMPLE_FIELDS = [
    "openalex_id",
    "title",
    "authors",
    "publication_year",
    "doi",
    "abstract",
    "cited_by_count",
    "source_name",
    "landing_page_url",
    "keyword",
    "retrieved_at",
    "run_id",
    "baseline_preliminary_score",
    "title_relevance_score",
    "abstract_relevance_score",
    "combined_relevance_score",
    "stage1_relevance_level",
    "stage2_ranking_score",
    "old_rank",
    "new_rank",
]


def assign_stage1_level(combined_relevance_score: float) -> str:
    """
    按固定阈值把词法相关性分数分成 high、medium、low 三层。

    参数：
        combined_relevance_score：0 到 1 之间的组合词法相关性分数。
    返回：分层名称；score >= 0.20 为 high，>= 0.05 为 medium，其余为 low。
    异常或特殊情况：分数缺失或非法时按 low 处理，不删除论文。
    """
    if combined_relevance_score is None:
        return "low"
    if combined_relevance_score >= STAGE1_HIGH_THRESHOLD:
        return "high"
    if combined_relevance_score >= STAGE1_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def apply_two_stage_ranking(papers: list[dict], keyword: str) -> list[dict]:
    """
    在 baseline 排序结果上追加两阶段排序字段并重新排名。

    参数：
        papers：已经过 add_preliminary_scores 的论文列表，
            必须带有 preliminary_score 及其四个子分。
        keyword：用户检索关键词，用于 TF-IDF 词法相关性。
    返回：按 stage2_ranking_score 从高到低排列的新论文列表，
        每篇追加 baseline_preliminary_score、三个相关性分数、
        stage1 字段、stage2_ranking_score、old_rank、new_rank 和 rank_change。
    异常或特殊情况：论文缺少 preliminary_score 时抛出 ValueError；
        空列表返回空列表；所有权重与阈值固定，不读取人工标签。
    """
    if not papers:
        return []
    for paper in papers:
        if paper.get("preliminary_score") is None:
            raise ValueError(
                "两阶段排序要求输入论文已带 preliminary_score；"
                "请先经过 processor.add_preliminary_scores。"
            )

    # 第 0 步：完整保留旧版分数作为 baseline，并按旧规则重算旧排名。
    # 旧排名按输入下标记录：add_text_relevance_scores 返回保持原顺序的副本，
    # 用下标而不是对象 id 对齐，避免复制后键失效。
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

    # 第一阶段：TF-IDF 词法相关性打分与分层。
    scored_papers = add_text_relevance_scores(papers, keyword)
    for paper_index, paper in enumerate(scored_papers):
        paper["baseline_preliminary_score"] = paper["preliminary_score"]
        paper["old_rank"] = old_rank_by_index[paper_index]
        paper["stage1_relevance_score"] = paper["combined_relevance_score"]
        paper["stage1_relevance_level"] = assign_stage1_level(
            paper["combined_relevance_score"]
        )

        # 第二阶段：固定权重综合四项指标，再乘以第一阶段分层的降权系数。
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


def prepare_baseline_papers(raw_papers: list[dict], keyword: str) -> list[dict]:
    """
    用 v0.2.0 现有流程清洗、去重并计算 baseline 排序。

    参数：
        raw_papers：原始论文字典列表。
        keyword：用户检索关键词。
    返回：经 add_preliminary_scores 排序后的论文列表。
    异常或特殊情况：流程完全复用 processor 模块，不修改其行为。
    """
    cleaned_papers = clean_papers(raw_papers, keyword)
    unique_papers, _duplicate_records = remove_duplicates(cleaned_papers)
    return add_preliminary_scores(unique_papers, keyword)


def load_papers_csv(input_file: Path) -> list[dict]:
    """
    从整理样例 CSV 读取论文列表。

    参数：
        input_file：包含统一论文字段的 CSV 路径。
    返回：原始论文字典列表，缺失值统一为 None。
    异常或特殊情况：文件不存在时抛出 ValueError。
        缺失值必须逐单元格用 pd.isna 判断并转成 None：NaN 不能直接进入
        下游清洗，否则会被 str() 变成字符串 "nan"，被误判为字段存在
        （不同 pandas 版本对 where/to_dict 的 None 转换行为不一致，
        逐单元格判断在所有版本下结果相同）。
    """
    input_path = Path(input_file)
    if not input_path.is_file():
        raise ValueError(f"输入 CSV 不存在：{input_path}")
    dataframe = pd.read_csv(input_path)
    records = []
    for row in dataframe.to_dict("records"):
        records.append(
            {key: (None if pd.isna(value) else value) for key, value in row.items()}
        )
    return records


def build_comparison_rows(ranked_papers: list[dict]) -> list[dict]:
    """
    生成 baseline 与两阶段排序的逐论文对比行。

    参数：
        ranked_papers：apply_two_stage_ranking 的输出。
    返回：按 new_rank 排列的对比行列表。
    """
    return [{field: paper.get(field) for field in COMPARISON_FIELDS} for paper in ranked_papers]


def explain_rank_change(paper: dict) -> str:
    """
    为排名变化案例生成可读的规则化解释。

    参数：
        paper：带 old_rank、new_rank 和两阶段字段的论文。
    返回：解释文本；排名不变时返回说明不变的文本。
    异常或特殊情况：解释只引用分数和阈值，不引用人工标签。
    """
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
    """
    选出排名变化最大的案例分析行。

    参数：
        ranked_papers：apply_two_stage_ranking 的输出。
        min_cases：至少输出的案例数量，默认 5。
    返回：按排名变化绝对值降序的案例行列表，含解释文本。
    异常或特殊情况：论文总数不足 min_cases 时输出全部论文。
    """
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


def save_csv(rows: list[dict], fields: list[str], output_file: Path) -> None:
    """
    按项目统一格式保存 CSV（UTF-8 with BOM，固定表头）。

    参数：
        rows：行字典列表。
        fields：固定表头字段。
        output_file：输出路径，父目录会自动创建。
    返回：无。
    异常或特殊情况：空行列表仍保存只有表头的 CSV。
    """
    ensure_directories([Path(output_file).parent])
    dataframe = pd.DataFrame(rows, columns=fields)
    dataframe.to_csv(output_file, index=False, encoding="utf-8-sig")


def print_metric_comparison(
    ranked_papers: list[dict], labels: dict[str, str], k: int = 10
) -> None:
    """
    用人工标签对旧版和新版排序分别计算离线指标并打印对比。

    参数：
        ranked_papers：apply_two_stage_ranking 的输出。
        labels：openalex_id 到标签原文的字典。
        k：指标截断位置。
    返回：无，结果打印到标准输出。
    异常或特殊情况：人工标签只在这里进入评价，不进入任何评分公式。
    """
    old_order = sorted(ranked_papers, key=lambda paper: paper["old_rank"])
    new_order = sorted(ranked_papers, key=lambda paper: paper["new_rank"])
    old_ids = [paper.get("openalex_id", "") for paper in old_order]
    new_ids = [paper.get("openalex_id", "") for paper in new_order]
    old_metrics = evaluate_ranking(old_ids, labels, k)
    new_metrics = evaluate_ranking(new_ids, labels, k)
    print(
        f"离线评价（judged 口径，K={k}，本次排名内标签 {old_metrics['labeled_count']} 条，"
        f"Top {k} 已标注 {old_metrics['judged_count_at_k']} 条，"
        f"覆盖率 {old_metrics['coverage_at_k']}，仅用于评价）"
    )
    for metric in (
        "judged_precision_at_k",
        "judged_ndcg_at_k",
        "irrelevant_in_top_k",
        "average_rank_of_highly_relevant",
    ):
        print(f"  {metric}: baseline={old_metrics[metric]}  two_stage={new_metrics[metric]}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """读取并校验命令行参数的基本类型。"""
    parser = argparse.ArgumentParser(
        description="两阶段排序评价：baseline 保留 + TF-IDF 词法相关性分层 + 固定权重综合排序"
    )
    parser.add_argument(
        "--mode",
        choices=["offline", "live"],
        default="offline",
        help="offline 读取整理样例 CSV；live 请求 OpenAlex（需要本地合法配置）。",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "samples" / "openalex_stellar_spectra_100.csv",
        help="offline 模式的输入 CSV。",
    )
    parser.add_argument(
        "--keyword",
        required=True,
        help="检索关键词，必须与获取数据时使用的关键词一致。",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=60,
        help="live 模式请求的论文数量，OpenAlex 单次最多 100 条。",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        help="可选的人工标签 CSV（openalex_id,label），只用于离线评价。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="分析结果输出目录，默认 data/analysis/w2_ranking。",
    )
    parser.add_argument(
        "--sample-csv",
        type=Path,
        help="可选的整理后样本 CSV 输出路径（live 验证时用于保存样本）。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """执行一次两阶段排序评价；成功返回 0，可读错误返回 1。"""
    args = parse_args(argv)
    keyword = args.keyword.strip()
    if not keyword:
        print("keyword 不能为空或只包含空白字符。")
        return 1

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    # 每次运行都生成 run_id，写入样本 CSV 用于来源追踪；
    # 本入口不创建实验目录，run_id 只作为本次运行的唯一标识。
    run_id = build_run_id(args.mode, keyword, args.max_results)

    try:
        print("第 1 步：正在准备论文数据。")
        if args.mode == "live":
            fetch_result = fetch_openalex_papers(keyword, args.max_results)
            raw_papers = fetch_result["papers"]
        else:
            raw_papers = load_papers_csv(args.input)
        print(f"原始论文数量：{len(raw_papers)}")

        print("第 2 步：正在用 v0.2.0 流程计算 baseline 排序。")
        baseline_papers = prepare_baseline_papers(raw_papers, keyword)
        print(f"baseline 论文数量（清洗去重后）：{len(baseline_papers)}")

        print("第 3 步：正在计算两阶段排序。")
        ranked_papers = apply_two_stage_ranking(baseline_papers, keyword)
        level_counts = {"high": 0, "medium": 0, "low": 0}
        for paper in ranked_papers:
            level_counts[paper["stage1_relevance_level"]] += 1
        print(f"第一阶段分层：{level_counts}")

        print("第 4 步：正在保存对比与案例分析 CSV。")
        comparison_rows = build_comparison_rows(ranked_papers)
        comparison_file = output_dir / "baseline_vs_two_stage.csv"
        save_csv(comparison_rows, COMPARISON_FIELDS, comparison_file)
        error_rows = select_ranking_error_cases(ranked_papers)
        error_file = output_dir / "ranking_error_cases.csv"
        save_csv(error_rows, ERROR_CASE_FIELDS, error_file)
        print(f"已保存：{comparison_file}")
        print(f"已保存：{error_file}")

        if args.sample_csv is not None:
            sample_file = args.sample_csv
            if not sample_file.is_absolute():
                sample_file = PROJECT_ROOT / sample_file
            sample_rows = []
            for paper in ranked_papers:
                row = {field: paper.get(field) for field in LIVE_SAMPLE_FIELDS}
                row["run_id"] = run_id
                sample_rows.append(row)
            save_csv(sample_rows, LIVE_SAMPLE_FIELDS, sample_file)
            print(f"已保存样本：{sample_file}（run_id：{run_id}）")

        if args.labels is not None:
            print("第 5 步：正在用人工标签做离线评价。")
            labels = load_label_csv(args.labels)
            print_metric_comparison(ranked_papers, labels)
    except (ValueError, RuntimeError) as error:
        print(f"运行失败：{error}")
        return 1

    print("两阶段排序评价完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
