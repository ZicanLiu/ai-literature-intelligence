"""Deterministic Boundary-Aware ranking prototype for W6.

The prototype is deliberately small and label-free.  It combines a transparent
per-topic BM25 relevance component with four structured compatibility dimensions
and explicit scope-out/boundary overlap penalties.  A backend protocol keeps the
scoring formulation testable with a deterministic fake backend; the default
backend is lexical and requires no model download or network access.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.annotation_tasks import sha256_file, write_csv_rows
from src.bm25_ranking import (
    BM25_B,
    BM25_K1,
    bm25_score,
    build_document_tokens,
    compute_corpus_stats,
    rank_scored_pairs,
)
from src.text_relevance import tokenize_text
from src.w5_method_contract import RANKING_FIELDS
from src.w6_method_contract import (
    compute_method_configuration_hash,
    validate_w6_method_package,
)
from src.w6_contracts import load_json_object


BOUNDARY_DIMENSIONS = (
    "scientific_object",
    "data_modality",
    "target_task",
    "method_role",
)
DEFAULT_METHOD_ID = "boundary_aware_structured_lexical_v1"
DEFAULT_ARTIFACT_ID = "w6_boundary_aware_structured_lexical_v1"

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "their",
        "to",
        "using",
        "with",
    }
)


@dataclass(frozen=True)
class BoundaryRankingConfig:
    """Frozen, label-independent scoring configuration."""

    relevance_weight: float = 0.60
    compatibility_weight: float = 0.40
    boundary_penalty: float = 0.50
    scientific_object_weight: float = 0.25
    data_modality_weight: float = 0.25
    target_task_weight: float = 0.25
    method_role_weight: float = 0.25
    bm25_k1: float = BM25_K1
    bm25_b: float = BM25_B
    missing_abstract_policy: str = "retain_with_title_only_no_missingness_penalty"

    def validate(self) -> None:
        numeric = asdict(self)
        for name, value in numeric.items():
            if name == "missing_abstract_policy":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Boundary config {name} 必须是 finite number。")
            if not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"Boundary config {name} 必须是非负 finite number。")
        if not math.isclose(
            self.relevance_weight + self.compatibility_weight,
            1.0,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("relevance/compatibility weights 必须和为 1。")
        dimension_sum = sum(self.dimension_weights.values())
        if not math.isclose(dimension_sum, 1.0, rel_tol=0, abs_tol=1e-12):
            raise ValueError("四个 boundary dimension weights 必须和为 1。")
        if self.missing_abstract_policy != "retain_with_title_only_no_missingness_penalty":
            raise ValueError("missing abstract policy 不得删除或凭空惩罚 candidate。")

    @property
    def dimension_weights(self) -> dict[str, float]:
        return {
            "scientific_object": self.scientific_object_weight,
            "data_modality": self.data_modality_weight,
            "target_task": self.target_task_weight,
            "method_role": self.method_role_weight,
        }


@dataclass(frozen=True)
class BoundaryAssessment:
    dimension_scores: Mapping[str, float]
    scope_out_overlap: float
    boundary_case_overlap: float
    missing_abstract: bool
    evidence_summary: str


class BoundaryCompatibilityBackend(Protocol):
    name: str
    version: str

    def assess(
        self,
        *,
        topic: Mapping[str, Any],
        record: Mapping[str, Any],
        pool_item_id: str,
    ) -> BoundaryAssessment: ...


class DeterministicLexicalBoundaryBackend:
    """Structured lexical decomposition with no external model or label access."""

    name = "deterministic_structured_lexical_boundary"
    version = "1.0"

    def assess(
        self,
        *,
        topic: Mapping[str, Any],
        record: Mapping[str, Any],
        pool_item_id: str,
    ) -> BoundaryAssessment:
        del pool_item_id
        candidate_tokens = _content_tokens(
            f"{record.get('title') or ''} {record.get('abstract') or ''}"
        )
        dimension_scores = {
            dimension: _coverage_score(
                _content_tokens(topic[dimension]), candidate_tokens
            )
            for dimension in BOUNDARY_DIMENSIONS
        }
        scope_out_overlap = _maximum_statement_overlap(
            topic["scope_out"], candidate_tokens
        )
        boundary_overlap = _maximum_statement_overlap(
            topic["boundary_cases"], candidate_tokens
        )
        matched = [
            dimension
            for dimension, score in dimension_scores.items()
            if score >= 0.5
        ]
        evidence = (
            "Structured lexical compatibility matched dimensions: "
            + (", ".join(matched) if matched else "none")
            + "; scope-out and boundary overlaps were computed from frozen Topic text."
        )
        return BoundaryAssessment(
            dimension_scores=dimension_scores,
            scope_out_overlap=scope_out_overlap,
            boundary_case_overlap=boundary_overlap,
            missing_abstract=record.get("abstract") is None,
            evidence_summary=evidence,
        )


class DeterministicFakeBoundaryBackend:
    """Explicit fixed assessments for offline unit tests and synthetic fixtures."""

    name = "deterministic_fake_boundary"
    version = "fixture-v1"

    def __init__(self, assessments: Mapping[str, BoundaryAssessment]) -> None:
        self._assessments = dict(assessments)

    def assess(
        self,
        *,
        topic: Mapping[str, Any],
        record: Mapping[str, Any],
        pool_item_id: str,
    ) -> BoundaryAssessment:
        del topic, record
        try:
            return self._assessments[pool_item_id]
        except KeyError as error:
            raise ValueError(
                f"fake boundary backend 缺少 assessment：{pool_item_id}。"
            ) from error


def load_boundary_ranking_config(path: str | Path) -> BoundaryRankingConfig:
    """Load the preregistered Issue #64 config without accepting label-aware fields."""
    payload = load_json_object(path, label="W6 Boundary-Aware config")
    expected_fields = {
        "schema_version",
        "artifact_type",
        "artifact_id",
        "status",
        "is_fixture",
        "method_id",
        "frozen_at",
        "frozen_before_w6_evaluation",
        "historical_diagnostic_use",
        "options_considered",
        "selected_option",
        "selection_reason",
        "scoring",
        "backend",
        "input_policy",
        "limitations",
        "provenance",
    }
    if set(payload) != expected_fields:
        raise ValueError("Boundary-Aware frozen config fields 不完整或含额外字段。")
    if (
        payload["schema_version"] != "0.2-alpha"
        or payload["artifact_type"] != "w6_boundary_aware_ranking_config"
        or payload["status"] != "frozen"
        or payload["is_fixture"] is not False
        or payload["method_id"] != DEFAULT_METHOD_ID
        or payload["frozen_before_w6_evaluation"] is not True
    ):
        raise ValueError("Boundary-Aware config header/freeze identity 非法。")
    _require_method_id(str(payload["artifact_id"]))
    _require_datetime(str(payload["frozen_at"]), "Boundary config frozen_at")

    diagnostic = payload["historical_diagnostic_use"]
    if not isinstance(diagnostic, dict) or set(diagnostic) != {
        "source",
        "purpose",
        "runtime_input",
        "independent_validation_claimed",
    }:
        raise ValueError("Boundary historical diagnostic declaration 不完整。")
    if diagnostic["runtime_input"] is not False or diagnostic[
        "independent_validation_claimed"
    ] is not False:
        raise ValueError("W5 diagnostics 只能用于 hypothesis generation。")

    options = payload["options_considered"]
    if not isinstance(options, list) or len(options) < 3:
        raise ValueError("Boundary config 必须保留多方案比较。")
    option_ids: set[str] = set()
    for option in options:
        if not isinstance(option, dict) or set(option) != {
            "option_id",
            "deterministic",
            "external_model",
            "decision",
            "tradeoff",
        }:
            raise ValueError("Boundary option comparison schema 非法。")
        option_id = option["option_id"]
        if not isinstance(option_id, str) or not option_id or option_id in option_ids:
            raise ValueError("Boundary option_id 非法或重复。")
        option_ids.add(option_id)
    if payload["selected_option"] not in option_ids:
        raise ValueError("Boundary selected option 未出现在方案比较中。")
    if not isinstance(payload["selection_reason"], str) or not payload["selection_reason"]:
        raise ValueError("Boundary selection reason 不能为空。")

    scoring = payload["scoring"]
    expected_scoring = set(asdict(BoundaryRankingConfig()))
    if not isinstance(scoring, dict) or set(scoring) != expected_scoring:
        raise ValueError("Boundary scoring config roster 不完整。")
    configuration = BoundaryRankingConfig(**scoring)
    configuration.validate()

    backend = payload["backend"]
    if not isinstance(backend, dict) or backend != {
        "name": DeterministicLexicalBoundaryBackend.name,
        "version": DeterministicLexicalBoundaryBackend.version,
        "external_model": False,
        "network_access": False,
    }:
        raise ValueError("Boundary default backend declaration 非法。")
    input_policy = payload["input_policy"]
    if not isinstance(input_policy, dict) or set(input_policy) != {
        "required_inputs",
        "source_records_auxiliary_input_required",
        "relevance_labels_read",
        "hidden_test_labels_read",
        "metrics_read",
    }:
        raise ValueError("Boundary input policy schema 非法。")
    if input_policy["required_inputs"] != [
        "topic_set",
        "candidate_pool",
        "source_records",
    ]:
        raise ValueError("Boundary runtime input roster 非法。")
    if input_policy["source_records_auxiliary_input_required"] is not True or any(
        input_policy[name] is not False
        for name in ("relevance_labels_read", "hidden_test_labels_read", "metrics_read")
    ):
        raise ValueError("Boundary config 违反 source-record/no-label policy。")
    limitations = payload["limitations"]
    if not isinstance(limitations, list) or not limitations or not all(
        isinstance(item, str) and item for item in limitations
    ):
        raise ValueError("Boundary limitations 必须显式记录。")
    provenance = payload["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != {
        "kind",
        "created_by",
        "created_at",
        "git_revision",
    }:
        raise ValueError("Boundary config provenance 不完整。")
    _require_datetime(str(provenance["created_at"]), "Boundary config provenance time")
    _require_git_revision(str(provenance["git_revision"]))
    return configuration


