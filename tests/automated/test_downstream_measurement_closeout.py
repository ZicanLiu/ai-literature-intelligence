"""Directory migration and formal first-look verification regressions."""
from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import build_downstream_evidence_registry as build_cli
from app import run_downstream_measurement_audit as audit_cli
from src.downstream_measurement.canonical import build_canonical
from src.downstream_measurement.dag import DagContext
from src.downstream_measurement.figures import REQUIRED_FIGURES
from src.downstream_measurement.first_look import assess_frozen_comparison, reproduce_first_look
from src.downstream_measurement.inventory import (
    PACKAGE_ROLE_TABLE, build_inventory, discover_packages, package_directory_names,
    resolve_package_directories, resolve_package_directory,
)
from src.downstream_measurement.util import sha256_file
from tests.automated.test_downstream_measurement import MiniEvidenceRoot


def frozen_csv():
    # Independently specified expectations for MiniEvidenceRoot's fixed units.
    return (
        "judge,n_cells,BM25_mean_U,MCA_mean_U,Delta_U,BM25_mean_E,MCA_mean_E,Delta_E,U_direction,E_direction\n"
        "GPT,4,1,2,1,1,0,-1,MCA_HIGHER,MCA_LOWER\n"
        "DeepSeek,4,2,2,0,0,0,0,EQUAL,EQUAL\n"
        "GLM,4,2,2,0,0,0,0,EQUAL,EQUAL\n"
    )


def without_column(text, column):
    reader = csv.DictReader(io.StringIO(text))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=[f for f in reader.fieldnames if f != column],
                            extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(reader)
    return out.getvalue()


class TestDirectoryMigration(unittest.TestCase):
    def test_lowercase_migration_preserves_canonical_identity_and_source_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mini = MiniEvidenceRoot(tmp / "legacy")
            before = build_canonical(mini.root, None).to_dict()
            old_dirs = resolve_package_directories(mini.root)
            before_bytes = {f"{pid}/{p.relative_to(mini.root / name).as_posix()}": sha256_file(p)
                            for pid, name in old_dirs.items() for p in (mini.root / name).rglob("*")
                            if p.is_file()}
            migrated = tmp / "migrated"
            migrated.mkdir()
            for directory in mini.root.iterdir():
                directory.rename(migrated / directory.name.lower())
            self.assertEqual(build_canonical(migrated, None).to_dict(), before)
            self.assertEqual(audit_cli._verify_registry_matches_evidence(before, migrated), [])
            self.assertEqual(audit_cli._verify_registry_matches_reconstruction(before, migrated, None), [])
            new_dirs = resolve_package_directories(migrated)
            after_bytes = {f"{pid}/{p.relative_to(migrated / name).as_posix()}": sha256_file(p)
                           for pid, name in new_dirs.items() for p in (migrated / name).rglob("*")
                           if p.is_file()}
            self.assertEqual(before_bytes, after_bytes)
            rows, unknown = discover_packages(migrated)
            self.assertEqual(unknown, [])
            self.assertTrue(all(row["directory"] == row["canonical_directory"] for row in rows))

    def test_legacy_restore_is_recognized_without_unknown_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            rows, unknown = discover_packages(mini.root)
            self.assertEqual(unknown, [])
            prep = next(row for row in rows if row["package_id"] == "experiment_prep")
            self.assertTrue(prep["present"])
            self.assertEqual(prep["directory"], mini.prep.name)
            self.assertEqual(prep["canonical_directory"], mini.prep.name.lower())
            self.assertIn(mini.prep.name, prep["legacy_directory_names"])

    def test_all_package_ids_unique_and_canonical_names_lowercase(self):
        ids = [meta["package_id"] for meta in PACKAGE_ROLE_TABLE.values()]
        self.assertEqual(len(ids), len(set(ids)))
        for name, meta in PACKAGE_ROLE_TABLE.items():
            self.assertEqual(name, name.lower())
            self.assertEqual(name, meta["canonical_directory"])

    def test_two_present_aliases_fail_closed_on_every_platform(self):
        names = package_directory_names("experiment_prep")
        # Simulate a case-sensitive directory listing even when running on NTFS.
        entries = [SimpleNamespace(name=name, is_dir=lambda: True) for name in names]
        with patch.object(Path, "iterdir", return_value=iter(entries)):
            with self.assertRaisesRegex(ValueError, "ambiguous package directories"):
                resolve_package_directory(Path("fixture"), "experiment_prep")

    def test_frozen_legacy_dag_anchor_survives_canonical_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = package_directory_names("experiment_prep")
            package = root / names[0]
            package.mkdir()
            manifest = package / "SHA256_manifest.txt"
            manifest.write_text("synthetic anchor\n", encoding="utf-8")
            ctx = DagContext(root, {"experiment_prep": names[0]}, None, [])
            binding = {"sha256": sha256_file(manifest), "path_hints": [names[1]]}
            self.assertEqual(ctx.strict_path_hint_matches("experiment_prep", [binding]), (0, 1))

    def test_actual_alias_collision_on_case_sensitive_filesystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical, legacy = package_directory_names("experiment_prep")
            (root / canonical).mkdir()
            try:
                (root / legacy).mkdir()
            except FileExistsError:
                self.skipTest("filesystem cannot represent both case-distinct aliases")
            with self.assertRaisesRegex(ValueError, "ambiguous package directories"):
                discover_packages(root)

    def test_explicit_supplement_does_not_hide_unknown_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            container = mini.root / "srtp_meeting_latest_supplement_20260919"
            container.mkdir()
            supplement = container / "SRTP_MEETING_LATEST_SUPPLEMENT_20260919.zip"
            mini.write_supplement_zip(supplement)
            (mini.root / "unexpected_evidence").mkdir()
            self.assertEqual(build_inventory(mini.root, supplement)["unknown_top_level_directories"],
                             ["unexpected_evidence"])
            self.assertIn(container.name, build_inventory(mini.root, None)["unknown_top_level_directories"])


