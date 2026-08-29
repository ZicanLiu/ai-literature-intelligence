"""Algorithm-independent W6 multi-retriever candidate-pool builder.

The builder consumes frozen W6 topic, retrieval-run/hit and source-record
artifacts.  Retriever implementations remain upstream: adding a new retrieval
family only requires producing valid ``w6_retrieval_provenance`` rows.

Pooling deliberately separates two concepts:

* per-run depth decides whether a topic-record is admitted to the pool;
* once admitted, provenance contains every hit for that topic-record from the
  complete frozen included-run roster, including hits below admission depth.

No relevance annotation or benchmark artifact is accepted by this module.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import platform
import random
import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from src.annotation_tasks import sha256_file
from src.w6_contracts import (
    W6_SCHEMA_VERSION,
    canonical_json_sha256,
    compute_pool_identity,
    validate_candidate_pool,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
)


MERGED_RETRIEVAL_FILENAME = "retrieval_provenance.json"
PRECANONICAL_POOL_FILENAME = "precanonical_candidate_pool.json"
STATISTICS_FILENAME = "pool_statistics.json"
BUILD_MANIFEST_FILENAME = "build_manifest.json"

TARGET_OVERFLOW_POLICY = "retain_all_depth_qualified_candidates"
DUPLICATE_HIT_POLICY = "deduplicate_topic_record_keep_all_hit_refs"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_POLICY_PARAMETER_FIELDS = {
    "depth_by_system",
    "depth_overrides_by_run",
    "target_size_per_topic",
    "minimum_size_per_topic",
    "deterministic_random_seed",
    "random_fill_enabled",
    "target_overflow_policy",
    "duplicate_hit_handling",
}


class RetrievalArtifactBackend(Protocol):
    """Replaceable provider of already-frozen retrieval artifacts."""

    def load_retrieval_artifacts(self) -> Sequence["LoadedArtifact"]:
        """Return one or more local, label-free retrieval artifacts."""


@dataclass(frozen=True)
class LoadedArtifact:
    """A parsed JSON artifact paired with its exact file SHA-256."""

    payload: dict[str, Any]
    sha256: str


@dataclass(frozen=True)
class PoolBuildArtifacts:
    """In-memory output of one deterministic pool build."""

    retrieval_provenance: dict[str, Any]
    candidate_pool: dict[str, Any]
    statistics: dict[str, Any]


class JsonRetrievalArtifactBackend:
    """Load frozen retrieval artifacts from explicit local JSON paths."""

    def __init__(self, paths: Sequence[str | Path]) -> None:
        if not paths:
            raise ValueError("至少需要一个 retrieval artifact。")
        self._paths = tuple(Path(path) for path in paths)

    def load_retrieval_artifacts(self) -> list[LoadedArtifact]:
        return [load_json_artifact(path, label="retrieval artifact") for path in self._paths]


def load_json_artifact(path: str | Path, *, label: str) -> LoadedArtifact:
    """Load an object-valued UTF-8 JSON file and capture its byte hash."""

    artifact_path = Path(path)
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} 不是合法 JSON：{error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 顶层必须是 JSON object。")
    return LoadedArtifact(payload=payload, sha256=sha256_file(artifact_path))


def load_frozen_pool_policy(
    path: str | Path, *, expected_sha256: str
) -> LoadedArtifact:
    """Load a policy only when its exact file hash matches the frozen anchor."""

    _require_sha256(expected_sha256, "expected policy SHA-256")
    artifact = load_json_artifact(path, label="pool policy")
    if artifact.sha256 != expected_sha256:
        raise ValueError("pool policy SHA-256 drift。")
    return artifact


def validate_pooling_policy(
    policy: Mapping[str, Any],
    *,
    topics: Mapping[str, Any],
    retrieval: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the executable v1 pooling policy and its exact run roster."""

    mapping = _require_mapping(policy, "pool policy")
    _require_exact_fields(
        mapping,
        {"name", "version", "parameters", "included_retrieval_run_ids"},
        "pool policy",
    )
    _require_nonempty_string(mapping["name"], "pool policy.name")
    _require_nonempty_string(mapping["version"], "pool policy.version")

    raw_run_ids = mapping["included_retrieval_run_ids"]
    if not isinstance(raw_run_ids, list) or not raw_run_ids:
        raise ValueError("included_retrieval_run_ids 必须是非空 array。")
    run_ids: list[str] = []
    for value in raw_run_ids:
        run_ids.append(_require_id(value, "included retrieval_run_id"))
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("included_retrieval_run_ids 不得重复。")
    if run_ids != sorted(run_ids):
        raise ValueError("included_retrieval_run_ids 必须按 ID 升序冻结。")
    unknown_runs = sorted(set(run_ids).difference(retrieval["runs"]))
    if unknown_runs:
        raise ValueError("pool policy 引用 unknown retrieval run：" + ", ".join(unknown_runs) + "。")

    parameters = _require_mapping(mapping["parameters"], "pool policy.parameters")
    _require_exact_fields(
        parameters, _POLICY_PARAMETER_FIELDS, "pool policy.parameters"
    )

    included_runs = {run_id: retrieval["runs"][run_id] for run_id in run_ids}
    systems = {run["acquisition_system"] for run in included_runs.values()}
    depths_by_system = _validate_positive_integer_mapping(
        parameters["depth_by_system"], "depth_by_system", keys_are_ids=False
    )
    if set(depths_by_system) != systems:
        raise ValueError("depth_by_system 必须精确覆盖 included run 的 acquisition systems。")

    overrides = _validate_positive_integer_mapping(
        parameters["depth_overrides_by_run"],
        "depth_overrides_by_run",
        allow_empty=True,
        keys_are_ids=True,
    )
    unknown_overrides = sorted(set(overrides).difference(included_runs))
    if unknown_overrides:
        raise ValueError("depth_overrides_by_run 包含未纳入 roster 的 run。")

    _validate_topic_limit(
        parameters["target_size_per_topic"],
        topics=topics,
        label="target_size_per_topic",
        positive=True,
    )
    _validate_topic_limit(
        parameters["minimum_size_per_topic"],
        topics=topics,
        label="minimum_size_per_topic",
        positive=False,
    )
    for topic_id in topics:
        target = _resolve_topic_limit(
            parameters["target_size_per_topic"], topic_id=topic_id
        )
        minimum = _resolve_topic_limit(
            parameters["minimum_size_per_topic"], topic_id=topic_id
        )
        if minimum > target:
            raise ValueError(f"{topic_id} minimum size 不得大于 target size。")

    seed = parameters["deterministic_random_seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("deterministic_random_seed 必须是 integer。")
    if not isinstance(parameters["random_fill_enabled"], bool):
        raise ValueError("random_fill_enabled 必须是 boolean。")
    if parameters["target_overflow_policy"] != TARGET_OVERFLOW_POLICY:
        raise ValueError("target_overflow_policy 与冻结 Builder v1 语义不一致。")
    if parameters["duplicate_hit_handling"] != DUPLICATE_HIT_POLICY:
        raise ValueError("duplicate_hit_handling 与冻结 Builder v1 语义不一致。")

    return copy.deepcopy(mapping)


def merge_retrieval_provenance(
    artifacts: Sequence[LoadedArtifact],
    *,
    topics: Mapping[str, Any],
    generated_at: str,
    git_revision: str,
) -> dict[str, Any]:
    """Validate and deterministically merge N retrieval-provenance artifacts."""

    if not artifacts:
        raise ValueError("至少需要一个 retrieval artifact。")
    _require_datetime(generated_at, "generated_at")
    _require_git_revision(git_revision, "git_revision")

    artifact_ids: set[str] = set()
    fixture_flags: set[bool] = set()
    runs: dict[str, dict[str, Any]] = {}
    hits: dict[str, dict[str, Any]] = {}
    input_identities: list[dict[str, str]] = []

    for artifact in artifacts:
        _require_sha256(artifact.sha256, "retrieval artifact SHA-256")
        payload = artifact.payload
        validated = validate_retrieval_provenance(payload, topics=topics)
        artifact_id = _require_id(payload.get("artifact_id"), "retrieval artifact_id")
        if artifact_id in artifact_ids:
            raise ValueError(f"duplicate retrieval artifact_id：{artifact_id}。")
        artifact_ids.add(artifact_id)
        fixture_flags.add(bool(payload["is_fixture"]))
        input_identities.append({"artifact_id": artifact_id, "sha256": artifact.sha256})

        for run_id, run in validated["runs"].items():
            if run_id in runs:
                raise ValueError(f"retrieval artifact roster drift/duplicate run：{run_id}。")
            runs[run_id] = copy.deepcopy(run)
        for hit_id, hit in validated["hits"].items():
            if hit_id in hits:
                raise ValueError(f"duplicate retrieval hit across artifacts：{hit_id}。")
            hits[hit_id] = copy.deepcopy(hit)

    if len(fixture_flags) != 1:
        raise ValueError("不得混合 fixture 与非 fixture retrieval artifacts。")

    input_identities.sort(key=lambda row: row["artifact_id"])
    merged_created_at = max(
        (artifact.payload["created_at"] for artifact in artifacts),
        key=_parse_datetime,
    )
    merged_identity = canonical_json_sha256(
        {"input_artifacts": input_identities, "run_ids": sorted(runs), "hit_ids": sorted(hits)}
    )
    merged = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_retrieval_provenance",
        "artifact_id": f"w6_retrieval_union_{merged_identity[:24]}",
        "is_fixture": fixture_flags.pop(),
        "created_at": merged_created_at,
        "provenance": _build_provenance(
            is_fixture=all(artifact.payload["is_fixture"] for artifact in artifacts),
            generated_at=merged_created_at,
            git_revision=git_revision,
        ),
        "runs": [runs[run_id] for run_id in sorted(runs)],
        "hits": sorted(
            hits.values(),
            key=lambda hit: (
                hit["retrieval_run_id"],
                hit["source_rank"],
                hit["retrieval_hit_id"],
            ),
        ),
    }
    validate_retrieval_provenance(merged, topics=topics)
    return merged


