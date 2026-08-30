"""Offline regressions for Pilot v0.2 selection and matched-context tooling."""

from __future__ import annotations

import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from app.run_pilot_bm25_selection import build_parser as build_bm25_cli_parser
from app.run_pilot_bm25_selection import main as run_bm25_cli
from src.pilot_context import (
    build_matched_context,
    count_context_tokens,
    neutral_order_key,
    truncate_paper_fields,
    validate_matched_context,
    validate_matched_context_pair,
)
from src.pilot_selection import (
    CURATOR_FORBIDDEN_KEYS,
    FIXTURE_METHOD_ID,
    MINIMUM_CURATOR_OVERLAP,
    SELECTION_K,
    assemble_curator_preparation_payloads,
    build_adjudication_task,
    build_blank_adjudication_response,
    build_blank_curator_response,
    build_curator_comparison,
    build_curator_task_and_map,
    build_final_human_selection,
    build_selection_artifact,
    import_adjudication_submission,
    import_curator_submission,
    load_pilot_selection_inputs,
    payload_sha256,
    rank_pilot_bm25_candidates,
    render_curator_task_markdown,
    validate_completed_curator_response,
    validate_curator_comparison,
    validate_curator_preparation_package,
    validate_curator_task,
    validate_selection_artifact,
    write_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_selection_context_v1.json"
)
COMMITTED_CURATOR_PACKAGE = (
    PROJECT_ROOT
    / "data"
    / "research"
    / "pilot"
    / "v0.2"
    / "selection-preparation-v1"
)
TOPIC_ID = "w6_topic_21cm_foreground_removal"
CREATED_AT = "2026-08-30T21:10:54+08:00"
GIT_REVISION = "1" * 40


def _all_keys(value):
    keys = set()
    if isinstance(value, dict):
        keys.update(str(key).casefold() for key in value)
        for child in value.values():
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


class PilotSelectionContextFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load_pilot_selection_inputs(CONFIG_PATH, project_root=PROJECT_ROOT)

    def fixture_selection(
        self,
        *,
        topic_id: str = TOPIC_ID,
        ids: list[str] | None = None,
        strategy: str = "deterministic_first_eight_plumbing_only",
    ):
        selected = ids or list(self.inputs.u80_by_topic[topic_id][:SELECTION_K])
        return build_selection_artifact(
            inputs=self.inputs,
            topic_id=topic_id,
            selection_method={
                "method_id": FIXTURE_METHOD_ID,
                "family": "testing_only",
                "config_identity": "fixture",
            },
            selected_canonical_entity_ids=selected,
            method_specific_provenance={"fixture_strategy": strategy},
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
            purpose="plumbing_only",
        )

    def fixture_task(self, slot: str):
        return build_curator_task_and_map(
            self.inputs,
            topic_id=TOPIC_ID,
            curator_slot=slot,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
        )

    @staticmethod
    def completed_response(task, selected_candidate_ids, curator_id):
        form = build_blank_curator_response(task)
        form.update(
            {
                "status": "completed",
                "curator_id": curator_id,
                "selected_candidates": [
                    {
                        "candidate_id": candidate_id,
                        "selection_reason": "Mock reason for plumbing-only regression.",
                    }
                    for candidate_id in selected_candidate_ids
                ],
                "timing": {
                    "started_at": "",
                    "completed_at": "",
                    "elapsed_minutes": 30.0,
                },
                "external_lookup": False,
                "independent_submission_acknowledged": True,
                "submitted_at": "2026-08-30T22:00:00+08:00",
                "notes": "fixture only",
            }
        )
        return form


