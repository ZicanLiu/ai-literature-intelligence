"""W6 evidence-grounded synthesis 原型的离线回归测试（Issue #65 Part B）。"""

from __future__ import annotations

import copy
import csv
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from app import run_w6_synthesis
from src.annotation_tasks import sha256_file, write_csv_rows
from src.w5_method_contract import RANKING_FIELDS
from src.w6_contracts import load_json_object, validate_w6_bootstrap_bundle
from src.w6_method_contract import (
    compute_method_configuration_hash,
    validate_w6_method_package,
)
from src.w6_synthesis_contract import (
    MAX_SNIPPET_CHARACTERS,
    load_and_validate_evidence_units,
    validate_evidence_units,
    validate_structured_synthesis,
    validate_synthesis_input,
)
from src.w6_synthesis_pipeline import (
    DeterministicFakeBackend,
    audit_unsupported_claims,
    build_evidence_units,
    generate_structured_synthesis,
    render_mini_review,
    validate_canonical_render,
)
from src.w6_task_context import (
    BASE_CONTEXT_ARTIFACT_NAMES,
    LABEL_AWARE_ARTIFACT_NAMES,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap"
VALID_ROOT = FIXTURE_ROOT / "valid"
BUNDLE_PATH = VALID_ROOT / "bundle_manifest.json"
FAKE_GIT_REVISION = "6b9eb12f898bf880c297902463e48f2ff3e0388b"
FIXED_TIME = "2026-08-24T12:00:00+08:00"


class W6SynthesisTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)
        cls.registry = cls.bundle["registry"]
        cls.topics = cls.bundle["topics"]
        cls.pool_members = cls.bundle["pool_members"]
        cls.records = cls.bundle["records"]
        cls.canonical = cls.bundle["canonical"]
        cls.payloads = cls.bundle["payloads"]
        cls.paths = cls.bundle["paths"]
        cls.method_packages = cls.bundle["method_packages"]
        cls.fixture_evidence = cls.bundle["evidence_units"]
        cls.fixture_synthesis_input = cls.bundle["synthesis_input"]

    def _build_evidence(self, record_ids):
        payload = build_evidence_units(
            self.records,
            self.canonical,
            record_ids,
            artifact_id="w6_test_evidence",
            created_at=FIXED_TIME,
            git_revision=FAKE_GIT_REVISION,
        )
        return validate_evidence_units(payload, records=self.records, canonical=self.canonical)


class EvidenceExtractionTests(W6SynthesisTestBase):
    def test_build_evidence_passes_validator(self) -> None:
        evidence = self._build_evidence(["rec_001", "rec_003", "rec_008"])
        self.assertEqual(set(evidence), {"ev_rec_001", "ev_rec_003", "ev_rec_008"})
        for unit in evidence.values():
            # 机器抽取一律标记 extracted，不得伪装 human_verified。
            self.assertEqual(unit["extraction_status"], "extracted")

    def test_evidence_binds_selected_paper_identity(self) -> None:
        evidence = self._build_evidence(["rec_008"])
        unit = evidence["ev_rec_008"]
        # rec_008 是 rec_003 的 confirmed alias，必须绑定同一 canonical entity。
        self.assertEqual(unit["paper_identity"]["canonical_entity_id"], "entity_003")

    def test_missing_abstract_becomes_structured_metadata(self) -> None:
        evidence = self._build_evidence(["rec_006"])
        unit = evidence["ev_rec_006"]
        self.assertEqual(unit["evidence_type"], "structured_metadata")
        self.assertEqual(
            unit["content"]["structured_field"], {"name": "abstract_present", "value": False}
        )

    def test_snippet_truncated_to_copyright_limit(self) -> None:
        records = copy.deepcopy(self.records)
        records["rec_001"]["abstract"] = "a" * (MAX_SNIPPET_CHARACTERS + 200)
        payload = build_evidence_units(
            records,
            self.canonical,
            ["rec_001"],
            artifact_id="w6_test_evidence_long",
            created_at=FIXED_TIME,
            git_revision=FAKE_GIT_REVISION,
        )
        snippet = payload["evidence_units"][0]["content"]["snippet"]
        self.assertEqual(len(snippet), MAX_SNIPPET_CHARACTERS)
        self.assertTrue(snippet.endswith("..."))
        validate_evidence_units(payload, records=records, canonical=self.canonical)


