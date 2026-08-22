"""W5 通用 RRF 混合排序融合模块。

RRF（Reciprocal Rank Fusion）是算法无关、只依赖排名的融合方法：

    RRF_score(d) = Σ 1 / (k + rank_i(d))

本模块实现完全通用的 rank-based RRF，不依赖 BM25 / SPECTER2 / Cross-Encoder
的任何特定字段，只读取每个输入 artifact 的 ``pair_id``、``research_query_id``
和 ``rank``，以及 manifest 身份。输入必须是已经通过 W5 validator 的 method
package。输出继续遵守 W5 Method Ranking Contract。
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from typing import Any

from src.w5_method_contract import RANKING_ROWS_PER_QUERY, RRF_K


HYBRID_FAMILY = "hybrid"
RRF_ORDER_SEMANTIC = "order_independent"

# 每个输入 package 必须提供的融合字段（来自 validate_method_output 的结果）。
_REQUIRED_PACKAGE_FIELDS = {
    "method_id",
    "manifest_sha256",
    "ranking_sha256",
    "ranking_rows",
    "candidate_pool_path",
    "research_queries_path",
}


def compute_rrf_score(ranks: list[int], *, k: int = RRF_K) -> Fraction:
    """计算单个文档的 RRF 分数。

    使用精确有理数（fractions.Fraction）累加，避免浮点非结合性导致
    “同一数学结果因输入顺序不同而产生不同浮点值”，从而保证确定性并列。

    ``k`` 仅作为可参数化的数学 helper 保留给单元测试；正式 fusion 路径固定使用
    ``RRF_K = 60``。
    """
    total = Fraction(0)
    for rank in ranks:
        total += Fraction(1, k + rank)
    return total


def validate_fusion_inputs(input_packages: list[dict[str, Any]]) -> None:
    """校验多个 method package 之间的融合一致性。

    不读取 benchmark labels，只检查身份、来源与 pair identity。
    每个输入必须先各自通过 W5 validator；这里只做跨输入的额外校验。
    """
    if not input_packages:
        raise ValueError("RRF 融合至少需要两个输入 method artifact。")
    if len(input_packages) < 2:
        raise ValueError("RRF 融合至少需要两个输入 method artifact。")

    seen_method_ids: set[str] = set()
    seen_manifest_hashes: set[str] = set()
    seen_ranking_hashes: set[str] = set()
    reference_pairs: set[tuple[str, str]] | None = None
    reference_candidate_pool: str | None = None
    reference_research_queries: str | None = None

    for package in input_packages:
        missing = sorted(_REQUIRED_PACKAGE_FIELDS.difference(package))
        if missing:
            raise ValueError("输入 package 缺少融合字段：" + ", ".join(missing) + "。")

        method_id = package["method_id"]
        if method_id in seen_method_ids:
            raise ValueError(f"输入 method_id 重复：{method_id}。")
        seen_method_ids.add(method_id)

        if package["manifest_sha256"] in seen_manifest_hashes:
            raise ValueError(f"同一 manifest 被重复融合（method_id={method_id}）。")
        seen_manifest_hashes.add(package["manifest_sha256"])

        if package["ranking_sha256"] in seen_ranking_hashes:
            raise ValueError(f"同一 ranking artifact 被重复融合（method_id={method_id}）。")
        seen_ranking_hashes.add(package["ranking_sha256"])

        pairs = {
            (row["pair_id"], row["research_query_id"])
            for row in package["ranking_rows"]
        }
        if reference_pairs is None:
            reference_pairs = pairs
        elif pairs != reference_pairs:
            raise ValueError(f"{method_id} 的 pair identity 与其他输入不一致。")

        if reference_candidate_pool is None:
            reference_candidate_pool = str(package["candidate_pool_path"])
        elif str(package["candidate_pool_path"]) != reference_candidate_pool:
            raise ValueError(f"{method_id} 的 Candidate Pool 与其他输入不一致。")

        if reference_research_queries is None:
            reference_research_queries = str(package["research_queries_path"])
        elif str(package["research_queries_path"]) != reference_research_queries:
            raise ValueError(f"{method_id} 的 Research Query 与其他输入不一致。")

    # 每个 RQ 必须 20 条（防重复的显式断言；validator 已保证，但这里再核对 pair identity）。
    query_counts: dict[str, int] = defaultdict(int)
    for pair_id, query_id in reference_pairs or set():
        query_counts[query_id] += 1
    if any(count != RANKING_ROWS_PER_QUERY for count in query_counts.values()):
        raise ValueError(
            "每个 Research Query 必须恰好 20 条：" + str(dict(query_counts)) + "。"
        )


def _ensure_distinct_float_scores(scores: list[Fraction], query_id: str) -> None:
    """拒绝“不同精确分数却序列化为同一 float”的精度碰撞。

    W5 Contract 的 tie-breaking 基于写入 CSV 的 float ``score``，而 rank 由精确
    ``Fraction`` 决定。若两个不同的精确分数在 float 下发生碰撞，序列化后的顺序会与
    精确数学顺序不一致，当前 Contract 无法无损表达，因此 fail closed，而不是生成
    一个数学顺序已经失真的正式 artifact。
    """
    by_float: dict[float, Fraction] = {}
    for score in scores:
        as_float = float(score)
        previous = by_float.setdefault(as_float, score)
        if previous != score:
            raise ValueError(
                f"{query_id} 存在 RRF 分数精度碰撞：两个不同的精确分数 "
                f"{previous} 与 {score} 都序列化为 {as_float!r}，无法在 W5 "
                "Contract 中无损表达排序，已 fail closed。"
            )


def fuse_rankings(
    input_packages: list[dict[str, Any]],
    *,
    output_method_id: str,
) -> dict[str, Any]:
    """把多个已验证的 method package 通过 RRF 融合为一个 hybrid ranking。

    参数：
        input_packages：``validate_method_output()`` 返回结果的列表，至少两个。
        output_method_id：输出 hybrid artifact 的 method_id。

    RRF 常量固定使用 ``RRF_K = 60``（Issue #53），不接受外部传值。

    返回：
        rows：按 (research_query_id, rank) 排好序的 ranking 行；
        rrf_k、input_method_ids、input_manifest_sha256、input_ranking_sha256、
        input_order_semantic 供 manifest provenance 使用。
    """
    validate_fusion_inputs(input_packages)

    ranks_by_pair: dict[str, list[int]] = defaultdict(list)
    query_by_pair: dict[str, str] = {}
    for package in input_packages:
        for row in package["ranking_rows"]:
            pair_id = row["pair_id"]
            ranks_by_pair[pair_id].append(row["rank"])
            query_by_pair[pair_id] = row["research_query_id"]

    scores = {
        pair_id: compute_rrf_score(ranks)
        for pair_id, ranks in ranks_by_pair.items()
    }

    by_query: dict[str, list[tuple[str, Fraction]]] = defaultdict(list)
    for pair_id, score_fraction in scores.items():
        by_query[query_by_pair[pair_id]].append((pair_id, score_fraction))

    rows: list[dict[str, Any]] = []
    for query_id in sorted(by_query):
        pairs = by_query[query_id]
        # tie-breaking 与 W5 contract 一致：score 降序 → pair_id 升序。
        # 用精确 Fraction 比较，避免 float 碰撞改变数学顺序。
        pairs.sort(key=lambda item: (-item[1], item[0]))
        _ensure_distinct_float_scores([score for _, score in pairs], query_id)
        for rank, (pair_id, score_fraction) in enumerate(pairs, start=1):
            rows.append(
                {
                    "pair_id": pair_id,
                    "research_query_id": query_id,
                    "method_id": output_method_id,
                    "score": float(score_fraction),
                    "rank": rank,
                }
            )

    return {
        "rows": rows,
        "rrf_k": RRF_K,
        "input_method_ids": [p["method_id"] for p in input_packages],
        "input_manifest_sha256": {
            p["method_id"]: p["manifest_sha256"] for p in input_packages
        },
        "input_ranking_sha256": {
            p["method_id"]: p["ranking_sha256"] for p in input_packages
        },
        "input_order_semantic": RRF_ORDER_SEMANTIC,
    }
