"""Phase A: evidence package discovery and machine-readable inventory.

Roles and statuses below are assigned from package-internal provenance
(README/status lines and report files), never from directory names alone.
Each row records where the status evidence came from.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from .util import atomic_write_json, load_json, sha256_file, write_csv

# Curated package role table. `status_evidence` names the in-package files the
# role statement is grounded in; the builder re-reads those files and records
# their declared status strings verbatim instead of trusting this table.
PACKAGE_ROLE_TABLE = {
    "RCP_v0.3.1_CODEX_SCREENING_RESULTS": {
        "package_id": "rcp_screening_codex",
        "role": "RCP-v0.3.1 screening execution (Codex, two independent topic runs)",
        "chain_position": "rcp_screening",
        "primary_or_sensitivity": "primary_chain_upstream",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "execution_report.json", "SHA256_manifest.txt"],
    },
    "RCP_v0.3.1_CODEX_ULTRA_SCREENING_RESULTS": {
        "package_id": "rcp_screening_codex_ultra",
        "role": "RCP-v0.3.1 screening sensitivity re-run (Codex Ultra; never a sixth independent model or Primary vote)",
        "chain_position": "rcp_screening_sensitivity",
        "primary_or_sensitivity": "sensitivity",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "execution_report.json", "SHA256_manifest.txt"],
    },
    "RCP_v0.3.1_DEEPSEEK_SCREENING_RESULTS": {
        "package_id": "rcp_screening_deepseek",
        "role": "RCP-v0.3.1 screening execution (DeepSeek)",
        "chain_position": "rcp_screening",
        "primary_or_sensitivity": "primary_chain_upstream",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "execution_report.json", "SHA256_manifest.txt"],
    },
    "RCP_RUNNER_RESULTS_20260905": {
        "package_id": "rcp_runner_zips",
        "role": "Retained ZIP set of runner results (delivery archive)",
        "chain_position": "rcp_screening_archive",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "pre_treatment_blind",
        "immutability": "archive_no_manifest",
        "status_evidence": [],
    },
    "RCP_INTEGRATION_20260905": {
        "package_id": "rcp_integration",
        "role": "Mechanical integration of 5-runner RCP results (160 cases, 800 Primary judgments); descriptive only",
        "chain_position": "rcp_integration",
        "primary_or_sensitivity": "primary_chain_upstream",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "validation_report.json", "SHA256_manifest.txt"],
    },
    "MCA_V1_PROTOCOL_AND_AUDIT_20260905": {
        "package_id": "mca_protocol_audit",
        "role": "MCA-v1 protocol freeze + R1/R2 independent human audit preparation",
        "chain_position": "mca_protocol",
        "primary_or_sensitivity": "primary_chain_upstream",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "protocol_implementability_report.json", "SHA256_manifest.txt"],
    },
    "MCA_V1_HUMAN_AUDIT_AGGREGATION_20260906": {
        "package_id": "mca_human_aggregation",
        "role": "R1/R2 submission import, normalization provenance and aggregation; R3 adjudication preparation",
        "chain_position": "mca_human_audit",
        "primary_or_sensitivity": "primary_chain_upstream",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "validation_report.json", "SHA256_manifest.txt"],
    },
    "MCA_V1_FINAL_20260906": {
        "package_id": "mca_final",
        "role": "Final MCA-v1 treatment: R3 adjudication import and frozen Top-8 per topic",
        "chain_position": "mca_final",
        "primary_or_sensitivity": "primary_chain_upstream",
        "treatment_state": "treatment_arm_definition",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "validation_report.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_EXPERIMENT_PREP_20260906": {
        "package_id": "experiment_prep",
        "role": "Experiment preparation: BM25 Top-8 replay, matched contexts, blinding condition mapping, downstream protocol",
        "chain_position": "experiment_prep",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind_by_private_mapping",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "validation_report.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_CODEX_GENERATOR_FREEZE_20260906": {
        "package_id": "generator_freeze_v1",
        "role": "Generator isolation freeze v1 (superseded by v2)",
        "chain_position": "generator_freeze",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_CODEX_GENERATOR_FREEZE_V2_20260906": {
        "package_id": "generator_freeze_v2",
        "role": "Generator isolation freeze v2 (PASS; basis of formal execution)",
        "chain_position": "generator_freeze",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "pre_treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "runtime_capability_report_v2.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_CODEX_EXECUTION_20260906": {
        "package_id": "codex_execution_superseded",
        "role": "Superseded execution workspace (empty directory tree retained)",
        "chain_position": "formal_execution_superseded",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "pre_treatment_blind",
        "immutability": "empty_tree",
        "status_evidence": [],
    },
    "DOWNSTREAM_CODEX_FORMAL_EXECUTION_20260906": {
        "package_id": "formal_execution",
        "role": "24 formal generator outputs (2 topics x 2 tasks x 2 arms x 3 repetitions) with blinded public outputs",
        "chain_position": "formal_execution",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind_public_view",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "formal_execution_manifest.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_HUMAN_EVAL_PACKAGES_20260906": {
        "package_id": "human_eval_preparation",
        "role": "Human evaluation packages (prepared, not executed; superseded downstream by AI judges + qualification track)",
        "chain_position": "human_eval_preparation_not_executed",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_AI_EVAL_GPT_20260915": {
        "package_id": "ai_eval_gpt",
        "role": "Formal blind AI evaluation by GPT judge (24 outputs)",
        "chain_position": "ai_evaluation",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["summary.md", "judge_freeze.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_AI_EVAL_DEEPSEEK_20260915": {
        "package_id": "ai_eval_deepseek",
        "role": "Formal blind AI evaluation by DeepSeek judge (24 outputs)",
        "chain_position": "ai_evaluation",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["summary.md", "judge_freeze.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_AI_EVAL_GLM_20260915": {
        "package_id": "ai_eval_glm",
        "role": "Formal blind AI evaluation by GLM judge (24 outputs)",
        "chain_position": "ai_evaluation",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["summary.md", "judge_freeze.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_AI_JUDGE_AGREEMENT_20260915": {
        "package_id": "judge_agreement_v1",
        "role": "Three-judge blinded agreement analysis v1 (BLOCKED; superseded by V2)",
        "chain_position": "agreement_superseded",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["summary.md", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_AI_JUDGE_AGREEMENT_V2_20260915": {
        "package_id": "judge_agreement_v2",
        "role": "Three-judge blinded agreement analysis v2 (COMPLETE; identity alignment 24/144/432)",
        "chain_position": "agreement",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["summary.md", "source_verification.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_PRO_BLIND_AUDIT_PACKAGE_20260916": {
        "package_id": "pro_targeted_audit",
        "role": "Targeted Pro audit package (25 claim targets; sensitivity reviewer, not a fourth judge)",
        "chain_position": "sensitivity_audit_targeted",
        "primary_or_sensitivity": "sensitivity",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["README.md", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_PRE_UNBLINDING_CLOSURE_20260916": {
        "package_id": "pre_unblinding_closure",
        "role": "Pre-unblinding closure: rule binding, blind audit registration, analysis policy freeze (STATUS BLOCKED by design)",
        "chain_position": "pre_unblinding",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind_at_creation",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["FINAL_CLOSURE_REPORT.md", "FREEZE_MANIFEST.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_PRE_UNBLINDING_AUTHORITY_RECOVERY_20260916": {
        "package_id": "authority_recovery",
        "role": "Amendment authority recovery (Outcome C; proposed amendment DRAFT_NOT_EFFECTIVE)",
        "chain_position": "pre_unblinding_authority",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_blind",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["AUTHORITY_RECOVERY_REPORT.md", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_PRE_UNBLINDING_AUTHORIZATION_APPROVED_20260916": {
        "package_id": "unblinding_authorization",
        "role": "Narrow scientific-analysis authorization (APPROVED_EFFECTIVE; Gate 1 not authorized)",
        "chain_position": "unblinding_authorization",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_aware_process_control",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["FINAL_AUTHORIZATION_REPORT.md", "APPROVAL_RECORD.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_SCIENTIFIC_UNBLINDED_ANALYSIS_20260916": {
        "package_id": "unblinded_analysis",
        "role": "Formal judge-specific first-look unblinded analysis (frozen first look)",
        "chain_position": "first_look_analysis",
        "primary_or_sensitivity": "primary_chain",
        "treatment_state": "treatment_aware",
        "immutability": "frozen_with_manifest",
        "status_evidence": ["SCIENTIFIC_RESULT_REPORT.md", "FIRST_LOOK_FREEZE.json", "SHA256_manifest.txt"],
    },
    "DOWNSTREAM_HUMAN_REVIEWER_QUALIFICATION_V1_20260918": {
        "package_id": "reviewer_qualification_v1",
        "role": "Synthetic-only human reviewer qualification pack V1 (not a formal experiment evaluation)",
        "chain_position": "human_reviewer_qualification_parallel",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "synthetic_no_treatment",
        "immutability": "package_with_manifests",
        "status_evidence": ["README.md", "QA_REPORT.json"],
    },
    "DOWNSTREAM_HUMAN_REVIEWER_QUALIFICATION_V1_1_20260918": {
        "package_id": "reviewer_qualification_v1_1",
        "role": "Synthetic-only human reviewer qualification pack V1.1 (retest form; parallel track)",
        "chain_position": "human_reviewer_qualification_parallel",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "synthetic_no_treatment",
        "immutability": "package_with_manifests",
        "status_evidence": ["README.md", "QA_REPORT.json"],
    },
    "SRTP_MEETING_PREP_20260919": {
        "package_id": "meeting_prep",
        "role": "Meeting preparation artifacts and provenance map (report-only)",
        "chain_position": "reporting",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "treatment_aware",
        "immutability": "report_only",
        "status_evidence": ["00_START_HERE.md"],
    },
    "SRTP_Production_Blueprint_20260915": {
        "package_id": "production_blueprint",
        "role": "Rendered SRTP learning book / production blueprint (report-only deliverable)",
        "chain_position": "reporting_supporting",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "treatment_aware",
        "immutability": "report_only",
        "status_evidence": ["srtp_learning_book/README.md"],
    },
    "rcp_deepseek_runner_tools": {
        "package_id": "rcp_runner_tools",
        "role": "Runner tooling for DeepSeek screening execution (supporting tools)",
        "chain_position": "supporting_tools",
        "primary_or_sensitivity": "supporting",
        "treatment_state": "pre_treatment_blind",
        "immutability": "working_tools",
        "status_evidence": [],
    },
}

# The full Pro sensitivity evaluation lives in a supplement ZIP outside the
# evidence root (referenced by meeting-prep SOURCE_MAP as S14/S15/S16).
SUPPLEMENT_PACKAGE = {
    "package_id": "meeting_supplement_pro_full",
    "logical_location": "download/SRTP_MEETING_LATEST_SUPPLEMENT_20260919.zip",
    "role": "Full Pro blind audit of all 24 outputs / 144 claims + post-hoc measurement diagnostics (SENSITIVITY_EVALUATOR; not a frozen primary judge)",
    "chain_position": "post_hoc_sensitivity_full",
    "primary_or_sensitivity": "sensitivity",
    "treatment_state": "treatment_blind_at_creation_schema_missing",
    "immutability": "zip_archive_report_only",
    "status_evidence": ["README.md", "PRO_FULL_BLIND_AUDIT_REPORT.md", "SRTP_Measurement_Validity_Audit_20260918.md"],
}

FORMAL_CHAIN_PACKAGES = {
    "experiment_prep",
    "generator_freeze_v2",
    "formal_execution",
    "ai_eval_gpt",
    "ai_eval_deepseek",
    "ai_eval_glm",
    "judge_agreement_v2",
    "pre_unblinding_closure",
    "unblinding_authorization",
    "unblinded_analysis",
    "mca_final",
    "mca_human_aggregation",
    "mca_protocol_audit",
    "rcp_integration",
}


def _declared_status(path: Path) -> str:
    """Extract a declared status string from a report file's head."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    head = "\n".join(text.splitlines()[:60])
    for marker in ("STATUS = ", "Status: ", "status: ", "**STATUS** = ", "STATUS="):
        for line in head.splitlines():
            stripped = line.strip()
            if stripped.startswith(marker):
                return stripped[:120]
    for line in head.splitlines():
        if line.strip().startswith(("COMPLETE", "BLOCKED", "APPROVED_EFFECTIVE", "PASS")):
            return line.strip()[:120]
    return ""


