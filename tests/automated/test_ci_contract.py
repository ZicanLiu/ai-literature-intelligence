"""Offline checks for the W5 CI workflow and formal-artifact checker."""

from __future__ import annotations

import contextlib
import copy
import shlex
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

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
    """Check parsed workflow behavior; names, comments and YAML layout are free."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_text = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        # BaseLoader preserves GitHub's `on` key and treats values consistently
        # without YAML 1.1's implicit boolean conversion.
        cls.workflow = yaml.load(cls.workflow_text, Loader=yaml.BaseLoader)

    def assert_verification_contract(self, workflow):
        commands = []
        for job_name, job in workflow["jobs"].items():
            for index, step in enumerate(job["steps"]):
                if "run" in step:
                    tokens = shlex.split(step["run"], comments=True)
                    commands.append((job_name, index, step, tokens))

        def find(prefix):
            return [row for row in commands if row[3][:len(prefix)] == prefix]

        def blocking(row):
            job = workflow["jobs"][row[0]]
            for scope in (job, row[2]):
                self.assertEqual(str(scope.get("continue-on-error", "false")).lower(), "false")
                self.assertIn(scope.get("if"), (None, "success()", "${{ success() }}"))
                self.assertNotIn("ASTRO_QUALITY_GATE_RUNNING", scope.get("env", {}))
            shell = row[2].get("shell", job.get("defaults", {}).get("run", {}).get("shell"))
            self.assertIn(shell, (None, "bash"))
            self.assertFalse(set(row[3]) & {"||", "&&", ";", "true", "exit", "--help", "-h", "--version"})

        tests = find(["python", "-m", "unittest", "discover"])
        self.assertEqual(len(tests), 1, "full unittest must be an independent step")
        test = tests[0]
        # Catch repeated or embedded invocations, including compound scripts.
        self.assertEqual(sum(row[3][i:i+2] == ["-m", "unittest"]
                             for row in commands for i in range(len(row[3]))), 1)
        self.assertNotIn("matrix", workflow["jobs"][test[0]].get("strategy", {}))
        blocking(test)
        tokens = test[3]
        self.assertEqual(tokens[tokens.index("-s") + 1], "tests/automated")
        self.assertEqual(tokens[tokens.index("-p") + 1], "test_*.py")
        self.assertTrue(set(tokens[4:]) <= {"-s", "tests/automated", "-p", "test_*.py", "-q", "-v"})

        gates = find(["python", "-m", "app.quality_gate"])
        self.assertTrue(gates)
        self.assertTrue(any("basic" in row[3] for row in gates))
        for gate in gates:
            blocking(gate)
            self.assertEqual(gate[0], test[0])
            self.assertGreater(gate[1], test[1])
            self.assertIn("--skip-tests", gate[3])

        for module in ("app.validate_w4_benchmark", "app.validate_w6_bootstrap",
                       "app.validate_pilot_reference_curation", "app.w6_quality_gate"):
            rows = find(["python", "-m", module])
            self.assertEqual(len(rows), 1, module)
            blocking(rows[0])
            if module == "app.w6_quality_gate":
                self.assertEqual(rows[0][3][rows[0][3].index("--mode") + 1], "basic")
        artifacts = find(["python", "scripts/check_w5_method_artifacts.py"])
        self.assertEqual(len(artifacts), 1)
        blocking(artifacts[0])
        diffs = find(["git", "diff", "--check"])
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0][2].get("if"), "github.event_name == 'pull_request'")
        self.assertEqual(diffs[0][2].get("continue-on-error", "false"), "false")
        diff_range = " ".join(diffs[0][3][3:])
        self.assertIn("github.event.pull_request.base.sha", diff_range)
        self.assertIn("github.event.pull_request.head.sha", diff_range)
        self.assertIn("..", diff_range)

    def test_required_validations_are_blocking_and_unittest_runs_once(self):
        self.assert_verification_contract(self.workflow)

    def test_names_comments_and_yaml_layout_do_not_change_contract(self):
        workflow = copy.deepcopy(self.workflow)
        for job in workflow["jobs"].values():
            for index, step in enumerate(job["steps"]):
                step["name"] = f"renamed step {index}"
                if "run" in step:
                    step["run"] = "# arbitrary explanation\n" + step["run"]
        rendered = yaml.dump(workflow, indent=4, sort_keys=True)
        self.assert_verification_contract(yaml.load(rendered, Loader=yaml.BaseLoader))

    def test_weakened_or_repeated_execution_is_rejected(self):
        for mutation in ("duplicate", "nonblocking", "skip_condition", "gate_reruns", "missing_validator"):
            with self.subTest(mutation=mutation):
                workflow = copy.deepcopy(self.workflow)
                steps = next(iter(workflow["jobs"].values()))["steps"]
                test = next(s for s in steps if "-m unittest" in s.get("run", ""))
                if mutation == "duplicate":
                    steps.append(copy.deepcopy(test))
                elif mutation == "nonblocking":
                    test["continue-on-error"] = "true"
                elif mutation == "skip_condition":
                    test["if"] = "false"
                elif mutation == "gate_reruns":
                    gate = next(s for s in steps if "-m app.quality_gate" in s.get("run", ""))
                    gate["run"] = gate["run"].replace("--skip-tests", "")
                else:
                    steps[:] = [s for s in steps if "app.validate_w4_benchmark" not in s.get("run", "")]
                with self.assertRaises(AssertionError):
                    self.assert_verification_contract(workflow)

    def test_triggers_environment_and_dependencies(self):
        for event in ("push", "pull_request"):
            self.assertIn("main", self.workflow["on"][event]["branches"])
        steps = [step for job in self.workflow["jobs"].values() for step in job["steps"]]
        python = [s for s in steps if s.get("uses", "").startswith("actions/setup-python@")]
        self.assertEqual(len(python), 1)
        self.assertEqual(python[0]["with"]["python-version"], "3.13")
        run_text = "\n".join(s.get("run", "") for s in steps)
        self.assertIn("pip install -r requirements.txt", run_text)
        self.assertNotIn("secrets.", json.dumps(self.workflow))
        self.assertTrue(any(job.get("env", {}).get("DISABLE_LIVE_API") == "true"
                            for job in self.workflow["jobs"].values()))
        for package in ("torch", "transformers", "sentence-transformers"):
            self.assertNotIn(package, run_text.lower())


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
