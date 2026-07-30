"""
两级去重模块说明：

这个文件负责识别确定重复和疑似重复论文。
它在旧 baseline 严格去重（processor.py 的 remove_duplicates）之外提供新增能力，
不会修改旧逻辑。

两级去重：
  - 确定重复（exact）→ 可直接自动合并
  - 疑似重复（suspected）→ 进入人工复核队列，不自动删除

输入需要包含 keyword、run_id、openalex_id、doi、title、authors、publication_year。
输出是确定重复记录、疑似重复对，以及合并后的唯一论文列表。
"""

import hashlib
import re
import uuid
from difflib import SequenceMatcher

from src.utils import current_timestamp, value_is_missing


INVERTED_INDEX_FIELDS = [
    "keyword",
    "run_id",
    "openalex_id",
    "doi",
    "title",
    "authors",
    "publication_year",
    "source_name",
    "landing_page_url",
    "cited_by_count",
    "abstract",
]


def generate_pair_id(left_id: str, right_id: str) -> str:
    """为疑似重复对生成唯一 pair_id，基于左右两侧的 OpenAlex ID。

    参数：
        left_id：左侧论文的 openalex_id。
        right_id：右侧论文的 openalex_id。
    返回：格式为 "SP-" + UUID8 的字符串。
    """
    combined = f"{left_id}|{right_id}"
    short_hash = hashlib.md5(combined.encode("utf-8")).hexdigest()[:8]
    return f"SP-{short_hash}"


