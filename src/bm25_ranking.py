"""W5 BM25 稀疏排序模块。

该模块为 W5 Pilot 提供经典、透明、可解释的 sparse lexical baseline。它在冻结的
W4 Candidate Pool 上运行：文档是 60 个 record-level pair 的 ``title + abstract``
词项（缺 abstract 时只用 title，pair 保留），查询是每个 Research Query 的显式
``ranking_keyword``。

设计约束（Issue 第七节/第八节）：

1. 分词与文本规范化完全复用 ``src.text_relevance.tokenize_text``，与 TF-IDF
   baseline 保持一致，不新增 query expansion；
2. 参数按 W5 预注册固定为 ``k1=1.5, b=0.75``，写死在模块常量里，不提供调参
   入口，也不得根据 benchmark 指标回调；
3. corpus statistics（文档频率与平均长度）来自冻结池全部 60 条 record-level
   文本；同一论文的 alias 记录保留为独立文档，不合并、不删除；
4. 每个 Research Query 只排序属于该 RQ 的 20 个 pair，排序规则固定为
   ``score desc → pair_id asc``（W5 Method Ranking Contract）。

BM25 只是词法相关性参考线，不代表语义理解，也不能替代人工 Query Relevance
判断。
"""

from __future__ import annotations

import math

from src.text_relevance import tokenize_text


# W5 Pilot 预注册固定参数：目的不是声称最优，而是固定一个透明参数集，
# 避免看到 benchmark 指标后调参。修改它们等于换一个方法，必须换 method_id。
BM25_K1 = 1.5
BM25_B = 0.75

# 排序规则与 W5 Method Ranking Contract 一致：分数降序，同分按 pair_id 升序。
CONTRACT_TIE_BREAKING = ("score_desc", "pair_id_asc")


def build_document_tokens(title: object, abstract: object) -> list[str]:
    """把一对 pair 的标题与摘要拼成一份文档词项列表。

    参数：
        title：论文标题，可能为空或 None。
        abstract：论文摘要，可能为空或 None。
    返回：标题词项与摘要词项按序拼接的列表；缺 abstract 时只保留 title 词项，
        不删除 pair；两者都为空时返回空列表（该文档对任何查询都得 0 分）。
    """
    return tokenize_text(str(title or "")) + tokenize_text(str(abstract or ""))


def compute_corpus_stats(documents: dict[str, list[str]]) -> dict:
    """在固定语料上统计 BM25 所需的语料量。

    参数：
        documents：文档标识（pair_id）到词项列表的映射。W5 中为冻结池全部
            60 条 record-level 文本。
    返回：包含 document_count（N）、document_frequency（df）、doc_lengths 与
        average_length 的字典。
    异常或特殊情况：空语料返回 N=0、average_length=0；长度为 0 的文档计入
        N 与平均长度，但不贡献任何 df。
    """
    document_count = len(documents)
    document_frequency: dict[str, int] = {}
    doc_lengths: dict[str, int] = {}
    for doc_id, tokens in documents.items():
        doc_lengths[doc_id] = len(tokens)
        # 同一词项在同一文档内出现多次，df 只记一次。
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    average_length = (
        sum(doc_lengths.values()) / document_count if document_count else 0.0
    )
    return {
        "document_count": document_count,
        "document_frequency": document_frequency,
        "doc_lengths": doc_lengths,
        "average_length": average_length,
    }


def bm25_idf(document_frequency: int, document_count: int) -> float:
    """标准 Okapi BM25 的非负 IDF：ln(1 + (N - df + 0.5) / (df + 0.5))。

    参数：
        document_frequency：包含该词项的文档数（df），可以为 0。
        document_count：语料文档总数（N）。
    返回：有限的非负 IDF；N=0 时返回 0，避免对空语料赋分。
    """
    if document_count <= 0:
        return 0.0
    return math.log(
        1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
    )


def bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    corpus_stats: dict,
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> float:
    """计算单篇文档对一个查询的 BM25 分数。

    参数：
        query_tokens：查询词项列表（ranking_keyword 经 tokenize_text 拆分）。
        doc_tokens：单篇文档的词项列表。
        corpus_stats：``compute_corpus_stats`` 的返回结果。
        k1：term-frequency saturation 参数，预注册固定为 1.5。
        b：document-length normalization 参数，预注册固定为 0.75。
    返回：非负有限分数，越高越相关；查询或文档为空、查询词全部未登录时
        返回 0.0。
    """
    if not query_tokens or not doc_tokens:
        return 0.0
    document_count = corpus_stats["document_count"]
    average_length = corpus_stats["average_length"]
    if document_count <= 0 or average_length <= 0:
        return 0.0

    term_frequency: dict[str, int] = {}
    for token in doc_tokens:
        term_frequency[token] = term_frequency.get(token, 0) + 1

    doc_length = len(doc_tokens)
    length_norm = 1.0 - b + b * doc_length / average_length
    score = 0.0
    for token in set(query_tokens):
        frequency = term_frequency.get(token, 0)
        if frequency == 0:
            # 文档不包含该查询词项时不贡献分数。
            continue
        idf = bm25_idf(
            corpus_stats["document_frequency"].get(token, 0), document_count
        )
        score += idf * (frequency * (k1 + 1.0)) / (frequency + k1 * length_norm)
    return score


def rank_scored_pairs(scored_pairs: list[tuple[str, float]]) -> list[dict]:
    """按 Contract 规则把 (pair_id, score) 列表转成带 rank 的行。

    排序规则固定为 score 降序、同分按 pair_id 字典序升序；rank 从 1 开始
    连续编号，每个输入恰好得到一个 rank。
    """
    ordered = sorted(scored_pairs, key=lambda item: (-item[1], item[0]))
    return [
        {"pair_id": pair_id, "score": score, "rank": rank}
        for rank, (pair_id, score) in enumerate(ordered, start=1)
    ]


def build_pool_rankings(
    pool_rows: list[dict[str, str]],
    research_queries: dict,
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> list[dict]:
    """在冻结 Candidate Pool 上为全部 Research Query 生成 BM25 排序行。

    参数：
        pool_rows：冻结 Candidate Pool 的全部 60 条 record-level 行。
        research_queries：``load_research_queries`` 的返回结果。
        k1 / b：预注册 BM25 参数，默认即固定值。
    返回：60 个 ``pair_id / research_query_id / score / rank`` 字典，按
        (research_query_id, rank) 排序。corpus statistics 使用全部 60 条
        文本；每个 RQ 只对属于它的 20 个 pair 排名。
    异常或特殊情况：pool 中某 pair 的 RQ 不在正式配置中时抛出 ValueError，
        不允许静默丢弃冻结 pair。
    """
    documents = {
        str(row.get("pair_id") or ""): build_document_tokens(
            row.get("title"), row.get("abstract")
        )
        for row in pool_rows
    }
    corpus_stats = compute_corpus_stats(documents)

    pairs_by_query: dict[str, list[str]] = {}
    for row in pool_rows:
        pair_id = str(row.get("pair_id") or "")
        query_id = str(row.get("research_query_id") or "")
        pairs_by_query.setdefault(query_id, []).append(pair_id)

    rows: list[dict] = []
    for query in research_queries["queries"]:
        query_id = str(query["research_query_id"])
        query_tokens = tokenize_text(str(query["ranking_keyword"]))
        scored = [
            (
                pair_id,
                bm25_score(
                    query_tokens, documents[pair_id], corpus_stats, k1=k1, b=b
                ),
            )
            for pair_id in pairs_by_query.get(query_id, [])
        ]
        for ranked_row in rank_scored_pairs(scored):
            rows.append(
                {
                    "pair_id": ranked_row["pair_id"],
                    "research_query_id": query_id,
                    "score": ranked_row["score"],
                    "rank": ranked_row["rank"],
                }
            )

    covered_pairs = {row["pair_id"] for row in rows}
    missing_pairs = sorted(set(documents).difference(covered_pairs))
    if missing_pairs:
        raise ValueError(
            "Candidate Pool 包含未知 research_query_id 的 pair："
            + ", ".join(missing_pairs)
            + "。"
        )
    rows.sort(key=lambda row: (row["research_query_id"], row["rank"]))
    return rows
