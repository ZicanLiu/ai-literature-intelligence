"""Phase E: independent first-look reproduction from canonical judgements.

Metric semantics (reimplemented from the frozen protocol, not imported):
- U per output = count of first-six submitted units with
  atomic AND SUPPORTED AND IN_SCOPE AND NONREDUNDANT.
- E per output = number of distinct substantive error event records.
- Cell-arm mean over 3 repetitions; cell contrast MCA - BM25;
  macro = equal-weight mean of the four Topic x Task contrasts.
All aggregation uses exact rational arithmetic.
"""
from __future__ import annotations

from fractions import Fraction

ARMS = ["BM25", "MCA"]
FIRST_N_UNITS = 6
PRIMARY_ROLE = "PRIMARY_JUDGE"


def useful_slots(units: list[dict]) -> int:
    return sum(
        unit["atomic"] is True
        and unit["support"] == "SUPPORTED"
        and unit["scope"] == "IN_SCOPE"
        and unit["redundancy"] == "NONREDUNDANT"
        for unit in units[:FIRST_N_UNITS]
    )


def output_score_rows(claim_judgements: list[dict], error_events: list[dict],
                      evaluator: str | None = None) -> list[dict]:
    """Per evaluator-output U/E with run identity, from canonical rows only."""
    unit_index: dict[tuple[str, str], list[dict]] = {}
    for unit in claim_judgements:
        if evaluator and unit["evaluator"] != evaluator:
            continue
        unit_index.setdefault((unit["evaluator"], unit["output_id"]), []).append(unit)
    event_index: dict[tuple[str, str], list[dict]] = {}
    for event in error_events:
        if evaluator and event["evaluator"] != evaluator:
            continue
        event_index.setdefault((event["evaluator"], event["output_id"]), []).append(event)
    rows = []
    for (ev, oid), units in unit_index.items():
        units_sorted = sorted(units, key=lambda u: u["appearance_index"])
        run = units_sorted[0]
        events = event_index.get((ev, oid), [])
        rows.append({
            "evaluator": ev,
            "output_id": oid,
            "topic_id": run["topic_id"],
            "task_id": run["task_id"],
            "arm": run["arm"],
            "repetition": run["repetition"],
            "useful_information_slots": useful_slots(units_sorted),
            "substantive_error_count": len(events),
            "submitted_claim_count": len(units_sorted),
            "role": run["role"],
        })
    return rows


def aggregate(scores: list[dict], evaluator: str) -> dict:
    """Recompute cell/marginal/macro contrasts for one evaluator."""
    own = [r for r in scores if r["evaluator"] == evaluator]
    topics = sorted({r["topic_id"] for r in own})
    tasks = sorted({r["task_id"] for r in own})
    cells = []
    for topic in topics:
        for task in tasks:
            arm_means = {}
            for arm in ARMS:
                values = [r["useful_information_slots"] for r in own
                          if (r["topic_id"], r["task_id"], r["arm"]) == (topic, task, arm)]
                if len(values) != 3:
                    raise AssertionError(f"cell {topic}/{task}/{arm} has {len(values)} reps, expected 3")
                arm_means[arm] = {"U": Fraction(sum(values), 3),
                                  "E": Fraction(sum(r["substantive_error_count"] for r in own
                                                    if (r["topic_id"], r["task_id"], r["arm"]) == (topic, task, arm)), 3)}
            cells.append({
                "topic_id": topic, "task_id": task,
                "BM25_mean_U": arm_means["BM25"]["U"], "MCA_mean_U": arm_means["MCA"]["U"],
                "BM25_mean_E": arm_means["BM25"]["E"], "MCA_mean_E": arm_means["MCA"]["E"],
                "Delta_U": arm_means["MCA"]["U"] - arm_means["BM25"]["U"],
                "Delta_E": arm_means["MCA"]["E"] - arm_means["BM25"]["E"],
            })
    def _marginal(selector, key_fields):
        selected = [c for c in cells if selector(c)]
        row = dict(key_fields)
        for field in ("BM25_mean_U", "MCA_mean_U", "BM25_mean_E", "MCA_mean_E", "Delta_U", "Delta_E"):
            row[field] = sum(c[field] for c in selected) / len(selected)
        return row

    macro = _marginal(lambda c: True, {"grain": "macro"})
    topic_rows = [_marginal(lambda c, t=t: c["topic_id"] == t, {"grain": "topic", "topic_id": t}) for t in topics]
    task_rows = [_marginal(lambda c, k=k: c["task_id"] == k, {"grain": "task", "task_id": k}) for k in tasks]

    def _direction(value: Fraction) -> str:
        return "MCA_HIGHER" if value > 0 else "MCA_LOWER" if value < 0 else "EQUAL"

    for row in [macro, *topic_rows, *task_rows, *cells]:
        row["U_direction"] = _direction(row["Delta_U"])
        row["E_direction"] = _direction(row["Delta_E"])
    return {"evaluator": evaluator, "cells": cells, "macro": macro,
            "topic_marginals": topic_rows, "task_marginals": task_rows}