class FakeBackendTests(W6SynthesisTestBase):
    def test_deterministic_output(self) -> None:
        backend = DeterministicFakeBackend()
        kwargs = {
            "research_question": "q",
            "selected_entity_ids": {"entity_001", "entity_003"},
            "evidence": self.fixture_evidence,
        }
        self.assertEqual(backend.generate_claims(**kwargs), backend.generate_claims(**kwargs))

    def test_human_verified_evidence_yields_supported_verified(self) -> None:
        backend = DeterministicFakeBackend()
        claims = backend.generate_claims(
            research_question="q",
            selected_entity_ids={"entity_001"},
            evidence=self.fixture_evidence,
        )
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim["evidence_refs"], ["evidence_001"])
        self.assertEqual(claim["supporting_canonical_entity_ids"], ["entity_001"])
        self.assertEqual(claim["support_status"], "supported")
        self.assertEqual(claim["citation_status"], "verified")

    def test_unselected_papers_produce_no_claims(self) -> None:
        backend = DeterministicFakeBackend()
        claims = backend.generate_claims(
            research_question="q",
            selected_entity_ids={"entity_001", "entity_003"},
            evidence=self.fixture_evidence,
        )
        referenced = {ref for claim in claims for ref in claim["evidence_refs"]}
        # evidence_006/007 属于 selection 之外的论文，不得产生 claim。
        self.assertEqual(referenced, {"evidence_001", "evidence_003"})

    def test_rejected_evidence_produces_no_claim(self) -> None:
        evidence = copy.deepcopy(self.fixture_evidence)
        evidence["evidence_001"]["extraction_status"] = "rejected"
        backend = DeterministicFakeBackend()
        claims = backend.generate_claims(
            research_question="q",
            selected_entity_ids={"entity_001", "entity_003"},
            evidence=evidence,
        )
        referenced = {ref for claim in claims for ref in claim["evidence_refs"]}
        self.assertEqual(referenced, {"evidence_003"})

    def test_machine_extracted_evidence_only_partially_supports(self) -> None:
        evidence = self._build_evidence(["rec_001"])
        backend = DeterministicFakeBackend()
        claims = backend.generate_claims(
            research_question="q",
            selected_entity_ids={"entity_001"},
            evidence=evidence,
        )
        self.assertEqual(len(claims), 1)
        # 未经人工核验的 evidence 不得产出 supported/verified claim。
        self.assertEqual(claims[0]["support_status"], "partially_supported")
        self.assertEqual(claims[0]["citation_status"], "incomplete")