def build_broad_candidate_universe(
    *,
    retrieval: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Index all topic-record evidence from the included frozen run roster."""

    included = set(policy["included_retrieval_run_ids"])
    universe: dict[tuple[str, str], dict[str, Any]] = {}
    for hit_id, hit in retrieval["hits"].items():
        run_id = hit["retrieval_run_id"]
        if run_id not in included:
            continue
        run = retrieval["runs"][run_id]
        key = (run["topic_id"], hit["record_id"])
        entry = universe.setdefault(
            key,
            {
                "topic_id": key[0],
                "record_id": key[1],
                "hit_ids": [],
                "run_ids": set(),
                "systems": set(),
                "admission_run_ids": set(),
            },
        )
        entry["hit_ids"].append(hit_id)
        entry["run_ids"].add(run_id)
        entry["systems"].add(run["acquisition_system"])
        if hit["source_rank"] <= _depth_for_run(policy, run):
            entry["admission_run_ids"].add(run_id)

    for entry in universe.values():
        entry["hit_ids"].sort(
            key=lambda hit_id: (
                retrieval["hits"][hit_id]["retrieval_run_id"],
                retrieval["hits"][hit_id]["source_rank"],
                hit_id,
            )
        )
    return universe


def build_pool_artifacts(
    *,
    topic_set: LoadedArtifact,
    retrieval_artifacts: Sequence[LoadedArtifact],
    source_records: LoadedArtifact,
    policy: LoadedArtifact,
    generated_at: str,
    git_revision: str,
    status: str = "candidate",
) -> PoolBuildArtifacts:
    """Build and cross-validate merged retrieval, pre-canonical pool and stats."""

    _require_sha256(topic_set.sha256, "topic set SHA-256")
    _require_sha256(source_records.sha256, "source records SHA-256")
    _require_sha256(policy.sha256, "policy SHA-256")
    if status not in {"candidate", "frozen"}:
        raise ValueError("candidate pool status 必须是 candidate/frozen。")

    topics = validate_topic_set(topic_set.payload)
    merged = merge_retrieval_provenance(
        retrieval_artifacts,
        topics=topics,
        generated_at=generated_at,
        git_revision=git_revision,
    )
    retrieval = validate_retrieval_provenance(merged, topics=topics)
    records = validate_source_records(
        source_records.payload, topics=topics, retrieval=retrieval
    )
    fixture_flags = {
        bool(topic_set.payload["is_fixture"]),
        bool(merged["is_fixture"]),
        bool(source_records.payload["is_fixture"]),
    }
    if len(fixture_flags) != 1:
        raise ValueError("不得混合 fixture 与非 fixture topic/retrieval/source artifacts。")
    frozen_policy = validate_pooling_policy(
        policy.payload, topics=topics, retrieval=retrieval
    )
    universe = build_broad_candidate_universe(
        retrieval=retrieval, policy=frozen_policy
    )
    selected = _select_topic_records(
        topics=topics,
        universe=universe,
        policy=frozen_policy,
    )

    members = [
        _build_pool_member(key=key, evidence=universe[key])
        for key in sorted(selected)
    ]
    topic_counts = Counter(member["topic_id"] for member in members)
    merged_sha256 = _payload_sha256(merged)
    pool = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_candidate_pool",
        "artifact_id": "w6_precanonical_pool_pending",
        "is_fixture": bool(topic_set.payload["is_fixture"]),
        "status": status,
        "identity_stage": "pre_canonicalization",
        "pool_identity": "pending",
        "policy": frozen_policy,
        "inputs": {
            "topic_set": {
                "artifact_id": topic_set.payload["artifact_id"],
                "sha256": topic_set.sha256,
            },
            "retrieval_provenance": {
                "artifact_id": merged["artifact_id"],
                "sha256": merged_sha256,
            },
            "source_records": {
                "artifact_id": source_records.payload["artifact_id"],
                "sha256": source_records.sha256,
            },
        },
        "topic_counts": {topic_id: topic_counts.get(topic_id, 0) for topic_id in sorted(topics)},
        "members": members,
        "created_at": generated_at,
        "provenance": _build_provenance(
            is_fixture=bool(topic_set.payload["is_fixture"]),
            generated_at=generated_at,
            git_revision=git_revision,
        ),
    }
    pool["pool_identity"] = compute_pool_identity(pool)
    pool_digest = pool["pool_identity"].rsplit(":", 1)[-1]
    pool["artifact_id"] = f"w6_precanonical_pool_{pool_digest[:24]}"

    registry = {
        topic_set.payload["artifact_id"]: {
            "artifact_id": topic_set.payload["artifact_id"],
            "sha256": topic_set.sha256,
        },
        merged["artifact_id"]: {
            "artifact_id": merged["artifact_id"],
            "sha256": merged_sha256,
        },
        source_records.payload["artifact_id"]: {
            "artifact_id": source_records.payload["artifact_id"],
            "sha256": source_records.sha256,
        },
    }
    validate_candidate_pool(
        pool,
        topics=topics,
        records=records,
        retrieval=retrieval,
        registry=registry,
        canonical=None,
    )

    pool_sha256 = _payload_sha256(pool)
    statistics = _build_statistics(
        topic_ids=sorted(topics),
        input_artifact_count=len(retrieval_artifacts),
        retrieval=retrieval,
        universe=universe,
        pool=pool,
        pool_sha256=pool_sha256,
        policy_sha256=policy.sha256,
        generated_at=generated_at,
        git_revision=git_revision,
    )
    validate_pool_statistics(
        statistics,
        retrieval=retrieval,
        universe=universe,
        pool=pool,
        input_artifact_count=len(retrieval_artifacts),
    )
    return PoolBuildArtifacts(
        retrieval_provenance=merged,
        candidate_pool=pool,
        statistics=statistics,
    )


def validate_pool_statistics(
    payload: Mapping[str, Any],
    *,
    retrieval: Mapping[str, Any],
    universe: Mapping[tuple[str, str], Mapping[str, Any]],
    pool: Mapping[str, Any],
    input_artifact_count: int,
) -> dict[str, Any]:
    """Recompute label-free diagnostics and reject self-reported count drift."""

    mapping = _require_mapping(payload, "pool statistics")
    _require_exact_fields(
        mapping,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "candidate_pool",
            "policy_sha256",
            "counts",
            "per_system_contribution",
            "created_at",
            "provenance",
        },
        "pool statistics",
    )
    if mapping["schema_version"] != W6_SCHEMA_VERSION:
        raise ValueError("pool statistics schema_version 非法。")
    if mapping["artifact_type"] != "w6_pool_statistics":
        raise ValueError("pool statistics artifact_type 非法。")
    _require_id(mapping["artifact_id"], "pool statistics artifact_id")
    if not isinstance(mapping["is_fixture"], bool):
        raise ValueError("pool statistics is_fixture 必须是 boolean。")
    _require_sha256(mapping["policy_sha256"], "pool statistics policy_sha256")
    _require_datetime(mapping["created_at"], "pool statistics created_at")
    _validate_builder_provenance(mapping["provenance"], "pool statistics provenance")

    pool_reference = _require_mapping(mapping["candidate_pool"], "statistics candidate_pool")
    _require_exact_fields(
        pool_reference, {"artifact_id", "sha256", "pool_identity"}, "statistics candidate_pool"
    )
    if pool_reference != {
        "artifact_id": pool["artifact_id"],
        "sha256": _payload_sha256(pool),
        "pool_identity": pool["pool_identity"],
    }:
        raise ValueError("pool statistics candidate_pool identity/hash drift。")

    expected_counts, expected_contribution = _compute_statistics_values(
        topic_ids=sorted(pool["topic_counts"]),
        input_artifact_count=input_artifact_count,
        retrieval=retrieval,
        universe=universe,
        pool=pool,
    )
    if mapping["counts"] != expected_counts:
        raise ValueError("pool statistics counts 与实际 pool/retrieval 不一致。")
    if mapping["per_system_contribution"] != expected_contribution:
        raise ValueError("pool statistics per-system contribution 不一致。")
    return copy.deepcopy(mapping)


def build_pool_from_backend(
    *,
    backend: RetrievalArtifactBackend,
    topic_set: LoadedArtifact,
    source_records: LoadedArtifact,
    policy: LoadedArtifact,
    generated_at: str,
    git_revision: str,
    status: str = "candidate",
) -> PoolBuildArtifacts:
    """Backend-injected entry point used by the CLI and offline fake tests."""

    retrieval_artifacts = list(backend.load_retrieval_artifacts())
    return build_pool_artifacts(
        topic_set=topic_set,
        retrieval_artifacts=retrieval_artifacts,
        source_records=source_records,
        policy=policy,
        generated_at=generated_at,
        git_revision=git_revision,
        status=status,
    )


def write_pool_build_outputs(
    *,
    output_dir: str | Path,
    artifacts: PoolBuildArtifacts,
    topic_set: LoadedArtifact,
    retrieval_inputs: Sequence[LoadedArtifact],
    source_records: LoadedArtifact,
    policy: LoadedArtifact,
    generated_at: str,
    git_revision: str,
    git_worktree_clean: bool,
    duration_seconds: float,
) -> Path:
    """Write a validated build and return the build-manifest path."""

    if not isinstance(git_worktree_clean, bool):
        raise ValueError("git_worktree_clean 必须是 boolean。")
    if not isinstance(duration_seconds, (int, float)) or not math.isfinite(duration_seconds) or duration_seconds < 0:
        raise ValueError("duration_seconds 必须是非负有限数值。")
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise ValueError("output directory 必须不存在或为空，避免覆盖既有 artifact。")
    target.mkdir(parents=True, exist_ok=True)

    payloads = {
        MERGED_RETRIEVAL_FILENAME: artifacts.retrieval_provenance,
        PRECANONICAL_POOL_FILENAME: artifacts.candidate_pool,
        STATISTICS_FILENAME: artifacts.statistics,
    }
    encoded = {name: _json_bytes(payload) for name, payload in payloads.items()}
    output_hashes = {
        name: hashlib.sha256(content).hexdigest() for name, content in encoded.items()
    }

    input_refs = sorted(
        (
            {"artifact_id": artifact.payload["artifact_id"], "sha256": artifact.sha256}
            for artifact in retrieval_inputs
        ),
        key=lambda row: row["artifact_id"],
    )
    manifest_identity = canonical_json_sha256(
        {
            "pool_identity": artifacts.candidate_pool["pool_identity"],
            "policy_sha256": policy.sha256,
            "outputs": output_hashes,
        }
    )
    manifest = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_pool_build_manifest",
        "artifact_id": f"w6_pool_build_{manifest_identity[:24]}",
        "is_fixture": artifacts.candidate_pool["is_fixture"],
        "created_at": generated_at,
        "provenance": _build_provenance(
            is_fixture=artifacts.candidate_pool["is_fixture"],
            generated_at=generated_at,
            git_revision=git_revision,
        ),
        "policy": {"sha256": policy.sha256},
        "inputs": {
            "topic_set": {
                "artifact_id": topic_set.payload["artifact_id"],
                "sha256": topic_set.sha256,
            },
            "retrieval_provenance_inputs": input_refs,
            "source_records": {
                "artifact_id": source_records.payload["artifact_id"],
                "sha256": source_records.sha256,
            },
        },
        "outputs": {
            "retrieval_provenance": {
                "artifact_id": artifacts.retrieval_provenance["artifact_id"],
                "path": MERGED_RETRIEVAL_FILENAME,
                "sha256": output_hashes[MERGED_RETRIEVAL_FILENAME],
            },
            "candidate_pool": {
                "artifact_id": artifacts.candidate_pool["artifact_id"],
                "path": PRECANONICAL_POOL_FILENAME,
                "sha256": output_hashes[PRECANONICAL_POOL_FILENAME],
                "pool_identity": artifacts.candidate_pool["pool_identity"],
            },
            "pool_statistics": {
                "artifact_id": artifacts.statistics["artifact_id"],
                "path": STATISTICS_FILENAME,
                "sha256": output_hashes[STATISTICS_FILENAME],
            },
        },
        "generation": {
            "git_revision": git_revision,
            "git_worktree_clean": git_worktree_clean,
            "duration_seconds": float(duration_seconds),
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
        },
        "label_access": {
            "benchmark_labels_read": False,
            "declaration": "Candidate-pool generation did not read relevance labels or judgements.",
        },
    }
    manifest_bytes = _json_bytes(manifest)

    for filename, content in encoded.items():
        (target / filename).write_bytes(content)
    manifest_path = target / BUILD_MANIFEST_FILENAME
    manifest_path.write_bytes(manifest_bytes)
    validate_pool_build_manifest(manifest_path)
    return manifest_path


def validate_pool_build_manifest(path: str | Path) -> dict[str, Any]:
    """Validate build metadata and all output file hashes without live access."""

    manifest_path = Path(path).resolve()
    loaded = load_json_artifact(manifest_path, label="pool build manifest")
    payload = loaded.payload
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "created_at",
            "provenance",
            "policy",
            "inputs",
            "outputs",
            "generation",
            "label_access",
        },
        "pool build manifest",
    )
    if payload["schema_version"] != W6_SCHEMA_VERSION or payload["artifact_type"] != "w6_pool_build_manifest":
        raise ValueError("pool build manifest header 非法。")
    _require_id(payload["artifact_id"], "pool build artifact_id")
    if not isinstance(payload["is_fixture"], bool):
        raise ValueError("pool build is_fixture 必须是 boolean。")
    _require_datetime(payload["created_at"], "pool build created_at")
    _validate_builder_provenance(payload["provenance"], "pool build provenance")

    policy = _require_mapping(payload["policy"], "manifest policy")
    _require_exact_fields(policy, {"sha256"}, "manifest policy")
    _require_sha256(policy["sha256"], "manifest policy sha256")
    inputs = _require_mapping(payload["inputs"], "manifest inputs")
    _require_exact_fields(
        inputs,
        {"topic_set", "retrieval_provenance_inputs", "source_records"},
        "manifest inputs",
    )
    _validate_artifact_reference(inputs["topic_set"], "manifest topic_set")
    _validate_artifact_reference(inputs["source_records"], "manifest source_records")
    retrieval_inputs = inputs["retrieval_provenance_inputs"]
    if not isinstance(retrieval_inputs, list) or not retrieval_inputs:
        raise ValueError("manifest retrieval inputs 必须是非空 array。")
    for reference in retrieval_inputs:
        _validate_artifact_reference(reference, "manifest retrieval input")

    outputs = _require_mapping(payload["outputs"], "manifest outputs")
    _require_exact_fields(
        outputs,
        {"retrieval_provenance", "candidate_pool", "pool_statistics"},
        "manifest outputs",
    )
    expected_filenames = {
        "retrieval_provenance": MERGED_RETRIEVAL_FILENAME,
        "candidate_pool": PRECANONICAL_POOL_FILENAME,
        "pool_statistics": STATISTICS_FILENAME,
    }
    for name, expected_filename in expected_filenames.items():
        reference = _require_mapping(outputs[name], f"manifest outputs.{name}")
        fields = {"artifact_id", "path", "sha256"}
        if name == "candidate_pool":
            fields.add("pool_identity")
        _require_exact_fields(reference, fields, f"manifest outputs.{name}")
        _require_id(reference["artifact_id"], f"manifest outputs.{name}.artifact_id")
        if reference["path"] != expected_filename:
            raise ValueError(f"manifest outputs.{name}.path 非法。")
        _require_sha256(reference["sha256"], f"manifest outputs.{name}.sha256")
        output_path = manifest_path.parent / expected_filename
        if not output_path.is_file() or sha256_file(output_path) != reference["sha256"]:
            raise ValueError(f"manifest output hash drift：{name}。")
        output_payload = load_json_artifact(
            output_path, label=f"manifest output {name}"
        ).payload
        if output_payload.get("artifact_id") != reference["artifact_id"]:
            raise ValueError(f"manifest output artifact identity drift：{name}。")
        if name == "candidate_pool" and output_payload.get("pool_identity") != reference["pool_identity"]:
            raise ValueError("manifest candidate pool_identity drift。")
    pool_identity = outputs["candidate_pool"]["pool_identity"]
    _require_nonempty_string(pool_identity, "manifest candidate pool_identity")

    generation = _require_mapping(payload["generation"], "manifest generation")
    _require_exact_fields(
        generation,
        {"git_revision", "git_worktree_clean", "duration_seconds", "python", "platform"},
        "manifest generation",
    )
    _require_git_revision(generation["git_revision"], "manifest git_revision")
    if not isinstance(generation["git_worktree_clean"], bool):
        raise ValueError("manifest git_worktree_clean 必须是 boolean。")
    duration = generation["duration_seconds"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
        raise ValueError("manifest duration_seconds 非法。")
    for key in ("python", "platform"):
        if not isinstance(generation[key], dict) or not generation[key]:
            raise ValueError(f"manifest generation.{key} 必须是非空 object。")

    label_access = _require_mapping(payload["label_access"], "manifest label_access")
    _require_exact_fields(
        label_access, {"benchmark_labels_read", "declaration"}, "manifest label_access"
    )
    if label_access["benchmark_labels_read"] is not False:
        raise ValueError("pool generation 不得读取 benchmark labels。")
    _require_nonempty_string(label_access["declaration"], "manifest label declaration")
    return payload


def capture_git_state(project_root: str | Path) -> dict[str, Any]:
    """Capture the commit and clean state before any build output is written."""

    root = Path(project_root)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _require_git_revision(revision, "Git revision")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"git_revision": revision, "git_worktree_clean": not bool(status.strip())}


def current_iso_datetime() -> str:
    """Return an offset-aware ISO-8601 timestamp."""

    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_pool_build(
    *,
    topic_set_path: str | Path,
    retrieval_paths: Sequence[str | Path],
    source_records_path: str | Path,
    policy_path: str | Path,
    expected_policy_sha256: str,
    output_dir: str | Path,
    project_root: str | Path,
    status: str = "candidate",
    clock: Callable[[], float] = time.monotonic,
) -> Path:
    """End-to-end local build used by the thin CLI."""

    started = clock()
    generated_at = current_iso_datetime()
    git_state = capture_git_state(project_root)
    if status == "frozen" and not git_state["git_worktree_clean"]:
        raise ValueError("frozen pool 必须在生成开始前的 clean Git worktree 上构建。")

    topic_set = load_json_artifact(topic_set_path, label="topic set")
    source_records = load_json_artifact(source_records_path, label="source records")
    policy = load_frozen_pool_policy(
        policy_path, expected_sha256=expected_policy_sha256
    )
    backend = JsonRetrievalArtifactBackend(retrieval_paths)
    retrieval_inputs = list(backend.load_retrieval_artifacts())
    artifacts = build_pool_artifacts(
        topic_set=topic_set,
        retrieval_artifacts=retrieval_inputs,
        source_records=source_records,
        policy=policy,
        generated_at=generated_at,
        git_revision=git_state["git_revision"],
        status=status,
    )
    duration = clock() - started
    return write_pool_build_outputs(
        output_dir=output_dir,
        artifacts=artifacts,
        topic_set=topic_set,
        retrieval_inputs=retrieval_inputs,
        source_records=source_records,
        policy=policy,
        generated_at=generated_at,
        git_revision=git_state["git_revision"],
        git_worktree_clean=git_state["git_worktree_clean"],
        duration_seconds=duration,
    )


def _select_topic_records(
    *,
    topics: Mapping[str, Any],
    universe: Mapping[tuple[str, str], Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> set[tuple[str, str]]:
    parameters = policy["parameters"]
    selected: set[tuple[str, str]] = {
        key for key, evidence in universe.items() if evidence["admission_run_ids"]
    }
    for topic_id in sorted(topics):
        topic_selected = {key for key in selected if key[0] == topic_id}
        target = _resolve_topic_limit(parameters["target_size_per_topic"], topic_id=topic_id)
        minimum = _resolve_topic_limit(parameters["minimum_size_per_topic"], topic_id=topic_id)
        if parameters["random_fill_enabled"] and len(topic_selected) < target:
            remaining = sorted(
                key for key in universe if key[0] == topic_id and key not in selected
            )
            fill_count = min(target - len(topic_selected), len(remaining))
            topic_rng = random.Random(_topic_seed(parameters["deterministic_random_seed"], topic_id))
            chosen = topic_rng.sample(remaining, fill_count)
            for key in chosen:
                universe[key]["random_fill_selected"] = True
            selected.update(chosen)
            topic_selected.update(chosen)
        if len(topic_selected) < minimum:
            raise ValueError(
                f"{topic_id} pool size {len(topic_selected)} 小于 minimum {minimum}。"
            )
    return selected


def _build_pool_member(
    *, key: tuple[str, str], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    identity = canonical_json_sha256({"topic_id": key[0], "record_id": key[1]})
    reasons = [
        f"depth_qualified:{run_id}" for run_id in sorted(evidence["admission_run_ids"])
    ]
    if evidence.get("random_fill_selected"):
        reasons.append("deterministic_random_fill")
    if len(evidence["systems"]) > 1:
        reasons.append("multi_system_provenance")
    else:
        reasons.append("single_system_only")
    return {
        "pool_item_id": f"w6_pool_item_{identity[:24]}",
        "topic_id": key[0],
        "record_id": key[1],
        "canonical_entity_id": None,
        "retrieval_hit_ids": list(evidence["hit_ids"]),
        "source_system_membership": sorted(evidence["systems"]),
        "selection_reasons": reasons,
    }


def _build_statistics(
    *,
    topic_ids: Sequence[str],
    input_artifact_count: int,
    retrieval: Mapping[str, Any],
    universe: Mapping[tuple[str, str], Mapping[str, Any]],
    pool: Mapping[str, Any],
    pool_sha256: str,
    policy_sha256: str,
    generated_at: str,
    git_revision: str,
) -> dict[str, Any]:
    counts, contribution = _compute_statistics_values(
        topic_ids=topic_ids,
        input_artifact_count=input_artifact_count,
        retrieval=retrieval,
        universe=universe,
        pool=pool,
    )
    identity = canonical_json_sha256(
        {"pool_identity": pool["pool_identity"], "counts": counts, "contribution": contribution}
    )
    return {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_pool_statistics",
        "artifact_id": f"w6_pool_statistics_{identity[:24]}",
        "is_fixture": pool["is_fixture"],
        "candidate_pool": {
            "artifact_id": pool["artifact_id"],
            "sha256": pool_sha256,
            "pool_identity": pool["pool_identity"],
        },
        "policy_sha256": policy_sha256,
        "counts": counts,
        "per_system_contribution": contribution,
        "created_at": generated_at,
        "provenance": _build_provenance(
            is_fixture=pool["is_fixture"],
            generated_at=generated_at,
            git_revision=git_revision,
        ),
    }


def _compute_statistics_values(
    *,
    topic_ids: Sequence[str],
    input_artifact_count: int,
    retrieval: Mapping[str, Any],
    universe: Mapping[tuple[str, str], Mapping[str, Any]],
    pool: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    included = set(pool["policy"]["included_retrieval_run_ids"])
    included_hits = [
        hit for hit in retrieval["hits"].values() if hit["retrieval_run_id"] in included
    ]
    depth_eligible_hits = [
        hit
        for hit in included_hits
        if hit["source_rank"]
        <= _depth_for_run(pool["policy"], retrieval["runs"][hit["retrieval_run_id"]])
    ]
    selected_members = pool["members"]
    multi_system = sum(
        len(member["source_system_membership"]) > 1 for member in selected_members
    )
    topic_counts = {topic_id: pool["topic_counts"][topic_id] for topic_id in topic_ids}
    parameters = pool["policy"]["parameters"]
    overflow = {
        topic_id: max(
            0,
            topic_counts[topic_id]
            - _resolve_topic_limit(parameters["target_size_per_topic"], topic_id=topic_id),
        )
        for topic_id in topic_ids
    }
    minimum_satisfied = {
        topic_id: topic_counts[topic_id]
        >= _resolve_topic_limit(parameters["minimum_size_per_topic"], topic_id=topic_id)
        for topic_id in topic_ids
    }
    counts = {
        "input_artifact_count": input_artifact_count,
        "input_run_count": len(retrieval["runs"]),
        "included_run_count": len(included),
        "raw_hit_count": len(included_hits),
        "depth_eligible_hit_count": len(depth_eligible_hits),
        "unique_record_count": len({hit["record_id"] for hit in included_hits}),
        "unique_topic_record_count": len(universe),
        "multi_system_hit_count": multi_system,
        "single_system_only_count": len(selected_members) - multi_system,
        "pool_size": len(selected_members),
        "topic_counts": topic_counts,
        "target_overflow_by_topic": overflow,
        "minimum_satisfied_by_topic": minimum_satisfied,
    }

    hit_counts: Counter[str] = Counter()
    for hit in included_hits:
        run = retrieval["runs"][hit["retrieval_run_id"]]
        hit_counts[run["acquisition_system"]] += 1
    all_systems = sorted(
        {retrieval["runs"][run_id]["acquisition_system"] for run_id in included}
    )
    contribution = {}
    for system in all_systems:
        member_count = sum(system in member["source_system_membership"] for member in selected_members)
        single_only = sum(
            member["source_system_membership"] == [system] for member in selected_members
        )
        contribution[system] = {
            "raw_hit_count": hit_counts[system],
            "pool_member_count": member_count,
            "single_system_only_count": single_only,
        }
    return counts, contribution


def _depth_for_run(policy: Mapping[str, Any], run: Mapping[str, Any]) -> int:
    parameters = policy["parameters"]
    overrides = parameters["depth_overrides_by_run"]
    return int(
        overrides.get(
            run["retrieval_run_id"],
            parameters["depth_by_system"][run["acquisition_system"]],
        )
    )


def _topic_seed(seed: int, topic_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{topic_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _validate_topic_limit(
    value: Any,
    *,
    topics: Mapping[str, Any],
    label: str,
    positive: bool,
) -> None:
    minimum = 1 if positive else 0
    if isinstance(value, bool):
        raise ValueError(f"{label} 必须是 integer 或 topic mapping。")
    if isinstance(value, int):
        if value < minimum:
            raise ValueError(f"{label} 必须 >= {minimum}。")
        return
    mapping = _require_mapping(value, label)
    if set(mapping) != set(topics):
        raise ValueError(f"{label} topic mapping 必须精确覆盖全部 topics。")
    for topic_id, limit in mapping.items():
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < minimum:
            raise ValueError(f"{label}.{topic_id} 必须是 >= {minimum} 的 integer。")


def _resolve_topic_limit(value: int | Mapping[str, int], *, topic_id: str) -> int:
    return int(value if isinstance(value, int) else value[topic_id])


def _validate_positive_integer_mapping(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
    keys_are_ids: bool = True,
) -> dict[str, int]:
    mapping = _require_mapping(value, label)
    if not mapping and not allow_empty:
        raise ValueError(f"{label} 不得为空。")
    result: dict[str, int] = {}
    for key, raw_value in mapping.items():
        clean_key = (
            _require_id(key, f"{label} key")
            if keys_are_ids
            else _require_nonempty_string(key, f"{label} key")
        )
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
            raise ValueError(f"{label}.{clean_key} 必须是正整数。")
        result[clean_key] = raw_value
    return result


def _build_provenance(
    *, is_fixture: bool, generated_at: str, git_revision: str
) -> dict[str, Any]:
    return {
        "kind": "synthetic_fixture_build" if is_fixture else "multi_retriever_pool_build",
        "created_by": "w6_candidate_pool_builder",
        "created_at": generated_at,
        "git_revision": git_revision,
    }


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _validate_artifact_reference(value: Any, label: str) -> dict[str, str]:
    mapping = _require_mapping(value, label)
    _require_exact_fields(mapping, {"artifact_id", "sha256"}, label)
    _require_id(mapping["artifact_id"], f"{label}.artifact_id")
    _require_sha256(mapping["sha256"], f"{label}.sha256")
    return mapping


def _validate_builder_provenance(value: Any, label: str) -> None:
    mapping = _require_mapping(value, label)
    _require_exact_fields(mapping, {"kind", "created_by", "created_at", "git_revision"}, label)
    _require_nonempty_string(mapping["kind"], f"{label}.kind")
    _require_nonempty_string(mapping["created_by"], f"{label}.created_by")
    _require_datetime(mapping["created_at"], f"{label}.created_at")
    _require_git_revision(mapping["git_revision"], f"{label}.git_revision")


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON object。")
    return value


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected.difference(actual))
        extra = sorted(actual.difference(expected))
        raise ValueError(f"{label} 字段不符合 contract；missing={missing}, extra={extra}。")


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串。")
    return value


def _require_id(value: Any, label: str) -> str:
    clean = _require_nonempty_string(value, label)
    if not _ID_PATTERN.fullmatch(clean):
        raise ValueError(f"{label} 不是合法 stable ID。")
    return clean


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} 必须是 64 位小写 SHA-256。")
    return value


def _require_git_revision(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _GIT_REVISION_PATTERN.fullmatch(value):
        raise ValueError(f"{label} 必须是完整 40 位小写 Git SHA。")
    return value


def _require_datetime(value: Any, label: str) -> None:
    clean = _require_nonempty_string(value, label)
    try:
        parsed = _parse_datetime(clean)
    except ValueError as error:
        raise ValueError(f"{label} 不是合法 ISO-8601 datetime。") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} 必须包含时区。")


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


__all__ = [
    "BUILD_MANIFEST_FILENAME",
    "DUPLICATE_HIT_POLICY",
    "JsonRetrievalArtifactBackend",
    "LoadedArtifact",
    "PoolBuildArtifacts",
    "RetrievalArtifactBackend",
    "TARGET_OVERFLOW_POLICY",
    "build_broad_candidate_universe",
    "build_pool_artifacts",
    "build_pool_from_backend",
    "capture_git_state",
    "load_frozen_pool_policy",
    "load_json_artifact",
    "merge_retrieval_provenance",
    "run_pool_build",
    "validate_pool_build_manifest",
    "validate_pool_statistics",
    "validate_pooling_policy",
    "write_pool_build_outputs",
]
