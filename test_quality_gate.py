"""
quality_gate.py 的自动化单元测试。
"""

import csv
import json
import sys
from pathlib import Path

# 最顶层注入项目根目录路径，彻底避免找不到 src/app
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from app.quality_gate import run_quality_gate
from src.validation import (
    check_json_syntax,
    check_required_directories,
    check_sensitive_files_and_secrets,
    validate_csv_structure,
    validate_numeric_range,
)


def test_qg_missing_required_directories(tmp_path):
    """1. 测试缺少必需目录时的拦截机制。"""
    (tmp_path / "src").mkdir()
    
    errs, warns = check_required_directories(tmp_path, ["src", "app", "tests", "docs"])
    assert len(errs) == 3
    assert any("缺失必需目录" in e for e in errs)


def test_qg_invalid_json_syntax(tmp_path):
    """2. 测试损坏的 JSON 配置文件语法拦截。"""
    bad_json = tmp_path / "config.json"
    bad_json.write_text("{invalid_json: true,", encoding="utf-8")

    errs, warns = check_json_syntax(bad_json)
    assert len(errs) == 1
    assert "JSON 格式错误" in errs[0]


def test_qg_sensitive_files_and_api_keys(tmp_path):
    """3. 测试敏感文件（如 .env）与硬编码 API Key 的扫描与拦截。"""
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-proj-1234567890abcdef", encoding="utf-8")

    code_file = tmp_path / "secret_code.py"
    code_file.write_text('api_key = "sk-proj-99999999999999999"', encoding="utf-8")

    errs, warns = check_sensitive_files_and_secrets(tmp_path)
    assert len(errs) >= 1
    assert any(".env" in e for e in errs)


def test_qg_csv_structure_validation(tmp_path):
    """4. 测试 CSV 列名缺失拦截。"""
    csv_path = tmp_path / "test.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "title"])
        writer.writerow(["C01", "Paper Title"])

    req_headers = ["case_id", "title", "label", "similarity_score"]
    errs, warns, rows = validate_csv_structure(csv_path, req_headers)
    assert len(errs) == 2
    assert "缺失必需表头" in errs[0]


def test_qg_csv_numeric_range_validation():
    """5. 测试 CSV 数值列（如 similarity_score）超出 [0.0, 1.0] 区间拦截。"""
    rows = [
        {"case_id": "C01", "similarity_score": "0.85"},
        {"case_id": "C02", "similarity_score": "1.50"},
        {"case_id": "C03", "similarity_score": "invalid_num"},
    ]
    errs, warns = validate_numeric_range(rows, "similarity_score", 0.0, 1.0, "test.csv")
    assert len(errs) == 2
    assert "数值超出范围" in errs[0]
    assert "无法解析为数值" in errs[1]


def test_qg_run_quality_gate_pass_and_fail(tmp_path):
    """6. 测试 run_quality_gate 入口函数在通过与失败时的 Exit Code。"""
    for d in ["src", "app", "tests", "docs"]:
        (tmp_path / d).mkdir()

    (tmp_path / "config.json").write_text(json.dumps({"key": "value"}), encoding="utf-8")

    exit_code = run_quality_gate(level="basic", root_dir=tmp_path)
    assert exit_code == 0

    (tmp_path / "bad.json").write_text("{bad", encoding="utf-8")
    
    exit_code_failed = run_quality_gate(level="basic", root_dir=tmp_path)
    assert exit_code_failed == 1