def build_boundary_aware_rankings(
    *,
    topics: Mapping[str, dict[str, Any]],
    pool_members: Mapping[str, dict[str, Any]],
    records: Mapping[str, dict[str, Any]],
    backend: BoundaryCompatibilityBackend,
    method_id: str = DEFAULT_METHOD_ID,
    config: BoundaryRankingConfig | None = None,
) -> dict[str, Any]:
    """Generate W5-column-compatible rows without accepting any label input."""
    configuration = config or BoundaryRankingConfig()
    configuration.validate()
    _require_method_id(method_id)
    if not pool_members:
        raise ValueError("Boundary-Aware ranking 需要非空 frozen Candidate Pool。")

    documents: dict[str, list[str]] = {}
    by_topic: dict[str, list[str]] = defaultdict(list)
    for pool_item_id, member in pool_members.items():
        topic_id = member.get("topic_id")
        record_id = member.get("record_id")
        if topic_id not in topics or record_id not in records:
            raise ValueError(f"Boundary ranking candidate identity mismatch：{pool_item_id}。")
        record = records[record_id]
        documents[pool_item_id] = build_document_tokens(
            record.get("title"), record.get("abstract")
        )
        by_topic[topic_id].append(pool_item_id)
    corpus_stats = compute_corpus_stats(documents)

    raw_lexical: dict[str, float] = {}
    assessments: dict[str, BoundaryAssessment] = {}
    for topic_id in sorted(by_topic):
        topic = topics[topic_id]
        query_tokens = tokenize_text(_structured_query_text(topic))
        for pool_item_id in sorted(by_topic[topic_id]):
            raw_lexical[pool_item_id] = bm25_score(
                query_tokens,
                documents[pool_item_id],
                corpus_stats,
                k1=configuration.bm25_k1,
                b=configuration.bm25_b,
            )
            record = records[pool_members[pool_item_id]["record_id"]]
            assessment = backend.assess(
                topic=topic,
                record=record,
                pool_item_id=pool_item_id,
            )
            _validate_assessment(assessment, pool_item_id)
            assessments[pool_item_id] = assessment

    normalized_lexical: dict[str, float] = {}
    for topic_id, item_ids in by_topic.items():
        values = [raw_lexical[item_id] for item_id in item_ids]
        minimum = min(values)
        maximum = max(values)
        for item_id in item_ids:
            normalized_lexical[item_id] = (
                0.0
                if math.isclose(maximum, minimum, rel_tol=0, abs_tol=1e-15)
                else (raw_lexical[item_id] - minimum) / (maximum - minimum)
            )

    scored_by_topic: dict[str, list[tuple[str, float]]] = defaultdict(list)
    diagnostics: dict[str, dict[str, Any]] = {}
    for pool_item_id, member in pool_members.items():
        assessment = assessments[pool_item_id]
        compatibility = sum(
            configuration.dimension_weights[dimension]
            * float(assessment.dimension_scores[dimension])
            for dimension in BOUNDARY_DIMENSIONS
        )
        mismatch = max(
            float(assessment.scope_out_overlap),
            float(assessment.boundary_case_overlap),
        )
        score = (
            configuration.relevance_weight * normalized_lexical[pool_item_id]
            + configuration.compatibility_weight * compatibility
            - configuration.boundary_penalty * mismatch
        )
        if not math.isfinite(score):
            raise ValueError(f"Boundary score 非 finite：{pool_item_id}。")
        scored_by_topic[member["topic_id"]].append((pool_item_id, score))
        diagnostics[pool_item_id] = {
            "topic_id": member["topic_id"],
            "record_id": member["record_id"],
            "raw_bm25": raw_lexical[pool_item_id],
            "normalized_relevance": normalized_lexical[pool_item_id],
            "dimension_scores": dict(assessment.dimension_scores),
            "compatibility": compatibility,
            "scope_out_overlap": assessment.scope_out_overlap,
            "boundary_case_overlap": assessment.boundary_case_overlap,
            "mismatch": mismatch,
            "missing_abstract": assessment.missing_abstract,
            "score": score,
            "evidence_summary": assessment.evidence_summary,
        }

    rows: list[dict[str, Any]] = []
    for topic_id in sorted(scored_by_topic):
        for ranked in rank_scored_pairs(scored_by_topic[topic_id]):
            rows.append(
                {
                    "pair_id": ranked["pair_id"],
                    "research_query_id": topic_id,
                    "method_id": method_id,
                    "score": ranked["score"],
                    "rank": ranked["rank"],
                }
            )
    return {
        "rows": rows,
        "diagnostics": diagnostics,
        "config": configuration,
        "backend": {"name": backend.name, "version": backend.version},
    }


