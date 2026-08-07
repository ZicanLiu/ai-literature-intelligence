"""
src/validation.py 的自动化单元测试。
"""

import csv
import json
import sys
from pathlib import Path

# 最顶层注入项目根目录路径
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from src.validation import (
    check_git_purity,
    check_json_syntax,
    check_markdown_links,
    check_python_modules_importable,
    check_required_directories,
    check_sensitive_files_and_secrets,
    validate_csv_structure,
    validate_foreign_key_relation,
    validate_id_uniqueness,
    validate_label_values,
    validate_numeric_range,
)


def test_check_required_directories(tmp_path):
    """测试目录校验函数。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "app").mkdir()

    errs, warns = check_required_directories(tmp_path, ["src", "app", "tests", "docs"])
    assert len(errs) == 2
    assert any("tests" in e for e in errs)
    assert any("docs" in e for e in errs)


def test_check_json_syntax(tmp_path):
    """测试 JSON 语法校验。"""
    valid_json = tmp_path / "valid.json"
    valid_json.write_text('{"status": "ok"}', encoding="utf-8")
    errs, warns = check_json_syntax(valid_json)
    assert len(errs) == 0

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text('{"status": "ok"', encoding="utf-8")
    errs, warns = check_json_syntax(invalid_json)
    assert len(errs) == 1


def test_check_markdown_links(tmp_path):
    """测试 Markdown 本地链接可达性。"""
    md_file = tmp_path / "README.md"
    (tmp_path / "exist.txt").write_text("hello", encoding="utf-8")
    
    md_file.write_text(
        "[Exist](./exist.txt)\n[Missing](./missing.txt)",
        encoding="utf-8"
    )

    errs, warns = check_markdown_links(tmp_path, [md_file])
    assert len(errs) == 1
    assert "missing.txt" in errs[0]


def test_check_sensitive_files_and_secrets(tmp_path):
    """测试敏感文件与秘钥风险识别。"""
    (tmp_path / ".env").write_text("SECRET=123", encoding="utf-8")
    
    code_file = tmp_path / "test.py"
    code_file.write_text('API_KEY = "sk-proj-12345678901234567890"', encoding="utf-8")

    errs, warns = check_sensitive_files_and_secrets(tmp_path)
    assert len(errs) >= 1


def test_validate_csv_structure(tmp_path):
    """测试 CSV 结构校验。"""
    csv_file = tmp_path / "data.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "score"])
        writer.writerow(["1", "Alice", "90"])

    errs, warns, rows = validate_csv_structure(csv_file, ["id", "name", "score"])
    assert len(errs) == 0
    assert len(rows) == 1

    errs, warns, rows = validate_csv_structure(csv_file, ["id", "name", "score", "age"])
    assert len(errs) == 1
    assert "age" in errs[0]


def test_validate_id_uniqueness():
    """测试 ID 唯一性校验。"""
    rows_unique = [{"id": "A1"}, {"id": "A2"}]
    errs, warns = validate_id_uniqueness(rows_unique, "id", "test.csv")
    assert len(errs) == 0

    rows_dup = [{"id": "A1"}, {"id": "A1"}]
    errs, warns = validate_id_uniqueness(rows_dup, "id", "test.csv")
    assert len(errs) == 1
    assert "重复" in errs[0]


def test_validate_label_values():
    """测试标签合法枚举值校验。"""
    rows = [{"label": "relevant"}, {"label": "unknown"}]
    allowed = {"relevant", "irrelevant"}
    errs, warns = validate_label_values(rows, "label", allowed, "test.csv")
    assert len(errs) == 1
    assert "非法标签" in errs[0]


def test_validate_numeric_range():
    """测试数值区间边界校验。"""
    rows = [
        {"val": "0.5"},
        {"val": "-0.1"},
        {"val": "1.1"},
    ]
    errs, warns = validate_numeric_range(rows, "val", 0.0, 1.0, "test.csv")
    assert len(errs) == 2


def test_validate_foreign_key_relation():
    """测试外键关联约束校验。"""
    rows = [{"ref_id": "R1"}, {"ref_id": "R99"}]
    valid_ids = {"R1", "R2", "R3"}
    errs, warns = validate_foreign_key_relation(rows, "ref_id", valid_ids, "test.csv", "Master")
    assert len(errs) == 1
    assert "外键关联失效" in errs[0]
