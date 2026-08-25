"""W6 generation 进程的递归 No-Leakage guard。

W6 No-Leakage 边界要求 ranking/fusion/synthesis 的 **generation** 不读取
relevance labels / annotations / reviews / adjudications / evaluation metrics 等
反馈信号。仅约束“读哪些文件”不够：合法 whitelist artifact 内的自由-form object
（如 ``retrieval.frozen_configuration``、``pool.policy.parameters``）可以被当作
side-channel 携带 label/metric payload，且全部 hash 可以自洽重算。

本模块提供集中式、可复用的递归 key policy：对 generation 实际读取的每个 JSON
payload 递归遍历（dict / nested dict / list 内 object），发现禁止 key 即 fail closed。

设计约束：

- 使用 **exact key**（统一 lowercase 后精确匹配），**不做 substring 匹配**——
  避免误杀 ``retrieval`` / ``review_state`` / ``reviewer`` / ``source_score`` 等
  合法科研字段；
- 当前 artifact 中合法存在的 score / rank / retrieval provenance 本身不是
  relevance label，不在禁止之列；
- 禁的是 benchmark relevance labels / annotations / reviews / adjudications /
  evaluation metrics 等反馈信号。
"""

from __future__ import annotations

from typing import Any


# generation-readable payload 中禁止出现的 key（lowercase 精确匹配）。
# 复用公共 contract 的 forbidden vocabulary（src/w6_method_contract.py 的
# FORBIDDEN_GENERATION_INPUT_NAMES / FORBIDDEN_RANKING_FIELDS），并补充
# evaluation metric 语义；注意 reviewer/annotator/retrieval_method 是 CSV 字段级
# 禁令，且 reviewer 是 canonical provenance 的合法字段，不在此列。
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


def find_forbidden_keys(value: Any) -> list[str]:
    """递归查找 payload 中的禁止 key，返回点分路径列表（确定性排序）。"""
    hits: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text.lower() in GENERATION_FORBIDDEN_KEYS:
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