def build_w6_boundary_method_package(
    *,
    topics: Mapping[str, dict[str, Any]],
    pool_members: Mapping[str, dict[str, Any]],
    records: Mapping[str, dict[str, Any]],
    artifact_registry: Mapping[str, dict[str, str]],
    topic_reference: Mapping[str, str],
    candidate_pool_reference: Mapping[str, str],
    source_records_reference: Mapping[str, str],
    output_dir: str | Path,
    is_fixture: bool,
    generated_at: str,
    frozen_at: str,
    git_revision: str,
    git_worktree_clean: bool,
    backend: BoundaryCompatibilityBackend | None = None,
    method_id: str = DEFAULT_METHOD_ID,
    artifact_id: str = DEFAULT_ARTIFACT_ID,
    config: BoundaryRankingConfig | None = None,
) -> Path:
    """Generate, self-validate, and publish one frozen W6 method package."""
    _require_method_id(method_id)
    _require_method_id(artifact_id)
    _require_datetime(generated_at, "boundary generated_at")
    _require_datetime(frozen_at, "boundary frozen_at")
    if _parse_datetime(frozen_at) < _parse_datetime(generated_at):
        raise ValueError("Boundary method frozen_at 不得早于 generated_at。")
    _require_git_revision(git_revision)
    if git_worktree_clean is not True:
        raise ValueError("Boundary-Aware frozen package 必须从 clean Git snapshot 生成。")
    for label, reference in (
        ("topic_set", topic_reference),
        ("candidate_pool", candidate_pool_reference),
        ("source_records", source_records_reference),
    ):
        trusted = artifact_registry.get(reference.get("artifact_id"))
        if trusted != dict(reference):
            raise ValueError(f"Boundary method {label} input identity/hash drift。")

    active_backend = backend or DeterministicLexicalBoundaryBackend()
    configuration = config or BoundaryRankingConfig()
    generated = build_boundary_aware_rankings(
        topics=topics,
        pool_members=pool_members,
        records=records,
        backend=active_backend,
        method_id=method_id,
        config=configuration,
    )
    output = Path(output_dir).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Boundary output 已存在且非空，拒绝覆盖：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.build_", dir=output.parent
    ) as temp_dir:
        staging = Path(temp_dir)
        ranking_path = staging / "ranking.csv"
        write_csv_rows(ranking_path, RANKING_FIELDS, generated["rows"])
        ranking_sha = sha256_file(ranking_path)
        manifest = {
            "schema_version": "0.2-alpha",
            "contract_name": "w6_method_ranking_extension",
            "contract_version": "0.2-alpha",
            "artifact_type": "method_ranking",
            "artifact_id": artifact_id,
            "is_fixture": is_fixture,
            "status": "frozen",
            "compatibility": {
                "base_contract": "w5_method_ranking",
                "base_ranking_schema_version": "1.0",
                "ranking_fields": RANKING_FIELDS,
                "identity_mapping": {
                    "pair_id": "pool_item_id",
                    "research_query_id": "topic_id",
                },
                "ranking_unit": "source_record",
            },
            "method": {
                "method_id": method_id,
                "display_name": "Boundary-Aware Structured Lexical Ranking v1",
                "family": "sparse",
                "parameters": {
                    "prototype_version": "1.0",
                    "problem_dimensions": list(BOUNDARY_DIMENSIONS),
                    "formulation": (
                        f"{configuration.relevance_weight:.12g} * per-topic min-max BM25 "
                        f"relevance + {configuration.compatibility_weight:.12g} * structured "
                        f"compatibility - {configuration.boundary_penalty:.12g} * "
                        "max(scope-out overlap, boundary overlap)"
                    ),
                    "configuration": asdict(configuration),
                    "backend": generated["backend"],
                    "tokenizer": "src.text_relevance.tokenize_text",
                    "corpus_scope": "complete frozen W6 candidate pool",
                    "query_source": "frozen structured Topic fields and scope-in statements",
                    "missing_abstract_policy": configuration.missing_abstract_policy,
                },
                "model": None,
            },
            "inputs": {
                "topic_set": dict(topic_reference),
                "candidate_pool": dict(candidate_pool_reference),
            },
            "auxiliary_inputs": {"source_records": dict(source_records_reference)},
            "method_inputs": [],
            "score_processing": {
                "output_score_semantics": "higher_is_better",
                "normalization": None,
            },
            "ranking": {
                "path": "ranking.csv",
                "sha256": ranking_sha,
                "row_count": len(generated["rows"]),
                "score_direction": "higher_is_better",
                "tie_breaking": ["score_desc", "pair_id_asc"],
            },
            "freeze": {
                "frozen_at": frozen_at,
                "configuration_sha256": "",
                "evaluation_started_at": None,
            },
            "generation": {
                "generated_at": generated_at,
                "git_revision": git_revision,
                "git_worktree_clean": True,
                "dependencies": {},
                "deterministic_seed": None,
            },
            "label_access": {
                "relevance_labels_read": False,
                "hidden_test_labels_read": False,
                "declaration": (
                    "Boundary-Aware generation read only frozen Topic, Candidate Pool, and "
                    "source-record text; it did not read Dev or Hidden relevance labels, "
                    "judgements, metrics, or error-analysis artifacts."
                ),
            },
        }
        manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(
            manifest
        )
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        validate_w6_method_package(
            manifest_path,
            artifact_registry=artifact_registry,
            pool_members=pool_members,
            known_method_packages={},
        )
        if output.exists():
            output.rmdir()
        staging.replace(output)
    return output / "manifest.json"


