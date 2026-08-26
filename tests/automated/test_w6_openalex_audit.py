"""Offline and adversarial tests for the W6 post-freeze OpenAlex audit."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.annotation_tasks import sha256_file
from src.openalex_client import convert_openalex_work
from src.w6_openalex_audit import (
    ACQUISITION_IDENTITY_PREFIX,
    PACKAGE_FILES,
    acquire_and_audit,
    build_topic_audit,
    compute_acquisition_run_id,
    compute_query_config_identity,
    compute_query_hit_id,
    compute_query_run_id,
    load_and_validate_query_config,
    refresh_acquisition_audit,
    render_topic_audit_markdown,
    resolve_openalex_api_key,
    validate_acquisition_package,
    validate_query_config,
)
from src.w6_contracts import deterministic_identity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "w6" / "openalex_topic_query_audit_v1.json"
TOPIC_PATH = PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha" / "topics.json"
SPLIT_PATH = PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha" / "split_manifest.json"
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "w6_openalex_audit" / "base_works.json"
COMMITTED_PACKAGE_PATH = (
    PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha" / "openalex-audit-v1"
)
TEST_API_KEY = "offline-test-key-never-persist"


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def repackage_with_fresh_hashes(package: Path) -> None:
    """Rehash every child and the manifest identity after an adversarial mutation."""

    manifest = read_json(package / "manifest.json")
    manifest["files"] = {name: sha256_file(package / name) for name in PACKAGE_FILES}
    manifest["acquisition_identity"] = deterministic_identity(
        ACQUISITION_IDENTITY_PREFIX,
        {
            "config_identity": manifest["config_reference"]["config_identity"],
            "topic_set_sha256": manifest["topic_set_reference"]["sha256"],
            "split_identity": manifest["split_reference"]["split_identity"],
            "file_hashes": manifest["files"],
        },
    )
    write_json(package / "manifest.json", manifest)


def rewrite_package_run_identity(
    package: Path,
    *,
    acquisition_run_id: str,
    config_identity: str | None = None,
) -> None:
    """Synchronize every child identity so tests do not rely on a stale reference."""

    manifest = read_json(package / "manifest.json")
    runs_artifact = read_json(package / "query_runs.json")
    hits = read_jsonl(package / "query_hits.jsonl")
    records = read_jsonl(package / "works.jsonl")
    manifest["acquisition_run_id"] = acquisition_run_id
    runs_artifact["acquisition_run_id"] = acquisition_run_id
    if config_identity is not None:
        runs_artifact["config_identity"] = config_identity
    query_run_ids: dict[tuple[str, str], str] = {}
    for run in runs_artifact["runs"]:
        run["acquisition_run_id"] = acquisition_run_id
        run["query_run_id"] = compute_query_run_id(
            acquisition_run_id=acquisition_run_id,
            topic_id=run["topic_id"],
            query_variant_id=run["query_variant_id"],
        )
        query_run_ids[(run["topic_id"], run["query_variant_id"])] = run[
            "query_run_id"
        ]
    hit_ids_by_record: dict[str, list[str]] = {}
    for hit in hits:
        hit["acquisition_run_id"] = acquisition_run_id
        key = (hit["topic_id"], hit["query_variant_id"])
        hit["query_run_id"] = query_run_ids[key]
        hit["hit_id"] = compute_query_hit_id(
            acquisition_run_id=acquisition_run_id,
            topic_id=hit["topic_id"],
            query_variant_id=hit["query_variant_id"],
            openalex_id=hit["openalex_id"],
        )
        hit_ids_by_record.setdefault(hit["record_id"], []).append(hit["hit_id"])
    for record in records:
        record["acquisition_run_id"] = acquisition_run_id
        record["hit_ids"] = sorted(hit_ids_by_record[record["record_id"]])
    write_json(package / "manifest.json", manifest)
    write_json(package / "query_runs.json", runs_artifact)
    write_jsonl(package / "query_hits.jsonl", hits)
    write_jsonl(package / "works.jsonl", records)


class FrozenQueryFetcher:
    """Deterministic one-page OpenAlex replacement driven by frozen query text."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.base_works = read_json(FIXTURE_PATH)
        self.query_lookup: dict[str, tuple[int, int]] = {}
        for topic_index, topic in enumerate(config["topics"]):
            for query_index, query in enumerate(topic["query_variants"]):
                self.query_lookup[query["query_text"]] = (topic_index, query_index)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        keyword: str,
        max_results: int,
        *,
        from_year: int,
        to_year: int,
        api_key: str,
    ) -> dict[str, Any]:
        topic_index, query_index = self.query_lookup[keyword]
        self.calls.append(
            {
                "keyword": keyword,
                "max_results": max_results,
                "from_year": from_year,
                "to_year": to_year,
                "api_key": api_key,
            }
        )
        topic_common = copy.deepcopy(self.base_works["topic_common"])
        topic_common["id"] = f"https://openalex.org/W{9910000 + topic_index}"
        topic_common["display_name"] += f" {topic_index}"
        query_unique = copy.deepcopy(self.base_works["query_unique"])
        query_unique["id"] = (
            f"https://openalex.org/W{9920000 + topic_index * 10 + query_index}"
        )
        works = [topic_common, query_unique]
        if query_index == 0:
            works.append(copy.deepcopy(self.base_works["shared"]))
        papers = [convert_openalex_work(work, keyword) for work in works]
        return {
            "raw_response": {
                "meta": {"aggregation": "offline_fixture"},
                "page_meta": [
                    {
                        "count": 100 + topic_index * 10 + query_index,
                        "per_page": len(works),
                        "next_cursor": "unused",
                    }
                ],
                "results": works,
            },
            "papers": papers,
            "stats": {
                "requested_max_results": max_results,
                "actual_result_count": len(works),
                "page_count": 1,
                "request_count": 1,
                "retry_count": 0,
                "applied_filters": {"from_year": from_year, "to_year": to_year},
                "elapsed_seconds": 0.125,
                "stopped_reason": "cursor_exhausted",
                "status": "success",
                "duplicate_records_skipped": 0,
                "output_duplicate_id_count": 0,
            },
        }


