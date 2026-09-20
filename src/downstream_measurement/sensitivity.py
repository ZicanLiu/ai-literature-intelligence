"""Phase H: evaluator sensitivity analysis (three primary judges + Full Pro).

Agreement statistics deliberately avoid a misleading kappa when a rater is
degenerate (all-same labels): we then report raw agreement, the contingency
table and prevalence instead of a kappa number.
"""
from __future__ import annotations

from collections import Counter

from .first_look import output_score_rows


def _joint_eligibility(unit: dict) -> str:
    passes = (unit["atomic"] is True and unit["support"] == "SUPPORTED"
              and unit["scope"] == "IN_SCOPE" and unit["redundancy"] == "NONREDUNDANT")
    return "PASS" if passes else "FAIL"


def unit_table(claim_judgements: list[dict]) -> dict[tuple[str, str, int], dict]:
    table = {}
    for unit in claim_judgements:
        table[(unit["evaluator"], unit["output_id"], unit["appearance_index"])] = unit
    return table


def pairwise_agreement(table: dict, evaluator_a: str, evaluator_b: str, field_fn) -> dict:
    units_a = {k[1:]: table[k] for k in table if k[0] == evaluator_a}
    units_b = {k[1:]: table[k] for k in table if k[0] == evaluator_b}
    shared = sorted(units_a.keys() & units_b.keys())
    if not shared:
        return {"pair": f"{evaluator_a}|{evaluator_b}", "n": 0, "status": "NO_OVERLAP"}
    labels_a = [field_fn(units_a[k]) for k in shared]
    labels_b = [field_fn(units_b[k]) for k in shared]
    agree = sum(a == b for a, b in zip(labels_a, labels_b))
    contingency = Counter(zip(labels_a, labels_b))
    marginal_a = Counter(labels_a)
    marginal_b = Counter(labels_b)
    degenerate = len(marginal_a) == 1 or len(marginal_b) == 1
    result = {
        "pair": f"{evaluator_a}|{evaluator_b}",
        "n": len(shared),
        "raw_agreement": agree / len(shared),
        "contingency": {f"{a}->{b}": count for (a, b), count in sorted(contingency.items())},
        "prevalence_a": dict(sorted(marginal_a.items())),
        "prevalence_b": dict(sorted(marginal_b.items())),
        "label_set_a": sorted(marginal_a),
        "label_set_b": sorted(marginal_b),
    }
    if degenerate:
        result["kappa"] = None
        result["kappa_status"] = "NOT_COMPUTED_DEGENERATE_MARGINAL (constant-label rater; kappa would be misleading)"
    else:
        categories = sorted(set(marginal_a) | set(marginal_b))
        n = len(shared)
        po = agree / n
        pe = sum((marginal_a[c] / n) * (marginal_b[c] / n) for c in categories)
        result["kappa"] = None if pe == 1 else (po - pe) / (1 - pe)
        result["kappa_status"] = "COMPUTED"
    return result