def _structured_query_text(topic: Mapping[str, Any]) -> str:
    values = [
        topic["research_question"],
        topic["scientific_object"],
        topic["data_modality"],
        topic["target_task"],
        topic["method_role"],
        *topic["scope_in"],
    ]
    return " ".join(str(value) for value in values)


def _content_tokens(value: Any) -> set[str]:
    return {
        token
        for token in tokenize_text(str(value or ""))
        if token not in _STOPWORDS and len(token) > 1
    }


def _coverage_score(expected: set[str], observed: set[str]) -> float:
    if not expected:
        return 0.0
    return min(1.0, len(expected & observed) / math.sqrt(len(expected)))


def _maximum_statement_overlap(statements: list[str], candidate_tokens: set[str]) -> float:
    maximum = 0.0
    for statement in statements:
        tokens = _content_tokens(statement)
        if not tokens:
            continue
        union = tokens | candidate_tokens
        overlap = len(tokens & candidate_tokens) / len(union) if union else 0.0
        maximum = max(maximum, overlap)
    return maximum


def _validate_assessment(assessment: BoundaryAssessment, pool_item_id: str) -> None:
    if set(assessment.dimension_scores) != set(BOUNDARY_DIMENSIONS):
        raise ValueError(f"Boundary assessment dimensions 不完整：{pool_item_id}。")
    values = [
        *assessment.dimension_scores.values(),
        assessment.scope_out_overlap,
        assessment.boundary_case_overlap,
    ]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 1
        for value in values
    ):
        raise ValueError(f"Boundary assessment scores 必须在 0..1：{pool_item_id}。")
    if not isinstance(assessment.missing_abstract, bool):
        raise ValueError("Boundary assessment missing_abstract 必须是 boolean。")
    if not assessment.evidence_summary.strip():
        raise ValueError("Boundary assessment 必须保存简短可审查依据。")


def _require_method_id(value: str) -> None:
    import re

    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value):
        raise ValueError("method/artifact ID 必须是 W5-compatible 小写机器标识。")


def _require_datetime(value: str, label: str) -> None:
    try:
        _parse_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} 必须是带时区 ISO-8601 时间。") from error


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime 缺少时区。")
    return parsed


def _require_git_revision(value: str) -> None:
    if len(str(value)) != 40 or any(
        character not in "0123456789abcdef" for character in str(value)
    ):
        raise ValueError("git_revision 必须是 40 位小写 Git SHA。")
