"""W6 evidence-grounded literature synthesis 原型流水线。

实现 Issue #65 Part B 的最小闭环：

    Research Question + Frozen Ranked Papers
    → Evidence Extraction → Structured Claims
    → Claim ↔ Paper ↔ Evidence → Human-readable Mini Review

设计约束：

- 输入必须是已验证、冻结的 ranked-paper selection（W6 method package + pool item）；
- 本模块提供 deterministic fake backend，保证自动测试完全离线；不内置任何真实
  LLM client、不读取 ``.env``、不引入模型 SDK 依赖；
- evidence 只使用 title/abstract 短 snippet（<= 800 字符）与 structured metadata，
  不复制整篇 PDF 或大段受版权保护正文；
- 机器抽取的 evidence 默认 ``extracted``（未经人工核验），因此只能支撑
  ``partially_supported`` claim；``supported``/``verified`` 必须全部来自
  ``human_verified`` evidence（由 ``src/w6_synthesis_contract.py`` 强制）；
- Markdown mini review 只是 structured claims 的 render，不引入额外事实主张；
- relevance score 不等于 factual correctness，本模块绝不把 ranking 分数当作
  claim 的真实性依据。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from src.w6_contracts import W6_SCHEMA_VERSION
from src.w6_synthesis_contract import (
    MAX_SNIPPET_CHARACTERS,
    validate_structured_synthesis,
)


COPYRIGHT_POLICY = "short_public_snippets_or_structured_fields_only"
EVIDENCE_TOOL_NAME = "w6_synthesis_pipeline"
EVIDENCE_TOOL_VERSION = "0.1"
FAKE_BACKEND_NAME = "deterministic_fake"
FAKE_BACKEND_VERSION = "1.0"
SNIPPET_ELLIPSIS = "..."


class SynthesisBackend(Protocol):
    """provider-agnostic 的 synthesis backend 接口。

    真实 LLM backend 应以独立模块实现本接口并自行管理凭据；核心流水线只依赖
    本 Protocol，保证离线测试始终可以走 ``DeterministicFakeBackend``。
    """

    name: str
    version: str

    def generate_claims(
        self,
        *,
        research_question: str,
        selected_entity_ids: set[str],
        evidence: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """从 evidence units 生成 structured claims（含 claim_id）。"""
        ...


def _claim_sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


class DeterministicFakeBackend:
    """完全离线、确定性的 fake synthesis backend。

    规则透明：每条非 rejected 的 evidence 生成一条 claim，claim 文本直接取自
    evidence 内容本身（不允许自由发挥）；``human_verified`` evidence 产出
    ``supported``/``verified``，其余产出 ``partially_supported``/``incomplete``。
    """

    name = FAKE_BACKEND_NAME
    version = FAKE_BACKEND_VERSION

    def generate_claims(
        self,
        *,
        research_question: str,
        selected_entity_ids: set[str],
        evidence: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        for evidence_id in sorted(evidence):
            unit = evidence[evidence_id]
            entity_id = unit["paper_identity"]["canonical_entity_id"]
            if entity_id not in selected_entity_ids:
                continue
            if unit["extraction_status"] == "rejected":
                continue
            record_id = unit["paper_identity"]["record_id"]
            content = unit["content"]
            if content["snippet"] is not None:
                claim_text = _claim_sentence(
                    f"Paper {record_id} reports: {content['snippet']}"
                )
            else:
                field = content["structured_field"]
                claim_text = (
                    f"Paper {record_id} metadata indicates "
                    f"{field['name']} = {field['value']}."
                )
            if unit["extraction_status"] == "human_verified":
                support_status = "supported"
                citation_status = "verified"
            else:
                support_status = "partially_supported"
                citation_status = "incomplete"
            claims.append(
                {
                    "claim_id": f"claim_{len(claims) + 1:03d}",
                    "claim_text": claim_text,
                    "supporting_canonical_entity_ids": [entity_id],
                    "evidence_refs": [evidence_id],
                    "confidence": unit["confidence"],
                    "support_status": support_status,
                    "citation_status": citation_status,
                }
            )
        return claims


def truncate_snippet(text: str) -> str:
    """把 snippet 截断到版权安全上限以内。"""
    if len(text) <= MAX_SNIPPET_CHARACTERS:
        return text
    return text[: MAX_SNIPPET_CHARACTERS - len(SNIPPET_ELLIPSIS)] + SNIPPET_ELLIPSIS


def build_evidence_units(
    records: Mapping[str, dict[str, Any]],
    canonical: Mapping[str, Any],
    selected_record_ids: list[str],
    *,
    artifact_id: str,
    created_at: str,
    git_revision: str,
    is_fixture: bool = False,
) -> dict[str, Any]:
    """为 selected papers 从 source records 确定性抽取结构化 evidence。

    有 abstract 的记录产出 ``abstract_snippet``（<= 800 字符）；缺失 abstract 的记录
    产出 ``structured_metadata``（``abstract_present = false``）。所有机器抽取结果
    一律标记为 ``extracted``，不得伪装成 ``human_verified``。
    """
    units: list[dict[str, Any]] = []
    for record_id in selected_record_ids:
        record = records[record_id]
        entity_id = canonical["entity_by_record"][record_id]
        abstract = record.get("abstract")
        if isinstance(abstract, str) and abstract.strip():
            content = {"snippet": truncate_snippet(abstract.strip()), "structured_field": None}
            evidence_type = "abstract_snippet"
            source_location = {
                "source_type": "public_abstract",
                "source_reference": record.get("landing_page_url") or f"record:{record_id}",
                "locator": "abstract",
            }
            extraction_method = "deterministic_abstract_excerpt"
            confidence = "medium"
        else:
            content = {
                "snippet": None,
                "structured_field": {"name": "abstract_present", "value": False},
            }
            evidence_type = "structured_metadata"
            source_location = {
                "source_type": "source_record",
                "source_reference": f"record:{record_id}",
                "locator": "metadata_completeness",
            }
            extraction_method = "deterministic_field_projection"
            confidence = "high"
        units.append(
            {
                "evidence_id": f"ev_{record_id}",
                "paper_identity": {
                    "canonical_entity_id": entity_id,
                    "record_id": record_id,
                },
                "evidence_type": evidence_type,
                "source_location": source_location,
                "content": content,
                "provenance": {
                    "extraction_method": extraction_method,
                    "model_or_tool": {
                        "name": EVIDENCE_TOOL_NAME,
                        "version": EVIDENCE_TOOL_VERSION,
                    },
                    "extracted_at": created_at,
                    "source_license_note": (
                        "Short public abstract snippet or structured metadata only; "
                        "no full text stored."
                    ),
                },
                "extraction_status": "extracted",
                "confidence": confidence,
            }
        )
    return {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_evidence_units",
        "artifact_id": artifact_id,
        "is_fixture": is_fixture,
        "copyright_policy": COPYRIGHT_POLICY,
        "created_at": created_at,
        "provenance": {
            "kind": "deterministic_evidence_extraction",
            "created_by": EVIDENCE_TOOL_NAME,
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "evidence_units": units,
    }


def build_synthesis_input(
    *,
    topic_id: str,
    topics: Mapping[str, dict[str, Any]],
    package: Mapping[str, Any],
    top_n: int,
    references: Mapping[str, Mapping[str, str]],
    artifact_id: str,
    synthesis_input_id: str,
    created_at: str,
    git_revision: str,
    is_fixture: bool = False,
) -> dict[str, Any]:
    """从一个已验证 frozen method package 构造 rank-ordered synthesis selection。

    ``references`` 必须提供 ``topic_artifact`` / ``paper_metadata`` /
    ``source_provenance`` / ``evidence_units`` 四个 ``{artifact_id, sha256}`` 引用。
    """
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        raise ValueError("top_n 必须是正整数。")
    topic = topics.get(topic_id)
    if topic is None:
        raise ValueError(f"未知 topic：{topic_id}。")
    missing_refs = sorted(
        {"topic_artifact", "paper_metadata", "source_provenance", "evidence_units"}
        - set(references)
    )
    if missing_refs:
        raise ValueError("synthesis input references 不完整：" + ", ".join(missing_refs) + "。")

    topic_rows = [
        row
        for row in package["ranking_rows"]
        if row["research_query_id"] == topic_id
    ]
    topic_rows.sort(key=lambda row: row["rank"])
    selected = [row["pair_id"] for row in topic_rows[:top_n]]
    if not selected:
        raise ValueError(f"topic {topic_id} 在 ranked list 中没有候选。")

    return {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_synthesis_input",
        "artifact_id": artifact_id,
        "is_fixture": is_fixture,
        "synthesis_input_id": synthesis_input_id,
        "topic": {
            "topic_id": topic_id,
            "research_question": topic["research_question"],
            "topic_artifact": dict(references["topic_artifact"]),
        },
        "ranked_papers": {
            "method_manifest_artifact_id": package["artifact_id"],
            "manifest_sha256": package["manifest_sha256"],
            "ranking_sha256": package["ranking_sha256"],
            "method_id": package["method_id"],
            "status": "frozen",
        },
        "selected_pool_item_ids": selected,
        "paper_metadata": dict(references["paper_metadata"]),
        "source_provenance": dict(references["source_provenance"]),
        "evidence_units": dict(references["evidence_units"]),
        "created_at": created_at,
        "provenance": {
            "kind": "deterministic_synthesis_input",
            "created_by": EVIDENCE_TOOL_NAME,
            "created_at": created_at,
            "git_revision": git_revision,
        },
    }


def render_mini_review(claims: Mapping[str, dict[str, Any]]) -> str:
    """仅从 structured claims 渲染 Markdown 文本（每句绑定 claim_id 引用）。"""
    sentences = []
    for claim_id in sorted(claims):
        claim = claims[claim_id]
        sentences.append(f"{_claim_sentence(claim['claim_text'])} [{claim_id}]")
    return " ".join(sentences)


def audit_unsupported_claims(claims: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    """输出 unsupported / 部分支持 claim 的审计清单。

    检测职责：contract validator 负责 fail closed；本函数负责把风险显式呈现给人工。
    """
    unsupported = sorted(
        claim_id
        for claim_id, claim in claims.items()
        if claim["support_status"] == "unsupported"
    )
    partial = sorted(
        claim_id
        for claim_id, claim in claims.items()
        if claim["support_status"] == "partially_supported"
    )
    no_evidence = sorted(
        claim_id for claim_id, claim in claims.items() if not claim["evidence_refs"]
    )
    return {
        "claim_count": len(claims),
        "supported_claim_ids": sorted(
            claim_id
            for claim_id, claim in claims.items()
            if claim["support_status"] == "supported"
        ),
        "partially_supported_claim_ids": partial,
        "unsupported_claim_ids": unsupported,
        "claims_without_evidence": no_evidence,
        "note": (
            "unsupported / partially_supported claim 不得表述为已验证事实；"
            "relevance score 不代表 factual correctness。"
        ),
    }


def generate_structured_synthesis(
    backend: SynthesisBackend,
    *,
    synthesis_input: Mapping[str, Any],
    evidence: Mapping[str, dict[str, Any]],
    canonical: Mapping[str, Any],
    artifact_id: str,
    synthesis_id: str,
    created_at: str,
    git_revision: str,
    is_fixture: bool = False,
) -> dict[str, Any]:
    """用 backend 生成 structured synthesis，并在返回前通过 contract validator。

    fail closed：任何 claim/evidence/selection 闭包破坏都会在这里抛错，
    不会把未验证的 payload 交给调用方。
    """
    claims_list = backend.generate_claims(
        research_question=synthesis_input["payload"]["topic"]["research_question"],
        selected_entity_ids=set(synthesis_input["selected_entity_ids"]),
        evidence=evidence,
    )
    if not claims_list:
        raise ValueError("backend 没有为 selection 生成任何 claim。")
    claims = {claim["claim_id"]: claim for claim in claims_list}
    rendered_text = render_mini_review(claims)
    payload = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_structured_synthesis",
        "artifact_id": artifact_id,
        "is_fixture": is_fixture,
        "synthesis_id": synthesis_id,
        "synthesis_input_id": synthesis_input["payload"]["synthesis_input_id"],
        "synthesis_input": {
            "artifact_id": synthesis_input["artifact_id"],
            "sha256": synthesis_input["artifact_sha256"],
        },
        "claims": claims_list,
        "rendered_review": {
            "format": "markdown",
            "text": rendered_text,
            "generated_from_claim_ids": [claim["claim_id"] for claim in claims_list],
        },
        "generation_provenance": {
            "kind": "deterministic_fake_backend",
            "created_by": f"{backend.name} {backend.version}",
            "created_at": created_at,
            "git_revision": git_revision,
        },
    }
    validated_claims = validate_structured_synthesis(
        payload,
        synthesis_input=synthesis_input,
        evidence=evidence,
        canonical=canonical,
    )
    return {
        "payload": payload,
        "claims": validated_claims,
        "rendered_review": rendered_text,
        "audit": audit_unsupported_claims(validated_claims),
    }
