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
from src.annotation_tasks import read_csv_rows, sha256_file, write_csv_rows
from src.w5_formal_policy import FORMAL_METHOD_IDS
from src.w5_method_contract import RANKING_FIELDS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORMAL_ARTIFACT_SOURCE = PROJECT_ROOT / "data" / "analysis" / "w5_methods"


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
            "python -m app.validate_w6_bootstrap",
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

    def _copy_formal_package(
        self, method_id: str, *, as_name: str | None = None
    ) -> Path:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        target = self.artifact_root / (as_name or method_id)
        shutil.copytree(FORMAL_ARTIFACT_SOURCE / method_id, target)
        return target

    def _copy_full_roster(self) -> None:
        for method_id in sorted(FORMAL_METHOD_IDS):
            self._copy_formal_package(method_id)

    def _run_checker(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_formal_artifacts(
                project_root=PROJECT_ROOT,
                artifact_root=self.artifact_root,
            )
        return code, output.getvalue()

    def test_missing_artifact_root_fails(self) -> None:
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("不存在或不是目录", output)

    def test_empty_artifact_root_fails(self) -> None:
        self.artifact_root.mkdir(parents=True)
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("root 为空", output)

    def test_complete_six_method_roster_passes(self) -> None:
        self._copy_full_roster()
        code, output = self._run_checker()
        self.assertEqual(code, 0, output)
        self.assertIn("6/6 formal packages valid", output)
        self.assertEqual(
            discover_formal_manifests(self.artifact_root),
            sorted(
                (self.artifact_root / method_id / "manifest.json").resolve()
                for method_id in FORMAL_METHOD_IDS
            ),
        )

    def test_missing_one_formal_method_fails(self) -> None:
        self._copy_full_roster()
        shutil.rmtree(self.artifact_root / "rrf_bm25_specter2_v1")
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("缺少正式方法目录：rrf_bm25_specter2_v1", output)

    def test_unknown_formal_method_directory_fails(self) -> None:
        self._copy_full_roster()
        self._copy_formal_package(
            "bm25_v1",
            as_name="unknown_method_v1",
        )
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("存在未知正式方法目录：unknown_method_v1", output)

    def test_directory_and_manifest_method_identity_mismatch_fails(self) -> None:
        self._copy_full_roster()
        package_dir = self.artifact_root / "specter2_adhoc_v1"
        manifest_path = package_dir / "manifest.json"
        ranking_path = package_dir / "ranking.csv"
        _fields, rows = read_csv_rows(ranking_path)
        for row in rows:
            row["method_id"] = "impostor_specter2_v1"
        write_csv_rows(ranking_path, RANKING_FIELDS, rows)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["method"]["method_id"] = "impostor_specter2_v1"
        payload["ranking"]["sha256"] = sha256_file(ranking_path)
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("目录 specter2_adhoc_v1", output)
        self.assertIn("method_id 'impostor_specter2_v1' 不一致", output)

    def test_duplicate_manifest_method_id_fails(self) -> None:
        self._copy_full_roster()
        specter_dir = self.artifact_root / "specter2_adhoc_v1"
        shutil.rmtree(specter_dir)
        shutil.copytree(self.artifact_root / "bm25_v1", specter_dir)
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("method_id 重复：bm25_v1", output)

    def test_package_directory_without_manifest_fails(self) -> None:
        self._copy_full_roster()
        (self.artifact_root / "cross_encoder_msmarco_v1" / "manifest.json").unlink()
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("缺少顶层 manifest.json", output)

    def test_downgraded_official_baseline_fails(self) -> None:
        self._copy_full_roster()
        manifest_path = self.artifact_root / "preliminary_score_v1" / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["schema_version"] = "1.0"
        payload["contract_version"] = "1.0"
        payload["inputs"].pop("source_sample")
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        code, output = self._run_checker()
        self.assertEqual(code, 1)
        self.assertIn("不得降级为 v1.0", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
