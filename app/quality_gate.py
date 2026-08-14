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
from src.annotation_validation import VALID_LABELS


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


def is_negative_test_fixture(path: Path) -> bool:
    """识别只用于断言失败路径的测试 fixture。"""
    parts = tuple(part.casefold() for part in path.parts)
    if len(parts) < 3 or parts[:2] != ("tests", "fixtures"):
        return False
    fixture_parts = parts[2:]
    negative_directory_names = {"invalid", "negative", "expected_fail", "expected-fail"}
    if any(part in negative_directory_names for part in fixture_parts[:-1]):
        return True
    filename = fixture_parts[-1]
    return any(
        marker in filename
        for marker in ("invalid", "deliberate", "negative", "expected_fail", "expected-fail")
    )


def should_require_unique_openalex_id(path: Path) -> bool:
    """按数据用途判断 OpenAlex ID 是否必须唯一。"""
    parts = tuple(part.casefold() for part in path.parts)
    if parts[:4] == ("data", "samples", "w2", "dedup"):
        return False
    if parts[:2] in {("data", "samples"), ("data", "manual")}:
        return True
    return (
        parts[:3] == ("data", "analysis", "w2_dedup")
        and path.stem.casefold().startswith("deduplicated")
    )


# W4 标注任务目录使用数字 Query Relevance 等级（2/1/0/?），
# 与 W2 的中文相关性标签词汇不同；单一事实来源是 src.annotation_validation。
W4_ANNOTATION_DATA_PREFIX = ("data", "annotation_tasks", "w4")


def allowed_relevance_labels(path: Path) -> set[str]:
    """按数据契约选择 label 列的允许词汇。"""
    parts = tuple(part.casefold() for part in path.parts)
    if parts[:3] == W4_ANNOTATION_DATA_PREFIX:
        return set(VALID_LABELS)
    return set(ALLOWED_RELEVANCE_LABELS)


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
    schema_files = [path for path in files if not is_negative_test_fixture(path)]
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

    eligible_files = [path for path in files if not is_negative_test_fixture(path)]
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
        if "openalex_id" in headers and should_require_unique_openalex_id(path):
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
                        allowed_relevance_labels(path),
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
