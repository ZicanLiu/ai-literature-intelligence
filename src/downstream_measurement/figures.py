"""Phase P: matplotlib figures generated exclusively from derived canonical data."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PRIMARY_COLOR = "#2b5a8c"
SENSITIVITY_COLOR = "#b3541e"
NEUTRAL = "#777777"


def _style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 150})


def fig_delta_by_evaluator(sensitivity: dict, path: Path) -> None:
    rows = sensitivity["treatment_contrasts"]
    evaluators = [r["evaluator"] for r in rows]
    fig, ax = plt.subplots(figsize=(7.5, 4.2), layout="constrained")
    xs = range(len(rows))
    for offset, field, label in ((-0.18, "Delta_U", "Delta U (useful slots)"), (0.18, "Delta_E", "Delta E (error events)")):
        values = [r[field] for r in rows]
        colors = [PRIMARY_COLOR if r["role"] == "PRIMARY_JUDGE" else SENSITIVITY_COLOR for r in rows]
        bars = ax.bar([x + offset for x in xs], values, width=0.35, label=label,
                      color=colors if field == "Delta_U" else "none",
                      edgecolor=colors, linewidth=1.4)
        for bar, value in zip(bars, values):
            ax.annotate(f"{value:+.3f}", (bar.get_x() + bar.get_width() / 2, value),
                        xytext=(0, 4 if value >= 0 else -12), textcoords="offset points", ha="center", fontsize=8)
    ax.axhline(0, color=NEUTRAL, linewidth=1)
    ax.set_xticks(list(xs), evaluators)
    ax.set_ylabel("MCA - BM25")
    ax.set_title("Treatment contrast by evaluator (solid = primary judge, outlined = sensitivity evaluator)")
    ax.legend(loc="lower left")
    fig.savefig(path)
    plt.close(fig)


def fig_component_failures(decomposition: dict, path: Path) -> None:
    data = decomposition["component_failures_by_evaluator_arm"]
    entries = sorted(data.items())
    evaluators = sorted({key.split("|")[0] for key, _ in entries})
    components = ["A", "S", "C", "N"]
    fig, axes = plt.subplots(1, len(evaluators), figsize=(3.2 * len(evaluators), 3.6),
                             sharey=True, layout="constrained", squeeze=False)
    for ax, evaluator in zip(axes[0], evaluators):
        for position, arm in enumerate(("BM25", "MCA")):
            values = [data.get(f"{evaluator}|{arm}|{comp}", 0) for comp in components]
            offset = -0.19 if arm == "BM25" else 0.19
            bars = ax.bar([position_ + offset for position_ in range(len(components))], values,
                          width=0.36, color=PRIMARY_COLOR if arm == "BM25" else SENSITIVITY_COLOR, label=arm)
            for bar, value in zip(bars, values):
                if value:
                    ax.annotate(str(value), (bar.get_x() + bar.get_width() / 2, value),
                                xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
        ax.set_xticks(range(len(components)), components)
        ax.set_title(evaluator)
        ax.grid(axis="y", alpha=0.2)
    axes[0][0].set_ylabel("first-six failure count")
    axes[0][0].legend()
    fig.suptitle("Component failures by evaluator x arm (A=atomicity S=support C=scope N=redundancy)")
    fig.savefig(path)
    plt.close(fig)


def fig_cell_contrasts(reproduction: dict, path: Path) -> None:
    panels = {**reproduction["primary"],
              **{ev: p for ev, p in reproduction["sensitivity"].items() if "cells" in p}}
    evaluators = sorted(panels)
    cells = [(t, k) for t in sorted({c["topic_id"] for p in panels.values() for c in p["cells"]})
             for k in ("A", "B")]
    fig, axes = plt.subplots(1, len(evaluators), figsize=(3.4 * len(evaluators), 3.4),
                             layout="constrained", squeeze=False)
    for ax, evaluator in zip(axes[0], evaluators):
        values = []
        for topic, task in cells:
            cell = next(c for c in panels[evaluator]["cells"] if c["topic_id"] == topic and c["task_id"] == task)
            values.append(float(cell["Delta_U"]))
        ax.bar(range(len(cells)), values, color=PRIMARY_COLOR if evaluator in reproduction["primary"] else SENSITIVITY_COLOR)
        ax.axhline(0, color=NEUTRAL, linewidth=1)
        def _label(topic: str, task: str) -> str:
            short = topic.split('_')[2][:6] if len(topic.split('_')) > 2 else topic[:6]
            return f"{short}|{task}"

        ax.set_xticks(range(len(cells)), [_label(t, k) for t, k in cells], rotation=45, ha="right", fontsize=7)
        ax.set_title(evaluator)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("Topic x Task Delta U contrasts (equal-weight macro components)")
    fig.savefig(path)
    plt.close(fig)


def fig_agreement_heatmap(sensitivity: dict, path: Path) -> None:
    rows = [r for r in sensitivity["pairwise_agreement"] if r.get("field") == "joint_U_eligibility" and r.get("n")]
    if not rows:
        return
    pairs = [r["pair"] for r in rows]
    fig, ax = plt.subplots(figsize=(max(6.5, 0.9 * len(pairs)), 3.2), layout="constrained")
    values = [r["raw_agreement"] for r in rows]
    bars = ax.barh(range(len(pairs)), values, color=PRIMARY_COLOR)
    for bar, row in zip(bars, rows):
        kappa = row.get("kappa")
        note = f"k={kappa:.2f}" if isinstance(kappa, float) else "k=NA(degenerate)"
        ax.annotate(f"{row['raw_agreement']:.3f} {note}", (bar.get_width(), bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points", va="center", fontsize=8)
    ax.set_yticks(range(len(pairs)), pairs)
    ax.set_xlim(0, 1.25)
    ax.axvline(1.0, color=NEUTRAL, linewidth=0.8, linestyle="--")
    ax.set_title("Pairwise raw agreement on joint U eligibility (kappa only when both raters vary)")
    ax.set_xlabel("raw agreement")
    fig.savefig(path)
    plt.close(fig)


def fig_lambda_sensitivity(counterfactual: dict, path: Path) -> None:
    rows = [r for r in counterfactual["lambda_sensitivity"]]
    evaluators = sorted({r["evaluator"] for r in rows})
    fig, ax = plt.subplots(figsize=(6.5, 4), layout="constrained")
    for evaluator in evaluators:
        series = sorted((r for r in rows if r["evaluator"] == evaluator), key=lambda r: r["lambda"])
        lambdas = [r["lambda"] for r in series]
        deltas = [r["Delta"] for r in series]
        style = "-o" if any(r["role"] == "PRIMARY_JUDGE" for r in series) else "--s"
        color = PRIMARY_COLOR if style == "-o" else SENSITIVITY_COLOR
        ax.plot(lambdas, deltas, style, label=evaluator, color=color, markersize=4)
        for point in series:
            if point["direction"] != "EQUAL" and abs(point["Delta"]) > 1e-9:
                ax.annotate(point["direction"][:3], (point["lambda"], point["Delta"]),
                            xytext=(0, 5), textcoords="offset points", ha="center", fontsize=6)
    ax.axhline(0, color=NEUTRAL, linewidth=1)
    ax.set_xlabel("lambda (atomicity-failure weight in U_lambda = S*C*N*[A + lambda*(1-A)])")
    ax.set_ylabel("macro Delta U")
    ax.set_title("Metric sensitivity: Delta U across fixed lambda grid (diagnostic, no optimal lambda)")
    ax.legend(fontsize=8)
    fig.savefig(path)
    plt.close(fig)


REQUIRED_FIGURES = (
    "fig1_delta_by_evaluator.png",
    "fig2_component_failures.png",
    "fig3_cell_contrasts.png",
    "fig4_agreement_heatmap.png",
    "fig5_lambda_sensitivity.png",
    "fig6_leave_one_out_influence.png",
    "fig7_evidence_chain_verification.png",
)


def loo_endpoint_series(influence: dict, endpoint: str = "U") -> list[dict]:
    """Leave-one-output-out rows for exactly one endpoint (figure data gate).

    fig6 plots Delta U only; accidentally mixing the E rows into the same
    axes would mislabel the estimate. This helper is the single filter both
    the figure and its regression test consume.
    """
    return [row for row in influence.get("leave_one_output_out", [])
            if row.get("endpoint") == endpoint]


def fig_influence(influence: dict, path: Path) -> None:
    rows = loo_endpoint_series(influence, "U")
    evaluators = sorted({r["evaluator"] for r in rows})
    fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
    for position, evaluator in enumerate(evaluators):
        own = [r["macro_after_exclusion"] for r in rows
               if r["evaluator"] == evaluator and r["macro_after_exclusion"] is not None]
        if not own:
            continue
        baseline = next(r["baseline_macro"] for r in rows if r["evaluator"] == evaluator)
        color = PRIMARY_COLOR if evaluator != "FullPro" else SENSITIVITY_COLOR
        ax.scatter([position + (i % 24) * 0.02 for i in range(len(own))], own, s=14, color=color, alpha=0.65)
        ax.hlines(baseline, position - 0.25, position + 0.25, color="black", linewidth=2)
        spread = max(own) - min(own)
        ax.annotate(f"spread {spread:.3f}", (position, min(own)), xytext=(0, -14),
                    textcoords="offset points", ha="center", fontsize=7)
    ax.set_xticks(range(len(evaluators)), evaluators)
    ax.set_ylabel("macro Delta U after leaving one output out")
    ax.set_title("Leave-one-output-out influence (descriptive; line = full-data macro)")
    fig.savefig(path)
    plt.close(fig)


def fig_evidence_chain(integrity: dict, path: Path) -> None:
    packages = integrity.get("packages") or {k: v for k, v in integrity.items() if k != "counts"}
    names = sorted(packages)
    verified = [packages[n]["summary"].get("verified", 0) for n in names]
    mismatched = [packages[n]["summary"].get("mismatched", 0) for n in names]
    missing = [packages[n]["summary"].get("missing", 0) for n in names]
    self_hashed = [packages[n]["summary"].get("self_hashed_unanchored", 0) for n in names]
    fig, ax = plt.subplots(figsize=(9.5, 0.28 * len(names) + 1.6), layout="constrained")
    positions = range(len(names))
    ax.barh(positions, verified, color=PRIMARY_COLOR, label="VERIFIED_BYTES (anchored)")
    ax.barh(positions, self_hashed, left=verified, color="#7a9e7a", label="SELF_HASHED_UNANCHORED")
    ax.barh(positions, mismatched, left=[v + s for v, s in zip(verified, self_hashed)],
            color="#c0392b", label="BYTES_MISMATCH")
    ax.barh(positions, missing, left=[v + s + m for v, s, m in zip(verified, self_hashed, mismatched)],
            color="#e5a50a", label="MISSING_SOURCE_BYTES")
    ax.set_yticks(positions, names, fontsize=7)
    ax.invert_yaxis()
    ax.set_xscale("symlog", linthresh=10)
    ax.set_xlabel("files (symlog)")
    counts = integrity.get("counts", {})
    ax.set_title(f"Evidence byte verification by package "
                 f"(anchored verified={counts.get('files_verified', sum(verified))}, "
                 f"self-hashed unanchored={counts.get('self_hashed_unanchored', sum(self_hashed))}, "
                 f"mismatch={counts.get('bytes_mismatch', sum(mismatched))}, "
                 f"missing={counts.get('missing_source_bytes', sum(missing))})")
    ax.legend(fontsize=7)
    fig.savefig(path)
    plt.close(fig)


def render_all(derived: dict, output_dir: Path) -> dict:
    """Render the required figure roster.

    Returns {"written": [...], "failed": [{"name", "error"}]}. A rendering
    error never aborts the audit, but the caller must treat any failed
    REQUIRED figure as a failed audit (no COMPLETE manifest).
    """
    _style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    failed = []
    jobs = (
        (fig_delta_by_evaluator, (derived["sensitivity"], "fig1_delta_by_evaluator.png")),
        (fig_component_failures, (derived["decomposition"], "fig2_component_failures.png")),
        (fig_cell_contrasts, (derived["reproduction"], "fig3_cell_contrasts.png")),
        (fig_agreement_heatmap, (derived["sensitivity"], "fig4_agreement_heatmap.png")),
        (fig_lambda_sensitivity, (derived["counterfactual"], "fig5_lambda_sensitivity.png")),
        (fig_influence, (derived["influence"], "fig6_leave_one_out_influence.png")),
        (fig_evidence_chain, (derived["integrity"], "fig7_evidence_chain_verification.png")),
    )
    for fn, (payload, name) in jobs:
        target = output_dir / name
        try:
            fn(payload, target)
            written.append(name)
        except Exception as error:  # noqa: BLE001 - recorded, never silent
            failed.append({"name": name, "error": f"{type(error).__name__}: {error}"})
            (output_dir / f"{name}.FAILED.txt").write_text(f"{type(error).__name__}: {error}\n",
                                                           encoding="utf-8")
    return {"written": written, "failed": failed}
