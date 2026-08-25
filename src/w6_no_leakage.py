"""W6 generation 进程的递归 No-Leakage guard。

W6 No-Leakage 边界要求 ranking/fusion/synthesis 的 **generation** 不读取
relevance labels / annotations / reviews / adjudications / evaluation metrics 等
反馈信号。仅约束“读哪些文件”不够：合法 whitelist artifact 内的自由-form object
（如 ``retrieval.frozen_configuration``、``pool.policy.parameters``）可以被当作
side-channel 携带 label/metric payload，且全部 hash 可以自洽重算。

本模块提供集中式、可复用的递归 key policy：对 generation 实际读取的每个 JSON
payload 递归遍历（dict / nested dict / list 内 object），发现禁止 key 即 fail closed。

策略（在 exact-key 基础上增加 token family 识别，而不是无限扩 blacklist）：

1. **exact key**（lowercase 精确匹配）：``GENERATION_FORBIDDEN_KEYS``；
2. **token family**：key lowercase 后按非字母数字切词，命中
   ``GENERATION_FORBIDDEN_TOKENS``（label / judgement / annotation / adjudication /
   review / metric / ndcg / precision / recall / evaluation 及其复数形）即禁止——
   因此 ``gold_label`` / ``relevance_labels`` / ``ndcg_at_10`` / ``precision_at_k`` /
   ``review_results`` / ``evaluation_metrics`` 等单复数或 ``_at_k`` 别名无法绕开；
3. **allowlist 优先**：``GENERATION_ALLOWED_KEYS`` 中的当前合法 provenance key
   （``label_access`` / ``review_state`` / ``reviewer``）不被 token 规则误杀；
   ``retrieval`` / ``source_score`` / ``score_direction`` 等本身不含 forbidden token，
   天然安全。

不防御任意隐写（如 ``foo = 2``）；目标是明显的 label / review / adjudication /
evaluation / metric 语义家族不能以别名绕过。当前 artifact 中合法存在的
score / rank / retrieval provenance 本身不是 relevance label。
"""

from __future__ import annotations

import re
from typing import Any


# exact key 禁止集（lowercase 精确匹配；与公共 contract 的 forbidden vocabulary 对齐）。
GENERATION_FORBIDDEN_KEYS = frozenset(
    {
        "label",
        "labels",
        "relevance_label",
        "final_label",
        "human_label",
        "hidden_label",
        "hidden_labels",
        "hidden_test_label",
        "hidden_test_labels",
        "benchmark_labels",
        "judgement",
        "judgements",
        "annotation",
        "annotations",
        "annotation_result",
        "annotation_results",
        "review",
        "reviews",
        "review_decision",
        "adjudication",
        "metric",
        "metrics",
        "ndcg",
        "precision",
        "recall",
        "evaluation",
        "error_analysis",
    }
)

# token family 禁止集：key 切词后命中即禁止（含单复数形）。
GENERATION_FORBIDDEN_TOKENS = frozenset(
    {
        "label",
        "labels",
        "judgement",
        "judgements",
        "annotation",
        "annotations",
        "adjudication",
        "adjudications",
        "review",
        "reviews",
        "metric",
        "metrics",
        "ndcg",
        "precision",
        "recall",
        "evaluation",
    }
)

# 当前合法的 provenance key（allowlist 优先于 token 规则，防误杀）。
GENERATION_ALLOWED_KEYS = frozenset(
    {
        "label_access",
        "review_state",
        "reviewer",
        "evaluation_started_at",
        "hidden_test_labels_read",
        "relevance_labels_read",
    }
)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _key_tokens(key_lower: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(key_lower) if token]


def is_forbidden_key(key: Any) -> bool:
    """判断单个 key 是否命中 generation No-Leakage 禁令。"""
    key_lower = str(key).lower()
    if key_lower in GENERATION_FORBIDDEN_KEYS:
        return True
    if key_lower in GENERATION_ALLOWED_KEYS:
        return False
    return any(token in GENERATION_FORBIDDEN_TOKENS for token in _key_tokens(key_lower))


def find_forbidden_keys(value: Any) -> list[str]:
    """递归查找 payload 中的禁止 key，返回点分路径列表（确定性排序）。"""
    hits: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if is_forbidden_key(key):
                    hits.append(child_path)
                walk(child, child_path)
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(value, "")
    return sorted(hits)


def assert_no_label_side_channel(payload: Any, *, artifact_label: str) -> None:
    """generation 读取 payload 前的 fail-closed 检查。"""
    hits = find_forbidden_keys(payload)
    if hits:
        raise ValueError(
            f"{artifact_label} 含 generation 禁止的 label/metric side-channel key："
            + ", ".join(hits)
            + "。"
        )
