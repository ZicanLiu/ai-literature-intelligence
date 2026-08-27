"""Public-entry regression tests for the W6 Quality Gate."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.w6_quality_gate as gate_cli
from src.annotation_tasks import sha256_file
from src.w6_contracts import compute_benchmark_identity, compute_pool_identity
from src.w6_method_contract import compute_method_configuration_hash
from src.w6_quality_gate import GATE_NAME


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALID_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid"
INVALID_RECIPES_PATH = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_bootstrap"
    / "invalid"
    / "invalid_cases.json"
)
INVALID_RECIPES = {
    case["case_id"]: case
    for case in json.loads(INVALID_RECIPES_PATH.read_text(encoding="utf-8"))["cases"]
}


def _resolve_mutation_parent(payload, path):
    current = payload
    for part in path[:-1]:
        current = current[part]
    return current, path[-1]


def _apply_recipe(payload: dict, recipe: dict) -> None:
    operation = recipe["operation"]
    if operation == "set":
        parent, key = _resolve_mutation_parent(payload, recipe["path"])
        parent[key] = copy.deepcopy(recipe["value"])
    elif operation == "delete":
        parent, key = _resolve_mutation_parent(payload, recipe["path"])
        del parent[key]
    elif operation == "append":
        parent, key = _resolve_mutation_parent(payload, recipe["path"])
        parent[key].append(copy.deepcopy(recipe["value"]))
    elif operation == "append_copy":
        parent, key = _resolve_mutation_parent(payload, recipe["path"])
        source_parent, source_key = _resolve_mutation_parent(
            payload, recipe["copy_from"]
        )
        parent[key].append(copy.deepcopy(source_parent[source_key]))
    elif operation == "set_many":
        for change in recipe["changes"]:
            parent, key = _resolve_mutation_parent(payload, change["path"])
            parent[key] = copy.deepcopy(change["value"])
    else:
        raise AssertionError(f"unknown invalid mutation operation: {operation}")


class FixtureWorkspace:
    """A disposable copy of the frozen valid fixture."""

    def __init__(self, root: Path):
        self.root = root
        shutil.copytree(VALID_ROOT, self.root)
        self.manifest_path = self.root / "bundle_manifest.json"

    def load_manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict) -> None:
        self._write_json(self.manifest_path, manifest)

    def artifact_path(self, artifact_name: str) -> Path:
        manifest = self.load_manifest()
        return self.root / manifest["artifacts"][artifact_name]["path"]

    def mutate_artifact(self, artifact_name: str, mutation, *, rehash: bool = True) -> None:
        path = self.artifact_path(artifact_name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutation(payload)
        self._write_json(path, payload)
        if rehash:
            manifest = self.load_manifest()
            manifest["artifacts"][artifact_name]["sha256"] = sha256_file(path)
            self.write_manifest(manifest)

    def apply_invalid_recipe(self, case_id: str) -> None:
        recipe = INVALID_RECIPES[case_id]
        if recipe["base"] == "bundle_manifest.json":
            manifest = self.load_manifest()
            _apply_recipe(manifest, recipe)
            self.write_manifest(manifest)
            return
        manifest = self.load_manifest()
        artifact_name = next(
            name
            for name, reference in manifest["artifacts"].items()
            if reference["path"] == recipe["base"]
        )
        self.mutate_artifact(
            artifact_name, lambda payload: _apply_recipe(payload, recipe)
        )

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


class W6QualityGateCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.fixture_index = 0

    def new_fixture(self) -> FixtureWorkspace:
        self.fixture_index += 1
        return FixtureWorkspace(self.root / f"fixture_{self.fixture_index}")

    def run_cli(
        self,
        manifest: Path,
        *,
        mode: str = "full",
        output: Path | None = None,
        ascii_console: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], dict, bytes]:
        output_path = output or (self.root / f"report_{self.fixture_index}.json")
        environment = os.environ.copy()
        environment.pop("PYTHONUTF8", None)
        environment.pop("PYTHONIOENCODING", None)
        if ascii_console:
            environment["PYTHONIOENCODING"] = "ascii"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.w6_quality_gate",
                "--manifest",
                str(manifest),
                "--mode",
                mode,
                "--output",
                str(output_path),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertTrue(
            output_path.is_file(),
            f"report missing; stdout={completed.stdout!r}, stderr={completed.stderr!r}",
        )
        report_bytes = output_path.read_bytes()
        return completed, json.loads(report_bytes), report_bytes

    def assert_gate_failure(
        self,
        fixture: FixtureWorkspace,
        *,
        mode: str,
        expected_check: str,
        ascii_console: bool = False,
    ) -> dict:
        completed, report, _ = self.run_cli(
            fixture.manifest_path,
            mode=mode,
            ascii_console=ascii_console,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(report["result"], "FAIL")
        self.assertIn(expected_check, report["failed_checks"])
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertEqual(report["summary"]["error_count"], 1)
        return report

    def test_valid_full_bundle_passes_from_cli(self) -> None:
        completed, report, _ = self.run_cli(
            VALID_ROOT / "bundle_manifest.json", mode="full"
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["mode"], "full")
        self.assertEqual(report["summary"]["artifact_count"], 19)
        self.assertEqual(report["summary"]["file_count"], 23)
        self.assertEqual(report["failed_checks"], [])
        self.assertEqual(
            set(report),
            {
                "schema_version",
                "gate",
                "mode",
                "result",
                "input",
                "inventory",
                "checks",
                "summary",
                "errors",
                "warnings",
                "failed_checks",
            },
        )
        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["gate"], GATE_NAME)
        self.assertEqual(
            report["input"]["sha256"],
            sha256_file(VALID_ROOT / "bundle_manifest.json"),
        )

    def test_basic_and_full_are_distinct_stages(self) -> None:
        basic_result, basic, _ = self.run_cli(
            VALID_ROOT / "bundle_manifest.json",
            mode="basic",
            output=self.root / "basic.json",
        )
        full_result, full, _ = self.run_cli(
            VALID_ROOT / "bundle_manifest.json",
            mode="full",
            output=self.root / "full.json",
        )
        self.assertEqual((basic_result.returncode, full_result.returncode), (0, 0))
        self.assertEqual(basic["summary"]["check_count"], 12)
        self.assertEqual(full["summary"]["check_count"], 13)
        self.assertEqual(basic["summary"]["file_count"], 20)
        self.assertEqual(full["summary"]["file_count"], 23)
        self.assertNotIn("full_bundle_contract", [row["name"] for row in basic["checks"]])
        self.assertIn("full_bundle_contract", [row["name"] for row in full["checks"]])

    def test_report_is_byte_deterministic(self) -> None:
        output = self.root / "deterministic.json"
        first_result, first_report, first_bytes = self.run_cli(
            VALID_ROOT / "bundle_manifest.json", mode="full", output=output
        )
        second_result, second_report, second_bytes = self.run_cli(
            VALID_ROOT / "bundle_manifest.json", mode="full", output=output
        )
        self.assertEqual((first_result.returncode, second_result.returncode), (0, 0))
        self.assertEqual(first_report, second_report)
        self.assertEqual(first_bytes, second_bytes)

    def test_missing_artifact_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.artifact_path("topic_set").unlink()
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="bundle_inventory"
        )

    def test_malformed_manifest_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.manifest_path.write_text("{not-json}\n", encoding="utf-8")
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="bundle_inventory"
        )

    def test_hash_drift_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.mutate_artifact(
            "topic_set",
            lambda payload: payload["topics"][0].__setitem__("scientific_object", "tampered"),
            rehash=False,
        )
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="bundle_inventory"
        )

    def test_sibling_dependency_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        manifest = fixture.load_manifest()
        manifest["parallel_development"]["quality_gate"]["depends_on"] = [
            "unmerged_sibling"
        ]
        fixture.write_manifest(manifest)
        self.assert_gate_failure(
            fixture,
            mode="basic",
            expected_check="quality_gate_dependency_closure",
        )

    def test_dev_hidden_overlap_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.apply_invalid_recipe("split_overlap")
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="topic_split_leakage"
        )

    def test_blind_view_leakage_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.apply_invalid_recipe("blind_task_score_leak")
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="blind_annotation_view"
        )

    def test_hidden_label_repository_path_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.mutate_artifact(
            "hidden_label_anchor",
            lambda payload: payload["storage"].__setitem__(
                "repository_path", "data/hidden_labels.json"
            ),
        )
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="hidden_label_seal"
        )

    def test_hidden_labels_as_method_input_fail_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.apply_invalid_recipe("method_hidden_generation_input")
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_method_input_hash_drift_fails_from_cli(self) -> None:
        fixture = self.new_fixture()

        def mutate(payload: dict) -> None:
            payload["method_inputs"][0]["ranking_sha256"] = "0" * 64
            payload["freeze"]["configuration_sha256"] = compute_method_configuration_hash(
                payload
            )

        fixture.mutate_artifact("method_fusion_manifest", mutate)
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_fusion_weight_roster_mismatch_fails_from_cli(self) -> None:
        fixture = self.new_fixture()

        def mutate(payload: dict) -> None:
            del payload["method"]["parameters"]["weights"]["w6_fixture_dense_v1"]
            payload["freeze"]["configuration_sha256"] = compute_method_configuration_hash(
                payload
            )

        fixture.mutate_artifact("method_fusion_manifest", mutate)
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_pool_provenance_loss_fails_from_cli(self) -> None:
        fixture = self.new_fixture()

        def mutate(payload: dict) -> None:
            payload["members"][0]["retrieval_hit_ids"] = ["hit_doa_001"]
            payload["members"][0]["source_system_membership"] = ["openalex_native"]
            payload["pool_identity"] = compute_pool_identity(payload)

        fixture.mutate_artifact("candidate_pool", mutate)
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="candidate_pool_closure"
        )

    def test_dangling_synthesis_evidence_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.apply_invalid_recipe("synthesis_dangling_evidence")
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_unselected_synthesis_paper_fails_from_cli(self) -> None:
        fixture = self.new_fixture()

        def mutate(payload: dict) -> None:
            payload["claims"][0]["supporting_canonical_entity_ids"] = ["entity_007"]
            payload["claims"][0]["evidence_refs"] = ["evidence_007"]

        fixture.mutate_artifact("structured_synthesis", mutate)
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_benchmark_approved_self_report_fails_from_cli(self) -> None:
        fixture = self.new_fixture()

        def mutate(payload: dict) -> None:
            payload["review_provenance"] = {
                "status": "approved",
                "reviewers": ["fixture_self_approver"],
                "note": "Deliberately invalid self-approval.",
            }
            payload["benchmark_identity"] = compute_benchmark_identity(payload)

        fixture.mutate_artifact("benchmark_manifest", mutate)
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_revealed_hidden_split_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.mutate_artifact(
            "split_manifest",
            lambda payload: payload.__setitem__("reveal_state", "revealed"),
        )
        self.assert_gate_failure(
            fixture, mode="basic", expected_check="topic_split_leakage"
        )

    def test_annotation_contract_failures_are_gated_from_cli(self) -> None:
        mutations = {
            "illegal_label": lambda payload: payload["annotations"][0].__setitem__(
                "relevance_label", 7
            ),
            "missing_evidence": lambda payload: payload["annotations"][0].__setitem__(
                "evidence_sources", []
            ),
            "missing_confidence": lambda payload: payload["annotations"][0].pop(
                "confidence"
            ),
            "missing_model_tool_provenance": lambda payload: payload["annotations"][
                0
            ]["annotation_provenance"].pop("model_or_tool"),
        }
        for case_name, mutation in mutations.items():
            with self.subTest(case=case_name):
                fixture = self.new_fixture()
                fixture.mutate_artifact("annotation_results", mutation)
                self.assert_gate_failure(
                    fixture, mode="full", expected_check="full_bundle_contract"
                )

    def test_review_identity_mismatch_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.apply_invalid_recipe("review_unknown_annotation")
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_source_and_canonical_provenance_failures_are_gated(self) -> None:
        cases = {
            "source_missing_provenance": "source_record_provenance",
            "canonical_dangling_alias": "canonical_identity",
        }
        for case_id, expected_check in cases.items():
            with self.subTest(case=case_id):
                fixture = self.new_fixture()
                fixture.apply_invalid_recipe(case_id)
                self.assert_gate_failure(
                    fixture, mode="basic", expected_check=expected_check
                )

    def test_synthesis_input_hash_drift_fails_from_cli(self) -> None:
        fixture = self.new_fixture()
        fixture.mutate_artifact(
            "synthesis_input",
            lambda payload: payload["paper_metadata"].__setitem__("sha256", "0" * 64),
        )
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_normalization_label_access_fails_from_cli(self) -> None:
        fixture = self.new_fixture()

        def mutate(payload: dict) -> None:
            payload["score_processing"]["normalization"]["label_access"] = True
            payload["freeze"]["configuration_sha256"] = compute_method_configuration_hash(
                payload
            )

        fixture.mutate_artifact("method_fusion_manifest", mutate)
        self.assert_gate_failure(
            fixture, mode="full", expected_check="full_bundle_contract"
        )

    def test_ascii_console_does_not_crash_on_non_ascii_validator_error(self) -> None:
        fixture = self.new_fixture()
        fixture.apply_invalid_recipe("split_overlap")
        report = self.assert_gate_failure(
            fixture,
            mode="basic",
            expected_check="topic_split_leakage",
            ascii_console=True,
        )
        self.assertEqual(report["result"], "FAIL")

    def test_missing_input_replaces_stale_pass_report(self) -> None:
        output = self.root / "shared_report.json"
        completed, first_report, _ = self.run_cli(
            VALID_ROOT / "bundle_manifest.json", mode="basic", output=output
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(first_report["result"], "PASS")

        missing = self.root / "missing" / "bundle_manifest.json"
        failed, current_report, _ = self.run_cli(
            missing, mode="basic", output=output
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(current_report["result"], "FAIL")
        self.assertIsNone(current_report["input"]["sha256"])
        self.assertEqual(current_report["failed_checks"], ["bundle_inventory"])

    def test_unexpected_programming_error_cannot_leave_stale_pass(self) -> None:
        output = self.root / "stale.json"
        output.write_text(
            json.dumps({"gate": GATE_NAME, "result": "PASS"}) + "\n",
            encoding="utf-8",
        )
        with mock.patch.object(
            gate_cli, "run_w6_quality_gate", side_effect=RuntimeError("programmer bug")
        ):
            with self.assertRaisesRegex(RuntimeError, "programmer bug"):
                gate_cli.main(
                    [
                        "--manifest",
                        str(VALID_ROOT / "bundle_manifest.json"),
                        "--output",
                        str(output),
                    ]
                )
        self.assertFalse(output.exists())

    def test_unrelated_output_file_is_not_overwritten(self) -> None:
        output = self.root / "user_data.json"
        original = b'{"owner": "user"}\n'
        output.write_bytes(original)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            exit_code = gate_cli.main(
                [
                    "--manifest",
                    str(VALID_ROOT / "bundle_manifest.json"),
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(output.read_bytes(), original)
        self.assertIn("refusing to overwrite", stream.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
