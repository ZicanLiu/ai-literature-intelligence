"""
命令行主程序说明：

这个文件负责接收用户命令，串起数据获取、清洗去重、初步排序、保存和可视化流程。
它是整个项目的入口，适合初学者从这里开始阅读项目如何运行。
输入来自命令行参数和本地文件/环境变量，输出是 CSV、SQLite、图表和运行摘要。
"""

import argparse
from pathlib import Path

from src.mock_client import load_mock_papers
from src.openalex_client import fetch_openalex_papers
from src.processor import (
    add_preliminary_scores,
    clean_papers,
    count_missing_fields,
    remove_duplicates,
)
from src.storage import (
    save_duplicates_csv,
    save_ranked_csv,
    save_raw_response,
    save_run_summary,
    save_to_sqlite,
)
from src.utils import ensure_directories
from src.visualizer import generate_charts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
RAW_DIR = OUTPUTS_DIR / "raw"
TABLES_DIR = OUTPUTS_DIR / "tables"
FIGURES_DIR = OUTPUTS_DIR / "figures"
REPORTS_DIR = OUTPUTS_DIR / "reports"
PROJECT_VERSION = "0.2.0"


def parse_args() -> argparse.Namespace:
    """
    读取命令行参数。

    参数：无，argparse 会从命令行读取。
    返回：包含 mode、keyword、max_results 的 Namespace。
    异常或特殊情况：参数不合法时 argparse 会打印帮助信息并退出。
    """
    parser = argparse.ArgumentParser(
        description="AI 在天文光谱数据处理中的应用文献检索、处理与初步排序 MVP"
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "live"],
        default="mock",
        help="mock 表示读取本地数据；live 表示请求 OpenAlex。",
    )
    parser.add_argument(
        "--keyword",
        required=True,
        help='检索关键词，例如 "machine learning astronomical spectra"。',
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="最多处理多少条文献，mock 和 live 模式都会使用这个限制。",
    )
    return parser.parse_args()


def main() -> int:
    """
    主流程入口。

    参数：无，实际输入来自命令行参数。
    返回：0 表示成功，1 表示出现可读错误。
    异常或特殊情况：普通运行错误会被捕获并打印，避免直接输出难懂的堆栈。
    """
    # 第 1 步：读取命令行参数
    args = parse_args()
    print(f"项目版本：v{PROJECT_VERSION}")
    if args.max_results <= 0:
        print("max-results 必须大于 0。")
        return 1

    ensure_directories([DATA_DIR, RAW_DIR, TABLES_DIR, FIGURES_DIR, REPORTS_DIR])
    print("第 1 步：已读取命令行参数。")
    print(f"运行模式：{args.mode}")
    print(f"关键词：{args.keyword}")
    print(f"最大结果数：{args.max_results}")
    if args.mode == "live" and args.max_results > 100:
        print("提示：OpenAlex 单次最多请求 100 条，本次 live 请求将自动限制为 100 条。")

    try:
        # 第 2 步：获取 OpenAlex 或 mock 文献数据
        # 数据流向：命令行关键词 -> 数据源客户端 -> raw_response 和 raw_papers。
        print("第 2 步：正在获取文献数据。")
        if args.mode == "mock":
            fetch_result = load_mock_papers(DATA_DIR / "mock_papers.json", args.keyword, args.max_results)
        else:
            fetch_result = fetch_openalex_papers(args.keyword, args.max_results)

        raw_response = fetch_result["raw_response"]
        raw_papers = fetch_result["papers"]
        print(f"已获取原始文献数量：{len(raw_papers)}")

        # 第 3 步：清洗字段并完成去重
        # 数据流向：raw_papers -> cleaned_papers -> ranked input 的 unique_papers。
        print("第 3 步：正在清洗字段并按 DOI/标题去重。")
        cleaned_papers = clean_papers(raw_papers, args.keyword)
        unique_papers, duplicate_records = remove_duplicates(cleaned_papers)
        missing_counts = count_missing_fields(unique_papers)
        print(f"清洗后文献数量：{len(cleaned_papers)}")
        print(f"去重后文献数量：{len(unique_papers)}")
        print(f"被去重文献数量：{len(duplicate_records)}")

        # 第 4 步：计算初步排序分
        # 数据流向：unique_papers + keyword -> ranked_papers。
        print("第 4 步：正在计算初步文献排序分。")
        ranked_papers = add_preliminary_scores(unique_papers, args.keyword)

        # 第 5 步：保存结果
        # 数据流向：raw_response/ranked_papers/duplicate_records -> JSON、CSV、SQLite。
        print("第 5 步：正在保存 JSON、CSV 和 SQLite。")
        raw_output_file = RAW_DIR / "raw_response.json"
        ranked_csv_file = TABLES_DIR / "papers_ranked.csv"
        duplicates_csv_file = TABLES_DIR / "duplicates_removed.csv"
        database_file = DATA_DIR / "literature.db"

        save_raw_response(raw_response, raw_output_file)
        save_ranked_csv(ranked_papers, ranked_csv_file)
        save_duplicates_csv(duplicate_records, duplicates_csv_file)
        save_to_sqlite(ranked_papers, database_file)

        # 第 6 步：生成图表和运行摘要
        # 数据流向：ranked_papers -> PNG 图表；运行状态 -> run_summary.txt。
        print("第 6 步：正在生成图表和运行摘要。")
        chart_files = generate_charts(ranked_papers, FIGURES_DIR, args.mode)
        summary_text = build_run_summary(
            args,
            raw_count=len(raw_papers),
            cleaned_count=len(cleaned_papers),
            unique_count=len(unique_papers),
            duplicate_count=len(duplicate_records),
            missing_counts=missing_counts,
            output_files={
                "raw_response": raw_output_file,
                "papers_ranked": ranked_csv_file,
                "duplicates_removed": duplicates_csv_file,
                "database": database_file,
                "top10_citations": chart_files["top10_citations"],
                "top10_preliminary_score": chart_files["top10_preliminary_score"],
                "run_summary": REPORTS_DIR / "run_summary.txt",
            },
        )
        save_run_summary(summary_text, REPORTS_DIR / "run_summary.txt")

    except RuntimeError as error:
        print(f"运行失败：{error}")
        return 1
    except OSError as error:
        print(f"文件读写失败：{error}")
        return 1

    print("运行完成。主要结果已生成到 outputs/ 和 data/literature.db。")
    return 0


