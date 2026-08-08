"""项目 basic/full 质量门禁命令行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from src.validation import (
    ALLOWED_RELEVANCE_LABELS,
    ValidationResult,
    list_project_files,
    run_unittest_suite,
    scan_sensitive_risks,
    validate_csv_file,
    validate_json_file,
    validate_label_values,
    validate_markdown_links,
    validate_numeric_ranges,
    validate_python_imports,
    validate_references,
    validate_required_directories,
    validate_run_config,
    validate_tracked_experiments,
    validate_unique_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRECTORIES = ("app", "src", "tests", "docs", "data")
KEY_MODULES = ("app.main", "app.quality_gate", "src.processor", "src.validation")
ID_COLUMNS = ("annotation_id", "case_id", "term_id")
SCORE_COLUMN_NAMES = {
    "similarity",
    "similarity_score",
    "precision",
    "recall",
    "ndcg",
    "metric_value",
}
INVALID_FIXTURE_PREFIX = "tests/fixtures/validation/invalid/"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查项目结构、测试、链接、安全风险和 W2 数据契约。"
    )
    parser.add_argument(
        "--level", choices=("basic", "full"), default="basic", help="检查级别。"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="待检查项目根目录；默认是当前仓库。",
    )
    return parser.parse_args(argv)


def run_quality_gate(
    root: Path,
    level: str = "basic",
    *,
    run_tests: bool = True,
    check_imports: bool = True,
) -> ValidationResult:
    """执行质量门禁并返回结构化结果，不直接退出。"""
    if level not in {"basic", "full"}:
        raise ValueError("level 必须是 basic 或 full。")
    root = root.resolve()
    files = list_project_files(root)
    result = ValidationResult(details={"level": level, "root": "."})
    checks: list[dict[str, object]] = []

    def add_check(name: str, check_result: ValidationResult) -> None:
        result.merge(check_result)
        checks.append(
            {
                "name": name,
                "status": check_result.status,
                "errors": len(check_result.errors),
                "warnings": len(check_result.warnings),
            }
        )

    add_check(
        "required_directories",
        validate_required_directories(root, REQUIRED_DIRECTORIES),
    )
    schema_files = [
        path for path in files if not path.as_posix().startswith(INVALID_FIXTURE_PREFIX)
    ]
    json_paths = [path for path in schema_files if path.suffix.casefold() == ".json"]
    for path in json_paths:
        add_check(
            f"json:{path.as_posix()}",
            validate_json_file(root / path, path.as_posix()),
        )
    if check_imports:
        add_check("python_imports", validate_python_imports(root, KEY_MODULES))
    markdown_paths = [path for path in schema_files if path.suffix.casefold() == ".md"]
    add_check("markdown_links", validate_markdown_links(root, markdown_paths))
    add_check("sensitive_risks", scan_sensitive_risks(root, files))
    if run_tests:
        add_check("automated_tests", run_unittest_suite(root))

    if level == "full":
        _run_full_checks(root, files, add_check)

    result.details["checks"] = checks
    result.details["file_count"] = len(files)
    result.details["json_count"] = len(json_paths)
    result.details["markdown_count"] = len(markdown_paths)
    return result


def _run_full_checks(root: Path, files: Sequence[Path], add_check) -> None:
    sample_ids: set[str] = set()
    annotation_tables: list[tuple[Path, list[dict[str, str]]]] = []

    eligible_files = [
        path for path in files if not path.as_posix().startswith(INVALID_FIXTURE_PREFIX)
    ]
    for path in [value for value in eligible_files if value.suffix.casefold() == ".csv"]:
        csv_result = validate_csv_file(root / path, path.as_posix())
        if path.as_posix() == "data/manual/relevance_labels_w1.csv" and csv_result.errors:
            issue_count = len(csv_result.errors)
            csv_result.errors.clear()
            csv_result.add_warning(
                f"历史 W1 标注存在 {issue_count} 个 CSV 结构问题；"
                "保留原始交付物并作为遗留问题记录。"
            )
            csv_result.details["legacy_scope"] = True
        add_check(f"csv:{path.as_posix()}", csv_result)
        headers = list(csv_result.details.get("headers", []))
        rows = list(csv_result.details.get("rows", []))
        if csv_result.errors:
            continue

        for column in ID_COLUMNS:
            if column in headers:
                add_check(
                    f"unique:{path.as_posix()}:{column}",
                    validate_unique_ids(rows, column, path.as_posix()),
                )
        if "openalex_id" in headers and (
            "data/samples/" in path.as_posix() or "data/manual/" in path.as_posix()
        ):
            add_check(
                f"unique:{path.as_posix()}:openalex_id",
                validate_unique_ids(rows, "openalex_id", path.as_posix()),
            )
        if "openalex_id" in headers and (
            "data/samples/" in path.as_posix() or path.name == "papers_ranked.csv"
        ):
            sample_ids.update(
                (row.get("openalex_id") or "").strip()
                for row in rows
                if (row.get("openalex_id") or "").strip()
            )
        if "openalex_id" in headers and "data/manual/" in path.as_posix():
            annotation_tables.append((path, rows))

        for label_column in ("label", "relevance_label"):
            if label_column in headers:
                add_check(
                    f"labels:{path.as_posix()}:{label_column}",
                    validate_label_values(
                        rows,
                        label_column,
                        ALLOWED_RELEVANCE_LABELS,
                        path.as_posix(),
                    ),
                )

        score_columns = [
            header
            for header in headers
            if header in SCORE_COLUMN_NAMES or header.endswith("_score")
        ]
        if score_columns:
            add_check(
                f"ranges:{path.as_posix()}",
                validate_numeric_ranges(rows, score_columns, 0.0, 1.0, path.as_posix()),
            )

    for path, rows in annotation_tables:
        relation = validate_references(rows, "openalex_id", sample_ids, path.as_posix())
        if "w2" not in path.name.casefold():
            missing_count = len(relation.errors)
            relation.errors.clear()
            if missing_count:
                relation.add_warning(
                    f"历史标注 {path.as_posix()} 有 {missing_count} 个 ID "
                    "未在当前统一样例中找到；作为 W1 遗留问题记录。"
                )
            relation.details["legacy_scope"] = True
        add_check(f"references:{path.as_posix()}", relation)

    for path in eligible_files:
        if path.name == "run_config.json":
            add_check(
                f"run_config:{path.as_posix()}",
                validate_run_config(root / path, path.as_posix()),
            )
    add_check("tracked_experiments", validate_tracked_experiments(files))


def exit_code_for_result(result: ValidationResult) -> int:
    return 0 if result.status == "passed" else 1


def print_summary(result: ValidationResult) -> None:
    level = str(result.details.get("level", "unknown")).upper()
    print(f"质量门禁级别：{level}")
    print(f"检查文件：{result.details.get('file_count', 0)}")
    print(f"错误：{len(result.errors)}；警告：{len(result.warnings)}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}")
    print("结果：PASSED" if result.status == "passed" else "结果：FAILED")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_quality_gate(args.root, args.level)
    print_summary(result)
    return exit_code_for_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
