"""Offline tests for the SRTP Pilot v0.2 real-data foundation."""

from __future__ import annotations

import copy
import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pilot_real_data_foundation import (
    SELECTION_VIEW_FILENAME,
    U80_FILENAME,
    assemble_pilot_payloads,
    build_openalex_w6_bridge,
    build_pilot_package,
    build_query_registry,
    build_topic_adapter,
    compute_pilot_config_identity,
    load_and_validate_pilot_inputs,
    sample_query_balanced_u80,
    _validate_config_shape,
)
from src.w6_contracts import (
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_real_data_foundation_v1.json"
)
CREATED_AT = "2026-08-30T18:19:26+08:00"
GIT_REVISION = "a8d9b1f95001e74e1e96328db401dd55fc7df5e6"
TOPIC_IDS = (
    "w6_topic_21cm_foreground_removal",
    "w6_topic_spectral_anomaly_detection",
)


def _all_keys(value):
    keys = set()
    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


class PilotRealDataFixture(unittest.TestCase):
    _cache = None

    @classmethod
    def setUpClass(cls) -> None:
        if PilotRealDataFixture._cache is None:
            inputs = load_and_validate_pilot_inputs(
                CONFIG_PATH, project_root=PROJECT_ROOT
            )
            payloads, manifest = assemble_pilot_payloads(
                inputs,
                created_at=CREATED_AT,
                git_revision=GIT_REVISION,
                git_worktree_clean=True,
            )
            PilotRealDataFixture._cache = (inputs, payloads, manifest)
        cls.inputs, cls.payloads, cls.manifest = PilotRealDataFixture._cache
        cls.registry = cls.payloads["query_registry.json"]
        cls.retrieval_payload = cls.payloads["retrieval_provenance.json"]
        cls.source_payload = cls.payloads["source_records.json"]
        cls.selection_view = cls.payloads[SELECTION_VIEW_FILENAME]
        cls.u80 = cls.payloads[U80_FILENAME]


class PilotConfigAndQueryIdentityTests(PilotRealDataFixture):
    def test_config_is_hash_bound_and_dev_only(self) -> None:
        self.assertEqual(
            self.inputs.config["config_identity"],
            compute_pilot_config_identity(self.inputs.config),
        )
        self.assertEqual(tuple(self.inputs.config["topic_ids"]), TOPIC_IDS)
        self.assertTrue(set(TOPIC_IDS) <= self.inputs.split["dev"])
        self.assertFalse(set(TOPIC_IDS) & self.inputs.split["hidden"])

    def test_all_twelve_real_aq_runs_are_preserved(self) -> None:
        configured = {
            row["source_query_run_id"] for row in self.inputs.config["query_roster"]
        }
        adapted = {
            run["retrieval_run_id"] for run in self.retrieval_payload["runs"]
        }
        self.assertEqual(len(configured), 12)
        self.assertEqual(adapted, configured)
        self.assertEqual(
            {run["query_variant_id"].rsplit("_", 1)[-1] for run in self.retrieval_payload["runs"]},
            {f"aq{index:02d}" for index in range(1, 7)},
        )
        self.assertTrue(
            all("_qv" not in run["query_variant_id"] for run in self.retrieval_payload["runs"])
        )

    def test_exact_text_lineage_only_links_aq01_aq02(self) -> None:
        for topic_id in TOPIC_IDS:
            rows = [row for row in self.registry["queries"] if row["topic_id"] == topic_id]
            linked = [
                row for row in rows if row["historical_topic_query_lineage"] is not None
            ]
            unlinked = [
                row for row in rows if row["historical_topic_query_lineage"] is None
            ]
            self.assertEqual(
                {row["acquisition_query_id"].rsplit("_", 1)[-1] for row in linked},
                {"aq01", "aq02"},
            )
            self.assertEqual(
                {row["acquisition_query_id"].rsplit("_", 1)[-1] for row in unlinked},
                {"aq03", "aq04", "aq05", "aq06"},
            )
            for row in linked:
                self.assertEqual(
                    row["exact_query_text"],
                    row["historical_topic_query_lineage"]["historical_query_text"],
                )

    def test_registry_binds_query_run_config_and_source_package(self) -> None:
        for query in self.registry["queries"]:
            self.assertEqual(
                query["acquisition_config_reference"]["config_identity"],
                self.inputs.acquisition_config["config_identity"],
            )
            self.assertEqual(
                query["source_package_reference"]["acquisition_identity"],
                self.inputs.source_manifest["acquisition_identity"],
            )
            source_run = self.inputs.query_runs_by_id[query["source_query_run_id"]]
            self.assertEqual(query["exact_query_text"], source_run["query_text"])

    def test_hidden_topic_cannot_enter_mutated_config(self) -> None:
        mutated = copy.deepcopy(self.inputs.config)
        mutated["topic_ids"][0] = next(iter(sorted(self.inputs.split["hidden"])))
        mutated["config_identity"] = compute_pilot_config_identity(mutated)
        with self.assertRaisesRegex(ValueError, "两个指定 Dev Topics"):
            _validate_config_shape(mutated)