def reproduce_first_look(registry: dict) -> dict:
    """Full reproduction for primary judges; sensitivity evaluator reported separately.

    Primary aggregation fails closed on lattice violations. A sensitivity
    evaluator with incomplete coverage is reported as INCOMPLETE_LATTICE
    instead of aborting the whole reproduction.
    """
    claim_judgements = registry["claim_judgements"]
    error_events = registry["error_events"]
    primary_evaluators = sorted({r["evaluator"] for r in claim_judgements if r["role"] == PRIMARY_ROLE})
    sensitivity_evaluators = sorted({r["evaluator"] for r in claim_judgements if r["role"] != PRIMARY_ROLE})
    scores = output_score_rows(claim_judgements, error_events)
    sensitivity_results = {}
    for evaluator in sensitivity_evaluators:
        try:
            sensitivity_results[evaluator] = aggregate(scores, evaluator)
        except AssertionError as error:
            sensitivity_results[evaluator] = {"status": "INCOMPLETE_LATTICE", "error": str(error)}
    return {
        "primary": {ev: aggregate(scores, ev) for ev in primary_evaluators},
        "sensitivity": sensitivity_results,
        "roles": {"primary_evaluators": primary_evaluators, "sensitivity_evaluators": sensitivity_evaluators},
    }


FROZEN_COMPARISON_FIELDS = (
    "BM25_mean_U", "MCA_mean_U", "Delta_U",
    "BM25_mean_E", "MCA_mean_E", "Delta_E",
    "U_direction", "E_direction",
)
FROZEN_JUDGE_ROSTER = ("GPT", "DeepSeek", "GLM")