def discover_packages(evidence_root: Path) -> list[dict]:
    """Scan the evidence root and describe every evidence package found."""
    evidence_root = Path(evidence_root)
    known_dirs = {entry.name for entry in evidence_root.iterdir() if entry.is_dir()}
    rows = []
    for dir_name, meta in sorted(PACKAGE_ROLE_TABLE.items()):
        package_dir = evidence_root / dir_name
        if not package_dir.exists():
            rows.append({"package_id": meta["package_id"], "directory": dir_name, "present": False})
            continue
        file_count = 0
        total_bytes = 0
        sha_manifest = package_dir / "SHA256_manifest.txt"
        evidence_statuses = []
        for r, _dirs, files in os.walk(package_dir):
            for f in files:
                fp = Path(r) / f
                file_count += 1
                try:
                    total_bytes += fp.stat().st_size
                except OSError:
                    pass
        for rel in meta["status_evidence"]:
            fp = package_dir / rel
            if fp.exists():
                status = _declared_status(fp) if fp.suffix in {".md", ".txt"} else _declared_status(fp)
                evidence_statuses.append({"file": rel, "declared": status})
        mtime = datetime.datetime.fromtimestamp(package_dir.stat().st_mtime).isoformat(timespec="minutes")
        rows.append(
            {
                "package_id": meta["package_id"],
                "directory": dir_name,
                "present": True,
                "role": meta["role"],
                "chain_position": meta["chain_position"],
                "in_formal_dependency_chain": meta["package_id"] in FORMAL_CHAIN_PACKAGES,
                "primary_or_sensitivity_or_supporting": meta["primary_or_sensitivity"],
                "treatment_blind_or_aware": meta["treatment_state"],
                "immutability": meta["immutability"],
                "observed_dir_mtime": mtime,
                "file_count": file_count,
                "total_bytes": total_bytes,
                "has_sha256_manifest": sha_manifest.exists(),
                "source_bytes_inspected": "inventory_level_only_manifests_and_reports",
                "status_evidence_files": evidence_statuses,
                "evidence_strength": (
                    "frozen_manifest_bytes_verifiable" if sha_manifest.exists() else "report_assertion_only"
                ),
            }
        )
    unknown = sorted(known_dirs - set(PACKAGE_ROLE_TABLE))
    return rows, unknown


