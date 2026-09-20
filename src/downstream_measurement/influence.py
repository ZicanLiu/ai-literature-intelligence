"""Phase I: descriptive influence / concentration diagnostics.

Leave-one-out recomputation is descriptive: repetitions are not independent
samples and no inferential claim is made.
"""
from __future__ import annotations

import re
from collections import Counter
from fractions import Fraction

from .first_look import aggregate, output_score_rows


def equal_cell_delta_allow_variable_reps(scores: list[dict], evaluator: str,
                                          field: str = "useful_information_slots",
                                          cells: list[tuple[str, str]] | None = None):
    """Frozen first-look estimand under output exclusion.

    Each Topic x Task cell contrast = mean over that cell's available
    repetitions per arm (>= 1 required); the macro keeps EQUAL weight over
    the four cells (or over the explicitly provided `cells`). On complete
    data this equals the frozen macro exactly; after leaving one output out
    the deleted output's cell-arm mean uses 2 reps while cell weighting
    stays 1/4, preserving the original estimand.
    """
    own = [r for r in scores if r["evaluator"] == evaluator]
    if cells is None:
        cells = sorted({(r["topic_id"], r["task_id"]) for r in own})
    contrasts = []
    for topic, task in cells:
        cell_contrast = None
        arm_means = {}
        for arm in ("BM25", "MCA"):
            values = [Fraction(r[field]) for r in own
                      if (r["topic_id"], r["task_id"], r["arm"]) == (topic, task, arm)]
            if not values:
                break
            arm_means[arm] = sum(values) / len(values)
        if len(arm_means) != 2:
            return None
        contrasts.append(arm_means["MCA"] - arm_means["BM25"])
    if not contrasts:
        return None
    return sum(contrasts) / len(contrasts)


def leave_one_out(scores: list[dict], evaluator: str, field: str = "useful_information_slots") -> list[dict]:
    """Leave-one-output-out under the equal-cell estimand."""
    own = [r for r in scores if r["evaluator"] == evaluator]
    all_cells = sorted({(r["topic_id"], r["task_id"]) for r in own})
    baseline = equal_cell_delta_allow_variable_reps(scores, evaluator, field, all_cells)
    rows = []
    for excluded in own:
        remainder = [r for r in scores if r is not excluded]
        recomputed = equal_cell_delta_allow_variable_reps(remainder, evaluator, field, all_cells)
        rows.append({
            "evaluator": evaluator,
            "endpoint": "U" if field == "useful_information_slots" else "E",
            "estimand": "equal-cell macro, variable reps allowed",
            "excluded_output_id": excluded["output_id"],
            "excluded_topic": excluded["topic_id"], "excluded_task": excluded["task_id"],
            "excluded_arm": excluded["arm"], "excluded_repetition": excluded["repetition"],
            "macro_after_exclusion": None if recomputed is None else float(recomputed),
            "baseline_macro": None if baseline is None else float(baseline),
            "change": None if recomputed is None or baseline is None else float(recomputed - baseline),
        })
    return rows


def leave_one_cell_out(scores: list[dict], evaluator: str) -> list[dict]:
    """Leave-one-cell-out: equal weight over the REMAINING three cells."""
    own = [r for r in scores if r["evaluator"] == evaluator]
    all_cells = sorted({(r["topic_id"], r["task_id"]) for r in own})
    baseline = equal_cell_delta_allow_variable_reps(scores, evaluator, cells=all_cells)
    rows = []
    for topic, task in all_cells:
        remaining_cells = [c for c in all_cells if c != (topic, task)]
        recomputed = equal_cell_delta_allow_variable_reps(scores, evaluator, cells=remaining_cells)
        rows.append({
            "evaluator": evaluator, "excluded_cell": f"{topic}|{task}",
            "estimand": "equal weight over remaining 3 cells",
            "macro_after_exclusion": None if recomputed is None else float(recomputed),
            "change": None if recomputed is None or baseline is None else float(recomputed - baseline),
        })
    return rows


def claim_slot_contribution(registry: dict) -> list[dict]:
    rows = []
    table = {}
    for unit in registry["claim_judgements"]:
        table.setdefault((unit["evaluator"], unit["appearance_index"], unit["arm"]), []).append(unit)
    for (evaluator, slot, arm), units in sorted(table.items()):
        eligible = sum(
            1 for u in units
            if u["atomic"] is True and u["support"] == "SUPPORTED"
            and u["scope"] == "IN_SCOPE" and u["redundancy"] == "NONREDUNDANT"
        )
        rows.append({
            "evaluator": evaluator, "appearance_index": slot, "arm": arm,
            "n_units": len(units), "first_six_eligible": eligible,
            "eligible_rate": eligible / len(units),
        })
    return rows


