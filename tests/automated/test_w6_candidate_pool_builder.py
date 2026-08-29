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
from src.annotation_tasks import sha256_file
from src.w6_candidate_pool_builder import (
    DUPLICATE_HIT_POLICY,
    TARGET_OVERFLOW_POLICY,
    LoadedArtifact,
    build_pool_artifacts,
    build_pool_from_backend,
    load_frozen_pool_policy,
    load_json_artifact,
    validate_pool_build_manifest,
)
from src.w6_contracts import (
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


def loaded_copy(payload: dict) -> LoadedArtifact:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return LoadedArtifact(payload=payload, sha256=hashlib.sha256(encoded).hexdigest())


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
            manifest = validate_pool_build_manifest(output / "build_manifest.json")
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
                validate_pool_build_manifest(output / "build_manifest.json")

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
