"""
论文处理模块说明：

这个文件负责文献元数据的清洗、去重、缺失统计和初步文献排序。
它位于数据获取之后、保存和可视化之前，是本 MVP 的核心处理环节。
输入是原始论文字典列表和用户关键词，输出是清洗后的论文、去重记录、缺失统计和排序分。
"""

import math
import re
from datetime import datetime

from src.utils import current_timestamp, value_is_missing


OUTPUT_FIELDS = [
    "title",
    "authors",
    "publication_year",
    "doi",
    "abstract",
    "cited_by_count",
    "source_name",
    "openalex_id",
    "landing_page_url",
    "keyword",
    "retrieved_at",
]

PRELIMINARY_SCORE_WEIGHTS = {
    "relevance_score": 0.40,
    "impact_score": 0.30,
    "recency_score": 0.20,
    "completeness_score": 0.10,
}


def clean_papers(raw_papers: list[dict], keyword: str) -> list[dict]:
    """
    清洗论文列表中的基础字段。

    参数：
        raw_papers：OpenAlex 或 mock 返回的原始论文列表。
        keyword：用户输入的检索关键词。
    返回：字段统一、文本去除首尾空格后的论文列表。
    异常或特殊情况：
        字段缺失时使用 None 或空字符串保留缺失状态，不编造 DOI、作者、摘要等信息。
    """
    cleaned_papers = []
    for raw_paper in raw_papers:
        cleaned_papers.append(clean_single_paper(raw_paper, keyword))
    return cleaned_papers


def clean_single_paper(raw_paper: dict, keyword: str) -> dict:
    """
    清洗单篇论文的字段。

    参数：
        raw_paper：单条原始论文字典。
        keyword：用户输入的检索关键词。
    返回：清洗后的单条论文字典。
    异常或特殊情况：
        数字字段无法转换时返回 None，避免把错误值写入排序公式。
    """
    paper = {
        "title": clean_text(raw_paper.get("title")),
        "authors": clean_authors(raw_paper.get("authors")),
        "publication_year": clean_int(raw_paper.get("publication_year")),
        "doi": normalize_doi(raw_paper.get("doi")),
        "abstract": clean_text(raw_paper.get("abstract")),
        "cited_by_count": clean_int(raw_paper.get("cited_by_count")),
        "source_name": clean_text(raw_paper.get("source_name")),
        "openalex_id": clean_text(raw_paper.get("openalex_id")),
        "landing_page_url": clean_text(raw_paper.get("landing_page_url")),
        "keyword": clean_text(raw_paper.get("keyword")) or keyword,
        "retrieved_at": clean_text(raw_paper.get("retrieved_at")) or current_timestamp(),
    }
    return paper


def clean_text(value: object) -> str:
    """
    清洗普通文本字段。

    参数：
        value：可能是字符串、None 或其他类型的字段值。
    返回：去除首尾空格后的字符串；缺失时返回空字符串。
    异常或特殊情况：非字符串会转成字符串，但 None 会保持为空字符串。
    """
    if value is None:
        return ""
    return str(value).strip()


def clean_authors(value: object) -> str:
    """
    清洗作者字段。

    参数：
        value：作者字符串、作者列表或 None。
    返回：用分号分隔的作者字符串；缺失时返回空字符串。
    异常或特殊情况：列表中为空的作者名会被跳过，不会补造作者。
    """
    if value is None:
        return ""
    if isinstance(value, list):
        author_names = []
        for author in value:
            clean_name = clean_text(author)
            if clean_name:
                author_names.append(clean_name)
        return "; ".join(author_names)
    return clean_text(value)