def build_inventory(evidence_root: Path, supplement_zip: Path | None) -> dict:
    rows, unknown_dirs = discover_packages(evidence_root)
    supplement_row = dict(SUPPLEMENT_PACKAGE)
    supplement_path = Path(supplement_zip) if supplement_zip else None
    supplement_row["present"] = bool(supplement_path and supplement_path.exists())
    if supplement_row["present"]:
        if supplement_path.is_dir():
            pro = next(supplement_path.glob("PRO_FULL_BLIND_AUDIT_144.json"), None)
            supplement_row["zip_sha256"] = f"extracted-dir:{sha256_file(pro)}" if pro else "extracted-dir:no-pro-json"
            supplement_row["zip_bytes"] = sum(p.stat().st_size for p in supplement_path.iterdir() if p.is_file())
        else:
            supplement_row["zip_sha256"] = sha256_file(supplement_path)
            supplement_row["zip_bytes"] = supplement_path.stat().st_size
    return {
        "schema_version": "1.0",
        "generated_by": "downstream_measurement.inventory",
        "evidence_root_logical_name": "srtp_mvp_external_root",
        "packages": rows,
        "supplement_package": supplement_row,
        "unknown_top_level_directories": unknown_dirs,
        "notes": [
            "roles assigned from in-package README/report/manifest provenance (status_evidence_files)",
            "rcp_screening_codex_ultra is a sensitivity re-run, never a sixth independent model or Primary vote",
            "pro full blind audit is post-hoc SENSITIVITY_EVALUATOR data, excluded from primary three-judge aggregates by construction",
        ],
    }


