"""Offline RCP-v0.3 regressions; all model/human outcomes are plumbing fixtures."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.pilot_reference_curation import _require_clean_formal_worktree

from src.pilot_context import (
    build_matched_context,
    validate_formal_reference_pair_method_roster,
    validate_matched_context,
)
from src.pilot_reference_curation import (
    AI_TASK_FORBIDDEN_KEYS,
    BM25_METHOD_ID,
    FINAL_REFERENCE_IDENTITY_PREFIX,
    HUMAN_SUBMISSION_IDENTITY_PREFIX,
    REFERENCE_METHOD_ID,
    build_ai_task_package,
    build_evidence_span,
    build_fake_model_judgement_response,
    build_invalid_after_repair_envelope,
    build_judgement_aggregation,
    build_model_judgement_batch,
    build_model_roster,
    build_reference_execution_manifest,
    build_response_envelopes_from_import_records,
    build_safe_zero_audit_outcome,
    build_safe_zero_audit_plan,
    build_valid_response_envelope,
    export_ai_task_package,
    load_reference_curation_inputs,
    minimum_safe_zero_audit_size,
    validate_ai_task_package,
    validate_judgement_aggregation,
    validate_model_judgement_batch,
    validate_model_judgement_response,
    validate_model_roster,
    validate_reference_execution_manifest,
    validate_reference_preparation_package,
    validate_safe_zero_audit_outcome,
    validate_safe_zero_audit_plan,
    _artifact_id,
    _identity_without,
)
from src.pilot_reference_review import (
    build_anonymized_h2_evidence_packet,
    build_blank_cutoff_response,
    build_cutoff_task_package,
    build_final_human_labels,
    build_human_task_package,
    compute_h2_triggers,
    compute_r3_triggers,
    derive_h1_candidate_ids,
    export_human_task_package,
    import_cutoff_submission,
    import_human_submission,
    validate_cutoff_submission,
    validate_human_submission,
)
from src.pilot_reference_selection import (
    build_bm25_selection_after_reference,
    build_cutoff_decision_from_submissions,
    build_final_reference,
    build_rcp_quality_report,
    build_reference_selection_artifact,
    build_reference_selection_freeze_reference,
    validate_final_reference,
    validate_cutoff_decision,
    validate_reference_selection_freeze_reference,
)
from src.pilot_selection import payload_sha256, validate_selection_artifact
from src.w6_contracts import canonical_json_sha256, deterministic_identity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RCP_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.3_reference_curation_v1.json"
)
PREPARATION_PACKAGE = (
    PROJECT_ROOT
    / "data"
    / "research"
    / "pilot"
    / "v0.3"
    / "reference-curation-preparation-v1"
)
CREATED_AT = "2026-08-31T22:50:00+08:00"
COMPLETED_AT = "2026-08-31T23:00:00+08:00"
GIT_REVISION = "1" * 40


def _all_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).casefold())
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


class RCPFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load_reference_curation_inputs(
            RCP_CONFIG, project_root=PROJECT_ROOT
        )
        roles = ["core", "core", "core", "sentinel", "sentinel"]
        cls.entries = []
        for index, role in enumerate(roles, start=1):
            execution_config = {
                "temperature": 0,
                "response_format": "json",
                "fixture_only": True,
            }
            cls.entries.append(
                {
                    "roster_entry_id": f"fixture_{role}_{index}",
                    "role": role,
                    "provider": f"fixture_provider_{index}",
                    "model_family": f"fixture_family_{index}",
                    "independence_group": f"fixture_group_{index}",
                    "requested_model_id": f"fixture_model_{index}_v1",
                    "requested_model_id_type": "exact_version",
                    "provider_reported_model_id": f"fixture_model_{index}_v1",
                    "resolved_model_id": f"fixture_model_{index}_v1",
                    "resolved_identity_confirmed": True,
                    "snapshot_version": "fixture-v1",
                    "snapshot_guarantee": "immutable",
                    "execution_config": execution_config,
                    "execution_config_sha256": canonical_json_sha256(execution_config),
                    "status": "frozen",
                }
            )
        cls.roster = build_model_roster(
            inputs=cls.inputs,
            entries=cls.entries,
            frozen_at=CREATED_AT,
            git_revision=GIT_REVISION,
            created_by="fixture_test",
            run_scope="plumbing_only",
            is_fixture=True,
        )
        cls.bundles_by_topic = {}
        cls.aggregations = {}
        all_bundles = []
        for topic_id in sorted(cls.inputs.pilot_inputs.u80_by_topic):
            u80_order = list(cls.inputs.pilot_inputs.u80_by_topic[topic_id])
            index_by_canonical = {
                candidate_id: index for index, candidate_id in enumerate(u80_order)
            }
            topic_bundles = []
            for panel_index, entry in enumerate(cls.entries):
                task_package, mapping = build_ai_task_package(
                    inputs=cls.inputs,
                    roster=cls.roster,
                    roster_entry_id=entry["roster_entry_id"],
                    topic_id=topic_id,
                    created_at=CREATED_AT,
                    git_revision=GIT_REVISION,
                    allow_fixture=True,
                )
                canonical_by_opaque = {
                    row["candidate_id"]: row["canonical_entity_id"]
                    for row in mapping["candidate_map"]
                }
                envelopes = []
                for task in task_package["tasks"]:
                    canonical_id = canonical_by_opaque[
                        task["candidate"]["candidate_id"]
                    ]
                    index = index_by_canonical[canonical_id]
                    if index < 30:
                        scenario = "safe_zero"
                    elif index == 30:
                        scenario = "sentinel_challenge"
                    elif index == 31:
                        scenario = "abstain"
                    elif index == 32:
                        scenario = "boundary_conflict"
                    else:
                        scenario = "label_two"
                    if index == 33 and panel_index == 0:
                        envelopes.append(
                            build_invalid_after_repair_envelope(
                                task,
                                raw_response_sha256="a" * 64,
                                repaired_response_sha256="b" * 64,
                                external_retention_reference=(
                                    "external-content-sha256:" + "a" * 64
                                ),
                                validation_errors=["fixture invalid evidence span"],
                            )
                        )
                        continue
                    response = build_fake_model_judgement_response(
                        task,
                        scenario=scenario,
                        role=entry["role"],
                        panel_index=panel_index,
                    )
                    response_hash = payload_sha256(response)
                    envelopes.append(
                        build_valid_response_envelope(
                            response,
                            raw_response_sha256=response_hash,
                            external_retention_reference=(
                                "external-content-sha256:" + response_hash
                            ),
                        )
                    )
                batch = build_model_judgement_batch(
                    inputs=cls.inputs,
                    roster=cls.roster,
                    task_package=task_package,
                    mapping=mapping,
                    envelopes=envelopes,
                    started_at=CREATED_AT,
                    completed_at=COMPLETED_AT,
                    git_revision=GIT_REVISION,
                    allow_fixture=True,
                )
                topic_bundles.append(
                    {
                        "batch": batch,
                        "task_package": task_package,
                        "mapping": mapping,
                    }
                )
            cls.bundles_by_topic[topic_id] = topic_bundles
            all_bundles.extend(topic_bundles)
            cls.aggregations[topic_id] = build_judgement_aggregation(
                inputs=cls.inputs,
                roster=cls.roster,
                run_bundles=topic_bundles,
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                allow_fixture=True,
            )
        cls.all_bundles = all_bundles
        cls.execution_manifest = build_reference_execution_manifest(
            inputs=cls.inputs,
            roster=cls.roster,
            run_bundles=all_bundles,
            frozen_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
            allow_fixture=True,
        )

    @staticmethod
    def _human_response(package, mapping, reviewer_id, label_for_canonical):
        canonical_by_opaque = {
            row["candidate_id"]: row["canonical_entity_id"]
            for row in mapping["candidate_map"]
        }
        judgements = []
        for task in package["tasks"]:
            opaque_id = task["candidate"]["candidate_id"]
            canonical_id = canonical_by_opaque[opaque_id]
            relevance = label_for_canonical(canonical_id)
            boundary = {
                dimension: "match"
                for dimension in (
                    "scientific_object",
                    "data_modality",
                    "target_task",
                    "method_role",
                )
            }
            sufficiency = "sufficient"
            spans = [
                build_evidence_span(
                    task,
                    field="title",
                    start_char=0,
                    end_char=min(16, len(task["candidate"]["title"])),
                )
            ]
            if relevance == 0:
                boundary["scientific_object"] = "mismatch"
            elif relevance == "defer":
                boundary["data_modality"] = "unclear"
                sufficiency = "insufficient"
                spans = []
            judgements.append(
                {
                    "candidate_id": opaque_id,
                    "relevance": relevance,
                    "boundary": boundary,
                    "evidence_sufficiency": sufficiency,
                    "evidence_spans": spans,
                    "short_reason": "Deterministic plumbing-only human fixture.",
                }
            )
        return {
            "schema_version": "1.0",
            "artifact_type": "srtp_rcp_human_review_response",
            "protocol_id": "srtp_reference_curation_v0.3",
            "task_package_artifact_id": package["artifact_id"],
            "task_package_identity": package["package_identity"],
            "reviewer_slot": package["reviewer_slot"],
            "stage": package["stage"],
            "status": "completed",
            "reviewer_id": reviewer_id,
            "judgements": judgements,
            "timing": {
                "started_at": CREATED_AT,
                "completed_at": COMPLETED_AT,
                "elapsed_minutes": 10,
            },
            "external_lookup": False,
            "independent_submission_acknowledged": True,
            "submitted_at": COMPLETED_AT,
        }

    @classmethod
    def human_chain(cls, topic_id):
        aggregation = cls.aggregations[topic_id]
        audit_plan = build_safe_zero_audit_plan(
            aggregation,
            inputs=cls.inputs,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        required = derive_h1_candidate_ids(aggregation, audit_plan)
        u80 = list(cls.inputs.pilot_inputs.u80_by_topic[topic_id])
        special = u80[30:33]
        packages = {}
        maps = {}
        h1 = {}
        for reviewer in ("r1", "r2"):
            package, mapping = build_human_task_package(
                inputs=cls.inputs,
                aggregation=aggregation,
                reviewer_slot=reviewer,
                stage="h1",
                candidate_ids=required,
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
            packages[(reviewer, "h1")] = package
            maps[(reviewer, "h1")] = mapping
            if reviewer == "r1":
                labels = {special[0]: 2, special[1]: "defer", special[2]: 0}
            else:
                labels = {special[0]: 1, special[1]: 1, special[2]: 2}
            safe_set = set(audit_plan["safe_zero_canonical_entity_ids"])
            response = cls._human_response(
                package,
                mapping,
                f"fixture_{reviewer}",
                lambda candidate_id, labels=labels: labels.get(
                    candidate_id, 0 if candidate_id in safe_set else 2
                ),
            )
            h1[reviewer] = import_human_submission(
                response,
                task_package=package,
                mapping=mapping,
                imported_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
        triggers = compute_h2_triggers(aggregation, h1["r1"], h1["r2"])
        h2_packet = build_anonymized_h2_evidence_packet(
            aggregation,
            r1_h1=h1["r1"],
            r2_h1=h1["r2"],
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        h2 = {}
        for reviewer in ("r1", "r2"):
            package, mapping = build_human_task_package(
                inputs=cls.inputs,
                aggregation=aggregation,
                reviewer_slot=reviewer,
                stage="h2",
                candidate_ids=list(triggers),
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                h2_evidence_packet=h2_packet,
            )
            packages[(reviewer, "h2")] = package
            maps[(reviewer, "h2")] = mapping
            response = cls._human_response(
                package,
                mapping,
                f"fixture_{reviewer}",
                lambda candidate_id, reviewer=reviewer: (
                    2 if candidate_id != special[0] or reviewer == "r1" else 1
                ),
            )
            h2[reviewer] = import_human_submission(
                response,
                task_package=package,
                mapping=mapping,
                imported_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
        r3_triggers = compute_r3_triggers(
            aggregation,
            h1["r1"],
            h1["r2"],
            r1_h2=h2["r1"],
            r2_h2=h2["r2"],
        )
        r3_package, r3_map = build_human_task_package(
            inputs=cls.inputs,
            aggregation=aggregation,
            reviewer_slot="r3",
            stage="r3_h1",
            candidate_ids=list(r3_triggers),
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        r3_response = cls._human_response(
            r3_package,
            r3_map,
            "fixture_r3",
            lambda _candidate_id: 2,
        )
        r3 = import_human_submission(
            r3_response,
            task_package=r3_package,
            mapping=r3_map,
            imported_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        final_labels = build_final_human_labels(
            aggregation,
            r1_h1=h1["r1"],
            r2_h1=h1["r2"],
            r1_h2=h2["r1"],
            r2_h2=h2["r2"],
            r3=r3,
            required_candidate_ids=required,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        audit_outcome = build_safe_zero_audit_outcome(
            audit_plan,
            inputs=cls.inputs,
            aggregation=aggregation,
            final_human_labels=final_labels,
            completed_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        return {
            "aggregation": aggregation,
            "audit_plan": audit_plan,
            "audit_outcome": audit_outcome,
            "required": required,
            "packages": packages,
            "maps": maps,
            "h1": h1,
            "h2": h2,
            "h2_packet": h2_packet,
            "r3_triggers": r3_triggers,
            "r3_package": r3_package,
            "r3_map": r3_map,
            "r3": r3,
            "final_labels": final_labels,
            "special": special,
        }


class RCPPreparationAndRosterTests(RCPFixture):
    def test_committed_preparation_is_hash_bound_and_not_started(self) -> None:
        result = validate_reference_preparation_package(
            PREPARATION_PACKAGE,
            config_path=RCP_CONFIG,
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(result["status"], "prepared_not_started")
        self.assertFalse(result["real_model_judgements_started"])
        legacy = self.inputs.project_root / (
            "data/research/pilot/v0.2/selection-preparation-v1/manifest.json"
        )
        self.assertTrue(legacy.is_file())

    def test_roster_requires_exact_three_core_two_sentinel(self) -> None:
        for mutation in (self.entries[:-1], self.entries + [self.entries[0]]):
            with self.assertRaises(ValueError):
                build_model_roster(
                    inputs=self.inputs,
                    entries=mutation,
                    frozen_at=CREATED_AT,
                    git_revision=GIT_REVISION,
                    created_by="fixture",
                    run_scope="plumbing_only",
                    is_fixture=True,
                )

    def test_same_family_or_unfrozen_model_fails_closed(self) -> None:
        duplicate = copy.deepcopy(self.entries)
        duplicate[1]["model_family"] = duplicate[0]["model_family"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            build_model_roster(
                inputs=self.inputs,
                entries=duplicate,
                frozen_at=CREATED_AT,
                git_revision=GIT_REVISION,
                created_by="fixture",
                run_scope="plumbing_only",
                is_fixture=True,
            )
        unfrozen = copy.deepcopy(self.roster)
        unfrozen["entries"][0]["status"] = "prepared"
        with self.assertRaises(ValueError):
            validate_model_roster(unfrozen, inputs=self.inputs, allow_fixture=True)

    def test_actual_model_identity_duplicate_fails_despite_distinct_declared_family(
        self,
    ) -> None:
        duplicate = copy.deepcopy(self.entries)
        for field in (
            "provider",
            "requested_model_id",
            "provider_reported_model_id",
            "resolved_model_id",
            "snapshot_version",
        ):
            duplicate[1][field] = duplicate[0][field]
        with self.assertRaisesRegex(ValueError, "actual model identity"):
            build_model_roster(
                inputs=self.inputs,
                entries=duplicate,
                frozen_at=CREATED_AT,
                git_revision=GIT_REVISION,
                created_by="fixture",
                run_scope="plumbing_only",
                is_fixture=True,
            )

    def test_formal_cli_requires_clean_worktree(self) -> None:
        with mock.patch(
            "app.pilot_reference_curation.capture_git_state",
            return_value={
                "git_revision": GIT_REVISION,
                "git_worktree_clean": False,
            },
        ):
            with self.assertRaisesRegex(ValueError, "clean Git worktree"):
                _require_clean_formal_worktree()

    def test_model_identity_and_downstream_family_fail_closed(self) -> None:
        alias = copy.deepcopy(self.entries)
        alias[0]["requested_model_id_type"] = "rolling_alias"
        with self.assertRaisesRegex(ValueError, "rolling alias"):
            build_model_roster(
                inputs=self.inputs,
                entries=alias,
                frozen_at=CREATED_AT,
                git_revision=GIT_REVISION,
                created_by="fixture",
                run_scope="plumbing_only",
                is_fixture=True,
            )
        mismatch = copy.deepcopy(self.entries)
        mismatch[0]["provider_reported_model_id"] = "different_exact_model"
        with self.assertRaisesRegex(ValueError, "identity"):
            build_model_roster(
                inputs=self.inputs,
                entries=mismatch,
                frozen_at=CREATED_AT,
                git_revision=GIT_REVISION,
                created_by="fixture",
                run_scope="plumbing_only",
                is_fixture=True,
            )
        overlap = copy.deepcopy(self.roster)
        overlap["downstream_generator_family"] = self.entries[0]["model_family"]
        with self.assertRaisesRegex(ValueError, "downstream"):
            validate_model_roster(overlap, inputs=self.inputs, allow_fixture=True)


class RCPTaskAndJudgementTests(RCPFixture):
    def test_ai_tasks_are_one_candidate_blind_and_run_specific(self) -> None:
        topic = sorted(self.bundles_by_topic)[0]
        left, right = self.bundles_by_topic[topic][:2]
        self.assertEqual(len(left["task_package"]["tasks"]), 80)
        self.assertFalse(_all_keys(left["task_package"]) & AI_TASK_FORBIDDEN_KEYS)
        self.assertEqual(
            set(left["task_package"]["tasks"][0]["candidate"]),
            {"candidate_id", "title", "abstract"},
        )
        left_ids = {row["candidate_id"] for row in left["mapping"]["candidate_map"]}
        right_ids = {row["candidate_id"] for row in right["mapping"]["candidate_map"]}
        self.assertFalse(left_ids & right_ids)

    def test_task_snapshot_or_mapping_tamper_is_rejected(self) -> None:
        topic = sorted(self.bundles_by_topic)[0]
        bundle = self.bundles_by_topic[topic][0]
        tampered = copy.deepcopy(bundle["task_package"])
        tampered["tasks"][0]["candidate"]["abstract"] += " tampered"
        with self.assertRaisesRegex(ValueError, "reconstruction"):
            validate_ai_task_package(
                tampered,
                mapping=bundle["mapping"],
                roster=self.roster,
                inputs=self.inputs,
                allow_fixture=True,
            )

    def test_judgement_rejects_external_lookup_invalid_label_and_span(self) -> None:
        topic = sorted(self.bundles_by_topic)[0]
        task = self.bundles_by_topic[topic][0]["task_package"]["tasks"][0]
        valid = build_fake_model_judgement_response(
            task, scenario="label_two", role="core"
        )
        for mutate in ("external", "label", "boundary", "span"):
            bad = copy.deepcopy(valid)
            if mutate == "external":
                bad["external_lookup"] = True
            elif mutate == "label":
                bad["judgement"]["relevance"] = 3
            elif mutate == "boundary":
                bad["judgement"]["boundary"]["method_role"] = "maybe"
            else:
                bad["judgement"]["evidence_spans"][0]["text"] += "x"
            with self.assertRaises(ValueError):
                validate_model_judgement_response(bad, task=task)

    def test_batch_requires_exact_eighty_and_rejects_tamper(self) -> None:
        topic = sorted(self.bundles_by_topic)[0]
        bundle = self.bundles_by_topic[topic][0]
        with self.assertRaisesRegex(ValueError, "80"):
            build_model_judgement_batch(
                inputs=self.inputs,
                roster=self.roster,
                task_package=bundle["task_package"],
                mapping=bundle["mapping"],
                envelopes=bundle["batch"]["outcomes"][:-1],
                started_at=CREATED_AT,
                completed_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                allow_fixture=True,
            )
        duplicate = copy.deepcopy(bundle["batch"]["outcomes"])
        duplicate[-1] = copy.deepcopy(duplicate[0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_model_judgement_batch(
                inputs=self.inputs,
                roster=self.roster,
                task_package=bundle["task_package"],
                mapping=bundle["mapping"],
                envelopes=duplicate,
                started_at=CREATED_AT,
                completed_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                allow_fixture=True,
            )
        overfull = copy.deepcopy(bundle["batch"]["outcomes"])
        overfull.append(copy.deepcopy(overfull[0]))
        with self.assertRaisesRegex(ValueError, "80"):
            build_model_judgement_batch(
                inputs=self.inputs,
                roster=self.roster,
                task_package=bundle["task_package"],
                mapping=bundle["mapping"],
                envelopes=overfull,
                started_at=CREATED_AT,
                completed_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                allow_fixture=True,
            )
        tampered = copy.deepcopy(bundle["batch"])
        tampered["outcomes"][0]["raw_response_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "reconstruction"):
            validate_model_judgement_batch(
                tampered,
                inputs=self.inputs,
                roster=self.roster,
                task_package=bundle["task_package"],
                mapping=bundle["mapping"],
                allow_fixture=True,
            )

    def test_external_import_records_build_strict_envelopes(self) -> None:
        topic = sorted(self.bundles_by_topic)[0]
        bundle = self.bundles_by_topic[topic][0]
        records = []
        for envelope in bundle["batch"]["outcomes"]:
            if envelope["status"] == "valid":
                records.append(
                    {
                        "status": "valid",
                        "response": envelope["response"],
                        "raw_response_sha256": envelope["raw_response_sha256"],
                        "external_retention_reference": envelope[
                            "external_retention_reference"
                        ],
                        "schema_repair_attempted": envelope["repair_provenance"][
                            "attempted"
                        ],
                    }
                )
            else:
                records.append(
                    {
                        "status": "invalid_after_schema_repair",
                        "candidate_id": envelope["candidate_id"],
                        "raw_response_sha256": envelope["raw_response_sha256"],
                        "repaired_response_sha256": envelope[
                            "repaired_response_sha256"
                        ],
                        "external_retention_reference": envelope[
                            "external_retention_reference"
                        ],
                        "validation_errors": envelope["validation_errors"],
                    }
                )
        reconstructed = build_response_envelopes_from_import_records(
            records,
            task_package=bundle["task_package"],
        )
        self.assertEqual(reconstructed, bundle["batch"]["outcomes"])

    def test_external_task_export_does_not_modify_repository(self) -> None:
        topic = sorted(self.bundles_by_topic)[0]
        bundle = self.bundles_by_topic[topic][0]
        before = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = export_ai_task_package(
                package=bundle["task_package"],
                mapping=bundle["mapping"],
                roster=self.roster,
                inputs=self.inputs,
                model_output_dir=root / "model",
                coordinator_map_output=root / "coordinator" / "map.json",
                allow_fixture=True,
            )
            self.assertTrue(Path(result["task_package"]).is_file())
            self.assertNotIn(
                "canonical_entity_id",
                json.dumps(
                    json.loads(Path(result["task_package"]).read_text(encoding="utf-8"))
                ),
            )
            with self.assertRaisesRegex(ValueError, "隔离目录"):
                export_ai_task_package(
                    package=bundle["task_package"],
                    mapping=bundle["mapping"],
                    roster=self.roster,
                    inputs=self.inputs,
                    model_output_dir=root / "shared_model_bundle",
                    coordinator_map_output=root / "shared_model_bundle" / "map.json",
                    allow_fixture=True,
                )
        after = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(before, after)


class RCPAggregationAndAuditTests(RCPFixture):
    def test_strict_safe_zero_and_sentinel_challenge_semantics(self) -> None:
        topic = sorted(self.aggregations)[0]
        aggregation = self.aggregations[topic]
        self.assertEqual(aggregation["safe_zero_count"], 30)
        u80 = list(self.inputs.pilot_inputs.u80_by_topic[topic])
        rows = {
            row["canonical_entity_id"]: row for row in aggregation["judgement_matrix"]
        }
        self.assertTrue(rows[u80[0]]["safe_zero"])
        self.assertFalse(rows[u80[30]]["safe_zero"])
        self.assertIn("sentinel_challenge", rows[u80[30]]["routing_reasons"])
        self.assertEqual(rows[u80[30]]["n_core_label_ge_1"], 0)
        self.assertTrue(rows[u80[31]]["human_route"])
        self.assertIn("abstain", rows[u80[31]]["routing_reasons"])
        self.assertIn(
            "invalid_schema_after_one_repair", rows[u80[33]]["routing_reasons"]
        )

    def test_aggregation_is_input_order_invariant_and_tamper_rejected(self) -> None:
        topic = sorted(self.aggregations)[0]
        reverse = build_judgement_aggregation(
            inputs=self.inputs,
            roster=self.roster,
            run_bundles=list(reversed(self.bundles_by_topic[topic])),
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
            allow_fixture=True,
        )
        self.assertEqual(reverse, self.aggregations[topic])
        tampered = copy.deepcopy(reverse)
        tampered["judgement_matrix"][0]["safe_zero"] = False
        with self.assertRaisesRegex(ValueError, "reconstruction"):
            validate_judgement_aggregation(
                tampered,
                inputs=self.inputs,
                roster=self.roster,
                run_bundles=self.bundles_by_topic[topic],
                allow_fixture=True,
            )

    def test_execution_manifest_binds_exact_ten_batches(self) -> None:
        result = validate_reference_execution_manifest(
            self.execution_manifest,
            inputs=self.inputs,
            roster=self.roster,
            run_bundles=self.all_bundles,
            allow_fixture=True,
        )
        self.assertEqual(result["batch_count"], 10)
        with self.assertRaisesRegex(ValueError, "10"):
            build_reference_execution_manifest(
                inputs=self.inputs,
                roster=self.roster,
                run_bundles=self.all_bundles[:-1],
                frozen_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                allow_fixture=True,
            )

    def test_safe_zero_audit_formula_determinism_and_escalation(self) -> None:
        self.assertEqual(minimum_safe_zero_audit_size(0)["sample_size"], 0)
        stats = minimum_safe_zero_audit_size(30)
        self.assertLessEqual(stats["miss_probability"], 0.05)
        if stats["sample_size"]:
            previous = stats["sample_size"] - 1
            previous_probability = __import__("math").comb(27, previous) / __import__(
                "math"
            ).comb(30, previous)
            self.assertGreater(previous_probability, 0.05)
        topic = sorted(self.aggregations)[0]
        left = build_safe_zero_audit_plan(
            self.aggregations[topic],
            inputs=self.inputs,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        right = build_safe_zero_audit_plan(
            self.aggregations[topic],
            inputs=self.inputs,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        self.assertEqual(left, right)
        validate_safe_zero_audit_plan(
            left,
            aggregation=self.aggregations[topic],
            inputs=self.inputs,
        )
        aggregation = self.aggregations[topic]
        required = derive_h1_candidate_ids(aggregation, left)
        discrepancy_id = left["audit_sample_canonical_entity_ids"][0]
        safe_ids = set(left["safe_zero_canonical_entity_ids"])
        submissions = {}
        for reviewer in ("r1", "r2"):
            package, mapping = build_human_task_package(
                inputs=self.inputs,
                aggregation=aggregation,
                reviewer_slot=reviewer,
                stage="h1",
                candidate_ids=required,
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
            response = self._human_response(
                package,
                mapping,
                f"fixture_audit_{reviewer}",
                lambda candidate_id: (
                    1
                    if candidate_id == discrepancy_id
                    else (0 if candidate_id in safe_ids else 2)
                ),
            )
            submissions[reviewer] = import_human_submission(
                response,
                task_package=package,
                mapping=mapping,
                imported_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
        human_labels = build_final_human_labels(
            aggregation,
            r1_h1=submissions["r1"],
            r2_h1=submissions["r2"],
            required_candidate_ids=required,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        outcome = build_safe_zero_audit_outcome(
            left,
            inputs=self.inputs,
            aggregation=aggregation,
            final_human_labels=human_labels,
            completed_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        self.assertTrue(outcome["escalation_required"])
        self.assertEqual(outcome["confirmed_discrepancy_ids"], [discrepancy_id])
        validate_safe_zero_audit_outcome(
            outcome,
            audit_plan=left,
            inputs=self.inputs,
            aggregation=aggregation,
            final_human_labels=human_labels,
        )
        self.assertEqual(
            set(outcome["escalated_review_canonical_entity_ids"]),
            set(left["safe_zero_canonical_entity_ids"])
            - set(left["audit_sample_canonical_entity_ids"]),
        )


class RCPHumanAndFinalSelectionTests(RCPFixture):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.topic_id = sorted(cls.aggregations)[0]
        cls.chain = cls.human_chain(cls.topic_id)

    def test_h1_is_blind_h2_anonymized_and_r3_blind_first(self) -> None:
        h1_package = self.chain["packages"][("r1", "h1")]
        forbidden = {
            "model_family",
            "provider",
            "core_labels",
            "sentinel_labels",
            "safe_zero",
            "routing_reasons",
            "bm25_score",
        }
        self.assertFalse(_all_keys(h1_package) & forbidden)
        self.assertTrue(
            all(not task["anonymous_ai_evidence_cards"] for task in h1_package["tasks"])
        )
        packet_keys = _all_keys(self.chain["h2_packet"])
        self.assertFalse(
            packet_keys
            & {"provider", "model_family", "roster_entry_id", "votes", "majority"}
        )
        self.assertTrue(self.chain["r3_triggers"])
        self.assertTrue(
            all(
                not task["anonymous_ai_evidence_cards"]
                for task in self.chain["r3_package"]["tasks"]
            )
        )
        with self.assertRaisesRegex(ValueError, "blind R3 H1"):
            build_human_task_package(
                inputs=self.inputs,
                aggregation=self.chain["aggregation"],
                reviewer_slot="r3",
                stage="r3_h2",
                candidate_ids=list(self.chain["r3_triggers"]),
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                h2_evidence_packet=self.chain["h2_packet"],
            )
        r3_h2_package, _ = build_human_task_package(
            inputs=self.inputs,
            aggregation=self.chain["aggregation"],
            reviewer_slot="r3",
            stage="r3_h2",
            candidate_ids=list(self.chain["r3_triggers"]),
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
            h2_evidence_packet=self.chain["h2_packet"],
            prior_r3_h1_submission=self.chain["r3"],
        )
        self.assertTrue(r3_h2_package["prior_r3_h1_submission"])
        self.assertTrue(
            all(task["anonymous_ai_evidence_cards"] for task in r3_h2_package["tasks"])
        )

    def test_human_export_stays_external_and_private_map_is_separate(self) -> None:
        package = self.chain["packages"][("r1", "h1")]
        mapping = self.chain["maps"][("r1", "h1")]
        before = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = export_human_task_package(
                package=package,
                mapping=mapping,
                inputs=self.inputs,
                aggregation=self.chain["aggregation"],
                candidate_ids=self.chain["required"],
                human_output_dir=root / "reviewer",
                coordinator_map_output=root / "coordinator" / "map.json",
            )
            self.assertTrue(Path(result["response"]).is_file())
            instructions = (
                Path(result["human_output_dir"]) / "HUMAN_REVIEW_INSTRUCTIONS.md"
            )
            self.assertTrue(instructions.is_file())
            visible = json.loads(
                Path(result["task_package"]).read_text(encoding="utf-8")
            )
            self.assertNotIn("canonical_entity_id", json.dumps(visible))
            with self.assertRaisesRegex(ValueError, "隔离目录"):
                export_human_task_package(
                    package=package,
                    mapping=mapping,
                    inputs=self.inputs,
                    aggregation=self.chain["aggregation"],
                    candidate_ids=self.chain["required"],
                    human_output_dir=root / "shared_human_bundle",
                    coordinator_map_output=root / "shared_human_bundle" / "map.json",
                )
        after = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(before, after)

    def test_h1_submission_is_immutable_and_mapping_tamper_fails(self) -> None:
        submission = self.chain["h1"]["r1"]
        package = self.chain["packages"][("r1", "h1")]
        mapping = self.chain["maps"][("r1", "h1")]
        validate_human_submission(submission, task_package=package, mapping=mapping)
        tampered = copy.deepcopy(submission)
        old_relevance = tampered["canonical_records"][0]["relevance"]
        tampered["canonical_records"][0]["relevance"] = 1 if old_relevance != 1 else 2
        identity = _identity_without(
            tampered,
            prefix=HUMAN_SUBMISSION_IDENTITY_PREFIX,
            omitted={"artifact_id", "submission_identity"},
        )
        tampered["submission_identity"] = identity
        tampered["artifact_id"] = _artifact_id("srtp_rcp_human_submission", identity)
        with self.assertRaisesRegex(ValueError, "immutable"):
            validate_human_submission(tampered)
        with self.assertRaisesRegex(ValueError, "immutable"):
            build_final_human_labels(
                self.chain["aggregation"],
                r1_h1=tampered,
                r2_h1=self.chain["h1"]["r2"],
                required_candidate_ids=self.chain["required"],
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
        swapped = copy.deepcopy(mapping)
        swapped["candidate_map"][0]["canonical_entity_id"] = swapped["candidate_map"][
            1
        ]["canonical_entity_id"]
        with self.assertRaises(ValueError):
            validate_human_submission(submission, task_package=package, mapping=swapped)

    def test_same_topic_reviewer_ids_must_be_distinct(self) -> None:
        r2_response = copy.deepcopy(self.chain["h1"]["r2"]["raw_response"])
        r2_response["reviewer_id"] = self.chain["h1"]["r1"]["reviewer_id"]
        r2 = import_human_submission(
            r2_response,
            task_package=self.chain["packages"][("r2", "h1")],
            mapping=self.chain["maps"][("r2", "h1")],
            imported_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        with self.assertRaisesRegex(ValueError, "reviewer_id 必须互异"):
            build_final_human_labels(
                self.chain["aggregation"],
                r1_h1=self.chain["h1"]["r1"],
                r2_h1=r2,
                required_candidate_ids=self.chain["required"],
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )

    def test_h2_and_r3_resolve_by_median_without_ai_auto_inclusion(self) -> None:
        labels = {
            row["canonical_entity_id"]: row
            for row in self.chain["final_labels"]["labels"]
        }
        special = self.chain["special"][0]
        self.assertEqual(
            labels[special]["resolution_rule"], "three_numeric_label_median"
        )
        self.assertEqual(labels[special]["final_human_relevance"], 2)

    def _cutoff_inputs(self):
        labels = self.chain["final_labels"]["labels"]
        eligible = [row for row in labels if row["final_human_relevance"] in {1, 2}]
        eligible.sort(
            key=lambda row: (
                -row["final_human_relevance"],
                -row["n_core_label_2"],
                -row["n_core_label_ge_1"],
                row["canonical_entity_id"],
            )
        )

        def key(row: dict[str, object]) -> tuple[object, object, object]:
            return (
                row["final_human_relevance"],
                row["n_core_label_2"],
                row["n_core_label_ge_1"],
            )

        cutoff_key = key(eligible[7])
        tie_group = [
            row["canonical_entity_id"] for row in eligible if key(row) == cutoff_key
        ]
        before = [row for row in eligible if key(row) > cutoff_key]
        slots = 8 - len(before)
        if len(tie_group) <= slots:
            return None, None
        return tie_group, slots

    def _cutoff_submission(self, reviewer, tie_group, slots, choice_ids):
        package, mapping = build_cutoff_task_package(
            inputs=self.inputs,
            aggregation=self.chain["aggregation"],
            reviewer_slot=reviewer,
            tie_group_candidate_ids=tie_group,
            slots_required=slots,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        opaque_by_canonical = {
            row["canonical_entity_id"]: row["candidate_id"]
            for row in mapping["candidate_map"]
        }
        response = build_blank_cutoff_response(package)
        response.update(
            {
                "status": "completed",
                "reviewer_id": f"fixture_cutoff_{reviewer}",
                "short_reason": "Independent plumbing-only cutoff choice.",
                "timing": {
                    "started_at": CREATED_AT,
                    "completed_at": COMPLETED_AT,
                    "elapsed_minutes": 10,
                },
                "independent_submission_acknowledged": True,
                "submitted_at": COMPLETED_AT,
            }
        )
        if reviewer in {"r1", "r2"}:
            response["selected_candidate_ids"] = [
                opaque_by_canonical[candidate_id] for candidate_id in choice_ids
            ]
        else:
            response["priority_groups"] = [
                [opaque_by_canonical[candidate_id]] for candidate_id in choice_ids
            ]
        submission = import_cutoff_submission(
            response,
            task_package=package,
            mapping=mapping,
            imported_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        return package, mapping, submission

    def _cutoff_decision(self):
        tie_group, slots = self._cutoff_inputs()
        if tie_group is None:
            return None
        choices = tie_group[:slots]
        _, _, r1 = self._cutoff_submission("r1", tie_group, slots, choices)
        _, _, r2 = self._cutoff_submission("r2", tie_group, slots, choices)
        return build_cutoff_decision_from_submissions(
            r1_submission=r1,
            r2_submission=r2,
            r3_submission=None,
            tie_break_seed="srtp-rcp-v0.3-cutoff-tie-v1",
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )

    def test_cutoff_tasks_are_blind_and_decision_binds_submissions(self) -> None:
        tie_group, slots = self._cutoff_inputs()
        self.assertIsNotNone(tie_group)
        r1_package, r1_map, r1 = self._cutoff_submission(
            "r1", tie_group, slots, tie_group[:slots]
        )
        r2_package, r2_map, r2 = self._cutoff_submission(
            "r2", tie_group, slots, tie_group[:slots]
        )
        self.assertFalse(
            _all_keys(r1_package)
            & {
                "canonical_entity_id",
                "model_family",
                "core_labels",
                "bm25_score",
                "rank",
            }
        )
        self.assertEqual(
            set(r1_package["candidates"][0]),
            {"candidate_id", "title", "abstract"},
        )
        validate_cutoff_submission(r1, task_package=r1_package, mapping=r1_map)
        duplicate_reviewer_response = copy.deepcopy(r2["raw_response"])
        duplicate_reviewer_response["reviewer_id"] = r1["reviewer_id"]
        duplicate_reviewer_r2 = import_cutoff_submission(
            duplicate_reviewer_response,
            task_package=r2_package,
            mapping=r2_map,
            imported_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        with self.assertRaisesRegex(ValueError, "reviewer_id 必须互异"):
            build_cutoff_decision_from_submissions(
                r1_submission=r1,
                r2_submission=duplicate_reviewer_r2,
                r3_submission=None,
                tie_break_seed="srtp-rcp-v0.3-cutoff-tie-v1",
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
        decision = build_cutoff_decision_from_submissions(
            r1_submission=r1,
            r2_submission=r2,
            r3_submission=None,
            tie_break_seed="srtp-rcp-v0.3-cutoff-tie-v1",
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        validate_cutoff_decision(decision)
        self.assertEqual(len(decision["blind_submission_refs"]), 2)

    def test_cutoff_requires_r3_when_r1_r2_intersection_is_short(self) -> None:
        tie_group, slots = self._cutoff_inputs()
        _, _, r1 = self._cutoff_submission("r1", tie_group, slots, tie_group[:slots])
        _, _, r2 = self._cutoff_submission("r2", tie_group, slots, tie_group[-slots:])
        with self.assertRaisesRegex(ValueError, "R3"):
            build_cutoff_decision_from_submissions(
                r1_submission=r1,
                r2_submission=r2,
                r3_submission=None,
                tie_break_seed="srtp-rcp-v0.3-cutoff-tie-v1",
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
        _, _, r3 = self._cutoff_submission("r3", tie_group, slots, tie_group)
        decision = build_cutoff_decision_from_submissions(
            r1_submission=r1,
            r2_submission=r2,
            r3_submission=r3,
            tie_break_seed="srtp-rcp-v0.3-cutoff-tie-v1",
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        self.assertEqual(len(decision["selected_from_tie"]), slots)

    def test_fixture_final_reference_generic_selection_and_context(self) -> None:
        cutoff = self._cutoff_decision()
        final = build_final_reference(
            inputs=self.inputs,
            roster=self.roster,
            execution_manifest=self.execution_manifest,
            aggregation=self.chain["aggregation"],
            audit_plan=self.chain["audit_plan"],
            audit_outcome=self.chain["audit_outcome"],
            final_human_labels=self.chain["final_labels"],
            cutoff_decision=cutoff,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
            run_bundles=self.all_bundles,
            allow_fixture=True,
        )
        validated_final = validate_final_reference(
            final,
            inputs=self.inputs,
            aggregation=self.chain["aggregation"],
            audit_plan=self.chain["audit_plan"],
            audit_outcome=self.chain["audit_outcome"],
            final_human_labels=self.chain["final_labels"],
            cutoff_decision=cutoff,
        )
        self.assertEqual(len(validated_final["selected_canonical_entity_ids"]), 8)
        self.assertTrue(final["all_top8_human_reviewed"])
        self.assertGreaterEqual(len(final["frontier_8_9_10"]), 1)
        self.assertEqual(
            final["one_swap_sensitivity_status"],
            "deferred_not_primary_rcp_v0.3",
        )
        self.assertEqual(final["one_swap_sensitivity_sets"], [])
        tampered = copy.deepcopy(final)
        tampered["selected_canonical_entity_ids"][:2] = reversed(
            tampered["selected_canonical_entity_ids"][:2]
        )
        body = copy.deepcopy(tampered)
        body.pop("artifact_id")
        body.pop("final_reference_identity")
        tampered_identity = deterministic_identity(
            FINAL_REFERENCE_IDENTITY_PREFIX, body
        )
        tampered["final_reference_identity"] = tampered_identity
        tampered["artifact_id"] = _artifact_id(
            "srtp_rcp_final_reference", tampered_identity
        )
        with self.assertRaisesRegex(ValueError, "protocol reconstruction"):
            validate_final_reference(
                tampered,
                inputs=self.inputs,
                aggregation=self.chain["aggregation"],
                audit_plan=self.chain["audit_plan"],
                audit_outcome=self.chain["audit_outcome"],
                final_human_labels=self.chain["final_labels"],
                cutoff_decision=cutoff,
            )
        selection = build_reference_selection_artifact(
            inputs=self.inputs,
            final_reference=final,
            aggregation=self.chain["aggregation"],
            audit_plan=self.chain["audit_plan"],
            audit_outcome=self.chain["audit_outcome"],
            final_human_labels=self.chain["final_labels"],
            cutoff_decision=cutoff,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        validated_selection = validate_selection_artifact(
            selection, inputs=self.inputs.pilot_inputs
        )
        self.assertEqual(validated_selection["method_id"], REFERENCE_METHOD_ID)
        self.assertTrue(validated_selection["is_fixture"])
        context = build_matched_context(
            inputs=self.inputs.pilot_inputs,
            selection=selection,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        validate_matched_context(
            context,
            selection=selection,
            inputs=self.inputs.pilot_inputs,
        )
        rendered = context["exact_rendered_context"].casefold()
        for forbidden_method_metadata in (
            REFERENCE_METHOD_ID,
            BM25_METHOD_ID,
            "roster_entry_id",
            "core_labels",
            "sentinel_labels",
            "safe_zero",
            "selection_score",
        ):
            self.assertNotIn(forbidden_method_metadata.casefold(), rendered)

    def test_finalizer_fails_with_less_than_eight_eligible(self) -> None:
        safe_ids = set(self.chain["audit_plan"]["safe_zero_canonical_entity_ids"])
        eligible_ids = set(
            [
                candidate_id
                for candidate_id in self.chain["required"]
                if candidate_id not in safe_ids
            ][:7]
        )
        submissions = {}
        for reviewer in ("r1", "r2"):
            package = self.chain["packages"][(reviewer, "h1")]
            mapping = self.chain["maps"][(reviewer, "h1")]
            response = self._human_response(
                package,
                mapping,
                f"fixture_{reviewer}_seven_eligible",
                lambda candidate_id: 1 if candidate_id in eligible_ids else 0,
            )
            submissions[reviewer] = import_human_submission(
                response,
                task_package=package,
                mapping=mapping,
                imported_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )
        labels = build_final_human_labels(
            self.chain["aggregation"],
            r1_h1=submissions["r1"],
            r2_h1=submissions["r2"],
            required_candidate_ids=self.chain["required"],
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        audit_outcome = build_safe_zero_audit_outcome(
            self.chain["audit_plan"],
            inputs=self.inputs,
            aggregation=self.chain["aggregation"],
            final_human_labels=labels,
            completed_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        with self.assertRaisesRegex(ValueError, "insufficient_eligible"):
            build_final_reference(
                inputs=self.inputs,
                roster=self.roster,
                execution_manifest=self.execution_manifest,
                aggregation=self.chain["aggregation"],
                audit_plan=self.chain["audit_plan"],
                audit_outcome=audit_outcome,
                final_human_labels=labels,
                cutoff_decision=None,
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
                allow_fixture=True,
            )

    def test_reference_freeze_attack_and_formal_fixture_boundary(self) -> None:
        cutoff = self._cutoff_decision()
        final = build_final_reference(
            inputs=self.inputs,
            roster=self.roster,
            execution_manifest=self.execution_manifest,
            aggregation=self.chain["aggregation"],
            audit_plan=self.chain["audit_plan"],
            audit_outcome=self.chain["audit_outcome"],
            final_human_labels=self.chain["final_labels"],
            cutoff_decision=cutoff,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
            allow_fixture=True,
        )
        selection = build_reference_selection_artifact(
            inputs=self.inputs,
            final_reference=final,
            aggregation=self.chain["aggregation"],
            audit_plan=self.chain["audit_plan"],
            audit_outcome=self.chain["audit_outcome"],
            final_human_labels=self.chain["final_labels"],
            cutoff_decision=cutoff,
            created_at=COMPLETED_AT,
            git_revision=GIT_REVISION,
        )
        freeze = build_reference_selection_freeze_reference(selection)
        validate_reference_selection_freeze_reference(
            freeze,
            selection,
            inputs=self.inputs.pilot_inputs,
            require_formal=False,
        )
        tampered = copy.deepcopy(selection)
        tampered["purpose"] = "changed"
        with self.assertRaisesRegex(ValueError, "hash binding"):
            validate_reference_selection_freeze_reference(
                freeze,
                tampered,
                inputs=self.inputs.pilot_inputs,
                require_formal=False,
            )
        with self.assertRaisesRegex(ValueError, "non-fixture"):
            build_bm25_selection_after_reference(
                self.inputs,
                topic_id=self.topic_id,
                reference_selection_freeze=selection,
                created_at=COMPLETED_AT,
                git_revision=GIT_REVISION,
            )

    def test_formal_pair_roster_comes_from_config_and_quality_is_stability_only(
        self,
    ) -> None:
        policy = self.inputs.config["comparison_policy"]
        validate_formal_reference_pair_method_roster(
            BM25_METHOD_ID,
            REFERENCE_METHOD_ID,
            comparison_policy=policy,
            left_is_fixture=False,
            right_is_fixture=False,
        )
        with self.assertRaises(ValueError):
            validate_formal_reference_pair_method_roster(
                BM25_METHOD_ID,
                "pilot_dual_curator_v1",
                comparison_policy=policy,
                left_is_fixture=False,
                right_is_fixture=False,
            )
        report = build_rcp_quality_report(
            aggregation=self.chain["aggregation"],
            human_submissions=[
                self.chain["h1"]["r1"],
                self.chain["h1"]["r2"],
                self.chain["h2"]["r1"],
                self.chain["h2"]["r2"],
                self.chain["r3"],
            ],
            audit_outcome=self.chain["audit_outcome"],
            cutoff_decision=self._cutoff_decision(),
        )
        self.assertTrue(report["artifact_id"].startswith("srtp_rcp_quality_"))
        self.assertIsNotNone(report["human_layer"]["h1_to_h2_change_rate"])
        self.assertIsNotNone(report["human_layer"]["final_cutoff_disagreement"])
        self.assertEqual(
            report["interpretation"],
            "stability_and_workflow_metrics_not_astronomy_correctness",
        )


if __name__ == "__main__":
    unittest.main()