class TestStagingProtection(unittest.TestCase):
    def test_cli_staging_collision_cannot_erase_evidence(self):
        for cli in (build_cli, audit_cli):
            with self.subTest(cli=cli.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                evidence = root / "output.staging"
                evidence.mkdir()
                source = evidence / "frozen.txt"
                source.write_bytes(b"synthetic frozen evidence")
                before = sha256_file(source)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = cli.main(["--evidence-root", str(evidence), "--output-dir", str(root / "output")])
                self.assertNotEqual(code, 0)
                self.assertEqual(sha256_file(source), before)
                self.assertEqual(list(evidence.iterdir()), [source])


class TestFormalVerificationCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mini = MiniEvidenceRoot(self.root / "evidence")
        self.registry_dir = self.root / "registry"
        self.audit_dir = self.root / "audit"
        self.frozen = (resolve_package_directory(self.mini.root, "unblinded_analysis")
                       / "results" / "JUDGE_PRIMARY_MACRO_RESULTS.csv")
        self.frozen.parent.mkdir(parents=True)
        self.frozen.write_text(frozen_csv(), encoding="utf-8")

    def write_fixture_manifest(self):
        # Only the synthetic starting fixture is frozen here. Mutation callbacks
        # run AFTER registry construction and never refresh that registry anchor.
        if self.frozen.is_file():
            (self.frozen.parent.parent / "SHA256_manifest.txt").write_text(
                f"{sha256_file(self.frozen)}  results/JUDGE_PRIMARY_MACRO_RESULTS.csv\n", encoding="utf-8")

    def run_cli(self, formal=True, before_audit=None):
        self.write_fixture_manifest()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build_cli.main(["--evidence-root", str(self.mini.root),
                                             "--output-dir", str(self.registry_dir)]), 0)
            if before_audit:
                before_audit()
            args = ["--evidence-root", str(self.mini.root), "--registry-dir", str(self.registry_dir),
                    "--output-dir", str(self.audit_dir)]
            if formal:
                args.append("--formal-verification")
            # Rendering already has a real integration test; focus on publication/exit semantics.
            with patch.object(audit_cli, "render_all", return_value={"written": list(REQUIRED_FIGURES),
                                                                   "failed": []}) as render:
                code = audit_cli.main(args)
        return code, render.called

    def assert_failed(self, status, before_audit=None):
        code, rendered = self.run_cli(before_audit=before_audit)
        self.assertNotEqual(code, 0)
        self.assertFalse(rendered)
        self.assertFalse(self.audit_dir.exists())
        staging = self.audit_dir.with_name("audit.staging")
        self.assertTrue((staging / "_PARTIAL_FAILED.txt").is_file())
        self.assertFalse((staging / "manifest.json").exists())
        result = json.loads((staging / "first_look/comparison_vs_frozen_first_look.json").read_text())
        self.assertEqual(result["status"], status)
        self.assertEqual(result["mode"], "formal_verification")
        return result

    def test_complete_match_publishes_and_exits_zero(self):
        code, rendered = self.run_cli()
        self.assertEqual(code, 0)
        self.assertTrue(rendered)
        result = json.loads((self.audit_dir / "first_look/comparison_vs_frozen_first_look.json").read_text())
        self.assertEqual((result["status"], result["fields_compared"]), ("MATCH", 28))
        manifest = json.loads((self.audit_dir / "manifest.json").read_text())
        self.assertEqual(manifest["analysis_config"]["verification_mode"], "formal_verification")
        source = manifest["analysis_config"]["first_look_source"]
        self.assertEqual(source["status"], "VERIFIED_BYTES")
        self.assertEqual(source["actual_sha256"], sha256_file(self.frozen))
        self.assertEqual(source["actual_sha256"], source["expected_sha256"])

    def test_mismatch_fails_without_publishing(self):
        self.frozen.write_text(frozen_csv().replace("GPT,4,1,2,1,", "GPT,4,9,2,1,"), encoding="utf-8")
        self.assert_failed("MISMATCH")

    def test_missing_frozen_source_fails(self):
        self.frozen.unlink()
        self.assert_failed("MISSING_SOURCE")

    def test_missing_semantic_column_fails(self):
        self.frozen.write_text(without_column(frozen_csv(), "BM25_mean_E"), encoding="utf-8")
        self.assert_failed("INCOMPLETE")

    def test_missing_structural_column_fails(self):
        self.frozen.write_text(without_column(frozen_csv(), "n_cells"), encoding="utf-8")
        self.assert_failed("INCOMPLETE")

    def test_blank_field_fails(self):
        self.frozen.write_text(frozen_csv().replace("GPT,4,1,2,1,", "GPT,4,,2,1,"), encoding="utf-8")
        self.assert_failed("INCOMPLETE")

    def test_missing_judge_fails(self):
        self.frozen.write_text("\n".join(frozen_csv().splitlines()[:-1]) + "\n", encoding="utf-8")
        self.assert_failed("INCOMPLETE")

    def test_duplicate_judge_fails(self):
        self.frozen.write_text(frozen_csv() + frozen_csv().splitlines()[1] + "\n", encoding="utf-8")
        self.assert_failed("INCOMPLETE")

    def test_diagnostic_missing_source_continues_with_explicit_status(self):
        self.frozen.unlink()
        code, rendered = self.run_cli(formal=False)
        self.assertEqual(code, 0)
        self.assertTrue(rendered)
        config = json.loads((self.audit_dir / "manifest.json").read_text())["analysis_config"]
        self.assertEqual(config["verification_mode"], "diagnostic")
        self.assertEqual(config["first_look_comparison_status"], "MISSING_SOURCE")

    def test_diagnostic_mismatch_continues_with_explicit_status(self):
        self.frozen.write_text(frozen_csv().replace("GPT,4,1,2,1,", "GPT,4,9,2,1,"), encoding="utf-8")
        code, _ = self.run_cli(formal=False)
        self.assertEqual(code, 0)
        config = json.loads((self.audit_dir / "manifest.json").read_text())["analysis_config"]
        self.assertEqual(config["first_look_comparison_status"], "MISMATCH")

    def test_incomplete_reproduction_roster_cannot_pass(self):
        reproduction = reproduce_first_look(build_canonical(self.mini.root, None).to_dict())
        del reproduction["primary"]["GLM"]
        self.assertEqual(assess_frozen_comparison(reproduction, frozen_csv())["status"], "INCOMPLETE")

    def test_duplicate_header_cannot_pass(self):
        text = frozen_csv().replace("judge,n_cells,", "judge,n_cells,n_cells,")
        reproduction = reproduce_first_look(build_canonical(self.mini.root, None).to_dict())
        self.assertNotEqual(assess_frozen_comparison(reproduction, text)["status"], "MATCH")

    def test_malformed_csv_cannot_match(self):
        reproduction = reproduce_first_look(build_canonical(self.mini.root, None).to_dict())
        good = frozen_csv()
        cases = {
            "extra cell": good.replace("MCA_LOWER\n", "MCA_LOWER,unexpected\n"),
            "short row": good.replace(",MCA_LOWER\n", "\n"),
            "unclosed quote": good.replace("GLM,4,2,2,0,0,0,0,EQUAL,EQUAL\n",
                                          'GLM,4,2,2,0,0,0,0,EQUAL,"EQUAL'),
            "whitespace field": good.replace("GPT,4,1,2,1,", "GPT,4, ,2,1,"),
            "non-numeric": good.replace("GPT,4,1,2,1,", "GPT,4,invalid,2,1,"),
            "nan": good.replace("GPT,4,1,2,1,", "GPT,4,NaN,2,1,"),
            "infinity": good.replace("GPT,4,1,2,1,", "GPT,4,1e999,2,1,"),
            "non-finite structure": good.replace("GPT,4,", "GPT,NaN,"),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                self.assertEqual(assess_frozen_comparison(reproduction, text)["status"], "INCOMPLETE")

    def test_numeric_tolerance_stays_at_one_trillionth(self):
        reproduction = reproduce_first_look(build_canonical(self.mini.root, None).to_dict())
        for value, expected in (("1.0000000000005", "MATCH"), ("1.000000000002", "MISMATCH")):
            with self.subTest(value=value):
                text = frozen_csv().replace("GPT,4,1,2,1,", f"GPT,4,{value},2,1,")
                self.assertEqual(assess_frozen_comparison(reproduction, text)["status"], expected)

    def test_malformed_csv_formal_cli_preserves_partial(self):
        self.frozen.write_text(frozen_csv().replace("MCA_LOWER\n", "MCA_LOWER,unexpected\n"), encoding="utf-8")
        self.assert_failed("INCOMPLETE")

    def test_diagnostic_short_row_continues(self):
        self.frozen.write_text(frozen_csv().replace(",MCA_LOWER\n", "\n"), encoding="utf-8")
        code, rendered = self.run_cli(formal=False)
        self.assertEqual(code, 0)
        self.assertTrue(rendered)
        config = json.loads((self.audit_dir / "manifest.json").read_text())["analysis_config"]
        self.assertEqual(config["first_look_comparison_status"], "INCOMPLETE")

    def test_stale_frozen_csv_bytes_fail_even_when_values_match(self):
        result = self.assert_failed("SOURCE_MISMATCH", before_audit=lambda: self.frozen.write_text(
            frozen_csv() + "\n", encoding="utf-8"))
        self.assertEqual(result["value_comparison_status"], "MATCH")

    def test_rehashed_frozen_package_cannot_replace_registry_anchor(self):
        def mutate():
            self.frozen.write_text(frozen_csv() + "\n", encoding="utf-8")
            self.write_fixture_manifest()
        result = self.assert_failed("SOURCE_MISMATCH", before_audit=mutate)
        source = result["source_verification"]
        self.assertNotEqual(source["manifest_sha256"], source["registered_manifest_sha256"])

    def test_missing_frozen_manifest_fails(self):
        self.assert_failed("UNVERIFIED_SOURCE", before_audit=lambda:
                           (self.frozen.parent.parent / "SHA256_manifest.txt").unlink())

    def test_missing_registry_source_anchor_fails(self):
        def mutate():
            path = self.registry_dir / "integrity/integrity_summary.json"
            summary = json.loads(path.read_text(encoding="utf-8"))
            summary["packages"]["unblinded_analysis"]["manifest_sha256"] = None
            path.write_text(json.dumps(summary), encoding="utf-8")
        self.assert_failed("UNVERIFIED_SOURCE", before_audit=mutate)

    def test_diagnostic_source_drift_is_explicit(self):
        code, _ = self.run_cli(formal=False, before_audit=lambda: self.frozen.write_text(
            frozen_csv() + "\n", encoding="utf-8"))
        self.assertEqual(code, 0)
        config = json.loads((self.audit_dir / "manifest.json").read_text())["analysis_config"]
        self.assertEqual(config["verification_mode"], "diagnostic")
        self.assertEqual(config["first_look_comparison_status"], "SOURCE_MISMATCH")
        self.assertEqual(config["first_look_source"]["status"], "SOURCE_MISMATCH")

    def test_retry_cannot_erase_failed_staging(self):
        self.frozen.write_text(frozen_csv().replace("GPT,4,1,2,1,", "GPT,4,9,2,1,"), encoding="utf-8")
        self.assert_failed("MISMATCH")
        staging = self.audit_dir.with_name("audit.staging")
        before = {p.relative_to(staging): sha256_file(p) for p in staging.rglob("*") if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = audit_cli.main(["--evidence-root", str(self.mini.root), "--registry-dir", str(self.registry_dir),
                                   "--output-dir", str(self.audit_dir), "--formal-verification"])
        self.assertNotEqual(code, 0)
        self.assertEqual(before, {p.relative_to(staging): sha256_file(p)
                                  for p in staging.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
