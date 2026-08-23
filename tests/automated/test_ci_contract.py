"""Offline checks for the W5 CI workflow and formal-artifact checker."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_w5_method_artifacts import (
    check_formal_artifacts,
    discover_formal_manifests,
)
from src.annotation_tasks import sha256_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "w5_method_contract"
BASE_REVISION = "d558a0888e4c71a9d001a67e0640d28394b6ac88"


class CIWorkflowContractTests(unittest.TestCase):
    """Lightweight workflow smoke checks without adding a YAML dependency."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
        if not cls.workflow_path.is_file():
            raise AssertionError("CI workflow file is missing")
        cls.workflow = cls.workflow_path.read_text(encoding="utf-8")

    def test_ci_triggers_main_push_and_pull_request(self) -> None:
        self.assertIn("push:", self.workflow)
        self.assertIn("pull_request:", self.workflow)
        self.assertGreaterEqual(self.workflow.count('branches: [ "main" ]'), 2)

    def test_python_environment_and_core_install(self) -> None:
        self.assertIn("actions/setup-python@v5", self.workflow)
        self.assertIn('python-version: "3.13"', self.workflow)
        self.assertIn("pip install -r requirements.txt", self.workflow)

    def test_required_gates_are_separate_blocking_steps(self) -> None:
        required_commands = [
            'git diff --check ${{ github.event.pull_request.base.sha }}..${{ github.event.pull_request.head.sha }}',
            "python -m app.validate_w4_benchmark",
            'python -m unittest discover -s tests/automated -p "test_*.py" -q',
            "python -m app.quality_gate --level basic",
            "python scripts/check_w5_method_artifacts.py",
        ]
        for command in required_commands:
            self.assertIn(command, self.workflow)
        self.assertNotIn("continue-on-error", self.workflow)

    def test_no_secret_or_model_environment_is_required(self) -> None:
        self.assertNotIn("secrets.", self.workflow)
        self.assertIn("DISABLE_LIVE_API", self.workflow)
        for package in ("torch", "transformers", "sentence-transformers"):
            self.assertNotIn(package, self.workflow.lower())


class W5ArtifactCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.artifact_root = self.root / "data" / "analysis" / "w5_methods"

    def _create_package(
        self,
        *,
        method_id: str,
        fixture_name: str = "lexical_fixture.csv",
        family: str = "sparse",
    ) -> Path:
        package_dir = self.artifact_root / method_id
        package_dir.mkdir(parents=True)
        ranking_path = package_dir / "ranking.csv"
        shutil.copyfile(FIXTURE_DIR / fixture_name, ranking_path)
        model = None
        if family in {"dense", "neural"}:
            model = {
                "name": "fixture-encoder",
                "revision": "fixture-v1",
                "adapter": None,
            }
        manifest = {
            "schema_version": "1.0",
            "contract_name": "w5_method_ranking",
            "contract_version": "1.0",
            "artifact_type": "method_ranking",
            "method": {
                "method_id": method_id,
                "display_name": method_id.replace("_", " "),
                "family": family,
                "parameters": {"fixture_only": True},
                "model": model,
            },
            "inputs": {
                "candidate_pool": {
                    "path": "data/annotation_tasks/w4/candidate_pool_v0.1.csv",
                    "sha256": (
                        "25f608eb4c94218dfa220ba108b15ec846b2bd418174501420a468c376ed17cc"
                    ),
                    "version": "w4_pilot_v0.1",
                },
                "research_queries": {
                    "path": "configs/w4/research_queries.json",
                    "sha256": (
                        "c77ec74ef4567614d3dfb6dab937b85398f95128cdb29e823587715002d99ab1"
                    ),
                    "version": "w4_pilot_v0.1",
                },
            },
            "ranking": {
                "path": "ranking.csv",
                "sha256": sha256_file(ranking_path),
                "row_count": 60,
                "score_direction": "higher_is_better",
                "tie_breaking": ["score_desc", "pair_id_asc"],
            },
            "generation": {
                "generated_at": "2026-08-17T20:00:00+08:00",
                "duration_seconds": 0.0,
                "git_revision": BASE_REVISION,
                "git_worktree_clean": True,
                "python": {"version": "3.fixture", "implementation": "CPython"},
                "platform": {
                    "system": "fixture",
                    "release": "fixture",
                    "machine": "fixture",
                },
                "dependencies": {"fixture-generator": "1.0"},
            },
            "label_access": {
                "benchmark_labels_read": False,
                "declaration": "Synthetic ranking created without benchmark judgements.",
            },
        }
        manifest_path = package_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def _run_checker(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_formal_artifacts(
                project_root=PROJECT_ROOT,
                artifact_root=self.artifact_root,
            )
        return code, output.getvalue()

    def test_no_artifact_is_a_clear_pass(self) -> None:
        code, output = self._run_checker()
        self.assertEqual(code, 0)
        self.assertIn("No formal W5 artifacts", output)

    def test_normal_method_directory_manifest_is_discovered(self) -> None:
        manifest_path = self._create_package(method_id="fixture_lexical_v1")
        self.assertEqual(
            discover_formal_manifests(self.artifact_root),
            [manifest_path.resolve()],
        )

    def test_one_valid_artifact_passes_real_validator(self) -> None:
        self._create_package(method_id="fixture_lexical_v1")
        code, output = self._run_checker()
        self.assertEqual(code, 0, output)
        self.assertIn("method_id=fixture_lexical_v1", output)
        self.assertIn("1/1 valid", output)

    def test_multiple_valid_artifacts_are_all_validated(self) -> None:
        self._create_package(method_id="fixture_lexical_v1")
        self._create_package(
            method_id="fixture_dense_v1",
            fixture_name="dense_fixture.csv",
            family="dense",
        )
        code, output = self._run_checker()
        self.assertEqual(code, 0, output)
        self.assertIn("method_id=fixture_lexical_v1", output)
        self.assertIn("method_id=fixture_dense_v1", output)
        self.assertIn("2/2 valid", output)

    def test_one_invalid_artifact_fails_after_checking_all(self) -> None:
        self._create_package(method_id="fixture_lexical_v1")
        invalid_manifest = self._create_package(
            method_id="fixture_dense_v1",
            fixture_name="dense_fixture.csv",
            family="dense",
        )
        payload = json.loads(invalid_manifest.read_text(encoding="utf-8"))
        payload["ranking"]["sha256"] = "0" * 64
        invalid_manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("method_id=fixture_lexical_v1", output)
        self.assertIn("FAIL", output)
        self.assertIn("1/2 invalid", output)

    def test_fixture_and_unrelated_json_are_not_scanned(self) -> None:
        self.artifact_root.mkdir(parents=True)
        (self.artifact_root / "manifest.json").write_text("{}\n", encoding="utf-8")
        (self.artifact_root / "notes.json").write_text("{}\n", encoding="utf-8")
        nested = self.artifact_root / "not-a-package" / "nested"
        nested.mkdir(parents=True)
        (nested / "manifest.json").write_text("{}\n", encoding="utf-8")
        external_fixture = self.root / "tests" / "fixtures" / "w5_method_contract"
        external_fixture.mkdir(parents=True)
        (external_fixture / "manifest.json").write_text("{}\n", encoding="utf-8")

        self.assertEqual(discover_formal_manifests(self.artifact_root), [])
        code, output = self._run_checker()
        self.assertEqual(code, 0)
        self.assertIn("No formal W5 artifacts", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
