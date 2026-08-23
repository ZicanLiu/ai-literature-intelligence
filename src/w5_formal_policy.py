"""W5 final-closure formal method roster policy.

The public Method Ranking Contract remains algorithm-neutral.  This module adds
the narrower promotion policy for the six artifacts frozen by the W5 final
closure: exact roster, directory/method identity, and the contract version each
official package is expected to use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


FORMAL_METHOD_VERSION_PAIRS = {
    "preliminary_score_v1": ("1.1", "1.1"),
    "tfidf_two_stage_v1": ("1.1", "1.1"),
    "bm25_v1": ("1.0", "1.0"),
    "specter2_adhoc_v1": ("1.0", "1.0"),
    "cross_encoder_msmarco_v1": ("1.0", "1.0"),
    "rrf_bm25_specter2_v1": ("1.0", "1.0"),
}
FORMAL_METHOD_IDS = frozenset(FORMAL_METHOD_VERSION_PAIRS)


def validate_formal_method_roster(
    packages_by_directory: Mapping[str, dict[str, Any]],
) -> None:
    """Validate the exact six-package W5 final promotion set.

    Values must be normalized packages returned by
    :func:`src.w5_method_contract.validate_method_output`.
    """
    directory_ids = set(packages_by_directory)
    missing = sorted(FORMAL_METHOD_IDS.difference(directory_ids))
    unknown = sorted(directory_ids.difference(FORMAL_METHOD_IDS))
    if missing or unknown:
        details = []
        if missing:
            details.append("缺少正式方法目录：" + ", ".join(missing))
        if unknown:
            details.append("存在未知正式方法目录：" + ", ".join(unknown))
        raise ValueError("；".join(details) + "。")

    seen_method_ids: set[str] = set()
    for directory_id in sorted(FORMAL_METHOD_IDS):
        package = packages_by_directory[directory_id]
        method_id = str(package.get("method_id") or "")
        if method_id in seen_method_ids:
            raise ValueError(f"正式方法 method_id 重复：{method_id}。")
        seen_method_ids.add(method_id)
        if method_id != directory_id:
            raise ValueError(
                f"正式目录 {directory_id} 与 manifest method_id "
                f"{method_id!r} 不一致。"
            )

        manifest = package.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError(f"正式方法 {method_id} 缺少已验证 manifest。")
        actual_pair = (
            str(manifest.get("schema_version") or ""),
            str(manifest.get("contract_version") or ""),
        )
        expected_pair = FORMAL_METHOD_VERSION_PAIRS[method_id]
        if actual_pair != expected_pair:
            raise ValueError(
                f"正式方法 {method_id} 的 schema/contract version 必须是 "
                f"{expected_pair[0]}/{expected_pair[1]}，实际为 "
                f"{actual_pair[0]}/{actual_pair[1]}。"
            )
