"""Issue #64 tests for W6 Topic freeze and Benchmark workflow."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.build_w6_benchmark import build_parser as build_benchmark_cli_parser
from src.annotation_tasks import sha256_file
from src.w6_benchmark import (
    artifact_paths_from_bootstrap_bundle,
    build_empty_second_annotation_payload,
    build_review_plan_payload,
    build_w6_benchmark_package,
    compute_package_identity,
    validate_annotation_protocol,
    validate_benchmark_status_gate,
    validate_frozen_topic_roster,
    validate_second_annotation_results,
    validate_topic_freeze_files,
    validate_w6_benchmark_package,
)
from src.w6_contracts import (
    compute_benchmark_identity,
    compute_pool_identity,
    compute_split_identity,
    load_json_object,
    validate_topic_split,
    validate_w6_bootstrap_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_bootstrap"
    / "valid"
    / "bundle_manifest.json"
)
REAL_PROTOCOL = PROJECT_ROOT / "configs" / "w6" / "annotation_protocol_v1.json"
PROTOCOL = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_issue64"
    / "annotation_protocol_fixture.json"
)
RESEARCH_ROOT = PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha"
COMMITTED_BENCHMARK_FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_issue64"
    / "benchmark_package"
    / "package_manifest.json"
)
BASE_REVISION = "90811052194801263708627c1eda39a2765e9037"


class W6TopicFreezeTests(unittest.TestCase):
    def test_real_topic_roster_and_topic_level_split_pass(self) -> None:
        result = validate_topic_freeze_files(
            RESEARCH_ROOT / "topics.json",
            RESEARCH_ROOT / "split_manifest.json",
            research_path=RESEARCH_ROOT / "topic_research.json",
        )
        self.assertEqual(len(result["topics"]), 9)
        self.assertEqual(len(result["split_sets"]["dev"]), 5)
        self.assertEqual(len(result["split_sets"]["hidden"]), 4)
        self.assertFalse(result["split_sets"]["dev"] & result["split_sets"]["hidden"])

    def test_near_duplicate_topic_question_fails(self) -> None:
        payload = load_json_object(RESEARCH_ROOT / "topics.json")
        duplicate = copy.deepcopy(payload["topics"][0])
        duplicate["topic_id"] = "w6_topic_duplicate_question"
        duplicate["research_question"] = payload["topics"][1]["research_question"]
        duplicate["acquisition_query_variants"][0]["query_variant_id"] = "dup_qv1"
        duplicate["acquisition_query_variants"][0][
            "query_text"
        ] = "unique duplicate test query one"
        duplicate["acquisition_query_variants"][1]["query_variant_id"] = "dup_qv2"
        duplicate["acquisition_query_variants"][1][
            "query_text"
        ] = "unique duplicate test query two"
        payload["topics"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "near-duplicate research question"):
            validate_frozen_topic_roster(payload)

    def test_scope_in_out_contradiction_fails(self) -> None:
        payload = load_json_object(RESEARCH_ROOT / "topics.json")
        payload["topics"][0]["scope_out"][0] = payload["topics"][0]["scope_in"][0]
        with self.assertRaisesRegex(ValueError, "自相矛盾"):
            validate_frozen_topic_roster(payload)

    def test_split_overlap_and_hash_drift_fail(self) -> None:
        topics = validate_frozen_topic_roster(
            load_json_object(RESEARCH_ROOT / "topics.json")
        )
        split = load_json_object(RESEARCH_ROOT / "split_manifest.json")
        split["hidden_test_topic_ids"].append(split["dev_topic_ids"][0])
        split["split_identity"] = compute_split_identity(split)
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_topic_split(split, topics=topics)

        split = load_json_object(RESEARCH_ROOT / "split_manifest.json")
        split["topic_set"]["sha256"] = "0" * 64
        split["split_identity"] = compute_split_identity(split)
        with tempfile.TemporaryDirectory() as temp_dir:
            split_path = Path(temp_dir) / "split.json"
            split_path.write_text(json.dumps(split), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "actual frozen Topic Set hash|实际 frozen Topic Set hash"
            ):
                validate_topic_freeze_files(RESEARCH_ROOT / "topics.json", split_path)

    def test_split_chronology_fails(self) -> None:
        split = load_json_object(RESEARCH_ROOT / "split_manifest.json")
        split["frozen_at"] = "2026-08-24T14:00:00+08:00"
        split["split_identity"] = compute_split_identity(split)
        with tempfile.TemporaryDirectory() as temp_dir:
            split_path = Path(temp_dir) / "split.json"
            split_path.write_text(json.dumps(split), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不得早于 Topic Set"):
                validate_topic_freeze_files(RESEARCH_ROOT / "topics.json", split_path)

    def test_viability_after_topic_freeze_fails(self) -> None:
        research = load_json_object(RESEARCH_ROOT / "topic_research.json")
        research["viability_evidence"][0]["checked_at"] = "2026-08-24T14:18:01+08:00"
        with tempfile.TemporaryDirectory() as temp_dir:
            research_path = Path(temp_dir) / "topic_research.json"
            research_path.write_text(json.dumps(research), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不得晚于 Topic research freeze"):
                validate_topic_freeze_files(
                    RESEARCH_ROOT / "topics.json",
                    RESEARCH_ROOT / "split_manifest.json",
                    research_path=research_path,
                )


class W6AnnotationProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BOOTSTRAP)
        cls.protocol = validate_annotation_protocol(load_json_object(PROTOCOL))

    def test_protocol_is_blind_evidence_backed_and_preregistered(self) -> None:
        protocol = self.protocol
        self.assertTrue(protocol["frozen_before_annotations"])
        self.assertFalse(protocol["review_policy"]["ranking_signals_allowed"])
        self.assertEqual(
            protocol["evidence_policy"]["private_reasoning_storage"], "forbidden"
        )
        self.assertIn(
            "lookup_status", protocol["evidence_policy"]["required_result_fields"]
        )

    def test_blind_leakage_policy_drift_fails(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["blind_view"]["forbidden_signals"].remove("rank")
        with self.assertRaisesRegex(ValueError, "leakage keys"):
            validate_annotation_protocol(protocol)

    def test_review_plan_is_deterministic_and_exposes_incomplete_review(self) -> None:
        kwargs = self._review_plan_kwargs()
        first = build_review_plan_payload(**kwargs)
        second = build_review_plan_payload(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(
            first["coverage"]["missing_review_annotation_ids"],
            ["annotation_denoise_005"],
        )
        reasons = {
            item["annotation_id"]: item["reasons"] for item in first["review_items"]
        }
        self.assertIn("nonempty_uncertainty", reasons["annotation_denoise_005"])

    def test_insufficient_evidence_enters_review_without_ranking_signal(self) -> None:
        kwargs = self._review_plan_kwargs()
        kwargs["evidence_lookup_statuses"] = {
            annotation_id: "not_needed" for annotation_id in self.bundle["annotations"]
        }
        kwargs["evidence_lookup_statuses"]["annotation_denoise_001"] = "insufficient"
        plan = build_review_plan_payload(**kwargs)
        item = next(
            row
            for row in plan["review_items"]
            if row["annotation_id"] == "annotation_denoise_001"
        )
        self.assertIn("evidence_insufficient", item["reasons"])
        self.assertNotIn("rank", json.dumps(plan))

    def test_non_independent_reviewer_fails(self) -> None:
        reviews = copy.deepcopy(self.bundle["reviews"])
        target = reviews["review_denoise_002"]
        target["reviewer_id"] = self.bundle["annotations"][target["annotation_id"]][
            "annotation_provenance"
        ]["actor_id"]
        target["provenance"]["created_by"] = target["reviewer_id"]
        kwargs = self._review_plan_kwargs()
        kwargs["reviews"] = reviews
        with self.assertRaisesRegex(ValueError, "reviewer 不独立"):
            build_review_plan_payload(**kwargs)

    def test_protocol_frozen_after_primary_annotation_fails(self) -> None:
        kwargs = self._review_plan_kwargs()
        protocol = copy.deepcopy(self.protocol)
        protocol["frozen_at"] = "2026-08-24T08:49:00+08:00"
        kwargs["protocol"] = protocol
        with self.assertRaisesRegex(ValueError, "晚于 primary annotation"):
            build_review_plan_payload(**kwargs)

    def test_second_annotation_independence_conflict_and_gate(self) -> None:
        target = self.bundle["annotations"]["annotation_denoise_005"]
        task_id = target["annotation_task_id"]
        second_payload = self._second_payload(target, relevance_label=2)
        seconds = validate_second_annotation_results(
            second_payload,
            annotations={target["annotation_id"]: target},
            tasks={task_id: self.bundle["annotation_tasks"][task_id]},
            task_mappings={task_id: self.bundle["annotation_task_mappings"][task_id]},
            selected_task_ids=[task_id],
            protocol=self.protocol,
            primary_annotation_reference=second_payload["primary_annotations"],
            protocol_reference=second_payload["annotation_protocol"],
        )
        kwargs = self._review_plan_kwargs()
        kwargs.update(
            {
                "annotations": {target["annotation_id"]: target},
                "reviews": {},
                "tasks": {task_id: self.bundle["annotation_tasks"][task_id]},
                "task_mappings": {
                    task_id: self.bundle["annotation_task_mappings"][task_id]
                },
                "second_annotations": seconds,
            }
        )
        plan = build_review_plan_payload(**kwargs)
        self.assertEqual(plan["conflicting_annotation_ids"], [target["annotation_id"]])
        self.assertEqual(
            plan["coverage"]["missing_conflict_adjudication_annotation_ids"],
            [target["annotation_id"]],
        )
        graph = {
            "pool_members": {
                target["pool_item_id"]: {
                    "topic_id": target["topic_id"],
                    "record_id": target["record_id"],
                }
            },
            "split_sets": {"dev": {target["topic_id"]}, "hidden": set()},
            "annotations": {target["annotation_id"]: target},
        }
        with self.assertRaisesRegex(ValueError, "unadjudicated annotation conflict"):
            validate_benchmark_status_gate(
                "sealed_candidate", graph=graph, review_plan=plan
            )

        review = {
            "review_id": "review_denoise_005_conflict",
            "annotation_id": target["annotation_id"],
            "topic_id": target["topic_id"],
            "pool_item_id": target["pool_item_id"],
            "reviewer_type": "human",
            "reviewer_id": "fixture_adjudicator",
            "decision": "modify",
            "final_label": 1,
            "reviewed_at": "2026-08-24T08:49:00+08:00",
            "review_note": "The primary and second judgements are preserved; final label is partial.",
            "provenance": {
                "kind": "synthetic_conflict_adjudication_fixture",
                "created_by": "fixture_adjudicator",
                "created_at": "2026-08-24T08:49:00+08:00",
                "git_revision": BASE_REVISION,
            },
        }
        kwargs["reviews"] = {review["review_id"]: review}
        adjudicated = build_review_plan_payload(**kwargs)
        self.assertFalse(
            adjudicated["coverage"]["missing_conflict_adjudication_annotation_ids"]
        )
        validate_benchmark_status_gate(
            "sealed_candidate", graph=graph, review_plan=adjudicated
        )
        self.assertEqual(target["relevance_label"], 0)
        self.assertEqual(seconds[task_id]["relevance_label"], 2)
        self.assertEqual(review["final_label"], 1)

    def test_selected_second_missing_result_fails_sealed_gate(self) -> None:
        kwargs = self._review_plan_kwargs()
        plan = build_review_plan_payload(**kwargs)
        graph = copy.deepcopy(self.bundle)
        annotated_pool_ids = {
            annotation["pool_item_id"] for annotation in graph["annotations"].values()
        }
        graph["pool_members"] = {
            item_id: member
            for item_id, member in graph["pool_members"].items()
            if item_id in annotated_pool_ids
        }
        with self.assertRaisesRegex(
            ValueError, "incomplete selected second annotation"
        ):
            validate_benchmark_status_gate(
                "sealed_candidate", graph=graph, review_plan=plan
            )

    def test_second_same_actor_and_invalid_chronology_fail(self) -> None:
        target = self.bundle["annotations"]["annotation_denoise_005"]
        task_id = target["annotation_task_id"]
        kwargs = {
            "annotations": {target["annotation_id"]: target},
            "tasks": {task_id: self.bundle["annotation_tasks"][task_id]},
            "task_mappings": {
                task_id: self.bundle["annotation_task_mappings"][task_id]
            },
            "selected_task_ids": [task_id],
            "protocol": self.protocol,
        }
        same_actor = self._second_payload(target, relevance_label=0)
        same_actor["annotations"][0]["annotation_provenance"]["actor_id"] = target[
            "annotation_provenance"
        ]["actor_id"]
        with self.assertRaisesRegex(ValueError, "second annotator 不独立"):
            validate_second_annotation_results(
                same_actor,
                primary_annotation_reference=same_actor["primary_annotations"],
                protocol_reference=same_actor["annotation_protocol"],
                **kwargs,
            )
        early = self._second_payload(target, relevance_label=0)
        early["annotations"][0]["annotation_provenance"][
            "created_at"
        ] = "2026-08-24T08:47:59+08:00"
        with self.assertRaisesRegex(ValueError, "时间早于 primary"):
            validate_second_annotation_results(
                early,
                primary_annotation_reference=early["primary_annotations"],
                protocol_reference=early["annotation_protocol"],
                **kwargs,
            )

    def test_review_before_second_annotation_fails(self) -> None:
        target = self.bundle["annotations"]["annotation_denoise_005"]
        task_id = target["annotation_task_id"]
        second_payload = self._second_payload(target, relevance_label=2)
        seconds = validate_second_annotation_results(
            second_payload,
            annotations={target["annotation_id"]: target},
            tasks={task_id: self.bundle["annotation_tasks"][task_id]},
            task_mappings={task_id: self.bundle["annotation_task_mappings"][task_id]},
            selected_task_ids=[task_id],
            protocol=self.protocol,
            primary_annotation_reference=second_payload["primary_annotations"],
            protocol_reference=second_payload["annotation_protocol"],
        )
        review = copy.deepcopy(self.bundle["reviews"]["review_denoise_004"])
        review["review_id"] = "review_denoise_005_early"
        review["annotation_id"] = target["annotation_id"]
        review["pool_item_id"] = target["pool_item_id"]
        review["reviewed_at"] = "2026-08-24T08:48:00+08:00"
        review["provenance"]["created_at"] = "2026-08-24T08:48:00+08:00"
        kwargs = self._review_plan_kwargs()
        kwargs.update(
            {
                "annotations": {target["annotation_id"]: target},
                "reviews": {review["review_id"]: review},
                "tasks": {task_id: self.bundle["annotation_tasks"][task_id]},
                "task_mappings": {
                    task_id: self.bundle["annotation_task_mappings"][task_id]
                },
                "second_annotations": seconds,
            }
        )
        with self.assertRaisesRegex(ValueError, "时间早于 annotation workflow"):
            build_review_plan_payload(**kwargs)

    def _review_plan_kwargs(self) -> dict:
        payloads = self.bundle["payloads"]
        return {
            "annotations": self.bundle["annotations"],
            "reviews": self.bundle["reviews"],
            "tasks": self.bundle["annotation_tasks"],
            "task_mappings": self.bundle["annotation_task_mappings"],
            "split_sets": self.bundle["split_sets"],
            "protocol": self.protocol,
            "protocol_reference": {
                "artifact_id": self.protocol["artifact_id"],
                "sha256": sha256_file(PROTOCOL),
            },
            "annotation_reference": self.bundle["registry"][
                payloads["annotation_results"]["artifact_id"]
            ],
            "second_annotation_reference": {
                "artifact_id": "w6_second_annotations_v1",
                "sha256": "1" * 64,
            },
            "review_reference": self.bundle["registry"][
                payloads["annotation_reviews"]["artifact_id"]
            ],
            "second_annotations": {},
            "is_fixture": True,
            "created_at": "2026-08-24T14:25:00+08:00",
            "git_revision": BASE_REVISION,
        }

    def _second_payload(self, primary: dict, *, relevance_label: int) -> dict:
        payloads = self.bundle["payloads"]
        primary_ref = self.bundle["registry"][
            payloads["annotation_results"]["artifact_id"]
        ]
        protocol_ref = {
            "artifact_id": self.protocol["artifact_id"],
            "sha256": sha256_file(PROTOCOL),
        }
        payload = build_empty_second_annotation_payload(
            primary_annotation_reference=primary_ref,
            protocol_reference=protocol_ref,
            is_fixture=True,
            created_at="2026-08-24T08:48:31+08:00",
            git_revision=BASE_REVISION,
        )
        payload["annotations"] = [
            {
                "second_annotation_id": "second_annotation_denoise_005",
                "annotation_task_id": primary["annotation_task_id"],
                "annotation_round": "independent_second",
                "topic_id": primary["topic_id"],
                "pool_item_id": primary["pool_item_id"],
                "record_id": primary["record_id"],
                "relevance_label": relevance_label,
                "confidence": "medium",
                "evidence_sources": [
                    {
                        "source_type": "title_abstract",
                        "source_reference": f"record:{primary['record_id']}",
                        "checked_at": "2026-08-24T08:48:15+08:00",
                    }
                ],
                "justification_summary": "Independent fixture judgement from the same blind task.",
                "uncertainty": "",
                "annotation_provenance": {
                    "actor_type": "human",
                    "actor_id": "fixture_independent_second",
                    "model_or_tool": None,
                    "prompt_or_protocol_version": "w6_annotation_fixture_v1",
                    "created_at": "2026-08-24T08:48:30+08:00",
                    "evidence_lookup_performed": False,
                },
            }
        ]
        return payload


class W6BenchmarkPackageTests(unittest.TestCase):
    def test_standalone_cli_exposes_fixture_build_only(self) -> None:
        destinations = {action.dest for action in build_benchmark_cli_parser()._actions}
        self.assertNotIn("status", destinations)

    def test_committed_bootstrap_fixture_package_validates(self) -> None:
        result = validate_w6_benchmark_package(COMMITTED_BENCHMARK_FIXTURE)
        self.assertEqual(result["package"]["status"], "bootstrap_fixture")
        self.assertTrue(result["package"]["is_fixture"])

    def _build(self, root: Path) -> Path:
        return build_w6_benchmark_package(
            artifact_paths=artifact_paths_from_bootstrap_bundle(BOOTSTRAP),
            annotation_protocol_path=PROTOCOL,
            output_dir=root / "benchmark",
            status="bootstrap_fixture",
            created_at="2026-08-24T14:25:00+08:00",
            git_revision=BASE_REVISION,
            git_worktree_clean=True,
        )

    def test_fixture_driven_builder_and_validator_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_w6_benchmark_package(self._build(Path(temp_dir)))
        self.assertEqual(result["package"]["status"], "bootstrap_fixture")
        self.assertTrue(result["package"]["is_fixture"])
        self.assertEqual(
            result["benchmark"]["benchmark_version"],
            "w6_query_relevance_v0.2-alpha.bootstrap-fixture",
        )
        self.assertEqual(result["review_plan"]["status"], "in_review")

    def test_package_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = self._build(Path(temp_dir))
            package = load_json_object(package_path)
            topics_path = (
                package_path.parent / package["artifacts"]["topic_set"]["path"]
            )
            topics_path.write_text(
                topics_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "hash drift"):
                validate_w6_benchmark_package(package_path)

    def test_self_consistent_late_protocol_rehash_fails_chronology(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = self._build(Path(temp_dir))
            package = load_json_object(package_path)
            root = package_path.parent
            protocol_path = root / package["artifacts"]["annotation_protocol"]["path"]
            protocol = load_json_object(protocol_path)
            protocol["frozen_at"] = "2026-08-24T08:46:00+08:00"
            protocol["provenance"]["created_at"] = "2026-08-24T08:46:00+08:00"
            self._write_json(protocol_path, protocol)
            protocol_sha = sha256_file(protocol_path)

            second_path = (
                root / package["artifacts"]["second_annotation_results"]["path"]
            )
            second = load_json_object(second_path)
            second["annotation_protocol"]["sha256"] = protocol_sha
            self._write_json(second_path, second)
            second_sha = sha256_file(second_path)

            plan_path = root / package["artifacts"]["review_plan"]["path"]
            plan = load_json_object(plan_path)
            plan["protocol"]["sha256"] = protocol_sha
            plan["second_annotations"]["sha256"] = second_sha
            self._write_json(plan_path, plan)

            for name in (
                "annotation_protocol",
                "second_annotation_results",
                "review_plan",
            ):
                artifact_path = root / package["artifacts"][name]["path"]
                package["artifacts"][name]["sha256"] = sha256_file(artifact_path)
            package["package_identity"] = compute_package_identity(package)
            self._write_json(package_path, package)
            with self.assertRaisesRegex(
                ValueError, "晚于 annotation_started_at|晚于 primary annotation"
            ):
                validate_w6_benchmark_package(package_path)

    def test_approved_self_promotion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = self._build(Path(temp_dir))
            package = load_json_object(package_path)
            package["status"] = "approved"
            package["package_identity"] = compute_package_identity(package)
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不得自报 approved"):
                validate_w6_benchmark_package(package_path)

    def test_self_consistent_fixture_to_real_rehash_needs_external_trust_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = self._build(Path(temp_dir))
            package = load_json_object(package_path)
            artifact_files = {
                name: package_path.parent / entry["path"]
                for name, entry in package["artifacts"].items()
            }
            for name, path in artifact_files.items():
                payload = load_json_object(path)
                payload["is_fixture"] = False
                if name == "benchmark_manifest":
                    payload["status"] = "sealed_candidate"
                self._write_json(path, payload)

            for _ in range(20):
                hashes = {
                    load_json_object(path)["artifact_id"]: sha256_file(path)
                    for path in artifact_files.values()
                }
                changed = False
                for name, path in artifact_files.items():
                    payload = load_json_object(path)
                    self._rewrite_identity_refs(payload, hashes)
                    if name == "candidate_pool":
                        payload["pool_identity"] = compute_pool_identity(payload)
                    elif name == "split_manifest":
                        payload["split_identity"] = compute_split_identity(payload)
                    elif name == "benchmark_manifest":
                        payload["benchmark_identity"] = compute_benchmark_identity(
                            payload
                        )
                    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
                    if rendered != path.read_text(encoding="utf-8"):
                        path.write_text(rendered, encoding="utf-8")
                        changed = True
                if not changed:
                    break
            else:
                self.fail("self-consistent fixture rehash did not converge")

            package = load_json_object(package_path)
            package["is_fixture"] = False
            package["status"] = "sealed_candidate"
            for name, path in artifact_files.items():
                package["artifacts"][name]["sha256"] = sha256_file(path)
            package["package_identity"] = compute_package_identity(package)
            self._write_json(package_path, package)
            with self.assertRaisesRegex(ValueError, "外部 trusted input registry"):
                validate_w6_benchmark_package(package_path)

    def test_proposed_gate_rejects_incomplete_dev_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_w6_benchmark_package(self._build(Path(temp_dir)))
        with self.assertRaisesRegex(ValueError, "完整覆盖 Dev"):
            validate_benchmark_status_gate(
                "proposed", graph=result["graph"], review_plan=result["review_plan"]
            )

    def test_sealed_candidate_gate_rejects_incomplete_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_w6_benchmark_package(self._build(Path(temp_dir)))
        graph = copy.deepcopy(result["graph"])
        annotated_pool_ids = {
            annotation["pool_item_id"] for annotation in graph["annotations"].values()
        }
        graph["pool_members"] = {
            item_id: member
            for item_id, member in graph["pool_members"].items()
            if item_id in annotated_pool_ids
        }
        plan = copy.deepcopy(result["review_plan"])
        plan["coverage"]["missing_second_annotation_task_ids"] = []
        plan["coverage"]["missing_conflict_adjudication_annotation_ids"] = []
        with self.assertRaisesRegex(ValueError, "incomplete mandatory review"):
            validate_benchmark_status_gate(
                "sealed_candidate", graph=graph, review_plan=plan
            )

    def test_benchmark_output_overlap_equal_child_ancestor_and_resolved_fails(
        self,
    ) -> None:
        input_root = BOOTSTRAP.parent
        cases = {
            "equal": input_root,
            "child": input_root / "generated",
            "ancestor": input_root.parent,
            "resolved": input_root / "nested" / "..",
        }
        inputs = artifact_paths_from_bootstrap_bundle(BOOTSTRAP)
        for label, output in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError, "frozen input tree"
            ):
                build_w6_benchmark_package(
                    artifact_paths=inputs,
                    annotation_protocol_path=PROTOCOL,
                    output_dir=output,
                    status="bootstrap_fixture",
                    created_at="2026-08-24T14:51:20+08:00",
                    git_revision=BASE_REVISION,
                    git_worktree_clean=True,
                )

    def test_benchmark_output_symlink_overlap_fails_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            alias = Path(temp_dir) / "input_alias"
            try:
                os.symlink(BOOTSTRAP.parent, alias, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "frozen input tree"):
                build_w6_benchmark_package(
                    artifact_paths=artifact_paths_from_bootstrap_bundle(BOOTSTRAP),
                    annotation_protocol_path=PROTOCOL,
                    output_dir=alias / "generated",
                    status="bootstrap_fixture",
                    created_at="2026-08-24T14:51:20+08:00",
                    git_revision=BASE_REVISION,
                    git_worktree_clean=True,
                )

    @staticmethod
    def _rewrite_identity_refs(value: object, hashes: dict[str, str]) -> None:
        if isinstance(value, dict):
            if (
                set(value) == {"artifact_id", "sha256"}
                and value.get("artifact_id") in hashes
            ):
                value["sha256"] = hashes[value["artifact_id"]]
            for child in value.values():
                W6BenchmarkPackageTests._rewrite_identity_refs(child, hashes)
        elif isinstance(value, list):
            for child in value:
                W6BenchmarkPackageTests._rewrite_identity_refs(child, hashes)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
