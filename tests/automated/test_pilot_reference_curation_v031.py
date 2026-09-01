"""Narrow RCP-v0.3.1 external-agent-runner contract regressions."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.pilot_reference_curation import (
    build_model_roster,
    load_reference_curation_inputs,
    validate_reference_preparation_package,
)
from src.w6_contracts import canonical_json_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RCP_V031_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.3.1_reference_curation_v1.json"
)
RCP_V031_PREPARATION = (
    PROJECT_ROOT
    / "data"
    / "research"
    / "pilot"
    / "v0.3.1"
    / "reference-curation-preparation-v1"
)
CREATED_AT = "2026-09-01T21:55:45+08:00"
GIT_REVISION = "a" * 40


class RCPV031ExternalAgentRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load_reference_curation_inputs(
            RCP_V031_CONFIG, project_root=PROJECT_ROOT
        )

    @classmethod
    def _entries(cls, *, external_runner: bool) -> list[dict[str, object]]:
        roles = ["core", "core", "core", "sentinel", "sentinel"]
        entries = []
        for index, role in enumerate(roles, start=1):
            displayed_label = f"offline-test-model-{index}"
            if external_runner:
                execution_config = {
                    "execution_route": "external_agent_runner",
                    "runner_name": f"offline-test-runner-{index}",
                    "runner_version": None if index == 1 else "1.0",
                    "displayed_model_label": displayed_label,
                    "execution_mode": "sequential_shared_runner_session",
                    "prompt_identity": cls.inputs.prompt_package["prompt_identity"],
                    "protocol_config_identity": cls.inputs.config[
                        "config_identity"
                    ],
                    "external_lookup": False,
                    "fulltext_access": False,
                    "one_candidate_per_judgement": True,
                    "response_format": "json",
                }
                requested_type = "rolling_alias"
                snapshot_version = None
                snapshot_guarantee = "unavailable"
            else:
                execution_config = {
                    "temperature": 0,
                    "response_format": "json",
                }
                requested_type = "exact_version"
                snapshot_version = f"snapshot-{index}"
                snapshot_guarantee = "provider_versioned"
            entries.append(
                {
                    "roster_entry_id": f"offline_test_{role}_{index}",
                    "role": role,
                    "provider": f"offline-test-provider-{index}",
                    "model_family": f"offline-test-family-{index}",
                    "independence_group": f"offline-test-group-{index}",
                    "requested_model_id": displayed_label,
                    "requested_model_id_type": requested_type,
                    "provider_reported_model_id": displayed_label,
                    "resolved_model_id": displayed_label,
                    "resolved_identity_confirmed": True,
                    "snapshot_version": snapshot_version,
                    "snapshot_guarantee": snapshot_guarantee,
                    "execution_config": execution_config,
                    "execution_config_sha256": canonical_json_sha256(
                        execution_config
                    ),
                    "status": "frozen",
                }
            )
        return entries

    def test_exact_snapshot_primary_path_remains_valid(self) -> None:
        roster = build_model_roster(
            inputs=self.inputs,
            entries=self._entries(external_runner=False),
            frozen_at=CREATED_AT,
            git_revision=GIT_REVISION,
            created_by="offline_test",
            run_scope="primary",
        )
        self.assertFalse(roster["allow_snapshot_unavailable_exception"])

    def test_external_runner_snapshot_unavailable_primary_path_is_valid(self) -> None:
        roster = build_model_roster(
            inputs=self.inputs,
            entries=self._entries(external_runner=True),
            frozen_at=CREATED_AT,
            git_revision=GIT_REVISION,
            created_by="offline_test",
            run_scope="primary",
            allow_snapshot_unavailable_exception=True,
        )
        self.assertTrue(roster["allow_snapshot_unavailable_exception"])
        self.assertTrue(
            all(
                entry["snapshot_guarantee"] == "unavailable"
                and entry["snapshot_version"] is None
                for entry in roster["entries"]
            )
        )

    def test_snapshot_unavailable_missing_runner_provenance_fails(self) -> None:
        entries = self._entries(external_runner=True)
        broken = copy.deepcopy(entries[0]["execution_config"])
        broken.pop("runner_name")
        entries[0]["execution_config"] = broken
        entries[0]["execution_config_sha256"] = canonical_json_sha256(broken)
        with self.assertRaisesRegex(ValueError, "runner_name"):
            build_model_roster(
                inputs=self.inputs,
                entries=entries,
                frozen_at=CREATED_AT,
                git_revision=GIT_REVISION,
                created_by="offline_test",
                run_scope="primary",
                allow_snapshot_unavailable_exception=True,
            )

    def test_committed_v031_preparation_is_not_started(self) -> None:
        result = validate_reference_preparation_package(
            RCP_V031_PREPARATION,
            config_path=RCP_V031_CONFIG,
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(result["protocol_version"], "RCP-v0.3.1")
        self.assertEqual(result["status"], "prepared_not_started")
        self.assertFalse(result["real_model_judgements_started"])


if __name__ == "__main__":
    unittest.main()