def persist_inventory(inventory: dict, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    (output_dir / "inventory").mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "inventory" / "evidence_inventory.json", inventory)
    flat_rows = []
    for row in inventory["packages"]:
        flat = {k: v for k, v in row.items() if k != "status_evidence_files"}
        flat["status_evidence"] = "; ".join(
            f"{e['file']}=>{e['declared']}" for e in row.get("status_evidence_files", [])
        )
        flat_rows.append(flat)
    supp = inventory["supplement_package"]
    flat_rows.append(
        {
            "package_id": supp["package_id"],
            "directory": supp["logical_location"],
            "present": supp["present"],
            "role": supp["role"],
            "chain_position": supp["chain_position"],
            "in_formal_dependency_chain": False,
            "primary_or_sensitivity_or_supporting": supp["primary_or_sensitivity"],
            "treatment_blind_or_aware": supp["treatment_state"],
            "immutability": supp["immutability"],
            "observed_dir_mtime": "",
            "file_count": "",
            "total_bytes": supp.get("zip_bytes", ""),
            "has_sha256_manifest": False,
            "source_bytes_inspected": "zip_members_verified",
            "status_evidence": "; ".join(supp["status_evidence"]),
            "evidence_strength": "zip_bytes_verifiable",
        }
    )
    header = list(flat_rows[0].keys())
    write_csv(output_dir / "inventory" / "evidence_inventory.csv", header, flat_rows)
