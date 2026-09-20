"""Phase J: counterfactual metric sensitivity (DIAGNOSTIC ONLY).

U_original = A*S*C*N (first six units), U_lambda = S*C*N*[A + lambda*(1-A)].
The lambda grid is fixed and transparent; no 'optimal' lambda is searched and
these variants are never new primary endpoints.
"""
from __future__ import annotations

from fractions import Fraction

from .first_look import ARMS, aggregate, output_score_rows

LAMBDA_GRID = [Fraction(0), Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1)]


def unit_score_original(unit: dict) -> Fraction:
    passes = (unit["atomic"] is True and unit["support"] == "SUPPORTED"
              and unit["scope"] == "IN_SCOPE" and unit["redundancy"] == "NONREDUNDANT")
    return Fraction(1) if passes else Fraction(0)


def unit_score_variant(unit: dict, variant: str, lam: Fraction | None = None) -> Fraction:
    a = unit["atomic"] is True
    s = unit["support"] == "SUPPORTED"
    c = unit["scope"] == "IN_SCOPE"
    n = unit["redundancy"] == "NONREDUNDANT"
    if variant == "U_original":
        return Fraction(1) if (a and s and c and n) else Fraction(0)
    if variant == "U_without_atomicity":
        return Fraction(1) if (s and c and n) else Fraction(0)
    if variant == "U_without_scope":
        return Fraction(1) if (a and s and n) else Fraction(0)
    if variant == "U_support_scope":
        return Fraction(1) if (s and c) else Fraction(0)
    if variant == "U_support_only":
        return Fraction(1) if s else Fraction(0)
    if variant == "U_lambda":
        if not (s and c and n):
            return Fraction(0)
        return Fraction(1) if a else lam
    raise ValueError(variant)


VARIANTS = ["U_original", "U_without_atomicity", "U_without_scope", "U_support_scope", "U_support_only"]


def _aggregate_variant(unit_index: dict, evaluator: str, variant: str, lam: Fraction | None) -> dict:
    cell_values: dict[tuple, dict[str, list[Fraction]]] = {}
    for (ev, oid), units in unit_index.items():
        if ev != evaluator:
            continue
        run = units[0]
        score = sum((unit_score_variant(u, variant, lam) for u in sorted(units, key=lambda x: x["appearance_index"])[:6]), Fraction(0))
        cell_values.setdefault((run["topic_id"], run["task_id"]), {}).setdefault(run["arm"], []).append(score)
    deltas = []
    for cell, arms in sorted(cell_values.items()):
        for arm in ARMS:
            if arm not in arms or len(arms[arm]) != 3:
                raise AssertionError(f"variant lattice broken at {cell}/{arm}")
        bm25 = sum(arms["BM25"]) / 3
        mca = sum(arms["MCA"]) / 3
        deltas.append(mca - bm25)
    macro_delta = sum(deltas) / len(deltas)
    bm25_macro = sum(sum(arms["BM25"]) / 3 for arms in cell_values.values()) / len(cell_values)
    mca_macro = sum(sum(arms["MCA"]) / 3 for arms in cell_values.values()) / len(cell_values)
    return {"Delta": macro_delta, "BM25_mean": bm25_macro, "MCA_mean": mca_macro}


def build_counterfactual(registry: dict) -> dict:
    unit_index: dict[tuple[str, str], list[dict]] = {}
    for unit in registry["claim_judgements"]:
        unit_index.setdefault((unit["evaluator"], unit["output_id"]), []).append(unit)
    evaluators = sorted({ev for ev, _ in unit_index})
    variant_rows = []
    lambda_rows = []
    direction_flips = []
    for evaluator in evaluators:
        first_key = next(k for k in unit_index if k[0] == evaluator)
        role = unit_index[first_key][0]["role"]
        for variant in VARIANTS:
            result = _aggregate_variant(unit_index, evaluator, variant, None)
            variant_rows.append({
                "evaluator": evaluator, "role": role, "variant": variant,
                "BM25_mean": float(result["BM25_mean"]), "MCA_mean": float(result["MCA_mean"]),
                "Delta": float(result["Delta"]), "exact_delta": str(result["Delta"]),
                "direction": "MCA_HIGHER" if result["Delta"] > 0 else "MCA_LOWER" if result["Delta"] < 0 else "EQUAL",
            })
        original = _aggregate_variant(unit_index, evaluator, "U_original", None)["Delta"]
        for lam in LAMBDA_GRID:
            result = _aggregate_variant(unit_index, evaluator, "U_lambda", lam)
            lambda_rows.append({
                "evaluator": evaluator, "role": role, "lambda": float(lam), "exact_lambda": str(lam),
                "BM25_mean": float(result["BM25_mean"]), "MCA_mean": float(result["MCA_mean"]),
                "Delta": float(result["Delta"]), "exact_delta": str(result["Delta"]),
                "direction": "MCA_HIGHER" if result["Delta"] > 0 else "MCA_LOWER" if result["Delta"] < 0 else "EQUAL",
            })
        zero_lambda = _aggregate_variant(unit_index, evaluator, "U_lambda", Fraction(0))["Delta"]
        one_lambda = _aggregate_variant(unit_index, evaluator, "U_lambda", Fraction(1))["Delta"]
        flips_within_grid = any(
            (a > 0) != (b > 0) and (a != 0 or b != 0)
            for a, b in zip(
                [_aggregate_variant(unit_index, evaluator, "U_lambda", l)["Delta"] for l in LAMBDA_GRID],
                [_aggregate_variant(unit_index, evaluator, "U_lambda", l)["Delta"] for l in LAMBDA_GRID[1:]],
            )
        )
        direction_flips.append({
            "evaluator": evaluator, "role": role,
            "delta_lambda_0": float(zero_lambda), "delta_lambda_1": float(one_lambda),
            "direction_lambda_0": "MCA_HIGHER" if zero_lambda > 0 else "MCA_LOWER" if zero_lambda < 0 else "EQUAL",
            "direction_lambda_1": "MCA_HIGHER" if one_lambda > 0 else "MCA_LOWER" if one_lambda < 0 else "EQUAL",
            "direction_reverses_across_grid": flips_within_grid or (zero_lambda > 0) != (one_lambda > 0) and (zero_lambda != 0 and one_lambda != 0),
        })
    return {
        "schema_version": "1.0",
        "status": "DIAGNOSTIC SENSITIVITY ANALYSIS; NOT a new primary endpoint; no optimal lambda searched",
        "lambda_grid": [str(v) for v in LAMBDA_GRID],
        "variants": variant_rows,
        "lambda_sensitivity": lambda_rows,
        "direction_flips": direction_flips,
    }
