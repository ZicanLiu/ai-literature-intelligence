"""项目质量门禁使用的可复用验证函数。

验证函数返回结构化 ``ValidationResult``，不直接退出进程，也不会输出疑似密钥原文。
"""

from __future__ import annotations

import csv
import importlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import unquote


ALLOWED_RELEVANCE_LABELS = frozenset(
    {"高度相关", "部分相关", "不相关", "待讨论"}
)
TEXT_SUFFIXES = frozenset(
    {".py", ".md", ".json", ".csv", ".txt", ".yml", ".yaml", ".toml"}
)
SENSITIVE_FILENAMES = (
    re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE),
    re.compile(r"^id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?$", re.IGNORECASE),
    re.compile(r".*\.(?:pem|key|p12|pfx)$", re.IGNORECASE),
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"(?:api[_-]?key|token|password)\s*[:=]\s*['\"][A-Za-z0-9_./+-]{16,}['\"]",
        re.IGNORECASE,
    ),
)
_WINDOWS_USER_HOME = r"[A-Za-z]:\\" + "Users" + r"\\[^\\\s]+"
_LINUX_USER_HOME = "/" + "home" + r"/[^/\s]+"
_MAC_USER_HOME = "/" + "Users" + r"/[^/\s]+"
LOCAL_PERSONAL_PATH = re.compile(
    f"(?:{_WINDOWS_USER_HOME}|{_LINUX_USER_HOME}|{_MAC_USER_HOME})"
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SKIP_PARTS = frozenset(
    {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "node_modules"}
)


@dataclass
class ValidationResult:
    """一次或多次验证的结构化结果。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "failed" if self.errors else "passed"

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.details.update(other.details)
        return self

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "details": dict(self.details),
        }


def list_project_files(root: Path) -> list[Path]:
    """列出已跟踪和未忽略的新文件；失败时退化为安全的递归扫描。"""
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        paths = []
        for raw_path in completed.stdout.split(b"\0"):
            if not raw_path:
                continue
            relative = Path(raw_path.decode("utf-8", errors="surrogateescape"))
            path = root / relative
            if path.is_file() and not _has_skipped_part(relative):
                paths.append(relative)
        return sorted(set(paths), key=lambda value: value.as_posix())

    paths = []
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root)
            if not _has_skipped_part(relative):
                paths.append(relative)
    return sorted(paths, key=lambda value: value.as_posix())


def validate_required_directories(root: Path, names: Sequence[str]) -> ValidationResult:
    result = ValidationResult(details={"required_directories": list(names)})
    for name in names:
        if not (root / name).is_dir():
            result.add_error(f"缺少必需目录：{name}")
    return result


def validate_json_file(path: Path, display_name: str | None = None) -> ValidationResult:
    name = display_name or path.name
    result = ValidationResult(details={"json_file": name})
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        result.add_error(f"JSON 无法解析：{name}（{type(error).__name__}）")
    return result


def validate_python_imports(root: Path, module_names: Sequence[str]) -> ValidationResult:
    result = ValidationResult(details={"imported_modules": list(module_names)})
    root_text = str(root.resolve())
    inserted = root_text not in sys.path
    if inserted:
        sys.path.insert(0, root_text)
    try:
        importlib.invalidate_caches()
        for module_name in module_names:
            try:
                importlib.import_module(module_name)
            except Exception as error:  # import-time failures must be reported by the gate
                result.add_error(
                    f"关键模块无法导入：{module_name}（{type(error).__name__}）"
                )
    finally:
        if inserted:
            sys.path.remove(root_text)
    return result


def validate_markdown_links(
    root: Path, relative_markdown_paths: Iterable[Path]
) -> ValidationResult:
    result = ValidationResult()
    checked = 0
    for relative in relative_markdown_paths:
        markdown_path = root / relative
        try:
            content = markdown_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            result.add_error(
                f"Markdown 无法读取：{relative.as_posix()}（{type(error).__name__}）"
            )
            continue
        checked += 1
        for raw_target in MARKDOWN_LINK.findall(content):
            target = _clean_markdown_target(raw_target)
            if not target or _is_external_target(target):
                continue
            target_without_anchor = unquote(target.split("#", 1)[0])
            if not target_without_anchor:
                continue
            if target_without_anchor.startswith("/"):
                candidate = root / target_without_anchor.lstrip("/")
            else:
                candidate = markdown_path.parent / target_without_anchor
            if not candidate.exists():
                result.add_error(
                    "Markdown 本地链接失效："
                    f"{relative.as_posix()} -> {target_without_anchor}"
                )
    result.details["markdown_files_checked"] = checked
    return result


def scan_sensitive_risks(root: Path, relative_paths: Iterable[Path]) -> ValidationResult:
    """只扫描项目文件名和文本；敏感文件只报告路径，不读取其内容。"""
    result = ValidationResult()
    checked_text = 0
    for relative in relative_paths:
        if any(pattern.fullmatch(relative.name) for pattern in SENSITIVE_FILENAMES):
            if relative.name != ".env.example":
                result.add_error(f"发现不应提交的敏感文件名：{relative.as_posix()}")
            continue
        path = root / relative
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8-sig", errors="strict")
        except (OSError, UnicodeError):
            result.add_warning(f"文本安全扫描无法读取：{relative.as_posix()}")
            continue
        checked_text += 1
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            result.add_error(f"发现疑似硬编码凭据：{relative.as_posix()}（内容已隐藏）")
        if LOCAL_PERSONAL_PATH.search(content):
            result.add_error(f"发现个人绝对路径：{relative.as_posix()}（路径已隐藏）")
    result.details["security_text_files_checked"] = checked_text
    return result


def validate_csv_file(
    path: Path,
    display_name: str | None = None,
    required_headers: Sequence[str] = (),
) -> ValidationResult:
    name = display_name or path.name
    result = ValidationResult(details={"csv_file": name, "headers": [], "rows": []})
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_rows = list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        result.add_error(f"CSV 无法读取：{name}（{type(error).__name__}）")
        return result
    if not raw_rows:
        result.add_error(f"CSV 为空且没有表头：{name}")
        return result
    headers = [header.strip() for header in raw_rows[0]]
    result.details["headers"] = headers
    if not headers or any(not header for header in headers):
        result.add_error(f"CSV 存在空表头：{name}")
    if len(set(headers)) != len(headers):
        result.add_error(f"CSV 存在重复表头：{name}")
    for header in required_headers:
        if header not in headers:
            result.add_error(f"CSV 缺少字段：{name} -> {header}")
    rows: list[dict[str, str]] = []
    for row_number, values in enumerate(raw_rows[1:], start=2):
        if len(values) != len(headers):
            result.add_error(
                f"CSV 行列数不一致：{name} 第 {row_number} 行，"
                f"期望 {len(headers)} 列，实际 {len(values)} 列"
            )
            continue
        rows.append(dict(zip(headers, values)))
    result.details["rows"] = rows
    result.details["row_count"] = len(rows)
    return result


def validate_unique_ids(
    rows: Sequence[dict[str, str]], column: str, source_name: str
) -> ValidationResult:
    result = ValidationResult(details={"id_column": column})
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        value = (row.get(column) or "").strip()
        if not value:
            result.add_error(f"ID 为空：{source_name} 第 {row_number} 行 -> {column}")
        elif value in seen:
            result.add_error(f"ID 重复：{source_name} 第 {row_number} 行 -> {column}")
        else:
            seen.add(value)
    return result


def validate_label_values(
    rows: Sequence[dict[str, str]],
    column: str,
    allowed: set[str] | frozenset[str],
    source_name: str,
) -> ValidationResult:
    result = ValidationResult(details={"label_column": column})
    for row_number, row in enumerate(rows, start=2):
        value = (row.get(column) or "").strip()
        if not value or value not in allowed:
            result.add_error(f"标签非法：{source_name} 第 {row_number} 行 -> {column}")
    return result


def validate_references(
    rows: Sequence[dict[str, str]],
    column: str,
    valid_ids: set[str],
    source_name: str,
) -> ValidationResult:
    result = ValidationResult(details={"reference_column": column})
    for row_number, row in enumerate(rows, start=2):
        value = (row.get(column) or "").strip()
        if not value or value not in valid_ids:
            result.add_error(
                f"数据关联失效：{source_name} 第 {row_number} 行 -> {column}"
            )
    return result


def validate_numeric_ranges(
    rows: Sequence[dict[str, str]],
    columns: Sequence[str],
    minimum: float,
    maximum: float,
    source_name: str,
) -> ValidationResult:
    result = ValidationResult(details={"numeric_columns": list(columns)})
    for row_number, row in enumerate(rows, start=2):
        for column in columns:
            raw_value = (row.get(column) or "").strip()
            if not raw_value:
                continue
            try:
                value = float(raw_value)
            except ValueError:
                result.add_error(
                    f"数值无法解析：{source_name} 第 {row_number} 行 -> {column}"
                )
                continue
            if not math.isfinite(value) or not minimum <= value <= maximum:
                result.add_error(
                    f"数值超出 [{minimum}, {maximum}]："
                    f"{source_name} 第 {row_number} 行 -> {column}"
                )
    return result


def validate_run_config(path: Path, display_name: str | None = None) -> ValidationResult:
    name = display_name or path.name
    result = validate_json_file(path, name)
    if result.errors:
        return result
    with path.open("r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    required = ("run_id", "created_at", "mode", "keyword", "max_results", "status")
    for field_name in required:
        if config.get(field_name) in (None, ""):
            result.add_error(f"run_config 缺少字段：{name} -> {field_name}")
    if config.get("status") not in {"running", "completed", "failed"}:
        result.add_error(f"run_config status 非法：{name}")
    if "success" in config and not isinstance(config["success"], bool):
        result.add_error(f"run_config success 必须是布尔值：{name}")
    return result


def validate_tracked_experiments(relative_paths: Iterable[Path]) -> ValidationResult:
    result = ValidationResult()
    run_names = set()
    for relative in relative_paths:
        parts = relative.as_posix().split("/")
        if len(parts) >= 3 and parts[:2] == ["outputs", "experiments"]:
            run_names.add(parts[2])
    if run_names:
        result.add_warning(
            "检测到历史已跟踪 experiments：" + ", ".join(sorted(run_names))
        )
    result.details["tracked_experiment_runs"] = sorted(run_names)
    return result


def run_unittest_suite(root: Path, timeout_seconds: int = 180) -> ValidationResult:
    result = ValidationResult()
    if os.getenv("ASTRO_QUALITY_GATE_RUNNING") == "1":
        result.add_warning("自动测试已处于质量门禁子进程中，跳过递归执行。")
        result.details["test_status"] = "already_running"
        return result
    env = os.environ.copy()
    env["ASTRO_QUALITY_GATE_RUNNING"] = "1"
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/automated",
                "-p",
                "test_*.py",
                "-v",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result.add_error(f"自动测试超过 {timeout_seconds} 秒未结束。")
        result.details["test_status"] = "timeout"
        return result
    combined = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"Ran (\d+) tests?", combined)
    test_count = int(match.group(1)) if match else None
    result.details.update(
        {
            "test_status": "passed" if completed.returncode == 0 else "failed",
            "test_returncode": completed.returncode,
            "test_count": test_count,
        }
    )
    if completed.returncode != 0:
        result.add_error(
            "自动测试失败；请直接运行 unittest discovery 查看具体失败用例。"
        )
    return result


def _clean_markdown_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")].strip()
    if " \"" in target:
        target = target.split(" \"", 1)[0]
    if " '" in target:
        target = target.split(" '", 1)[0]
    return target


def _is_external_target(target: str) -> bool:
    lowered = target.casefold()
    return lowered.startswith(("http://", "https://", "mailto:", "ftp://", "#"))


def _has_skipped_part(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)
