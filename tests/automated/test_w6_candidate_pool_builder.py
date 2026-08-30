"""Completely offline tests for the W6 Multi-Retriever Pool Builder."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.build_w6_candidate_pool import build_parser, main as build_cli_main
from src import w6_candidate_pool_builder as pool_builder_module
from src.annotation_tasks import sha256_file
from src.w6_candidate_pool_builder import (
    BUILD_MANIFEST_FILENAME,
    DUPLICATE_HIT_POLICY,
    MERGED_RETRIEVAL_FILENAME,
    PRECANONICAL_POOL_FILENAME,
    STATISTICS_FILENAME,
    TARGET_OVERFLOW_POLICY,
    LoadedArtifact,
    build_pool_artifacts,
    build_pool_from_backend,
    load_frozen_pool_policy,
    load_json_artifact,
    validate_pool_build_manifest,
    write_pool_build_outputs,
)
from src.w6_contracts import (
    canonical_json_sha256,
    compute_pool_identity,
    validate_candidate_pool,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid"
POOL_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "w6_pool_builder"
TOPICS_PATH = BOOTSTRAP / "topics.json"
RETRIEVAL_PATH = BOOTSTRAP / "retrieval_runs.json"
SOURCE_PATH = BOOTSTRAP / "source_records.json"
POLICY_PATH = POOL_FIXTURE / "pool_policy.json"
POLICY_SHA256 = "cdb6508ba7e62ec1daf122901c93abb94e0f5dfdd30d5f5ff5a98a2261b99713"
GENERATED_AT = "2026-08-29T12:00:00+08:00"
GIT_REVISION = "a" * 40

OUTPUT_FILES = {
    "retrieval_provenance": MERGED_RETRIEVAL_FILENAME,
    "candidate_pool": PRECANONICAL_POOL_FILENAME,
    "pool_statistics": STATISTICS_FILENAME,
}


def loaded_copy(payload: dict) -> LoadedArtifact:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return LoadedArtifact(payload=payload, sha256=hashlib.sha256(encoded).hexdigest())


def write_json(path: Path, payload: dict) -> None:
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def refresh_statistics_artifact_id(statistics: dict) -> None:
    identity = canonical_json_sha256(
        {
            "pool_identity": statistics["candidate_pool"]["pool_identity"],
            "counts": statistics["counts"],
            "contribution": statistics["per_system_contribution"],
        }
    )
    statistics["artifact_id"] = f"w6_pool_statistics_{identity[:24]}"


def repack_build_manifest(output_dir: Path) -> dict:
    manifest_path = output_dir / BUILD_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_hashes = {}
    for logical_name, filename in OUTPUT_FILES.items():
        output_path = output_dir / filename
        output_payload = json.loads(output_path.read_text(encoding="utf-8"))
        reference = manifest["outputs"][logical_name]
        reference["artifact_id"] = output_payload["artifact_id"]
        reference["sha256"] = sha256_file(output_path)
        output_hashes[filename] = reference["sha256"]
        if logical_name == "candidate_pool":
            reference["pool_identity"] = output_payload["pool_identity"]
    identity = canonical_json_sha256(
        {
            "pool_identity": manifest["outputs"]["candidate_pool"]["pool_identity"],
            "policy_sha256": manifest["policy"]["sha256"],
            "outputs": output_hashes,
        }
    )
    manifest["artifact_id"] = f"w6_pool_build_{identity[:24]}"
    write_json(manifest_path, manifest)
    return manifest


def split_retrieval_artifact(payload: dict) -> list[LoadedArtifact]:
    run_ids = sorted(run["retrieval_run_id"] for run in payload["runs"])
    midpoint = len(run_ids) // 2
    artifacts = []
    for index, included in enumerate((set(run_ids[:midpoint]), set(run_ids[midpoint:])), start=1):
        part = copy.deepcopy(payload)
        part["artifact_id"] = f"w6_fixture_retrieval_part_{index}"
        part["runs"] = [
            run for run in part["runs"] if run["retrieval_run_id"] in included
        ]
        part["hits"] = [
            hit for hit in part["hits"] if hit["retrieval_run_id"] in included
        ]
        artifacts.append(loaded_copy(part))
    return artifacts


class FakeRetrievalBackend:
    def __init__(self, artifacts: list[LoadedArtifact]) -> None:
        self.artifacts = artifacts
        self.call_count = 0

    def load_retrieval_artifacts(self) -> list[LoadedArtifact]:
        self.call_count += 1
        return list(self.artifacts)


class W6PoolBuilderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.topics = load_json_artifact(TOPICS_PATH, label="topics")
        self.retrieval = load_json_artifact(RETRIEVAL_PATH, label="retrieval")
        self.source = load_json_artifact(SOURCE_PATH, label="source")
        self.policy = load_frozen_pool_policy(
            POLICY_PATH, expected_sha256=POLICY_SHA256
        )

    def build(
        self,
        *,
        retrieval_artifacts: list[LoadedArtifact] | None = None,
        source: LoadedArtifact | None = None,
        policy: LoadedArtifact | None = None,
    ):
        return build_pool_artifacts(
            topic_set=self.topics,
            retrieval_artifacts=retrieval_artifacts or [self.retrieval],
            source_records=source or self.source,
            policy=policy or self.policy,
            generated_at=GENERATED_AT,
            git_revision=GIT_REVISION,
        )

    def modified_policy(self, mutator) -> LoadedArtifact:
        payload = copy.deepcopy(self.policy.payload)
        mutator(payload)
        return loaded_copy(payload)

    def validator_kwargs(
        self, retrieval_inputs: list[LoadedArtifact] | None = None
    ) -> dict:
        return {
            "topic_set": self.topics,
            "retrieval_inputs": retrieval_inputs or [self.retrieval],
            "source_records": self.source,
            "policy": self.policy,
        }

    def write_package(
        self,
        output_dir: Path,
        *,
        artifacts=None,
        retrieval_inputs: list[LoadedArtifact] | None = None,
        status: str = "candidate",
        git_worktree_clean: bool = False,
    ) -> Path:
        inputs = retrieval_inputs or [self.retrieval]
        if artifacts is None:
            artifacts = build_pool_artifacts(
                topic_set=self.topics,
                retrieval_artifacts=inputs,
                source_records=self.source,
                policy=self.policy,
                generated_at=GENERATED_AT,
                git_revision=GIT_REVISION,
                status=status,
                git_worktree_clean=git_worktree_clean,
            )
        return write_pool_build_outputs(
            output_dir=output_dir,
            artifacts=artifacts,
            topic_set=self.topics,
            retrieval_inputs=inputs,
            source_records=self.source,
            policy=self.policy,
            generated_at=GENERATED_AT,
            git_revision=GIT_REVISION,
            git_worktree_clean=git_worktree_clean,
            duration_seconds=0.25,
            declared_input_paths=[TOPICS_PATH, RETRIEVAL_PATH, SOURCE_PATH, POLICY_PATH],
            project_root=PROJECT_ROOT,
        )

    def rewrite_statistics_for_pool(self, output_dir: Path, pool: dict) -> None:
        retrieval_payload = json.loads(
            (output_dir / MERGED_RETRIEVAL_FILENAME).read_text(encoding="utf-8")
        )
        topics = validate_topic_set(self.topics.payload)
        retrieval = validate_retrieval_provenance(retrieval_payload, topics=topics)
        universe = pool_builder_module.build_broad_candidate_universe(
            retrieval=retrieval, policy=pool["policy"]
        )
        counts, contribution = pool_builder_module._compute_statistics_values(
            topic_ids=sorted(topics),
            input_artifact_count=1,
            retrieval=retrieval,
            universe=universe,
            pool=pool,
        )
        statistics_path = output_dir / STATISTICS_FILENAME
        statistics = json.loads(statistics_path.read_text(encoding="utf-8"))
        pool_path = output_dir / PRECANONICAL_POOL_FILENAME
        statistics["candidate_pool"] = {
            "artifact_id": pool["artifact_id"],
            "sha256": sha256_file(pool_path),
            "pool_identity": pool["pool_identity"],
        }
        statistics["counts"] = counts
        statistics["per_system_contribution"] = contribution
        refresh_statistics_artifact_id(statistics)
        write_json(statistics_path, statistics)


class W6PoolHappyPathTests(W6PoolBuilderTestCase):
    def test_multi_query_multi_retriever_pool_and_counts(self) -> None:
        artifacts = self.build()
        self.assertEqual(
            artifacts.candidate_pool["topic_counts"],
            {
                "w6_fixture_topic_denoising": 6,
                "w6_fixture_topic_transients": 6,
            },
        )
        self.assertEqual(len(artifacts.candidate_pool["members"]), 12)
        self.assertEqual(artifacts.statistics["counts"]["included_run_count"], 6)
        self.assertEqual(artifacts.statistics["counts"]["raw_hit_count"], 17)
        self.assertEqual(artifacts.statistics["counts"]["unique_record_count"], 10)
        self.assertEqual(
            artifacts.statistics["counts"]["unique_topic_record_count"], 13
        )

    def test_arbitrary_n_artifacts_are_merged_without_algorithm_branches(self) -> None:
        parts = split_retrieval_artifact(self.retrieval.payload)
        artifacts = self.build(retrieval_artifacts=parts)
        self.assertEqual(artifacts.statistics["counts"]["input_artifact_count"], 2)
        self.assertEqual(len(artifacts.retrieval_provenance["runs"]), 6)
        self.assertEqual(len(artifacts.retrieval_provenance["hits"]), 17)
        families = {
            run["method"]["family"]
            for run in artifacts.retrieval_provenance["runs"]
        }
        self.assertGreaterEqual(len(families), 3)

    def test_multiple_query_variants_are_preserved_in_run_provenance(self) -> None:
        runs = self.build().retrieval_provenance["runs"]
        variants_by_topic: dict[str, set[str]] = {}
        for run in runs:
            variants_by_topic.setdefault(run["topic_id"], set()).add(
                run["query_variant_id"]
            )
        self.assertEqual(
            variants_by_topic,
            {
                "w6_fixture_topic_denoising": {"denoise_qv1", "denoise_qv2"},
                "w6_fixture_topic_transients": {"transient_qv1", "transient_qv2"},
            },
        )

    def test_single_retriever_only_candidate_is_preserved(self) -> None:
        members = {
            (row["topic_id"], row["record_id"]): row
            for row in self.build().candidate_pool["members"]
        }
        member = members[("w6_fixture_topic_transients", "rec_009")]
        self.assertEqual(member["source_system_membership"], ["dense_fixture"])
        self.assertIn("single_system_only", member["selection_reasons"])

    def test_below_depth_hit_is_retained_after_other_run_admits_candidate(self) -> None:
        members = {
            (row["topic_id"], row["record_id"]): row
            for row in self.build().candidate_pool["members"]
        }
        member = members[("w6_fixture_topic_denoising", "rec_003")]
        self.assertEqual(
            set(member["retrieval_hit_ids"]), {"hit_dbm_003", "hit_doa_003"}
        )
        self.assertEqual(
            member["selection_reasons"],
            ["depth_qualified:run_denoise_bm25", "multi_system_provenance"],
        )

    def test_precanonical_output_has_no_canonical_dependency(self) -> None:
        pool = self.build().candidate_pool
        self.assertEqual(pool["identity_stage"], "pre_canonicalization")
        self.assertNotIn("canonical_entities", pool["inputs"])
        self.assertTrue(
            all(member["canonical_entity_id"] is None for member in pool["members"])
        )

    def test_statistics_are_label_free_and_recomputable(self) -> None:
        statistics = self.build().statistics
        serialized = json.dumps(statistics, ensure_ascii=False).casefold()
        for forbidden in ("relevance_label", "final_label", "judgement", "benchmark"):
            self.assertNotIn(forbidden, serialized)
        counts = statistics["counts"]
        self.assertEqual(
            counts["multi_system_hit_count"] + counts["single_system_only_count"],
            counts["pool_size"],
        )
        self.assertTrue(all(counts["minimum_satisfied_by_topic"].values()))

    def test_public_w6_candidate_pool_validator_passes(self) -> None:
        artifacts = self.build()
        topics = validate_topic_set(self.topics.payload)
        retrieval = validate_retrieval_provenance(
            artifacts.retrieval_provenance, topics=topics
        )
        records = validate_source_records(
            self.source.payload, topics=topics, retrieval=retrieval
        )
        pool = artifacts.candidate_pool
        registry = {ref["artifact_id"]: dict(ref) for ref in pool["inputs"].values()}
        members = validate_candidate_pool(
            pool,
            topics=topics,
            records=records,
            retrieval=retrieval,
            registry=registry,
            canonical=None,
        )
        self.assertEqual(len(members), 12)


class W6PoolDeterminismTests(W6PoolBuilderTestCase):
    def test_same_inputs_and_seed_produce_identical_pool_identity(self) -> None:
        first = self.build()
        second = self.build()
        self.assertEqual(first.candidate_pool, second.candidate_pool)
        self.assertEqual(first.statistics, second.statistics)

    def test_build_time_does_not_change_merged_input_or_pool_identity(self) -> None:
        first = self.build()
        second = build_pool_artifacts(
            topic_set=self.topics,
            retrieval_artifacts=[self.retrieval],
            source_records=self.source,
            policy=self.policy,
            generated_at="2026-08-30T18:30:00+08:00",
            git_revision=GIT_REVISION,
        )
        self.assertEqual(first.retrieval_provenance, second.retrieval_provenance)
        self.assertEqual(
            first.candidate_pool["pool_identity"],
            second.candidate_pool["pool_identity"],
        )
        self.assertEqual(first.candidate_pool["members"], second.candidate_pool["members"])

    def test_retrieval_artifact_input_order_does_not_change_result(self) -> None:
        parts = split_retrieval_artifact(self.retrieval.payload)
        forward = self.build(retrieval_artifacts=parts)
        reverse = self.build(retrieval_artifacts=list(reversed(parts)))
        self.assertEqual(
            forward.retrieval_provenance, reverse.retrieval_provenance
        )
        self.assertEqual(forward.candidate_pool, reverse.candidate_pool)
        self.assertEqual(forward.statistics, reverse.statistics)

    def test_equal_instant_timestamps_are_canonical_across_input_order(self) -> None:
        parts = split_retrieval_artifact(self.retrieval.payload)
        representations = ("2026-08-24T08:00:00+08:00", "2026-08-24T00:00:00Z")
        normalized_parts = []
        for part, timestamp in zip(parts, representations, strict=True):
            payload = copy.deepcopy(part.payload)
            payload["created_at"] = timestamp
            payload["provenance"]["created_at"] = timestamp
            normalized_parts.append(loaded_copy(payload))

        forward = self.build(retrieval_artifacts=normalized_parts)
        reverse = self.build(retrieval_artifacts=list(reversed(normalized_parts)))

        self.assertEqual(
            forward.retrieval_provenance["created_at"],
            "2026-08-24T00:00:00+00:00",
        )
        self.assertEqual(forward.retrieval_provenance, reverse.retrieval_provenance)
        self.assertEqual(forward.candidate_pool, reverse.candidate_pool)
        self.assertEqual(forward.statistics, reverse.statistics)

    def test_latest_non_equivalent_timestamp_semantics_are_preserved(self) -> None:
        parts = split_retrieval_artifact(self.retrieval.payload)
        timestamps = ("2026-08-24T00:00:00Z", "2026-08-24T08:00:01+08:00")
        normalized_parts = []
        for part, timestamp in zip(parts, timestamps, strict=True):
            payload = copy.deepcopy(part.payload)
            payload["created_at"] = timestamp
            payload["provenance"]["created_at"] = timestamp
            normalized_parts.append(loaded_copy(payload))

        merged = self.build(retrieval_artifacts=normalized_parts).retrieval_provenance
        self.assertEqual(merged["created_at"], "2026-08-24T00:00:01+00:00")

    def test_different_seed_changes_only_deterministic_fill(self) -> None:
        baseline = self.build().candidate_pool
        changed = self.build(
            policy=self.modified_policy(
                lambda policy: policy["parameters"].__setitem__(
                    "deterministic_random_seed", 7
                )
            )
        ).candidate_pool
        baseline_depth = {
            (row["topic_id"], row["record_id"])
            for row in baseline["members"]
            if any(reason.startswith("depth_qualified:") for reason in row["selection_reasons"])
        }
        changed_depth = {
            (row["topic_id"], row["record_id"])
            for row in changed["members"]
            if any(reason.startswith("depth_qualified:") for reason in row["selection_reasons"])
        }
        baseline_all = {(row["topic_id"], row["record_id"]) for row in baseline["members"]}
        changed_all = {(row["topic_id"], row["record_id"]) for row in changed["members"]}
        self.assertEqual(baseline_depth, changed_depth)
        self.assertNotEqual(baseline_all, changed_all)

    def test_target_overflow_is_retained_and_reported(self) -> None:
        def mutate(policy: dict) -> None:
            policy["parameters"]["target_size_per_topic"] = 1
            policy["parameters"]["minimum_size_per_topic"] = 1
            policy["parameters"]["depth_by_system"] = {
                system: 100
                for system in policy["parameters"]["depth_by_system"]
            }

        artifacts = self.build(policy=self.modified_policy(mutate))
        self.assertGreater(artifacts.candidate_pool["topic_counts"]["w6_fixture_topic_denoising"], 1)
        self.assertTrue(
            all(
                value > 0
                for value in artifacts.statistics["counts"]["target_overflow_by_topic"].values()
            )
        )


class W6PoolFailureTests(W6PoolBuilderTestCase):
    def test_policy_hash_drift_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "policy SHA-256 drift"):
            load_frozen_pool_policy(POLICY_PATH, expected_sha256="0" * 64)

    def test_unknown_run_roster_drift_fails(self) -> None:
        def mutate(policy: dict) -> None:
            policy["included_retrieval_run_ids"][-1] = "run_unknown"

        with self.assertRaisesRegex(ValueError, "unknown retrieval run"):
            self.build(policy=self.modified_policy(mutate))

    def test_missing_system_depth_fails_closed(self) -> None:
        def mutate(policy: dict) -> None:
            del policy["parameters"]["depth_by_system"]["dense_fixture"]

        with self.assertRaisesRegex(ValueError, "精确覆盖"):
            self.build(policy=self.modified_policy(mutate))

    def test_minimum_policy_fails_when_pool_is_too_small(self) -> None:
        def mutate(policy: dict) -> None:
            policy["parameters"]["depth_by_system"] = {
                system: 1 for system in policy["parameters"]["depth_by_system"]
            }
            policy["parameters"]["random_fill_enabled"] = False
            policy["parameters"]["target_size_per_topic"] = 8
            policy["parameters"]["minimum_size_per_topic"] = 5

        with self.assertRaisesRegex(ValueError, "小于 minimum"):
            self.build(policy=self.modified_policy(mutate))

    def test_missing_source_hit_reference_fails(self) -> None:
        source = copy.deepcopy(self.source.payload)
        source["records"][0]["acquisition_provenance_refs"].remove("hit_doa_001")
        with self.assertRaisesRegex(ValueError, "未闭合 retrieval hits"):
            self.build(source=loaded_copy(source))

    def test_extra_unknown_source_hit_reference_fails(self) -> None:
        source = copy.deepcopy(self.source.payload)
        source["records"][0]["acquisition_provenance_refs"].append("hit_unknown")
        with self.assertRaisesRegex(ValueError, "dangling/mismatch"):
            self.build(source=loaded_copy(source))

    def test_missing_member_hit_fails_even_after_pool_identity_recomputed(self) -> None:
        artifacts = self.build()
        pool = copy.deepcopy(artifacts.candidate_pool)
        member = next(
            row for row in pool["members"] if row["record_id"] == "rec_003"
        )
        member["retrieval_hit_ids"] = ["hit_dbm_003"]
        member["source_system_membership"] = ["bm25_fixture"]
        pool["pool_identity"] = compute_pool_identity(pool)
        topics = validate_topic_set(self.topics.payload)
        retrieval = validate_retrieval_provenance(
            artifacts.retrieval_provenance, topics=topics
        )
        records = validate_source_records(
            self.source.payload, topics=topics, retrieval=retrieval
        )
        registry = {ref["artifact_id"]: dict(ref) for ref in pool["inputs"].values()}
        with self.assertRaisesRegex(ValueError, "provenance union"):
            validate_candidate_pool(
                pool,
                topics=topics,
                records=records,
                retrieval=retrieval,
                registry=registry,
                canonical=None,
            )

    def test_extra_expected_hit_is_detected(self) -> None:
        artifacts = self.build()
        topics = validate_topic_set(self.topics.payload)
        retrieval_payload = copy.deepcopy(artifacts.retrieval_provenance)
        extra = copy.deepcopy(retrieval_payload["hits"][0])
        extra["retrieval_hit_id"] = "hit_extra_001"
        extra["source_rank"] = 99
        retrieval_payload["hits"].append(extra)
        retrieval = validate_retrieval_provenance(retrieval_payload, topics=topics)
        records = validate_source_records(
            self.source.payload, topics=topics, retrieval=validate_retrieval_provenance(
                artifacts.retrieval_provenance, topics=topics
            )
        )
        pool = artifacts.candidate_pool
        registry = {ref["artifact_id"]: dict(ref) for ref in pool["inputs"].values()}
        with self.assertRaisesRegex(ValueError, "provenance union"):
            validate_candidate_pool(
                pool,
                topics=topics,
                records=records,
                retrieval=retrieval,
                registry=registry,
                canonical=None,
            )

    def test_duplicate_hits_collapse_candidate_but_keep_all_hit_refs(self) -> None:
        retrieval = copy.deepcopy(self.retrieval.payload)
        duplicate = next(
            copy.deepcopy(hit)
            for hit in retrieval["hits"]
            if hit["retrieval_hit_id"] == "hit_tde_009"
        )
        duplicate["retrieval_hit_id"] = "hit_tde_009_alias"
        duplicate["source_rank"] = 99
        retrieval["hits"].append(duplicate)
        source = copy.deepcopy(self.source.payload)
        record = next(row for row in source["records"] if row["record_id"] == "rec_009")
        record["acquisition_provenance_refs"].append("hit_tde_009_alias")
        artifacts = self.build(
            retrieval_artifacts=[loaded_copy(retrieval)], source=loaded_copy(source)
        )
        members = [
            row for row in artifacts.candidate_pool["members"] if row["record_id"] == "rec_009"
        ]
        self.assertEqual(len(members), 1)
        self.assertEqual(
            set(members[0]["retrieval_hit_ids"]),
            {"hit_tde_009", "hit_tde_009_alias"},
        )

    def test_duplicate_run_across_artifacts_fails(self) -> None:
        duplicate = copy.deepcopy(self.retrieval.payload)
        duplicate["artifact_id"] = "w6_fixture_retrieval_duplicate"
        with self.assertRaisesRegex(ValueError, "duplicate run"):
            self.build(retrieval_artifacts=[self.retrieval, loaded_copy(duplicate)])

    def test_invalid_score_direction_fails(self) -> None:
        retrieval = copy.deepcopy(self.retrieval.payload)
        retrieval["hits"][0]["score_direction"] = "lower_is_better"
        with self.assertRaisesRegex(ValueError, "score_direction"):
            self.build(retrieval_artifacts=[loaded_copy(retrieval)])

    def test_nonfinite_score_fails(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                retrieval = copy.deepcopy(self.retrieval.payload)
                retrieval["hits"][0]["source_score"] = value
                with self.assertRaisesRegex(ValueError, "有限"):
                    self.build(retrieval_artifacts=[loaded_copy(retrieval)])

    def test_policy_semantic_drift_fails(self) -> None:
        for field, value, message in (
            ("target_overflow_policy", "truncate", "target_overflow_policy"),
            ("duplicate_hit_handling", "drop_duplicates", "duplicate_hit_handling"),
        ):
            with self.subTest(field=field):
                changed = self.modified_policy(
                    lambda policy, field=field, value=value: policy["parameters"].__setitem__(field, value)
                )
                with self.assertRaisesRegex(ValueError, message):
                    self.build(policy=changed)


class W6PoolBackendAndCliTests(W6PoolBuilderTestCase):
    def test_offline_fake_backend_is_called_once(self) -> None:
        backend = FakeRetrievalBackend(split_retrieval_artifact(self.retrieval.payload))
        with mock.patch("requests.get") as request_get:
            artifacts = build_pool_from_backend(
                backend=backend,
                topic_set=self.topics,
                source_records=self.source,
                policy=self.policy,
                generated_at=GENERATED_AT,
                git_revision=GIT_REVISION,
            )
        self.assertEqual(backend.call_count, 1)
        self.assertEqual(artifacts.statistics["counts"]["pool_size"], 12)
        request_get.assert_not_called()

    def test_cli_has_no_label_benchmark_or_canonical_inputs(self) -> None:
        destinations = {action.dest for action in build_parser()._actions}
        serialized = " ".join(sorted(destinations)).casefold()
        for forbidden in ("label", "benchmark", "judgement", "canonical"):
            self.assertNotIn(forbidden, serialized)

    def test_cli_writes_hash_bound_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            with contextlib.redirect_stdout(io.StringIO()):
                result = build_cli_main(
                    [
                        "--topics",
                        str(TOPICS_PATH),
                        "--retrieval",
                        str(RETRIEVAL_PATH),
                        "--source-records",
                        str(SOURCE_PATH),
                        "--policy",
                        str(POLICY_PATH),
                        "--policy-sha256",
                        POLICY_SHA256,
                        "--output-dir",
                        str(output),
                    ]
                )
            self.assertEqual(result, 0)
            manifest = validate_pool_build_manifest(
                output / "build_manifest.json", **self.validator_kwargs()
            )
            self.assertEqual(
                manifest["outputs"]["candidate_pool"]["sha256"],
                sha256_file(output / "precanonical_candidate_pool.json"),
            )

    def test_output_hash_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            with contextlib.redirect_stdout(io.StringIO()):
                result = build_cli_main(
                    [
                        "--topics",
                        str(TOPICS_PATH),
                        "--retrieval",
                        str(RETRIEVAL_PATH),
                        "--source-records",
                        str(SOURCE_PATH),
                        "--policy",
                        str(POLICY_PATH),
                        "--policy-sha256",
                        POLICY_SHA256,
                        "--output-dir",
                        str(output),
                    ]
                )
            self.assertEqual(result, 0)
            statistics = output / "pool_statistics.json"
            statistics.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output hash drift"):
                validate_pool_build_manifest(
                    output / "build_manifest.json", **self.validator_kwargs()
                )

    def test_frozen_cli_requires_clean_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.w6_candidate_pool_builder.capture_git_state",
            return_value={"git_revision": GIT_REVISION, "git_worktree_clean": False},
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                result = build_cli_main(
                    [
                        "--topics",
                        str(TOPICS_PATH),
                        "--retrieval",
                        str(RETRIEVAL_PATH),
                        "--source-records",
                        str(SOURCE_PATH),
                        "--policy",
                        str(POLICY_PATH),
                        "--policy-sha256",
                        POLICY_SHA256,
                        "--output-dir",
                        str(Path(temp_dir) / "pool"),
                        "--status",
                        "frozen",
                    ]
                )
        self.assertEqual(result, 1)


class W6PoolPackageClosureTests(W6PoolBuilderTestCase):
    def assert_package_hashes_are_self_consistent(self, output_dir: Path) -> None:
        manifest = json.loads(
            (output_dir / BUILD_MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        output_hashes = {}
        for logical_name, filename in OUTPUT_FILES.items():
            reference = manifest["outputs"][logical_name]
            self.assertEqual(reference["sha256"], sha256_file(output_dir / filename))
            output_hashes[filename] = reference["sha256"]
        expected_id = canonical_json_sha256(
            {
                "pool_identity": manifest["outputs"]["candidate_pool"]["pool_identity"],
                "policy_sha256": manifest["policy"]["sha256"],
                "outputs": output_hashes,
            }
        )
        self.assertEqual(manifest["artifact_id"], f"w6_pool_build_{expected_id[:24]}")

    def test_self_consistent_missing_below_depth_hit_fails_package_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            self.write_package(output)
            pool_path = output / PRECANONICAL_POOL_FILENAME
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            member = next(
                row
                for row in pool["members"]
                if row["topic_id"] == "w6_fixture_topic_denoising"
                and row["record_id"] == "rec_003"
            )
            member["retrieval_hit_ids"].remove("hit_doa_003")
            member["source_system_membership"] = ["bm25_fixture"]
            member["selection_reasons"].remove("multi_system_provenance")
            pool["pool_identity"] = compute_pool_identity(pool)
            pool["artifact_id"] = (
                "w6_precanonical_pool_" + pool["pool_identity"].rsplit(":", 1)[-1][:24]
            )
            write_json(pool_path, pool)
            self.rewrite_statistics_for_pool(output, pool)
            repack_build_manifest(output)

            self.assert_package_hashes_are_self_consistent(output)
            with self.assertRaisesRegex(ValueError, "semantic closure drift：candidate_pool"):
                validate_pool_build_manifest(
                    output / BUILD_MANIFEST_FILENAME, **self.validator_kwargs()
                )

    def test_self_consistent_statistics_pool_size_repack_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            self.write_package(output)
            statistics_path = output / STATISTICS_FILENAME
            statistics = json.loads(statistics_path.read_text(encoding="utf-8"))
            statistics["counts"]["pool_size"] = 999
            refresh_statistics_artifact_id(statistics)
            write_json(statistics_path, statistics)
            repack_build_manifest(output)

            self.assert_package_hashes_are_self_consistent(output)
            with self.assertRaisesRegex(ValueError, "semantic closure drift：pool_statistics"):
                validate_pool_build_manifest(
                    output / BUILD_MANIFEST_FILENAME, **self.validator_kwargs()
                )

    def test_self_consistent_system_contribution_repack_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            self.write_package(output)
            statistics_path = output / STATISTICS_FILENAME
            statistics = json.loads(statistics_path.read_text(encoding="utf-8"))
            statistics["per_system_contribution"]["openalex_native"][
                "pool_member_count"
            ] = 999
            refresh_statistics_artifact_id(statistics)
            write_json(statistics_path, statistics)
            repack_build_manifest(output)

            self.assert_package_hashes_are_self_consistent(output)
            with self.assertRaisesRegex(ValueError, "semantic closure drift：pool_statistics"):
                validate_pool_build_manifest(
                    output / BUILD_MANIFEST_FILENAME, **self.validator_kwargs()
                )

    def test_self_consistent_pool_input_reference_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            self.write_package(output)
            pool_path = output / PRECANONICAL_POOL_FILENAME
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["inputs"]["source_records"]["artifact_id"] = (
                "w6_fixture_source_records_drift"
            )
            pool["pool_identity"] = compute_pool_identity(pool)
            pool["artifact_id"] = (
                "w6_precanonical_pool_" + pool["pool_identity"].rsplit(":", 1)[-1][:24]
            )
            write_json(pool_path, pool)
            self.rewrite_statistics_for_pool(output, pool)
            repack_build_manifest(output)

            self.assert_package_hashes_are_self_consistent(output)
            with self.assertRaisesRegex(ValueError, "semantic closure drift：candidate_pool"):
                validate_pool_build_manifest(
                    output / BUILD_MANIFEST_FILENAME, **self.validator_kwargs()
                )

    def test_manifest_cannot_self_bless_changed_input_roster(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            self.write_package(output)
            manifest_path = output / BUILD_MANIFEST_FILENAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["inputs"]["retrieval_provenance_inputs"][0]["artifact_id"] = (
                "w6_fixture_retrieval_changed"
            )
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(ValueError, "input binding/roster drift"):
                validate_pool_build_manifest(manifest_path, **self.validator_kwargs())

    def test_removed_retrieval_run_with_repacked_output_hash_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            self.write_package(output)
            manifest = json.loads(
                (output / BUILD_MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            retrieval_path = output / MERGED_RETRIEVAL_FILENAME
            retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
            removed_run = "run_denoise_tail"
            retrieval["runs"] = [
                run
                for run in retrieval["runs"]
                if run["retrieval_run_id"] != removed_run
            ]
            retrieval["hits"] = [
                hit
                for hit in retrieval["hits"]
                if hit["retrieval_run_id"] != removed_run
            ]
            identity = canonical_json_sha256(
                {
                    "input_artifacts": manifest["inputs"][
                        "retrieval_provenance_inputs"
                    ],
                    "run_ids": sorted(
                        run["retrieval_run_id"] for run in retrieval["runs"]
                    ),
                    "hit_ids": sorted(
                        hit["retrieval_hit_id"] for hit in retrieval["hits"]
                    ),
                }
            )
            retrieval["artifact_id"] = f"w6_retrieval_union_{identity[:24]}"
            write_json(retrieval_path, retrieval)
            repack_build_manifest(output)

            self.assert_package_hashes_are_self_consistent(output)
            with self.assertRaisesRegex(
                ValueError, "semantic closure drift：retrieval_provenance"
            ):
                validate_pool_build_manifest(
                    output / BUILD_MANIFEST_FILENAME, **self.validator_kwargs()
                )

    def test_file_backed_input_is_reloaded_during_package_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "inputs"
            input_dir.mkdir()
            topic_path = input_dir / "topics.json"
            topic_path.write_bytes(TOPICS_PATH.read_bytes())
            topic_set = load_json_artifact(topic_path, label="topics")
            artifacts = build_pool_artifacts(
                topic_set=topic_set,
                retrieval_artifacts=[self.retrieval],
                source_records=self.source,
                policy=self.policy,
                generated_at=GENERATED_AT,
                git_revision=GIT_REVISION,
            )
            output = Path(temp_dir) / "pool"
            manifest_path = write_pool_build_outputs(
                output_dir=output,
                artifacts=artifacts,
                topic_set=topic_set,
                retrieval_inputs=[self.retrieval],
                source_records=self.source,
                policy=self.policy,
                generated_at=GENERATED_AT,
                git_revision=GIT_REVISION,
                git_worktree_clean=False,
                duration_seconds=0.25,
                declared_input_paths=[
                    topic_path,
                    RETRIEVAL_PATH,
                    SOURCE_PATH,
                    POLICY_PATH,
                ],
                project_root=PROJECT_ROOT,
            )
            topic_path.write_bytes(topic_path.read_bytes() + b"\n")

            with self.assertRaisesRegex(ValueError, "bytes/payload drift"):
                validate_pool_build_manifest(
                    manifest_path,
                    topic_set=topic_set,
                    retrieval_inputs=[self.retrieval],
                    source_records=self.source,
                    policy=self.policy,
                )


class W6PoolFrozenSafetyTests(W6PoolBuilderTestCase):
    def test_reusable_build_frozen_requires_clean_and_candidate_allows_dirty(self) -> None:
        with self.assertRaisesRegex(ValueError, "git_worktree_clean=true"):
            build_pool_artifacts(
                topic_set=self.topics,
                retrieval_artifacts=[self.retrieval],
                source_records=self.source,
                policy=self.policy,
                generated_at=GENERATED_AT,
                git_revision=GIT_REVISION,
                status="frozen",
                git_worktree_clean=False,
            )
        frozen = build_pool_artifacts(
            topic_set=self.topics,
            retrieval_artifacts=[self.retrieval],
            source_records=self.source,
            policy=self.policy,
            generated_at=GENERATED_AT,
            git_revision=GIT_REVISION,
            status="frozen",
            git_worktree_clean=True,
        )
        candidate = build_pool_artifacts(
            topic_set=self.topics,
            retrieval_artifacts=[self.retrieval],
            source_records=self.source,
            policy=self.policy,
            generated_at=GENERATED_AT,
            git_revision=GIT_REVISION,
            status="candidate",
            git_worktree_clean=False,
        )
        self.assertEqual(frozen.candidate_pool["status"], "frozen")
        self.assertEqual(candidate.candidate_pool["status"], "candidate")

    def test_reusable_backend_frozen_dirty_fails(self) -> None:
        backend = FakeRetrievalBackend([self.retrieval])
        with self.assertRaisesRegex(ValueError, "git_worktree_clean=true"):
            build_pool_from_backend(
                backend=backend,
                topic_set=self.topics,
                source_records=self.source,
                policy=self.policy,
                generated_at=GENERATED_AT,
                git_revision=GIT_REVISION,
                status="frozen",
                git_worktree_clean=False,
            )

    def test_write_and_manifest_layers_enforce_frozen_clean_invariant(self) -> None:
        frozen = build_pool_artifacts(
            topic_set=self.topics,
            retrieval_artifacts=[self.retrieval],
            source_records=self.source,
            policy=self.policy,
            generated_at=GENERATED_AT,
            git_revision=GIT_REVISION,
            status="frozen",
            git_worktree_clean=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            rejected = Path(temp_dir) / "dirty"
            with self.assertRaisesRegex(ValueError, "git_worktree_clean=true"):
                self.write_package(
                    rejected, artifacts=frozen, git_worktree_clean=False
                )
            self.assertFalse(rejected.exists())

            accepted = Path(temp_dir) / "clean"
            manifest_path = self.write_package(
                accepted, artifacts=frozen, git_worktree_clean=True
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["generation"]["git_worktree_clean"] = False
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "git_worktree_clean=true"):
                validate_pool_build_manifest(manifest_path, **self.validator_kwargs())

    def test_frozen_output_rejects_input_and_repository_evidence_trees(self) -> None:
        frozen = build_pool_artifacts(
            topic_set=self.topics,
            retrieval_artifacts=[self.retrieval],
            source_records=self.source,
            policy=self.policy,
            generated_at=GENERATED_AT,
            git_revision=GIT_REVISION,
            status="frozen",
            git_worktree_clean=True,
        )
        unsafe_outputs = (
            BOOTSTRAP / "new-dir",
            PROJECT_ROOT,
            PROJECT_ROOT / "data" / "benchmarks" / "new-w6-output",
            PROJECT_ROOT / "data" / "analysis" / "w5_methods" / "new-w6-output",
        )
        for output in unsafe_outputs:
            with self.subTest(output=output), self.assertRaisesRegex(
                ValueError, "重合|evidence tree"
            ):
                self.write_package(
                    output, artifacts=frozen, git_worktree_clean=True
                )

        candidate = self.build()
        with self.assertRaisesRegex(ValueError, "evidence tree"):
            self.write_package(
                PROJECT_ROOT / "data" / "benchmarks" / "candidate-output",
                artifacts=candidate,
                git_worktree_clean=False,
            )

    def test_frozen_output_resolves_directory_symlink_when_supported(self) -> None:
        frozen = build_pool_artifacts(
            topic_set=self.topics,
            retrieval_artifacts=[self.retrieval],
            source_records=self.source,
            policy=self.policy,
            generated_at=GENERATED_AT,
            git_revision=GIT_REVISION,
            status="frozen",
            git_worktree_clean=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            link = Path(temp_dir) / "bootstrap-link"
            try:
                link.symlink_to(BOOTSTRAP, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"当前平台不允许创建目录 symlink/junction：{error}")
            with self.assertRaisesRegex(ValueError, "声明输入树重合"):
                self.write_package(
                    link / "new-dir", artifacts=frozen, git_worktree_clean=True
                )


class W6PoolAtomicPublicationTests(W6PoolBuilderTestCase):
    def test_partial_write_failure_does_not_expose_final_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            original_write_bytes = Path.write_bytes

            def fail_on_candidate_pool(path: Path, content: bytes) -> int:
                if path.name == PRECANONICAL_POOL_FILENAME:
                    raise OSError("injected second-file failure")
                return original_write_bytes(path, content)

            with mock.patch.object(Path, "write_bytes", new=fail_on_candidate_pool):
                with self.assertRaisesRegex(OSError, "second-file failure"):
                    self.write_package(output)
            self.assertFalse(output.exists())

    def test_semantic_validation_failure_does_not_expose_final_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pool"
            with mock.patch(
                "src.w6_candidate_pool_builder.validate_pool_build_manifest",
                side_effect=ValueError("injected semantic validation failure"),
            ):
                with self.assertRaisesRegex(ValueError, "semantic validation failure"):
                    self.write_package(output)
            self.assertFalse(output.exists())


class W6PoolPolicyConstantsTests(unittest.TestCase):
    def test_frozen_policy_strings_are_explicit(self) -> None:
        self.assertEqual(
            TARGET_OVERFLOW_POLICY, "retain_all_depth_qualified_candidates"
        )
        self.assertEqual(
            DUPLICATE_HIT_POLICY, "deduplicate_topic_record_keep_all_hit_refs"
        )


if __name__ == "__main__":
    unittest.main()