class PipelineTests(W6SynthesisTestBase):
    def _generate_on_fixture_input(self):
        backend = DeterministicFakeBackend()
        return generate_structured_synthesis(
            backend,
            synthesis_input=self.fixture_synthesis_input,
            evidence=self.fixture_evidence,
            canonical=self.canonical,
            artifact_id="w6_test_structured",
            synthesis_id="w6_test_synthesis",
            created_at=FIXED_TIME,
            git_revision=FAKE_GIT_REVISION,
        )

    def test_end_to_end_on_fixture_selection(self) -> None:
        result = self._generate_on_fixture_input()
        claims = result["claims"]
        # selection {entity_001, entity_003}，fixture evidence 全部 human_verified。
        self.assertEqual(set(claims), {"claim_001", "claim_002"})
        self.assertTrue(
            all(claim["support_status"] == "supported" for claim in claims.values())
        )
        rendered = result["payload"]["rendered_review"]
        self.assertEqual(set(rendered["generated_from_claim_ids"]), set(claims))
        self.assertEqual(result["audit"]["unsupported_claim_ids"], [])
        self.assertEqual(result["audit"]["claims_without_evidence"], [])

    def test_render_uses_only_claim_content(self) -> None:
        claims = {
            "claim_001": {
                "claim_text": "First finding.",
                "supporting_canonical_entity_ids": ["entity_001"],
                "evidence_refs": ["evidence_001"],
                "confidence": "high",
                "support_status": "supported",
                "citation_status": "verified",
            },
            "claim_002": {
                "claim_text": "Second finding",
                "supporting_canonical_entity_ids": [],
                "evidence_refs": [],
                "confidence": "low",
                "support_status": "unsupported",
                "citation_status": "missing",
            },
        }
        text = render_mini_review(claims)
        header, _, body = text.partition("\n\n")
        self.assertEqual(
            body,
            "First finding. [claim_001; supported/verified] "
            "Second finding. [claim_002; unsupported/missing]",
        )
        # 头部必须显式标注核验状态统计与人工核验提示。
        self.assertIn("1 supported", header)
        self.assertIn("1 unsupported", header)
        self.assertIn("NOT completed human verification", header)

    def test_audit_flags_unsupported_claims(self) -> None:
        claims = {
            "claim_001": {"support_status": "supported", "evidence_refs": ["e1"]},
            "claim_002": {"support_status": "unsupported", "evidence_refs": []},
            "claim_003": {"support_status": "partially_supported", "evidence_refs": ["e2"]},
        }
        audit = audit_unsupported_claims(claims)
        self.assertEqual(audit["unsupported_claim_ids"], ["claim_002"])
        self.assertEqual(audit["partially_supported_claim_ids"], ["claim_003"])
        self.assertEqual(audit["claims_without_evidence"], ["claim_002"])

    def _fixture_payload(self):
        return copy.deepcopy(self.payloads["structured_synthesis"])

    def _validate(self, payload, evidence=None) -> None:
        validate_structured_synthesis(
            payload,
            synthesis_input=self.fixture_synthesis_input,
            evidence=evidence or self.fixture_evidence,
            canonical=self.canonical,
        )

    def test_dangling_evidence_detected(self) -> None:
        payload = self._fixture_payload()
        payload["claims"][0]["evidence_refs"] = ["evidence_999"]
        with self.assertRaisesRegex(ValueError, "dangling evidence"):
            self._validate(payload)

    def test_unselected_paper_detected(self) -> None:
        payload = self._fixture_payload()
        # entity_007 是其他 topic 的论文，不在 denoise selection 内。
        payload["claims"][0]["supporting_canonical_entity_ids"] = ["entity_007"]
        with self.assertRaisesRegex(ValueError, "ranked selection 之外"):
            self._validate(payload)

    def test_rejected_evidence_cannot_support_claim(self) -> None:
        evidence_payload = copy.deepcopy(self.payloads["evidence_units"])
        rejected_unit = copy.deepcopy(evidence_payload["evidence_units"][1])
        rejected_unit["evidence_id"] = "evidence_003r"
        rejected_unit["extraction_status"] = "rejected"
        evidence_payload["evidence_units"].append(rejected_unit)
        evidence = validate_evidence_units(
            evidence_payload, records=self.records, canonical=self.canonical
        )
        payload = self._fixture_payload()
        payload["claims"][0]["evidence_refs"] = ["evidence_003r"]
        with self.assertRaisesRegex(ValueError, "rejected evidence"):
            self._validate(payload, evidence=evidence)

    def test_input_hash_drift_detected(self) -> None:
        payload = self._fixture_payload()
        payload["synthesis_input"] = {
            "artifact_id": "w6_fixture_synthesis_input_v1",
            "sha256": "0" * 64,
        }
        with self.assertRaisesRegex(ValueError, "未绑定实际 synthesis input hash"):
            self._validate(payload)

    def test_rendered_review_must_cover_exact_claims(self) -> None:
        payload = self._fixture_payload()
        payload["rendered_review"]["generated_from_claim_ids"] = ["claim_001", "claim_002"]
        with self.assertRaisesRegex(ValueError, "全部且仅结构化 claims"):
            self._validate(payload)

    def test_canonical_render_consistency_enforced(self) -> None:
        result = self._generate_on_fixture_input()
        payload = copy.deepcopy(result["payload"])
        validate_canonical_render(payload)
        # 保持 claim IDs 不变，但删除真实 claim 内容 → fail。
        tampered = copy.deepcopy(payload)
        tampered["rendered_review"]["text"] = "All claims removed. [claim_001] [claim_002]"
        with self.assertRaisesRegex(ValueError, "canonical render 不一致"):
            validate_canonical_render(tampered)
        # 保持 claim IDs 不变，但添加 claims 之外的事实性主张 → fail。
        injected = copy.deepcopy(payload)
        injected["rendered_review"]["text"] += " Proven best on hidden data. [claim_001]"
        with self.assertRaisesRegex(ValueError, "canonical render 不一致"):
            validate_canonical_render(injected)