def clean_int(value: object) -> int | None:
    """
    清洗整数数字字段。

    参数：
        value：年份、引用量等可能为整数的值。
    返回：整数或 None。
    异常或特殊情况：空字符串、None 或无法转换的值返回 None。
    """
    if value_is_missing(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_doi(value: object) -> str:
    """
    标准化 DOI 字段。

    参数：
        value：原始 DOI，可能含有 https://doi.org/ 前缀。
    返回：小写且去掉常见 DOI 前缀后的字符串；缺失时返回空字符串。
    异常或特殊情况：不会生成新的 DOI，只处理已有 DOI 的格式。
    """
    doi = clean_text(value).lower()
    if not doi:
        return ""

    # DOI 常见来源可能是 "https://doi.org/10.xxxx/ABC"。
    # 为了让同一 DOI 在去重时能被识别，需要先统一小写，再移除这些前缀。
    prefixes = ["https://doi.org/", "http://doi.org/", "doi.org/", "doi:"]
    for prefix in prefixes:
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip()


def normalize_title_for_match(title: str) -> str:
    """
    标准化标题用于完全匹配去重。

    参数：
        title：论文标题。
    返回：小写、首尾去空格、多个空白合并后的标题。
    异常或特殊情况：这里只做完全匹配准备，不做模糊匹配或语义相似度。
    """
    # 标题去重只在 DOI 缺失时使用。这里合并空白和统一小写，是为了消除大小写、
    # 多余空格这类格式差异；不处理同义词，也不猜测标题是否“意思相近”。
    clean_title = clean_text(title).lower()
    return re.sub(r"\s+", " ", clean_title)


def remove_duplicates(cleaned_papers: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    根据 DOI 和标题去除重复论文。

    参数：
        cleaned_papers：已完成字段清洗的论文列表。
    返回：二元组，第一项是保留论文列表，第二项是被去重论文及原因。
    异常或特殊情况：
        DOI 存在时只按 DOI 判断重复；DOI 缺失时才按标准化标题完全相同判断重复。
    """
    unique_papers = []
    duplicate_records = []
    seen_by_doi = {}
    seen_by_title_without_doi = {}

    for paper in cleaned_papers:
        doi = paper.get("doi", "")
        title_key = normalize_title_for_match(paper.get("title", ""))

        # 去重规则 1：如果 DOI 存在，DOI 是最稳定的标识，重复 DOI 直接去重。
        if doi:
            if doi in seen_by_doi:
                duplicate_records.append(
                    build_duplicate_record(paper, seen_by_doi[doi], "DOI 重复")
                )
                continue
            seen_by_doi[doi] = paper
            unique_papers.append(paper)
            continue

        # 去重规则 2：只有 DOI 缺失时，才用标准化标题完全相同来去重。
        # 这样可以避免把不同 DOI 的相似标题论文误删。
        if title_key:
            if title_key in seen_by_title_without_doi:
                duplicate_records.append(
                    build_duplicate_record(
                        paper,
                        seen_by_title_without_doi[title_key],
                        "DOI 缺失且标准化标题完全相同",
                    )
                )
                continue
            seen_by_title_without_doi[title_key] = paper

        unique_papers.append(paper)

    return unique_papers, duplicate_records


def build_duplicate_record(duplicate_paper: dict, kept_paper: dict, reason: str) -> dict:
    """
    生成被去重记录。

    参数：
        duplicate_paper：本次被移除的论文。
        kept_paper：此前已保留的论文。
        reason：去重原因。
    返回：包含原始字段和去重原因的字典。
    异常或特殊情况：如果 openalex_id 缺失，也会保留空字符串。
    """
    record = dict(duplicate_paper)
    record["duplicate_reason"] = reason
    record["kept_openalex_id"] = kept_paper.get("openalex_id", "")
    record["kept_title"] = kept_paper.get("title", "")
    return record


def count_missing_fields(papers: list[dict]) -> dict:
    """
    统计每个输出字段的缺失数量。

    参数：
        papers：论文列表。
    返回：字段名到缺失数量的字典。
    异常或特殊情况：数字 0 不视为缺失，避免把 0 引用论文误判为字段缺失。
    """
    missing_counts = {}
    for field in OUTPUT_FIELDS:
        missing_counts[field] = 0
        for paper in papers:
            if value_is_missing(paper.get(field)):
                missing_counts[field] += 1
    return missing_counts


def add_preliminary_scores(
    papers: list[dict], keyword: str, *, reference_year: int | None = None
) -> list[dict]:
    """
    为论文计算初步文献排序分。

    参数：
        papers：去重后的论文列表。
        keyword：用户输入的检索关键词。
        reference_year：可选的固定近期程度参考年；None 保持旧运行时年份行为。
    返回：按 preliminary_score 从高到低排序后的论文列表。
    异常或特殊情况：论文列表为空时返回空列表；缺失字段按 0 分参与对应子分计算。
    """
    if not papers:
        return []

    max_log_citation = find_max_log_citation(papers)
    ranked_papers = []
    for paper in papers:
        relevance_score = calculate_relevance_score(paper, keyword)
        impact_score = calculate_impact_score(paper, max_log_citation)
        recency_score = calculate_recency_score(paper, reference_year=reference_year)
        completeness_score = calculate_completeness_score(paper)

        # 初步排序分只是一条透明的辅助规则：
        # 相关性 40%，引用影响 30%，近期程度 20%，字段完整度 10%。
        # 它不等同于论文“学术价值”，也不能替代人工阅读和判断。
        preliminary_score = (
            PRELIMINARY_SCORE_WEIGHTS["relevance_score"] * relevance_score
            + PRELIMINARY_SCORE_WEIGHTS["impact_score"] * impact_score
            + PRELIMINARY_SCORE_WEIGHTS["recency_score"] * recency_score
            + PRELIMINARY_SCORE_WEIGHTS["completeness_score"]
            * completeness_score
        )

        scored_paper = dict(paper)
        scored_paper["relevance_score"] = round(relevance_score, 4)
        scored_paper["impact_score"] = round(impact_score, 4)
        scored_paper["recency_score"] = round(recency_score, 4)
        scored_paper["completeness_score"] = round(completeness_score, 4)
        scored_paper["preliminary_score"] = round(preliminary_score, 4)
        ranked_papers.append(scored_paper)

    ranked_papers.sort(
        key=lambda paper: (
            paper.get("preliminary_score", 0),
            paper.get("cited_by_count") or 0,
            paper.get("publication_year") or 0,
        ),
        reverse=True,
    )
    return ranked_papers


def find_max_log_citation(papers: list[dict]) -> float:
    """
    找到引用量 log1p 后的最大值。

    参数：
        papers：论文列表。
    返回：最大 log1p 引用量。
    异常或特殊情况：全部引用量缺失或为 0 时返回 0。
    """
    max_value = 0.0
    for paper in papers:
        citation_count = paper.get("cited_by_count") or 0
        max_value = max(max_value, math.log1p(max(0, citation_count)))
    return max_value


def calculate_relevance_score(paper: dict, keyword: str) -> float:
    """
    根据关键词在标题和摘要中的出现情况计算相关性分数。

    参数：
        paper：单篇论文。
        keyword：用户输入关键词。
    返回：0 到 1 之间的相关性分数。
    异常或特殊情况：关键词为空时返回 0。
    """
    keyword_terms = split_keyword_terms(keyword)
    if not keyword_terms:
        return 0.0

    title_terms = set(tokenize_english_text(paper.get("title") or ""))
    abstract_terms = set(tokenize_english_text(paper.get("abstract") or ""))

    # 标题通常比摘要更能直接表达主题，所以标题匹配给 70% 权重，摘要匹配给 30% 权重。
    # 不能直接使用子字符串匹配，否则 ai 会误匹配 training；这里仅比较完整英文数字词项。
    title_matches = count_term_matches(keyword_terms, title_terms)
    abstract_matches = count_term_matches(keyword_terms, abstract_terms)
    term_count = len(keyword_terms)

    title_score = title_matches / term_count
    abstract_score = abstract_matches / term_count
    return min(1.0, 0.70 * title_score + 0.30 * abstract_score)


def split_keyword_terms(keyword: str) -> list[str]:
    """
    把关键词拆成用于匹配的词项。

    参数：
        keyword：用户输入关键词。
    返回：去重后的英文小写词项列表。
    异常或特殊情况：会忽略长度小于 2 的词，减少无意义匹配。
    """
    terms = []
    for term in tokenize_english_text(keyword):
        if len(term) >= 2 and term not in terms:
            terms.append(term)
    return terms


def tokenize_english_text(text: str) -> list[str]:
    """
    把文本拆成小写英文数字词项。

    参数：
        text：关键词、标题或摘要文本。
    返回：按原顺序排列的英文数字词项列表。
    异常或特殊情况：文本为空时返回空列表；不做词干还原或同义词扩展。
    """
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def count_term_matches(keyword_terms: list[str], text_terms: set[str]) -> int:
    """
    统计关键词词项在文本中出现了多少个。

    参数：
        keyword_terms：关键词拆出的词项。
        text_terms：标题或摘要拆分后得到的词项集合。
    返回：出现的词项数量。
    异常或特殊情况：文本为空时返回 0。
    """
    match_count = 0
    for term in keyword_terms:
        if term in text_terms:
            match_count += 1
    return match_count


def calculate_impact_score(paper: dict, max_log_citation: float) -> float:
    """
    根据引用量计算影响分。

    参数：
        paper：单篇论文。
        max_log_citation：本批论文中最大的 log1p 引用量。
    返回：0 到 1 之间的影响分。
    异常或特殊情况：最大引用量为 0 时返回 0，避免除以 0。
    """
    if max_log_citation <= 0:
        return 0.0
    citation_count = paper.get("cited_by_count") or 0
    return math.log1p(max(0, citation_count)) / max_log_citation


def calculate_recency_score(
    paper: dict, reference_year: int | None = None
) -> float:
    """
    根据发表年份计算近期程度分。

    参数：
        paper：单篇论文。
        reference_year：可选的固定评分参考年；None 保持旧行为，使用运行时当前年。
    返回：0 到 1 之间的近期程度分。
    异常或特殊情况：年份缺失时返回 0；未来年份按 1 分处理。
    """
    publication_year = paper.get("publication_year")
    if publication_year is None:
        return 0.0

    if reference_year is None:
        current_year = datetime.now().year
    elif (
        isinstance(reference_year, bool)
        or not isinstance(reference_year, int)
        or not 1000 <= reference_year <= 9999
    ):
        raise ValueError("reference_year 必须是 1000 到 9999 的整数或 None。")
    else:
        current_year = reference_year
    age = current_year - publication_year
    if age <= 0:
        return 1.0
    if age >= 10:
        return 0.0
    return (10 - age) / 10


def calculate_completeness_score(paper: dict) -> float:
    """
    根据关键字段完整程度计算完整性分。

    参数：
        paper：单篇论文。
    返回：0 到 1 之间的完整性分。
    异常或特殊情况：字段缺失越多，分数越低，但不会补造缺失信息。
    """
    important_fields = [
        "doi",
        "abstract",
        "authors",
        "publication_year",
        "source_name",
        "landing_page_url",
    ]
    present_count = 0
    for field in important_fields:
        if not value_is_missing(paper.get(field)):
            present_count += 1
    return present_count / len(important_fields)


if __name__ == "__main__":
    demo_papers = [
        {
            "title": "Machine Learning for Astronomical Spectra",
            "authors": "Demo Author",
            "publication_year": 2024,
            "doi": "https://doi.org/10.0000/example",
            "abstract": "Machine learning can help classify astronomical spectra.",
            "cited_by_count": 12,
            "source_name": "Demo Journal",
            "openalex_id": "mock-1",
            "landing_page_url": "https://example.org/mock-1",
        }
    ]
    cleaned = clean_papers(demo_papers, "machine learning astronomical spectra")
    unique, duplicates = remove_duplicates(cleaned)
    ranked = add_preliminary_scores(unique, "machine learning astronomical spectra")
    print(f"演示清洗数量：{len(cleaned)}，重复数量：{len(duplicates)}，最高分：{ranked[0]['preliminary_score']}")
