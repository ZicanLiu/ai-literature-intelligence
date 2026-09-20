"""Third-layer closure review regression tests (R1-R15).

Deterministic, offline, synthetic. Uses the mini evidence root builder; no
external evidence, network, LLM, or repository mutation involved.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.automated.test_downstream_measurement import MiniEvidenceRoot
from src.downstream_measurement.canonical import CanonicalBuildError, build_canonical
from src.downstream_measurement.first_look import (
    FROZEN_COMPARISON_FIELDS,
    FROZEN_JUDGE_ROSTER,
    compare_to_frozen,
    reproduce_first_look,
)
from src.downstream_measurement.figures import REQUIRED_FIGURES, loo_endpoint_series, render_all
from src.downstream_measurement.integrity import (
    DUPLICATE_MEMBER_BASENAME,
    MISSING_SOURCE_BYTES,
    MISSING_UNANCHORED_SUPPLEMENT_MEMBER,
    SELF_HASHED_UNANCHORED,
    SUPPLEMENT_MEMBER_NAMES,
    collect_missing_source_rows,
    verify_zip_package,
)
from src.downstream_measurement.util import (
    mark_staging_partial,
    prepare_staging_target,
    publish_staging,
)


class TestR1RegistryEvidenceByteBinding(unittest.TestCase):
    """Registry <-> evidence drift must fail closed at BYTE level, not only
    manifest-file level (R1/R13)."""

    def _registry_and_root(self, tmp):
        mini = MiniEvidenceRoot(Path(tmp))
        registry = build_canonical(mini.root, None)
        return mini, registry

    def test_condition_mapping_mutation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, registry = self._registry_and_root(tmp)
            mapping = mini.prep / "contexts" / "private_mapping" / "condition_mapping.json"
            doc = json.loads(mapping.read_text("utf-8"))
            doc[0]["context_token_count"] += 1
            mapping.write_text(json.dumps(doc), encoding="utf-8")
            from app.run_downstream_measurement_audit import _verify_registry_matches_evidence

            mismatches = _verify_registry_matches_evidence(registry.to_dict(), mini.root)
            self.assertTrue(any("condition_mapping" in m or "byte-layer" in m for m in mismatches),
                            mismatches)

    def test_generator_output_mutation_with_unchanged_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, registry = self._registry_and_root(tmp)
            victim = mini.formal / "public_blinded_outputs" / mini.runs[0]["output_id"] / "generator_output.json"
            doc = json.loads(victim.read_text("utf-8"))
            doc["claims"][0]["claim_text"] += " tampered"
            victim.write_text(json.dumps(doc), encoding="utf-8")  # manifest left untouched
            from app.run_downstream_measurement_audit import _verify_registry_matches_evidence

            mismatches = _verify_registry_matches_evidence(registry.to_dict(), mini.root)
            self.assertTrue(any("byte-layer" in m and "generator_output" in m for m in mismatches),
                            mismatches)

    def test_judgement_mutation_with_unchanged_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, registry = self._registry_and_root(tmp)
            victim = next((mini.root / "DOWNSTREAM_AI_EVAL_GLM_20260915" / "judgements").glob("*.json"))
            doc = json.loads(victim.read_text("utf-8"))
            doc["claim_units"][0]["scope"] = "OUT_OF_SCOPE"
            victim.write_text(json.dumps(doc), encoding="utf-8")  # judge manifest untouched
            from app.run_downstream_measurement_audit import _verify_registry_matches_evidence

            mismatches = _verify_registry_matches_evidence(registry.to_dict(), mini.root)
            self.assertTrue(any("byte-layer" in m for m in mismatches), mismatches)

    def test_unchanged_evidence_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, registry = self._registry_and_root(tmp)
            from app.run_downstream_measurement_audit import _verify_registry_matches_evidence

            self.assertEqual(_verify_registry_matches_evidence(registry.to_dict(), mini.root), [])


class TestR2FullProExactRoster(unittest.TestCase):
    def _supplement_with(self, tmp, mutate):
        mini = MiniEvidenceRoot(Path(tmp))
        zpath = Path(tmp) / "supp.zip"
        mini.write_supplement_zip(zpath)
        member_dir = Path(tmp) / "supp_dir"
        with zipfile.ZipFile(zpath) as archive:
            archive.extractall(member_dir)
        doc_path = next(member_dir.rglob("PRO_FULL_BLIND_AUDIT_144.json"))
        doc = json.loads(doc_path.read_text("utf-8"))
        mutate(doc)
        doc_path.write_text(json.dumps(doc), encoding="utf-8")
        return mini, member_dir

    def test_unknown_output_fails(self):
        def mutate(doc):
            doc["outputs"][0]["output_id"] = "output_unknown"
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._supplement_with(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_missing_output_fails(self):
        def mutate(doc):
            doc["outputs"] = doc["outputs"][:-1]
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._supplement_with(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_duplicate_output_fails(self):
        def mutate(doc):
            doc["outputs"].append(json.loads(json.dumps(doc["outputs"][0])))
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._supplement_with(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_duplicate_evaluation_id_fails(self):
        def mutate(doc):
            doc["outputs"][1]["evaluation_id"] = doc["outputs"][0]["evaluation_id"]
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._supplement_with(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)


class TestR3FullProEventStructure(unittest.TestCase):
    def _supplement_with(self, tmp, mutate):
        mini = MiniEvidenceRoot(Path(tmp))
        zpath = Path(tmp) / "supp.zip"
        mini.write_supplement_zip(zpath)
        member_dir = Path(tmp) / "supp_dir"
        with zipfile.ZipFile(zpath) as archive:
            archive.extractall(member_dir)
        doc_path = next(member_dir.rglob("PRO_FULL_BLIND_AUDIT_144.json"))
        doc = json.loads(doc_path.read_text("utf-8"))
        mutate(doc)
        doc_path.write_text(json.dumps(doc), encoding="utf-8")
        return mini, member_dir

    def test_duplicate_error_id_inflating_e_fails(self):
        def mutate(doc):
            out = doc["outputs"][0]
            out["claims"][0]["error_ids"] = ["E1"]
            out["claims"][1]["error_ids"] = ["E1"]
            out["error_events"] = [
                {"error_id": "E1", "affected_appearance_indices": [1, 2], "error_types": ["t"]},
                {"error_id": "E1", "affected_appearance_indices": [1], "error_types": ["t"]},
            ]
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._supplement_with(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_nonreciprocal_event_link_fails(self):
        def mutate(doc):
            out = doc["outputs"][0]
            out["claims"][0]["error_ids"] = ["E1"]
            out["error_events"] = [
                {"error_id": "E1", "affected_appearance_indices": [1, 2], "error_types": ["t"]},
            ]
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._supplement_with(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_unknown_event_link_fails(self):
        def mutate(doc):
            out = doc["outputs"][0]
            out["claims"][0]["error_ids"] = ["E9"]
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._supplement_with(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)


class TestR4FrozenComparisonFields(unittest.TestCase):
    def _reproduction_with_judges(self):
        rows = []
        for topic in ("t1", "t2"):
            for task in ("A", "B"):
                for arm in ("BM25", "MCA"):
                    for rep in (1, 2, 3):
                        rows.append({"evaluator": "J", "output_id": f"{topic}{task}{arm}{rep}",
                                     "topic_id": topic, "task_id": task, "arm": arm,
                                     "repetition": rep,
                                     "useful_information_slots": 5 if arm == "BM25" else 6,
                                     "substantive_error_count": 1 if arm == "BM25" else 0,
                                     "submitted_claim_count": 6, "role": "PRIMARY_JUDGE"})
        return rows

    def _frozen_csv(self, bm25_e="1.0", mca_e="0.0"):
        rows = []
        for judge in FROZEN_JUDGE_ROSTER:
            rows.append(
                f"{judge},4,12,12,5.0,6.0,1.0,MCA_HIGHER,{bm25_e},{mca_e},"
                f"{float(mca_e) - float(bm25_e):.16g},MCA_LOWER,PASS")
        return "judge,n_cells,n_expected_per_arm,n_observed_per_arm,BM25_mean_U,MCA_mean_U,Delta_U,U_direction,BM25_mean_E,MCA_mean_E,Delta_E,E_direction,E_status\n" + "\n".join(rows)

    def test_e_arm_means_corrupted_but_delta_kept_must_fail(self):
        registry = {
            "claim_judgements": [],
            "error_events": [],
            "primary": {},
        }
        # build a real reproduction via lattice rows
        from src.downstream_measurement.first_look import aggregate, output_score_rows

        score_rows = self._reproduction_with_judges()
        # relabel evaluator to each judge so all three appear
        for judge in FROZEN_JUDGE_ROSTER:
            for row in score_rows:
                pass
        # simplest: one judge rows cloned per judge
        cloned = []
        for judge in FROZEN_JUDGE_ROSTER:
            for row in score_rows:
                item = dict(row, evaluator=judge, output_id=judge + row["output_id"])
                cloned.append(item)
        reproduction = {"primary": {judge: aggregate(cloned, judge) for judge in FROZEN_JUDGE_ROSTER},
                        "sensitivity": {}, "roles": {}}
        comparison = compare_to_frozen(reproduction, self._frozen_csv(bm25_e="999.0", mca_e="998.0"))
        self.assertFalse(all(row.get("match", True) for row in comparison))

    def test_all_fields_compared_and_roster_locked(self):
        self.assertEqual(len(FROZEN_COMPARISON_FIELDS), 8)
        self.assertEqual(sorted(FROZEN_JUDGE_ROSTER), ["DeepSeek", "GLM", "GPT"])


class TestR5R12Figures(unittest.TestCase):
    def test_loo_series_filters_endpoint_u_only(self):
        influence = {"leave_one_output_out": [
            {"evaluator": "GPT", "endpoint": "U", "macro_after_exclusion": 0.5},
            {"evaluator": "GPT", "endpoint": "E", "macro_after_exclusion": -0.5},
            {"evaluator": "FullPro", "endpoint": "U", "macro_after_exclusion": -0.6},
        ]}
        series = loo_endpoint_series(influence, "U")
        self.assertEqual(len(series), 2)
        self.assertTrue(all(row["endpoint"] == "U" for row in series))

    def test_required_figure_roster_locked(self):
        self.assertEqual(len(REQUIRED_FIGURES), 7)

    def test_render_all_reports_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = render_all({
                "reproduction": {}, "sensitivity": {}, "decomposition": {},
                "influence": {}, "counterfactual": {}, "integrity": {},
            }, Path(tmp) / "figs")
            self.assertTrue(result["failed"])
            self.assertEqual(len(result["written"]) + len(result["failed"]), 7)


class TestR6SupplementRosterClosure(unittest.TestCase):
    def test_missing_expected_members_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            supplement = Path(tmp) / "supp"
            supplement.mkdir()
            (supplement / "PRO_FULL_BLIND_AUDIT_144.json").write_text("{}", encoding="utf-8")
            result = verify_zip_package(supplement, "meeting_supplement_pro_full")
            self.assertEqual(result["summary"]["missing_unanchored_supplement_members"],
                             len(SUPPLEMENT_MEMBER_NAMES) - 1)

    def test_duplicate_zip_basename_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "dup.zip"
            with zipfile.ZipFile(zpath, "w") as archive:
                archive.writestr("a/PRO_FULL_BLIND_AUDIT_144.json", "one")
                archive.writestr("b/PRO_FULL_BLIND_AUDIT_144.json", "two")
            result = verify_zip_package(zpath, "meeting_supplement_pro_full")
            dupes = [row for row in result["rows"] if row["verification_level"] == DUPLICATE_MEMBER_BASENAME]
            self.assertEqual(len(dupes), 1)


class TestR7FullProLocators(unittest.TestCase):
    def test_row_level_locators(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            zpath = Path(tmp) / "supp.zip"
            mini.write_supplement_zip(zpath)
            registry = build_canonical(mini.root, zpath)
            pro_units = [r for r in registry.claim_judgements if r["evaluator"] == "FullPro"]
            for row in pro_units[:5]:
                self.assertRegex(row["source_locator"], r"#/outputs/\d+/claims/\d+$")


class TestR8AtomicPublication(unittest.TestCase):
    def test_existing_target_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            target.mkdir()
            (target / "stale.txt").write_text("stale", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                prepare_staging_target(target)

    def test_staging_publish_and_partial_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            staging = prepare_staging_target(target)
            self.assertFalse(target.exists())
            (staging / "x.txt").write_text("x", encoding="utf-8")
            mark_staging_partial(staging, "unit-test failure")
            self.assertTrue((staging / "_PARTIAL_FAILED.txt").exists())
            (staging / "_PARTIAL_FAILED.txt").unlink()
            publish_staging(staging, target)
            self.assertTrue((target / "x.txt").exists())
            self.assertFalse(staging.exists())

    def test_build_cli_midrun_failure_leaves_no_final_target(self):
        from app import build_downstream_evidence_registry as cli

        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            # break the chain so the build fails mid-run after staging creation
            (mini.formal / "SHA256_manifest.txt").write_text(
                "0" * 64 + "  public_blinded_outputs/nonexistent.json\n", encoding="utf-8")
            target = Path(tmp).parent / (Path(tmp).name + "_derived")
            code = cli.main(["--evidence-root", str(mini.root), "--output-dir", str(target)])
            self.assertNotEqual(code, 0)
            self.assertFalse(target.exists(), "final target must not appear on failure")
            staging = Path(str(target) + ".staging")
            self.assertTrue((staging / "_PARTIAL_FAILED.txt").exists(),
                            "staging must carry an explicit partial marker")


class TestR9MissingRowsFromIntegrity(unittest.TestCase):
    def test_collect_missing_source_rows(self):
        rows = [
            {"package": "p", "file": "a", "verification_level": MISSING_SOURCE_BYTES},
            {"package": "p", "file": "b", "verification_level": SELF_HASHED_UNANCHORED},
            {"package": "s", "file": "c",
             "verification_level": MISSING_UNANCHORED_SUPPLEMENT_MEMBER},
        ]
        missing = collect_missing_source_rows(rows)
        self.assertEqual({row["file"] for row in missing}, {"a", "c"})


class TestR15DocsAndRosters(unittest.TestCase):
    def test_preservation_plan_has_no_stale_count(self):
        text = (Path(__file__).resolve().parents[2] / "docs" / "project"
                / "EXTERNAL_RESEARCH_EVIDENCE_PRESERVATION_PLAN.md").read_text(encoding="utf-8")
        self.assertNotIn("9754", text)
        self.assertNotIn("9,754", text)
        self.assertIn("RAW PRIVATE EVIDENCE", text)

    def test_report_has_no_retired_driver(self):
        text = (Path(__file__).resolve().parents[2] / "docs" / "reports" / "downstream"
                / "DOWNSTREAM_EVIDENCE_AND_MEASUREMENT_RECONSTRUCTION_20260919.md").read_text(encoding="utf-8")
        self.assertNotIn("08c8969a", text)


if __name__ == "__main__":
    unittest.main()
