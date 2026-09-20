"""Final pre-commit closure tests (C1-C3).

C1: a persisted canonical registry must equal a fresh reconstruction.
C2: obtainable Full Pro binding fields fail closed on mismatch.
C3: manifest source_packages retain full package identity.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.automated.test_downstream_measurement import MiniEvidenceRoot
from src.downstream_measurement.canonical import CanonicalBuildError, build_canonical


class TestC1RegistryReconstructionEquality(unittest.TestCase):
    def _loaded(self, tmp):
        mini = MiniEvidenceRoot(Path(tmp))
        zpath = Path(tmp) / "supp.zip"
        mini.write_supplement_zip(zpath)
        return mini, zpath, build_canonical(mini.root, zpath).to_dict()

    def _check(self, mini, zpath, loaded):
        from app.run_downstream_measurement_audit import _verify_registry_matches_reconstruction

        return _verify_registry_matches_reconstruction(loaded, mini.root, zpath)

    def test_unchanged_registry_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, zpath, loaded = self._loaded(tmp)
            self.assertEqual(self._check(mini, zpath, loaded), [])

    def test_claim_scope_mutated_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, zpath, loaded = self._loaded(tmp)
            loaded["claim_judgements"][0]["scope"] = "OUT_OF_SCOPE"
            self.assertTrue(self._check(mini, zpath, loaded))

    def test_claim_deleted_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, zpath, loaded = self._loaded(tmp)
            loaded["claim_judgements"].pop(0)
            self.assertTrue(self._check(mini, zpath, loaded))

    def test_claim_added_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, zpath, loaded = self._loaded(tmp)
            loaded["claim_judgements"].append(dict(loaded["claim_judgements"][0]))
            self.assertTrue(self._check(mini, zpath, loaded))

    def test_provenance_locator_mutated_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, zpath, loaded = self._loaded(tmp)
            loaded["claim_judgements"][0]["source_locator"] = "somewhere:else#/x"
            self.assertTrue(self._check(mini, zpath, loaded))

    def test_sensitivity_rows_without_supplement_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, _, loaded = self._loaded(tmp)
            from app.run_downstream_measurement_audit import _verify_registry_matches_reconstruction

            mismatches = _verify_registry_matches_reconstruction(loaded, mini.root, None)
            self.assertTrue(any("supplement" in m for m in mismatches))


class TestC2FullProBindingFailClosed(unittest.TestCase):
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

    def _wrong_field(self, field):
        def mutate(doc):
            doc["outputs"][0]["source_binding"][field] = "0" * 64
        return mutate

    def test_rubric_binding_wrong_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, self._wrong_field("rubric_sha256_raw_bytes"))
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_task_binding_wrong_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, self._wrong_field("task_sha256_utf8"))
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_research_question_binding_wrong_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, self._wrong_field("research_question_sha256_utf8"))
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_generator_binding_wrong_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, self._wrong_field("output_sha256_raw_bytes"))
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_context_binding_wrong_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, self._wrong_field("context_sha256_utf8"))
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_input_binding_wrong_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini, supp = self._tampered(tmp, self._wrong_field("input_sha256_raw_bytes"))
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, supp)

    def test_genuinely_unavailable_source_stays_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            zpath = Path(tmp) / "supp.zip"
            mini.write_supplement_zip(zpath)
            registry = build_canonical(mini.root, zpath)
            binding = registry.validation["full_pro_binding"]
            self.assertGreaterEqual(binding["binding_fields_unverifiable_no_source"], 24)
            self.assertEqual(binding["status"], "QUALIFIED")


class TestC3ManifestPackageIdentity(unittest.TestCase):
    def test_supplement_identity_survives_into_source_packages(self):
        from src.downstream_measurement.integrity import load_integrity_summary, persist_integrity

        with tempfile.TemporaryDirectory() as tmp:
            integrity = {
                "packages": {
                    "meeting_supplement_pro_full": {
                        "identity_kind": "SELF_HASHED_MEMBER_SET",
                        "manifest_sha256": None,
                        "package_identity_sha256": "c" * 64,
                        "summary": {"verified": 0, "mismatched": 0, "missing": 0, "total": 12},
                    },
                    "formal_execution": {
                        "identity_kind": "SHA256_MANIFEST",
                        "manifest_sha256": "a" * 64,
                        "package_identity_sha256": None,
                        "summary": {"verified": 5, "mismatched": 0, "missing": 0, "total": 5},
                    },
                },
                "rows": [],
                "documented_exceptions": [],
                "fail_closed": False,
                "counts": {"packages_verified": 2},
            }
            out = Path(tmp) / "d"
            persist_integrity(integrity, out)
            loaded = load_integrity_summary(out / "integrity" / "integrity_summary.json")
            manifest_style = {pid: {
                "identity_kind": info.get("identity_kind"),
                "manifest_sha256": info.get("manifest_sha256"),
                "package_identity_sha256": info.get("package_identity_sha256"),
                "summary": info.get("summary"),
            } for pid, info in loaded["packages"].items()}
            supp = manifest_style["meeting_supplement_pro_full"]
            self.assertIsNone(supp["manifest_sha256"])
            self.assertEqual(supp["package_identity_sha256"], "c" * 64)
            self.assertEqual(supp["identity_kind"], "SELF_HASHED_MEMBER_SET")


class TestC3ProductionManifestExit(unittest.TestCase):
    def test_final_manifest_written_by_production_audit(self):
        from app import build_downstream_evidence_registry as build_cli
        from app import run_downstream_measurement_audit as audit_cli

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mini = MiniEvidenceRoot(tmp / "evidence")
            supp_zip = tmp / "supp.zip"
            mini.write_supplement_zip(supp_zip)
            registry_dir = tmp / "registry"
            audit_dir = tmp / "audit"
            code = build_cli.main(["--evidence-root", str(mini.root),
                                   "--supplement-zip", str(supp_zip),
                                   "--output-dir", str(registry_dir)])
            self.assertEqual(code, 0)
            code = audit_cli.main(["--evidence-root", str(mini.root),
                                   "--supplement-zip", str(supp_zip),
                                   "--registry-dir", str(registry_dir),
                                   "--output-dir", str(audit_dir)])
            self.assertEqual(code, 0)
            manifest = json.loads((audit_dir / "manifest.json").read_text("utf-8"))
            supplement = manifest["source_packages"]["meeting_supplement_pro_full"]
            self.assertEqual(supplement["identity_kind"], "SELF_HASHED_ZIP")
            self.assertIsNone(supplement["manifest_sha256"])
            self.assertTrue(supplement["package_identity_sha256"])
            self.assertIn("summary", supplement)
            for key in ("canonical_registry_sha256", "integrity_summary_sha256",
                        "evidence_integrity_sha256", "evidence_dag_sha256"):
                self.assertRegex(manifest["registry_inputs"][key], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
