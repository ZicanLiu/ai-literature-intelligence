"""
图表生成模块说明：

这个文件负责用 matplotlib 生成两张基础柱状图。
它位于排序和保存之后，用 CSV/内存中的排序论文生成可演示的图片。
输入是已排序论文列表，输出是引用量 Top 10 和初步排序分 Top 10 的 PNG 图表。
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.utils import short_title


def generate_charts(ranked_papers: list[dict], figures_dir: Path, mode: str) -> dict:
    """
    生成项目要求的两张图表。

    参数：
        ranked_papers：已计算初步排序分的论文列表。
        figures_dir：图表输出目录。
        mode：当前数据模式，mock 或 live。
    返回：图表名称到文件路径的字典。
    异常或特殊情况：论文为空时会生成带 No data 提示的空图，不让流程崩溃。
    """
    citations_file = figures_dir / "top10_citations.png"
    score_file = figures_dir / "top10_preliminary_score.png"

    source_label = "[MOCK DATA]" if mode == "mock" else "[OPENALEX LIVE]"
    plot_top10_citations(ranked_papers, citations_file, source_label)
    plot_top10_preliminary_scores(ranked_papers, score_file, source_label)

    return {
        "top10_citations": citations_file,
        "top10_preliminary_score": score_file,
    }


def plot_top10_citations(
    ranked_papers: list[dict], output_file: Path, source_label: str
) -> None:
    """
    绘制引用量最高的 Top 10 文献柱状图。

    参数：
        ranked_papers：已排序论文列表。
        output_file：PNG 输出路径。
        source_label：图表标题中的数据来源标识。
    返回：无。
    异常或特殊情况：列表为空时生成空图。
    """
    if not ranked_papers:
        save_empty_chart(output_file, f"{source_label} Top 10 Papers by Citations")
        return

    dataframe = pd.DataFrame(ranked_papers)
    dataframe["cited_by_count"] = dataframe["cited_by_count"].fillna(0)

    # 图表数据筛选逻辑：按 cited_by_count 从高到低排序，只取前 10 篇。
    # 这里不改变论文表本身的顺序，只为图表展示临时排序。
    top10 = dataframe.sort_values("cited_by_count", ascending=False).head(10)
    labels = [short_title(title) for title in top10["title"].tolist()]
    values = top10["cited_by_count"].tolist()

    save_bar_chart(
        labels,
        values,
        output_file,
        f"{source_label} Top 10 Papers by Citations",
        "Cited by count",
    )


def plot_top10_preliminary_scores(
    ranked_papers: list[dict], output_file: Path, source_label: str
) -> None:
    """
    绘制 preliminary_score 最高的 Top 10 文献柱状图。

    参数：
        ranked_papers：已排序论文列表。
        output_file：PNG 输出路径。
        source_label：图表标题中的数据来源标识。
    返回：无。
    异常或特殊情况：列表为空时生成空图。
    """
    if not ranked_papers:
        save_empty_chart(
            output_file, f"{source_label} Top 10 Papers by Preliminary Score"
        )
        return

    dataframe = pd.DataFrame(ranked_papers)
    dataframe["preliminary_score"] = dataframe["preliminary_score"].fillna(0)

    # 图表数据筛选逻辑：按第一版的 preliminary_score 从高到低排序，只取前 10 篇。
    # 这个分数只是辅助排序，不表示论文价值高低。
    top10 = dataframe.sort_values("preliminary_score", ascending=False).head(10)
    labels = [short_title(title) for title in top10["title"].tolist()]
    values = top10["preliminary_score"].tolist()

    save_bar_chart(
        labels,
        values,
        output_file,
        f"{source_label} Top 10 Papers by Preliminary Score",
        "Preliminary score",
    )


def save_bar_chart(
    labels: list[str],
    values: list[float],
    output_file: Path,
    title: str,
    x_label: str,
) -> None:
    """
    保存横向柱状图。

    参数：
        labels：图表中的论文短标题。
        values：每篇论文对应的数值。
        output_file：PNG 输出路径。
        title：图表标题。
        x_label：横轴标签。
    返回：无。
    异常或特殊情况：matplotlib 后端异常会向上抛出。
    """
    plt.figure(figsize=(11, 6))
    y_positions = range(len(labels))
    plt.barh(y_positions, values, color="#4C78A8")
    plt.yticks(y_positions, labels, fontsize=8)
    plt.xlabel(x_label)
    plt.title(title)
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()


def save_empty_chart(output_file: Path, title: str) -> None:
    """
    在没有论文数据时保存空图。

    参数：
        output_file：PNG 输出路径。
        title：图表标题。
    返回：无。
    异常或特殊情况：matplotlib 后端异常会向上抛出。
    """
    plt.figure(figsize=(8, 4))
    plt.title(title)
    plt.text(0.5, 0.5, "No data", ha="center", va="center")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()


if __name__ == "__main__":
    print("visualizer.py 负责生成图表。")
    print("请通过 python -m app.main 生成完整结果图。")