def build_run_summary(
    args: argparse.Namespace,
    raw_count: int,
    cleaned_count: int,
    unique_count: int,
    duplicate_count: int,
    missing_counts: dict,
    output_files: dict,
) -> str:
    """
    生成运行摘要文本。

    参数：
        args：命令行参数。
        raw_count：原始文献数量。
        cleaned_count：清洗后文献数量。
        unique_count：去重后文献数量。
        duplicate_count：被去重文献数量。
        missing_counts：缺失字段统计。
        output_files：输出文件路径字典。
    返回：适合写入 run_summary.txt 的字符串。
    异常或特殊情况：路径会转换为相对项目根目录的形式，便于阅读。
    """
    lines = [
        "运行摘要",
        "=" * 40,
        f"项目版本：v{PROJECT_VERSION}",
        f"模式：{args.mode}",
        f"图表数据模式：{args.mode}",
        f"关键词：{args.keyword}",
        f"最大结果数：{args.max_results}",
        "",
        "数量统计",
        "-" * 40,
        f"原始文献数量：{raw_count}",
        f"清洗后文献数量：{cleaned_count}",
        f"去重后文献数量：{unique_count}",
        f"被去重文献数量：{duplicate_count}",
        "",
        "缺失字段统计（按去重后文献计算）",
        "-" * 40,
    ]

    for field, count in missing_counts.items():
        lines.append(f"{field}: {count}")

    lines.extend(["", "输出文件", "-" * 40])
    for name, path in output_files.items():
        lines.append(f"{name}: {relative_to_project(path)}")

    lines.extend(
        [
            "",
            "图表数据说明",
            "-" * 40,
            (
                "当前图表由 mock 教学样例生成，不代表真实论文数据或学术结论。"
                if args.mode == "mock"
                else "当前图表由本次 OpenAlex live 返回数据生成。"
            ),
            "",
            "评分说明",
            "-" * 40,
            "preliminary_score = 0.40 * relevance_score + 0.30 * impact_score + "
            "0.20 * recency_score + 0.10 * completeness_score",
            "该分数只用于第一版初步文献排序，不代表论文价值评价。",
        ]
    )
    return "\n".join(lines) + "\n"


def relative_to_project(path: Path) -> str:
    """
    把绝对路径转成相对项目根目录的路径。

    参数：
        path：任意文件路径。
    返回：相对路径字符串。
    异常或特殊情况：如果路径不在项目内，则返回原路径字符串。
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
