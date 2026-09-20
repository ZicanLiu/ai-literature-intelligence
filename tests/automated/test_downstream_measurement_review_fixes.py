"""Regression tests for the second-layer code review findings (F1-F11).

Deterministic, offline, synthetic: reuses the mini evidence root builder from
test_downstream_measurement. No external evidence, network, or LLM involved.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
import zipfile
from fractions import Fraction
from pathlib import Path

from tests.automated.test_downstream_measurement import MiniEvidenceRoot
from src.downstream_measurement.canonical import CanonicalBuildError, build_canonical
from src.downstream_measurement.first_look import aggregate
from src.downstream_measurement.influence import (
    claim_template_concentration,
    equal_cell_delta_allow_variable_reps,
)
from src.downstream_measurement.integrity import (
    SELF_HASHED_UNANCHORED,
    VERIFIED_BYTES,
    load_integrity_summary,
    persist_integrity,
    verify_zip_package,
)
from src.downstream_measurement.util import sha256_file


class TestF1IntegritySummarySchema(unittest.TestCase):
    def test_schema_roundtrip_and_legacy_compatibility(self):
        integrity = {
            "packages": {"formal_execution": {"summary": {"verified": 48, "mismatched": 0, "missing": 0},
                                              "manifest_sha256": "a" * 64}},
            "rows": [],
            "counts": {"packages_verified": 1, "files_verified": 48, "bytes_mismatch": 0,
                       "missing_source_bytes": 0, "formal_chain_mismatch": 0,
                       "formal_chain_missing": 0, "self_hashed_unanchored": 0,
                       "documented_exceptions_confirmed": 0},
            "documented_exceptions": [],
            "fail_closed": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "derived"
            persist_integrity(integrity, out)
            loaded = load_integrity_summary(out / "integrity" / "integrity_summary.json")
            self.assertEqual(set(loaded["packages"]), {"formal_execution"})
            self.assertEqual(loaded["packages"]["formal_execution"]["summary"]["verified"], 48)
            legacy_path = out / "legacy.json"
            legacy_path.write_text(
                json.dumps({"formal_execution": {"summary": {"verified": 1}}, "counts": {}}),
                encoding="utf-8")
            legacy_loaded = load_integrity_summary(legacy_path)
            self.assertEqual(set(legacy_loaded["packages"]), {"formal_execution"})


class TestF2SupplementSelfHashed(unittest.TestCase):
    def test_supplement_present_members_self_hashed_and_missing_roster_visible(self):
        from src.downstream_measurement.integrity import MISSING_UNANCHORED_SUPPLEMENT_MEMBER

        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            zpath = Path(tmp) / "supp.zip"
            mini.write_supplement_zip(zpath)  # contains only PRO_FULL_BLIND_AUDIT_144.json
            result = verify_zip_package(zpath, "meeting_supplement_pro_full")
            levels = {row["verification_level"]: 0 for row in result["rows"]}
            counts = {}
            for row in result["rows"]:
                counts[row["verification_level"]] = counts.get(row["verification_level"], 0) + 1
            self.assertEqual(counts.get(SELF_HASHED_UNANCHORED), 1)
            self.assertEqual(counts.get(MISSING_UNANCHORED_SUPPLEMENT_MEMBER), 11)
            self.assertNotIn(VERIFIED_BYTES, counts)
            self.assertEqual(result["summary"]["verified"], 0)
            self.assertIsNone(result["manifest_sha256"])
            self.assertEqual(result["identity_kind"], "SELF_HASHED_ZIP")

    def test_extracted_dir_scope_limited_to_known_members(self):
        from src.downstream_measurement.integrity import MISSING_UNANCHORED_SUPPLEMENT_MEMBER

        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            zpath = Path(tmp) / "supp.zip"
            mini.write_supplement_zip(zpath)
            extract = Path(tmp) / "extracted"
            with zipfile.ZipFile(zpath) as archive:
                archive.extractall(extract)
            supplement_dir = next(extract.rglob("PRO_FULL_BLIND_AUDIT_144.json")).parent
            (supplement_dir / "unrelated_download.txt").write_text("not a supplement member", encoding="utf-8")
            result = verify_zip_package(supplement_dir, "meeting_supplement_pro_full")
            names = {row["file"] for row in result["rows"]}
            self.assertNotIn("unrelated_download.txt", names)
            self.assertIn("PRO_FULL_BLIND_AUDIT_144.json", names)
            missing = [row for row in result["rows"]
                       if row["verification_level"] == MISSING_UNANCHORED_SUPPLEMENT_MEMBER]
            self.assertEqual(len(missing), 11)
            self.assertEqual(result["identity_kind"], "SELF_HASHED_MEMBER_SET")


class TestF3FullProClaimAlignment(unittest.TestCase):
    def _tampered(self, tmp, mutate):
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

    def test_claim_order_swapped_fails_closed(self):
        def mutate(doc):
            out = doc["outputs"][0]
            out["claims"][0], out["claims"][1] = out["claims"][1], out["claims"][0]
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_appearance_index_wrong_fails_closed(self):
        def mutate(doc):
            doc["outputs"][0]["claims"][0]["appearance_index"] = 7
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_claim_text_one_char_mutation_fails_closed(self):
        def mutate(doc):
            doc["outputs"][0]["claims"][0]["claim_text"] += "x"
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_output_binding_intact_but_claim_text_drift_fails_closed(self):
        def mutate(doc):
            text = doc["outputs"][0]["claims"][1]["claim_text"]
            doc["outputs"][0]["claims"][1]["claim_text"] = text[:-1] + "!"
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, mutate)
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)


class TestF4RowLevelProvenance(unittest.TestCase):
    def test_canonical_rows_carry_source_package_and_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            zpath = Path(tmp) / "supp.zip"
            mini.write_supplement_zip(zpath)
            registry = build_canonical(mini.root, zpath)
            for row in registry.claim_judgements:
                self.assertIn("source_package_id", row)
                self.assertRegex(row["source_file_sha256"], r"^[0-9a-f]{64}$")
            for row in registry.error_events:
                self.assertIn("source_package_id", row)
                self.assertRegex(row["source_file_sha256"], r"^[0-9a-f]{64}$")
            pro_evals = [r for r in registry.evaluations if r["evaluator"] == "FullPro"]
            self.assertTrue(pro_evals)
            self.assertTrue(all(r["judgement_file_sha256"] for r in pro_evals))


class TestF5EqualCellEstimand(unittest.TestCase):
    def _lattice_rows(self):
        rows = []
        for topic in ("t1", "t2"):
            for task in ("A", "B"):
                for arm, u_values in (("BM25", [4, 5, 6]), ("MCA", [6, 6, 6])):
                    for rep, u in zip((1, 2, 3), u_values):
                        rows.append({"evaluator": "J", "output_id": f"{topic}{task}{arm}{rep}",
                                     "topic_id": topic, "task_id": task, "arm": arm,
                                     "repetition": rep, "useful_information_slots": u,
                                     "substantive_error_count": 0, "submitted_claim_count": 6,
                                     "role": "PRIMARY_JUDGE"})
        return rows

    def test_complete_data_equals_frozen_macro(self):
        rows = self._lattice_rows()
        frozen_macro = aggregate(rows, "J")["macro"]["Delta_U"]
        self.assertEqual(equal_cell_delta_allow_variable_reps(rows, "J"), frozen_macro)

    def test_exclusion_keeps_equal_cell_weights(self):
        rows = self._lattice_rows()
        reduced = [r for r in rows if r["output_id"] != "t1AMCA3"]
        # t1|A MCA mean drops to 2 reps (6+6)/2=6; cell weight stays 1/4
        expected = Fraction(4 * (6 - 5)) / 4
        self.assertEqual(equal_cell_delta_allow_variable_reps(reduced, "J"), expected)

    def test_arm_emptied_returns_none(self):
        rows = [r for r in self._lattice_rows() if not (r["topic_id"] == "t1" and r["task_id"] == "A" and r["arm"] == "MCA")]
        self.assertIsNone(equal_cell_delta_allow_variable_reps(rows, "J"))


class TestF6ClaimRepetitionCountingUnit(unittest.TestCase):
    def test_two_claims_four_evaluators_counted_once(self):
        claims = [
            {"output_id": "o1", "claim_text_sha256": "a" * 64, "claim_text": "alpha beta gamma delta"},
            {"output_id": "o2", "claim_text_sha256": "b" * 64, "claim_text": "epsilon zeta eta theta"},
        ]
        judgements = []
        for evaluator in ("GPT", "DeepSeek", "GLM", "FullPro"):
            for index, claim in enumerate(claims):
                judgements.append({"evaluator": evaluator, "output_id": claim["output_id"],
                                   "appearance_index": index + 1})
        result = claim_template_concentration({"claims": claims, "claim_judgements": judgements})
        self.assertEqual(result["exact_text_repetition"]["distinct_claim_texts"], 2)
        self.assertEqual(result["exact_text_repetition"]["claim_texts_appearing_more_than_once"], 0)
        self.assertIn("not semantic clustering",
                      result["lexical_template_diagnostic"]["rule"])


class TestF7DagStrictBinding(unittest.TestCase):
    def test_unrelated_upstream_hash_cannot_verify_edge(self):
        from src.downstream_measurement.dag import DagContext

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / "up"
            upstream.mkdir()
            (upstream / "related.json").write_text("related", encoding="utf-8")
            (upstream / "unrelated.json").write_text("unrelated", encoding="utf-8")
            rows = [
                {"package": "up", "file": "related.json", "actual_sha256": sha256_file(upstream / "related.json"),
                 "verification_level": "VERIFIED_BYTES", "match": True},
                {"package": "up", "file": "unrelated.json", "actual_sha256": sha256_file(upstream / "unrelated.json"),
                 "verification_level": "VERIFIED_BYTES", "match": True},
            ]
            ctx = DagContext(root, {"up": "up"}, None, rows)
            attack = [{"pointer": "$/sha256", "sha256": sha256_file(upstream / "unrelated.json"),
                       "path_hints": ["elsewhere/related.json"]}]
            # correct digest of an unrelated file named as "related" must NOT match
            self.assertEqual(ctx.strict_path_hint_matches("up", attack), (0, 0))
            honest = [{"pointer": "$/sha256", "sha256": sha256_file(upstream / "related.json"),
                       "path_hints": ["pkg/up/related.json"]}]
            self.assertEqual(ctx.strict_path_hint_matches("up", honest), (1, 0))


class TestF8RegistryEvidenceBinding(unittest.TestCase):
    def test_registry_evidence_mismatch_fails_closed(self):
        from app.run_downstream_measurement_audit import _verify_registry_matches_evidence

        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            registry = build_canonical(mini.root, None)
            self.assertEqual(_verify_registry_matches_evidence(registry.to_dict(), mini.root), [])
            (mini.formal / "formal_execution_manifest.json").write_text(
                json.dumps({**mini.formal_manifest, "status": "TAMPERED"}), encoding="utf-8")
            mismatches = _verify_registry_matches_evidence(registry.to_dict(), mini.root)
            self.assertTrue(mismatches)


class TestF9F10DocsHygiene(unittest.TestCase):
    def test_new_docs_free_of_personal_absolute_paths(self):
        docs_root = Path(__file__).resolve().parents[2] / "docs"
        pattern = re.compile("|".join([
            "[A-Za-z][:][" + chr(92) * 2 + "/]+(?:Use" + "rs|UserData)",
            "/" + "Users" + "/",
            "/" + "home" + "/",
        ]))
        offenders = []
        for path in docs_root.rglob("*.md"):
            if not any(key in path.name.upper() for key in
                       ("DOWNSTREAM", "PRESERVATION", "RUBRIC", "MEASUREMENT")):
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_scientific_report_avoids_causal_overreach(self):
        report = (Path(__file__).resolve().parents[2]
                  / "docs" / "reports" / "downstream"
                  / "DOWNSTREAM_EVIDENCE_AND_MEASUREMENT_RECONSTRUCTION_20260919.md").read_text(encoding="utf-8")
        self.assertNotIn("可完全由", report)
        self.assertNotIn("规则解释，不是证据支持判定", report)
        self.assertIn("仍需 human reason audit", report)


if __name__ == "__main__":
    unittest.main()