class W6OpenAlexAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = read_json(CONFIG_PATH)
        self.topic_set = read_json(TOPIC_PATH)
        self.split = read_json(SPLIT_PATH)

    def validate_config(self, config: dict[str, Any]) -> None:
        validate_query_config(
            config,
            topic_set=self.topic_set,
            topic_set_sha256=sha256_file(TOPIC_PATH),
            split=self.split,
            split_sha256=sha256_file(SPLIT_PATH),
        )

    def build_package(self, output: Path) -> tuple[dict[str, Any], FrozenQueryFetcher]:
        fetcher = FrozenQueryFetcher(self.config)
        manifest = acquire_and_audit(
            config_path=CONFIG_PATH,
            topic_set_path=TOPIC_PATH,
            split_path=SPLIT_PATH,
            output_dir=output,
            api_key=TEST_API_KEY,
            authentication_source="process_environment",
            fetcher=fetcher,
            timestamp_fn=lambda: "2026-08-26T08:00:00+00:00",
        )
        return manifest, fetcher

    def assert_repacked_mutation_rejected(
        self,
        mutate: Any,
        message_pattern: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package = Path(temporary_directory) / "package"
            self.build_package(package)
            mutate(package)
            repackage_with_fresh_hashes(package)
            with self.assertRaisesRegex(ValueError, message_pattern):
                validate_acquisition_package(
                    package_dir=package,
                    config_path=CONFIG_PATH,
                    topic_set_path=TOPIC_PATH,
                    split_path=SPLIT_PATH,
                )

    def test_frozen_config_binds_nine_topics_and_fifty_four_queries(self) -> None:
        config, topics, split = load_and_validate_query_config(
            CONFIG_PATH,
            topic_set_path=TOPIC_PATH,
            split_path=SPLIT_PATH,
        )

        self.assertEqual(config["config_identity"], compute_query_config_identity(config))
        self.assertEqual(len(config["topics"]), 9)
        self.assertEqual(sum(len(topic["query_variants"]) for topic in config["topics"]), 54)
        self.assertEqual(config["topic_set_reference"]["sha256"], sha256_file(TOPIC_PATH))
        self.assertEqual(config["split_reference"]["sha256"], sha256_file(SPLIT_PATH))
        self.assertEqual(topics["artifact_id"], "w6_research_topics_v0.2_alpha")
        self.assertEqual(split["reveal_state"], "sealed")

    def test_query_text_or_topic_and_split_hash_drift_is_rejected(self) -> None:
        drifted = copy.deepcopy(self.config)
        drifted["topics"][0]["query_variants"][0]["query_text"] += " changed"
        with self.assertRaisesRegex(ValueError, "identity/hash drift"):
            self.validate_config(drifted)

        rebound = copy.deepcopy(drifted)
        rebound["config_identity"] = compute_query_config_identity(rebound)
        with self.assertRaisesRegex(ValueError, "Topic Set sha256"):
            validate_query_config(
                rebound,
                topic_set=self.topic_set,
                topic_set_sha256="0" * 64,
                split=self.split,
                split_sha256=sha256_file(SPLIT_PATH),
            )
        with self.assertRaisesRegex(ValueError, "split sha256"):
            validate_query_config(
                rebound,
                topic_set=self.topic_set,
                topic_set_sha256=sha256_file(TOPIC_PATH),
                split=self.split,
                split_sha256="0" * 64,
            )

    def test_label_or_adaptive_policy_drift_is_rejected_after_reidentity(self) -> None:
        for key in ("labels_allowed", "adaptive_query_tuning_after_results"):
            with self.subTest(key=key):
                drifted = copy.deepcopy(self.config)
                drifted["acquisition_policy"][key] = True
                drifted["config_identity"] = compute_query_config_identity(drifted)
                with self.assertRaises(ValueError):
                    self.validate_config(drifted)

    def test_missing_facet_duplicate_query_and_preset_amendment_are_rejected(self) -> None:
        mutations = []
        missing_facet = copy.deepcopy(self.config)
        missing_facet["topics"][0]["query_variants"][0]["coverage_facets"] = ["unknown"]
        mutations.append(missing_facet)
        duplicate = copy.deepcopy(self.config)
        duplicate["topics"][0]["query_variants"][1]["query_text"] = duplicate["topics"][0]["query_variants"][0]["query_text"]
        mutations.append(duplicate)
        amendment = copy.deepcopy(self.config)
        amendment["potential_topic_amendments"] = [{"topic_id": "not-allowed-before-audit"}]
        mutations.append(amendment)
        for drifted in mutations:
            drifted["config_identity"] = compute_query_config_identity(drifted)
            with self.assertRaises(ValueError):
                self.validate_config(drifted)

    def test_acquisition_exact_id_dedup_preserves_every_query_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package = Path(temporary_directory) / "package"
            manifest, fetcher = self.build_package(package)
            records = read_jsonl(package / "works.jsonl")
            hits = read_jsonl(package / "query_hits.jsonl")
            audit = read_json(package / "topic_audit.json")

            self.assertEqual(manifest["query_count"], 54)
            self.assertEqual(manifest["unique_work_count"], 64)
            self.assertEqual(manifest["query_hit_count"], 117)
            self.assertEqual(len(fetcher.calls), 54)
            self.assertTrue(all(call["api_key"] == TEST_API_KEY for call in fetcher.calls))
            self.assertTrue(all(call["max_results"] == 80 for call in fetcher.calls))
            self.assertEqual(len({row["openalex_id"] for row in records}), 64)
            same_title = [
                row for row in records
                if row["title"] == "Same title retained under different exact Work IDs"
            ]
            self.assertEqual(len(same_title), 54)
            self.assertEqual(len({row["openalex_id"] for row in same_title}), 54)
            shared = next(row for row in records if row["openalex_id"] == "W9900001")
            self.assertEqual(len(shared["topic_ids"]), 9)
            self.assertEqual(len(shared["hit_ids"]), 9)
            self.assertEqual(audit["topics"][0]["union_work_count"], 8)
            self.assertEqual(
                audit["topics"][0]["multi_query_support_distribution"],
                {"1": 7, "6": 1},
            )
            self.assertEqual(
                sum(row["intersection_count"] > 0 for row in audit["cross_topic_overlap"]),
                36,
            )
            self.assertTrue(all("source_rank" in row for row in hits))
            self.assertTrue(all("query_run_id" in row for row in hits))
            self.assertTrue(all("acquisition_run_id" in row for row in records + hits))
            self.assertEqual(shared["publication_date"], "2022-04-01")
            self.assertEqual(shared["work_type"], "article")
            self.assertEqual(shared["openalex_url"], "https://openalex.org/W9900001")

    def test_api_counts_years_metadata_representatives_and_risks_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package = Path(temporary_directory) / "package"
            self.build_package(package)
            audit = read_json(package / "topic_audit.json")
            first = audit["topics"][0]

            self.assertEqual(first["query_variants"][0]["api_hit_count"], 100)
            self.assertEqual(first["query_variants"][0]["retrieved_work_count"], 3)
            self.assertEqual(first["query_variants"][0]["unique_contribution_count"], 2)
            self.assertEqual(first["query_variants"][0]["unique_contribution_ratio"], 0.666667)
            self.assertEqual(first["publication_year_distribution"], {"2021": 1, "2022": 1, "missing": 6})
            self.assertEqual(
                first["publication_year_summary"],
                {
                    "minimum": 2021,
                    "median": 2021.5,
                    "maximum": 2022,
                    "known_count": 2,
                    "missing_count": 6,
                    "recent_five_year_count": 1,
                    "bins": {
                        "2000-2009": 0,
                        "2010-2014": 0,
                        "2015-2019": 0,
                        "2020-2022": 2,
                        "2023-2026": 0,
                        "missing": 6,
                    },
                },
            )
            self.assertEqual(first["metadata_completeness"]["abstract"]["present_count"], 2)
            self.assertIn("below_target_unique_work_count", first["audit_signals"])
            self.assertIn("abstract_completeness_below_0.5", first["audit_signals"])
            self.assertEqual(first["representative_works"][0]["query_support_count"], 6)
            self.assertEqual(first["potential_topic_amendments"], [])

    def test_secret_and_personal_paths_are_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package = Path(temporary_directory) / "package"
            self.build_package(package)
            rendered = "".join(
                path.read_text(encoding="utf-8")
                for path in package.iterdir()
                if path.is_file()
            )

            self.assertNotIn(TEST_API_KEY, rendered)
            self.assertNotIn(str(PROJECT_ROOT), rendered)
            self.assertNotIn(str(Path.home()), rendered)
            manifest = read_json(package / "manifest.json")
            self.assertEqual(
                manifest["secret_handling"],
                {
                    "api_key_received_from_environment": True,
                    "authentication_source": "process_environment",
                    "api_key_persisted": False,
                    "dotenv_read": False,
                },
            )

    def test_key_resolution_uses_process_then_explicit_windows_scopes(self) -> None:
        registry_calls: list[str] = []

        def reader(scope: str) -> str | None:
            registry_calls.append(scope)
            return "user-key" if scope == "user" else "machine-key"

        self.assertEqual(
            resolve_openalex_api_key(
                getenv=lambda _name, _default: "process-key",
                windows_reader=reader,
            ),
            ("process-key", "process_environment"),
        )
        self.assertEqual(registry_calls, [])
        self.assertEqual(
            resolve_openalex_api_key(
                getenv=lambda _name, _default: "",
                windows_reader=reader,
            ),
            ("user-key", "windows_user_environment"),
        )
        self.assertEqual(registry_calls, ["user"])

    def test_key_resolution_can_fall_back_to_machine_or_unavailable(self) -> None:
        self.assertEqual(
            resolve_openalex_api_key(
                getenv=lambda _name, _default: "",
                windows_reader=lambda scope: "machine-key" if scope == "machine" else None,
            ),
            ("machine-key", "windows_machine_environment"),
        )
        self.assertEqual(
            resolve_openalex_api_key(
                getenv=lambda _name, _default: "",
                windows_reader=lambda _scope: None,
            ),
            ("", "unavailable"),
        )

    def test_missing_key_and_output_overlap_fail_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fetcher = FrozenQueryFetcher(self.config)
            with self.assertRaisesRegex(ValueError, "OPENALEX_API_KEY"):
                acquire_and_audit(
                    config_path=CONFIG_PATH,
                    topic_set_path=TOPIC_PATH,
                    split_path=SPLIT_PATH,
                    output_dir=Path(temporary_directory) / "missing-key",
                    api_key="",
                    fetcher=fetcher,
                )
            self.assertEqual(fetcher.calls, [])
            with self.assertRaisesRegex(ValueError, "重合"):
                acquire_and_audit(
                    config_path=CONFIG_PATH,
                    topic_set_path=TOPIC_PATH,
                    split_path=SPLIT_PATH,
                    output_dir=PROJECT_ROOT,
                    api_key=TEST_API_KEY,
                    fetcher=fetcher,
                )
            self.assertEqual(fetcher.calls, [])

    def test_package_hash_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package = Path(temporary_directory) / "package"
            self.build_package(package)
            with (package / "works.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("{}\n")
            with self.assertRaisesRegex(ValueError, "file hash drift"):
                validate_acquisition_package(
                    package_dir=package,
                    config_path=CONFIG_PATH,
                    topic_set_path=TOPIC_PATH,
                    split_path=SPLIT_PATH,
                )

    def test_derived_audit_refresh_preserves_captured_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package = Path(temporary_directory) / "package"
            before, _ = self.build_package(package)
            source_hashes = {
                name: before["files"][name]
                for name in ("works.jsonl", "query_hits.jsonl", "query_runs.json")
            }

            after = refresh_acquisition_audit(
                package_dir=package,
                config_path=CONFIG_PATH,
                topic_set_path=TOPIC_PATH,
                split_path=SPLIT_PATH,
            )

            self.assertEqual(
                {name: after["files"][name] for name in source_hashes},
                source_hashes,
            )
            self.assertIn("Unique ratio", (package / "topic_audit.md").read_text(encoding="utf-8"))

    def test_same_fixture_produces_same_acquisition_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first, _ = self.build_package(root / "first")
            second, _ = self.build_package(root / "second")

            self.assertEqual(first["acquisition_identity"], second["acquisition_identity"])
            self.assertEqual(first["files"], second["files"])

    def test_committed_openalex_package_has_full_provenance_closure(self) -> None:
        manifest = validate_acquisition_package(
            package_dir=COMMITTED_PACKAGE_PATH,
            config_path=CONFIG_PATH,
            topic_set_path=TOPIC_PATH,
            split_path=SPLIT_PATH,
        )

        self.assertEqual(manifest["query_count"], 54)
        self.assertEqual(manifest["unique_work_count"], 2977)
        self.assertEqual(manifest["query_hit_count"], 4265)

    def test_repacked_absurd_rank_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            hits = read_jsonl(package / "query_hits.jsonl")
            hits[0]["source_rank"] = 9999
            write_jsonl(package / "query_hits.jsonl", hits)

        self.assert_repacked_mutation_rejected(mutate, "source_rank coverage")

    def test_repacked_query_text_drift_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            runs = read_json(package / "query_runs.json")
            runs["runs"][0]["query_text"] += " post-hoc drift"
            write_json(package / "query_runs.json", runs)

        self.assert_repacked_mutation_rejected(mutate, "query_text.*frozen config drift")

    def test_repacked_unknown_topic_hit_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            hits = read_jsonl(package / "query_hits.jsonl")
            records = read_jsonl(package / "works.jsonl")
            hit = hits[1]
            old_hit_id = hit["hit_id"]
            hit["topic_id"] = "w6_topic_unknown"
            hit["hit_id"] = compute_query_hit_id(
                acquisition_run_id=hit["acquisition_run_id"],
                topic_id=hit["topic_id"],
                query_variant_id=hit["query_variant_id"],
                openalex_id=hit["openalex_id"],
            )
            record = next(row for row in records if row["record_id"] == hit["record_id"])
            record["hit_ids"] = [
                hit["hit_id"] if value == old_hit_id else value
                for value in record["hit_ids"]
            ]
            record["topic_ids"] = sorted(set(record["topic_ids"] + [hit["topic_id"]]))
            write_jsonl(package / "query_hits.jsonl", hits)
            write_jsonl(package / "works.jsonl", records)

        self.assert_repacked_mutation_rejected(mutate, "unknown frozen topic/query")

    def test_repacked_duplicate_topic_query_work_triple_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            hits = read_jsonl(package / "query_hits.jsonl")
            hits.append(copy.deepcopy(hits[0]))
            write_jsonl(package / "query_hits.jsonl", hits)

        self.assert_repacked_mutation_rejected(mutate, "重复 \\(topic, query, work\\)")

    def test_repacked_run_and_client_count_drift_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            runs = read_json(package / "query_runs.json")
            run = runs["runs"][0]
            run["retrieved_work_count"] += 1
            run["client_stats"]["actual_result_count"] += 1
            write_json(package / "query_runs.json", runs)

        self.assert_repacked_mutation_rejected(mutate, "run/hit retrieved count closure")

        def fabricate_missing_id_count(package: Path) -> None:
            runs = read_json(package / "query_runs.json")
            run = runs["runs"][0]
            run["missing_openalex_id_skipped"] = 1
            run["client_stats"]["actual_result_count"] += 1
            write_json(package / "query_runs.json", runs)

        self.assert_repacked_mutation_rejected(
            fabricate_missing_id_count,
            "不允许无法绑定 canonical Work ID",
        )

    def test_repacked_malformed_openalex_work_id_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            records = read_jsonl(package / "works.jsonl")
            hits = read_jsonl(package / "query_hits.jsonl")
            record = next(row for row in records if len(row["hit_ids"]) == 1)
            hit = next(row for row in hits if row["record_id"] == record["record_id"])
            malformed_id = "W01"
            record["openalex_id"] = malformed_id
            record["record_id"] = f"openalex:{malformed_id}"
            record["openalex_url"] = f"https://openalex.org/{malformed_id}"
            hit["openalex_id"] = malformed_id
            hit["record_id"] = record["record_id"]
            hit["hit_id"] = compute_query_hit_id(
                acquisition_run_id=hit["acquisition_run_id"],
                topic_id=hit["topic_id"],
                query_variant_id=hit["query_variant_id"],
                openalex_id=malformed_id,
            )
            record["hit_ids"] = [hit["hit_id"]]
            write_jsonl(package / "works.jsonl", records)
            write_jsonl(package / "query_hits.jsonl", hits)

        self.assert_repacked_mutation_rejected(mutate, "canonical OpenAlex Work ID")

    def test_repacked_inverted_query_chronology_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            runs = read_json(package / "query_runs.json")
            runs["runs"][0]["query_completed_at"] = "2026-08-26T07:59:59+00:00"
            write_json(package / "query_runs.json", runs)

        self.assert_repacked_mutation_rejected(mutate, "chronology drift")

    def test_repacked_modified_frozen_query_semantics_are_rejected_by_trust_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package = root / "package"
            drifted_config_path = root / "drifted-config.json"
            self.build_package(package)
            drifted_config = copy.deepcopy(self.config)
            drifted_variant = drifted_config["topics"][0]["query_variants"][0]
            drifted_variant["query_text"] += " post-hoc drift"
            drifted_config["config_identity"] = compute_query_config_identity(
                drifted_config
            )
            write_json(drifted_config_path, drifted_config)

            manifest = read_json(package / "manifest.json")
            manifest["config_reference"] = {
                "artifact_id": drifted_config["artifact_id"],
                "config_identity": drifted_config["config_identity"],
                "sha256": sha256_file(drifted_config_path),
            }
            write_json(package / "manifest.json", manifest)
            runs = read_json(package / "query_runs.json")
            runs["runs"][0]["query_text"] = drifted_variant["query_text"]
            write_json(package / "query_runs.json", runs)
            new_run_id = compute_acquisition_run_id(
                config_identity=drifted_config["config_identity"],
                acquisition_started_at=manifest["acquisition_started_at"],
            )
            rewrite_package_run_identity(
                package,
                acquisition_run_id=new_run_id,
                config_identity=drifted_config["config_identity"],
            )
            runs = read_json(package / "query_runs.json")
            records = read_jsonl(package / "works.jsonl")
            hits = read_jsonl(package / "query_hits.jsonl")
            audit = build_topic_audit(
                config=drifted_config,
                records=records,
                hits=hits,
                query_runs=runs["runs"],
                generated_at=runs["acquisition_completed_at"],
            )
            write_json(package / "topic_audit.json", audit)
            (package / "topic_audit.md").write_text(
                render_topic_audit_markdown(audit),
                encoding="utf-8",
                newline="\n",
            )
            repackage_with_fresh_hashes(package)

            with self.assertRaisesRegex(ValueError, "pre-acquisition.*identity"):
                validate_acquisition_package(
                    package_dir=package,
                    config_path=drifted_config_path,
                    topic_set_path=TOPIC_PATH,
                    split_path=SPLIT_PATH,
                )

    def test_repacked_arbitrary_acquisition_run_id_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            rewrite_package_run_identity(
                package,
                acquisition_run_id="w6-openalex-live-run:sha256:" + "0" * 64,
            )

        self.assert_repacked_mutation_rejected(
            mutate, "acquisition_run_id deterministic derivation drift"
        )

    def test_repacked_arbitrary_query_run_id_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            runs = read_json(package / "query_runs.json")
            hits = read_jsonl(package / "query_hits.jsonl")
            run = runs["runs"][0]
            arbitrary_id = "w6-openalex-query-run:sha256:" + "1" * 64
            run["query_run_id"] = arbitrary_id
            for hit in hits:
                if (
                    hit["topic_id"] == run["topic_id"]
                    and hit["query_variant_id"] == run["query_variant_id"]
                ):
                    hit["query_run_id"] = arbitrary_id
            write_json(package / "query_runs.json", runs)
            write_jsonl(package / "query_hits.jsonl", hits)

        self.assert_repacked_mutation_rejected(
            mutate, "query_run_id deterministic derivation drift"
        )

    def test_repacked_arbitrary_hit_id_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            hits = read_jsonl(package / "query_hits.jsonl")
            records = read_jsonl(package / "works.jsonl")
            hit = hits[0]
            old_hit_id = hit["hit_id"]
            hit["hit_id"] = "w6-openalex-hit:sha256:" + "2" * 64
            record = next(row for row in records if row["record_id"] == hit["record_id"])
            record["hit_ids"] = [
                hit["hit_id"] if value == old_hit_id else value
                for value in record["hit_ids"]
            ]
            write_jsonl(package / "query_hits.jsonl", hits)
            write_jsonl(package / "works.jsonl", records)

        self.assert_repacked_mutation_rejected(
            mutate, "hit ID deterministic derivation drift"
        )

    def test_repacked_derived_work_provenance_drift_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            records = read_jsonl(package / "works.jsonl")
            records[0]["query_variant_ids"] = ["fabricated_query_variant"]
            write_jsonl(package / "works.jsonl", records)

        self.assert_repacked_mutation_rejected(mutate, "反向 provenance drift")

    def test_repacked_topic_audit_drift_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            audit = read_json(package / "topic_audit.json")
            audit["topics"][0]["union_work_count"] += 1
            write_json(package / "topic_audit.json", audit)

        self.assert_repacked_mutation_rejected(mutate, "canonical full audit model drift")

    def test_repacked_cross_topic_statistic_drift_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            audit = read_json(package / "topic_audit.json")
            audit["cross_topic_overlap"][0]["jaccard"] = 0.999999
            write_json(package / "topic_audit.json", audit)

        self.assert_repacked_mutation_rejected(mutate, "canonical full audit model drift")

    def test_repacked_missing_query_run_breaks_frozen_bijection(self) -> None:
        def mutate(package: Path) -> None:
            runs = read_json(package / "query_runs.json")
            runs["runs"].pop()
            runs["query_count"] -= 1
            manifest = read_json(package / "manifest.json")
            manifest["query_count"] -= 1
            write_json(package / "query_runs.json", runs)
            write_json(package / "manifest.json", manifest)

        self.assert_repacked_mutation_rejected(
            mutate, "manifest/query_runs/frozen config query_count drift"
        )

    def test_repacked_topic_audit_markdown_drift_is_rejected(self) -> None:
        def mutate(package: Path) -> None:
            with (package / "topic_audit.md").open(
                "a", encoding="utf-8", newline="\n"
            ) as handle:
                handle.write("post-hoc narrative drift\n")

        self.assert_repacked_mutation_rejected(mutate, "canonical audit render drift")

    def test_live_path_does_not_import_dotenv_or_label_aware_w6_modules(self) -> None:
        source = (PROJECT_ROOT / "app" / "run_w6_openalex_audit.py").read_text(encoding="utf-8")
        module_source = (PROJECT_ROOT / "src" / "w6_openalex_audit.py").read_text(encoding="utf-8")

        self.assertNotIn("load_dotenv", source + module_source)
        self.assertNotIn("src.w6_benchmark", source + module_source)
        self.assertNotIn("src.w6_boundary_ranking", source + module_source)


if __name__ == "__main__":
    unittest.main()
