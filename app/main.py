"""
命令行主程序。

该入口串联数据获取、清洗去重、初步排序、保存和可视化流程。每次合法运行
都会创建独立实验目录，避免连续运行覆盖历史结果。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.mock_client import load_mock_papers
from src.openalex_client import fetch_openalex_papers
from src.processor import (
    PRELIMINARY_SCORE_WEIGHTS,
    add_preliminary_scores,
    clean_papers,
    count_missing_fields,
    remove_duplicates,
)
from src.run_context import RunContext, safe_error_summary
from src.storage import (
    save_duplicates_csv,
    save_ranked_csv,
    save_raw_response,
    save_run_summary,
    save_to_sqlite,
)
from src.visualizer import generate_charts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "experiments"
PROJECT_VERSION = "0.2.0"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """读取并校验命令行参数的基本类型。"""
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
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="实验输出根目录；默认是 outputs/experiments。",
    )
    parser.add_argument(
        "--run-name",
        help="可选的运行名称，会经过文件名安全处理后加入 run_id。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """执行一次完整流程；成功返回 0，可读运行错误返回 1。"""
    args = parse_args(argv)
    print(f"项目版本：v{PROJECT_VERSION}")

    args.keyword = args.keyword.strip()
    if not args.keyword:
        print("keyword 不能为空或只包含空白字符。")
        return 1
    if args.max_results <= 0:
        print("max-results 必须大于 0。")
        return 1

    output_root = args.output_root.expanduser()
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root

    run_context: RunContext | None = None
    try:
        run_context = RunContext.create(
            project_root=PROJECT_ROOT,
            output_root=output_root,
            mode=args.mode,
            keyword=args.keyword,
            max_results=args.max_results,
            project_version=PROJECT_VERSION,
            scoring_weights=PRELIMINARY_SCORE_WEIGHTS,
            run_name=args.run_name,
        )
        print("第 1 步：已读取命令行参数并创建独立实验目录。")
        print(f"run_id：{run_context.run_id}")
        print(f"运行模式：{args.mode}")
        print(f"关键词：{args.keyword}")
        print(f"最大结果数：{args.max_results}")
        if args.mode == "live" and args.max_results > 100:
            print("提示：OpenAlex 单次最多请求 100 条，本次 live 请求将自动限制为 100 条。")

        print("第 2 步：正在获取文献数据。")
        if args.mode == "mock":
            fetch_result = load_mock_papers(
                DATA_DIR / "mock_papers.json",
                args.keyword,
                args.max_results,
            )
        else:
            fetch_result = fetch_openalex_papers(args.keyword, args.max_results)

        raw_response = fetch_result["raw_response"]
        raw_papers = fetch_result["papers"]
        save_raw_response(raw_response, run_context.raw_response_file)
        print(f"已获取原始文献数量：{len(raw_papers)}")

        print("第 3 步：正在清洗字段并按 DOI/标题去重。")
        cleaned_papers = clean_papers(raw_papers, args.keyword)
        unique_papers, duplicate_records = remove_duplicates(cleaned_papers)
        missing_counts = count_missing_fields(unique_papers)
        print(f"清洗后文献数量：{len(cleaned_papers)}")
        print(f"去重后文献数量：{len(unique_papers)}")
        print(f"被去重文献数量：{len(duplicate_records)}")
        run_context.record_counts(
            raw_count=len(raw_papers),
            cleaned_count=len(cleaned_papers),
            unique_count=len(unique_papers),
            duplicate_count=len(duplicate_records),
        )

        print("第 4 步：正在计算初步文献排序分。")
        ranked_papers = add_preliminary_scores(unique_papers, args.keyword)

        print("第 5 步：正在保存 CSV 和 SQLite。")
        save_ranked_csv(ranked_papers, run_context.ranked_csv_file)
        save_duplicates_csv(duplicate_records, run_context.duplicates_csv_file)
        save_to_sqlite(ranked_papers, run_context.database_file)

        print("第 6 步：正在生成图表和运行摘要。")
        generate_charts(ranked_papers, run_context.figures_dir, args.mode)
        summary_text = build_run_summary(
            args,
            run_id=run_context.run_id,
            run_dir=run_context.run_dir,
            raw_count=len(raw_papers),
            cleaned_count=len(cleaned_papers),
            unique_count=len(unique_papers),
            duplicate_count=len(duplicate_records),
            missing_counts=missing_counts,
            output_files=run_context.output_files(),
        )
        save_run_summary(summary_text, run_context.summary_file)
        run_context.record_success(
            raw_count=len(raw_papers),
            cleaned_count=len(cleaned_papers),
            unique_count=len(unique_papers),
            duplicate_count=len(duplicate_records),
        )
    except Exception as error:
        if run_context is not None:
            try:
                run_context.record_failure(error)
            except OSError:
                pass
            error_text = safe_error_summary(error, PROJECT_ROOT, run_context.run_dir)
        else:
            error_text = safe_error_summary(error, PROJECT_ROOT, output_root)
        print(f"运行失败：{error_text}")
        return 1

    print(f"运行完成。结果目录：{display_path(run_context.run_dir)}")
    return 0


def build_run_summary(
    args: argparse.Namespace,
    run_id: str,
    run_dir: Path,
    raw_count: int,
    cleaned_count: int,
    unique_count: int,
    duplicate_count: int,
    missing_counts: dict,
    output_files: dict[str, Path],
) -> str:
    """生成不含本地绝对路径的运行摘要。"""
    lines = [
        "运行摘要",
        "=" * 40,
        f"run_id：{run_id}",
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

    lines.extend(["", "输出文件（相对本次实验目录）", "-" * 40])
    for name, path in output_files.items():
        lines.append(f"{name}: {path.relative_to(run_dir).as_posix()}")

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
            "该分数只用于项目内部初步排序，不代表论文真实学术价值。",
        ]
    )
    return "\n".join(lines) + "\n"


def display_path(path: Path) -> str:
    """项目内路径使用相对形式，避免普通输出过长。"""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
