"""Build the reviewable W4 Pilot Query Relevance judged-set draft."""

from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.annotation_tasks import (
    ANNOTATORS,
    ASSIGNMENT_FIELDS,
    CANDIDATE_POOL_FIELDS,
    read_csv_rows,
    sha256_file,
    validate_assignment_invariants,
    write_csv_rows,
)
from src.annotation_validation import validate_annotation_file
from src.w4_benchmark_validation import (
    BENCHMARK_NAME,
    BENCHMARK_VERSION,
    JUDGEMENT_FIELDS,
    PROPOSAL_FIELDS,
    compute_input_set_identity,
    validate_proposal_annotation_provenance,
)


def build_benchmark_draft(
    *,
    project_root: str | Path,
    candidate_pool_path: str | Path,
    assignments_path: str | Path,
    research_queries_path: str | Path,
    source_sample_path: str | Path,
    pool_manifest_path: str | Path,
    annotations_dir: str | Path,
    proposals_path: str | Path,
    output_dir: str | Path,
    reference_year: int = 2026,
    force: bool = False,
) -> dict[str, Path]:
    """Create 60-row draft judgements and a hash-pinned package manifest."""
    root = Path(project_root).resolve()
    output = Path(output_dir).resolve()
    try:
        output.relative_to(root)
    except ValueError as error:
        raise ValueError("benchmark package 必须位于项目目录内。") from error

    paths = {
        "candidate_pool": Path(candidate_pool_path).resolve(),
        "assignments": Path(assignments_path).resolve(),
        "research_queries": Path(research_queries_path).resolve(),
        "source_sample": Path(source_sample_path).resolve(),
        "pool_manifest": Path(pool_manifest_path).resolve(),
        "proposals": Path(proposals_path).resolve(),
        "judgements": output / "judgements.csv",
        "manifest": output / "manifest.json",
    }
    for name in (
        "candidate_pool",
        "assignments",
        "research_queries",
        "source_sample",
        "pool_manifest",
        "proposals",
    ):
        if not paths[name].is_file():
            raise ValueError(f"输入文件不存在：{paths[name]}")
    existing = [
        path.name for path in (paths["judgements"], paths["manifest"]) if path.exists()
    ]
    if existing and not force:
        raise FileExistsError("拒绝覆盖 benchmark draft：" + ", ".join(existing))

    pool_fields, pool_rows = read_csv_rows(paths["candidate_pool"])
    assignment_fields, assignments = read_csv_rows(paths["assignments"])
    if pool_fields != CANDIDATE_POOL_FIELDS:
        raise ValueError("candidate pool 表头与冻结 W4 v0.1 契约不一致。")
    if assignment_fields != ASSIGNMENT_FIELDS:
        raise ValueError("assignments 表头与冻结 W4 v0.1 契约不一致。")
    errors = validate_assignment_invariants(pool_rows, assignments)
    if errors:
        raise ValueError("冻结 assignment 无效：" + "; ".join(errors))

    annotation_paths: dict[str, Path] = {}
    annotation_rows: dict[str, dict[str, dict[str, str]]] = {}
    for slug in ANNOTATORS:
        path = Path(annotations_dir).resolve() / f"{slug}.csv"
        validation_errors = validate_annotation_file(
            annotation_path=path,
            candidate_pool_path=paths["candidate_pool"],
            assignments_path=paths["assignments"],
        )
        if validation_errors:
            raise ValueError(f"原始 annotation {slug} 无效：" + "; ".join(validation_errors))
        _fields, rows = read_csv_rows(path)
        annotation_paths[slug] = path
        annotation_rows[slug] = {row["pair_id"]: row for row in rows}

    proposal_fields, proposal_rows = read_csv_rows(paths["proposals"])
    if proposal_fields != PROPOSAL_FIELDS:
        raise ValueError("adjudication_proposals.csv 表头与复核契约不一致。")
    proposals_by_pair = _proposal_index(proposal_rows)

    pool_by_pair = {row["pair_id"]: row for row in pool_rows}
    assignments_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in assignments:
        assignments_by_pair[row["pair_id"]].append(row)

    judgements: list[dict[str, str]] = []
    disagreement_ids: set[str] = set()
    for pair_id in sorted(pool_by_pair):
        pool_row = pool_by_pair[pair_id]
        pair_assignments = assignments_by_pair[pair_id]
        primary_assignment = next(
            row for row in pair_assignments if row["assignment_role"] == "primary"
        )
        secondary_assignment = next(
            (
                row
                for row in pair_assignments
                if row["assignment_role"] == "secondary"
            ),
            None,
        )
        primary = annotation_rows[primary_assignment["annotator_slug"]][pair_id]
        secondary = (
            annotation_rows[secondary_assignment["annotator_slug"]][pair_id]
            if secondary_assignment is not None
            else None
        )
        row = {
            "pair_id": pair_id,
            "research_query_id": pool_row["research_query_id"],
            "openalex_id": pool_row["openalex_id"],
            "final_label": primary["label"],
            "proposed_label": "",
            "judgement_status": "ready",
            "agreement_status": "single_annotation",
            "judgement_basis": "primary_annotation",
            "primary_annotator": primary["annotator"],
            "primary_label": primary["label"],
            "primary_ai_assistance": primary["ai_assistance"],
            "secondary_annotator": "",
            "secondary_label": "",
            "secondary_ai_assistance": "",
            "adjudication_ai_assistance": "",
            "review_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "review_note": "",
            "benchmark_version": BENCHMARK_VERSION,
        }
        if secondary is not None:
            row.update(
                {
                    "secondary_annotator": secondary["annotator"],
                    "secondary_label": secondary["label"],
                    "secondary_ai_assistance": secondary["ai_assistance"],
                }
            )
            if primary["label"] == secondary["label"]:
                row.update(
                    {
                        "agreement_status": "agreement",
                        "judgement_basis": "double_annotation_agreement",
                    }
                )
            else:
                disagreement_ids.add(pair_id)
                proposal = proposals_by_pair.get(pair_id)
                if proposal is None:
                    raise ValueError(f"双标分歧缺少 adjudication proposal：{pair_id}。")
                validate_proposal_annotation_provenance(
                    proposal,
                    pool_row=pool_row,
                    primary=primary,
                    secondary=secondary,
                )
                if proposal["proposal_status"] != "pending_human_review":
                    raise ValueError(
                        f"当前 AI proposal 必须标记 pending_human_review：{pair_id}。"
                    )
                if (
                    proposal["proposed_final_label"] not in {"0", "1", "2"}
                    or not proposal["proposal_reason"].strip()
                    or not proposal["evidence_sources"].strip()
                ):
                    raise ValueError(
                        f"adjudication proposal 必须记录 0/1/2、理由和证据来源：{pair_id}。"
                    )
                row.update(
                    {
                        "final_label": "",
                        "proposed_label": proposal["proposed_final_label"],
                        "judgement_status": "pending_human_review",
                        "agreement_status": "disagreement",
                        "judgement_basis": "ai_adjudication_proposal",
                        "adjudication_ai_assistance": "label_suggestion",
                    }
                )
        judgements.append(row)

    if set(proposals_by_pair) != disagreement_ids:
        raise ValueError(
            "adjudication proposal 必须与双标分歧一一对应："
            f"proposals={sorted(proposals_by_pair)}, disagreements={sorted(disagreement_ids)}。"
        )

    write_csv_rows(paths["judgements"], JUDGEMENT_FIELDS, judgements)
    status_counts = Counter(row["agreement_status"] for row in judgements)
    input_refs = {
        "candidate_pool": _file_ref(paths["candidate_pool"], root, version="w4_pilot_v0.1"),
        "assignments": _file_ref(paths["assignments"], root, version="w4_pilot_v0.1"),
        "research_queries": _file_ref(paths["research_queries"], root, version="w4_pilot_v0.1"),
        "source_sample": _file_ref(paths["source_sample"], root),
        "pool_manifest": _file_ref(paths["pool_manifest"], root, version="w4_pilot_v0.1"),
        "annotations": {
            slug: _file_ref(path, root) for slug, path in annotation_paths.items()
        },
    }
    manifest = {
        "schema_version": "1.0",
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_version": BENCHMARK_VERSION,
        "status": "proposed",
        "display_name": "W4 Pilot Adjudicated Judged Set (draft)",
        "evaluation_target": "query_relevance",
        "label_scheme": {
            "type": "graded_relevance",
            "allowed_values": [0, 1, 2],
        },
        "record_unit": "research_query_id + openalex_id",
        "entity_policy": (
            "record-level Pilot Benchmark; high-confidence same-paper aliases remain "
            "separate frozen v0.1 records"
        ),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_from_git_revision": _git_revision(root),
        "reference_year": reference_year,
        "input_set_identity": compute_input_set_identity(input_refs),
        "parent_package": None,
        "approval": {
            "status": "pending_human_review",
            "approved_by": "",
            "approved_at": "",
            "review_note": "",
            "checklist": {
                "all_disagreements_human_reviewed": False,
                "original_annotation_provenance_verified": False,
                "frozen_input_anchor_verified": False,
                "jiafucheng_provenance_checked": False,
                "parent_draft_reviewed": False,
            },
        },
        "counts": {
            "pair_count": len(judgements),
            "research_query_count": len(
                {row["research_query_id"] for row in judgements}
            ),
            "single_annotation_pairs": status_counts["single_annotation"],
            "agreement_pairs": status_counts["agreement"],
            "disagreement_pairs": status_counts["disagreement"],
            "pending_human_review_pairs": sum(
                row["judgement_status"] == "pending_human_review"
                for row in judgements
            ),
        },
        "inputs": input_refs,
        "artifacts": {
            "judgements": _file_ref(paths["judgements"], root),
            "adjudication_proposals": _file_ref(paths["proposals"], root),
        },
        "annotation_review_provenance": {
            "chenxingyu": {
                "status": "human_confirmed",
                "note": (
                    "The annotator reviewed and confirmed all 15 submitted judgements; "
                    "this factual correction changes no original label."
                ),
            },
            "jiafucheng": {
                "status": "human_judgement_with_recorded_ai_assistance",
                "github_self_confirmation_recorded": False,
                "protocol_review_checklist_required": True,
                "note": (
                    "The labels are human judgements with per-row AI assistance provenance. "
                    "No nonexistent GitHub self-confirmation is asserted."
                ),
            },
        },
        "known_record_aliases": [
            {
                "research_query_id": "rq02_stellar_parameters",
                "pair_ids": ["w4_rq02_002", "w4_rq02_011"],
                "policy": "retain_as_separate_records_in_v0.1",
            },
            {
                "research_query_id": "rq03_spectral_preprocessing",
                "pair_ids": ["w4_rq03_004", "w4_rq03_011"],
                "policy": "retain_as_separate_records_in_v0.1",
            },
        ],
        "promotion_requirements": [
            "independent human review of every pending adjudication proposal",
            "reviewer name, decision, final label and review time recorded",
            "Jia Fucheng provenance confirmation checked without inventing a GitHub record",
            "new approved version directory and hashes created without overwriting this draft",
            "strict benchmark validator passes before formal evaluation",
        ],
    }
    paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        name: path
        for name, path in paths.items()
        if name in {"judgements", "manifest", "proposals"}
    }


def _proposal_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        pair_id = row["pair_id"].strip()
        if not pair_id or pair_id in result:
            raise ValueError("adjudication proposal 的 pair_id 必须非空且唯一。")
        result[pair_id] = row
    return result


def _file_ref(path: Path, root: Path, *, version: str | None = None) -> dict[str, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"benchmark provenance 文件必须位于项目目录：{resolved}") from error
    result = {"path": relative, "sha256": sha256_file(resolved)}
    if version is not None:
        result["version"] = version
    return result


def _git_revision(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None
