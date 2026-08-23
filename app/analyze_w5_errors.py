"""CLI for validated W5 Hard Negative and Error Taxonomy analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.w5_error_analysis import analyze_w5_errors, render_analysis_outputs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "benchmarks"
    / "w4_query_relevance"
    / "v0.1.0"
    / "manifest.json"
)
DEFAULT_TAXONOMY_MAPPING = (
    PROJECT_ROOT
    / "data"
    / "analysis"
    / "w5_error_taxonomy"
    / "w5_taxonomy_mapping.csv"
)
DEFAULT_TAXONOMY_SOURCE = (
    PROJECT_ROOT / "data" / "analysis" / "w4_query_boundary_examples.csv"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "验证一个或多个 W5 method manifest，并使用 approved W4 benchmark "
            "与 frozen W4 taxonomy 执行 pair-level error analysis。"
        )
    )
    parser.add_argument(
        "--manifest",
        action="append",
        type=Path,
        required=True,
        help="W5 method manifest；可重复传入以比较多个方法。",
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=DEFAULT_BENCHMARK_MANIFEST,
        help="strict approved W4 benchmark manifest。",
    )
    parser.add_argument(
        "--taxonomy-mapping",
        type=Path,
        default=DEFAULT_TAXONOMY_MAPPING,
        help="由 frozen W4 Query Boundary evidence 确定性生成的 mapping。",
    )
    parser.add_argument(
        "--taxonomy-source",
        type=Path,
        default=DEFAULT_TAXONOMY_SOURCE,
        help="frozen W4 Query Boundary evidence CSV。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="分析输出目录；所有输入验证通过后才写入。",
    )
    return parser.parse_args(argv)


def _write_outputs(output_dir: Path, rendered: dict[str, str]) -> None:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths: dict[str, Path] = {}
    try:
        for filename in sorted(rendered):
            temporary = output_dir / f".{filename}.tmp"
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered[filename])
            temporary_paths[filename] = temporary
        for filename in sorted(rendered):
            temporary_paths[filename].replace(output_dir / filename)
    except Exception:
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = analyze_w5_errors(
            args.manifest,
            benchmark_manifest_path=args.benchmark_manifest,
            taxonomy_mapping_path=args.taxonomy_mapping,
            taxonomy_source_path=args.taxonomy_source,
            project_root=PROJECT_ROOT,
        )
        rendered = render_analysis_outputs(result)
        _write_outputs(args.output_dir, rendered)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W5 error analysis 失败：{error}")
        return 1

    print(
        "W5 error analysis 完成："
        f"methods={len(result['methods'])}，"
        f"benchmark_pairs={result['benchmark']['pair_count']}，"
        f"taxonomy_evidence={result['taxonomy']['evidence_pair_count']}，"
        f"unclassified={result['taxonomy']['unclassified_pair_count']}"
    )
    print(f"输出目录：{args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
