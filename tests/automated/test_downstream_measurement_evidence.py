"""Primary arithmetic/identity regression against the REAL external evidence.

These tests are gated behind SRTP_DOWNSTREAM_EVIDENCE_ROOT because the
evidence lives outside the repository. In CI without the variable they skip
silently; locally they exercise the full 24/144/72/432 identity lattice and
the frozen first-look reproduction.
"""
from __future__ import annotations

import os
import unittest
from fractions import Fraction
from pathlib import Path

EVIDENCE_ROOT = os.environ.get("SRTP_DOWNSTREAM_EVIDENCE_ROOT")
SUPPLEMENT_ZIP = os.environ.get("SRTP_DOWNSTREAM_SUPPLEMENT_ZIP")

REQ = EVIDENCE_ROOT and Path(EVIDENCE_ROOT).exists()


@unittest.skipUnless(REQ, "SRTP_DOWNSTREAM_EVIDENCE_ROOT not set or missing")
class TestRealEvidenceIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.downstream_measurement.canonical import build_canonical
        from src.downstream_measurement.first_look import reproduce_first_look

        cls.registry = build_canonical(Path(EVIDENCE_ROOT), Path(SUPPLEMENT_ZIP) if SUPPLEMENT_ZIP else None)
        cls.reproduction = reproduce_first_look(cls.registry.to_dict())

    def test_lattice_complete_24_outputs(self):
        v = self.registry.validation
        self.assertEqual(v["outputs"], 24)
        self.assertTrue(v["lattice_complete"])
        cells = {(r["topic_id"], r["task_id"], r["arm"], r["repetition"]) for r in self.registry.outputs}
        self.assertEqual(len(cells), 24)

    def test_claims_144(self):
        self.assertEqual(self.registry.validation["claims"], 144)

    def test_evaluations_72_primary_plus_24_sensitivity(self):
        v = self.registry.validation
        self.assertEqual(v["primary_evaluations"], 72)
        self.assertEqual(v["sensitivity_evaluations"], 24)

    def test_primary_claim_judgements_432(self):
        self.assertEqual(self.registry.validation["primary_claim_judgements"], 432)

    def test_arm_mapping_unique_per_output(self):
        per_output = {}
        for row in self.registry.claim_judgements:
            per_output.setdefault((row["evaluator"], row["output_id"]), set()).add(row["arm"])
        self.assertTrue(all(len(arms) == 1 for arms in per_output.values()))

    def test_identity_consistent_across_judges(self):
        identity = {(r["output_id"]): (r["topic_id"], r["task_id"], r["arm"], r["repetition"])
                    for r in self.registry.outputs}
        for row in self.registry.claim_judgements:
            self.assertEqual(identity[row["output_id"]],
                             (row["topic_id"], row["task_id"], row["arm"], row["repetition"]))

    def test_no_duplicate_evaluator_output(self):
        keys = [(r["evaluator"], r["output_id"]) for r in self.registry.evaluations]
        self.assertEqual(len(keys), len(set(keys)))

    def test_full_pro_never_in_primary(self):
        result = self.reproduction
        self.assertNotIn("FullPro", result["primary"])
        self.assertIn("FullPro", result["sensitivity"])

    def test_directions_are_mca_minus_bm25(self):
        for evaluator, agg in self.reproduction["primary"].items():
            macro = agg["macro"]
            self.assertEqual(macro["Delta_U"], macro["MCA_mean_U"] - macro["BM25_mean_U"])

    def test_frozen_first_look_reproduced(self):
        from src.downstream_measurement.inventory import resolve_package_directory

        frozen_csv = (resolve_package_directory(Path(EVIDENCE_ROOT), "unblinded_analysis")
                      / "results" / "JUDGE_PRIMARY_MACRO_RESULTS.csv")
        from src.downstream_measurement.first_look import compare_to_frozen

        comparison = compare_to_frozen(self.reproduction, frozen_csv.read_text(encoding="utf-8-sig"))
        mismatches = [row for row in comparison if not row.get("match", False)]
        self.assertEqual(mismatches, [], f"frozen first-look reproduction mismatch: {mismatches}")


if __name__ == "__main__":
    unittest.main()
