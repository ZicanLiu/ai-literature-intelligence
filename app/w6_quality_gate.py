"""CLI for the W6 data-quality, leakage, and artifact gate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from src.w6_quality_gate import (
    exit_code_for_report,
    remove_previous_gate_report,
    run_w6_quality_gate,
    write_w6_gate_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_bootstrap"
    / "valid"
    / "bundle_manifest.json"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "quality" / "w6_gate_report.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="W6 Data Quality / Leakage / Artifact Gate"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="W6 bundle manifest (default: public valid Bootstrap fixture)",
    )
    parser.add_argument(
        "--mode",
        choices=("basic", "full"),
        default="basic",
        help="basic checks the public boundary; full also validates downstream contracts",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="machine-readable JSON report path",
    )
    return parser


def _print_console(message: str) -> None:
    """Print validator details without assuming a UTF-8 Windows console."""

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_message = message.encode(encoding, errors="backslashreplace").decode(encoding)
    print(safe_message)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.manifest.resolve()
    output = args.output.resolve()
    if manifest == output:
        _print_console("W6 Quality Gate ERROR: --output must differ from --manifest")
        return 2

    try:
        remove_previous_gate_report(output)
    except (OSError, ValueError) as exc:
        _print_console(f"W6 Quality Gate ERROR: {exc}")
        return 2

    report = run_w6_quality_gate(manifest, mode=args.mode)
    try:
        written_path = write_w6_gate_report(report, output)
    except (OSError, ValueError) as exc:
        _print_console(f"W6 Quality Gate ERROR: could not write report: {exc}")
        return 2

    summary = report["summary"]
    _print_console(f"W6 Quality Gate {report['result']} ({report['mode']})")
    _print_console(
        "Checks: "
        f"{summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['skipped']} skipped"
    )
    _print_console(f"Files checked: {summary['file_count']}")
    for error in report["errors"]:
        _print_console(f"FAIL {error['check']}: {error['detail']}")
    _print_console(f"Report: {written_path}")
    return exit_code_for_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