def compare_to_frozen(reproduction: dict, frozen_macro_csv: str) -> list[dict]:
    """Compare reproduced macro against the frozen first-look table (no hardcoded values).

    Every semantic field present in the frozen table is compared:
    arm means, deltas and directions for both endpoints (8 fields x 3 judges
    = 24 comparisons), plus structural columns that can be independently
    rebuilt (n_cells / n_observed_per_arm). The judge roster must be exactly
    the frozen three. Numeric equality is asserted at the frozen artifact's
    own serialisation precision (double, tolerance 1e-12).
    """
    import csv
    import io

    reader = csv.DictReader(io.StringIO(frozen_macro_csv.lstrip("\ufeff")))
    comparison = []
    frozen_judges = []
    numeric_fields = {"BM25_mean_U", "MCA_mean_U", "Delta_U", "BM25_mean_E", "MCA_mean_E", "Delta_E"}
    text_fields = {"U_direction", "E_direction"}
    structural_fields = {"n_cells"}
    for row in reader:
        judge = row["judge"]
        frozen_judges.append(judge)
        rep = reproduction["primary"].get(judge)
        if rep is None:
            comparison.append({"judge": judge, "field": "ROSTER", "status": "MISSING_IN_REPRODUCTION"})
            continue
        macro = rep["macro"]
        for field in FROZEN_COMPARISON_FIELDS:
            if field not in row or row[field] in ("", "NA"):
                continue
            if field in numeric_fields:
                frozen_value = float(row[field].strip())
                reproduced_value = float(macro[field])
                comparison.append({
                    "judge": judge, "field": field,
                    "frozen": row[field].strip(),
                    "reproduced_exact": str(macro[field]),
                    "float_frozen": frozen_value, "float_reproduced": reproduced_value,
                    "match": abs(frozen_value - reproduced_value) <= 1e-12,
                })
            elif field in text_fields:
                comparison.append({
                    "judge": judge, "field": field,
                    "frozen": row[field].strip(), "reproduced": macro[field],
                    "match": row[field].strip() == macro[field],
                })
        for field in sorted(structural_fields & set(row.keys())):
            comparison.append({
                "judge": judge, "field": field,
                "frozen": row[field].strip(), "reproduced": str(len(rep["cells"])),
                "match": row[field].strip() == str(len(rep["cells"])),
            })
    roster_ok = sorted(frozen_judges) == sorted(FROZEN_JUDGE_ROSTER)
    comparison.append({"field": "JUDGE_ROSTER", "frozen": sorted(frozen_judges),
                       "reproduced": sorted(reproduction["primary"]),
                       "match": roster_ok and sorted(reproduction["primary"]) == sorted(FROZEN_JUDGE_ROSTER)})
    return comparison


def assess_frozen_comparison(reproduction: dict, frozen_macro_csv: str | None) -> dict:
    """Check the complete frozen contract without changing endpoint arithmetic.

    A subset of matching fields is not a successful formal reproduction.
    The required multiset is 3 judges x (8 endpoint fields + n_cells), plus
    the exact judge-roster comparison. Diagnostic callers may persist this
    result and continue; formal callers must stop unless status is MATCH.
    """
    import csv
    import io
    from collections import Counter

    expected_keys = {(judge, field) for judge in FROZEN_JUDGE_ROSTER
                     for field in (*FROZEN_COMPARISON_FIELDS, "n_cells")}
    expected_keys.add((None, "JUDGE_ROSTER"))
    result = {"status": "MISSING_SOURCE", "fields_compared": 0,
              "expected_fields": len(expected_keys), "rows": [], "problems": []}
    if frozen_macro_csv is None:
        result["problems"].append("frozen macro CSV missing")
        return result
    header = csv.DictReader(io.StringIO(frozen_macro_csv.lstrip("\ufeff"))).fieldnames or []
    required_columns = ("judge", *FROZEN_COMPARISON_FIELDS, "n_cells")
    bad_columns = [field for field in required_columns if header.count(field) != 1]
    if bad_columns:
        result["problems"].append(f"missing or duplicate frozen columns: {bad_columns}")
    try:
        comparison = compare_to_frozen(reproduction, frozen_macro_csv)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        result["status"] = "INCOMPLETE"
        result["problems"].append(f"invalid frozen comparison: {type(error).__name__}")
        return result
    result["rows"] = comparison
    result["fields_compared"] = sum("match" in row for row in comparison)
    observed_keys = Counter((row.get("judge"), row.get("field")) for row in comparison)
    if observed_keys != Counter(expected_keys):
        result["problems"].append("comparison field set incomplete, duplicated or unexpected")
    if sorted(reproduction.get("primary", {})) != sorted(FROZEN_JUDGE_ROSTER):
        result["problems"].append("primary evaluator roster incomplete or unexpected")
    if result["problems"]:
        result["status"] = "INCOMPLETE"
    else:
        result["status"] = "MATCH" if all(row.get("match") is True for row in comparison) else "MISMATCH"
    return result
