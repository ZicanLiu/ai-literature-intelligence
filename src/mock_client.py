"""
mock 数据读取模块说明：

这个文件负责读取本地 data/mock_papers.json。
它位于数据获取阶段，用来保证项目在没有网络、没有 API Key 的情况下也能完整运行。
输入是 mock JSON 文件路径、关键词和最大记录数，输出是原始响应字典和论文列表。
"""

import json
from pathlib import Path

from src.utils import current_timestamp


def load_mock_papers(mock_file: Path, keyword: str, max_results: int) -> dict:
    """
    从本地 JSON 文件读取 mock 文献数据。

    参数：
        mock_file：mock_papers.json 的路径。
        keyword：用户输入的检索关键词，会写入每条记录的 keyword 字段。
        max_results：最多返回的论文数量。
    返回：包含 raw_response 和 papers 两个键的字典。
    异常或特殊情况：
        文件不存在或 JSON 格式错误时会抛出可读的 RuntimeError。
        mock 数据为空时返回空列表，不会让主程序崩溃。
    """
    try:
        with mock_file.open("r", encoding="utf-8") as file:
            mock_papers = json.load(file)
    except FileNotFoundError as error:
        raise RuntimeError(f"找不到 mock 数据文件：{mock_file}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"mock 数据不是合法 JSON：{mock_file}") from error

    if not isinstance(mock_papers, list):
        raise RuntimeError("mock_papers.json 顶层必须是论文列表。")

    selected_papers = mock_papers[:max_results]
    retrieved_at = current_timestamp()

    papers_with_run_info = []
    for paper in selected_papers:
        copied_paper = dict(paper)
        copied_paper["keyword"] = keyword
        copied_paper["retrieved_at"] = copied_paper.get("retrieved_at") or retrieved_at
        papers_with_run_info.append(copied_paper)

    raw_response = {
        "source": "mock",
        "keyword": keyword,
        "max_results": max_results,
        "results": papers_with_run_info,
        "retrieved_at": retrieved_at,
    }

    return {"raw_response": raw_response, "papers": papers_with_run_info}


if __name__ == "__main__":
    demo_file = Path(__file__).resolve().parents[1] / "data" / "mock_papers.json"
    demo_result = load_mock_papers(demo_file, "machine learning astronomical spectra", 3)
    print(f"已读取 mock 文献数量：{len(demo_result['papers'])}")
