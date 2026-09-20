"""Phase G: mechanical decomposition of the U construct.

U_original = A AND S AND C AND N over the first six submitted units.
This module counts component failures and their exclusive combinations, and
checks the data-specific identity U_original + E_f + B = 6 where
B = units passing S,C,N but failing A, and E_f = units failing (S AND C AND N).
"""
from __future__ import annotations

from collections import Counter

FIRST_N_UNITS = 6


def _unit_fails(unit: dict) -> set[str]:
    fails = set()
    if unit["atomic"] is not True:
        fails.add("A")
    if unit["support"] != "SUPPORTED":
        fails.add("S")
    if unit["scope"] != "IN_SCOPE":
        fails.add("C")
    if unit["redundancy"] != "NONREDUNDANT":
        fails.add("N")
    return fails


def decompose_output(units: list[dict]) -> dict:
    units = sorted(units, key=lambda u: u["appearance_index"])[:FIRST_N_UNITS]
    combo_counter: Counter = Counter()
    u_count = 0
    b_count = 0
    e_f_count = 0
    for unit in units:
        fails = _unit_fails(unit)
        if not fails:
            u_count += 1
            combo_counter["ALL_PASS"] += 1
            continue
        combo_counter["+".join(sorted(fails))] += 1
        if fails == {"A"}:
            b_count += 1
        if fails & {"S", "C", "N"}:
            e_f_count += 1
    return {
        "U_original": u_count,
        "B_atomic_only_failure": b_count,
        "E_f_fail_SCN": e_f_count,
        "identity_holds": u_count + b_count + e_f_count == len(units),
        "failure_combinations": dict(combo_counter),
    }


def build_decomposition(registry: dict) -> dict:
    claim_judgements = registry["claim_judgements"]
    unit_index: dict[tuple[str, str], list[dict]] = {}
    for unit in claim_judgements:
        unit_index.setdefault((unit["evaluator"], unit["output_id"]), []).append(unit)
    per_output = []
    per_evaluator_arm = {}
    identity_all = True
    for (evaluator, oid), units in sorted(unit_index.items()):
        decomposed = decompose_output(units)
        run = units[0]
        per_output.append({
            "evaluator": evaluator, "role": run["role"], "output_id": oid,
            "topic_id": run["topic_id"], "task_id": run["task_id"], "arm": run["arm"],
            "repetition": run["repetition"], **decomposed,
        })
        identity_all = identity_all and decomposed["identity_holds"]
        key = (evaluator, run["arm"])
        bucket = per_evaluator_arm.setdefault(key, Counter())
        for combo, count in decomposed["failure_combinations"].items():
            bucket[combo] += count
        bucket["U_original_total"] += decomposed["U_original"]
        bucket["B_total"] += decomposed["B_atomic_only_failure"]
    component_failures = {}
    for (evaluator, oid), units in sorted(unit_index.items()):
        run = units[0]
        for unit in sorted(units, key=lambda u: u["appearance_index"])[:FIRST_N_UNITS]:
            for component in _unit_fails(unit):
                key = (evaluator, run["arm"], component)
                component_failures[key] = component_failures.get(key, 0) + 1
    return {
        "schema_version": "1.0",
        "status": "DIAGNOSTIC DECOMPOSITION; not a new endpoint",
        "per_output": per_output,
        "per_evaluator_arm_failure_combinations": {
            f"{ev}|{arm}": dict(counter) for (ev, arm), counter in sorted(per_evaluator_arm.items())
        },
        "component_failures_by_evaluator_arm": {
            f"{ev}|{arm}|{comp}": count for (ev, arm, comp), count in sorted(component_failures.items())
        },
        "identity_check": {
            "statement": "U_original + B + E_f == 6 per output, where B = S,C,N pass with atomic failure, E_f = fails (S AND C AND N)",
            "holds_for_all_outputs": identity_all,
            "classification": "DATA-SPECIFIC IDENTITY (partition of first-six units), not a general theorem about the metric",
        },
    }