class PilotConfigAndBM25Tests(PilotSelectionContextFixture):
    def test_real_inputs_are_hash_bound_to_two_complete_u80_topics(self) -> None:
        self.assertEqual(set(self.inputs.u80_by_topic), set(self.inputs.config["topics"][index]["topic_id"] for index in range(2)))
        self.assertTrue(all(len(ids) == 80 for ids in self.inputs.u80_by_topic.values()))
        self.assertEqual(self.inputs.config["selection_policy"]["k_per_topic"], 8)
        self.assertEqual(
            self.inputs.config["bm25"]["formal_execution_policy"],
            "after_dual_curator_final_selection_freeze",
        )

    def test_bm25_is_deterministic_top_eight_with_canonical_tie_break(self) -> None:
        candidates = {
            f"entity_{index:02d}": {
                "title": "Identical spectral anomaly title",
                "abstract": "Identical unsupervised discovery abstract",
            }
            for index in range(12)
        }
        forward = rank_pilot_bm25_candidates(
            research_question="spectral anomaly discovery",
            candidates=candidates,
        )
        reverse = rank_pilot_bm25_candidates(
            research_question="spectral anomaly discovery",
            candidates=dict(reversed(list(candidates.items()))),
        )
        self.assertEqual(forward, reverse)
        self.assertEqual(len(forward), SELECTION_K)
        self.assertEqual(
            [row["canonical_entity_id"] for row in forward],
            sorted(candidates)[:SELECTION_K],
        )
        self.assertEqual([row["rank"] for row in forward], list(range(1, 9)))

    def test_formal_bm25_cli_requires_human_selection_attestation(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_bm25_cli_parser().parse_args(
                ["--topic-id", TOPIC_ID, "--output", "unused.json"]
            )
        fixture = self.fixture_selection()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture_selection.json"
            output = Path(temp_dir) / "bm25.json"
            write_json(path, fixture)
            with contextlib.redirect_stderr(io.StringIO()):
                result = run_bm25_cli(
                    [
                        "--topic-id",
                        TOPIC_ID,
                        "--human-selection-attestation",
                        str(path),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())


class GenericSelectionContractTests(PilotSelectionContextFixture):
    def test_fixture_selection_validates_with_u80_question_and_k_binding(self) -> None:
        selection = self.fixture_selection()
        validated = validate_selection_artifact(selection, inputs=self.inputs)
        self.assertEqual(validated["topic_id"], TOPIC_ID)
        self.assertEqual(validated["k"], 8)
        self.assertTrue(validated["is_fixture"])
        self.assertEqual(validated["purpose"], "plumbing_only")

    def test_duplicate_unknown_k_and_wrong_u80_fail_closed(self) -> None:
        base = self.fixture_selection()
        duplicate = copy.deepcopy(base)
        duplicate["selected_canonical_entity_ids"][1] = duplicate[
            "selected_canonical_entity_ids"
        ][0]
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_selection_artifact(duplicate, inputs=self.inputs)

        unknown = copy.deepcopy(base)
        unknown["selected_canonical_entity_ids"][-1] = "not_in_u80"
        with self.assertRaisesRegex(ValueError, "U80 外"):
            validate_selection_artifact(unknown, inputs=self.inputs)

        wrong_k = copy.deepcopy(base)
        wrong_k["k"] = 7
        with self.assertRaisesRegex(ValueError, "精确为 8"):
            validate_selection_artifact(wrong_k, inputs=self.inputs)

        wrong_u80 = copy.deepcopy(base)
        wrong_u80["u80"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "U80 identity/hash"):
            validate_selection_artifact(wrong_u80, inputs=self.inputs)

    def test_fixture_method_cannot_masquerade_as_real_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "is_fixture=true"):
            build_selection_artifact(
                inputs=self.inputs,
                topic_id=TOPIC_ID,
                selection_method={
                    "method_id": FIXTURE_METHOD_ID,
                    "family": "testing_only",
                    "config_identity": "fixture",
                },
                selected_canonical_entity_ids=list(
                    self.inputs.u80_by_topic[TOPIC_ID][:8]
                ),
                method_specific_provenance={"fixture_strategy": "mock"},
                created_at=CREATED_AT,
                git_revision=GIT_REVISION,
                is_fixture=False,
                purpose="formal",
            )


class BlindHumanWorkflowTests(PilotSelectionContextFixture):
    def test_task_contains_only_allowed_candidate_fields_and_no_hidden_ids(self) -> None:
        task, mapping = self.fixture_task("curator_a")
        validate_curator_task(task, mapping=mapping, inputs=self.inputs)
        self.assertEqual(len(task["candidates"]), 80)
        self.assertEqual(
            set(task["candidates"][0]), {"candidate_id", "title", "abstract"}
        )
        self.assertFalse(
            CURATOR_FORBIDDEN_KEYS & _all_keys({"candidates": task["candidates"]})
        )
        rendered = json.dumps(task, ensure_ascii=False)
        markdown = render_curator_task_markdown(task)
        for row in mapping["candidate_map"]:
            self.assertNotIn(row["canonical_entity_id"], rendered)
            self.assertNotIn(row["canonical_entity_id"], markdown)
        self.assertFalse(task["blindness"]["bm25_output_generated"])
        self.assertFalse(task["blindness"]["other_curator_submission_visible"])
        self.assertTrue(task["blindness"]["authors_hidden"])
        self.assertTrue(task["blindness"]["venue_hidden"])

    def test_hidden_candidate_field_tamper_is_rejected(self) -> None:
        task, mapping = self.fixture_task("curator_a")
        task["candidates"][0]["bm25_score"] = 1.0
        with self.assertRaisesRegex(ValueError, "暴露字段"):
            validate_curator_task(task, mapping=mapping, inputs=self.inputs)

        task, mapping = self.fixture_task("curator_a")
        task["bm25_top8"] = ["must_not_be_visible"]
        with self.assertRaisesRegex(ValueError, "字段漂移"):
            validate_curator_task(task, mapping=mapping, inputs=self.inputs)

    def test_completed_response_requires_eight_unique_in_scope_items_and_provenance(self) -> None:
        task, mapping = self.fixture_task("curator_a")
        selected = [row["candidate_id"] for row in task["candidates"][:8]]
        form = self.completed_response(task, selected, "fixture_curator_a")
        validated = validate_completed_curator_response(
            form, task=task, mapping=mapping
        )
        self.assertEqual(len(validated["canonical_entity_ids"]), 8)

        duplicate = copy.deepcopy(form)
        duplicate["selected_candidates"][1]["candidate_id"] = duplicate[
            "selected_candidates"
        ][0]["candidate_id"]
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_completed_curator_response(
                duplicate, task=task, mapping=mapping
            )

        external = copy.deepcopy(form)
        external["external_lookup"] = True
        with self.assertRaisesRegex(ValueError, "必须是 False"):
            validate_completed_curator_response(
                external, task=task, mapping=mapping
            )

        no_ack = copy.deepcopy(form)
        no_ack["independent_submission_acknowledged"] = False
        with self.assertRaisesRegex(ValueError, "必须是 True"):
            validate_completed_curator_response(no_ack, task=task, mapping=mapping)

    def _submissions(self, indices_a, indices_b):
        task_a, map_a = self.fixture_task("curator_a")
        task_b, map_b = self.fixture_task("curator_b")
        candidate_ids = [row["candidate_id"] for row in task_a["candidates"]]
        response_a = self.completed_response(
            task_a,
            [candidate_ids[index] for index in indices_a],
            "fixture_curator_a",
        )
        response_b = self.completed_response(
            task_b,
            [candidate_ids[index] for index in indices_b],
            "fixture_curator_b",
        )
        submission_a = import_curator_submission(
            response_a,
            task=task_a,
            mapping=map_a,
            imported_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        submission_b = import_curator_submission(
            response_b,
            task=task_b,
            mapping=map_b,
            imported_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        return submission_a, submission_b, map_a

    def test_overlap_adjudication_and_fixture_final_selection_pipeline(self) -> None:
        submission_a, submission_b, mapping = self._submissions(
            range(0, 8), range(4, 12)
        )
        comparison = build_curator_comparison(
            submission_a,
            submission_b,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        self.assertEqual(comparison["overlap_count"], MINIMUM_CURATOR_OVERLAP)
        self.assertEqual(comparison["status"], "ready_for_adjudication")
        self.assertEqual(comparison["jaccard"], 4 / 12)
        self.assertEqual(len(comparison["symmetric_difference_canonical_entity_ids"]), 8)
        tampered_comparison = copy.deepcopy(comparison)
        tampered_comparison["intersection_canonical_entity_ids"].pop()
        with self.assertRaisesRegex(ValueError, "set reconstruction"):
            validate_curator_comparison(
                tampered_comparison, inputs=self.inputs
            )

        task = build_adjudication_task(
            comparison,
            mapping=mapping,
            inputs=self.inputs,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        self.assertEqual(task["candidate_scope"], "symmetric_difference_only")
        self.assertEqual(task["required_additional_count"], 4)
        self.assertNotIn("curator_slot", _all_keys(task["candidates"]))
        form = build_blank_adjudication_response(task)
        form.update(
            {
                "status": "completed",
                "adjudicator_id": "fixture_adjudicator",
                "selected_candidates": [
                    {
                        "candidate_id": row["candidate_id"],
                        "selection_reason": "Mock adjudication reason.",
                    }
                    for row in task["candidates"][:4]
                ],
                "timing": {
                    "started_at": "",
                    "completed_at": "",
                    "elapsed_minutes": 20.0,
                },
                "external_lookup": False,
                "submitted_at": "2026-08-30T22:30:00+08:00",
                "notes": "fixture only",
            }
        )
        adjudication = import_adjudication_submission(
            form,
            task=task,
            mapping=mapping,
            imported_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        final = build_final_human_selection(
            comparison,
            inputs=self.inputs,
            comparison_sha256=payload_sha256(comparison),
            adjudication=adjudication,
            adjudication_sha256=payload_sha256(adjudication),
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        validated = validate_selection_artifact(final, inputs=self.inputs)
        self.assertEqual(validated["method_id"], FIXTURE_METHOD_ID)
        self.assertTrue(validated["is_fixture"])
        self.assertEqual(validated["k"], 8)

    def test_overlap_below_four_fails_closed_without_topic_replacement(self) -> None:
        submission_a, submission_b, mapping = self._submissions(
            range(0, 8), range(6, 14)
        )
        comparison = build_curator_comparison(
            submission_a,
            submission_b,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        self.assertEqual(comparison["overlap_count"], 2)
        self.assertEqual(comparison["status"], "curation_stability_failure")
        self.assertEqual(
            comparison["failure_action"], "fail_closed_do_not_auto_replace_topic"
        )
        with self.assertRaisesRegex(ValueError, "fail closed"):
            build_adjudication_task(
                comparison,
                mapping=mapping,
                inputs=self.inputs,
                created_at=CREATED_AT,
                git_revision=GIT_REVISION,
            )


class MatchedContextTests(PilotSelectionContextFixture):
    def build_context(self, selection):
        return build_matched_context(
            inputs=self.inputs,
            selection=selection,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )

    def test_context_is_deterministic_exact_and_hash_bound(self) -> None:
        selection = self.fixture_selection()
        first = self.build_context(selection)
        second = self.build_context(selection)
        self.assertEqual(first, second)
        self.assertEqual(first["k"], 8)
        self.assertEqual(len(first["paper_snapshots"]), 8)
        self.assertEqual(
            first["rendered_context_sha256"],
            __import__("hashlib").sha256(
                first["exact_rendered_context"].encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            first["actual_total_token_count"],
            count_context_tokens(
                first["exact_rendered_context"], first["context_policy"]
            ),
        )
        validate_matched_context(first, selection=selection, inputs=self.inputs)

    def test_method_metadata_and_input_priority_do_not_change_context(self) -> None:
        ids = list(self.inputs.u80_by_topic[TOPIC_ID][:8])
        first_selection = self.fixture_selection(
            ids=ids, strategy="mock_strategy_alpha"
        )
        second_selection = self.fixture_selection(
            ids=list(reversed(ids)), strategy="mock_strategy_beta"
        )
        first = self.build_context(first_selection)
        second = self.build_context(second_selection)
        self.assertEqual(
            first["ordered_canonical_entity_ids"],
            second["ordered_canonical_entity_ids"],
        )
        self.assertEqual(
            first["exact_rendered_context"], second["exact_rendered_context"]
        )
        self.assertNotEqual(first["selection"]["sha256"], second["selection"]["sha256"])
        expected = sorted(
            ids,
            key=lambda entity_id: (
                neutral_order_key(
                    question_id=first["topic"]["question_id"],
                    canonical_entity_id=entity_id,
                    policy=first["context_policy"],
                ),
                entity_id,
            ),
        )
        self.assertEqual(first["ordered_canonical_entity_ids"], expected)

    def test_tokenizer_and_per_paper_truncation_are_deterministic(self) -> None:
        policy = self.inputs.config["context_policy"]
        title = "short title"
        abstract = " ".join(f"token{index}" for index in range(400))
        first = truncate_paper_fields(title, abstract, policy=policy)
        second = truncate_paper_fields(title, abstract, policy=policy)
        self.assertEqual(first, second)
        self.assertTrue(first["abstract_truncated"])
        self.assertTrue(first["truncated"])
        self.assertEqual(first["token_count"], policy["per_paper_token_cap"])

    def test_context_tamper_and_selection_k_mismatch_fail_closed(self) -> None:
        selection = self.fixture_selection()
        context = self.build_context(selection)
        tampered = copy.deepcopy(context)
        tampered["ordered_canonical_entity_ids"].reverse()
        with self.assertRaisesRegex(ValueError, "reconstruction drift"):
            validate_matched_context(tampered, selection=selection, inputs=self.inputs)

        invalid_selection = copy.deepcopy(selection)
        invalid_selection["selected_canonical_entity_ids"].pop()
        with self.assertRaisesRegex(ValueError, "精确包含 8"):
            self.build_context(invalid_selection)

    def test_pairwise_fairness_allows_natural_token_delta_only(self) -> None:
        ids = list(self.inputs.u80_by_topic[TOPIC_ID])
        left_selection = self.fixture_selection(
            ids=ids[:8], strategy="mock_condition_left"
        )
        right_selection = self.fixture_selection(
            ids=ids[8:16], strategy="mock_condition_right"
        )
        left = self.build_context(left_selection)
        right = self.build_context(right_selection)
        report = validate_matched_context_pair(
            left,
            right,
            left_selection=left_selection,
            right_selection=right_selection,
            inputs=self.inputs,
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["padding_used"])
        self.assertEqual(
            report["actual_token_delta_left_minus_right"],
            left["actual_total_token_count"] - right["actual_total_token_count"],
        )
        self.assertEqual(
            report["context_policy_identity"],
            self.inputs.config["context_policy"]["config_identity"],
        )


class CuratorPackageTests(PilotSelectionContextFixture):
    def test_preparation_payload_has_four_blank_tasks_and_no_selection_result(self) -> None:
        payloads, manifest = assemble_curator_preparation_payloads(
            self.inputs, created_at=CREATED_AT, git_revision=GIT_REVISION
        )
        self.assertEqual(manifest["task_count"], 4)
        self.assertEqual(manifest["human_selection_status"], "not_started")
        self.assertEqual(
            manifest["bm25_execution_status"],
            "deferred_until_dual_curator_final_selection_freeze",
        )
        self.assertIn("CURATOR_INSTRUCTIONS.md", payloads)
        self.assertFalse(
            any("selection.json" in name for name in payloads)
        )
        for name, payload in payloads.items():
            if name.startswith("responses/"):
                self.assertEqual(payload["status"], "blank_template")
                self.assertFalse(payload["independent_submission_acknowledged"])

    def test_reconstructed_temporary_package_validates(self) -> None:
        payloads, manifest = assemble_curator_preparation_payloads(
            self.inputs, created_at=CREATED_AT, git_revision=GIT_REVISION
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            package = Path(temp_dir)
            for relative, payload in payloads.items():
                path = package / relative
                if isinstance(payload, dict):
                    write_json(path, payload)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(payload, encoding="utf-8", newline="\n")
            write_json(package / "manifest.json", manifest)
            validated = validate_curator_preparation_package(
                package, config_path=CONFIG_PATH, project_root=PROJECT_ROOT
            )
            self.assertEqual(validated["package_identity"], manifest["package_identity"])

    def test_committed_curator_preparation_package_validates(self) -> None:
        manifest = validate_curator_preparation_package(
            COMMITTED_CURATOR_PACKAGE,
            config_path=CONFIG_PATH,
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(manifest["status"], "prepared_not_started")
        self.assertEqual(manifest["human_selection_status"], "not_started")
        self.assertEqual(manifest["task_count"], 4)


if __name__ == "__main__":
    unittest.main()
