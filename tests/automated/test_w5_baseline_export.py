"""B0/B1 W5 基线导出的定向测试（全部离线）。

核心不变量：导出的 artifact 分数必须与直接调用现有
``src.processor.add_preliminary_scores`` / ``src.ranking.apply_two_stage_ranking``
的结果完全一致——exporter 不改变任何公式、权重或阈值。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.annotation_tasks import read_csv_rows
from src.w4_benchmark_evaluation import build_source_index, rank_query_papers
from src.w4_benchmark_validation import TRUSTED_W4_V01_INPUTS
from src.w5_baseline_export import (
    BASELINE_METHODS,
    baseline_parameters,
    collect_baseline_rankings,
    export_baseline_packages,
    load_frozen_inputs,
)
from src.w5_method_contract import (
    FORBIDDEN_RANKING_FIELDS,
    RANKING_FIELDS,
    validate_method_output,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

FIXTURE_ENVIRONMENT = {
    "git_revision": "d558a0888e4c71a9d001a67e0640d28394b6ac88",
    "git_worktree_clean": True,
    "python": {"version": "3.fixture", "implementation": "CPython"},
    "platform": {"system": "fixture", "release": "fixture", "machine": "fixture"},
    "dependencies": {},
}
FIXTURE_STARTED_AT = datetime(2026, 8, 17, 20, 0, tzinfo=timezone(timedelta(hours=8)))

SOURCE_SAMPLE = (
    PROJECT_ROOT / TRUSTED_W4_V01_INPUTS["source_sample"]["path"]
)


class BaselineExportTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        frozen = load_frozen_inputs(PROJECT_ROOT)
        cls.pool_rows = frozen["pool_rows"]
        cls.research_queries = frozen["research_queries"]
        cls.reference_year = frozen["reference_year"]
        cls.source_index = build_source_index(SOURCE_SAMPLE)
        cls.rankings = collect_baseline_rankings(
            cls.pool_rows,
            cls.research_queries,
            cls.source_index,
            cls.reference_year,
        )
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp_dir.cleanup)
        cls.output_root = Path(cls.temp_dir.name) / "w5_methods"
        cls.manifests = export_baseline_packages(
            pool_rows=cls.pool_rows,
            research_queries=cls.research_queries,
            source_index=cls.source_index,
            reference_year=cls.reference_year,
            output_root=cls.output_root,
            environment=FIXTURE_ENVIRONMENT,
        )

    def _direct_scores(self) -> dict[str, dict[str, float]]:
        """不经 exporter，直接复用现有算法重算每个 pair 的 B0/B1 分数。"""
        pool_by_query: dict[str, list[dict]] = {}
        for row in self.pool_rows:
            pool_by_query.setdefault(row["research_query_id"], []).append(row)
        direct: dict[str, dict[str, float]] = {
            "preliminary_score_v1": {},
            "tfidf_two_stage_v1": {},
        }
        for query in self.research_queries["queries"]:
            ranking = rank_query_papers(
                pool_by_query[query["research_query_id"]],
                self.source_index,
                query["ranking_keyword"],
                self.reference_year,
            )
            for paper in ranking["ranked_papers"]:
                direct["preliminary_score_v1"][paper["pair_id"]] = float(
                    paper["preliminary_score"]
                )
                direct["tfidf_two_stage_v1"][paper["pair_id"]] = float(
                    paper["stage2_ranking_score"]
                )
        return direct


class BaselineScoreFidelityTests(BaselineExportTestCase):
    def test_exported_scores_match_direct_recomputation(self) -> None:
        direct = self._direct_scores()
        for method_id, rows in self.rankings.items():
            self.assertEqual(len(rows), 60)
            for row in rows:
                self.assertEqual(
                    row["score"],
                    direct[method_id][row["pair_id"]],
                    f"{method_id} 的 {row['pair_id']} 分数与原算法不一致",
                )

    def test_reference_year_follows_frozen_pool_manifest(self) -> None:
        self.assertEqual(self.reference_year, 2026)
        for method_id in BASELINE_METHODS:
            parameters = self.manifests[method_id]["method"]["parameters"]
            self.assertEqual(parameters["reference_year"], 2026)

    def test_parameters_record_actual_fixed_config(self) -> None:
        b0 = baseline_parameters("preliminary_score_v1", 2026)
        self.assertEqual(b0["preliminary_score_weights"]["relevance_score"], 0.40)
        b1 = baseline_parameters("tfidf_two_stage_v1", 2026)
        self.assertEqual(b1["tfidf_title_weight"], 0.7)
        self.assertEqual(b1["stage1_high_threshold"], 0.20)
        self.assertEqual(b1["stage2_score_weights"]["relevance_score"], 0.50)


class BaselinePackageContractTests(BaselineExportTestCase):
    def test_both_packages_pass_validator(self) -> None:
        for method_id in BASELINE_METHODS:
            result = validate_method_output(
                self.output_root / method_id / "manifest.json",
                project_root=PROJECT_ROOT,
            )
            self.assertEqual(result["method_id"], method_id)
            self.assertEqual(len(result["ranking_rows"]), 60)
            self.assertEqual(
                sorted(result["counts_by_query"].values()), [20, 20, 20]
            )

    def test_ranking_csv_has_exact_contract_fields_and_no_labels(self) -> None:
        for method_id in BASELINE_METHODS:
            fields, rows = read_csv_rows(
                self.output_root / method_id / "ranking.csv"
            )
            self.assertEqual(fields, RANKING_FIELDS)
            self.assertFalse(set(fields) & FORBIDDEN_RANKING_FIELDS)
            self.assertEqual(len(rows), 60)
            self.assertTrue(
                all(row["method_id"] == method_id for row in rows)
            )

    def test_known_aliases_are_independent_rows(self) -> None:
        for method_id in BASELINE_METHODS:
            rows = self.rankings[method_id]
            pair_ids = {row["pair_id"] for row in rows}
            self.assertIn("w4_rq02_002", pair_ids)
            self.assertIn("w4_rq02_011", pair_ids)

    def test_manifest_inputs_match_trusted_anchors(self) -> None:
        for method_id in BASELINE_METHODS:
            inputs = self.manifests[method_id]["inputs"]
            for name in ("candidate_pool", "research_queries"):
                self.assertEqual(
                    inputs[name]["sha256"], TRUSTED_W4_V01_INPUTS[name]["sha256"]
                )
                self.assertEqual(inputs[name]["version"], "w4_pilot_v0.1")
            self.assertEqual(
                inputs["source_sample"]["sha256"],
                TRUSTED_W4_V01_INPUTS["source_sample"]["sha256"],
            )
            self.assertEqual(
                inputs["source_sample"]["version"],
                "w2_live_query_sample_v1",
            )

    def test_baselines_use_contract_v11_for_complete_input_closure(self) -> None:
        for method_id in BASELINE_METHODS:
            manifest = self.manifests[method_id]
            self.assertEqual(manifest["schema_version"], "1.1")
            self.assertEqual(manifest["contract_version"], "1.1")

    def test_label_access_is_declared_false(self) -> None:
        for method_id in BASELINE_METHODS:
            label_access = self.manifests[method_id]["label_access"]
            self.assertIs(label_access["benchmark_labels_read"], False)
            self.assertTrue(label_access["declaration"].strip())

    def test_manifest_roundtrip_as_json(self) -> None:
        manifest_path = self.output_root / "preliminary_score_v1" / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["contract_name"], "w5_method_ranking")
        self.assertEqual(payload["method"]["family"], "baseline")
        self.assertIsNone(payload["method"]["model"])


if __name__ == "__main__":
    unittest.main()
