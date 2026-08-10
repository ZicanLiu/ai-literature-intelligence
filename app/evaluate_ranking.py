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
from src.ranking import (
    COMPARISON_FIELDS,
    ERROR_CASE_FIELDS,
    STAGE1_HIGH_THRESHOLD,
    STAGE1_LEVEL_GATE,
    STAGE1_MEDIUM_THRESHOLD,
    STAGE2_SCORE_WEIGHTS,
    apply_two_stage_ranking,
    assign_stage1_level,
    build_comparison_rows,
    explain_rank_change,
    select_ranking_error_cases,
)
from src.run_context import build_run_id
from src.utils import ensure_directories


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "w2_ranking"

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
