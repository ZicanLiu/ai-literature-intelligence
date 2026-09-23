"""Fail-closed boundaries and invocation-local source reuse regressions."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from app.build_downstream_evidence_registry import main as build_main
from app.run_downstream_measurement_audit import main as audit_main
from src.downstream_measurement import canonical
from src.downstream_measurement.integrity import (
    build_integrity, load_integrity_summary, parse_sha_manifest,
    persist_integrity, verify_package,
)
from src.downstream_measurement.util import sha256_file
from src.downstream_measurement.inventory import resolve_package_directory
from tests.automated.test_downstream_measurement import MiniEvidenceRoot
from tests.automated.test_downstream_measurement_closeout import frozen_csv


class ManifestBoundaries(unittest.TestCase):
    def test_normalized_path_aliases_fail_with_same_or_different_digests(self):
        aliases = ("./sub/file", "sub//file", "sub/./file", "sub/../sub/file")
        if os.name == "nt":
            aliases += ("SUB/FILE",)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "SHA256_manifest.txt"
            for alias in aliases:
                for digest in ("a" * 64, "b" * 64):
                    with self.subTest(alias=alias, digest=digest):
                        manifest.write_text(f"{'a' * 64}  sub/file\n{digest}  {alias}\n")
                        with self.assertRaisesRegex(ValueError, "duplicate relative path"):
                            parse_sha_manifest(manifest)

    def test_manifest_paths_must_be_package_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "SHA256_manifest.txt"
            for name in ("/file", "C:/file", "C:file", "//server/share/file",
                         "../file", "sub/../../file", ".", "sub/.."):
                with self.subTest(name=name):
                    manifest.write_text(f"{'a' * 64}  {name}\n")
                    with self.assertRaisesRegex(ValueError, "package-relative"):
                        parse_sha_manifest(manifest)

    def test_legacy_digest_forms_and_relative_spelling_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "SHA256_manifest.txt"
            manifest.write_bytes(("\ufeff# historical format\r\n  " + "A" * 64
                                  + "\t ./sub\\file  \r\n").encode("utf-8"))
            self.assertEqual(parse_sha_manifest(manifest), {"./sub/file": "a" * 64})
            if os.name != "nt":
                manifest.write_text(f"{'a' * 64}  file\n{'b' * 64}  FILE\n")
                self.assertEqual(len(parse_sha_manifest(manifest)), 2)

    def test_registry_cli_rejects_aliased_manifest_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mini = MiniEvidenceRoot(tmp / "evidence")
            package = resolve_package_directory(mini.root, "generator_freeze_v2")
            manifest = package / "SHA256_manifest.txt"
            original = manifest.read_text(encoding="utf-8")
            digest, name = original.splitlines()[0].split(None, 1)
            manifest.write_text(original + f"{digest}  ./{name}\n", encoding="utf-8")
            output = tmp / "registry"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = build_main(["--evidence-root", str(mini.root), "--output-dir", str(output)])
            self.assertNotEqual(code, 0)
            self.assertFalse(output.exists())
            marker = tmp / "registry.staging/_PARTIAL_FAILED.txt"
            self.assertIn("duplicate relative path", marker.read_text(encoding="utf-8"))

    def test_duplicate_paths_fail_even_with_matching_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "SHA256_manifest.txt"
            for digest in ("a" * 64, "b" * 64):
                for second_path in ("sub/file", "sub\\file"):
                    with self.subTest(digest=digest, second_path=second_path):
                        manifest.write_text(f"{'a' * 64}  sub/file\n{digest}  {second_path}\n")
                        with self.assertRaisesRegex(ValueError, "duplicate relative path"):
                            parse_sha_manifest(manifest)

    def test_malformed_and_empty_manifests_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "SHA256_manifest.txt"
            for text in ("", "# no entries\n", "a" * 64, "abc file", "g" * 64 + " file"):
                with self.subTest(text=text):
                    manifest.write_text(text)
                    with self.assertRaises(ValueError):
                        parse_sha_manifest(manifest)

    def test_required_package_and_manifest_are_counted_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            for directory_exists in (False, True):
                if directory_exists:
                    package.mkdir()
                with self.subTest(directory_exists=directory_exists):
                    result = build_integrity(root, {"required": "package"}, None, {"required"})
                    self.assertTrue(result["fail_closed"])
                    self.assertEqual(result["counts"]["formal_chain_missing"], 1)
                    self.assertEqual(result["counts"]["missing_source_bytes"], 1)
                    self.assertEqual(result["counts"]["packages_manifest_verified"], 0)
                    self.assertIn("manifest" if directory_exists else "package",
                                  result["rows"][0]["source_of_expected_hash"])
            undeclared = build_integrity(root, {}, None, {"required"})
            self.assertTrue(undeclared["fail_closed"])
            self.assertEqual(undeclared["counts"]["formal_chain_missing"], 1)
            self.assertEqual(verify_package(package, "required")["summary"]["missing"], 1)

    def test_checked_and_verified_counts_preserve_legacy_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("good", "bad", "unanchored"):
                (root / name).mkdir()
            for name in ("good", "bad"):
                path = root / name / "file"
                path.write_bytes(b"source")
                digest = sha256_file(path) if name == "good" else "0" * 64
                (path.parent / "SHA256_manifest.txt").write_text(f"{digest}  file\n")
            result = build_integrity(root, {n: n for n in ("good", "bad", "unanchored")}, None, {"good"})
            self.assertFalse(result["fail_closed"])
            self.assertEqual(result["counts"]["packages_checked"], 3)
            self.assertEqual(result["counts"]["packages_verified"], 3)
            self.assertEqual(result["counts"]["packages_manifest_verified"], 1)
            persist_integrity(result, root / "derived")
            loaded = load_integrity_summary(root / "derived/integrity/integrity_summary.json")
            self.assertEqual(loaded["counts"], result["counts"])

    def test_registry_cli_never_publishes_missing_required_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()
            output = Path(tmp) / "registry"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = build_main(["--evidence-root", str(root), "--output-dir", str(output)])
            self.assertNotEqual(code, 0)
            self.assertFalse(output.exists())
            summary = load_integrity_summary(Path(str(output) + ".staging") / "integrity/integrity_summary.json")
            self.assertTrue(summary["fail_closed"])
            self.assertGreater(summary["counts"]["formal_chain_missing"], 0)

    def test_formal_audit_rechecks_required_chain_after_registry_build(self):
        for missing in ("package", "manifest"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                mini = MiniEvidenceRoot(tmp / "evidence")
                frozen_package = resolve_package_directory(mini.root, "unblinded_analysis")
                frozen = frozen_package / "results/JUDGE_PRIMARY_MACRO_RESULTS.csv"
                frozen.parent.mkdir()
                frozen.write_text(frozen_csv(), encoding="utf-8")
                (frozen_package / "SHA256_manifest.txt").write_text(
                    f"{sha256_file(frozen)}  results/JUDGE_PRIMARY_MACRO_RESULTS.csv\n")
                registry, audit = tmp / "registry", tmp / "audit"
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(build_main(["--evidence-root", str(mini.root),
                                                 "--output-dir", str(registry)]), 0)
                    package = resolve_package_directory(mini.root, "generator_freeze_v2")
                    if missing == "package":
                        package.rename(tmp / "removed_package")
                    else:
                        (package / "SHA256_manifest.txt").unlink()
                    code = audit_main(["--evidence-root", str(mini.root), "--registry-dir", str(registry),
                                       "--output-dir", str(audit), "--formal-verification"])
                self.assertNotEqual(code, 0)
                self.assertFalse(audit.exists())
                comparison = json.loads((tmp / "audit.staging/first_look/comparison_vs_frozen_first_look.json").read_bytes())
                self.assertEqual(comparison["value_comparison_status"], "MATCH")
                self.assertEqual(comparison["status"], "FORMAL_CHAIN_INVALID")
                self.assertEqual(comparison["formal_chain_verification"]["formal_chain_missing"], 1)


class CanonicalSourceBoundaries(unittest.TestCase):
    def test_only_explicit_boolean_forms_are_accepted(self):
        for value, expected in ((True, True), (False, False), ("true", True), ("False", False),
                                (" TRUE ", True), (" false ", False)):
            self.assertIs(canonical._as_bool(value), expected)
        for value in ("not_a_boolean", "", "yes", "no", "1", "0", 1, 0, None, [], {}):
            with self.subTest(value=value), self.assertRaises(canonical.CanonicalBuildError):
                canonical._as_bool(value)

    def test_invalid_atomic_fails_primary_and_sensitivity_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp) / "evidence")
            key = next(iter(mini.judgement_specs))
            mini.judgement_specs[key]["claim_units"][0]["atomic"] = "not_a_boolean"
            mini._write_judgements()
            with self.assertRaisesRegex(canonical.CanonicalBuildError, "non-boolean"):
                canonical.build_canonical(mini.root, None)
            mini.judgement_specs[key]["claim_units"][0]["atomic"] = True
            mini._write_judgements()
            supplement = Path(tmp) / "supplement.zip"
            mini.write_supplement_zip(supplement, atomic_override="not_a_boolean")
            with self.assertRaisesRegex(canonical.CanonicalBuildError, "non-boolean"):
                canonical.build_canonical(mini.root, supplement)

    def test_each_json_source_is_read_and_hashed_once_per_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            sources = {p: p.read_bytes() for p in mini.root.rglob("*.json")}
            reads, hashes = Counter(), Counter()
            read_bytes, sha_bytes = Path.read_bytes, canonical.sha256_bytes

            def read(path):
                reads[path] += 1
                return read_bytes(path)

            def digest(raw):
                hashes[raw] += 1
                return sha_bytes(raw)

            with patch.object(Path, "read_bytes", read), patch.object(canonical, "sha256_bytes", digest):
                registry = canonical.build_canonical(mini.root, None)
            for path, raw in sources.items():
                self.assertEqual(reads[path], 1, str(path.relative_to(mini.root)))
                self.assertEqual(hashes[raw], 1, str(path.relative_to(mini.root)))
            for row in registry.evaluations + registry.claim_judgements + registry.error_events:
                source = mini.root / f"DOWNSTREAM_AI_EVAL_{row['evaluator'].upper()}_20260915" / "judgements" / (row["output_id"] + ".json")
                self.assertEqual(row.get("judgement_file_sha256", row.get("source_file_sha256")), sha256_file(source))

    def test_next_build_reads_current_bytes_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = MiniEvidenceRoot(Path(tmp))
            before = canonical.build_canonical(mini.root, None)
            key = next(iter(mini.judgement_specs))
            value = mini.judgement_specs[key]["claim_units"][0]["atomic"]
            mini.judgement_specs[key]["claim_units"][0]["atomic"] = not value
            mini._write_judgements()
            after = canonical.build_canonical(mini.root, None)
            self.assertNotEqual(before.evaluations, after.evaluations)
            self.assertNotEqual(before.claim_judgements, after.claim_judgements)
            source = next((mini.formal / "public_blinded_outputs").glob("*/generator_output.json"))
            source.write_bytes(source.read_bytes() + b" ")
            with self.assertRaisesRegex(canonical.CanonicalBuildError, "byte hash drift"):
                canonical.build_canonical(mini.root, None)
