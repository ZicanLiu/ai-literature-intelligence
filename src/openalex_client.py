"""
OpenAlex 数据获取模块说明：

这个文件负责在 live 模式下请求 OpenAlex Works API，并把返回 JSON 转成项目统一字段。
它位于数据获取阶段，输出会交给 processor.py 做清洗、去重和排序。
输入是用户关键词、最大记录数和环境变量中的 OPENALEX_API_KEY，输出是原始响应和论文列表。
"""

import os

import requests
from dotenv import load_dotenv

from src.utils import current_timestamp


OPENALEX_WORKS_URL = "https://api.openalex.org/works"


def fetch_openalex_papers(keyword: str, max_results: int, timeout_seconds: int = 20) -> dict:
    """
    使用 OpenAlex Works API 检索论文。

    参数：
        keyword：用户输入的检索关键词。
        max_results：最多返回的论文数量，OpenAlex 单页最多请求 100 条。
        timeout_seconds：网络请求超时时间。
    返回：包含 raw_response 和 papers 两个键的字典。
    异常或特殊情况：
        没有 OPENALEX_API_KEY 时抛出 RuntimeError。
        网络失败、HTTP 错误或 JSON 解析失败时抛出 RuntimeError，并提示可改用 mock 模式。
    """
    load_dotenv()
    api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "live 模式需要 OPENALEX_API_KEY。请在 .env 或环境变量中设置；"
            "如果暂时没有 key，请改用 --mode mock。"
        )

    # v0.2 暂不实现分页；OpenAlex 的 per_page 官方范围是 1 到 100。
    safe_max_results = max(1, min(max_results, 100))
    params = {
        "search": keyword,
        "per_page": safe_max_results,
        # select 只取第一版真正需要的字段，避免把无关 JSON 带进初学者项目。
        "select": (
            "id,display_name,authorships,publication_year,doi,"
            "abstract_inverted_index,cited_by_count,primary_location"
        ),
        # OpenAlex 当前官方文档要求 API key 通过 api_key 查询参数传入。
        "api_key": api_key,
    }

    try:
        response = requests.get(OPENALEX_WORKS_URL, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        raw_response = response.json()
    except requests.RequestException as error:
        raise RuntimeError(
            "访问 OpenAlex 失败，请检查网络、API Key 或稍后重试；"
            "演示时可以改用 --mode mock。"
        ) from error
    except ValueError as error:
        raise RuntimeError("OpenAlex 返回内容不是合法 JSON，请稍后重试或改用 mock 模式。") from error

    results = raw_response.get("results", [])
    papers = []
    for work in results:
        papers.append(convert_openalex_work(work, keyword))

    return {"raw_response": raw_response, "papers": papers}


def convert_openalex_work(work: dict, keyword: str) -> dict:
    """
    把单条 OpenAlex Work JSON 转为项目统一论文字段。

    参数：
        work：OpenAlex 返回的单条 work 字典。
        keyword：本次检索关键词。
    返回：只包含项目第一版需要字段的论文字典。
    异常或特殊情况：
        OpenAlex 某些字段缺失时返回空字符串或 None，不会编造论文信息。
    """
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}

    # OpenAlex 的作者信息在 authorships 列表中，每个 authorship 里有 author.display_name。
    # 这里只做直接提取和拼接，不猜测、不补全作者姓名。
    author_names = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        author_name = author.get("display_name")
        if author_name:
            author_names.append(author_name)

    # OpenAlex 的摘要常以 abstract_inverted_index 保存：
    # 形如 {"word": [0, 5]}，表示某个词出现在哪些位置。
    # 这里按位置还原词序；如果字段不存在，就保持摘要为空。
    abstract = rebuild_abstract(work.get("abstract_inverted_index"))

    paper = {
        "title": work.get("display_name") or "",
        "authors": "; ".join(author_names),
        "publication_year": work.get("publication_year"),
        "doi": work.get("doi") or "",
        "abstract": abstract,
        "cited_by_count": work.get("cited_by_count"),
        "source_name": source.get("display_name") or "",
        "openalex_id": work.get("id") or "",
        "landing_page_url": primary_location.get("landing_page_url") or "",
        "keyword": keyword,
        "retrieved_at": current_timestamp(),
    }
    return paper


def rebuild_abstract(abstract_inverted_index: dict | None) -> str:
    """
    从 OpenAlex 的 abstract_inverted_index 还原摘要文本。

    参数：
        abstract_inverted_index：OpenAlex 摘要倒排索引，可能为 None。
    返回：还原后的摘要字符串；没有摘要时返回空字符串。
    异常或特殊情况：
        如果位置索引格式异常，会尽量跳过异常位置，避免主流程崩溃。
    """
    if not abstract_inverted_index:
        return ""

    words_by_position = {}
    for word, positions in abstract_inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                words_by_position[position] = word

    ordered_words = []
    for position in sorted(words_by_position):
        ordered_words.append(words_by_position[position])
    return " ".join(ordered_words)


if __name__ == "__main__":
    print("openalex_client.py 负责 live 模式数据获取。")
    print("直接运行此文件不会自动请求网络；请通过 python -m app.main --mode live 使用。")