_TEMPLATE_STRIP = re.compile(r"[^a-z]+")


def template_key(claim_text: str) -> str:
    """Declared lexical template rule: first 12 normalized alpha words.

    LEXICAL DIAGNOSTIC ONLY — this is not semantic clustering and carries no
    claim about meaning equivalence; it merely groups claims sharing an
    identical normalized lexical prefix.
    """
    normalized = _TEMPLATE_STRIP.sub(" ", claim_text.lower()).strip()
    words = normalized.split()
    return " ".join(words[:12])


def claim_template_concentration(registry: dict) -> dict:
    """Exact claim-text repetition over GENERATOR claims (counting unit = one
    submitted claim, not one evaluator judgement), plus a declared lexical
    template diagnostic."""
    claims = registry["claims"]
    exact_counts = Counter(claim["claim_text_sha256"] for claim in claims)
    repeated_exact = {digest: count for digest, count in exact_counts.items() if count > 1}
    template_counts = Counter(template_key(claim.get("claim_text", "")) for claim in claims)
    repeated_templates = {key: count for key, count in template_counts.items() if count > 1}
    return {
        "status": "DESCRIPTIVE",
        "counting_unit": "generator output claim (each of the 144 submitted claims counted once)",
        "exact_text_repetition": {
            "distinct_claim_texts": len(exact_counts),
            "claim_texts_appearing_more_than_once": len(repeated_exact),
            "repeated_counts": dict(sorted(repeated_exact.items(), key=lambda kv: -kv[1])[:20]),
        },
        "lexical_template_diagnostic": {
            "rule": "first 12 normalized alpha-only words, lowercased; LEXICAL DIAGNOSTIC ONLY, not semantic clustering",
            "distinct_templates": len(template_counts),
            "templates_appearing_more_than_once": len(repeated_templates),
            "top_templates": [
                {"template": key[:60], "count": count}
                for key, count in sorted(repeated_templates.items(), key=lambda kv: -kv[1])[:10]
            ],
        },
        "note": "exact-hash equality and lexical-prefix grouping are string-level diagnostics; evaluator repeated "
                "measurements of the same claim are intentionally NOT counted here",
    }


def build_influence(registry: dict) -> dict:
    claim_judgements = registry["claim_judgements"]
    scores = output_score_rows(claim_judgements, registry["error_events"])
    evaluators = sorted({r["evaluator"] for r in scores})
    loo = []
    for evaluator in evaluators:
        loo.extend(leave_one_out(scores, evaluator))
        loo.extend(leave_one_out(scores, evaluator, field="substantive_error_count"))
    cell_loo = []
    for evaluator in evaluators:
        cell_loo.extend(leave_one_cell_out(scores, evaluator))
    per_output_contrast = []
    for evaluator in evaluators:
        own = {r["output_id"]: r for r in scores if r["evaluator"] == evaluator}
        by_cell = {}
        for row in own.values():
            by_cell.setdefault((row["topic_id"], row["task_id"]), {})[row["arm"]] = row
        for (topic, task), arms in sorted(by_cell.items()):
            for rep in (1, 2, 3):
                mca = next((r for r in own.values() if r["topic_id"] == topic and r["task_id"] == task
                            and r["arm"] == "MCA" and r["repetition"] == rep), None)
                bm25 = next((r for r in own.values() if r["topic_id"] == topic and r["task_id"] == task
                             and r["arm"] == "BM25" and r["repetition"] == rep), None)
                if mca and bm25:
                    per_output_contrast.append({
                        "evaluator": evaluator, "topic_id": topic, "task_id": task, "repetition": rep,
                        "U_mca": mca["useful_information_slots"], "U_bm25": bm25["useful_information_slots"],
                        "U_diff": mca["useful_information_slots"] - bm25["useful_information_slots"],
                        "E_mca": mca["substantive_error_count"], "E_bm25": bm25["substantive_error_count"],
                        "E_diff": mca["substantive_error_count"] - bm25["substantive_error_count"],
                    })
    return {
        "schema_version": "1.0",
        "status": "DESCRIPTIVE INFLUENCE DIAGNOSTICS; leave-one-out rows are not independent inferential samples",
        "leave_one_output_out": loo,
        "leave_one_cell_out": cell_loo,
        "claim_slot_contribution": claim_slot_contribution(registry),
        "claim_text_repetition": claim_template_concentration(registry),
        "per_repetition_arm_contrasts": per_output_contrast,
    }
