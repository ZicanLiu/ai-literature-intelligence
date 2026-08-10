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
from copy import deepcopy
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
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def sequence_similarity(a: str, b: str) -> float:
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
    set_a = set(surnames_a)
    set_b = set(surnames_b)
    union = set_a | set_b
    if not union:
        return 0.0
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


PROVENANCE_LIST_FIELDS = (
    "source_query_ids",
    "source_run_ids",
    "source_keywords",
)


def find_exact_duplicates(
    papers: list[dict], *, merge_provenance: bool = False
) -> dict:
    """识别确定重复；可选地把重复来源合并到首条保留记录。

    ``merge_provenance`` 默认关闭，因此旧 CLI 和既有调用的 first-seen 行为
    保持不变。统一 Pipeline 显式开启该选项，把三个 list 型来源字段稳定
    去重合并；除 provenance 外不做 metadata fusion。
    """
    # Pipeline 合并 provenance 时，输出语义是新阶段快照，不能通过共享 dict/list
    # 反向污染 retrieval 阶段的 combined_papers。默认模式继续沿用旧对象语义。
    working_papers = deepcopy(papers) if merge_provenance else papers

    exact_duplicates = []
    kept_papers = []
    seen_ids = {}
    seen_dois = {}
    seen_titles_no_id = {}

    stats = {"same_openalex_id": 0, "same_doi": 0, "same_title_no_id": 0}

    for paper in working_papers:
        oa_id = (paper.get("openalex_id") or "").strip()
        doi = normalize_doi(paper.get("doi") or "")
        title_norm = normalize_title(paper.get("title") or "")
        matches: list[tuple[str, dict]] = []
        if oa_id and oa_id in seen_ids:
            matches.append(("same_openalex_id", seen_ids[oa_id]))
        if doi and doi in seen_dois:
            matches.append(("same_doi", seen_dois[doi]))
        if title_norm and not oa_id and not doi and title_norm in seen_titles_no_id:
            matches.append(("same_title_no_id", seen_titles_no_id[title_norm]))

        matched_entities = {id(kept_paper) for _rule, kept_paper in matches}
        if merge_provenance and len(matched_entities) > 1:
            raise ValueError(
                "确定去重标识冲突：同一记录的 OpenAlex ID 与 DOI 指向不同保留实体；"
                "已停止自动合并，请人工核查。"
            )

        is_duplicate = bool(matches)
        if is_duplicate:
            reason, kept_paper = matches[0]
            record = _build_exact_dup(paper, kept_paper, reason)
            exact_duplicates.append(record)
            stats[reason] += 1
            if merge_provenance:
                _merge_provenance_lists(kept_paper, paper)
                # 已通过可靠 exact identifier 合并后，duplicate 自身携带的其他
                # OpenAlex ID/DOI 也成为同一 kept entity 的 alias，供后续记录命中。
                if oa_id:
                    seen_ids[oa_id] = kept_paper
                if doi:
                    seen_dois[doi] = kept_paper
                if title_norm and not oa_id and not doi:
                    seen_titles_no_id[title_norm] = kept_paper

        if not is_duplicate:
            if oa_id:
                seen_ids[oa_id] = paper
            if doi:
                seen_dois[doi] = paper
            if title_norm and not oa_id and not doi:
                seen_titles_no_id[title_norm] = paper
            kept_papers.append(paper)

    return {
        "exact_duplicates": exact_duplicates,
        "kept_papers": kept_papers,
        "stats": stats,
    }


def _merge_provenance_lists(kept_paper: dict, duplicate_paper: dict) -> None:
    """只合并统一 Pipeline 的 list 型来源字段，并保持首次出现顺序。"""
    for field in PROVENANCE_LIST_FIELDS:
        merged: list[str] = []
        for paper in (kept_paper, duplicate_paper):
            value = paper.get(field, [])
            values = value if isinstance(value, list) else [value]
            for item in values:
                text = str(item).strip() if item is not None else ""
                if text and text not in merged:
                    merged.append(text)
        if merged:
            kept_paper[field] = merged


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
            title_j_norm = normalize_title(pj.get("title") or "")

            if oa_id_i and oa_id_j and oa_id_i == oa_id_j:
                continue

            if not title_i_norm or not title_j_norm:
                continue

            if yi is not None and yj is not None and abs(yi - yj) > 2:
                continue

            doi_j = normalize_doi(pj.get("doi") or "")
            if doi_i and doi_j and doi_i != doi_j:
                continue

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