class SynthesisCliTests(W6SynthesisTestBase):
    def _run_cli(self, extra_args, output_dir: Path) -> int:
        argv = ["--output-dir", str(output_dir), *extra_args]
        with mock.patch.object(
            run_w6_synthesis, "_git_revision", return_value=FAKE_GIT_REVISION
        ), redirect_stdout(io.StringIO()):
            return run_w6_synthesis.main(argv)

    def _revalidate_outputs(self, output_dir: Path) -> dict:
        evidence = load_and_validate_evidence_units(
            output_dir / "evidence_units.json",
            records=self.records,
            canonical=self.canonical,
        )
        registry = dict(self.registry)
        registry["w6_synthesis_demo_evidence"] = {
            "artifact_id": "w6_synthesis_demo_evidence",
            "sha256": sha256_file(output_dir / "evidence_units.json"),
        }
        registry["w6_synthesis_demo_input"] = {
            "artifact_id": "w6_synthesis_demo_input",
            "sha256": sha256_file(output_dir / "synthesis_input.json"),
        }
        input_payload = load_json_object(output_dir / "synthesis_input.json")
        synthesis_input = validate_synthesis_input(
            input_payload,
            registry=registry,
            topics=self.topics,
            pool_members=self.pool_members,
            method_packages=self.method_packages,
            records=self.records,
            canonical=self.canonical,
            evidence=evidence,
            expected_artifact_ids={
                "topic_set": self.payloads["topic_set"]["artifact_id"],
                "source_records": self.payloads["source_records"]["artifact_id"],
                "retrieval_provenance": self.payloads["retrieval_provenance"]["artifact_id"],
                "evidence_units": "w6_synthesis_demo_evidence",
            },
        )
        structured = load_json_object(output_dir / "structured_synthesis.json")
        claims = validate_structured_synthesis(
            structured,
            synthesis_input=synthesis_input,
            evidence=evidence,
            canonical=self.canonical,
        )
        return {
            "evidence": evidence,
            "synthesis_input": synthesis_input,
            "structured": structured,
            "claims": claims,
        }

    def test_cli_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            rc = self._run_cli([], output_dir)
            self.assertEqual(rc, 0)
            for name in (
                "evidence_units.json",
                "synthesis_input.json",
                "structured_synthesis.json",
                "mini_review.md",
                "unsupported_claim_audit.json",
            ):
                self.assertTrue((output_dir / name).is_file(), name)
            result = self._revalidate_outputs(output_dir)
            claims = result["claims"]
            # 机器抽取 evidence 一律 extracted，因此全部 claim 只能 partially_supported。
            self.assertEqual(len(claims), 3)
            self.assertTrue(
                all(
                    claim["support_status"] == "partially_supported"
                    for claim in claims.values()
                )
            )
            review_text = (output_dir / "mini_review.md").read_text(encoding="utf-8")
            self.assertEqual(
                review_text, result["structured"]["rendered_review"]["text"] + "\n"
            )
            audit = load_json_object(output_dir / "unsupported_claim_audit.json")
            self.assertEqual(audit["claim_count"], len(claims))

    def test_cli_top_n_selection_follows_frozen_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            rc = self._run_cli(["--top-n", "2"], output_dir)
            self.assertEqual(rc, 0)
            input_payload = load_json_object(output_dir / "synthesis_input.json")
            # fixture fusion ranking 的 denoise 前两名。
            self.assertEqual(
                input_payload["selected_pool_item_ids"],
                ["pool_denoise_003", "pool_denoise_001"],
            )

    def test_cli_rejects_unknown_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = self._run_cli(
                ["--topic-id", "w6_fixture_topic_unknown"], Path(tmp) / "out"
            )
            self.assertEqual(rc, 1)

    def test_cli_rejects_nonempty_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            (output_dir / "junk.txt").write_text("x", encoding="utf-8")
            rc = self._run_cli([], output_dir)
            self.assertEqual(rc, 1)

    # ---- P1-2 / P1-5 / P1-1 回归 ----

    def test_cli_same_artifact_id_different_content_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tampered_manifest = _make_tampered_fusion_package(Path(tmp))
            rc = self._run_cli(
                ["--method-manifest", str(tampered_manifest)], Path(tmp) / "out"
            )
            self.assertEqual(rc, 1)

    def test_cli_rejects_output_inside_default_method_package(self) -> None:
        package_dir = self.paths["method_fusion_manifest"].parent
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = package_dir / "generated_default"
            argv = ["--output-dir", str(output_dir)]
            with mock.patch.object(
                run_w6_synthesis, "_git_revision", return_value=FAKE_GIT_REVISION
            ), redirect_stdout(io.StringIO()):
                rc = run_w6_synthesis.main(argv)
            self.assertEqual(rc, 1)
            # 冻结 package 目录树不得被写入。
            self.assertFalse(output_dir.exists())

    def test_cli_rejects_output_inside_explicit_method_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "pkg"
            shutil.copytree(
                VALID_ROOT / "method_rankings" / "fake_fusion", package_dir
            )
            output_dir = package_dir / "generated_explicit"
            rc = self._run_cli(
                ["--method-manifest", str(package_dir / "manifest.json")], output_dir
            )
            self.assertEqual(rc, 1)
            self.assertFalse(output_dir.exists())

    def test_cli_rejects_output_containing_method_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "pkg"
            shutil.copytree(
                VALID_ROOT / "method_rankings" / "fake_fusion", package_dir
            )
            rc = self._run_cli(
                ["--method-manifest", str(package_dir / "manifest.json")],
                Path(tmp),
            )
            self.assertEqual(rc, 1)

    def test_cli_never_opens_label_aware_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc, opened = _tracked_open_calls(
                lambda: self._run_cli([], Path(tmp) / "out")
            )
        self.assertEqual(rc, 0)
        hits = sorted(
            {
                path
                for path in opened
                for name in LABEL_AWARE_ARTIFACT_NAMES
                if name in path
            }
        )
        self.assertEqual(hits, [])

    def test_cli_runs_on_declared_closure_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subset_root = _copy_generation_subset(Path(tmp))
            argv = [
                "--bundle",
                str(subset_root / "bundle_manifest.json"),
                "--output-dir",
                str(Path(tmp) / "out"),
            ]
            with mock.patch.object(
                run_w6_synthesis, "_git_revision", return_value=FAKE_GIT_REVISION
            ), redirect_stdout(io.StringIO()):
                rc = run_w6_synthesis.main(argv)
            self.assertEqual(rc, 0)