def build_sensitivity(registry: dict, reproduction: dict) -> dict:
    claim_judgements = registry["claim_judgements"]
    table = unit_table(claim_judgements)
    evaluators = sorted({k[0] for k in table})
    fields = {
        "joint_U_eligibility": _joint_eligibility,
        "atomic": lambda u: str(u["atomic"]),
        "support": lambda u: u["support"],
        "scope": lambda u: u["scope"],
        "redundancy": lambda u: u["redundancy"],
    }
    agreement = []
    for field_name, field_fn in fields.items():
        for i, evaluator_a in enumerate(evaluators):
            for evaluator_b in evaluators[i + 1:]:
                row = pairwise_agreement(table, evaluator_a, evaluator_b, field_fn)
                row["field"] = field_name
                agreement.append(row)

    label_distributions = []
    for field_name, field_fn in fields.items():
        for evaluator in evaluators:
            units = [table[k] for k in table if k[0] == evaluator]
            label_distributions.append({
                "evaluator": evaluator, "field": field_name,
                "distribution": dict(sorted(Counter(field_fn(u) for u in units).items())),
                "n": len(units),
            })

    disagreement_slices = []
    for evaluator_a in evaluators:
        for evaluator_b in evaluators[evaluators.index(evaluator_a) + 1:]:
            units_a = {k[1:]: table[k] for k in table if k[0] == evaluator_a}
            units_b = {k[1:]: table[k] for k in table if k[0] == evaluator_b}
            for unit_key in sorted(units_a.keys() & units_b.keys()):
                unit = units_a[unit_key]
                other = units_b[unit_key]
                if _joint_eligibility(unit) != _joint_eligibility(other):
                    disagreement_slices.append({
                        "pair": f"{evaluator_a}|{evaluator_b}", "output_id": unit_key[0],
                        "appearance_index": unit_key[1], "topic_id": unit["topic_id"],
                        "task_id": unit["task_id"], "arm": unit["arm"],
                        "repetition": unit["repetition"],
                        "labels_a": {f: fields[f](unit) for f in fields},
                        "labels_b": {f: fields[f](other) for f in fields},
                    })
    slice_counts = Counter()
    for row in disagreement_slices:
        slice_counts[(row["pair"], row["topic_id"])] += 1
        slice_counts[(row["pair"], f"task_{row['task_id']}")] += 1
        slice_counts[(row["pair"], f"arm_{row['arm']}")] += 1
        slice_counts[(row["pair"], f"slot_{row['appearance_index']}")] += 1

    contrast_rows = []
    for role_key in ("primary", "sensitivity"):
        for evaluator, agg in sorted(reproduction.get(role_key, {}).items()):
            if "macro" not in agg:
                contrast_rows.append({
                    "evaluator": evaluator,
                    "role": "PRIMARY_JUDGE" if role_key == "primary" else "SENSITIVITY_EVALUATOR",
                    "status": agg.get("status", "OK"),
                })
                continue
            contrast_rows.append({
                "evaluator": evaluator,
                "role": "PRIMARY_JUDGE" if role_key == "primary" else "SENSITIVITY_EVALUATOR",
                "BM25_mean_U": float(agg["macro"]["BM25_mean_U"]),
                "MCA_mean_U": float(agg["macro"]["MCA_mean_U"]),
                "Delta_U": float(agg["macro"]["Delta_U"]),
                "BM25_mean_E": float(agg["macro"]["BM25_mean_E"]),
                "MCA_mean_E": float(agg["macro"]["MCA_mean_E"]),
                "Delta_E": float(agg["macro"]["Delta_E"]),
                "U_direction": agg["macro"]["U_direction"],
                "E_direction": agg["macro"]["E_direction"],
            })
    scores = output_score_rows(claim_judgements, registry["error_events"])
    by_arm = {}
    for row in scores:
        key = (row["evaluator"], row["arm"])
        bucket = by_arm.setdefault(key, {"U_sum": 0, "E_sum": 0, "n": 0})
        bucket["U_sum"] += row["useful_information_slots"]
        bucket["E_sum"] += row["substantive_error_count"]
        bucket["n"] += 1
    return {
        "schema_version": "1.0",
        "status": "DESCRIPTIVE SENSITIVITY ANALYSIS; Full Pro is SENSITIVITY_EVALUATOR, never a fourth primary judge",
        "evaluator_label_distributions": label_distributions,
        "evaluator_arm_means": {
            f"{ev}|{arm}": {"mean_U": b["U_sum"] / b["n"], "mean_E": b["E_sum"] / b["n"], "n_outputs": b["n"]}
            for (ev, arm), b in sorted(by_arm.items())
        },
        "treatment_contrasts": contrast_rows,
        "pairwise_agreement": agreement,
        "joint_eligibility_disagreement_slices": {
            "total_disagreements": len(disagreement_slices),
            "by_pair_topic_task_arm_slot": {f"{pair}|{dim}": count for (pair, dim), count in sorted(slice_counts.items())},
        },
        "disagreement_examples": disagreement_slices[:40],
    }