def normalize_title(title: str) -> str:
    """激进标准化标题，用于模糊匹配。

    处理：小写、去除 HTML 标签、去除方括号内 arXiv ID、
    统一标点为空格、合并连续空白。

    参数：
        title：原始标题字符串。
    返回：标准化后的标题。
    """
    if not title:
        return ""
    text = title.lower()
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[arxiv[^\]]*\]", "", text)
    text = re.sub(r"arxiv:\s*\d{4}\.\d{4,}(v\d+)?", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize_title(title: str) -> set[str]:
    """将标准化后的标题拆分为词项集合（Jaccard 用）。

    参数：
        title：已完成 normalize_title 的标题。
    返回：长度 ≥ 2 的词项集合。
    """
    if not title:
        return set()
    tokens = set()
    for word in title.split():
        if len(word) >= 2:
            tokens.add(word)
    return tokens


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """计算两个集合的 Jaccard 相似度。

    参数：
        set_a、set_b：两个集合。
    返回：0 到 1 的 Jaccard 系数。两个集合均为空时返回 1.0。
    """
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


def sequence_similarity(a: str, b: str) -> float:
    """计算两个字符串的 SequenceMatcher 相似度。

    参数：
        a、b：两个标准化后的标题字符串。
    返回：0 到 1 的 ratio 值。
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def extract_author_surnames(authors: str) -> list[str]:
    """从分号分隔的作者字符串中提取姓氏（最后一个词）。

    参数：
        authors：用 "; " 分隔的作者字符串。
    返回：小写姓氏列表。
    """
    if not authors or not authors.strip():
        return []
    surnames = []
    for author in authors.split(";"):
        name = author.strip()
        if not name:
            continue
        parts = name.split()
        if parts:
            surname = parts[-1].rstrip(".").lower()
            if len(surname) >= 2:
                surnames.append(surname)
    return surnames


def author_overlap_ratio(surnames_a: list[str], surnames_b: list[str]) -> float:
    """计算两组作者姓氏的 Jaccard 重合度。

    参数：
        surnames_a、surnames_b：姓氏列表。
    返回：0 到 1 的重合比例。两边都为空时返回 1.0。
    """
    set_a = set(surnames_a)
    set_b = set(surnames_b)
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


def normalize_doi(doi: str) -> str:
    """标准化 DOI 用于精确匹配。

    参数：
        doi：原始 DOI 字符串。
    返回：小写、去除 https://doi.org/ 等前缀后的 DOI。
    """
    if not doi:
        return ""
    d = doi.strip().lower()
    prefixes = ["https://doi.org/", "http://doi.org/", "doi.org/", "doi:"]
    for prefix in prefixes:
        if d.startswith(prefix):
            d = d[len(prefix):]
            break
    return d.strip()


def find_exact_duplicates(papers: list[dict]) -> dict:
    """查找确定重复的论文。

    三条规则（优先级依次降低）：
      1. openalex_id 完全相同 → 同一实体返回两次
      2. 非空 DOI 标准化后相同 → 相同论文不同版本
      3. openalex_id 缺失时，标准化标题完全相同 → 缺少稳定标识

    参数：
        papers：包含 keyword、run_id、openalex_id、doi、title 等字段的论文列表。
    返回：
        {
            "exact_duplicates": [...],
            "kept_papers": [...],
            "stats": {"same_openalex_id": N, "same_doi": N, "same_title_no_id": N}
        }
    """
    exact_duplicates = []
    kept_papers = []
    seen_ids = {}
    seen_dois = {}
    seen_titles_no_id = {}

    stats = {"same_openalex_id": 0, "same_doi": 0, "same_title_no_id": 0}

    for paper in papers:
        oa_id = (paper.get("openalex_id") or "").strip()
        doi = normalize_doi(paper.get("doi") or "")
        title_norm = normalize_title(paper.get("title") or "")
        is_duplicate = False

        if oa_id and oa_id in seen_ids:
            record = _build_exact_dup(paper, seen_ids[oa_id], "same_openalex_id")
            exact_duplicates.append(record)
            stats["same_openalex_id"] += 1
            is_duplicate = True

        if not is_duplicate and doi and doi in seen_dois:
            record = _build_exact_dup(paper, seen_dois[doi], "same_doi")
            exact_duplicates.append(record)
            stats["same_doi"] += 1
            is_duplicate = True

        if not is_duplicate and title_norm and title_norm in seen_titles_no_id:
            record = _build_exact_dup(paper, seen_titles_no_id[title_norm], "same_title_no_id")
            exact_duplicates.append(record)
            stats["same_title_no_id"] += 1
            is_duplicate = True

        if not is_duplicate:
            if oa_id:
                seen_ids[oa_id] = paper
            if doi:
                seen_dois[doi] = paper
            if title_norm and not doi:
                seen_titles_no_id[title_norm] = paper
            kept_papers.append(paper)

    return {
        "exact_duplicates": exact_duplicates,
        "kept_papers": kept_papers,
        "stats": stats,
    }


def _build_exact_dup(duplicate_paper: dict, kept_paper: dict, reason: str) -> dict:
    """构造一条确定重复记录。

    参数：
        duplicate_paper：被合并的论文。
        kept_paper：保留的论文。
        reason：去重原因（same_openalex_id / same_doi / same_title_no_id）。
    返回：包含源信息、保留信息、判定规则的字典。
    """
    return {
        "rule": reason,
        "kept_openalex_id": kept_paper.get("openalex_id", ""),
        "kept_title": kept_paper.get("title", ""),
        "merged_openalex_id": duplicate_paper.get("openalex_id", ""),
        "merged_title": duplicate_paper.get("title", ""),
        "source_keyword": [
            kept_paper.get("keyword", ""),
            duplicate_paper.get("keyword", ""),
        ],
        "source_run_id": [
            kept_paper.get("run_id", ""),
            duplicate_paper.get("run_id", ""),
        ],
        "merged_at": current_timestamp(),
    }


def _build_suspected_record(
    left: dict,
    right: dict,
    title_sim: float,
    author_overlap: float,
    year_diff: int,
    doi_relation: str,
    suspected_reason: str,
) -> dict:
    """构造一条疑似重复记录。

    返回字段按 CSV 规范排好顺序。
    """
    pair_id = generate_pair_id(
        left.get("openalex_id", ""),
        right.get("openalex_id", ""),
    )
    return {
        "pair_id": pair_id,
        "left_id": left.get("openalex_id", ""),
        "right_id": right.get("openalex_id", ""),
        "left_title": left.get("title", ""),
        "right_title": right.get("title", ""),
        "title_similarity": round(title_sim, 4),
        "author_overlap": round(author_overlap, 4),
        "year_difference": year_diff,
        "doi_relation": doi_relation,
        "suspected_reason": suspected_reason,
        "recommended_action": "manual_review",
        "review_status": "pending",
        "reviewer_note": "",
        "left_keyword": left.get("keyword", ""),
        "right_keyword": right.get("keyword", ""),
        "left_run_id": left.get("run_id", ""),
        "right_run_id": right.get("run_id", ""),
        "created_at": current_timestamp(),
    }


def find_suspected_duplicates(
    papers: list[dict],
    jaccard_threshold: float = 0.50,
    sequence_threshold: float = 0.65,
) -> dict:
    """查找疑似重复论文对。

    使用轻量、可解释的启发式规则：

      blocking：按 publication_year ± 2 分块，减少 O(n²) 比较。
      主信号：标题 token Jaccard ≥ jaccard_threshold OR
              SequenceMatcher ratio ≥ sequence_threshold
      辅助确认：作者姓氏重合度 ≥ 0.3
      排除规则：两侧均为非空 DOI 且标准化后不同 → 排除

    疑似重复对不删除任何记录，全部进入 review_status=pending。

    参数：
        papers：论文列表。
        jaccard_threshold：标题 Jaccard 阈值，默认 0.50。
        sequence_threshold：SequenceMatcher 阈值，默认 0.65。
    返回：
        {
            "suspected_duplicates": [...],
            "stats": {"pairs_generated": N, "reasons": {...}}
        }
    """
    suspected = []
    reason_counts = {}

    n = len(papers)
    if n < 2:
        return {"suspected_duplicates": [], "stats": {"pairs_generated": 0, "reasons": {}}}

    indexed = list(enumerate(papers))

    for i in range(n):
        pi = papers[i]
        yi = _safe_int(pi.get("publication_year"))
        doi_i = normalize_doi(pi.get("doi") or "")
        title_i_norm = normalize_title(pi.get("title") or "")
        tokens_i = tokenize_title(title_i_norm)
        surnames_i = extract_author_surnames(pi.get("authors") or "")
        oa_id_i = (pi.get("openalex_id") or "").strip()

        for j in range(i + 1, n):
            pj = papers[j]
            yj = _safe_int(pj.get("publication_year"))
            oa_id_j = (pj.get("openalex_id") or "").strip()

            if oa_id_i and oa_id_j and oa_id_i == oa_id_j:
                continue

            if yi is not None and yj is not None and abs(yi - yj) > 2:
                continue

            doi_j = normalize_doi(pj.get("doi") or "")
            if doi_i and doi_j and doi_i != doi_j:
                continue

            title_j_norm = normalize_title(pj.get("title") or "")
            tokens_j = tokenize_title(title_j_norm)
            surnames_j = extract_author_surnames(pj.get("authors") or "")

            jaccard = jaccard_similarity(tokens_i, tokens_j)
            seq_sim = sequence_similarity(title_i_norm, title_j_norm)
            auth_overlap = author_overlap_ratio(surnames_i, surnames_j)
            year_diff = abs(yi - yj) if yi is not None and yj is not None else 999

            if jaccard < jaccard_threshold and seq_sim < sequence_threshold:
                continue

            if auth_overlap < 0.3 and jaccard < 0.80:
                continue

            doi_relation = _classify_doi_relation(doi_i, doi_j)
            reason = _determine_reason(jaccard, seq_sim, auth_overlap, year_diff, doi_relation)

            record = _build_suspected_record(
                left=pi,
                right=pj,
                title_sim=max(jaccard, seq_sim),
                author_overlap=auth_overlap,
                year_diff=year_diff,
                doi_relation=doi_relation,
                suspected_reason=reason,
            )
            suspected.append(record)
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "suspected_duplicates": suspected,
        "stats": {
            "pairs_generated": len(suspected),
            "reasons": reason_counts,
        },
    }


def _safe_int(value: object) -> int | None:
    """安全转为整数，失败返回 None。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _classify_doi_relation(doi_a: str, doi_b: str) -> str:
    """分类两个 DOI 的关系。

    返回：
        both_present_different：两侧均有不同 DOI
        both_present_same：两侧 DOI 相同（应已被精确去重处理）
        both_missing：均无 DOI
        one_missing：一侧有 DOI 另一侧无
        one_arxiv_one_publisher：一侧 arXiv 一侧正式出版
    """
    if not doi_a and not doi_b:
        return "both_missing"
    if not doi_a or not doi_b:
        return "one_missing"
    if doi_a == doi_b:
        return "both_present_same"
    a_is_arxiv = doi_a.startswith("10.48550/") or "arxiv" in doi_a
    b_is_arxiv = doi_b.startswith("10.48550/") or "arxiv" in doi_b
    if (a_is_arxiv and not b_is_arxiv) or (b_is_arxiv and not a_is_arxiv):
        return "one_arxiv_one_publisher"
    return "both_present_different"


def _determine_reason(
    jaccard: float,
    seq_sim: float,
    author_overlap: float,
    year_diff: int,
    doi_relation: str,
) -> str:
    """根据各维度信号给出可解释的疑似原因。"""
    parts = []

    if jaccard >= 0.90 or seq_sim >= 0.95:
        parts.append("title_very_high_similarity")
    elif jaccard >= 0.70 or seq_sim >= 0.85:
        parts.append("title_high_similarity")
    else:
        parts.append("title_moderate_similarity")

    if author_overlap >= 0.70:
        parts.append("author_high_overlap")
    elif author_overlap >= 0.30:
        parts.append("author_moderate_overlap")
    else:
        parts.append("author_low_overlap")

    if year_diff <= 1:
        parts.append("year_close")
    elif year_diff <= 2:
        parts.append("year_nearby")
    else:
        parts.append("year_uncertain")

    if doi_relation == "one_arxiv_one_publisher":
        parts.append("preprint_publisher_pair")

    return "|".join(parts)
