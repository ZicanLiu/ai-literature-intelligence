"""W6 标准化分数融合模块（score-level fusion）。

与 W5 RRF（``src/w5_rank_fusion.py``）只利用 rank 不同，本模块在明确、无标签的
normalization 之后对 raw score 做加权融合：

    fused_score(d) = Σ_i weight_i * normalize_i(raw_score_i(d))

设计约束（Issue #65 / W6 Method Ranking Contract）：

- 输入必须是 >= 2 个已通过 ``validate_w6_method_package`` 的 frozen method package；
- normalization 只能是简单、透明、unsupervised 的策略，且绝不读取 relevance labels；
- 不同 method 的 score scale 差异很大，禁止直接对 raw score 求和；
- 所有 W6 artifact 的 score direction 均为 higher_is_better（由 contract 保证），
  融合前再次显式核对；
- 输出继续遵守 W6 Method Ranking Contract（W5 五列、score desc → pair_id asc、
  每 topic rank 1..N 完整唯一），可以直接被 ``validate_w6_method_package`` 验证。

确定性：输入 method 按 method_id 字典序固定累加顺序（order-independent），排序键为
写入 CSV 的 float 分数本身（``str(float)`` 可无损 round-trip），同分由 pair_id
字典序打破，与 contract 的排序复核完全一致。
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Iterable


NORMALIZATION_STRATEGIES = frozenset({"z_score", "min_max", "robust"})
FIT_SCOPES = frozenset({"per_topic", "global_frozen_pool"})
GLOBAL_SCOPE_KEY = "__global_frozen_pool__"
FUSION_RULE = "weighted_sum"
INPUT_ORDER_SEMANTIC = "method_id_sorted"

# 每种 normalization 策略的冻结参数（写入 manifest score_processing.normalization.parameters）。
NORMALIZATION_PARAMETERS = {
    "z_score": {
        "center": "mean",
        "scale": "std",
        "estimator": "population",
        "ddof": 0,
        "zero_variance": "constant_zero",
    },
    "min_max": {
        "center": "min",
        "scale": "max_minus_min",
        "output_range": [0.0, 1.0],
        "zero_variance": "constant_midpoint",
    },
    "robust": {
        "center": "median",
        "scale": "iqr",
        "quartile_method": "tukey_hinges_exclusive",
        "zero_iqr": "constant_zero",
    },
}

# 每个输入 package 必须提供的融合字段（来自 validate_w6_method_package 的结果）。
_REQUIRED_PACKAGE_FIELDS = {
    "method_id",
    "manifest_sha256",
    "ranking_sha256",
    "ranking_rows",
    "input_references",
}


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _tukey_hinges(sorted_values: list[float]) -> tuple[float, float]:
    """Tukey exclusive hinges：奇数长度时中位数元素不进入上下两半。

    singleton（n=1）明确定义为 ``Q1 = Q3 = median``，从而落入 zero-IQR 规则。
    """
    count = len(sorted_values)
    if count == 1:
        return sorted_values[0], sorted_values[0]
    half = count // 2
    lower = sorted_values[:half]
    upper = sorted_values[count - half :]
    return _median(lower), _median(upper)


def _apply_strategy(values: list[float], strategy: str) -> list[float] | None:
    """在给定向量上应用 normalization；中间量非有限时返回 None（触发缩放重算）。"""
    if strategy == "z_score":
        # z-score 的数值可靠实现：
        # 1) 用 fsum 计算均值（correctly rounded），再以偏差向量计算方差——
        #    大公共 offset 下偏差仍精确（近值相减无精度损失）；
        # 2) 方差在 max(abs(deviation)) 缩放后的偏差上计算，避免平方下溢/溢出；
        # 3) min == max 才是真正的 zero variance；非常量输入但偏差/方差数值
        #    归零 → fail closed，绝不静默误判 zero variance。
        if min(values) == max(values):
            return [0.0] * len(values)
        try:
            mean = math.fsum(values) / len(values)
        except OverflowError:
            return None
        deviations = [value - mean for value in values]
        scale = max(abs(deviation) for deviation in deviations)
        if scale == 0.0:
            raise ValueError("非常量输入的 z-score 偏差数值归零，无法可靠 normalization。")
        scaled = [deviation / scale for deviation in deviations]
        variance = math.fsum(value * value for value in scaled) / len(scaled)
        std = math.sqrt(variance)
        if not math.isfinite(std):
            return None
        if std == 0.0:
            raise ValueError("非常量输入的 z-score variance 数值下溢，无法可靠 normalization。")
        return [value / std for value in scaled]
    if strategy == "min_max":
        low = min(values)
        high = max(values)
        span = high - low
        if not math.isfinite(span):
            return None
        if span == 0.0:
            return [0.5] * len(values)
        return [(value - low) / span for value in values]
    # robust：median / IQR（Tukey exclusive hinges）
    ordered = sorted(values)
    median = _median(ordered)
    q1, q3 = _tukey_hinges(ordered)
    iqr = q3 - q1
    if not math.isfinite(iqr):
        return None
    if iqr == 0.0:
        return [0.0] * len(values)
    return [(value - median) / iqr for value in values]


def normalize_scores(scores: Iterable[float], strategy: str) -> list[float]:
    """对单个 score 向量做无标签 normalization。

    - ``z_score``：``(x - mean) / std``，总体标准差（ddof=0），始终在
      ``max(abs(x))`` 缩放值上计算（scale-equivariant），避免平方下溢/溢出；
      ``min == max`` 才是真 zero variance → 全部 0.0；非常量输入但方差数值
      下溢 → fail closed ``ValueError``；
    - ``min_max``：``(x - min) / (max - min)``；zero variance → 全部 0.5（区间中点）；
    - ``robust``：``(x - median) / IQR``，IQR 为 Tukey exclusive hinges 的 Q3-Q1；
      IQR 为 0 → 全部 0.0；singleton 输入定义为 Q1=Q3=median，落入 zero-IQR 规则。

    极端但合法的 finite 输入（如 ±1e308）会先尝试直接计算；一旦中间量溢出，
    改在 ``max(abs(x))`` 缩放后的值上重算——三种策略都是 scale-equivariant，
    数学结果与未缩放完全一致。非有限输入、以及任何产生非有限结果的情况，
    一律 fail closed（``ValueError``），不会抛出 ``OverflowError``/
    ``StatisticsError`` 或返回 ``nan``。
    """
    if strategy not in NORMALIZATION_STRATEGIES:
        raise ValueError(f"未知 normalization 策略：{strategy}。")
    values = [float(score) for score in scores]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("normalization 输入 score 必须全部有限。")
    if not values:
        raise ValueError("normalization 输入不能为空。")

    try:
        result = _apply_strategy(values, strategy)
    except OverflowError:
        result = None
    if result is None or any(not math.isfinite(value) for value in result):
        # overflow-safe fallback：先缩放到 [-1, 1] 再重算。
        scale = max(abs(value) for value in values)
        if scale == 0.0:
            result = _apply_strategy([0.0] * len(values), strategy)
        else:
            result = _apply_strategy([value / scale for value in values], strategy)
    if result is None or any(not math.isfinite(value) for value in result):
        raise ValueError(f"normalization（{strategy}）产生非有限结果。")
    return result


def validate_fusion_input_packages(input_packages: list[dict[str, Any]]) -> None:
    """校验多个已验证 W6 method package 之间的融合一致性。

    不读取任何 relevance label，只检查身份、来源与 candidate identity。
    每个输入必须先各自通过 ``validate_w6_method_package``；这里只做跨输入校验。
    """
    if not isinstance(input_packages, list) or len(input_packages) < 2:
        raise ValueError("score fusion 至少需要两个输入 method artifact。")

    seen_method_ids: set[str] = set()
    seen_manifest_hashes: set[str] = set()
    seen_ranking_hashes: set[str] = set()
    reference_inputs: dict[str, Any] | None = None
    reference_pairs: set[tuple[str, str]] | None = None

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

        # 所有输入必须绑定完全相同的 topic_set / candidate_pool identity（含 sha256）。
        inputs = package["input_references"]
        if reference_inputs is None:
            reference_inputs = inputs
        elif inputs != reference_inputs:
            raise ValueError(f"{method_id} 的 topic/pool artifact identity 与其他输入不一致。")

        pairs = {
            (row["pair_id"], row["research_query_id"])
            for row in package["ranking_rows"]
        }
        if reference_pairs is None:
            reference_pairs = pairs
        elif pairs != reference_pairs:
            raise ValueError(f"{method_id} 的 candidate identity 与其他输入不一致。")


def _validate_weights(weights: dict[str, Any], method_ids: list[str]) -> dict[str, float]:
    if not isinstance(weights, dict):
        raise ValueError("fusion weights 必须是 method_id → 数值 的映射。")
    expected = set(method_ids)
    actual = set(weights)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"fusion weights 必须精确覆盖输入 method_id：missing={missing}, extra={extra}。"
        )
    normalized: dict[str, float] = {}
    for method_id, value in weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"fusion weight 必须是数值：{method_id}。")
        weight = float(value)
        if not math.isfinite(weight):
            raise ValueError(f"fusion weight 必须有限：{method_id}。")
        normalized[method_id] = weight
    return normalized


def fuse_method_rankings(
    input_packages: list[dict[str, Any]],
    *,
    output_method_id: str,
    strategy: str,
    fit_scope: str,
    weights: dict[str, Any],
) -> dict[str, Any]:
    """把多个已验证的 W6 method package 按标准化分数加权融合为 hybrid ranking。

    参数：
        input_packages：``validate_w6_method_package()`` 返回结果的列表，至少两个；
        output_method_id：输出 hybrid artifact 的 method_id；
        strategy：normalization 策略（``z_score`` / ``min_max`` / ``robust``）；
        fit_scope：``per_topic`` 在 topic 内拟合；``global_frozen_pool`` 在整个冻结
            Candidate Pool 上拟合；
        weights：method_id → 权重，必须精确覆盖全部输入 method_id。

    返回 rows（按 (research_query_id, rank) 排序）与供 manifest provenance 使用的
    normalization/weights/输入 identity 信息。
    """
    if strategy not in NORMALIZATION_STRATEGIES:
        raise ValueError(f"未知 normalization 策略：{strategy}。")
    if fit_scope not in FIT_SCOPES:
        raise ValueError(f"未知 normalization fit_scope：{fit_scope}。")
    validate_fusion_input_packages(input_packages)

    # 固定累加顺序，保证与传入顺序无关（order-independent）。
    ordered_packages = sorted(input_packages, key=lambda package: package["method_id"])
    method_ids = [package["method_id"] for package in ordered_packages]
    normalized_weights = _validate_weights(weights, method_ids)

    def scope_key(topic_id: str) -> str:
        return topic_id if fit_scope == "per_topic" else GLOBAL_SCOPE_KEY

    # 每个 method 在各自 fit scope 内做 normalization。
    normalized_by_method: dict[str, dict[str, float]] = {}
    for package in ordered_packages:
        by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in package["ranking_rows"]:
            by_scope[scope_key(row["research_query_id"])].append(row)
        normalized_scores: dict[str, float] = {}
        for scope_rows in by_scope.values():
            # 同一 scope 内按 pair_id 排序对齐，保证向量化确定。
            scope_rows = sorted(scope_rows, key=lambda row: row["pair_id"])
            values = normalize_scores(
                [float(row["score"]) for row in scope_rows], strategy
            )
            for row, value in zip(scope_rows, values):
                normalized_scores[row["pair_id"]] = value
        normalized_by_method[package["method_id"]] = normalized_scores

    topic_by_pair: dict[str, str] = {}
    fused_scores: dict[str, float] = {}
    for row in ordered_packages[0]["ranking_rows"]:
        topic_by_pair[row["pair_id"]] = row["research_query_id"]
    for pair_id, topic_id in topic_by_pair.items():
        total = 0.0
        for method_id in method_ids:
            total += normalized_weights[method_id] * normalized_by_method[method_id][pair_id]
        if not math.isfinite(total):
            raise ValueError(f"融合分数必须有限：{pair_id}。")
        fused_scores[pair_id] = total

    by_topic: dict[str, list[str]] = defaultdict(list)
    for pair_id, topic_id in topic_by_pair.items():
        by_topic[topic_id].append(pair_id)

    rows: list[dict[str, Any]] = []
    for topic_id in sorted(by_topic):
        pair_ids = by_topic[topic_id]
        # tie-breaking 与 W6 contract 一致：score 降序 → pair_id 升序；
        # 排序键使用写入 CSV 的 float 本身，与 contract 复核完全一致。
        pair_ids.sort(key=lambda pair_id: (-fused_scores[pair_id], pair_id))
        for rank, pair_id in enumerate(pair_ids, start=1):
            rows.append(
                {
                    "pair_id": pair_id,
                    "research_query_id": topic_id,
                    "method_id": output_method_id,
                    "score": fused_scores[pair_id],
                    "rank": rank,
                }
            )

    return {
        "rows": rows,
        "strategy": strategy,
        "fit_scope": fit_scope,
        "normalization_parameters": dict(NORMALIZATION_PARAMETERS[strategy]),
        "weights": normalized_weights,
        "input_method_ids": method_ids,
        "input_manifest_sha256": {
            package["method_id"]: package["manifest_sha256"]
            for package in ordered_packages
        },
        "input_ranking_sha256": {
            package["method_id"]: package["ranking_sha256"]
            for package in ordered_packages
        },
        "input_order_semantic": INPUT_ORDER_SEMANTIC,
    }