class PilotBridgeAndMetadataTests(PilotRealDataFixture):
    def test_bridge_passes_existing_w6_contracts(self) -> None:
        topics = validate_topic_set(self.payloads["topic_adapter.json"])
        retrieval = validate_retrieval_provenance(
            self.retrieval_payload, topics=topics
        )
        records = validate_source_records(
            self.source_payload, topics=topics, retrieval=retrieval
        )
        self.assertEqual(len(retrieval["runs"]), 12)
        self.assertEqual(len(records), 702)
        self.assertEqual(
            {
                hit_id
                for record in records.values()
                for hit_id in record["acquisition_provenance_refs"]
            },
            set(retrieval["hits"]),
        )

    def test_machine_ids_are_legal_and_openalex_identity_is_retained(self) -> None:
        for record in self.source_payload["records"]:
            self.assertRegex(record["record_id"], r"^pilot_openalex_w[1-9][0-9]*$")
            self.assertRegex(record["openalex_id"], r"^W[1-9][0-9]*$")
            self.assertEqual(
                record["record_provenance"]["source_record_id"],
                record["openalex_id"],
            )

    def test_metadata_is_not_fabricated_or_enriched(self) -> None:
        report = self.payloads["eligibility_report.json"]
        self.assertEqual(report["source_record_exclusion_count"], 23)
        self.assertEqual(
            report["source_exclusion_reason_counts"],
            {"missing_authors": 2, "missing_title": 3, "missing_venue": 18},
        )
        self.assertFalse(report["policy"]["enrichment_enabled"])
        for record in self.source_payload["records"]:
            self.assertNotEqual(record["venue"].casefold(), "unknown")
            self.assertTrue(record["authors"])
            if "abstract" in record["metadata_completeness"]["missing_fields"]:
                self.assertIsNone(record["abstract"])
            if "doi" in record["metadata_completeness"]["missing_fields"]:
                self.assertIsNone(record["doi"])

    def test_bridge_is_invariant_to_source_row_order(self) -> None:
        registry = build_query_registry(
            self.inputs, created_at=CREATED_AT, git_revision=GIT_REVISION
        )
        topic_adapter = build_topic_adapter(
            self.inputs,
            query_registry=registry,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        reversed_inputs = dataclasses.replace(
            self.inputs,
            source_hits=list(reversed(self.inputs.source_hits)),
            source_works=list(reversed(self.inputs.source_works)),
        )
        reversed_bridge = build_openalex_w6_bridge(
            reversed_inputs,
            topic_adapter=topic_adapter,
            query_registry=registry,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        normal_bridge = build_openalex_w6_bridge(
            self.inputs,
            topic_adapter=topic_adapter,
            query_registry=registry,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        self.assertEqual(reversed_bridge, normal_bridge)

    def test_source_revision_is_not_current_head_masquerading_as_acquisition(self) -> None:
        revision = self.inputs.config["source_revision_provenance"]
        self.assertFalse(revision["exact_acquisition_execution_revision_captured"])
        self.assertEqual(
            revision["w6_compatibility_git_revision"],
            revision["source_package_parent_commit"],
        )
        self.assertNotEqual(revision["w6_compatibility_git_revision"], GIT_REVISION)
        for run in self.retrieval_payload["runs"]:
            self.assertEqual(run["git_revision"], revision["w6_compatibility_git_revision"])
            self.assertFalse(
                run["frozen_configuration"]["exact_acquisition_execution_revision_captured"]
            )


class PilotCanonicalSelectionAndU80Tests(PilotRealDataFixture):
    def test_real_counts_and_exact_u80(self) -> None:
        counts = self.manifest["counts"]
        self.assertEqual(counts["raw_unique_source_work_count"], 725)
        self.assertEqual(counts["w6_source_record_count"], 702)
        self.assertEqual(counts["precanonical_pool_item_count"], 714)
        self.assertEqual(counts["canonical_entity_count"], 693)
        self.assertEqual(counts["suspected_relationship_count"], 36)
        self.assertEqual(counts["canonical_selection_item_count"], 678)
        self.assertEqual(counts["u80_total_count"], 160)
        per_topic = {row["topic_id"]: row for row in counts["per_topic"]}
        self.assertEqual(
            per_topic[TOPIC_IDS[0]]["eligible_canonical_entity_count"], 322
        )
        self.assertEqual(
            per_topic[TOPIC_IDS[1]]["eligible_canonical_entity_count"], 356
        )
        self.assertEqual(self.u80["topic_counts"], {topic_id: 80 for topic_id in TOPIC_IDS})

    def test_confirmed_aliases_take_one_selection_slot(self) -> None:
        for topic_id in TOPIC_IDS:
            items = [
                item for item in self.selection_view["items"] if item["topic_id"] == topic_id
            ]
            entity_ids = [item["canonical_entity_id"] for item in items]
            self.assertEqual(len(entity_ids), len(set(entity_ids)))
            self.assertTrue(any(len(item["alias_record_ids"]) > 1 for item in items))
            self.assertEqual(
                self.selection_view["topic_counts"][topic_id][
                    "confirmed_alias_record_collapse_count"
                ],
                5,
            )

    def test_suspected_duplicates_remain_explicit_separate_entities(self) -> None:
        relationship_entities = {
            entity_id
            for relationship in self.payloads["canonical_entities.json"][
                "suspected_relationships"
            ]
            for entity_id in relationship["entity_ids"]
        }
        marked = {
            item["canonical_entity_id"]
            for item in self.selection_view["items"]
            if item["suspected_duplicate_status"] != "none"
        }
        self.assertTrue(marked)
        self.assertTrue(marked <= relationship_entities)
        self.assertTrue(
            all(
                len(set(relationship["entity_ids"])) == 2
                for relationship in self.payloads["canonical_entities.json"][
                    "suspected_relationships"
                ]
            )
        )

    def test_preferred_title_and_abstract_gate_is_consistent(self) -> None:
        self.assertTrue(
            all(item["title"].strip() and item["abstract"].strip() for item in self.selection_view["items"])
        )
        self.assertEqual(len(self.selection_view["excluded_entities"]), 26)
        self.assertEqual(
            {
                reason
                for row in self.selection_view["excluded_entities"]
                for reason in row["reason_codes"]
            },
            {"missing_preferred_abstract"},
        )

    def _resample(self, view, registry=None):
        return sample_query_balanced_u80(
            selection_view=view,
            query_registry=registry or self.registry,
            config=self.inputs.config,
            input_references=self.u80["inputs"],
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            git_worktree_clean=True,
        )

    def test_sampling_is_repeatable_and_input_order_invariant(self) -> None:
        first = self._resample(self.selection_view)
        second = self._resample(self.selection_view)
        shuffled_view = copy.deepcopy(self.selection_view)
        shuffled_view["items"].reverse()
        shuffled_registry = copy.deepcopy(self.registry)
        shuffled_registry["queries"].reverse()
        reordered = self._resample(shuffled_view, shuffled_registry)
        self.assertEqual(first, second)
        self.assertEqual(first, reordered)
        self.assertEqual(first["u80_identity"], self.u80["u80_identity"])

    def test_sampling_does_not_read_source_rank_citations_or_labels(self) -> None:
        mutated = copy.deepcopy(self.selection_view)
        for index, item in enumerate(mutated["items"], start=1):
            item["source_rank"] = 100000 - index
            item["cited_by_count"] = index * 1000
            item["relevance_label"] = index % 3
        self.assertEqual(self._resample(mutated), self.u80)
        forbidden = {
            "source_rank",
            "source_score",
            "cited_by_count",
            "relevance_label",
            "bm25_score",
            "synthesis_output",
        }
        self.assertFalse(forbidden & _all_keys(self.selection_view))
        self.assertFalse(forbidden & _all_keys(self.u80))

    def test_six_query_contribution_is_complete(self) -> None:
        for topic in self.u80["topics"]:
            diagnostics = topic["query_contribution_diagnostics"]
            self.assertEqual(len(diagnostics), 6)
            self.assertEqual(
                sum(row["first_selection_contribution_count"] for row in diagnostics),
                80,
            )
            self.assertTrue(all(row["eligible_roster_count"] > 0 for row in diagnostics))
            self.assertEqual(len(topic["ordered_canonical_entity_ids"]), 80)
            self.assertEqual(len(set(topic["ordered_canonical_entity_ids"])), 80)

    def test_insufficient_universe_fails_closed(self) -> None:
        too_small = copy.deepcopy(self.selection_view)
        retained = []
        for topic_id in TOPIC_IDS:
            retained.extend(
                [item for item in too_small["items"] if item["topic_id"] == topic_id][
                    :79
                ]
            )
        too_small["items"] = retained
        with self.assertRaisesRegex(ValueError, "< 80"):
            self._resample(too_small)


class PilotBuildSafetyTests(PilotRealDataFixture):
    def test_frozen_build_rejects_dirty_worktree_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.pilot_real_data_foundation.capture_git_state",
            return_value={"git_revision": GIT_REVISION, "git_worktree_clean": False},
        ):
            output = Path(temp_dir) / "out"
            with self.assertRaisesRegex(ValueError, "clean Git worktree"):
                build_pilot_package(
                    config_path=CONFIG_PATH,
                    output_dir=output,
                    project_root=PROJECT_ROOT,
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