def _make_tampered_fusion_package(root: Path) -> Path:
    """构造 artifact_id/method_id 不变但内容不同且内部自洽的 fusion package。"""
    source = VALID_ROOT / "method_rankings" / "fake_fusion"
    target = root / "fake_fusion_tampered"
    shutil.copytree(source, target)
    rows = []
    with (target / "ranking.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row["score"] = str(round(float(row["score"]) + 0.25, 6))
            rows.append(row)
    by_topic: dict[str, list[dict]] = {}
    for row in rows:
        by_topic.setdefault(row["research_query_id"], []).append(row)
    ordered = []
    for topic_id in sorted(by_topic):
        topic_rows = sorted(
            by_topic[topic_id], key=lambda row: (-float(row["score"]), row["pair_id"])
        )
        for rank, row in enumerate(topic_rows, start=1):
            row["rank"] = str(rank)
            ordered.append(row)
    write_csv_rows(target / "ranking.csv", RANKING_FIELDS, ordered)
    manifest = load_json_object(target / "manifest.json")
    manifest["ranking"]["sha256"] = sha256_file(target / "ranking.csv")
    manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(manifest)
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # 自洽性 sanity check：篡改后的 package 自身必须能通过 contract validator。
    bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)
    validate_w6_method_package(
        target / "manifest.json",
        artifact_registry=bundle["registry"],
        pool_members=bundle["pool_members"],
        known_method_packages=bundle["method_packages"],
    )
    return target / "manifest.json"


def _tracked_open_calls(func):
    """运行 func 并记录所有 Path.open 访问的文件路径。"""
    opened: list[str] = []
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        opened.append(str(self))
        return real_open(self, *args, **kwargs)

    with mock.patch.object(Path, "open", tracking_open):
        result = func()
    return result, opened


def _copy_generation_subset(destination: Path) -> Path:
    """只复制 synthesis default 任务实际需要的 artifact（base + fusion 及其
    传递依赖 sparse/dense），构造最小 dependency closure bundle。"""
    names = [
        *BASE_CONTEXT_ARTIFACT_NAMES,
        "method_sparse_manifest",
        "method_dense_manifest",
        "method_fusion_manifest",
    ]
    root = destination / "subset"
    root.mkdir(parents=True)
    manifest = load_json_object(BUNDLE_PATH)
    subset = copy.deepcopy(manifest)
    subset["artifacts"] = {name: manifest["artifacts"][name] for name in names}
    (root / "bundle_manifest.json").write_text(
        json.dumps(subset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in names:
        relative = Path(manifest["artifacts"][name]["path"])
        source = VALID_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.name == "manifest.json" and "method_rankings" in relative.parts:
            shutil.copytree(source.parent, target.parent, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return root


if __name__ == "__main__":
    unittest.main(verbosity=2)
